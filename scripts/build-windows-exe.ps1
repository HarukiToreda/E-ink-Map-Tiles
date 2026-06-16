$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BuildVenv = Join-Path $RepoRoot ".build-venv"
$Python = Get-Command python -ErrorAction SilentlyContinue
$PyLauncher = Get-Command py -ErrorAction SilentlyContinue

Push-Location $RepoRoot
try {
  if ($Python) {
    python -m venv $BuildVenv
  } elseif ($PyLauncher) {
    py -3 -m venv $BuildVenv
  } else {
    throw "Python was not found on PATH."
  }

  $VenvPython = Join-Path $BuildVenv "Scripts\python.exe"
  if (-not (Test-Path -LiteralPath $VenvPython)) {
    throw "Failed to create build venv at $BuildVenv"
  }

  & $VenvPython -m pip install --upgrade pip
  & $VenvPython -m pip install -e . pyinstaller
  $ExePath = Join-Path $RepoRoot "dist\EinkMapTiles.exe"
  $RunningExe = Get-Process EinkMapTiles -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $ExePath }
  if ($RunningExe) {
    throw "Close EinkMapTiles.exe before rebuilding: $ExePath"
  }

  & $VenvPython -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name EinkMapTiles `
    --paths src `
    scripts\eink_map_tiles_app.py
  if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
  }

  foreach ($NoticeFile in @("README.md", "LICENSE", "NOTICE.md", "CHANGELOG.md")) {
    $SourcePath = Join-Path $RepoRoot $NoticeFile
    if (Test-Path -LiteralPath $SourcePath) {
      Copy-Item -LiteralPath $SourcePath -Destination (Join-Path (Join-Path $RepoRoot "dist") $NoticeFile) -Force
    }
  }

  Write-Host ""
  Write-Host "Built:"
  Write-Host $ExePath
} finally {
  Pop-Location
}
