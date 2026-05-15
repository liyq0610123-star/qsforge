<#
QSForge - Build script

Produces a distributable one-folder PyInstaller build at:
    dist\QSForge\QSForge.exe

Usage:
    .\build.ps1            # clean build
    .\build.ps1 -Run       # build, then launch the produced .exe
    .\build.ps1 -Console   # build with a visible console (for debugging
                             first-launch crashes); production build is
                             console-less.

Tip: if SmartScreen warns the first time you run QSForge.exe, click
"More info" -> "Run anyway". The exe is unsigned by design.
#>
param(
    [switch]$Run,
    [switch]$Console,
    # Override the DDC source folder. Default: QSFORGE_DDC_SOURCE env var,
    # or the path used during development. Point this at the folder that
    # CONTAINS RvtExporter.exe (i.e. DDC_CONVERTER_REVIT\) — the whole
    # folder is copied into dist\QSForge\vendor\ddc\ so end users don't
    # need to install DDC separately.
    # DDC source folder. Set $env:QSFORGE_DDC_SOURCE or pass -DdcSource explicitly.
    # If empty, the build will skip DDC bundling and warn the user.
    [string]$DdcSource = $(
        if ($env:QSFORGE_DDC_SOURCE) { $env:QSFORGE_DDC_SOURCE }
        else { "" }
    ),
    # Skip copying DDC into the bundle (for faster dev rebuilds when you
    # already have a previous full build you can test against).
    [switch]$NoDdc,
    # DDC version stamp written into vendor\ddc\.qsforge-ddc-version.
    # The updater compares this against the manifest at runtime to decide
    # whether a newer DDC is available. Default: read from _version.py
    # so build.ps1 + the running app + the installer all stay in sync.
    [string]$DdcVersion = ""
)

# Force UTF-8 for stdout and for native exe arg passing. Without this,
# PowerShell 5.x defaults to the system ANSI code page, which produces
# mojibake in any Chinese strings written by this script (e.g. PDF
# filenames, version.iss header text). The Console.OutputEncoding line
# matters for `Write-Host` output ending up readable in CI logs.
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "=== QSForge :: PyInstaller build ===" -ForegroundColor Cyan
Write-Host ""

# 1. Make sure dependencies are present -------------------------------------
Write-Host "Checking Python dependencies..." -ForegroundColor Yellow
$pipArgs = @("install", "-q", "-r", "requirements.txt", "pyinstaller>=6.0,<7.0")
& python -m pip @pipArgs
if ($LASTEXITCODE -ne 0) { throw "pip install failed ($LASTEXITCODE)" }

# 2. Clean previous build ----------------------------------------------------
foreach ($dir in @("build", "dist")) {
    if (Test-Path $dir) {
        Write-Host "Removing $dir/..." -ForegroundColor DarkGray
        Remove-Item -Recurse -Force $dir
    }
}

# 3. Optional: flip console flag temporarily ---------------------------------
$specFile = "qsforge.spec"
$specBackup = $null
if ($Console) {
    Write-Host "Console mode: enabling stdout/stderr window." -ForegroundColor Yellow
    $specBackup = Get-Content $specFile -Raw
    (Get-Content $specFile -Raw) -replace 'console=False', 'console=True' |
        Set-Content $specFile -Encoding UTF8
}

# 4. Run PyInstaller ---------------------------------------------------------
try {
    Write-Host "Running PyInstaller..." -ForegroundColor Yellow
    & python -m PyInstaller --noconfirm --clean $specFile
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed ($LASTEXITCODE)" }
}
finally {
    if ($specBackup) {
        Set-Content $specFile -Value $specBackup -Encoding UTF8 -NoNewline
    }
}

# 5. Verify PyInstaller output ----------------------------------------------
$exePath = Join-Path $PSScriptRoot "dist\QSForge\QSForge.exe"
if (-not (Test-Path $exePath)) {
    throw "Build claimed success but QSForge.exe is missing: $exePath"
}

$folderSize = (Get-ChildItem "dist\QSForge" -Recurse -File |
               Measure-Object -Property Length -Sum).Sum / 1MB

Write-Host ""
Write-Host "=== PyInstaller build OK ===" -ForegroundColor Green
Write-Host ("Executable : {0}" -f $exePath)
Write-Host ("Folder size: {0:N1} MB" -f $folderSize)

# 6. Render user-facing manuals as PDFs inside the distribution folder -----
# QS teams shouldn't need Notepad or a markdown viewer — ship ready-to-read
# PDFs alongside the .exe. tools/md_to_pdf.py handles the conversion and
# embeds Microsoft YaHei for CJK support.
$docPairs = @(
    @{ Src = "docs\QUICK_START_CN.md"; Pdf = "QSForge 使用说明.pdf";    Title = "QSForge 使用说明" },
    @{ Src = "docs\README.md";         Pdf = "QSForge User Manual.pdf"; Title = "QSForge User Manual" }
)
Write-Host ""
Write-Host "=== Rendering user manuals to PDF ===" -ForegroundColor Cyan
foreach ($pair in $docPairs) {
    $src = Join-Path $PSScriptRoot $pair.Src
    $dst = Join-Path $PSScriptRoot ("dist\QSForge\" + $pair.Pdf)
    if (-not (Test-Path $src)) {
        Write-Host ("  WARN    source doc missing: {0}" -f $pair.Src) -ForegroundColor Yellow
        continue
    }
    & python "tools\md_to_pdf.py" $src $dst --title $pair.Title
    if ($LASTEXITCODE -ne 0) {
        throw ("md_to_pdf.py failed for {0}" -f $pair.Src)
    }
    $kb = (Get-Item $dst).Length / 1KB
    Write-Host ("  Rendered {0,-22} -> {1}  ({2:N1} KB)" -f $pair.Src, $pair.Pdf, $kb) -ForegroundColor Green
}

# 7. Bundle DDC (RvtExporter + all its DLLs) next to the app ----------------
# We do NOT route DDC through PyInstaller's data/hidden-import machinery —
# it's a standalone Windows tool, completely independent of Python. Simpler
# and much faster to just robocopy the folder as a post-build step.
if (-not $NoDdc) {
    $ddcDest = Join-Path $PSScriptRoot "dist\QSForge\vendor\ddc"

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
        $rvtExe = Join-Path $DdcSource "RvtExporter.exe"
        if (-not (Test-Path $rvtExe)) {
            Write-Host ""
            Write-Host "WARNING: RvtExporter.exe not present in DDC source — skipping." -ForegroundColor Yellow
            Write-Host ("  Expected: {0}" -f $rvtExe)
        } else {
            Write-Host ""
            Write-Host "=== Bundling DDC converter ===" -ForegroundColor Cyan
            Write-Host ("  From : {0}" -f $DdcSource)
            Write-Host ("  To   : {0}" -f $ddcDest)

            $null = New-Item -ItemType Directory -Force -Path $ddcDest

            # robocopy exit codes 0-7 are all "success" variants; only >=8 is fatal.
            $rcArgs = @($DdcSource, $ddcDest, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/R:1", "/W:1")
            & robocopy @rcArgs | Out-Null
            if ($LASTEXITCODE -ge 8) {
                throw "robocopy failed (exit $LASTEXITCODE)"
            }
            $global:LASTEXITCODE = 0   # reset so downstream checks don't trip

            $ddcSize = (Get-ChildItem $ddcDest -Recurse -File |
                        Measure-Object Length -Sum).Sum / 1MB
            $ddcCount = (Get-ChildItem $ddcDest -Recurse -File).Count
            Write-Host ("  Copied: {0} files, {1:N1} MB" -f $ddcCount, $ddcSize) -ForegroundColor Green

            # Stamp the DDC folder with its version so the in-app updater can
            # tell at runtime which build is installed. The marker is read
            # by updater.get_ddc_installed_version() and rewritten after
            # every successful in-app DDC update.
            if (-not $DdcVersion) {
                # Pull the default from _version.py so the constants live in
                # exactly one place. Inline Python keeps build.ps1 free of
                # ad-hoc parsing logic for tomorrow's version bumps.
                $resolved = & python -c "import sys; sys.path.insert(0,'src'); import _version; print(_version.DDC_BUNDLED_VERSION)"
                if ($LASTEXITCODE -eq 0 -and $resolved) {
                    $DdcVersion = $resolved.Trim()
                }
            }
            if ($DdcVersion) {
                $marker = Join-Path $ddcDest ".qsforge-ddc-version"
                # Use UTF8 NoBOM — matches what updater.py writes after an
                # in-app upgrade so the file format stays consistent across
                # both code paths.
                [System.IO.File]::WriteAllText($marker, $DdcVersion, [System.Text.UTF8Encoding]::new($false))
                Write-Host ("  DDC version marker: {0}" -f $DdcVersion) -ForegroundColor DarkGray
            } else {
                Write-Host "  WARN: could not determine DDC version — marker not written." -ForegroundColor Yellow
            }

            $folderSize = (Get-ChildItem "dist\QSForge" -Recurse -File |
                           Measure-Object -Property Length -Sum).Sum / 1MB
            Write-Host ("  Bundle total now: {0:N1} MB" -f $folderSize) -ForegroundColor Green
        }
    }
} else {
    Write-Host ""
    Write-Host "-NoDdc flag set: skipping DDC bundling." -ForegroundColor DarkGray
    Write-Host "  End users will need DDC installed or QSFORGE_DDC_EXE set."
}

# 7b. Copy the DDC ad-block utility alongside the .exe ---------------------
# One-time tool users can double-click to permanently block DDC's promo
# domains via the Windows hosts file. Our in-process ad_blocker already
# catches promo windows in most cases; this is the root-cause fix for the
# "already-open browser" case where DDC opens the promo as a new TAB
# (no new top-level window to close).
$adBlockerSrc = Join-Path $PSScriptRoot "tools\block_ddc_ads.bat"
$adBlockerDst = Join-Path $PSScriptRoot "dist\QSForge\block_ddc_ads.bat"
if (Test-Path $adBlockerSrc) {
    Copy-Item -Force $adBlockerSrc $adBlockerDst
    Write-Host ""
    Write-Host ("Added DDC ad-block utility: {0}" -f $adBlockerDst) -ForegroundColor DarkGray
} else {
    Write-Host ""
    Write-Host "WARN: tools\block_ddc_ads.bat missing — DDC ad-block helper not bundled." -ForegroundColor Yellow
}

# 8. Optional: compile Windows installer with Inno Setup --------------------
# Check the three locations where Inno Setup can live: per-machine (both
# Program Files flavours) and per-user (winget's default). This lets the
# script work without admin privileges on the build machine.
$iscCandidates = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
)
$iscc = $iscCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($iscc) {
    Write-Host ""
    Write-Host "=== Compiling installer with Inno Setup ===" -ForegroundColor Cyan

    # Pull the canonical version straight out of _version.py so the
    # installer, the running app, and the update manifest can never
    # disagree by more than the time between two file edits.
    $resolvedAppVer = & python -c "import sys; sys.path.insert(0,'src'); import _version; print(_version.QSFORGE_VERSION)"
    if ($LASTEXITCODE -ne 0 -or -not $resolvedAppVer) {
        throw "Could not read QSFORGE_VERSION from _version.py"
    }
    $resolvedAppVer = $resolvedAppVer.Trim()

    # Emit a tiny generated header for qsforge.iss to include. Keeping
    # this as a separate file (rather than passing /D on the command
    # line) makes it visible in source control diffs at release time.
    $genIss = Join-Path $PSScriptRoot "installer\version.iss"
    $genBody = @"
; AUTO-GENERATED by build.ps1 from _version.py — do not edit by hand.
#define QSForgeVersion "$resolvedAppVer"
"@
    # Inno Setup's #include reads the file via its own preprocessor. UTF-8 *with*
    # BOM is what Inno Setup 6 expects for non-ASCII content; without the BOM it
    # falls back to the system code page on some systems.
    [System.IO.File]::WriteAllText($genIss, $genBody, [System.Text.UTF8Encoding]::new($true))
    Write-Host ("  Wrote installer\version.iss (QSForgeVersion={0})" -f $resolvedAppVer) -ForegroundColor DarkGray

    & $iscc "installer\qsforge.iss"
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed ($LASTEXITCODE)" }

    $setup = Get-ChildItem "installer\output\QSForge-Setup-*.exe" |
             Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($setup) {
        Write-Host ""
        Write-Host "=== Installer OK ===" -ForegroundColor Green
        Write-Host ("Installer  : {0}" -f $setup.FullName)
        Write-Host ("Size       : {0:N1} MB" -f ($setup.Length / 1MB))
    }
} else {
    Write-Host ""
    Write-Host "Inno Setup not found — skipping installer build." -ForegroundColor DarkGray
    Write-Host "To enable: install Inno Setup 6 from https://jrsoftware.org/isdl.php"
    Write-Host "Re-run this script; it will detect ISCC.exe automatically."
}

Write-Host ""
Write-Host "Distribution options:" -ForegroundColor Yellow
Write-Host "  * Portable  -> zip the ENTIRE 'dist\QSForge' folder"
Write-Host "  * Installer -> ship 'installer\output\QSForge-Setup-*.exe' (requires Inno Setup)"
Write-Host ""
if ($NoDdc) {
    Write-Host "DDC was NOT bundled (-NoDdc). Recipients need DDC installed separately." -ForegroundColor Yellow
} else {
    Write-Host "DDC is bundled at 'vendor\ddc\' — recipients need nothing else." -ForegroundColor Green
}
Write-Host ""

if ($Run) {
    Write-Host "Launching QSForge.exe..." -ForegroundColor Cyan
    Start-Process $exePath
}
