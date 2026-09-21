<#
updater_helper.ps1
Garmin Local Archive - T3 self-update helper (v1.7.2.4)

Started detached by either the GUI (interactive "Update" button) or
daily_update.exe (unattended auto-apply). Runs OUTSIDE both processes
so it can wait for them to exit and then replace their own files -
something neither process can do to itself while still running.
PowerShell instead of a 4th PyInstaller EXE: preinstalled on every
Windows 10/11 target, no Python required, no new build artefact
(v1.7.2.4 concept, Baustein 4).

NOTE: this file must stay plain ASCII. A non-ASCII character (an
em-dash) inside a string literal here previously broke the PowerShell
parser outright when the file was read without a UTF-8 BOM/under a
non-UTF-8 system codepage (found via a real test run, 2026-09-21,
Baustein 14) - not a hypothetical risk, since end-user machines have
unknown locale/codepage settings.

Parameters:
  -ExeDir         Install folder (contains the current live files).
  -PendingDir     Sibling folder with the already-downloaded, verified,
                  extracted new version (see updater.prepare_update() on
                  the Python side) - produced BEFORE this script starts.
  -WaitPids       Comma-separated PIDs to wait for before touching any
                  file: the caller's own PID, plus MCP's/daily_update's
                  if they were found running (Baustein 2/3/13).
  -RestartGui     Switch - restart the GUI EXE (see -GuiExeName) after
                  the swap. Only the GUI-button trigger sets this; the
                  daily_update.exe trigger does not (Baustein 4/9 -
                  "einziger Unterschied am Ende").
  -GuiExeName     Filename of the GUI EXE to restart when -RestartGui is
                  set, resolved relative to ExeDir - differs by build
                  target (Garmin_Local_Archive_Standalone.exe for T3,
                  Garmin_Local_Archive.exe for T2, v1.7.2.4-
                  Nacherweiterung, Baustein 29). Defaults to the T3 name
                  for backward compatibility with callers that don't
                  pass it yet.
  -RestartMcpCmd  Full path/command to relaunch MCP with, or empty if
                  MCP wasn't running before the update - mcp_server.exe
                  for T3, clients/Starte_MCP_Server.bat for T2.

Own lock file (_update_helper.lock in ExeDir) guards against two helper
runs overlapping - GUI-triggered and daily_update.exe-triggered updates
could otherwise collide (Baustein 5/6, still-open point, closed here).

Console behaviour mirrors daily_update.py's own convention: closes
automatically on a clean swap, stays open with the failure message on
any error (Read-Host, not just exit) - a human gets a chance to see
what went wrong even in a run that happens to have a visible console.

Old install contents are moved aside into _update_backup/ (overwritten
by the next update, not kept indefinitely) rather than deleted outright
- a one-step rollback safety net if the new version turns out broken,
at the cost of holding one extra copy on disk (Baustein 5/6 decision,
made concrete here).
#>

param(
    [Parameter(Mandatory = $true)][string]$ExeDir,
    [Parameter(Mandatory = $true)][string]$PendingDir,
    [string]$WaitPids = "",
    [switch]$RestartGui,
    [string]$GuiExeName = "Garmin_Local_Archive_Standalone.exe",
    [string]$RestartMcpCmd = ""
)

$ErrorActionPreference = "Stop"
$lockPath = Join-Path $ExeDir "_update_helper.lock"

# -- 0. Is another helper already running? ---------------------------------
if (Test-Path $lockPath) {
    $existingPid = Get-Content $lockPath -ErrorAction SilentlyContinue
    if ($existingPid -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
        Write-Host "UPDATE FAILED: another update is already in progress (PID $existingPid)." -ForegroundColor Red
        Read-Host "Press Enter to close"
        exit 1
    }
}
$PID | Out-File -FilePath $lockPath -Encoding ascii

$exitCode = 0
try {
    # -- 1. Wait for the given PIDs (max. 60s each) -------------------------
    if ($WaitPids) {
        foreach ($p in ($WaitPids -split ",")) {
            $p = $p.Trim()
            if (-not $p) { continue }
            $deadline = (Get-Date).AddSeconds(60)
            while ((Get-Process -Id $p -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {
                Start-Sleep -Milliseconds 500
            }
            if (Get-Process -Id $p -ErrorAction SilentlyContinue) {
                throw "Process $p did not exit within 60 seconds - update aborted, nothing changed."
            }
        }
    }

    # -- 2. Back up the old install, move the new one into place -----------
    $backupDir = Join-Path $ExeDir "_update_backup"
    if (Test-Path $backupDir) { Remove-Item $backupDir -Recurse -Force }
    New-Item -ItemType Directory -Path $backupDir | Out-Null

    Get-ChildItem $ExeDir -Force |
        Where-Object { $_.Name -notin @("_update_pending", "_update_backup", "_update_helper.lock") } |
        ForEach-Object { Move-Item $_.FullName (Join-Path $backupDir $_.Name) -Force }

    Get-ChildItem $PendingDir -Force |
        ForEach-Object { Move-Item $_.FullName (Join-Path $ExeDir $_.Name) -Force }

    Remove-Item $PendingDir -Recurse -Force -ErrorAction SilentlyContinue

    # -- 3. Strip Mark-of-the-Web (SmartScreen friction, Baustein 6) -------
    Get-ChildItem $ExeDir -Recurse -File | Unblock-File -ErrorAction SilentlyContinue

    # -- 4. Restart what needs restarting ------------------------------------
    if ($RestartGui) {
        Start-Process (Join-Path $ExeDir $GuiExeName)
    }
    if ($RestartMcpCmd) {
        Start-Process -FilePath $RestartMcpCmd
    }

    Write-Host "Update applied successfully."
}
catch {
    Write-Host "UPDATE FAILED: $($_.Exception.Message)" -ForegroundColor Red
    $exitCode = 1
}
finally {
    Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
}

if ($exitCode -ne 0) {
    Read-Host "Press Enter to close"
}
exit $exitCode
