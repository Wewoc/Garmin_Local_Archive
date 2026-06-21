# run_tests.ps1 - Garmin Local Archive
# Output gleichzeitig auf Konsole und in Log-Datei (UTF-8 ohne BOM).

$ErrorActionPreference = "Continue"
$LOGFILE = Join-Path $PSScriptRoot "test_all_log.txt"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)

# Log-Datei neu anlegen (UTF-8 ohne BOM)
[System.IO.File]::WriteAllText($LOGFILE, "", $Utf8NoBom)

# Sammelt die Zusammenfassungs-Zeilen aller Suites fuer den Gesamtblock am Ende
$Script:SuiteSummaries = @()

function Write-Log {
    param([string]$Line)
    $writer = [System.IO.StreamWriter]::new($LOGFILE, $true, $Utf8NoBom)
    $writer.WriteLine($Line)
    $writer.Close()
    Write-Host $Line
}

function Run-And-Tee {
    param([string]$Command, [string[]]$Arguments, [string]$SuiteLabel)
    $collectedLines = New-Object System.Collections.Generic.List[string]
    & $Command @Arguments 2>&1 | ForEach-Object {
        $line = if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.ToString() } else { $_ }
        $collectedLines.Add($line)
        $writer = [System.IO.StreamWriter]::new($LOGFILE, $true, $Utf8NoBom)
        $writer.WriteLine($line)
        $writer.Close()
        Write-Host $line
    }

    # eigenes Format: "  N checks -- N passed, N failed"
    $dashChar = [char]0x2014
    $ownFormatLine = $collectedLines | Where-Object { $_ -match ('^\s*\d+\s+checks?\s+' + $dashChar + '\s+\d+\s+passed,\s+\d+\s+failed') } | Select-Object -Last 1

    if ($ownFormatLine) {
        $m = [regex]::Match($ownFormatLine, ('(\d+)\s+checks?\s+' + $dashChar + '\s+(\d+)\s+passed,\s+(\d+)\s+failed'))
        $Script:SuiteSummaries += "  $SuiteLabel  $($m.Groups[1].Value) checks $dashChar $($m.Groups[2].Value) passed, $($m.Groups[3].Value) failed"
        return
    }

    # pytest-Format: "42 passed in 1.17s" (optional "X failed" davor)
    $pytestLine = $collectedLines | Where-Object { $_ -match '\d+\s+passed' -or $_ -match '\d+\s+failed' } | Select-Object -Last 1

    if ($pytestLine) {
        $passedMatch = [regex]::Match($pytestLine, '(\d+)\s+passed')
        $failedMatch = [regex]::Match($pytestLine, '(\d+)\s+failed')
        $passed = if ($passedMatch.Success) { [int]$passedMatch.Groups[1].Value } else { 0 }
        $failed = if ($failedMatch.Success) { [int]$failedMatch.Groups[1].Value } else { 0 }
        $total = $passed + $failed
        $Script:SuiteSummaries += "  $SuiteLabel  $total checks $dashChar $passed passed, $failed failed"
        return
    }

    $Script:SuiteSummaries += "  $SuiteLabel  Ergebnis nicht erkannt $dashChar siehe Log oben"
}

# Header
Write-Log "running tests"
Write-Log (Get-Date -Format "dd.MM.yyyy HH:mm:ss")
Write-Log ""

# Tests
Run-And-Tee "python" @("tests/test_local.py")          "test_local.py"
Run-And-Tee "python" @("tests/test_local_context.py")  "test_local_context.py"
Run-And-Tee "python" @("tests/test_dashboard.py")       "test_dashboard.py"
Run-And-Tee "python" @("tests/test_app_logic.py")       "test_app_logic.py"
Run-And-Tee "pytest"  @("tests/test_qt_app.py", "-v")   "test_qt_app.py"
Run-And-Tee "python" @("tests/test_static.py")          "test_static.py"

# Gesamt-Zusammenfassung
$summaryLine = [string]::new([char]0x2550, 57)
Write-Log ""
Write-Log $summaryLine
Write-Log "  ZUSAMMENFASSUNG"
Write-Log $summaryLine
foreach ($line in $Script:SuiteSummaries) {
    Write-Log $line
}
Write-Log $summaryLine

# Footer
Write-Log ""
Write-Log (Get-Date -Format "dd.MM.yyyy HH:mm:ss")
Write-Host "done."
