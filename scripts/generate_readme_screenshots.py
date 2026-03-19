#!/usr/bin/env python3
"""Generate README screenshots from the native HTML export path.

This avoids viewport-scaled browser screenshots and instead renders the
dashboard at the real target resolution (1872x1404), which is closer to the
actual on-device/browser appearance.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from main import build_mock_dashboard_data
from mock_data import seed_mock_database
from src.export_dashboard import export_dashboard_png
from src.preview_scenarios import apply_preview_scenario
from src.storage import Storage

SCREENSHOT_DIR = ROOT / "docs" / "screenshots"


def main() -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="solar-readme-shots-") as tmpdir:
        db_path = Path(tmpdir) / "mock.db"
        storage = Storage(db_path)
        seed_mock_database(storage)
        base = build_mock_dashboard_data(storage)

        targets = [
            ("mock-dashboard-v4.png", None),
            ("mock-dashboard-no-battery-v4.png", "no_battery"),
            ("mock-dashboard-pv-surplus-v4.png", "pv_surplus"),
        ]

        for filename, scenario in targets:
            data = apply_preview_scenario(base, scenario) if scenario else base
            export_dashboard_png(
                data,
                SCREENSHOT_DIR / filename,
                grayscale_levels=0,
            )
            print(filename)


if __name__ == "__main__":
    main()
