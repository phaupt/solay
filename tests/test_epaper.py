"""Tests for the EpaperDisplay module.

All tests mock IT8951 since it is not installed on dev machines.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image


@pytest.fixture
def mock_it8951():
    """Inject fake IT8951 modules and return the mock display instance."""
    mock_display = MagicMock()
    mock_display.width = 1872
    mock_display.height = 1404
    mock_display.epd = MagicMock()

    mock_constants = MagicMock()

    with patch.dict("sys.modules", {
        "IT8951": MagicMock(),
        "IT8951.display": MagicMock(),
        "IT8951.constants": mock_constants,
    }):
        with patch("src.epaper.AutoEPDDisplay", return_value=mock_display), \
             patch("src.epaper.constants", mock_constants), \
             patch("src.epaper._HAS_IT8951", True):
            yield mock_display, mock_constants


class TestEpaperInit:
    def test_init_sets_vcom(self, mock_it8951):
        mock_display, _ = mock_it8951
        from src.epaper import EpaperDisplay

        epd = EpaperDisplay(vcom=-1.48)

        # AutoEPDDisplay should have been called with the vcom value
        from src.epaper import AutoEPDDisplay
        AutoEPDDisplay.assert_called_once_with(vcom=-1.48)
        assert not epd._closed
        assert not epd._sleeping

    def test_init_raises_without_it8951(self):
        with patch.dict("sys.modules", {
            "IT8951": None,
            "IT8951.display": None,
            "IT8951.constants": None,
        }):
            # Force reload to pick up missing modules
            import importlib
            import src.epaper
            importlib.reload(src.epaper)

            with pytest.raises(RuntimeError, match="IT8951"):
                src.epaper.EpaperDisplay(vcom=-1.48)


class TestShowFull:
    def test_show_full_calls_display(self, mock_it8951):
        mock_display, mock_constants = mock_it8951
        from src.epaper import EpaperDisplay

        epd = EpaperDisplay(vcom=-1.48)
        img = Image.new("RGB", (1872, 1404), color=128)
        epd.show_full(img)

        mock_display.frame_buf.paste.assert_called_once()
        mock_display.draw_full.assert_called_once_with(
            mock_constants.DisplayModes.GC16
        )

    def test_show_full_converts_to_grayscale(self, mock_it8951):
        mock_display, _ = mock_it8951
        from src.epaper import EpaperDisplay

        epd = EpaperDisplay(vcom=-1.48)
        img = Image.new("RGB", (1872, 1404), color=(255, 0, 0))
        epd.show_full(img)

        # The pasted image should be mode "L"
        pasted_img = mock_display.frame_buf.paste.call_args[0][0]
        assert pasted_img.mode == "L"

    def test_show_full_resizes_if_needed(self, mock_it8951):
        mock_display, _ = mock_it8951
        from src.epaper import EpaperDisplay

        epd = EpaperDisplay(vcom=-1.48)
        img = Image.new("L", (800, 600), color=128)
        epd.show_full(img)

        pasted_img = mock_display.frame_buf.paste.call_args[0][0]
        assert pasted_img.size == (1872, 1404)

    def test_show_full_auto_wakes_from_sleep(self, mock_it8951):
        mock_display, _ = mock_it8951
        from src.epaper import EpaperDisplay

        epd = EpaperDisplay(vcom=-1.48)
        epd._sleeping = True
        img = Image.new("L", (1872, 1404))
        epd.show_full(img)

        mock_display.epd.run.assert_called_once()
        assert not epd._sleeping


class TestClear:
    def test_clear_fills_white(self, mock_it8951):
        mock_display, mock_constants = mock_it8951
        from src.epaper import EpaperDisplay

        epd = EpaperDisplay(vcom=-1.48)
        epd.clear()

        mock_display.frame_buf.paste.assert_called_once()
        pasted_img = mock_display.frame_buf.paste.call_args[0][0]
        assert pasted_img.mode == "L"
        assert pasted_img.size == (1872, 1404)
        # All pixels should be white (255)
        assert pasted_img.getpixel((0, 0)) == 255
        mock_display.draw_full.assert_called_once_with(
            mock_constants.DisplayModes.GC16
        )


class TestClose:
    def test_close_is_safe(self, mock_it8951):
        mock_display, _ = mock_it8951
        from src.epaper import EpaperDisplay

        epd = EpaperDisplay(vcom=-1.48)
        epd.close()
        assert epd._closed

        # Second close should be a no-op
        mock_display.epd.sleep.reset_mock()
        epd.close()
        mock_display.epd.sleep.assert_not_called()

    def test_close_puts_display_to_sleep(self, mock_it8951):
        mock_display, _ = mock_it8951
        from src.epaper import EpaperDisplay

        epd = EpaperDisplay(vcom=-1.48)
        epd.close()

        mock_display.epd.sleep.assert_called_once()
        assert epd._sleeping


class TestSleepWake:
    def test_sleep_wake_cycle(self, mock_it8951):
        mock_display, _ = mock_it8951
        from src.epaper import EpaperDisplay

        epd = EpaperDisplay(vcom=-1.48)

        epd.sleep()
        assert epd._sleeping
        mock_display.epd.sleep.assert_called_once()

        epd.wake()
        assert not epd._sleeping
        mock_display.epd.run.assert_called_once()

    def test_sleep_when_already_sleeping_is_noop(self, mock_it8951):
        mock_display, _ = mock_it8951
        from src.epaper import EpaperDisplay

        epd = EpaperDisplay(vcom=-1.48)
        epd.sleep()
        mock_display.epd.sleep.reset_mock()

        epd.sleep()
        mock_display.epd.sleep.assert_not_called()

    def test_wake_when_not_sleeping_is_noop(self, mock_it8951):
        mock_display, _ = mock_it8951
        from src.epaper import EpaperDisplay

        epd = EpaperDisplay(vcom=-1.48)
        mock_display.epd.run.reset_mock()

        epd.wake()
        mock_display.epd.run.assert_not_called()

    def test_sleep_exception_does_not_raise(self, mock_it8951):
        mock_display, _ = mock_it8951
        from src.epaper import EpaperDisplay

        epd = EpaperDisplay(vcom=-1.48)
        mock_display.epd.sleep.side_effect = OSError("SPI error")

        # Should not raise
        epd.sleep()

    def test_wake_exception_does_not_raise(self, mock_it8951):
        mock_display, _ = mock_it8951
        from src.epaper import EpaperDisplay

        epd = EpaperDisplay(vcom=-1.48)
        epd._sleeping = True
        mock_display.epd.run.side_effect = OSError("SPI error")

        # Should not raise
        epd.wake()


class TestShowPartial:
    def test_show_partial_calls_draw_partial(self, mock_it8951):
        mock_display, mock_constants = mock_it8951
        from src.epaper import EpaperDisplay

        epd = EpaperDisplay(vcom=-1.48)
        img = Image.new("L", (200, 100), color=64)
        epd.show_partial(img, x=10, y=20, w=200, h=100)

        mock_display.frame_buf.paste.assert_called_once()
        mock_display.draw_partial.assert_called_once_with(
            mock_constants.DisplayModes.DU
        )


def _blank_frame(h: int, w: int) -> np.ndarray:
    """A uint8 grayscale frame filled with light-theme background."""
    return np.full((h, w), 250, dtype=np.uint8)


def _paint_text_block(
    frame: np.ndarray,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    *,
    value: int = 30,
) -> None:
    """Paint a solid dark block into the frame to stand in for text."""
    frame[y0:y1, x0:x1] = value


class TestFindChangedTiles:
    """Regression tests for tile detection with content-aware expansion.

    These lock in the fix for darkness inconsistency between partial
    refreshes — when a single glyph changes, the whole surrounding
    text line must be re-driven so it ages uniformly.
    """

    def test_no_changes_returns_empty(self):
        from src.epaper import EpaperDisplay

        prev = _blank_frame(100, 200)
        curr = prev.copy()

        assert EpaperDisplay._find_changed_tiles(prev, curr) == []

    def test_changes_on_blank_frame_return_tight_tile(self):
        """With no surrounding content, expansion is a no-op."""
        from src.epaper import EpaperDisplay

        prev = _blank_frame(100, 400)
        curr = prev.copy()
        # Isolated change on a pure background.
        curr[40:60, 180:200] = 30

        tiles = EpaperDisplay._find_changed_tiles(prev, curr)
        assert len(tiles) == 1
        x, y, w, h = tiles[0]
        # Tight horizontally (nothing to the sides to expand into).
        # Vertical gets a small v_pad = 16; align to 4-px boundary.
        assert x <= 180 < 200 <= x + w
        assert x + w - x <= 32  # tight: no horizontal expansion
        assert y <= 40 and y + h >= 60
        # Aligned to 4-pixel boundaries (IT8951 requirement).
        assert x % 4 == 0 and y % 4 == 0
        assert w % 4 == 0 and h % 4 == 0

    def test_single_digit_change_pulls_in_surrounding_text_line(self):
        """Regression for 'Letztes Update HH:MM' ghosting issue.

        Simulates a text line where a prefix label is static and a
        trailing digit changes.  The expanded tile must cover the
        entire line, not just the changed digit, so the whole line
        gets re-driven with the same GL16 pulse.
        """
        from src.epaper import EpaperDisplay

        H, W = 200, 1872
        prev = _blank_frame(H, W)
        # Fake text line "Letztes Update 14:37": one long dark bar at
        # y in [40, 80), x in [1200, 1820), with small kerning gaps.
        _paint_text_block(prev, 1200, 40, 1550, 80)  # label "Letztes Update"
        _paint_text_block(prev, 1570, 40, 1800, 80)  # time "14:37"

        curr = prev.copy()
        # Minute ones digit flips: a single glyph area changes.
        # This is the only diff between prev and curr.
        curr[50:75, 1775:1800] = 200  # subtle pixel flip inside the digit

        tiles = EpaperDisplay._find_changed_tiles(prev, curr)
        assert len(tiles) == 1, (
            f"expected single merged tile, got {len(tiles)}: {tiles}"
        )

        x, y, w, h = tiles[0]
        # The critical assertion: the tile must extend leftward far
        # enough to cover the static label ("Letztes Update"), so the
        # whole line re-anchors together.
        assert x <= 1200, (
            f"tile starts at {x} but must reach label at 1200"
        )
        # And the tile must still cover the changed digit on the right.
        assert x + w >= 1800
        # Sanity: tile is bounded and does not span the whole display.
        assert x + w <= W
        assert 0 <= y and y + h <= H

    def test_distant_changes_stay_separate(self):
        """Two changes far apart (e.g. flow panel vs history panel)
        must remain separate tiles, not merge via content walk."""
        from src.epaper import EpaperDisplay

        H, W = 400, 1872
        prev = _blank_frame(H, W)
        # Two separate content blocks far apart, separated by a wide
        # empty gap that exceeds content_max_gap.
        _paint_text_block(prev, 50, 40, 200, 80)
        _paint_text_block(prev, 1600, 300, 1800, 340)

        curr = prev.copy()
        curr[55:65, 100:120] = 200   # small flip inside the first block
        curr[305:315, 1700:1720] = 200  # small flip inside the second block

        tiles = EpaperDisplay._find_changed_tiles(prev, curr)
        assert len(tiles) == 2, (
            f"expected two tiles, got {len(tiles)}: {tiles}"
        )

    def test_content_walk_stops_at_large_blank_gap(self):
        """A 100-pixel empty gap must stop the horizontal expansion
        even though there's more content beyond it — panel padding
        must not be bridged."""
        from src.epaper import EpaperDisplay

        H, W = 120, 1200
        prev = _blank_frame(H, W)
        _paint_text_block(prev, 50, 40, 300, 80)     # content block A
        _paint_text_block(prev, 800, 40, 1000, 80)   # content block B (far)

        curr = prev.copy()
        curr[50:60, 100:120] = 200  # flip inside block A only

        tiles = EpaperDisplay._find_changed_tiles(prev, curr)
        assert len(tiles) == 1

        x, y, w, h = tiles[0]
        # Tile covers block A fully.
        assert x <= 50 and x + w >= 300
        # Tile does NOT reach block B (gap too large to bridge).
        assert x + w < 800

    def test_tiles_are_clamped_to_frame_bounds(self):
        from src.epaper import EpaperDisplay

        H, W = 120, 600
        prev = _blank_frame(H, W)
        _paint_text_block(prev, 0, 0, 100, 40)
        curr = prev.copy()
        curr[5:15, 10:30] = 200

        tiles = EpaperDisplay._find_changed_tiles(prev, curr)
        for x, y, w, h in tiles:
            assert x >= 0 and y >= 0
            assert x + w <= W
            assert y + h <= H


class TestMergeRects:
    def test_disjoint_rects_stay_separate(self):
        from src.epaper import EpaperDisplay

        rects = [[0, 0, 10, 10], [100, 100, 110, 110]]
        merged = EpaperDisplay._merge_rects(rects)
        assert len(merged) == 2

    def test_overlapping_rects_merge(self):
        from src.epaper import EpaperDisplay

        rects = [[0, 0, 20, 20], [10, 10, 30, 30]]
        merged = EpaperDisplay._merge_rects(rects)
        assert merged == [[0, 0, 30, 30]]

    def test_chain_of_overlaps_collapses(self):
        from src.epaper import EpaperDisplay

        rects = [
            [0, 0, 20, 20],
            [15, 0, 40, 20],
            [35, 0, 60, 20],
        ]
        merged = EpaperDisplay._merge_rects(rects)
        assert merged == [[0, 0, 60, 20]]


class TestWalkOutward:
    def test_walk_min_stops_at_large_gap(self):
        from src.epaper import EpaperDisplay

        #            0  1  2  3  4  5  6  7  8  9 10
        mask = np.array([1, 1, 0, 0, 0, 0, 0, 1, 1, 1, 1], dtype=bool)
        # Walking left from 9 with max_gap=3: walks through 8, 7, then
        # hits four blanks (3, 4, 5, 6) — exceeds max_gap, stops at 7.
        assert EpaperDisplay._walk_outward_min(9, mask, max_gap=3) == 7

    def test_walk_min_bridges_small_gap(self):
        from src.epaper import EpaperDisplay

        mask = np.array([1, 1, 0, 0, 1, 1, 1], dtype=bool)
        # Walking left from 6 with max_gap=3 bridges the 2-cell gap.
        assert EpaperDisplay._walk_outward_min(6, mask, max_gap=3) == 0

    def test_walk_max_extends_right(self):
        from src.epaper import EpaperDisplay

        mask = np.array([1, 1, 1, 0, 0, 0, 0, 0, 1], dtype=bool)
        # Walking right from 3 (half-open) with max_gap=2: bails after
        # two blanks, new_bound stays at 3 (no content touched).
        assert EpaperDisplay._walk_outward_max(3, mask, max_gap=2) == 3

    def test_walk_outward_never_returns_past_edge(self):
        from src.epaper import EpaperDisplay

        mask = np.array([1, 1, 1], dtype=bool)
        assert EpaperDisplay._walk_outward_min(0, mask, max_gap=5) == 0
        assert EpaperDisplay._walk_outward_max(3, mask, max_gap=5) == 3
