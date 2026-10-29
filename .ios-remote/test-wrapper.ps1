$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Load only pure guard functions, never the wrapper's action dispatch or SSH.
$tokens = $null
$parseErrors = $null
$wrapper = Join-Path $PSScriptRoot 'trotter-ios.ps1'
$ast = [Management.Automation.Language.Parser]::ParseFile($wrapper, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
foreach ($name in @('Assert-BranchIsPushed', 'Get-LocalCommit', 'Assert-SafeRemoteValue')) {
    $definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    if (-not $definition) { throw "Missing wrapper guard $name" }
    . ([scriptblock]::Create($definition.Extent.Text))
}

$Branch = 'codex/test-ios'
$script:LocalBranch = $Branch
$script:LocalStatus = ''
$script:LocalCommit = 'a' * 40
$script:RemoteCommit = $script:LocalCommit
function Get-GitOutput {
    param([string[]]$Arguments)
    switch ($Arguments -join ' ') {
        'branch --show-current' { return $script:LocalBranch }
        'status --porcelain --untracked-files=all' { return $script:LocalStatus }
        'rev-parse HEAD' { return $script:LocalCommit }
        "ls-remote --heads origin refs/heads/$Branch" {
            if ($script:RemoteCommit) { return "$($script:RemoteCommit)`trefs/heads/$Branch" }
            return ''
        }
        default { throw "Unexpected Git request: $Arguments" }
    }
}
function Assert-Throws {
    param([scriptblock]$Run, [string]$Pattern)
    try { & $Run | Out-Null } catch {
        if ($_.Exception.Message -notmatch $Pattern) { throw }
        return
    }
    throw "Expected rejection matching $Pattern"
}

if ((Assert-BranchIsPushed -RequireClean) -ne $script:LocalCommit) { throw 'Exact pushed SHA was not preserved.' }
$script:LocalStatus = '?? mobile-v2/native-ios/Uncommitted.swift'
Assert-Throws { Assert-BranchIsPushed -RequireClean } 'not clean'
$script:LocalStatus = ''
$script:RemoteCommit = 'b' * 40
Assert-Throws { Assert-BranchIsPushed -RequireClean } 'not the pushed'
$script:RemoteCommit = ''
Assert-Throws { Assert-BranchIsPushed -RequireClean } 'does not exist'
$script:RemoteCommit = $script:LocalCommit
$script:LocalBranch = 'some-other-branch'
Assert-Throws { Assert-BranchIsPushed -RequireClean } 'Configured branch'
foreach ($unsafe in @('path with spaces', 'x;id', '$(id)', 'x`id', "x`ny", '')) {
    Assert-Throws { Assert-SafeRemoteValue -Name test -Value $unsafe } 'unsupported characters'
}
Assert-SafeRemoteValue -Name test -Value '~/Developer/trotter-build'
Write-Output 'Wrapper syntax and release guards passed; no network or filesystem changes performed.'
