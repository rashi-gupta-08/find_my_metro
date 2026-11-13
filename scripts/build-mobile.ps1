param([string]$FlutterPath='', [string]$OutputPath='', [ValidateSet('1','2','3','4')][string]$OptimizationLevel='2')
$ErrorActionPreference='Stop'
$metroRoot=[System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$metroRecordPath=Join-Path $metroRoot '.local/mobile-runtime.json'
if (Test-Path -LiteralPath $metroRecordPath) {
    $metroRuntime=Get-Content -LiteralPath $metroRecordPath -Raw | ConvertFrom-Json
    if (-not $FlutterPath) { $FlutterPath=$metroRuntime.flutter }
    if (-not $OutputPath) { $OutputPath=$metroRuntime.web_root }
}
if (-not $FlutterPath) { $FlutterPath=(Get-Command flutter -ErrorAction Stop).Source }
if (-not $OutputPath) { $OutputPath=Join-Path $metroRoot 'mobile/build/web' }
$OutputPath=[System.IO.Path]::GetFullPath($OutputPath)
$env:Path+=';'+$env:SystemRoot+'\System32;'+$env:SystemRoot+'\System32\WindowsPowerShell\v1.0'
Push-Location -LiteralPath (Join-Path $metroRoot 'mobile')
try {
    & $FlutterPath pub get
    if ($LASTEXITCODE -ne 0) { throw 'Mobile dependency resolution failed.' }
    & $FlutterPath build web --no-web-resources-cdn --no-wasm-dry-run --optimization-level $OptimizationLevel --output $OutputPath
    if ($LASTEXITCODE -ne 0) { throw 'Mobile web build failed.' }
} finally { Pop-Location }
@{ flutter=$FlutterPath;web_root=$OutputPath } | ConvertTo-Json | Set-Content -LiteralPath $metroRecordPath -Encoding utf8
