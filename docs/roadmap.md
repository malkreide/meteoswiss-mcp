# Roadmap — meteoswiss-mcp

Diese Roadmap dokumentiert die Phasen-Architektur (OPS-003 aus dem [MCP-Audit](https://github.com/malkreide/mcp-audit-skill)). Sie listet, welche Features in welcher Phase erlaubt sind, welche Voraussetzungen für den Phasen-Übergang gelten, und was bewusst nicht geplant ist.

## Phase-Statustabelle

| Phase | Status | Tools / Features | Datenklasse | Auth | Voraussetzungen |
|---|---|---|---|---|---|
| **1 — Public Read** | ✅ aktiv | `meteo_stations`, `meteo_current`, `meteo_forecast`, `meteo_school_check`, `meteo_climate_normals`, `meteo_warnings` | Public Open Data (CC BY 4.0) | `none` (stdio) bzw. optional API-Key (HTTP) | erfüllt |
| **2 — Cached + Mocked** | 🟡 geplant | TTL-Caching (httpx-cache oder lokaler Disk-Cache); `respx`-Mock-Tests für jeden HTTP-Pfad; nightly Live-Test-Workflow | Public Open Data | unverändert | OBS-006 OTLP-Tracing optional |
| **3 — Write-capable** | ❌ nicht geplant | Write-Operationen sind ausserhalb des Server-Mandats. Falls je nötig: separater Server mit OAuth-Proxy + HITL. | n/a | n/a | n/a |

## Aktueller Sicherheitsstand (Audit-Verfolgung)

Stand: nach PR-1..PR-5. Vollständige Findings: `audits/run/AUDIT_REPORT.md`.

| Block | Status |
|---|---|
| Critical-Findings | ✅ 0 offen |
| SSRF + Egress-Allow-List (SEC-004/SEC-021) | ✅ pass |
| 0.0.0.0-Binding-Hardening (SEC-016) | ✅ pass |
| HTTP-CORS + API-Key (SDK-004/SEC-009/SEC-013) | ✅ pass |
| Structured Logging (OBS-001/OBS-003/OBS-004) | ✅ pass |
| Container + Resource-Limits (SEC-007/SCALE-004/SCALE-006) | ✅ pass |
| Multi-Replica via Stateless-HTTP (SCALE-002/SCALE-003) | ✅ pass — opt-in via `MCP_STATELESS_HTTP=1` |
| OpenTelemetry-Tracing (OBS-006) | ✅ pass — opt-in via `OTEL_EXPORTER_OTLP_ENDPOINT` + `[otel]`-extras |
| Tool-Hash-Pinning (SEC-022) | ✅ pass — `scripts/tool_hashes.py` + CI-Guard |
| Pre-Flight-Tool-Poisoning-Detection (SEC-015) | 🟡 offen — Gateway-Pattern, nicht Server |

## Phasen-Übergangs-Kriterien

### Phase 1 → Phase 2 (geplant)

- [ ] Caching-Layer integriert, mit TTL pro Endpoint (Open-Meteo 10 min, STAC 5 min, opendata.swiss 1 h)
- [ ] Jeder HTTP-Tool-Test existiert in zwei Varianten: `respx`-Mock (CI-default) + `live` (nightly)
- [ ] OpenTelemetry-Spans für jeden Tool-Call (optional, aktiv via `OTEL_EXPORTER_OTLP_ENDPOINT`)
- [ ] CHANGELOG dokumentiert getestete MCP-Spec-Version

### Phase 2 → Phase 3 (nicht geplant)

Write-Operationen sind explizit **out-of-scope**. Begründung: Wetter-Daten kommen von MeteoSchweiz / Open-Meteo — der MCP-Server ist read-only Konsument, kein Producer. Falls Use-Cases wie «Benutzer reicht Wetterbeobachtung ein» auftauchen, wird das in einem separaten Server mit OAuth-Proxy + HITL gebaut, nicht hier.

## Update-Policy

- **MCP-SDK** (`mcp[cli]`): Updates via Dependabot, manuelles Review pro Minor-Bump. Bei Breaking-Change (Spec-Version): CHANGELOG-Eintrag + Reset Phase-2-Tests.
- **Best-Practice-Audit**: jährlich oder bei Major-Catalog-Update (siehe `mcp-audit-skill`-Repo).
- **Render-Image**: Dockerfile-`PYTHON_VERSION`-Arg + Dependabot-Docker-Ecosystem hält Base-Image aktuell.
