; Inno Setup script for the Master application.
; Build with (from repo root):
;   "C:\Users\vanjr\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer_build\MasterSetup.iss /DSharedToken=<token> /DSourceDist=installer_build\dist\master /DOutputDir=installer_build\out
;
; SharedToken, SourceDist and OutputDir are supplied by the build script at
; compile time -- nothing secret is stored in this file itself.

#ifndef SharedToken
  #define SharedToken "CHANGEME"
#endif
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
; Set the shared token as a SYSTEM environment variable (not per-user) so it
; is visible both to interactively-launched GUI processes and to the slave's
; Windows Service (which runs as LocalSystem) -- mirrors this repo's existing
; "DEPLOYER_SHARED_TOKEN must be a real env var" security convention.
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
    ValueType: string; ValueName: "DEPLOYER_SHARED_TOKEN"; ValueData: "{#SharedToken}"; \
    Flags: preservestringtype

[Run]
; Allow this specific program through Windows Firewall on ALL network
; profiles (Domain/Private/Public) so the control (5050), discovery (5051
; UDP), and file (5052) ports it opens aren't silently blocked -- especially
; important on a network Windows classifies as "Public" (default for new
; connections), where inbound traffic is blocked much more aggressively.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Smart Software Deployer - Master"" dir=in action=allow program=""{app}\SmartDeployerMaster.exe"" enable=yes profile=any"; Flags: runhidden waituntilterminated; StatusMsg: "Configuring Windows Firewall..."
; NOTE: deliberately no "launch now" entry here. Launching the app directly
; from the installer would spawn it as a CHILD PROCESS of Setup.exe, which
; inherits Setup.exe's OWN environment as captured when Setup.exe itself
; started -- i.e. BEFORE the [Registry] section above wrote the new
; DEPLOYER_SHARED_TOKEN. The app would crash with "environment variable is
; not set" even though the registry is correctly updated. Explorer (and
; anything it launches, like the Desktop/Start Menu shortcut below) DOES
; get notified via the BroadcastEnvironmentChange call below and picks up
; the fresh value correctly -- so launching must happen via the shortcut,
; never as a direct child of this installer process.

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Smart Software Deployer - Master"""; Flags: runhidden waituntilterminated; RunOnceId: "RemoveMasterFirewallRule"

[Code]
const
  WM_SETTINGCHANGE = $001A;
  SMTO_ABORTIFHUNG = $0002;

function SendMessageTimeoutA(hWnd: LongInt; Msg: LongInt; wParam: LongInt; lParam: AnsiString;
  fuFlags: LongInt; uTimeout: LongInt; var lpdwResult: LongInt): LongInt;
  external 'SendMessageTimeoutA@user32.dll stdcall';

function SetEnvironmentVariableW(lpName: string; lpValue: string): BOOL;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

procedure BroadcastEnvironmentChange;
var
  ResultCode: LongInt;
begin
  { Notifies already-running processes (e.g. Explorer) that the environment
    changed, so a Start Menu / Desktop shortcut launched right after this
    install picks up the new DEPLOYER_SHARED_TOKEN without a reboot/logoff.
    This does NOT affect Setup.exe's own already-captured environment (see
    UpdateOwnProcessEnvironment below), only OTHER processes that choose to
    refresh their cache in response to this broadcast. }
  SendMessageTimeoutA(HWND_BROADCAST, WM_SETTINGCHANGE, 0, 'Environment', SMTO_ABORTIFHUNG, 5000, ResultCode);
end;

procedure UpdateOwnProcessEnvironment;
begin
  { Setup.exe's own process environment block was captured when it started,
    BEFORE the [Registry] section wrote DEPLOYER_SHARED_TOKEN -- any [Run]
    entry after this point would otherwise spawn a child process that
    inherits that stale (missing) value and crash. Explicitly set it in our
    own process now so every subsequent [Run] step in this installer sees it. }
  SetEnvironmentVariableW('DEPLOYER_SHARED_TOKEN', '{#SharedToken}');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    UpdateOwnProcessEnvironment;
    BroadcastEnvironmentChange;
  end;
end;
