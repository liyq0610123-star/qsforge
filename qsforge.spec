# -*- mode: python ; coding: utf-8 -*-
"""
QSForge — PyInstaller build spec.

Build:
    pyinstaller --noconfirm --clean qsforge.spec

Output:
    dist/QSForge/QSForge.exe   (one-folder build — faster startup than --onefile)
    dist/QSForge/static/       (bundled UI)

One-folder is deliberate: onefile would extract ~100+ DLLs to %TEMP% on every
launch. One-folder starts fast, is easier to antivirus-whitelist, and lets the
user see last_result.json / exported PDFs next to the .exe.

External dependency not bundled at PyInstaller level (we copy DDC post-build
in build.ps1):
    RvtExporter.exe (DDC) — runtime override with QSFORGE_DDC_EXE.
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

PROJECT = Path(SPECPATH)

datas = [
    (str(PROJECT / "static"), "static"),
    (str(PROJECT / "assets"), "assets"),
    # Explicit fonts entry — guarantees PyInstaller bundles the large .otf
    # files even if `collect_data_files` heuristics ever change.
    (str(PROJECT / "assets" / "fonts"), "assets/fonts"),
    # Bundle the LICENSE + third-party notices so the installed app can show them.
    (str(PROJECT / "LICENSE"), "."),
    (str(PROJECT / "THIRD-PARTY-NOTICES.md"), "."),
]
datas += collect_data_files("reportlab")

hiddenimports = []
hiddenimports += collect_submodules("webview.platforms")
hiddenimports += collect_submodules("reportlab.pdfbase")
hiddenimports += collect_submodules("pandas")
hiddenimports += [
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "openpyxl.cell._writer",
    "clr_loader",
    "ad_blocker",
    "pandas._libs.tslibs.np_datetime",
    "pandas._libs.tslibs.nattype",
    "pandas._libs.tslibs.timedeltas",
    "pandas._libs.skiplist",
]

block_cipher = None


a = Analysis(
    ["main.py"],
    pathex=[str(PROJECT), str(PROJECT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "numpy.distutils",
        "pytest",
        "sphinx",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="QSForge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT / "assets" / "qsforge.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="QSForge",
)
