#!/usr/bin/env bash
# First-time Raspberry Pi 5 setup for Solar E-Ink Dashboard.
# Run from the repo root: bash scripts/setup-pi.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
IT8951_COMMIT="master"  # Pin to specific commit after testing

echo "=== Solar E-Ink Dashboard — Pi Setup ==="
echo "Repo directory: ${REPO_DIR}"

# -------------------------------------------------------
# 1. Enable SPI
# -------------------------------------------------------
BOOT_CONFIG="/boot/firmware/config.txt"
if [ ! -f "$BOOT_CONFIG" ]; then
    BOOT_CONFIG="/boot/config.txt"  # older Pi OS layout
fi

if grep -q "^dtparam=spi=on" "$BOOT_CONFIG" 2>/dev/null; then
    echo "[OK] SPI already enabled in ${BOOT_CONFIG}"
else
    echo "[>>] Enabling SPI in ${BOOT_CONFIG} ..."
    echo "dtparam=spi=on" | sudo tee -a "$BOOT_CONFIG" > /dev/null
    echo "[!!] SPI enabled — a reboot is required before the display will work."
fi

# -------------------------------------------------------
# 2. Install system dependencies
# -------------------------------------------------------
echo "[>>] Installing system packages ..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3.12 python3.12-dev python3.12-venv \
    gcc make cython3 \
    libatlas-base-dev \
    libgbm1 libnss3 libxss1 libasound2

# -------------------------------------------------------
# 3. Create venv and install Python deps
# -------------------------------------------------------
echo "[>>] Creating Python 3.12 venv ..."
python3.12 -m venv "${REPO_DIR}/.venv312"
PIP="${REPO_DIR}/.venv312/bin/pip"
$PIP install --upgrade pip setuptools wheel -q

echo "[>>] Installing Python requirements ..."
$PIP install -r "${REPO_DIR}/requirements-pi.txt" -q

# -------------------------------------------------------
# 4. Install Cython in venv (needed for IT8951 build)
# -------------------------------------------------------
echo "[>>] Ensuring Cython is available in venv ..."
$PIP install cython -q

# -------------------------------------------------------
# 5. Clone and install IT8951 from source
# -------------------------------------------------------
echo "[>>] Installing IT8951 driver from source ..."
IT8951_TMP="$(mktemp -d)"
git clone --depth 1 -b "${IT8951_COMMIT}" https://github.com/GregDMeyer/IT8951.git "${IT8951_TMP}/IT8951"
$PIP install "${IT8951_TMP}/IT8951[rpi]" -q
rm -rf "${IT8951_TMP}"
echo "[OK] IT8951 installed."

# -------------------------------------------------------
# 6. Install Playwright Chromium
# -------------------------------------------------------
echo "[>>] Installing Playwright Chromium browser ..."
"${REPO_DIR}/.venv312/bin/playwright" install chromium
echo "[OK] Playwright Chromium installed."

# -------------------------------------------------------
# 7. Create .env.local from template if it doesn't exist
# -------------------------------------------------------
if [ ! -f "${REPO_DIR}/.env.local" ]; then
    echo "[>>] Creating .env.local from template ..."
    cat > "${REPO_DIR}/.env.local" <<'ENVEOF'
# Solar Manager gateway address (required for live mode)
SM_LOCAL_BASE_URL=https://YOUR-GATEWAY-IP

# Optional API key
# SM_LOCAL_API_KEY=

# TLS settings (adjust for your gateway)
# SM_LOCAL_VERIFY_TLS=false
# SM_LOCAL_CA_BUNDLE=
# SM_LOCAL_TLS_FINGERPRINT_SHA256=

# Display language: EN, DE, FR, IT
DASHBOARD_LANGUAGE=DE

# Timezone
TZ=Europe/Zurich

# Optional cloud backfill
# SM_CLOUD_BACKFILL_ENABLED=true
# SM_CLOUD_EMAIL=
# SM_CLOUD_PASSWORD=
# SM_CLOUD_SMID=
ENVEOF
    echo "[OK] .env.local created — edit it with your gateway details."
else
    echo "[OK] .env.local already exists, skipping."
fi

# -------------------------------------------------------
# 8. Install systemd service
# -------------------------------------------------------
echo "[>>] Installing systemd service ..."
sudo cp "${REPO_DIR}/deploy/solar-dashboard.service" /etc/systemd/system/solar-dashboard.service
sudo systemctl daemon-reload
sudo systemctl enable solar-dashboard.service
echo "[OK] Service installed and enabled. Start with: sudo systemctl start solar-dashboard"

echo ""
echo "=== Setup complete ==="
echo "Next steps:"
echo "  1. Edit .env.local with your Solar Manager gateway address"
echo "  2. Reboot if SPI was just enabled"
echo "  3. Test the display: .venv312/bin/python scripts/epaper_test.py --vcom YOUR_VCOM"
echo "  4. Start the service: sudo systemctl start solar-dashboard"
