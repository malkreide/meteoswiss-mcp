# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Behoben

- **`mcp` auf `<2` begrenzt.** `mcp` 2.0.0, veröffentlicht am 28.07.2026, hat
  `mcp.server.fastmcp` entfernt — genau das Modul, das dieser Server importiert.
  Mit dem bisherigen offenen `>=1.28.1` wählte jede frische Auflösung 2.0.0 und
  scheiterte beim Import mit `ModuleNotFoundError`, in der CI ebenso wie bei
  jedem `pip install`. In beide Richtungen verifiziert: 2.0.0 scheitert, `<2`
  löst auf 1.29.0 auf und importiert sauber. Die Migration auf die 2.x-API
  (`mcp.server.mcpserver`) bleibt eine eigene, bewusste Aufgabe.

## [0.4.0] - 2026-07-26

Feature-Release: `meteo_warnings` liefert neu **echte Live-Warnungen** aus dem
öffentlichen MeteoSwiss-App-Backend statt nur eines Linkstacks. Kein Breaking
Change — bestehende Aufrufe funktionieren unverändert (neue Parameter `plz` /
`language` sind optional).

### Added

#### Live-Wetterwarnungen (`meteo_warnings`)

- **`meteo_warnings` liefert jetzt echte, aktive Warnungen** statt nur eines
  Linkstacks. Live-Quelle ist das öffentliche MeteoSwiss-App-Backend
  (`app-prod-ws.meteoswiss-app.ch/v1/plzDetail`) — öffentlich und ohne Auth.
  Aggregierte Wetterwarnungen (Sturm, Gewitter, Hitze, Waldbrand, Frost,
  Schnee, …) mit Typ- und Stufen-Label, betroffener Warnregion, Gültig-ab und
  offiziellem Handlungslink; zusätzlich eine `Vorausschau`-Sektion für noch
  nicht aktive Warnungen.
- **Drei Abfrage-Granularitäten:** `plz="8001"` (ortsgenau), `canton="TI"`
  (Kanton via Hauptort-PLZ) oder ohne Filter → landesweite Aggregation über je
  eine Kantonshauptort-PLZ pro Kanton (26 Abfragen, dedupliziert, nach Typ
  gruppiert). Einzelne fehlgeschlagene PLZ-Abfragen degradieren den Aufruf
  nicht (Teilergebnis + Hinweis).
- **Mehrsprachige Warntexte** via neuen Parameter `language` (`de`/`fr`/`it`/
  `en`, Default `de`) — wird als `Accept-Language` an die App-API durchgereicht.
- **Neuer Egress-Host** `app-prod-ws.meteoswiss-app.ch` in der Allow-List.
  `MCP_WARNINGS_API_URL` überschreibt die App-Quelle weiterhin (Vorbereitung
  auf die künftige offizielle OGD-Warnings-REST-API).
- `warnType`-Mapping (7=Hitze, 10=Waldbrand gegen die natural-hazards.ch-Slugs
  verifiziert) mit Slug-Fallback für unbekannte Codes; Warnstufen 1–5.

### Changed

- **`meteo_warnings`-Tool-Definition erweitert** (neue Parameter `plz`,
  `language`; aktualisierte Description) → `tool-hashes.json` neu generiert
  (Rug-Pull-Signal, SEC-022). Für Clients nicht breaking: bestehende Aufrufe
  ohne `plz`/`language` funktionieren unverändert.

### Tests

- 12 neue Tests für die App-API-Warnungen (respx-gemockt, kein Netzwerk):
  PLZ-Detailansicht, landesweite Aggregation, JSON-Schema, unbekannter Kanton,
  Fehler-Degradation, PLZ-/Sprach-Validierung sowie Unit-Tests für
  `_warn_type_label`, `_epoch_millis_to_iso`, `_dedupe_warnings` und die
  Egress-Allow-List.

## [0.3.0] - 2026-05-21

Phase-2-Release: TTL-Caching aller Upstream-Calls, erweiterbare Klimanormwerte (19 Stationen statt 5), strukturierter Warnings-API-Hook. Kein Breaking Change gegenüber 0.2.0 — alle neuen Features sind opt-in via ENV.

### Added

#### Performance

- **TTL-Cache** für alle Upstream-Calls (STAC, Open-Meteo, Geocoding, opendata.swiss, Warnings-API). Asyncio-safe via Per-Key-Locks (Thundering-Herd-Schutz). Per-Endpoint-TTLs via `MCP_CACHE_TTL_STAC` / `MCP_CACHE_TTL_OPEN_METEO` / `MCP_CACHE_TTL_GEOCODING` / `MCP_CACHE_TTL_OPENDATA` / `MCP_CACHE_TTL_WARNINGS` / `MCP_CACHE_TTL_STAC_CLIMATE` (defaults: 5 min für Live-Daten, 1 h für Stammdaten, 24 h für Klima-Runtime-Lookup). Deaktivierbar via `MCP_CACHE_ENABLED=0`.

#### Daten

- **Klimanormwerte 1991-2020 für 19 SMN-Stationen** in `data/climate-normals.json`, ingested aus der offiziellen MeteoSwiss-NBCN-Publikation: BAS, BER, CHU, DAV, GVE, INT, JUN, KLO, LUG, LUZ, PIL, PUY, REH, SAE, SIO, SMA, STG, TAE, WAE (REC nicht in NBCN). Aktiviert via `MCP_CLIMATE_NORMALS_PATH=data/climate-normals.json`.
- **`MCP_CLIMATE_NORMALS_PATH`** lädt zusätzliche Klimanormwerte aus einer JSON-Datei zur Laufzeit. Datei-Werte gewinnen bei Konflikten gegenüber den eingebetteten 5 Stationen. Validation pro Eintrag (12-elementige Monatslisten); fehlerhafte Einträge werden geloggt und übersprungen.
- **`MCP_CLIMATE_NORMALS_URL_TEMPLATE`** aktiviert einen Runtime-HTTP-Lookup für Klimanormwerte (für Stationen ohne eingebettete oder JSON-Werte). Token-Substitution: `{station}` / `{STATION}` / `{param}` (`tre200m0` / `rre150m0` / `sre000m0`). Pro Tool-Call max. 3 GETs, 24-h-Cache. Bei Fehlschlag silent fallback zum bisherigen Linkstack-Hinweis.
- **`scripts/ingest_climate_normals.py`**: parst MeteoSwiss-NBCN-TSV-Dumps (Tab-separated, cp1252-encoded, Pattern `climate-reports-normtables_<param>_<period>_<lang>.txt`). Verzeichnis-Modus scannt automatisch alle relevanten Files; Plausibilitäts-Validierung mit Cross-Station-Checks. `--merge` für inkrementelle Ergänzungen. Siehe [`data/README.md`](data/README.md).

#### Strukturierte Warnings

- **`MCP_WARNINGS_API_URL`** aktiviert eine strukturierte MeteoSwiss-Warnings-API in `meteo_warnings`. Schema-tolerant gegen GeoJSON-Features, `warnings`-Array oder `items`. Canton-Filter wirkt auf das normalisierte Schema. Linkstack bleibt als Begleit-Info. Ohne ENV: bisheriges Verhalten (Linkstack only). Vorbereitet für die geplante MeteoSwiss-OGD-Phase-2-API.

### Changed

- `_geocode`, `_fetch_open_meteo_forecast`, `_fetch_stac_now_csv` und der opendata.swiss-Call in `meteo_warnings` gehen jetzt durch den TTL-Cache. Cache-Schlüssel: gerundete Koordinaten / Stationscode / lowercase-Locationsname.
- `meteo_climate_normals` akzeptiert jetzt einen optionalen `ctx: Context | None`-Parameter (wie die anderen HTTP-Tools), damit `ctx.info()`-Events während des Runtime-Fetches sichtbar sind.

### Quellen

- MeteoSwiss-NBCN-Klimanormwerte 1991-2020 (Lizenz CC BY 4.0 — Quelle: MeteoSchweiz)

## [0.2.0] - 2026-05-20

Komplette Umsetzung des [mcp-audit-skill](https://github.com/malkreide/mcp-audit-skill)-Reviews:
**0 critical / 0 high / 0 medium** Findings übrig (nur SEC-015 bewusst out-of-scope als Gateway-Pattern). Production-ready für stdio, single-instance HTTP und Multi-Replica HTTP.

### Breaking Changes

- **JSON-Output-Format**: Alle Tools mit `response_format="json"` liefern jetzt einen Envelope `{ "payload": ..., "provenance": { source, license, attribution, retrieved_at, data_source_url } }` statt eines flachen Dicts. Markdown-Outputs unverändert.
- **Entry-Point**: `pyproject.toml` `[project.scripts]` zeigt jetzt auf `meteoswiss_mcp.server:main` statt `mcp.run` — der neue Wrapper liest `MCP_TRANSPORT` / `MCP_HOST` / `MCP_PORT` / `MCP_ALLOW_ANY_HOST` aus ENV.

### Added

- **OpenTelemetry-Tracing** (opt-in via `OTEL_EXPORTER_OTLP_ENDPOINT` + `pip install meteoswiss-mcp[otel]`): pro Tool-Call ein Span mit `mcp.tool.name` + `mcp.tool.result.is_error`, automatische httpx-Instrumentierung. Ohne ENV: No-Op-Stub.
- **Stateless-HTTP-Mode** via `MCP_STATELESS_HTTP=1` — erlaubt Multi-Replica-Deploys ohne Sticky-Session-Routing.
- **CORS-Middleware** via `MCP_ALLOWED_ORIGINS` (komma-separiert). `Mcp-Session-Id` wird automatisch in `Access-Control-Expose-Headers` exponiert — browser-clients wie claude.ai Web können Sessions aufbauen.
- **Optionaler API-Key-Auth-Layer** via `MCP_API_KEY`. Akzeptiert `X-API-Key`- oder `Authorization: Bearer`-Header, constant-time-Vergleich. `/health` bleibt für Container-Probes offen.
- **OGD-Provenance-Envelope** für JSON-Outputs (`source` / `license=CC BY 4.0` / `attribution=MeteoSchweiz` / `retrieved_at` / `data_source_url`).
- **Multi-Stage-`Dockerfile`** (non-root user `mcp:10001`, `HEALTHCHECK`) + `render.yaml`-Blueprint (plan starter, healthCheckPath, explizit `numInstances: 1`).
- **Health-Endpoint** `GET /health` via FastMCP `custom_route` — trivialer 200-OK ohne Upstream-Pings.
- **Structured Logging** via `structlog`: JSON-Events auf stderr. Events: `tool_invoked`, `upstream_failed`, `egress_blocked`, `auth_rejected`, `cors_configured`, `otel_initialized`. Level via `MCP_LOG_LEVEL`.
- **Fuzzy-Geocoding-Fallback**: bei leerer DE-Suche zweiter Versuch ohne language-Restriktion. `_geocode` gibt `match_type` ("exact" / "fuzzy") zurück.
- **Tool-Beschreibungen mit `<use_case>` / `<important_notes>` / `<example>`-XML-Tags** (Anthropic-Prompt-Engineering-Konvention).
- **Tool-Hash-Pinning**: `scripts/tool_hashes.py` + `tool-hashes.json`. CI-Guard blockt PRs, die Tool-Definitionen ohne Hash-Update ändern.
- **README**: Annotations-Übersicht, MCP-Protocol-Version-Sektion, ENV-Tabelle.
- **`docs/roadmap.md`** mit Phasen-Statustabelle und Audit-Verfolgung.
- **Dependabot** für pip / github-actions / docker.

### Security

- **SSRF-Prevention** (SEC-004 / SEC-021): Egress-Allow-List `data.geo.admin.ch`, `api.open-meteo.com`, `geocoding-api.open-meteo.com`, `opendata.swiss`. Validiert alle Requests inkl. Redirect-Follow-Targets via httpx `event_hooks`. IP-Literale (insbesondere `169.254.169.254` und RFC1918) werden mit `EgressBlocked` abgelehnt.
- **0.0.0.0-Binding-Hardening** (SEC-016): `MCP_HOST` defaultet auf `127.0.0.1`; Binding an `0.0.0.0` benötigt explizites `MCP_ALLOW_ANY_HOST=1` (Container/Cloud-Opt-In).
- **Container-Sandboxing** (SEC-007): non-root user `mcp:10001` im Multi-Stage-Image.
- **CI-Guard** gegen `print()`-Regressionen in `src/` (OBS-004 — stdout-Reinheit für stdio-Transport).

### Changed

- Entry-Point: `meteoswiss_mcp.server:main` statt `mcp.run`.
- `FastMCP(..., lifespan=app_lifespan)`: ein wiederverwendeter `httpx.AsyncClient` ersetzt 5 Stellen mit Per-Call-Clients (Connection-Pooling).
- Tool-Funktionen akzeptieren jetzt optionalen `ctx: Context | None`-Parameter; FastMCP injiziert ihn zur Laufzeit, Tests können ohne `ctx` aufrufen.
- HTTP-Errors werden via `_sanitize_error()` von URL-Leaks bereinigt, bevor sie in User-Output gelangen.
- `httpx.AsyncClient` mit `event_hooks={"request": [_validate_request_hook]}` instrumentiert.

### Fixed

- `tool-hashes.json`-Guard läuft jetzt nur auf Python 3.13 (Produktions-Version), um Pydantic-Schema-Drift zwischen Versionen zu kompensieren.

## [0.1.0] - 2026-03-31

### Added
- Initial release
- **meteo_stations**: SwissMetNet-Stationen auflisten (kanton-filterbar)
- **meteo_current**: Aktuelle 10-min-Beobachtungen via BGDI STAC API
- **meteo_forecast**: 1–16 Tage Prognose via Open-Meteo (MeteoSwiss ICON-CH1/CH2-EPS)
- **meteo_school_check**: 🟢/🟡/🔴 Ampel für Schulveranstaltungen im Freien
- **meteo_climate_normals**: Monatliche Klimanormwerte 1991–2020
- **meteo_warnings**: Aktuelle MeteoSwiss-Wetterwarnungen & CAP-Links
- 3 Resources: `meteo://stationen/smn`, `meteo://schulplanung/schwellenwerte`, `meteo://wmo/codes`
- Dual transport: stdio (Claude Desktop) + Streamable HTTP (Cloud/Render.com)
- GitHub Actions CI (Python 3.11, 3.12, 3.13)
- Bilingual documentation (DE/EN)
