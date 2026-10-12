; Inno Setup script for the Master application.
; Build with (from repo root):
;   "C:\Users\vanjr\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer_build\MasterSetup.iss /DSourceDist=installer_build\dist\master /DOutputDir=installer_build\out
;
; The installer contains no secrets: the master generates its own TLS
; certificate on first launch, and slaves pair with it using a short-lived
; code shown in the app.

#ifndef SourceDist
  #define SourceDist "dist\master"
#endif
#ifndef OutputDir
  #define OutputDir "out"
#endif

[Setup]
AppId={{B6A6C6B0-4F9C-4B4B-9B9E-SMARTDEPLOYERMASTER}}
AppName=Smart Software Deployer - Master
AppVersion=1.0
AppPublisher=Smart Software Deployer
DefaultDirName={autopf}\SmartSoftwareDeployer\Master
DefaultGroupName=Smart Software Deployer
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=master
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
DisableWelcomePage=no
DisableReadyPage=yes
DisableFinishedPage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Dirs]
; The app's own files (exe, DLLs) live under Program Files and are never
; written to after install -- fine for a standard install location.
; But the app's MUTABLE data (config.json, TLS cert/key, the database, the
; catalog, the installers folder, logs) must NOT live there: Program Files
; is not writable by a normal (non-admin) launch of the app, which is how
; it's actually run after this elevated installer finishes. Windows'
; standard answer for "machine-wide app data any user can read/write" is
; %ProgramData%, so that's where master/config.py (MASTER_DIR) now points
; in a frozen build -- create it here with explicit write access for
; standard users, since a freshly created ProgramData subfolder does NOT
; inherit write access for non-admins by default.
Name: "{commonappdata}\SmartSoftwareDeployer\Master"; Permissions: users-modify
Name: "{commonappdata}\SmartSoftwareDeployer\Master\data"; Permissions: users-modify
Name: "{commonappdata}\SmartSoftwareDeployer\Master\auth_manager"; Permissions: users-modify
Name: "{commonappdata}\SmartSoftwareDeployer\Master\installers"; Permissions: users-modify
Name: "{commonappdata}\SmartSoftwareDeployer\Master\logs"; Permissions: users-modify

[Files]
Source: "{#SourceDist}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Place the mutable data templates in %ProgramData%, matching MASTER_DIR
; above -- NOT next to the exe in Program Files.
; "onlyifdoesntexist" means re-running/upgrading the installer never clobbers
; data an admin has already customized.
Source: "..\master\data\config.json.example"; DestDir: "{commonappdata}\SmartSoftwareDeployer\Master\data"; DestName: "config.json"; Flags: onlyifdoesntexist
Source: "..\master\data\catalog.csv"; DestDir: "{commonappdata}\SmartSoftwareDeployer\Master\data"; Flags: onlyifdoesntexist
Source: "..\installers\*"; DestDir: "{commonappdata}\SmartSoftwareDeployer\Master\installers"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\Smart Software Deployer - Master"; Filename: "{app}\SmartDeployerMaster.exe"
Name: "{autodesktop}\Smart Software Deployer - Master"; Filename: "{app}\SmartDeployerMaster.exe"

[Registry]
; Older versions stored a shared token here. Remove it when upgrading.
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
    ValueType: none; ValueName: "DEPLOYER_SHARED_TOKEN"; Flags: deletevalue

[Run]
; Allow this specific program through Windows Firewall on ALL network
; profiles (Domain/Private/Public) so the control (5050), discovery (5051
; UDP), and file (5052) ports it opens aren't silently blocked -- especially
; important on a network Windows classifies as "Public" (default for new
; connections), where inbound traffic is blocked much more aggressively.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Smart Software Deployer - Master"" dir=in action=allow program=""{app}\SmartDeployerMaster.exe"" enable=yes profile=any"; Flags: runhidden waituntilterminated; StatusMsg: "Configuring Windows Firewall..."

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Smart Software Deployer - Master"""; Flags: runhidden waituntilterminated; RunOnceId: "RemoveMasterFirewallRule"

[Code]
const
  WM_SETTINGCHANGE = $001A;
  SMTO_ABORTIFHUNG = $0002;

function SendMessageTimeoutA(hWnd: LongInt; Msg: LongInt; wParam: LongInt; lParam: AnsiString;
  fuFlags: LongInt; uTimeout: LongInt; var lpdwResult: LongInt): LongInt;
  external 'SendMessageTimeoutA@user32.dll stdcall';

procedure BroadcastEnvironmentChange;
var
  ResultCode: LongInt;
begin
  { Tells running processes the old DEPLOYER_SHARED_TOKEN variable is gone. }
  SendMessageTimeoutA(HWND_BROADCAST, WM_SETTINGCHANGE, 0, 'Environment', SMTO_ABORTIFHUNG, 5000, ResultCode);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    BroadcastEnvironmentChange;
end;
