@echo off
setlocal EnableExtensions

rem ============================================================
rem  QSForge - Block DDC promo pages (permanent, one-time setup)
rem
rem  DDC Community edition forces the default browser open to
rem  datadrivenconstruction.io after every Revit conversion.
rem  This script adds a few lines to the Windows hosts file so
rem  those pages can't load.
rem
rem  Requires: administrator rights (will auto-elevate via UAC).
rem  Undo:     run this script again and choose "unblock".
rem ============================================================

title QSForge - Block DDC ads

rem --- Self-elevate to admin if not already -----------------------
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  This script needs administrator rights to edit the hosts file.
    echo  A UAC prompt will appear next.
    echo.
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs -ArgumentList '%*'"
    exit /b
)

set "HOSTS=%SystemRoot%\System32\drivers\etc\hosts"
set "MARK1=# QSForge-BEGIN DDC-ad-block"
set "MARK2=# QSForge-END DDC-ad-block"
set "BACKUP=%HOSTS%.qsforge.bak"

echo ============================================================
echo   QSForge - Block DDC promo pages
echo ============================================================
echo.
echo  Hosts file: %HOSTS%
echo.

rem --- Pick action -------------------------------------------------
set "ACTION=%~1"
if /I "%ACTION%"=="unblock" goto :unblock
if /I "%ACTION%"=="block"   goto :block

echo  1) Block  DDC promo pages (recommended)
echo  2) Unblock (remove previous block)
echo  3) Cancel
echo.
set /p CHOICE=  Your choice [1/2/3]: 

if "%CHOICE%"=="1" goto :block
if "%CHOICE%"=="2" goto :unblock
goto :eof

:block
rem --- Abort if already installed ----------------------------------
findstr /C:"%MARK1%" "%HOSTS%" >nul 2>&1
if %errorlevel% equ 0 (
    echo.
    echo  [OK] DDC ad-block is ALREADY installed in your hosts file.
    echo       Nothing to do.
    echo.
    pause
    exit /b 0
)

rem --- Backup once -------------------------------------------------
if not exist "%BACKUP%" (
    copy /Y "%HOSTS%" "%BACKUP%" >nul
    echo  Backup written: %BACKUP%
)

rem --- Append the block --------------------------------------------
>>"%HOSTS%" echo.
>>"%HOSTS%" echo %MARK1%
>>"%HOSTS%" echo 0.0.0.0 datadrivenconstruction.io
>>"%HOSTS%" echo 0.0.0.0 www.datadrivenconstruction.io
>>"%HOSTS%" echo %MARK2%

rem --- Flush DNS cache so the change takes effect immediately ------
ipconfig /flushdns >nul 2>&1

echo.
echo  [DONE] DDC promo pages are now blocked for all browsers:
echo    - datadrivenconstruction.io
echo    - www.datadrivenconstruction.io
echo.
echo  QSForge itself is NOT affected (it doesn't need internet).
echo  Revit conversion will keep working exactly as before.
echo.
echo  To undo, run this script again and choose "unblock".
echo.
pause
exit /b 0

:unblock
rem --- Not installed? -----------------------------------------------
findstr /C:"%MARK1%" "%HOSTS%" >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  [OK] Nothing to remove - block is not present.
    echo.
    pause
    exit /b 0
)

rem --- Rewrite hosts without the marked block ----------------------
if not exist "%BACKUP%" copy /Y "%HOSTS%" "%BACKUP%" >nul

powershell -NoProfile -Command ^
    "$p = $env:SystemRoot + '\System32\drivers\etc\hosts';" ^
    "$t = Get-Content -Raw -LiteralPath $p;" ^
    "$r = [regex]'(?ms)\r?\n?# QSForge-BEGIN DDC-ad-block.*?# QSForge-END DDC-ad-block\s*';" ^
    "$t = $r.Replace($t, \"\");" ^
    "Set-Content -LiteralPath $p -Value $t -NoNewline -Encoding ASCII"

ipconfig /flushdns >nul 2>&1

echo.
echo  [DONE] DDC ad-block removed from hosts.
echo         Backup preserved at: %BACKUP%
echo.
pause
exit /b 0
