[CmdletBinding()]
param(
    [string]$Version = '',
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$clientRoot = Join-Path $repo 'clients\canvas-bridge'
$serviceRoot = Join-Path $repo 'services\rag-api'
$workRoot = Join-Path $repo 'work\canvas-bridge-windows'
$deliverRoot = Join-Path $repo 'deliverables\coursejesus-upload-bridge-20260926'
$publicRoot = Join-Path $repo 'apps\web\public\downloads\canvas-bridge'
$versionFile = Join-Path $clientRoot 'VERSION'
if (-not $Version) { $Version = (Get-Content -LiteralPath $versionFile -Raw).Trim() }

$runningOnWindows = $env:OS -eq 'Windows_NT'
if (-not $runningOnWindows -or [Environment]::Is64BitProcess -ne $true) {
    throw 'This script must run with 64-bit PowerShell on Windows.'
}
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "Invalid client version: $Version" }

$resolvedRepo = [IO.Path]::GetFullPath($repo)
foreach ($target in @($workRoot, $deliverRoot, $publicRoot)) {
    $resolved = [IO.Path]::GetFullPath($target)
    if (-not $resolved.StartsWith($resolvedRepo + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to write outside repository: $resolved"
    }
}

New-Item -ItemType Directory -Force -Path $workRoot,$deliverRoot,$publicRoot | Out-Null
$venv = Join-Path $workRoot '.venv'
if (-not (Test-Path -LiteralPath (Join-Path $venv 'Scripts\python.exe'))) {
    python -m venv $venv
}
$python = Join-Path $venv 'Scripts\python.exe'
if (-not $SkipDependencyInstall) {
    & $python -m pip install --disable-pip-version-check --requirement (Join-Path $clientRoot 'requirements-build.txt')
}

$build = Join-Path $workRoot 'build'
$dist = Join-Path $workRoot 'dist'
$spec = Join-Path $workRoot 'spec'
foreach ($target in @($build, $dist, $spec)) {
    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
}
New-Item -ItemType Directory -Force -Path $spec | Out-Null

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name CourseJesus-Canvas-Bridge `
    --distpath $dist `
    --workpath $build `
    --specpath $spec `
    --paths $clientRoot `
    --paths $serviceRoot `
    (Join-Path $clientRoot 'main.py')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$package = Join-Path $dist 'CourseJesus-Canvas-Bridge'
$exe = Join-Path $package 'CourseJesus-Canvas-Bridge.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw "Expected executable was not produced: $exe" }
Copy-Item -LiteralPath (Join-Path $clientRoot 'README_中文_首次使用.txt') -Destination $package
Copy-Item -LiteralPath (Join-Path $clientRoot 'README_中文_首次使用.txt') -Destination (Join-Path $package 'README_中文.txt')
Copy-Item -LiteralPath (Join-Path $clientRoot 'THIRD_PARTY_NOTICES.txt') -Destination $package

$sourceCommit = (git -C $repo rev-parse HEAD).Trim()
$builtAt = [DateTimeOffset]::UtcNow.ToString('o')
$clientManifest = [ordered]@{
    schemaVersion = 1
    product = 'CourseJesus Canvas Bridge'
    version = $Version
    protocol = 'coursejesus.canvas-bridge-ticket.v1'
    platform = 'windows'
    architecture = 'x64'
    executable = 'CourseJesus-Canvas-Bridge.exe'
    sourceCommit = $sourceCommit
    upstreamCanvasReaderCommit = 'f05ffae8e98d3d6860695abe11c59c52718dd277'
    builtAt = $builtAt
    signed = $false
    acceptedApiOrigins = @('https://rag.coursejesus.com','https://rag.qqttai.com')
    containsConnectionCode = $false
    containsCanvasCredential = $false
    verification = [ordered]@{
        sourceChanged = $true
        artifactBuilt = $true
        testsRun = $false
        liveCanvasRun = $false
        deployed = $false
    }
}
$clientManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $package 'release-manifest.json') -Encoding utf8

$archiveName = "CourseJesus-Canvas-Bridge-win-x64-$Version.zip"
$archive = Join-Path $deliverRoot $archiveName
if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
Compress-Archive -Path (Join-Path $package '*') -DestinationPath $archive -CompressionLevel Optimal
$archiveItem = Get-Item -LiteralPath $archive
$archiveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()

$releaseManifest = [ordered]@{
    schemaVersion = 1
    available = $true
    product = 'CourseJesus Canvas Bridge'
    version = $Version
    platform = 'windows'
    architecture = 'x64'
    archive = $archiveName
    publicPath = "/downloads/canvas-bridge/$archiveName"
    sizeBytes = $archiveItem.Length
    sha256 = $archiveHash
    sourceCommit = $sourceCommit
    builtAt = $builtAt
    signed = $false
    containsConnectionCode = $false
    containsCanvasCredential = $false
    testsRun = $false
    liveCanvasRun = $false
    deployed = $false
}
$manifestPath = Join-Path $deliverRoot 'canvas-bridge-release-manifest.json'
$releaseManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding utf8
Copy-Item -LiteralPath $archive -Destination (Join-Path $publicRoot $archiveName) -Force
Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $publicRoot 'manifest.json') -Force

[ordered]@{
    executable = $exe
    archive = $archive
    manifest = $manifestPath
    publicArchive = (Join-Path $publicRoot $archiveName)
    sha256 = $archiveHash
    sizeBytes = $archiveItem.Length
    sourceCommit = $sourceCommit
} | ConvertTo-Json -Depth 4
