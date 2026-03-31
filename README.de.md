# meteoswiss-mcp

[![CI](https://github.com/malkreide/meteoswiss-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/malkreide/meteoswiss-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/meteoswiss-mcp)](https://pypi.org/project/meteoswiss-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/meteoswiss-mcp)](https://pypi.org/project/meteoswiss-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![swiss-public-data-mcp](https://img.shields.io/badge/portfolio-swiss--public--data--mcp-blue)](https://github.com/malkreide/swiss-public-data-mcp)

**MCP-Server für Schweizer Wetter- und Klimadaten von MeteoSwiss.**

Verbindet KI-Modelle mit dem SwissMetNet-Messnetz (160+ Stationen, 10-Minuten-Intervall), MeteoSwiss ICON-CH1/CH2-EPS Prognosen und Klimanormwerten 1991–2020. Teil des [swiss-public-data-mcp](https://github.com/malkreide/swiss-public-data-mcp) Portfolios.

→ [English README](README.md)

---

## Demo-Abfrage (Anker-Beispiel)

```
Wie geeignet ist nächster Mittwoch für den Sporttag beim Schulhaus Leutschenbach?
```

→ `meteo_school_check(location="Zürich Oerlikon", activity="Sporttag")` liefert eine 🟢/🟡/🔴-Ampel für jeden Tag der nächsten Woche – direkt aus dem MeteoSwiss ICON-Modell.

**Kombiniert mit [swiss-environment-mcp](https://github.com/malkreide/swiss-environment-mcp):**

```
Wie war Luftqualität und Wetter beim Schulhaus Leutschenbach gestern?
```

→ `meteo_current(station='REH')` + `env_nabel_current(station='ZUE')` = vollständiges Umweltbild.

---

## Tools (6)

| Tool | Beschreibung | Datenquelle |
|------|-------------|-------------|
| `meteo_stations` | SwissMetNet-Stationen auflisten (kanton-filterbar) | Eingebettet |
| `meteo_current` | Aktuelle 10-min-Beobachtungen einer Station | BGDI STAC API |
| `meteo_forecast` | 1–16 Tage Prognose für Ort oder Koordinaten | Open-Meteo / MeteoSwiss ICON |
| `meteo_school_check` | 🟢/🟡/🔴 Ampel für Schulveranstaltungen im Freien | Open-Meteo / MeteoSwiss ICON |
| `meteo_climate_normals` | Monatliche Klimanormwerte 1991–2020 | Eingebettet (KLO, SMA, BER, LUG, GVE) |
| `meteo_warnings` | Aktuelle Wetterwarnungen & Links | opendata.swiss + Links |

---

## Schnellstart

### Claude Desktop

```json
{
  "mcpServers": {
    "meteoswiss": {
      "command": "uvx",
      "args": ["meteoswiss-mcp"]
    }
  }
}
```

### Claude Desktop (lokale Entwicklung)

```json
{
  "mcpServers": {
    "meteoswiss": {
      "command": "uv",
      "args": ["run", "--directory", "/pfad/zu/meteoswiss-mcp", "meteoswiss-mcp"]
    }
  }
}
```

### Cloud / Render.com (Streamable HTTP)

```bash
python -m meteoswiss_mcp.server --http --port 8000
```

---

## Beispiel-Abfragen

### Schulplanung

```
Welche Tage eignen sich nächste Woche für einen Sporttag in Zürich?
→ meteo_school_check(location="Zürich", activity="Sporttag")

Wie wird das Wetter am Schulhaus Leutschenbach am Freitag?
→ meteo_forecast(location="Zürich Oerlikon", days=5)

Zeig mir aktuelle Messwerte der nächsten MeteoSwiss-Station zu Zürich-Schwamendingen.
→ meteo_current(station="REH")
```

### Klimavergleich

```
Wie viel Regen fällt normalerweise im Juni in Zürich?
→ meteo_climate_normals(station="KLO")

Ist Lugano wirklich deutlich sonniger als Zürich? Zeig mir die Jahreswerte.
→ meteo_climate_normals(station="LUG") + meteo_climate_normals(station="SMA")
```

### Infrastruktur & Umwelt

```
Gibt es aktuell Wetterwarnungen für den Kanton Zürich?
→ meteo_warnings(canton="ZH")

Zeig mir eine 10-Tage-Prognose für die Schulanlage Heerenschürli mit Stundenwerten.
→ meteo_forecast(location="Sportanlage Heerenschürli Zürich", days=10, hourly=True)
```

---

## Architektur

```
Claude Desktop / KI-Agent
        │
        │ MCP (stdio / Streamable HTTP)
        ▼
meteoswiss-mcp (FastMCP)
        │
        ├── meteo_stations ──────────────── [eingebettet: ~20 SMN-Stationen]
        │
        ├── meteo_current ───────────────── BGDI STAC API
        │                                   data.geo.admin.ch/api/stac/v1
        │                                   Collection: ch.meteoschweiz.ogd-smn
        │
        ├── meteo_forecast ──────────────── Open-Meteo
        ├── meteo_school_check ──────────── api.open-meteo.com/v1/meteoswiss
        │                                   (MeteoSwiss ICON-CH1/CH2-EPS, 1–2 km)
        │
        ├── meteo_climate_normals ───────── [eingebettet: Normwerte 1991–2020]
        │
        └── meteo_warnings ──────────────── opendata.swiss CKAN + Links
```

### Datenquellen

| Quelle | URL | Lizenz |
|--------|-----|--------|
| BGDI STAC API (MeteoSwiss OGD) | `data.geo.admin.ch/api/stac/v1` | CC BY 4.0 |
| Open-Meteo (MeteoSwiss ICON) | `api.open-meteo.com/v1/meteoswiss` | CC BY 4.0 |
| Open-Meteo Geocoding | `geocoding-api.open-meteo.com` | CC BY 4.0 |
| opendata.swiss CKAN | `opendata.swiss/api/3/action` | CC BY 4.0 |

---

## Bekannte Einschränkungen

| ID | Tool | Beschreibung |
|----|------|-------------|
| BUG-01 | `meteo_current` | STAC Asset-Struktur kann je nach Station variieren; Fallback zu direktem Link implementiert |
| LIM-01 | `meteo_climate_normals` | Nur 5 Stationen eingebettet (KLO, SMA, BER, LUG, GVE); restliche via opendata.swiss-Link |
| LIM-02 | `meteo_warnings` | Direkte Warnings-REST-API geplant ab Q2 2026 (MeteoSwiss OGD Phase 2); aktuell Links + CAP |
| LIM-03 | `meteo_current` | Zeigt 10-min-Werte in UTC; keine automatische Umrechnung in lokale Zeit |

---

## Synergien im Portfolio

```
meteoswiss-mcp
    │
    ├── swiss-environment-mcp   Kombiniere Wetter + Luftqualität (NABEL)
    │                           «Wie war Wetter UND Luft beim Schulhaus Leutschenbach?»
    │
    └── zurich-opendata-mcp     Schulhausstandorte → Wetterprognose
                                «Welche Schulen in Zürich haben Sporttag-Wetter?»
```

---

## Testing

```bash
# Unit-Tests (kein Netzwerk)
PYTHONPATH=src pytest tests/ -m "not live" -v

# Live-Tests (echte APIs)
PYTHONPATH=src pytest tests/ -m live -v

# Linting
ruff check src/ tests/
```

---

## Entwicklung

```bash
git clone https://github.com/malkreide/meteoswiss-mcp
cd meteoswiss-mcp
pip install -e ".[dev]"
```

### MCP Inspector (lokaler Test)

```bash
PYTHONPATH=src npx @modelcontextprotocol/inspector python -m meteoswiss_mcp.server
```

---

## Lizenz

MIT License – siehe [LICENSE](LICENSE).

Quelldaten: MeteoSwiss Open Government Data (CC BY 4.0).
Bei Nutzung der Daten: **Quelle: MeteoSchweiz** angeben.

---

## Verwandte Server

[![swiss-environment-mcp](https://img.shields.io/badge/server-swiss--environment--mcp-green)](https://github.com/malkreide/swiss-environment-mcp)
[![zurich-opendata-mcp](https://img.shields.io/badge/server-zurich--opendata--mcp-green)](https://github.com/malkreide/zurich-opendata-mcp)
[![swiss-transport-mcp](https://img.shields.io/badge/server-swiss--transport--mcp-green)](https://github.com/malkreide/swiss-transport-mcp)
