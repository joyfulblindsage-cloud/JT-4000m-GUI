[CmdletBinding()]
param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot

$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw "Python 3.10+ and the Windows Python launcher (py.exe) are required."
    }
    py -3 -m venv .venv
}
if (-not (Test-Path $Python)) {
    throw "Could not create .venv. Install Python 3.10+ and retry."
}

& $Python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
& $Python -m pip install -e ".[build]"
if ($LASTEXITCODE -ne 0) { throw "Installing build dependencies failed." }

if (-not $SkipTests) {
    & $Python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Tests failed; refusing to build." }
}

& $Python -m PyInstaller --noconfirm --clean JT4000M-Studio.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

$Exe = Join-Path $PSScriptRoot "dist\JT4000M-Studio\JT4000M-Studio.exe"
if (-not (Test-Path $Exe)) {
    throw "Build completed without the expected executable: $Exe"
}
Write-Host ""
Write-Host "Build succeeded: $Exe" -ForegroundColor Green
Write-Host "Copy the entire dist\JT4000M-Studio folder, not just the .exe."
