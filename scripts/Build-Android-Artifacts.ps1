[CmdletBinding()]
param(
    [ValidateSet('both', 'apk', 'aab')]
    [string]$Mode = 'apk',

    [string]$Distro = 'Ubuntu',

    [ValidateRange(0, 2100000000)]
    [int]$VersionCode = 0,

    [string]$ApiBaseUrl = $env:EXPO_PUBLIC_TROTTER_API_URL,

    [switch]$Development
)

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$mobileRoot = Join-Path $repoRoot 'mobile-v2'
$bashScript = Join-Path $PSScriptRoot 'build-android-artifacts.sh'
$signingProperties = Join-Path $mobileRoot 'android\signing.properties'

if (!(Test-Path -LiteralPath $bashScript)) {
    throw "Android build script not found: $bashScript"
}

if (!(Get-Command git -ErrorAction SilentlyContinue)) {
    throw 'Git was not found in this PowerShell session.'
}

if (!(Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'WSL was not found. Install WSL with an Ubuntu distribution first.'
}

if ($Mode -in @('both', 'aab')) {
    if ($VersionCode -le 0) {
        throw 'A positive -VersionCode is required when building a Play AAB.'
    }
    if (!(Test-Path -LiteralPath $signingProperties)) {
        throw @"
A Play AAB requires mobile-v2\android\signing.properties and its upload keystore.
Copy signing.properties.example, fill in the real values, and keep both files out of Git.
"@
    }
}

function Convert-ToWslPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$WindowsPath
    )

    $resolvedPath = [System.IO.Path]::GetFullPath($WindowsPath)
    $convertedPath = & wsl.exe -d $Distro --exec wslpath -a -u $resolvedPath
    $conversionExit = $LASTEXITCODE
    $wslPath = (($convertedPath -join "`n").Trim())
    if ($conversionExit -ne 0 -or [string]::IsNullOrWhiteSpace($wslPath) -or
        $wslPath -notmatch '^/' -or $wslPath -match "[`r`n]") {
        throw "Could not convert the Windows path for WSL: $resolvedPath"
    }

    return $wslPath
}

$branch = (& git -C $repoRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($branch)) {
    throw 'Unable to resolve the current Git branch.'
}

$dirty = @(& git -C $repoRoot status --porcelain --untracked-files=all)
if ($LASTEXITCODE -ne 0) {
    throw 'Unable to inspect the Git worktree.'
}
$head = (& git -C $repoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
    throw 'Unable to resolve the current Git commit.'
}

$buildChannel = if ($Development) { 'development' } else { 'release' }
if (![string]::IsNullOrWhiteSpace($ApiBaseUrl)) {
    $parsedApiUrl = $null
    if (![Uri]::TryCreate($ApiBaseUrl, [UriKind]::Absolute, [ref]$parsedApiUrl) -or
        $parsedApiUrl.Scheme -notin @('http', 'https') -or
        !$parsedApiUrl.Host -or
        $parsedApiUrl.AbsolutePath -ne '/') {
        throw '-ApiBaseUrl must be an absolute HTTP(S) origin without a path.'
    }
    $ApiBaseUrl = $ApiBaseUrl.TrimEnd('/')
}
if (!$Development) {
    if ([string]::IsNullOrWhiteSpace($ApiBaseUrl) -or !$ApiBaseUrl.StartsWith('https://')) {
        throw 'Release artifacts require an HTTPS -ApiBaseUrl.'
    }
    if ($branch -ne 'main') {
        throw "Android release artifacts must be built from main; current branch: $branch"
    }
    if ($dirty.Count -gt 0) {
        throw "The repository has uncommitted files. Commit or remove them before building.`n$($dirty -join "`n")"
    }

    & git -C $repoRoot fetch origin main --quiet
    if ($LASTEXITCODE -ne 0) {
        throw 'Unable to refresh origin/main before building.'
    }

    $originMain = (& git -C $repoRoot rev-parse origin/main).Trim()
    if ($LASTEXITCODE -ne 0 -or $head -ne $originMain) {
        throw "Local main is not exactly origin/main. Local: $head Remote: $originMain"
    }
}

$windowsBuilds = Join-Path $env:USERPROFILE 'Documents\builds'
New-Item -ItemType Directory -Force -Path $windowsBuilds | Out-Null

$wslScript = Convert-ToWslPath -WindowsPath (Resolve-Path -LiteralPath $bashScript).Path
$wslRepoRoot = Convert-ToWslPath -WindowsPath $repoRoot
$wslBuilds = Convert-ToWslPath -WindowsPath $windowsBuilds

Write-Host ''
Write-Host '=== Trotter Android build-only pipeline ===' -ForegroundColor Cyan
Write-Host "Mode: $Mode"
Write-Host "Channel: $buildChannel"
Write-Host "Commit: $head"
Write-Host "API: $(if ($ApiBaseUrl) { $ApiBaseUrl } else { 'http://localhost:8000 (development fallback)' })"
if ($Development) {
    Write-Warning 'Development artifacts may include uncommitted files and are not release candidates.'
}
if ($VersionCode -gt 0) {
    Write-Host "Play version code: $VersionCode"
}
Write-Host 'This creates artifacts only; it does not use ADB or upload to Google Play.'
Write-Host ''

& wsl.exe -d $Distro --exec bash $wslScript $Mode $head $wslRepoRoot $wslBuilds $VersionCode $buildChannel $ApiBaseUrl
$wslExit = $LASTEXITCODE

if ($wslExit -ne 0) {
    throw "WSL Android build failed with exit code $wslExit"
}

Write-Host ''
Write-Host 'Trotter Android artifacts built successfully.' -ForegroundColor Green
Write-Host "Open: $windowsBuilds"
