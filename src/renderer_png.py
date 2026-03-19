"""PNG renderers using Playwright to screenshot the HTML dashboard.

Provides two implementations of the ``RendererPNG`` protocol:

* ``PersistentPlaywrightRenderer`` -- keeps a single Chromium instance alive
  across renders for low-latency repeated use (e.g. the render loop on the Pi).
* ``OneShotPlaywrightRenderer`` -- launches a fresh browser per render call,
  suitable for CLI one-off exports.
"""

from __future__ import annotations

import asyncio
import io
import logging
import threading
from concurrent.futures import Future
from pathlib import Path
from typing import Protocol, runtime_checkable

from PIL import Image

import config
from src.dashboard_document import render_dashboard_standalone
from src.export_dashboard import quantize_image
from src.html_renderer import build_dashboard_context
from src.models import DashboardData

log = logging.getLogger(__name__)

_SENTINEL = object()

_DEFAULT_TIMEOUT = 30  # seconds
_STARTUP_TIMEOUT = 60  # seconds — fail fast if Chromium won't launch


class RendererTimeout(Exception):
    """Raised when a render call exceeds the configured timeout."""


class RendererStartupError(Exception):
    """Raised when the background Chromium browser fails to start."""


@runtime_checkable
class RendererPNG(Protocol):
    """Protocol for PNG dashboard renderers."""

    def render(self, data: DashboardData) -> Image.Image: ...

    def render_to_file(self, data: DashboardData, path: str | Path) -> None: ...

    def close(self) -> None: ...


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _build_html(data: DashboardData, theme: str | None, lang: str | None) -> str:
    context = build_dashboard_context(data, theme=theme, lang=lang, refresh_seconds=0)
    return render_dashboard_standalone(context)


async def _render_screenshot(
    page: object,
    html: str,
) -> bytes:
    """Set content on *page* and return PNG screenshot bytes."""
    await page.set_content(html, wait_until="load")  # type: ignore[attr-defined]
    await page.evaluate("document.fonts.ready")  # type: ignore[attr-defined]
    return await page.screenshot(type="png", full_page=False)  # type: ignore[attr-defined]


def _bytes_to_image(png_bytes: bytes, grayscale_levels: int) -> Image.Image:
    img = Image.open(io.BytesIO(png_bytes))
    return quantize_image(img, grayscale_levels)


# ---------------------------------------------------------------------------
# PersistentPlaywrightRenderer
# ---------------------------------------------------------------------------


class PersistentPlaywrightRenderer:
    """Keeps a single Chromium browser alive in a background thread.

    The browser is launched once in ``__init__`` and reused for every
    ``render()`` call.  Communication with the async event loop running in
    the daemon thread happens via ``loop.call_soon_threadsafe`` and
    ``concurrent.futures.Future``.
    """

    def __init__(
        self,
        *,
        theme: str | None = None,
        lang: str | None = None,
        grayscale_levels: int | None = None,
        timeout: float | None = None,
    ) -> None:
        self._theme = theme
        self._lang = lang
        self._grayscale_levels = (
            config.EXPORT_GRAYSCALE_LEVELS if grayscale_levels is None else grayscale_levels
        )
        self._timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT

        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue | None = None  # type: ignore[type-arg]
        self._ready = threading.Event()
        self._startup_error: BaseException | None = None
        self._consecutive_failures = 0
        self._closed = False

        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=_STARTUP_TIMEOUT):
            self._closed = True
            self._cleanup_thread()
            raise RendererStartupError(
                f"Chromium browser did not start within {_STARTUP_TIMEOUT}s"
            )
        if self._startup_error is not None:
            self._closed = True
            self._cleanup_thread()
            raise RendererStartupError(
                f"Chromium browser startup failed: {self._startup_error}"
            ) from self._startup_error

    # -- background thread ----------------------------------------------------

    def _run_loop(self) -> None:
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._worker())
        except Exception as exc:
            self._startup_error = exc
            self._ready.set()  # unblock the waiting __init__

    async def _worker(self) -> None:
        from playwright.async_api import async_playwright

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
                    html = _build_html(data, self._theme, self._lang)
                    png_bytes = await _render_screenshot(page, html)
                    img = _bytes_to_image(png_bytes, self._grayscale_levels)
                    future.set_result(img)
                    self._consecutive_failures = 0
                except Exception as exc:
                    self._consecutive_failures += 1
                    future.set_exception(exc)

            await browser.close()

    # -- public API -----------------------------------------------------------

    def render(self, data: DashboardData) -> Image.Image:
        if self._closed:
            raise RuntimeError("Renderer is closed")

        future: Future[Image.Image] = Future()
        assert self._loop is not None
        self._loop.call_soon_threadsafe(self._queue.put_nowait, (data, future))

        try:
            return future.result(timeout=self._timeout)
        except TimeoutError as exc:
            raise RendererTimeout(
                f"Render did not complete within {self._timeout}s"
            ) from exc

    def render_to_file(self, data: DashboardData, path: str | Path) -> None:
        img = self.render(data)
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(out))

    def _cleanup_thread(self) -> None:
        """Best-effort shutdown of the background thread and event loop."""
        if self._loop is not None and self._queue is not None:
            try:
                self._loop.call_soon_threadsafe(self._queue.put_nowait, _SENTINEL)
            except RuntimeError:
                pass  # loop already closed
        if self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except RuntimeError:
                pass
        self._thread.join(timeout=5)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._cleanup_thread()


# ---------------------------------------------------------------------------
# OneShotPlaywrightRenderer
# ---------------------------------------------------------------------------


class OneShotPlaywrightRenderer:
    """Launches a fresh Chromium browser for every ``render()`` call."""

    def __init__(
        self,
        *,
        theme: str | None = None,
        lang: str | None = None,
        grayscale_levels: int | None = None,
        timeout: float | None = None,
    ) -> None:
        self._theme = theme
        self._lang = lang
        self._grayscale_levels = (
            config.EXPORT_GRAYSCALE_LEVELS if grayscale_levels is None else grayscale_levels
        )
        self._timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT

    async def _do_render(self, data: DashboardData) -> Image.Image:
        from playwright.async_api import async_playwright

        html = _build_html(data, self._theme, self._lang)

        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(
                viewport={
                    "width": config.DISPLAY_WIDTH,
                    "height": config.DISPLAY_HEIGHT,
                },
                device_scale_factor=1,
            )
            png_bytes = await _render_screenshot(page, html)
            await browser.close()

        return _bytes_to_image(png_bytes, self._grayscale_levels)

    def render(self, data: DashboardData) -> Image.Image:
        return asyncio.run(self._do_render(data))

    def render_to_file(self, data: DashboardData, path: str | Path) -> None:
        img = self.render(data)
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(out))

    def close(self) -> None:
        pass  # no-op: nothing to tear down
