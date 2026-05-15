"""
QSForge - DDC Runner
Wraps the DDC RvtExporter.exe subprocess so the rest of the app can treat
"give me an Excel from this .rvt" as a single function call.

The exporter writes its output next to the input file, using the naming
convention <originalname>_rvt.xlsx. We locate that file, verify it exists,
and return its path.

Usage (standalone test):
    python ddc_runner.py "C:\\path\\to\\model.rvt"
"""

import os
import sys
import time
import shutil
import threading
import subprocess
from pathlib import Path


def _kill_process_tree(proc) -> None:
    """
    Kill a subprocess **and all of its descendants**.

    Why this matters for QSForge: RvtExporter.exe internally spawns child
    workers that do the actual Revit parsing. A plain ``proc.kill()`` on
    Windows calls TerminateProcess on the top-level PID only — the grand-
    children keep running for 5+ more minutes and happily write 300+ MB of
    Collada (.dae) garbage next to the .rvt, with no one reaping them.

    Strategy:
      * On Windows, shell out to ``taskkill /F /T /PID <pid>`` — the /T flag
        tells it to walk the process tree. Fall back to ``proc.kill()`` only
        if taskkill is missing (pathological machines).
      * On other platforms, fall back to ``proc.kill()`` (we don't ship
        there anyway; this is just belt-and-braces).

    Safe to call on an already-dead process: taskkill exits non-zero and
    we swallow it. Never raises.
    """
    if proc is None:
        return
    try:
        pid = proc.pid
    except Exception:
        return
    if pid <= 0:
        return

    if sys.platform == "win32":
        try:
            # /F = force, /T = terminate the tree (incl. grandchildren).
            # CREATE_NO_WINDOW hides the taskkill console flash (0x08000000).
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=0x08000000,
                check=False,
                timeout=10,
            )
            return
        except (OSError, subprocess.TimeoutExpired):
            pass  # fall through to plain kill below
    try:
        proc.kill()
    except OSError:
        pass


def _reap_zombie_ddc_processes(log) -> int:
    """
    Kill any leftover RvtExporter.exe processes before we start a new run.

    Why this is essential — and painfully non-obvious:

    RvtExporter has a two-tier architecture under the hood: the parent
    process spawns a worker that does the actual Revit parsing. When DDC
    fails early (exit code 1, "File does not exist.", etc.) the **parent
    exits cleanly but the worker keeps running** as an orphan, holding an
    exclusive read lock on the .rvt. From that moment on, every new DDC
    invocation against the same .rvt reports "File does not exist." — the
    file is *there*, Windows just refuses to open it because the zombie
    has it pinned.

    The symptom is catastrophic: a user sees ONE legitimate failure, then
    every subsequent analysis in the same QSForge session fails with the
    same confusing error, and no combination of flags / CWDs / retries
    fixes it. The only recovery is to kill the zombies or restart QSForge.

    So before launching DDC we sweep for any RvtExporter.exe still alive
    and taskkill them (process tree, to get their orphan workers too).
    This runs in ~100 ms on a clean system and is harmless.

    Returns number of killed process IDs, purely for logging.
    """
    if sys.platform != "win32":
        return 0
    try:
        # /FI tells tasklist to filter by imagename; /NH skips the header.
        # /FO CSV keeps parsing trivial even with Chinese Windows locale.
        proc = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq RvtExporter.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0

    pids: list[str] = []
    for line in (proc.stdout or "").splitlines():
        # Lines look like:  "RvtExporter.exe","3416","Console","1","52,340 K"
        parts = [p.strip().strip('"') for p in line.split(",")]
        if len(parts) >= 2 and parts[0].lower() == "rvtexporter.exe":
            pid = parts[1]
            if pid.isdigit():
                pids.append(pid)

    if not pids:
        return 0

    log(
        f"Reaping {len(pids)} leftover RvtExporter process(es) before launch "
        f"(PID{'s' if len(pids) > 1 else ''}: {', '.join(pids)}). "
        "These are zombies from a previous failed run and would otherwise "
        "lock your .rvt file."
    )
    killed = 0
    for pid in pids:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", pid],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=0x08000000, check=False, timeout=5,
            )
            killed += 1
        except (OSError, subprocess.TimeoutExpired):
            pass
    # Give Windows a moment to release file handles. Without this wait,
    # the very next Popen can still see the file as locked.
    if killed:
        time.sleep(0.8)
    return killed

try:
    import paths as app_paths
except ImportError:  # pragma: no cover — running in a context without paths.py
    app_paths = None

try:
    from ad_blocker import AdWindowWatcher
except ImportError:  # pragma: no cover — ad_blocker is optional
    AdWindowWatcher = None  # type: ignore[assignment]


# ── Live progress helpers ───────────────────────────────────────────────────
# DDC writes the final .xlsx only in one last burst at the very end, so the
# output file size is useless as a progress signal (it stays 0 bytes for
# ~95% of the run). The most honest things we can show the user are:
#   1. Wall-clock elapsed time.
#   2. Whether the DDC process is still alive and burning memory.
# This lets the UI replace a single "DDC · converting · 2m 14s · 3.1 GB RAM"
# line every 2 seconds instead of sitting silent for 15+ minutes.
#
# Messages emitted through `on_progress` with the prefix `HEARTBEAT_PREFIX`
# are treated by the frontend as a "refresh the last line" signal.
HEARTBEAT_PREFIX = "DDC · "
_HEARTBEAT_INTERVAL_SEC = 2.0


def _fmt_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _fmt_bytes(n: int) -> str:
    if n <= 0:
        return "—"
    if n >= 1 << 30:
        return f"{n / (1 << 30):.2f} GB"
    if n >= 1 << 20:
        return f"{n / (1 << 20):.1f} MB"
    if n >= 1 << 10:
        return f"{n / (1 << 10):.1f} KB"
    return f"{n} B"


def _read_process_working_set(pid: int) -> int:
    """
    Return current WorkingSetSize in bytes for `pid`, or 0 if unavailable.
    Windows-only; on other platforms we just return 0 (the UI will hide it).
    Uses the psapi/kernel32 ctypes dance so we don't pull in psutil.
    """
    if sys.platform != "win32" or pid <= 0:
        return 0
    try:
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
            ]

        h = kernel32.OpenProcess(
            PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid
        )
        if not h:
            return 0
        try:
            pmc = PROCESS_MEMORY_COUNTERS()
            pmc.cb = ctypes.sizeof(pmc)
            ok = psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb)
            if not ok:
                return 0
            return int(pmc.WorkingSetSize)
        finally:
            kernel32.CloseHandle(h)
    except Exception:
        return 0


def _heartbeat_text(elapsed: float, ram_bytes: int) -> str:
    """Human string for one live heartbeat; the 'DDC · ' prefix matters."""
    parts = [f"converting · {_fmt_duration(elapsed)}"]
    if ram_bytes > 0:
        parts.append(f"RAM {_fmt_bytes(ram_bytes)}")
    parts.append("(large models can take 10–25 min)")
    return HEARTBEAT_PREFIX + " · ".join(parts)


# ── Configuration ───────────────────────────────────────────────────────────
# When running from the shipped .exe, DDC is bundled at ``<app>\vendor\ddc\``
# by build.ps1. The same relative path is also used (optionally) in dev so
# you can drop DDC into the project root and not have to set anything up.
BUNDLED_DDC_REL = Path("vendor") / "ddc" / "RvtExporter.exe"

# Dev-time fallback. We deliberately do not hardcode a path — any developer
# running from source either bundles DDC under vendor/ddc/ or sets the
# QSFORGE_DDC_EXE environment variable.
DEFAULT_DDC_EXE = None

# RvtExporter times on real projects we've measured:
#   * Single-discipline structural, ~40 MB   →   1–3 min
#   * Single-discipline architectural, 80 MB →   3–8 min
#   * Multi-discipline (AL+AR+ST) detached   →  15–45 min
# A 300 MB federated model has been seen to run past 25 min and still
# succeed. We set a generous 60 min ceiling so DDC isn't killed mid-run
# on the commercial user's heaviest model, and let power users override
# this without touching code.
DEFAULT_TIMEOUT_SEC = 60 * 60


def _resolved_timeout(explicit):
    """
    Pick the DDC timeout in seconds, in priority order:
        1. `explicit` argument passed to run_ddc()
        2. $QSFORGE_DDC_TIMEOUT_SEC environment variable (integer seconds)
        3. DEFAULT_TIMEOUT_SEC

    Values below 60 s are treated as "user slipped" and pinned to 60 s so
    we don't silently turn a giant model into an instant-kill.
    """
    if explicit is not None:
        try:
            t = int(explicit)
            return max(60, t)
        except (TypeError, ValueError):
            pass
    env = os.environ.get("QSFORGE_DDC_TIMEOUT_SEC", "").strip()
    if env:
        try:
            t = int(env)
            return max(60, t)
        except ValueError:
            pass
    return DEFAULT_TIMEOUT_SEC


# ── Exceptions ──────────────────────────────────────────────────────────────
class DDCError(Exception):
    """Base class for DDC runner failures."""


class DDCExecutableNotFound(DDCError):
    """RvtExporter.exe could not be located."""


class DDCInputNotFound(DDCError):
    """The input .rvt file does not exist or is not a file."""


class DDCExportFailed(DDCError):
    """RvtExporter ran but returned a non-zero exit code."""


class DDCOutputMissing(DDCError):
    """RvtExporter finished cleanly but the expected _rvt.xlsx is missing."""


class DDCTimeout(DDCError):
    """RvtExporter exceeded the allowed wall-clock time."""


# ── Helpers ─────────────────────────────────────────────────────────────────
def _bundled_ddc_candidates() -> list[Path]:
    """
    Places where a bundled (ship-it-with-the-app) RvtExporter.exe might live.

    In order of preference:
      1. Next to the running .exe         (PyInstaller frozen build)
      2. Project root (dev convenience)   (so you can drop DDC into vendor/ddc/
                                           locally without setting env vars)
    """
    cands: list[Path] = []
    if app_paths is not None:
        try:
            cands.append(app_paths.user_data_dir() / BUNDLED_DDC_REL)
        except OSError:
            pass
        try:
            cands.append(app_paths.resource_dir() / BUNDLED_DDC_REL)
        except OSError:
            pass
    # Absolute fallback if paths.py isn't available (e.g. direct CLI test).
    cands.append(Path(__file__).resolve().parent / BUNDLED_DDC_REL)
    # De-duplicate while preserving order.
    seen: set[str] = set()
    uniq: list[Path] = []
    for c in cands:
        key = str(c).lower()
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return uniq


def _resolve_exe(exe_path):
    """
    Pick the exe path to use, in priority order:
        1. Explicit ``exe_path=`` argument
        2. ``QSFORGE_DDC_EXE`` environment variable
        3. Bundled copy next to the app   (``<app>\\vendor\\ddc\\RvtExporter.exe``)
        4. Hard-coded dev-machine default (``DEFAULT_DDC_EXE``)
    """
    # 1. explicit arg
    if exe_path:
        p = Path(exe_path)
        if p.is_file():
            return p
        raise DDCExecutableNotFound(f"RvtExporter.exe not found at: {p}")

    # 2. env var
    env = os.environ.get("QSFORGE_DDC_EXE", "").strip()
    if env:
        p = Path(env)
        if p.is_file():
            return p
        # Env var was set but path is bad — tell the user clearly.
        raise DDCExecutableNotFound(
            f"QSFORGE_DDC_EXE is set but points to a missing file: {p}"
        )

    # 3. bundled-with-the-app copy (this is the normal case for end users)
    for cand in _bundled_ddc_candidates():
        if cand.is_file():
            return cand

    # 4. dev-machine default (only if explicitly configured)
    if DEFAULT_DDC_EXE is not None:
        p = Path(DEFAULT_DDC_EXE)
        if p.is_file():
            return p

    tried = [
        "$QSFORGE_DDC_EXE env var (not set or invalid)",
        *[f"bundled: {c}" for c in _bundled_ddc_candidates()],
        f"default: {DEFAULT_DDC_EXE}",
    ]
    raise DDCExecutableNotFound(
        "RvtExporter.exe could not be located.\n"
        "Tried:\n  - " + "\n  - ".join(tried) +
        "\n\nSet QSFORGE_DDC_EXE or drop RvtExporter.exe into '<app>\\vendor\\ddc\\'."
    )


def _expected_output(rvt_path: Path) -> Path:
    """DDC writes <name>_rvt.xlsx next to the input."""
    return rvt_path.with_name(rvt_path.stem + "_rvt.xlsx")


def _noop(_msg):
    pass


def _tail_block(text, max_lines=40, max_chars=12000):
    """Return last portion of captured console text, or empty string if none."""
    if not text or not str(text).strip():
        return ""
    s = str(text).strip()
    lines = s.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[-max_chars:]
    return out


def _cmd_line_for_log(cmd):
    try:
        return subprocess.list2cmdline(cmd)
    except (TypeError, ValueError, OSError):
        return repr(cmd)


def _first_writable_desktop() -> Path | None:
    """Return Desktop folder if it exists (EN/ZH/OneDrive variants)."""
    home = Path.home()
    for rel in ("Desktop", "桌面", "OneDrive/Desktop", "OneDrive/桌面"):
        p = home / rel
        if p.is_dir():
            return p
    return None


def _try_write_dump_file(path: Path, body: str) -> bool:
    """Write UTF-8 text; fall back to raw bytes if the text API fails (AV hooks, etc.)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    data = body.encode("utf-8", errors="replace")
    try:
        path.write_text(body, encoding="utf-8", errors="replace")
        return True
    except OSError:
        pass
    try:
        path.write_bytes(data)
        return True
    except OSError:
        return False


def _write_debug_dump(proc, cmd, rvt, exe, log=None) -> list[str]:
    """
    Save full stderr/stdout to several obvious paths. Never raises.
    Also mirrors paths into the UI via `log` when provided.
    """
    log = log or _noop
    cmd_line = _cmd_line_for_log(cmd)
    body = (
        f"exit_code={proc.returncode}\n"
        f"exe={exe}\n"
        f"input={rvt}\n"
        f"command_line={cmd_line}\n\n"
        f"=== stderr (raw) ===\n{proc.stderr or ''}\n\n"
        f"=== stdout (raw) ===\n{proc.stdout or ''}\n"
    )

    here = Path(__file__).resolve().parent
    candidates: list[Path] = [
        Path.cwd() / "qsforge_rvtexporter_last.txt",
        Path.home() / "qsforge_rvtexporter_last.txt",
        here / "qsforge_rvtexporter_last.txt",
        rvt.parent / "qsforge_rvtexporter_last.txt",
    ]
    desk = _first_writable_desktop()
    if desk is not None:
        candidates.append(desk / "qsforge_rvtexporter_last.txt")
    la = os.environ.get("LOCALAPPDATA", "").strip()
    if la:
        candidates.append(Path(la) / "QSForge" / "logs" / "rvtexporter_last.txt")
    tmp = os.environ.get("TEMP") or os.environ.get("TMP") or ""
    if tmp.strip():
        candidates.append(Path(tmp) / "qsforge_rvtexporter_last.txt")

    candidates = list(dict.fromkeys(candidates))

    written: list[str] = []
    for path in candidates:
        if _try_write_dump_file(path, body):
            resolved = str(path.resolve())
            written.append(resolved)
            log(f"DDC log saved: {resolved}")

    if written:
        msg = "[QSForge] DDC debug dump written to:\n  " + "\n  ".join(written)
        print(msg, file=sys.stderr)
    else:
        msg = (
            "[QSForge] WARN: could not write qsforge_rvtexporter_last.txt anywhere. "
            f"Tried {len(candidates)} locations (cwd, user profile, project, model folder, Desktop, …)."
        )
        print(msg, file=sys.stderr)
        log("Could not save DDC log to disk — see the terminal that started QSForge for details.")
    return written


def _format_failure_message(proc, cmd, rvt, exe, dump_paths: list[str]) -> str:
    """Human-readable failure text; dump files must already exist (paths may be empty)."""
    err_tail = _tail_block(proc.stderr)
    out_tail = _tail_block(proc.stdout)
    cmd_line = _cmd_line_for_log(cmd)

    lines = [
        f"RvtExporter exited with code {proc.returncode} (failure).",
        "",
        "Command line (copy into cmd.exe to reproduce):",
        f"  {cmd_line}",
        "",
        "--- stderr (last lines; empty means the tool wrote nothing here) ---",
        err_tail if err_tail else "  (empty)",
        "",
        "--- stdout (last lines) ---",
        out_tail if out_tail else "  (empty)",
    ]
    if not err_tail and not out_tail:
        lines.extend([
            "",
            "Note: Some Windows tools only show a GUI error, or log to a file next to the .exe.",
            "If the lines above are empty, open a dump file below with Notepad (same content in each path).",
            "The in-app log also prints lines starting with: DDC log saved:",
        ])
    if dump_paths:
        lines.extend(["", "Full stderr/stdout dump (identical copies):"])
        lines.extend(f"  {p}" for p in dump_paths)
    else:
        lines.extend([
            "",
            "Dump file was NOT written (all locations failed).",
            "Look in the analysis log for lines starting with: DDC log saved:",
            "Or check the terminal where you started main.py for [QSForge] messages.",
        ])
    return "\n".join(lines)


# ── Main entry point ────────────────────────────────────────────────────────
# Output files we need to clean up besides the main .xlsx
# (DDC writes several siblings; Collada .dae can be ~100 MB).
_DDC_SIDE_OUTPUTS = ("_rvt.dae", "_rvt_meta.json", "_rvt_views.json", "_rvt.pdf")

# Heuristic: a usable DDC xlsx is at least this big. Empty/half-written files
# under 1 KB are treated as missing.
_MIN_XLSX_BYTES = 1024

# What DDC v18.1.0 actually accepts in --mode. Anything else is coerced to
# "standard" (DDC's own default) so a typo can't crash the pipeline.
VALID_MODES = ("basic", "standard", "complete")
DEFAULT_MODE = "standard"


def _normalise_mode(mode) -> str:
    """Map user input to one of VALID_MODES; everything else -> DEFAULT_MODE."""
    if not mode:
        return DEFAULT_MODE
    m = str(mode).strip().lower()
    return m if m in VALID_MODES else DEFAULT_MODE


def _mode_marker(rvt: Path) -> Path:
    """Sidecar file recording which --mode the cached xlsx was produced under.

    Parked next to the .rvt so the marker lives and dies with the xlsx. The
    file is tiny (~10 bytes) and plain text so users can inspect it by hand.
    """
    return rvt.with_name(rvt.stem + "_rvt.qsforge-mode")


def _read_mode_marker(rvt: Path) -> str | None:
    try:
        return _mode_marker(rvt).read_text(encoding="utf-8", errors="replace").strip().lower() or None
    except OSError:
        return None


def _write_mode_marker(rvt: Path, mode: str) -> None:
    try:
        _mode_marker(rvt).write_text(mode, encoding="utf-8")
    except OSError:
        pass  # non-fatal: the xlsx is still usable, we'd just miss the cache next time


def _delete_mode_marker(rvt: Path) -> None:
    try:
        _mode_marker(rvt).unlink()
    except OSError:
        pass


class DDCCancelled(DDCError):
    """User asked to cancel the job mid-conversion."""


def _cache_is_fresh(rvt: Path, xlsx: Path, requested_mode: str) -> tuple[bool, str]:
    """
    Decide whether we can reuse an existing DDC .xlsx instead of running
    the 15-minute converter again. Returns (ok, reason).

    A cache is considered fresh when:
      - the .xlsx exists and is above the "not a half-written stub" floor
      - its mtime is >= the .rvt mtime (so the .rvt hasn't been re-saved
        after the last DDC run)
      - the mode the xlsx was produced under matches the requested mode.
        We persist that in a tiny sidecar file; a legacy xlsx without a
        sidecar is only honoured for the default "standard" mode, since
        that's what DDC used to run when we didn't pass --mode at all.
    """
    if not xlsx.exists():
        return False, "no previous xlsx on disk"
    try:
        xs = xlsx.stat()
        rs = rvt.stat()
    except OSError as e:
        return False, f"stat failed: {e}"
    if xs.st_size < _MIN_XLSX_BYTES:
        return False, f"xlsx is too small ({xs.st_size} bytes) — likely a half-written stub"
    if xs.st_mtime < rs.st_mtime - 1:  # 1s tolerance for FS granularity
        return False, "the .rvt file has been modified since the last DDC run"

    cached_mode = _read_mode_marker(rvt)
    want = _normalise_mode(requested_mode)
    if cached_mode is None:
        # Legacy xlsx from a pre-mode build of QSForge. Safe to reuse only
        # when the user is asking for the historical default.
        if want == DEFAULT_MODE:
            return True, f"cache hit (legacy xlsx, assumed {DEFAULT_MODE})"
        return False, f"cache is from before --mode was recorded; '{want}' requires a fresh run"
    if cached_mode != want:
        return False, f"cache was built with --mode {cached_mode}, but '{want}' was requested"
    return True, f"cache hit (--mode {cached_mode})"


def run_ddc(
    rvt_path,
    exe_path=None,
    mode=DEFAULT_MODE,
    timeout=None,
    on_progress=None,
    force=False,
    cancel_event=None,
    dae=False,
):
    """
    Convert a .rvt file to DDC Excel. Returns Path to the generated .xlsx.

    Parameters
    ----------
    rvt_path : str | Path
        Path to the input .rvt file.
    exe_path : str | Path, optional
        Override path to RvtExporter.exe. Falls back to env var and default.
    mode : str
        DDC export mode — one of "basic", "standard", "complete". Passed
        straight through to RvtExporter v18 as --mode. Unknown values are
        silently coerced to "standard" (DDC's own default) so a typo
        can't crash the pipeline.

        - basic:    element list + core identity columns. Fastest; does
                    NOT include geometric quantities, so Module 0 and
                    most of Module 2 will report 0 % coverage. Use only
                    for smoke tests / IFC-less inventory.
        - standard: adds Level, Family, Material, Volume/Area/Length and
                    host relationships. Covers every QS check today.
        - complete: standard + all Type parameters + extended metadata.
                    Larger xlsx, slightly slower, useful when we want to
                    surface custom Revit parameters in Module 2+.
    timeout : int, optional
        Seconds to wait before killing the subprocess. Falls back to
        QSFORGE_DDC_TIMEOUT_SEC env var, then DEFAULT_TIMEOUT_SEC (60 min).
    on_progress : callable(str) or None
        Receives short status strings — hook this up to Flask/pywebview later.
    force : bool
        If True, bypass the on-disk xlsx cache and re-run RvtExporter even
        when a fresh cache entry is available.
    dae : bool
        If True, also produce the COLLADA (.dae) 3D geometry file alongside
        the .xlsx. Required for the Module 3 3D preview tab. Adds ~10–60 s
        to the conversion depending on model size. Default False.
    cancel_event : threading.Event | None
        If provided, polled every ~0.5 s during the DDC run. When set, we
        kill the subprocess and raise DDCCancelled. The already-written
        xlsx (if DDC had finished) is preserved for the next run.

    Raises
    ------
    DDCInputNotFound, DDCExecutableNotFound, DDCExportFailed,
    DDCOutputMissing, DDCTimeout, DDCCancelled
    """
    log = on_progress or _noop
    timeout = _resolved_timeout(timeout)
    mode = _normalise_mode(mode)

    rvt = Path(rvt_path).resolve()
    if not rvt.is_file():
        raise DDCInputNotFound(f"Input .rvt not found: {rvt}")
    if rvt.suffix.lower() != ".rvt":
        raise DDCInputNotFound(f"Not a .rvt file: {rvt}")

    exe = _resolve_exe(exe_path)
    output = _expected_output(rvt)

    # ── Cache-hit path ──
    # DDC conversion is 10–25 min on large models, but it's deterministic:
    # the same .rvt + same --mode always produce the same xlsx (+ dae). If we
    # already have a fresh cache trio next to the .rvt we reuse it.
    import cache as _cache  # local import to avoid circular at module load

    if not force:
        hit = _cache.lookup(str(rvt), mode)
        # We only reuse if the cache has the artifacts the caller asked for.
        # (A cache made without DAE can't satisfy a dae=True request.)
        if hit is not None:
            if dae and (hit.dae_path is None or not hit.dae_path.is_file()):
                hit = None
        if hit is not None:
            try:
                age_min = (time.time() - hit.xlsx_path.stat().st_mtime) / 60.0
                size_mb = hit.xlsx_path.stat().st_size / 1e6
                log(
                    f"Cache hit — skipping DDC (age {age_min:.1f} min, "
                    f"xlsx {size_mb:.1f} MB). Tick 'Force reconvert' to rebuild."
                )
            except OSError:
                log("Cache hit — skipping DDC.")
            # Copy cached artifacts to the working location next to the .rvt
            # so the rest of the pipeline finds them where it expects.
            if hit.xlsx_path.resolve() != output.resolve():
                shutil.copy2(hit.xlsx_path, output)
            if dae and hit.dae_path is not None:
                expected_dae = rvt.with_name(rvt.stem + "_rvt.dae")
                if hit.dae_path.resolve() != expected_dae.resolve():
                    shutil.copy2(hit.dae_path, expected_dae)
            # Refresh the legacy mode-marker so any code path that still
            # reads it (e.g. _cache_is_fresh kept for backwards compat)
            # agrees with the new cache about which mode is on disk.
            _write_mode_marker(rvt, mode)
            return output
        log("Cache miss — running DDC.")
        if output.exists():
            try:
                output.unlink()
            except OSError as e:
                raise DDCError(f"Cannot remove stale output {output}: {e}")
        _delete_mode_marker(rvt)
    else:
        if output.exists():
            try:
                output.unlink()
            except OSError as e:
                raise DDCError(f"Cannot remove stale output {output}: {e}")
        _delete_mode_marker(rvt)
        # Force-reconvert means "throw away whatever cache thinks is current".
        # Best-effort — never block force-reconvert on a cache cleanup glitch.
        try:
            _cache.invalidate(str(rvt), mode)
        except Exception:
            pass
        log("Force reconvert: skipping any cached xlsx.")

    # Only sweep .dae cleanup if caller does NOT want DAE.
    if not dae:
        _cleanup_side_products(rvt, log)

    # DDC v18.1.0 ships with TWO command-line parsers and only one of them
    # actually works:
    #
    #   new-style:   RvtExporter.exe [OPTIONS] input
    #                e.g.  RvtExporter --mode standard --skip-dae <rvt>
    #   ^^^ BROKEN: any --double-dash flag placed in front of the positional
    #   triggers a spurious "File does not exist." even when the .rvt is
    #   perfectly readable. This isn't a path-quoting issue, isn't fixed by
    #   changing CWD, and isn't a zombie-lock issue — it's a regression
    #   inside DDC's CLI11 parser on this release. Reproduced on fresh
    #   systems with no concurrent RvtExporter processes.
    #
    #   legacy form: RvtExporter.exe <input> [<dae_out>] [<xlsx_out>] [<mode>] [<cat_file>] [-flags]
    #                e.g.  RvtExporter <rvt> -no-collada
    #   ^^^ WORKS reliably. This is the form DDC's own no-args help prints,
    #   and what 1.1.3 has been using for months without incident. Legacy
    #   flags use a single dash: "-no-collada" is the equivalent of the
    #   broken "--skip-dae", "-no-xlsx" the equivalent of "--skip-xlsx".
    #
    # So we build the command in legacy positional form:
    #   * input always comes first
    #   * mode is supplied as the 4th positional (only when it's not
    #     DDC's own default of "standard", to keep the command minimal)
    #   * -no-collada always appended to skip the 300+ MB Collada file
    # Construct the legacy positional command.
    # Drop -no-collada when the caller asked for the DAE file.
    flags = [] if dae else ["-no-collada"]
    if mode == DEFAULT_MODE:
        cmd = [str(exe), str(rvt), *flags]
    else:
        # Non-default mode requires positional slots #2 (dae_out) and #3
        # (xlsx_out). Even when -no-collada is on we have to populate slot
        # #2; DDC just won't write the file. When dae=True, this is the
        # path DDC writes the actual Collada output to.
        cmd = [
            str(exe),
            str(rvt),
            str(rvt.with_name(rvt.stem + "_rvt.dae")),
            str(output),
            mode,
            *flags,
        ]

    log_msg_suffix = "with-collada" if dae else "no-collada"
    try:
        size_mb = rvt.stat().st_size / (1 << 20)
        log(f"Launching DDC: {rvt.name} ({size_mb:.0f} MB, mode={mode}, {log_msg_suffix})")
    except OSError:
        log(f"Launching DDC: {rvt.name} (mode={mode}, {log_msg_suffix})")

    # Before launching DDC, sweep for any zombie RvtExporter.exe that a
    # previous failed run may have orphaned. Without this, the new DDC
    # will fail with the misleading "File does not exist." because the
    # zombie is still holding an exclusive read lock on the .rvt. See
    # _reap_zombie_ddc_processes() for the full root-cause writeup.
    _reap_zombie_ddc_processes(log)

    t0 = time.time()
    # DDC Community edition forcibly opens the default browser to its promo
    # pages (datadrivenconstruction.io) when a conversion finishes. We suppress
    # that by watching for new top-level windows with DDC keywords in the
    # title and sending WM_CLOSE. See ad_blocker.py for details. The watcher
    # is a no-op on non-Windows / when QSFORGE_ALLOW_DDC_ADS=1 is set.
    _watcher_cm = AdWindowWatcher(log=log) if AdWindowWatcher is not None else None

    # Reader threads keep the pipes from filling up on chatty DDC builds
    # (Windows pipe buffers are small; a blocked writer would dead-lock us).
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []

    def _drain(stream, bucket):
        try:
            while True:
                chunk = stream.readline()
                if not chunk:
                    break
                bucket.append(chunk)
        except (OSError, ValueError):
            # ValueError: I/O operation on closed file (happens on kill())
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    proc: subprocess.Popen | None = None
    timed_out = False
    cancelled = False
    try:
        if _watcher_cm is not None:
            _watcher_cm.__enter__()
        try:
            # IMPORTANT: run DDC with its *own* folder as CWD.
            #
            # Background: with the default (inherited) CWD, DDC fails with
            # "File does not exist." whenever QSForge is launched from
            # %LOCALAPPDATA%\QSForge (i.e. the installed build). The .rvt
            # path it's given is a perfectly valid absolute path and the
            # file is right there — DDC just can't find it from that CWD.
            # The message is misleading: it's actually ODA/Teigha failing
            # to locate one of its own runtime files next to RvtExporter.exe,
            # and reporting the miss as if the input .rvt were absent.
            #
            # Pinning CWD to exe.parent (the vendor\ddc folder, where all
            # the .tx/.dll/datadrivenlibs siblings live) makes DDC rock
            # solid regardless of where QSForge itself was started from.
            # CREATE_NO_WINDOW (0x08000000) stops Windows from spawning a
            # separate console window for RvtExporter. Without this flag
            # every DDC run flashes an opaque black cmd-style box on top
            # of QSForge — confusing to QS users who have no idea what
            # that window is or whether to close it. We still capture
            # stdout/stderr through PIPE, the flag only hides the console
            # chrome. No effect on non-Windows platforms.
            _popen_flags = 0x08000000 if sys.platform == "win32" else 0
            proc = subprocess.Popen(
                cmd,
                cwd=str(exe.parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=_popen_flags,
            )
        except OSError as e:
            raise DDCError(f"Failed to launch RvtExporter: {e}")

        t_out = threading.Thread(
            target=_drain, args=(proc.stdout, stdout_chunks),
            daemon=True, name="ddc-stdout",
        )
        t_err = threading.Thread(
            target=_drain, args=(proc.stderr, stderr_chunks),
            daemon=True, name="ddc-stderr",
        )
        t_out.start()
        t_err.start()

        next_heartbeat = t0 + _HEARTBEAT_INTERVAL_SEC
        while proc.poll() is None:
            now = time.time()
            elapsed = now - t0
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                _kill_process_tree(proc)
                break
            if elapsed > timeout:
                timed_out = True
                _kill_process_tree(proc)
                break
            if now >= next_heartbeat:
                ram = _read_process_working_set(proc.pid)
                log(_heartbeat_text(elapsed, ram))
                next_heartbeat = now + _HEARTBEAT_INTERVAL_SEC
            # Sleep short enough that we stay responsive but not so short
            # that we burn CPU ourselves during a 15-min conversion.
            time.sleep(min(0.5, max(0.05, next_heartbeat - time.time())))

        # Wait for the drain threads to finish flushing after proc exit/kill.
        if proc is not None:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _kill_process_tree(proc)
        t_out.join(timeout=2)
        t_err.join(timeout=2)
    finally:
        if _watcher_cm is not None:
            try:
                _watcher_cm.__exit__(None, None, None)
            except Exception:
                pass

    if cancelled:
        # Keep the xlsx on disk if DDC managed to produce one before we
        # killed it — next run will hit the cache. Most of the time the
        # kill lands mid-conversion and the xlsx is 0 bytes; we delete
        # those (and the mode marker) so _cache_is_fresh() won't falsely hit.
        try:
            if output.exists() and output.stat().st_size < _MIN_XLSX_BYTES:
                output.unlink()
                _delete_mode_marker(rvt)
            elif output.exists():
                # xlsx looks complete — record the mode it was built under
                # so a cache hit next time is safe.
                _write_mode_marker(rvt, mode)
        except OSError:
            pass
        # Always reap side products (Collada .dae can be 300+ MB). They
        # are worthless without the xlsx and must not be left on the
        # user's disk just because the pipeline exited via an exception.
        _cleanup_side_products(rvt, log)
        raise DDCCancelled(f"DDC conversion of {rvt.name} was cancelled by the user.")

    if timed_out:
        # Same: don't leak big Collada files when we kill an over-running DDC.
        _delete_mode_marker(rvt)
        _cleanup_side_products(rvt, log)
        mins = max(1, round(timeout / 60))
        raise DDCTimeout(
            f"DDC conversion of {rvt.name} did not finish within {mins} minutes "
            f"and was stopped to keep QSForge responsive.\n\n"
            f"What to try, in order:\n"
            f"  1. Hit 'Retry' — large federated models sometimes finish on "
            f"a second attempt once Windows has cached the file.\n"
            f"  2. Allow more time: set the environment variable "
            f"QSFORGE_DDC_TIMEOUT_SEC (e.g. 7200 for 2 hours), then reopen QSForge.\n"
            f"  3. If RAM was still climbing and CPU was still busy at the "
            f"timeout, the conversion was healthy and just needs more time.\n"
            f"  4. If DDC consistently hangs on this model (CPU drops to 0 "
            f"while RAM stays high), please open it in Revit, Purge Unused, "
            f"detach workshared references if any, save, and try again."
        )

    # Massage the live process into the shape the rest of the module expects:
    # attributes `.returncode`, `.stdout` (str), `.stderr` (str). We keep the
    # same `proc` object because the error-dump code paths read these fields.
    proc.stdout = "".join(stdout_chunks)  # type: ignore[assignment]
    proc.stderr = "".join(stderr_chunks)  # type: ignore[assignment]

    elapsed = time.time() - t0

    # RvtExporter v18 often exits non-zero *after* writing a valid .xlsx
    # (side-products like Collada .dae may fail, but the Excel we need is intact).
    # Therefore we trust the artifact on disk, not the exit code.
    xlsx_ok = output.exists() and output.stat().st_size >= _MIN_XLSX_BYTES

    if xlsx_ok:
        if proc.returncode == 0:
            log(f"DDC finished in {elapsed:.1f}s (exit=0, success)")
        else:
            log(
                f"DDC finished in {elapsed:.1f}s with exit code {proc.returncode}, "
                f"but the Excel was written successfully — continuing."
            )
        _write_mode_marker(rvt, mode)
        # Don't sweep the .dae if the caller asked for it.
        if not dae:
            _cleanup_side_products(rvt, log)
        log(f"Output ready: {output.name}  ({output.stat().st_size / 1e6:.1f} MB)")
        # Populate the new cache (so future runs hit it). Best-effort; cache
        # failures must NEVER block a successful DDC run.
        try:
            dae_path = rvt.with_name(rvt.stem + "_rvt.dae")
            if dae and dae_path.is_file():
                _cache.store(str(rvt), mode, str(output), str(dae_path))
            else:
                _cache.store_xlsx_only(str(rvt), mode, str(output))
        except Exception as e:
            log(f"(Cache store failed: {e}; non-fatal.)")
        return output

    # No usable Excel on disk → real failure. Capture full diagnostics.
    log(
        f"RvtExporter ended after {elapsed:.1f}s with exit code {proc.returncode} "
        f"and no Excel was produced (see error details below)."
    )
    dump_paths: list[str] = []
    try:
        dump_paths = _write_debug_dump(proc, cmd, rvt, exe, log=log)
    except Exception as e:
        import traceback
        log(f"Internal error while saving DDC log: {e}")
        print(traceback.format_exc(), file=sys.stderr)

    # Reap side products even in the no-xlsx failure path: DDC may have
    # written a half-complete .dae before crashing. Also clear the mode
    # marker so we don't claim a cache hit against a file that doesn't
    # exist (or worse, against a stub left over from a previous run).
    _delete_mode_marker(rvt)
    _cleanup_side_products(rvt, log)

    if proc.returncode == 0:
        raise DDCOutputMissing(
            f"RvtExporter reported success but no output found at:\n  {output}"
        )

    try:
        msg = _format_failure_message(proc, cmd, rvt, exe, dump_paths)
    except Exception as e:
        import traceback
        msg = (
            f"RvtExporter exited with code {proc.returncode}.\n"
            f"(Could not build full report: {e})\n"
        )
        if dump_paths:
            msg += "\nDump files:\n" + "\n".join(dump_paths)
        print(traceback.format_exc(), file=sys.stderr)
    raise DDCExportFailed(msg)


def _cleanup_side_products(rvt: Path, log):
    """
    Delete DDC's bulky side outputs AND any 0-byte stubs left by a failed run.

    Called from every exit path of run_ddc — success, cancel, timeout,
    and failure — so a 369 MB Collada file can't leak onto the user's
    disk just because the pipeline raised an exception.

    What gets reaped:
      - The fixed side-output suffixes (Collada .dae, metadata JSON, PDF)
        regardless of their size.
      - Any timestamped DDC leftover matching ``<stem>_rvt*.xlsx`` /
        ``<stem>_rvt*.dae`` that is **exactly 0 bytes**. DDC creates these
        before it crashes; they poison the directory because on the next
        run DDC sees a pre-existing output path and silently refuses to
        overwrite, then reports "File does not exist." against the *input*
        — one of the most misleading error messages in the stack.
      - The primary ``<stem>_rvt.xlsx`` output if (and only if) it is 0
        bytes. Non-empty xlsx is NEVER touched here: that's the cache.

    On Windows, freshly-killed processes sometimes hold file handles
    for a second or two after `taskkill /F`; we retry a few times
    with a short backoff before giving up and logging a warning.
    """
    stem = rvt.stem
    candidates: list[Path] = []

    # 1. Fixed side outputs (always safe to delete regardless of size).
    for suffix in _DDC_SIDE_OUTPUTS:
        p = rvt.with_name(stem + suffix)
        if p.exists():
            candidates.append(p)

    # 2. 0-byte stubs matching DDC's output family — including timestamped
    # variants like "<stem>_rvt_20260421_150125.xlsx" that DDC leaves
    # behind when it crashes between fopen() and any actual write.
    parent = rvt.parent
    try:
        for p in parent.glob(f"{stem}_rvt*"):
            if p in candidates:
                continue
            try:
                if p.is_file() and p.stat().st_size == 0:
                    candidates.append(p)
            except OSError:
                pass
    except OSError:
        # Directory unreadable — nothing we can do; side-products stay.
        pass

    for p in candidates:
        try:
            size_bytes = p.stat().st_size
        except OSError:
            size_bytes = 0
        size_mb = size_bytes / 1e6
        stub_tag = " [0-byte stub]" if size_bytes == 0 else ""

        last_err: Exception | None = None
        for attempt in range(5):  # ~0+0.2+0.4+0.8+1.6 = 3 s max wait
            try:
                p.unlink()
                log(f"Removed side output: {p.name} ({size_mb:.1f} MB){stub_tag}")
                last_err = None
                break
            except OSError as e:
                last_err = e
                time.sleep(0.2 * (2 ** attempt))
        if last_err is not None:
            log(
                f"WARN: could not delete {p.name} ({size_mb:.1f} MB): {last_err}. "
                f"You may safely delete it by hand."
            )


# ── Cleanup helper ──────────────────────────────────────────────────────────
def cleanup_excel(xlsx_path):
    """
    Delete the DDC-generated Excel. Call this after parsing is done.
    Silently ignores missing files; logs but does not raise on permission errors
    (a locked file shouldn't kill the whole pipeline).
    """
    if not xlsx_path:
        return False
    p = Path(xlsx_path)
    if not p.exists():
        return False
    try:
        p.unlink()
        return True
    except OSError as e:
        print(f"[ddc_runner] WARN: could not delete {p}: {e}", file=sys.stderr)
        return False


# ── CLI test harness ────────────────────────────────────────────────────────
if __name__ == "__main__":
    if sys.platform == "win32":
        for _stream in (sys.stdout, sys.stderr):
            try:
                _stream.reconfigure(encoding="utf-8")
            except (AttributeError, ValueError, OSError):
                pass

    if len(sys.argv) < 2:
        print("Usage: python ddc_runner.py <path_to_rvt>")
        sys.exit(2)

    rvt_arg = sys.argv[1]

    def _print(msg):
        print(f"  · {msg}")

    print("\n" + "═" * 70)
    print("  QSForge  |  DDC RUNNER  (standalone test)")
    print("═" * 70)

    try:
        xlsx = run_ddc(rvt_arg, on_progress=_print)
    except DDCError as e:
        print(f"\n  ❌ {type(e).__name__}: {e}")
        sys.exit(1)

    print(f"\n  ✅ Excel generated:\n     {xlsx}\n")
