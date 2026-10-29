[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet(
        'help',
        'test-ssh',
        'setup',
        'doctor',
        'doctor-local',
        'sync',
        'validate',
        'eas-login',
        'credentials',
        'build-cloud',
        'build-local',
        'attach',
        'status',
        'submit-latest',
        'submit-local',
        'submit-local-eas',
        'configure-direct-submit',
        'doctor-direct-submit',
        'direct-submit-status',
        'pull-latest',
        'smoke-simulator',
        'snapshot',
        'build-snapshot',
        'snapshot-status',
        'pull-snapshot',
        'shell'
    )]
    [string]$Action = 'help',

    [string]$Branch,
    [string]$Profile,
    [string]$SimulatorUdid,
    [string]$SnapshotId,
    [string]$AscKeyId,
    [string]$AscIssuerId,
    [string]$AscKeyPath,
    [switch]$SkipValidation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ConfigPath = Join-Path $PSScriptRoot 'config.psd1'
$ConfigExamplePath = Join-Path $PSScriptRoot 'config.example.psd1'
$MacHelperPath = Join-Path $PSScriptRoot 'mac\ios-remote.sh'
$SimulatorHelperPath = Join-Path $PSScriptRoot 'mac\simulator-smoke.sh'
$IpaVerifyHelperPath = Join-Path $PSScriptRoot 'mac\verify-production-ipa.sh'
$ArtifactValidationPath = Join-Path $PSScriptRoot 'mac\artifact-validation.py'
$SnapshotHelperPath = Join-Path $PSScriptRoot 'mac\snapshot-build.sh'
$SnapshotVerifierPath = Join-Path $PSScriptRoot 'verify-snapshot.py'
$SnapshotPackagePath = Join-Path $PSScriptRoot 'create-snapshot.cjs'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$LocalArtifacts = Join-Path $PSScriptRoot 'artifacts'

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    if (Test-Path -LiteralPath $ConfigExamplePath) {
        $ConfigPath = $ConfigExamplePath
    }
    else {
        throw "Missing both $ConfigPath and $ConfigExamplePath."
    }
}

if (-not (Test-Path -LiteralPath $MacHelperPath)) {
    throw "Missing $MacHelperPath"
}

if (-not (Test-Path -LiteralPath $SimulatorHelperPath)) {
    throw "Missing $SimulatorHelperPath"
}

if (-not (Test-Path -LiteralPath $IpaVerifyHelperPath)) {
    throw "Missing $IpaVerifyHelperPath"
}

$Config = Import-PowerShellDataFile -LiteralPath $ConfigPath
$HostAlias = [string]$Config.HostAlias
$MacRepo = [string]$Config.MacRepo
$RepoUrl = [string]$Config.RepoUrl
$MacArtifacts = [string]$Config.MacArtifacts
$EasCliVersion = [string]$Config.EasCliVersion

if (-not $Branch) {
    $Branch = [string]$Config.Branch
}

if (-not $Profile) {
    $Profile = [string]$Config.Profile
}

function Write-Step {
    param([string]$Message)
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    & $Command @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed with exit code $LASTEXITCODE"
    }
}

function Get-GitOutput {
    param([string[]]$Arguments)

    $output = & git -C $RepoRoot @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }

    return (($output -join "`n").Trim())
}

function Assert-SafeRemoteValue {
    param(
        [string]$Name,
        [string]$Value
    )

    if ([string]::IsNullOrWhiteSpace($Value) -or $Value -notmatch '^[A-Za-z0-9._~:/@+\-]+$') {
        throw "$Name contains unsupported characters. Avoid spaces and shell metacharacters: $Value"
    }
}

foreach ($entry in @{
    HostAlias     = $HostAlias
    MacRepo       = $MacRepo
    RepoUrl       = $RepoUrl
    Branch        = $Branch
    Profile       = $Profile
    MacArtifacts  = $MacArtifacts
    EasCliVersion = $EasCliVersion
}.GetEnumerator()) {
    Assert-SafeRemoteValue -Name $entry.Key -Value ([string]$entry.Value)
}

if ($HostAlias -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') { throw 'Use an SSH host alias, not SSH command options.' }
if ($MacRepo -notmatch '(?:^~/|^/Users/[A-Za-z0-9._-]+/)Developer/trotter[A-Za-z0-9._-]*$') { throw 'MacRepo must be a dedicated Trotter clone under ~/Developer.' }
if ($MacArtifacts -notmatch '(?:^~/|^/Users/[A-Za-z0-9._-]+/)TrotterBuilds[A-Za-z0-9._-]*$') { throw 'MacArtifacts must be a separate TrotterBuilds directory.' }
if ($Profile -notin @('iphone-simulator', 'iphone-development', 'iphone-testflight')) { throw 'Select a Trotter iPhone build profile.' }

function Get-LocalCommit {
    return Get-GitOutput -Arguments @('rev-parse', 'HEAD')
}

function Assert-BranchIsPushed {
    param([switch]$RequireClean)

    $currentBranch = Get-GitOutput -Arguments @('branch', '--show-current')
    if ($currentBranch -ne $Branch) {
        throw "Configured branch is '$Branch', but the PC is on '$currentBranch'. Switch branches or pass -Branch $currentBranch."
    }

    if ($RequireClean) {
        $status = Get-GitOutput -Arguments @('status', '--porcelain', '--untracked-files=all')
        if ($status) {
            throw "The PC worktree is not clean. Commit, move, or remove these changes before building:`n$status"
        }
    }

    $localCommit = Get-LocalCommit
    $remoteLine = Get-GitOutput -Arguments @('ls-remote', '--heads', 'origin', "refs/heads/$Branch")
    if (-not $remoteLine) {
        throw "origin/$Branch does not exist. Push the branch first."
    }

    $remoteCommit = ($remoteLine -split '\s+')[0]
    if ($localCommit -ne $remoteCommit) {
        throw "PC HEAD $localCommit is not the pushed origin/$Branch commit $remoteCommit. Push the exact commit first."
    }

    return $localCommit
}

function Install-MacHelper {
    Write-Step "Refreshing the Mac helper"
    Invoke-Native -Command 'ssh' -Arguments @($HostAlias, 'umask 077; mkdir -p ~/.trotter-ios-remote')
    Invoke-Native -Command 'scp' -Arguments @($MacHelperPath, "${HostAlias}:.trotter-ios-remote/ios-remote.sh")
    Invoke-Native -Command 'scp' -Arguments @($SimulatorHelperPath, "${HostAlias}:.trotter-ios-remote/simulator-smoke.sh")
    Invoke-Native -Command 'scp' -Arguments @($IpaVerifyHelperPath, "${HostAlias}:.trotter-ios-remote/verify-production-ipa.sh")
    Invoke-Native -Command 'scp' -Arguments @($ArtifactValidationPath, "${HostAlias}:.trotter-ios-remote/artifact-validation.py")
    Invoke-Native -Command 'scp' -Arguments @($SnapshotHelperPath, "${HostAlias}:.trotter-ios-remote/snapshot-build.sh")
    Invoke-Native -Command 'scp' -Arguments @($SnapshotVerifierPath, "${HostAlias}:.trotter-ios-remote/verify-snapshot.py")
    Invoke-Native -Command 'ssh' -Arguments @($HostAlias, 'chmod 700 ~/.trotter-ios-remote/ios-remote.sh ~/.trotter-ios-remote/simulator-smoke.sh ~/.trotter-ios-remote/verify-production-ipa.sh ~/.trotter-ios-remote/snapshot-build.sh')
}

function Invoke-MacHelper {
    param(
        [Parameter(Mandatory = $true)][string]$RemoteAction,
        [Parameter(Mandatory = $true)][string]$Commit,
        [string[]]$ExtraArguments = @(),
        [switch]$Interactive
    )

    foreach ($extraArgument in $ExtraArguments) {
        Assert-SafeRemoteValue -Name 'remote helper argument' -Value $extraArgument
    }

    $commandParts = @(
        '~/.trotter-ios-remote/ios-remote.sh',
        $RemoteAction,
        $MacRepo,
        $RepoUrl,
        $Branch,
        $Commit,
        $Profile,
        $MacArtifacts,
        $EasCliVersion
    ) + $ExtraArguments
    $command = $commandParts -join ' '
    $sshArguments = @()
    if ($Interactive) {
        $sshArguments += '-tt'
    }
    $sshArguments += $HostAlias
    $sshArguments += $command

    Invoke-Native -Command 'ssh' -Arguments $sshArguments
}

function Sync-ExactCommit {
    param([switch]$RequireClean)

    $commit = Assert-BranchIsPushed -RequireClean:$RequireClean
    Install-MacHelper
    Invoke-MacHelper -RemoteAction 'sync' -Commit $commit
    return $commit
}

function New-SourceSnapshot {
    $output = & node $SnapshotPackagePath
    if ($LASTEXITCODE -ne 0) { throw 'Source snapshot packaging failed.' }
    $snapshot = ($output -join "`n") | ConvertFrom-Json
    if ($snapshot.contentId -notmatch '^[a-f0-9]{64}$' -or $snapshot.archiveSha256 -notmatch '^[a-f0-9]{64}$') { throw 'Invalid source snapshot result.' }
    $record = Join-Path $LocalArtifacts 'snapshots\latest.json'
    [IO.File]::WriteAllText($record, ($snapshot | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
    Write-Host "Snapshot $($snapshot.contentId): $($snapshot.fileCount) files, $($snapshot.sourceBytes) source bytes."
    return $snapshot
}

function Get-SnapshotId {
    if ($SnapshotId) { $value = $SnapshotId }
    else {
        $record = Join-Path $LocalArtifacts 'snapshots\latest.json'
        if (-not (Test-Path -LiteralPath $record)) { throw 'Create a snapshot first, or pass -SnapshotId.' }
        $value = (Get-Content -Raw -LiteralPath $record | ConvertFrom-Json).contentId
    }
    if ($value -notmatch '^[a-f0-9]{64}$') { throw 'SnapshotId must be a 64-character content SHA256.' }
    return [string]$value
}

function Invoke-SnapshotHelper {
    param([string]$RemoteAction, [string]$Id, [string[]]$ExtraArguments = @())
    $source = "~/.trotter-ios-remote/snapshots/$Id"
    $parts = @('~/.trotter-ios-remote/ios-remote.sh', $RemoteAction, $source, $RepoUrl, $Branch,
        $Id, 'iphone-simulator', $MacArtifacts, $EasCliVersion) + $ExtraArguments
    foreach ($value in $parts | Select-Object -Skip 1) { Assert-SafeRemoteValue -Name 'snapshot argument' -Value $value }
    Invoke-Native -Command ssh -Arguments @($HostAlias, ($parts -join ' '))
}

function Show-Help {
    @"
Trotter PC -> Mac iOS build helper

Usage:
  .\.ios-remote\trotter-ios.ps1 <action> [-Branch name] [-Profile name]

First-time actions:
  test-ssh       Verify the Windows SSH alias reaches the Mac.
  setup          Install the helper and create/update the dedicated Mac clone.
  doctor         Check tools needed to trigger EAS cloud builds.
  doctor-local   Also check Xcode, CocoaPods, Fastlane, and tmux.
  eas-login      Sign the dedicated Mac user into Expo (interactive).
  credentials    Configure EAS-managed iOS signing after Apple approval.

Routine actions:
  sync           Require a clean, pushed PC commit and select that exact SHA on Mac.
  validate       Sync, npm ci, run iPhone readiness checks, typecheck and tests.
  build-cloud    Validate, then queue an EAS cloud iOS build and return.
  build-local    Validate, then run eas build --local in persistent tmux when available.
  attach         Reattach to the persistent local-build tmux session.
  status         Show recent EAS iOS builds.
  submit-latest  Submit the finished EAS build matching the exact SHA and profile.
  configure-direct-submit
                 Securely install a separately downloaded App Store Connect API key.
  doctor-direct-submit
                 Validate Apple's uploader, local key permissions, and Apple authentication.
  submit-local   Preferred: upload the exact-SHA Mac-local IPA directly to Apple.
  submit-local-eas
                 Fallback: send the exact-SHA Mac-local IPA through EAS Submit.
  direct-submit-status
                 Check Apple's processing state for the last direct upload.
  pull-latest    Copy the newest exact-SHA/profile Mac-local artifact.
  smoke-simulator Fresh-install a verified simulator artifact and copy launch evidence.
                  Pass -SnapshotId to check a source snapshot.
  snapshot       Package the current app sources, including uncommitted files, with hashes.
  build-snapshot Compile that isolated snapshot on the Mac without signing or publishing.
  snapshot-status Show the persistent simulator-snapshot result and log path.
  pull-snapshot  Download the matching successful simulator snapshot artifact.
  shell          Open a normal interactive SSH session.

Safety:
  Release builds refuse dirty, unpushed, stale, or mismatched commits. Unsigned
  snapshots can compile current working changes. Normal source transfers exclude
  node_modules, .env files, certificates, and provisioning profiles.
  Only configure-direct-submit copies its explicitly selected API key, directly into
  an owner-only directory outside both Git clones.
"@ | Write-Host
}

switch ($Action) {
    'help' {
        Show-Help
    }
    'snapshot' {
        $snapshot = New-SourceSnapshot
        Write-Host "Archive: $($snapshot.archivePath)"
    }
    'build-snapshot' {
        $snapshot = New-SourceSnapshot
        Install-MacHelper
        Invoke-Native -Command ssh -Arguments @($HostAlias, 'umask 077; mkdir -p ~/.trotter-ios-remote/incoming')
        Invoke-Native -Command scp -Arguments @([string]$snapshot.archivePath, "${HostAlias}:.trotter-ios-remote/incoming/$($snapshot.contentId).tar.gz")
        Invoke-SnapshotHelper -RemoteAction 'simulator-snapshot' -Id $snapshot.contentId -ExtraArguments @($snapshot.archiveSha256)
    }
    'snapshot-status' {
        Install-MacHelper
        Invoke-SnapshotHelper -RemoteAction 'snapshot-status' -Id (Get-SnapshotId)
    }
    'pull-snapshot' {
        $id = Get-SnapshotId
        Install-MacHelper
        $source = "~/.trotter-ios-remote/snapshots/$id"
        $output = & ssh $HostAlias "~/.trotter-ios-remote/ios-remote.sh snapshot-latest-artifact $source $RepoUrl $Branch $id iphone-simulator $MacArtifacts $EasCliVersion"
        if ($LASTEXITCODE -ne 0) { throw 'No successful matching snapshot artifact is available.' }
        $artifact = ([string]($output | Select-Object -Last 1)).Trim()
        Assert-SafeRemoteValue -Name 'snapshot artifact' -Value $artifact
        if ($artifact -notmatch '/TrotterBuilds[A-Za-z0-9._-]*/' -or -not $artifact.Contains($id)) { throw 'Snapshot artifact path does not match the selected Trotter snapshot.' }
        $destination = Join-Path $LocalArtifacts "snapshots\$id"
        New-Item -ItemType Directory -Force -Path $destination | Out-Null
        Invoke-Native -Command scp -Arguments @("${HostAlias}:$artifact", $destination)
        Write-Host "Saved under $destination"
    }
    'test-ssh' {
        Write-Step "Testing SSH alias '$HostAlias'"
        Invoke-Native -Command 'ssh' -Arguments @($HostAlias, 'printf "Connected to "; scutil --get LocalHostName; sw_vers -productVersion')
    }
    'setup' {
        $commit = Assert-BranchIsPushed
        Install-MacHelper
        Invoke-MacHelper -RemoteAction 'setup' -Commit $commit -Interactive
    }
    'doctor' {
        Install-MacHelper
        Invoke-MacHelper -RemoteAction 'doctor' -Commit (Get-LocalCommit) -Interactive
    }
    'doctor-local' {
        Install-MacHelper
        Invoke-MacHelper -RemoteAction 'doctor-local' -Commit (Get-LocalCommit) -Interactive
    }
    'sync' {
        [void](Sync-ExactCommit -RequireClean)
    }
    'validate' {
        $commit = Sync-ExactCommit -RequireClean
        Invoke-MacHelper -RemoteAction 'validate' -Commit $commit -Interactive
    }
    'eas-login' {
        Install-MacHelper
        Invoke-MacHelper -RemoteAction 'eas-login' -Commit (Get-LocalCommit) -Interactive
    }
    'credentials' {
        $commit = Sync-ExactCommit -RequireClean
        Invoke-MacHelper -RemoteAction 'credentials' -Commit $commit -Interactive
    }
    'build-cloud' {
        $commit = Sync-ExactCommit -RequireClean
        if (-not $SkipValidation) {
            Invoke-MacHelper -RemoteAction 'validate' -Commit $commit -Interactive
        }
        Invoke-MacHelper -RemoteAction 'build-cloud' -Commit $commit -Interactive
    }
    'build-local' {
        $commit = Sync-ExactCommit -RequireClean
        if (-not $SkipValidation) {
            Invoke-MacHelper -RemoteAction 'validate' -Commit $commit -Interactive
        }
        Invoke-MacHelper -RemoteAction 'build-local' -Commit $commit -Interactive
    }
    'attach' {
        Install-MacHelper
        Invoke-MacHelper -RemoteAction 'attach' -Commit (Get-LocalCommit) -Interactive
    }
    'status' {
        Install-MacHelper
        Invoke-MacHelper -RemoteAction 'status' -Commit (Get-LocalCommit) -Interactive
    }
    'submit-latest' {
        $commit = Sync-ExactCommit -RequireClean
        Invoke-MacHelper -RemoteAction 'submit-latest' -Commit $commit -Interactive
    }
    'submit-local' {
        $commit = Sync-ExactCommit -RequireClean
        Invoke-MacHelper -RemoteAction 'submit-local' -Commit $commit -Interactive
    }
    'submit-local-eas' {
        $commit = Sync-ExactCommit -RequireClean
        Invoke-MacHelper -RemoteAction 'submit-local-eas' -Commit $commit -Interactive
    }
    'configure-direct-submit' {
        if ([string]::IsNullOrWhiteSpace($AscKeyId) -or
            [string]::IsNullOrWhiteSpace($AscIssuerId) -or
            [string]::IsNullOrWhiteSpace($AscKeyPath)) {
            throw 'configure-direct-submit requires -AscKeyId, -AscIssuerId, and -AscKeyPath.'
        }
        if ($AscKeyId -notmatch '^[A-Z0-9]{10}$') {
            throw 'The App Store Connect Key ID must be exactly 10 uppercase letters or digits.'
        }
        if ($AscIssuerId -notmatch '^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$') {
            throw 'The App Store Connect Issuer ID must be a UUID.'
        }

        $resolvedKey = (Resolve-Path -LiteralPath $AscKeyPath).Path
        $expectedKeyName = "AuthKey_$AscKeyId.p8"
        if ([System.IO.Path]::GetFileName($resolvedKey) -cne $expectedKeyName) {
            throw "The API key filename must be exactly $expectedKeyName."
        }
        $repoPrefix = $RepoRoot.TrimEnd('\') + '\'
        if ($resolvedKey.StartsWith($repoPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw 'Keep the App Store Connect private key outside the Git repository.'
        }
        $keyItem = Get-Item -LiteralPath $resolvedKey
        if ($keyItem.PSIsContainer -or $keyItem.Length -lt 100 -or $keyItem.Length -gt 16384) {
            throw 'The selected App Store Connect .p8 file is missing, empty, or unexpectedly large.'
        }
        $firstLine = Get-Content -LiteralPath $resolvedKey -TotalCount 1
        $lastLine = Get-Content -LiteralPath $resolvedKey | Select-Object -Last 1
        if ($firstLine -ne '-----BEGIN PRIVATE KEY-----' -or $lastLine -ne '-----END PRIVATE KEY-----') {
            throw 'The selected file is not an unencrypted PKCS#8 private key.'
        }

        Install-MacHelper
        $stagingToken = [Guid]::NewGuid().ToString('N')
        $incomingName = "AuthKey_$AscKeyId.$stagingToken.p8"
        Invoke-Native -Command 'ssh' -Arguments @(
            $HostAlias,
            'umask 077; mkdir -p ~/.trotter-ios-remote/incoming; chmod 700 ~/.trotter-ios-remote/incoming'
        )
        try {
            Invoke-Native -Command 'scp' -Arguments @(
                $resolvedKey,
                "${HostAlias}:.trotter-ios-remote/incoming/$incomingName"
            )
            Invoke-MacHelper `
                -RemoteAction 'configure-direct-submit' `
                -Commit (Get-LocalCommit) `
                -ExtraArguments @($AscKeyId, $AscIssuerId, $incomingName) `
                -Interactive
        }
        finally {
            & ssh $HostAlias "rm -f ~/.trotter-ios-remote/incoming/$incomingName" | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "Could not confirm removal of the staged API key. When the Mac is reachable, run: ssh $HostAlias 'rm -f ~/.trotter-ios-remote/incoming/$incomingName'"
            }
        }
    }
    'doctor-direct-submit' {
        Install-MacHelper
        Invoke-MacHelper -RemoteAction 'doctor-direct-submit' -Commit (Get-LocalCommit) -Interactive
    }
    'direct-submit-status' {
        Install-MacHelper
        Invoke-MacHelper -RemoteAction 'direct-submit-status' -Commit (Get-LocalCommit) -Interactive
    }
    'pull-latest' {
        Install-MacHelper
        New-Item -ItemType Directory -Force -Path $LocalArtifacts | Out-Null
        $remoteCommand = "~/.trotter-ios-remote/ios-remote.sh latest-artifact $MacRepo $RepoUrl $Branch $(Get-LocalCommit) $Profile $MacArtifacts $EasCliVersion"
        $remoteOutput = & ssh $HostAlias $remoteCommand
        $sshExitCode = $LASTEXITCODE
        $remoteArtifact = ([string]($remoteOutput | Select-Object -Last 1)).Trim()
        if ($sshExitCode -ne 0 -or -not $remoteArtifact) {
            throw 'No matching Mac-local build artifact was found.'
        }
        Assert-SafeRemoteValue -Name 'remote artifact' -Value $remoteArtifact
        Write-Step "Copying $remoteArtifact"
        Invoke-Native -Command 'scp' -Arguments @("${HostAlias}:$remoteArtifact", $LocalArtifacts)
        Write-Host "Saved under $LocalArtifacts" -ForegroundColor Green
    }
    'smoke-simulator' {
        if ($Profile -ne 'iphone-simulator') {
            throw 'smoke-simulator requires -Profile iphone-simulator.'
        }

        if ($SnapshotId) {
            $commit = Get-SnapshotId
            $snapshotRepo = "~/.trotter-ios-remote/snapshots/$commit"
            $artifactCommand = "~/.trotter-ios-remote/ios-remote.sh snapshot-latest-artifact $snapshotRepo $RepoUrl $Branch $commit $Profile $MacArtifacts $EasCliVersion"
        }
        else {
            $commit = Assert-BranchIsPushed -RequireClean
            $artifactCommand = "~/.trotter-ios-remote/ios-remote.sh latest-artifact $MacRepo $RepoUrl $Branch $commit $Profile $MacArtifacts $EasCliVersion"
        }
        Install-MacHelper
        $artifactOutput = & ssh $HostAlias $artifactCommand
        $artifactExitCode = $LASTEXITCODE
        $remoteArtifact = ([string]($artifactOutput | Select-Object -Last 1)).Trim()
        if ($artifactExitCode -ne 0 -or -not $remoteArtifact) {
            throw 'No verified iphone-simulator artifact was found for the selected commit or snapshot. Complete its build first.'
        }
        Assert-SafeRemoteValue -Name 'remote artifact' -Value $remoteArtifact

        if (-not $SimulatorUdid) {
            $deviceJson = (& ssh $HostAlias 'export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer; xcrun simctl list devices available -j') -join "`n"
            if ($LASTEXITCODE -ne 0 -or -not $deviceJson) {
                throw 'Could not list available iPhone simulators on the Mac.'
            }

            $devices = (ConvertFrom-Json $deviceJson).devices.PSObject.Properties.Value |
                ForEach-Object { $_ } |
                Where-Object { $_.isAvailable -and $_.name -like 'Trotter*' }
            $selectedDevice = $devices | Where-Object { $_.state -eq 'Booted' } | Select-Object -First 1
            if (-not $selectedDevice) {
                $selectedDevice = $devices | Select-Object -First 1
            }
            if (-not $selectedDevice) {
                throw 'No dedicated Trotter simulator was found. Create a Trotter-named iPhone simulator, then pass its UDID.'
            }
            $SimulatorUdid = [string]$selectedDevice.udid
        }
        Assert-SafeRemoteValue -Name 'Simulator UDID' -Value $SimulatorUdid

        Write-Step "Fresh-installing the exact build on simulator $SimulatorUdid"
        $smokeOutput = & ssh $HostAlias "~/.trotter-ios-remote/simulator-smoke.sh $remoteArtifact $SimulatorUdid"
        $smokeExitCode = $LASTEXITCODE
        $smokeOutput | Out-Host
        if ($smokeExitCode -ne 0) {
            throw "Simulator smoke test failed with exit code $smokeExitCode"
        }

        $smokeValues = @{}
        foreach ($line in $smokeOutput) {
            if ([string]$line -match '^([A-Z_]+)=(.+)$') {
                $smokeValues[$Matches[1]] = $Matches[2]
            }
        }
        if ($smokeValues.APP_STATUS -ne 'running' -or -not $smokeValues.SCREENSHOT -or -not $smokeValues.LOG) {
            throw 'The simulator smoke test did not return complete running-app evidence.'
        }

        $shortCommit = $commit.Substring(0, 7)
        $evidenceDirectory = Join-Path $LocalArtifacts "simulator-$shortCommit"
        New-Item -ItemType Directory -Force -Path $evidenceDirectory | Out-Null
        foreach ($remotePath in @([string]$smokeValues.SCREENSHOT, [string]$smokeValues.LOG)) {
            Assert-SafeRemoteValue -Name 'smoke evidence path' -Value $remotePath
            Invoke-Native -Command 'scp' -Arguments @("${HostAlias}:$remotePath", $evidenceDirectory)
        }

        Write-Host "Simulator smoke test passed. Evidence: $evidenceDirectory" -ForegroundColor Green
    }
    'shell' {
        Invoke-Native -Command 'ssh' -Arguments @($HostAlias)
    }
}
