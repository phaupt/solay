# Contributing

Developer workflow for the Solar E-Ink Dashboard. For setup and usage, see [README.md](README.md). For architecture and domain rules, see [docs/architecture.md](docs/architecture.md).

## Dev Environment Setup

```bash
python3.12 -m venv .venv312
./.venv312/bin/pip install -r requirements.txt
./.venv312/bin/python -m playwright install chromium
```

## Running Tests

```bash
# All unit tests
./.venv312/bin/pytest -q

# Single test file
./.venv312/bin/pytest tests/test_aggregator.py -v

# Integration tests (requires real gateway on LAN)
RUN_LOCAL_SM_TESTS=1 ./.venv312/bin/pytest tests/test_local_api_integration.py -v
```

## Preview Modes

### Mock preview

```bash
./.venv312/bin/python main.py --mock --port 8090
```

Open:

- `http://127.0.0.1:8090/` for the default mock dashboard
- `http://127.0.0.1:8090/scenarios` for the full scenario + language matrix

Supported scenario URLs:

- `/?scenario=pv_surplus`
- `/?scenario=pv_deficit`
- `/?scenario=night`
- `/?scenario=battery_support`
- `/?scenario=grid_charge`
- `/?scenario=no_battery`
- `/?scenario=stale`

These scenario previews keep the same 24h chart context, including the peak-production marker.

### Live preview

```bash
./.venv312/bin/python main.py --port 8080
```

Open `http://127.0.0.1:8080/`. Live mode uses your local Solar Manager gateway data via `/v2/stream`, with `/v2/point` as fallback. The browser preview auto-refreshes every 15 seconds.

### PNG export

```bash
./.venv312/bin/python main.py --mock --export-png out/dashboard.png
./.venv312/bin/python main.py --export-png out/live-dashboard.png
```

The export path renders the same HTML/CSS/SVG dashboard through Playwright and writes a PNG at `1872x1404`. Output is quantized to 16 grayscale levels for the E-Ink target.

## Regenerating README Screenshots

The README depends on three mock screenshots in `docs/screenshots/`. If they are missing or outdated, regenerate them:

```bash
./.venv312/bin/python scripts/generate_readme_screenshots.py
```

## Documentation Sync

When the architecture or main screen changes, update all four:

- `README.md`
- `docs/architecture.md`

## Useful Reference Files

- `tmp/solar-eink-dashboard-PROJECT.md` — full product spec (German)
- `tmp/Solar Manager API.pdf` — official API docs
