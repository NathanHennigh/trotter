$RootScript = Resolve-Path (Join-Path $PSScriptRoot "..\..\scripts\dev.ps1")
& $RootScript @args
