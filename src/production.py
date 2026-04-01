"""Production runtime loop for the solar e-ink dashboard.

Ties together data collection, rendering, and display output in a
timer-based loop with day-rollover handling and retention cleanup.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config
from src.aggregator import aggregate_daily_summary

logger = logging.getLogger(__name__)

# vcgencmd get_throttled bit masks
_THROTTLE_UNDERVOLTAGE_NOW = 0x1
_THROTTLE_FREQ_CAPPED_NOW = 0x2
_THROTTLE_THROTTLED_NOW = 0x4
_THROTTLE_SOFT_TEMP_NOW = 0x8
_THROTTLE_UNDERVOLTAGE_SINCE = 0x10000
_THROTTLE_FREQ_CAPPED_SINCE = 0x20000
_THROTTLE_THROTTLED_SINCE = 0x40000
_THROTTLE_SOFT_TEMP_SINCE = 0x80000


def _check_throttle_state() -> int | None:
    """Read Pi throttle flags via vcgencmd. Returns None on non-Pi systems."""
    try:
        result = subprocess.run(
            ["vcgencmd", "get_throttled"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None
        # Output format: "throttled=0x50000"
        value = result.stdout.strip().split("=", 1)[-1]
        return int(value, 16)
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        return None


def _log_throttle_warnings(flags: int) -> None:
    """Log warnings for active throttle conditions."""
    if flags & _THROTTLE_UNDERVOLTAGE_NOW:
        logger.warning("UNDERVOLTAGE detected RIGHT NOW -- check power supply")
    elif flags & _THROTTLE_UNDERVOLTAGE_SINCE:
        logger.warning("Undervoltage occurred since last boot -- check power supply")

    if flags & _THROTTLE_THROTTLED_NOW:
        logger.warning("CPU is being THROTTLED right now")
    if flags & _THROTTLE_SOFT_TEMP_NOW:
        logger.warning("Soft temperature limit active -- consider cooling")


def _notify_watchdog() -> None:
    """Ping the systemd watchdog (no-op outside systemd)."""
    try:
        addr = os.environ.get("NOTIFY_SOCKET")
        if not addr:
            return
        import socket

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            if addr.startswith("@"):
                addr = "\0" + addr[1:]
            sock.sendto(b"WATCHDOG=1", addr)
        finally:
            sock.close()
    except Exception:
        pass


def _try_backfill(storage) -> None:
    """Run cloud backfill, skipping today's prefix.  Swallows all errors."""
    try:
        from src.api_cloud import optional_backfill

        optional_backfill(storage, skip_today=True)
    except Exception:
        logger.warning("Cloud backfill failed during reconciliation", exc_info=True)


class ProductionLoop:
    """Main production loop: collect -> render -> display on a timer."""

    def __init__(self, storage, collector, renderer, display=None):
        self._storage = storage
        self._collector = collector
        self._renderer = renderer
        self._display = display
        self._stopped = False
        self._render_failures = 0

        tz = ZoneInfo(config.TIMEZONE)
        self._tz = tz
        self._current_date = datetime.now(tz).date()
        self._last_cleanup_at = datetime.min.replace(tzinfo=tz)
        self._last_throttle_check = 0.0
        self._last_throttle_flags = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Block until stop() is called.  Registers signal handlers."""
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        self._reconcile_yesterday()

        while not self._stopped:
            self._run_one_cycle()

            # Sleep in 1-second increments so we can respond to stop quickly.
            deadline = time.monotonic() + config.DISPLAY_UPDATE_INTERVAL
            while not self._stopped and time.monotonic() < deadline:
                time.sleep(1)

        self._shutdown()

    def stop(self) -> None:
        """Signal the loop to exit gracefully."""
        self._stopped = True

    # ------------------------------------------------------------------
    # Internal cycle
    # ------------------------------------------------------------------

    def _run_one_cycle(self) -> None:
        self._check_day_rollover()
        self._check_throttle()
        _notify_watchdog()

        # Build dashboard data (lazy import to avoid circular imports).
        try:
            from main import build_dashboard_data

            data = build_dashboard_data(self._storage, self._collector)
        except Exception:
            logger.warning("Failed to build dashboard data", exc_info=True)
            self._maybe_cleanup()
            return

        # Render
        image = None
        try:
            image = self._renderer.render(data)
            self._render_failures = 0
        except Exception:
            self._render_failures = getattr(self, "_render_failures", 0) + 1
            logger.warning(
                "Renderer failed (%d consecutive)", self._render_failures,
                exc_info=True,
            )
            if self._render_failures >= 3:
                self._restart_renderer()

        # Display
        if image is not None and self._display is not None:
            try:
                self._display.show(image)
            except Exception:
                logger.warning("Display failed, attempting sleep/wake reset", exc_info=True)
                try:
                    self._display.sleep()
                    self._display.wake()
                except Exception:
                    logger.warning("Display reset also failed", exc_info=True)

        # Log cycle result
        if data.live:
            logger.info(
                "Cycle OK: p=%dW c=%dW grid=%dW | rendered=%s displayed=%s",
                int(data.live.p_w), int(data.live.c_w),
                int(data.live.grid_w),
                image is not None,
                image is not None and self._display is not None,
            )

        self._maybe_cleanup()

    # ------------------------------------------------------------------
    # Renderer self-healing
    # ------------------------------------------------------------------

    def _restart_renderer(self) -> None:
        """Tear down and recreate the renderer after repeated failures."""
        logger.warning("Attempting renderer restart after %d failures", self._render_failures)
        try:
            self._renderer.close()
        except Exception:
            logger.debug("Ignoring error during renderer teardown", exc_info=True)

        try:
            self._renderer = self._renderer.__class__(
                theme=getattr(self._renderer, "_theme", None),
                lang=getattr(self._renderer, "_lang", None),
                grayscale_levels=getattr(self._renderer, "_grayscale_levels", None),
                timeout=getattr(self._renderer, "_timeout", None),
            )
            self._render_failures = 0
            logger.info("Renderer restarted successfully")
        except Exception:
            logger.error("Renderer restart failed — will retry next cycle", exc_info=True)

    # ------------------------------------------------------------------
    # Day rollover & reconciliation
    # ------------------------------------------------------------------

    def _reconcile_yesterday(self) -> None:
        """Re-aggregate yesterday from raw points on startup."""
        yesterday = (datetime.now(self._tz) - timedelta(days=1)).date()
        points = self._storage.get_points_for_date(yesterday, tz=self._tz)
        if points:
            summary = aggregate_daily_summary(points, yesterday)
            self._storage.store_daily_summary(summary)
        _try_backfill(self._storage)

    def _check_day_rollover(self) -> None:
        """Detect date change, re-aggregate the previous day, backfill."""
        today = datetime.now(self._tz).date()
        if today == self._current_date:
            return

        old_date = self._current_date
        logger.info("Day rollover detected: %s -> %s", old_date, today)

        points = self._storage.get_points_for_date(old_date, tz=self._tz)
        if points:
            summary = aggregate_daily_summary(points, old_date)
            self._storage.store_daily_summary(summary)

        _try_backfill(self._storage)
        self._current_date = today

    # ------------------------------------------------------------------
    # Retention cleanup
    # ------------------------------------------------------------------

    def _maybe_cleanup(self) -> None:
        now = datetime.now(self._tz)
        if (now - self._last_cleanup_at) >= timedelta(hours=1):
            try:
                self._storage.cleanup_old_points()
                self._last_cleanup_at = now
            except Exception:
                logger.warning("Retention cleanup failed", exc_info=True)

    # ------------------------------------------------------------------
    # Hardware health
    # ------------------------------------------------------------------

    def _check_throttle(self) -> None:
        """Check Pi throttle/undervoltage state every 5 minutes."""
        now = time.monotonic()
        if now - self._last_throttle_check < 300:
            return
        self._last_throttle_check = now

        flags = _check_throttle_state()
        if flags is None:
            return

        # Only log when flags change or when an active condition persists.
        if flags != self._last_throttle_flags:
            if flags == 0 and self._last_throttle_flags != 0:
                logger.info("Throttle state cleared (power OK)")
            elif flags != 0:
                _log_throttle_warnings(flags)
            self._last_throttle_flags = flags

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def _shutdown(self) -> None:
        logger.info("Shutting down production loop")
        if self._display is not None:
            try:
                self._display.sleep()
            except Exception:
                logger.warning("Display sleep failed during shutdown", exc_info=True)
        try:
            self._renderer.close()
        except Exception:
            logger.warning("Renderer close failed during shutdown", exc_info=True)
        try:
            self._collector.stop()
        except Exception:
            logger.warning("Collector stop failed during shutdown", exc_info=True)

    def _handle_signal(self, signum, frame):
        logger.info("Received signal %s, stopping", signal.Signals(signum).name)
        self.stop()
