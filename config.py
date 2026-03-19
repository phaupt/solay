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
SM_LOCAL_VERIFY_TLS = os.getenv("SM_LOCAL_VERIFY_TLS", "true").lower() != "false"
SM_LOCAL_CA_BUNDLE = os.getenv("SM_LOCAL_CA_BUNDLE", "")
SM_LOCAL_TLS_FINGERPRINT_SHA256 = os.getenv("SM_LOCAL_TLS_FINGERPRINT_SHA256", "")
SM_LOCAL_TIMEOUT_SECONDS = 10

# --- Solar Manager Cloud API (optional, für Backfill) ---
SM_CLOUD_BASE_URL = "https://external-web.solar-manager.ch"
SM_CLOUD_EMAIL = os.getenv("SM_CLOUD_EMAIL", "")
SM_CLOUD_PASSWORD = os.getenv("SM_CLOUD_PASSWORD", "")
SM_CLOUD_SMID = os.getenv("SM_CLOUD_SMID", os.getenv("SM_GATEWAY_ID", ""))
SM_CLOUD_TIMEOUT_SECONDS = int(os.getenv("SM_CLOUD_TIMEOUT_SECONDS", "15"))
SM_CLOUD_BACKFILL_ENABLED = (
    os.getenv("SM_CLOUD_BACKFILL_ENABLED", "false").lower() == "true"
)
SM_CLOUD_BACKFILL_DAYS = int(os.getenv("SM_CLOUD_BACKFILL_DAYS", "7"))
SM_CLOUD_BACKFILL_INTERVAL_SECONDS = int(
    os.getenv("SM_CLOUD_BACKFILL_INTERVAL_SECONDS", "300")
)

# --- Zeitzone ---
# Lokale Zeitzone für Tagesaggregation und Anzeige
TIMEZONE = os.getenv("TZ", "Europe/Zurich")

# --- Display ---
# Default physical target: Waveshare 7.8" e-Paper HAT (IT8951), 1872x1404.
DISPLAY_WIDTH = 1872
DISPLAY_HEIGHT = 1404
DASHBOARD_TITLE = os.getenv("DASHBOARD_TITLE", "SOLAR DASHBOARD")
DASHBOARD_THEME = os.getenv("DASHBOARD_THEME", "light").strip().lower()
DASHBOARD_LANGUAGE = os.getenv("DASHBOARD_LANGUAGE", "EN").strip().lower()

# --- Datenerfassung ---
# Intervall für point-Polling als Fallback wenn Stream nicht verfügbar
POLL_INTERVAL_SECONDS = 10
# Intervall für Dashboard-Rendering
RENDER_INTERVAL_SECONDS = int(os.getenv("RENDER_INTERVAL_SECONDS", "15"))
STALE_DATA_SECONDS = int(os.getenv("STALE_DATA_SECONDS", "300"))

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

# --- Production / E-Ink ---
DISPLAY_UPDATE_INTERVAL = int(os.getenv("DISPLAY_UPDATE_INTERVAL", "60"))
EPAPER_VCOM = os.getenv("EPAPER_VCOM", "")
DISPLAY_FULL_REFRESH_INTERVAL = int(os.getenv("DISPLAY_FULL_REFRESH_INTERVAL", "1"))

# --- Export ---
EXPORT_GRAYSCALE_LEVELS = int(os.getenv("EXPORT_GRAYSCALE_LEVELS", "16"))
