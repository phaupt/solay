# Pi 5 + IT8951 Production Runtime — Design Spec

## Goal

Make the solar-eink-dashboard deployable as a 24/7 appliance on a Raspberry Pi 5
with a Waveshare 7.8" e-paper HAT (IT8951 controller). The app logic (collect,
persist, aggregate, render) is mature; this spec covers the missing hardware and
runtime layers.

## Scope

In scope:

- IT8951 display module (init, show, clear, sleep/wake)
- PNG renderer interface (persistent and one-shot Playwright implementations)
- Production loop (collect → render → display → housekeeping)
- Config additions for production mode
- Deployment assets (systemd unit, Pi setup script)
- Deterministic font bundling
- Waveshare bring-up checklist for first hardware validation

Out of scope (deferred):

- Partial refresh policy (requires hardware testing first)
- Dual-clock render/display scheduling (v2, if partial updates are proven)
- Alternative non-Playwright renderers (WeasyPrint, wkhtmltoimage)
- Remote monitoring, OTA updates

## Hardware Target

- Raspberry Pi 5B (4 GB or 8 GB)
- Waveshare 7.8" e-Paper HAT, IT8951 USB/SPI controller
- Resolution: 1872 × 1404, 16 grayscale levels
- VCOM: panel-specific, printed on ribbon cable label

## Architecture

```
main.py --production
  │
  ├── StreamCollector          (existing, daemon thread)
  │     WebSocket /v2/stream → SQLite
  │
  ├── PersistentPlaywrightRenderer   (new, src/renderer_png.py)
  │     warm Chromium → HTML → screenshot → quantize → PIL.Image
  │
  ├── EpaperDisplay            (new, src/epaper.py)
  │     IT8951 init → grayscale upload → GC16 full refresh
  │
  └── ProductionLoop           (new, src/production.py)
        timer loop: build data → render → display → housekeeping
        SIGTERM/SIGINT → graceful shutdown
```

## Module 1: Renderer Interface — `src/renderer_png.py`

### Protocol

```python
class RendererPNG(Protocol):
    def render(self, data: DashboardData) -> Image.Image:
        """Return a 1872×1404 grayscale PIL.Image (16 levels)."""
        ...

    def render_to_file(self, data: DashboardData, path: Path) -> None:
        """Render and write to disk (debug/export use)."""
        ...

    def close(self) -> None:
        """Release resources."""
        ...
```

### `PersistentPlaywrightRenderer`

- Constructor accepts `theme` and `lang` (default from `config`). These are
  baked in at construction time and used for every `render()` call. Production
  mode always uses the same theme/lang; the CLI `--theme`/`--lang` overrides
  are passed at construction, not per-render.
- Launches headless Chromium **once** at init.
- Creates a single page with viewport 1872 × 1404, `device_scale_factor=1`.
- On each `render()` call:
  1. Build dashboard context via `build_dashboard_context(data, theme, lang)`.
  2. Build standalone HTML via `render_dashboard_standalone(context)`.
  3. `page.set_content(html, wait_until="load")`.
  4. `await page.evaluate("document.fonts.ready")` — Playwright awaits the
     returned `Promise`, which resolves when all embedded `@font-face` data
     URLs are decoded. (Note: `wait_for_function("document.fonts.ready")`
     would be wrong — `document.fonts.ready` is a `Promise`, not a boolean.
     Alternative: `wait_for_function("() => document.fonts.status === 'loaded'")`)
  5. `page.screenshot(type="png")` → `bytes`.
  6. Load into `PIL.Image`, convert to `"L"` (8-bit grayscale).
  7. Quantize to 16 levels via an **in-memory** variant of the quantization
     logic. The existing `_quantize_grayscale()` in `export_dashboard.py`
     operates on file paths; the new renderer extracts the `point()` lambda
     into a shared `quantize_image(img, levels) -> Image` helper that works
     on `PIL.Image` directly. Both the new renderers and the existing
     `export_dashboard_png()` use this shared helper.
  8. Return `PIL.Image`.
- `close()` calls `browser.close()` and stops the event loop thread.
- **Dependency chain**: the renderer imports `build_dashboard_context` from
  `src.html_renderer` and `render_dashboard_standalone` from
  `src.dashboard_document`. These are explicit, not hidden — the renderer
  owns the full HTML→image pipeline.

### Asyncio threading model

Playwright's async API requires a running asyncio event loop. The persistent
renderer manages this as follows:

- `__init__` starts a dedicated daemon thread running `asyncio.run(_loop())`.
  The `_loop` coroutine launches the browser, creates the page, and then
  blocks on an `asyncio.Queue` waiting for render requests.
- The synchronous `render()` method creates a
  `concurrent.futures.Future[Image.Image]`, posts a `(DashboardData, Future)`
  tuple to the queue via `loop.call_soon_threadsafe()`, and blocks on
  `future.result(timeout=30)`. It must be `concurrent.futures.Future`, not
  `asyncio.Future` — only the former supports blocking `.result(timeout=...)`
  from a non-async thread. The 30-second timeout prevents the main loop from
  hanging if Chromium becomes unresponsive.
- If the future times out, `render()` raises `RendererTimeout`. The production
  loop catches this and logs a warning (same as any renderer failure).
- `close()` posts a sentinel to the queue, joins the thread (timeout 10s),
  and ensures the browser is closed.

### `OneShotPlaywrightRenderer`

- Same interface. Each `render()` launches Chromium, takes the screenshot,
  closes the browser. Wraps the existing `export_dashboard.py` logic.
- Used for debugging, benchmarking, and fallback if persistent mode is
  unstable on the Pi.

### Design decisions

- **Returns `PIL.Image`, not a file path.** Avoids SD-card writes every cycle.
  `render_to_file()` exists for debug/export. If file output is needed
  in the loop (e.g. for diagnostics), write to `/dev/shm`.
- **Existing `export_dashboard_png()` stays untouched.** It remains the CLI
  one-shot export entry point. The new renderers are for the production loop.
- **Chromium memory on 4 GB Pi**: a single headless Chromium page with a
  static HTML document (no JavaScript SPA, no network requests) typically
  uses 80–150 MB RSS. On a 4 GB Pi 5 this is acceptable. If memory grows
  unexpectedly over multi-day runs, the production loop can periodically
  restart the browser (e.g. every 24 hours) by calling `close()` + re-init.
  This is not implemented in v1 but is a simple fallback if needed.

## Module 2: E-Paper Display — `src/epaper.py`

### Interface

```python
class EpaperDisplay:
    def __init__(self, vcom: float):
        """Initialize IT8951 controller, set VCOM."""

    def show_full(self, image: Image.Image) -> None:
        """Full-screen GC16 refresh from a PIL.Image."""

    def show_partial(self, image: Image.Image, x: int, y: int, w: int, h: int) -> None:
        """Partial DU update of a sub-region. Gated behind config flag."""

    def clear(self) -> None:
        """White-fill the entire display (GC16)."""

    def sleep(self) -> None:
        """Put the display into low-power sleep."""

    def wake(self) -> None:
        """Wake the display from sleep."""

    def close(self) -> None:
        """Sleep + release resources."""
```

### Implementation notes

- Uses the `IT8951` library (GregDMeyer/IT8951). This is **not** a normal
  `pip install` — the upstream project requires a source install from a
  cloned repo (`pip install ./[rpi]`) and builds Cython extensions. See
  the install section below for prerequisites and pinning strategy.
- `show_full()` converts the `PIL.Image` to the IT8951's expected buffer
  format and issues a full `GC16` (16-level grayscale) display update.
- `show_partial()` is implemented but **not called by the production loop
  in v1**. It exists as a tested primitive for future use once ghosting
  behavior is validated on the actual panel.
- Error recovery: if a display call raises, log the error and attempt
  `sleep()` + `wake()` as a soft reset. If that also fails, log critical
  and let the production loop continue without display output (data
  collection must not stop).
- VCOM is read from `config.EPAPER_VCOM` (sourced from `.env.local`).
  The IT8951 library allows setting VCOM at init; using the wrong value
  can damage the panel, so it is never defaulted — the config must be
  explicitly set.
- **VCOM validation**: `main.py --production` validates `EPAPER_VCOM` before
  constructing `EpaperDisplay`. If the value is empty, unparseable as a
  float, or outside the expected range (typically -0.5 to -3.0 V), the
  process exits with a clear error message. This validation happens in
  `main.py`, not in `EpaperDisplay.__init__`, so the failure is obvious
  and early.

### First milestone (hardware bring-up)

Before integrating into the production loop:

1. Confirm SPI is enabled and `/dev/spidev0.0` is accessible.
2. Run a standalone script that inits IT8951, reads panel info, sets VCOM.
3. Display a single full-screen test PNG (GC16).
4. Test one partial DU update on a small region.
5. Test `clear()` → `sleep()` → `wake()` cycle.
6. Document observed ghosting behavior for partial updates.

A `scripts/epaper_test.py` script will be provided for this.

## Module 3: Production Loop — `src/production.py`

### Behavior

```python
class ProductionLoop:
    def __init__(
        self,
        storage: Storage,
        collector: StreamCollector,
        renderer: RendererPNG,
        display: EpaperDisplay | None,
    ):
        ...

    def run(self) -> None:
        """Main loop. Blocks until stop() is called."""
        ...

    def stop(self) -> None:
        """Signal the loop to exit gracefully."""
        ...
```

### Loop cycle (single cadence, v1)

Each cycle, spaced by `DISPLAY_UPDATE_INTERVAL` seconds (default 60):

1. **Build data**: `build_dashboard_data(storage, collector)`.
2. **Render**: `renderer.render(data)` → `PIL.Image`.
3. **Display**: `display.show_full(image)` (if display is not `None`).
4. **Housekeeping** (throttled, see below).
5. **Sleep** until next cycle.

If `display` is `None`, the loop still collects and renders (headless mode for
testing without hardware).

### Day-rollover finalization

The loop tracks `current_date`. When the local date changes:

1. Re-aggregate yesterday's full day from all raw points in storage.
2. Overwrite yesterday's `daily_summary` row (ensures completeness even if the
   service was the only writer).
3. Optionally trigger cloud backfill for any missing prior days.
4. Log the rollover.

This prevents partial daily summaries from surviving midnight. Ordering is
intentional: local re-aggregation runs first (it is authoritative — it has
all the raw points), then cloud backfill runs for **older** missing days only.
Since `api_cloud.py` skips days that already have a summary row (line 192),
the freshly overwritten yesterday row is not re-fetched from cloud.

**Important**: the existing `optional_backfill()` in `api_cloud.py` must
**not** be called directly from the rollover step. That function also
backfills the current-day prefix (line 199+), which is only appropriate at
startup — not on a midnight rollover where the collector is already running.
The rollover step must use either a new helper that only backfills past-day
summaries, or a parameterized version of the existing helper with a flag to
skip current-day prefix backfill (e.g. `optional_backfill(skip_today=True)`).

### Retention cleanup (throttled)

`storage.cleanup_old_points()` runs **once per hour**, not every cycle. The
loop tracks `last_cleanup_at` and checks against it each cycle. This avoids
unnecessary WAL writes on a device where SD-card longevity matters.

### Signal handling

- `SIGTERM` and `SIGINT` set an internal stop flag.
- On exit, shutdown order is: `display.sleep()` → `renderer.close()` →
  `collector.stop()`. This order is intentional: the display is put to sleep
  first (most visible side-effect of a dirty shutdown), then Chromium is
  closed (frees the most memory), then the collector daemon thread is stopped
  last (it may still be writing to SQLite during the prior steps, which is
  fine — SQLite WAL handles concurrent access).
- The loop must not leave the display powered on after shutdown.

### Error handling

- **Renderer failure**: log warning, skip this cycle's display update, retry
  next cycle. Do not crash — data collection must continue.
- **Display failure**: log warning, attempt soft reset (sleep/wake). If reset
  fails, continue without display. Set an internal flag so the next cycle
  attempts to reinitialize.
- **Collector failure**: handled by existing `StreamCollector` reconnect logic
  with exponential backoff. Not this module's responsibility.

## Changes to `main.py`

Add `--production` flag. The three top-level modes (`--production`, `--mock`,
`--export-png`) are **mutually exclusive**; `argparse` enforces this via a
mutually exclusive group or explicit validation with a clear error message.

```
main.py --production              # production loop: collect → render → display
main.py --production --no-display # same loop but no IT8951 (headless test)
main.py --mock                    # existing mock Flask preview
main.py                           # existing live Flask preview
main.py --export-png <path>       # existing one-shot PNG export
```

`--production` mode:

1. Validate `EPAPER_VCOM` (unless `--no-display`). Exit early if invalid.
2. Creates storage and collector (existing `create_live_storage_and_collector()`).
3. Creates `PersistentPlaywrightRenderer` (with theme/lang from CLI or config).
4. Creates `EpaperDisplay` (unless `--no-display`).
5. Runs `ProductionLoop.run()` (blocks until signal).

`RENDER_INTERVAL_SECONDS` is **not used** in production mode. It continues to
drive the browser auto-refresh meta tag in the Flask dev preview only.
`DISPLAY_UPDATE_INTERVAL` is the sole cadence control for the production loop.

## Config Additions — `config.py`

```python
# --- Production / E-Ink ---
DISPLAY_UPDATE_INTERVAL = int(os.getenv("DISPLAY_UPDATE_INTERVAL", "60"))
EPAPER_VCOM = os.getenv("EPAPER_VCOM", "")       # required for --production
DISPLAY_FULL_REFRESH_INTERVAL = int(os.getenv("DISPLAY_FULL_REFRESH_INTERVAL", "1"))
# ↑ every N display updates, force full GC16 (v1: always 1, all updates are full)
```

`DISPLAY_MODE` (currently at line 99) is replaced by the `--production` CLI
flag. The env var may remain for backwards compat but is no longer the primary
switch.

## Font Bundling

### Approach

- Bundle exactly one font family (regular + bold weights).
- Embed as `@font-face` rules with `data:font/woff2;base64,...` URLs.
- Inject into the standalone HTML path in `render_dashboard_standalone()`
  (`src/dashboard_document.py`), prepended to the embedded CSS.
- The specific font is chosen after a visual validation pass against the
  current Helvetica-tuned layout. Candidates: Inter, IBM Plex Sans,
  Source Sans 3, or similar neutral sans-serif fonts with good tabular
  numeral support.

### Validation criteria

- Numeric column alignment (tabular figures required).
- No line-break changes in flow labels, chart axis labels, weekday labels.
- Readability at e-ink viewing distance (~1–2 meters).
- File size: target < 100 KB for regular + bold woff2 combined.

### Integration

- `render_dashboard_standalone()` prepends the `@font-face` block to the
  embedded CSS string.
- `dashboard.css` font-family stack updated to reference the bundled font
  first, with existing fallbacks retained.
- `PersistentPlaywrightRenderer` awaits `page.evaluate("document.fonts.ready")`
  before screenshot.

## Deployment Assets

### `solar-dashboard.service` (systemd unit)

```ini
[Unit]
Description=Solar E-Ink Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/solar-eink-dashboard
ExecStart=/home/pi/solar-eink-dashboard/.venv312/bin/python main.py --production
Restart=on-failure
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

### `scripts/setup-pi.sh`

Automates first-time Pi setup:

1. Enable SPI via `raspi-config nonint` or `/boot/firmware/config.txt`.
2. Install system dependencies: `python3.12`, `python3.12-dev`,
   `libatlas-base-dev`, `gcc`, `make` (compiler toolchain for Cython
   extensions in IT8951).
3. Create venv, install `requirements-pi.txt` (see below).
4. Clone and install IT8951 from source:
   `git clone https://github.com/GregDMeyer/IT8951.git /tmp/IT8951 &&`
   `pip install /tmp/IT8951/[rpi]` — this builds the Cython SPI extension.
   Pin to a specific commit or tag for reproducibility.
5. Install Playwright Chromium (`python -m playwright install chromium`).
6. Copy `.env.local.example` → `.env.local`, prompt for gateway URL and VCOM.
7. Install and enable systemd service.

### `requirements-pi.txt`

Locked/pinned versions of all runtime dependencies. IT8951 is **not**
listed here — it is installed from source in `setup-pi.sh` (step 4) because
it requires Cython compilation on the target platform. All other deps:

- `pillow`, `numpy` (image processing)
- `requests`, `websocket-client` (data collection)
- `flask` (optional, only if dev preview is wanted on Pi)
- `playwright` (rendering)
- `jinja2` (templating)

## Waveshare Bring-Up Checklist

For first hardware validation before running the full production stack:

- [ ] SPI enabled in `/boot/firmware/config.txt` (`dtparam=spi=on`)
- [ ] `/dev/spidev0.0` exists and is accessible by the `pi` user
- [ ] IT8951 library installed from source (`pip install ./[rpi]` from cloned repo)
- [ ] Run `scripts/epaper_test.py` — confirm panel info is read
- [ ] Note VCOM value from panel ribbon cable label, set in `.env.local`
- [ ] Display a full-screen test image (GC16) — confirm correct orientation
- [ ] Test one partial DU update on a small region — note ghosting
- [ ] Test clear → sleep → wake cycle
- [ ] Document panel behavior observations

## Testing Strategy

### Unit tests (no hardware)

- `RendererPNG` protocol conformance for both implementations.
- `ProductionLoop` with `display=None` and a mock renderer.
- Day-rollover logic with synthetic date changes.
- Retention cleanup throttle logic.

### Integration tests (on Pi, manual)

- Full cycle: live data → render → display.
- 24-hour soak test: verify day rollover, retention cleanup, memory stability.
- Network disconnect/reconnect: collector recovery, continued rendering.
- Service restart: `systemctl restart solar-dashboard`, display recovers.

### Not tested (deferred)

- Partial refresh ghosting policy.
- Multi-day unattended runtime (planned for hardware acceptance phase).
