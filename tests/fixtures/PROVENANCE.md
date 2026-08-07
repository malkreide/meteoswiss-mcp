# Herkunft der Fixtures

**Erzeugt von `scripts/record_fixtures.py`. Nicht von Hand pflegen.**

Aufgezeichnet am **2026-08-07** von den drei Quellen dieses Servers:
`https://data.geo.admin.ch/api/stac/v1`, `https://app-prod-ws.meteoswiss-app.ch/v1` und `https://api.open-meteo.com/v1/forecast`.

Ohne Datum ist «aufgezeichnet» nach zwei Jahren von «ausgedacht» nicht
mehr zu unterscheiden — die Datei sieht gleich aus.

**Wetterdaten altern schnell.** Diese Fixtures belegen die *Form* der
Antwort und einen datierten Ausschnitt ihres Inhalts — Temperaturen und
Warnungen darin sind der Stand des Aufzeichnungstags und keine Aussage
ueber heute. Zusicherungen in den Tests leiten ihre Erwartungen deshalb
aus der Fixture ab, statt Zahlen hineinzuschreiben.

## `stac_item_klo.json`

- **Quelle:** `https://data.geo.admin.ch/api/stac/v1/collections/ch.meteoschweiz.ogd-smn/items/klo`
- **Aufgezeichnet:** 2026-08-07
- **Auswahl:** vollstaendig; 16 Assets, davon 11 Ablenker (Historik/Monat/Jahr), die der Selektor ablehnen muss
- **Groesse:** 7415 B
- **SHA-256:** `add6451f433b0405e3082f725956352fc4babc32a34e9bfda931a09d45aa5640`

## `smn_now.csv`

- **Quelle:** `https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/klo/ogd-smn_klo_t_now.csv`
- **Aufgezeichnet:** 2026-08-07
- **Auswahl:** Kopfzeile unveraendert (34 Spalten — die handgeschriebene Vorgaengerin hatte 7); die letzten 3 von 115 Zeilen. Enthaelt 15 leere Zellen, wie die Quelle sie liefert
- **Groesse:** 735 B
- **SHA-256:** `c0174ed322f0f67ae0c13675a60033347dacfa6cdeb05d5d0a142da6e9f6fa73`

## `app_plz_detail.json`

- **Quelle:** `https://app-prod-ws.meteoswiss-app.ch/v1/plzDetail?plz=800100`
- **Aufgezeichnet:** 2026-08-07
- **Auswahl:** vollstaendig fuer PLZ 800100; Felder ['currentWeather', 'forecast', 'graph', 'klimaGraph', 'warnings', 'warningsOverview'] — «warnings» mit 1 Eintrag/Eintraegen
- **Groesse:** 35632 B
- **SHA-256:** `b4353469d87bfa5e9ad9337abb31ddfe6d97280873ee8d7d5b39e3c79d7cbec9`

## `open_meteo_forecast.json`

- **Quelle:** `https://api.open-meteo.com/v1/forecast?latitude=47.3769&longitude=8.5417&daily=temperature_2m_max%2Ctemperature_2m_min%2Cprecipitation_sum%2Cweathercode&timezone=Europe%2FZurich&forecast_days=7`
- **Aufgezeichnet:** 2026-08-07
- **Auswahl:** vollstaendig; 7 Tage fuer Zuerich (47.3769, 8.5417), Variablen ['precipitation_sum', 'temperature_2m_max', 'temperature_2m_min', 'time', 'weathercode']
- **Groesse:** 1000 B
- **SHA-256:** `629f4329d73836844a277038606c732a1d9cd65c210d695e2a4edd9aea610b01`
