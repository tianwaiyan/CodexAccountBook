$ErrorActionPreference = "Stop"

$AppName = "CodexAccountBook"
$ShortcutName = ([char[]](0x4E2A, 0x4EBA, 0x8BB0, 0x8D26) -join '')
$ShortcutDescription = ([char[]](0x542F, 0x52A8, 0x4E2A, 0x4EBA, 0x8BB0, 0x8D26, 0x7CFB, 0x7EDF) -join '')
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

Write-Host "[1/4] Installing Python dependencies..."
$PythonLauncher = (Get-Command py -ErrorAction Stop).Source
& $PythonLauncher -3 -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
  throw "Python dependency installation failed with exit code $LASTEXITCODE."
}

Write-Host "[2/4] Cleaning previous build output..."
if (Test-Path "build") { Remove-Item "build" -Recurse -Force }
if (Test-Path "dist") { Remove-Item "dist" -Recurse -Force }
if (Test-Path "$AppName.spec") { Remove-Item "$AppName.spec" -Force }

Write-Host "[3/4] Building Windows executable..."
& $PythonLauncher -3 -m PyInstaller `
  --noconfirm `
  --clean `
  --onedir `
  --windowed `
  --name "$AppName" `
  --add-data "app.py;." `
  --add-data "db.py;." `
  --add-data "parser.py;." `
  --add-data "status_rules.py;." `
  --add-data "local_transaction_editor.py;." `
  --add-data "components;components" `
  --copy-metadata streamlit `
  --copy-metadata pandas `
  --copy-metadata plotly `
  --copy-metadata matplotlib `
  --copy-metadata altair `
  --copy-metadata pyarrow `
  --collect-all streamlit `
  --collect-data matplotlib `
  launcher.py
if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller failed with exit code $LASTEXITCODE."
}

Write-Host ""
$ExecutablePath = Join-Path $ProjectRoot "dist\$AppName\$AppName.exe"
if (-not (Test-Path -LiteralPath $ExecutablePath)) {
  throw "Build finished without producing the expected executable: $ExecutablePath"
}

$InternalPath = Join-Path (Split-Path -Parent $ExecutablePath) "_internal"
$RequiredBundledFiles = @(
  "app.py",
  "db.py",
  "parser.py",
  "status_rules.py",
  "local_transaction_editor.py",
  "streamlit\static\index.html"
)
foreach ($RelativePath in $RequiredBundledFiles) {
  $BundledPath = Join-Path $InternalPath $RelativePath
  if (-not (Test-Path -LiteralPath $BundledPath)) {
    throw "Build is missing a required runtime file: $BundledPath"
  }
}

$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopPath "$ShortcutName.lnk"

Write-Host "[4/4] Creating desktop shortcut..."
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $ExecutablePath
$Shortcut.WorkingDirectory = Split-Path -Parent $ExecutablePath
$Shortcut.Description = $ShortcutDescription
$Shortcut.Save()

Write-Host ""
Write-Host "Build completed. Double-click the desktop shortcut: $ShortcutName"
Write-Host "The executable is located at: $ExecutablePath"
