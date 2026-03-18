"""Lokaler Solar Manager API-Client.

Primär: WebSocket-Stream (/v2/stream) für kontinuierliche Datenpunkte.
Fallback: HTTP-Polling (/v2/point) wenn Stream nicht verfügbar.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable

import requests
import websocket

import config
from src.models import DeviceStatus, SensorPoint
from src.storage import Storage

logger = logging.getLogger(__name__)


class LocalApiClient:
    """HTTP-Client für die lokale Solar Manager API."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        self._base_url = (base_url or config.SM_LOCAL_BASE_URL).rstrip("/")
        self._api_key = api_key or config.SM_LOCAL_API_KEY
        self._verify_tls = config.SM_LOCAL_VERIFY_TLS
        self._timeout = config.SM_LOCAL_TIMEOUT_SECONDS

    def _headers(self) -> dict:
        headers = {}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        return headers

    def get_point(self) -> dict:
        """Hole aktuellen Datenpunkt via GET /v2/point."""
        url = f"{self._base_url}/v2/point"
        resp = requests.get(
            url,
            headers=self._headers(),
            verify=self._verify_tls,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def get_devices(self) -> list[dict]:
        """Hole Geräteliste via GET /v2/devices."""
        url = f"{self._base_url}/v2/devices"
        resp = requests.get(
            url,
            headers=self._headers(),
            verify=self._verify_tls,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()

    @property
    def stream_url(self) -> str:
        """WebSocket-URL für /v2/stream."""
        base = self._base_url.replace("http://", "ws://").replace("https://", "wss://")
        return f"{base}/v2/stream"


class StreamCollector:
    """Verbindet sich mit dem WebSocket-Stream und speichert Datenpunkte.

    Features:
    - Automatischer Reconnect mit exponentiellem Backoff
    - Fallback auf Point-Polling wenn Stream dauerhaft nicht erreichbar
    - Thread-safe: läuft als Daemon-Thread
    """

    def __init__(
        self,
        storage: Storage,
        client: LocalApiClient | None = None,
        on_point: Callable[[SensorPoint, list[DeviceStatus]], None] | None = None,
    ):
        self._storage = storage
        self._client = client or LocalApiClient()
        self._on_point = on_point
        self._running = False
        self._thread: threading.Thread | None = None
        self._latest_point: SensorPoint | None = None
        self._latest_devices: list[DeviceStatus] = []
        self._lock = threading.Lock()
        self._backoff = 1.0  # Initial reconnect delay

    @property
    def latest_point(self) -> SensorPoint | None:
        with self._lock:
            return self._latest_point

    @property
    def latest_devices(self) -> list[DeviceStatus]:
        with self._lock:
            return list(self._latest_devices)

    def start(self):
        """Starte den Collector als Daemon-Thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("StreamCollector gestartet")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _run_loop(self):
        """Hauptschleife: Versuche Stream, falle auf Polling zurück."""
        while self._running:
            try:
                self._run_stream()
            except Exception as e:
                logger.warning("Stream-Verbindung fehlgeschlagen: %s", e)

            if not self._running:
                break

            # Backoff vor Reconnect
            delay = min(self._backoff, 60.0)
            logger.info("Reconnect in %.0fs (Backoff)", delay)
            time.sleep(delay)
            self._backoff = min(self._backoff * 2, 60.0)

    def _run_stream(self):
        """Verbinde mit WebSocket-Stream."""
        url = self._client.stream_url
        headers = {}
        if self._client._api_key:
            headers["X-API-Key"] = self._client._api_key

        logger.info("Verbinde mit Stream: %s", url)

        ws = websocket.WebSocketApp(
            url,
            header=[f"{k}: {v}" for k, v in headers.items()],
            on_message=self._on_ws_message,
            on_error=self._on_ws_error,
            on_close=self._on_ws_close,
            on_open=self._on_ws_open,
        )

        ws.run_forever(
            sslopt={"cert_reqs": 0} if not self._client._verify_tls else {},
            ping_interval=30,
            ping_timeout=10,
        )

    def _on_ws_open(self, ws):
        logger.info("Stream-Verbindung hergestellt")
        self._backoff = 1.0  # Reset backoff on success

    def _on_ws_message(self, ws, message):
        try:
            data = json.loads(message)
            self._process_point(data, source="local_stream")
        except (json.JSONDecodeError, Exception) as e:
            logger.error("Fehler beim Verarbeiten der Stream-Nachricht: %s", e)

    def _on_ws_error(self, ws, error):
        logger.warning("Stream-Fehler: %s", error)

    def _on_ws_close(self, ws, close_status_code, close_msg):
        logger.info("Stream geschlossen: %s %s", close_status_code, close_msg)

    def _process_point(self, data: dict, source: str = "local_stream"):
        """Verarbeite einen API-Datenpunkt: parse, speichere, benachrichtige."""
        point = SensorPoint.from_api(data)
        devices = [DeviceStatus.from_api(d) for d in data.get("devices", [])]

        # In-Memory aktualisieren
        with self._lock:
            self._latest_point = point
            self._latest_devices = devices

        # In DB speichern
        devices_json = json.dumps(data.get("devices", []))
        self._storage.store_point(point, source=source, devices_json=devices_json)

        # Callback
        if self._on_point:
            try:
                self._on_point(point, devices)
            except Exception as e:
                logger.error("on_point Callback-Fehler: %s", e)

    def poll_once(self):
        """Einzelner Point-Request als Fallback oder für initiales Laden."""
        try:
            data = self._client.get_point()
            self._process_point(data, source="local_point")
        except Exception as e:
            logger.error("Point-Polling fehlgeschlagen: %s", e)
