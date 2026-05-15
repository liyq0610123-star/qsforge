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
#define QSForgeAppId       "{{F275A25B-A29D-4641-B29A-169A3B83C752}"
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
