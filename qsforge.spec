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
# pycollada (PyPI name) imports as `collada` (no "py" prefix). It ships
# its COLLADA XSDs (schema-1.4.1.xml, xsd.xml) under collada/resources/.
# Without this, trimesh's collada-backed DAE loader raises
# FileNotFoundError at runtime in the frozen build and Module 3 falls
# back to "3D preview unavailable" (caught the hard way during 1.0.1
# testing — the spec had the wrong package name and the schema was never
# bundled). collect_data_files walks the installed package and bundles
# every non-.py file (including the XSDs we need at runtime).
datas += collect_data_files("collada")
# trimesh has its own resource bundle (.json shaders, example primitives,
# etc.). Most aren't on the DAE→GLB code path but bundling them costs
# <1 MB and removes a class of "works in dev, breaks in frozen" surprises.
datas += collect_data_files("trimesh")

hiddenimports = []
hiddenimports += collect_submodules("webview.platforms")
hiddenimports += collect_submodules("reportlab.pdfbase")
hiddenimports += collect_submodules("pandas")
# trimesh imports its format backends lazily based on the input file
# extension, so PyInstaller's static analysis misses most of them.
# Same goes for pycollada's submodules (collada.geometry, collada.scene,
# collada.schema, collada.xmlutil, ...) — trimesh's DAE loader pulls
# them lazily as it parses the file.
hiddenimports += collect_submodules("trimesh")
hiddenimports += collect_submodules("collada")
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
    "waitress",
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
