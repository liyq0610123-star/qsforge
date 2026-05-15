# QSForge 3D Viewer: DAE → GLB Migration

**Status:** Approved
**Target release:** 1.0.1
**Author:** liyq0610123-star + Claude
**Date:** 2026-05-15

## Problem

The 1.0.0 release ships a three.js–based 3D preview that loads COLLADA (`.dae`)
files produced by DDC RvtExporter. In real-world testing, **most user Revit
models fail to render in the viewer** even though the same `.dae` files open
correctly in Open CASCADE's CAD Assistant. The failure is in three.js's
`ColladaLoader` — a poorly-maintained loader that chokes on complex material
trees, nested transforms, and the polygon counts typical of architectural
Revit exports.

QSForge's value proposition includes the 3D preview as a sanity check on the
quantity audit (Module 3). A viewer that fails on most inputs is worse than
no viewer — it implies the audit itself is unreliable.

## Goal

Replace the failing `ColladaLoader` rendering path with a conversion step
that emits glTF (`.glb`) and renders via three.js's first-class `GLTFLoader`.
Success means: models that render in CAD Assistant also render in QSForge.

## Non-goals

- IFC input pipeline (separate project; planned for 1.1.0+)
- Migration to a different rendering library (xeokit, Babylon, etc.) — reserved
  as fallback if GLTFLoader still fails on a meaningful fraction of inputs
- Material/texture fidelity beyond what Revit exports today (color by category
  is the existing UX and is unchanged)
- Backward compatibility with cached 1.0.0 results (cache schema bump invalidates)

## Architecture

```
DDC run
   ↓ produces  <stem>_rvt.dae       (existing — unchanged)
   ↓
[NEW] module3_3d_preview.run(dae_path)
   ├─ _convert_dae_to_glb()  via trimesh
   ├─ validate GLB
   │     ├─ node count
   │     ├─ element-ID preservation in glTF node names
   │     └─ non-empty geometry
   └─ return {status, glb_path, dae_path, element_count, has_element_ids, errors}
   ↓
server.py
   /api/3d/<job_id>  →  stream GLB
   Content-Type: model/gltf-binary
   ↓
viewer3d.js
   GLTFLoader.load(glbUrl, ...)
   ↓ render in pywebview
```

### Why trimesh

- Pure Python, pip-installable, fits the existing toolchain
- Wraps `pycollada` for DAE input and emits GLB natively
- Preserves node hierarchy and node names — required so element IDs survive
  the conversion (DDC encodes Revit element IDs as DAE node attributes; trimesh
  carries these through to glTF `node.name`)
- glTF spec is Y-up, so the manual Z-up→Y-up scene rewrite in `viewer3d.js`
  becomes unnecessary

### Why not xeokit

- xeokit is the right answer for very large BIM models (>500 MB) and native
  IFC, but neither applies today
- Migration cost is materially higher (different scene API, picking model,
  material system)
- Held in reserve as the 1.1.0 fallback if GLTFLoader proves insufficient

### Why not embed CAD Assistant

- CAD Assistant is a Qt desktop app (~150 MB), not embeddable in pywebview
- Launching it as a subprocess breaks the in-app UX and requires a separate
  install

## Component changes

### `requirements.txt`
- Add `trimesh>=4.0,<5.0`
- `numpy` is already a transitive dependency via pandas; trimesh's other
  optional deps (`scipy`, `networkx`) are not required for DAE→GLB conversion
  and will not be installed unless explicitly requested

### `qsforge.spec` (PyInstaller)
- Add to `hiddenimports`:
  - `trimesh`
  - `trimesh.exchange`
  - `trimesh.exchange.gltf`
  - `trimesh.exchange.dae`
  - `pycollada` (trimesh's DAE backend)

### `src/module3_3d_preview.py`
- New private helper `_convert_dae_to_glb(dae_path: Path) -> Path`
  - Loads the DAE via `trimesh.load(dae_path, force='scene')`
  - Exports to GLB via `scene.export(file_type='glb')` written to
    `<stem>_rvt.glb` next to the DAE
  - Raises `Module3ConversionError` on failure with the underlying exception
    message attached
- `run(dae_path)` now:
  1. Calls `_convert_dae_to_glb()` → produces `<stem>_rvt.glb`
  2. Validates the GLB (parse via trimesh, count nodes, sample node names for
     numeric element-ID pattern)
  3. Returns the existing result shape extended with `glb_path` and replaces
     the legacy `dae_path` consumption in `server.py`
- On conversion failure, returns `{"status": "unavailable", "errors": [...]}`
  with the DAE path retained for debug logging only — viewer is hidden

### `src/cache.py`
- Bump `CACHE_SCHEMA_VERSION` (1 → 2)
- Cached artefacts list includes both `.dae` (existing) and `.glb` (new)
- Existing v1 cache entries are ignored (re-run cost is acceptable; first-run
  experience for repeat models is unaffected once re-cached)

### `src/server.py`
- `/api/3d/<job_id>` endpoint:
  - Reads `module3.glb_path` from the job result
  - `send_file(glb_path, mimetype="model/gltf-binary", as_attachment=False,
    conditional=True)`
  - Route path is unchanged; only the served bytes and MIME differ
- Update progress messages if any reference "COLLADA" or ".dae" loading

### `static/js/viewer3d.js`
- Replace `import { ColladaLoader } ...` with
  `import { GLTFLoader } from '/static/vendor/three/GLTFLoader.js'`
- `load()` becomes:
  ```js
  const loader = new GLTFLoader();
  loader.load(glbUrl, gltf => {
    this.scene.add(gltf.scene);
    this._indexNodesByName(gltf.scene);  // unchanged ID→object map
  }, onProgress, onError);
  ```
- Remove the Z-up→Y-up reparenting block — glTF is Y-up by spec
- Element-ID pick: iterate `gltf.scene` descendants, key the index by
  `object.name` (numeric Revit element ID propagates from glTF node names)
- Update MIME / file-extension references in error messages

### `static/vendor/three/`
- Remove `ColladaLoader.js`
- Add `GLTFLoader.js` from three.js examples at the matching version
- If three.js version pin needs to bump for GLTFLoader compatibility, do that
  as part of this change

## Data flow: element-ID preservation

The critical correctness property: a user clicks a mesh in the viewer and the
UI highlights the corresponding row in the punch list. This depends on the
Revit element ID flowing through:

1. **DDC export**: writes element IDs into DAE `<node id="123456">` attributes
2. **Current code path** (1.0.0): `module3_3d_preview.run()` patches `id` →
   `name` so three.js's `ColladaLoader` preserves them, then exposes via
   `object.name`
3. **New code path** (1.0.1): trimesh reads DAE node IDs as node names during
   import and writes them into glTF `node.name` on export. `GLTFLoader`
   preserves `node.name` on the resulting Three.js `Object3D.name`
4. Viewer indexes meshes by `object.name`, lookup table feeds the click handler

This is verified in the validation step inside `module3_3d_preview.run()` —
if `has_element_ids` is false, the viewer falls back to "no picking" mode
(same fallback as 1.0.0).

## Error handling

| Failure mode | Behavior |
|---|---|
| DDC didn't produce a `.dae` | Existing 1.0.0 behavior — module3 status `unavailable` |
| trimesh raises on import (pycollada parse error) | module3 status `unavailable`, error message logged + surfaced in UI |
| trimesh produces empty GLB | Validation catches it; module3 status `unavailable` |
| GLB has no element-ID-shaped node names | module3 status `ok` but `has_element_ids: false`; viewer renders without picking |
| GLTFLoader fails client-side | Existing error overlay in viewer3d.js shows the error — no fallback to DAE |

No fallback path to `ColladaLoader` is retained. If trimesh fails on a class
of real models, the fix is to bundle the Khronos `COLLADA2GLTF.exe` CLI
(~3 MB) and shell out — adds half a day of work, no design change needed.

## Testing

### Unit tests (`tests/test_module3_3d_preview.py`)
- New: `test_convert_dae_to_glb_produces_glb` — feed a small fixture .dae,
  assert GLB file produced and parseable
- New: `test_convert_dae_to_glb_preserves_element_ids` — assert at least one
  glTF node has a numeric name matching a known fixture element ID
- New: `test_convert_dae_to_glb_handles_corrupt_dae` — feed garbage, assert
  module3 returns `unavailable` status with error message
- Update: existing DAE-validation tests adjust to GLB-validation equivalents

### Integration tests
- Existing job-pipeline test (with the fixture .rvt) must produce a `.glb`
  next to the `.dae` and the `/api/3d/<job_id>` endpoint must return
  `model/gltf-binary` content
- Cache test confirms v1 cache entries are invalidated and re-run produces
  v2 entries containing the `.glb`

### Manual acceptance test
Run QSForge against 3–5 of the .rvt files that failed to render in 1.0.0.
Document for each:
- Did the GLB render? (y/n)
- Did element-ID picking work?
- If still failed, log the trimesh / GLTFLoader error verbatim

Acceptance criterion for 1.0.1 ship: **≥80% of test models render
successfully**. If below 80%, escalate to bundled COLLADA2GLTF before
shipping.

## Build & installer

- `qsforge.spec`: confirm trimesh and pycollada are pulled into the frozen
  EXE (hidden imports above). PyInstaller's `--debug=imports` mode used
  during build verification
- `installer/qsforge.iss`: no changes required — assets path is the same;
  the only delta is which JS file is shipped under `static/vendor/three/`
- Installer size delta: +5–8 MB (trimesh + pycollada Python wheels). Stays
  comfortably under 250 MB total

## Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| trimesh's pycollada backend trips on the same DAEs that crashed ColladaLoader | Medium | Manual acceptance test (above) catches this pre-ship. Fallback: COLLADA2GLTF CLI subprocess |
| Element IDs lost in conversion | Low | Explicit validation step; well-defined trimesh behavior for node names |
| GLTFLoader requires a newer three.js version than currently vendored | Low | Bump three.js vendored version as part of the same change |
| Frozen-EXE missing trimesh submodule | Medium | Hidden imports declared; PyInstaller import audit run pre-release |
| Trimesh exports Y-up but DDC oriented scene differently | Low | Manual test on fixture catches; quick fix is one transform matrix in viewer3d.js |

## Rollout

- Bumps QSForge to **1.0.1**
- Auto-update via existing manifest.json mechanism (downgrade guard from
  H6 is unaffected — 1.0.1 > 1.0.0)
- Release notes call out: "Fixed: 3D preview now works on a much wider range
  of Revit models. Internal viewer pipeline migrated from COLLADA to glTF
  for reliability."

## Out of scope (deferred to later releases)

- xeokit migration (1.1.0 candidate, only if GLTFLoader still fails on
  meaningful fraction of inputs)
- Bundled COLLADA2GLTF CLI (only if trimesh fails acceptance criterion)
- IFC native input (1.1.0 or later)
- Deleting the intermediate `.dae` to save disk (revisit in 1.0.2 once
  trimesh path is proven stable in production)
