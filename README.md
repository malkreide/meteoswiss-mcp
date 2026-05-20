# meteoswiss-mcp

[![CI](https://github.com/malkreide/meteoswiss-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/malkreide/meteoswiss-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/meteoswiss-mcp)](https://pypi.org/project/meteoswiss-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/meteoswiss-mcp)](https://pypi.org/project/meteoswiss-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![swiss-public-data-mcp](https://img.shields.io/badge/portfolio-swiss--public--data--mcp-blue)](https://github.com/malkreide/swiss-public-data-mcp)

**MCP Server für Schweizer Wetter- und Klimadaten von MeteoSwiss.**

Verbindet KI-Modelle mit dem SwissMetNet-Messnetz (160+ Stationen, 10-Minuten-Intervall), MeteoSwiss ICON-CH1/CH2-EPS Prognosen und Klimanormwerten 1991–2020. Teil des [swiss-public-data-mcp](https://github.com/malkreide/swiss-public-data-mcp) Portfolios.

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
→ [More use cases by audience](EXAMPLES.md) →

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

### Tool Annotations (MCP-Hints)

Alle Tools tragen explizite [MCP-Annotations](https://modelcontextprotocol.io/specification/draft/server/tools#tool-annotations) — relevant für Client-Approval-UI und Sicherheitsentscheide des LLM.

| Tool | `readOnlyHint` | `destructiveHint` | `idempotentHint` | `openWorldHint` |
|------|---|---|---|---|
| `meteo_stations` | ✅ | ✗ | ✅ | ✗ (kuratierte Liste) |
| `meteo_current` | ✅ | ✗ | ✗ (Live-Daten) | ✅ (Upstream-STAC) |
| `meteo_forecast` | ✅ | ✗ | ✗ (Live-Daten) | ✅ (Upstream-Open-Meteo) |
| `meteo_school_check` | ✅ | ✗ | ✗ (Live-Daten) | ✅ (Geocoding + Forecast) |
| `meteo_climate_normals` | ✅ | ✗ | ✅ | ✗ (eingebettete Normwerte) |
| `meteo_warnings` | ✅ | ✗ | ✗ (Live-Daten) | ✅ (opendata.swiss) |

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

## Safety & Limits

| Aspect | Details |
|--------|---------|
| **Access** | Read-only (`readOnlyHint: true` on all tools) — the server cannot modify or delete any data |
| **Personal data** | No personal data — all sources are aggregated, publicly available open data |
| **Rate limits** | Built-in per-query caps: max 50 results per API call, 30 s timeout |
| **Authentication** | No API keys required — all data sources are publicly accessible |
| **Licenses** | All data under CC BY 4.0 (MeteoSwiss Open Government Data) |
| **Terms of Service** | Subject to ToS of the respective data sources: [MeteoSwiss OGD](https://www.meteoswiss.admin.ch/services-and-publications/service/open-government-data.html), [Open-Meteo](https://open-meteo.com/en/terms), [opendata.swiss](https://opendata.swiss/de/terms-of-use) |

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
