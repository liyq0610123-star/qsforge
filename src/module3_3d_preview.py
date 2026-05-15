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

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List

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

        return {
            "dae_path": str(p.resolve()),
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
