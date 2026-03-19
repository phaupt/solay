"""Lokaler Solar Manager API-Client.

Primär: WebSocket-Stream (/v2/stream) für kontinuierliche Datenpunkte.
Fallback: HTTP-Polling (/v2/point) wenn Stream nicht verfügbar.
"""

from __future__ import annotations

import hashlib
import json
import logging
import ssl
import threading
import time
from typing import Callable

import requests
import websocket
from requests.adapters import HTTPAdapter

import config
from src.models import DeviceStatus, SensorPoint
from src.storage import Storage

logger = logging.getLogger(__name__)


class FingerprintMismatchError(RuntimeError):
    """Raised when a pinned TLS fingerprint does not match the peer certificate."""


def _normalize_sha256_fingerprint(fingerprint: str | None) -> str | None:
    """Normalize SHA-256 fingerprints to lowercase hex without separators."""
    if not fingerprint:
        return None

    normalized = "".join(ch for ch in fingerprint.lower() if ch in "0123456789abcdef")
    if len(normalized) != 64:
        raise ValueError("SM_LOCAL_TLS_FINGERPRINT_SHA256 must be a SHA-256 fingerprint")
    return normalized


def _format_sha256_fingerprint(fingerprint_hex: str) -> str:
    """Format a normalized hex fingerprint as AA:BB:CC for logs and docs."""
    pairs = [fingerprint_hex[i:i + 2] for i in range(0, len(fingerprint_hex), 2)]
    return ":".join(pair.upper() for pair in pairs)


def _build_requests_verify_arg(verify_tls: bool, ca_bundle: str | None) -> bool | str:
    """Build the requests `verify=` argument from config."""
    return ca_bundle if ca_bundle else verify_tls


def _sha256_fingerprint_from_der(cert_der: bytes) -> str:
    return hashlib.sha256(cert_der).hexdigest()


def _peer_certificate_matches_fingerprint(cert_der: bytes, fingerprint: str | None) -> bool:
    if not fingerprint:
        return True
    return _sha256_fingerprint_from_der(cert_der) == fingerprint


class FingerprintPinningAdapter(HTTPAdapter):
    """Requests adapter that pins an HTTPS peer certificate fingerprint."""

    def __init__(self, fingerprint_sha256: str, *args, **kwargs):
        self._fingerprint_sha256 = fingerprint_sha256
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args, **kwargs):
        kwargs["assert_fingerprint"] = self._fingerprint_sha256
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        kwargs["assert_fingerprint"] = self._fingerprint_sha256
        return super().proxy_manager_for(*args, **kwargs)


class LocalApiClient:
    """HTTP-Client für die lokale Solar Manager API."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        verify_tls: bool | None = None,
        ca_bundle: str | None = None,
        fingerprint_sha256: str | None = None,
    ):
        self._base_url = (base_url or config.SM_LOCAL_BASE_URL).rstrip("/")
        self._api_key = api_key or config.SM_LOCAL_API_KEY
        self._verify_tls = (
            config.SM_LOCAL_VERIFY_TLS if verify_tls is None else verify_tls
        )
        self._ca_bundle = ca_bundle if ca_bundle is not None else config.SM_LOCAL_CA_BUNDLE
        self._fingerprint_sha256 = _normalize_sha256_fingerprint(
            fingerprint_sha256
            if fingerprint_sha256 is not None
            else config.SM_LOCAL_TLS_FINGERPRINT_SHA256
        )
        self._timeout = config.SM_LOCAL_TIMEOUT_SECONDS
        self._session = requests.Session()

        if self._fingerprint_sha256:
            self._session.mount(
                "https://",
                FingerprintPinningAdapter(self._fingerprint_sha256),
            )

    def _headers(self) -> dict:
        headers = {}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        return headers

    @property
    def requests_verify(self) -> bool | str:
        return _build_requests_verify_arg(self._verify_tls, self._ca_bundle)

    @property
    def websocket_sslopt(self) -> dict:
        sslopt: dict[str, object] = {}
        if self._ca_bundle:
            sslopt["ca_certs"] = self._ca_bundle

        if self._verify_tls or self._ca_bundle:
            sslopt["cert_reqs"] = ssl.CERT_REQUIRED
        else:
            sslopt["cert_reqs"] = ssl.CERT_NONE
            sslopt["check_hostname"] = False

        return sslopt

    @property
    def fingerprint_sha256(self) -> str | None:
        return self._fingerprint_sha256

    def get_point(self) -> dict:
        """Hole aktuellen Datenpunkt via GET /v2/point."""
        url = f"{self._base_url}/v2/point"
        resp = self._session.get(
            url,
            headers=self._headers(),
            verify=self.requests_verify,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def get_devices(self) -> list[dict]:
        """Hole Geräteliste via GET /v2/devices."""
        url = f"{self._base_url}/v2/devices"
        resp = self._session.get(
            url,
            headers=self._headers(),
            verify=self.requests_verify,
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
        self._last_stream_error: Exception | None = None
        self._device_metadata: dict[str, dict] = {}
        self._device_metadata_loaded = False

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

            # Stream ist weg — aktiv auf Point-Polling wechseln bis Reconnect
            delay = min(self._backoff, 60.0)
            logger.info(
                "Wechsle auf Point-Polling (alle %ds) für %.0fs, dann Reconnect",
                config.POLL_INTERVAL_SECONDS, delay,
            )
            self._poll_until(delay)
            self._backoff = min(self._backoff * 2, 60.0)

    def _poll_until(self, duration: float):
        """Polle /v2/point für die angegebene Dauer, dann zurück zum Stream."""
        deadline = time.monotonic() + duration
        while self._running and time.monotonic() < deadline:
            self.poll_once()
            remaining = deadline - time.monotonic()
            sleep_time = min(config.POLL_INTERVAL_SECONDS, max(0, remaining))
            if sleep_time > 0 and self._running:
                time.sleep(sleep_time)

    def _run_stream(self):
        """Verbinde mit WebSocket-Stream."""
        url = self._client.stream_url
        headers = {}
        if self._client._api_key:
            headers["X-API-Key"] = self._client._api_key
        self._last_stream_error = None

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
            sslopt=self._client.websocket_sslopt,
            ping_interval=30,
            ping_timeout=10,
        )

        if self._last_stream_error:
            err = self._last_stream_error
            self._last_stream_error = None
            raise err

    def _load_device_metadata(self):
        if self._device_metadata_loaded:
            return

        fetch = getattr(self._client, "get_devices", None)
        if fetch is None:
            self._device_metadata_loaded = True
            return

        try:
            devices = fetch() or []
        except Exception as exc:
            logger.debug("Geräte-Metadaten konnten nicht geladen werden: %s", exc)
            self._device_metadata_loaded = True
            return

        if not isinstance(devices, list):
            devices = []

        metadata: dict[str, dict] = {}
        for device in devices:
            for key in (
                device.get("_id"),
                device.get("deviceId"),
                device.get("data_id"),
                device.get("sensorId"),
            ):
                if key:
                    metadata[str(key)] = dict(device)
        self._device_metadata = metadata
        self._device_metadata_loaded = True

    def _enrich_devices(self, devices: list[dict]) -> list[dict]:
        self._load_device_metadata()
        if not self._device_metadata:
            return [dict(device) for device in devices]

        enriched: list[dict] = []
        for device in devices:
            device_id = (
                device.get("_id")
                or device.get("deviceId")
                or device.get("data_id")
                or device.get("sensorId")
            )
            merged = dict(self._device_metadata.get(str(device_id), {}))
            merged.update(device)
            enriched.append(merged)
        return enriched

    def _on_ws_open(self, ws):
        try:
            self._verify_websocket_peer_certificate(ws)
            logger.info("Stream-Verbindung hergestellt")
            self._backoff = 1.0  # Reset backoff on success
        except Exception as e:
            self._last_stream_error = e
            logger.error("TLS-Zertifikat des Streams ungültig: %s", e)
            ws.close()

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

    def _verify_websocket_peer_certificate(self, ws):
        """Prüfe optional den SHA-256-Fingerprint des TLS-Peer-Zertifikats."""
        fingerprint = self._client.fingerprint_sha256
        if not fingerprint:
            return

        try:
            peer_sock = ws.sock.sock
            cert_der = peer_sock.getpeercert(binary_form=True)
        except Exception as e:
            raise FingerprintMismatchError(
                f"Peer certificate for WebSocket stream could not be inspected: {e}"
            ) from e

        if not cert_der:
            raise FingerprintMismatchError("WebSocket peer did not provide a certificate")

        actual = _sha256_fingerprint_from_der(cert_der)
        if actual != fingerprint:
            raise FingerprintMismatchError(
                "Pinned SHA-256 fingerprint mismatch: "
                f"expected {_format_sha256_fingerprint(fingerprint)}, "
                f"got {_format_sha256_fingerprint(actual)}"
            )

    def _process_point(self, data: dict, source: str = "local_stream"):
        """Verarbeite einen API-Datenpunkt: parse, speichere, benachrichtige."""
        enriched_payload = dict(data)
        enriched_payload["devices"] = self._enrich_devices(data.get("devices", []))
        point = SensorPoint.from_api(enriched_payload)
        devices = [DeviceStatus.from_api(d) for d in enriched_payload["devices"]]

        # In-Memory aktualisieren
        with self._lock:
            self._latest_point = point
            self._latest_devices = devices

        # In DB speichern
        devices_json = json.dumps(enriched_payload["devices"])
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
