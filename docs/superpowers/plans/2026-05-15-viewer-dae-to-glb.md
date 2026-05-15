# Viewer DAE → GLB Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the failing three.js `ColladaLoader` rendering path with a trimesh-based DAE→GLB conversion step plus `GLTFLoader`-based rendering, so that the same Revit models that open in CAD Assistant also render in QSForge.

**Architecture:** DDC continues to emit `.dae`. A new server-side step converts the DAE to GLB via `trimesh`. The Flask `/api/3d/<job_id>` endpoint streams the GLB with MIME `model/gltf-binary`. The browser viewer swaps `ColladaLoader` for `GLTFLoader`. Element-IDs flow from DAE node `id` → patched `name` (existing logic) → trimesh node `name` → glTF node `name` → `Object3D.name`.

**Tech Stack:** Python 3.x + Flask + pywebview backend; PyInstaller frozen build; trimesh (with pycollada) for conversion; three.js + GLTFLoader for rendering; pytest for tests; Inno Setup for the installer; PowerShell `build.ps1` for build.

**Spec:** `docs/superpowers/specs/2026-05-15-viewer-dae-to-glb-design.md`

---

## File Structure

| File | Responsibility | Status |
|---|---|---|
| `requirements.txt` | Declare `trimesh` runtime dep | Modify |
| `qsforge.spec` | Add hidden imports for trimesh + pycollada | Modify |
| `src/_version.py` | Bump `QSFORGE_VERSION` to `1.0.1` | Modify |
| `src/module3_3d_preview.py` | Add `_convert_dae_to_glb()`, extend `run()` return shape | Modify |
| `src/cache.py` | Bump `SCHEMA_VERSION` to 2; track `.glb` artefact | Modify |
| `src/server.py` | `/api/3d/<job_id>` serves GLB with `model/gltf-binary` | Modify |
| `static/js/viewer3d.js` | Replace `ColladaLoader` with `GLTFLoader`; remove Z-up hack | Modify |
| `static/vendor/three/GLTFLoader.js` | Vendored three.js GLTFLoader | Create |
| `static/vendor/three/ColladaLoader.js` | Removed (no fallback path retained) | Delete |
| `tests/test_module3.py` | Update existing tests for new return shape | Modify |
| `tests/test_module3_dae_to_glb.py` | New TDD tests for converter | Create |
| `tests/fixtures/tiny_with_geom.dae` | Minimal DAE with real cube vertices | Create |
| `tests/test_cache.py` | Update for schema v2 + glb_path | Modify |
| `manifest.json` | Update 1.0.1 metadata (post-build) | Modify |

---

## Pre-flight: confirm workspace

- [ ] **Step 0.1: Confirm current branch + clean working tree**

Run:
```bash
git -C "C:/Archiqs/RVT Quality Check" status
git -C "C:/Archiqs/RVT Quality Check" log --oneline -5
```
Expected: clean working tree, HEAD at the spec-commit `docs(spec): viewer DAE→GLB migration design for 1.0.1`.

- [ ] **Step 0.2: Confirm tests baseline is green on 1.0.0 code**

Run:
```bash
python -m pytest "C:/Archiqs/RVT Quality Check/tests" -q
```
Expected: all tests pass. If anything is already failing, stop and report — those are not our problem to fix in this plan.

---

## Task 1: Add `trimesh` dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1.1: Append trimesh to requirements.txt**

Add this line at the end of the file (before any trailing blank lines):
```
trimesh>=4.0,<5.0
```

- [ ] **Step 1.2: Install into dev venv**

Run (from project root, with the dev venv activated):
```bash
pip install -r requirements.txt
```
Expected: `trimesh-4.x.x` and its dependency `pycollada` install successfully.

- [ ] **Step 1.3: Verify import works**

Run:
```bash
python -c "import trimesh; print(trimesh.__version__)"
python -c "import trimesh; s = trimesh.Scene(); s.add_geometry(trimesh.creation.box()); print('GLB bytes:', len(s.export(file_type='glb')))"
```
Expected: version prints (e.g. `4.5.2`); GLB bytes count is non-zero (e.g. ~1500).

- [ ] **Step 1.4: Commit**

```bash
git -C "C:/Archiqs/RVT Quality Check" add requirements.txt
git -C "C:/Archiqs/RVT Quality Check" commit -m "deps: add trimesh for DAE→GLB conversion"
```

---

## Task 2: Create test fixture with real geometry

**Why:** `tests/fixtures/tiny.dae` has empty `<vertices>` and a dangling `<instance_geometry url="#g1"/>`. trimesh will not produce a meaningful GLB from it. We need a small fixture with real, well-formed COLLADA geometry so conversion tests can verify both byte output and element-ID preservation.

**Files:**
- Create: `tests/fixtures/tiny_with_geom.dae`

- [ ] **Step 2.1: Write a minimal COLLADA file with a real cube and three numeric-named nodes**

Create `tests/fixtures/tiny_with_geom.dae` with this exact content:

```xml
<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
  <asset>
    <created>2026-05-15T00:00:00</created>
    <modified>2026-05-15T00:00:00</modified>
    <unit name="meter" meter="1"/>
    <up_axis>Z_UP</up_axis>
  </asset>
  <library_geometries>
    <geometry id="cube_geom" name="cube">
      <mesh>
        <source id="cube_pos">
          <float_array id="cube_pos_arr" count="24">
            0 0 0  1 0 0  1 1 0  0 1 0  0 0 1  1 0 1  1 1 1  0 1 1
          </float_array>
          <technique_common>
            <accessor source="#cube_pos_arr" count="8" stride="3">
              <param name="X" type="float"/>
              <param name="Y" type="float"/>
              <param name="Z" type="float"/>
            </accessor>
          </technique_common>
        </source>
        <vertices id="cube_vtx">
          <input semantic="POSITION" source="#cube_pos"/>
        </vertices>
        <triangles count="12">
          <input semantic="VERTEX" source="#cube_vtx" offset="0"/>
          <p>0 1 2  0 2 3  4 5 6  4 6 7  0 1 5  0 5 4  2 3 7  2 7 6  1 2 6  1 6 5  0 3 7  0 7 4</p>
        </triangles>
      </mesh>
    </geometry>
  </library_geometries>
  <library_visual_scenes>
    <visual_scene id="scene">
      <node id="element_1890568" name="1890568" type="NODE"><instance_geometry url="#cube_geom"/></node>
      <node id="element_1890569" name="1890569" type="NODE"><instance_geometry url="#cube_geom"/></node>
      <node id="element_1890570" name="1890570" type="NODE"><instance_geometry url="#cube_geom"/></node>
    </visual_scene>
  </library_visual_scenes>
  <scene><instance_visual_scene url="#scene"/></scene>
</COLLADA>
```

- [ ] **Step 2.2: Verify trimesh can load and export it**

Run:
```bash
python -c "import trimesh; s = trimesh.load(r'C:\Archiqs\RVT Quality Check\tests\fixtures\tiny_with_geom.dae', force='scene'); print('geometries:', list(s.geometry.keys())); print('GLB bytes:', len(s.export(file_type='glb')))"
```
Expected: prints at least one geometry key and GLB bytes > 0. If this fails, the fixture is malformed — fix it before continuing.

- [ ] **Step 2.3: Commit**

```bash
git -C "C:/Archiqs/RVT Quality Check" add tests/fixtures/tiny_with_geom.dae
git -C "C:/Archiqs/RVT Quality Check" commit -m "test: add minimal DAE fixture with real geometry"
```

---

## Task 3: TDD — `_convert_dae_to_glb` happy path

**Files:**
- Create: `tests/test_module3_dae_to_glb.py`
- Modify: `src/module3_3d_preview.py`

- [ ] **Step 3.1: Write failing test for basic conversion**

Create `tests/test_module3_dae_to_glb.py` with:

```python
"""Tests for the DAE→GLB conversion path added in 1.0.1."""
from __future__ import annotations

from pathlib import Path

import pytest

import module3_3d_preview as m3


def test_convert_dae_to_glb_produces_a_file(fixtures_dir, tmp_path):
    """A valid DAE converts to a non-empty GLB on disk."""
    src = fixtures_dir / "tiny_with_geom.dae"
    # Copy into tmp_path so we don't pollute the fixtures dir with .glb output.
    dae = tmp_path / "tiny_with_geom.dae"
    dae.write_bytes(src.read_bytes())

    glb = m3._convert_dae_to_glb(dae)

    assert glb.is_file()
    assert glb.suffix == ".glb"
    assert glb.stat().st_size > 0
    # GLB binary format starts with the magic "glTF" (0x46546C67 little-endian).
    assert glb.read_bytes()[:4] == b"glTF"
```

- [ ] **Step 3.2: Run the test and confirm it fails**

Run:
```bash
python -m pytest "C:/Archiqs/RVT Quality Check/tests/test_module3_dae_to_glb.py::test_convert_dae_to_glb_produces_a_file" -v
```
Expected: FAIL with `AttributeError: module 'module3_3d_preview' has no attribute '_convert_dae_to_glb'`.

- [ ] **Step 3.3: Add the helper to `src/module3_3d_preview.py`**

At the top of `src/module3_3d_preview.py`, add after the existing `from __future__ import` line:

```python
import logging

_log = logging.getLogger("qsforge.module3")
```

Add a new exception class near the top (after the imports, before `_NS`):

```python
class Module3ConversionError(RuntimeError):
    """Raised when DAE→GLB conversion fails. Caught by ``run()``."""
```

Add the converter function at the bottom of the file:

```python
def _convert_dae_to_glb(dae_path: Path) -> Path:
    """Convert ``dae_path`` to GLB next to the source. Returns the GLB path.

    Imports trimesh lazily so the module remains importable even if trimesh
    is missing (CI without the dep, dev sandbox, etc.). The frozen EXE always
    has trimesh bundled — see qsforge.spec hidden imports.

    Raises Module3ConversionError on any conversion failure with the
    underlying exception message attached.
    """
    glb_path = dae_path.with_suffix(".glb")
    try:
        import trimesh  # local import to avoid hard dep at module load
    except ImportError as e:
        raise Module3ConversionError(
            f"trimesh not available — DAE→GLB conversion impossible: {e}"
        ) from e

    try:
        scene = trimesh.load(str(dae_path), force="scene")
    except Exception as e:
        raise Module3ConversionError(
            f"trimesh failed to load DAE {dae_path.name}: {e}"
        ) from e

    try:
        glb_bytes = scene.export(file_type="glb")
    except Exception as e:
        raise Module3ConversionError(
            f"trimesh failed to export GLB for {dae_path.name}: {e}"
        ) from e

    if not glb_bytes:
        raise Module3ConversionError(
            f"trimesh produced an empty GLB for {dae_path.name}"
        )

    try:
        glb_path.write_bytes(glb_bytes)
    except OSError as e:
        raise Module3ConversionError(
            f"Could not write GLB to {glb_path}: {e}"
        ) from e

    return glb_path
```

- [ ] **Step 3.4: Run the test and confirm it passes**

Run:
```bash
python -m pytest "C:/Archiqs/RVT Quality Check/tests/test_module3_dae_to_glb.py::test_convert_dae_to_glb_produces_a_file" -v
```
Expected: PASS.

- [ ] **Step 3.5: Commit**

```bash
git -C "C:/Archiqs/RVT Quality Check" add src/module3_3d_preview.py tests/test_module3_dae_to_glb.py
git -C "C:/Archiqs/RVT Quality Check" commit -m "feat(module3): add _convert_dae_to_glb helper (trimesh)"
```

---

## Task 4: TDD — Element ID preservation through GLB

**Why:** The viewer's pick logic depends on element IDs surviving the conversion. The DAE has `<node name="1890568">`; we need `Object3D.name == "1890568"` after `GLTFLoader.load()`. Test the property at the trimesh→GLB level: re-parse the GLB and confirm node names match.

**Files:**
- Modify: `tests/test_module3_dae_to_glb.py`

- [ ] **Step 4.1: Write failing test**

Append to `tests/test_module3_dae_to_glb.py`:

```python
def test_convert_preserves_element_id_node_names(fixtures_dir, tmp_path):
    """Numeric node names in the DAE must survive into the GLB scene graph."""
    import trimesh

    src = fixtures_dir / "tiny_with_geom.dae"
    dae = tmp_path / "tiny_with_geom.dae"
    dae.write_bytes(src.read_bytes())

    glb = m3._convert_dae_to_glb(dae)

    # Re-parse the GLB and collect every named node/geometry in the scene.
    reloaded = trimesh.load(str(glb), force="scene")
    names = set()
    # In trimesh's Scene model, geometry names and graph node names both
    # surface as keys/labels. Collect both to be format-tolerant.
    names.update(reloaded.geometry.keys())
    if hasattr(reloaded, "graph"):
        names.update(reloaded.graph.nodes)

    expected_ids = {"1890568", "1890569", "1890570"}
    matched = expected_ids & names
    assert matched, (
        f"None of the expected element IDs {expected_ids} survived. "
        f"GLB names: {sorted(names)}"
    )
```

- [ ] **Step 4.2: Run the test**

Run:
```bash
python -m pytest "C:/Archiqs/RVT Quality Check/tests/test_module3_dae_to_glb.py::test_convert_preserves_element_id_node_names" -v
```

There are two outcomes:

**(a) PASS:** trimesh preserves the names natively — continue to Step 4.4.

**(b) FAIL:** trimesh stripped or renamed the IDs. In this case proceed to Step 4.3.

- [ ] **Step 4.3: (only if 4.2 failed) Implement explicit node-name preservation**

If trimesh strips names, we name geometries/nodes ourselves before export. Modify `_convert_dae_to_glb` in `src/module3_3d_preview.py` — replace the `scene.export(...)` call section with:

```python
    # Walk the DAE one more time with ElementTree to recover the numeric
    # node names trimesh dropped, then re-tag scene geometries by index.
    try:
        import xml.etree.ElementTree as _ET
        _ns = {"c": "http://www.collada.org/2005/11/COLLADASchema"}
        tree = _ET.parse(str(dae_path))
        dae_node_names = [
            (n.get("name") or "").strip()
            for n in tree.getroot().findall(".//c:visual_scene//c:node", _ns)
        ]
        # Bind names back into scene.graph if possible.
        geom_keys = list(scene.geometry.keys())
        renames = {}
        for idx, key in enumerate(geom_keys):
            if idx < len(dae_node_names) and dae_node_names[idx]:
                renames[key] = dae_node_names[idx]
        # trimesh.Scene exposes .geometry as a dict — rename keys.
        for old, new in renames.items():
            scene.geometry[new] = scene.geometry.pop(old)
    except Exception as e:
        _log.warning("Could not re-bind DAE node names onto GLB: %s", e)

    try:
        glb_bytes = scene.export(file_type="glb")
```

Re-run Step 4.2 to confirm green.

- [ ] **Step 4.4: Commit**

```bash
git -C "C:/Archiqs/RVT Quality Check" add src/module3_3d_preview.py tests/test_module3_dae_to_glb.py
git -C "C:/Archiqs/RVT Quality Check" commit -m "feat(module3): preserve element-ID node names through GLB conversion"
```

---

## Task 5: TDD — Corrupt DAE handling

**Files:**
- Modify: `tests/test_module3_dae_to_glb.py`

- [ ] **Step 5.1: Write failing test**

Append to `tests/test_module3_dae_to_glb.py`:

```python
def test_convert_raises_module3_conversion_error_on_garbage(tmp_path):
    """A non-XML file must raise Module3ConversionError, not a generic Exception."""
    dae = tmp_path / "garbage.dae"
    dae.write_bytes(b"this is not COLLADA at all")
    with pytest.raises(m3.Module3ConversionError):
        m3._convert_dae_to_glb(dae)


def test_convert_raises_on_missing_file(tmp_path):
    """A missing input file must raise Module3ConversionError."""
    dae = tmp_path / "does_not_exist.dae"
    with pytest.raises(m3.Module3ConversionError):
        m3._convert_dae_to_glb(dae)
```

- [ ] **Step 5.2: Run tests**

Run:
```bash
python -m pytest "C:/Archiqs/RVT Quality Check/tests/test_module3_dae_to_glb.py" -v
```
Expected: both new tests PASS — the `try/except` blocks already raise `Module3ConversionError`. If trimesh raises before the load wrapper (e.g. `FileNotFoundError` from disk read), the wrapper still catches it.

If `test_convert_raises_on_missing_file` fails because trimesh raises `OSError`/`FileNotFoundError` that escapes the broad `except Exception` — that means there's a code path before `trimesh.load`. Add an explicit existence check before the `import trimesh` block:

```python
    if not dae_path.is_file():
        raise Module3ConversionError(f"DAE not found: {dae_path}")
```

- [ ] **Step 5.3: Commit**

```bash
git -C "C:/Archiqs/RVT Quality Check" add src/module3_3d_preview.py tests/test_module3_dae_to_glb.py
git -C "C:/Archiqs/RVT Quality Check" commit -m "test(module3): cover DAE→GLB error paths"
```

---

## Task 6: Extend `module3_3d_preview.run()` to produce GLB

**Files:**
- Modify: `src/module3_3d_preview.py`
- Modify: `tests/test_module3.py`

- [ ] **Step 6.1: Update `_empty_result` to include `glb_path`**

In `src/module3_3d_preview.py`, replace the existing `_empty_result` function with:

```python
def _empty_result(warning: str) -> Dict[str, Any]:
    """Helper: result dict for the "3D not available" path."""
    return {
        "dae_path": None,
        "glb_path": None,
        "element_count": 0,
        "has_element_ids": False,
        "file_size_bytes": 0,
        "warnings": [warning],
    }
```

- [ ] **Step 6.2: Update `run()` to call the converter**

In `src/module3_3d_preview.py`, modify the final `return` block inside the happy path (currently lines ~134–140) to read:

```python
        # All validation passed — now convert to GLB so the viewer has a
        # GLTFLoader-friendly file. We do this last so that any conversion
        # failure surfaces as a warning but does NOT discard the validation
        # we just did against the DAE.
        glb_path_str: str | None = None
        try:
            glb_path = _convert_dae_to_glb(p)
            glb_path_str = str(glb_path.resolve())
        except Module3ConversionError as e:
            warnings.append(f"3D preview unavailable: {e}")
            # Return with glb_path=None so the viewer hides the tab.
            return {
                "dae_path": str(p.resolve()),
                "glb_path": None,
                "element_count": element_count,
                "has_element_ids": has_element_ids,
                "file_size_bytes": file_size_bytes,
                "warnings": warnings,
            }

        return {
            "dae_path": str(p.resolve()),
            "glb_path": glb_path_str,
            "element_count": element_count,
            "has_element_ids": has_element_ids,
            "file_size_bytes": file_size_bytes,
            "warnings": warnings,
        }
```

Also update the "zero nodes" early-return block to include `glb_path: None`:

```python
        if element_count == 0:
            return {
                "dae_path": str(p.resolve()),
                "glb_path": None,
                "element_count": 0,
                "has_element_ids": False,
                "file_size_bytes": file_size_bytes,
                "warnings": ["DAE contains no <node> elements"],
            }
```

- [ ] **Step 6.3: Update existing module3 tests for the new shape**

In `tests/test_module3.py`, modify `test_run_returns_dict_with_expected_keys` to also assert `glb_path`:

```python
def test_run_returns_dict_with_expected_keys(fixtures_dir):
    result = m3.run(str(fixtures_dir / "tiny.dae"))
    assert isinstance(result, dict)
    assert "dae_path" in result
    assert "glb_path" in result
    assert "element_count" in result
    assert "has_element_ids" in result
    assert "warnings" in result
```

In the same file, modify `test_run_handles_missing_file_gracefully` and `test_run_handles_malformed_dae_gracefully` to additionally assert `result["glb_path"] is None`.

- [ ] **Step 6.4: Add new integration test for `run()` producing a GLB**

Append to `tests/test_module3.py`:

```python
def test_run_produces_glb_for_valid_dae(fixtures_dir, tmp_path):
    """End-to-end: run() should validate AND convert."""
    src = fixtures_dir / "tiny_with_geom.dae"
    dae = tmp_path / "tiny_with_geom.dae"
    dae.write_bytes(src.read_bytes())
    result = m3.run(str(dae))
    assert result["glb_path"] is not None
    assert Path(result["glb_path"]).is_file()
    assert Path(result["glb_path"]).read_bytes()[:4] == b"glTF"
```

- [ ] **Step 6.5: Run the full module3 test suite**

Run:
```bash
python -m pytest "C:/Archiqs/RVT Quality Check/tests/test_module3.py" "C:/Archiqs/RVT Quality Check/tests/test_module3_dae_to_glb.py" -v
```
Expected: all tests pass. Note: `test_run_counts_elements_correctly` against the old `tiny.dae` (which has empty `<vertices>`) may now also produce a GLB during run() — that's fine; trimesh will load an empty scene and produce a tiny GLB header, but if trimesh raises, the `run()` warning path catches it and the test still passes (element_count is unaffected).

If `test_run_counts_elements_correctly` starts FAILING because trimesh raises on the empty `tiny.dae` and the warning gets pushed — that's OK behaviour-wise but verify by inspecting the warnings list. The element_count assertion (== 5) should still hold because conversion runs AFTER counting.

- [ ] **Step 6.6: Commit**

```bash
git -C "C:/Archiqs/RVT Quality Check" add src/module3_3d_preview.py tests/test_module3.py
git -C "C:/Archiqs/RVT Quality Check" commit -m "feat(module3): run() now returns glb_path alongside dae_path"
```

---

## Task 7: Cache schema bump (v1 → v2) + track GLB

**Files:**
- Modify: `src/cache.py`
- Modify: `tests/test_cache.py`

- [ ] **Step 7.1: Bump schema version and extend `CacheHit` + JSON**

In `src/cache.py`:

1. Change `SCHEMA_VERSION = 1` → `SCHEMA_VERSION = 2`.
2. Add `glb_path: Optional[Path] = None` to the `CacheHit` dataclass:

```python
@dataclass(frozen=True)
class CacheHit:
    xlsx_path: Path
    dae_path: Optional[Path]
    glb_path: Optional[Path]
    ddc_mode: str
    ddc_version: str
    qsforge_version: str
    created_at: str
```

3. In `lookup()`, after the existing `dae_path` check, add:

```python
    glb_str = data.get("glb_path", "")
    glb_path = Path(glb_str) if glb_str else None
    if glb_path is not None and not glb_path.is_file():
        return None
```

And include `glb_path=glb_path` in the `CacheHit(...)` constructor at the end of `lookup()`.

4. Update `store()` to optionally accept and persist `glb_path`. Change the signature to:

```python
def store(rvt_path: str, ddc_mode: str,
          xlsx_path: str, dae_path: str,
          glb_path: str | None = None) -> None:
```

After the `shutil.copy2(src_dae, dst_dae)` line, add:

```python
        dst_glb_str = ""
        if glb_path:
            src_glb = Path(glb_path)
            if src_glb.is_file():
                dst_glb = cache_dir / f"{base}_{ddc_mode}.glb"
                shutil.copy2(src_glb, dst_glb)
                dst_glb_str = str(dst_glb)
```

In the JSON dict literal inside `store()`, add `"glb_path": dst_glb_str,`.

5. In `store_xlsx_only()`, also add `"glb_path": "",` to the JSON dict.

6. In `invalidate()`, extend the loop's suffix tuple to include `.glb`:

```python
    for suffix in (".xlsx", ".dae", ".glb", ".cache.json", ".result.json"):
```

- [ ] **Step 7.2: Update cache tests**

Open `tests/test_cache.py` and:

1. Wherever a test calls `cache.lookup(...)` and asserts on `hit.xlsx_path` / `hit.dae_path`, add `assert hit.glb_path is None` for entries stored without a GLB.
2. Add one new test exercising the GLB cache round-trip:

```python
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
```

3. Add a test that confirms v1 caches are invalidated:

```python
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
```

- [ ] **Step 7.3: Run cache tests**

Run:
```bash
python -m pytest "C:/Archiqs/RVT Quality Check/tests/test_cache.py" -v
```
Expected: all tests pass.

- [ ] **Step 7.4: Commit**

```bash
git -C "C:/Archiqs/RVT Quality Check" add src/cache.py tests/test_cache.py
git -C "C:/Archiqs/RVT Quality Check" commit -m "feat(cache): bump schema to v2; track glb_path artefact"
```

---

## Task 8: Wire GLB through `server.py`

**Files:**
- Modify: `src/server.py`

- [ ] **Step 8.1: Update the cache-hit path to include GLB**

In `src/server.py`, find the cache-hit handler inside the analyze worker (the block that runs when `cache.lookup(...)` returns a hit). Update it so that if `hit.glb_path` is set, the module3 result includes it. Locate the block similar to:

```python
data["module3"] = module3_3d_preview.run(str(hit.dae_path))
```

The function-internal change to `run()` already populates `glb_path` — no further code change required here as long as `run()` is called with the DAE path. But verify the cache-hit branch passes `hit.dae_path` (not `hit.glb_path`) — `run()` does the conversion itself.

If there is any code path that previously skipped Module 3 on cache hit and short-circuited to `data["module3"] = {"dae_path": ..., ...}` with a hand-built dict, replace it with a fresh `module3_3d_preview.run(str(hit.dae_path))` call. (The first conversion is cached on disk; re-running `run()` re-reads the existing `.glb` next to the DAE — trimesh re-converts each time, ~1s for typical models, acceptable.)

- [ ] **Step 8.2: Update `store()` callsite to persist the GLB**

After the analyze worker writes a successful result with a `data["module3"]["glb_path"]`, ensure the cache store call passes it. Find the line:

```python
cache.store(job.rvt_path, job.mode, xlsx_path, str(dae_p))
```

Change to:

```python
glb_p = data.get("module3", {}).get("glb_path") or None
cache.store(job.rvt_path, job.mode, xlsx_path, str(dae_p), glb_path=glb_p)
```

- [ ] **Step 8.3: Update `/api/3d/<job_id>` to stream the GLB**

In `src/server.py`, replace the `stream_dae` function with:

```python
@app.get("/api/3d/<job_id>")
def stream_3d(job_id: str):
    """Stream the .glb bytes for a finished job to the browser.

    Why GLB (not DAE) since 1.0.1: three.js's ColladaLoader proved unreliable
    on real-world architectural Revit exports. We now convert DAE→GLB at
    analysis time (see module3_3d_preview._convert_dae_to_glb) and serve the
    GLB to GLTFLoader.

    Why a streaming endpoint and not a base64-blob in the JSON: a typical
    architectural .glb is 15–80 MB. Stuffing that into last_result.json
    would balloon JSON parsing time on the frontend AND blow our SSE event
    pipeline. HTTP streaming with the right Content-Type is the right
    channel for binary geometry.
    """
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None and job_id == "current":
            done_jobs = [j for j in _jobs.values() if j.state == "done"]
            if done_jobs:
                job = max(done_jobs, key=lambda j: j.started_at or 0)
    if job is None or job.state != "done" or not job.result:
        abort(404, description="Job not found or not finished")
    m3 = (job.result or {}).get("module3") or {}
    glb_path = m3.get("glb_path")
    if not glb_path:
        abort(404, description="No 3D preview available for this job")
    return send_file(glb_path, mimetype="model/gltf-binary",
                     as_attachment=False, conditional=True)
```

- [ ] **Step 8.4: Smoke test the endpoint via the test client (if integration test exists), otherwise manual launch**

If `tests/test_server.py` exists with a Flask test client fixture, run:
```bash
python -m pytest "C:/Archiqs/RVT Quality Check/tests/test_server.py" -v
```
Expected: existing tests still pass.

If no server tests exist, defer the smoke test to Task 12 (manual acceptance).

- [ ] **Step 8.5: Commit**

```bash
git -C "C:/Archiqs/RVT Quality Check" add src/server.py
git -C "C:/Archiqs/RVT Quality Check" commit -m "feat(server): stream GLB from /api/3d with model/gltf-binary MIME"
```

---

## Task 9: Vendor `GLTFLoader.js`, remove `ColladaLoader.js`

**Files:**
- Create: `static/vendor/three/GLTFLoader.js`
- Delete: `static/vendor/three/ColladaLoader.js`

- [ ] **Step 9.1: Check the current three.js version**

Run:
```bash
python -c "p = open(r'C:\Archiqs\RVT Quality Check\static\vendor\three\three.module.min.js', encoding='utf-8', errors='ignore').read(); import re; m = re.search(r'(?:REVISION|VERSION)[^a-z0-9]*([0-9]+(?:\.[0-9]+)?)', p); print(m.group(0) if m else 'no version string found')"
```
Note the three.js revision number (e.g. `r158`).

- [ ] **Step 9.2: Download the matching GLTFLoader.js**

Download GLTFLoader.js from `https://unpkg.com/three@0.<REV>.0/examples/jsm/loaders/GLTFLoader.js` matching the revision discovered in 9.1. Save to `static/vendor/three/GLTFLoader.js`.

PowerShell command (substitute `<REV>` with actual revision):
```powershell
Invoke-WebRequest -Uri "https://unpkg.com/three@0.<REV>.0/examples/jsm/loaders/GLTFLoader.js" -OutFile "C:\Archiqs\RVT Quality Check\static\vendor\three\GLTFLoader.js"
```

Verify the import line in the downloaded file references `three.module.min.js` or `three.module.js` — if it imports from `"three"` (bare specifier), edit it to import from `'/static/vendor/three/three.module.min.js'` to match the existing vendored module style:

```js
// Change:
import { ... } from 'three';
// To:
import { ... } from '/static/vendor/three/three.module.min.js';
```

- [ ] **Step 9.3: Delete the ColladaLoader**

Run:
```powershell
Remove-Item "C:\Archiqs\RVT Quality Check\static\vendor\three\ColladaLoader.js"
```

- [ ] **Step 9.4: Commit**

```bash
git -C "C:/Archiqs/RVT Quality Check" add static/vendor/three/GLTFLoader.js
git -C "C:/Archiqs/RVT Quality Check" rm static/vendor/three/ColladaLoader.js
git -C "C:/Archiqs/RVT Quality Check" commit -m "chore(viewer): vendor GLTFLoader.js; remove ColladaLoader.js"
```

---

## Task 10: Rewrite `viewer3d.js` for GLTFLoader

**Files:**
- Modify: `static/js/viewer3d.js`

- [ ] **Step 10.1: Swap the import**

In `static/js/viewer3d.js`, replace line 28:

```js
import { ColladaLoader } from '/static/vendor/three/ColladaLoader.js';
```

With:

```js
import { GLTFLoader } from '/static/vendor/three/GLTFLoader.js';
```

- [ ] **Step 10.2: Replace the `load()` method**

In `static/js/viewer3d.js`, replace the entire `async load(daeUrl, resultData) { ... }` method (currently starting around line 368) with:

```js
async load(glbUrl, resultData) {
  const loader = new GLTFLoader();
  return new Promise((resolve, reject) => {
    loader.load(
      glbUrl,
      (gltf) => {
        try {
          // glTF is Y-up by spec — no Z-up→Y-up rewrite needed.
          this.modelGroup.add(gltf.scene);
          this.modelGroup.updateMatrixWorld(true);

          // DIAGNOSTIC PASS: count what's in the scene, then force every
          // renderable into a lighting-independent bright material so the
          // model is visible even when normals are degenerate.
          const counts = { Mesh: 0, Line: 0, LineSegments: 0, Points: 0, Group: 0, other: 0 };
          this.modelGroup.traverse((obj) => {
            if (obj.isMesh) counts.Mesh++;
            else if (obj.isLineSegments) counts.LineSegments++;
            else if (obj.isLine) counts.Line++;
            else if (obj.isPoints) counts.Points++;
            else if (obj.isGroup) counts.Group++;
            else counts.other++;

            if (obj.isMesh && obj.material) {
              obj.material = DEFAULT_MATERIAL.clone();
            }
          });
          console.log('[Viewer3D] scene counts:', counts);

          // Build the element-ID → mesh index. With GLTFLoader, each
          // glTF node's `name` becomes Object3D.name. trimesh writes the
          // Revit element ID into node.name (via the conversion pipeline).
          this._indexMeshesByElementId(this.modelGroup);

          // Apply severities from the result payload.
          this._applySeverities(resultData);

          // Zoom to fit and start rendering.
          this._zoomToFit();
          this._render();
          resolve();
        } catch (err) {
          reject(err);
        }
      },
      (progress) => {
        // Optional: progress callback. Loader sends loaded/total bytes.
      },
      (err) => {
        console.error('[Viewer3D] GLTFLoader error:', err);
        reject(err);
      }
    );
  });
}

_indexMeshesByElementId(root) {
  this.elementMap = {};
  root.traverse((obj) => {
    if (!obj.isMesh) return;
    const name = (obj.name || '').trim();
    if (/^\d+$/.test(name)) {
      this.elementMap[name] = {
        mesh: obj,
        originalMaterial: obj.material,
      };
    } else if (obj.parent && /^\d+$/.test((obj.parent.name || '').trim())) {
      // Some glTF exporters wrap meshes in a parent node carrying the name.
      const pname = obj.parent.name.trim();
      this.elementMap[pname] = this.elementMap[pname] || {
        mesh: obj,
        originalMaterial: obj.material,
      };
    }
  });
}
```

**Note:** if `_applySeverities`, `_zoomToFit`, and `_render` are not already separate methods in the file, leave the existing inline logic from the old `load()` in place inside the new `load()` between the `_indexMeshesByElementId` call and the `resolve()` — the goal of this task is the loader swap, not refactoring unrelated method extraction.

- [ ] **Step 10.3: Update the comment header**

Replace the JSDoc block at the top of `static/js/viewer3d.js` (lines 1–26) — change references from "COLLADA" / "DAE" / "ColladaLoader" to "glTF" / "GLB" / "GLTFLoader". The behavior section about element ID join should now read:

```
 * Element ID join
 * ---------------
 *   DAE <node name="1890568">  →  trimesh GLB node.name = "1890568"
 *                              →  GLTFLoader Object3D.name = "1890568"
 *   We walk the loaded scene once and build:
 *     this.elementMap = { "1890568": { mesh, originalMaterial }, ... }
```

- [ ] **Step 10.4: Update any caller of `load()` that passes a `.dae` URL**

Run:
```bash
git -C "C:/Archiqs/RVT Quality Check" grep -n "daeUrl\|/api/3d/" static/
```

Each callsite that constructs a `daeUrl` (e.g. in `static/index.html` or `static/js/app.js`) needs the variable renamed to `glbUrl`. The URL itself is unchanged — `/api/3d/<job_id>` now serves GLB.

For each match, rename the local variable from `daeUrl` to `glbUrl` (or similar) for clarity. No functional change beyond readability.

- [ ] **Step 10.5: Manual smoke test against the small fixture**

Run the dev server:
```bash
cd "C:/Archiqs/RVT Quality Check"
python main.py
```

In the running app:
1. Open a Revit file you have on hand (or skip to Task 12 for full acceptance test)
2. Navigate to the 3D Preview tab after analysis completes
3. Confirm: the model renders, click-picking returns a numeric element ID, severity highlights apply

If the model is invisible, check browser devtools console for GLTFLoader errors and the `[Viewer3D] scene counts:` log line — Mesh count > 0 means geometry loaded; if 0, the conversion or scene-add step needs debugging.

- [ ] **Step 10.6: Commit**

```bash
git -C "C:/Archiqs/RVT Quality Check" add static/js/viewer3d.js static/
git -C "C:/Archiqs/RVT Quality Check" commit -m "feat(viewer): swap ColladaLoader for GLTFLoader; drop Z-up rewrite"
```

---

## Task 11: PyInstaller hidden imports + version bump

**Files:**
- Modify: `qsforge.spec`
- Modify: `src/_version.py`

- [ ] **Step 11.1: Add hidden imports to qsforge.spec**

Open `qsforge.spec` and find the `hiddenimports=[...]` list inside the `Analysis(...)` call. Add these strings:

```python
    'trimesh',
    'trimesh.exchange',
    'trimesh.exchange.gltf',
    'trimesh.exchange.dae',
    'pycollada',
```

- [ ] **Step 11.2: Bump version**

In `src/_version.py`, change:
```python
QSFORGE_VERSION = "1.0.0"
```
to:
```python
QSFORGE_VERSION = "1.0.1"
```

- [ ] **Step 11.3: Commit**

```bash
git -C "C:/Archiqs/RVT Quality Check" add qsforge.spec src/_version.py
git -C "C:/Archiqs/RVT Quality Check" commit -m "chore(build): add trimesh hidden imports; bump to 1.0.1"
```

---

## Task 12: Manual acceptance test against real Revit models

**Files:** none (testing only)

- [ ] **Step 12.1: Identify 3–5 Revit models that failed to render in 1.0.0**

Gather `.rvt` files the user previously reported as not rendering. Note their paths.

- [ ] **Step 12.2: Run each through the dev server and record result**

For each model, launch:
```bash
cd "C:/Archiqs/RVT Quality Check"
python main.py
```
Drop the .rvt onto QSForge, wait for analysis, open the 3D Preview tab.

Record a table in `docs/superpowers/plans/2026-05-15-viewer-dae-to-glb.md` at the bottom of the file (or scratchpad — does NOT need to be committed):

| Model | Status (1.0.0) | Status (1.0.1) | GLB size | Click-pick works? | Notes |
|---|---|---|---|---|---|
| Model A | Failed | Renders | 18 MB | Yes | — |
| Model B | Failed | Failed (trimesh error) | — | — | "pycollada parse error: ..." |
| ... | | | | | |

- [ ] **Step 12.3: Acceptance gate**

If **≥80%** of the test models render successfully → continue to Task 13.

If **<80%** render → STOP. Open a follow-up task to bundle Khronos `COLLADA2GLTF.exe` as a fallback (out of scope for this plan; gated on this result).

---

## Task 13: Build the installer

**Files:** none (build artefacts only)

- [ ] **Step 13.1: Run build.ps1**

Run:
```powershell
powershell.exe -ExecutionPolicy Bypass -File "C:\Archiqs\RVT Quality Check\build.ps1"
```
Expected: produces `installer/output/QSForge-Setup-1.0.1.exe`.

- [ ] **Step 13.2: Smoke test the installed build**

Install `QSForge-Setup-1.0.1.exe` (per-user install, no admin needed). Launch QSForge from the Start Menu. Run one of the test models that succeeded in Task 12. Confirm 3D preview renders.

If the frozen build fails to render where the dev build worked: the most likely cause is a missing hidden import — check the `qsforge_crash.log` next to the EXE and add any reported missing modules to `qsforge.spec` then rebuild.

- [ ] **Step 13.3: Compute SHA-256 of the installer**

Run:
```powershell
Get-FileHash "C:\Archiqs\RVT Quality Check\installer\output\QSForge-Setup-1.0.1.exe" -Algorithm SHA256
```
Record the hash for use in Step 14.

- [ ] **Step 13.4: Get installer size in bytes**

Run:
```powershell
(Get-Item "C:\Archiqs\RVT Quality Check\installer\output\QSForge-Setup-1.0.1.exe").Length
```
Record the byte count for use in Step 14.

---

## Task 14: Update manifest.json + draft release notes

**Files:**
- Modify: `manifest.json`

- [ ] **Step 14.1: Update manifest.json**

Open `manifest.json` and update the `qsforge` block:

```json
{
  "qsforge": {
    "version": "1.0.1",
    "released_at": "<TODAY's date in YYYY-MM-DD>",
    "installer_url": "https://github.com/liyq0610123-star/qsforge/releases/download/v1.0.1/QSForge-Setup-1.0.1.exe",
    "sha256": "<HASH from Step 13.3>",
    "size_bytes": <BYTES from Step 13.4>,
    "release_notes_url": "https://github.com/liyq0610123-star/qsforge/releases/tag/v1.0.1",
    "release_notes": "Fixes 3D preview compatibility on a much wider range of Revit models. Internal viewer pipeline migrated from COLLADA to glTF (GLTFLoader) for reliability. The DDC export step is unchanged; conversion happens client-side at analysis time."
  },
  "ddc": { ... unchanged ... }
}
```

Leave the `ddc` block unchanged — DDC version bundled in 1.0.1 is the same.

- [ ] **Step 14.2: Commit + tag**

```bash
git -C "C:/Archiqs/RVT Quality Check" add manifest.json
git -C "C:/Archiqs/RVT Quality Check" commit -m "release: QSForge 1.0.1 — viewer DAE→GLB migration"
git -C "C:/Archiqs/RVT Quality Check" tag v1.0.1
```

- [ ] **Step 14.3: Push branch + tag**

```bash
git -C "C:/Archiqs/RVT Quality Check" push origin main
git -C "C:/Archiqs/RVT Quality Check" push origin v1.0.1
```

- [ ] **Step 14.4: Create GitHub Release (manual)**

In the GitHub web UI:
1. Releases → Draft a new release
2. Choose tag: `v1.0.1`
3. Title: `QSForge 1.0.1 — 3D preview reliability`
4. Description (paste):
   ```
   ## What's fixed
   - 3D preview now renders correctly on a much wider range of Revit models.
   - Internal viewer pipeline migrated from COLLADA (DAE) to glTF (GLB), using three.js GLTFLoader for rendering.
   - Conversion happens client-side at analysis time; no change to the DDC export step.

   ## Known limitations
   - Some highly-complex or non-standard Revit models may still fail to convert. In that case, the rest of the QS audit (Modules 0, 1, 2) is unaffected — only the 3D preview tab will show "preview unavailable".
   - Please open an issue with the failing model details if you hit one.

   ## Auto-update
   - 1.0.0 installs will see this update via the existing manifest mechanism.

   SHA-256: `<HASH from Step 13.3>`
   ```
5. Upload `QSForge-Setup-1.0.1.exe` and `manifest.json` as Release assets.
6. Publish.

- [ ] **Step 14.5: Post-publish verification**

Run:
```bash
curl -sI https://github.com/liyq0610123-star/qsforge/releases/latest/download/manifest.json | grep -i "^http\|^content-type"
curl -s https://github.com/liyq0610123-star/qsforge/releases/latest/download/manifest.json | python -c "import sys, json; d = json.load(sys.stdin); print('version=', d['qsforge']['version'])"
```
Expected: HTTP 200 (after a 302 redirect to the asset CDN); `version= 1.0.1`.

---

## Final verification

- [ ] **Step F.1: Full test suite must pass**

Run:
```bash
python -m pytest "C:/Archiqs/RVT Quality Check/tests" -q
```
Expected: all tests pass.

- [ ] **Step F.2: Update project memory**

Append a short note to `C:\Users\11390\.claude\projects\C--Archiqs-RVT-Quality-Check\memory\project_qsforge_rebrand.md` (or create a dedicated `project_qsforge_1_0_1.md` if preferred):

> **1.0.1 shipped 2026-05-XX**: viewer migrated from COLLADA (`ColladaLoader`) to glTF (`GLTFLoader`) via a `trimesh`-based DAE→GLB conversion step. Driven by user reports that most real Revit models failed to render in 1.0.0. Cache schema bumped v1→v2 (auto-invalidates). Code signing (B6) still deferred to a future release.

---

## Out of scope (do NOT do in this plan)

- xeokit migration (1.1.0 candidate, only if GLTFLoader fails too)
- Bundled `COLLADA2GLTF.exe` fallback (only if Task 12 acceptance gate fails)
- IFC native input (separate project)
- Code signing (still deferred to a later release per project memory)
- Deleting the intermediate `.dae` from disk to save space (revisit in 1.0.2)
