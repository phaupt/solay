# Solar E-Ink Dashboard

A Raspberry Pi wall dashboard for Solar Manager with a Figma-aligned HTML/CSS/SVG preview, local SQLite history, and a layout optimized for a high-resolution grayscale E-Ink display.

## Screenshots

![Mock dashboard](docs/screenshots/mock-dashboard-v4.png)
![No battery scenario](docs/screenshots/mock-dashboard-no-battery-v4.png)
![PV surplus scenario](docs/screenshots/mock-dashboard-pv-surplus-v4.png)

## Current Scope

The current main dashboard contains:

- live flow panel with `Solar`, `Grid`, `Home`, and `Battery`
- straight live-flow paths with centered double arrowheads on active connections
- current-day 24h chart for production vs. consumption
- peak production marker line aligned to the displayed production curve
- 7-day history strip with `produced` and `consumed`
- mock preview, state/scenario previews, and live preview from a real Solar Manager gateway
- HTML-to-PNG export path for the E-Ink target
- production mode with persistent Playwright renderer and IT8951 e-paper display driver
- optional cloud backfill for missing previous days and the current-day startup gap
- configurable dashboard language: `EN`, `DE`, `FR`, `IT`

Not on the current main screen:

- extra KPI cards for import/export/self-consumption/autarky
- device list
- PV performance block

## Preview Modes

### Mock preview

```bash
./.venv312/bin/python main.py --mock --port 8090
```

Open:

- `http://127.0.0.1:8090/` for the default mock dashboard
- `http://127.0.0.1:8090/scenarios` for common fixed preview states

Supported scenario URLs:

- `/?scenario=pv_surplus`
- `/?scenario=pv_deficit`
- `/?scenario=night`
- `/?scenario=battery_support`
- `/?scenario=grid_charge`
- `/?scenario=no_battery`
- `/?scenario=stale`

These scenario previews keep the same 24h chart context, including the peak-production marker.

### Live preview

```bash
./.venv312/bin/python main.py --port 8080
```

Open:

- `http://127.0.0.1:8080/`

Live mode uses your local Solar Manager gateway data via `/v2/stream`, with `/v2/point` as fallback.
The browser preview auto-refreshes every 15 seconds.

### PNG export

```bash
./.venv312/bin/python main.py --mock --export-png out/dashboard.png
./.venv312/bin/python main.py --export-png out/live-dashboard.png
```

The export path renders the same HTML/CSS/SVG dashboard through Playwright and writes a PNG at `1872x1404`.
By default, the output is quantized to 16 grayscale levels for the E-Ink target.

### Production mode (Raspberry Pi)

```bash
# Full production loop: collect → render → e-paper display
./.venv312/bin/python main.py --production

# Headless (render loop without e-paper hardware, for testing)
./.venv312/bin/python main.py --production --no-display
```

Production mode runs a timer-based loop that collects data, renders the dashboard via a persistent Playwright instance, and pushes the grayscale PNG to the IT8951 e-paper display. Includes day-rollover detection with re-aggregation, startup reconciliation for yesterday's summary, hourly retention cleanup, and graceful shutdown on SIGTERM/SIGINT.

Requires `EPAPER_VCOM` in `.env.local` (check the FPC cable label on the display panel).

## Local Configuration

Create a local `.env.local` in the repo root. This file stays out of git.

Example:

```dotenv
SM_LOCAL_BASE_URL=https://192.168.1.95
SM_LOCAL_API_KEY=your-local-api-key
SM_LOCAL_VERIFY_TLS=false
DASHBOARD_LANGUAGE=EN
SM_CLOUD_BACKFILL_ENABLED=false
TZ=Europe/Zurich
WEB_HOST=127.0.0.1
WEB_PORT=8080
```

Important:

- use the Solar Manager gateway IP, not the inverter IP
- prefer `https`
- TLS verification is enabled by default; for gateways with self-signed certs, prefer one of:
  - `SM_LOCAL_TLS_FINGERPRINT_SHA256=...` (recommended — pin to the gateway cert)
  - `SM_LOCAL_CA_BUNDLE=/path/to/ca.pem` (if you have a local CA)
  - `SM_LOCAL_VERIFY_TLS=false` (last resort — disables all TLS checks)
- `DASHBOARD_LANGUAGE` supports `EN` (default), `DE`, `FR`, `IT`

### Optional cloud backfill

The local gateway API has no historical backfill endpoint.
If you want missing daily history after a restart, configure the optional cloud backfill:

```dotenv
SM_CLOUD_BACKFILL_ENABLED=true
SM_CLOUD_EMAIL=you@example.com
SM_CLOUD_PASSWORD=your-password
SM_CLOUD_SMID=your-smid
SM_CLOUD_BACKFILL_DAYS=7
SM_CLOUD_BACKFILL_INTERVAL_SECONDS=300
```

Current behavior:

- previous full days are backfilled into `daily_summary`
- the current-day gap before the first local sample is backfilled into `raw_points`
- this avoids double counting once the local stream is running

## Architecture

The current architecture is:

```text
Solar Manager Gateway
  ├── /v2/stream  (primary live source)
  └── /v2/point   (fallback snapshot)
          ↓
src/api_local.py
          ↓
src/storage.py      SQLite WAL
          ↓
src/aggregator.py   chart buckets + daily summaries
          ↓
src/models.py       DashboardData
          ↓
src/html_renderer.py
          ↓
┌─────────┼──────────────────┐
│         │                  │
web_preview.py  renderer_png.py    export_dashboard.py
(Flask dev)     (Playwright PNG)   (one-shot export)
                     ↓
                epaper.py (IT8951)
                     ↓
                production.py (timer loop)
```

Notes:

- the HTML/CSS/SVG renderer is the primary visual path
- `src/renderer.py` still exists as a legacy PNG/Pillow fallback via `/dashboard.png`
- mock mode and live mode use separate SQLite databases
- the optional cloud backfill uses `/v1/statistics/gateways/{smId}` and `/v3/users/{smId}/data/range`
- active live-flow paths currently use straight 45°/orthogonal lines with centered double arrowheads

## Domain Rules

- local `Wh` values are interval values, not daily totals
- daily totals must be summed from all interval `Wh` samples
- `/v2/stream` is the correct primary source for intraday charting
- battery-aware grid power is:

```text
grid_w = c_w + bc_w - p_w - bd_w
```

Semantics:

- positive `grid_w` = import / Bezug
- negative `grid_w` = export / Einspeisung
- the 7-day history strip shows daily **energy**, so the correct unit is `kWh`, not `kW`
- EV/car `soc` must not be mistaken for a home battery SOC in the live battery node

## Hardware Target

Reference target:

- Raspberry Pi 5B
- Waveshare 7.8" e-Paper HAT with IT8951 controller
- resolution target: `1872x1404`

The full pipeline is implemented: collect → persist → aggregate → render (HTML/CSS/SVG) → screenshot (Playwright) → quantize (16 grayscale) → display (IT8951 GC16).

### Pi deployment

```bash
# First-time setup (SPI, venv, IT8951, Playwright, systemd)
bash scripts/setup-pi.sh

# Hardware validation
./.venv312/bin/python scripts/epaper_test.py --vcom -1.48

# Start production service
sudo systemctl start solar-dashboard
```

## Development

Setup (dev machine):

```bash
python3.12 -m venv .venv312
./.venv312/bin/pip install -r requirements.txt
./.venv312/bin/python -m playwright install chromium
```

Setup (Raspberry Pi):

```bash
bash scripts/setup-pi.sh
```

Tests:

```bash
./.venv312/bin/pytest -q
RUN_LOCAL_SM_TESTS=1 ./.venv312/bin/pytest tests/test_local_api_integration.py -v
```

Regenerate README screenshots:

```bash
./.venv312/bin/python scripts/generate_readme_screenshots.py
```

Useful local files:

- `tmp/solar-eink-dashboard-PROJECT.md`
- `tmp/Solar Manager API.pdf`
- `.ai/solar-manager-eink-dashboard-context.md`
- `CLAUDE.md`

## Status

What is already working:

- mock dashboard preview
- live preview with real gateway data
- scenario previews for common flow states
- correct local persistence and current-day aggregation
- Figma-aligned HTML/CSS/SVG renderer
- peak-production marker in the 24h chart aligned to the visible production curve
- PNG export from the HTML renderer
- persistent Playwright renderer with warm Chromium for production use
- IT8951 e-paper display driver with GC16 full refresh
- production loop with day rollover, startup reconciliation, retention cleanup, signal handling
- bundled Inter font for cross-platform rendering consistency
- deployment assets: systemd unit, setup script, hardware bring-up script
- optional i18n for `EN`, `DE`, `FR`, `IT`
- optional cloud backfill for missing daily history and the current-day startup gap

What is still open:

- partial refresh strategy (DU mode) — needs real-panel testing before enabling
- long-running thermal/memory validation on Pi 5
