param([string]$FlutterPath='', [string]$AndroidSdk='')
$ErrorActionPreference='Stop'
$metroRoot=[System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not $FlutterPath) {
    $metroRuntime=Get-Content -LiteralPath (Join-Path $metroRoot '.local/mobile-runtime.json') -Raw | ConvertFrom-Json
    $FlutterPath=$metroRuntime.flutter
}
if (-not $AndroidSdk) { $AndroidSdk=$env:ANDROID_HOME }
if (-not $AndroidSdk) { $AndroidSdk=Join-Path $env:LOCALAPPDATA 'Android/SDK' }
if (-not (Test-Path -LiteralPath (Join-Path $AndroidSdk 'platform-tools/adb.exe'))) {
    throw 'Android SDK is missing. Install Android Studio/SDK, then pass -AndroidSdk with that folder. Flutter web remains available at localhost:5174.'
}
$env:ANDROID_HOME=$AndroidSdk
$env:Path+=';'+$env:SystemRoot+'\System32;'+$env:SystemRoot+'\System32\WindowsPowerShell\v1.0'
Push-Location -LiteralPath (Join-Path $metroRoot 'mobile')
try {
    & $FlutterPath build apk --debug --dart-define=API_BASE=http://localhost:5173 --dart-define=API_ORIGIN=http://localhost:5173
    if ($LASTEXITCODE -ne 0) { throw 'Android build failed.' }
    Write-Output 'APK: mobile/build/app/outputs/flutter-apk/app-debug.apk'
    Write-Output 'For a USB-connected test phone: adb reverse tcp:5173 tcp:5173'
    Write-Output 'Install the debug APK on your own phone; location checks need foreground precise-location permission.'
} finally { Pop-Location }
