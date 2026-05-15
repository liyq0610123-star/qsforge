# ArchiQS — 3D Model Preview (Module 3)

**Status:** Approved design, ready for implementation plan
**Author:** ArchiQS Team
**Date:** 2026-05-08
**Target version:** 1.3.0

## 1. Goal

Add a third tab to the ArchiQS results view — **3D View** — that renders the
analyzed Revit model as a 3D scene and visually overlays Module 1 quality
issues onto the geometry. The 3D viewer is QS-aware: it ties three.js scene
nodes back to the QS data already produced by Modules 0–2.

The feature is **additive**: failures in Module 3 must not break the existing
QS or BIM views.

## 2. Why

A plain 3D viewer is just CADAssistant. The differentiator is *deep
integration* with ArchiQS's QS data — clicking a wall in 3D shows its Element
ID, Family, Type, Volume, and which Module 1 dimensions flagged it. Elements
that failed CRITICAL checks glow red; WARNING checks glow orange; passing
elements stay default-colored. This turns the 3D view into a guided
walk-through of "what's wrong with this model," which is something
no other tool offers QS teams today.

## 3. User stories

- **U1.** As a QS, I open the 3D View and immediately see which walls/floors
  are missing Level data (red) without scrolling through ID lists.
- **U2.** As a BIM lead, I click a red element in the 3D view and see its
  Element ID + Family + Type so I can fix it in Revit.
- **U3.** As a power user re-analyzing the same .rvt to test a fix, the
  second analysis completes in ~1 s instead of ~30 s because the DDC output
  is cached.
- **U4.** As an offline user (corporate / air-gapped), the 3D viewer works
  without an internet connection (three.js is bundled, not CDN-loaded).

## 4. Design decisions (locked)

| # | Decision | Choice |
|---|---|---|
| D1 | Feature scope | Preview + click inspection + Module 1 problem highlighting |
| D2 | Renderer | three.js + ColladaLoader inside the existing WebView2 |
| D3 | Default visualization mode | Color by Module 1 status (red / orange / default) |
| D4 | DAE generation timing | Always generate during analysis (option A) |
| D5 | Cache invalidation | Size + mtime + DDC mode + DDC version (option A); existing `force=True` is the manual escape hatch |

Approaches considered and rejected:

- **Embed CADAssistant binary** — no embedding SDK; no API to programmatically
  highlight Element IDs; ~500 MB installer bloat. Rejected.
- **OCCT / pythonOCC native viewer** — heavy (300+ MB), needs a separate Qt
  window, hard to integrate with PyWebView. Rejected.
- **Lazy DAE generation (only on first 3D View click)** — forces a long wait
  at the moment of curiosity, kills the feature. Rejected.
- **SHA-256 cache key** — bulletproof but hashing a 500 MB .rvt every analysis
  defeats the purpose of caching. Rejected.

## 5. Architecture

```
RVT → [cache check] → DDC (xlsx + dae) → Module 0 → Module 1 → Module 2 → Module 3 → cache write → result
                ↑ if hit, skip DDC entirely, reuse xlsx + dae from disk
```

### 5.1 New modules

- **`src/cache.py`** — module-agnostic cache lookup / store / invalidate.
  Used by `ddc_runner` and `module3_3d_preview`.
  Public API:
  ```python
  def lookup(rvt_path: str, ddc_mode: str) -> CacheHit | None
  def store(rvt_path: str, ddc_mode: str, xlsx_path: str, dae_path: str) -> None
  def invalidate(rvt_path: str, ddc_mode: str) -> None
  ```
- **`src/module3_3d_preview.py`** — thin orchestrator. Confirms DAE exists,
  validates that ≥ 80 % of node names match `^\d+$`, returns:
  ```python
  {
    "dae_path": str,
    "element_count": int,
    "has_element_ids": bool,   # False → 3D works but C/D features disabled
    "warnings": list[str],
  }
  ```

### 5.2 New frontend code

- **`static/js/viewer3d.js`** — `Viewer3D` class encapsulating the three.js
  scene, ColladaLoader, merged-geometry build, raycaster picking, material
  switching, and toolbar wiring. Lazy-instantiated on first 3D tab click.
- **`static/vendor/three/`** — bundled three.js r160 ESM + ColladaLoader +
  BufferGeometryUtils (~700 KB total). No CDN, must work offline.

### 5.3 Modified modules

- **`src/ddc_runner.py`** — pass `dae=True` to RvtExporter args; emit DAE
  path in the result. Add cache check at the top of `run_ddc()` — short-circuit
  if cache hits.
- **`src/server.py`** — after M2, call `module3_3d_preview.run(...)`, attach
  to `data["module3"]`. New route `GET /api/3d/<job_id>` streams the DAE bytes
  to the browser (so we don't bloat `last_result.json`).
- **`src/_version.py`** — bump to **1.3.0** (new major feature).
- **`static/index.html`** — new `data-view="3d"` tab between QS View and BIM
  View; toolbar; viewport canvas; element inspector side panel.

### 5.4 Files NOT touched

`module0_inventory.py`, `module1_qs_readiness.py`, `module2_bq_draft.py`,
`module2_checks.py`, `scoring.py`, `pdf_report.py` — all unchanged. M3 is
layered on top, not woven in. `archiqs.spec` and `installer/archiqs.iss`
already bundle `static/` recursively, so no installer changes.

## 6. Caching mechanism

### 6.1 Layout

Beside the .rvt:

```
<rvt-folder>/.archiqs-cache/
    <basename>_<mode>.xlsx        # DDC structured data
    <basename>_<mode>.dae         # DDC 3D geometry (new)
    <basename>_<mode>.cache.json  # cache metadata (new)
```

The hidden directory keeps user-visible folders clean.

### 6.2 Metadata file

```json
{
  "schema_version": 1,
  "rvt_path": "C:\\...\\model.rvt",
  "rvt_size": 524288000,
  "rvt_mtime": 1715126400.123,
  "ddc_mode": "standard",
  "ddc_version": "18.1.0",
  "archiqs_version": "1.3.0",
  "created_at": "2026-05-08T10:23:14Z",
  "xlsx_path": ".../<basename>_standard.xlsx",
  "dae_path": ".../<basename>_standard.dae"
}
```

### 6.3 Invalidation rules

Any one triggers a re-run:

1. `rvt_size` changed.
2. `rvt_mtime` changed (with 2-second tolerance for filesystem rounding).
3. `ddc_mode` requested doesn't match cache's mode.
4. `ddc_version` differs (covers bundled-DDC upgrades).
5. `xlsx_path` or `dae_path` no longer exists on disk.
6. `force=True` passed by user (existing escape hatch).
7. `schema_version` differs (lets us bump the format later without breakage).

### 6.4 Telemetry

On cache hit, the SSE log emits
`"Cache hit — skipping DDC (saved ~XX s)"`. Small touch, big "premium product"
feel.

## 7. Element ID ↔ 3D node mapping

DDC writes Element IDs as COLLADA node names:

```xml
<node id="element_1890568" name="1890568" type="NODE">
  <instance_geometry url="#geom_1890568"/>
</node>
```

After ColladaLoader parses the file, every mesh in the scene graph carries
`mesh.name = "1890568"`. We walk the scene once on load:

```javascript
elementMap = {
  "1890568": { mesh: <THREE.Mesh>, originalMaterial: <Material> },
  "1890569": { ... },
  ...
}
```

### 7.1 Painting Module 1 status

```javascript
for (const [dim, info] of Object.entries(data.score.module1_detail)) {
  for (const group of info.groups || []) {
    for (const id of group.ids) {
      const entry = elementMap[String(id)];
      if (entry) entry.mesh.material = severityMaterial(dim, info.score);
    }
  }
}
```

Severity → material:

- score < 75 → red translucent (`#ef4444` @ 0.85 opacity)
- score < 90 → orange translucent (`#f59e0b` @ 0.85)
- pass → original DDC-assigned material (untouched)

### 7.2 Click picking

Standard three.js `Raycaster` against `scene.children`. On hit:

1. Read `mesh.name` (the Element ID).
2. Look up in `data.qs_element_list` → Family, Type, Volume, Level, Material.
3. Look up in `data.score.module1_detail` → which dimensions flagged it.
4. Render the side panel.

### 7.3 Edge cases

- **IDs in DAE but not in QS data** (Mass, Generic Models, Furniture):
  rendered in DDC default color, click-pickable but the panel shows
  "Non-QS element" instead of QS detail.
- **IDs in QS data but no DAE geometry** (elements without geometry):
  ignored by the 3D view; M1 detail in BIM View remains the source of truth.
- **Node-name format drift** (DDC config change): if < 80 % of nodes match
  `^\d+$`, set `has_element_ids = False`, show a warning banner, fall back
  to plain category coloring (no problem highlighting, no click inspection).

## 8. Frontend layout

### 8.1 Tab placement

```
[ QS View ]  [ 3D View ]  [ BIM View ]
```

QS first (executive summary), 3D in the middle (visual bridge), BIM last
(raw data).

### 8.2 Tab content

```
┌───────────────────────────────────────────────────────────────┐
│  TOOLBAR                                                       │
│  [Color by: Status ▾]  [✓ CRITICAL] [✓ WARNING]  [Reset view]  │
│  Loaded: 12,438 elements · 3.2 M triangles                     │
├───────────────────────────────────────┬───────────────────────┤
│                                       │  ELEMENT INSPECTOR    │
│        ╔═══════════════════╗          │                       │
│        ║   3D viewport     ║          │  Click an element     │
│        ║   (three.js       ║          │  to inspect.          │
│        ║    canvas)        ║          │                       │
│        ╚═══════════════════╝          │  ID:       1890568    │
│                                       │  Family:   Basic Wall │
│                                       │  Type:     Generic-200│
│                                       │  Level:    (missing)  │
│                                       │  Volume:   4.32 m³    │
│                                       │  Issues:              │
│                                       │   • Level Coverage    │
│                                       │     (CRITICAL)        │
│                                       │                       │
│                                       │  [Copy ID]            │
│  Mouse: drag rotate · scroll zoom     │                       │
│         shift+drag pan                │                       │
└───────────────────────────────────────┴───────────────────────┘
```

### 8.3 Toolbar controls

| Control | Behavior |
|---|---|
| `Color by: Status / Category / Family / Single tone` dropdown | Switches material assignment. **Status is default.** |
| `[✓] CRITICAL` checkbox | Unchecking restores default material on red elements. |
| `[✓] WARNING` checkbox | Same for orange. |
| `Reset view` | Re-frames camera to show the whole bounding box. |

### 8.4 Lazy initialization

The three.js scene is **not** built when the user lands on QS View. It's
built only on first click of the 3D tab — saves ~2 s of analysis-finished
latency for users who never open 3D.

```javascript
let viewer3d = null;
function show3DTab() {
  switchView('3d');
  if (!viewer3d && currentResult) {
    viewer3d = new Viewer3D(document.getElementById('viewport'));
    viewer3d.load(currentResult.module3.dae_path, currentResult);
  }
}
```

### 8.5 Loading UX

```
[Spinner] Loading 3D model… 12 / 100 MB
[Spinner] Parsing geometry…
[Spinner] Painting Module 1 status (12,438 elements)…
✓ Ready
```

Target end-to-end load time for a typical 50 MB DAE: ≤ 3 s.

### 8.6 Camera defaults

Orbit controls, perspective camera. Target = scene center. Position =
bounding-box-fit at 30° elevation / 45° azimuth (the standard
"isometric-ish" architectural view). Lighting: one ambient + one directional
from upper-front.

## 9. Performance

| Model size | Target load time | Strategy |
|---|---|---|
| Small (< 5 k elements, < 20 MB DAE) | < 1 s | Load whole scene as-is |
| Medium (5–30 k elements, 20–100 MB DAE) | < 3 s | Same path; rely on browser streaming |
| Large (30–100 k elements, 100–400 MB DAE) | < 8 s | Merge meshes per material into instanced groups; show progress |
| Huge (> 100 k elements, > 400 MB DAE) | "best effort" | Show warning; offer to skip 3D and use QS/BIM views only |

### 9.1 Critical optimization: merged geometry

Naïvely, ColladaLoader creates one `THREE.Mesh` per `<node>` — fine for
picking but kills frame rate above ~10 k draw calls. We do this once after
load:

1. Group meshes by their assigned material category (CRITICAL / WARNING /
   pass / non-QS).
2. Merge each group's `BufferGeometry` into a single mesh
   (`THREE.BufferGeometryUtils.mergeGeometries`).
3. Keep an index: `faceRange → originalElementId` for picking.

Picking still works because the raycaster returns face indices, which we map
back to Element IDs via the index. Trades a small amount of picking
complexity for 5–10× FPS gain on big models.

### 9.2 Memory cap

If the DAE file is > 500 MB, refuse to load and show:

> *This model is too large for the in-app 3D preview. Use the QS Data Excel
> and BIM View instead, or open the .dae file in CADAssistant for full 3D
> inspection.*

We don't want to crash the app or freeze WebView2 trying.

## 10. Error handling

The 3D feature is **additive** — any failure in M3 must NOT break Module
0 / 1 / 2 or the QS/BIM views. The result payload always returns Module 0–2
even if M3 errors out, the same way Module 2 errors don't break scoring
today.

| Failure mode | Detection | UX |
|---|---|---|
| DDC didn't produce a `.dae` (export failed mid-run) | `module3.dae_path` is `null` in result | 3D tab shows "3D preview not available — DDC could not generate geometry. See log for details." Other tabs unaffected. |
| `.dae` exists but is corrupt | `ColladaLoader.parse()` throws | "Could not parse the 3D file. Re-run analysis with **Force re-run** to regenerate." |
| Node names aren't Element IDs (config drift) | Validation pass: ≥ 80 % must match `^\d+$` | Warning banner: "3D model loaded but Element IDs could not be matched. Click-inspection and problem highlighting are disabled." Falls back to plain category coloring. |
| WebGL context lost (rare, GPU driver issue) | `webglcontextlost` event | "3D viewport crashed — refresh to retry." Other tabs continue to work. |
| Cache file points to a missing `.dae` (user deleted it) | `os.path.exists()` check in `cache.lookup()` | Auto-invalidate cache, re-run DDC. Logged. |

## 11. Test strategy

1. **Unit (`tests/test_cache.py`)** — fresh tmp dir, simulate the seven
   invalidation rules with stub files; assert lookup returns hit/miss
   correctly. Includes a 2-second mtime-tolerance test.
2. **Unit (`tests/test_module3.py`)** — feed a tiny hand-crafted `.dae`
   (5 elements) through the validator; assert element-count and
   `has_element_ids` flag. Add a malformed-DAE fixture for the error path.
3. **Integration (manual, documented)** — three real `.rvt` files of
   different sizes (small / medium / large) on Windows. Check load time,
   memory, picking accuracy, and that the cache hit message appears on
   second analysis.
4. **No frontend automation** — three.js + WebView2 is a hassle to drive
   headlessly. The viewer is small enough to test by hand.
5. **Regression** — run the existing analyze pipeline on the same `.rvt`s
   before/after the M3 change. Confirm score, BQ output, and result JSON are
   byte-identical except for the new `module3` key.

## 12. Rollout sequence

Each step is independently shippable.

1. Land `cache.py` + `ddc_runner` cache hooks. Works for xlsx today, no UI
   change yet — users immediately benefit from faster re-analysis.
2. Land `module3_3d_preview.py` + DAE export from DDC. Result payload gets
   the new `module3` key but no UI surface yet.
3. Land `viewer3d.js` + new tab. Full feature live.
4. Bump 1.3.0, build, ship.

If step 3 hits a snag, we still benefit from step 1's caching.

## 13. Out of scope (deliberately)

- **Section visualization** (cutting planes, hide-by-level). Possible v1.4
  feature.
- **Annotation / markup** in 3D. Out of scope.
- **Comparing two .rvt versions side-by-side** in 3D. Out of scope.
- **Export of the 3D scene** (PNG / GLTF). Out of scope.
- **VR / AR support.** Out of scope.
- **Editing the model** in any way. Out of scope — ArchiQS is read-only.
