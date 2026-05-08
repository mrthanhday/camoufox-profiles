#!/usr/bin/env bash
# Bootstrap dev environment for camoufox-profiles (Linux/macOS).
#
# The camoufox fork depends on a dev build of Playwright built from source.
# Its setup.py uses curl to download the driver binary, which can fail due
# to SSL issues.  This script pre-installs a stable Playwright wheel first.

set -euo pipefail

PW_VERSION="${1:-1.52.0}"

echo "=== camoufox-profiles dev setup ==="

echo ""
echo "[1/3] Pre-installing Playwright ${PW_VERSION} (stable wheel)..."
pip install "playwright==${PW_VERSION}" --quiet

echo "[2/3] Installing camoufox-profiles in editable mode with [dev] extras..."
pip install -e ".[dev]"

echo "[3/3] Installing Playwright browser binaries..."
python -m playwright install || echo "WARNING: browser install failed, retry with: python -m playwright install"

echo ""
echo "=== Setup complete ==="
echo "Run tests with: pytest"
