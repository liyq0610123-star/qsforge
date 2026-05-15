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
