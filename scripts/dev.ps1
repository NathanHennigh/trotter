param(
    [switch]$NoNgrok,
    [switch]$WithCelery,
    [switch]$NoExpo,
    [switch]$ExpoOffline,
    [switch]$SkipMigrate,
    [int]$BackendPort = 8000
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Backend = Join-Path $Root "backend"
$MobileV2 = Join-Path $Root "mobile-v2"
$Python = Join-Path $Backend ".venv\Scripts\python.exe"
$NgrokLocal = Join-Path $Backend "ngrok.exe"

function Write-Step($Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-Command($Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-PortListening($Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Test-ProcessCommandLine($Pattern) {
    return [bool](
        Get-CimInstance Win32_Process |
            Where-Object { $_.CommandLine -and $_.CommandLine -match $Pattern } |
            Select-Object -First 1
    )
}

function Write-Skip($Message) {
    Write-Host "    $Message" -ForegroundColor DarkGray
}

function Assert-DockerReady {
    $output = & docker version 2>&1
    if ($LASTEXITCODE -ne 0) {
        $message = @"
Docker CLI is installed, but Docker Desktop's Linux engine is not reachable.

Try this:
  1. Open Docker Desktop.
  2. Wait until it says the engine is running.
  3. In a new PowerShell window, run: docker version
  4. Re-run: .\scripts\dev.ps1

If Docker Desktop is already open, use Docker Desktop > Troubleshoot > Restart.

Docker said:
$($output -join [Environment]::NewLine)
"@
        throw $message
    }
}

function Start-DevWindow($Title, $WorkingDirectory, $Command) {
    $encodedTitle = $Title.Replace("'", "''")
    $encodedWorkingDirectory = $WorkingDirectory.Replace("'", "''")
    $script = @"
`$Host.UI.RawUI.WindowTitle = '$encodedTitle'
Set-Location -LiteralPath '$encodedWorkingDirectory'
if (Test-Path '.env') {
    Get-Content '.env' | ForEach-Object {
        `$line = `$_.Trim()
        if (-not `$line -or `$line.StartsWith('#') -or `$line -notmatch '=') { return }
        `$key, `$value = `$line.Split('=', 2)
        if (`$key) {
            [Environment]::SetEnvironmentVariable(`$key.Trim(), `$value.Trim().Trim('"').Trim("'"), 'Process')
        }
    }
}
$Command
Write-Host ''
Write-Host 'Process exited. Press any key to close this window...'
`$null = `$Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
"@
    $encodedScript = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
    Start-Process powershell.exe -WindowStyle Normal -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        $encodedScript
    )
}

function Wait-ForContainerHealth($ContainerName, $TimeoutSeconds = 90) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $status = docker inspect --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" $ContainerName 2>$null
        if ($status -eq "healthy" -or $status -eq "running") {
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "Timed out waiting for $ContainerName to become healthy."
}

Write-Step "Checking prerequisites"
if (-not (Test-Command "docker")) {
    throw "Docker CLI was not found. Open Docker Desktop and try again."
}
if (-not (Test-Path $Python)) {
    throw "Backend venv Python not found at $Python."
}
if (-not (Test-Path $MobileV2)) {
    throw "mobile-v2 folder not found."
}

Assert-DockerReady

$dockerServices = @("db")
if ($WithCelery) {
    $dockerServices += "redis"
}

Write-Step "Starting Docker services: $($dockerServices -join ', ')"
& docker compose -f (Join-Path $Root "docker-compose.yml") up -d @dockerServices
Wait-ForContainerHealth "trotter-db"
if ($WithCelery) {
    Wait-ForContainerHealth "trotter-redis"
}

if (-not $SkipMigrate) {
    Write-Step "Applying backend migrations"
    Push-Location $Backend
    try {
        & $Python -m alembic upgrade head
    } finally {
        Pop-Location
    }
}

Write-Step "Starting FastAPI backend on port $BackendPort"
if (Test-PortListening $BackendPort) {
    Write-Skip "Backend port $BackendPort is already listening; skipping backend launch."
} else {
    $backendCommand = ".\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port $BackendPort"
    Start-DevWindow "Trotter Backend :$BackendPort" $Backend $backendCommand
}

if ($WithCelery) {
    Write-Step "Starting Celery worker"
    if (Test-ProcessCommandLine "celery.*app\.celery_app\.celery_app.*worker") {
        Write-Skip "Celery worker already appears to be running; skipping Celery launch."
    } else {
        $celeryCommand = ".\.venv\Scripts\python.exe -m celery -A app.celery_app.celery_app worker --loglevel=info --pool=solo"
        Start-DevWindow "Trotter Celery Worker" $Backend $celeryCommand
    }
}

if (-not $NoNgrok) {
    Write-Step "Starting ngrok tunnel for backend"
    if (Test-ProcessCommandLine "ngrok(\.exe)?.*http\s+$BackendPort") {
        Write-Skip "ngrok already appears to be tunneling port $BackendPort; skipping ngrok launch."
    } else {
        if (Test-Command "ngrok") {
            $ngrokCommand = "ngrok http $BackendPort"
        } elseif (Test-Path $NgrokLocal) {
            $ngrokCommand = ".\ngrok.exe http $BackendPort"
        } else {
            Write-Warning "ngrok was not found on PATH or at backend\ngrok.exe. Skipping ngrok."
            $ngrokCommand = $null
        }
        if ($ngrokCommand) {
            Start-DevWindow "Trotter ngrok :$BackendPort" $Backend $ngrokCommand
        }
    }
}

if (-not $NoExpo) {
    Write-Step "Starting Expo dev client with cleared cache"
    if (Test-ProcessCommandLine "expo(\.cmd)?\s+start.*--dev-client|node.*expo.*start.*--dev-client") {
        Write-Skip "Expo dev client already appears to be running; skipping Expo launch."
    } else {
        $expoCommand = if ($ExpoOffline) {
            "`$env:EXPO_OFFLINE='1'; npx expo start --dev-client --clear"
        } else {
            "npx expo start --dev-client --clear"
        }
        Start-DevWindow "Trotter Expo Dev Client" $MobileV2 $expoCommand
    }
}

Write-Host ""
Write-Host "Trotter dev services are starting." -ForegroundColor Green
Write-Host "Backend: http://localhost:$BackendPort"
Write-Host "Expo: npx expo start --dev-client --clear"
Write-Host "Docker: docker compose ps"
Write-Host ""
Write-Host "Useful switches:"
Write-Host "  .\scripts\dev.ps1 -NoNgrok"
Write-Host "  .\scripts\dev.ps1 -SkipMigrate"
Write-Host "  .\scripts\dev.ps1 -ExpoOffline"
Write-Host "  .\scripts\dev.ps1 -WithCelery"
