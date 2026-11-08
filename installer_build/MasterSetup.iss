; Inno Setup script for the Master application.
; Build with (from repo root):
;   python installer_build/build_installers.py
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
; The master's mutable data lives in %ProgramData% (master/config.py,
; MASTER_DIR): config.json, the TLS private key, users.json, the database
; with the audit log, the catalog, the installers that get pushed to every
; lab PC, and logs. Anyone who can change these controls the whole fleet,
; so after install they're locked to Administrators and SYSTEM only (see
; LockDownMasterData below), and the master app itself requires admin
; rights to run (uac_admin in master.spec).
Name: "{commonappdata}\SmartSoftwareDeployer\Master"
Name: "{commonappdata}\SmartSoftwareDeployer\Master\data"
Name: "{commonappdata}\SmartSoftwareDeployer\Master\auth_manager"
Name: "{commonappdata}\SmartSoftwareDeployer\Master\installers"
Name: "{commonappdata}\SmartSoftwareDeployer\Master\logs"

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

function RunIcacls(const Params: string): Boolean;
var
  ResultCode: Integer;
begin
  ResultCode := -1;
  Result := Exec(ExpandConstant('{sys}\icacls.exe'), Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode)
    and (ResultCode = 0);
  if not Result then
    Log(Format('icacls %s failed (exit code %d)', [Params, ResultCode]));
end;

{ Restricts the master's data folder to Administrators (S-1-5-32-544) and
  SYSTEM (S-1-5-18). Three steps, because removing the old grants alone
  isn't enough on an upgrade:
  1. Make Administrators the owner of everything. Older versions ran the
     master as a normal user, so that user owns users.json, the database
     and the key -- and a file's owner can always rewrite its permissions.
  2. Reset every file and subfolder to plain inherited permissions, which
     drops the explicit "Users: modify" grants older versions added.
  3. Stop inheriting from %ProgramData% (which lets all users read) and
     grant only Administrators and SYSTEM; everything below inherits that. }
procedure LockDownMasterData;
var
  DataRoot: string;
  OwnerOk, ResetOk, GrantOk: Boolean;
begin
  DataRoot := '"' + ExpandConstant('{commonappdata}\SmartSoftwareDeployer\Master') + '"';
  OwnerOk := RunIcacls(DataRoot + ' /setowner *S-1-5-32-544 /T /C /Q');
  ResetOk := RunIcacls(DataRoot + ' /reset /T /C /Q');
  GrantOk := RunIcacls(DataRoot + ' /inheritance:r /grant:r *S-1-5-18:(OI)(CI)F *S-1-5-32-544:(OI)(CI)F /C /Q');
  if not (OwnerOk and ResetOk and GrantOk) then
    SuppressibleMsgBox('Setup could not fully restrict access to the Master''s data folder:' + #13#10 +
      ExpandConstant('{commonappdata}\SmartSoftwareDeployer\Master') + #13#10#13#10 +
      'Other users of this PC may be able to read or change it. Run Setup again, ' +
      'or check the folder''s permissions manually.', mbError, MB_OK, IDOK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    BroadcastEnvironmentChange;
    LockDownMasterData;
  end;
end;
