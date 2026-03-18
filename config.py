"""Konfiguration für das Solar E-Ink Dashboard.

Alle Secrets über Umgebungsvariablen oder .env-Datei laden, nie hardcoden.
"""

import os

# --- Solar Manager Lokale API ---
SM_LOCAL_BASE_URL = os.getenv("SM_LOCAL_BASE_URL", "http://192.168.1.XXX")
SM_LOCAL_API_KEY = os.getenv("SM_LOCAL_API_KEY", "")
SM_LOCAL_VERIFY_TLS = os.getenv("SM_LOCAL_VERIFY_TLS", "false").lower() == "true"
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

# --- Datenerfassung ---
# Intervall für point-Polling als Fallback wenn Stream nicht verfügbar
POLL_INTERVAL_SECONDS = 10
# Intervall für Dashboard-Rendering
RENDER_INTERVAL_SECONDS = 30

# --- Persistenz ---
DB_PATH = os.getenv("DB_PATH", "solar_dashboard.db")
# Raw points älter als N Tage werden gelöscht
RAW_RETENTION_DAYS = 7
# Daily summaries werden unbegrenzt aufbewahrt

# --- Web Preview (Dev-Modus) ---
WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))

# --- Modus ---
# "dev" = Browser-Preview, "prod" = E-Ink
DISPLAY_MODE = os.getenv("DISPLAY_MODE", "dev")
