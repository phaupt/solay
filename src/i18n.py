"""Small dashboard i18n helper for Switzerland's official languages."""

from __future__ import annotations

SUPPORTED_LANGUAGES = ("en", "de", "fr", "it")

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "page_title": "Solar Manager Dashboard Preview",
        "dashboard_aria": "Solar Manager dashboard preview",
        "chart_aria": "24 hour chart",
        "flow_aria": "Live energy flow",
        "history_aria": "7 day history",
        "last_update": "Last update",
        "stale": "stale",
        "no_live_data": "No live data",
        "unavailable": "unavailable",
        "produced": "produced",
        "consumed": "consumed",
        "today": "Today",
        "no_history": "No 7-day history yet",
        "current_day_empty": "No current-day data",
        "peak_production": "Peak Production",
    },
    "de": {
        "page_title": "Solar Manager Dashboard Vorschau",
        "dashboard_aria": "Solar Manager Dashboard Vorschau",
        "chart_aria": "24-Stunden-Diagramm",
        "flow_aria": "Live-Energiefluss",
        "history_aria": "7-Tage-Verlauf",
        "last_update": "Letztes Update",
        "stale": "veraltet",
        "no_live_data": "Keine Live-Daten",
        "unavailable": "nicht verfuegbar",
        "produced": "produziert",
        "consumed": "verbraucht",
        "today": "Heute",
        "no_history": "Noch keine 7-Tage-Historie",
        "current_day_empty": "Noch keine Daten fuer heute",
        "peak_production": "Spitzenproduktion",
    },
    "fr": {
        "page_title": "Apercu du tableau de bord Solar Manager",
        "dashboard_aria": "Apercu du tableau de bord Solar Manager",
        "chart_aria": "Graphique sur 24 heures",
        "flow_aria": "Flux d'energie en direct",
        "history_aria": "Historique sur 7 jours",
        "last_update": "Derniere mise a jour",
        "stale": "obsoletes",
        "no_live_data": "Pas de donnees en direct",
        "unavailable": "indisponible",
        "produced": "produit",
        "consumed": "consomme",
        "today": "Aujourd'hui",
        "no_history": "Pas encore d'historique sur 7 jours",
        "current_day_empty": "Pas encore de donnees pour aujourd'hui",
        "peak_production": "Pic de production",
    },
    "it": {
        "page_title": "Anteprima dashboard Solar Manager",
        "dashboard_aria": "Anteprima dashboard Solar Manager",
        "chart_aria": "Grafico delle 24 ore",
        "flow_aria": "Flusso energetico live",
        "history_aria": "Storico di 7 giorni",
        "last_update": "Ultimo aggiornamento",
        "stale": "non aggiornato",
        "no_live_data": "Nessun dato live",
        "unavailable": "non disponibile",
        "produced": "prodotto",
        "consumed": "consumato",
        "today": "Oggi",
        "no_history": "Nessuna cronologia di 7 giorni",
        "current_day_empty": "Nessun dato per oggi",
        "peak_production": "Picco di produzione",
    },
}

_WEEKDAYS: dict[str, list[str]] = {
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "de": ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"],
    "fr": ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"],
    "it": ["Lunedi", "Martedi", "Mercoledi", "Giovedi", "Venerdi", "Sabato", "Domenica"],
}

_WEEKDAY_SHORT: dict[str, list[str]] = {
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "de": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"],
    "fr": ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"],
    "it": ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"],
}

_TODAY_SHORT: dict[str, str] = {
    "en": "Today",
    "de": "Heute",
    "fr": "Auj.",
    "it": "Oggi",
}


def normalize_language(language: str | None) -> str:
    candidate = (language or "en").strip().lower()
    return candidate if candidate in SUPPORTED_LANGUAGES else "en"


def tr(language: str | None, key: str) -> str:
    lang = normalize_language(language)
    return _STRINGS.get(lang, _STRINGS["en"]).get(key, _STRINGS["en"].get(key, key))


def weekday_name(language: str | None, weekday_index: int) -> str:
    lang = normalize_language(language)
    labels = _WEEKDAYS.get(lang, _WEEKDAYS["en"])
    return labels[weekday_index]


def weekday_short_name(language: str | None, weekday_index: int) -> str:
    lang = normalize_language(language)
    labels = _WEEKDAY_SHORT.get(lang, _WEEKDAY_SHORT["en"])
    return labels[weekday_index]


def today_short(language: str | None) -> str:
    lang = normalize_language(language)
    return _TODAY_SHORT.get(lang, _TODAY_SHORT["en"])
