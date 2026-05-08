<#
.SYNOPSIS
    Bootstrap dev environment for camoufox-profiles on Windows.
.DESCRIPTION
    The camoufox fork depends on a dev build of Playwright that is built
    from source.  Its setup.py uses curl to download the driver binary,
    which frequently fails on Windows due to schannel SSL/TLS errors.

    This script works around the issue by pre-installing a stable
    Playwright wheel (which ships pre-built) before running the full
    editable install.
#>

param(
    [switch]$SkipPlaywright,
    [string]$PlaywrightVersion = "1.52.0"
)

$ErrorActionPreference = "Stop"

Write-Host "=== camoufox-profiles dev setup ===" -ForegroundColor Cyan

# Step 1: Pre-install stable Playwright wheel to cache the driver binary
if (-not $SkipPlaywright) {
    Write-Host "`n[1/3] Pre-installing Playwright $PlaywrightVersion (stable wheel)..." -ForegroundColor Yellow
    pip install "playwright==$PlaywrightVersion" --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Failed to install Playwright stable. Check your network." -ForegroundColor Red
        exit 1
    }
    Write-Host "      Playwright $PlaywrightVersion installed." -ForegroundColor Green
} else {
    Write-Host "`n[1/3] Skipping Playwright pre-install (--SkipPlaywright)." -ForegroundColor DarkGray
}

# Step 2: Editable install with dev extras
Write-Host "`n[2/3] Installing camoufox-profiles in editable mode with [dev] extras..." -ForegroundColor Yellow
pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: pip install -e '.[dev]' failed." -ForegroundColor Red
    exit 1
}
Write-Host "      camoufox-profiles installed." -ForegroundColor Green

# Step 3: Install Playwright browsers (if not already present)
Write-Host "`n[3/3] Installing Playwright browser binaries..." -ForegroundColor Yellow
python -m playwright install
if ($LASTEXITCODE -ne 0) {
    Write-Host "WARNING: Playwright browser install failed. You can retry with: python -m playwright install" -ForegroundColor DarkYellow
} else {
    Write-Host "      Browsers installed." -ForegroundColor Green
}

Write-Host "`n=== Setup complete ===" -ForegroundColor Cyan
Write-Host "Run tests with: pytest" -ForegroundColor DarkGray
