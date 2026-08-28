$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$sdkRoot = Join-Path $projectRoot '.android-tools\sdk'
$gradle = Join-Path $projectRoot '.android-tools\gradle-8.11.1\bin\gradle.bat'
$androidProject = $PSScriptRoot
$output = Join-Path $projectRoot 'dist\NanaPhone-debug.apk'

if (-not (Test-Path -LiteralPath $sdkRoot)) {
    throw "Android SDK not found: $sdkRoot"
}
if (-not (Test-Path -LiteralPath $gradle)) {
    throw "Gradle not found: $gradle"
}

$env:ANDROID_SDK_ROOT = $sdkRoot
$env:ANDROID_HOME = $sdkRoot
& $gradle --no-daemon --project-dir $androidProject assembleDebug
if ($LASTEXITCODE -ne 0) { throw "Gradle build failed with exit code $LASTEXITCODE" }

$apk = Join-Path $androidProject 'app\build\outputs\apk\debug\app-debug.apk'
if (-not (Test-Path -LiteralPath $apk)) { throw "APK not found after build: $apk" }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $output) | Out-Null
Copy-Item -LiteralPath $apk -Destination $output -Force
Write-Output "APK: $output"
