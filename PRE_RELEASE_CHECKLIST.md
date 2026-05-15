> **Status (2026-05-15):** This checklist was written before the rebrand from ArchiQS to QSForge. Item B7 (rebrand) is implemented by the plan at `docs/superpowers/plans/2026-05-15-qsforge-rebrand-and-release.md`. The checklist body still uses the old `ArchiQS` name for historical accuracy.

# ArchiQS 1.6.0 — Pre-Release Checklist

Audit date: 2026-05-15 · Target: commercial release to clients.

Items are grouped by severity. Every item has a **file path**, **what's wrong**, and a **concrete fix**. Tick the boxes as you go.

---

## ☠️ BLOCKERS — Do not ship until these are fixed

### B1. Auto-update is silently DISABLED

- **Where:** `src/_version.py`, lines 56–60.
- **What:** `DEFAULT_MANIFEST_URL = ""`. The code in `manifest_url()` then returns empty string, and `update_checks_enabled()` returns `False`. Customers will never receive updates, bug-fixes, or security patches. The in-app "Updates" panel will silently report "disabled".
- **Why this is a blocker:** You wrote an entire updater system, a manifest schema, SHA-256 verification, and a rollback path. If `DEFAULT_MANIFEST_URL` is empty when you ship, none of it runs.
- **Fix:**
  1. Decide where you're hosting `manifest.json` (GitHub Releases, your own VPS, S3). HTTPS only.
  2. Set `DEFAULT_MANIFEST_URL = "https://your-host/path/manifest.json"`.
  3. Create the live `manifest.json` from `updates/manifest.example.json`, fill in `archiqs.version=1.6.0`, the installer URL, SHA-256 (`Get-FileHash` of the 1.6.0 EXE), and size.
  4. Smoke test: launch ArchiQS, confirm the "Updates" panel shows "You're on the latest version".

### B2. Mojibake in shipped PDF filename — Chinese manual ships with a garbled name

- **Where:** `dist/ArchiQS/ArchiQS 浣跨敤璇存槑.pdf` (should be `ArchiQS 使用说明.pdf`).
- **Root cause:** `build.ps1` line 100 contains `Pdf = "ArchiQS 使用说明.pdf"`. PowerShell 5.x reads `.ps1` files using the system ANSI code page, not UTF-8, unless the file has a UTF-8 BOM. On a non-Chinese Windows, those Chinese bytes get mis-decoded once when PowerShell reads the script, then again when the PDF filename is written to disk. Result: `浣跨敤璇存槑`.
- **The same root cause produces:** the mojibake header in `installer/version.iss` line 1 (`鈥?` instead of `—`).
- **Fix (choose one):**
  - **Easiest:** Re-save `build.ps1` as **UTF-8 with BOM** in your editor. PowerShell 5.x respects the BOM.
  - **Or run the build under PowerShell 7+** (`pwsh.exe`), which defaults to UTF-8.
  - **Belt-and-braces fix in build.ps1:**
    ```powershell
    # At the top of the script:
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    ```
- **Also fix `installer/version.iss` generation** at `build.ps1:244`: replace `Set-Content -Path $genIss -Value $genBody -Encoding UTF8 -NoNewline` with `[System.IO.File]::WriteAllText($genIss, $genBody, [System.Text.UTF8Encoding]::new($true))` (UTF-8 **with** BOM).
- **Verify:** After fixing, rebuild and confirm `dir installer\output` and `dir dist\ArchiQS\*.pdf` show the correct Chinese filenames.

### B3. CJK font is NOT bundled — Chinese PDFs will be blank/boxed on non-CN Windows

- **Where:** `tools/md_to_pdf.py:63–72` (build-time) and the runtime PDF report generator in `src/pdf_report.py`.
- **What:** Font registration points at `C:\Windows\Fonts\msyh.ttc` (Microsoft YaHei). YaHei ships **by default only on Chinese-language Windows**. On English/SG/MY/HK Windows it's often missing. The fallback chain is `simhei.ttf → simsun.ttc`, all of which are also CN-only system fonts. Final fallback is Helvetica, which renders Chinese as `□□□`.
- **I confirmed:** no `*.ttc` or `msyh*` font ships in `dist/ArchiQS/`. Only matplotlib's bundled fonts are present, and none of them cover CJK.
- **Why this is a blocker:** Your product is targeted at SG/HK/MY QS teams (per code comments). Many of those machines are English Windows. The Chinese user manual and any PDF report containing Chinese text will be unreadable.
- **Fix:**
  1. Bundle a CJK-capable open-source font. Recommended: **Noto Sans CJK SC** (Open Font License — redistribution allowed). Download `NotoSansCJKsc-Regular.otf` and `NotoSansCJKsc-Bold.otf`.
  2. Drop them in `assets/fonts/`.
  3. Add to `archiqs.spec` datas: `(str(PROJECT / "assets" / "fonts"), "assets/fonts")`.
  4. Change `md_to_pdf.py` and `pdf_report.py` font lookups to prefer the bundled path first, then fall back to `C:\Windows\Fonts\*` for dev convenience.
  5. Test the PDF on an English Windows VM with no Chinese fonts installed.

### B4. Developer's username and absolute path is hardcoded into shipped EXE

- **Where:** `src/ddc_runner.py:262–265` (compiled into `dist/ArchiQS/_internal/...` and shipped to customers), and `build.ps1:27`.
- **What:**
  ```python
  DEFAULT_DDC_EXE = (
      r"C:\Users\11390\Desktop\cad2data-Revit-IFC-DWG-DGN-main\..."
  )
  ```
  `11390` is the dev account name. Anyone who runs `strings ArchiQS.exe` (or unzips `_internal/`) sees it. Not a security hole, but unprofessional, and the path is dead code on every customer machine.
- **Fix:** Replace `DEFAULT_DDC_EXE` with `None` and check for `None` at the call site. The bundled path and env-var path already cover all real cases. Same in `build.ps1`: change the default `DdcSource` to an empty string and produce a clearer error if no DDC source is given.

### B5. No LICENSE / EULA / Third-Party Notices anywhere

- **Where:** Root of the repo and `dist/ArchiQS/`. I checked — no `LICENSE`, `EULA`, `COPYING`, or `THIRD-PARTY-NOTICES` file exists.
- **Why this matters:**
  - **You need a EULA** that the customer accepts. Inno Setup has `[LicenseFile]` for exactly this purpose; currently your installer has none.
  - You **redistribute** Flask, pywebview, openpyxl, pandas, reportlab, ReportLab, and DDC (RvtExporter). Each of those has license obligations (Apache 2.0, BSD-3-Clause, MIT, etc.) that require attribution.
  - DDC is a third-party tool — confirm its license allows you to bundle and redistribute `RvtExporter.exe` + ~165 DLLs (~600 MB) inside a commercial product. The DDC website is `datadrivenconstruction.io`; check their terms.
- **Fix:**
  1. Add `LICENSE.txt` at repo root (your commercial EULA).
  2. Add `THIRD-PARTY-NOTICES.md` listing every Python dependency from `requirements.txt` with its license and copyright notice.
  3. In `installer/archiqs.iss`, add under `[Setup]`: `LicenseFile=..\LICENSE.txt` so the installer presents the EULA at install time.
  4. Bundle `LICENSE.txt` and `THIRD-PARTY-NOTICES.md` into `dist/ArchiQS/` so they're accessible from the installed app.
  5. **Verify DDC's redistribution license** before shipping. If it forbids redistribution, you have to ship a downloader instead of bundling DDC.

### B6. Installer and EXE are unsigned — every customer gets a SmartScreen warning

- **Where:** `archiqs.spec:103` (`codesign_identity=None`), `installer/archiqs.iss` (no `SignTool=` directive).
- **What:** On first launch, Windows SmartScreen shows "Windows protected your PC" with **only a "Don't run" button** by default. The user has to click "More info → Run anyway". For a paid commercial product, this looks unprofessional and many customers will refuse to install.
- **Fix:** Buy a code-signing certificate (OV ~$200/yr; EV ~$300/yr — EV is the only one that gets SmartScreen reputation immediately). Sign both:
  1. `dist/ArchiQS/ArchiQS.exe` (with `signtool sign ...` before running Inno Setup).
  2. `installer/output/ArchiQS-Setup-1.6.0.exe` (with Inno's `SignTool=` directive).
- **If you can't sign before this release:** include a "First launch may show a SmartScreen warning — click 'More info' → 'Run anyway'" note in `docs/QUICK_START_CN.md` AND in the installer welcome screen. Plan to sign for 1.6.1.

---

## ⚠️ HIGH — Should fix before release

### H1. `block_ddc_ads.bat` will trigger AV / SmartScreen and looks malicious

- **Where:** `tools/block_ddc_ads.bat`, shipped via `build.ps1:201–210` to `dist/ArchiQS/`.
- **What it does:** Requests UAC elevation, edits `%SystemRoot%\System32\drivers\etc\hosts` to DNS-blackhole DDC promo domains. Hosts-file edits are a textbook malware technique; Defender / Sophos / CrowdStrike will routinely flag this.
- **Why it's not a B-blocker:** The in-process `src/ad_blocker.py` already closes DDC promo windows in most cases. This batch is only needed for the "promo opens as a new tab in an already-open browser" edge case.
- **Fix (pick one):**
  1. **Best:** Remove the .bat from the shipped bundle. Instead, surface a "Block DDC ads in your hosts file" button in the in-app Settings that runs the same logic with a clear confirmation dialog, code-signed.
  2. **OK:** Keep it, but rename `block_ddc_ads.bat` → `block_ddc_ads (requires admin).cmd`, add a clear `echo` header explaining what it does, and document it in the user manual. Sign it with the same cert as the EXE.
  3. **Minimum:** Don't ship it. Document the manual hosts-file edit in the user manual instead.

### H2. `.gitignore` will leak the entire build output to your git repo

- **Where:** `.gitignore` (8 entries only).
- **What's missing:** `dist/`, `installer/output/`, `_to_delete/`, `venv/`, `.venv/`, `last_result.json`, `archiqs_crash.log`, `build_log*.txt`, `*.spec.bak`, `.cursorrules` is fine but `.superpowers/`, `.webview-data/` (already there), `tests/last_result.json`, `tests/*.xlsx` (test outputs).
- **Why it matters:** If you `git push` after building 1.6.0, you'll push ~3 GB of binaries to your remote, blow through GitHub's repo size limit, and ship dev paths.
- **Fix:** Replace `.gitignore` with the version below. **Critically**, also run `git status` after fixing and confirm no large binaries are already tracked. If they are, use `git rm --cached` then commit.

  ```gitignore
  # Python
  __pycache__/
  *.pyc
  *.pyo
  .pytest_cache/

  # Virtualenvs
  venv/
  .venv/
  env/

  # Build outputs
  build/
  dist/
  installer/output/
  *.spec.bak
  build_log*.txt

  # Runtime droppings
  .webview-data/
  last_result.json
  archiqs_crash.log
  archiqs_rvtexporter_last.txt
  *.log

  # Cleanup staging
  _to_delete/

  # IDE / OS
  .vscode/
  .idea/
  .cursorrules
  .superpowers/
  .DS_Store
  Thumbs.db
  ```

### H3. 94 `print()` calls in production source — log pollution & lost diagnostics

- **Where:** `src/ddc_runner.py` (12), `src/module0_inventory.py` (32), `src/module1_qs_readiness.py` (23), `src/module2_bq_draft.py` (15), `src/ad_blocker.py` (3), `src/pdf_report.py` (2), `src/updater.py` (6), `src/server.py` (1). Total ~94.
- **What's wrong:** In a `console=False` PyInstaller build, `sys.stdout` is `None`. Every `print()` either silently no-ops or, worse, raises `AttributeError: 'NoneType' object has no attribute 'write'` if anything depends on a return value. You're losing all diagnostic output customers would otherwise hand you when they hit a bug.
- **Fix:** Replace `print(...)` with `logging.getLogger(__name__).info(...)` (or `.warning` / `.error` as appropriate). Configure logging in `main.py` to write to `user_data_dir() / "archiqs.log"` with rotation. Customers can then attach that file to a support email.

### H4. `Flask app.run()` is a development server

- **Where:** `src/server.py:732`.
- **What:** `app.run(host=HOST, port=PORT, threaded=True, debug=False, use_reloader=False)`. Flask's own docs say "do not use the development server in a production deployment". For a single-user desktop app it's mostly fine, but you'll occasionally see weird socket errors under load (e.g. a customer running multiple concurrent jobs).
- **Fix:** Use `waitress` (pure Python, Windows-friendly, MIT-licensed). Add `waitress>=3.0,<4.0` to `requirements.txt`. Replace the `app.run(...)` call with:
  ```python
  from waitress import serve
  serve(app, host=HOST, port=PORT, threads=8)
  ```
  Then add `waitress` to `hiddenimports` in `archiqs.spec`.

### H5. Port 7890 may be in use → silent boot failure

- **Where:** `src/server.py:36-37`, `main.py:319-331` (the health check times out after 15s).
- **What:** If port 7890 is already taken (rare, but: VS Code Live Server, some game launchers), the Flask thread will raise `OSError: [WinError 10048]` inside a daemon thread; the crash hook captures it to `archiqs_crash.log`, but the user sees a window that says "ArchiQS server did not become ready in 15s" and quits. The crash log is buried.
- **Fix:** In `server.main()`, catch the bind error and either (a) try the next free port in a small range (7890–7899) and tell `main.py` which one was chosen, or (b) show a native `MessageBox` saying "Port 7890 is in use — please close <whatever> and retry". Option (a) is more robust.

### H6. No version-mismatch guard on the update installer

- **Where:** `src/updater.py` (downloads + runs `ArchiQS-Setup-x.y.z.exe`).
- **What:** If the manifest claims version 2.0.0 but the downloaded installer is somehow tampered or replaced with 1.5.10, your updater would happily apply a *downgrade*. The SHA-256 check protects integrity, but the manifest you trust is whatever's at the URL — if your release host is ever compromised, an attacker can publish a downgrade with a valid SHA.
- **Fix:** In `updater.py` (read the file and find the comparison spot), refuse to install any version that's not strictly greater than `ARCHIQS_VERSION`. Also reject installers whose `version` field doesn't match the filename pattern `ArchiQS-Setup-<version>.exe`.

---

## 🛠️ MEDIUM — Fix in 1.6.1 / next patch

### M1. `dist/` is 818 MB but the installer only needs to copy the same content once

- The installer at `installer/output/ArchiQS-Setup-1.6.0.exe` is 208 MB (LZMA-compressed). The `dist/ArchiQS/` tree it was compiled from is 818 MB. You can delete `dist/` after a build — it regenerates from `build.ps1`. Keeps your repo small.

### M2. Inno Setup AppId is not a real GUID

- `installer/archiqs.iss:33` uses `{{8B2E5F6C-0A1D-4E4A-9C5B-ARCHIQS00001}`. The trailing `ARCHIQS00001` contains non-hex characters (R, C, H, I, Q, S) — it's not a valid GUID. Inno tolerates this as a string, but Windows Installer-style tooling won't. Generate a real GUID once (`[guid]::NewGuid()` in PowerShell) and pin it forever — never change it, or upgrades break.

### M3. Default Inno install path is per-user (`{localappdata}\ArchiQS`)

- `installer/archiqs.iss:53`. This is intentional (no admin needed) but means the ~600 MB DDC bundle lives in every user profile on multi-user machines. Consider offering an "install for all users" branch via `PrivilegesRequiredOverridesAllowed=dialog`.

### M4. `last_result.json` at the repo root is leftover test output

- 48 KB file from May 7. You asked me to keep it, but flagging again that it's a runtime output — it should not be in source control. Confirm it's not referenced from anything (`grep -r "last_result.json" src/`) and delete it.

### M5. WebView2 cache is wiped on every launch

- `main.py:_reset_webview_cache` deletes `.webview-data` on every start. This is fine for forcing fresh JS/HTML, but it means every launch re-initialises WebView2 (slower cold start, occasional CCT prompts on locked-down corporate machines). Consider a versioned cache key: only wipe when the bundled `static/` hash changes.

### M6. Crash log lives in `user_data_dir()`, next to the EXE

- `archiqs_crash.log` lands at `{app}\archiqs_crash.log` (per-user install). When a user uninstalls, the `[UninstallDelete]` directive removes it — good. But during normal use, the log grows without bound (append-only). Add a 5 MB rotation or trim on launch.

### M7. Tests directory ships a real Revit model (167 MB)

- `tests/TIO (Beam Furring, Lift Pit)_detached.rvt`. Confirm `archiqs.spec` doesn't include it (it doesn't — `tests` isn't in `datas`). If you publish source to git, this single file blows the GitHub 100 MB hard limit per file. Use Git LFS or keep test fixtures out of the main repo.

### M8. PyInstaller `private_mode=True` for pywebview is a feature, but mixed with persistent state

- `main.py:394`. `private_mode=True` tells WebView2 to use a clean state — but you also set `WEBVIEW2_USER_DATA_FOLDER` to a persistent path two lines earlier. Decide which you want.

---

## ✨ LOW / Polish

- **L1.** `archiqs_crash.log` in `_to_delete/misc/` from earlier session — confirms users will see this file. Mention in user manual that they can email it to support.
- **L2.** No copyright header in any `.py` file. Add `# Copyright (c) 2026 <YourCompany>. Commercial use license.` to source files.
- **L3.** `main.py:33` AppUserModelID hardcodes `1` as the SubProduct version. Microsoft recommends bumping this when you do breaking shell changes (jump lists, pinned shortcuts). Not urgent.
- **L4.** No `docs/CHANGELOG.md`. Customers should be able to read what changed in 1.6.0 vs 1.5.12.
- **L5.** `requirements.txt` doesn't pin patch versions. For a commercial release, freeze with `pip freeze > requirements.lock.txt` so future rebuilds are reproducible.
- **L6.** `assets/archiqs.ico` — verify it has all sizes (16, 24, 32, 48, 64, 128, 256). Missing sizes show as blurry in Alt-Tab.

---

## ✅ Things that are already good (no action)

These came up during audit and look fine — listing so you don't worry about them:

- SHA-256 verification of update downloads is correctly enforced (`updater.py`, integrity check happens before swap).
- Crash log + boot breadcrumbs (`main.py:_install_crash_hook`, `_boot_marker`) is a thoughtful diagnostic setup.
- WebView2 install check in `archiqs.iss:135–159` is robust (3 registry locations checked).
- Per-user install path (`{localappdata}\ArchiQS`) means no admin required — good for corporate machines.
- Job model in `server.py` is thread-safe enough for the single-user desktop pattern.
- Module 2 checks are intentionally additive (one failing check doesn't kill the job).
- No bare `except:` clauses in the codebase. No `except Exception: pass`. Good hygiene.
- HTTPS-only manifest URL pattern is encouraged in `_version.py`'s comments.

---

## 🚦 Release decision

**If you can fix B1, B2, B3, B4, B5, B6 + H1, H2 in the next 1–2 days, ship 1.6.1 — not 1.6.0.**

The cleanest path: bump `_version.py` to `1.6.1`, do the fixes above, rebuild. **Do not ship 1.6.0 to clients** — too many of the blockers are externally visible (mojibake filename, unsigned EXE warnings, missing EULA, broken Chinese PDF on non-CN Windows). Each one is a refund request waiting to happen.
