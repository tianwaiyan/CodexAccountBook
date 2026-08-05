$ErrorActionPreference = "Stop"

$AppName = "CodexAccountBook"
$ShortcutName = ([char[]](0x4E2A, 0x4EBA, 0x8BB0, 0x8D26) -join '')
$ShortcutDescription = ([char[]](0x542F, 0x52A8, 0x4E2A, 0x8BB0, 0x8D26, 0x7CFB, 0x7EDF) -join '')
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BuildEnvironmentPath = Join-Path $ProjectRoot ".venv-build"
$BuildLockPath = Join-Path $ProjectRoot "requirements-build.lock.txt"
$StagingRoot = Join-Path $ProjectRoot ".package-staging"
$StagingDistPath = Join-Path $StagingRoot "dist"
$StagingWorkPath = Join-Path $StagingRoot "build"
$StagedReleasePath = Join-Path $StagingDistPath $AppName
$ReleaseParentPath = Join-Path $ProjectRoot "dist"
$ReleasePath = Join-Path $ReleaseParentPath $AppName
$PreviousReleasePath = Join-Path $ReleaseParentPath "$AppName.previous"
$LegacyBuildPath = Join-Path $ProjectRoot "build"
$LegacySpecPath = Join-Path $ProjectRoot "$AppName.spec"
$DataBackupPath = Join-Path $StagingRoot "data-backup"
$ProjectDataPath = Join-Path $ProjectRoot "data"
$VerificationScriptPath = Join-Path $ProjectRoot "verify_packaged_app.py"
Set-Location $ProjectRoot

function Remove-PathIfPresent {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

function Find-Python314 {
    $Candidates = @()
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $PythonCommand) {
        $Candidates += $PythonCommand.Source
    }
    if ($env:LOCALAPPDATA) {
        $Candidates += Join-Path $env:LOCALAPPDATA "Programs\Python\Python314\python.exe"
    }
    if ($env:ProgramFiles) {
        $Candidates += Join-Path $env:ProgramFiles "Python314\python.exe"
    }

    foreach ($Candidate in ($Candidates | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
            continue
        }

        $Version = & $Candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
        if ($LASTEXITCODE -eq 0 -and $Version.Trim() -eq "3.14") {
            return $Candidate
        }
    }

    throw "Python 3.14 was not found. Install the 64-bit Python 3.14 release and ensure python.exe is available."
}

function Stop-PackagedApplication {
    $ExpectedExecutablePath = Join-Path $ReleasePath "$AppName.exe"
    $ExpectedExecutablePath = [System.IO.Path]::GetFullPath($ExpectedExecutablePath)

    foreach ($Process in (Get-Process -Name $AppName -ErrorAction SilentlyContinue)) {
        try {
            if ([System.IO.Path]::GetFullPath($Process.Path) -eq $ExpectedExecutablePath) {
                Stop-Process -Id $Process.Id -Force
                Wait-Process -Id $Process.Id -Timeout 10 -ErrorAction SilentlyContinue
            }
        }
        catch {
            Write-Warning "Could not inspect or stop process $($Process.Id): $($_.Exception.Message)"
        }
    }
}

Write-Host "[1/7] Locating Python 3.14 and recreating the isolated build environment..."
$Python314 = Find-Python314
Write-Host "Using: $Python314"
Remove-PathIfPresent -Path $BuildEnvironmentPath
& $Python314 -m venv $BuildEnvironmentPath
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create the Python 3.14 build environment."
}
$BuildPython = Join-Path $BuildEnvironmentPath "Scripts\python.exe"

Write-Host "[2/7] Installing the locked build dependencies..."
if (-not (Test-Path -LiteralPath $BuildLockPath -PathType Leaf)) {
    throw "Missing dependency lock file: $BuildLockPath"
}
$PipIndexUrl = $env:PIP_INDEX_URL
if ([string]::IsNullOrWhiteSpace($PipIndexUrl)) {
    $PipIndexUrl = "https://pypi.tuna.tsinghua.edu.cn/simple"
}
$PipTrustedHost = ([System.Uri]$PipIndexUrl).Host
& $BuildPython -m pip install --disable-pip-version-check --index-url $PipIndexUrl --trusted-host $PipTrustedHost --requirement $BuildLockPath
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install the locked build dependencies."
}

Write-Host "[3/7] Preparing an isolated staging directory..."
Remove-PathIfPresent -Path $StagingRoot
Remove-PathIfPresent -Path $LegacyBuildPath
Remove-PathIfPresent -Path $LegacySpecPath
New-Item -ItemType Directory -Path $StagingRoot -Force | Out-Null

Write-Host "[4/7] Building the application with PyInstaller..."
& $BuildPython -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name $AppName `
    --distpath $StagingDistPath `
    --workpath $StagingWorkPath `
    --specpath $StagingRoot `
    --add-data ((Join-Path $ProjectRoot "app.py") + ";.") `
    --add-data ((Join-Path $ProjectRoot "db.py") + ";.") `
    --add-data ((Join-Path $ProjectRoot "parser.py") + ";.") `
    --add-data ((Join-Path $ProjectRoot "status_rules.py") + ";.") `
    --add-data ((Join-Path $ProjectRoot "local_transaction_editor.py") + ";.") `
    --add-data ((Join-Path $ProjectRoot "components") + ";components") `
    --hidden-import db `
    --hidden-import parser `
    --hidden-import status_rules `
    --hidden-import local_transaction_editor `
    --copy-metadata streamlit `
    --copy-metadata pandas `
    --copy-metadata plotly `
    --copy-metadata matplotlib `
    --copy-metadata altair `
    --copy-metadata pyarrow `
    --collect-all streamlit `
    --collect-data matplotlib `
    (Join-Path $ProjectRoot "launcher.py")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed. The existing packaged application was not changed."
}

Write-Host "[5/7] Verifying bundled files and starting an isolated Streamlit session..."
$StagedExecutablePath = Join-Path $StagedReleasePath "$AppName.exe"
$InternalPath = Join-Path $StagedReleasePath "_internal"
$RequiredBundledFiles = @(
    $StagedExecutablePath,
    (Join-Path $InternalPath "app.py"),
    (Join-Path $InternalPath "db.py"),
    (Join-Path $InternalPath "parser.py"),
    (Join-Path $InternalPath "status_rules.py"),
    (Join-Path $InternalPath "local_transaction_editor.py"),
    (Join-Path $InternalPath "streamlit\static\index.html")
)
foreach ($RequiredBundledFile in $RequiredBundledFiles) {
    if (-not (Test-Path -LiteralPath $RequiredBundledFile -PathType Leaf)) {
        throw "Packaged application is incomplete: $RequiredBundledFile"
    }
}
& $BuildPython -I $VerificationScriptPath $InternalPath
if ($LASTEXITCODE -ne 0) {
    throw "The packaged Streamlit session test failed. The existing packaged application was not changed."
}
Remove-PathIfPresent -Path (Join-Path $InternalPath "data")

Write-Host "[6/7] Preserving ledger data and replacing the verified release..."
Stop-PackagedApplication
New-Item -ItemType Directory -Path $DataBackupPath -Force | Out-Null
$ReleaseDataPath = Join-Path $ReleasePath "data"
if (Test-Path -LiteralPath $ReleaseDataPath -PathType Container) {
    Copy-Item -Path (Join-Path $ReleaseDataPath "*") -Destination $DataBackupPath -Recurse -Force
}
elseif (Test-Path -LiteralPath $ProjectDataPath -PathType Container) {
    Copy-Item -Path (Join-Path $ProjectDataPath "*") -Destination $DataBackupPath -Recurse -Force
}

$BackupDatabasePath = Join-Path $DataBackupPath "account_book.db"
if (Test-Path -LiteralPath $BackupDatabasePath -PathType Leaf) {
    $DatabaseCheck = & $BuildPython -c "import sqlite3, sys; connection = sqlite3.connect(sys.argv[1]); print(connection.execute('PRAGMA quick_check').fetchone()[0]); connection.close()" $BackupDatabasePath
    if ($LASTEXITCODE -ne 0 -or $DatabaseCheck.Trim() -ne "ok") {
        throw "The preserved ledger database did not pass SQLite integrity verification. The existing release was not replaced."
    }

    $StagedDataPath = Join-Path $StagedReleasePath "data"
    New-Item -ItemType Directory -Path $StagedDataPath -Force | Out-Null
    Copy-Item -Path (Join-Path $DataBackupPath "*") -Destination $StagedDataPath -Recurse -Force
}

New-Item -ItemType Directory -Path $ReleaseParentPath -Force | Out-Null
Remove-PathIfPresent -Path $PreviousReleasePath
$PreviousReleaseWasMoved = $false
$ReleaseWasSyncedInPlace = $false
try {
    if (Test-Path -LiteralPath $ReleasePath) {
        try {
            Move-Item -LiteralPath $ReleasePath -Destination $PreviousReleasePath -ErrorAction Stop
            $PreviousReleaseWasMoved = $true
        }
        catch {
            Write-Warning "The release directory is locked. Synchronizing the verified release in place."
            & robocopy.exe $StagedReleasePath $ReleasePath /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS /NP
            if ($LASTEXITCODE -gt 7) {
                throw "Could not synchronize the verified release. Robocopy exit code: $LASTEXITCODE"
            }
            $ReleaseWasSyncedInPlace = $true
        }
    }
    if (-not $ReleaseWasSyncedInPlace) {
        Move-Item -LiteralPath $StagedReleasePath -Destination $ReleasePath
    }
}
catch {
    if ($PreviousReleaseWasMoved -and -not (Test-Path -LiteralPath $ReleasePath)) {
        Move-Item -LiteralPath $PreviousReleasePath -Destination $ReleasePath
    }
    throw
}

Write-Host "[7/7] Creating the desktop shortcut and cleaning temporary output..."
$ExecutablePath = Join-Path $ReleasePath "$AppName.exe"
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopPath "$ShortcutName.lnk"
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $ExecutablePath
$Shortcut.WorkingDirectory = $ReleasePath
$Shortcut.Description = $ShortcutDescription
$Shortcut.IconLocation = "$ExecutablePath,0"
$Shortcut.Save()

Remove-PathIfPresent -Path $PreviousReleasePath
Remove-PathIfPresent -Path $StagingRoot
Remove-PathIfPresent -Path $LegacyBuildPath
Remove-PathIfPresent -Path $LegacySpecPath

Write-Host "Build completed:"
Write-Host "  Python: $(& $BuildPython --version)"
Write-Host "  Executable: $ExecutablePath"
Write-Host "  Shortcut: $ShortcutPath"
Write-Host "  Ledger data: preserved in $ReleasePath\data"