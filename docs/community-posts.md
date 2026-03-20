# Community Outreach Drafts

Use these as tailored launch posts instead of posting the same generic text everywhere.

## Recommended Order

1. Solar Manager community
2. Photovoltaikforum
3. Akkudoktor
4. Raspberry Pi or e-paper maker community
5. Home Assistant community only as a side audience, not the main pitch

## Suggested Communities

- Solar Manager community: <https://solarmanager.zohodesk.com/portal/en/home>
- Photovoltaikforum: <https://www.photovoltaikforum.com/thread/197303-solarmanager-ch-solar-manager-kennt-jemand-das-system/>
- Akkudoktor: <https://akkudoktor.net/t/enphase-pv-anlage-integration-solar-manager-fur-nicht-enphase-komponenten/19038>
- Raspberry Pi subreddit: <https://www.reddit.com/r/raspberry_pi/>
- Home Assistant "Share your Projects!": <https://community.home-assistant.io/c/projects/27>

## Core Positioning

- This is for Solar Manager owners who want a dedicated always-on wall display.
- The hardware target is a Raspberry Pi 5 plus a Waveshare 7.8" e-paper display.
- The dashboard uses the local Solar Manager API for live data and can optionally use the cloud only for history continuity after restarts.

## Solar Manager Community Draft

Best fit: owner or user communities where people already know what Solar Manager is.

```md
I built an open-source wall display for Solar Manager and wanted to share it here in case it is useful to other owners.

It runs on a Raspberry Pi 5 with a Waveshare 7.8" e-paper display and shows:

- live energy flow between PV, grid, home, and battery
- a 24-hour production vs. consumption chart
- a 7-day history view
- English, German, French, and Italian

The main idea was to have a quiet always-on display instead of keeping a tablet mounted on the wall.

Repo and setup guide:
https://github.com/phaupt/solay

If other Solar Manager users try it, I would be interested in feedback on:

- hardware choices and mounting
- local API stability on different gateways
- what information is most useful on a wall display
```

## PV Forum Draft

Best fit: German-speaking photovoltaic, battery, and home energy forums such as Photovoltaikforum or Akkudoktor.

```md
Ich habe ein Open-Source-Projekt gebaut, das Solar Manager Daten auf einem Waveshare 7.8" E-Paper Display anzeigt.

Ziel war ein stromsparendes Wanddisplay auf Raspberry Pi 5, das ohne Tablet dauerhaft laufen kann.

Aktuell zeigt das Dashboard:

- Live-Energiefluss zwischen PV, Netz, Haus und Batterie
- 24h Produktion vs. Verbrauch
- 7-Tage-Verlauf
- Mehrsprachig: DE, EN, FR, IT

Technisch nutzt es die lokale Solar Manager API fuer Live-Daten. Optional kann der Solar Manager Cloud-Zugang nur fuer die Historie nach Neustarts verwendet werden, ist aber fuer den normalen Betrieb nicht noetig.

Projekt:
https://github.com/phaupt/solay

Mich wuerde interessieren:

- ob es hier weitere Solar Manager Nutzer gibt
- welche Anzeigeelemente fuer euch am wichtigsten waeren
- ob Interesse an einer vorkonfigurierten Raspberry-Pi-Variante besteht
```

## Raspberry Pi / Maker Draft

Best fit: Raspberry Pi, e-paper, and DIY dashboard communities.

```md
I built an open-source Solar Manager wall dashboard on Raspberry Pi 5 + Waveshare 7.8" e-paper.

The goal was a high-resolution always-on home energy display that stays readable from a distance and uses far less power than a tablet.

What it shows:

- live solar / grid / home / battery flow
- 24-hour production vs. consumption chart
- 7-day history
- multilingual UI

It uses the local Solar Manager API for live data, stores points in SQLite, renders the UI as HTML/CSS/SVG, and exports it to grayscale PNG for the e-paper panel.

Repo:
https://github.com/phaupt/solay

Happy to compare notes with anyone building e-paper dashboards or other low-power wall displays.
```

## Posting Notes

- Use the product photo plus one screenshot as the lead image.
- Avoid calling it a general solar dashboard. The strongest angle is `Solar Manager wall display`.
- Mention that cloud login is optional and only relevant for filling history gaps after restarts.
- Ask one concrete question in each post so people have an easy way to reply.
- Do not post the exact same text everywhere. Keep the opening sentence and the question tailored to the audience.
