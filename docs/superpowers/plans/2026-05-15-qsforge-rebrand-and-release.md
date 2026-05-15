# QSForge 1.0.0 — Rebrand & First Public Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebrand the local-only `ArchiQS 1.6.0` project to `QSForge` and ship a polished `QSForge 1.0.0` as the first public release on GitHub.

**Architecture:** Sequential phases — foundations (gitignore, license) → blockers that survive the rename (B4 dev-path purge, B2 encoding) → bulk rebrand (B7, every file) → behavioural fixes (B3 fonts, H3 logging) → release wiring (B1 manifest) → docs → build, verify, release.

**Tech Stack:** Python 3.12, Flask, PyWebView, openpyxl, pandas, reportlab, PyInstaller, Inno Setup 6, PowerShell 5.1 / 7+, git, GitHub Releases.

**Spec:** `docs/superpowers/specs/2026-05-15-qsforge-rebrand-and-release-design.md`

**Working directory:** `C:\Archiqs\RVT Quality Check` (the repo dir name itself stays — only the *product* name changes).

**Convention for steps:**
- All `git` commands assume the repo has been `git init`'d (Task 1 does that).
- Commit subjects use **Conventional Commits** (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`). Scope token after the colon names the area (e.g. `feat(updater): …`).
- Commit messages do **NOT** include any `Co-Authored-By` footer — this is the user's repo, not Claude-generated work.
- For "verify zero hits" steps, the engineer uses **Grep tool** (ripgrep under the hood) rather than literal `rg`/`grep` commands.

---

## Phase 1 — Foundations

### Task 1: Initialize git repository with a clean `.gitignore`

**Files:**
- Create: `.gitignore`

The repo currently has no `.git/`. We add `.gitignore` **before** the first commit so the 818 MB `dist/`, 167 MB test `.rvt`, and runtime droppings never enter history.

- [ ] **Step 1: Write `.gitignore`**

Replace any existing `.gitignore` with this content:

```gitignore
# ── Python ──────────────────────────────────────────────────────────────────
__pycache__/
*.py[cod]
*$py.class
.pytest_cache/
.mypy_cache/
.ruff_cache/

# ── Virtualenvs ─────────────────────────────────────────────────────────────
venv/
.venv/
env/
ENV/

# ── Build outputs ───────────────────────────────────────────────────────────
build/
dist/
installer/output/
installer/version.iss
*.spec.bak
build_log*.txt

# ── Runtime droppings (next to the EXE in frozen builds) ────────────────────
.webview-data/
last_result.json
qsforge_crash.log
qsforge_rvtexporter_last.txt
archiqs_crash.log
archiqs_rvtexporter_last.txt
*.log

# ── Test fixtures too large for GitHub (>100 MB hard limit) ─────────────────
tests/*.rvt
tests/last_result.json

# ── Cleanup staging ─────────────────────────────────────────────────────────
_to_delete/

# ── IDE / OS ────────────────────────────────────────────────────────────────
.vscode/
.idea/
.cursorrules
.superpowers/
.DS_Store
Thumbs.db
desktop.ini
```

- [ ] **Step 2: Initialise the repo**

Run in PowerShell:

```powershell
git init
git config core.autocrlf true
```

Expected: `Initialized empty Git repository`.

- [ ] **Step 3: Verify `.gitignore` is doing its job**

Run:

```powershell
git status
```

Expected: no files larger than 1 MB appear in the "Untracked files" list. **Crucial check** — look at the output and confirm none of these paths show up:
- `dist/`
- `installer/output/`
- `.webview-data/`
- `tests/TIO (Beam Furring, Lift Pit)_detached.rvt`
- `last_result.json`
- `build_log_1.6.0.txt`

If any of them appear, the `.gitignore` is wrong — fix before continuing.

- [ ] **Step 4: Commit just the gitignore**

```powershell
git add .gitignore
git commit -m "chore: add .gitignore for QSForge"
```

---

### Task 2: Add MIT `LICENSE` and `THIRD-PARTY-NOTICES.md`

**Files:**
- Create: `LICENSE`
- Create: `THIRD-PARTY-NOTICES.md`

- [ ] **Step 1: Write `LICENSE` (root of repo)**

Standard MIT text:

```text
MIT License

Copyright (c) 2026 liyq0610123-star

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 2: Write `THIRD-PARTY-NOTICES.md`**

```markdown
# Third-Party Notices

QSForge bundles, links to, or otherwise redistributes the following third-party
components. Their respective licenses are reproduced or linked below.

## Python runtime dependencies

| Component | License | Project URL |
|---|---|---|
| Flask | BSD-3-Clause | https://palletsprojects.com/p/flask/ |
| Werkzeug | BSD-3-Clause | https://palletsprojects.com/p/werkzeug/ |
| Jinja2 | BSD-3-Clause | https://palletsprojects.com/p/jinja/ |
| MarkupSafe | BSD-3-Clause | https://palletsprojects.com/p/markupsafe/ |
| itsdangerous | BSD-3-Clause | https://palletsprojects.com/p/itsdangerous/ |
| click | BSD-3-Clause | https://palletsprojects.com/p/click/ |
| pywebview | BSD-3-Clause | https://pywebview.flowrl.com/ |
| openpyxl | MIT | https://openpyxl.readthedocs.io/ |
| pandas | BSD-3-Clause | https://pandas.pydata.org/ |
| numpy | BSD-3-Clause | https://numpy.org/ |
| reportlab | BSD-3-Clause | https://www.reportlab.com/opensource/ |
| matplotlib | Matplotlib License (PSF-based) | https://matplotlib.org/ |
| lxml | BSD-3-Clause | https://lxml.de/ |
| pyarrow | Apache-2.0 | https://arrow.apache.org/ |
| pyreadline3 | BSD-3-Clause | https://github.com/pyreadline3/pyreadline3 |
| pyinstaller | GPLv2 with bootloader exception (output not GPL-encumbered) | https://pyinstaller.org/ |

## Fonts

| Component | License | Project URL |
|---|---|---|
| Noto Sans CJK SC (Regular + Bold) | SIL Open Font License 1.1 (OFL-1.1) | https://github.com/notofonts/noto-cjk |

## External tooling redistributed in `vendor/`

| Component | Notes |
|---|---|
| DDC RvtExporter (datadrivenconstruction.io) | Bundled under `vendor/ddc/`. See `vendor/ddc/LICENSE` (preserved from upstream). **QSForge maintainers must confirm DDC's license permits redistribution inside an MIT-licensed product before each release.** If at any time the DDC license changes and forbids redistribution, the build switches to a first-launch downloader and DDC is no longer shipped inside the installer. |

## Full license text

The full text of each license above can be found in the upstream project. The
MIT License covering QSForge itself is at `LICENSE` in this repository.
```

- [ ] **Step 3: Commit**

```powershell
git add LICENSE THIRD-PARTY-NOTICES.md
git commit -m "chore: add MIT LICENSE and THIRD-PARTY-NOTICES"
```

---

## Phase 2 — Pre-rename blocker fixes

These two fixes target lines that the rebrand will rewrite. Doing them **before** the rebrand keeps each commit focused (the rebrand commit is a pure rename; this one is a security/correctness fix).

### Task 3: Remove dev username and hardcoded paths (B4)

**Files:**
- Modify: `src/ddc_runner.py:261-265`
- Modify: `build.ps1:25-28`

- [ ] **Step 1: Replace `DEFAULT_DDC_EXE` in `ddc_runner.py`**

Replace lines 259-265:

```python
# Dev-time fallback — only hit when neither a bundled copy nor the env var are
# present. It is the location where DDC lives on the original dev machine.
DEFAULT_DDC_EXE = (
    r"C:\Users\11390\Desktop\cad2data-Revit-IFC-DWG-DGN-main"
    r"\cad2data-Revit-IFC-DWG-DGN-main\DDC_WINDOWS_Converters"
    r"\DDC_CONVERTER_REVIT\RvtExporter.exe"
)
```

with:

```python
# Dev-time fallback. We deliberately do not hardcode a path — any developer
# running from source either bundles DDC under vendor/ddc/ or sets the
# QSFORGE_DDC_EXE environment variable.
DEFAULT_DDC_EXE = None
```

- [ ] **Step 2: Confirm `ddc_runner.py` handles `None` at the call site**

Use Grep to find every reference to `DEFAULT_DDC_EXE` in `src/ddc_runner.py`. For each call site that previously assumed a string, ensure it handles `None` — typically by treating `None` as "no fallback configured, give the user a clear error".

If any site does `Path(DEFAULT_DDC_EXE)` directly, wrap with `if DEFAULT_DDC_EXE is None: raise <clear error>` or simply skip that branch.

- [ ] **Step 3: Replace `$DdcSource` default in `build.ps1`**

Find this block (lines 25-28):

```powershell
    [string]$DdcSource = $(
        if ($env:ARCHIQS_DDC_SOURCE) { $env:ARCHIQS_DDC_SOURCE }
        else { "C:\Users\11390\Desktop\cad2data-Revit-IFC-DWG-DGN-main\cad2data-Revit-IFC-DWG-DGN-main\DDC_WINDOWS_Converters\DDC_CONVERTER_REVIT" }
    ),
```

Replace with (note the env var name change to `QSFORGE_DDC_SOURCE` — that's part of the rebrand, but rolled in now):

```powershell
    # DDC source folder. Set $env:QSFORGE_DDC_SOURCE or pass -DdcSource explicitly.
    # If empty, the build will skip DDC bundling and warn the user.
    [string]$DdcSource = $(
        if ($env:QSFORGE_DDC_SOURCE) { $env:QSFORGE_DDC_SOURCE }
        else { "" }
    ),
```

And update the "DDC source folder not found" warning block (around line 127-132) so the empty case is handled gracefully:

```powershell
    if (-not $DdcSource -or -not (Test-Path $DdcSource)) {
        Write-Host ""
        Write-Host "WARNING: No DDC source folder — skipping DDC bundling." -ForegroundColor Yellow
        if (-not $DdcSource) {
            Write-Host "  Set `$env:QSFORGE_DDC_SOURCE or pass -DdcSource 'D:\path\to\DDC_CONVERTER_REVIT'."
        } else {
            Write-Host ("  Looked for: {0}" -f $DdcSource)
        }
        Write-Host "  Users will need DDC installed separately or QSFORGE_DDC_EXE set."
    } else {
```

(Adjust the surrounding `else` block accordingly — see existing structure.)

- [ ] **Step 4: Verify no `11390` or hardcoded `C:\Users\` remains in source**

Use Grep across `src/`, `installer/`, `tools/`, `build.ps1`, `main.py`, and `archiqs.spec` for `11390`. Expected hits: **zero** in source files (matches in `.cursorrules`, `.claude/`, `last_result.json`, `.webview-data/`, `build_log_1.6.0.txt` are fine — they're ignored by git or one-time runtime artefacts).

- [ ] **Step 5: Commit**

```powershell
git add src/ddc_runner.py build.ps1
git commit -m "fix: remove hardcoded developer path and username (B4)"
```

---

### Task 4: Fix PowerShell encoding to eliminate mojibake (B2)

**Files:**
- Modify: `build.ps1` (top of file + `version.iss` write line)

- [ ] **Step 1: Force UTF-8 encoding at top of `build.ps1`**

Immediately after the `param(...)` block and before `$ErrorActionPreference = "Stop"`, insert:

```powershell
# Force UTF-8 for stdout and for native exe arg passing. Without this,
# PowerShell 5.x defaults to the system ANSI code page, which produces
# mojibake in any Chinese strings written by this script (e.g. PDF
# filenames, version.iss header text). The Console.OutputEncoding line
# matters for `Write-Host` output ending up readable in CI logs.
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
```

- [ ] **Step 2: Fix the `version.iss` write**

Find the existing `Set-Content -Path $genIss -Value $genBody -Encoding UTF8 -NoNewline` line (around line 244). Replace with:

```powershell
# Inno Setup's #include reads the file via its own preprocessor. UTF-8 *with*
# BOM is what Inno Setup 6 expects for non-ASCII content; without the BOM it
# falls back to the system code page on some systems.
[System.IO.File]::WriteAllText($genIss, $genBody, [System.Text.UTF8Encoding]::new($true))
```

- [ ] **Step 3: Re-save `build.ps1` itself as UTF-8 with BOM**

PowerShell 5.x will only honour non-ASCII characters in a script if the script file has a UTF-8 BOM. In PowerShell:

```powershell
$content = Get-Content -Path build.ps1 -Raw -Encoding UTF8
[System.IO.File]::WriteAllText((Resolve-Path build.ps1), $content, [System.Text.UTF8Encoding]::new($true))
```

Verify the BOM is present:

```powershell
$bytes = [System.IO.File]::ReadAllBytes((Resolve-Path build.ps1))[0..2]
$bytes -join ','   # expect 239,187,191
```

- [ ] **Step 4: Commit**

```powershell
git add build.ps1
git commit -m "fix(build): force UTF-8 encoding in PowerShell script (B2)"
```

---

## Phase 3 — The rebrand (B7)

The rename is split into one task per file/area so each commit stays reviewable. Every task verifies with a grep at the end. We're doing **exact-case replacements** in three forms simultaneously where it makes sense:

- `ArchiQS` → `QSForge` (display name, comments, log strings)
- `ARCHIQS` → `QSFORGE` (env vars, constant names)
- `archiqs` → `qsforge` (filenames, paths, JSON keys)

### Task 5: Rebrand `src/_version.py`

**Files:**
- Modify: `src/_version.py`

- [ ] **Step 1: Replace `src/_version.py` entirely**

```python
"""
QSForge — Single source of truth for version numbers and update channel.

Why one file
-------------
Every other place that needs a version (Inno Setup script, Flask /api/version
endpoint, the about dialog, the update manifest comparator) reads from here
so we can bump the version in exactly one location at release time.

How to release a new version
----------------------------
1. Bump QSFORGE_VERSION below.
2. If a new DDC build is also being shipped, bump DDC_BUNDLED_VERSION.
3. Run ``.\build.ps1`` — the installer script picks up the new version
   automatically (see installer\\qsforge.iss).
4. Upload the produced ``QSForge-Setup-<ver>.exe`` to GitHub Releases under
   tag ``v<ver>`` and upload ``manifest.json`` alongside it.

Update channel
--------------
The default points at the public GitHub Releases manifest. Override at
runtime via the ``QSFORGE_UPDATE_MANIFEST_URL`` environment variable. Set
that env var to an empty string to disable update checks (air-gapped use).
"""

from __future__ import annotations

import os

# Public version of the QSForge desktop app.
QSFORGE_VERSION = "1.0.0"

# Version of DDC bundled inside this build's ``vendor\ddc\`` folder.
DDC_BUNDLED_VERSION = "18.1.0"

# Default update manifest URL — published to the same GitHub Release that
# hosts the installer EXE.
DEFAULT_MANIFEST_URL = (
    "https://github.com/liyq0610123-star/qsforge/"
    "releases/latest/download/manifest.json"
)


def manifest_url() -> str:
    """Return the active manifest URL, or empty string when checks are disabled."""
    env = os.environ.get("QSFORGE_UPDATE_MANIFEST_URL")
    if env is None:
        return DEFAULT_MANIFEST_URL
    return env.strip()


def update_checks_enabled() -> bool:
    """True when we should attempt to fetch the manifest."""
    return bool(manifest_url())
```

- [ ] **Step 2: Verify no `ArchiQS` or `ARCHIQS` survives in `_version.py`**

Use Grep on `src/_version.py` for `ArchiQS|ARCHIQS|archiqs`. Expected: **zero hits**.

- [ ] **Step 3: Commit**

```powershell
git add src/_version.py
git commit -m "refactor(version): rename ArchiQS -> QSForge, reset to 1.0.0 (B7)"
```

---

### Task 6: Rebrand `main.py` (crash log filename + AppUserModelID)

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Read `main.py`** and apply these exact replacements (use Edit tool with replace_all where the string is unique enough):

| Old | New |
|---|---|
| `ArchiQS - Desktop entry point.` | `QSForge - Desktop entry point.` |
| `APP_USER_MODEL_ID = "ArchiQS.Desktop.RVTQualityCheck.1"` | `APP_USER_MODEL_ID = "QSForge.Desktop.RVTQualityCheck.1"` |
| `"archiqs_crash.log"` | `"qsforge_crash.log"` |
| (every other) `ArchiQS` | `QSForge` |
| (every other) `archiqs` | `qsforge` |

For mass replacement of remaining literals, use Grep first to enumerate, then Edit on each occurrence (or `replace_all` if the literal is unambiguous).

- [ ] **Step 2: Verify**

Grep `main.py` for `ArchiQS|ARCHIQS|archiqs`. Expected: zero hits.

- [ ] **Step 3: Commit**

```powershell
git add main.py
git commit -m "refactor(main): rename ArchiQS -> QSForge (B7)"
```

---

### Task 7: Rebrand `src/updater.py`

**Files:**
- Modify: `src/updater.py`

- [ ] **Step 1: Read `src/updater.py`** and apply these replacements:

| Old | New |
|---|---|
| `ArchiQS - Update mechanism` | `QSForge - Update mechanism` |
| `_version.ARCHIQS_VERSION` | `_version.QSFORGE_VERSION` |
| `_USER_AGENT = f"ArchiQS-Updater/...` | `_USER_AGENT = f"QSForge-Updater/{_version.QSFORGE_VERSION} (Windows; +manifest)"` |
| `COMPONENT_ARCHIQS = "archiqs"` | `COMPONENT_QSFORGE = "qsforge"` |
| `KNOWN_COMPONENTS = (COMPONENT_ARCHIQS, COMPONENT_DDC)` | `KNOWN_COMPONENTS = (COMPONENT_QSFORGE, COMPONENT_DDC)` |
| Every other `COMPONENT_ARCHIQS` reference | `COMPONENT_QSFORGE` |
| `ArchiQS-Setup-` (filename pattern in installer matching) | `QSForge-Setup-` |
| `archiqs` (JSON manifest top-level key) | `qsforge` |
| Every other display-name `ArchiQS` | `QSForge` |

- [ ] **Step 2: Verify**

Grep `src/updater.py` for `ArchiQS|ARCHIQS|archiqs`. Expected: zero hits.

- [ ] **Step 3: Commit**

```powershell
git add src/updater.py
git commit -m "refactor(updater): rename ArchiQS -> QSForge, manifest key archiqs -> qsforge (B7)"
```

---

### Task 8: Rebrand `src/ddc_runner.py` (env var + log filename)

**Files:**
- Modify: `src/ddc_runner.py`

- [ ] **Step 1: Apply replacements:**

| Old | New |
|---|---|
| `ARCHIQS_DDC_EXE` (env var name) | `QSFORGE_DDC_EXE` |
| `ARCHIQS_DDC_TIMEOUT_SEC` (env var name) | `QSFORGE_DDC_TIMEOUT_SEC` |
| `ARCHIQS_DDC_SOURCE` (env var name, if present) | `QSFORGE_DDC_SOURCE` |
| `"archiqs_rvtexporter_last.txt"` | `"qsforge_rvtexporter_last.txt"` |
| `.archiqs-ddc-version` (DDC version marker filename) | `.qsforge-ddc-version` |
| Every other `ArchiQS` / `archiqs` | `QSForge` / `qsforge` |

- [ ] **Step 2: Verify**

Grep `src/ddc_runner.py` for `ArchiQS|ARCHIQS|archiqs`. Expected: zero hits.

- [ ] **Step 3: Commit**

```powershell
git add src/ddc_runner.py
git commit -m "refactor(ddc): rename env vars + log filenames to QSFORGE_*/qsforge_* (B7)"
```

---

### Task 9: Rebrand remaining `src/*.py` modules

**Files:**
- Modify: `src/server.py`
- Modify: `src/paths.py`
- Modify: `src/pdf_report.py`
- Modify: `src/ad_blocker.py`
- Modify: `src/cache.py`
- Modify: `src/scoring.py`
- Modify: `src/module0_inventory.py`
- Modify: `src/module1_qs_readiness.py`
- Modify: `src/module2_bq_draft.py`
- Modify: `src/module2_checks.py`
- Modify: `src/module3_3d_preview.py`
- Modify: `src/__init__.py`

For each file:

- [ ] **Step 1:** Read the file, then use Edit with `replace_all=true` for each form:
  - `ArchiQS` → `QSForge`
  - `ARCHIQS` → `QSFORGE` (only constants/env var names — confirm none of these are intentional)
  - `archiqs` → `qsforge`

  Be careful with mixed-case substring collisions. Specifically:
  - `archiqs_ddc_version` → `qsforge_ddc_version` (variable names)
  - `archiqs_crash.log` → `qsforge_crash.log`
  - `archiqs_rvtexporter_last.txt` → `qsforge_rvtexporter_last.txt`

- [ ] **Step 2: Grep the entire `src/` tree**

Use Grep across `src/` for `ArchiQS|ARCHIQS|archiqs`. Expected: zero hits.

- [ ] **Step 3: Sanity-import test**

```powershell
python -c "import sys; sys.path.insert(0,'src'); import server, paths, _version, ddc_runner, updater, pdf_report, ad_blocker, cache, scoring, module0_inventory, module1_qs_readiness, module2_bq_draft, module2_checks, module3_3d_preview; print('All modules import OK')"
```

Expected: `All modules import OK`.

- [ ] **Step 4: Commit**

```powershell
git add src/
git commit -m "refactor(src): rename ArchiQS -> QSForge across all modules (B7)"
```

---

### Task 10: Rebrand `static/index.html`

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1: Read `static/index.html`**

There are ~26 occurrences. Look for the `<title>`, header logo text, About-dialog content, and footer copy.

- [ ] **Step 2: Replace** all `ArchiQS` → `QSForge` and `archiqs` → `qsforge` (use Edit `replace_all` for each form).

- [ ] **Step 3: Verify**

Grep `static/index.html` for `ArchiQS|archiqs`. Expected: zero hits.

- [ ] **Step 4: Also update `static/js/viewer3d.js`** (1 hit).

- [ ] **Step 5: Commit**

```powershell
git add static/index.html static/js/viewer3d.js
git commit -m "refactor(ui): rename ArchiQS -> QSForge in frontend (B7)"
```

> Note: `static/vendor/three/ColladaLoader.js` has one hit — leave it alone (vendored upstream library, not our string).

---

### Task 11: Rebrand `tools/` scripts

**Files:**
- Modify: `tools/md_to_pdf.py`
- Modify: `tools/make_icon.py`
- Modify: `tools/block_ddc_ads.bat` (carefully — Windows batch file, ANSI-encoded)

- [ ] **Step 1: `tools/md_to_pdf.py`** — replace all `ArchiQS` → `QSForge` and `archiqs` → `qsforge`.

- [ ] **Step 2: `tools/make_icon.py`** — replace all `ArchiQS` → `QSForge` and `archiqs` → `qsforge`. Specifically, if the script writes to `assets/archiqs.ico`, update the output filename to `assets/qsforge.ico`.

- [ ] **Step 3: `tools/block_ddc_ads.bat`** — replace all `ArchiQS` → `QSForge`. Keep the file ANSI-encoded (Windows batch convention).

- [ ] **Step 4: Verify**

Grep `tools/` for `ArchiQS|archiqs`. Expected: zero hits.

- [ ] **Step 5: Commit**

```powershell
git add tools/
git commit -m "refactor(tools): rename ArchiQS -> QSForge in helper scripts (B7)"
```

---

### Task 12: Rebrand tests

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/test_cache.py`
- Modify: `tests/test_module3.py`

- [ ] **Step 1:** For each test file, replace `ArchiQS|archiqs|ARCHIQS` with the QSForge equivalent.

- [ ] **Step 2: Skip the large `.rvt` fixture if it's not available**

`tests/test_module3.py` likely depends on `tests/TIO (Beam Furring, Lift Pit)_detached.rvt`. The fixture is ignored by `.gitignore`. Add a graceful skip at the top of any test that requires it:

```python
import pytest
from pathlib import Path

_FIXTURE = Path(__file__).parent / "TIO (Beam Furring, Lift Pit)_detached.rvt"
if not _FIXTURE.exists():
    pytest.skip("Large RVT fixture not present (not committed to git)", allow_module_level=True)
```

(Adjust path if the fixture has a different name.)

- [ ] **Step 3: Run tests**

```powershell
python -m pytest tests/ -q
```

Expected: passing tests pass, missing-fixture tests skip with the message above. No failures from string renames.

- [ ] **Step 4: Commit**

```powershell
git add tests/
git commit -m "refactor(tests): rename ArchiQS -> QSForge; skip on missing RVT fixture (B7)"
```

---

### Task 13: Rebrand `updates/` manifest template

**Files:**
- Modify: `updates/manifest.example.json`
- Modify: `updates/README.md`

- [ ] **Step 1: Replace `updates/manifest.example.json`**

```json
{
  "_comment": "QSForge update manifest. Host this file at the URL configured in _version.py (DEFAULT_MANIFEST_URL) or in the QSFORGE_UPDATE_MANIFEST_URL env var. The QSForge desktop app fetches it on startup and from the in-app 'Updates' panel.",

  "qsforge": {
    "version": "1.0.0",
    "released_at": "2026-05-15",
    "installer_url": "https://github.com/liyq0610123-star/qsforge/releases/download/v1.0.0/QSForge-Setup-1.0.0.exe",
    "sha256": "REPLACE_WITH_SHA256_OF_THE_INSTALLER_EXE",
    "size_bytes": 0,
    "release_notes_url": "https://github.com/liyq0610123-star/qsforge/releases/tag/v1.0.0",
    "release_notes": "First public release of QSForge."
  },

  "ddc": {
    "version": "18.1.0",
    "released_at": "2026-05-15",
    "package_url": "https://github.com/liyq0610123-star/qsforge/releases/download/ddc-18.1.0/DDC-18.1.0.zip",
    "sha256": "REPLACE_WITH_SHA256_OF_THE_DDC_ZIP",
    "size_bytes": 0,
    "release_notes_url": "https://datadrivenconstruction.io/changelog",
    "release_notes": "Bundled DDC version."
  }
}
```

- [ ] **Step 2: Update `updates/README.md`**

Replace every `ArchiQS|archiqs` with the QSForge equivalent. The owner/repo placeholder becomes `liyq0610123-star/qsforge`.

- [ ] **Step 3: Verify**

Grep `updates/` for `ArchiQS|archiqs`. Expected: zero hits.

- [ ] **Step 4: Commit**

```powershell
git add updates/
git commit -m "refactor(updates): rename ArchiQS -> QSForge in manifest template (B7)"
```

---

### Task 14: Rename `archiqs.spec` → `qsforge.spec`

**Files:**
- Delete: `archiqs.spec`
- Create: `qsforge.spec`

- [ ] **Step 1: Create `qsforge.spec`**

Copy the contents of `archiqs.spec`, with these changes:

```python
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
```

(Task 18 will add `assets/fonts` to `datas` later — leave it out here so each commit is self-consistent.)

- [ ] **Step 2: Delete the old spec**

```powershell
Remove-Item archiqs.spec
```

- [ ] **Step 3: Commit**

```powershell
git add qsforge.spec
git rm archiqs.spec
git commit -m "refactor(build): rename archiqs.spec -> qsforge.spec, bundle LICENSE (B7)"
```

> The actual icon file `assets/archiqs.ico` is renamed in Task 17 — the spec references the new name in advance, but the build won't succeed until Task 17 lands. That's fine; we build at the end of the rebrand phase.

---

### Task 15: Rename and rewrite the Inno Setup installer

**Files:**
- Delete: `installer/archiqs.iss`
- Create: `installer/qsforge.iss`

- [ ] **Step 1: Generate a real, permanent AppId GUID**

This GUID **must never change** across versions — Windows uses it to recognise upgrades. Generate it once:

```powershell
[guid]::NewGuid().ToString().ToUpper()
```

Write the result down. Example output: `D8F2C1A3-9B47-4E5F-A6D8-0123456789AB`. (Yours will differ — use the actual output.)

- [ ] **Step 2: Create `installer/qsforge.iss`**

Replace the file content with (substitute your actual GUID where `<NEW-GUID>` appears):

```ini
; =============================================================================
;  QSForge — Inno Setup script
; =============================================================================
;  Builds QSForge-Setup-<version>.exe by packaging the PyInstaller output
;  folder (dist\QSForge\) into a self-contained Windows installer with:
;    * Start Menu entry + optional desktop shortcut
;    * Uninstaller in "Apps & features"
;    * Clean uninstall (also removes last_result.json, crash log, webview cache)
;    * No admin rights required — installs to the user's AppData by default
;
;  How to compile
;  --------------
;  1. Download Inno Setup 6 from https://jrsoftware.org/isdl.php  (free, MIT)
;  2. Build the app first:         pyinstaller --noconfirm --clean qsforge.spec
;  3. Compile this script:         "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\qsforge.iss
;  4. Output lands in:             installer\output\QSForge-Setup-<version>.exe
; =============================================================================

#define QSForgeName        "QSForge"
#ifexist "version.iss"
  #include "version.iss"
#endif
#ifndef QSForgeVersion
  #define QSForgeVersion   "1.0.0"
#endif
#define QSForgePublisher   "liyq0610123-star"
#define QSForgeAppId       "{{<NEW-GUID>}"
#define QSForgeExe         "QSForge.exe"
#define QSForgeSourceDir   "..\dist\QSForge"

[Setup]
AppId={#QSForgeAppId}
AppName={#QSForgeName}
AppVersion={#QSForgeVersion}
AppVerName={#QSForgeName} {#QSForgeVersion}
AppPublisher={#QSForgePublisher}
AppPublisherURL=https://github.com/liyq0610123-star/qsforge
AppComments=Free Revit Model Quality Check + BQ Draft for Quantity Surveyors
VersionInfoCompany={#QSForgePublisher}
VersionInfoProductName={#QSForgeName}
VersionInfoProductVersion={#QSForgeVersion}
VersionInfoVersion={#QSForgeVersion}

LicenseFile=..\LICENSE

PrivilegesRequired=lowest
DefaultDirName={localappdata}\{#QSForgeName}
DefaultGroupName={#QSForgeName}
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
UsePreviousGroup=yes
AllowNoIcons=yes

OutputDir=output
OutputBaseFilename=QSForge-Setup-{#QSForgeVersion}
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
SetupIconFile=..\assets\qsforge.ico
WizardStyle=modern
ShowLanguageDialog=auto

UninstallDisplayName={#QSForgeName} {#QSForgeVersion}
UninstallDisplayIcon={app}\{#QSForgeExe}

MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon";  Description: "{cm:CreateDesktopIcon}";  GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startmenu";    Description: "Create a Start Menu shortcut"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#QSForgeSourceDir}\{#QSForgeExe}";  DestDir: "{app}"; Flags: ignoreversion
Source: "{#QSForgeSourceDir}\_internal\*";    DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#QSForgeSourceDir}\vendor\ddc\*"; DestDir: "{app}\vendor\ddc"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "{#QSForgeSourceDir}\*.pdf"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "{#QSForgeSourceDir}\block_ddc_ads.bat"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD-PARTY-NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#QSForgeName}";                Filename: "{app}\{#QSForgeExe}"; Tasks: startmenu
Name: "{group}\QSForge 使用说明 (中文)";       Filename: "{app}\QSForge 使用说明.pdf";    Tasks: startmenu
Name: "{group}\User Manual (English)";         Filename: "{app}\QSForge User Manual.pdf"; Tasks: startmenu
Name: "{group}\Block DDC promo pages (admin)"; Filename: "{app}\block_ddc_ads.bat"; Tasks: startmenu
Name: "{group}\Uninstall {#QSForgeName}";      Filename: "{uninstallexe}";   Tasks: startmenu
Name: "{autodesktop}\{#QSForgeName}"; Filename: "{app}\{#QSForgeExe}";  Tasks: desktopicon

[Run]
Filename: "{app}\{#QSForgeExe}"; Description: "{cm:LaunchProgram,{#QSForgeName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.webview-data"
Type: files;          Name: "{app}\last_result.json"
Type: files;          Name: "{app}\qsforge_crash.log"
Type: files;          Name: "{app}\qsforge_rvtexporter_last.txt"

[Code]
function IsWebView2Installed(): Boolean;
var
  Value: String;
  Key: String;
begin
  Result := False;
  Key := 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  if RegQueryStringValue(HKLM, Key, 'pv', Value) and (Value <> '') and (Value <> '0.0.0.0') then
  begin
    Result := True;
    Exit;
  end;
  Key := 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  if RegQueryStringValue(HKLM, Key, 'pv', Value) and (Value <> '') and (Value <> '0.0.0.0') then
  begin
    Result := True;
    Exit;
  end;
  Key := 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  if RegQueryStringValue(HKCU, Key, 'pv', Value) and (Value <> '') and (Value <> '0.0.0.0') then
    Result := True;
end;

function InitializeSetup(): Boolean;
var
  ProceedAnyway: Integer;
begin
  Result := True;
  if not IsWebView2Installed() then
  begin
    ProceedAnyway := MsgBox(
      'Microsoft Edge WebView2 Runtime does not appear to be installed.' + #13#10 +
      'QSForge needs it to display its interface.' + #13#10 + #13#10 +
      'You can still install QSForge now, but the window will fail to' + #13#10 +
      'appear until WebView2 is installed. Download it free from:' + #13#10 +
      'https://developer.microsoft.com/microsoft-edge/webview2/' + #13#10 + #13#10 +
      'Continue with installation anyway?',
      mbConfirmation, MB_YESNO);
    if ProceedAnyway <> IDYES then
      Result := False;
  end;
end;
```

**IMPORTANT:** Save `installer/qsforge.iss` as **UTF-8 with BOM** so the Chinese strings in the `[Icons]` section render correctly when Inno Setup compiles. In PowerShell:

```powershell
$content = Get-Content -Path installer/qsforge.iss -Raw -Encoding UTF8
[System.IO.File]::WriteAllText((Resolve-Path installer/qsforge.iss), $content, [System.Text.UTF8Encoding]::new($true))
```

- [ ] **Step 3: Delete the old iss**

```powershell
Remove-Item installer/archiqs.iss
```

- [ ] **Step 4: Commit**

```powershell
git rm installer/archiqs.iss
git add installer/qsforge.iss
git commit -m "refactor(installer): rewrite as qsforge.iss, fresh GUID, MIT LicenseFile (B7+M2)"
```

---

### Task 16: Update `build.ps1` to reference the new names

**Files:**
- Modify: `build.ps1`

- [ ] **Step 1: Apply targeted replacements**

| Old | New |
|---|---|
| `ArchiQS - Build script` (docstring) | `QSForge - Build script` |
| `dist\ArchiQS\ArchiQS.exe` | `dist\QSForge\QSForge.exe` |
| `dist\ArchiQS` (all occurrences) | `dist\QSForge` |
| `archiqs.spec` | `qsforge.spec` |
| `installer\archiqs.iss` | `installer\qsforge.iss` |
| `installer\output\ArchiQS-Setup-*.exe` | `installer\output\QSForge-Setup-*.exe` |
| `=== ArchiQS :: PyInstaller build ===` | `=== QSForge :: PyInstaller build ===` |
| `ARCHIQS_VERSION` (in the python -c invocation) | `QSFORGE_VERSION` |
| Inline `_version.ARCHIQS_VERSION` | `_version.QSFORGE_VERSION` |
| `"ArchiQS 使用说明.pdf"` | `"QSForge 使用说明.pdf"` |
| `"ArchiQS 使用说明"` (title arg) | `"QSForge 使用说明"` |
| `"ArchiQS User Manual.pdf"` | `"QSForge User Manual.pdf"` |
| `"ArchiQS User Manual"` (title arg) | `"QSForge User Manual"` |
| `Launching ArchiQS.exe` | `Launching QSForge.exe` |
| `Could not read ARCHIQS_VERSION` | `Could not read QSFORGE_VERSION` |
| Generated `version.iss` body content `#define ArchiQSVersion` | `#define QSForgeVersion` |
| Comment `archiqs.iss` | `qsforge.iss` |
| Path comment `vendor\ddc\.archiqs-ddc-version` | `vendor\ddc\.qsforge-ddc-version` |
| Marker filename literal `".archiqs-ddc-version"` | `".qsforge-ddc-version"` |
| Any remaining `ArchiQS` / `archiqs` / `ARCHIQS` | `QSForge` / `qsforge` / `QSFORGE` |

- [ ] **Step 2: Verify**

Grep `build.ps1` for `ArchiQS|ARCHIQS|archiqs`. Expected: zero hits.

- [ ] **Step 3: Re-save `build.ps1` as UTF-8 with BOM** (Task 4 did this, but if Edit operations have stripped the BOM, re-apply):

```powershell
$content = Get-Content -Path build.ps1 -Raw -Encoding UTF8
[System.IO.File]::WriteAllText((Resolve-Path build.ps1), $content, [System.Text.UTF8Encoding]::new($true))
```

- [ ] **Step 4: Commit**

```powershell
git add build.ps1
git commit -m "refactor(build): rename ArchiQS -> QSForge in build.ps1 (B7)"
```

---

### Task 17: Rename icon asset

**Files:**
- Delete: `assets/archiqs.ico`
- Create: `assets/qsforge.ico` (initially a copy of the old file)

The icon **artwork** can stay the same for 1.0.0 — only the filename changes. A redesign can happen post-launch.

- [ ] **Step 1: Rename the file**

```powershell
Move-Item assets/archiqs.ico assets/qsforge.ico
```

- [ ] **Step 2: Verify no remaining reference to `archiqs.ico`**

Grep the repo for `archiqs.ico`. Expected: zero hits (Tasks 14 and 15 should have updated all references).

- [ ] **Step 3: Commit**

```powershell
git add assets/qsforge.ico
git rm assets/archiqs.ico
git commit -m "refactor(assets): rename archiqs.ico -> qsforge.ico (B7)"
```

---

### Task 18: Full repo rebrand verification

**Files:** none (verification only)

- [ ] **Step 1: Grep the entire tree (excluding ignored paths) for the old name**

Use Grep with pattern `ArchiQS|ARCHIQS|archiqs` and `glob` set to exclude `dist/**`, `_to_delete/**`, `.webview-data/**`, `build_log*.txt`, `last_result.json`, `tests/last_result.json`, `.claude/**`, `docs/superpowers/specs/2026-05-15-qsforge-rebrand-and-release-design.md`, `docs/superpowers/plans/2026-05-15-qsforge-rebrand-and-release.md`.

Acceptable remaining hits:
- The two spec/plan files (this file itself describes the rename).
- `PRE_RELEASE_CHECKLIST.md` (audit history — leave intact or update separately).
- `docs/superpowers/specs/2026-05-08-3d-preview-design.md` (historical doc).
- `docs/superpowers/plans/2026-05-08-3d-preview.md` (historical doc).
- `static/vendor/three/ColladaLoader.js` (vendored upstream — not our string).

**Everything else must be zero.** If anything else lights up, fix it before continuing.

- [ ] **Step 2: Update `PRE_RELEASE_CHECKLIST.md` header to note rebrand status**

Add a banner at the top of `PRE_RELEASE_CHECKLIST.md`:

```markdown
> **Status (2026-05-15):** This checklist was written before the rebrand from ArchiQS to QSForge. Item B7 (rebrand) is implemented by the plan at `docs/superpowers/plans/2026-05-15-qsforge-rebrand-and-release.md`. The checklist body still uses the old `ArchiQS` name for historical accuracy.
```

- [ ] **Step 3: Commit**

```powershell
git add PRE_RELEASE_CHECKLIST.md
git commit -m "docs: note rebrand status on top of PRE_RELEASE_CHECKLIST"
```

---

## Phase 4 — CJK font bundling (B3)

### Task 19: Add Noto Sans CJK SC fonts and update lookup logic

**Files:**
- Create: `assets/fonts/NotoSansCJKsc-Regular.otf`
- Create: `assets/fonts/NotoSansCJKsc-Bold.otf`
- Create: `assets/fonts/OFL.txt`
- Modify: `tools/md_to_pdf.py` (font lookup)
- Modify: `src/pdf_report.py` (font lookup)
- Modify: `qsforge.spec` (datas)

- [ ] **Step 1: Download Noto Sans CJK SC fonts**

From https://github.com/notofonts/noto-cjk/releases/latest, download:
- `NotoSansCJKsc-Regular.otf`
- `NotoSansCJKsc-Bold.otf`

Save into `assets/fonts/`. Each face is ~18 MB.

Also download the OFL-1.1 license text and save as `assets/fonts/OFL.txt`. (Available at https://github.com/notofonts/noto-cjk/blob/main/Sans/LICENSE.)

- [ ] **Step 2: Update `tools/md_to_pdf.py` font lookup**

Locate the font registration block (around lines 63-72). Add the bundled path as the **first** candidate:

```python
from pathlib import Path

# Prefer fonts bundled inside the QSForge install. This guarantees Chinese
# text renders on any Windows machine — including English Windows where
# YaHei / SimHei / SimSun are not installed.
_BUNDLED_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

_CJK_FONT_CANDIDATES = [
    (_BUNDLED_FONT_DIR / "NotoSansCJKsc-Regular.otf", _BUNDLED_FONT_DIR / "NotoSansCJKsc-Bold.otf"),
    (Path(r"C:\Windows\Fonts\msyh.ttc"), Path(r"C:\Windows\Fonts\msyhbd.ttc")),
    (Path(r"C:\Windows\Fonts\simhei.ttf"), Path(r"C:\Windows\Fonts\simhei.ttf")),
    (Path(r"C:\Windows\Fonts\simsun.ttc"), Path(r"C:\Windows\Fonts\simsun.ttc")),
]
```

Then replace the existing font-registration logic with:

```python
def _register_cjk_fonts():
    """Register a CJK-capable font pair with reportlab.

    Returns (regular_name, bold_name). Falls back to Helvetica if no CJK
    font is available — the caller should still call this so reportlab
    has *some* font to reach for.
    """
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for regular, bold in _CJK_FONT_CANDIDATES:
        if regular.exists() and bold.exists():
            try:
                pdfmetrics.registerFont(TTFont("QSForgeCJK", str(regular)))
                pdfmetrics.registerFont(TTFont("QSForgeCJK-Bold", str(bold)))
                return "QSForgeCJK", "QSForgeCJK-Bold"
            except Exception:
                continue
    return "Helvetica", "Helvetica-Bold"
```

Update the rest of `tools/md_to_pdf.py` to use the names returned by `_register_cjk_fonts()` instead of hardcoded YaHei/etc.

- [ ] **Step 3: Update `src/pdf_report.py` with the same lookup logic**

The exact location depends on the file; find any reference to `msyh.ttc` / `simhei.ttf` / `simsun.ttc` and apply the same pattern. Use `_BUNDLED_FONT_DIR = paths.resource_dir() / "assets" / "fonts"` since `pdf_report.py` runs inside the frozen app (where `paths.resource_dir()` returns the PyInstaller extraction dir).

```python
import paths as app_paths
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

_BUNDLED_FONT_DIR = app_paths.resource_dir() / "assets" / "fonts"

_CJK_FONT_CANDIDATES = [
    (_BUNDLED_FONT_DIR / "NotoSansCJKsc-Regular.otf",
     _BUNDLED_FONT_DIR / "NotoSansCJKsc-Bold.otf"),
    (Path(r"C:\Windows\Fonts\msyh.ttc"),
     Path(r"C:\Windows\Fonts\msyhbd.ttc")),
    (Path(r"C:\Windows\Fonts\simhei.ttf"),
     Path(r"C:\Windows\Fonts\simhei.ttf")),
    (Path(r"C:\Windows\Fonts\simsun.ttc"),
     Path(r"C:\Windows\Fonts\simsun.ttc")),
]
```

- [ ] **Step 4: Add `assets/fonts` to `qsforge.spec` datas**

In `qsforge.spec`, update the `datas` list to include the fonts directory explicitly (it's already inside `assets/` so this is technically redundant, but being explicit avoids any "did PyInstaller skip large .otf files" question later):

```python
datas = [
    (str(PROJECT / "static"), "static"),
    (str(PROJECT / "assets"), "assets"),
    (str(PROJECT / "assets" / "fonts"), "assets/fonts"),
    (str(PROJECT / "LICENSE"), "."),
    (str(PROJECT / "THIRD-PARTY-NOTICES.md"), "."),
]
```

- [ ] **Step 5: Smoke-test the font registration**

```powershell
python -c "import sys; sys.path.insert(0,'src'); from pdf_report import _register_cjk_fonts; print(_register_cjk_fonts())"
```

Expected: `('QSForgeCJK', 'QSForgeCJK-Bold')` — using the bundled font.

- [ ] **Step 6: Commit**

The fonts themselves are large; verify `.gitignore` doesn't exclude them (`*.otf` is **not** in the gitignore from Task 1, so they'll be committed). Also verify no individual file exceeds GitHub's 100 MB hard limit:

```powershell
Get-ChildItem assets/fonts/ | ForEach-Object { "{0,-40} {1:N1} MB" -f $_.Name, ($_.Length / 1MB) }
```

Expected: each face ~18 MB. Well within limits.

```powershell
git add assets/fonts/ tools/md_to_pdf.py src/pdf_report.py qsforge.spec
git commit -m "feat(pdf): bundle Noto Sans CJK SC for cross-platform Chinese rendering (B3)"
```

---

## Phase 5 — Logging migration (H3)

### Task 20: Configure rotating logger in `main.py`

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add logging setup**

Near the top of `main.py`, immediately after `import paths as app_paths`, add:

```python
import logging
from logging.handlers import RotatingFileHandler


def _setup_logging() -> None:
    """Install a rotating file handler so production builds capture diagnostics.

    Frozen QSForge has no console — print() output is silently lost. This
    handler writes to %LOCALAPPDATA%\\QSForge\\qsforge.log (or the source
    project folder in dev). 5 MB cap × 3 backups = bounded disk use.
    """
    log_path = app_paths.user_data_dir() / "qsforge.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Don't duplicate handlers across re-imports (relevant if main.py is
    # invoked multiple times in a single Python process, e.g. tests).
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        root.addHandler(handler)


_setup_logging()
```

The `_setup_logging()` call must happen **before** the `import server` line so every downstream `logging.getLogger(__name__)` inherits the root handler.

- [ ] **Step 2: Verify the log file is created on import**

```powershell
python -c "import main"
```

Then:

```powershell
Test-Path "$env:LOCALAPPDATA\QSForge\qsforge.log"
```

Wait — at this point `paths.user_data_dir()` in **source mode** returns the project root, so the file lands at `C:\Archiqs\RVT Quality Check\qsforge.log`. Verify:

```powershell
Test-Path "qsforge.log"
```

Expected: `True`. (Once frozen, it'll be next to the .exe.)

The freshly-created `qsforge.log` is gitignored (per Task 1) — leave it.

- [ ] **Step 3: Commit**

```powershell
git add main.py
git commit -m "feat(log): install rotating file handler for production diagnostics (H3)"
```

---

### Task 21: Migrate `print()` to `logging` — `src/server.py` (1 call)

**Files:**
- Modify: `src/server.py`

- [ ] **Step 1: Add logger at top of file**

Near the existing imports, add:

```python
import logging

logger = logging.getLogger(__name__)
```

- [ ] **Step 2: Replace the single `print()` call**

Grep `src/server.py` for `print(`. There's one call. Replace with the appropriate `logger.info(...)` / `logger.warning(...)` / `logger.error(...)` based on context (informational messages → `info`; "failed", "could not", "error" → `error`; "WARN", "deprecated" → `warning`).

- [ ] **Step 3: Verify**

Grep `src/server.py` for `\bprint\(`. Expected: zero hits (other than print inside string literals, which Grep regex `\bprint\(` should not hit).

- [ ] **Step 4: Commit**

```powershell
git add src/server.py
git commit -m "refactor(server): print() -> logging (H3)"
```

---

### Task 22: Migrate `print()` — `src/ad_blocker.py` (3 calls)

**Files:**
- Modify: `src/ad_blocker.py`

- [ ] **Step 1: Add logger import + replace 3 `print()` calls** following the same pattern as Task 21.

- [ ] **Step 2: Verify** — Grep for `\bprint\(` in `src/ad_blocker.py`. Expected: zero hits.

- [ ] **Step 3: Commit**

```powershell
git add src/ad_blocker.py
git commit -m "refactor(ad_blocker): print() -> logging (H3)"
```

---

### Task 23: Migrate `print()` — `src/pdf_report.py` (2 calls)

**Files:**
- Modify: `src/pdf_report.py`

- [ ] **Step 1: Add logger import + replace 2 `print()` calls**.

- [ ] **Step 2: Verify** — zero hits for `\bprint\(`.

- [ ] **Step 3: Commit**

```powershell
git add src/pdf_report.py
git commit -m "refactor(pdf): print() -> logging (H3)"
```

---

### Task 24: Migrate `print()` — `src/updater.py` (6 calls)

**Files:**
- Modify: `src/updater.py`

- [ ] **Step 1: Add logger import + replace 6 `print()` calls**.

- [ ] **Step 2: Verify** — zero hits for `\bprint\(`.

- [ ] **Step 3: Commit**

```powershell
git add src/updater.py
git commit -m "refactor(updater): print() -> logging (H3)"
```

---

### Task 25: Migrate `print()` — `src/ddc_runner.py` (13 calls)

**Files:**
- Modify: `src/ddc_runner.py`

- [ ] **Step 1: Add logger import + replace all 13 `print()` calls**. DDC subprocess output handling may use `print()` for streaming — those should become `logger.info()` calls so the data still ends up in `qsforge.log`.

- [ ] **Step 2: Verify** — zero hits for `\bprint\(`.

- [ ] **Step 3: Commit**

```powershell
git add src/ddc_runner.py
git commit -m "refactor(ddc): print() -> logging (H3)"
```

---

### Task 26: Migrate `print()` — `src/module2_bq_draft.py` (15 calls)

**Files:**
- Modify: `src/module2_bq_draft.py`

- [ ] **Step 1: Add logger import + replace 15 `print()` calls**.

- [ ] **Step 2: Verify** — zero hits for `\bprint\(`.

- [ ] **Step 3: Commit**

```powershell
git add src/module2_bq_draft.py
git commit -m "refactor(module2): print() -> logging (H3)"
```

---

### Task 27: Migrate `print()` — `src/module1_qs_readiness.py` (23 calls)

**Files:**
- Modify: `src/module1_qs_readiness.py`

- [ ] **Step 1: Add logger import + replace 23 `print()` calls**.

- [ ] **Step 2: Verify** — zero hits for `\bprint\(`.

- [ ] **Step 3: Commit**

```powershell
git add src/module1_qs_readiness.py
git commit -m "refactor(module1): print() -> logging (H3)"
```

---

### Task 28: Migrate `print()` — `src/module0_inventory.py` (32 calls)

**Files:**
- Modify: `src/module0_inventory.py`

- [ ] **Step 1: Add logger import + replace 32 `print()` calls**. Largest single migration; take it slow and re-verify per logical block.

- [ ] **Step 2: Verify** — zero hits for `\bprint\(` in `src/module0_inventory.py`.

- [ ] **Step 3: Run an end-to-end sanity test**

```powershell
python -c "import sys; sys.path.insert(0,'src'); import module0_inventory, module1_qs_readiness, module2_bq_draft, ddc_runner, server, updater, pdf_report, ad_blocker; print('imports OK')"
```

Expected: `imports OK`. (No NameError on stale `print` references.)

- [ ] **Step 4: Commit**

```powershell
git add src/module0_inventory.py
git commit -m "refactor(module0): print() -> logging (H3)"
```

---

### Task 29: Whole-`src/` print-free verification

- [ ] **Step 1:** Grep across `src/` for `\bprint\(`. Expected: zero hits.

If any hits remain, fix them in the relevant module and amend that module's commit (or add a small "chore: clean up trailing print calls" commit).

---

## Phase 6 — Memory file updates

### Task 30: Update Claude memory files to reflect QSForge

**Files:**
- Modify: `C:\Users\11390\.claude\projects\C--Archiqs-RVT-Quality-Check\memory\MEMORY.md`
- Modify: `C:\Users\11390\.claude\projects\C--Archiqs-RVT-Quality-Check\memory\project_overview.md`
- Modify: `C:\Users\11390\.claude\projects\C--Archiqs-RVT-Quality-Check\memory\feedback_module2_shape.md`
- Modify: `C:\Users\11390\.claude\projects\C--Archiqs-RVT-Quality-Check\memory\feature_3d_preview.md`

- [ ] **Step 1: Update each memory file** — replace `ArchiQS` references with `QSForge` and add a note that the product was rebranded on 2026-05-15.

- [ ] **Step 2: Verify** — Grep each file for `ArchiQS`. Expected: zero hits (or only inside historical "previously known as" sentences).

- [ ] **Step 3: No commit** — these files live outside the repo.

---

## Phase 7 — Documentation

### Task 31: Update `docs/README.md` and `docs/QUICK_START_CN.md`

**Files:**
- Modify: `docs/README.md`
- Modify: `docs/QUICK_START_CN.md`

- [ ] **Step 1:** Replace all `ArchiQS` → `QSForge` and `archiqs` → `qsforge` in both files.

- [ ] **Step 2:** Update file titles, version references (v1.0 not v1.x), and the "What ArchiQS does NOT do" → "What QSForge does NOT do" section.

- [ ] **Step 3:** Add a "License" section near the bottom of `docs/README.md`:

```markdown
## License

QSForge is free and open source under the [MIT License](../LICENSE). See
[THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md) for the licenses of
bundled dependencies (Flask, openpyxl, reportlab, Noto Sans CJK SC, etc.)
and for the redistribution status of the DDC RvtExporter under `vendor/ddc/`.
```

- [ ] **Step 4: Verify** — Grep `docs/` for `ArchiQS|archiqs`. Expected: zero hits except in `docs/superpowers/specs/*` and `docs/superpowers/plans/*` (historical artefacts).

- [ ] **Step 5: Commit**

```powershell
git add docs/README.md docs/QUICK_START_CN.md
git commit -m "docs: rename ArchiQS -> QSForge, add MIT license section (B7)"
```

---

### Task 32: Create a top-level `README.md` for GitHub

**Files:**
- Create: `README.md` (root of repo)

- [ ] **Step 1: Write a concise GitHub-landing README**

```markdown
# QSForge

**Free Revit Model Quality Check + BQ Draft for Quantity Surveyors.**

QSForge is a Windows desktop tool that takes a `.rvt` file, runs nine
category-aware quality checks for QS workflows, and produces a draft NRM2
Bill of Quantities. Drop a model in, get a verdict and an Excel BQ within
60–120 seconds. No Revit licence required — the DDC converter is bundled.

Built for QS teams in Singapore, Hong Kong, and Malaysia, where you often
have to decide within minutes whether a handed-over Revit model is usable
for take-off.

## Download

Grab the latest installer from
[Releases](https://github.com/liyq0610123-star/qsforge/releases/latest).

On first launch, Windows SmartScreen may show "Windows protected your PC".
This is expected for an unsigned installer — click **More info → Run anyway**.
A signed installer is planned for a later release.

## What it does

- ✅ Inspects a `.rvt` for QS-readiness across 9 dimensions (Volume Coverage,
  Level Assignment, Multi-storey vertical elements, Material completeness, etc.)
- ✅ Produces a draft NRM2 Bill of Quantities (Excel) for sections H, 11, 14, 17, 28
- ✅ Element-ID-level punch list for the BIM team
- ✅ Exports a two-page PDF report (executive summary + detailed BIM follow-up)
- ✅ Optional 3D preview of the model (powered by three.js)
- ❌ Does **not** produce final BQs or fix the model — it tells you whether
  you can trust quantities pulled from it.

## See also

- [User manual (English)](docs/README.md)
- [使用说明 (中文)](docs/QUICK_START_CN.md)
- [Third-party licenses](THIRD-PARTY-NOTICES.md)

## License

[MIT](LICENSE) — free for any use, including commercial.

---

QSForge is the successor to the internal-only **ArchiQS** prototype.
```

- [ ] **Step 2: Commit**

```powershell
git add README.md
git commit -m "docs: add GitHub landing README"
```

---

## Phase 8 — Build, verify, release

### Task 33: Clean build & local smoke test

**Files:** none directly modified — this task builds and tests.

- [ ] **Step 1: Clean previous build artefacts**

```powershell
if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path dist) { Remove-Item -Recurse -Force dist }
if (Test-Path installer/output) { Remove-Item -Recurse -Force installer/output }
```

- [ ] **Step 2: Set the DDC source env var (if your DDC checkout is local)**

```powershell
$env:QSFORGE_DDC_SOURCE = "C:\path\to\your\DDC_CONVERTER_REVIT"
```

(Replace with the actual path to your local DDC checkout. If you skip this, the build will warn and produce an installer without bundled DDC — fine for testing the launcher but the produced installer won't be shippable.)

- [ ] **Step 3: Run the build**

```powershell
.\build.ps1
```

Expected:
- `=== QSForge :: PyInstaller build ===` banner
- No mojibake in any output line
- `Executable : <path>\dist\QSForge\QSForge.exe`
- Folder size ~200–250 MB without DDC, ~800 MB with DDC
- `Rendered docs\QUICK_START_CN.md -> QSForge 使用说明.pdf` (Chinese filename, correctly encoded)
- `Rendered docs\README.md -> QSForge User Manual.pdf`
- If Inno Setup is installed: `Installer : <path>\installer\output\QSForge-Setup-1.0.0.exe`

- [ ] **Step 4: Verify shipped filenames are correctly encoded**

```powershell
Get-ChildItem dist\QSForge\*.pdf | Select-Object Name
Get-ChildItem installer\output\QSForge-Setup-*.exe | Select-Object Name
```

Expected: both `QSForge 使用说明.pdf` and `QSForge User Manual.pdf` show with **correct** Chinese characters (no `浣跨敤` mojibake).

- [ ] **Step 5: Verify no `ArchiQS` or `11390` strings in the shipped EXE**

```powershell
$exe = "dist\QSForge\QSForge.exe"
Select-String -Path $exe -Pattern "ArchiQS|11390" -SimpleMatch
```

Note: `Select-String` against a binary is imperfect but catches embedded plaintext. For a thorough check, do the same against `dist\QSForge\_internal\` Python bytecode:

```powershell
Get-ChildItem dist\QSForge\_internal\*.pyc -Recurse | Select-String -Pattern "ArchiQS|11390" -SimpleMatch | Select-Object -First 5
```

Expected: zero hits in both checks.

- [ ] **Step 6: Launch the EXE and run a manual smoke test**

```powershell
Start-Process dist\QSForge\QSForge.exe
```

- The window should open within 5–10 seconds.
- Title bar reads **QSForge**.
- Drop a test `.rvt` (or click to browse) — analysis should complete.
- Verify `%LOCALAPPDATA%\QSForge\qsforge.log` exists and contains entries.
- Export a PDF report — confirm Chinese text renders as glyphs, not boxes.
- Open the Update panel — should report "You're on the latest version" once the GitHub Release exists (skip this until after Task 35).

If anything fails, fix it before continuing. Do not commit the build outputs — they're gitignored.

---

### Task 34: First push to GitHub

**Files:** none modified.

- [ ] **Step 1: Confirm the GitHub repo exists**

User creates an **empty** public repo at `https://github.com/liyq0610123-star/qsforge` (no README, no LICENSE, no gitignore — those come from this local repo).

- [ ] **Step 2: Add the remote**

```powershell
git remote add origin https://github.com/liyq0610123-star/qsforge.git
git branch -M main
```

- [ ] **Step 3: Verify the working tree is clean and small**

```powershell
git status
git ls-files | Measure-Object
```

Expected: clean working tree (no unstaged changes), and the file count is small (under ~200 files of actual source). If `git ls-files` shows anything from `dist/` or `installer/output/`, **stop** and fix `.gitignore` + `git rm --cached`.

```powershell
# Quick repo-size sanity check (count of tracked bytes):
(git ls-files | ForEach-Object { (Get-Item $_).Length } | Measure-Object -Sum).Sum / 1MB
```

Expected: well under 100 MB total (the fonts are the largest tracked binaries at ~36 MB combined).

- [ ] **Step 4: First push**

```powershell
git push -u origin main
```

Watch the output — if push fails for size, identify the offending file and add it to `.gitignore` + `git rm --cached <file>` + commit + retry.

- [ ] **Step 5: Verify on GitHub**

Open `https://github.com/liyq0610123-star/qsforge` in a browser and confirm:
- README renders correctly.
- LICENSE shows up with the MIT badge.
- `assets/fonts/` is present.
- `dist/`, `installer/output/`, `.webview-data/` are **absent**.

---

### Task 35: Create GitHub Release v1.0.0 with installer + manifest

**Files:**
- Create: `updates/manifest-1.0.0.json` (local copy of what's about to be uploaded; for reference only — not committed since it contains an SHA-256 only valid for this build)

- [ ] **Step 1: Compute SHA-256 + size of the installer**

```powershell
$installer = "installer\output\QSForge-Setup-1.0.0.exe"
$hash = (Get-FileHash $installer -Algorithm SHA256).Hash.ToLower()
$size = (Get-Item $installer).Length
Write-Host "SHA-256: $hash"
Write-Host "Size:    $size bytes ($([math]::Round($size / 1MB, 1)) MB)"
```

Record both values.

- [ ] **Step 2: Author the live `manifest.json`**

Create a local file `manifest.json` (in repo root, not committed — just for upload). Populate from the template at `updates/manifest.example.json`, substituting:

```json
{
  "qsforge": {
    "version": "1.0.0",
    "released_at": "2026-05-15",
    "installer_url": "https://github.com/liyq0610123-star/qsforge/releases/download/v1.0.0/QSForge-Setup-1.0.0.exe",
    "sha256": "<hash from Step 1>",
    "size_bytes": <size from Step 1>,
    "release_notes_url": "https://github.com/liyq0610123-star/qsforge/releases/tag/v1.0.0",
    "release_notes": "First public release of QSForge — Revit model quality check + draft BQ generator for Quantity Surveyors."
  },
  "ddc": {
    "version": "18.1.0",
    "released_at": "2026-05-15",
    "package_url": "",
    "sha256": "",
    "size_bytes": 0,
    "release_notes_url": "https://datadrivenconstruction.io/changelog",
    "release_notes": "DDC ships bundled inside the QSForge installer for 1.0.0; no separate download yet."
  }
}
```

- [ ] **Step 3: Tag v1.0.0**

```powershell
git tag -a v1.0.0 -m "QSForge 1.0.0 — first public release"
git push origin v1.0.0
```

- [ ] **Step 4: Create the GitHub Release**

Either via the GitHub web UI, or using `gh` CLI if installed:

```powershell
gh release create v1.0.0 `
  "installer\output\QSForge-Setup-1.0.0.exe" `
  "manifest.json" `
  --title "QSForge 1.0.0" `
  --notes "First public release of QSForge. See README and User Manual for details."
```

If `gh` is not installed: in the GitHub web UI, click **Releases → Draft a new release → choose tag v1.0.0 → drag in `QSForge-Setup-1.0.0.exe` and `manifest.json` → Publish release.**

- [ ] **Step 5: Verify the manifest URL is reachable**

```powershell
curl.exe -sI https://github.com/liyq0610123-star/qsforge/releases/latest/download/manifest.json
```

Expected: HTTP 302 redirect, eventually 200 OK on the asset.

- [ ] **Step 6: Verify the update check in the installed app**

Uninstall any prior `dist/QSForge` test instance, then install via `QSForge-Setup-1.0.0.exe`. Launch from Start Menu. Open the Update panel — should report **"You're on the latest version"** (since the manifest's version matches the installed version).

- [ ] **Step 7: Final smoke**

Drop a small test `.rvt`. Confirm analysis completes, the BQ draft Excel is produced next to the input file, and the PDF report exports with correctly-rendered Chinese.

---

## Self-review

**Spec coverage:**
- §4.1 Rebrand mapping — Tasks 5–17 (every layer covered).
- §4.2 B1 manifest URL — Task 5 sets URL, Task 35 publishes the live manifest.
- §4.2 B2 mojibake — Task 4.
- §4.2 B3 CJK fonts — Task 19.
- §4.2 B4 dev path — Task 3.
- §4.2 B5-lite licensing — Task 2 + Task 15 (installer `LicenseFile=`) + Task 14 (bundled in datas).
- §4.2 H3 logging — Tasks 20–29.
- §4.2 H2 gitignore — Task 1.
- §4.3 Release flow — Tasks 33–35.
- §5 risks — DDC license verification is called out in `THIRD-PARTY-NOTICES.md` (Task 2). The engineer is expected to verify this independently before Task 35.
- §7 success criteria — verified explicitly in Tasks 33 (Steps 4–6) and 35 (Steps 5–7).

**No placeholders:** Every step contains the actual content or an exact command. Where the engineer is expected to pick a value (e.g. the new GUID in Task 15), the step provides the exact command that produces it.

**Type / name consistency:** `QSFORGE_VERSION`, `QSFORGE_DDC_EXE`, `QSFORGE_DDC_SOURCE`, `QSFORGE_DDC_TIMEOUT_SEC`, `QSFORGE_UPDATE_MANIFEST_URL`, `COMPONENT_QSFORGE`, `qsforge_crash.log`, `qsforge_rvtexporter_last.txt`, `.qsforge-ddc-version`, `qsforge.log`, `QSForgeCJK` (font name) — these names are used consistently across all tasks that reference them.

---

## Effort summary

| Phase | Tasks | Rough time |
|---|---|---|
| 1 — Foundations | 1, 2 | 20 min |
| 2 — Pre-rename blockers | 3, 4 | 45 min |
| 3 — Rebrand (B7) | 5–18 | 4–6 hours |
| 4 — CJK fonts | 19 | 1 hour (incl. font download) |
| 5 — Logging migration | 20–29 | 3–4 hours |
| 6 — Memory updates | 30 | 10 min |
| 7 — Docs | 31, 32 | 1 hour |
| 8 — Build + release | 33, 34, 35 | 2 hours (incl. smoke tests) |
| **Total** | **35 tasks** | **~2–3 focused days** |
