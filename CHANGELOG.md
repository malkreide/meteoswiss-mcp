# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (Phase 2 — Caching + Data Extension)

- **TTL-Cache** für alle Upstream-Calls (STAC / Open-Meteo / Geocoding / opendata.swiss / Warnings-API). asyncio-safe via Per-Key-Locks (verhindert Thundering-Herd). Per-Endpoint-TTLs via ENV (`MCP_CACHE_TTL_*`), default 5 min für Live-Daten, 1 h für Stammdaten. Deaktivierbar via `MCP_CACHE_ENABLED=0`.
- **`MCP_CLIMATE_NORMALS_PATH`** lädt zusätzliche Klimanormwerte aus einer JSON-Datei zur Laufzeit. Die eingebetteten 5 Stationen werden mit dem File gemerged; Datei-Werte gewinnen bei Konflikten. Validiert pro Eintrag: 12-elementige Monatslisten, sonst geloggt + geskippt. Beispiel: `data/climate-normals.example.json`.
- **`MCP_WARNINGS_API_URL`** aktiviert die strukturierte MeteoSwiss-Warnings-API in `meteo_warnings`. Tool fetcht die URL, normalisiert das Schema (GeoJSON / `warnings`-Array / `items`), filtert nach Kanton und rendert eine Tabelle mit Stufe / Typ / Region / Gültigkeit. Linkstack bleibt als Begleit-Info. Ohne ENV: bisheriges Verhalten (Linkstack only).

### Changed

- `_geocode`, `_fetch_open_meteo_forecast`, `_fetch_stac_now_csv` und der opendata.swiss-Call in `meteo_warnings` gehen jetzt über `_cached(...)`. Cache-Schlüssel: gerundete Koordinaten / Stationscode / lowercase-Locationsname.

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
