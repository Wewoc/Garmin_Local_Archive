# run_coverage.ps1 - Garmin Local Archive
# Misst die Zeilenabdeckung ueber alle Suiten aus run_tests.ps1 (nur Messung,
# kein Gate, keine Mindestquote). Ergebnis: coverage_out\coverage_report.log
#
# Die Suite-Liste wird aus run_tests.ps1 gelesen (eine einzige Liste, kein
# Duplikat). Konfiguration: .coveragerc. Voraussetzung: pip install coverage
# (kommt mit pytest-cov aus requirements.txt).
#
# Aufruf:  powershell -ExecutionPolicy Bypass -File run_coverage.ps1
# Optional: -Html  erzeugt zusaetzlich coverage_out\html\index.html

param([switch]$Html)

$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"
if (-not $env:QT_QPA_PLATFORM) { $env:QT_QPA_PLATFORM = "offscreen" }

Set-Location $PSScriptRoot
$outDir = Join-Path $PSScriptRoot "coverage_out"
if (Test-Path $outDir) { Remove-Item $outDir -Recurse -Force }
New-Item -ItemType Directory -Path $outDir | Out-Null
$env:COVERAGE_FILE = Join-Path $outDir ".coverage"
$rcFile = Join-Path $PSScriptRoot ".coveragerc"

# --- Suite-Liste aus run_tests.ps1 lesen ------------------------------------
# Zeilenformat: Run-And-Tee "python" @("tests/test_x.py")  "test_x.py"
#               Run-And-Tee "pytest" @("tests/test_y.py", "-v")  "test_y.py"
$suites = @()
foreach ($line in Get-Content (Join-Path $PSScriptRoot "run_tests.ps1")) {
    if ($line -match '^\s*Run-And-Tee\s+"(python|pytest)"\s+@\("([^"]+)"') {
        $suites += [pscustomobject]@{ Kind = $Matches[1]; File = $Matches[2] }
    }
}
$expected = @(Select-String -Path (Join-Path $PSScriptRoot "run_tests.ps1") -Pattern '^\s*Run-And-Tee\s+"').Count
if ($suites.Count -eq 0 -or $suites.Count -ne $expected) {
    Write-Host "FEHLER: Suite-Liste aus run_tests.ps1 nicht vollstaendig gelesen ($($suites.Count) von $expected)."
    exit 1
}

# --- Suiten unter coverage ausfuehren ---------------------------------------
$failed = @()
foreach ($s in $suites) {
    Write-Host "coverage: $($s.File)"
    $global:LASTEXITCODE = $null
    if ($s.Kind -eq "pytest") {
        & python -m coverage run --rcfile=$rcFile -m pytest $s.File -q 2>&1 | Out-Null
    } else {
        & python -m coverage run --rcfile=$rcFile $s.File 2>&1 | Out-Null
    }
    if ($global:LASTEXITCODE -ne 0) { $failed += "$($s.File) (Exit $global:LASTEXITCODE)" }
}

# --- Zusammenfuehren + Bericht ----------------------------------------------
& python -m coverage combine --rcfile=$rcFile --quiet
$reportFile = Join-Path $outDir "coverage_report.log"
& python -m coverage report --rcfile=$rcFile --sort=cover 2>&1 | Out-File -FilePath $reportFile -Encoding utf8
if ($Html) {
    & python -m coverage html --rcfile=$rcFile -d (Join-Path $outDir "html") --quiet
}

Get-Content $reportFile -Tail 3
Write-Host ""
Write-Host "Bericht: $reportFile"
if ($failed.Count -gt 0) {
    Write-Host "HINWEIS: Suiten mit Exit ungleich 0 (Messung unvollstaendig): $($failed -join ', ')"
    exit 1
}
exit 0
