# Pi 5 + IT8951 Production Runtime — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the solar-eink-dashboard as a 24/7 appliance on a Raspberry Pi 5 with Waveshare 7.8" e-paper (IT8951).

**Architecture:** Three new modules (`src/renderer_png.py`, `src/epaper.py`, `src/production.py`) plus config additions, a `--production` CLI mode, deployment assets, and font bundling. The existing collect/persist/aggregate/render pipeline is untouched; the new modules layer on top.

**Tech Stack:** Python 3.12, Playwright (async API), PIL/Pillow, IT8951 (GregDMeyer), asyncio, concurrent.futures, signal, systemd.

**Spec:** `docs/specs/2026-03-19-pi5-production-runtime-design.md`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `src/renderer_png.py` | `RendererPNG` protocol, `quantize_image()`, `PersistentPlaywrightRenderer`, `OneShotPlaywrightRenderer` |
| Create | `src/epaper.py` | `EpaperDisplay` class — IT8951 init, show, clear, sleep/wake |
| Create | `src/production.py` | `ProductionLoop` class — timer loop, day rollover, retention cleanup, signal handling |
| Create | `tests/test_renderer_png.py` | Tests for quantize, renderer protocol, persistent renderer |
| Create | `tests/test_production.py` | Tests for production loop, day rollover, cleanup throttle |
| Create | `tests/test_epaper.py` | Tests for EpaperDisplay with mocked IT8951 |
| Create | `scripts/epaper_test.py` | Standalone hardware bring-up script |
| Create | `deploy/solar-dashboard.service` | systemd unit file |
| Create | `scripts/setup-pi.sh` | Pi first-time setup script |
| Create | `requirements-pi.txt` | Pinned Pi runtime dependencies |
| Modify | `src/export_dashboard.py` | Extract `quantize_image()` into shared helper, reuse from `renderer_png` |
| Modify | `config.py:97-103` | Add production config vars (`DISPLAY_UPDATE_INTERVAL`, `EPAPER_VCOM`, etc.) |
| Modify | `main.py:186-218` | Add `--production` / `--no-display` flags, mutual exclusivity |
| Modify | `src/api_cloud.py:169-217` | Add `skip_today` parameter to `optional_backfill()` |
| Modify | `src/dashboard_document.py` | Inject `@font-face` block into standalone HTML |
| Modify | `src/static/dashboard.css:60` | Update font-family stack to bundled font first |

---

## Task 1: Extract in-memory quantize helper

The existing `_quantize_grayscale()` in `export_dashboard.py` works on file
paths. Extract the core logic into a shared `quantize_image()` that works on
`PIL.Image` directly. Both the existing export path and the new renderers will
use it.

**Files:**
- Modify: `src/export_dashboard.py:16-23`
- Test: `tests/test_renderer_png.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_renderer_png.py
"""Tests for the PNG renderer helpers and protocol."""

from PIL import Image

from src.export_dashboard import quantize_image


def test_quantize_image_16_levels():
    """quantize_image should map pixel values to nearest of 16 levels."""
    img = Image.new("L", (4, 4), color=128)
    result = quantize_image(img, levels=16)
    assert result.mode == "L"
    # 128 should map to round(128 / (255/15)) * (255/15) = 8 * 17 = 136
    assert result.getpixel((0, 0)) == 136


def test_quantize_image_returns_new_image():
    """quantize_image must not mutate the input image."""
    img = Image.new("L", (2, 2), color=100)
    result = quantize_image(img, levels=16)
    assert result is not img
    assert img.getpixel((0, 0)) == 100


def test_quantize_image_1_level_returns_grayscale():
    """With 1 level, output should be all zeros (black)."""
    img = Image.new("L", (2, 2), color=200)
    result = quantize_image(img, levels=1)
    assert result.getpixel((0, 0)) == 0


def test_quantize_image_converts_rgb_to_grayscale():
    """RGB input should be converted to grayscale before quantizing."""
    img = Image.new("RGB", (2, 2), color=(128, 128, 128))
    result = quantize_image(img, levels=16)
    assert result.mode == "L"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv312/bin/pytest tests/test_renderer_png.py -v`
Expected: FAIL — `quantize_image` does not exist yet.

- [ ] **Step 3: Implement quantize_image and refactor export_dashboard.py**

In `src/export_dashboard.py`, replace the file-based `_quantize_grayscale` with:

```python
def quantize_image(image: Image.Image, levels: int) -> Image.Image:
    """Quantize a PIL Image to N grayscale levels. Returns a new image."""
    gray = image.convert("L")
    if levels <= 1:
        return gray.point(lambda px: 0)
    step = 255 / (levels - 1)
    return gray.point(lambda px: int(round(px / step) * step))
```

Make it a public function (no underscore). Update `_quantize_grayscale` to call it:

```python
def _quantize_grayscale(path: Path, levels: int) -> None:
    image = Image.open(path)
    quantized = quantize_image(image, levels)
    quantized.save(path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv312/bin/pytest tests/test_renderer_png.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run existing tests to verify no regression**

Run: `./.venv312/bin/pytest tests/ -v`
Expected: all existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/export_dashboard.py tests/test_renderer_png.py
git commit -m "Extract quantize_image() as shared in-memory helper"
```

---

## Task 2: Add production config vars

Add the new config variables needed by the production runtime.

**Files:**
- Modify: `config.py:97-103`

- [ ] **Step 1: Add config vars after the existing DISPLAY_MODE line**

```python
# --- Production / E-Ink ---
DISPLAY_UPDATE_INTERVAL = int(os.getenv("DISPLAY_UPDATE_INTERVAL", "60"))
EPAPER_VCOM = os.getenv("EPAPER_VCOM", "")
DISPLAY_FULL_REFRESH_INTERVAL = int(os.getenv("DISPLAY_FULL_REFRESH_INTERVAL", "1"))
```

Keep `DISPLAY_MODE` as-is for backwards compatibility.

- [ ] **Step 2: Verify config loads without errors**

Run: `./.venv312/bin/python -c "import config; print(config.DISPLAY_UPDATE_INTERVAL, config.EPAPER_VCOM, config.DISPLAY_FULL_REFRESH_INTERVAL)"`
Expected: `60  1`

- [ ] **Step 3: Run existing tests**

Run: `./.venv312/bin/pytest tests/ -v`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add config.py
git commit -m "Add production config: DISPLAY_UPDATE_INTERVAL, EPAPER_VCOM, DISPLAY_FULL_REFRESH_INTERVAL"
```

---

## Task 3: PersistentPlaywrightRenderer

The core renderer: keeps Chromium warm, renders HTML→quantized PIL.Image
in-memory. Uses a dedicated asyncio event loop thread with
`concurrent.futures.Future` for cross-thread communication.

**Files:**
- Create: `src/renderer_png.py`
- Test: `tests/test_renderer_png.py` (append)

- [ ] **Step 1: Write the failing test for PersistentPlaywrightRenderer**

Append to `tests/test_renderer_png.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from src.models import DashboardData


def _make_minimal_dashboard_data():
    """Create a minimal DashboardData for renderer tests."""
    from datetime import date
    from src.models import DailySummary
    return DashboardData(
        live=None,
        chart_buckets=[],
        peak_production_w=0.0,
        daily_summary=DailySummary(local_date=date.today()),
        daily_history=[],
        devices=[],
    )


def _has_playwright():
    """Check if Playwright + Chromium are available."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.launch().close()
        return True
    except Exception:
        return False


_skip_no_playwright = pytest.mark.skipif(
    not _has_playwright(),
    reason="Playwright/Chromium not installed — skipping renderer integration tests",
)


@_skip_no_playwright
class TestPersistentPlaywrightRenderer:
    """Integration tests for PersistentPlaywrightRenderer.

    These tests launch real Chromium — skipped automatically when
    Playwright/Chromium is not installed. Not part of the fast unit suite.
    """

    def test_render_returns_grayscale_image(self):
        from src.renderer_png import PersistentPlaywrightRenderer
        renderer = PersistentPlaywrightRenderer()
        try:
            data = _make_minimal_dashboard_data()
            img = renderer.render(data)
            assert img.mode == "L"
            assert img.size == (1872, 1404)
        finally:
            renderer.close()

    def test_render_to_file_writes_png(self, tmp_path):
        from src.renderer_png import PersistentPlaywrightRenderer
        renderer = PersistentPlaywrightRenderer()
        try:
            data = _make_minimal_dashboard_data()
            out = tmp_path / "test.png"
            renderer.render_to_file(data, out)
            assert out.exists()
            img = Image.open(out)
            assert img.mode == "L"
        finally:
            renderer.close()

    def test_multiple_renders_reuse_browser(self):
        from src.renderer_png import PersistentPlaywrightRenderer
        renderer = PersistentPlaywrightRenderer()
        try:
            data = _make_minimal_dashboard_data()
            img1 = renderer.render(data)
            img2 = renderer.render(data)
            assert img1.size == img2.size
        finally:
            renderer.close()

    def test_close_is_idempotent(self):
        from src.renderer_png import PersistentPlaywrightRenderer
        renderer = PersistentPlaywrightRenderer()
        renderer.close()
        renderer.close()  # should not raise


@_skip_no_playwright
class TestOneShotPlaywrightRenderer:
    """Protocol conformance tests for OneShotPlaywrightRenderer."""

    def test_render_returns_grayscale_image(self):
        from src.renderer_png import OneShotPlaywrightRenderer
        renderer = OneShotPlaywrightRenderer()
        try:
            data = _make_minimal_dashboard_data()
            img = renderer.render(data)
            assert img.mode == "L"
            assert img.size == (1872, 1404)
        finally:
            renderer.close()

    def test_close_is_noop(self):
        from src.renderer_png import OneShotPlaywrightRenderer
        renderer = OneShotPlaywrightRenderer()
        renderer.close()  # should not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv312/bin/pytest tests/test_renderer_png.py::TestPersistentPlaywrightRenderer -v`
Expected: FAIL — `PersistentPlaywrightRenderer` not defined.

- [ ] **Step 3: Implement src/renderer_png.py**

```python
"""PNG renderer interface and implementations.

Provides a Protocol for rendering DashboardData to a quantized grayscale
PIL.Image, plus two Playwright-backed implementations:
- PersistentPlaywrightRenderer: keeps Chromium warm (production use)
- OneShotPlaywrightRenderer: cold-start per render (debug/fallback)
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import io
import logging
import threading
from pathlib import Path
from typing import Protocol

from PIL import Image

import config
from src.dashboard_document import render_dashboard_standalone
from src.export_dashboard import quantize_image
from src.html_renderer import build_dashboard_context
from src.models import DashboardData

logger = logging.getLogger(__name__)

_SENTINEL = object()


class RendererTimeout(Exception):
    """Raised when a render call exceeds the timeout."""


class RendererPNG(Protocol):
    def render(self, data: DashboardData) -> Image.Image:
        """Return a 1872x1404 grayscale PIL.Image (16 levels)."""
        ...

    def render_to_file(self, data: DashboardData, path: Path) -> None:
        """Render and write to disk (debug/export use)."""
        ...

    def close(self) -> None:
        """Release resources."""
        ...


class PersistentPlaywrightRenderer:
    """Keeps a single headless Chromium instance warm for repeated renders."""

    def __init__(
        self,
        *,
        theme: str | None = None,
        lang: str | None = None,
        grayscale_levels: int | None = None,
        timeout: float = 30.0,
    ):
        self._theme = theme
        self._lang = lang
        self._levels = grayscale_levels if grayscale_levels is not None else config.EXPORT_GRAYSCALE_LEVELS
        self._timeout = timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue | None = None
        self._closed = False

        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="playwright-renderer"
        )
        self._thread.start()
        if not self._ready.wait(timeout=30):
            raise RuntimeError("Playwright renderer thread failed to start")

    def _run_loop(self) -> None:
        asyncio.run(self._loop_main())

    async def _loop_main(self) -> None:
        from playwright.async_api import async_playwright

        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()

        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(
                viewport={
                    "width": config.DISPLAY_WIDTH,
                    "height": config.DISPLAY_HEIGHT,
                },
                device_scale_factor=1,
            )
            self._ready.set()

            while True:
                item = await self._queue.get()
                if item is _SENTINEL:
                    break

                data, future = item
                try:
                    img = await self._render_async(page, data)
                    future.set_result(img)
                except Exception as exc:
                    future.set_exception(exc)

            await browser.close()

    async def _render_async(
        self, page, data: DashboardData
    ) -> Image.Image:
        context = build_dashboard_context(
            data, theme=self._theme, lang=self._lang, refresh_seconds=0
        )
        html = render_dashboard_standalone(context)
        await page.set_content(html, wait_until="load")
        await page.evaluate("document.fonts.ready")
        png_bytes = await page.screenshot(type="png", full_page=False)
        img = Image.open(io.BytesIO(png_bytes))
        return quantize_image(img, self._levels)

    def render(self, data: DashboardData) -> Image.Image:
        if self._closed:
            raise RuntimeError("Renderer is closed")
        future: concurrent.futures.Future[Image.Image] = concurrent.futures.Future()
        self._loop.call_soon_threadsafe(self._queue.put_nowait, (data, future))
        try:
            return future.result(timeout=self._timeout)
        except concurrent.futures.TimeoutError:
            raise RendererTimeout(
                f"Render timed out after {self._timeout}s"
            ) from None

    def render_to_file(self, data: DashboardData, path: Path) -> None:
        img = self.render(data)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        img.save(path)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._loop is not None and self._queue is not None:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, _SENTINEL)
        if self._thread.is_alive():
            self._thread.join(timeout=10)


class OneShotPlaywrightRenderer:
    """Cold-start renderer: launches Chromium per render. Debug/fallback use."""

    def __init__(
        self,
        *,
        theme: str | None = None,
        lang: str | None = None,
        grayscale_levels: int | None = None,
    ):
        self._theme = theme
        self._lang = lang
        self._levels = grayscale_levels if grayscale_levels is not None else config.EXPORT_GRAYSCALE_LEVELS

    def render(self, data: DashboardData) -> Image.Image:
        context = build_dashboard_context(
            data, theme=self._theme, lang=self._lang, refresh_seconds=0
        )
        html = render_dashboard_standalone(context)
        png_bytes = asyncio.run(self._screenshot(html))
        img = Image.open(io.BytesIO(png_bytes))
        return quantize_image(img, self._levels)

    async def _screenshot(self, html: str) -> bytes:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(
                viewport={
                    "width": config.DISPLAY_WIDTH,
                    "height": config.DISPLAY_HEIGHT,
                },
                device_scale_factor=1,
            )
            await page.set_content(html, wait_until="load")
            await page.evaluate("document.fonts.ready")
            png_bytes = await page.screenshot(type="png", full_page=False)
            await browser.close()
            return png_bytes

    def render_to_file(self, data: DashboardData, path: Path) -> None:
        img = self.render(data)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        img.save(path)

    def close(self) -> None:
        pass  # nothing to clean up
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv312/bin/pytest tests/test_renderer_png.py -v`
Expected: all pass (including Task 1 tests + new renderer tests).

- [ ] **Step 5: Commit**

```bash
git add src/renderer_png.py tests/test_renderer_png.py
git commit -m "Add PersistentPlaywrightRenderer and OneShotPlaywrightRenderer"
```

---

## Task 4: EpaperDisplay module

IT8951 display wrapper. On dev machines without hardware, all tests mock the
IT8951 library. The actual hardware validation uses `scripts/epaper_test.py`.

**Files:**
- Create: `src/epaper.py`
- Create: `tests/test_epaper.py`

- [ ] **Step 1: Write failing tests with mocked IT8951**

```python
# tests/test_epaper.py
"""Tests for the e-paper display module with mocked IT8951."""

from unittest.mock import MagicMock, patch
from PIL import Image
import pytest


@pytest.fixture
def mock_it8951():
    """Mock the IT8951 library so tests run without hardware."""
    mock_display = MagicMock()
    mock_display.width = 1872
    mock_display.height = 1404

    with patch.dict("sys.modules", {
        "IT8951": MagicMock(),
        "IT8951.display": MagicMock(),
        "IT8951.constants": MagicMock(),
    }):
        with patch("src.epaper.AutoEPDDisplay", return_value=mock_display):
            yield mock_display


class TestEpaperDisplay:

    def test_init_sets_vcom(self, mock_it8951):
        from src.epaper import EpaperDisplay
        display = EpaperDisplay(vcom=-1.48)
        assert display._vcom == -1.48

    def test_show_full_calls_display(self, mock_it8951):
        from src.epaper import EpaperDisplay
        display = EpaperDisplay(vcom=-1.48)
        img = Image.new("L", (1872, 1404), color=128)
        display.show_full(img)
        assert mock_it8951.frame_buf is not None

    def test_clear_fills_white(self, mock_it8951):
        from src.epaper import EpaperDisplay
        display = EpaperDisplay(vcom=-1.48)
        display.clear()
        # Should call draw_full with a white image
        assert mock_it8951.draw_full.called or mock_it8951.frame_buf is not None

    def test_close_is_safe(self, mock_it8951):
        from src.epaper import EpaperDisplay
        display = EpaperDisplay(vcom=-1.48)
        display.close()
        display.close()  # idempotent

    def test_sleep_wake_cycle(self, mock_it8951):
        from src.epaper import EpaperDisplay
        mock_it8951.epd = MagicMock()
        display = EpaperDisplay(vcom=-1.48)
        display.sleep()
        display.wake()
        # Should not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv312/bin/pytest tests/test_epaper.py -v`
Expected: FAIL — `src.epaper` does not exist.

- [ ] **Step 3: Implement src/epaper.py**

```python
"""E-Paper display module for Waveshare 7.8" with IT8951 controller."""

from __future__ import annotations

import logging
from PIL import Image
import numpy as np

logger = logging.getLogger(__name__)

try:
    from IT8951.display import AutoEPDDisplay
    from IT8951 import constants as epd_constants
    _HAS_IT8951 = True
except ImportError:
    AutoEPDDisplay = None
    epd_constants = None
    _HAS_IT8951 = False


class EpaperDisplay:
    """IT8951-based e-paper display wrapper.

    Provides init, full-screen GC16 refresh, partial DU update (for future
    use), clear, sleep, wake, and cleanup.
    """

    def __init__(self, vcom: float):
        self._vcom = vcom
        self._closed = False
        self._sleeping = False

        if not _HAS_IT8951:
            raise RuntimeError(
                "IT8951 library not installed. Install from source: "
                "pip install ./[rpi] from the GregDMeyer/IT8951 repo."
            )

        logger.info("Initializing IT8951 display (VCOM=%.2f)", vcom)
        self._display = AutoEPDDisplay(vcom=vcom)
        logger.info(
            "Display initialized: %dx%d",
            self._display.width,
            self._display.height,
        )

    def show_full(self, image: Image.Image) -> None:
        """Full-screen GC16 refresh from a PIL.Image."""
        if self._sleeping:
            self.wake()

        img = image.convert("L").resize(
            (self._display.width, self._display.height), Image.LANCZOS
        )
        self._display.frame_buf.paste(img)
        self._display.draw_full(epd_constants.DisplayModes.GC16)

    def show_partial(
        self, image: Image.Image, x: int, y: int, w: int, h: int
    ) -> None:
        """Partial DU update of a sub-region. Not used in v1 production loop."""
        if self._sleeping:
            self.wake()

        region = image.convert("L").crop((0, 0, w, h))
        self._display.frame_buf.paste(region, (x, y))
        self._display.draw_partial(epd_constants.DisplayModes.DU)

    def clear(self) -> None:
        """White-fill the entire display with a full GC16 refresh."""
        if self._sleeping:
            self.wake()

        white = Image.new("L", (self._display.width, self._display.height), 255)
        self._display.frame_buf.paste(white)
        self._display.draw_full(epd_constants.DisplayModes.GC16)

    def sleep(self) -> None:
        """Put the display controller into low-power sleep."""
        if self._sleeping or self._closed:
            return
        try:
            self._display.epd.sleep()
            self._sleeping = True
            logger.info("Display entered sleep mode")
        except Exception:
            logger.exception("Failed to put display to sleep")

    def wake(self) -> None:
        """Wake the display controller from sleep."""
        if not self._sleeping:
            return
        try:
            self._display.epd.run()
            self._sleeping = False
            logger.info("Display woke from sleep")
        except Exception:
            logger.exception("Failed to wake display")

    def close(self) -> None:
        """Sleep the display and release resources."""
        if self._closed:
            return
        self._closed = True
        self.sleep()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv312/bin/pytest tests/test_epaper.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/epaper.py tests/test_epaper.py
git commit -m "Add EpaperDisplay module wrapping IT8951 driver"
```

---

## Task 5: Parameterize cloud backfill for rollover safety

Add `skip_today` parameter to `optional_backfill()` so the production loop
can call it at day rollover without triggering current-day prefix backfill.

**Files:**
- Modify: `src/api_cloud.py:169`
- Test: `tests/test_api_cloud.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_api_cloud.py`:

```python
def test_optional_backfill_skip_today_skips_prefix(monkeypatch, tmp_path):
    """When skip_today=True, optional_backfill must not fetch current-day prefix."""
    import config
    monkeypatch.setattr(config, "SM_CLOUD_BACKFILL_ENABLED", True)
    monkeypatch.setattr(config, "SM_CLOUD_BACKFILL_DAYS", 3)
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))

    from src.storage import Storage
    storage = Storage(str(tmp_path / "test.db"))

    mock_client = MagicMock()
    mock_client.configured = True
    mock_client.get_statistics.return_value = {
        "production": 5000, "consumption": 3000,
        "gridImport": 1000, "gridExport": 2000,
        "selfConsumption": 2000,
        "batteryCharge": 500, "batteryDischarge": 400,
    }

    with patch("src.api_cloud.CloudApiClient", return_value=mock_client):
        from src.api_cloud import optional_backfill
        optional_backfill(storage, skip_today=True)

    # get_range is the current-day prefix call — must NOT have been called
    mock_client.get_range.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv312/bin/pytest tests/test_api_cloud.py::test_optional_backfill_skip_today_skips_prefix -v`
Expected: FAIL — `optional_backfill()` does not accept `skip_today`.

- [ ] **Step 3: Add skip_today parameter**

In `src/api_cloud.py`, change the signature at line 169:

```python
def optional_backfill(storage: Storage, *, skip_today: bool = False) -> int:
```

Then wrap the current-day prefix block (lines 199–215) with:

```python
    if not skip_today:
        # existing current-day prefix backfill code ...
```

- [ ] **Step 4: Run all tests to verify**

Run: `./.venv312/bin/pytest tests/ -v`
Expected: all pass, including existing cloud backfill tests.

- [ ] **Step 5: Commit**

```bash
git add src/api_cloud.py tests/test_api_cloud.py
git commit -m "Add skip_today param to optional_backfill for rollover safety"
```

---

## Task 6: ProductionLoop

The main production runtime loop: single-cadence timer, day-rollover
finalization, throttled retention cleanup, signal handling, graceful shutdown.

**Files:**
- Create: `src/production.py`
- Create: `tests/test_production.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_production.py
"""Tests for the production loop."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, call
from PIL import Image
import pytest

from src.production import ProductionLoop


@pytest.fixture
def mock_deps():
    """Create mocked dependencies for ProductionLoop."""
    storage = MagicMock()
    storage.get_points_for_date.return_value = []
    storage.get_daily_summaries.return_value = []
    storage.get_latest_point.return_value = None

    collector = MagicMock()
    collector.latest_point = None
    collector.latest_devices = []

    renderer = MagicMock()
    renderer.render.return_value = Image.new("L", (1872, 1404), 128)

    display = MagicMock()

    return storage, collector, renderer, display


class TestProductionLoopSingleCycle:

    def test_one_cycle_renders_and_displays(self, mock_deps):
        storage, collector, renderer, display = mock_deps
        loop = ProductionLoop(storage, collector, renderer, display)
        loop._run_one_cycle()
        renderer.render.assert_called_once()
        display.show_full.assert_called_once()

    def test_one_cycle_without_display(self, mock_deps):
        storage, collector, renderer, _ = mock_deps
        loop = ProductionLoop(storage, collector, renderer, display=None)
        loop._run_one_cycle()
        renderer.render.assert_called_once()

    def test_renderer_failure_does_not_crash(self, mock_deps):
        storage, collector, renderer, display = mock_deps
        renderer.render.side_effect = RuntimeError("browser died")
        loop = ProductionLoop(storage, collector, renderer, display)
        loop._run_one_cycle()  # should not raise
        display.show_full.assert_not_called()

    def test_display_failure_does_not_crash(self, mock_deps):
        storage, collector, renderer, display = mock_deps
        display.show_full.side_effect = OSError("SPI error")
        loop = ProductionLoop(storage, collector, renderer, display)
        loop._run_one_cycle()  # should not raise


class TestStartupReconciliation:

    def test_reconcile_reaggregates_yesterday_on_startup(self, mock_deps):
        """If the service restarts after midnight, yesterday's partial
        summary must be overwritten from raw points."""
        storage, collector, renderer, display = mock_deps
        storage.get_points_for_date.return_value = [MagicMock()]  # has points

        loop = ProductionLoop(storage, collector, renderer, display)

        with patch("src.production.aggregate_daily_summary") as mock_agg:
            with patch("src.api_cloud.optional_backfill") as mock_backfill:
                mock_agg.return_value = MagicMock(samples=42)
                loop._reconcile_yesterday()

        mock_agg.assert_called_once()
        storage.store_daily_summary.assert_called_once()
        mock_backfill.assert_called_once()
        assert mock_backfill.call_args.kwargs.get("skip_today") is True

    def test_reconcile_skips_if_no_points(self, mock_deps):
        """If there are no raw points for yesterday, don't overwrite."""
        storage, collector, renderer, display = mock_deps
        storage.get_points_for_date.return_value = []

        loop = ProductionLoop(storage, collector, renderer, display)

        with patch("src.production.aggregate_daily_summary") as mock_agg:
            with patch("src.api_cloud.optional_backfill"):
                loop._reconcile_yesterday()

        mock_agg.assert_not_called()
        storage.store_daily_summary.assert_not_called()


class TestDayRollover:

    def test_rollover_reaggregates_yesterday(self, mock_deps):
        storage, collector, renderer, display = mock_deps
        yesterday = date.today() - timedelta(days=1)

        loop = ProductionLoop(storage, collector, renderer, display)
        loop._current_date = yesterday  # simulate running since yesterday

        with patch("src.production.aggregate_daily_summary") as mock_agg:
            with patch("src.api_cloud.optional_backfill") as mock_backfill:
                mock_agg.return_value = MagicMock()
                loop._check_day_rollover()

        # Should have fetched yesterday's points and re-aggregated
        storage.get_points_for_date.assert_called()
        mock_agg.assert_called_once()
        storage.store_daily_summary.assert_called_once()
        # Cloud backfill must be called with skip_today=True
        mock_backfill.assert_called_once()
        assert mock_backfill.call_args.kwargs.get("skip_today") is True


class TestRetentionCleanup:

    def test_cleanup_runs_hourly_not_every_cycle(self, mock_deps):
        storage, collector, renderer, display = mock_deps
        loop = ProductionLoop(storage, collector, renderer, display)

        # First call should run cleanup
        loop._maybe_cleanup()
        assert storage.cleanup_old_points.call_count == 1

        # Immediate second call should NOT run cleanup
        loop._maybe_cleanup()
        assert storage.cleanup_old_points.call_count == 1

        # After 1 hour, should run again
        loop._last_cleanup_at -= timedelta(hours=1, seconds=1)
        loop._maybe_cleanup()
        assert storage.cleanup_old_points.call_count == 2


class TestShutdown:

    def test_stop_sets_flag(self, mock_deps):
        storage, collector, renderer, display = mock_deps
        loop = ProductionLoop(storage, collector, renderer, display)
        assert not loop._stopped
        loop.stop()
        assert loop._stopped

    def test_shutdown_order(self, mock_deps):
        storage, collector, renderer, display = mock_deps
        loop = ProductionLoop(storage, collector, renderer, display)
        call_order = []
        display.sleep.side_effect = lambda: call_order.append("display.sleep")
        renderer.close.side_effect = lambda: call_order.append("renderer.close")
        collector.stop.side_effect = lambda: call_order.append("collector.stop")

        loop._shutdown()
        assert call_order == ["display.sleep", "renderer.close", "collector.stop"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv312/bin/pytest tests/test_production.py -v`
Expected: FAIL — `src.production` does not exist.

- [ ] **Step 3: Implement src/production.py**

```python
"""Production loop: collect → render → display → housekeeping."""

from __future__ import annotations

import logging
import signal
import threading
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from PIL import Image

import config
from src.aggregator import aggregate_daily_summary
from src.models import DashboardData
from src.storage import Storage

logger = logging.getLogger(__name__)

# Import optional_backfill lazily to avoid hard dependency on cloud config
def _try_backfill(storage: Storage) -> None:
    try:
        from src.api_cloud import optional_backfill
        optional_backfill(storage, skip_today=True)
    except Exception as exc:
        logger.warning("Rollover cloud backfill failed: %s", exc)


class ProductionLoop:
    """Timer-based production loop for the e-ink dashboard.

    Runs: build_dashboard_data → render → display → housekeeping
    on a fixed cadence (DISPLAY_UPDATE_INTERVAL seconds).
    """

    def __init__(
        self,
        storage: Storage,
        collector,
        renderer,
        display=None,
    ):
        self._storage = storage
        self._collector = collector
        self._renderer = renderer
        self._display = display
        self._stopped = False

        tz = ZoneInfo(config.TIMEZONE)
        self._current_date = datetime.now(tz).date()
        self._last_cleanup_at = datetime.min.replace(tzinfo=tz)  # run cleanup on first cycle
        self._tz = tz

    def run(self) -> None:
        """Main loop. Blocks until stop() is called or a signal is received."""
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        logger.info(
            "Production loop started (interval=%ds)", config.DISPLAY_UPDATE_INTERVAL
        )

        self._reconcile_yesterday()

        try:
            while not self._stopped:
                cycle_start = time.monotonic()
                self._run_one_cycle()
                elapsed = time.monotonic() - cycle_start
                sleep_time = max(0, config.DISPLAY_UPDATE_INTERVAL - elapsed)
                if sleep_time > 0 and not self._stopped:
                    # Sleep in small increments to respond to stop signal quickly
                    end = time.monotonic() + sleep_time
                    while time.monotonic() < end and not self._stopped:
                        time.sleep(min(1.0, end - time.monotonic()))
        finally:
            self._shutdown()

    def stop(self) -> None:
        """Signal the loop to exit gracefully."""
        self._stopped = True

    def _handle_signal(self, signum, frame) -> None:
        logger.info("Received signal %d, stopping...", signum)
        self.stop()

    def _run_one_cycle(self) -> None:
        """Execute one collect → render → display → housekeeping cycle."""
        self._check_day_rollover()

        try:
            # Lazy import to avoid circular dependency (main imports production)
            from main import build_dashboard_data
            data = build_dashboard_data(self._storage, self._collector)
        except Exception:
            logger.exception("Failed to build dashboard data")
            return

        try:
            image = self._renderer.render(data)
        except Exception:
            logger.exception("Renderer failed, skipping display update")
            return

        if self._display is not None:
            try:
                self._display.show_full(image)
            except Exception:
                logger.exception("Display update failed")
                try:
                    self._display.sleep()
                    self._display.wake()
                    logger.info("Display soft-reset succeeded")
                except Exception:
                    logger.exception("Display soft-reset also failed")

        self._maybe_cleanup()

    def _reconcile_yesterday(self) -> None:
        """On startup, re-aggregate yesterday if we have raw points for it.

        Handles the case where the service was down at midnight: yesterday's
        daily_summary row may be partial or missing. Re-aggregation from raw
        points overwrites it with the correct total. Cloud backfill then fills
        any older missing days (with skip_today=True so it does not touch the
        current-day prefix while the collector is already running).
        """
        from datetime import timedelta
        yesterday = self._current_date - timedelta(days=1)
        try:
            points = self._storage.get_points_for_date(yesterday, tz=self._tz)
            if points:
                summary = aggregate_daily_summary(points, yesterday)
                self._storage.store_daily_summary(summary)
                logger.info(
                    "Startup reconciliation: re-aggregated yesterday (%s), %d samples",
                    yesterday, summary.samples,
                )
        except Exception:
            logger.exception("Startup reconciliation failed for %s", yesterday)

        _try_backfill(self._storage)

    def _check_day_rollover(self) -> None:
        """Finalize yesterday's summary when the date changes."""
        today = datetime.now(self._tz).date()
        if today == self._current_date:
            return

        yesterday = self._current_date
        logger.info("Day rollover: %s → %s", yesterday, today)

        try:
            points = self._storage.get_points_for_date(yesterday, tz=self._tz)
            summary = aggregate_daily_summary(points, yesterday)
            if summary.samples > 0:
                self._storage.store_daily_summary(summary)
                logger.info(
                    "Finalized yesterday's summary: %d samples", summary.samples
                )
        except Exception:
            logger.exception("Failed to finalize yesterday's summary")

        _try_backfill(self._storage)
        self._current_date = today

    def _maybe_cleanup(self) -> None:
        """Run retention cleanup at most once per hour."""
        now = datetime.now(self._tz)
        if now - self._last_cleanup_at < timedelta(hours=1):
            return
        try:
            self._storage.cleanup_old_points()
        except Exception:
            logger.exception("Retention cleanup failed")
        self._last_cleanup_at = now

    def _shutdown(self) -> None:
        """Graceful shutdown in specified order."""
        logger.info("Shutting down production loop...")

        if self._display is not None:
            try:
                self._display.sleep()
            except Exception:
                logger.exception("Failed to sleep display during shutdown")

        try:
            self._renderer.close()
        except Exception:
            logger.exception("Failed to close renderer during shutdown")

        try:
            self._collector.stop()
        except Exception:
            logger.exception("Failed to stop collector during shutdown")

        logger.info("Shutdown complete")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv312/bin/pytest tests/test_production.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/production.py tests/test_production.py
git commit -m "Add ProductionLoop with day rollover, cleanup throttle, signal handling"
```

---

## Task 7: Wire --production mode into main.py

Add the `--production` and `--no-display` CLI flags. Enforce mutual exclusivity
with `--mock` and `--export-png`. Add VCOM validation.

**Files:**
- Modify: `main.py:186-218`

- [ ] **Step 1: Write failing test for VCOM validation**

Append to `tests/test_production.py`:

```python
def test_vcom_validation_rejects_empty():
    from main import _validate_vcom
    with pytest.raises(SystemExit):
        _validate_vcom("")


def test_vcom_validation_rejects_non_float():
    from main import _validate_vcom
    with pytest.raises(SystemExit):
        _validate_vcom("notanumber")


def test_vcom_validation_rejects_positive():
    from main import _validate_vcom
    with pytest.raises(SystemExit):
        _validate_vcom("1.5")


def test_vcom_validation_accepts_valid():
    from main import _validate_vcom
    result = _validate_vcom("-1.48")
    assert result == -1.48
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv312/bin/pytest tests/test_production.py::test_vcom_validation_rejects_empty -v`
Expected: FAIL — `_validate_vcom` not defined.

- [ ] **Step 3: Implement VCOM validation and --production mode in main.py**

Add before the `main()` function:

```python
def _validate_vcom(vcom_str: str) -> float:
    """Validate EPAPER_VCOM. Exit with error if invalid."""
    if not vcom_str.strip():
        logger.error(
            "EPAPER_VCOM not set. Check the label on the panel ribbon cable "
            "and set EPAPER_VCOM in .env.local (e.g. EPAPER_VCOM=-1.48)."
        )
        sys.exit(1)
    try:
        vcom = float(vcom_str)
    except ValueError:
        logger.error("EPAPER_VCOM='%s' is not a valid number.", vcom_str)
        sys.exit(1)
    if vcom > 0 or vcom < -5.0:
        logger.error(
            "EPAPER_VCOM=%.2f is outside expected range (-5.0 to 0.0). "
            "Check the panel label.", vcom
        )
        sys.exit(1)
    return vcom
```

Add `run_production_mode`:

```python
def run_production_mode(no_display: bool, theme: str | None, lang: str | None):
    """Production mode: collect → render → display loop."""
    from src.renderer_png import PersistentPlaywrightRenderer
    from src.production import ProductionLoop

    if not no_display:
        vcom = _validate_vcom(config.EPAPER_VCOM)

    storage, collector = create_live_storage_and_collector()
    renderer = PersistentPlaywrightRenderer(theme=theme, lang=lang)

    display = None
    if not no_display:
        from src.epaper import EpaperDisplay
        display = EpaperDisplay(vcom=vcom)

    loop = ProductionLoop(storage, collector, renderer, display)
    loop.run()
```

Update `main()` to add args and enforce mutual exclusivity:

```python
def main():
    parser = argparse.ArgumentParser(description="Solar E-Ink Dashboard")
    parser.add_argument("--mock", action="store_true",
                        help="Mock-Daten für UI-Entwicklung verwenden")
    parser.add_argument("--production", action="store_true",
                        help="Production mode: collect → render → e-ink display loop")
    parser.add_argument("--export-png", type=str, default="",
                        help="Dashboard einmalig als PNG exportieren")
    parser.add_argument("--no-display", action="store_true",
                        help="Production mode without e-paper hardware (headless)")
    parser.add_argument("--port", type=int, default=config.WEB_PORT,
                        help="Web-Preview Port (default: 8080)")
    parser.add_argument("--theme", type=str, default="",
                        help="Theme override: light|dark")
    parser.add_argument("--lang", type=str, default="",
                        help="Language override: en|de|fr|it")
    args = parser.parse_args()

    # --production is mutually exclusive with --mock and bare live mode,
    # but --mock and --export-png CAN combine (existing documented workflow:
    # `main.py --mock --export-png out/dashboard.png`).
    if args.production and args.mock:
        parser.error("--production and --mock are mutually exclusive")
    if args.production and args.export_png:
        parser.error("--production and --export-png are mutually exclusive")

    if args.export_png:
        export_once(
            args.mock, args.export_png,
            theme=args.theme or None, lang=args.lang or None,
        )
        return

    if args.production:
        logger.info("Starting in production mode")
        run_production_mode(
            args.no_display,
            theme=args.theme or None,
            lang=args.lang or None,
        )
        return

    if args.mock:
        logger.info("Starte im Mock-Modus")
        run_mock_mode(args.port)
    else:
        logger.info("Starte im Live-Modus")
        run_live_mode(args.port)
```

The `--mock --export-png` combination is preserved (existing README workflow).
Only `--production` is mutually exclusive with the other modes.

- [ ] **Step 4: Run tests to verify**

Run: `./.venv312/bin/pytest tests/test_production.py -v`
Expected: all pass, including VCOM validation tests.

- [ ] **Step 5: Verify CLI help and mutual exclusivity**

Run: `./.venv312/bin/python main.py --help`
Run: `./.venv312/bin/python main.py --mock --production 2>&1` — should error.

- [ ] **Step 6: Run all tests**

Run: `./.venv312/bin/pytest tests/ -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_production.py
git commit -m "Add --production and --no-display CLI modes with VCOM validation"
```

---

## Task 8: Hardware bring-up script

Standalone script for first-time IT8951 validation on the Pi. Not part of the
production runtime — used once to confirm hardware works.

**Files:**
- Create: `scripts/epaper_test.py`

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""E-Paper hardware bring-up test script.

Run this on the Raspberry Pi to validate IT8951 connectivity before
deploying the full production dashboard.

Usage:
    python scripts/epaper_test.py --vcom -1.48
    python scripts/epaper_test.py --vcom -1.48 --image test.png
    python scripts/epaper_test.py --vcom -1.48 --partial
    python scripts/epaper_test.py --vcom -1.48 --sleep-wake
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    parser = argparse.ArgumentParser(description="E-Paper IT8951 bring-up test")
    parser.add_argument("--vcom", type=float, required=True,
                        help="Panel VCOM voltage (e.g. -1.48)")
    parser.add_argument("--image", type=str, default="",
                        help="Path to a PNG to display full-screen")
    parser.add_argument("--partial", action="store_true",
                        help="Test partial DU update on a 200x200 region")
    parser.add_argument("--sleep-wake", action="store_true",
                        help="Test sleep → wake → clear cycle")
    args = parser.parse_args()

    print(f"Initializing IT8951 with VCOM={args.vcom}...")

    try:
        from IT8951.display import AutoEPDDisplay
        from IT8951 import constants
    except ImportError:
        print("ERROR: IT8951 library not installed.")
        print("Install: git clone https://github.com/GregDMeyer/IT8951.git && pip install ./IT8951/[rpi]")
        sys.exit(1)

    display = AutoEPDDisplay(vcom=args.vcom)
    print(f"Display: {display.width}x{display.height}")

    from PIL import Image

    if args.image:
        print(f"Displaying {args.image} (full GC16)...")
        img = Image.open(args.image).convert("L")
        img = img.resize((display.width, display.height), Image.LANCZOS)
        display.frame_buf.paste(img)
        display.draw_full(constants.DisplayModes.GC16)
        print("Done.")

    elif args.partial:
        print("Testing partial DU update (200x200 gray square at 100,100)...")
        gray = Image.new("L", (200, 200), color=128)
        display.frame_buf.paste(gray, (100, 100))
        display.draw_partial(constants.DisplayModes.DU)
        print("Done. Check for ghosting artifacts.")

    elif args.sleep_wake:
        print("Clearing display...")
        white = Image.new("L", (display.width, display.height), 255)
        display.frame_buf.paste(white)
        display.draw_full(constants.DisplayModes.GC16)
        print("Sleeping display...")
        display.epd.sleep()
        time.sleep(3)
        print("Waking display...")
        display.epd.run()
        print("Clearing again after wake...")
        display.frame_buf.paste(white)
        display.draw_full(constants.DisplayModes.GC16)
        print("Done.")

    else:
        print("Clearing display (full white GC16)...")
        white = Image.new("L", (display.width, display.height), 255)
        display.frame_buf.paste(white)
        display.draw_full(constants.DisplayModes.GC16)
        print("Done. Display should be white.")

    print("\nBring-up complete. Put display to sleep.")
    display.epd.sleep()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
chmod +x scripts/epaper_test.py
git add scripts/epaper_test.py
git commit -m "Add IT8951 hardware bring-up test script"
```

---

## Task 9: Deployment assets

systemd service file, Pi setup script, and pinned requirements.

**Files:**
- Create: `deploy/solar-dashboard.service`
- Create: `scripts/setup-pi.sh`
- Create: `requirements-pi.txt`

- [ ] **Step 1: Create systemd service file**

```ini
# deploy/solar-dashboard.service
[Unit]
Description=Solar E-Ink Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/solar-eink-dashboard
EnvironmentFile=/home/pi/solar-eink-dashboard/.env.local
ExecStart=/home/pi/solar-eink-dashboard/.venv312/bin/python main.py --production
Restart=on-failure
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Create setup script**

```bash
#!/usr/bin/env bash
# scripts/setup-pi.sh — First-time Raspberry Pi 5 setup for Solar E-Ink Dashboard
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$REPO_DIR/.venv312"
IT8951_COMMIT="master"  # pin to a specific commit after testing

echo "=== Solar E-Ink Dashboard — Pi Setup ==="

# 1. Enable SPI
echo "Enabling SPI..."
if ! grep -q "^dtparam=spi=on" /boot/firmware/config.txt 2>/dev/null; then
    echo "dtparam=spi=on" | sudo tee -a /boot/firmware/config.txt
    echo "SPI enabled. A reboot will be needed."
fi

# 2. System dependencies
echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y \
    python3.12 python3.12-dev python3.12-venv \
    gcc make cython3 \
    libatlas-base-dev \
    libgbm1 libnss3 libxss1 libasound2

# 3. Python venv
echo "Creating Python venv..."
python3.12 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$REPO_DIR/requirements-pi.txt"
# Cython is needed to build IT8951's SPI extension in the next step
"$VENV_DIR/bin/pip" install cython

# 4. IT8951 from source
echo "Installing IT8951 from source..."
IT8951_TMP=$(mktemp -d)
git clone https://github.com/GregDMeyer/IT8951.git "$IT8951_TMP"
(cd "$IT8951_TMP" && git checkout "$IT8951_COMMIT")
"$VENV_DIR/bin/pip" install "$IT8951_TMP/[rpi]"
rm -rf "$IT8951_TMP"

# 5. Playwright
echo "Installing Playwright Chromium..."
"$VENV_DIR/bin/python" -m playwright install chromium

# 6. .env.local
if [ ! -f "$REPO_DIR/.env.local" ]; then
    echo "Creating .env.local..."
    cat > "$REPO_DIR/.env.local" <<'ENVEOF'
# Solar Manager gateway URL (required)
SM_LOCAL_BASE_URL=http://192.168.1.XXX

# E-Paper VCOM voltage (check panel ribbon cable label)
EPAPER_VCOM=-1.48

# Optional: display update interval in seconds (default: 60)
# DISPLAY_UPDATE_INTERVAL=60
ENVEOF
    echo "IMPORTANT: Edit .env.local with your gateway URL and panel VCOM."
fi

# 7. systemd service
echo "Installing systemd service..."
sudo cp "$REPO_DIR/deploy/solar-dashboard.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable solar-dashboard
echo "Service installed. Start with: sudo systemctl start solar-dashboard"

echo ""
echo "=== Setup complete ==="
echo "Next steps:"
echo "  1. Edit .env.local with your gateway URL and VCOM"
echo "  2. Test hardware: $VENV_DIR/bin/python scripts/epaper_test.py --vcom YOUR_VCOM"
echo "  3. Start service: sudo systemctl start solar-dashboard"
echo "  4. Check logs: journalctl -u solar-dashboard -f"
```

- [ ] **Step 3: Create requirements-pi.txt**

Generate pinned versions from the current venv:

Run: `./.venv312/bin/pip freeze | grep -iE "^(pillow|numpy|requests|websocket-client|flask|playwright|jinja2|markupsafe|werkzeug|itsdangerous|blinker|click|certifi|charset-normalizer|idna|urllib3|greenlet|pyee)" > requirements-pi.txt`

If that's not available, create a reasonable starting point:

```
pillow>=10.0
numpy>=1.26
requests>=2.31
websocket-client>=1.6
flask>=3.0
playwright>=1.40
jinja2>=3.1
cython>=3.0
```

Note: `cython` is a build-time dependency for IT8951's SPI extension. IT8951
itself is installed from source in `setup-pi.sh` (not listed here).

- [ ] **Step 4: Commit**

```bash
chmod +x scripts/setup-pi.sh
git add deploy/solar-dashboard.service scripts/setup-pi.sh requirements-pi.txt
git commit -m "Add deployment assets: systemd unit, setup script, Pi requirements"
```

---

## Task 10: Font bundling

Bundle a deterministic font for reproducible rendering across Mac and Pi.

**Files:**
- Modify: `src/dashboard_document.py`
- Modify: `src/static/dashboard.css:60`
- Create: `src/static/fonts/` (font files)

- [ ] **Step 1: Select and validate font candidate**

Run the dashboard with mock mode. Take a screenshot. Then pick a candidate
font (Inter, IBM Plex Sans, Source Sans 3) and compare:

Run: `./.venv312/bin/python main.py --mock --export-png out/before-font.png`

Download the candidate font woff2 files (regular + bold, 2 weights). Generate
the base64 `@font-face` CSS block. Place the `.woff2` files in `src/static/fonts/`
for reference.

- [ ] **Step 2: Create font embedding helper**

In `src/dashboard_document.py`, add a function that returns the `@font-face`
CSS block with embedded data URLs:

```python
_FONT_DIR = _SRC_DIR / "static" / "fonts"

def _embedded_font_css() -> str:
    """Return @font-face CSS with base64-embedded woff2 fonts."""
    css_parts = []
    for weight_name, weight_value, filename in [
        ("Regular", "400", "chosen-font-regular.woff2"),
        ("Bold", "700", "chosen-font-bold.woff2"),
    ]:
        font_path = _FONT_DIR / filename
        if not font_path.exists():
            return ""  # no fonts bundled yet
        import base64
        b64 = base64.b64encode(font_path.read_bytes()).decode("ascii")
        css_parts.append(
            f"@font-face {{\n"
            f"  font-family: 'DashboardFont';\n"
            f"  font-weight: {weight_value};\n"
            f"  font-style: normal;\n"
            f"  src: url('data:font/woff2;base64,{b64}') format('woff2');\n"
            f"}}\n"
        )
    return "\n".join(css_parts)
```

- [ ] **Step 3: Inject font CSS into standalone export**

Update `render_dashboard_standalone()`:

```python
def render_dashboard_standalone(context: dict[str, object]) -> str:
    css = _STATIC_CSS.read_text(encoding="utf-8")
    font_css = _embedded_font_css()
    if font_css:
        css = font_css + "\n" + css
    return render_dashboard_html(context, embedded_css=css)
```

- [ ] **Step 4: Update font-family in dashboard.css**

In `src/static/dashboard.css`, line 60:

```css
font-family: "DashboardFont", "Helvetica Neue", Helvetica, Arial, sans-serif;
```

- [ ] **Step 5: Visual validation**

Run: `./.venv312/bin/python main.py --mock --export-png out/after-font.png`

Compare `out/before-font.png` and `out/after-font.png`:
- Numeric columns still aligned (tabular figures)
- No line-break changes in flow labels, axis labels, weekday labels
- Overall layout unchanged

If there are problems, try a different font candidate and repeat.

- [ ] **Step 6: Run all tests**

Run: `./.venv312/bin/pytest tests/ -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/static/fonts/ src/dashboard_document.py src/static/dashboard.css
git commit -m "Bundle deterministic font for reproducible rendering across platforms"
```

---

## Task 11: Final integration test

Verify the entire production path works end-to-end in headless mode (no
hardware, but the full data→render→loop pipeline).

**Files:**
- No new files.

- [ ] **Step 1: Run production mode headless with mock data**

This verifies the full pipeline without hardware:

Run: `./.venv312/bin/python main.py --mock --export-png out/integration-test.png`

Verify the PNG exists and is 1872x1404 grayscale.

- [ ] **Step 2: Run all tests**

Run: `./.venv312/bin/pytest tests/ -v`
Expected: all pass.

- [ ] **Step 3: Verify --production --no-display starts and stops cleanly**

This requires a live gateway or needs to be tested with mock. Test that the
CLI arg parsing works:

Run: `./.venv312/bin/python main.py --production --no-display &` then send SIGTERM.

- [ ] **Step 4: Commit any fixes from integration testing**

```bash
git add -u
git commit -m "Fix integration issues from end-to-end testing"
```

---

## Summary

| Task | What | Commits |
|------|------|---------|
| 1 | Extract `quantize_image()` helper | 1 |
| 2 | Add production config vars | 1 |
| 3 | `PersistentPlaywrightRenderer` + `OneShotPlaywrightRenderer` | 1 |
| 4 | `EpaperDisplay` module | 1 |
| 5 | Parameterize `optional_backfill(skip_today=)` | 1 |
| 6 | `ProductionLoop` | 1 |
| 7 | Wire `--production` into `main.py` | 1 |
| 8 | Hardware bring-up script | 1 |
| 9 | Deployment assets | 1 |
| 10 | Font bundling | 1 |
| 11 | Integration test | 0-1 |

Total: ~10-11 commits, 6 new files, 5 modified files.
