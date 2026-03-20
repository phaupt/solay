# GitHub Discovery Checklist

Repo content can improve first impressions, but these items still need to be set in the GitHub UI.

## Suggested Repository Description

Solar Manager dashboard for Waveshare e-paper on Raspberry Pi. Shows live energy flow, today's production vs. consumption, and 7-day history.

## Suggested Topics

Use 10 to 12 literal topics that match how people search:

- `solar-manager`
- `raspberry-pi`
- `waveshare`
- `e-paper`
- `eink-display`
- `energy-dashboard`
- `home-energy`
- `solar-monitoring`
- `photovoltaic`
- `pv`
- `smart-home`
- `python`

## Suggested Social Preview

Create a `1280x640` image with:

- the hardware photo on one side
- one dashboard screenshot on the other side
- headline: `Solar Manager E-Paper Dashboard`
- subheadline: `Waveshare + Raspberry Pi wall display`

Upload it in GitHub under `Settings -> General -> Social preview`.

## Suggested First Release

Tag: `v0.1.0`

Release title:

`v0.1.0 - First public Raspberry Pi build`

Release notes:

```md
## Highlights

- Solar Manager dashboard for Waveshare 7.8" e-paper on Raspberry Pi
- Live energy flow, 24h production vs. consumption chart, and 7-day history
- Local data collection with SQLite persistence
- HTML/CSS/SVG rendering pipeline exported to grayscale PNG for the display
- Multilingual UI: English, German, French, Italian

## Getting Started

See the README for the Raspberry Pi setup flow, `.env.local` configuration, display test, and service startup.

## Known Constraints

- Full history continuity is optional. Without Solar Manager cloud credentials, the dashboard still works, but the 7-day history only includes data collected locally on this Pi.
- Production deployment expects the Waveshare IT8951-based 7.8" panel
```
