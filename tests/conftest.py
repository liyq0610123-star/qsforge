"""Shared pytest fixtures for QSForge test suite."""
from __future__ import annotations

import sys
from pathlib import Path

# Make src/ importable so tests can `import cache`, `import module3_3d_preview`
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


import pytest


@pytest.fixture
def tmp_rvt(tmp_path) -> Path:
    """Create a fake .rvt file with deterministic size (~14 KB).

    Note: mtime is set by the OS at write time and is NOT controlled here.
    Tests that need a specific mtime should call ``os.utime`` on the
    returned path explicitly.
    """
    rvt = tmp_path / "model.rvt"
    rvt.write_bytes(b"FAKE_RVT_BYTES" * 1000)  # ~14 KB
    return rvt


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to the static fixtures directory."""
    return Path(__file__).resolve().parent / "fixtures"
