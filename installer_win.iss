; SiGMaR Windows installer (Inno Setup)
; -----------------------------------------------------------------------
; Compiled and tested end-to-end on Windows (ISCC.exe from Inno Setup 6):
; install -> Docker image load -> Desktop shortcut -> app responds on
; localhost:8060. If you change this file, recompile with:
;   ISCC.exe installer_win.iss
; (from this folder) and re-run the resulting Output\SiGMaR-Setup.exe.
;
; What it does: copies the whole project (including bin/*.tar.gz, ~7GB) to
; a per-user folder (no admin/UAC needed), then runs the existing
; setup_win.ps1 as a wizard step - same docker-load + shortcut-creation
; logic already used by the manual install path, just wrapped in a
; Next/Next/Install/Finish UI instead of a script the user has to find and
; run themselves.
; -----------------------------------------------------------------------

#define AppName "SiGMaR"
#define AppVersion "1.0"
#define AppPublisher "SiGMaR"

[Setup]
AppId={{9C4B6C1A-6B7B-4E3E-8B7A-3F2C7C6B8A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
; Per-user install under LocalAppData - no administrator prompt, matches
; the "as simple as possible for the user" goal from the macOS side.
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=SiGMaR-Setup
OutputDir=Output
Compression=lzma2
SolidCompression=yes
; The bin\*.tar.gz images are already compressed - don't burn time
; re-compressing several GB of already-compressed data.
CompressionThreads=auto
; The bin\*.tar.gz images push the payload past ~6.8GB, well over Inno
; Setup's ~4.2GB limit for a single embedded Setup.exe. DiskSliceSize=max
; keeps disk spanning as a single unlimited-size slice instead of splitting
; into multiple volumes - the output becomes SiGMaR-Setup.exe plus one
; SiGMaR-Setup-1.bin file that must stay next to it (both are required to
; run the installer; ship them together, e.g. zipped as one download).
DiskSpanning=yes
DiskSliceSize=max
WizardStyle=modern
DisableWelcomePage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion; \
  Excludes: ".git,.git\*,__pycache__,__pycache__\*,*\__pycache__,*\__pycache__\*,.DS_Store,*\.DS_Store,uploads,uploads\*,.sigmar_cache,*\.sigmar_cache,.dmg_stage,.dmg_stage\*,Install SiGMaR.app,Install SiGMaR.app\*,SiGMaR.dmg,Output,Output\*,installer_win.iss,uninstall_all_sigmar.ps1,uninstall_all_sigmar.bat,Installer,Installer\*,docs_build,docs_build\*,win_installer.7z"

[UninstallDelete]
; Runtime-created leftovers that unins000.exe doesn't know about, because
; [Files]/[Icons] never installed them - uploads/ is created by the app on
; first upload (deliberately excluded above), __pycache__ folders by Python
; running (only ever appears at {app}'s root or one level down, e.g.
; callbacks\__pycache__, layouts\__pycache__, scripts\__pycache__ - same
; depth already covered by the Excludes patterns above). Harmless (~270KB)
; but confusing to find after "uninstalling" - see the uninstall-cleanup TODO.
Type: filesandordirs; Name: "{app}\uploads"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\*\__pycache__"

[Run]
; setup_win.ps1 itself is launched from [Code]'s CurStepChanged below, not
; from here - see the comment there for why. Only the optional post-install
; launch stays a plain [Run] entry.

; Offer to launch immediately, same shortcut setup_win.ps1 just created on
; the Desktop. Guarded by Check: if setup_win.ps1 failed before reaching
; New-AppShortcut (e.g. Docker Desktop never became ready), the .lnk never
; got created and shellexec-ing it would just throw a confusing
; "ShellExecuteEx failed; code 2" dialog - skip the step instead.
Filename: "{userdesktop}\SiGMaR.lnk"; Description: "Launch SiGMaR now"; \
  Flags: postinstall skipifsilent nowait shellexec; Check: ShortcutWasCreated

[Code]
function ShortcutWasCreated(): Boolean;
begin
  Result := FileExists(ExpandConstant('{userdesktop}\SiGMaR.lnk'));
end;

// GetTickCount is not one of Pascal Script's built-in support functions -
// confirmed by test-compiling without this import first (Inno reports
// "Unknown identifier 'GetTickCount'"), so it has to come from kernel32.
function GetTickCount: DWORD;
  external 'GetTickCount@kernel32.dll stdcall';

// A plain Sleep()-based wait loop (the first version of RunSetupScript
// below used exactly that) does NOT pump the Windows message queue, even
// though Inno's own built-in wait for a [Run] entry with waituntilterminated
// does. Confirmed the hard way: real users found the wizard window stopped
// responding to minimize/restore/close for the whole several-minute docker
// load - Windows silently marks an unresponsive top-level window "not
// responding" and further clicks go nowhere. Verified BOTH the failure and
// the fix on a minimal standalone test .iss with user32's IsHungAppWindow
// (the same API Windows itself uses to decide this) polled every second
// during the wait: hung=True throughout with a bare Sleep() loop, hung=False
// throughout once PumpMessages below was added - before touching this file.
type
  TMsg = record
    hwnd: LongInt;
    message: LongInt;
    wParam: LongInt;
    lParam: LongInt;
    time: LongInt;
    ptX: LongInt;
    ptY: LongInt;
  end;

function PeekMessage(var lpMsg: TMsg; hWnd, wMsgFilterMin, wMsgFilterMax, wRemoveMsg: LongInt): LongInt;
  external 'PeekMessageA@user32.dll stdcall';
function TranslateMessageAPI(const lpMsg: TMsg): LongInt;
  external 'TranslateMessage@user32.dll stdcall';
function DispatchMessageAPI(const lpMsg: TMsg): LongInt;
  external 'DispatchMessageA@user32.dll stdcall';

procedure PumpMessages;
var
  Msg: TMsg;
  i: Integer;
begin
  // Bounded to 20 messages per call (PM_REMOVE=1) rather than draining
  // until empty, so a flood of input events can't turn this into an
  // unbounded loop and starve the status-file polling below it.
  for i := 1 to 20 do
  begin
    if PeekMessage(Msg, 0, 0, 0, 1) = 0 then
      Break;
    TranslateMessageAPI(Msg);
    DispatchMessageAPI(Msg);
  end;
end;

// Runs setup_win.ps1 (Docker readiness check, image load, icon + shortcut
// generation) launched *asynchronously* (Exec ewNoWait) instead of the old
// single blocking [Run] entry, so this procedure can poll a status file the
// script writes to (setup_win.ps1's Write-Status helper) and update
// WizardForm.StatusLabel.Caption with real progress - "Loading application
// image...", "Loading GDAN-TMP model images (3 of 5)...", etc. - instead of
// one static "please wait" message sitting under a progress bar that looks
// stuck/finished (it's already full from the file-copy phase) for the
// several minutes docker load can take. A visible PowerShell console was
// tried before and looked broken enough to get the wizard cancelled
// mid-install (see git history) - SW_HIDE keeps that fixed while still
// surfacing readable status text through the wizard's own UI.
//
// Verified against a minimal standalone test .iss before touching this
// file (full ISCC recompile here costs ~40min, not worth spending on a
// syntax/logic mistake): GetTickCount needs the import above,
// LoadStringFromFile's var parameter must be AnsiString (not String, or
// Inno reports a type mismatch), and status text must be written without a
// UTF-8 BOM (Set-Content -Encoding UTF8 prepends one, which silently broke
// Pos('DONE:', CurStatus) = 1 - use Pos(...) > 0 defensively regardless).
procedure RunSetupScript;
var
  ResultCode: Integer;
  StatusFile: String;
  LastStatus, CurStatus: AnsiString;
  StartTime: DWORD;
  TimedOut: Boolean;
  Launched: Boolean;
begin
  StatusFile := ExpandConstant('{tmp}\sigmar_setup_status.txt');
  DeleteFile(StatusFile);

  WizardForm.StatusLabel.Caption := 'Setting up SiGMaR (first run can take several minutes)...';
  // Marquee (animated, no fixed fill level) instead of the normal bar, which
  // would otherwise still show 100%/full from the earlier file-copy phase
  // for the whole docker-load wait - looked finished/stuck even before the
  // window-freeze bug above. Restored to normal once this step is done.
  WizardForm.ProgressGauge.Style := npbstMarquee;

  // No runasoriginaluser here (that [Run]-only flag addressed running as
  // the non-elevated original user when Setup itself is elevated) -
  // PrivilegesRequired=lowest means Setup already runs as the plain
  // current user, so Exec() here already runs in that same context.
  Launched := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\setup_win.ps1') +
    '" -StatusFile "' + StatusFile + '"',
    ExpandConstant('{app}'), SW_HIDE, ewNoWait, ResultCode);

  if not Launched then
  begin
    WizardForm.ProgressGauge.Style := npbstNormal;
    MsgBox('Could not start setup_win.ps1 (CreateProcess failed). Try running it manually from: ' + ExpandConstant('{app}'), mbError, MB_OK);
    Exit;
  end;

  LastStatus := '';
  CurStatus := '';
  StartTime := GetTickCount;
  TimedOut := False;
  while True do
  begin
    PumpMessages;
    Sleep(50);
    if FileExists(StatusFile) then
    begin
      if LoadStringFromFile(StatusFile, CurStatus) then
      begin
        if (CurStatus <> '') and (CurStatus <> LastStatus) then
        begin
          if Pos('DONE:', CurStatus) > 0 then
            Break;
          WizardForm.StatusLabel.Caption := CurStatus;
          LastStatus := CurStatus;
        end;
      end;
    end;
    // 25 minutes - generous margin over the "several minutes" docker load
    // normally takes, to cover a slow disk or a first-ever Docker Desktop
    // start, without ever hanging the wizard forever on a genuine stall.
    if (GetTickCount - StartTime) > 1500000 then
    begin
      TimedOut := True;
      Break;
    end;
  end;

  WizardForm.ProgressGauge.Style := npbstNormal;

  if TimedOut then
    MsgBox('SiGMaR setup is taking longer than expected. It may still be running in the background - check Docker Desktop, or open a command prompt and run setup_win.ps1 manually from: ' + ExpandConstant('{app}'), mbInformation, MB_OK)
  else if (Pos('DONE:0', CurStatus) <> 1) then
    MsgBox('SiGMaR setup reported a problem:' + #13#10 + CurStatus + #13#10#13#10 + 'You can try running setup_win.ps1 manually from the install folder, or re-run this installer after fixing the issue (e.g. starting Docker Desktop).', mbError, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    RunSetupScript;
end;

function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  // Routed through cmd.exe /C rather than calling 'where' directly - Exec()
  // does not reliably resolve bare command names against PATH the way a
  // shell does.
  if not Exec('cmd.exe', '/C where docker', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    // Couldn't even launch the check - don't block install on that alone.
    Result := True;
  end
  else if ResultCode <> 0 then
  begin
    MsgBox('Docker Desktop was not found. Install it from docker.com before continuing, then run this installer again.', mbError, MB_OK);
    Result := False;
  end;
end;