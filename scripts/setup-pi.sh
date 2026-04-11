#!/usr/bin/env bash
# First-time Raspberry Pi 5 setup for Solar E-Ink Dashboard.
# Run from the repo root: bash scripts/setup-pi.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEPLOY_USER="$(whoami)"
IT8951_REF="master"  # GregDMeyer/IT8951 has no tags; pin to commit after install

# Detect system Python version (e.g. python3.13 on Trixie, python3.12 on Bookworm)
PY_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
VENV_DIR="${REPO_DIR}/.venv"

echo "=== Solar E-Ink Dashboard — Pi Setup ==="
echo "Repo directory: ${REPO_DIR}"
echo "Deploy user:    ${DEPLOY_USER}"
echo "Python version: ${PY_VERSION}"

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
# 1b. Enable hardware watchdog
# -------------------------------------------------------
if grep -q "^dtparam=watchdog=on" "$BOOT_CONFIG" 2>/dev/null; then
    echo "[OK] Hardware watchdog already enabled in ${BOOT_CONFIG}"
else
    echo "[>>] Enabling hardware watchdog in ${BOOT_CONFIG} ..."
    echo "dtparam=watchdog=on" | sudo tee -a "$BOOT_CONFIG" > /dev/null
    echo "[!!] Hardware watchdog enabled — a reboot is required to activate it."
fi

# Configure the kernel watchdog daemon to reboot after 15 seconds of
# unresponsiveness.  This is the last-resort safety net: if systemd itself
# hangs (e.g. OOM pressure freezes the system), the BCM2835 hardware
# watchdog triggers a hard reboot.
if [ -f /etc/watchdog.conf ]; then
    if ! grep -q "^watchdog-device" /etc/watchdog.conf 2>/dev/null; then
        echo "[>>] Configuring /etc/watchdog.conf ..."
        sudo apt-get install -y -qq watchdog
        sudo tee /etc/watchdog.conf > /dev/null <<'WDEOF'
watchdog-device = /dev/watchdog
watchdog-timeout = 15
max-load-1 = 24
WDEOF
        sudo systemctl enable watchdog
        echo "[OK] Hardware watchdog configured (15 s timeout)"
    else
        echo "[OK] /etc/watchdog.conf already configured"
    fi
else
    echo "[>>] Installing and configuring watchdog daemon ..."
    sudo apt-get install -y -qq watchdog
    sudo tee /etc/watchdog.conf > /dev/null <<'WDEOF'
watchdog-device = /dev/watchdog
watchdog-timeout = 15
max-load-1 = 24
WDEOF
    sudo systemctl enable watchdog
    echo "[OK] Hardware watchdog configured (15 s timeout)"
fi

# -------------------------------------------------------
# 2. Install system dependencies
# -------------------------------------------------------
echo "[>>] Installing system packages ..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    "python${PY_VERSION}" "python${PY_VERSION}-dev" "python${PY_VERSION}-venv" \
    gcc make cython3 swig \
    libblas-dev liblgpio-dev \
    libgbm1 libnss3 libxss1 libasound2

# -------------------------------------------------------
# 3. Create venv and install Python deps
# -------------------------------------------------------
echo "[>>] Creating Python ${PY_VERSION} venv ..."
"python${PY_VERSION}" -m venv "${VENV_DIR}"
PIP="${VENV_DIR}/bin/pip"
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
echo "[>>] Installing IT8951 driver from source (${IT8951_REF}) ..."
IT8951_TMP="$(mktemp -d)"
git clone --depth 1 -b "${IT8951_REF}" https://github.com/GregDMeyer/IT8951.git "${IT8951_TMP}/IT8951"
$PIP install "${IT8951_TMP}/IT8951[rpi]" -q
rm -rf "${IT8951_TMP}"

# RPi.GPIO does not support Pi 5 (RP1 chip). Replace with rpi-lgpio,
# a drop-in compatibility shim that uses lgpio under the hood.
echo "[>>] Replacing RPi.GPIO with rpi-lgpio (Pi 5 support) ..."
$PIP uninstall -y RPi.GPIO -q 2>/dev/null
$PIP install rpi-lgpio -q
echo "[OK] IT8951 installed."

# -------------------------------------------------------
# 6. Install Playwright Chromium
# -------------------------------------------------------
echo "[>>] Installing Playwright Chromium browser ..."
"${VENV_DIR}/bin/playwright" install chromium
echo "[OK] Playwright Chromium installed."

# -------------------------------------------------------
# 7. Create .env.local from template if it doesn't exist
# -------------------------------------------------------
if [ ! -f "${REPO_DIR}/.env.local" ]; then
    echo "[>>] Creating .env.local from template ..."
    cat > "${REPO_DIR}/.env.local" <<'ENVEOF'
# Solar Manager gateway address (required)
SM_LOCAL_BASE_URL=https://YOUR-GATEWAY-IP

# API key for the Solar Manager local API (required)
# Generate with: openssl rand -hex 32
# Then add the same key on the gateway web UI under API settings.
SM_LOCAL_API_KEY=

# TLS — the gateway uses a self-signed certificate.
# Disable verification (simplest):
SM_LOCAL_VERIFY_TLS=false
# Or pin the certificate fingerprint (more secure):
# SM_LOCAL_TLS_FINGERPRINT_SHA256=AA:BB:CC:...

# Display language: EN, DE, FR, IT
DASHBOARD_LANGUAGE=DE

# Timezone
TZ=Europe/Zurich

# E-paper VCOM voltage (required — read from IT8951 controller, see README)
EPAPER_VCOM=

# Optional cloud backfill
# SM_CLOUD_BACKFILL_ENABLED=true
# SM_CLOUD_EMAIL=
# SM_CLOUD_PASSWORD=
# SM_CLOUD_SMID=
ENVEOF
    echo "[OK] .env.local created — edit it with your gateway details and EPAPER_VCOM."
else
    echo "[OK] .env.local already exists, skipping."
fi

# -------------------------------------------------------
# 8. Install systemd service (templated for current user)
# -------------------------------------------------------
echo "[>>] Installing systemd service ..."
UNIT_TMP="$(mktemp)"
sed -e "s|%DEPLOY_USER%|${DEPLOY_USER}|g" \
    -e "s|%DEPLOY_DIR%|${REPO_DIR}|g" \
    "${REPO_DIR}/deploy/solar-dashboard.service" > "${UNIT_TMP}"
sudo cp "${UNIT_TMP}" /etc/systemd/system/solar-dashboard.service
rm -f "${UNIT_TMP}"
sudo systemctl daemon-reload
sudo systemctl enable solar-dashboard.service
echo "[OK] Service installed and enabled. Start with: sudo systemctl start solar-dashboard"

echo ""
echo "=== Setup complete ==="
echo "Next steps:"
echo "  1. Edit .env.local with your Solar Manager gateway address and EPAPER_VCOM"
echo "  2. Reboot if SPI was just enabled"
echo "  3. Test the display: .venv/bin/python scripts/epaper_test.py --vcom YOUR_VCOM"
echo "  4. Start the service: sudo systemctl start solar-dashboard"
