param([string]$PythonPath = '')
$ErrorActionPreference = 'Stop'
$metroProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $metroProjectRoot
if (-not $PythonPath) {
    $metroCandidate = Join-Path $metroProjectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $metroCandidate)) { $metroCandidate = Join-Path $metroProjectRoot '..\.venv\Scripts\python.exe' }
    $PythonPath = (Resolve-Path -LiteralPath $metroCandidate).Path
}
& $PythonPath -m pip install -q -r backend/requirements-dev.txt --no-cache-dir --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw "Test dependency installation failed." }
& $PythonPath -m pytest backend/tests -q
if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed.' }
Push-Location -LiteralPath 'frontend'
try { & npm.cmd run build; if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' } }
finally { Pop-Location }
