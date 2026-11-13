param([string]$PythonPath='', [string]$Scenario='')
$ErrorActionPreference='Stop'
$metroBetaRoot=[System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if(-not $PythonPath) {
    foreach($metroBetaCandidate in @((Join-Path $metroBetaRoot '.venv/Scripts/python.exe'),(Join-Path $metroBetaRoot '../.venv/Scripts/python.exe'))) {
        if(Test-Path -LiteralPath $metroBetaCandidate){$PythonPath=(Resolve-Path -LiteralPath $metroBetaCandidate).Path;break}
    }
}
if(-not $PythonPath){throw 'Pass -PythonPath with the application Python environment.'}
Push-Location -LiteralPath $metroBetaRoot
try {
    $metroBetaArguments=@('-m','scripts.run_crowd_beta')
    if($Scenario){$metroBetaArguments+=@('--scenario',$Scenario)}
    & $PythonPath @metroBetaArguments
    if($LASTEXITCODE -ne 0){throw 'A beta expectation failed. Inspect artifacts/crowdsourcing-beta/latest-report.html.'}
    Write-Output 'Open artifacts/crowdsourcing-beta/latest-report.html to review the results.'
    Write-Output 'Synthetic input only. The passenger database was not opened.'
} finally {Pop-Location}
