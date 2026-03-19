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

- `src/models.py` -Typed dataclasses: `SensorPoint`, `ChartBucket`, `DailySummary`, `DeviceStatus`, `DashboardData`
- `src/api_local.py` -`LocalApiClient` (HTTP), `StreamCollector` (WebSocket with auto-reconnect + exponential backoff)
- `src/storage.py` -SQLite with WAL mode for concurrent read/write
- `src/aggregator.py` -Chart bucket averaging and daily Wh summation
- `src/html_renderer.py` -Primary browser-faithful dashboard renderer
- `src/dashboard_document.py` -Standalone HTML document rendering for export (with embedded Inter font)
- `src/export_dashboard.py` -One-shot PNG export path via Playwright
- `src/renderer_png.py` -`PersistentPlaywrightRenderer` (warm Chromium) + `OneShotPlaywrightRenderer`
- `src/epaper.py` -IT8951 e-paper display driver (show, clear, sleep/wake)
- `src/production.py` -`ProductionLoop`: timer-based collect→render→display with day rollover, startup reconciliation, retention cleanup, signal handling
- `src/renderer.py` -Legacy PNG/Pillow fallback
- `src/web_preview.py` -Flask dev server (binds 127.0.0.1 only)
- `src/preview_scenarios.py` -fixed dashboard state overrides for preview/review
- `config.py` -All config from env vars, loaded from `.env.local` (git-ignored)
- `src/api_cloud.py` -optional cloud backfill for missing day history and the current-day startup gap

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
- all time conversions use `zoneinfo.ZoneInfo(config.TIMEZONE)` -never hard-coded UTC offsets; day boundaries, chart x-axis, and "today" aggregation must respect DST transitions

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

- partial refresh strategy (DU mode) -needs real-panel testing before enabling
- long-running thermal/memory validation on Pi 5
