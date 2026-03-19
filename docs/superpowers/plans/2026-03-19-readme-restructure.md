# README Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure repository documentation from developer-oriented to maker-first, so a hobbyist can go from unboxing to a working solar e-paper display in 5 steps.

**Architecture:** Three-file split: `README.md` (install/use/troubleshoot for makers), `CONTRIBUTING.md` (dev workflow, tests, scenarios), `docs/architecture.md` (technical deep dive, domain rules). Content is migrated from the current README, not invented — the spec at `docs/specs/2026-03-19-readme-restructure-design.md` defines exactly what goes where.

**Tech Stack:** Markdown only. No code changes.

---

## Task 1: Create `docs/architecture.md`

Extract technical content from the current README into a standalone architecture document. This must be done first because Task 3 (README rewrite) will delete this content from README.

**Files:**
- Create: `docs/architecture.md`
- Reference: `README.md:141-277` (Architecture, Domain Rules, Hardware Target details, Status sections)

- [ ] **Step 1: Create `docs/architecture.md` with content migrated from README**

Write the file with these sections, sourced verbatim or lightly edited from the current README:

```markdown
# Architecture

Technical reference for the Solar E-Ink Dashboard. For setup and usage, see [README.md](../README.md). For development workflow, see [CONTRIBUTING.md](../CONTRIBUTING.md).

## Pipeline

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

## Key Modules

- `src/models.py` — Typed dataclasses: `SensorPoint`, `ChartBucket`, `DailySummary`, `DeviceStatus`, `DashboardData`
- `src/api_local.py` — `LocalApiClient` (HTTP), `StreamCollector` (WebSocket with auto-reconnect + exponential backoff)
- `src/storage.py` — SQLite with WAL mode for concurrent read/write
- `src/aggregator.py` — Chart bucket averaging and daily Wh summation
- `src/html_renderer.py` — Primary browser-faithful dashboard renderer
- `src/dashboard_document.py` — Standalone HTML document rendering for export (with embedded Inter font)
- `src/export_dashboard.py` — One-shot PNG export path via Playwright
- `src/renderer_png.py` — `PersistentPlaywrightRenderer` (warm Chromium) + `OneShotPlaywrightRenderer`
- `src/epaper.py` — IT8951 e-paper display driver (show, clear, sleep/wake)
- `src/production.py` — `ProductionLoop`: timer-based collect→render→display with day rollover, startup reconciliation, retention cleanup, signal handling
- `src/renderer.py` — Legacy PNG/Pillow fallback
- `src/web_preview.py` — Flask dev server (binds 127.0.0.1 only)
- `src/preview_scenarios.py` — fixed dashboard state overrides for preview/review
- `config.py` — All config from env vars, loaded from `.env.local` (git-ignored)
- `src/api_cloud.py` — optional cloud backfill for missing day history and the current-day startup gap

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
- all time conversions use `zoneinfo.ZoneInfo(config.TIMEZONE)` — never hard-coded UTC offsets; day boundaries, chart x-axis, and "today" aggregation must respect DST transitions

## Current Status

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
```

- [ ] **Step 2: Verify the file renders correctly**

Visually scan the markdown for broken fenced code blocks (the nested triple-backtick sections need care). Ensure the text diagram renders inside a code fence.

- [ ] **Step 3: Commit**

```bash
git add docs/architecture.md
git commit -m "Add docs/architecture.md with technical deep dive extracted from README"
```

---

## Task 2: Create `CONTRIBUTING.md`

Extract developer workflow content from the current README and consolidate into a contributor guide.

**Files:**
- Create: `CONTRIBUTING.md`
- Reference: `README.md:219-253` (Development section), `README.md:32-78` (Preview Modes for scenario list)

- [ ] **Step 1: Create `CONTRIBUTING.md`**

```markdown
# Contributing

Developer workflow for the Solar E-Ink Dashboard. For setup and usage, see [README.md](README.md). For architecture and domain rules, see [docs/architecture.md](docs/architecture.md).

## Dev Environment Setup

```bash
python3.12 -m venv .venv312
./.venv312/bin/pip install -r requirements.txt
./.venv312/bin/python -m playwright install chromium
```

## Running Tests

```bash
# All unit tests
./.venv312/bin/pytest -q

# Single test file
./.venv312/bin/pytest tests/test_aggregator.py -v

# Integration tests (requires real gateway on LAN)
RUN_LOCAL_SM_TESTS=1 ./.venv312/bin/pytest tests/test_local_api_integration.py -v
```

## Preview Modes

### Mock preview

```bash
./.venv312/bin/python main.py --mock --port 8090
```

Open:

- `http://127.0.0.1:8090/` for the default mock dashboard
- `http://127.0.0.1:8090/scenarios` for the full scenario + language matrix

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

Open `http://127.0.0.1:8080/`. Live mode uses your local Solar Manager gateway data via `/v2/stream`, with `/v2/point` as fallback. The browser preview auto-refreshes every 15 seconds.

### PNG export

```bash
./.venv312/bin/python main.py --mock --export-png out/dashboard.png
./.venv312/bin/python main.py --export-png out/live-dashboard.png
```

The export path renders the same HTML/CSS/SVG dashboard through Playwright and writes a PNG at `1872x1404`. Output is quantized to 16 grayscale levels for the E-Ink target.

## Regenerating README Screenshots

```bash
./.venv312/bin/python scripts/generate_readme_screenshots.py
```

## Documentation Sync

When the architecture or main screen changes, update all three:

- `README.md`
- `CLAUDE.md`
- `.ai/solar-manager-eink-dashboard-context.md`

## Useful Reference Files

- `tmp/solar-eink-dashboard-PROJECT.md` — full product spec (German)
- `tmp/Solar Manager API.pdf` — official API docs
- `.ai/solar-manager-eink-dashboard-context.md` — hard technical constraints
- `CLAUDE.md` — AI assistant guidance
```

- [ ] **Step 2: Commit**

```bash
git add CONTRIBUTING.md
git commit -m "Add CONTRIBUTING.md with developer workflow extracted from README"
```

---

## Task 3: Rewrite `README.md`

Replace the current developer-oriented README with the maker-first version defined in the spec. This is the largest task — the entire file is rewritten.

**Files:**
- Modify: `README.md` (full rewrite)
- Reference: `docs/specs/2026-03-19-readme-restructure-design.md` (the spec)
- Reference: `config.py` (for complete env var table)

- [ ] **Step 1: Write the new README.md**

The new README follows this structure. All content below is the complete file:

```markdown
# Solar E-Ink Dashboard

> A wall-mounted e-paper display for your Solar Manager — shows live energy flow, today's production vs. consumption, and 7-day history at a glance.

<!-- TODO: Replace with real hardware photo once available -->

![Mock dashboard](docs/screenshots/mock-dashboard-v4.png)
![No battery scenario](docs/screenshots/mock-dashboard-no-battery-v4.png)
![PV surplus scenario](docs/screenshots/mock-dashboard-pv-surplus-v4.png)

**What the display shows:**

- Live energy flow between solar, grid, home, and battery
- 24-hour production vs. consumption chart with peak marker
- 7-day energy history (produced and consumed in kWh)
- Multilingual: English, German, French, Italian

## What You Need

| Part | Specification |
|---|---|
| Solar Manager gateway | Any gateway exposing the local v2 API (`/v2/stream`, `/v2/point`) |
| Raspberry Pi 5B | 4 GB RAM is fine as the reference target |
| Waveshare 7.8" e-Paper HAT | IT8951 controller, 1872×1404, black/white panel with 2–16 grayscale levels |
| microSD card | SanDisk Extreme PRO 128 GB (reference card) |
| Power supply | USB-C, 5V/5A recommended for Pi 5 (5V/3A works only with reduced peripheral budget) |
| Frame / mount | Your choice — display area is 7.8" diagonal |

> **Note:** The VCOM voltage is printed on the display's FPC ribbon cable label. You'll need it during setup.

## Quick Start

### 1. Flash Raspberry Pi OS

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/) to flash Raspberry Pi OS (64-bit). Enable SSH and configure your Wi-Fi during setup.

The setup script requires `python3.12` — see `scripts/setup-pi.sh` for how it is installed on your OS version.

### 2. Clone the repo and run setup

```bash
git clone https://github.com/phaupt/solar-eink-dashboard.git
cd solar-eink-dashboard
bash scripts/setup-pi.sh
```

This installs system dependencies, creates a Python virtual environment, installs the IT8951 display driver, sets up Playwright, and registers the systemd service.

### 3. Edit `.env.local`

The setup script creates `.env.local` in the repo root. Open it and set your values:

```dotenv
SM_LOCAL_BASE_URL=https://<your-gateway-ip>
EPAPER_VCOM=<from your display FPC label, e.g. -1.48>
DASHBOARD_LANGUAGE=EN
```

Use the **Solar Manager gateway IP**, not the inverter IP. The setup script defaults language to `DE` — change to your preferred language.

### 4. Reboot, then validate the display

```bash
sudo reboot
```

After reboot, test the e-paper display:

```bash
cd solar-eink-dashboard
./.venv312/bin/python scripts/epaper_test.py --vcom <your-vcom>
```

You should see a test pattern on the display.

### 5. Start the dashboard

```bash
sudo systemctl start solar-dashboard
sudo systemctl status solar-dashboard
```

The dashboard should now be collecting data and updating the display. The service auto-starts on boot (configured by the setup script).

## How It Works

```
Solar Manager gateway → local collector → SQLite → HTML renderer → Playwright PNG → e-paper display
```

The Pi connects to the Solar Manager gateway on your LAN via WebSocket, collects live energy data, and stores it in a local SQLite database. A rendering pipeline converts the dashboard to HTML, screenshots it to a grayscale PNG via Playwright, and pushes it to the e-paper display periodically (default: every 60 seconds, configurable via `DISPLAY_UPDATE_INTERVAL`).

## Configuration

All settings are configured via environment variables in `.env.local`.

### Key settings

| Variable | Description | Default |
|---|---|---|
| `SM_LOCAL_BASE_URL` | Solar Manager gateway address | `http://192.168.1.XXX` |
| `SM_LOCAL_API_KEY` | Optional gateway API key | (empty) |
| `EPAPER_VCOM` | VCOM voltage from display FPC label (required for production) | (empty) |
| `DASHBOARD_LANGUAGE` | Display language: `EN`, `DE`, `FR`, `IT` | `EN` |
| `TZ` | Timezone | `Europe/Zurich` |
| `DISPLAY_UPDATE_INTERVAL` | E-paper refresh cadence in seconds | `60` |
| `DISPLAY_FULL_REFRESH_INTERVAL` | Full GC16 refreshes between partial updates | `1` |
| `RENDER_INTERVAL_SECONDS` | Dashboard render interval in seconds | `15` |

### TLS configuration

TLS verification is enabled by default. For gateways with self-signed certificates, choose one (in order of preference):

1. **Certificate pinning (recommended):** `SM_LOCAL_TLS_FINGERPRINT_SHA256=<sha256-fingerprint>`
2. **Custom CA bundle:** `SM_LOCAL_CA_BUNDLE=/path/to/ca.pem`
3. **Disable verification (last resort):** `SM_LOCAL_VERIFY_TLS=false`

## Cloud Backfill (optional)

The local gateway has no historical data endpoint. If you restart the Pi, the 7-day history chart will have gaps. The optional cloud backfill fills in:

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
python3.12 -m venv .venv312
./.venv312/bin/pip install -r requirements.txt
./.venv312/bin/python -m playwright install chromium

# Run with mock data
./.venv312/bin/python main.py --mock --port 8090
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
**Fix:** Check the FPC ribbon cable label on your display panel and update `EPAPER_VCOM` in `.env.local` to match (e.g. `-1.48`). Then restart:
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
**Fix:** Add certificate pinning to `.env.local`:
```bash
# Get the fingerprint from your gateway
openssl s_client -connect <gateway-ip>:443 < /dev/null 2>/dev/null \
  | openssl x509 -fingerprint -sha256 -noout
```
Then add to `.env.local`:
```dotenv
SM_LOCAL_TLS_FINGERPRINT_SHA256=<the-fingerprint>
```

## License

[MIT](LICENSE)
```

- [ ] **Step 2: Verify all internal links resolve**

Check that these paths exist:
- `docs/screenshots/mock-dashboard-v4.png`
- `docs/screenshots/mock-dashboard-no-battery-v4.png`
- `docs/screenshots/mock-dashboard-pv-surplus-v4.png`
- `CONTRIBUTING.md` (created in Task 2)
- `docs/architecture.md` (created in Task 1)
- `LICENSE`

If any screenshots are missing, regenerate them:
```bash
./.venv312/bin/python scripts/generate_readme_screenshots.py
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Rewrite README as maker-first install/use/troubleshoot guide"
```

---

## Task 4: Final verification and cleanup

- [ ] **Step 1: Verify cross-references between all three files**

Check that:
- `README.md` links to `CONTRIBUTING.md` but intentionally does not link to `docs/architecture.md` (that cross-reference is in CONTRIBUTING.md)
- `CONTRIBUTING.md` links to `README.md` and `docs/architecture.md`
- `docs/architecture.md` links to `README.md` and `CONTRIBUTING.md`

- [ ] **Step 2: Run existing tests to ensure nothing is broken**

```bash
./.venv312/bin/pytest tests/ -q
```

Expected: all tests pass (documentation changes should not affect tests, but verify).

- [ ] **Step 3: Commit any link fixes**

Only if Step 1 found broken cross-references:
```bash
git add -A
git commit -m "Fix cross-references between README, CONTRIBUTING, and architecture docs"
```

- [ ] **Step 4: Push**

```bash
git push
```

**Note:** `CLAUDE.md` is intentionally left unchanged per the spec — it already has comprehensive developer context and serves as the AI-facing doc. Do not update it as part of this restructure.
