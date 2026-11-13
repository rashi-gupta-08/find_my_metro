param([string]$PythonPath='', [string]$NodePath='', [string]$PlaywrightModules='')
$ErrorActionPreference='Stop'
$metroRoot=[System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $metroRoot
if (-not $PythonPath) {
    foreach ($metroCandidate in @((Join-Path $metroRoot '.venv/Scripts/python.exe'),(Join-Path $metroRoot '../.venv/Scripts/python.exe'))) {
        if (Test-Path -LiteralPath $metroCandidate) { $PythonPath=(Resolve-Path -LiteralPath $metroCandidate).Path; break }
    }
}
if (-not $PythonPath) { throw 'Pass -PythonPath with the application Python environment.' }
if (-not $NodePath) { $NodePath=(Get-Command node -ErrorAction Stop).Source }
if (-not $PlaywrightModules) {
    $metroBundledModules=Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'
    if (Test-Path -LiteralPath (Join-Path $metroBundledModules 'playwright')) { $PlaywrightModules=$metroBundledModules }
}
foreach ($metroPort in @(8010,5180)) {
    if (Get-NetTCPConnection -LocalPort $metroPort -State Listen -ErrorAction SilentlyContinue) { throw "Test port $metroPort is in use. The test does not stop existing applications." }
}
$metroRun=Join-Path $metroRoot ('.local/crowd-checks/'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $metroRun -Force | Out-Null
$metroOverrides=@{
    APP_ENV='test'; SIMULATION_ENABLED='false'; NETWORK_FILE='data/operator-network.json';
    DATABASE_URL=('sqlite:///'+(Join-Path $metroRun 'crowd-test.db').Replace('\','/')); MIGRATION_DATABASE_URL='';
    AUTH_SECRET=('isolated-crowd-check-'+[Guid]::NewGuid().ToString('N')+[Guid]::NewGuid().ToString('N'));
    SECURE_COOKIES='false'; PREDICTION_MODEL_FILE=''; MQTT_ENABLED='false'; SENSOR_API_KEY=''; ADMIN_API_KEY=''; CROWD_TOKENS='';
    CORS_ORIGINS='http://localhost:5180,http://127.0.0.1:5180'; ALLOWED_HOSTS='localhost,127.0.0.1';
    METRO_ENV_FILE=(Join-Path $metroRun 'test.env'); PORT='5180'; BACKEND_URL='http://127.0.0.1:8010';
    STATIC_ROOT=(Join-Path $metroRoot 'frontend/dist'); MOBILE_CLIENT='false';
    METRO_CROWD_CHECK_URL='http://localhost:5180'; METRO_CROWD_CHECK_OUTPUT=$metroRun;
    PYTHONUTF8='1'; PYTHONUNBUFFERED='1'; PYTHONDONTWRITEBYTECODE='1'
}
if ($PlaywrightModules) { $metroOverrides['NODE_PATH']=$PlaywrightModules }
Set-Content -LiteralPath $metroOverrides.METRO_ENV_FILE -Value '# Isolated browser test configuration is supplied through the process environment.' -Encoding UTF8
$metroOriginal=@{}
foreach ($metroKey in $metroOverrides.Keys) { $metroOriginal[$metroKey]=[Environment]::GetEnvironmentVariable($metroKey,'Process'); [Environment]::SetEnvironmentVariable($metroKey,$metroOverrides[$metroKey],'Process') }
$metroProcesses=@()
try {
    if (-not (Test-Path -LiteralPath 'frontend/dist/sw.js')) { throw 'Build the frontend first: cd frontend; npm.cmd run build' }
    & $PythonPath -m backend.app.bootstrap
    if ($LASTEXITCODE -ne 0) { throw 'Isolated test migration failed.' }
    $metroDefinitions=@(
        @{name='api';exe=$PythonPath;args=@('-m','uvicorn','backend.app.main:app','--host','127.0.0.1','--port','8010','--no-proxy-headers');cwd=$metroRoot},
        @{name='worker';exe=$PythonPath;args=@('-m','backend.app.worker');cwd=$metroRoot},
        @{name='frontend';exe=$NodePath;args=@('server.mjs');cwd=(Join-Path $metroRoot 'frontend')}
    )
    foreach ($metroDefinition in $metroDefinitions) {
        $metroProcess=Start-Process -FilePath $metroDefinition.exe -ArgumentList $metroDefinition.args -WorkingDirectory $metroDefinition.cwd -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $metroRun ($metroDefinition.name+'.out.log')) -RedirectStandardError (Join-Path $metroRun ($metroDefinition.name+'.err.log'))
        $metroProcesses+=@{pid=$metroProcess.Id;start=$metroProcess.StartTime.ToUniversalTime().Ticks}
    }
    $metroReady=$false
    for ($metroAttempt=0; $metroAttempt -lt 30; $metroAttempt++) {
        Start-Sleep -Milliseconds 500
        try {
            $metroHealth=Invoke-RestMethod -Uri 'http://localhost:5180/api/v1/health' -TimeoutSec 2
            if ($metroHealth.ready -and $metroHealth.database -eq 'sqlite' -and -not $metroHealth.simulated) { $metroReady=$true; break }
        } catch { }
    }
    if (-not $metroReady) { throw ('Isolated services did not become ready. Logs: '+$metroRun) }
    & $NodePath (Join-Path $PSScriptRoot 'crowdsourcing-browser-check.cjs')
    if ($LASTEXITCODE -ne 0) { throw ('Crowdsourcing check failed. Evidence: '+$metroRun) }
    Write-Output ('Crowdsourcing verified with three independent browser sessions. Evidence: '+$metroRun)
} finally {
    foreach ($metroRecord in $metroProcesses) {
        $metroProcess=Get-Process -Id $metroRecord.pid -ErrorAction SilentlyContinue
        if ($metroProcess -and $metroProcess.StartTime.ToUniversalTime().Ticks -eq $metroRecord.start) { & (Join-Path $env:SystemRoot 'System32/taskkill.exe') /PID $metroRecord.pid /T /F | Out-Null }
    }
    foreach ($metroKey in $metroOriginal.Keys) { [Environment]::SetEnvironmentVariable($metroKey,$metroOriginal[$metroKey],'Process') }
}
