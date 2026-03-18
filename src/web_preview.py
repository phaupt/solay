"""Flask Dev-Server: Dashboard-Vorschau im Browser.

Security:
- Bindet standardmässig auf 127.0.0.1 (nur lokal erreichbar)
- Kein Debug-Modus
- Kein offener Listener im Heimnetz als Default
"""

from __future__ import annotations

import io
import logging
import threading
import time
from typing import Callable

from flask import Flask, Response

import config
from src.models import DashboardData
from src.renderer import render_dashboard

logger = logging.getLogger(__name__)
app = Flask(__name__)

_current_image_bytes: bytes | None = None
_lock = threading.Lock()


def update_image(dashboard_data: DashboardData):
    """Rendere das Dashboard neu und cache das PNG."""
    global _current_image_bytes
    img = render_dashboard(dashboard_data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    with _lock:
        _current_image_bytes = buf.getvalue()


@app.route("/")
def index():
    refresh_seconds = config.RENDER_INTERVAL_SECONDS
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Solar E-Ink Dashboard</title>
    <meta charset="utf-8">
    <style>
        body {{
            margin: 0;
            background: #2a2a2a;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            font-family: -apple-system, sans-serif;
        }}
        .container {{ text-align: center; }}
        img {{
            max-width: 95vw;
            max-height: 90vh;
            border: 2px solid #555;
            border-radius: 8px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.5);
        }}
        .info {{
            color: #888;
            font-size: 14px;
            margin-top: 10px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <img src="/dashboard.png" id="dashboard" />
        <div class="info">
            Auto-Refresh alle {refresh_seconds}s &bull;
            {config.DISPLAY_WIDTH}&times;{config.DISPLAY_HEIGHT} px &bull;
            16 Graustufen
        </div>
    </div>
    <script>
        setInterval(function() {{
            document.getElementById('dashboard').src = '/dashboard.png?' + Date.now();
        }}, {refresh_seconds * 1000});
    </script>
</body>
</html>"""


@app.route("/dashboard.png")
def dashboard_png():
    with _lock:
        data = _current_image_bytes
    if data is None:
        return Response("Dashboard not yet rendered", status=503)
    return Response(data, mimetype="image/png",
                    headers={"Cache-Control": "no-cache"})


def start_server(
    get_dashboard_data: Callable[[], DashboardData],
    host: str | None = None,
    port: int | None = None,
):
    """Starte den Flask Dev-Server mit periodischem Rendering.

    Args:
        get_dashboard_data: Callable das DashboardData liefert.
        host: Bind-Adresse (default: 127.0.0.1).
        port: Server-Port (default: 8080).
    """
    host = host or config.WEB_HOST
    port = port or config.WEB_PORT

    # Initiales Rendering
    try:
        update_image(get_dashboard_data())
    except Exception as e:
        logger.error("Initiales Rendering fehlgeschlagen: %s", e)

    def refresh_loop():
        while True:
            time.sleep(config.RENDER_INTERVAL_SECONDS)
            try:
                update_image(get_dashboard_data())
            except Exception as e:
                logger.error("Render-Fehler: %s", e)

    t = threading.Thread(target=refresh_loop, daemon=True)
    t.start()

    logger.info("Dashboard: http://%s:%d", host, port)
    print(f"Dashboard: http://{host}:{port}")
    app.run(host=host, port=port, debug=False)
