"""Tests for src/cache.py — DDC output cache."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

import cache  # imported via conftest.py sys.path injection


def _write_cache_files(rvt: Path, mode: str, ddc_version: str = "18.1.0",
                      qsforge_version: str = "1.3.0") -> tuple[Path, Path, Path]:
    """Create a complete cache trio (xlsx, dae, json) for a .rvt fixture.

    Returns (xlsx_path, dae_path, json_path).
    """
    cache_dir = rvt.parent / ".qsforge-cache"
    cache_dir.mkdir(exist_ok=True)
    base = rvt.stem
    xlsx = cache_dir / f"{base}_{mode}.xlsx"
    dae = cache_dir / f"{base}_{mode}.dae"
    meta = cache_dir / f"{base}_{mode}.cache.json"
    xlsx.write_bytes(b"fake xlsx")
    dae.write_bytes(b"fake dae")
    stat = rvt.stat()
    meta.write_text(json.dumps({
        "schema_version": 2,
        "rvt_path": str(rvt),
        "rvt_size": stat.st_size,
        "rvt_mtime": stat.st_mtime,
        "ddc_mode": mode,
        "ddc_version": ddc_version,
        "qsforge_version": qsforge_version,
        "created_at": "2026-05-08T10:23:14Z",
        "xlsx_path": str(xlsx),
        "dae_path": str(dae),
        "glb_path": "",
    }))
    return xlsx, dae, meta


def test_lookup_returns_none_when_no_cache_exists(tmp_rvt):
    assert cache.lookup(str(tmp_rvt), "standard") is None


def test_lookup_returns_none_when_only_xlsx_exists(tmp_rvt):
    cache_dir = tmp_rvt.parent / ".qsforge-cache"
    cache_dir.mkdir()
    (cache_dir / f"{tmp_rvt.stem}_standard.xlsx").write_bytes(b"x")
    assert cache.lookup(str(tmp_rvt), "standard") is None


def test_lookup_returns_none_when_meta_json_missing(tmp_rvt):
    cache_dir = tmp_rvt.parent / ".qsforge-cache"
    cache_dir.mkdir()
    (cache_dir / f"{tmp_rvt.stem}_standard.xlsx").write_bytes(b"x")
    (cache_dir / f"{tmp_rvt.stem}_standard.dae").write_bytes(b"d")
    assert cache.lookup(str(tmp_rvt), "standard") is None


def test_lookup_returns_hit_when_cache_is_fresh(tmp_rvt):
    _write_cache_files(tmp_rvt, "standard")
    hit = cache.lookup(str(tmp_rvt), "standard")
    assert hit is not None
    assert hit.ddc_mode == "standard"
    assert hit.xlsx_path.name.endswith("_standard.xlsx")
    assert hit.dae_path.name.endswith("_standard.dae")
    assert hit.glb_path is None


def test_lookup_invalidates_when_rvt_size_changed(tmp_rvt):
    _write_cache_files(tmp_rvt, "standard")
    # Append bytes to change the size
    with open(tmp_rvt, "ab") as f:
        f.write(b"more data")
    assert cache.lookup(str(tmp_rvt), "standard") is None


def test_lookup_invalidates_when_rvt_mtime_changed_beyond_tolerance(tmp_rvt):
    _write_cache_files(tmp_rvt, "standard")
    # Touch the rvt 5 s into the future (> 2 s tolerance)
    new_t = tmp_rvt.stat().st_mtime + 5.0
    os.utime(tmp_rvt, (new_t, new_t))
    assert cache.lookup(str(tmp_rvt), "standard") is None


def test_lookup_tolerates_mtime_drift_within_tolerance(tmp_rvt):
    _write_cache_files(tmp_rvt, "standard")
    new_t = tmp_rvt.stat().st_mtime + 1.0  # < 2 s tolerance
    os.utime(tmp_rvt, (new_t, new_t))
    hit = cache.lookup(str(tmp_rvt), "standard")
    assert hit is not None
    assert hit.glb_path is None


def test_lookup_invalidates_when_mode_differs(tmp_rvt):
    _write_cache_files(tmp_rvt, "standard")
    # Asking for 'complete' against a 'standard' cache → miss
    assert cache.lookup(str(tmp_rvt), "complete") is None


def test_lookup_invalidates_when_ddc_version_differs(tmp_rvt, monkeypatch):
    _write_cache_files(tmp_rvt, "standard", ddc_version="17.0.0")
    # Pretend our bundled DDC is now 18.1.0
    monkeypatch.setattr(cache, "_current_ddc_version", lambda: "18.1.0")
    assert cache.lookup(str(tmp_rvt), "standard") is None


def test_lookup_invalidates_when_xlsx_was_deleted(tmp_rvt):
    xlsx, _, _ = _write_cache_files(tmp_rvt, "standard")
    xlsx.unlink()
    assert cache.lookup(str(tmp_rvt), "standard") is None


def test_lookup_invalidates_when_dae_was_deleted(tmp_rvt):
    _, dae, _ = _write_cache_files(tmp_rvt, "standard")
    dae.unlink()
    assert cache.lookup(str(tmp_rvt), "standard") is None


def test_lookup_invalidates_when_schema_version_differs(tmp_rvt):
    _, _, meta = _write_cache_files(tmp_rvt, "standard")
    data = json.loads(meta.read_text())
    data["schema_version"] = 999
    meta.write_text(json.dumps(data))
    assert cache.lookup(str(tmp_rvt), "standard") is None


def test_lookup_returns_none_on_corrupt_json(tmp_rvt):
    _, _, meta = _write_cache_files(tmp_rvt, "standard")
    meta.write_text("{ this is not valid json")
    assert cache.lookup(str(tmp_rvt), "standard") is None


def test_store_writes_xlsx_dae_and_meta_to_cache_dir(tmp_path, monkeypatch):
    rvt = tmp_path / "m.rvt"
    rvt.write_bytes(b"x" * 100)
    src_xlsx = tmp_path / "src.xlsx"
    src_dae = tmp_path / "src.dae"
    src_xlsx.write_bytes(b"xlsx-bytes")
    src_dae.write_bytes(b"dae-bytes")

    monkeypatch.setattr(cache, "_current_ddc_version", lambda: "18.1.0")
    cache.store(str(rvt), "standard", str(src_xlsx), str(src_dae))

    cache_dir = rvt.parent / ".qsforge-cache"
    assert (cache_dir / "m_standard.xlsx").read_bytes() == b"xlsx-bytes"
    assert (cache_dir / "m_standard.dae").read_bytes() == b"dae-bytes"
    meta = json.loads((cache_dir / "m_standard.cache.json").read_text())
    assert meta["schema_version"] == 2
    assert meta["ddc_mode"] == "standard"
    assert meta["ddc_version"] == "18.1.0"
    assert meta["rvt_size"] == 100
    assert meta["glb_path"] == ""


def test_store_then_lookup_round_trip(tmp_path, monkeypatch):
    rvt = tmp_path / "m.rvt"
    rvt.write_bytes(b"y" * 50)
    src_xlsx = tmp_path / "src.xlsx"
    src_dae = tmp_path / "src.dae"
    src_xlsx.write_bytes(b"x")
    src_dae.write_bytes(b"d")
    monkeypatch.setattr(cache, "_current_ddc_version", lambda: "18.1.0")

    cache.store(str(rvt), "standard", str(src_xlsx), str(src_dae))
    hit = cache.lookup(str(rvt), "standard")
    assert hit is not None
    assert hit.ddc_mode == "standard"
    assert hit.glb_path is None


def test_invalidate_removes_cache_files(tmp_rvt, monkeypatch):
    monkeypatch.setattr(cache, "_current_ddc_version", lambda: "18.1.0")
    _write_cache_files(tmp_rvt, "standard")
    cache.invalidate(str(tmp_rvt), "standard")
    assert cache.lookup(str(tmp_rvt), "standard") is None
    cache_dir = tmp_rvt.parent / ".qsforge-cache"
    assert not (cache_dir / f"{tmp_rvt.stem}_standard.xlsx").exists()
    assert not (cache_dir / f"{tmp_rvt.stem}_standard.dae").exists()
    assert not (cache_dir / f"{tmp_rvt.stem}_standard.cache.json").exists()


def test_invalidate_is_safe_when_no_cache_exists(tmp_rvt):
    cache.invalidate(str(tmp_rvt), "standard")  # should not raise


def test_store_raises_when_rvt_missing(tmp_path):
    src_xlsx = tmp_path / "src.xlsx"; src_xlsx.write_bytes(b"x")
    src_dae = tmp_path / "src.dae"; src_dae.write_bytes(b"d")
    with pytest.raises(FileNotFoundError, match="rvt"):
        cache.store(str(tmp_path / "missing.rvt"), "standard",
                    str(src_xlsx), str(src_dae))


def test_store_raises_when_xlsx_missing(tmp_rvt, tmp_path):
    src_dae = tmp_path / "src.dae"; src_dae.write_bytes(b"d")
    with pytest.raises(FileNotFoundError, match="xlsx"):
        cache.store(str(tmp_rvt), "standard",
                    str(tmp_path / "missing.xlsx"), str(src_dae))


def test_store_raises_when_dae_missing(tmp_rvt, tmp_path):
    src_xlsx = tmp_path / "src.xlsx"; src_xlsx.write_bytes(b"x")
    with pytest.raises(FileNotFoundError, match="dae"):
        cache.store(str(tmp_rvt), "standard",
                    str(src_xlsx), str(tmp_path / "missing.dae"))


def test_store_rolls_back_on_partial_failure(tmp_rvt, tmp_path, monkeypatch):
    """If JSON write fails after copies succeed, no orphans should remain."""
    src_xlsx = tmp_path / "src.xlsx"; src_xlsx.write_bytes(b"x")
    src_dae = tmp_path / "src.dae"; src_dae.write_bytes(b"d")
    monkeypatch.setattr(cache, "_current_ddc_version", lambda: "18.1.0")

    # Force the JSON write to fail by patching write_text on the meta path.
    # Easiest approach: patch json.dumps to raise.
    real_dumps = cache.json.dumps
    def boom(*a, **kw):
        raise RuntimeError("simulated metadata write failure")
    monkeypatch.setattr(cache.json, "dumps", boom)

    with pytest.raises(RuntimeError):
        cache.store(str(tmp_rvt), "standard", str(src_xlsx), str(src_dae))

    # Restore so post-test inspection works
    monkeypatch.setattr(cache.json, "dumps", real_dumps)

    cache_dir = tmp_rvt.parent / ".qsforge-cache"
    assert not (cache_dir / f"{tmp_rvt.stem}_standard.xlsx").exists()
    assert not (cache_dir / f"{tmp_rvt.stem}_standard.dae").exists()
    assert not (cache_dir / f"{tmp_rvt.stem}_standard.cache.json").exists()


def test_store_xlsx_only_round_trip_has_no_dae(tmp_path, monkeypatch):
    """xlsx-only entries round-trip through lookup with dae_path=None.

    The dae-aware downgrade ("treat as miss when caller wants DAE but cache
    has none") lives in the caller (``ddc_runner.run_ddc``), not in
    ``cache.lookup`` itself — ``lookup`` just reports what's recorded.
    This test verifies that recording side: a `store_xlsx_only` write
    becomes a hit whose `dae_path` is ``None``, which is the signal the
    caller uses to decide whether to re-run DDC.
    """
    rvt = tmp_path / "m.rvt"
    rvt.write_bytes(b"x" * 100)
    src_xlsx = tmp_path / "src.xlsx"
    src_xlsx.write_bytes(b"xlsx-bytes")
    monkeypatch.setattr(cache, "_current_ddc_version", lambda: "18.1.0")

    cache.store_xlsx_only(str(rvt), "standard", str(src_xlsx))

    # Plain lookup hits — caller did not ask for dae
    hit = cache.lookup(str(rvt), "standard")
    assert hit is not None
    assert hit.dae_path is None
    assert hit.glb_path is None
    # Caller-side dae-aware logic: a dae=True request would treat this as a miss
    assert hit.dae_path is None or not hit.dae_path.is_file()


def test_store_and_lookup_with_glb(tmp_rvt, tmp_path, monkeypatch):
    """A store call that includes glb_path must round-trip through lookup."""
    import cache
    monkeypatch.setattr(cache, "_current_ddc_version", lambda: "test-1.0")

    xlsx = tmp_path / "out.xlsx"
    xlsx.write_bytes(b"FAKE_XLSX")
    dae = tmp_path / "out.dae"
    dae.write_bytes(b"FAKE_DAE")
    glb = tmp_path / "out.glb"
    glb.write_bytes(b"glTF" + b"FAKE_GLB_PAYLOAD")

    cache.store(str(tmp_rvt), "default", str(xlsx), str(dae), str(glb))
    hit = cache.lookup(str(tmp_rvt), "default")
    assert hit is not None
    assert hit.glb_path is not None
    assert hit.glb_path.is_file()
    assert hit.glb_path.read_bytes()[:4] == b"glTF"


def test_v1_cache_is_invalidated(tmp_rvt, tmp_path, monkeypatch):
    """A v1 cache JSON must be ignored by v2 lookup."""
    import cache, json
    monkeypatch.setattr(cache, "_current_ddc_version", lambda: "test-1.0")
    cache_dir = tmp_rvt.parent / ".qsforge-cache"
    cache_dir.mkdir()
    (cache_dir / "model_default.cache.json").write_text(json.dumps({
        "schema_version": 1,  # OLD version
        "rvt_path": str(tmp_rvt),
        "rvt_size": tmp_rvt.stat().st_size,
        "rvt_mtime": tmp_rvt.stat().st_mtime,
        "ddc_mode": "default",
        "ddc_version": "test-1.0",
        "qsforge_version": "1.0.0",
        "xlsx_path": "",
        "dae_path": "",
    }))
    assert cache.lookup(str(tmp_rvt), "default") is None


def test_update_glb_promotes_into_existing_cache(tmp_rvt, tmp_path, monkeypatch):
    """A regenerated GLB should be promoted into the cache and its path
    written back into the sidecar so the next hit is free."""
    monkeypatch.setattr(cache, "_current_ddc_version", lambda: "test-1.0")
    # Seed an existing cache entry with empty glb_path.
    _write_cache_files(tmp_rvt, "standard")
    new_glb = tmp_path / "regenerated.glb"
    new_glb.write_bytes(b"glTF" + b"FRESH_GLB_PAYLOAD")

    result = cache.update_glb(str(tmp_rvt), "standard", str(new_glb))

    assert result is not None
    assert result.is_file()
    # Sidecar should now record the cache-dir copy.
    sidecar = tmp_rvt.parent / ".qsforge-cache" / f"{tmp_rvt.stem}_standard.cache.json"
    data = json.loads(sidecar.read_text())
    assert data["glb_path"] == str(result)
    # The cache-dir copy must match the source bytes.
    assert result.read_bytes() == new_glb.read_bytes()


def test_update_glb_returns_none_when_no_cache(tmp_rvt, tmp_path):
    """update_glb should silently no-op if there's no sidecar to update."""
    new_glb = tmp_path / "regenerated.glb"
    new_glb.write_bytes(b"glTF" + b"payload")
    # No cache entry seeded for this rvt.
    assert cache.update_glb(str(tmp_rvt), "standard", str(new_glb)) is None


def test_update_glb_returns_none_when_source_missing(tmp_rvt, tmp_path, monkeypatch):
    """update_glb should not crash when the source GLB file is gone."""
    monkeypatch.setattr(cache, "_current_ddc_version", lambda: "test-1.0")
    _write_cache_files(tmp_rvt, "standard")
    assert cache.update_glb(str(tmp_rvt), "standard", str(tmp_path / "does_not_exist.glb")) is None


def test_load_result_accepts_caches_from_same_major_version(tmp_rvt, monkeypatch):
    """1.0.2-created cache must remain usable under 1.0.3 (same major)."""
    monkeypatch.setattr(cache, "_current_ddc_version", lambda: "18.1.0")
    monkeypatch.setattr(cache, "_current_qsforge_version", lambda: "1.0.3")
    _write_cache_files(tmp_rvt, "standard", qsforge_version="1.0.2")
    # Seed the result.json sidecar that load_result needs.
    result_p = tmp_rvt.parent / ".qsforge-cache" / f"{tmp_rvt.stem}_standard.result.json"
    result_p.write_text(json.dumps({"module0": {}, "module2": {}, "module3": {}, "score": {}}))
    assert cache.load_result(str(tmp_rvt), "standard") is not None


def test_load_result_rejects_caches_from_different_major(tmp_rvt, monkeypatch):
    """A 0.x cache (different major) should be invalidated under 1.x."""
    monkeypatch.setattr(cache, "_current_ddc_version", lambda: "18.1.0")
    monkeypatch.setattr(cache, "_current_qsforge_version", lambda: "1.0.3")
    _write_cache_files(tmp_rvt, "standard", qsforge_version="0.9.0")
    result_p = tmp_rvt.parent / ".qsforge-cache" / f"{tmp_rvt.stem}_standard.result.json"
    result_p.write_text("{}")
    assert cache.load_result(str(tmp_rvt), "standard") is None
