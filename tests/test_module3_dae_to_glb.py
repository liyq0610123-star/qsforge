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
