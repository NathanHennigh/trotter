param(
    [switch]$NoNgrok,
    [switch]$WithCelery,
    [switch]$NoExpo,
    [switch]$ExpoOffline,
    [switch]$InstallAndroid,
    [switch]$SkipInstall,
    [switch]$SkipMigrate,
    [int]$BackendPort = 8000,
    [int]$ExpoPort = 8083
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

function Add-PathDirectory($Directory) {
    if ((Test-Path $Directory) -and (($env:Path -split ";") -notcontains $Directory)) {
        $env:Path = "$Directory;$env:Path"
    }
}

function Initialize-WindowsTooling {
    $dockerBin = "C:\Program Files\Docker\Docker\resources\bin"
    $androidSdk = if ($env:ANDROID_HOME) {
        $env:ANDROID_HOME
    } else {
        Join-Path $env:LOCALAPPDATA "Android\Sdk"
    }
    $androidStudioJdk = "C:\Program Files\Android\Android Studio\jbr"

    Add-PathDirectory $dockerBin

    if (Test-Path $androidSdk) {
        $env:ANDROID_HOME = $androidSdk
        $env:ANDROID_SDK_ROOT = $androidSdk
        Add-PathDirectory (Join-Path $androidSdk "platform-tools")
    }

    if (-not $env:JAVA_HOME -and (Test-Path (Join-Path $androidStudioJdk "bin\java.exe"))) {
        $env:JAVA_HOME = $androidStudioJdk
    }
    if ($env:JAVA_HOME) {
        Add-PathDirectory (Join-Path $env:JAVA_HOME "bin")
    }
}

function Assert-LastCommandSucceeded($Message) {
    if ($LASTEXITCODE -ne 0) {
        throw $Message
    }
}

function Test-PortListening($Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Test-TrotterBackend($Port) {
    try {
        $response = Invoke-RestMethod -Uri "http://localhost:$Port/health" -TimeoutSec 3
        return $null -ne $response
    } catch {
        return $false
    }
}

function Get-PortOwnerDescription($Port) {
    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $connection) {
        return "unknown process"
    }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($connection.OwningProcess)" -ErrorAction SilentlyContinue
    if (-not $process) {
        return "PID $($connection.OwningProcess)"
    }
    return "$($process.Name) (PID $($process.ProcessId)): $($process.CommandLine)"
}

function Assert-PortAvailable($Port, $ServiceName) {
    if (Test-PortListening $Port) {
        $portOwner = Get-PortOwnerDescription $Port
        throw @"
$ServiceName port $Port is already in use:
  $portOwner

Choose another port, for example:
  .\scripts\dev.ps1 -ExpoPort 8084
"@
    }
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

function Get-LanIPv4Address {
    return Get-NetIPConfiguration |
        Where-Object { $_.IPv4DefaultGateway -and $_.IPv4Address } |
        ForEach-Object { $_.IPv4Address.IPAddress } |
        Select-Object -First 1
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

function Get-ConnectedAndroidDevice {
    if (-not (Test-Command "adb")) {
        throw @"
Android Debug Bridge (adb) was not found.

Install Android Studio and its Android SDK Platform-Tools, then re-run this script.
"@
    }

    $deviceLines = & adb devices -l |
        Select-Object -Skip 1 |
        Where-Object { $_ -match "^\S+\s+device(?:\s|$)" -and $_ -notmatch "^emulator-" }
    $unauthorized = & adb devices -l |
        Select-Object -Skip 1 |
        Where-Object { $_ -match "^\S+\s+unauthorized(?:\s|$)" }
    $offline = & adb devices -l |
        Select-Object -Skip 1 |
        Where-Object { $_ -match "^\S+\s+offline(?:\s|$)" }

    if ($unauthorized) {
        throw "Your phone is connected but unauthorized. Unlock it, accept the USB debugging prompt, and try again."
    }
    if ($offline) {
        throw @"
Your phone is connected but ADB reports it as offline.

Unlock the phone, unplug and reconnect USB, choose File transfer, and accept the USB debugging prompt.
If it stays offline, revoke USB debugging authorizations in Developer options and reconnect.
"@
    }
    if (-not $deviceLines) {
        throw @"
No physical Android phone is connected.

On the phone:
  1. Enable Developer options by tapping Build number seven times.
  2. Enable USB debugging.
  3. Connect USB and choose File transfer if prompted.
  4. Accept the computer authorization prompt.
  5. Verify with: adb devices

The phone must appear with the status "device".
"@
    }

    $deviceLine = $deviceLines | Select-Object -First 1
    $serial = ($deviceLine -split "\s+")[0]
    $modelMatch = [regex]::Match($deviceLine, "(?:^|\s)model:(\S+)")
    $expoName = if ($modelMatch.Success) {
        $modelMatch.Groups[1].Value
    } else {
        "Device $serial"
    }

    return [PSCustomObject]@{
        Serial = $serial
        ExpoName = $expoName
    }
}

Initialize-WindowsTooling

Write-Step "Checking prerequisites"
if (-not (Test-Command "docker")) {
    throw "Docker CLI was not found. Install Docker Desktop, then open a new PowerShell window."
}
if (-not (Test-Path $MobileV2)) {
    throw "mobile-v2 folder not found."
}
if (-not (Test-Command "node") -or -not (Test-Command "npm")) {
    throw "Node.js and npm are required but were not found."
}

Assert-DockerReady

if (-not $SkipInstall) {
    if (-not (Test-Path $Python)) {
        if (-not (Test-Command "python")) {
            throw "Python 3.11 or newer is required but was not found."
        }
        Write-Step "Creating backend virtual environment"
        & python -m venv (Join-Path $Backend ".venv")
        Assert-LastCommandSucceeded "Could not create the backend virtual environment."
    }

    Write-Step "Installing backend dependencies"
    & $Python -m pip install --disable-pip-version-check -e $Backend
    Assert-LastCommandSucceeded "Backend dependency installation failed."

    if (-not (Test-Path (Join-Path $MobileV2 "node_modules"))) {
        Write-Step "Installing mobile dependencies"
        Push-Location $MobileV2
        try {
            & npm ci
            Assert-LastCommandSucceeded "Mobile dependency installation failed."
        } finally {
            Pop-Location
        }
    }
} elseif (-not (Test-Path $Python)) {
    throw "Backend venv Python not found at $Python. Re-run without -SkipInstall to create it."
}

if ($InstallAndroid -and $NoExpo) {
    throw "-InstallAndroid cannot be combined with -NoExpo."
}
$androidDevice = if ($InstallAndroid) {
    Get-ConnectedAndroidDevice
} else {
    $null
}

$dockerServices = @("db")
if ($WithCelery) {
    $dockerServices += "redis"
}

Write-Step "Starting Docker services: $($dockerServices -join ', ')"
& docker compose -f (Join-Path $Root "docker-compose.yml") up -d @dockerServices
Assert-LastCommandSucceeded "Docker services failed to start."
Wait-ForContainerHealth "trotter-db"
if ($WithCelery) {
    Wait-ForContainerHealth "trotter-redis"
}

if (-not $SkipMigrate) {
    Write-Step "Applying backend migrations"
    Push-Location $Backend
    try {
        & $Python -m alembic upgrade head
        Assert-LastCommandSucceeded "Backend migrations failed."
    } finally {
        Pop-Location
    }
}

Write-Step "Starting FastAPI backend on port $BackendPort"
if (Test-PortListening $BackendPort) {
    if (Test-TrotterBackend $BackendPort) {
        Write-Skip "Trotter backend is already listening on port $BackendPort; skipping backend launch."
    } else {
        $portOwner = Get-PortOwnerDescription $BackendPort
        throw @"
Port $BackendPort is already in use by another process:
  $portOwner

Stop that process or choose another port, for example:
  .\scripts\dev.ps1 -BackendPort 8001
"@
    }
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

if ($InstallAndroid) {
    Write-Step "Building and installing Trotter on Android device $($androidDevice.ExpoName) ($($androidDevice.Serial))"
    Assert-PortAvailable $ExpoPort "Expo"
    Push-Location $MobileV2
    try {
        & npx expo run:android --device $androidDevice.ExpoName --port $ExpoPort
        Assert-LastCommandSucceeded "The Android build or installation failed."
    } finally {
        Pop-Location
    }
} elseif (-not $NoExpo) {
    Write-Step "Starting Trotter Expo dev client on port $ExpoPort with cleared cache"
    Assert-PortAvailable $ExpoPort "Expo"
    $expoCommand = if ($ExpoOffline) {
        "`$env:EXPO_OFFLINE='1'; npx expo start --dev-client --clear --port $ExpoPort"
    } else {
        "npx expo start --dev-client --clear --port $ExpoPort"
    }
    Start-DevWindow "Trotter Expo Dev Client :$ExpoPort" $MobileV2 $expoCommand
}

Write-Host ""
Write-Host "Trotter dev services are starting." -ForegroundColor Green
Write-Host "Backend: http://localhost:$BackendPort"
Write-Host "Expo: npx expo start --dev-client --clear --port $ExpoPort"
$lanAddress = Get-LanIPv4Address
if ($lanAddress) {
    Write-Host "Phone/Expo LAN address: http://${lanAddress}:$ExpoPort"
}
Write-Host "Docker: docker compose ps"
Write-Host ""
Write-Host "Useful switches:"
Write-Host "  .\scripts\dev.ps1 -NoNgrok"
Write-Host "  .\scripts\dev.ps1 -SkipMigrate"
Write-Host "  .\scripts\dev.ps1 -ExpoOffline"
Write-Host "  .\scripts\dev.ps1 -WithCelery"
Write-Host "  .\scripts\dev.ps1 -InstallAndroid"
Write-Host "  .\scripts\dev.ps1 -SkipInstall"
Write-Host "  .\scripts\dev.ps1 -ExpoPort 8084"
