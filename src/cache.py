"""QSForge — DDC output cache.

Stores the (xlsx, dae) pair next to the .rvt under `.qsforge-cache/` along
with a tiny JSON sidecar that records the metadata we need to decide whether
the cache is still valid for a given .rvt + DDC mode.

Public API
----------
* :func:`lookup`     — returns a :class:`CacheHit` or ``None``
* :func:`store`      — write metadata after a successful DDC run
* :func:`invalidate` — delete the cache entry for one (.rvt, mode) pair

Design notes
------------
* Cache files live next to the .rvt in a hidden ``.qsforge-cache/`` folder.
* The JSON sidecar is tiny (< 1 KB) and human-readable for debugging.
* All paths in the JSON are stored as absolute strings; we re-validate on
  every lookup that they still exist on disk.
* Any IO/JSON error is treated as a cache miss — never a fatal error.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Bumped whenever the JSON shape changes. Old caches are silently invalidated.
SCHEMA_VERSION = 2

# Filesystem mtimes can round up to 2 s on some Windows filesystems.
MTIME_TOLERANCE_SEC = 2.0


@dataclass(frozen=True)
class CacheHit:
    xlsx_path: Path
    dae_path: Optional[Path]
    glb_path: Optional[Path]
    ddc_mode: str
    ddc_version: str
    qsforge_version: str
    created_at: str


def _cache_dir(rvt_path: str | Path) -> Path:
    return Path(rvt_path).resolve().parent / ".qsforge-cache"


def _meta_path(rvt_path: str | Path, ddc_mode: str) -> Path:
    base = Path(rvt_path).stem
    return _cache_dir(rvt_path) / f"{base}_{ddc_mode}.cache.json"


def _current_ddc_version() -> str:
    """Read the bundled DDC version stamped at build time."""
    # Override hook for tests; both possible locations are checked because
    # the source tree puts the file at <root>/vendor/ddc/ but tests can
    # also place it at <src>/vendor/ddc/ for hermetic runs.
    candidates = [
        Path(__file__).parent.parent / "vendor" / "ddc" / ".qsforge-ddc-version",
        Path(__file__).parent / "vendor" / "ddc" / ".qsforge-ddc-version",
    ]
    for c in candidates:
        if c.is_file():
            try:
                return c.read_text(encoding="utf-8").strip()
            except OSError:
                pass
    return "unknown"


def _current_qsforge_version() -> str:
    try:
        import _version
        return _version.QSFORGE_VERSION
    except Exception:
        return "unknown"


def lookup(rvt_path: str, ddc_mode: str) -> Optional[CacheHit]:
    """Return a :class:`CacheHit` if the cache is fresh, else ``None``.

    Treats every error condition as a miss. Never raises.
    """
    rvt = Path(rvt_path)
    if not rvt.is_file():
        return None

    meta_p = _meta_path(rvt_path, ddc_mode)
    if not meta_p.is_file():
        return None

    try:
        data = json.loads(meta_p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if data.get("schema_version") != SCHEMA_VERSION:
        return None
    if data.get("ddc_mode") != ddc_mode:
        return None
    if data.get("ddc_version") != _current_ddc_version():
        return None

    try:
        rvt_stat = rvt.stat()
    except OSError:
        return None
    if data.get("rvt_size") != rvt_stat.st_size:
        return None
    cached_mtime = data.get("rvt_mtime", 0)
    if abs(rvt_stat.st_mtime - cached_mtime) > MTIME_TOLERANCE_SEC:
        return None

    xlsx = Path(data.get("xlsx_path", ""))
    if not xlsx.is_file():
        return None
    dae_str = data.get("dae_path", "")
    dae_path = Path(dae_str) if dae_str else None
    # If the cache entry has a DAE recorded, it must still exist.
    if dae_path is not None and not dae_path.is_file():
        return None

    glb_str = data.get("glb_path", "")
    glb_path = Path(glb_str) if glb_str else None
    if glb_path is not None and not glb_path.is_file():
        return None

    return CacheHit(
        xlsx_path=xlsx,
        dae_path=dae_path,
        glb_path=glb_path,
        ddc_mode=data.get("ddc_mode", ddc_mode),
        ddc_version=data.get("ddc_version", ""),
        qsforge_version=data.get("qsforge_version", ""),
        created_at=data.get("created_at", ""),
    )


def store(rvt_path: str, ddc_mode: str,
          xlsx_path: str, dae_path: str,
          glb_path: str | None = None) -> None:
    """Copy fresh xlsx + dae (+ optional glb) into the cache dir and write metadata.

    The xlsx and dae source files MUST exist on disk. The glb source, if
    provided, is copied best-effort: a missing glb does not raise (it just
    isn't recorded). Copies are used (not moves) so the caller can keep its
    own working files.
    """
    rvt = Path(rvt_path).resolve()
    src_xlsx = Path(xlsx_path)
    src_dae = Path(dae_path)
    if not rvt.is_file():
        raise FileNotFoundError(f".rvt does not exist: {rvt}")
    if not src_xlsx.is_file():
        raise FileNotFoundError(f"xlsx does not exist: {src_xlsx}")
    if not src_dae.is_file():
        raise FileNotFoundError(f"dae does not exist: {src_dae}")

    cache_dir = _cache_dir(rvt_path)
    cache_dir.mkdir(exist_ok=True)
    base = rvt.stem

    dst_xlsx = cache_dir / f"{base}_{ddc_mode}.xlsx"
    dst_dae = cache_dir / f"{base}_{ddc_mode}.dae"
    meta_p = cache_dir / f"{base}_{ddc_mode}.cache.json"

    # Atomic-ish: if any step fails, roll back so we never leave an orphan
    # xlsx / dae sitting in the cache dir without metadata. The next lookup
    # would correctly miss (because meta is required), but the orphans
    # would consume disk forever.
    try:
        shutil.copy2(src_xlsx, dst_xlsx)
        shutil.copy2(src_dae, dst_dae)
        dst_glb_str = ""
        if glb_path:
            src_glb = Path(glb_path)
            if src_glb.is_file():
                dst_glb = cache_dir / f"{base}_{ddc_mode}.glb"
                shutil.copy2(src_glb, dst_glb)
                dst_glb_str = str(dst_glb)
        rvt_stat = rvt.stat()
        meta_p.write_text(json.dumps({
            "schema_version": SCHEMA_VERSION,
            "rvt_path": str(rvt),
            "rvt_size": rvt_stat.st_size,
            "rvt_mtime": rvt_stat.st_mtime,
            "ddc_mode": ddc_mode,
            "ddc_version": _current_ddc_version(),
            "qsforge_version": _current_qsforge_version(),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "xlsx_path": str(dst_xlsx),
            "dae_path": str(dst_dae),
            "glb_path": dst_glb_str,
        }, indent=2), encoding="utf-8")
    except Exception:
        invalidate(rvt_path, ddc_mode)
        raise


def store_xlsx_only(rvt_path: str, ddc_mode: str, xlsx_path: str) -> None:
    """Store an xlsx-only cache entry (no DAE).

    Used when DDC is run without `dae=True`. A future `dae=True` request
    will see no `.dae` next to the metadata and treat this as a cache miss,
    correctly forcing a fresh DDC run that produces both files.
    """
    rvt = Path(rvt_path).resolve()
    src_xlsx = Path(xlsx_path)
    if not rvt.is_file() or not src_xlsx.is_file():
        return  # silent miss

    cache_dir = _cache_dir(rvt_path)
    cache_dir.mkdir(exist_ok=True)
    base = rvt.stem

    dst_xlsx = cache_dir / f"{base}_{ddc_mode}.xlsx"
    meta_p = cache_dir / f"{base}_{ddc_mode}.cache.json"

    try:
        shutil.copy2(src_xlsx, dst_xlsx)
        rvt_stat = rvt.stat()
        meta_p.write_text(json.dumps({
            "schema_version": SCHEMA_VERSION,
            "rvt_path": str(rvt),
            "rvt_size": rvt_stat.st_size,
            "rvt_mtime": rvt_stat.st_mtime,
            "ddc_mode": ddc_mode,
            "ddc_version": _current_ddc_version(),
            "qsforge_version": _current_qsforge_version(),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "xlsx_path": str(dst_xlsx),
            "dae_path": "",  # absent — lookup returns CacheHit with dae_path=None
            "glb_path": "",
        }, indent=2), encoding="utf-8")
    except Exception:
        invalidate(rvt_path, ddc_mode)
        raise


def update_glb(rvt_path: str, ddc_mode: str, glb_path: str) -> Optional[Path]:
    """Promote a freshly-generated GLB into an existing cache entry.

    Used on cache-hit when the cache's xlsx+dae are still good but no GLB
    was cached (e.g. because Module 3 failed when the entry was first
    created on a build with broken trimesh — see 1.0.2 retrospective).
    We copy the new GLB into the cache dir and rewrite the sidecar's
    ``glb_path`` field so the *next* cache hit can serve it without any
    trimesh re-conversion.

    Best-effort: silently returns ``None`` on any failure rather than
    breaking the cache hit. The caller still has the regenerated GLB at
    its original path; we're just trying to make future hits faster.
    """
    rvt = Path(rvt_path).resolve()
    src_glb = Path(glb_path)
    if not rvt.is_file() or not src_glb.is_file():
        return None
    meta_p = _meta_path(rvt_path, ddc_mode)
    if not meta_p.is_file():
        return None
    try:
        data = json.loads(meta_p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    cache_dir = _cache_dir(rvt_path)
    cache_dir.mkdir(exist_ok=True)
    base = rvt.stem
    dst_glb = cache_dir / f"{base}_{ddc_mode}.glb"
    try:
        if src_glb.resolve() != dst_glb.resolve():
            shutil.copy2(src_glb, dst_glb)
        data["glb_path"] = str(dst_glb)
        meta_p.write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )
        return dst_glb
    except Exception:
        return None


def _result_path(rvt_path: str | Path, ddc_mode: str) -> Path:
    base = Path(rvt_path).stem
    return _cache_dir(rvt_path) / f"{base}_{ddc_mode}.result.json"


def store_result(rvt_path: str, ddc_mode: str, result: dict) -> None:
    """Persist the full Module-0/1/2/3 + scoring result dict.

    Lets future analyses of the same .rvt skip the entire pipeline and
    just deserialise the cached result. Saves ~100s on big models.

    Best-effort: if writing fails for any reason (disk full, permissions),
    we log nothing and move on — the pipeline already produced a result.
    """
    rvt = Path(rvt_path).resolve()
    if not rvt.is_file():
        return
    cache_dir = _cache_dir(rvt_path)
    try:
        cache_dir.mkdir(exist_ok=True)
        path = _result_path(rvt_path, ddc_mode)
        path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception:
        pass


def load_result(rvt_path: str, ddc_mode: str) -> Optional[dict]:
    """Return the cached result dict if fresh, else ``None``.

    Re-uses :func:`lookup` for freshness — so all the same invalidation
    rules apply (rvt size/mtime, ddc_mode, ddc_version, schema_version).
    Additionally requires ``qsforge_version`` to match: schema changes
    between releases otherwise risk feeding stale dicts to new code.
    """
    hit = lookup(rvt_path, ddc_mode)
    if hit is None:
        return None
    if hit.qsforge_version != _current_qsforge_version():
        return None
    path = _result_path(rvt_path, ddc_mode)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def invalidate(rvt_path: str, ddc_mode: str) -> None:
    """Remove the cache files for one (.rvt, mode) pair. Safe if absent."""
    base = Path(rvt_path).stem
    cache_dir = _cache_dir(rvt_path)
    for suffix in (".xlsx", ".dae", ".glb", ".cache.json", ".result.json"):
        p = cache_dir / f"{base}_{ddc_mode}{suffix}"
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            # Best effort — don't crash on permissions errors etc.
            pass
