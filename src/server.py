"""
QSForge - Local Flask server
Coordinates: DDC export → Module 0 parse → JSON result.

Endpoints
---------
GET  /                        → static/index.html
GET  /api/health              → liveness probe
POST /api/analyze             → {path: "...", keep_xlsx?: bool (default true)} → {job_id}
GET  /api/jobs/<job_id>       → current state + result (polling)
GET  /api/jobs/<job_id>/stream→ Server-Sent Events (progress push)

Runs locally on 127.0.0.1:7890. pywebview (main.py) owns the window.
"""

import json
import queue
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_file, send_from_directory

import ddc_runner
import module0_inventory
import module2_checks
import module3_3d_preview
import scoring
import pdf_report
import updater
import _version


# ── Config ──────────────────────────────────────────────────────────────────
HOST = "127.0.0.1"
PORT = 7890

import paths as app_paths

# Read-only bundled assets (served by Flask) — inside _MEIPASS when frozen.
STATIC_DIR = app_paths.resource_dir() / "static"

# Writable directory for `last_result.json`, etc. — next to the .exe when
# frozen so users can find their exports; project root in source mode.
DATA_DIR = app_paths.user_data_dir()

# BASE_DIR is retained as a synonym for DATA_DIR because every writable
# location in this module historically used that name.
BASE_DIR = DATA_DIR


# ── Job registry ────────────────────────────────────────────────────────────
class Job:
    """One analysis run. Thread-safe enough for a single-user desktop app."""

    __slots__ = ("id", "state", "rvt_path", "created_at", "started_at",
                 "finished_at", "events", "result", "error", "subscribers",
                 "_lock", "cancel_event", "force", "cached_ddc", "mode")

    def __init__(self, rvt_path, *, force=False, mode=None):
        self.id = uuid.uuid4().hex[:12]
        # queued | running | done | error | cancelled
        self.state = "queued"
        self.rvt_path = str(rvt_path)
        self.created_at = time.time()
        self.started_at = None
        self.finished_at = None
        self.events = []               # list[{ts, message}]
        self.result = None             # Module 0 dict when done
        self.error = None              # {type, message} when error
        self.subscribers = []          # list[queue.Queue] for SSE
        self._lock = threading.Lock()
        self.cancel_event = threading.Event()
        self.force = bool(force)
        # DDC export depth. ddc_runner normalises unknown values to the
        # DDC default ("standard"), so we can forward the client's value
        # verbatim without validating it here.
        self.mode = ddc_runner._normalise_mode(mode)
        # Tracks whether DDC managed to produce a fresh xlsx this run.
        # Used by the finally-clause to decide whether to delete it.
        self.cached_ddc = False

    def emit(self, message):
        """Append a progress event and push to every SSE subscriber."""
        ev = {"ts": time.time(), "message": str(message)}
        with self._lock:
            self.events.append(ev)
            subs = list(self.subscribers)
        for q in subs:
            try:
                q.put_nowait(ev)
            except queue.Full:
                pass

    def subscribe(self):
        q = queue.Queue(maxsize=2048)
        with self._lock:
            self.subscribers.append(q)
            backlog = list(self.events)
        for ev in backlog:
            try:
                q.put_nowait(ev)
            except queue.Full:
                pass
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def to_public(self):
        with self._lock:
            return {
                "id": self.id,
                "state": self.state,
                "rvt_path": self.rvt_path,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "events": list(self.events),
                "result": self.result,
                "error": self.error,
                "mode": self.mode,
                "force": self.force,
            }


_jobs_lock = threading.Lock()
_jobs = {}   # id -> Job


def _get_job_or_404(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        abort(404, description=f"Job not found: {job_id}")
    return job


# ── Worker ──────────────────────────────────────────────────────────────────
def _run_job(job, keep_xlsx=True):
    job.state = "running"
    job.started_at = time.time()
    job.emit(f"Starting analysis: {Path(job.rvt_path).name}")

    # Let the user see up-front which DDC export depth we're about to run.
    # Basic explicitly does NOT include geometry columns, so Module 2
    # checks that need Volume/Area/Length will report 0 % coverage —
    # surface that expectation here instead of burying it in the flags.
    mode_blurb = {
        "basic":    "DDC mode: basic — fastest, element inventory only. "
                    "Module 2 geometry checks will be limited.",
        "standard": "DDC mode: standard — balanced. Covers every QS check "
                    "QSForge ships today.",
        "complete": "DDC mode: complete — deepest export, includes Type "
                    "parameters. Slightly slower, larger xlsx.",
    }.get(job.mode, f"DDC mode: {job.mode}")
    job.emit(mode_blurb)

    xlsx_path = None
    ddc_succeeded = False
    try:
        # Full-result cache: skip the whole pipeline if we already have a
        # fresh result for this (.rvt, mode, qsforge_version). Hit time is
        # ~1 s vs ~120 s on a 370 MB model. Force-reconvert bypasses this
        # exactly like it bypasses the DDC cache.
        if not job.force:
            try:
                import cache as _cache
                cached = _cache.load_result(job.rvt_path, job.mode)
            except Exception:
                cached = None
            if cached is not None:
                job.emit("✨ Full result cache hit — skipping entire pipeline.")
                # Audit dump still happens so /api/last_result works.
                try:
                    dump_path = BASE_DIR / "last_result.json"
                    dump_path.write_text(
                        json.dumps(cached, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8",
                    )
                except Exception:
                    pass
                job.result = cached
                job.state = "done"
                job.emit("Done (from cache).")
                return

        job.emit("Running DDC converter…")
        xlsx_path = ddc_runner.run_ddc(
            job.rvt_path,
            mode=job.mode,
            on_progress=job.emit,
            force=job.force,
            cancel_event=job.cancel_event,
            dae=True,    # Module 3 needs the COLLADA file
        )
        ddc_succeeded = True

        job.emit("Parsing Excel (Module 0)…")
        data = module0_inventory.parse(xlsx_path, do_export=True)

        job.emit("Running quality checks (Module 2)…")
        try:
            data["module2"] = module2_checks.run_checks(xlsx_path)
        except Exception as e:
            # Checks are additive; don't fail the whole analysis if one check blows up.
            job.emit(f"Module 2 checks failed: {e}")
            data["module2"] = {
                "checks": [],
                "summary": {"critical": 0, "warning": 0, "ok": 0},
                "error": str(e),
            }

        job.emit("Validating 3D preview (Module 3)…")
        try:
            # ddc_runner names the DAE: <stem>_rvt.xlsx → <stem>_rvt.dae
            # (same suffix swap rule)
            xlsx_p = Path(xlsx_path)
            dae_p = xlsx_p.with_name(xlsx_p.stem + ".dae")
            data["module3"] = module3_3d_preview.run(str(dae_p))
            for w in data["module3"].get("warnings", []):
                job.emit(f"M3: {w}")
        except Exception as e:
            job.emit(f"Module 3 failed: {e}")
            data["module3"] = {
                "dae_path": None,
                "element_count": 0,
                "has_element_ids": False,
                "warnings": [str(e)],
            }

        job.emit("Scoring (Module 2c)…")
        try:
            data["score"] = scoring.compute_score(data)
        except Exception as e:
            job.emit(f"Scoring failed: {e}")
            data["score"] = {"error": str(e)}

        # Audit dump — write full payload to disk so the user can verify
        # each module's output without re-running the (slow) DDC conversion.
        try:
            dump_path = BASE_DIR / "last_result.json"
            dump_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            job.emit(f"Result dumped → {dump_path.name}")
        except Exception as e:
            job.emit(f"(Could not write last_result.json: {e})")

        # Full-result cache: store the analysis result alongside the cached
        # xlsx/dae so the next analysis of this same .rvt skips the pipeline.
        try:
            import cache as _cache
            _cache.store_result(job.rvt_path, job.mode, data)
        except Exception as e:
            job.emit(f"(Result cache store failed: {e})")

        job.result = data
        job.state = "done"
        # Guard the final log line independently — any KeyError / formatting issue
        # here must NEVER bubble up, because the job is already successfully done
        # and the UI needs the terminal state event to flip to the results page.
        try:
            m2 = (data.get("module2") or {}).get("summary") or {}
            sc = data.get("score") or {}
            verdict = (sc.get("verdict") or {}).get("label", "—")
            file_info = data.get("file") or {}
            qs_count = file_info.get("qs_entity_count", 0) or 0
            issues_count = len(data.get("issues") or [])
            job.emit(
                f"Done — Score {sc.get('overall', '—')}/100 ({verdict}) · "
                f"{qs_count:,} QS entities, "
                f"{issues_count} readiness flags, "
                f"{m2.get('critical', 0)} critical / {m2.get('warning', 0)} warning checks."
            )
        except Exception as e:
            job.emit(f"Done (summary line skipped: {type(e).__name__}: {e})")

    except ddc_runner.DDCCancelled as e:
        job.state = "cancelled"
        job.error = {"type": "DDCCancelled", "message": str(e)}
        job.emit(f"Cancelled: {e}")
    except ddc_runner.DDCError as e:
        job.state = "error"
        job.error = {"type": type(e).__name__, "message": str(e)}
        job.emit(f"DDC error: {e}")
    except module0_inventory.ParserError as e:
        job.state = "error"
        job.error = {"type": "ParserError", "message": str(e)}
        job.emit(f"Parser error: {e}")
    except Exception as e:
        job.state = "error"
        job.error = {"type": type(e).__name__, "message": str(e)}
        job.emit(f"Unexpected error: {e}")
    finally:
        # The DDC xlsx IS the on-disk cache. A QS typically re-analyses
        # the same .rvt many times during one session (different --mode,
        # re-run after a BIM fix, peeking at another check). DDC takes
        # 10-25 min on a 300 MB model; the xlsx is ~6 % the size of the
        # .rvt itself. Keeping it is a no-brainer.
        #
        # So the new policy is: always preserve the xlsx on disk. The
        # `keep_xlsx=False` path is retained for explicit API callers
        # that want a fire-and-forget one-shot (e.g. a CI pipeline),
        # but it is NO LONGER the default — requests that don't specify
        # the field get keep_xlsx=True and cache is preserved.
        if (
            job.state == "done"
            and xlsx_path
            and not keep_xlsx  # honoured only when the caller explicitly opts in
        ):
            if ddc_runner.cleanup_excel(xlsx_path):
                job.emit("Temporary Excel deleted (keep_xlsx=false was requested).")
        elif xlsx_path and ddc_succeeded:
            # Cover both "done" and "error/cancel after DDC wrote the xlsx" —
            # in every case the xlsx stays where DDC put it, next to the .rvt,
            # so the very next Analyze click hits the cache.
            try:
                size_mb = Path(xlsx_path).stat().st_size / 1e6
                job.emit(
                    f"DDC output kept as on-disk cache: {Path(xlsx_path).name} "
                    f"({size_mb:.1f} MB). Next analysis of the same .rvt will "
                    f"skip the 15-min reconvert."
                )
            except OSError:
                pass
        job.finished_at = time.time()


# ── Flask app ───────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=None)


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "QSForge", "port": PORT})


# ── Version + update endpoints ─────────────────────────────────────────────
# Three small, side-effect-free GETs and two state-changing POSTs.
# The frontend uses these to drive the "About / Updates" panel and the
# silent-on-startup notification toast. All endpoints are designed to
# never raise — network errors / disabled checks are returned as JSON
# so the UI can stay calm even on offline machines.

@app.get("/api/version")
def api_version():
    """Return current installed versions of QSForge + the bundled DDC."""
    return jsonify(updater.get_versions())


@app.get("/api/updates/check")
def api_updates_check():
    """
    Hit the configured update manifest and report whether anything newer
    is available. Never raises — see updater.check_for_updates() for the
    full result shape (status: ok | offline | disabled | error).
    """
    return jsonify(updater.check_for_updates())


@app.post("/api/updates/download")
def api_updates_download():
    """
    Body: {"component": "qsforge" | "ddc",
           "manifest": <full manifest dict from /api/updates/check>}
    Kicks off a background download + SHA256 verify. Returns a job_id
    the client polls via /api/updates/jobs/<id>.
    """
    payload = request.get_json(silent=True) or {}
    component = payload.get("component")
    manifest = payload.get("manifest")
    if component not in updater.KNOWN_COMPONENTS:
        return jsonify({"error": f"unknown component: {component!r}"}), 400
    if not isinstance(manifest, dict):
        return jsonify({"error": "missing 'manifest' object"}), 400
    try:
        job = updater.start_download_job(component, manifest)
    except updater.UpdaterError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"job_id": job.id, "state": job.state}), 202


@app.get("/api/updates/jobs/<job_id>")
def api_updates_job(job_id):
    job = updater.get_job(job_id)
    if job is None:
        return jsonify({"error": f"job not found: {job_id}"}), 404
    return jsonify(job.to_public())


@app.post("/api/updates/jobs/<job_id>/cancel")
def api_updates_cancel(job_id):
    job = updater.get_job(job_id)
    if job is None:
        return jsonify({"error": f"job not found: {job_id}"}), 404
    job.cancel_event.set()
    return jsonify({"ok": True, "job_id": job.id, "state": job.state})


@app.post("/api/updates/apply")
def api_updates_apply():
    """
    Body: {"component": "qsforge" | "ddc",
           "artefact_path": "<path returned by the download job>",
           "version": "<expected version string for marker file>"}

    For DDC: synchronously swaps vendor\\ddc\\ with the new copy.
    For QSForge: spawns the Inno Setup installer with /SILENT and asks
        the caller to close the window. We return *immediately* — the
        caller (frontend) is responsible for telling pywebview to exit.
    """
    payload = request.get_json(silent=True) or {}
    component = payload.get("component")
    artefact_path = payload.get("artefact_path")
    version = payload.get("version")
    if component not in updater.KNOWN_COMPONENTS:
        return jsonify({"error": f"unknown component: {component!r}"}), 400
    if not artefact_path:
        return jsonify({"error": "missing 'artefact_path'"}), 400

    p = Path(artefact_path)
    if not p.is_file():
        return jsonify({"error": f"artefact missing on disk: {p}"}), 404

    if component == updater.COMPONENT_DDC:
        try:
            res = updater.apply_ddc_update(p, expected_version=version)
        except Exception as e:  # noqa: BLE001 — never let apply crash the API
            return jsonify({"status": "error", "message": str(e)}), 500
        # Map updater statuses to HTTP codes so the frontend can branch.
        http = 200 if res.get("status") == "ok" else 409 if res.get("status") == "blocked" else 500
        return jsonify(res), http

    if component == updater.COMPONENT_QSFORGE:
        res = updater.apply_qsforge_update(p)
        http = 200 if res.get("status") == "ok" else 500
        return jsonify(res), http

    return jsonify({"error": "unreachable"}), 500


@app.post("/api/updates/rollback_ddc")
def api_updates_rollback():
    """Restore the previous DDC from vendor\\ddc-backup\\, if present."""
    res = updater.rollback_ddc()
    http = 200 if res.get("status") == "ok" else 409 if res.get("status") == "blocked" else 500
    return jsonify(res), http


@app.get("/api/last_result_path")
def last_result_path():
    """Return the absolute path of the most recent result dump, if any."""
    p = BASE_DIR / "last_result.json"
    if p.is_file():
        return jsonify({"exists": True, "path": str(p), "size": p.stat().st_size})
    return jsonify({"exists": False, "path": str(p)})


@app.get("/api/last_result")
def last_result():
    """
    Stream the most recent `last_result.json` straight from disk.

    Exists as a robust fallback: on some frozen Windows builds the
    /api/jobs/<id> response (which serialises the whole result dict via
    jsonify) has been observed to hang in WebView2 after a large analysis.
    `send_file` uses a plain file handle and Flask's battle-tested static
    code path, so this endpoint keeps working when the other one doesn't.
    """
    p = BASE_DIR / "last_result.json"
    if not p.is_file():
        return jsonify({"error": "No analysis result available yet."}), 404
    resp = send_file(
        str(p),
        mimetype="application/json",
        as_attachment=False,
        conditional=False,
    )
    # Prevent the browser from caching across analyses.
    for k, v in _NO_CACHE.items():
        resp.headers[k] = v
    return resp


@app.get("/api/3d/<job_id>")
def stream_dae(job_id: str):
    """Stream the .dae bytes for a finished job to the browser.

    Why a streaming endpoint and not a base64-blob in the JSON: a typical
    architectural .dae is 30–200 MB. Stuffing that into last_result.json
    would balloon JSON parsing time on the frontend AND blow our SSE event
    pipeline. HTTP streaming with the right Content-Type is the right
    channel for binary geometry.
    """
    # Hold the lock for the whole lookup so we don't race against analyze().
    # The "current" branch lets the frontend ask for the most recent done
    # job when it has lost track (e.g. user reloaded the page).
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None and job_id == "current":
            done_jobs = [j for j in _jobs.values() if j.state == "done"]
            if done_jobs:
                job = max(done_jobs, key=lambda j: j.started_at or 0)
    if job is None or job.state != "done" or not job.result:
        abort(404, description="Job not found or not finished")
    m3 = (job.result or {}).get("module3") or {}
    dae_path = m3.get("dae_path")
    if not dae_path:
        abort(404, description="No DAE for this job")
    return send_file(dae_path, mimetype="model/vnd.collada+xml",
                     as_attachment=False, conditional=True)


@app.post("/api/export_pdf")
def export_pdf():
    """Generate a PDF report to the requested path, using the latest analysis.

    Body: {"output_path": "<absolute path to .pdf>",
           "job_id": "<optional; falls back to last_result.json>"}
    """
    payload = request.get_json(silent=True) or {}
    out_path = payload.get("output_path")
    if not out_path:
        return jsonify({"error": "Missing 'output_path'."}), 400

    out = Path(out_path)
    if out.suffix.lower() != ".pdf":
        out = out.with_suffix(".pdf")

    # Resolve source data: prefer the job result, fall back to last_result.json.
    data = None
    source_name = None
    job_id = payload.get("job_id")
    if job_id:
        with _jobs_lock:
            job = _jobs.get(job_id)
        if job and job.state == "done" and job.result:
            data = job.result
            source_name = Path(job.rvt_path).name if job.rvt_path else None

    if data is None:
        dump = BASE_DIR / "last_result.json"
        if not dump.is_file():
            return jsonify({"error": "No analysis result available."}), 404
        try:
            data = json.loads(dump.read_text(encoding="utf-8"))
        except Exception as e:
            return jsonify({"error": f"Failed to read last_result.json: {e}"}), 500
        if not source_name:
            file_path = (data.get("file") or {}).get("path") or ""
            source_name = Path(file_path).name if file_path else "analysis"

    try:
        result_path = pdf_report.generate_pdf(data, out, source_name=source_name)
    except Exception as e:
        return jsonify({"error": f"PDF generation failed: {e}"}), 500

    return jsonify({
        "ok": True,
        "path": str(result_path),
        "size": result_path.stat().st_size,
    })


@app.post("/api/analyze")
def analyze():
    payload = request.get_json(silent=True) or {}
    rvt_path = payload.get("path")
    # Default to preserving the DDC xlsx so the next Analyze click hits
    # the on-disk cache (DDC re-conversion is 10-25 min on large models).
    # Explicit callers can still pass keep_xlsx=false for one-shot runs.
    keep_xlsx = bool(payload.get("keep_xlsx", True))
    force = bool(payload.get("force", False))
    mode = payload.get("mode")  # "basic" | "standard" | "complete" | None

    if not rvt_path:
        return jsonify({"error": "Missing 'path'."}), 400

    p = Path(rvt_path)
    if not p.is_file():
        return jsonify({"error": f"File not found: {p}"}), 404
    if p.suffix.lower() != ".rvt":
        return jsonify({"error": f"Not a .rvt file: {p.name}"}), 400

    job = Job(p.resolve(), force=force, mode=mode)
    with _jobs_lock:
        _jobs[job.id] = job

    t = threading.Thread(
        target=_run_job, args=(job,), kwargs={"keep_xlsx": keep_xlsx},
        daemon=True, name=f"qsforge-job-{job.id}",
    )
    t.start()

    return jsonify({"job_id": job.id, "state": job.state, "mode": job.mode}), 202


@app.post("/api/jobs/<job_id>/cancel")
def job_cancel(job_id):
    """
    Request cancellation of a running analysis. The worker polls the
    cancel_event every ~0.5 s inside ddc_runner and will kill the DDC
    subprocess on the next tick. If the job is already finished we
    just return its current state.
    """
    job = _get_job_or_404(job_id)
    already_terminal = job.state in ("done", "error", "cancelled")
    if not already_terminal:
        job.cancel_event.set()
        job.emit("Cancel requested — stopping DDC…")
    return jsonify({
        "ok": True,
        "job_id": job.id,
        "state": job.state,
        "cancel_requested": job.cancel_event.is_set(),
        "already_terminal": already_terminal,
    })


@app.get("/api/jobs/<job_id>")
def job_status(job_id):
    return jsonify(_get_job_or_404(job_id).to_public())


@app.get("/api/jobs/<job_id>/stream")
def job_stream(job_id):
    job = _get_job_or_404(job_id)

    def gen():
        q = job.subscribe()
        try:
            yield "retry: 86400000\n\n"
            yield _sse("state", {"state": job.state})
            while True:
                try:
                    ev = q.get(timeout=5)
                except queue.Empty:
                    yield ": keep-alive\n\n"
                    if job.state in ("done", "error", "cancelled"):
                        yield _sse("state", {"state": job.state})
                        break
                    continue

                yield _sse("event", ev)

                if job.state in ("done", "error", "cancelled"):
                    # Drain any remaining queued events before we close the stream
                    # so the "Done — ..." line doesn't get lost.
                    while True:
                        try:
                            extra = q.get_nowait()
                        except queue.Empty:
                            break
                        yield _sse("event", extra)
                    yield _sse("state", {"state": job.state})
                    break
        except GeneratorExit:
            # Client disconnected — normal on page reload / window close.
            raise
        except Exception as e:
            # Never let the generator crash silently — emit a best-effort final
            # state event so the client isn't left waiting forever.
            try:
                yield _sse("state", {"state": "error", "_reason": f"stream-{type(e).__name__}"})
            except Exception:
                pass
        finally:
            job.unsubscribe(q)

    return Response(gen(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })


def _sse(event, data):
    # ensure_ascii=True: DDC stderr may contain lone surrogates that break
    # JSON in UTF-8 mode and crash the SSE generator (would abort the stream).
    try:
        payload = json.dumps(data, ensure_ascii=True, default=str)
    except Exception as e:
        # Last-ditch fallback so the generator never dies on a bad payload.
        payload = json.dumps(
            {"_sse_encode_error": f"{type(e).__name__}: {e}"},
            ensure_ascii=True,
        )
    return f"event: {event}\ndata: {payload}\n\n"


# ── Static (index.html) ─────────────────────────────────────────────────────
_NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma":        "no-cache",
    "Expires":       "0",
}


@app.get("/")
def index():
    if not (STATIC_DIR / "index.html").is_file():
        return (
            "<h1>QSForge server is running.</h1>"
            "<p>static/index.html has not been built yet. "
            "Use the API at <code>/api/analyze</code>.</p>"
        ), 200
    resp = send_from_directory(STATIC_DIR, "index.html")
    for k, v in _NO_CACHE.items():
        resp.headers[k] = v
    return resp


@app.get("/static/<path:filename>")
def static_file(filename):
    resp = send_from_directory(STATIC_DIR, filename)
    for k, v in _NO_CACHE.items():
        resp.headers[k] = v
    return resp


# ── Entry ───────────────────────────────────────────────────────────────────
def main():
    # Don't mkdir STATIC_DIR when frozen — it lives inside _MEIPASS (read-only).
    if not app_paths.is_frozen():
        STATIC_DIR.mkdir(exist_ok=True)
    print(f"QSForge server listening on http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
