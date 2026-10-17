$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DesktopRoot = Join-Path $RepoRoot "src"
$WebRoot = Join-Path $RepoRoot "webui"
$Ui = "tkinter"
$WebHost = "127.0.0.1"
$WebPortText = "8765"
$OpenBrowser = $true
$AllowRemote = $false
$WebOptionUsed = $false
$UnknownArguments = [System.Collections.Generic.List[string]]::new()

function Show-Usage {
  @"
Usage: .\scripts\eink-map-tiles.ps1 [--ui=tkinter|web] [options]

Interfaces:
  --ui=tkinter          Start the original Python/Tk application (default)
  --ui=web              Start the browser application with Node.js and Vite

Web options:
  --host HOST           Bind address (default: 127.0.0.1)
  --port PORT           Preferred port (default: 8765)
  --no-open             Do not open the browser automatically
  --allow-remote        Permit a non-loopback bind address

General options:
  -h, --help            Show this help
"@ | Write-Output
}

function Stop-WithError {
  param(
    [Parameter(Mandatory = $true)][string]$Message,
    [int]$ExitCode = 2
  )

  [Console]::Error.WriteLine("eink-map-tiles: $Message")
  exit $ExitCode
}

function Invoke-Native {
  param(
    [Parameter(Mandatory = $true)][string]$Command,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
  )

  & $Command @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "Command failed with exit code ${LASTEXITCODE}: $Command $($Arguments -join ' ')"
  }
}

$Index = 0
while ($Index -lt $args.Count) {
  $Argument = [string]$args[$Index]
  if ($Argument -eq "--ui" -or $Argument -eq "--host" -or $Argument -eq "--port") {
    if ($Index + 1 -ge $args.Count -or [string]::IsNullOrWhiteSpace([string]$args[$Index + 1])) {
      Stop-WithError "$Argument requires a value"
    }
    $Value = [string]$args[$Index + 1]
    $Index += 2
    switch ($Argument) {
      "--ui" { $Ui = $Value }
      "--host" { $WebHost = $Value; $WebOptionUsed = $true }
      "--port" { $WebPortText = $Value; $WebOptionUsed = $true }
    }
    continue
  }

  if ($Argument.StartsWith("--ui=")) {
    $Ui = $Argument.Substring(5)
  } elseif ($Argument.StartsWith("--host=")) {
    $WebHost = $Argument.Substring(7)
    if ([string]::IsNullOrWhiteSpace($WebHost)) { Stop-WithError "--host requires a value" }
    $WebOptionUsed = $true
  } elseif ($Argument.StartsWith("--port=")) {
    $WebPortText = $Argument.Substring(7)
    if ([string]::IsNullOrWhiteSpace($WebPortText)) { Stop-WithError "--port requires a value" }
    $WebOptionUsed = $true
  } elseif ($Argument -eq "--no-open") {
    $OpenBrowser = $false
    $WebOptionUsed = $true
  } elseif ($Argument -eq "--allow-remote") {
    $AllowRemote = $true
    $WebOptionUsed = $true
  } elseif ($Argument -eq "-h" -or $Argument -eq "--help") {
    Show-Usage
    exit 0
  } else {
    $UnknownArguments.Add($Argument)
  }
  $Index += 1
}

if ($Ui -ne "tkinter" -and $Ui -ne "web") {
  Stop-WithError "--ui must be 'tkinter' or 'web'"
}
if ($UnknownArguments.Count -gt 0) {
  Stop-WithError "unrecognized arguments: $($UnknownArguments -join ' ')"
}

$WebPort = 0
if (-not [int]::TryParse($WebPortText, [ref]$WebPort) -or $WebPort -lt 1 -or $WebPort -gt 65535) {
  Stop-WithError "--port must be an integer from 1 through 65535"
}

if ($Ui -eq "tkinter") {
  if ($WebOptionUsed) {
    Stop-WithError "--host, --port, --no-open, and --allow-remote require --ui=web"
  }

  $DesktopEntry = Join-Path $DesktopRoot "eink_map_tiles\desktop_app.py"
  if (-not (Test-Path -LiteralPath $DesktopEntry -PathType Leaf)) {
    Stop-WithError "desktop application source is missing from `"$DesktopRoot`"" 1
  }

  $PythonArguments = [System.Collections.Generic.List[string]]::new()
  $VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
  if (Test-Path -LiteralPath $VenvPython -PathType Leaf) {
    $PythonCommand = $VenvPython
  } elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCommand = "python"
  } elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCommand = "py"
    $PythonArguments.Add("-3")
  } else {
    Stop-WithError "Python 3 was not found" 1
  }

  if ([string]::IsNullOrEmpty($env:PYTHONPATH)) {
    $env:PYTHONPATH = $DesktopRoot
  } else {
    $env:PYTHONPATH = "$DesktopRoot$([IO.Path]::PathSeparator)$($env:PYTHONPATH)"
  }
  $PythonArguments.Add("-m")
  $PythonArguments.Add("eink_map_tiles.desktop_app")
  & $PythonCommand @PythonArguments
  exit $LASTEXITCODE
}

$LoopbackHosts = @("127.0.0.1", "localhost", "::1", "[::1]")
if ($WebHost -notin $LoopbackHosts -and -not $AllowRemote) {
  Stop-WithError "non-loopback binding requires --allow-remote"
}

if (-not (Get-Command node -ErrorAction SilentlyContinue) -or -not (Get-Command npm -ErrorAction SilentlyContinue)) {
  Stop-WithError "Node.js 22 or newer and npm are required for --ui=web" 1
}

$NodeMajorText = & node --eval 'process.stdout.write(process.versions.node.split(".")[0])'
$NodeMajor = 0
if (-not [int]::TryParse($NodeMajorText, [ref]$NodeMajor) -or $NodeMajor -lt 22) {
  $NodeVersion = & node --version
  Stop-WithError "Node.js 22 or newer is required (found $NodeVersion)" 1
}

$NodeModules = Join-Path $WebRoot "node_modules"
$ViteEntry = Join-Path $NodeModules "vite\bin\vite.js"
if (-not (Test-Path -LiteralPath $NodeModules -PathType Container)) {
  Write-Host "E-ink Map Tiles: installing Web UI dependencies with npm ci..."
  Invoke-Native "npm" "--prefix" $WebRoot "ci"
}
if (-not (Test-Path -LiteralPath $ViteEntry -PathType Leaf)) {
  Stop-WithError "Web UI dependencies are incomplete. Remove `"$NodeModules`" and launch Web mode again" 1
}

Invoke-Native "npm" "--prefix" $WebRoot "run" "build"
$ViteArguments = [System.Collections.Generic.List[string]]::new()
$ViteArguments.Add("preview")
$ViteArguments.Add($WebRoot)
$ViteArguments.Add("--host")
$ViteArguments.Add($WebHost)
$ViteArguments.Add("--port")
$ViteArguments.Add($WebPort.ToString())
if ($OpenBrowser) { $ViteArguments.Add("--open") }
& node $ViteEntry @ViteArguments
exit $LASTEXITCODE
