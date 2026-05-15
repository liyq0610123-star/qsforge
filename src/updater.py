"""
QSForge - Update mechanism (QSForge app + bundled DDC converter).

What this module does
---------------------
1. Reports the currently-installed versions of QSForge and DDC.
2. Fetches a small JSON "manifest" (over HTTPS) that lists the latest
   available versions and their download URLs.
3. Downloads update artefacts in the background with progress callbacks
   and cancellation support.
4. Verifies SHA-256 + file size before trusting any download.
5. Applies updates safely:
     - DDC:     downloaded zip -> staging folder -> backup current
                vendor\\ddc\\ -> rename staging into place. One backup
                kept for instant rollback.
     - QSForge: launch the downloaded Inno Setup installer with
                /SILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS and exit.

Design choices
--------------
* **Network failures NEVER raise.** The desktop app must keep working
  with no internet — this module returns ``{"status": "offline"}`` and
  similar tagged results instead of throwing, so callers (Flask, the
  startup hook in main.py) can treat updates as a soft enhancement.
* **No third-party libs.** urllib + hashlib + zipfile are enough; the
  app is already heavy enough that pulling ``requests`` or ``packaging``
  would balloon the PyInstaller bundle for nothing.
* **Versioned download cache** in ``user_data_dir() / .updates`` so a
  half-finished download can be resumed across app restarts and so
  multiple update checks don't redownload the same bytes.
* **DDC swap is atomic-ish on Windows.** We use ``os.rename`` between
  sibling folders on the same drive (which is atomic on NTFS) and only
  delete the backup on the *next* successful update — never during the
  swap itself, so a power loss leaves a bootable system either way.

Public surface
--------------
    get_versions()                         -> {qsforge, ddc, ...}
    check_for_updates()                    -> {status, qsforge, ddc, ...}
    download_update(component, manifest, *, on_progress, cancel_event)
                                           -> Path to verified artefact
    apply_ddc_update(zip_path, on_progress)-> {status, message, ...}
    apply_qsforge_update(installer_path)   -> spawns installer, returns
                                              after launching it
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import _version


# ── Module-level constants ──────────────────────────────────────────────────

# How long to wait for the manifest server to respond (seconds). Manifests
# are tiny (<5 KB) so a generous timeout for slow corporate proxies.
MANIFEST_TIMEOUT_SEC = 15

# How often to poll the cancel event while a download is in flight.
_CANCEL_POLL_SEC = 0.25

# Minimum free-space buffer we insist on before starting a download
# (avoid filling up the user's C: drive with a 600 MB DDC zip when they
# only have 100 MB free).
_FREE_SPACE_HEADROOM = 200 * 1024 * 1024  # 200 MB

# Buffer used by both downloader and SHA256-verifier. 1 MB is large
# enough that disk I/O dominates over Python loop overhead.
_IO_BUFFER = 1024 * 1024

# User-Agent header — useful for the release host's logs and for
# diagnosing why an HTTP request was blocked by some corporate proxy.
_USER_AGENT = f"QSForge-Updater/{_version.QSFORGE_VERSION} (Windows; +manifest)"

# Component tags. Kept as constants so the JS side and Python side
# can't drift out of sync via typos.
COMPONENT_QSFORGE = "qsforge"
COMPONENT_DDC = "ddc"
KNOWN_COMPONENTS = (COMPONENT_QSFORGE, COMPONENT_DDC)


# ── Path helpers (cooperate with paths.py for frozen vs source layouts) ────
try:
    import paths as app_paths
except ImportError:  # pragma: no cover — direct CLI use without paths.py
    app_paths = None


def _user_data_dir() -> Path:
    if app_paths is not None:
        return app_paths.user_data_dir()
    return Path(__file__).resolve().parent


def _resource_dir() -> Path:
    if app_paths is not None:
        return app_paths.resource_dir()
    return Path(__file__).resolve().parent


def _vendor_ddc_dir() -> Path:
    """Return the live ``vendor\\ddc\\`` folder — the one we'll be replacing."""
    return _user_data_dir() / "vendor" / "ddc"


def _updates_cache_dir() -> Path:
    """Folder for downloaded artefacts. Created on demand."""
    p = _user_data_dir() / ".updates"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _backup_ddc_dir() -> Path:
    """Sibling folder where we keep ONE rollback copy of vendor\\ddc\\."""
    return _user_data_dir() / "vendor" / "ddc-backup"


def _staging_ddc_dir() -> Path:
    """Folder we extract a new DDC into before swapping it in."""
    return _user_data_dir() / "vendor" / "ddc-new"


# ── Version helpers ─────────────────────────────────────────────────────────
_DDC_VERSION_MARKER = ".qsforge-ddc-version"


def _read_ddc_version_from_marker() -> str | None:
    """Return the DDC version recorded by build.ps1, or None if missing."""
    marker = _vendor_ddc_dir() / _DDC_VERSION_MARKER
    try:
        text = marker.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    return text or None


def get_ddc_installed_version() -> str | None:
    """
    Best-effort current DDC version.

    Priority order:
      1. The marker file ``vendor\\ddc\\.qsforge-ddc-version`` written by
         build.ps1 at package time. If the marker exists it always wins —
         after a successful update we rewrite this file to track the new
         version regardless of what _version.py says.
      2. ``_version.DDC_BUNDLED_VERSION`` fallback (only useful from-source
         when the marker hasn't been generated yet).
      3. None when DDC isn't installed at all.

    Never raises.
    """
    if not _vendor_ddc_dir().is_dir():
        return None
    marker = _read_ddc_version_from_marker()
    if marker:
        return marker
    return _version.DDC_BUNDLED_VERSION


def get_versions() -> dict:
    """
    Snapshot of what's installed right now. Cheap; safe to call often.
    """
    ddc_dir = _vendor_ddc_dir()
    return {
        "qsforge": _version.QSFORGE_VERSION,
        "ddc": get_ddc_installed_version(),
        "ddc_path": str(ddc_dir) if ddc_dir.is_dir() else None,
        "manifest_url": _version.manifest_url() or None,
        "update_checks_enabled": _version.update_checks_enabled(),
    }


# ── Semver comparison (tolerant) ────────────────────────────────────────────
_VERSION_PART_RE = re.compile(r"\d+")


def _parse_version(v: str) -> tuple[int, ...]:
    """
    Turn "1.2.3", "v1.2.3", "1.2.3-rc1", "1.2" into a tuple of ints.

    Pre-release suffixes are dropped — we treat 1.2.3-rc1 == 1.2.3 for
    ordering, which is good enough for our update flow (we never publish
    rc builds to the stable manifest anyway).
    """
    if not v:
        return (0,)
    nums = _VERSION_PART_RE.findall(str(v))
    if not nums:
        return (0,)
    return tuple(int(n) for n in nums[:4])  # cap at 4 components


def is_newer(candidate: str | None, current: str | None) -> bool:
    """True if ``candidate`` is strictly newer than ``current``."""
    if not candidate:
        return False
    if not current:
        return True  # nothing installed → anything is newer
    return _parse_version(candidate) > _parse_version(current)


# ── Manifest fetch ──────────────────────────────────────────────────────────
class UpdaterError(Exception):
    """Anything that can go wrong inside the updater pipeline."""


class ManifestError(UpdaterError):
    """Manifest could not be fetched or parsed."""


class VerificationError(UpdaterError):
    """A downloaded artefact failed SHA-256 / size verification."""


class UpdateCancelled(UpdaterError):
    """The caller cancelled a download mid-flight."""


def _fetch_manifest_raw(url: str) -> dict:
    """Tight, single-purpose HTTP GET → parsed JSON. Raises ManifestError."""
    if not url:
        raise ManifestError("manifest URL is empty (update checks disabled)")
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=MANIFEST_TIMEOUT_SEC) as resp:
            if resp.status != 200:
                raise ManifestError(f"manifest HTTP {resp.status} at {url}")
            body = resp.read()
    except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
        raise ManifestError(f"cannot reach manifest: {e}")
    except OSError as e:
        raise ManifestError(f"network error fetching manifest: {e}")

    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ManifestError(f"manifest is not valid JSON: {e}")
    if not isinstance(data, dict):
        raise ManifestError("manifest must be a JSON object")
    return data


def _component_section(manifest: dict, key: str) -> dict | None:
    """Return the per-component sub-dict, or None if missing/malformed."""
    sec = manifest.get(key)
    if not isinstance(sec, dict):
        return None
    return sec


def check_for_updates() -> dict:
    """
    Check the manifest. Result shape:

    {
      "status": "ok" | "offline" | "disabled" | "error",
      "checked_at": <unix_ts>,
      "current": {"qsforge": "...", "ddc": "..." or None},
      "latest":  {"qsforge": "...", "ddc": "..." or None},
      "available": {
          "qsforge": <bool>,
          "ddc":     <bool>,
      },
      "manifest": <raw manifest dict, only on status=ok>,
      "error": <human string, only on status=error/offline>,
    }
    """
    versions = get_versions()
    out: dict = {
        "status": "error",
        "checked_at": time.time(),
        "current": {"qsforge": versions["qsforge"], "ddc": versions["ddc"]},
        "latest": {"qsforge": None, "ddc": None},
        "available": {"qsforge": False, "ddc": False},
        "manifest": None,
        "error": None,
    }

    if not _version.update_checks_enabled():
        out["status"] = "disabled"
        out["error"] = "Update checks are disabled (QSFORGE_UPDATE_MANIFEST_URL is empty)."
        return out

    try:
        manifest = _fetch_manifest_raw(_version.manifest_url())
    except ManifestError as e:
        # Differentiate "no internet" from "server returned garbage" so the
        # UI can stay quiet on the former and surface the latter.
        msg = str(e)
        offline_signals = (
            "cannot reach manifest",
            "network error",
            "Name or service not known",
            "getaddrinfo failed",
            "Temporary failure",
        )
        out["status"] = "offline" if any(s in msg for s in offline_signals) else "error"
        out["error"] = msg
        return out

    qsforge_sec = _component_section(manifest, COMPONENT_QSFORGE) or {}
    ddc_sec = _component_section(manifest, COMPONENT_DDC) or {}
    latest_qsforge = qsforge_sec.get("version") or None
    latest_ddc = ddc_sec.get("version") or None

    out["latest"]["qsforge"] = latest_qsforge
    out["latest"]["ddc"] = latest_ddc
    out["available"]["qsforge"] = is_newer(latest_qsforge, versions["qsforge"])
    out["available"]["ddc"] = is_newer(latest_ddc, versions["ddc"])
    out["manifest"] = manifest
    out["status"] = "ok"
    return out


# ── Download with progress + verification ──────────────────────────────────
def _free_bytes_for(path: Path) -> int:
    """Free disk space at the volume containing ``path``. Best-effort."""
    try:
        usage = shutil.disk_usage(str(path))
        return int(usage.free)
    except OSError:
        return 0


def _sha256_of_file(path: Path, on_progress=None, cancel_event=None) -> str:
    """Stream-hash a file. ``on_progress(bytes_done, total)`` receives byte counts."""
    total = path.stat().st_size
    h = hashlib.sha256()
    done = 0
    with path.open("rb") as f:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise UpdateCancelled("hash verification cancelled")
            chunk = f.read(_IO_BUFFER)
            if not chunk:
                break
            h.update(chunk)
            done += len(chunk)
            if on_progress is not None:
                on_progress(done, total)
    return h.hexdigest()


def _verify_artefact(
    path: Path,
    expected_sha256: str | None,
    expected_size: int | None,
    on_progress=None,
    cancel_event=None,
) -> None:
    """Raise VerificationError if file doesn't match expected size/hash."""
    if not path.is_file():
        raise VerificationError(f"file is missing: {path}")
    actual_size = path.stat().st_size
    if expected_size is not None and int(expected_size) != actual_size:
        raise VerificationError(
            f"size mismatch: expected {expected_size} bytes, got {actual_size}"
        )
    if expected_sha256:
        actual = _sha256_of_file(path, on_progress=on_progress, cancel_event=cancel_event)
        if actual.lower() != str(expected_sha256).lower():
            raise VerificationError(
                f"sha256 mismatch: expected {expected_sha256}, got {actual}"
            )


def _download_artefact(
    url: str,
    dest: Path,
    *,
    expected_size: int | None = None,
    on_progress=None,
    cancel_event=None,
) -> Path:
    """
    Download ``url`` → ``dest``. Resumes if ``dest.partial`` already exists
    and the server supports HTTP range requests.

    Progress callback signature: ``on_progress(downloaded_bytes, total_bytes)``.
    ``total_bytes`` may be 0 if the server doesn't send Content-Length.
    """
    if not url:
        raise UpdaterError("download URL is empty")
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".partial")

    # Estimate required free space: the partial we'll be writing PLUS the
    # final renamed file (during the rename moment both exist briefly).
    needed = max(0, int(expected_size or 0)) + _FREE_SPACE_HEADROOM
    if needed and _free_bytes_for(partial.parent) < needed:
        free_mb = _free_bytes_for(partial.parent) / 1e6
        raise UpdaterError(
            f"not enough free disk space to download update "
            f"({free_mb:.0f} MB free, need at least {needed / 1e6:.0f} MB)"
        )

    headers = {"User-Agent": _USER_AGENT}
    resume_from = 0
    if partial.exists():
        resume_from = partial.stat().st_size
        if expected_size is not None and resume_from >= int(expected_size):
            # Already-downloaded copy on disk; rename and let the caller verify.
            os.replace(str(partial), str(dest))
            return dest
        if resume_from > 0:
            headers["Range"] = f"bytes={resume_from}-"

    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=MANIFEST_TIMEOUT_SEC)
    except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as e:
        raise UpdaterError(f"download failed before any bytes: {e}")

    try:
        # If we asked for a range but server returned 200 instead of 206,
        # we have to start fresh — wipe whatever was on disk so we don't
        # mix the two halves.
        status = getattr(resp, "status", 200)
        if resume_from and status != 206:
            try:
                partial.unlink(missing_ok=True)  # type: ignore[arg-type]
            except TypeError:  # py<3.8 — should never hit, app needs 3.10+
                if partial.exists():
                    partial.unlink()
            resume_from = 0

        # Total = what server reports + whatever we already had on disk.
        try:
            content_len = int(resp.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            content_len = 0
        total = content_len + (resume_from if status == 206 else 0)
        if expected_size is not None and total == 0:
            total = int(expected_size)

        mode = "ab" if (resume_from and status == 206) else "wb"
        downloaded = resume_from if status == 206 else 0
        # Throttle progress callbacks: at most ~5 per second so the UI
        # doesn't choke on a fast LAN download (200 MB/s = thousands of
        # updates per second otherwise).
        last_emit = 0.0
        with partial.open(mode) as out:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise UpdateCancelled("download cancelled by caller")
                chunk = resp.read(_IO_BUFFER)
                if not chunk:
                    break
                out.write(chunk)
                downloaded += len(chunk)
                if on_progress is not None:
                    now = time.monotonic()
                    if now - last_emit >= 0.2:
                        on_progress(downloaded, total)
                        last_emit = now
        if on_progress is not None:
            on_progress(downloaded, total or downloaded)
    finally:
        try:
            resp.close()
        except OSError:
            pass

    os.replace(str(partial), str(dest))
    return dest


def download_update(
    component: str,
    manifest: dict,
    *,
    on_progress=None,
    cancel_event=None,
) -> Path:
    """
    High-level: download (or reuse cached) artefact for a component, and
    verify SHA-256 + size against the manifest. Returns the path to the
    verified file inside the update cache.
    """
    if component not in KNOWN_COMPONENTS:
        raise UpdaterError(f"unknown component: {component!r}")
    section = _component_section(manifest, component)
    if not section:
        raise UpdaterError(f"manifest has no '{component}' section")

    url_key = "package_url" if component == COMPONENT_DDC else "installer_url"
    url = section.get(url_key)
    if not url:
        raise UpdaterError(f"manifest '{component}' is missing '{url_key}'")
    expected_sha = section.get("sha256")
    expected_size = section.get("size_bytes")
    version = section.get("version") or "unknown"

    cache = _updates_cache_dir()
    # Filename embeds the version so we don't accidentally reuse an old
    # download when the caller bumps the manifest mid-session.
    suffix = ".zip" if component == COMPONENT_DDC else ".exe"
    dest = cache / f"{component}-{version}{suffix}"

    # Fast path: artefact is already on disk and hash matches.
    if dest.is_file():
        try:
            _verify_artefact(dest, expected_sha, expected_size)
            if on_progress is not None:
                size = dest.stat().st_size
                on_progress({"phase": "cache", "downloaded": size, "total": size})
            return dest
        except VerificationError:
            # Stale / corrupted cache — drop it and redownload.
            try:
                dest.unlink()
            except OSError:
                pass

    if on_progress is not None:
        on_progress({"phase": "downloading", "downloaded": 0,
                     "total": int(expected_size or 0), "version": version})

    def _on_dl(done, total):
        if on_progress is not None:
            on_progress({"phase": "downloading", "downloaded": done, "total": total})

    _download_artefact(
        url, dest,
        expected_size=expected_size,
        on_progress=_on_dl,
        cancel_event=cancel_event,
    )

    if on_progress is not None:
        on_progress({"phase": "verifying", "downloaded": 0,
                     "total": dest.stat().st_size})

    def _on_hash(done, total):
        if on_progress is not None:
            on_progress({"phase": "verifying", "downloaded": done, "total": total})

    try:
        _verify_artefact(
            dest, expected_sha, expected_size,
            on_progress=_on_hash, cancel_event=cancel_event,
        )
    except VerificationError:
        # Corrupted download — leave nothing usable behind so the next
        # call starts clean.
        try:
            dest.unlink()
        except OSError:
            pass
        raise

    if on_progress is not None:
        on_progress({"phase": "verified", "downloaded": dest.stat().st_size,
                     "total": dest.stat().st_size, "path": str(dest)})
    return dest


# ── DDC apply (safe in-place swap with one rollback backup) ────────────────
def _is_ddc_running() -> bool:
    """Best-effort check for any RvtExporter.exe still alive on the box."""
    if sys.platform != "win32":
        return False
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq RvtExporter.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5,
            creationflags=0x08000000,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    out = (proc.stdout or "").strip().lower()
    return "rvtexporter.exe" in out


def _rmtree_with_retry(path: Path, attempts: int = 5) -> None:
    """Robust rmtree: Windows holds onto files briefly after process exit."""
    last_err: Exception | None = None
    for i in range(attempts):
        try:
            shutil.rmtree(path, ignore_errors=False)
            return
        except FileNotFoundError:
            return
        except OSError as e:
            last_err = e
            time.sleep(0.3 * (2 ** i))
    if last_err is not None:
        # Last resort: ignore_errors so we at least leave the system bootable.
        shutil.rmtree(path, ignore_errors=True)


def _validate_extracted_ddc(folder: Path) -> Path:
    """
    Confirm an extracted DDC folder actually contains RvtExporter.exe.
    The zip may put files in a top-level folder (``DDC_CONVERTER_REVIT/...``)
    or directly in the root — handle both.

    Returns the directory that should become the new ``vendor\\ddc\\`` —
    i.e. the directory that *directly* contains RvtExporter.exe.
    """
    direct = folder / "RvtExporter.exe"
    if direct.is_file():
        return folder
    # Look one level deep: a single subfolder pattern is the most common
    # zip layout for this kind of bundle.
    children = [p for p in folder.iterdir() if p.is_dir()]
    if len(children) == 1:
        nested = children[0] / "RvtExporter.exe"
        if nested.is_file():
            return children[0]
    raise UpdaterError(
        "downloaded DDC zip does not contain RvtExporter.exe "
        "(zip layout is unexpected; aborting to avoid overwriting working DDC)"
    )


def apply_ddc_update(
    zip_path: Path,
    expected_version: str | None = None,
    on_progress=None,
) -> dict:
    """
    Replace ``vendor\\ddc\\`` with the contents of a verified DDC zip.

    Steps:
      1. Refuse if RvtExporter.exe is currently running (no analysis in flight).
      2. Wipe any stale ``vendor\\ddc-new\\`` from a previous failed attempt.
      3. Extract zip into ``vendor\\ddc-new\\``.
      4. Verify the extracted folder contains RvtExporter.exe.
      5. Rotate any existing ``vendor\\ddc-backup\\`` out of the way and
         rename the live ``vendor\\ddc\\`` -> ``vendor\\ddc-backup\\``.
      6. Rename ``vendor\\ddc-new\\`` -> ``vendor\\ddc\\``.
      7. Write the new version into the marker file.
    """
    log = on_progress or (lambda _msg: None)
    log({"phase": "preflight", "message": "checking that DDC is not running…"})

    if _is_ddc_running():
        return {
            "status": "blocked",
            "message": (
                "An RvtExporter.exe is still running. Wait for the current "
                "analysis to finish (or cancel it) before updating DDC."
            ),
        }

    if not zip_path.is_file():
        return {"status": "error", "message": f"zip not found: {zip_path}"}

    staging = _staging_ddc_dir()
    backup = _backup_ddc_dir()
    live = _vendor_ddc_dir()

    # 2 + 3
    log({"phase": "extract", "message": "extracting DDC archive…"})
    if staging.exists():
        _rmtree_with_retry(staging)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(staging)
    except (zipfile.BadZipFile, OSError) as e:
        _rmtree_with_retry(staging)
        return {"status": "error", "message": f"could not extract zip: {e}"}

    # 4
    try:
        usable = _validate_extracted_ddc(staging)
    except UpdaterError as e:
        _rmtree_with_retry(staging)
        return {"status": "error", "message": str(e)}

    # If the layout was nested, flatten so vendor\ddc-new\ ends up with
    # RvtExporter.exe at its root (matches the existing folder layout).
    if usable != staging:
        flat = _user_data_dir() / "vendor" / "ddc-new-flat"
        if flat.exists():
            _rmtree_with_retry(flat)
        os.replace(str(usable), str(flat))
        _rmtree_with_retry(staging)
        os.replace(str(flat), str(staging))

    # 5: prepare backup folder. If a backup from the previous update is
    # still around, retire it now (we only ever keep ONE rollback copy
    # because each one is ~600 MB).
    if backup.exists():
        log({"phase": "prune_backup",
             "message": "removing previous DDC backup to free disk space…"})
        _rmtree_with_retry(backup)

    log({"phase": "swap", "message": "swapping live DDC with new version…"})
    if live.exists():
        try:
            os.replace(str(live), str(backup))
        except OSError as e:
            _rmtree_with_retry(staging)
            return {
                "status": "error",
                "message": f"could not move existing DDC out of the way: {e}",
            }

    # 6
    try:
        os.replace(str(staging), str(live))
    except OSError as e:
        # Try to roll back so the user isn't left without a working DDC.
        if backup.exists() and not live.exists():
            try:
                os.replace(str(backup), str(live))
            except OSError:
                pass
        return {
            "status": "error",
            "message": f"could not move new DDC into place: {e}",
        }

    # 7
    if expected_version:
        try:
            (live / _DDC_VERSION_MARKER).write_text(
                expected_version, encoding="utf-8",
            )
        except OSError:
            # Non-fatal: marker is purely informational.
            pass

    log({"phase": "done",
         "message": f"DDC updated to {expected_version or 'new version'}.",
         "version": expected_version})
    return {
        "status": "ok",
        "message": f"DDC updated to {expected_version or 'new version'}.",
        "version": expected_version,
        "backup_path": str(backup) if backup.exists() else None,
    }


def rollback_ddc() -> dict:
    """Restore vendor\\ddc-backup\\ -> vendor\\ddc\\. Used after a failed update."""
    backup = _backup_ddc_dir()
    live = _vendor_ddc_dir()
    if not backup.exists():
        return {"status": "error", "message": "no DDC backup to roll back to."}
    if _is_ddc_running():
        return {
            "status": "blocked",
            "message": "RvtExporter.exe is running; cannot roll back right now.",
        }
    if live.exists():
        # Keep the broken update around in a discarded folder for forensic
        # purposes (auto-deleted next successful update).
        retired = _user_data_dir() / "vendor" / f"ddc-failed-{int(time.time())}"
        try:
            os.replace(str(live), str(retired))
        except OSError as e:
            return {"status": "error", "message": f"could not move broken DDC: {e}"}
    try:
        os.replace(str(backup), str(live))
    except OSError as e:
        return {"status": "error", "message": f"rollback failed: {e}"}
    return {"status": "ok", "message": "Rolled back to previous DDC."}


# ── QSForge apply (delegate to Inno Setup) ─────────────────────────────────
def apply_qsforge_update(installer_path: Path) -> dict:
    """
    Launch the downloaded Inno Setup installer in silent-restart mode and
    request the running QSForge to exit cleanly. The new build will be
    started by Inno's RESTARTAPPLICATIONS handler when /SILENT finishes.

    Note this does NOT block — Inno keeps running after we return. Caller
    should immediately tear down the webview window so the installer can
    overwrite QSForge.exe without "file in use" errors.
    """
    if not installer_path.is_file():
        return {"status": "error", "message": f"installer missing: {installer_path}"}

    # /SILENT shows progress, /VERYSILENT hides everything. Pick /SILENT
    # so commercial users still get *some* feedback that an update is
    # happening — a totally invisible re-install would be alarming.
    args = [
        str(installer_path),
        "/SILENT",
        "/CLOSEAPPLICATIONS",
        "/RESTARTAPPLICATIONS",
        "/NORESTART",
    ]
    try:
        # DETACHED_PROCESS (0x00000008) so the installer survives this
        # process exiting in the next few hundred ms.
        creationflags = 0
        if sys.platform == "win32":
            creationflags = 0x00000008  # DETACHED_PROCESS
        subprocess.Popen(  # noqa: S603 — args are constructed from validated paths
            args,
            creationflags=creationflags,
            close_fds=True,
        )
    except OSError as e:
        return {"status": "error", "message": f"failed to launch installer: {e}"}

    return {
        "status": "ok",
        "message": "Installer launched. QSForge will close shortly.",
        "installer_path": str(installer_path),
    }


# ── Background download job (used by Flask /api/updates/download) ──────────
class UpdateJob:
    """A single in-flight download/apply job. Mirrors the Job class in server.py."""

    __slots__ = (
        "id", "component", "manifest", "state", "progress", "result",
        "error", "created_at", "started_at", "finished_at", "cancel_event",
        "_lock",
    )

    def __init__(self, component: str, manifest: dict):
        import uuid
        self.id = uuid.uuid4().hex[:12]
        self.component = component
        self.manifest = manifest
        # queued | downloading | verifying | downloaded | applying | done | error | cancelled
        self.state = "queued"
        self.progress = {"phase": "queued", "downloaded": 0, "total": 0}
        self.result: dict | None = None
        self.error: str | None = None
        self.created_at = time.time()
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.cancel_event = threading.Event()
        self._lock = threading.Lock()

    def to_public(self) -> dict:
        with self._lock:
            return {
                "id": self.id,
                "component": self.component,
                "state": self.state,
                "progress": dict(self.progress),
                "result": self.result,
                "error": self.error,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            }

    def update_progress(self, p: dict) -> None:
        with self._lock:
            # Don't overwrite a path-bearing terminal frame with a partial one
            self.progress = dict(p)
            phase = p.get("phase")
            if phase == "downloading":
                self.state = "downloading"
            elif phase == "verifying":
                self.state = "verifying"
            elif phase == "verified":
                self.state = "downloaded"


_jobs_lock = threading.Lock()
_jobs: dict[str, UpdateJob] = {}


def get_job(job_id: str) -> UpdateJob | None:
    with _jobs_lock:
        return _jobs.get(job_id)


def start_download_job(component: str, manifest: dict) -> UpdateJob:
    """Kick off an asynchronous download for ``component``. Returns the job."""
    if component not in KNOWN_COMPONENTS:
        raise UpdaterError(f"unknown component: {component!r}")
    job = UpdateJob(component, manifest)
    with _jobs_lock:
        _jobs[job.id] = job

    def _run():
        job.started_at = time.time()
        try:
            artefact = download_update(
                component, manifest,
                on_progress=job.update_progress,
                cancel_event=job.cancel_event,
            )
            with job._lock:
                job.state = "downloaded"
                job.result = {"artefact_path": str(artefact)}
        except UpdateCancelled:
            with job._lock:
                job.state = "cancelled"
                job.error = "download cancelled"
        except (UpdaterError, OSError) as e:
            with job._lock:
                job.state = "error"
                job.error = str(e)
        finally:
            job.finished_at = time.time()

    t = threading.Thread(target=_run, daemon=True, name=f"updater-{component}-{job.id}")
    t.start()
    return job


# ── CLI smoke test ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("QSForge Updater — quick status report")
    print("─" * 50)
    v = get_versions()
    for k, val in v.items():
        print(f"  {k}: {val}")
    print()
    if "--check" in sys.argv:
        print("Checking for updates…")
        result = check_for_updates()
        print(json.dumps(result, indent=2, default=str))
