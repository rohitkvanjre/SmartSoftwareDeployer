; Inno Setup script for the Slave agent.
; Build with (from repo root):
;   "C:\Users\vanjr\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer_build\SlaveSetup.iss /DSharedToken=<token> /DSourceDist=installer_build\dist\slave /DOutputDir=installer_build\out
;
; SharedToken MUST be the exact same value used to build MasterSetup.iss in
; the same build run, or the slave will never authenticate to the master.

#ifndef SharedToken
  #define SharedToken "CHANGEME"
#endif
#ifndef SourceDist
  #define SourceDist "dist\slave"
#endif
#ifndef OutputDir
  #define OutputDir "out"
#endif

[Setup]
AppId={{C7B7D7C1-5A0D-4C5C-AC0F-SMARTDEPLOYERSLAVE}}
AppName=Smart Software Deployer - Slave Agent
AppVersion=1.0
AppPublisher=Smart Software Deployer
DefaultDirName={autopf}\SmartSoftwareDeployer\Slave
DefaultGroupName=Smart Software Deployer
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=slave
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

[Files]
Source: "{#SourceDist}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Place the config template exactly where slave/config.py looks for it:
; {app}\config.json, directly next to SoftwareDeployerAgent.exe.
; "onlyifdoesntexist" so re-running/upgrading never clobbers a customized config.
Source: "..\slave\config.json.example"; DestDir: "{app}"; DestName: "config.json"; Flags: onlyifdoesntexist

[Registry]
; Same SYSTEM environment variable as the master installer, so this agent
; authenticates automatically -- must be built with the identical token.
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
    ValueType: string; ValueName: "DEPLOYER_SHARED_TOKEN"; ValueData: "{#SharedToken}"; \
    Flags: preservestringtype

[Run]
; Allow this program through Windows Firewall on ALL network profiles
; (Domain/Private/Public) BEFORE starting the service, so its outbound UDP
; discovery broadcast and TCP connection to the master aren't blocked --
; especially on a network Windows classifies as "Public" (the default for
; new connections), which restricts traffic much more aggressively.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Smart Software Deployer - Slave Agent"" dir=in action=allow program=""{app}\SoftwareDeployerAgent.exe"" enable=yes profile=any"; Flags: runhidden waituntilterminated; StatusMsg: "Configuring Windows Firewall..."
; Register the Windows Service (this also silently registers the tray-app
; autostart Scheduled Task -- see slave/service.py's install_tray_autostart(),
; which looks for tray_app.exe right next to this same exe).
; --startup=auto MUST come before the "install" command -- pywin32's
; HandleCommandLine parses options-then-command, not the other way round.
; Without it, pywin32 defaults a newly installed service to Manual startup,
; so it only ever ran because this [Run] section starts it once, right now;
; it would never come back on its own after the next reboot. Plain "auto"
; (not "delayed") starts it immediately at boot rather than waiting ~2
; minutes for the delayed-start window -- fine either way since SvcDoRun's
; own connect loop already retries every 15s regardless of how soon the
; network is actually up, so "auto" just means the first attempt (and any
; retries) happen sooner.
Filename: "{app}\SoftwareDeployerAgent.exe"; Parameters: "--startup=auto install"; Flags: runhidden waituntilterminated; StatusMsg: "Registering the Software Deployer Agent service..."
Filename: "{app}\SoftwareDeployerAgent.exe"; Parameters: "start"; Flags: runhidden waituntilterminated; StatusMsg: "Starting the Software Deployer Agent service..."

[UninstallRun]
; Cleanly stop and unregister the service (and its scheduled task, via
; remove_tray_autostart()) BEFORE Inno Setup deletes the executable files.
Filename: "{app}\SoftwareDeployerAgent.exe"; Parameters: "stop"; Flags: runhidden waituntilterminated; RunOnceId: "StopAgentService"
Filename: "{app}\SoftwareDeployerAgent.exe"; Parameters: "remove"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveAgentService"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Smart Software Deployer - Slave Agent"""; Flags: runhidden waituntilterminated; RunOnceId: "RemoveSlaveFirewallRule"

[Code]
const
  WM_SETTINGCHANGE = $001A;
  SMTO_ABORTIFHUNG = $0002;

var
  MasterIPPage: TInputQueryWizardPage;

function IsValidOctet(const S: string): Boolean;
var
  I: Integer;
  Ch: Char;
begin
  Result := False;
  if (Length(S) = 0) or (Length(S) > 3) then
    Exit;
  for I := 1 to Length(S) do
  begin
    { Plain equality checks instead of a ['0'..'9'] set range -- Inno's
      Pascal Script parser rejects char ranges inside set literals here. }
    Ch := S[I];
    if not ((Ch = '0') or (Ch = '1') or (Ch = '2') or (Ch = '3') or (Ch = '4') or
            (Ch = '5') or (Ch = '6') or (Ch = '7') or (Ch = '8') or (Ch = '9')) then
      Exit;
  end;
  Result := StrToIntDef(S, -1) <= 255;
end;

function IsValidIPv4(const S: string): Boolean;
var
  Work, Part: string;
  DotPos, PartCount: Integer;
begin
  Result := False;
  Work := S;
  PartCount := 0;
  repeat
    DotPos := Pos('.', Work);
    if DotPos = 0 then
    begin
      Part := Work;
      Work := '';
    end
    else
    begin
      Part := Copy(Work, 1, DotPos - 1);
      Work := Copy(Work, DotPos + 1, MaxInt);
    end;
    if not IsValidOctet(Part) then
      Exit;
    PartCount := PartCount + 1;
    if PartCount > 4 then
      Exit;
  until DotPos = 0;
  Result := (PartCount = 4);
end;

procedure MasterIPKeyPress(Sender: TObject; var Key: Char);
begin
  { Blocks every keystroke that isn't a digit, the dot separator, or a
    control character (Backspace, etc.) -- letters and other symbols never
    even make it into the field, rather than only being rejected on Next.
    Plain equality checks instead of a set range, matching IsValidOctet. }
  if not ((Key = '0') or (Key = '1') or (Key = '2') or (Key = '3') or (Key = '4') or
          (Key = '5') or (Key = '6') or (Key = '7') or (Key = '8') or (Key = '9') or
          (Key = '.') or (Key < #32)) then
    Key := #0;
end;

procedure InitializeWizard;
begin
  { Asked once, at install time -- optional. Left blank, MASTER_IP stays null
    and the slave falls back to UDP-broadcast auto-discovery. Filled in, the
    slave connects directly to that address instead, which works even on
    networks (e.g. Wi-Fi with client isolation) where broadcast discovery
    never reaches the master. }
  MasterIPPage := CreateInputQueryPage(wpSelectDir,
    'Master Server Address', 'Optional: enter the Master server''s IP address',
    'If you know the IP address of the computer running the Master console, ' +
    'enter it below for a direct, reliable connection (format: ###.###.###.###).' + #13#10#13#10 +
    'Leave this blank to use automatic discovery instead -- this only works ' +
    'if both machines are on the same network segment and broadcast traffic ' +
    'is not blocked (some Wi-Fi networks block this between devices).');
  MasterIPPage.Add('Master IP Address (optional, e.g. 192.168.1.10):', False);
  MasterIPPage.Edits[0].OnKeyPress := @MasterIPKeyPress;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  IPValue: string;
begin
  Result := True;
  if CurPageID = MasterIPPage.ID then
  begin
    IPValue := Trim(MasterIPPage.Values[0]);
    if (IPValue <> '') and not IsValidIPv4(IPValue) then
    begin
      MsgBox('Please enter a valid IPv4 address in the form ###.###.###.### ' +
        '(each number from 0 to 255), or leave the field blank to use ' +
        'automatic discovery instead.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function SendMessageTimeoutA(hWnd: LongInt; Msg: LongInt; wParam: LongInt; lParam: AnsiString;
  fuFlags: LongInt; uTimeout: LongInt; var lpdwResult: LongInt): LongInt;
  external 'SendMessageTimeoutA@user32.dll stdcall';

function SetEnvironmentVariableW(lpName: string; lpValue: string): BOOL;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

procedure BroadcastEnvironmentChange;
var
  ResultCode: LongInt;
begin
  { Notifies already-running processes (e.g. Explorer) of the change. This
    does NOT fix the "install"/"start" [Run] steps below on its own -- see
    UpdateOwnProcessEnvironment, which is what actually makes those work. }
  SendMessageTimeoutA(HWND_BROADCAST, WM_SETTINGCHANGE, 0, 'Environment', SMTO_ABORTIFHUNG, 5000, ResultCode);
end;

procedure UpdateOwnProcessEnvironment;
begin
  { Setup.exe's own process environment was captured when it started, BEFORE
    the Registry section wrote DEPLOYER_SHARED_TOKEN. The install/start
    Run-section steps below run SoftwareDeployerAgent.exe as a CHILD of this
    installer process, inheriting that stale (missing) environment -- which
    would crash immediately, since slave/config.py checks for this variable
    at import time regardless of which command-line argument is passed.
    Explicitly setting it in our own process here fixes that for every
    subsequent Run-section step. (The actual running Windows Service, once
    started, gets its environment fresh from the registry via the Service
    Control Manager regardless -- this fix is specifically for the
    install/start commands themselves, run directly by Setup.exe.) }
  SetEnvironmentVariableW('DEPLOYER_SHARED_TOKEN', '{#SharedToken}');
end;

function ReplaceMasterIPValue(Content: AnsiString; NewIP: AnsiString): AnsiString;
var
  KeyPos, ValueStart, ValueEnd: Integer;
  Prefix, Suffix, NewValueLiteral: AnsiString;
begin
  { Finds "MASTER_IP":'s value -- whatever it currently is (the template's
    null, OR a real IP string left over from an earlier install, since
    config.json is NOT replaced on reinstall -- see [Files]'s
    onlyifdoesntexist flag) -- and replaces it, so re-running this installer
    to change the Master IP actually takes effect every time, not just on a
    truly fresh install where the value still happens to be null. }
  Result := Content;
  KeyPos := Pos('"MASTER_IP":', Content);
  if KeyPos = 0 then
    Exit; { key not present at all -- nothing we can patch }

  ValueStart := KeyPos + Length('"MASTER_IP":');
  while (ValueStart <= Length(Content)) and (Content[ValueStart] = ' ') do
    ValueStart := ValueStart + 1;

  if (ValueStart <= Length(Content)) and (Content[ValueStart] = '"') then
  begin
    { Quoted string value -- find its closing quote. }
    ValueEnd := ValueStart + 1;
    while (ValueEnd <= Length(Content)) and (Content[ValueEnd] <> '"') do
      ValueEnd := ValueEnd + 1;
  end
  else
  begin
    { Unquoted literal (null) -- ends at the next comma/brace/newline. }
    ValueEnd := ValueStart;
    while (ValueEnd <= Length(Content)) and (Content[ValueEnd] <> ',') and
          (Content[ValueEnd] <> '}') and (Content[ValueEnd] <> #13) and
          (Content[ValueEnd] <> #10) do
      ValueEnd := ValueEnd + 1;
    ValueEnd := ValueEnd - 1;
  end;

  Prefix := Copy(Content, 1, ValueStart - 1);
  Suffix := Copy(Content, ValueEnd + 1, MaxInt);

  if NewIP = '' then
    NewValueLiteral := 'null'
  else
    NewValueLiteral := '"' + NewIP + '"';

  Result := Prefix + NewValueLiteral + Suffix;
end;

procedure ApplyMasterIPToConfig;
var
  ConfigPath: string;
  ConfigContent: AnsiString;
  MasterIP: AnsiString;
begin
  { LoadStringFromFile/SaveStringToFile work with AnsiString specifically in
    Inno's Pascal Script, so every string touched below is kept AnsiString
    consistently (a plain := assignment from the wizard page's Unicode
    string narrows it to AnsiString, which is fine -- IP addresses/hostnames
    are plain ASCII). }
  MasterIP := MasterIPPage.Values[0];
  MasterIP := Trim(MasterIP);

  ConfigPath := ExpandConstant('{app}\config.json');
  if LoadStringFromFile(ConfigPath, ConfigContent) then
  begin
    ConfigContent := ReplaceMasterIPValue(ConfigContent, MasterIP);
    SaveStringToFile(ConfigPath, ConfigContent, False);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    UpdateOwnProcessEnvironment;
    BroadcastEnvironmentChange;
    ApplyMasterIPToConfig;
  end;
end;
