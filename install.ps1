# PowerShell: .\install.ps1   (same as: python scripts/install.py)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
& python (Join-Path $PSScriptRoot "scripts\install.py") @args
exit $LASTEXITCODE
