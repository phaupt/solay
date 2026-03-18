# Solar E-Ink Dashboard

A wall-mounted E-Ink display for [Solar Manager](https://www.solarmanager.ch/) that shows live solar production, consumption, battery state, and historical charts — powered by a Raspberry Pi.

## What You Get

- Live power values (PV, consumption, grid, battery)
- 24h chart of today's production and consumption
- Daily totals with self-consumption rate and autarky degree
- 30-day PV performance overview
- Device status (Wattpilot, boiler, etc.)
- Optimized for 16-level grayscale E-Ink displays

## Hardware

| Component | Example | Notes |
|-----------|---------|-------|
| Raspberry Pi | Pi 4 or Pi 5 (2 GB+) | Any model with network access works |
| E-Ink display | Waveshare 7.8" (1872x1404) | Connected via USB/SPI, 16 grayscale levels |
| Solar Manager gateway | Any Solar Manager installation | Must be reachable on the local network |
| Power supply | Official Pi PSU | USB-C for Pi 4/5 |
| Case / frame | Picture frame or 3D-printed | Optional, for wall mounting |

The display resolution is configured for 1872x1404. If you use a different display, adjust `DISPLAY_WIDTH` and `DISPLAY_HEIGHT` in your `.env.local`.

## Prerequisites

- Python 3.9 or newer (3.11+ recommended for HTTPS gateways)
- The Solar Manager gateway must be accessible on your LAN
- You need the gateway's local IP address (e.g. `http://192.168.1.100`)
- Optional: a local API key if your gateway requires one

## Setup

### 1. Clone and install

```bash
git clone https://github.com/<your-user>/solar-eink-dashboard.git
cd solar-eink-dashboard
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

### 2. Configure

Create a `.env.local` file in the project root (this file is git-ignored):

```bash
# Required: your Solar Manager gateway IP
SM_LOCAL_BASE_URL=http://192.168.1.100

# Optional: API key if your gateway requires one
SM_LOCAL_API_KEY=your-key-here

# Optional: timezone (default: Europe/Zurich)
TZ=Europe/Zurich
```

See [Configuration Reference](#configuration-reference) below for all options.

### 3. Test with mock data

Before connecting to real hardware, verify everything works:

```bash
./venv/bin/python main.py --mock
```

Open http://127.0.0.1:8080 in your browser. You should see a dashboard with simulated data. Mock mode uses a separate database and never touches your live data.

### 4. Run live

```bash
./venv/bin/python main.py
```

The app connects to your gateway's WebSocket stream, collects data every ~10 seconds, and renders the dashboard. Open http://127.0.0.1:8080 to see the live preview.

If the WebSocket stream is temporarily unavailable, the app automatically falls back to HTTP polling until the stream reconnects.

### 5. Run on boot (Raspberry Pi)

Create a systemd service to start the dashboard automatically:

```bash
sudo nano /etc/systemd/system/solar-dashboard.service
```

```ini
[Unit]
Description=Solar E-Ink Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/solar-eink-dashboard
ExecStart=/home/pi/solar-eink-dashboard/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable solar-dashboard
sudo systemctl start solar-dashboard
```

## HTTPS Options for the Local Gateway

Some Solar Manager gateways expose HTTPS with a self-signed certificate. Three modes are supported:

**1. No verification (simplest, local network only)**
```
SM_LOCAL_VERIFY_TLS=false
```

**2. Certificate fingerprint pinning (recommended)**
```
SM_LOCAL_VERIFY_TLS=false
SM_LOCAL_TLS_FINGERPRINT_SHA256=AA:BB:CC:...
```

**3. Custom CA bundle**
```
SM_LOCAL_VERIFY_TLS=true
SM_LOCAL_CA_BUNDLE=/path/to/ca.pem
```

For most home-network setups, fingerprint pinning is the most practical secure option.

## Configuration Reference

All settings via environment variables or `.env.local`:

| Variable | Default | Description |
|----------|---------|-------------|
| `SM_LOCAL_BASE_URL` | — | Gateway address (required) |
| `SM_LOCAL_API_KEY` | — | API key for the gateway |
| `SM_LOCAL_VERIFY_TLS` | `false` | Enable TLS certificate verification |
| `SM_LOCAL_CA_BUNDLE` | — | Path to custom CA bundle |
| `SM_LOCAL_TLS_FINGERPRINT_SHA256` | — | Pin gateway certificate by SHA-256 fingerprint |
| `TZ` | `Europe/Zurich` | Timezone for day boundaries and display |
| `DB_PATH` | `solar_dashboard.db` | SQLite database path |
| `MOCK_DB_PATH` | `solar_dashboard_mock.db` | Separate database for mock mode |
| `RAW_RETENTION_DAYS` | `7` | Auto-delete raw data older than N days |
| `DISPLAY_WIDTH` | `1872` | Display width in pixels |
| `DISPLAY_HEIGHT` | `1404` | Display height in pixels |
| `WEB_HOST` | `127.0.0.1` | Web preview bind address |
| `WEB_PORT` | `8080` | Web preview port |
| `POLL_INTERVAL_SECONDS` | `10` | Fallback polling interval |
| `RENDER_INTERVAL_SECONDS` | `30` | Dashboard re-render interval |

## Development

```bash
# Run all tests
./venv/bin/pytest tests/ -v

# Run a single test file
./venv/bin/pytest tests/test_aggregator.py -v

# Run integration tests (requires real gateway on LAN)
RUN_LOCAL_SM_TESTS=1 ./venv/bin/pytest tests/test_local_api_integration.py -v
```

## License

See [LICENSE](LICENSE).
