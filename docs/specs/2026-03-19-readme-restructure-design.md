# README Restructure — Design Spec

**Date:** 2026-03-19
**Goal:** Restructure the repository documentation so a maker/hobbyist with a Solar Manager can go from unboxing to a working wall display as fast as possible, while preserving contributor context in dedicated files.

## Audience

Primary: Maker/hobbyist who owns a Solar Manager and wants to build the hardware. They don't care about codebase internals. They want: what do I buy, how do I set it up, how do I fix it if something goes wrong.

Secondary: Developer who wants to extend or contribute. Served by separate files.

## File Structure

### `README.md` — Install / Use / Troubleshoot

1. **Hero**
   - Project title
   - One-line description as blockquote
   - Placeholder for real hardware photo (swap in later)
   - Mock dashboard screenshots (3 existing v4 PNGs)
   - Short bullet list of what the display shows:
     - Live energy flow (solar, grid, home, battery)
     - 24h production vs. consumption chart with peak marker
     - 7-day energy history (kWh)
     - Multilingual: EN, DE, FR, IT

2. **What You Need**

   | Part | Specification |
   |---|---|
   | Solar Manager gateway | Any Solar Manager gateway exposing the local v2 API (`/v2/stream`, `/v2/point`) |
   | Raspberry Pi 5B | 4 GB RAM is fine as the reference target |
   | Waveshare 7.8" e-Paper HAT | IT8951 controller, 1872×1404, black/white panel with 2–16 grayscale levels |
   | microSD card | SanDisk Extreme PRO 128 GB (reference card) |
   | Power supply | USB-C, 5V/5A recommended for Pi 5 (5V/3A works only with reduced peripheral budget) |
   | Frame / mount | Your choice — display area is 7.8" diagonal |

   Note: VCOM voltage is printed on the display's FPC ribbon cable label. You'll need it during setup.

3. **Quick Start** (5 steps)

   1. **Flash Raspberry Pi OS** — Raspberry Pi OS Bookworm (64-bit); enable SSH and network during Raspberry Pi Imager setup
   2. **Clone and run setup**
      ```bash
      git clone <repo-url>
      cd solar-eink-dashboard
      bash scripts/setup-pi.sh
      ```
   3. **Edit `.env.local`** (created by setup script)
      ```dotenv
      SM_LOCAL_BASE_URL=https://<your-gateway-ip>
      EPAPER_VCOM=<from your display FPC label>
      DASHBOARD_LANGUAGE=EN
      ```
      Use the Solar Manager gateway IP, not the inverter IP. The setup script defaults language to `DE` — change to your preferred language.
   4. **Reboot, then validate the display**
      ```bash
      sudo reboot
      # after reboot:
      ./.venv312/bin/python scripts/epaper_test.py --vcom <your-vcom>
      ```
   5. **Start the dashboard**
      ```bash
      sudo systemctl start solar-dashboard
      sudo systemctl status solar-dashboard
      ```

4. **How It Works** (3–5 lines, not full architecture)

   Brief pipeline description:
   ```
   Solar Manager gateway → local collector → SQLite → HTML renderer → Playwright PNG → e-paper display
   ```
   One paragraph explaining: the Pi connects to the Solar Manager gateway on your LAN, collects live data via WebSocket stream, stores it locally, renders the dashboard as HTML, screenshots it to a grayscale PNG, and pushes it to the e-paper display periodically (default: every 60 seconds, configurable via `DISPLAY_UPDATE_INTERVAL`).

5. **Configuration**
   - `EPAPER_VCOM` — VCOM voltage from display FPC label (required for production)
   - TLS options (ordered by preference):
     1. `SM_LOCAL_TLS_FINGERPRINT_SHA256` — pin to gateway cert (recommended for self-signed)
     2. `SM_LOCAL_CA_BUNDLE` — path to custom CA bundle
     3. `SM_LOCAL_VERIFY_TLS=false` — last resort
   - Language: `DASHBOARD_LANGUAGE` — `EN` (default), `DE`, `FR`, `IT`
   - `DISPLAY_UPDATE_INTERVAL` — e-paper refresh cadence in seconds (default 60)
   - Full env var table (from current README, reformatted)

6. **Cloud Backfill (optional)**
   - What it does: fills in missing daily history after a restart
   - When you need it: only if you care about 7-day history continuity after power loss
   - The env vars (existing content, cleaned up)

7. **Development**
   - Dev machine setup (venv + requirements + playwright)
   - Mock mode command
   - Scenario preview URLs
   - Link to `CONTRIBUTING.md` for deeper workflow

8. **Troubleshooting**
   - New section. Common issues:
     - SPI not enabled / display not detected after setup
     - Wrong VCOM voltage (garbled display)
     - Gateway not found (wrong IP, firewall, inverter IP vs gateway IP)
     - Display not refreshing (check with `sudo systemctl status solar-dashboard` and `sudo journalctl -u solar-dashboard -f`)
     - TLS errors with self-signed gateway certs
   - Each issue: symptom → likely cause → fix command

9. **License**

### `CONTRIBUTING.md` — Developer Workflow

New file. Content sourced from current README sections that are developer-focused:

- Dev environment setup (already in README, move here as canonical)
- Running tests (`pytest`, integration tests)
- Mock mode and full scenario preview list (scenario URLs)
- Preview and screenshot regeneration
- Code/doc sync expectations (when architecture changes, update README + CLAUDE.md + context file)
- PR expectations (if any)

### `docs/architecture.md` — Technical Deep Dive

New file. Content sourced from current README:

- Architecture diagram (the existing text diagram)
- Key modules list
- Domain rules (Wh semantics, grid power formula, battery SOC, timezone handling)
- Current technical status and open items (partial refresh, thermal validation)
- API notes (stream vs. point, cloud backfill endpoints)

## What Gets Removed from README

- Architecture diagram → `docs/architecture.md`
- Key modules list → `docs/architecture.md`
- Domain rules section → `docs/architecture.md`
- Status section (working/open items) → `docs/architecture.md`
- Detailed developer setup → `CONTRIBUTING.md`
- Test commands → `CONTRIBUTING.md`
- Screenshot regeneration → `CONTRIBUTING.md`
- References to internal files (`tmp/`, `.ai/`, `CLAUDE.md`) → `CONTRIBUTING.md`

## What Gets Added (net new content)

- Hero blockquote + feature bullets
- Hardware BOM table with verified specs
- "How It Works" 3–5 line summary
- Troubleshooting section (common issues with fix commands)
- Hardware photo placeholder

## Design Decisions

- **No external links in BOM** — parts named precisely with model/SKU so they can be searched; links rot
- **Quick Start is 5 steps** — flash, clone+setup, configure, reboot+validate, start. Minimal path to working display.
- **Setup script creates `.env.local`** — quick start says "edit", not "create"
- **`systemctl enable` not in quick start** — setup script already handles it
- **Reboot is explicit** — SPI enable requires it; don't let users skip to hardware test
- **TLS config ordered by preference** — fingerprint pinning first, disable last
- **Troubleshooting is new** — highest-value addition for makers; doesn't exist today
- **CLAUDE.md unchanged** — it already has comprehensive developer context and is the AI-facing doc
- **Dropped `/v2/devices` from BOM** — not currently used by the application; avoid implying it's required
- **Pi OS version specified** — Bookworm 64-bit required for python3.12 from apt; older/32-bit images will fail
- **Language default mismatch noted** — setup script defaults to `DE`, Quick Start example shows `EN`; made explicit
- **Display interval is "configurable"** — avoids prose going stale if default changes
- **`journalctl` command in troubleshooting** — the primary debugging tool for systemd; name it explicitly
- **Mock mode stays briefly in README** — useful for makers validating without hardware; full scenario list moves to CONTRIBUTING.md
