"""Konfiguration für das Solar E-Ink Dashboard.

Alle Secrets über Umgebungsvariablen oder lokale, nicht versionierte Env-Dateien laden.
"""

from __future__ import annotations

import os
from pathlib import Path


def _load_local_env_file(path: Path, *, override: bool = False) -> None:
    """Lade KEY=VALUE Einträge aus einer lokalen Env-Datei.

    Bereits gesetzte Prozessvariablen haben Vorrang.
    """
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')

        if not key:
            continue

        if override:
            os.environ[key] = value
        else:
            os.environ.setdefault(key, value)


_REPO_ROOT = Path(__file__).resolve().parent
_load_local_env_file(_REPO_ROOT / ".env.local")

# Optional: lokale Testwerte können .env.local für Integrationstests überschreiben.
if os.getenv("RUN_LOCAL_SM_TESTS") == "1":
    _load_local_env_file(_REPO_ROOT / ".env.test.local", override=True)

# --- Solar Manager Lokale API ---
SM_LOCAL_BASE_URL = os.getenv("SM_LOCAL_BASE_URL", "http://192.168.1.XXX")
SM_LOCAL_API_KEY = os.getenv("SM_LOCAL_API_KEY", "")
SM_LOCAL_VERIFY_TLS = os.getenv("SM_LOCAL_VERIFY_TLS", "false").lower() == "true"
SM_LOCAL_CA_BUNDLE = os.getenv("SM_LOCAL_CA_BUNDLE", "")
SM_LOCAL_TLS_FINGERPRINT_SHA256 = os.getenv("SM_LOCAL_TLS_FINGERPRINT_SHA256", "")
SM_LOCAL_TIMEOUT_SECONDS = 10

# --- Solar Manager Cloud API (optional, für Backfill) ---
SM_CLOUD_BASE_URL = "https://external-web.solar-manager.ch"
SM_CLOUD_EMAIL = os.getenv("SM_CLOUD_EMAIL", "")
SM_CLOUD_PASSWORD = os.getenv("SM_CLOUD_PASSWORD", "")
SM_GATEWAY_ID = os.getenv("SM_GATEWAY_ID", "")

# --- Zeitzone ---
# Lokale Zeitzone für Tagesaggregation und Anzeige
TIMEZONE = os.getenv("TZ", "Europe/Zurich")

# --- Display ---
DISPLAY_WIDTH = 1872
DISPLAY_HEIGHT = 1404
DASHBOARD_TITLE = os.getenv("DASHBOARD_TITLE", "SOLAR DASHBOARD")

# --- Datenerfassung ---
# Intervall für point-Polling als Fallback wenn Stream nicht verfügbar
POLL_INTERVAL_SECONDS = 10
# Intervall für Dashboard-Rendering
RENDER_INTERVAL_SECONDS = 30

# --- Persistenz ---
DB_PATH = os.getenv("DB_PATH", "solar_dashboard.db")
MOCK_DB_PATH = os.getenv("MOCK_DB_PATH", "solar_dashboard_mock.db")
# Raw points älter als N Tage werden gelöscht
RAW_RETENTION_DAYS = 7
# Daily summaries werden unbegrenzt aufbewahrt

# --- Web Preview (Dev-Modus) ---
WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))

# --- Modus ---
# "dev" = Browser-Preview, "prod" = E-Ink
DISPLAY_MODE = os.getenv("DISPLAY_MODE", "dev")
