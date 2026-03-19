"""E-Paper display driver wrapping the IT8951 library.

Provides a high-level interface for the Waveshare 7.8" e-paper display
(IT8951 controller) used by the solar dashboard on Raspberry Pi.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    from IT8951.display import AutoEPDDisplay as _AutoEPDDisplay

logger = logging.getLogger(__name__)

# Try importing IT8951 at module level.  On dev machines (x86, no SPI)
# the library is unavailable, so we let callers know via the flag.
_HAS_IT8951 = False
try:
    from IT8951.display import AutoEPDDisplay  # type: ignore[import-untyped]
    from IT8951 import constants  # type: ignore[import-untyped]

    _HAS_IT8951 = True
except ImportError:
    AutoEPDDisplay = None  # type: ignore[assignment,misc]
    constants = None  # type: ignore[assignment]


class EpaperDisplay:
    """High-level wrapper around the IT8951 e-paper controller."""

    def __init__(self, vcom: float) -> None:
        """Initialise the IT8951 display.

        Args:
            vcom: VCOM voltage from the FPC cable label (e.g. -1.48).

        Raises:
            RuntimeError: If the IT8951 library is not installed.
        """
        if not _HAS_IT8951:
            raise RuntimeError(
                "IT8951 library is not installed. "
                "Install it with: pip install IT8951"
            )

        logger.info("Initialising e-paper display with VCOM=%.2f", vcom)
        self._display: _AutoEPDDisplay = AutoEPDDisplay(vcom=vcom)
        self._sleeping = False
        self._closed = False
        logger.info(
            "Display ready: %dx%d", self._display.width, self._display.height
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_full(self, image: Image.Image) -> None:
        """Full-screen refresh using GC16 waveform.

        The image is converted to 8-bit grayscale and resized to the
        display dimensions if necessary.
        """
        self._ensure_awake()
        prepared = self._prepare_image(image)
        self._display.frame_buf.paste(prepared)
        self._display.draw_full(constants.DisplayModes.GC16)
        logger.debug("Full refresh complete")

    def show_partial(
        self, image: Image.Image, x: int, y: int, w: int, h: int
    ) -> None:
        """Partial refresh of a rectangular region using DU waveform.

        Args:
            image: Source image (will be cropped/converted as needed).
            x: Left edge of the update region on the display.
            y: Top edge of the update region on the display.
            w: Width of the update region.
            h: Height of the update region.
        """
        self._ensure_awake()
        img = image.convert("L")
        if img.size != (w, h):
            img = img.resize((w, h), Image.LANCZOS)
        self._display.frame_buf.paste(img, (x, y))
        self._display.draw_partial(constants.DisplayModes.DU)
        logger.debug("Partial refresh at (%d,%d) %dx%d complete", x, y, w, h)

    def clear(self) -> None:
        """Fill the display with white and do a full GC16 refresh."""
        self._ensure_awake()
        white = Image.new(
            "L", (self._display.width, self._display.height), 255
        )
        self._display.frame_buf.paste(white)
        self._display.draw_full(constants.DisplayModes.GC16)
        logger.info("Display cleared")

    def sleep(self) -> None:
        """Put the display controller into low-power sleep."""
        if self._sleeping:
            return
        try:
            self._display.epd.sleep()
            self._sleeping = True
            logger.info("Display entered sleep mode")
        except Exception:
            logger.exception("Failed to enter sleep mode")

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
        """Release the display (idempotent).

        Puts the controller to sleep.  Safe to call multiple times.
        """
        if self._closed:
            return
        self._closed = True
        logger.info("Closing e-paper display")
        self.sleep()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_awake(self) -> None:
        """Auto-wake if the display is currently sleeping."""
        if self._sleeping:
            self.wake()

    def _prepare_image(self, image: Image.Image) -> Image.Image:
        """Convert and resize an image for the display."""
        img = image.convert("L")
        target = (self._display.width, self._display.height)
        if img.size != target:
            img = img.resize(target, Image.LANCZOS)
        return img
