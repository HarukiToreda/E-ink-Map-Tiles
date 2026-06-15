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
  & $VenvPython -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --console `
    --name EinkMapTiles `
    --paths src `
    --add-data "docs;docs" `
    scripts\eink_map_tiles_app.py

  Write-Host ""
  Write-Host "Built:"
  Write-Host (Join-Path $RepoRoot "dist\EinkMapTiles.exe")
} finally {
  Pop-Location
}
