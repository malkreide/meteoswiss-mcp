# MCP Audit Report — `meteoswiss-mcp`

| Feld | Wert |
|---|---|
| Server | `meteoswiss-mcp` |
| Repo | https://github.com/malkreide/meteoswiss-mcp |
| Audit-Datum | 2026-05-20 |
| Audit-Skill | https://github.com/malkreide/mcp-audit-skill |
| Skill-Branch | claude/audit-mcp-skill-TEtJY |
| Anwendbare Checks | 44 / 68 |

---

## Executive Summary

`meteoswiss-mcp` ist ein Python-FastMCP-Server mit 6 read-only-Tools auf öffentliche MeteoSwiss-Open-Government-Daten. **Production-Ready: nein.** Von 44 anwendbaren Checks bestehen nur **9 vollständig**, 16 sind `partial`, 19 schlagen fehl. Es gibt **3 offene `critical`- und 8 offene `high`-Findings**, die einen produktiven Cloud-Betrieb über den `--http`-Modus blockieren — insbesondere fehlende SSRF-Defense, fehlendes Host-Binding-Hardening (0.0.0.0-NeighborJack), keine Session-Bindung und keinerlei strukturiertes Logging. Im **stdio-only**-Modus (Claude Desktop, lokal) ist das Risiko deutlich kleiner; die Read-only-Architektur, sauberen Pydantic-Inputs und das OIDC-PyPI-Publishing sind Stärken.

---

## Profile-Snapshot

```yaml
name: meteoswiss-mcp
repo: https://github.com/malkreide/meteoswiss-mcp
transport: dual                  # stdio default, streamable-http via --http
auth_model: none
data_class: Public Open Data
write_capable: false
deployment: [local-stdio, Render]
is_cloud_deployed: true
sdk_language: Python             # FastMCP (mcp[cli]>=1.0.0)
tools_make_external_requests: true
data_source.is_swiss_open_data: true
```

Datenquellen: BGDI STAC (data.geo.admin.ch), Open-Meteo MeteoSwiss-ICON, Open-Meteo Geocoding, opendata.swiss CKAN — alle keyless, CC BY 4.0.

---

## Applicability-Übersicht

| Kategorie | Anwendbar | pass | partial | fail |
|---|---|---|---|---|
| ARCH  | 11 | 6 | 4 | 1 |
| SDK   | 4  | 0 | 1 | 3 |
| SEC   | 15 | 3 | 3 | 9 |
| SCALE | 5  | 0 | 1 | 4 |
| OBS   | 5  | 0 | 2 | 3 |
| OPS   | 3  | 1 | 2 | 0 |
| CH    | 1  | 0 | 1 | 0 |
| HITL  | 0  | — | — | — | (read-only)
| **Σ** | **44** | **9** | **16** | **19** |

### Severity × Status

| Severity | pass | partial | fail | Σ |
|---|---|---|---|---|
| critical | 2 | 2 | 3 | 7 |
| high     | 3 | 8 | 8 | 19 |
| medium   | 4 | 6 | 8 | 18 |
| **Σ** | **9** | **16** | **19** | **44** |

---

## Findings-Tabelle (sortiert nach Severity)

### Critical

| ID | Status | Titel | Effort |
|---|---|---|---|
| SEC-004 | fail | SSRF-Prevention fehlt (Geocoding-Input + STAC-Asset-href ungeprüft) | M |
| SEC-009 | fail | Keine Session-ID-Bindung im HTTP-Modus | M |
| SEC-016 | fail | 0.0.0.0-Binding ohne MCP_HOST-Default 127.0.0.1 (NeighborJack) | S |
| SEC-019 | partial | Lethal-Trifecta-Bewertung nicht dokumentiert (faktisch read-only) | S |
| OBS-004 | partial | Keine defensive stderr-Konfiguration (aktuell kein Logger aktiv) | S |
| ARCH-005 | pass | Keine Hardcoded Secrets — ✅ |
| SEC-020 | pass | Command Injection vermieden — ✅ |

### High

| ID | Status | Titel | Effort |
|---|---|---|---|
| SEC-005 | fail | Keine DNS-Rebinding-Prevention (kein PinnedTransport) | M |
| SEC-007 | fail | Kein Container-Sandboxing (kein Dockerfile / USER non-root) | M |
| SEC-021 | fail | Keine Egress-Allow-List + STAC-href ungeprüft | M |
| SDK-001 | fail | Kein Lifespan + httpx.AsyncClient pro Call (kein Connection-Pool) | M |
| SDK-004 | fail | CORS Mcp-Session-Id Header nicht exposed (HTTP-Modus browser-untauglich) | S |
| OBS-001 | fail | Keine Trennung Protocol- vs. Execution-Error (kein isError-Flag) | M |
| SCALE-002 | fail | Kein Sticky-Session/Shared-State für Multi-Replica | L |
| SCALE-003 | fail | Kein Mcp-Session-Id-Routing auf Edge-LB | L |
| SEC-006 | partial | Transport-Switch via CLI-Flag statt MCP_TRANSPORT-Env | S |
| SEC-013 | partial | Keine docs/secret-management.md (auch wenn keine Secrets nötig) | S |
| SEC-022 | partial | Kein Tool-Hash-Pinning / kurzer Namespace-Präfix | M |
| OBS-002 | partial | mask_error_details fehlt; rohe httpx-Exception-Strings im Output | S |
| SCALE-001 | partial | Kein explizites host=-Binding, kein MCP_TRANSPORT-Env | S |
| ARCH-009 | partial | Annotations vollständig, aber Doku-Tabelle im README fehlt | S |
| OPS-001 | partial | respx deklariert aber ungenutzt; kein nightly Live-Workflow | M |
| OPS-003 | partial | Phase-1-Disziplin im Code, aber keine formelle Phasen-Deklaration | S |
| ARCH-004 | pass | Transport-agnostische Tool-Logik — ✅ |
| ARCH-006 | pass | High-Level-Tool-Cluster (6 Tools, ≤8) — ✅ |
| SEC-018 | pass | Pydantic-Input-Validation mit extra="forbid" + Bounds — ✅ |

### Medium (Auswahl der `fail`-Items)

| ID | Status | Titel | Effort |
|---|---|---|---|
| ARCH-012 | fail | Kein protocolVersion-Pinning, kein Dependabot/Renovate | S |
| OBS-003 | fail | Komplett kein Logging (kein structlog/logger initialisiert) | M |
| OBS-006 | fail | Kein OpenTelemetry-Tracing | M |
| SDK-003 | fail | Keine Context-Injection / Progress-Reports | S |
| SCALE-004 | fail | Kein Dockerfile / Multi-Stage-Build | M |
| SCALE-006 | fail | Keine Resource-Limits im Repo dokumentiert | S |
| SEC-014 | fail | Kein Tool-Allow-Listing / Gateway-Pattern | M |
| SEC-015 | fail | Keine Pre-Flight-Tool-Poisoning-Detection | M |

### Top-Stärken (passes)

`ARCH-001` (Tool-Naming), `ARCH-004` (Transport-agnostisch), `ARCH-005` (keine Secrets), `ARCH-006` (Tool-Budget), `ARCH-008` (Tools + Resources), `SDK-002` (Pydantic-Inputs vorbildlich — Returns als `str` ist `partial`), `OPS-002` (Doku-Standard), `SEC-008` (PyPI-OIDC-Publish), `SEC-018` (Input-Validation), `SEC-020` (Command-Injection-Prevention).

---

## Detail-Findings (Top-10 Blocker)

Vollständige Per-Check-Evidenz: `audits/run/raw/*.txt`. Hier die kritischsten Items mit Code-Referenz und Remediation-Vorschlag.

### F-1 — SEC-016 (critical) · 0.0.0.0-Binding ohne Hardening

**Observed:** `src/meteoswiss_mcp/server.py:1245-1250` ruft `mcp.run(transport="streamable-http", port=port)` ohne `host=`-Argument. FastMCP-Default für streamable-http ist `0.0.0.0` — d.h. wer den Server lokal mit `--http` startet, exponiert ihn ins gesamte lokale Subnetz («NeighborJack»).

**Expected:** ENV-Variable `MCP_HOST` mit Default `127.0.0.1`; nur in Container/Render bewusst `0.0.0.0`.

**Remediation (S, ~1 h):**
```python
import os
host = os.environ.get("MCP_HOST", "127.0.0.1")
mcp.run(transport="streamable-http", host=host, port=port)
```
README ergänzen: «Lokal nie `MCP_HOST=0.0.0.0` setzen.»

---

### F-2 — SEC-004 (critical) · SSRF-Prevention fehlt

**Observed:** Zwei Tainted-Pfade:
1. `src/meteoswiss_mcp/server.py:363-381` `_geocode()` reicht User-`location` direkt an `httpx.get(GEOCODING_BASE, params={"name": location, ...})`.
2. `src/meteoswiss_mcp/server.py:422-462` `_fetch_stac_now_csv()` folgt `asset["href"]` **aus der STAC-API-Antwort** mit `follow_redirects=True` ohne Scheme/Host/IP-Check.

**Expected:** Frozenset `ALLOWED_HOSTS`; Pre-Request-`assert_host_allowed(url)`; HTTPS-Schema-Enforcement; IP-Blocklist (169.254.169.254, RFC1918, loopback, link-local); `follow_redirects=False` oder Custom-Hook.

**Remediation (M, ~3 h):**
```python
from urllib.parse import urlparse
import ipaddress, socket

ALLOWED_HOSTS = frozenset({
    "data.geo.admin.ch", "api.open-meteo.com",
    "geocoding-api.open-meteo.com", "opendata.swiss",
})

def assert_safe_url(url: str) -> None:
    p = urlparse(url)
    if p.scheme != "https": raise ValueError("https required")
    if p.hostname not in ALLOWED_HOSTS: raise ValueError(f"host not allowed: {p.hostname}")
    for fam, *_, sa in socket.getaddrinfo(p.hostname, None):
        ip = ipaddress.ip_address(sa[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            raise ValueError(f"private IP: {ip}")
```
Vor jedem `httpx.get(...)` aufrufen; `follow_redirects=False` setzen.

---

### F-3 — SEC-009 (critical) · Keine Session-ID-Bindung im HTTP-Modus

**Observed:** `streamable-http`-Modus aktiv, `auth_model: none`, keine `secrets.token_urlsafe`/`Mcp-Session-Id`-Handler im Code. Server vertraut komplett auf FastMCP-Defaults ohne dokumentierte Verifikation.

**Expected:** Entweder explizit dokumentieren, dass FastMCP cryptographic Session-IDs vergibt (Link auf Upstream-Code), **oder** HTTP-Modus auf Read-Only + striktes Rate-Limit + Origin-Whitelist beschränken.

**Remediation (M):** SecurityModel-Sektion im README, die HTTP-Modus-Threat-Model dokumentiert. Mittelfristig: Auth-Layer (OAuth-Proxy oder API-Key) wenn HTTP-Modus produktiv genutzt wird.

---

### F-4 — SEC-021 (high) · Egress-Allow-List fehlt

Wird gemeinsam mit F-2 (SEC-004) gelöst: derselbe `assert_safe_url`-Helper liefert die Allow-List-Funktionalität.

---

### F-5 — SDK-001 (high) · Kein Lifespan + httpx-Client pro Call

**Observed:** `_geocode`, `_fetch_open_meteo_forecast`, `_fetch_stac_now_csv` (zweimal!), `meteo_warnings` öffnen je einen `httpx.AsyncClient`. Connection-Pooling/Keep-Alive entfällt; latenz-Overhead pro Call.

**Remediation (M, ~2 h):**
```python
from contextlib import asynccontextmanager
from dataclasses import dataclass

@dataclass
class AppContext:
    http: httpx.AsyncClient

@asynccontextmanager
async def lifespan(server):
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as http:
        yield AppContext(http=http)

mcp = FastMCP("meteoswiss_mcp", lifespan=lifespan, instructions=...)
```
Tools via `ctx: Context` → `ctx.request_context.lifespan_context.http` benutzen (löst zugleich SDK-003).

---

### F-6 — SDK-004 (high) · CORS-Header fehlt

**Observed:** `mcp.run(transport="streamable-http", ...)` ohne CORS-Konfig. Browser-Clients (claude.ai Web) können keine Session aufbauen, weil `Mcp-Session-Id`-Header nicht in `Access-Control-Expose-Headers` ist.

**Remediation (S, ~30 min):** FastMCP-CORS-Settings (`mcp.settings.cors_*` oder Starlette-Middleware vor `streamable_http_app()`) mit `expose_headers=["Mcp-Session-Id"]` und ENV-gesteuerte `allow_origins`.

---

### F-7 — OBS-003 (medium, fail) + OBS-001 (high, fail) + OBS-002 (high, partial) · Logging & Error-Handling

**Observed:** `grep "logging|logger" src/` ergibt 0 Treffer. Errors werden als Markdown-String mit ⚠️ in den Tool-Output geschrieben (z.B. `f"⚠️ Live-Daten nicht abrufbar: {exc}"` in Z. 656, 747, 758, 898, 903) — kein `isError`-Flag, rohe `httpx.HTTPStatusError`-Strings können URL-Strukturen leaken.

**Remediation (M, ~2 h):**
1. `structlog` als Dependency, `logger = structlog.get_logger(__name__)` mit `WriteLoggerFactory(file=sys.stderr)`.
2. `FastMCP(..., mask_error_details=True)` setzen.
3. Errors via `raise McpError(...)` oder `Content(isError=True, ...)` zurückgeben statt String-Konkatenation.
4. CI-Guard: `ruff` Regel oder Pytest gegen `print(` in `src/`.

---

### F-8 — SEC-007 + SCALE-004 + SCALE-006 (high/medium) · Kein Dockerfile, keine Resource-Limits

**Observed:** Repo enthält weder `Dockerfile` noch `render.yaml`. Image-Reproduzierbarkeit und Sandboxing sind nicht versioniert.

**Remediation (M, ~3 h):** Multi-Stage-Dockerfile (`python:3.13-slim` Builder + Distroless Runtime), `USER 10001`, `HEALTHCHECK`, `render.yaml` mit explizitem `MCP_HOST=0.0.0.0` + Memory-/CPU-Limits.

---

### F-9 — ARCH-012 (medium, fail) · protocolVersion-Pinning

**Observed:** Kein `FastMCP(..., protocol_version=...)`, kein `.github/dependabot.yml`, kein `renovate.json`, README hat keine «MCP Protocol Version»-Sektion.

**Remediation (S, ~1 h):** Dependabot-Config für `pip` + `github-actions` Weekly; README-Sektion mit getesteten Spec-Versionen + Update-Policy.

---

### F-10 — OPS-001 (high, partial) · Test-Strategie

**Observed:** `respx>=0.21.0` ist als Dev-Dependency deklariert, wird aber **nicht** verwendet. Alle HTTP-abhängigen Tools haben keine mocked Unit-Tests — nur die Live-Variante (CI ausgeschlossen via `-m "not live"`).

**Remediation (M, ~3 h):** Pro Tool 1 respx-Mock-Test für Happy-Path + 1 für 4xx/5xx. Optional: nightly `live-test.yml`-Workflow.

---

## Remediation-Plan (vorgeschlagene Reihenfolge)

Fokus: blockierende Items vor Cloud-Produktiv-Release lösen.

| # | Block | Items | Effort | Begründung |
|---|---|---|---|---|
| 1 | **Härtung HTTP-Transport** | SEC-016, SEC-006, SEC-004, SEC-005, SEC-021 | M | Macht den `--http`-Modus überhaupt verantwortbar; Allow-List+Host-Binding sind die Single-Source-of-Truth-Pflöcke. |
| 2 | **Observability-Baseline** | OBS-003, OBS-002, OBS-001, OBS-004 | M | Production-Debug ohne Logs unmöglich. |
| 3 | **Lifecycle + CORS** | SDK-001, SDK-004, SDK-003 | M | Connection-Pool + Browser-Support; löst Performance + claude.ai-Web. |
| 4 | **Container + Limits** | SCALE-004, SCALE-006, SEC-007 | M | Image-Reproduzierbarkeit, Sandboxing. |
| 5 | **Auth/Session** | SEC-009, SEC-013, SEC-019 | M | Mindestens dokumentieren, was FastMCP-Default leistet; ggf. API-Key-Layer hinzufügen. |
| 6 | **Test/Doku** | OPS-001, OPS-003, ARCH-009, ARCH-012, SEC-022, CH-004 | S+M | Wartungsfähigkeit + Schweizer-Lizenz-Provenance. |
| 7 | **Mehrere Replicas** (falls Render-Skalierung geplant) | SCALE-002, SCALE-003 | L | Nur relevant wenn >1 Instance betrieben wird. |
| 8 | **Polish** | ARCH-002, ARCH-003, ARCH-007, ARCH-011, SDK-002, OBS-006, SEC-014, SEC-015 | S+M | Nach Production-Freigabe. |

**Geschätzter Gesamtaufwand bis "production_ready" für HTTP-Modus:** ~3-5 Personentage (Blöcke 1-3). Für stdio-only-Modus reichen die Blöcke 2 + 6 (~1-2 Tage).

---

## Audit-Metadata

| Feld | Wert |
|---|---|
| Audit-Methode | mcp-audit-skill v1.0 (8 Kategorien, 68 Checks, applies_when-DSL) |
| Catalog-Quelle | https://github.com/malkreide/mcp-audit-skill/tree/main/checks |
| Applicability-Filter | dual transport, no auth, Public Open Data, read-only, Python SDK, Render |
| Anwendbare Checks | 44 / 68 (60 % Coverage) |
| Auditor | Claude Code (claude-opus-4-7[1m]) |
| Profile | `audits/run/profile.yaml` |
| Raw-Outputs | `audits/run/raw/*.txt` |
| Severity-Mapping | `audits/run/summary.txt` |

**production_ready:** `false` (3 critical-fail + 8 high-fail offen)
