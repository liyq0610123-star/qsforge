"""Tests for src/module3_3d_preview.py."""
from __future__ import annotations

from pathlib import Path

import pytest

import module3_3d_preview as m3


def test_run_returns_dict_with_expected_keys(fixtures_dir):
    result = m3.run(str(fixtures_dir / "tiny.dae"))
    assert isinstance(result, dict)
    assert "dae_path" in result
    assert "element_count" in result
    assert "has_element_ids" in result
    assert "warnings" in result


def test_run_counts_elements_correctly(fixtures_dir):
    result = m3.run(str(fixtures_dir / "tiny.dae"))
    assert result["element_count"] == 5


def test_run_detects_numeric_node_names_as_element_ids(fixtures_dir):
    result = m3.run(str(fixtures_dir / "tiny.dae"))
    assert result["has_element_ids"] is True


def test_run_returns_dae_path_resolved_absolute(fixtures_dir):
    p = str(fixtures_dir / "tiny.dae")
    result = m3.run(p)
    assert Path(result["dae_path"]).is_absolute()
    assert Path(result["dae_path"]).is_file()


def test_run_handles_missing_file_gracefully():
    result = m3.run("C:/does/not/exist.dae")
    assert result["dae_path"] is None
    assert result["element_count"] == 0
    assert result["has_element_ids"] is False
    assert any("not found" in w.lower() for w in result["warnings"])


def test_run_handles_malformed_dae_gracefully(fixtures_dir):
    result = m3.run(str(fixtures_dir / "malformed.dae"))
    assert result["dae_path"] is None
    assert result["element_count"] == 0
    assert result["has_element_ids"] is False
    assert any("parse" in w.lower() or "invalid" in w.lower()
               for w in result["warnings"])


def test_run_detects_when_node_names_are_not_element_ids(tmp_path):
    """If < 80% of nodes have numeric names, has_element_ids must be False."""
    dae = tmp_path / "weird.dae"
    dae.write_text('''<?xml version="1.0"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
  <library_visual_scenes><visual_scene id="s">
    <node id="a" name="WallStyle" type="NODE"/>
    <node id="b" name="FloorStyle" type="NODE"/>
    <node id="c" name="ColumnStyle" type="NODE"/>
    <node id="d" name="123456" type="NODE"/>
    <node id="e" name="654321" type="NODE"/>
  </visual_scene></library_visual_scenes>
</COLLADA>''')
    result = m3.run(str(dae))
    assert result["has_element_ids"] is False  # only 2/5 = 40% numeric


def test_run_handles_zero_nodes(tmp_path):
    """Valid COLLADA with no <node> elements: dae_path returned but no IDs."""
    dae = tmp_path / "empty.dae"
    dae.write_text(
        '<?xml version="1.0"?>'
        '<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1"/>'
    )
    result = m3.run(str(dae))
    assert result["element_count"] == 0
    assert result["has_element_ids"] is False
    # File parsed successfully, so dae_path is set (different from missing/malformed)
    assert result["dae_path"] is not None
    assert any("no <node>" in w.lower() for w in result["warnings"])


def test_run_never_raises_on_invalid_input_types():
    """Totality contract: passing bad input types must not raise."""
    for bad in (None, 0, [], {}, ""):
        result = m3.run(bad)  # type: ignore[arg-type]
        assert isinstance(result, dict)
        assert result["dae_path"] is None
        assert result["has_element_ids"] is False
