# Solar Manager E-Paper Dashboard for Raspberry Pi

> Wall-mounted Solar Manager dashboard for Waveshare e-paper on Raspberry Pi. Shows live energy flow, today's production vs. consumption, and 7-day history at a glance.

<p align="center">
  <img src="docs/screenshots/hero-product-photo.png" alt="Solar E-Ink Dashboard on a Waveshare 7.8 inch e-paper display in a wooden frame" width="720">
</p>

**20-second overview:** This project turns a Raspberry Pi 5 and a Waveshare 7.8" e-paper display into a quiet, always-on Solar Manager dashboard. It connects to the local Solar Manager v2 API, stores live data in SQLite, and refreshes a high-resolution grayscale display every 15 seconds by default.

**Who this is for:** Solar Manager users who want a dedicated home energy dashboard instead of keeping a tablet or phone mounted on the wall.

**What the display shows:**

- Live energy flow between solar, grid, home, and battery
- 24-hour production vs. consumption chart with peak marker
- 7-day energy history (produced and consumed in kWh)
- Multilingual: English, German, French, Italian

<table>
  <tr>
    <td align="center"><strong>Standard</strong></td>
    <td align="center"><strong>No Battery</strong></td>
    <td align="center"><strong>PV Surplus</strong></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/mock-dashboard-v4.png" alt="Standard dashboard with battery" width="280"></td>
    <td><img src="docs/screenshots/mock-dashboard-no-battery-v4.png" alt="Dashboard without battery" width="280"></td>
    <td><img src="docs/screenshots/mock-dashboard-pv-surplus-v4.png" alt="Dashboard with PV surplus and grid export" width="280"></td>
  </tr>
</table>

## What You Need

| Part | Specification |
|---|---|
| Solar Manager gateway | Any gateway exposing the local v2 API (`/v2/stream`, `/v2/point`) |
| Raspberry Pi 5B | 4 GB RAM is fine as the reference target |
| Waveshare 7.8" e-Paper HAT | IT8951 controller, 1872×1404, black/white panel with 2-16 grayscale levels |
| microSD card | SanDisk Extreme PRO 128 GB (reference card) |
| Power supply | USB-C, 5V/5A recommended for Pi 5 (5V/3A works only with reduced peripheral budget) |
| Frame / mount | Your choice, display area is 7.8" diagonal |

## Quick Start

### 1. Flash Raspberry Pi OS

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/) to flash **Raspberry Pi OS Lite (64-bit)**. Enable SSH and configure your Wi-Fi during setup.

The setup script auto-detects the system Python version.

### 2. Clone the repo and run setup

```bash
git clone https://github.com/phaupt/solay.git ~/solay
cd ~/solay
bash scripts/setup-pi.sh
```

This installs system dependencies, creates a Python virtual environment (`.venv`), builds the IT8951 display driver with Pi 5 GPIO support (`rpi-lgpio`), installs Playwright Chromium, and registers the systemd service.

### 3. Generate an API key for the Solar Manager gateway

The Solar Manager local API requires an API key for authentication. Generate a random 256-bit hex key:

```bash
openssl rand -hex 32
```

Copy the output (e.g. `a1b2c3d4...64 hex characters`). Then add this same key in two places:

1. **On the Solar Manager gateway:** Open the gateway web UI at `https://<gateway-ip>`, navigate to the API settings, and add the key
2. **On the Pi:** Set it in `.env.local` (next step)

### 4. Edit `.env.local`

The setup script creates `.env.local` in the repo root. Open it and set your values:

```dotenv
SM_LOCAL_BASE_URL=https://<your-gateway-ip>
SM_LOCAL_API_KEY=<your-256-bit-hex-key>
SM_LOCAL_VERIFY_TLS=false
EPAPER_VCOM=<your-vcom, e.g. -1.50>
DASHBOARD_LANGUAGE=DE
```

- Use the **Solar Manager gateway IP**, not the inverter IP
- `SM_LOCAL_VERIFY_TLS=false` is needed because the gateway uses a self-signed TLS certificate (see [TLS configuration](#tls-configuration) for more secure alternatives)
- The setup script defaults language to `DE`; change to `EN`, `FR`, or `IT` as needed

#### Finding the VCOM voltage

The VCOM voltage is specific to your display panel. Look for a small sticker on the FPC connector or on the back of the glass panel showing a value like `-1.48` or `-2.06`. If you cannot find the label, read it from the IT8951 controller after setup:

```bash
cd ~/solay
sudo .venv/bin/python -c "
from IT8951.interface import EPD
epd = EPD(vcom=-1.5)
print('VCOM:', epd.get_vcom())
"
```

### 5. Reboot, then validate the display

```bash
sudo reboot
```

A reboot is required after first setup because SPI gets enabled by the setup script.

After reboot, test the e-paper display:

```bash
cd ~/solay
sudo .venv/bin/python scripts/epaper_test.py --vcom <your-vcom>
```

You should see a test pattern on the display.

### 6. Start the dashboard

```bash
sudo systemctl start solar-dashboard
sudo systemctl status solar-dashboard
```

The dashboard should now be collecting data and updating the display. The service auto-starts on boot (configured by the setup script).

> **Note:** The 24-hour chart and 7-day history build up over time from locally collected data. After a fresh install, expect the chart to fill in over the next hours and the history over the next days. To backfill historical data immediately, see [Cloud Backfill](#cloud-backfill-optional).

## How It Works

```
Solar Manager gateway → local collector → SQLite → HTML renderer → Playwright PNG → e-paper display
```

The Pi connects to the Solar Manager gateway on your LAN via WebSocket, collects live energy data, and stores it in a local SQLite database. A rendering pipeline converts the dashboard to HTML, screenshots it to a grayscale PNG via Playwright, and pushes it to the e-paper display periodically (default: every 15 seconds, configurable via `DISPLAY_UPDATE_INTERVAL`).

## Configuration

All settings are configured via environment variables in `.env.local`.

### Key settings

| Variable | Description | Default |
|---|---|---|
| `SM_LOCAL_BASE_URL` | Solar Manager gateway address (required) | `http://192.168.1.XXX` |
| `SM_LOCAL_API_KEY` | Gateway API key (required) — see [step 3](#3-generate-an-api-key-for-the-solar-manager-gateway) | (empty) |
| `EPAPER_VCOM` | VCOM voltage (required for production) — see [finding the VCOM](#finding-the-vcom-voltage) | (empty) |
| `DASHBOARD_LANGUAGE` | Display language: `EN`, `DE`, `FR`, `IT` | `EN` |
| `TZ` | Timezone | `Europe/Zurich` |
| `DISPLAY_UPDATE_INTERVAL` | E-paper refresh cadence in seconds | `15` |
| `DISPLAY_FULL_REFRESH_INTERVAL` | Full GC16 refresh (brief black flash) every N updates; GL16 is used in between for flicker-free updates. At 15s update interval, 240 = once per hour | `240` |

### TLS configuration

The Solar Manager gateway uses a self-signed TLS certificate. The setup script defaults to `SM_LOCAL_VERIFY_TLS=false` in `.env.local`.

For additional security, pin the gateway's certificate fingerprint (the fingerprint is stable across certificate renewals on the same key pair):

```dotenv
SM_LOCAL_VERIFY_TLS=false
SM_LOCAL_TLS_FINGERPRINT_SHA256=AA:BB:CC:...
```

Both settings are needed: `VERIFY_TLS=false` disables chain validation (which fails on self-signed certs), while the fingerprint ensures the Pi only talks to your specific gateway.

To get the fingerprint:
```bash
openssl s_client -connect <gateway-ip>:443 < /dev/null 2>/dev/null \
  | openssl x509 -fingerprint -sha256 -noout
```

Other options (if your gateway has a proper CA-signed certificate):
1. **Custom CA bundle:** `SM_LOCAL_CA_BUNDLE=/path/to/ca.pem`
2. **Full verification (default):** remove `SM_LOCAL_VERIFY_TLS=false`

## Cloud Backfill (optional)

The local gateway has no historical data endpoint. The dashboard still works without cloud backfill, but after a restart or fresh install the 7-day history will only show data collected locally on this Pi. Optional cloud backfill uses your Solar Manager cloud account to fill in:

- **Previous days:** missing daily summaries from before the restart
- **Today's gap:** the period between midnight and whenever the Pi first started collecting

To enable it, add to `.env.local`:

```dotenv
SM_CLOUD_BACKFILL_ENABLED=true
SM_CLOUD_EMAIL=you@example.com
SM_CLOUD_PASSWORD=your-password
SM_CLOUD_SMID=your-smid
SM_CLOUD_BACKFILL_DAYS=7
SM_CLOUD_BACKFILL_INTERVAL_SECONDS=300
```

## Development

For local development without hardware:

```bash
# Setup (dev machine)
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python -m playwright install chromium

# Run with mock data
./.venv/bin/python main.py --mock --port 8090
```

Open `http://127.0.0.1:8090/` for the mock dashboard or `http://127.0.0.1:8090/scenarios` for the scenario matrix.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full developer workflow, testing, and preview modes.

## Troubleshooting

### Display not detected after setup

**Symptom:** `epaper_test.py` fails with a device error.
**Cause:** SPI was just enabled and needs a reboot.
**Fix:**
```bash
sudo reboot
```

### Garbled or faint display

**Symptom:** Display shows noise or very faint image.
**Cause:** Wrong VCOM voltage.
**Fix:** Read the correct VCOM from the IT8951 controller (see [finding the VCOM](#finding-the-vcom-voltage)) and update `EPAPER_VCOM` in `.env.local`. Then restart:
```bash
sudo systemctl restart solar-dashboard
```

### Gateway not found

**Symptom:** Dashboard shows no data or connection errors in logs.
**Cause:** Wrong IP address, firewall blocking, or using the inverter IP instead of the gateway IP.
**Fix:**
1. Verify the IP is your **Solar Manager gateway**, not the inverter
2. Test connectivity: `curl -k https://<your-gateway-ip>/v2/point`
3. Update `SM_LOCAL_BASE_URL` in `.env.local`

### Dashboard not updating

**Symptom:** Display is stuck on an old image.
**Cause:** Service may have stopped or crashed.
**Fix:**
```bash
sudo systemctl status solar-dashboard
sudo journalctl -u solar-dashboard -f
```

### TLS certificate errors

**Symptom:** Connection refused or SSL errors in logs.
**Cause:** Gateway uses a self-signed certificate.
**Fix:** Ensure `.env.local` has `SM_LOCAL_VERIFY_TLS=false`. For additional security, also add fingerprint pinning — see [TLS configuration](#tls-configuration).

## License

[PolyForm Noncommercial 1.0.0](LICENSE). Free for personal, educational, and noncommercial use.
