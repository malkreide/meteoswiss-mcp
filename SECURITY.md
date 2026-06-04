# Security Policy

🇩🇪 [Deutsche Version](SECURITY.de.md)

This server is part of the [Swiss Public Data MCP Portfolio](https://github.com/malkreide/swiss-public-data-mcp).

## Supported versions

Security fixes are applied to the latest released version on [PyPI](https://pypi.org/project/meteoswiss-mcp/) and the `main` branch. Please always run the most recent version before reporting an issue.

## Reporting a vulnerability

Please **do not** report security vulnerabilities through public GitHub issues.

Instead, report them privately via [GitHub Security Advisories](https://github.com/malkreide/meteoswiss-mcp/security/advisories/new). If that is not possible, open a minimal issue asking for a private contact channel — without disclosing any details.

Please include where possible:
- A description of the vulnerability and its potential impact
- Steps to reproduce (proof-of-concept if available)
- Affected version, transport (`stdio` / `streamable-http`) and configuration
- Any suggested mitigation

You can expect an initial acknowledgement within **5 working days**. We aim to provide a remediation timeline after triage and will keep you informed about progress. Responsible disclosure is appreciated — please give us reasonable time to release a fix before any public disclosure.

## Security model

This is a **read-only** MCP server over public open-government data. It holds no user credentials and writes no data. Key safeguards (see audit findings referenced in the [README](README.md) and the `audits/` directory):

- **Read-only tools** — all tools carry `readOnlyHint: true`; the server cannot modify or delete data.
- **Egress allow-list** — outgoing HTTP calls (including redirect follows) are restricted to `data.geo.admin.ch`, `api.open-meteo.com`, `geocoding-api.open-meteo.com` and `opendata.swiss`. IP literals and cloud metadata endpoints (e.g. `169.254.169.254`, RFC1918) are rejected with `EgressBlocked` (SEC-004 / SEC-021).
- **Safe bind defaults** — `MCP_HOST` defaults to `127.0.0.1`; binding to `0.0.0.0` requires the explicit `MCP_ALLOW_ANY_HOST=1` (SEC-016).
- **Optional API-key auth** — set `MCP_API_KEY` to require `X-API-Key` / `Authorization: Bearer` on all routes except `/health`, with constant-time comparison (SEC-009 / SEC-013).
- **CORS off by default** — same-origin only unless `MCP_ALLOWED_ORIGINS` is set (SDK-004).

For deployment hardening in HTTP mode, see the **HTTP-mode security** section of the [README](README.md).

## Scope

In scope: the server code in this repository (`src/`), its tool definitions and the HTTP transport layer.

Out of scope: vulnerabilities in upstream data providers (MeteoSwiss, Open-Meteo, opendata.swiss) and in third-party dependencies — please report those to the respective maintainers. Dependency advisories are tracked via Dependabot.
