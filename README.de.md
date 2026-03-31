# meteoswiss-mcp

**MCP-Server für Schweizer Wetter- und Klimadaten von MeteoSwiss.**

Verbindet KI-Modelle mit dem SwissMetNet-Messnetz (160+ Stationen), MeteoSwiss ICON-CH1/CH2-EPS Prognosen und Klimanormwerten 1991–2020. Teil des [swiss-public-data-mcp](https://github.com/malkreide/swiss-public-data-mcp) Portfolios.

→ [English README](README.md)

---

## Demo-Abfrage

```
Welche Tage eignen sich nächste Woche für den Sporttag beim Schulhaus Leutschenbach?
```

→ `meteo_school_check(location="Zürich Oerlikon", activity="Sporttag")`

---

## Tools

| Tool | Funktion |
|------|---------|
| `meteo_stations` | SwissMetNet-Stationen auflisten |
| `meteo_current` | Aktuelle 10-min-Beobachtungen |
| `meteo_forecast` | 1–16 Tage Prognose |
| `meteo_school_check` | Ampel für Schulveranstaltungen im Freien |
| `meteo_climate_normals` | Klimanormwerte 1991–2020 |
| `meteo_warnings` | Aktuelle Wetterwarnungen |

## Schnellstart (Claude Desktop)

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

## Datenquellen

- **BGDI STAC API** (data.geo.admin.ch): SwissMetNet-Beobachtungen
- **Open-Meteo** (api.open-meteo.com): MeteoSwiss ICON-CH1/CH2-EPS Prognosen
- **opendata.swiss**: MeteoSwiss Datenkatalog

Lizenz der Quelldaten: Creative Commons BY 4.0 – **Quelle: MeteoSchweiz** angeben.

## Lizenz

MIT License – siehe [LICENSE](LICENSE).
