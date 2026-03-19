# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Solar Manager E-Ink Dashboard for Raspberry Pi. Collects real-time solar energy data from a local Solar Manager gateway via WebSocket stream, persists it in SQLite, aggregates correctly, and renders the main dashboard primarily through HTML/CSS/SVG for a Figma-aligned browser preview.

## Key Documentation

Before making architectural or data-model changes, read:

- `.ai/solar-manager-eink-dashboard-context.md` — hard technical constraints, API details, architectural bias
- `tmp/solar-eink-dashboard-PROJECT.md` — full product spec (German), acceptance criteria, known prototype errors
- `tmp/Solar Manager API.pdf` — official API docs

Treat the current code as a prototype that may contain wrong assumptions.

## Commands

```bash
# Setup (dev machine)
python3.12 -m venv .venv312 && ./.venv312/bin/pip install -r requirements.txt

# Setup (Raspberry Pi — installs IT8951, Playwright, systemd service)
bash scripts/setup-pi.sh

# Run with mock data
./.venv312/bin/python main.py --mock --port 8090

# Run live (requires SM_LOCAL_BASE_URL in .env.local)
./.venv312/bin/python main.py --port 8080

# Production mode (collect → render → e-ink display loop)
./.venv312/bin/python main.py --production

# Production headless (render loop without e-paper hardware)
./.venv312/bin/python main.py --production --no-display

# Preview scenarios
open http://127.0.0.1:8090/scenarios

# Run all unit tests
./.venv312/bin/pytest tests/ -v

# Run a single test file
./.venv312/bin/pytest tests/test_aggregator.py -v

# Run integration tests (requires real gateway on LAN)
RUN_LOCAL_SM_TESTS=1 ./.venv312/bin/pytest tests/test_local_api_integration.py -v

# Hardware bring-up (IT8951 validation on Pi)
./.venv312/bin/python scripts/epaper_test.py --vcom YOUR_VCOM
```

## Architecture

**Pipeline:** Collect → Persist → Aggregate → Render

```
Solar Manager Gateway (LAN)
  ├── /v2/stream (WebSocket) → primary real-time data source
  └── /v2/point (HTTP GET)   → fallback snapshot
                ↓
  api_local.py (LocalApiClient + StreamCollector)
                ↓
  storage.py (SQLite WAL: raw_points + daily_summary)
                ↓
  aggregator.py (5-min chart buckets, daily Wh summation)
                ↓
  html_renderer.py (primary HTML/CSS/SVG renderer)
                ↓
  ┌─────────────┼─────────────────┐
  │             │                 │
  web_preview.py    renderer_png.py    export_dashboard.py
  (Flask dev)       (Playwright PNG)   (one-shot export)
                        ↓
                    epaper.py (IT8951 display driver)
                        ↓
                    production.py (timer loop, day rollover, signal handling)

Optional legacy fallback:
  renderer.py (Pillow PNG fallback via /dashboard.png)
```

**Key modules:**
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

## Critical Domain Rules

- **Data correctness over UI polish.** Wh values are per-interval (~10s), not instantaneous. Daily totals = SUM of all interval Wh values. Never derive daily totals from sparse polling.
- **Battery-aware grid power:** `grid_w = c_w + bc_w - p_w - bd_w` (positive = import, negative = export)
- **`/v2/stream` is the primary data source** for intraday history. `/v2/point` is an active fallback — when the stream drops, the collector polls `/v2/point` until the stream reconnects.
- **Timezone handling:** All time conversions use `zoneinfo.ZoneInfo(config.TIMEZONE)`. Never use hard-coded UTC offsets. Day boundaries, chart x-axis, and "today" aggregation must respect DST transitions.
- **`soc=0` is a valid value** (empty battery). Only `soc is None` means "no battery present".
- **Current main screen:** live flow + 24h chart + 7-day history. No device list, no PV-performance block, no extra KPI-card section.
- **The 24h chart includes a peak-production guide derived from the real max production of the current day.**
- **The peak-production guide must align to the displayed production curve, not a detached raw spike above it.**
- **7-day history is energy history, so it must use `kWh`, not `kW`.**
- **Car/EV SOC must not be treated as home battery SOC.**
- **The 7-day history must always show 7 columns with today on the far right; missing days render as `0.0`.**
- **Localized weekday labels must stay short enough to avoid wrapping in `EN`, `DE`, `FR`, and `IT`.**
- **For stale data, prefer a quiet stale marker in the update line over redundant warning text inside the flow panel.**
- **Active live-flow paths currently use straight connections with centered double arrowheads. Do not revert to curved paths or marker-end arrows unless explicitly asked.**
- **README screenshots should be generated from the native export path (`1872x1404`), not from a smaller viewport screenshot, otherwise the layout looks incorrectly scaled down.**
- **E-Ink constraints:** 16 grayscale levels, no color, optimize for readability at distance.
- **Security by design:** No secrets in source, `.env.local` for credentials, dev server on localhost only, no Flask debug mode.
- **Docs sync matters:** When the architecture or main screen changes, update `README.md`, `.ai/solar-manager-eink-dashboard-context.md`, and this file.

## Configuration

All via environment variables or `.env.local` (see `config.py`). Key settings:
- `SM_LOCAL_BASE_URL` — gateway address (required for live mode)
- `SM_LOCAL_API_KEY` — optional API key
- `SM_LOCAL_VERIFY_TLS` / `SM_LOCAL_CA_BUNDLE` / `SM_LOCAL_TLS_FINGERPRINT_SHA256` — TLS options
- `DASHBOARD_LANGUAGE` — `EN` / `DE` / `FR` / `IT`
- `TZ` — timezone, default `Europe/Zurich` (used via `zoneinfo.ZoneInfo` throughout)
- `DB_PATH` — default `solar_dashboard.db`
- `MOCK_DB_PATH` — default `solar_dashboard_mock.db` (mock mode uses a separate DB, never touches live data)
- `RAW_RETENTION_DAYS` — default 7
- `SM_CLOUD_BACKFILL_ENABLED` + `SM_CLOUD_EMAIL` + `SM_CLOUD_PASSWORD` + `SM_CLOUD_SMID` — optional cloud backfill
- `RENDER_INTERVAL_SECONDS` — default 15
- `DISPLAY_UPDATE_INTERVAL` — e-paper refresh cadence in seconds, default 60
- `EPAPER_VCOM` — VCOM voltage from the panel FPC label (e.g. `-1.48`), required for `--production`
- `DISPLAY_FULL_REFRESH_INTERVAL` — full GC16 refreshes between partial updates, default 1
