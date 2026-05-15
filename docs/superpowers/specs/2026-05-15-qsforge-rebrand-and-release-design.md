# QSForge 1.0.0 — Rebrand & First Public Release (Design)

**Date:** 2026-05-15
**Author:** Claude (with liyq0610123-star)
**Status:** Approved by user; ready for implementation plan
**Implementation plan:** `docs/superpowers/plans/2026-05-15-qsforge-rebrand-and-release.md` (to be written next)

---

## 1. Background

The product currently called **ArchiQS** (version 1.6.0, never released publicly) is a Windows desktop tool that takes a `.rvt` file, runs it through the bundled DDC converter, scores it across QS-readiness dimensions, and produces a draft Bill of Quantities. Four functional modules are in place: M0 inventory parse, M1 QS readiness scoring, M2 BQ draft generation, M3 three.js 3D preview.

This document specifies the **first public release** as a **free, open-source product** distributed via GitHub. The release covers two coupled efforts:

1. **Rebrand** `ArchiQS` → `QSForge`. The previous name implied "Architecture", but the product is fundamentally a QS tool (quality check + BQ + structural data) and is expected to grow into IFC / CAD / PDF input formats — none of which justify "Archi". `QSForge` reads as "forges QS-ready data and BQ drafts from any model", scales across future input formats, and pairs naturally with module names.
2. **Ship a polished v1.0.0** with the release blockers from `PRE_RELEASE_CHECKLIST.md` resolved.

## 2. Goals

- Public GitHub repository at `github.com/liyq0610123-star/qsforge`, MIT-licensed.
- Single installer `QSForge-Setup-1.0.0.exe` distributed via GitHub Releases.
- In-app auto-update mechanism live and working — users get fixes shipped to them automatically.
- Chinese-language PDFs render correctly on **non-Chinese Windows** (the SG/HK/MY target market).
- No mojibake in shipped filenames or installer artifacts.
- No developer username, hardcoded developer path, or other personal data leaked in the EXE.
- Clean, professional logging — no `print()` calls in production source.
- Explicit licensing of every redistributed third-party component.

## 3. Non-goals (deferred to 1.0.1 or later)

- **Code signing** (B6). Defer to 1.0.1; document the SmartScreen workaround for first-launch users.
- **Production WSGI server** (H4, `waitress`). The `flask.app.run()` dev server is acceptable for a single-user desktop app.
- **Port fallback** (H5). Port 7890 is rarely in use; document the workaround.
- **Downgrade attack guard** in updater (H6). Lower priority for a free product with no audit trail.
- **DDC hosts-file batch file improvements** (H1). Keep as-is for now; revisit in 1.0.1.
- All M-class and L-class items from the checklist except where they fold into other work for free (M2 GUID is fixed because we rewrite the .iss file anyway).

## 4. Scope

### 4.1 Rebrand mapping

Every shipped artifact and runtime side-effect changes from `ArchiQS` to `QSForge`:

| Layer | Change |
|---|---|
| Display name | `ArchiQS` → `QSForge` everywhere (UI, docs, installer, About dialog) |
| Python constants | `ARCHIQS_VERSION` → `QSFORGE_VERSION`; reset to `"1.0.0"` |
| Env vars | `ARCHIQS_DDC_EXE` → `QSFORGE_DDC_EXE`; `ARCHIQS_UPDATE_MANIFEST_URL` → `QSFORGE_UPDATE_MANIFEST_URL` |
| Install path | `%LOCALAPPDATA%\ArchiQS\` → `%LOCALAPPDATA%\QSForge\` |
| Crash / runtime files | `archiqs_crash.log` → `qsforge_crash.log`; `archiqs_rvtexporter_last.txt` → `qsforge_rvtexporter_last.txt`. `last_result.json` stays generic. |
| AppUserModelID | `ArchiQS.Desktop.RVTQualityCheck.1` → `QSForge.Desktop.RVTQualityCheck.1` |
| Inno AppId | New, valid GUID generated once via `[guid]::NewGuid()`. Pin forever. |
| Update manifest key | JSON top-level `"archiqs"` → `"qsforge"` (read in `updater.py`; template in `updates/manifest.example.json`) |
| File renames | `archiqs.spec` → `qsforge.spec`; `installer/archiqs.iss` → `installer/qsforge.iss`; `assets/archiqs.ico` → `assets/qsforge.ico` |
| Output directories | `dist/ArchiQS/` → `dist/QSForge/`; installer output `ArchiQS-Setup-x.y.z.exe` → `QSForge-Setup-x.y.z.exe` |

**Clean break, no legacy aliases.** No customers have ever installed ArchiQS, so no compatibility shims for old env-var names or old install paths.

### 4.2 Release blocker fixes

**B1 — Auto-update wired up**
- `DEFAULT_MANIFEST_URL` set to `"https://github.com/liyq0610123-star/qsforge/releases/latest/download/manifest.json"`.
- Live `manifest.json` produced from `updates/manifest.example.json` at release time, with the top-level key renamed `archiqs` → `qsforge`.
- Manifest contains: `version`, installer `url`, `sha256` (from `Get-FileHash`), `size` (bytes), `released` (ISO date), `notes`.
- Smoke test: install QSForge 1.0.0, open the Update panel, confirm "You're on the latest version".

**B2 — Mojibake fix**
- Add to top of `build.ps1`:
  ```powershell
  $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
  [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
  ```
- Re-save `build.ps1` as **UTF-8 with BOM** so PowerShell 5.x respects the encoding regardless of system code page.
- Replace the line that writes `version.iss` from build.ps1 with:
  ```powershell
  [System.IO.File]::WriteAllText($genIss, $genBody, [System.Text.UTF8Encoding]::new($true))
  ```
- Verify after rebuild: `dir installer\output` and `dir dist\QSForge\*.pdf` show correct Chinese characters in filenames.

**B3 — CJK fonts bundled**
- Download `NotoSansCJKsc-Regular.otf` and `NotoSansCJKsc-Bold.otf` from the official Google Fonts / Noto Sans release. License: OFL-1.1 (redistribution allowed).
- Place under `assets/fonts/` in the repo.
- Add to `qsforge.spec`'s `datas`:
  ```python
  (str(PROJECT / "assets" / "fonts"), "assets/fonts"),
  ```
- Update font-resolution logic in `tools/md_to_pdf.py` and `src/pdf_report.py` to prefer the bundled path first, then fall back to system `C:\Windows\Fonts\*` (for dev convenience). The fallback chain becomes: bundled Noto → system YaHei → system SimHei → Helvetica.
- Verification: test the build on an English Windows VM with no CJK system fonts.

**B4 — Remove dev paths**
- `src/ddc_runner.py`: replace `DEFAULT_DDC_EXE = r"C:\Users\11390\..."` with `DEFAULT_DDC_EXE = None`; update call-site to check for `None`.
- `build.ps1`: change the default `$DdcSource` to empty string with a clearer error message if no DDC source is supplied.
- Run a recursive grep for `11390` and any `C:\Users\` literal across the entire source tree (including comments, docstrings, and tests) and replace each hit.

**B5-lite — Licensing**
- `LICENSE` at repo root: standard **MIT** text, "Copyright (c) 2026 liyq0610123-star".
- `THIRD-PARTY-NOTICES.md` at repo root, listing each redistributed dependency with its license:
  - Python deps from `requirements.txt`: Flask, openpyxl, pandas, reportlab, pywebview, numpy, matplotlib, lxml, etc.
  - DDC RvtExporter (datadrivenconstruction.io) — license **must be verified**: if their license permits redistribution inside a free/OSS product, bundle a copy of their LICENSE file under `vendor/ddc/LICENSE`; if not, switch the build to download DDC on first launch (would push the release date out).
  - Noto Sans CJK SC under OFL-1.1.
- Installer (`qsforge.iss`): add `LicenseFile=..\LICENSE` under `[Setup]` so the MIT license is shown during install.
- Bundle `LICENSE` and `THIRD-PARTY-NOTICES.md` into `dist/QSForge/` via `qsforge.spec`'s `datas`.

**H3 — Logging migration**
- Configure root `logging` in `main.py` before any module imports:
  ```python
  import logging
  from logging.handlers import RotatingFileHandler

  _log_path = app_paths.user_data_dir() / "qsforge.log"
  _log_path.parent.mkdir(parents=True, exist_ok=True)
  handler = RotatingFileHandler(_log_path, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
  handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
  logging.basicConfig(level=logging.INFO, handlers=[handler])
  ```
- Replace every `print(...)` in `src/*.py` (94 calls across 8 files) with `logger = logging.getLogger(__name__); logger.info/warning/error(...)`. Severity mapping is a per-call judgement call — most are `info`, anything currently prefixed with "WARN" / "ERROR" / "failed" / "could not" becomes the matching level.

**H2 — Comprehensive `.gitignore`**
- The repo is not yet `git init`'d, so `.gitignore` lands **before** the first commit. No `git rm --cached` recovery needed.
- Use the comprehensive ignore list from `PRE_RELEASE_CHECKLIST.md` section H2: Python caches, virtualenvs, `dist/`, `installer/output/`, `build/`, runtime droppings (`.webview-data/`, `last_result.json`, `qsforge_crash.log`, `qsforge_rvtexporter_last.txt`, `build_log*.txt`, `*.log`), the 167 MB `tests/TIO ... _detached.rvt` fixture, IDE / OS files, `.superpowers/`, `_to_delete/`.
- `tests/test_module3.py` and any other test that depends on the large `.rvt` fixture must either skip gracefully when the fixture is absent (`pytest.skip("requires local fixture")`) or ship a small synthetic fixture.

### 4.3 Release flow

1. All rebrand + fix work merged to local `main`.
2. Run `build.ps1` — produces `dist/QSForge/` + `installer/output/QSForge-Setup-1.0.0.exe`.
3. Smoke test on the developer machine: install, launch, drop a test `.rvt`, verify analysis runs, verify Chinese PDF export renders correctly.
4. Compute SHA-256 of the installer: `Get-FileHash installer/output/QSForge-Setup-1.0.0.exe -Algorithm SHA256`.
5. Produce `manifest.json` from the example template.
6. Initial `git init`; verify `.gitignore` excludes `dist/`, `installer/output/`, `.webview-data/`, and the 167 MB test fixture. Confirm `git status` shows no large binaries before staging.
7. First commit, push to `https://github.com/liyq0610123-star/qsforge` (user creates the empty repo first).
8. Tag `v1.0.0`. Create GitHub Release; upload the installer EXE and `manifest.json` as release assets.
9. Smoke test the update mechanism from a clean Windows VM: install 1.0.0, open Update panel, verify "latest" status (since the latest release matches).
10. Update memory files (`project_overview.md`, `MEMORY.md`, etc.) to refer to QSForge.

## 5. Risks & open questions

- **DDC redistribution license** — biggest unresolved risk. If `datadrivenconstruction.io`'s license forbids bundling, the entire release model changes (would need a first-launch downloader for the ~600 MB DDC bundle). Verify before tagging v1.0.0.
- **Microsoft SmartScreen** on the unsigned installer — every user sees a "Windows protected your PC" warning on first launch. Mitigation: a prominent "First-launch warning is normal" note in `docs/QUICK_START_CN.md`, in the GitHub README, and on the installer welcome screen. Code signing is the 1.0.1 follow-up.
- **GitHub repo size** — `dist/` is 818 MB and the bundled DDC is ~600 MB. Neither is committed (gitignore), but if the user accidentally commits anything from `dist/`, push will fail. Verify `git status` shows nothing large before the first commit.
- **CJK font on resource-constrained machines** — Noto Sans CJK SC adds ~20 MB per face to the installer. Acceptable.
- **Update channel switching** — if a user has set `ARCHIQS_UPDATE_MANIFEST_URL` (legacy env), QSForge won't read it. Acceptable since there are no shipped customers.

## 6. Out of scope explicitly

- Domain registration (`qsforge.com` / `qsforge.io`) — user can decide separately. The product works fine with only a GitHub presence.
- Trademark filing — not required for a free OSS product, but the user should run a quick clearance search against existing `QSForge` trademarks before publicizing.
- Localization beyond zh-CN / en — the current bilingual UX is sufficient.
- Telemetry / analytics — explicitly **none**, per the existing privacy stance in `docs/README.md`.
- Migration of any installed-ArchiQS user data — there are none.

## 7. Success criteria

The release is shippable when **all** of these are true:

1. `dist/QSForge/QSForge.exe` exists and runs to the analysis screen on a clean Windows 10/11 VM with WebView2 installed.
2. `dir dist/QSForge/*.pdf` shows correctly-encoded Chinese filenames.
3. Dropping a test `.rvt` produces a Chinese PDF report where Chinese characters render as glyphs (not `□□□`) on the English-Windows VM.
4. `strings dist/QSForge/QSForge.exe` (or grep across `_internal/`) returns zero hits for `11390`, zero hits for `C:\Users`, zero hits for `ArchiQS`.
5. `qsforge.log` is created on first launch under `%LOCALAPPDATA%\QSForge\` and receives entries instead of dropped `print()` output.
6. `git status` after init + `.gitignore` shows a clean tree of <50 MB of actual source.
7. The GitHub Release v1.0.0 has both `QSForge-Setup-1.0.0.exe` and `manifest.json` as downloadable assets.
8. Installing 1.0.0 and opening Update panel reports "You're on the latest version".
9. `LICENSE` (MIT) and `THIRD-PARTY-NOTICES.md` are visible in both the GitHub repo root and the installed `%LOCALAPPDATA%\QSForge\` folder.

## 8. Effort estimate

Approximately **2–3 focused days** of work:

- Day 1: rebrand string replacements (script-driven where safe; manual on `static/index.html` and docs); B4 dev-path purge; H2 `.gitignore`; B5-lite LICENSE + THIRD-PARTY-NOTICES.
- Day 2: B2 encoding fix; B3 CJK font bundling + lookup change; H3 logging migration (largest single mechanical task); B1 manifest + URL wiring.
- Day 3: build, smoke test, fix anything that surfaces, `git init` + first push, GitHub Release.
