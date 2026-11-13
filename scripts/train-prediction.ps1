param([switch]$Software, [string]$InputFile='', [string]$OutputFile='', [string]$PythonPath='', [double]$NominalSegmentSeconds=0)
$ErrorActionPreference='Stop'
$metroRoot=[System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $metroRoot
if (-not $PythonPath -and (Test-Path -LiteralPath '.local/ml-runtime.json')) {
    $PythonPath=(Get-Content -LiteralPath '.local/ml-runtime.json' -Raw | ConvertFrom-Json).python
}
if (-not $PythonPath -or -not (Test-Path -LiteralPath $PythonPath)) {
    throw 'Pass -PythonPath from an environment installed with backend/requirements-ml.lock.txt.'
}
if ($Software -and $InputFile) { throw 'Choose -Software or -InputFile.' }
if (-not $Software -and -not $InputFile) { throw 'Supply -Software or a historical journey JSONL file.' }
if (-not $OutputFile) {
    if (-not $Software) { throw 'Supply -OutputFile for an operator model.' }
    $OutputFile='.local/software/prediction-model.json'
}
$env:PYTHONUTF8='1'
$metroArguments=@('-m','scripts.train_prediction','--output',$OutputFile)
if ($Software) { $metroArguments+='--software' } else { $metroArguments+=@('--input',$InputFile) }
if ($NominalSegmentSeconds -gt 0) { $metroArguments+=@('--nominal-segment-seconds',$NominalSegmentSeconds.ToString([Globalization.CultureInfo]::InvariantCulture)) }
& $PythonPath @metroArguments
if ($LASTEXITCODE -ne 0) { throw 'Prediction training failed.' }
