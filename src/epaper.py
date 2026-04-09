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
        updates compare the new frame against the previous one, expand
        the changed regions along the surrounding content so whole text
        lines re-anchor together, and update those tiles with GL16 —
        static regions (gaps between panels, backgrounds) are never
        touched and therefore never flicker.
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
        prev: np.ndarray,
        curr: np.ndarray,
        min_gap: int = 8,
        content_threshold: int = 240,
        content_max_gap: int = 24,
        v_pad: int = 16,
    ) -> list[tuple[int, int, int, int]]:
        """Find rectangular tiles to partial-refresh.

        Two-stage algorithm:

        1. **Tight bounding boxes from the diff.** Walk columns for
           changed runs (splitting on gaps of at least ``min_gap``
           unchanged columns), then scan rows to get the tight
           vertical bounds of each run.

        2. **Content-aware expansion.** Each tight tile is expanded
           horizontally along the previous frame's content row-band so
           a single-glyph change (e.g. the minute digit in
           "Letztes Update HH:MM") pulls in the rest of its visible
           text line.  Vertically, a small fixed pad catches ascenders
           and descenders of neighbouring glyphs.

        Without step 2, repeated GL16 partial updates touch only the
        pixels that actually change.  Adjacent static glyphs slowly
        drift toward lighter gray between full GC16 refreshes,
        producing visible darkness inconsistency inside a single text
        line.  Expanding to the full content run lets the whole logical
        element re-anchor together on every update.

        Args:
            prev: Previous frame, shape ``(H, W)``, uint8 grayscale.
            curr: Current frame, same shape.
            min_gap: Unchanged-column threshold that splits changed
                runs into separate tight tiles (stage 1).
            content_threshold: Pixels strictly darker than this count
                as foreground "content" during horizontal walk.
                Tuned for the default light-theme dashboard (panel
                background ~250, text ~0-80).
            content_max_gap: Maximum blank span the horizontal walk
                will bridge.  Large enough to cross inter-word spaces
                in 38 px Inter (~20 px) but small enough to stop at
                panel padding (~40+ px).
            v_pad: Fixed vertical padding added above/below the tight
                y-range to capture full line-height of the surrounding
                text.

        Returns:
            List of ``(x, y, w, h)`` tuples, each aligned to 4-pixel
            boundaries as required by the IT8951 controller.
        """
        H, W = curr.shape[:2]
        diff = prev != curr

        # --- Stage 1: tight tiles from the diff. ---
        col_has_change = np.any(diff, axis=0)
        n = len(col_has_change)
        tight: list[list[int]] = []
        in_run = False
        run_start = 0

        for c in range(n + 1):
            if c < n and col_has_change[c]:
                if not in_run:
                    run_start = c
                    in_run = True
                continue

            if not in_run:
                continue

            # Check if gap ahead is large enough to split the run.
            gap_end = c
            while gap_end < n and not col_has_change[gap_end]:
                gap_end += 1
            if c < n and (gap_end - c) < min_gap:
                continue  # gap too small, keep extending run

            region_diff = diff[:, run_start:c]
            row_has_change = np.any(region_diff, axis=1)
            rows = np.where(row_has_change)[0]
            if len(rows) > 0:
                y0 = int(rows[0])
                y1 = int(rows[-1]) + 1
                tight.append([run_start, y0, c, y1])

            in_run = False

        if not tight:
            return []

        # --- Stage 2: content-aware expansion per tile. ---
        expanded: list[list[int]] = []
        for x0, y0, x1, y1 in tight:
            expanded.append(list(EpaperDisplay._expand_tile_to_content(
                x0, y0, x1, y1,
                prev,
                content_threshold=content_threshold,
                max_gap=content_max_gap,
                v_pad=v_pad,
            )))

        # --- Stage 3: merge overlapping/touching rects to fixpoint. ---
        merged = EpaperDisplay._merge_rects(expanded)

        # --- Stage 4: 4-pixel alignment (IT8951 requirement). ---
        result: list[tuple[int, int, int, int]] = []
        for x0, y0, x1, y1 in merged:
            x0a = (x0 // 4) * 4
            y0a = (y0 // 4) * 4
            x1a = min(((x1 + 3) // 4) * 4, W)
            y1a = min(((y1 + 3) // 4) * 4, H)
            result.append((x0a, y0a, x1a - x0a, y1a - y0a))
        return result

    @staticmethod
    def _expand_tile_to_content(
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        prev: np.ndarray,
        content_threshold: int,
        max_gap: int,
        v_pad: int,
    ) -> tuple[int, int, int, int]:
        """Expand a tight tile outward along the surrounding content.

        Vertical extent is widened by a fixed ``v_pad`` (enough for
        ascenders/descenders at the dashboard's font sizes).
        Horizontal extent is widened by walking the previous frame's
        content columns in the expanded y-band until a blank run
        longer than ``max_gap`` is hit, or the frame edge is reached.
        The walk bridges glyph kerning and inter-word spaces but stops
        at panel padding.

        Returns half-open ``(x0, y0, x1, y1)`` clamped to frame bounds.
        """
        H, W = prev.shape[:2]

        ny0 = max(0, y0 - v_pad)
        ny1 = min(H, y1 + v_pad)
        if ny1 <= ny0:
            return x0, y0, x1, y1

        row_band = prev[ny0:ny1]
        col_has_content = np.any(row_band < content_threshold, axis=0)

        nx0 = EpaperDisplay._walk_outward_min(x0, col_has_content, max_gap)
        nx1 = EpaperDisplay._walk_outward_max(x1, col_has_content, max_gap)
        # Safety clamp in case a degenerate walk returned something
        # outside the frame.
        nx0 = max(0, nx0)
        nx1 = min(W, nx1)
        return nx0, ny0, nx1, ny1

    @staticmethod
    def _walk_outward_min(
        start: int, has_content: np.ndarray, max_gap: int
    ) -> int:
        """Walk left from ``start`` past content-bearing columns.

        Returns the smallest index still in the connected content
        block.  Blank runs of up to ``max_gap`` cells are bridged.
        If the column immediately left of ``start`` is blank and no
        content lies within ``max_gap`` of it, the original ``start``
        is returned unchanged.
        """
        new_bound = start
        gap = 0
        pos = start - 1
        while pos >= 0:
            if has_content[pos]:
                new_bound = pos
                gap = 0
            else:
                gap += 1
                if gap > max_gap:
                    break
            pos -= 1
        return new_bound

    @staticmethod
    def _walk_outward_max(
        end: int, has_content: np.ndarray, max_gap: int
    ) -> int:
        """Walk right from half-open ``end`` past content-bearing cells.

        Returns the largest half-open index still in the connected
        content block.  Blank runs of up to ``max_gap`` cells are
        bridged.
        """
        n = len(has_content)
        new_bound = end
        gap = 0
        pos = end
        while pos < n:
            if has_content[pos]:
                new_bound = pos + 1
                gap = 0
            else:
                gap += 1
                if gap > max_gap:
                    break
            pos += 1
        return new_bound

    @staticmethod
    def _merge_rects(rects: list[list[int]]) -> list[list[int]]:
        """Merge overlapping or touching ``[x0, y0, x1, y1]`` rects.

        Runs until a fixpoint is reached so that chains of overlapping
        rects collapse into a single bounding rect.
        """
        out: list[list[int]] = [list(r) for r in rects]
        changed = True
        while changed:
            changed = False
            merged_pass: list[list[int]] = []
            for r in out:
                combined = False
                for s in merged_pass:
                    if (
                        r[0] <= s[2]
                        and s[0] <= r[2]
                        and r[1] <= s[3]
                        and s[1] <= r[3]
                    ):
                        s[0] = min(s[0], r[0])
                        s[1] = min(s[1], r[1])
                        s[2] = max(s[2], r[2])
                        s[3] = max(s[3], r[3])
                        combined = True
                        changed = True
                        break
                if not combined:
                    merged_pass.append(list(r))
            out = merged_pass
        return out
