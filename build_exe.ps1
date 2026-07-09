$ErrorActionPreference = "Stop"

$AppName = "CodexAccountBook"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

Write-Host "[1/3] Installing Python dependencies..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Write-Host "[2/3] Cleaning previous build output..."
if (Test-Path "build") { Remove-Item "build" -Recurse -Force }
if (Test-Path "dist") { Remove-Item "dist" -Recurse -Force }
if (Test-Path "$AppName.spec") { Remove-Item "$AppName.spec" -Force }

Write-Host "[3/3] Building Windows executable..."
python -m PyInstaller `
  --noconfirm `
  --clean `
  --onedir `
  --windowed `
  --name "$AppName" `
  --add-data "app.py;." `
  --add-data "db.py;." `
  --add-data "parser.py;." `
  --copy-metadata streamlit `
  --copy-metadata pandas `
  --copy-metadata plotly `
  --copy-metadata altair `
  --copy-metadata pyarrow `
  launcher.py

Write-Host ""
Write-Host "Build completed. You can run:"
Write-Host "dist\$AppName\$AppName.exe"
