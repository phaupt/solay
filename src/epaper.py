"""E-Paper display driver wrapping the IT8951 library.

Provides a high-level interface for the Waveshare 7.8" e-paper display
(IT8951 controller) used by the solar dashboard on Raspberry Pi.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
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

    def __init__(self, vcom: float, full_refresh_interval: int = 1) -> None:
        """Initialise the IT8951 display.

        Args:
            vcom: VCOM voltage (e.g. -1.48).  Read from the IT8951 controller
                  or the FPC cable label on the panel.
            full_refresh_interval: Do a full GC16 refresh (black flash) every
                  N updates.  Between full refreshes, GL16 is used for
                  flicker-free grayscale updates.  Set to 1 to always use
                  GC16 (default for backwards compat).

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
        self._full_refresh_interval = max(1, full_refresh_interval)
        self._updates_since_full = 0
        self._prev_frame: np.ndarray | None = None
        logger.info(
            "Display ready: %dx%d (full refresh every %d updates)",
            self._display.width, self._display.height, self._full_refresh_interval,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show(self, image: Image.Image) -> None:
        """Update the display, choosing the waveform automatically.

        Every *full_refresh_interval* updates a GC16 full refresh (brief
        black flash) is used to clear accumulated ghosting.  All other
        updates compare the new frame against the previous one, split the
        changed area into independent tiles, and update only those tiles
        with GL16 — static regions (gaps between panels, backgrounds)
        are never touched and therefore never flicker.
        """
        self._ensure_awake()
        prepared = self._prepare_image(image)

        self._updates_since_full += 1
        if self._updates_since_full >= self._full_refresh_interval:
            self._display.frame_buf.paste(prepared)
            self._display.draw_full(constants.DisplayModes.GC16)
            self._prev_frame = np.array(prepared)
            self._updates_since_full = 0
            logger.debug("Full GC16 refresh complete")
        else:
            new_frame = np.array(prepared)
            if self._prev_frame is not None:
                tiles = self._find_changed_tiles(self._prev_frame, new_frame)
            else:
                tiles = [(0, 0, new_frame.shape[1], new_frame.shape[0])]

            self._display.frame_buf.paste(prepared)

            if not tiles:
                logger.debug("No changed tiles, skipping display update")
            else:
                for x, y, w, h in tiles:
                    tile_img = prepared.crop((x, y, x + w, y + h))
                    self._display.update(
                        self._display._get_frame_buf().crop(
                            (x, y, x + w, y + h)
                        ).tobytes(),
                        (x, y), (w, h),
                        constants.DisplayModes.GL16,
                    )
                logger.debug("Updated %d tile(s) with GL16 (next full in %d)",
                             len(tiles),
                             self._full_refresh_interval - self._updates_since_full)

            self._prev_frame = new_frame

    def show_full(self, image: Image.Image) -> None:
        """Full-screen refresh using GC16 waveform (always flashes).

        Prefer :meth:`show` for normal dashboard updates — it
        automatically alternates between GL16 and GC16.
        """
        self._ensure_awake()
        prepared = self._prepare_image(image)
        self._display.frame_buf.paste(prepared)
        self._display.draw_full(constants.DisplayModes.GC16)
        self._updates_since_full = 0
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

    @staticmethod
    def _find_changed_tiles(
        prev: np.ndarray, curr: np.ndarray, min_gap: int = 8
    ) -> list[tuple[int, int, int, int]]:
        """Find independent rectangular tiles that contain changed pixels.

        Scans columns for changed regions, then for each region scans rows
        to get the tight vertical bounds.  Regions separated by at least
        *min_gap* unchanged columns become separate tiles so that static
        areas (panel gaps) are never included in an update.

        Returns a list of (x, y, w, h) tuples, each aligned to 4-pixel
        boundaries as required by the IT8951 controller.
        """
        diff = prev != curr
        # Columns that have at least one changed pixel
        col_has_change = np.any(diff, axis=0)

        # Find contiguous runs of changed columns, splitting on gaps
        tiles: list[tuple[int, int, int, int]] = []
        in_run = False
        run_start = 0

        for c in range(len(col_has_change) + 1):
            if c < len(col_has_change) and col_has_change[c]:
                if not in_run:
                    run_start = c
                    in_run = True
            else:
                if in_run:
                    # Check if gap ahead is large enough to split
                    gap_end = c
                    while gap_end < len(col_has_change) and not col_has_change[gap_end]:
                        gap_end += 1
                    if c < len(col_has_change) and (gap_end - c) < min_gap:
                        continue  # gap too small, keep extending run

                    # Find vertical bounds for this column range
                    region_diff = diff[:, run_start:c]
                    row_has_change = np.any(region_diff, axis=1)
                    rows = np.where(row_has_change)[0]
                    if len(rows) > 0:
                        y0 = int(rows[0])
                        y1 = int(rows[-1]) + 1
                        x0 = run_start
                        x1 = c
                        # Align to 4-pixel boundaries (IT8951 requirement)
                        x0 = (x0 // 4) * 4
                        y0 = (y0 // 4) * 4
                        x1 = min(((x1 + 3) // 4) * 4, curr.shape[1])
                        y1 = min(((y1 + 3) // 4) * 4, curr.shape[0])
                        tiles.append((x0, y0, x1 - x0, y1 - y0))

                    in_run = False

        return tiles
