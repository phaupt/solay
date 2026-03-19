"""Tests for the EpaperDisplay module.

All tests mock IT8951 since it is not installed on dev machines.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
