/**
 * QSForge — Viewer3D
 *
 * Encapsulates a three.js scene that renders a glTF (GLB) file produced by
 * the server-side trimesh DAE→GLB conversion (see
 * src/module3_3d_preview.py::_convert_dae_to_glb) and overlays Module 1
 * quality issues on top of the geometry.
 *
 * Lifecycle
 * ---------
 *   const v = new Viewer3D(containerEl);
 *   await v.load(glbUrl, resultData);    // parses + paints + zooms-to-fit
 *   v.setColorMode('status' | 'category' | 'family' | 'single');
 *   v.toggleSeverity('CRITICAL', false);
 *   v.dispose();                         // tear down on tab change / new analysis
 *
 * Element ID join
 * ---------------
 *   DAE <node name="1890568">  →  trimesh GLB node.name = "1890568"
 *                              →  GLTFLoader Object3D.name = "1890568"
 *   We walk the loaded scene once and build:
 *     this.elementMap = { "1890568": { mesh, originalMaterial, ... }, ... }
 *
 * Picking
 * -------
 *   Standard THREE.Raycaster against scene children. On hit, mesh.name is
 *   the Element ID; the host page joins it with QS data via the inspector
 *   callback.
 */
import * as THREE from '/static/vendor/three/three.module.min.js';
import { GLTFLoader } from '/static/vendor/three/GLTFLoader.js';
import { OrbitControls } from '/static/vendor/three/OrbitControls.js';

const SEVERITY_COLORS = {
  CRITICAL: 0xef4444,   // red
  WARNING:  0xf59e0b,   // orange
};

const SELECTION_COLOR = 0x22d3ee;  // cyan

// Deterministic colour from any string. Same string → same hue forever.
// Used by Color-by Category and Color-by Family modes so the palette is
// stable across app launches and re-analyses without us having to maintain
// a mapping table.
function colorForString(s, saturation = 0.55, lightness = 0.58) {
  let hash = 0;
  for (let i = 0; i < s.length; i++) {
    hash = ((hash << 5) - hash) + s.charCodeAt(i);
    hash |= 0;
  }
  const hue = ((hash >>> 0) % 360) / 360;
  return new THREE.Color().setHSL(hue, saturation, lightness);
}

// Default mesh material. We use MeshLambertMaterial (cheap diffuse lighting
// that DOES NOT depend on per-vertex normals being correct) plus a strong
// ambient light, so meshes from DDC always have a baseline brightness even
// when the geometry's normals are missing or degenerate. MeshStandardMaterial
// was previously used but rendered some real-world DDC meshes as almost-black
// due to broken normals.
const DEFAULT_MATERIAL = new THREE.MeshLambertMaterial({
  color: 0xb0b8c4,
  side: THREE.DoubleSide,
  emissive: 0x303338,        // baseline brightness even when lit edge-on
  emissiveIntensity: 1.0,
});

export class Viewer3D {
  constructor(container, opts = {}) {
    this.container = container;
    this.opts = opts;
    this.elementMap = {};            // { "1890568": { mesh, originalMaterial } }
    this.severityMap = {};           // { "1890568": "CRITICAL" | "WARNING" }
    this.currentColorMode = 'status';
    this.severityVisibility = { CRITICAL: true, WARNING: true };
    this.onPick = opts.onPick || (() => {});
    this._initScene();
    this._initEvents();
  }

  _initScene() {
    // Defensive: when the panel has just been un-hidden, layout may not have
    // computed yet and clientWidth/clientHeight can be 0. Fall back to safe
    // defaults; the ResizeObserver below corrects the canvas as soon as the
    // real dimensions are known.
    const w = this.container.clientWidth || 800;
    const h = this.container.clientHeight || 600;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    this.renderer.setPixelRatio(window.devicePixelRatio || 1);
    this.renderer.setSize(w, h);
    this.container.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0a0a0d);

    this.camera = new THREE.PerspectiveCamera(50, w / h, 0.1, 1e7);
    this.camera.position.set(60, 60, 60);
    this.camera.lookAt(0, 0, 0);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;

    // Aggressive ambient + hemisphere lighting. Hemisphere lighting is
    // direction-only (no need for correct vertex normals), so even meshes
    // with broken normals get baseline brightness from above/below tint.
    this.scene.add(new THREE.AmbientLight(0xffffff, 1.2));
    this.scene.add(new THREE.HemisphereLight(0xddeeff, 0x202028, 0.6));
    const dir1 = new THREE.DirectionalLight(0xffffff, 0.6);
    dir1.position.set(80, 120, 60);
    this.scene.add(dir1);
    const dir2 = new THREE.DirectionalLight(0xffffff, 0.3);
    dir2.position.set(-80, 60, -120);
    this.scene.add(dir2);

    this.modelGroup = new THREE.Group();
    this.scene.add(this.modelGroup);

    this.raycaster = new THREE.Raycaster();
    this._renderLoop = this._renderLoop.bind(this);
    requestAnimationFrame(this._renderLoop);

    // Watch for size changes (panel reveal, window resize, sidebar toggles).
    if (typeof ResizeObserver !== 'undefined') {
      this._resizeObserver = new ResizeObserver(() => {
        const cw = this.container.clientWidth;
        const ch = this.container.clientHeight;
        if (cw > 0 && ch > 0) {
          this.renderer.setSize(cw, ch);
          this.camera.aspect = cw / ch;
          this.camera.updateProjectionMatrix();
        }
      });
      this._resizeObserver.observe(this.container);
    }
  }

  _renderLoop() {
    if (this._disposed) return;
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    requestAnimationFrame(this._renderLoop);
  }

  _initEvents() {
    this._onResize = () => {
      const w = this.container.clientWidth;
      const h = this.container.clientHeight;
      this.renderer.setSize(w, h);
      this.camera.aspect = w / h;
      this.camera.updateProjectionMatrix();
    };
    window.addEventListener('resize', this._onResize);

    this._onClick = (ev) => {
      const rect = this.renderer.domElement.getBoundingClientRect();
      const x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
      const y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
      this.raycaster.setFromCamera({ x, y }, this.camera);
      const targets = this.modelGroup.children.filter((o) => o.visible);
      const hits = this.raycaster.intersectObjects(targets, true);
      const additive = ev.shiftKey || ev.ctrlKey || ev.metaKey;
      if (hits.length === 0) {
        if (!additive) {
          this.setSelected(null);
          this.onPick(this.getSelection());
        }
        return;
      }
      // Mesh names may be either bare element IDs ("1473185") or suffixed
      // for multi-shape elements ("1473185_1"); accept both shapes.
      const ID_RE = /^\d+(?:_\d+)?$/;
      let target = hits[0].object;
      while (target && (!target.name || !ID_RE.test(target.name)) && target.parent) {
        target = target.parent;
      }
      const id = target && ID_RE.test(target.name) ? target.name : null;
      this.setSelected(id, additive);
      this.onPick(this.getSelection());
    };
    this.renderer.domElement.addEventListener('click', this._onClick);
  }

  // ── Selection highlight (multi) ────────────────────────────────────
  // _selectedIds: Set<string> of currently selected Element IDs
  // _selectedRestoreMats: Map<id, originalMat> so we can restore exactly
  setSelected(id, additive = false) {
    if (!this._selectedIds) this._selectedIds = new Set();
    if (!this._selectedRestoreMats) this._selectedRestoreMats = new Map();

    if (!additive) {
      // Replace selection: clear all then select id (if any)
      this._clearSelectionHighlight();
      if (id && this.elementMap[id]) {
        this._selectedIds.add(id);
        this._highlightOne(id);
      }
      return;
    }
    // Additive (Shift+click): toggle this id
    if (!id || !this.elementMap[id]) return;
    if (this._selectedIds.has(id)) {
      this._unhighlightOne(id);
      this._selectedIds.delete(id);
    } else {
      this._selectedIds.add(id);
      this._highlightOne(id);
    }
  }

  _highlightOne(id) {
    const entry = this.elementMap[id];
    if (!entry) return;
    this._selectedRestoreMats.set(id, entry.mesh.material);
    entry.mesh.material = new THREE.MeshStandardMaterial({
      color: SELECTION_COLOR,
      emissive: SELECTION_COLOR,
      emissiveIntensity: 0.45,
      roughness: 0.4,
      metalness: 0.0,
      side: THREE.DoubleSide,
    });
  }

  _unhighlightOne(id) {
    const restore = this._selectedRestoreMats && this._selectedRestoreMats.get(id);
    const entry = this.elementMap[id];
    if (entry && restore) entry.mesh.material = restore;
    if (this._selectedRestoreMats) this._selectedRestoreMats.delete(id);
  }

  _clearSelectionHighlight() {
    if (this._selectedIds) {
      for (const id of this._selectedIds) this._unhighlightOne(id);
      this._selectedIds.clear();
    }
    if (this._selectedRestoreMats) this._selectedRestoreMats.clear();
  }

  getSelection() {
    return this._selectedIds ? Array.from(this._selectedIds) : [];
  }

  // Helper for code paths that still want a single id (e.g. _applyColorMode
  // after a recolour) — re-apply the highlight to whatever is selected.
  _reapplySelectionAfterRecolor() {
    if (!this._selectedIds || this._selectedIds.size === 0) return;
    const ids = Array.from(this._selectedIds);
    // Restore mats are stale (point at the pre-recolour material). Refresh
    // each to the new current material before reapplying the cyan glow.
    for (const id of ids) {
      const entry = this.elementMap[id];
      if (entry) this._selectedRestoreMats.set(id, entry.mesh.material);
      this._highlightOne(id);
    }
  }

  // ── Category filtering ──────────────────────────────────────────────
  getCategoryCounts() {
    const cats = {};
    for (const entry of Object.values(this.elementMap)) {
      const c = entry.category || '(no category)';
      cats[c] = (cats[c] || 0) + 1;
    }
    return cats;
  }

  setCategoryVisibility(category, visible) {
    this._setVisibilityBy('category', category, visible);
  }

  // ── Level filtering ─────────────────────────────────────────────────
  getLevelCounts() {
    const lvls = {};
    for (const entry of Object.values(this.elementMap)) {
      const raw = entry.raw || {};
      const lvl = raw.Level || raw.level || '(no level)';
      lvls[lvl] = (lvls[lvl] || 0) + 1;
    }
    return lvls;
  }

  setLevelVisibility(level, visible) {
    this._setVisibilityBy('level', level, visible);
  }

  // Shared visibility-by-attribute logic. We track per-attribute hidden sets
  // so two filters (Category off + Level off) compose correctly: a mesh is
  // visible iff it's hidden in NO active filter.
  _setVisibilityBy(kind, value, visible) {
    if (!this._hidden) this._hidden = { category: new Set(), level: new Set() };
    const set = this._hidden[kind];
    if (!set) return;
    if (visible) set.delete(value);
    else set.add(value);
    this._recomputeVisibility();
    // If any selected element is now invisible, drop those.
    if (this._selectedIds) {
      let removed = false;
      for (const id of Array.from(this._selectedIds)) {
        const entry = this.elementMap[id];
        if (entry && !entry.mesh.visible) {
          this._unhighlightOne(id);
          this._selectedIds.delete(id);
          removed = true;
        }
      }
      if (removed) this.onPick(this.getSelection());
    }
  }

  _recomputeVisibility() {
    const hCat = (this._hidden && this._hidden.category) || new Set();
    const hLvl = (this._hidden && this._hidden.level) || new Set();
    for (const entry of Object.values(this.elementMap)) {
      const cat = entry.category || '(no category)';
      const raw = entry.raw || {};
      const lvl = raw.Level || raw.level || '(no level)';
      entry.mesh.visible = !hCat.has(cat) && !hLvl.has(lvl);
    }
  }

  // ── Search ──────────────────────────────────────────────────────────
  // Returns array of matching Element IDs. Numeric query → exact ID match.
  // Text query → case-insensitive substring against family/type/category.
  search(query) {
    if (!query) return [];
    const q = String(query).trim().toLowerCase();
    if (!q) return [];
    const numeric = /^\d+$/.test(q);
    const matches = [];
    for (const [id, entry] of Object.entries(this.elementMap)) {
      if (numeric) {
        if (id === q) matches.push(id);
      } else {
        const hay = ((entry.family || '') + ' ' + (entry.type || '') + ' ' + (entry.category || '')).toLowerCase();
        if (hay.includes(q)) matches.push(id);
      }
    }
    return matches;
  }

  // Frame the camera tightly on a set of element IDs.
  frameOn(ids) {
    if (!ids || ids.length === 0) return;
    const box = new THREE.Box3();
    let any = false;
    for (const id of ids) {
      const entry = this.elementMap[id];
      if (!entry) continue;
      const meshBox = new THREE.Box3().setFromObject(entry.mesh);
      if (!meshBox.isEmpty()) { box.union(meshBox); any = true; }
    }
    if (!any) return;
    const size = new THREE.Vector3(); box.getSize(size);
    const center = new THREE.Vector3(); box.getCenter(center);
    const radius = Math.max(size.length() * 0.5, 0.5);
    const fov = (this.camera.fov * Math.PI) / 180;
    const dist = radius / Math.sin(fov / 2);
    const dir = new THREE.Vector3(1, 0.7, 1).normalize();
    this.camera.position.copy(center).addScaledVector(dir, dist * 1.8);
    this.camera.near = Math.max(0.01, dist / 1000);
    this.camera.far = Math.max(dist * 100, 1e5);
    this.camera.updateProjectionMatrix();
    this.controls.target.copy(center);
    this.controls.update();
  }

  // Returns the metadata entry for an id (useful for the host-page inspector).
  getElementMeta(id) {
    return this.elementMap[String(id)] || null;
  }

  async load(glbUrl, resultData) {
    console.log('[Viewer3D] load() called, url:', glbUrl);
    const loader = new GLTFLoader();
    console.log('[Viewer3D] GLTFLoader instance OK, typeof:', typeof loader, 'load fn:', typeof loader.load);
    return new Promise((resolve, reject) => {
      loader.load(
        glbUrl,
        (gltf) => {
          console.log('[Viewer3D] GLTFLoader callback entered. gltf keys:', Object.keys(gltf || {}));
          try {
            console.log('[Viewer3D] gltf.scene type:', typeof gltf.scene, 'children:', gltf.scene && gltf.scene.children && gltf.scene.children.length);
            // glTF scenes are Y-up by spec — no manual reparenting / matrix
            // baking is needed (ColladaLoader required that hack because it
            // put unit-scale and Z-up→Y-up rotation on ancestor groups, which
            // got applied twice at render time). GLTFLoader hands us a scene
            // we can drop straight into modelGroup.
            this.modelGroup.add(gltf.scene);
            this.modelGroup.updateMatrixWorld(true);
            console.log('[Viewer3D] scene added to modelGroup');

            // DIAGNOSTIC PASS: count what's actually in the scene by type,
            // sample first 3 meshes' geometry data, and force every
            // renderable into a lighting-independent bright material.
            const counts = { Mesh: 0, Line: 0, LineSegments: 0, Points: 0, Group: 0, other: 0 };
            const meshSamples = [];
            this.modelGroup.traverse((obj) => {
              if (obj.isMesh) {
                counts.Mesh++;
                if (meshSamples.length < 3) {
                  const g = obj.geometry;
                  const pos = g && g.attributes && g.attributes.position;
                  const idx = g && g.index;
                  const sample = {
                    name: obj.name || '(no name)',
                    posCount: pos ? pos.count : -1,
                    posArrayType: pos ? pos.array.constructor.name : 'none',
                    firstVerts: pos && pos.count > 0
                      ? Array.from(pos.array.slice(0, 9)).map((n) => n.toFixed(2)).join(',')
                      : 'empty',
                    indexCount: idx ? idx.count : 0,
                    drawRange: g ? `${g.drawRange.start},${g.drawRange.count}` : 'n/a',
                    visible: obj.visible,
                    matrixWorld: obj.matrixWorld
                      ? `(${obj.matrixWorld.elements[12].toFixed(0)},${obj.matrixWorld.elements[13].toFixed(0)},${obj.matrixWorld.elements[14].toFixed(0)})`
                      : 'n/a',
                  };
                  meshSamples.push(sample);
                }
              }
              else if (obj.isLineSegments) counts.LineSegments++;
              else if (obj.isLine) counts.Line++;
              else if (obj.isPoints) counts.Points++;
              else if (obj.isGroup) counts.Group++;
              else counts.other++;

              if (obj.isMesh) {
                if (obj.material) {
                  if (Array.isArray(obj.material)) obj.material.forEach((m) => m.dispose && m.dispose());
                  else obj.material.dispose && obj.material.dispose();
                }
                // Default light-gray double-sided material. Module 1 status
                // painting overlays red/orange via _applyColorMode below.
                obj.material = DEFAULT_MATERIAL.clone();
                if (obj.geometry && !obj.geometry.attributes.normal) {
                  obj.geometry.computeVertexNormals();
                }
                obj.frustumCulled = false;
              }
            });
            this._sceneCounts = counts;
            this._meshSamples = meshSamples;
            console.log('[Viewer3D] diagnostic pass done. counts:', counts);
            this._buildElementMap(resultData);
            console.log('[Viewer3D] _buildElementMap done, elementMap size:', Object.keys(this.elementMap).length);
            this._mergedMode = false;
            if (Object.keys(this.elementMap).length > 8000) {
              this._tryMergeGeometries();
            }
            this._buildSeverityMap(resultData);
            console.log('[Viewer3D] _buildSeverityMap done, severityMap size:', Object.keys(this.severityMap).length);
            this._applyColorMode('status');
            console.log('[Viewer3D] _applyColorMode done');
            this._frameModel();
            console.log('[Viewer3D] _frameModel done');
            const diagnostics = this.diagnostics || {};
            diagnostics.sceneCounts = this._sceneCounts || {};
            diagnostics.meshSamples = this._meshSamples || [];
            resolve({
              elementCount: Object.keys(this.elementMap).length,
              triangleCount: this._countTriangles(),
              diagnostics: diagnostics,
            });
          } catch (e) {
            console.error('[Viewer3D] error inside success callback:', e, e && e.stack);
            reject(e);
          }
        },
        (progress) => {
          if (progress && progress.lengthComputable) {
            console.log('[Viewer3D] download progress:', Math.round(100 * progress.loaded / progress.total), '%');
          }
        },
        (err) => {
          console.error('[Viewer3D] GLTFLoader error callback:', err, err && err.stack, err && err.message);
          reject(err);
        },
      );
    });
  }

  _buildElementMap(resultData) {
    this.elementMap = {};
    // Build a fast id → metadata lookup from the QS Element List so we
    // can colour-by-family / category at draw time without scanning the
    // big list every time.
    const meta = {};
    const list = (resultData && resultData.qs_element_list) || [];
    for (const el of list) {
      const id = String(el['Element ID'] ?? el.id ?? '');
      if (!id) continue;
      meta[id] = {
        family:   el.Family   || el.family   || '(no family)',
        type:     el['Type Name'] || el.type || '(no type)',
        category: el.Category || el.category || '(no category)',
        // Stash the whole row so the inspector can show every field.
        raw: el,
      };
    }
    // Mesh names may be a bare element ID ("1473185") OR a suffixed form
    // ("1473185_1", "1473185_2", ...) when one Revit element contains
    // multiple shapes — the server-side DAE→GLB converter appends a numeric
    // suffix to keep all shapes in the GLB after renaming collisions.
    // Strip the suffix when looking up metadata + when keying elementMap.
    const ID_RE = /^(\d+)(?:_\d+)?$/;
    this.modelGroup.traverse((obj) => {
      if (!obj.isMesh) return;
      const m = ID_RE.exec(obj.name || '');
      if (!m) return;
      const baseId = m[1];
      const md = meta[baseId] || {
        family: 'Non-QS', type: '', category: 'Non-QS', raw: null,
      };
      // The mesh.name itself (with any suffix) stays as the elementMap key
      // so each shape is independently selectable. The `baseId` is what
      // links back to QS data and severity. Multiple entries can share the
      // same baseId — that's intentional.
      this.elementMap[obj.name] = {
        mesh: obj,
        originalMaterial: obj.material,
        family: md.family,
        type: md.type,
        category: md.category,
        raw: md.raw,
        baseId,
      };
    });
  }

  /**
   * v1.4 hook — geometry merging for very large scenes.
   *
   * Plan: group meshes by material category (CRITICAL / WARNING / pass /
   * non-QS), merge each group's BufferGeometries via THREE.BufferGeometryUtils
   * .mergeGeometries, and keep a faceRange→ElementId index for picking.
   *
   * For v1.3 we ship without merging: small/medium models render fine, and
   * very large models surface the console warning emitted in `load()` so the
   * user knows performance is the trade-off. We'll wire merging in v1.4 once
   * we have a real reproducer to optimize against.
   */
  _tryMergeGeometries() {
    // No-op for v1.3 — see docstring above.
    return;
  }

  _buildSeverityMap(resultData) {
    this.severityMap = {};
    const detail = (resultData && resultData.score && resultData.score.module1_detail) || {};
    for (const [dim, info] of Object.entries(detail)) {
      const score = info && info.score;
      let sev = null;
      if (typeof score === 'number') {
        if (score < 75) sev = 'CRITICAL';
        else if (score < 90) sev = 'WARNING';
      }
      if (!sev) continue;
      for (const group of (info.groups || [])) {
        for (const id of (group.ids || [])) {
          const k = String(id);
          // CRITICAL wins over WARNING if an element is flagged in both
          if (this.severityMap[k] === 'CRITICAL') continue;
          this.severityMap[k] = sev;
        }
      }
    }
  }

  _applyColorMode(mode) {
    this.currentColorMode = mode;
    // Dispose materials created by the previous mode so we don't leak GPU
    // memory across repeated Color-By switches. originalMaterial is kept
    // so 'single' mode can restore it.
    for (const entry of Object.values(this.elementMap)) {
      const mat = entry.mesh.material;
      if (mat && mat !== entry.originalMaterial && typeof mat.dispose === 'function') {
        mat.dispose();
      }
    }
    for (const [id, entry] of Object.entries(this.elementMap)) {
      let mat;
      // Severity is indexed by the bare Revit element ID. When mesh names
      // carry a "_N" suffix for multi-shape elements, look up by baseId so
      // every shape of an element shares the same severity colour.
      const sevKey = entry.baseId || id;
      if (mode === 'status') {
        const sev = this.severityMap[sevKey];
        if (sev && this.severityVisibility[sev]) {
          mat = new THREE.MeshStandardMaterial({
            color: SEVERITY_COLORS[sev],
            roughness: 0.7, metalness: 0.0,
            side: THREE.DoubleSide,
            transparent: true, opacity: 0.85,
          });
        } else {
          mat = entry.originalMaterial || DEFAULT_MATERIAL;
        }
      } else if (mode === 'category') {
        mat = new THREE.MeshStandardMaterial({
          color: colorForString(entry.category || 'unknown'),
          roughness: 0.85, metalness: 0.0,
          side: THREE.DoubleSide,
        });
      } else {
        // 'single' / 'plain' / unknown mode: default gray
        mat = entry.originalMaterial || DEFAULT_MATERIAL;
      }
      entry.mesh.material = mat;
    }
    // Re-apply selection highlight if something was selected before the
    // mode switch — otherwise the cyan glow disappears on every recolour.
    this._reapplySelectionAfterRecolor();
  }

  setColorMode(mode) { this._applyColorMode(mode); }

  toggleSeverity(severity, visible) {
    this.severityVisibility[severity] = !!visible;
    if (this.currentColorMode === 'status') this._applyColorMode('status');
  }

  resetView() { this._frameModel(); }

  _frameModel() {
    // Two bounding-box strategies:
    //  A) full bbox    — Box3.setFromObject(modelGroup)  — covers ALL geometry
    //  B) percentile   — 5th–95th percentile of mesh centroids — ignores outliers
    //
    // For most models the full bbox is what users expect ("Reset View" → see
    // everything). But some Revit/DDC exports include a handful of stray
    // elements far from the main building (e.g. coordinate markers placed at
    // project base point thousands of metres away), and the full bbox then
    // frames the camera on an empty area between the cluster and the
    // outliers — the user sees nothing.
    //
    // Rule: use the percentile bbox only when it's MUCH smaller than the
    // full bbox (clear evidence of outliers). Otherwise use the full bbox.
    const fullBox = new THREE.Box3().setFromObject(this.modelGroup);

    const meshCenters = [];
    this.modelGroup.traverse((obj) => {
      if (obj.isMesh && obj.geometry) {
        if (!obj.geometry.boundingBox) obj.geometry.computeBoundingBox();
        const c = new THREE.Vector3();
        obj.geometry.boundingBox.getCenter(c);
        c.applyMatrix4(obj.matrixWorld);
        meshCenters.push(c);
      }
    });

    let size = new THREE.Vector3(10, 10, 10);
    let center = new THREE.Vector3(0, 0, 0);
    let originalCenter = center.clone();
    let isEmpty = meshCenters.length === 0 || fullBox.isEmpty();

    if (!isEmpty) {
      // Compute percentile box from mesh centroids
      const xs = meshCenters.map((c) => c.x).sort((a, b) => a - b);
      const ys = meshCenters.map((c) => c.y).sort((a, b) => a - b);
      const zs = meshCenters.map((c) => c.z).sort((a, b) => a - b);
      const pct = (arr, p) => arr[Math.floor((arr.length - 1) * p)];
      const pX = pct(xs, 0.95) - pct(xs, 0.05);
      const pY = pct(ys, 0.95) - pct(ys, 0.05);
      const pZ = pct(zs, 0.95) - pct(zs, 0.05);

      const fullSize = new THREE.Vector3();
      fullBox.getSize(fullSize);

      // Outlier heuristic: if the 5th–95th-percentile span of mesh centroids
      // is much smaller than the full bbox on any axis, the full bbox is
      // being stretched by stragglers — use the percentile box.
      // Catches both "1 outlier at extreme" (pX == 0) and "few outliers"
      // (pX small but nonzero).
      const outlierThreshold = 0.10;
      const outliers =
        (fullSize.x > 0.5 && pX < fullSize.x * outlierThreshold) ||
        (fullSize.y > 0.5 && pY < fullSize.y * outlierThreshold) ||
        (fullSize.z > 0.5 && pZ < fullSize.z * outlierThreshold);

      if (outliers) {
        const xMin = pct(xs, 0.05), xMax = pct(xs, 0.95);
        const yMin = pct(ys, 0.05), yMax = pct(ys, 0.95);
        const zMin = pct(zs, 0.05), zMax = pct(zs, 0.95);
        const padX = (xMax - xMin) * 0.1 + 1;
        const padY = (yMax - yMin) * 0.1 + 1;
        const padZ = (zMax - zMin) * 0.1 + 1;
        size.set(xMax - xMin + padX * 2, yMax - yMin + padY * 2, zMax - zMin + padZ * 2);
        center.set((xMin + xMax) / 2, (yMin + yMax) / 2, (zMin + zMax) / 2);
      } else {
        // Normal model: use the actual full bounding box.
        fullBox.getSize(size);
        fullBox.getCenter(center);
      }

      originalCenter = center.clone();
      if (center.length() > 0.01) {
        this.modelGroup.position.sub(center);
        center.set(0, 0, 0);
      }
    }
    const box = isEmpty
      ? new THREE.Box3()
      : new THREE.Box3(
          new THREE.Vector3(center.x - size.x / 2, center.y - size.y / 2, center.z - size.z / 2),
          new THREE.Vector3(center.x + size.x / 2, center.y + size.y / 2, center.z + size.z / 2),
        );

    // Floor the framing radius so degenerate models don't crash the math,
    // but keep it low so genuinely small details (e.g. a 1 m connection
    // detail) still get framed at a sensible distance.
    const radius = Math.max(size.length() * 0.5, 0.5);
    const fov = (this.camera.fov * Math.PI) / 180;
    const dist = radius / Math.sin(fov / 2);

    // Pick a viewing direction that won't look edge-on at flat models.
    // Many Revit detail/coordination DAEs are mostly horizontal slabs with
    // tiny vertical extent — viewing those at an isometric angle makes them
    // disappear. If Y (vertical, after Z-up→Y-up rotation) is < 25% of the
    // largest horizontal dimension, switch to a steeper top-down view.
    const horizMax = Math.max(size.x, size.z);
    const isFlat = size.y < horizMax * 0.25;
    const dir = isFlat
      ? new THREE.Vector3(0.5, 1.0, 0.5).normalize()  // mostly top-down, slight perspective
      : new THREE.Vector3(1, 0.7, 1).normalize();      // standard isometric-ish

    this.camera.position.copy(center).addScaledVector(dir, dist * 1.5);
    this.camera.near = Math.max(0.01, dist / 1000);
    this.camera.far = Math.max(dist * 100, 1e5);
    this.camera.updateProjectionMatrix();
    this.controls.target.copy(center);
    this.controls.update();

    // Helpers were used during 1.5.x debugging to verify the renderer +
    // recentering math; now removed for production. If a viewer issue
    // resurfaces, re-enable a small AxesHelper for diagnostics.
    if (this._helpersGroup) {
      this.scene.remove(this._helpersGroup);
      this._helpersGroup = null;
    }

    this.diagnostics = this.diagnostics || {};
    this.diagnostics.bboxEmpty = isEmpty;
    this.diagnostics.modelSize = `${size.x.toFixed(1)}×${size.y.toFixed(1)}×${size.z.toFixed(1)}`;
    this.diagnostics.modelCenter = `(${originalCenter.x.toFixed(0)}, ${originalCenter.y.toFixed(0)}, ${originalCenter.z.toFixed(0)})`;
    this.diagnostics.cameraDist = dist.toFixed(1);
    this.diagnostics.near = this.camera.near.toFixed(3);
    this.diagnostics.far = this.camera.far.toFixed(0);
    console.info('Viewer3D framing:', this.diagnostics);
  }

  _countTriangles() {
    let n = 0;
    this.modelGroup.traverse((o) => {
      if (o.isMesh && o.geometry) {
        const pos = o.geometry.attributes && o.geometry.attributes.position;
        if (!pos) return;
        const idx = o.geometry.index;
        n += idx ? Math.floor(idx.count / 3) : Math.floor(pos.count / 3);
      }
    });
    return n;
  }

  dispose() {
    this._disposed = true;
    window.removeEventListener('resize', this._onResize);
    if (this._resizeObserver) {
      this._resizeObserver.disconnect();
      this._resizeObserver = null;
    }
    if (this.renderer && this._onClick) {
      this.renderer.domElement.removeEventListener('click', this._onClick);
    }
    if (this.modelGroup) {
      this.modelGroup.traverse((o) => {
        if (o.geometry) o.geometry.dispose();
        if (o.material) {
          if (Array.isArray(o.material)) o.material.forEach((m) => m.dispose());
          else o.material.dispose();
        }
      });
    }
    if (this.renderer) {
      this.renderer.dispose();
      if (this.renderer.domElement.parentElement) {
        this.renderer.domElement.parentElement.removeChild(this.renderer.domElement);
      }
    }
  }
}
