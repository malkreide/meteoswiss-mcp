# 🌦️ meteoswiss-mcp

[![CI](https://github.com/malkreide/meteoswiss-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/malkreide/meteoswiss-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/meteoswiss-mcp)](https://pypi.org/project/meteoswiss-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/meteoswiss-mcp)](https://pypi.org/project/meteoswiss-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![swiss-public-data-mcp](https://img.shields.io/badge/portfolio-swiss--public--data--mcp-blue)](https://github.com/malkreide/swiss-public-data-mcp)

**MCP-Server für Schweizer Wetter- und Klimadaten von MeteoSwiss.**

Verbindet KI-Modelle mit dem SwissMetNet-Messnetz (160+ Stationen, 10-Minuten-Intervall), MeteoSwiss ICON-CH1/CH2-EPS Prognosen und Klimanormwerten 1991–2020. Teil des [swiss-public-data-mcp](https://github.com/malkreide/swiss-public-data-mcp) Portfolios.

🇬🇧 [English version](README.md)

---

## Demo-Abfrage (Anker-Beispiel)

<img src="assets/demo.png" width="720" alt="Demo: Claude fragt nach Sporttag-Eignung → meteo_school_check Tool Call → strukturierte Wetterampel-Antwort">

```
Wie geeignet ist nächster Mittwoch für den Sporttag beim Schulhaus Leutschenbach?
```

→ `meteo_school_check(location="Zürich Oerlikon", activity="Sporttag")` liefert eine 🟢/🟡/🔴-Ampel für jeden Tag der nächsten Woche – direkt aus dem MeteoSwiss ICON-Modell.

**Kombiniert mit [swiss-environment-mcp](https://github.com/malkreide/swiss-environment-mcp):**

```
Wie war Luftqualität und Wetter beim Schulhaus Leutschenbach gestern?
```

→ `meteo_current(station='REH')` + `env_nabel_current(station='ZUE')` = vollständiges Umweltbild.
→ [Weitere Anwendungsbeispiele nach Zielgruppe](EXAMPLES.md) →

---

## Tools (6)

| Tool | Beschreibung | Datenquelle |
|------|-------------|-------------|
| `meteo_stations` | SwissMetNet-Stationen auflisten (kanton-filterbar) | Eingebettet |
| `meteo_current` | Aktuelle 10-min-Beobachtungen einer Station | BGDI STAC API |
| `meteo_forecast` | 1–16 Tage Prognose für Ort oder Koordinaten | Open-Meteo / MeteoSwiss ICON |
| `meteo_school_check` | 🟢/🟡/🔴 Ampel für Schulveranstaltungen im Freien | Open-Meteo / MeteoSwiss ICON |
| `meteo_climate_normals` | Monatliche Klimanormwerte 1991–2020 | Eingebettet (KLO, SMA, BER, LUG, GVE) |
| `meteo_warnings` | Aktive amtliche Wetterwarnungen (Sturm, Gewitter, Hitze, Waldbrand, …) — landesweit, pro Kanton oder pro PLZ | MeteoSwiss App-API + opendata.swiss |

### Tool Annotations (MCP-Hints)

Alle Tools tragen explizite [MCP-Annotations](https://modelcontextprotocol.io/specification/draft/server/tools#tool-annotations) — relevant für Client-Approval-UI und Sicherheitsentscheide des LLM.

| Tool | `readOnlyHint` | `destructiveHint` | `idempotentHint` | `openWorldHint` |
|------|---|---|---|---|
| `meteo_stations` | ✅ | ✗ | ✅ | ✗ (kuratierte Liste) |
| `meteo_current` | ✅ | ✗ | ✗ (Live-Daten) | ✅ (Upstream-STAC) |
| `meteo_forecast` | ✅ | ✗ | ✗ (Live-Daten) | ✅ (Upstream-Open-Meteo) |
| `meteo_school_check` | ✅ | ✗ | ✗ (Live-Daten) | ✅ (Geocoding + Forecast) |
| `meteo_climate_normals` | ✅ | ✗ | ✅ | ✗ (eingebettete Normwerte) |
| `meteo_warnings` | ✅ | ✗ | ✗ (Live-Daten) | ✅ (MeteoSwiss App-API) |

**Lese-Regeln**: alle 6 Tools sind `readOnly + non-destructive` — der Server kann grundsätzlich nichts schreiben oder löschen. `idempotentHint=False` markiert Tools, die je nach Zeitpunkt unterschiedliche Werte liefern.

### MCP Protocol Version

| Aspekt | Wert |
|---|---|
| Getestete Spec-Versionen | `2024-11-05`, `2025-03-26`, `2025-06-18` (via `mcp[cli]` SDK) |
| FastMCP-SDK-Version | siehe `pyproject.toml` → `mcp[cli]>=1.0.0` |
| Update-Policy | Dependabot bewacht `mcp[cli]`; Spec-Bumps werden im CHANGELOG mit «Tool Definition Changes»-Marker dokumentiert |

→ Vollständige Roadmap & Update-Strategie: [`docs/roadmap.md`](docs/roadmap.md)

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

Konfiguration via ENV-Variablen (CLI-Flags `--http` / `--port N` funktionieren weiterhin als Override):

| Variable | Default | Bedeutung |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | `stdio` oder `streamable-http` |
| `MCP_HOST` | `127.0.0.1` | Bind-Address — **lokal nie ändern** |
| `MCP_PORT` | `8000` | Port |
| `MCP_ALLOW_ANY_HOST` | _unset_ | Muss auf `1` gesetzt sein, damit der Server an `0.0.0.0` binden darf (nur in Container/Cloud) |
| `MCP_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` — strukturierte JSON-Logs auf stderr |
| `MCP_ALLOWED_ORIGINS` | _unset_ | Komma-separierte Liste erlaubter Origins für CORS. Leer = CORS deaktiviert (same-origin only). `Mcp-Session-Id` wird automatisch exposed. |
| `MCP_API_KEY` | _unset_ | Wenn gesetzt: alle Requests ausser `/health` brauchen `X-API-Key: <key>` oder `Authorization: Bearer <key>`. Constant-time-Vergleich. |
| `MCP_STATELESS_HTTP` | `0` | `1` aktiviert FastMCP-Stateless-Mode → jeder HTTP-Request öffnet eine neue Session. Voraussetzung für Multi-Replica-Deploys ohne Sticky-Sessions (SCALE-002/003). |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | _unset_ | Wenn gesetzt + `pip install meteoswiss-mcp[otel]`: OpenTelemetry-Spans pro Tool-Call + automatische httpx-Instrumentierung gehen als OTLP-HTTP an den Collector. |
| `OTEL_SERVICE_NAME` | `meteoswiss_mcp` | Service-Name in den OTel-Resources |
| `MCP_CACHE_ENABLED` | `1` | `0` schaltet den TTL-Cache komplett aus (z.B. für End-to-End-Tests) |
| `MCP_CACHE_TTL_STAC` | `300` | TTL in Sekunden für STAC-SMN-Beobachtungen (default 5 min) |
| `MCP_CACHE_TTL_OPEN_METEO` | `600` | TTL für ICON-Prognosen (default 10 min) |
| `MCP_CACHE_TTL_GEOCODING` | `3600` | TTL für Geocoding-Lookups (default 1 h) |
| `MCP_CACHE_TTL_OPENDATA` | `3600` | TTL für opendata.swiss-Katalog (default 1 h) |
| `MCP_CACHE_TTL_WARNINGS` | `300` | TTL für Warnungen (MeteoSwiss App-API / strukturierter Override; default 5 min) |
| `MCP_CLIMATE_NORMALS_PATH` | _unset_ | Pfad auf JSON-Datei mit zusätzlichen Klimanormwerten — siehe `data/climate-normals.example.json` |
| `MCP_WARNINGS_API_URL` | _unset_ | **Override** der Default-Quelle (MeteoSwiss App-API): URL einer strukturierten MeteoSwiss-Warnings-API (z.B. die künftige OGD-Warnings-REST-API). Host muss in der Egress-Allow-List stehen. Schema-tolerant (GeoJSON `features`, `warnings`-Array oder `items`). Unset → Live-App-API. |
| `MCP_CLIMATE_NORMALS_URL_TEMPLATE` | _unset_ | URL-Template für Runtime-Lookup von Klimanormwerten (für Stationen ohne eingebettete oder JSON-Werte). Tokens: `{station}` (lowercase), `{STATION}` (uppercase), `{param}` (MeteoSwiss-Code `tre200m0`/`rre150m0`/`sre000m0`). Beispiel: `https://data.geo.admin.ch/.../{station}/{param}.txt`. Host muss in der Egress-Allow-List stehen. |

```bash
# Lokaler Test (sicher, nur loopback)
MCP_TRANSPORT=streamable-http meteoswiss-mcp

# Container / Render
MCP_TRANSPORT=streamable-http MCP_HOST=0.0.0.0 MCP_ALLOW_ANY_HOST=1 meteoswiss-mcp
```

#### Docker / Render

Das Repo enthält ein produktionsfertiges **Multi-Stage-Dockerfile** (non-root user, HEALTHCHECK) und ein **`render.yaml`**-Blueprint:

```bash
# Lokal bauen + testen
docker build -t meteoswiss-mcp .
docker run --rm -p 8000:8000 meteoswiss-mcp
curl http://127.0.0.1:8000/health   # → {"status":"ok","service":"meteoswiss-mcp"}
```

Auf Render: «New → Blueprint» → Repo auswählen. Defaults (Plan `starter`, Frankfurt, single-instance) sind im `render.yaml` vorgegeben.

**Wichtig:** `numInstances: 1` ist bewusst gesetzt — Sticky-Session-Routing für Multi-Replica (Audit SCALE-002/003) ist noch nicht implementiert.

#### Structured Logging

Alle Tool-Invocations, Upstream-Failures und Egress-Blocks werden als JSON-Events auf `stderr` ausgegeben (stdio-Transport-sicher). Beispiel:

```json
{"tool": "meteo_forecast", "days": 7, "has_coords": false, "event": "tool_invoked", "level": "info", "timestamp": "2026-05-20T07:00:00Z"}
{"tool": "meteo_forecast", "endpoint": "geocoding", "error_type": "HTTPStatusError", "event": "upstream_failed", "level": "warning", "timestamp": "..."}
{"url": "https://evil.example.com/", "method": "GET", "reason": "host not in allow-list", "event": "egress_blocked", "level": "warning", "timestamp": "..."}
```

#### HTTP-Modus Sicherheit

- `MCP_HOST` defaultet bewusst auf `127.0.0.1`, damit `--http` auf dem Dev-Laptop nicht versehentlich ins lokale Subnetz exponiert ist (Audit-Finding SEC-016).
- Alle ausgehenden HTTP-Calls (auch Redirect-Follows) werden gegen eine Allow-List validiert: `data.geo.admin.ch`, `api.open-meteo.com`, `geocoding-api.open-meteo.com`, `opendata.swiss`. Andere Hosts und IP-Literale (insb. `169.254.169.254`, RFC1918) werden mit `EgressBlocked` abgelehnt (SEC-004 / SEC-021).
- **CORS**: per Default deaktiviert (same-origin only). Browser-Clients (z.B. claude.ai Web) brauchen `MCP_ALLOWED_ORIGINS=<csv>` — der `Mcp-Session-Id`-Header ist dann automatisch in `Access-Control-Expose-Headers` (SDK-004).
- **API-Key-Auth**: per Default deaktiviert. Im produktiven HTTP-Setup unbedingt `MCP_API_KEY=<random>` setzen — Requests ohne gültigen `X-API-Key` oder `Authorization: Bearer …` werden mit 401 abgelehnt (SEC-009 / SEC-013). `/health` bleibt für Container-Health-Probes offen.

#### Beispiel: produktiver HTTP-Stack

```bash
# 32 Bytes Zufall als Auth-Key
export MCP_API_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")

MCP_TRANSPORT=streamable-http \
MCP_HOST=0.0.0.0 \
MCP_ALLOW_ANY_HOST=1 \
MCP_ALLOWED_ORIGINS=https://app.example.com \
MCP_API_KEY="$MCP_API_KEY" \
meteoswiss-mcp
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
        └── meteo_warnings ──────────────── app-prod-ws.meteoswiss-app.ch
                                            (MeteoSwiss App-API) + opendata.swiss
```

### Datenquellen

| Quelle | URL | Lizenz |
|--------|-----|--------|
| BGDI STAC API (MeteoSwiss OGD) | `data.geo.admin.ch/api/stac/v1` | CC BY 4.0 |
| Open-Meteo (MeteoSwiss ICON) | `api.open-meteo.com/v1/meteoswiss` | CC BY 4.0 |
| Open-Meteo Geocoding | `geocoding-api.open-meteo.com` | CC BY 4.0 |
| opendata.swiss CKAN | `opendata.swiss/api/3/action` | CC BY 4.0 |
| MeteoSwiss App-API (Warnungen) | `app-prod-ws.meteoswiss-app.ch/v1/plzDetail` | CC BY 4.0 |

---

## Safety & Limits

| Aspekt | Details |
|--------|---------|
| **Zugriff** | Nur-Lesen (`readOnlyHint: true` auf allen Tools) — der Server kann keine Daten verändern oder löschen |
| **Personendaten** | Keine Personendaten — alle Quellen liefern aggregierte, öffentliche Open Data |
| **Rate Limits** | Eingebaute Limits pro Abfrage: max. 50 Ergebnisse pro API-Call, 30 s Timeout |
| **Authentifizierung** | Kein API-Key erforderlich — alle Datenquellen sind öffentlich zugänglich |
| **Lizenzen** | Alle Daten unter CC BY 4.0 (MeteoSwiss Open Government Data) |
| **Nutzungsbedingungen** | Es gelten die Nutzungsbedingungen der jeweiligen Datenquellen: [MeteoSwiss OGD](https://www.meteoswiss.admin.ch/services-and-publications/service/open-government-data.html), [Open-Meteo](https://open-meteo.com/en/terms), [opendata.swiss](https://opendata.swiss/de/terms-of-use) |

---

## Bekannte Einschränkungen

| ID | Tool | Beschreibung |
|----|------|-------------|
| BUG-01 | `meteo_current` | STAC Asset-Struktur kann je nach Station variieren; Fallback zu direktem Link implementiert |
| LIM-01 | `meteo_climate_normals` | Nur 5 Stationen eingebettet (KLO, SMA, BER, LUG, GVE); restliche via opendata.swiss-Link |
| LIM-02 | `meteo_warnings` | Live-Warnungen stammen aus der **MeteoSwiss App-API** (`plzDetail`) — öffentlich und ohne Auth, aber undokumentiert (App-Backend, nicht die OGD-REST-API). Es gibt keinen landesweiten Endpoint, daher aggregiert die Schweiz-Sicht je eine Kantonshauptort-PLZ pro Kanton (sub-regionale Warnungen ausserhalb dieser PLZ können fehlen — mit `plz`/`canton` eingrenzen). `MCP_WARNINGS_API_URL` überschreibt die Quelle, sobald die offizielle OGD-Warnings-REST-API verfügbar ist. |
| LIM-03 | `meteo_current` | Zeigt 10-min-Werte in UTC; keine automatische Umrechnung in lokale Zeit |

### Zuständigkeitsmatrix — Schnee & Niederschlag (Abgrenzung zu `swiss-environment-mcp`)

Damit sich **Schnee- und Niederschlagsdaten** im Portfolio nicht duplizieren, sind
die Zuständigkeiten wie folgt aufgeteilt. `meteoswiss-mcp` verantwortet den
atmosphärischen Niederschlag und das Wetter; `swiss-environment-mcp` (SLF-Domäne)
verantwortet Schnee am Boden und Lawinengefahr.

| Grösse | meteoswiss-mcp (MeteoSchweiz) | swiss-environment-mcp (BAFU / SLF) |
|---|---|---|
| Niederschlagsmenge (mm): Messnetz, Prognose, Klimanormwerte | ✅ `meteo_current` / `meteo_forecast` / `meteo_climate_normals` | ❌ |
| Schneefall als aktuelle Wetterlage | ✅ `meteo_current` / `meteo_forecast` (Wettercode) | ❌ |
| Wetterwarnungen (Sturm, Gewitter, Hitze) | ✅ `meteo_warnings` | ❌ |
| Schneehöhe am Boden (`HS`) | ❌ | ✅ SLF IMIS / Beobachtungsfeld ¹ |
| Neuschnee 24 h (`HN_1D`) | ❌ | ✅ SLF ¹ |
| Lawinenwarnstufe | ❌ | ✅ SLF-Lawinenbulletin ¹ |
| Naturgefahren-Warnungen (Hochwasser, Lawine, Waldbrand) | ❌ | ✅ `env_flood_warnings`, `env_hazard_*`, `env_wildfire_danger` |

**Regel:** **atmosphärischer Niederschlag** (Regen/Schneefall als mm) sowie Wetter,
Prognose, Warnungen und Klimanormwerte gehören zu `meteoswiss-mcp`; Schnee **am
Boden** und **Lawinengefahr** gehören zu `swiss-environment-mcp` (SLF). Der
IMIS-Niederschlagssensor des SLF dient dort nur als Kontext zur Schneedecke und
wird nie als Niederschlags-Tool exponiert — damit keine Duplikation mit
MeteoSchweiz.

¹ SLF-/Schnee-Tools in `swiss-environment-mcp` sind in Vorbereitung
(Phase-1-Live-Probe abgeschlossen am 2026-07-19, siehe `docs/probe-slf.md` in jenem
Repo); die Abgrenzung wird bereits jetzt fixiert, damit die beiden Server bei der
Umsetzung nicht kollidieren.

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

## Mitwirken & Sicherheit

- [Beitragsrichtlinien](CONTRIBUTING.de.md) ([English](CONTRIBUTING.md))
- [Sicherheitsrichtlinie](SECURITY.de.md) ([English](SECURITY.md))

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
</content>
