"""Module 3 — 3D Preview metadata.

Validates a DDC-produced COLLADA file and returns metadata the frontend
needs to render the 3D View tab. The actual rendering happens in the
browser via three.js + ColladaLoader; this module is purely a server-side
validator + element-count reporter.

Public API
----------
* :func:`run`  — returns ``{"dae_path", "element_count", "has_element_ids", "warnings"}``

The function is total: it never raises. Any error becomes a ``warnings``
entry and the result dict is shaped to indicate "3D not available" without
breaking the rest of the pipeline.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List

_log = logging.getLogger("qsforge.module3")


class Module3ConversionError(RuntimeError):
    """Raised when DAE→GLB conversion fails. Caught by ``run()``."""


# COLLADA's default namespace; element names in ET include this prefix.
_NS = "{http://www.collada.org/2005/11/COLLADASchema}"

# A DDC-emitted node name is recognised as an Element ID when it's all digits.
_NUMERIC_NAME = re.compile(r"^\d+$")

# Fraction of nodes that must have numeric names for us to claim
# "Element IDs are present". Below this, we disable problem-highlighting and
# click-inspection in the 3D viewer.
ELEMENT_ID_THRESHOLD = 0.80


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


def run(dae_path: str) -> Dict[str, Any]:
    """Validate a .dae file and return metadata for the frontend.

    Always returns a dict with the same keys; missing/broken files surface
    via ``warnings`` and the boolean/numeric fields default to "no 3D".

    Note on trust: the DAE is produced by the bundled DDC subprocess, not
    by user input. We deliberately don't use defusedxml — XXE / billion-laughs
    isn't part of our threat model since the file path comes from
    ``ddc_runner.run_ddc(...).with_suffix('.dae')`` (or a cache hit), never
    from a network request.
    """
    # Outermost safety net — the function MUST NOT raise. Any unforeseen
    # exception (TypeError on bad input, UnicodeDecodeError on a corrupt
    # encoding declaration, etc.) becomes a warning instead.
    try:
        warnings: List[str] = []

        if not isinstance(dae_path, (str, Path)) or not dae_path:
            return _empty_result("Invalid dae_path argument")

        p = Path(dae_path)
        if not p.is_file():
            return _empty_result(f"DAE file not found: {p}")

        # File size — used by the frontend to refuse loading models that
        # would OOM or freeze WebView2 during parse.
        try:
            file_size_bytes = p.stat().st_size
        except OSError:
            file_size_bytes = 0

        try:
            tree = ET.parse(str(p))
        except ET.ParseError as e:
            return _empty_result(f"Could not parse DAE (invalid XML): {e}")
        except OSError as e:
            return _empty_result(f"Could not read DAE: {e}")

        root = tree.getroot()
        # Find every <node> in any <visual_scene>. The fallback to a non-
        # namespaced findall handles malformed/non-standard DAE files that
        # omit the standard ``xmlns="http://www.collada.org/..."`` declaration.
        nodes = root.findall(f".//{_NS}node")
        if not nodes:
            nodes = root.findall(".//node")

        element_count = len(nodes)
        if element_count == 0:
            return {
                "dae_path": str(p.resolve()),
                "glb_path": None,
                "element_count": 0,
                "has_element_ids": False,
                "file_size_bytes": file_size_bytes,
                "warnings": ["DAE contains no <node> elements"],
            }

        # DDC v18 puts the Revit Element ID in the ``id`` attribute (e.g.
        # ``<node id="989990" name="node" ...>``). The ``name`` attribute is
        # the literal placeholder ``"node"`` for every element.
        # three.js's ColladaLoader sets ``mesh.name`` from the ``name``
        # attribute, so we'd lose the Element ID. Detect this case and
        # post-process the file to copy ``id`` into ``name`` so the viewer's
        # standard click-pick + element-map logic works.
        numeric_names = sum(
            1 for n in nodes
            if _NUMERIC_NAME.match((n.get("name") or "").strip())
        )
        if numeric_names / element_count >= ELEMENT_ID_THRESHOLD:
            has_element_ids = True
        else:
            # Try the `id` attribute. If most nodes have numeric ids,
            # patch the file in place so the viewer can use them.
            numeric_ids = sum(
                1 for n in nodes
                if _NUMERIC_NAME.match((n.get("id") or "").strip())
            )
            if numeric_ids / element_count >= ELEMENT_ID_THRESHOLD:
                _patch_dae_id_to_name(p, warnings)
                has_element_ids = True
            else:
                has_element_ids = False
                warnings.append(
                    f"Only {numeric_names}/{element_count} nodes have numeric names "
                    f"and {numeric_ids}/{element_count} have numeric ids; "
                    "click-inspection and problem-highlighting will be disabled."
                )

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
    except Exception as e:
        # Totality safety net. We catch everything because callers (the
        # server pipeline) treat M3 as additive — no M3 failure may break
        # M0/M1/M2 results.
        return _empty_result(f"Unexpected error in module3_3d_preview.run: {e}")


def _patch_dae_id_to_name(path: Path, warnings: List[str]) -> None:
    """Rewrite each ``<node id="<id>" name="node" ...>`` so ``name="<id>"``.

    DDC v18's COLLADA output uses ``id`` for the Element ID and a literal
    ``name="node"`` placeholder. three.js's ColladaLoader propagates ``name``
    to ``mesh.name``, so we'd lose the ID. Patching in place is the simplest
    fix — does it once per analysis at validation time and the file becomes
    self-describing for any subsequent reads.

    Uses a streaming regex rewrite (not full XML re-parse) because typical
    DAE files are 50–300 MB and full ET reserialization is slow.
    """
    import re as _re
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        warnings.append(f"DAE id→name patch skipped (could not re-read file): {e}")
        return

    # Match <node id="<digits>" name="<anything>" — replace the name value
    # with the id value. Conservative: only act on numeric ids.
    pattern = _re.compile(r'(<node\b[^>]*?\bid=")(\d+)("[^>]*?\bname=")[^"]*(")')
    new_text, n_subs = pattern.subn(r'\1\2\3\2\4', text)

    # Also catch the rarer attribute order: name first, then id.
    pattern2 = _re.compile(r'(<node\b[^>]*?\bname=")[^"]*("[^>]*?\bid=")(\d+)(")')
    new_text, n_subs2 = pattern2.subn(r'\1\3\2\3\4', new_text)

    total = n_subs + n_subs2
    if total == 0:
        warnings.append("DAE id→name patch made no substitutions (unexpected format).")
        return
    try:
        path.write_text(new_text, encoding="utf-8")
        warnings.append(f"Patched {total:,} <node> tags: id → name (Element IDs now visible to viewer).")
    except OSError as e:
        warnings.append(f"DAE id→name patch could not write file: {e}")


def _convert_dae_to_glb(dae_path: Path) -> Path:
    """Convert ``dae_path`` to GLB next to the source. Returns the GLB path.

    Imports trimesh lazily so the module remains importable even if trimesh
    is missing (CI without the dep, dev sandbox, etc.). The frozen EXE always
    has trimesh bundled — see qsforge.spec hidden imports.

    Raises Module3ConversionError on any conversion failure with the
    underlying exception message attached.
    """
    glb_path = dae_path.with_suffix(".glb")
    if not dae_path.is_file():
        raise Module3ConversionError(f"DAE not found: {dae_path}")
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

    # Re-bind Revit element IDs from the source DAE onto scene geometries.
    #
    # DDC's COLLADA structure is many-to-one: a single Revit element ID can
    # reference multiple <geometry> blocks via separate <node> entries that
    # each carry the same `name` attribute. Example for element 1473185:
    #     <node name="1473185"><instance_geometry url="#shape5-lib"/></node>
    #     <node name="1473185"><instance_geometry url="#shape6-lib"/></node>
    #     ... (six shapes for that one element)
    #
    # trimesh's DAE loader keys scene.geometry by the underlying <geometry id>
    # (e.g. "shape5-lib") AND names every scene.graph node the same way,
    # losing the Revit element ID entirely. We walk the DAE's <visual_scene>
    # once and build a shape_id → element_id map, then rebuild BOTH
    # scene.geometry AND scene.graph so the GLB carries element IDs as both
    # mesh names and glTF node names. (glTF node names are what GLTFLoader
    # surfaces as Object3D.name in three.js — that's what the viewer's
    # element map keys on.)
    #
    # Collisions (multiple shapes mapping to the same element) get a numeric
    # suffix — "1473185", "1473185_1", "1473185_2" — so all geometry survives
    # the rename. The viewer (viewer3d.js) strips the suffix when matching
    # severity / metadata so picking and highlighting still work.
    try:
        import xml.etree.ElementTree as _ET
        _ns = {"c": "http://www.collada.org/2005/11/COLLADASchema"}
        tree = _ET.parse(str(dae_path))

        # Step 1: build shape_id → element_id from the visual_scene.
        shape_to_element: Dict[str, str] = {}
        for n in tree.getroot().findall(".//c:visual_scene//c:node", _ns):
            name = (n.get("name") or "").strip()
            if not (name and _NUMERIC_NAME.match(name)):
                raw_id = (n.get("id") or "").strip()
                if raw_id.startswith("element_"):
                    raw_id = raw_id[len("element_"):]
                if _NUMERIC_NAME.match(raw_id):
                    name = raw_id
                else:
                    continue
            for ig in n.findall("c:instance_geometry", _ns):
                url = (ig.get("url") or "").strip().lstrip("#")
                if url and url not in shape_to_element:
                    # First occurrence wins. DDC sometimes emits dangling
                    # <instance_geometry url="#shapeN-lib"/> references where
                    # no matching <geometry id="shapeN-lib"> exists; those
                    # simply never match a scene.geometry key, which is fine.
                    shape_to_element[url] = name

        # Step 2: pick a new key for every existing geometry, suffixing
        # collisions so we don't drop any meshes.
        seen_counts: Dict[str, int] = {}
        old_to_new: Dict[str, str] = {}
        for old_key in list(scene.geometry.keys()):
            new_base = shape_to_element.get(old_key)
            if not new_base:
                old_to_new[old_key] = old_key
                continue
            count = seen_counts.get(new_base, 0)
            new_key = new_base if count == 0 else f"{new_base}_{count}"
            seen_counts[new_base] = count + 1
            old_to_new[old_key] = new_key

        # Step 3: rename in scene.geometry.
        renamed_geom = 0
        for old_key, new_key in old_to_new.items():
            if new_key != old_key and old_key in scene.geometry and new_key not in scene.geometry:
                scene.geometry[new_key] = scene.geometry.pop(old_key)
                renamed_geom += 1

        # Step 4: rebuild scene.graph so glTF node names also become the
        # element IDs. (trimesh keys nodes by `frame_to` in its edge list,
        # and the GLB exporter uses these names verbatim as glTF node names.)
        edgelist = list(scene.graph.to_edgelist())
        new_edges = []
        for frame_from, frame_to, data in edgelist:
            new_frame_to = old_to_new.get(frame_to, frame_to)
            new_data = dict(data)
            if "geometry" in new_data:
                new_data["geometry"] = old_to_new.get(
                    new_data["geometry"], new_data["geometry"]
                )
            new_edges.append([frame_from, new_frame_to, new_data])
        scene.graph.clear()
        scene.graph.from_edgelist(new_edges)

        _log.info(
            "Element-ID rebind: %d/%d geometries renamed (%d unique element IDs)",
            renamed_geom, len(scene.geometry), len(seen_counts),
        )
    except Exception as e:
        _log.warning("Could not re-bind DAE node names onto GLB: %s", e)

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
