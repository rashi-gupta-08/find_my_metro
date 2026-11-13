param([switch]$Docker)
$ErrorActionPreference = 'Stop'
$metroProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ($Docker) {
    Push-Location -LiteralPath $metroProjectRoot
    try { & docker compose down; if ($LASTEXITCODE -ne 0) { throw 'Docker stop failed.' } }
    finally { Pop-Location }
    return
}
$metroRecordPath = Join-Path $metroProjectRoot '.local\processes.json'
if (-not (Test-Path -LiteralPath $metroRecordPath)) { Write-Output 'No recorded local processes.'; return }
$metroRecords = Get-Content -LiteralPath $metroRecordPath -Raw | ConvertFrom-Json
foreach ($metroRecord in $metroRecords) {
    $metroProcess = Get-Process -Id $metroRecord.pid -ErrorAction SilentlyContinue
    if ($metroProcess -and $metroProcess.StartTime.ToUniversalTime().Ticks -eq ([datetime]$metroRecord.start).ToUniversalTime().Ticks) {
        & (Join-Path $env:SystemRoot 'System32/taskkill.exe') /PID $metroRecord.pid /T /F | Out-Null
        Write-Output ('Stopped '+$metroRecord.name)
    }
}
Write-Output 'Local services stopped. Stored events and reports are preserved.'

$metroDatabaseRecord = Join-Path $metroProjectRoot '.local/database.json'
if (Test-Path -LiteralPath $metroDatabaseRecord) {
    $metroDatabase = Get-Content -LiteralPath $metroDatabaseRecord -Raw | ConvertFrom-Json
    $metroPgStop = Start-Process -FilePath (Join-Path $metroDatabase.bin 'pg_ctl.exe') -ArgumentList @('-D',$metroDatabase.data,'-m','fast','-w','stop') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $metroProjectRoot '.local/pg-stop.out.log') -RedirectStandardError (Join-Path $metroProjectRoot '.local/pg-stop.err.log')
    if (-not $metroPgStop.WaitForExit(60000)) { throw 'Application PostgreSQL shutdown timed out; services have stopped and stored data is preserved.' }
    if ($metroPgStop.ExitCode -ne 0) { throw 'Application PostgreSQL shutdown failed; inspect .local/pg-stop.err.log.' }
    Write-Output 'Stopped the separate application database.'
}
