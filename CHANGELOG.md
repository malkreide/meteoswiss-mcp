# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **OBS-006** Optionale OpenTelemetry-Tracing: pro Tool-Call ein Span (`tool.<name>` mit `mcp.tool.name` / `mcp.tool.result.is_error`), automatische httpx-Instrumentierung. Aktiv via `OTEL_EXPORTER_OTLP_ENDPOINT` + `pip install meteoswiss-mcp[otel]`. Ohne ENV: No-Op-Stub, kein Performance-Overhead.
- **SCALE-002 / SCALE-003** Optionaler FastMCP-Stateless-Mode via `MCP_STATELESS_HTTP=1` — erlaubt Multi-Replica-Deploys ohne Sticky-Session-Routing.
- **ARCH-003** Fuzzy-Fallback im Geokoding: bei leerer DE-Suche zweiter Versuch ohne language-Restriktion + count=5. `_geocode` gibt `match_type` ("exact" / "fuzzy") als viertes Tuple-Element zurück.
- **ARCH-002** Tool-Beschreibungen strukturiert mit `<use_case>` / `<important_notes>` / `<example>` XML-Tags — bessere LLM-Lesbarkeit (folgt Anthropic-Prompt-Engineering-Konvention). Static-Test im CI guard's the Konvention.

### Changed

- Stateless-Mode + neue Docstrings führen zu geänderten Tool-Hashes — `tool-hashes.json` aktualisiert.

### Added (PR-6)

- **CH-004 / SDK-002** OGD-Provenance-Envelope für alle JSON-Tool-Outputs: `payload` + `provenance` (`source`, `license=CC BY 4.0`, `attribution=MeteoSchweiz`, `retrieved_at`, `data_source_url`). Markdown-Outputs unverändert.
- **ARCH-012** Dependabot-Konfiguration für `pip`, `github-actions` und `docker`. README enthält jetzt eine «MCP Protocol Version»-Sektion mit Update-Policy.
- **ARCH-009** README-Annotations-Tabelle mit `readOnlyHint` / `destructiveHint` / `idempotentHint` / `openWorldHint` pro Tool.
- **OPS-003** `docs/roadmap.md` mit expliziter Phasen-Statustabelle (Phase 1 aktiv, Phase 2 geplant, Phase 3 explizit out-of-scope) und Audit-Verfolgung.
- **SEC-022** `scripts/tool_hashes.py` + `tool-hashes.json` Snapshot. CI-Guard `git diff --exit-code tool-hashes.json` blockt PRs, die Tool-Definitionen ändern ohne den Hash zu aktualisieren.
- **SDK-004** CORS-Middleware via `MCP_ALLOWED_ORIGINS`-ENV (komma-separiert). `Mcp-Session-Id` wird automatisch in `Access-Control-Expose-Headers` exponiert — browser-clients wie claude.ai Web können jetzt Sessions aufbauen.
- **SEC-009 / SEC-013** Optionaler API-Key-Auth-Layer via `MCP_API_KEY`. Akzeptiert `X-API-Key`- oder `Authorization: Bearer`-Header, constant-time-Vergleich via `secrets.compare_digest`. `/health` ist bewusst aus der Auth-Pflicht ausgenommen, damit Container-Probes nicht 401 zurückbekommen. `auth_rejected`-Events werden geloggt.
- **SEC-007 / SCALE-004 / SCALE-006** Multi-Stage-`Dockerfile` (non-root user `mcp:10001`, `HEALTHCHECK`) + `render.yaml`-Blueprint (plan starter, healthCheckPath, explizit `numInstances: 1`). `.dockerignore` schliesst Audits/Assets/Tests aus.
- **SCALE-004** Health-Endpoint `GET /health` via FastMCP `custom_route` — trivialer 200-OK ohne Upstream-Pings. Test deckt Statuscode + Body ab.
- **OBS-003** Structured Logging via `structlog`: JSON-Events auf `stderr` (stdio-safe). Events: `tool_invoked`, `upstream_failed`, `egress_blocked`. Log-Level via `MCP_LOG_LEVEL`-ENV (default `INFO`).
- **OBS-004** CI-Guard `ruff` + `grep -rnE '^\s*print\s*\(' src/` blockt regressionen mit `print()`-Calls in src/.
- 3 neue respx/monkeypatch-basierte Tests verifizieren die Log-Events.

### Security

- **SEC-004 / SEC-021** Egress-Allow-List: alle ausgehenden HTTP-Requests werden gegen eine frozenset-Allow-List validiert; Redirect-Follow-Targets ebenfalls. IP-Literale (insbesondere 169.254.169.254 + RFC1918) werden mit `EgressBlocked` abgelehnt.
- **SEC-016** `MCP_HOST` defaultet jetzt auf `127.0.0.1`; Binding an `0.0.0.0` benötigt explizites `MCP_ALLOW_ANY_HOST=1` (vermeidet NeighborJack bei lokalen `--http`-Sessions).
- **SEC-006** Transport-Selektion via `MCP_TRANSPORT`-ENV-Variable (CLI-Flags `--http`/`--port` bleiben als Override erhalten).

### Changed

- Entry-Point ist jetzt `meteoswiss_mcp.server:main` (statt `mcp.run`), um Transport-Settings aus ENV/CLI zu lesen.
- `httpx.AsyncClient` ist nun mit `event_hooks={"request": [...]}` für die Allow-List instrumentiert.

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
