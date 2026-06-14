# run_tests.ps1 — Garmin Local Archive
# Output gleichzeitig auf Konsole und in Log-Datei (UTF-8 ohne BOM).

$ErrorActionPreference = "Continue"
$LOGFILE = Join-Path $PSScriptRoot "test_all_log.txt"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)

# Log-Datei neu anlegen (UTF-8 ohne BOM)
[System.IO.File]::WriteAllText($LOGFILE, "", $Utf8NoBom)

function Write-Log {
    param([string]$Line)
    $writer = [System.IO.StreamWriter]::new($LOGFILE, $true, $Utf8NoBom)
    $writer.WriteLine($Line)
    $writer.Close()
    Write-Host $Line
}

function Run-And-Tee {
    param([string]$Command, [string[]]$Arguments)
    & $Command @Arguments 2>&1 | ForEach-Object {
        $line = if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.ToString() } else { $_ }
        $writer = [System.IO.StreamWriter]::new($LOGFILE, $true, $Utf8NoBom)
        $writer.WriteLine($line)
        $writer.Close()
        Write-Host $line
    }
}

# Header
Write-Log "running tests"
Write-Log (Get-Date -Format "dd.MM.yyyy HH:mm:ss")
Write-Log ""

# Tests
Run-And-Tee "python" @("tests/test_local.py")
Run-And-Tee "python" @("tests/test_local_context.py")
Run-And-Tee "python" @("tests/test_dashboard.py")
Run-And-Tee "python" @("tests/test_app_logic.py")
Run-And-Tee "pytest"  @("tests/test_qt_app.py", "-v")
Run-And-Tee "python" @("tests/test_static.py")

# Footer
Write-Log ""
Write-Log (Get-Date -Format "dd.MM.yyyy HH:mm:ss")
Write-Host "done."
