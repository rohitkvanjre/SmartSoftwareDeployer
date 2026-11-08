; Inno Setup script for the Slave agent.
; Build with (from repo root):
;   "C:\Users\vanjr\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer_build\SlaveSetup.iss /DSourceDist=installer_build\dist\slave /DOutputDir=installer_build\out
;
; The installer contains no secrets. Each slave pairs with the master using
; the code shown on the master's "Pair New Slaves" screen. For unattended
; installs:  slave.exe /VERYSILENT /PAIRCODE=XXXX-XXXX [/MASTERIP=a.b.c.d]

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
; Older versions stored a shared token here. Remove it when upgrading.
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
    ValueType: none; ValueName: "DEPLOYER_SHARED_TOKEN"; Flags: deletevalue

[Run]
; Allow this program through Windows Firewall on ALL network profiles
; (Domain/Private/Public) BEFORE starting the service, so its outbound UDP
; discovery broadcast and TCP connection to the master aren't blocked --
; especially on a network Windows classifies as "Public" (the default for
; new connections), which restricts traffic much more aggressively.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Smart Software Deployer - Slave Agent"" dir=in action=allow program=""{app}\SoftwareDeployerAgent.exe"" enable=yes profile=any"; Flags: runhidden waituntilterminated; StatusMsg: "Configuring Windows Firewall..."
; Register the Windows Service (this also registers the tray app to start at
; logon -- see slave/service.py's install_tray_autostart(), which looks for
; tray_app.exe right next to this same exe).
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
; Stop first so an upgrade always runs a fresh agent process, which picks up
; a newly entered pairing code immediately. On a fresh install there's
; nothing to stop and this fails harmlessly.
Filename: "{app}\SoftwareDeployerAgent.exe"; Parameters: "--wait=30 stop"; Flags: runhidden waituntilterminated; StatusMsg: "Stopping the Software Deployer Agent service..."
Filename: "{app}\SoftwareDeployerAgent.exe"; Parameters: "start"; Flags: runhidden waituntilterminated; StatusMsg: "Starting the Software Deployer Agent service..."
; Setup closes the tray app before copying files, so start it again for the
; user running Setup (other users get it at their next logon).
Filename: "{app}\tray_app.exe"; Flags: nowait runasoriginaluser skipifsilent

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
  { Must match CODE_ALPHABET in common/pairing_protocol.py. }
  CodeAlphabet = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';

var
  ConnectPage: TInputQueryWizardPage;

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

procedure PairingCodeKeyPress(Sender: TObject; var Key: Char);
begin
  { Letters, digits, and the separators people naturally type. Ambiguous
    letters (O, I, L) are allowed and normalized later. }
  if not (((Key >= '0') and (Key <= '9')) or ((Key >= 'A') and (Key <= 'Z')) or
          ((Key >= 'a') and (Key <= 'z')) or (Key = '-') or (Key = ' ') or (Key < #32)) then
    Key := #0;
end;

{ Mirrors normalize_code() in common/pairing_protocol.py: returns the
  8-character code, or '' if the input isn't a valid code. }
function NormalizePairingCode(const S: string): string;
var
  I: Integer;
  Raw, Ch: string;
begin
  Result := '';
  Raw := Uppercase(S);
  for I := 1 to Length(Raw) do
  begin
    Ch := Copy(Raw, I, 1);
    if (Ch <> '-') and (Ch <> ' ') then
    begin
      if Ch = 'O' then
        Ch := '0';
      if (Ch = 'I') or (Ch = 'L') then
        Ch := '1';
      if Pos(Ch, CodeAlphabet) = 0 then
      begin
        Result := '';
        Exit;
      end;
      Result := Result + Ch;
    end;
  end;
  if Length(Result) <> 8 then
    Result := '';
end;

function AlreadyPaired: Boolean;
begin
  Result := FileExists(ExpandConstant('{commonappdata}\SoftwareDeployerAgent\credentials\slave_credentials.json'));
end;

{ Shared by the wizard page and silent installs (/PAIRCODE=, /MASTERIP=). }
function ValidateConnectInputs(const Code, IP: string; var Error: string): Boolean;
begin
  Result := False;
  if (Code = '') and not AlreadyPaired then
    Error := 'Enter the pairing code shown on the Master''s "Pair New Slaves" screen.'
  else if (Code <> '') and (NormalizePairingCode(Code) = '') then
    Error := 'That pairing code isn''t valid. It has 8 letters and digits, like 7KQ4-M2XP.'
  else if (IP <> '') and not IsValidIPv4(IP) then
    Error := 'Please enter a valid IPv4 address in the form ###.###.###.### ' +
      '(each number from 0 to 255), or leave it blank to find the Master automatically.'
  else
    Result := True;
end;

function InitializeSetup: Boolean;
var
  Error: string;
begin
  Result := True;
  if WizardSilent and not ValidateConnectInputs(Trim(ExpandConstant('{param:PAIRCODE|}')),
                                                Trim(ExpandConstant('{param:MASTERIP|}')), Error) then
  begin
    Log('Setup aborted: ' + Error);
    SuppressibleMsgBox(Error, mbError, MB_OK, IDOK);
    Result := False;
  end;
end;

procedure InitializeWizard;
var
  PairingNote: string;
begin
  if AlreadyPaired then
    PairingNote := 'This PC is already paired. Leave the pairing code blank to keep that pairing, ' +
      'or enter a new code to pair it again.'
  else
    PairingNote := 'Enter the pairing code shown on the Master''s "Pair New Slaves" screen. ' +
      'It only works while that pairing window is open.';

  ConnectPage := CreateInputQueryPage(wpSelectDir,
    'Connect to the Master', 'Pair this PC with the Master console',
    PairingNote + #13#10#13#10 +
    'The Master IP address is optional. Leave it blank to find the Master automatically; ' +
    'enter it if your network blocks broadcast traffic (common on Wi-Fi).');
  ConnectPage.Add('Pairing code (e.g. 7KQ4-M2XP):', False);
  ConnectPage.Add('Master IP address (optional, e.g. 192.168.1.10):', False);
  ConnectPage.Edits[0].OnKeyPress := @PairingCodeKeyPress;
  ConnectPage.Edits[1].OnKeyPress := @MasterIPKeyPress;
  ConnectPage.Values[0] := ExpandConstant('{param:PAIRCODE|}');
  ConnectPage.Values[1] := ExpandConstant('{param:MASTERIP|}');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Error: string;
begin
  Result := True;
  if CurPageID = ConnectPage.ID then
  begin
    Result := ValidateConnectInputs(Trim(ConnectPage.Values[0]), Trim(ConnectPage.Values[1]), Error);
    if not Result then
      MsgBox(Error, mbError, MB_OK);
  end;
end;

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

procedure SavePairingCode;
var
  Code: AnsiString;
begin
  { Picked up (and moved into a protected folder) by the agent on its next
    connection attempt -- see slave/pairing.py. }
  Code := NormalizePairingCode(Trim(ConnectPage.Values[0]));
  if Code <> '' then
    SaveStringToFile(ExpandConstant('{app}\pairing_code.txt'), Code, False);
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
  MasterIP := ConnectPage.Values[1];
  MasterIP := Trim(MasterIP);

  ConfigPath := ExpandConstant('{app}\config.json');
  if LoadStringFromFile(ConfigPath, ConfigContent) then
  begin
    ConfigContent := ReplaceMasterIPValue(ConfigContent, MasterIP);
    SaveStringToFile(ConfigPath, ConfigContent, False);
  end;
end;

procedure RunHidden(const Exe, Params: string);
var
  ResultCode: Integer;
begin
  { Failures are expected and fine here, e.g. on a fresh install where the
    service and tray app don't exist yet. }
  Exec(ExpandConstant('{sys}\' + Exe), Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Log(Format('%s %s -> exit code %d', [Exe, Params, ResultCode]));
end;

{ Runs before any file is copied. On an upgrade the agent service and the
  tray app are running, and Windows won't let Setup replace a program file
  that's in use ("DeleteFile failed; code 5. Access is denied"). }
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  { Clear the "restart on failure" action first, or Windows would relaunch
    the agent a few seconds after it's stopped, mid-upgrade. The install
    step in the Run section sets it again (slave/service.py,
    configure_service_recovery). }
  RunHidden('sc.exe', 'failure SoftwareDeployerAgent reset= 0 actions= ""');
  RunHidden('net.exe', 'stop SoftwareDeployerAgent');
  { Only matters if a graceful stop didn't finish. }
  RunHidden('taskkill.exe', '/F /IM SoftwareDeployerAgent.exe');
  RunHidden('taskkill.exe', '/F /IM tray_app.exe');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    BroadcastEnvironmentChange;
    ApplyMasterIPToConfig;
    SavePairingCode;
  end;
end;
