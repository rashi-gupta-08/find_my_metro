param([string]$PythonPath = '', [switch]$Docker, [switch]$Software, [switch]$Mobile, [switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
$metroProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $metroProjectRoot
New-Item -ItemType Directory -Force -Path (Join-Path $metroProjectRoot '.local/provider') | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $metroProjectRoot '.env'))) {
    $metroSecretBytes = New-Object byte[] 48
    $metroDatabaseBytes = New-Object byte[] 36
    $metroRng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $metroRng.GetBytes($metroSecretBytes)
    $metroRng.GetBytes($metroDatabaseBytes)
    $metroRng.Dispose()
    $metroEnv = @('APP_ENV=local', 'NETWORK_FILE=data/operator-network.json', 'SIMULATION_ENABLED=false', 'SECURE_COOKIES=false', ('AUTH_SECRET='+[Convert]::ToBase64String($metroSecretBytes)), ('POSTGRES_PASSWORD='+[Convert]::ToBase64String($metroDatabaseBytes).Replace('+','-').Replace('/','_')), ('APP_DATABASE_PASSWORD='+[Convert]::ToBase64String($metroSecretBytes).Replace('+','-').Replace('/','_')), ('MIGRATION_PASSWORD='+[Convert]::ToBase64String($metroDatabaseBytes).Replace('+','-').Replace('/','_')),  'CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173', 'ALLOWED_HOSTS=localhost,127.0.0.1')
    $metroEnv | Set-Content -LiteralPath (Join-Path $metroProjectRoot '.env') -Encoding UTF8
    Write-Output 'Created private configuration for this installation.'
}
if ($Docker) {
    if ($Software -or $Mobile) { throw 'Run the software/mobile profile locally without -Docker.' }
    & docker compose up --build -d
    if ($LASTEXITCODE -ne 0) { throw 'Docker could not start. Open Docker Desktop and retry, or run this script without -Docker.' }
    Write-Output 'Frontend: http://localhost:5173 | API: http://localhost:8000/docs'
    return
}
New-Item -ItemType Directory -Force -Path (Join-Path $metroProjectRoot '.local') | Out-Null
if (-not $PythonPath) {
    foreach ($metroCandidate in @((Join-Path $metroProjectRoot '.venv\Scripts\python.exe'), (Join-Path $metroProjectRoot '..\.venv\Scripts\python.exe'))) {
        if (Test-Path -LiteralPath $metroCandidate) { $PythonPath = (Resolve-Path -LiteralPath $metroCandidate).Path; break }
    }
}
if (-not $PythonPath) {
    $metroBundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Test-Path -LiteralPath $metroBundledPython) { & $metroBundledPython -m venv .venv }
    elseif (Get-Command py -ErrorAction SilentlyContinue) { & py -3.12 -m venv .venv }
    else { throw 'Install Python 3.12, or pass -PythonPath with its full path.' }
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the local Python environment.' }
    $PythonPath = Join-Path $metroProjectRoot '.venv\Scripts\python.exe'
}
$metroNode = (Get-Command node -ErrorAction Stop).Source
$metroNpm = (Get-Command npm.cmd -ErrorAction Stop).Source
$metroPorts=@(8000,5173)
if ($Mobile) { $metroPorts+=5174 }
foreach ($metroPort in $metroPorts) {
    if (Get-NetTCPConnection -LocalPort $metroPort -State Listen -ErrorAction SilentlyContinue) {
        throw "Local port $metroPort is already in use. Stop the existing app before starting this one."
    }
}
if (-not $SkipInstall) {
    & $PythonPath -m pip install -q -r backend/requirements.lock.txt --no-cache-dir --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
}
if (-not (Test-Path -LiteralPath 'frontend\node_modules\vite\bin\vite.js')) {
    Push-Location -LiteralPath 'frontend'
    try { & $metroNpm ci; if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' } }
    finally { Pop-Location }
}
Push-Location -LiteralPath 'frontend'
try { & $metroNpm run build; if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' } }
finally { Pop-Location }
if ($Mobile) {
    $metroMobileRecord=Join-Path $metroProjectRoot '.local/mobile-runtime.json'
    if (-not (Test-Path -LiteralPath $metroMobileRecord)) { & (Join-Path $PSScriptRoot 'build-mobile.ps1') }
    $metroMobileRuntime=Get-Content -LiteralPath $metroMobileRecord -Raw | ConvertFrom-Json
    if (-not (Test-Path -LiteralPath (Join-Path $metroMobileRuntime.web_root 'index.html'))) { & (Join-Path $PSScriptRoot 'build-mobile.ps1') }
}
$metroDatabaseRecord = Join-Path $metroProjectRoot '.local/database.json'
if (Test-Path -LiteralPath $metroDatabaseRecord) {
    $metroDatabase = Get-Content -LiteralPath $metroDatabaseRecord -Raw | ConvertFrom-Json
    $metroPgCtl = Join-Path $metroDatabase.bin 'pg_ctl.exe'
    & $metroPgCtl -D $metroDatabase.data status | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $metroPgLaunch = Start-Process -FilePath $metroPgCtl -ArgumentList @('-D',$metroDatabase.data,'-l',(Join-Path $metroDatabase.data 'server.log'),'-o','"-h 127.0.0.1 -p 5433"','-w','start') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $metroProjectRoot '.local/pg-start.out.log') -RedirectStandardError (Join-Path $metroProjectRoot '.local/pg-start.err.log')
        if (-not $metroPgLaunch.WaitForExit(60000)) { throw 'Application PostgreSQL startup timed out.' }
        if ($metroPgLaunch.ExitCode -ne 0) { throw 'Application PostgreSQL could not start; inspect .local/pg-start.err.log.' }
    }
}
$env:PYTHONUTF8='1'
$env:METRO_ENV_FILE = Join-Path $metroProjectRoot '.env'
if ($Software) {
    & $PythonPath -m scripts.setup_software
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the separate software-validation environment.' }
    $env:METRO_ENV_FILE = Join-Path $metroProjectRoot '.local/software.env'
}
if ($Mobile) {
    $metroCorsLine=Get-Content -LiteralPath $env:METRO_ENV_FILE | Where-Object { $_.StartsWith('CORS_ORIGINS=') } | Select-Object -Last 1
    $metroOrigins=if($metroCorsLine){$metroCorsLine.Substring(13).Trim('"').Split(',')}else{@('http://localhost:5173','http://127.0.0.1:5173')}
    $env:CORS_ORIGINS=(@($metroOrigins)+@('http://localhost:5174','http://127.0.0.1:5174') | Select-Object -Unique)-join ','
}
& $PythonPath -m backend.app.bootstrap
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed; services were not started.' }
$metroProcesses = @()
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONUNBUFFERED = '1'
try {
    $metroDefinitions = @(
        @{ name='api'; exe=$PythonPath; args=@('-m','uvicorn','backend.app.main:app','--host','127.0.0.1','--port','8000','--no-proxy-headers','--no-server-header','--ws-max-size','4096','--limit-concurrency','300'); cwd=$metroProjectRoot },
        @{ name='worker'; exe=$PythonPath; args=@('-m','backend.app.worker'); cwd=$metroProjectRoot },
        @{ name='frontend'; exe=$metroNode; args=@('server.mjs'); cwd=(Join-Path $metroProjectRoot 'frontend') }
    )
    if ($Mobile) { $metroDefinitions+=@{name='mobile';exe=$metroNode;args=@('server.mjs');cwd=(Join-Path $metroProjectRoot 'frontend')} }
    foreach ($metroDefinition in $metroDefinitions) {
        if ($metroDefinition.name -eq 'mobile') {
            $env:PORT='5174';$env:STATIC_ROOT=$metroMobileRuntime.web_root;$env:MOBILE_CLIENT='true'
        }
        $metroProcess = Start-Process -FilePath $metroDefinition.exe -ArgumentList $metroDefinition.args -WorkingDirectory $metroDefinition.cwd -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $metroProjectRoot ('.local\'+$metroDefinition.name+'.out.log')) -RedirectStandardError (Join-Path $metroProjectRoot ('.local\'+$metroDefinition.name+'.err.log'))
        if ($metroDefinition.name -eq 'mobile') { Remove-Item Env:PORT,Env:STATIC_ROOT,Env:MOBILE_CLIENT }
        $metroProcesses += @{ name=$metroDefinition.name; pid=$metroProcess.Id; start=$metroProcess.StartTime.ToUniversalTime().ToString('o') }
    }
    $metroProcesses | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $metroProjectRoot '.local\processes.json') -Encoding UTF8
    $metroReady = $false
    for ($metroAttempt=0; $metroAttempt -lt 30; $metroAttempt++) {
        Start-Sleep -Milliseconds 1000
        try {
            $metroHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/health' -TimeoutSec 2
            $metroFrontend = Invoke-WebRequest -Uri 'http://127.0.0.1:5173' -UseBasicParsing -TimeoutSec 2
            $metroMobileReady=$true
            if ($Mobile) { $metroMobileReady=(Invoke-WebRequest -Uri 'http://127.0.0.1:5174' -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 }
            if ($metroHealth.ready -and $metroFrontend.StatusCode -eq 200 -and $metroMobileReady) { $metroReady=$true; break }
        } catch { }
    }
    if (-not $metroReady) { throw 'Services did not become ready. Inspect the .local logs.' }
    Write-Output 'FindMyMetro is running locally.'
    if ($Software) { Write-Output 'Software input feed enabled in a separate database. No real metro tracking is being claimed.' }
    Write-Output 'Frontend: http://localhost:5173'
    Write-Output 'API documentation: http://localhost:8000/docs'
    if ($Mobile) { Write-Output 'Flutter client: http://localhost:5174' }
    Write-Output ('Database: '+$metroHealth.database+' | Worker: '+$metroHealth.worker)
    Write-Output 'Stop with: powershell -ExecutionPolicy Bypass -File scripts/stop.ps1'
} catch {
    foreach ($metroRecord in $metroProcesses) {
        $metroProcess = Get-Process -Id $metroRecord.pid -ErrorAction SilentlyContinue
        if ($metroProcess -and $metroProcess.StartTime.ToUniversalTime().Ticks -eq ([datetime]$metroRecord.start).ToUniversalTime().Ticks) { & (Join-Path $env:SystemRoot 'System32/taskkill.exe') /PID $metroRecord.pid /T /F | Out-Null }
    }
    throw
}
