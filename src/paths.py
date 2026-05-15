"""
QSForge - Path helpers

Works transparently in two modes:
  * running from source  (`python main.py`)  — paths live inside the project.
  * running as a frozen PyInstaller `.exe`    — bundled assets come out of
    the PyInstaller temp dir (``sys._MEIPASS``) while writable files live
    next to the .exe so users can find them without digging into %TEMP%.
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """True when running from a PyInstaller-built executable."""
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """
    Read-only bundled assets (``static/``, future templates, etc.).
    In frozen mode this is the PyInstaller extraction directory.
    """
    if is_frozen():
        # PyInstaller sets _MEIPASS when the bootloader extracts resources.
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def user_data_dir() -> Path:
    """
    Writable directory for runtime artefacts (``last_result.json``, exported
    PDFs, the WebView2 profile, log dumps). Persists across runs.

    * Frozen → folder sitting next to the .exe. Visible, deletable, no admin
      needed. Makes it easy for QS to locate the PDF / JSON after a run.
    * Source → the project folder, so development behaviour is unchanged.
    """
    if is_frozen():
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent.parent
    base.mkdir(parents=True, exist_ok=True)
    return base
