# Solar Manager E-Ink Dashboard Context

Use this file as shared project context for AI coding agents working in this repo.

## Read These First

- `tmp/solar-eink-dashboard-PROJECT.md`
- `tmp/Solar Manager API.pdf`
- current repo code — the production pipeline is implemented and the codebase is the source of truth

## What This Project Is

A Raspberry Pi plus E-Ink dashboard for Solar Manager that should present the key information from the Solar Manager app, but in an E-Ink-optimized layout.

The currently approved main dashboard shape is:

- live flow with Solar, Grid, Home, Battery
- a clean 24h current-day chart
- a 7-day history strip
- last update

Not currently part of the main screen:

- PV performance block
- device list
- extra KPI-card rows

## Hard Technical Constraints

- The local Solar Manager API exposes `/v2/devices`, `/v2/point`, and `/v2/stream`.
- The local `Wh` values are only for the current interval, typically around 10 seconds.
- A 30 second poll of `/v2/point` is not enough for a correct daily chart or correct daily totals.
- For intraday history, prefer `/v2/stream` plus local persistence.
- Use the Cloud API only as optional backfill or validation, not as the only dependency for the wall display.

Relevant Cloud endpoints:

- `/v3/users/{smId}/data/range`
- `/v1/statistics/gateways/{smId}`
- `/v1/chart/gateway/{smId}`

Current backfill approach:

- previous full days can be backfilled from cloud statistics
- the current-day prefix before the first local sample can be backfilled from cloud range data
- avoid overlapping current-day cloud points with already collected local stream data

## Architectural Bias

Default toward this flow:

1. collect local live data
2. persist it locally
3. aggregate it into chart and daily summaries
4. render the UI from the aggregated model
5. only then optimize for E-Ink hardware output

If the current code conflicts with that, refactor it.

## UI Direction

Aim for app-like information density, not a 1:1 copy of the phone UI.

Current target:

- current Solar / Grid / Home / Battery live values
- last update
- 24h chart with production and consumption
- peak production marker based on the real current-day maximum
- compact 7-day history strip
- language support for `EN`, `DE`, `FR`, `IT`

Important UI/state learnings from the current implementation:

- the 7-day strip must always render all 7 columns
- today must always be the far-right column
- missing historical days should render as `0.0`, not disappear
- weekday labels must use short localized forms so they do not wrap or overflow in `EN`, `DE`, `FR`, or `IT`
- stale state should be indicated quietly in the update meta line; avoid redundant centered warning text if the inactive flow already makes the state obvious
- active flow paths currently use straight connections with centered double arrowheads; do not revert to end markers or curved paths unless explicitly requested
- the peak-production guide should align to the displayed charted production peak, not a detached raw spike above the visible curve
- README screenshots should be generated from the native export path at `1872x1404`, not from a smaller browser viewport capture, otherwise typography and spacing look misleadingly small

For the chart:

- x-axis: current local day, 00:00 to 24:00
- y-axis: power in kW
- at minimum show production and consumption
- battery and grid can be secondary if needed

## E-Ink Rules

- Use the 1872x1404 resolution properly.
- Use 16 grayscale levels deliberately, not accidentally.
- Quantize output to the display's effective grayscale budget.
- Favor readability from distance over decorative complexity.
- Avoid LCD-like assumptions about color, motion, and refresh.
- Keep the browser preview and README aligned with the actual renderer.

## Domain Notes

- Do not compute grid power as `consumption - production` if battery flows exist.
- Battery-aware grid power should account for charge and discharge.
- Keep self-consumption and autarky separate.
- Treat time zones carefully. Do not mix UTC collection with local-day charting carelessly.
- A device `soc` in local API payloads is not automatically a home battery. EV/car SOC must not be shown in the battery node unless the device metadata clearly identifies a battery.

## Security Notes

- No secrets in source files.
- No API keys or passwords in logs.
- Dev preview should default to localhost, not an open LAN listener.
- Use timeouts, retries, and reconnect logic for network IO.

## Renderer Notes

- The primary renderer is now `src/html_renderer.py` with HTML/CSS/SVG preview through `src/web_preview.py`.
- Standalone document rendering lives in `src/dashboard_document.py`, with embedded Inter font for cross-platform consistency.
- One-shot PNG export lives in `src/export_dashboard.py`.
- `src/renderer_png.py` provides `PersistentPlaywrightRenderer` (warm Chromium for production) and `OneShotPlaywrightRenderer`.
- `src/epaper.py` wraps the IT8951 e-paper controller (GC16 full refresh, sleep/wake, auto-wake).
- `src/production.py` runs the timer-based production loop with day rollover, startup reconciliation, retention cleanup, and signal handling.
- `src/renderer.py` remains only as a legacy PNG/Pillow fallback.
- When user-visible architecture changes, keep `README.md`, this file, and the local agent guidance files in sync.

## Working Style

- Be willing to challenge existing code if it is wrong.
- Keep mock data only for tests or UI iteration.
- Prefer a correct data model over a fast but misleading demo.
- If a better structure than the current project doc emerges, explain it briefly and move forward.
