# Sicherheitsrichtlinie

🇬🇧 [English version](SECURITY.md)

Dieser Server ist Teil des [Swiss Public Data MCP Portfolios](https://github.com/malkreide/swiss-public-data-mcp).

## Unterstützte Versionen

Sicherheitsfixes werden auf die jeweils neueste auf [PyPI](https://pypi.org/project/meteoswiss-mcp/) veröffentlichte Version sowie den `main`-Branch angewendet. Bitte führe immer die aktuellste Version aus, bevor du ein Problem meldest.

## Eine Schwachstelle melden

Bitte melde Sicherheitslücken **nicht** über öffentliche GitHub Issues.

Melde sie stattdessen vertraulich über [GitHub Security Advisories](https://github.com/malkreide/meteoswiss-mcp/security/advisories/new). Falls das nicht möglich ist, öffne ein minimales Issue mit der Bitte um einen privaten Kontaktkanal — ohne Details preiszugeben.

Bitte gib nach Möglichkeit an:
- Eine Beschreibung der Schwachstelle und ihrer möglichen Auswirkung
- Schritte zur Reproduktion (Proof-of-Concept, falls vorhanden)
- Betroffene Version, Transport (`stdio` / `streamable-http`) und Konfiguration
- Vorschläge zur Behebung

Du erhältst innerhalb von **5 Arbeitstagen** eine erste Bestätigung. Nach der Triage streben wir einen Zeitplan zur Behebung an und halten dich über den Fortschritt auf dem Laufenden. Responsible Disclosure wird geschätzt — bitte gib uns angemessen Zeit, einen Fix zu veröffentlichen, bevor du Details öffentlich machst.

## Sicherheitsmodell

Dies ist ein **nur lesender** MCP-Server über öffentliche Open-Government-Daten. Er hält keine Benutzer-Credentials und schreibt keine Daten. Wichtige Schutzmechanismen (siehe die im [README](README.de.md) referenzierten Audit-Findings und das Verzeichnis `audits/`):

- **Nur-Lese-Tools** — alle Tools tragen `readOnlyHint: true`; der Server kann keine Daten verändern oder löschen.
- **Egress-Allow-List** — ausgehende HTTP-Calls (auch Redirect-Follows) sind auf `data.geo.admin.ch`, `api.open-meteo.com`, `geocoding-api.open-meteo.com` und `opendata.swiss` beschränkt. IP-Literale und Cloud-Metadata-Endpunkte (z.B. `169.254.169.254`, RFC1918) werden mit `EgressBlocked` abgelehnt (SEC-004 / SEC-021).
- **Sichere Bind-Defaults** — `MCP_HOST` defaultet auf `127.0.0.1`; das Binden an `0.0.0.0` erfordert das explizite `MCP_ALLOW_ANY_HOST=1` (SEC-016).
- **Optionale API-Key-Auth** — mit `MCP_API_KEY` lässt sich `X-API-Key` / `Authorization: Bearer` für alle Routen ausser `/health` erzwingen, mit Constant-time-Vergleich (SEC-009 / SEC-013).
- **CORS standardmässig aus** — nur same-origin, sofern `MCP_ALLOWED_ORIGINS` nicht gesetzt ist (SDK-004).

Zur Härtung des Deployments im HTTP-Modus siehe den Abschnitt **HTTP-Modus Sicherheit** im [README](README.de.md).

## Geltungsbereich

Im Geltungsbereich: der Server-Code in diesem Repository (`src/`), seine Tool-Definitionen und die HTTP-Transport-Schicht.

Ausserhalb des Geltungsbereichs: Schwachstellen in vorgelagerten Datenanbietern (MeteoSwiss, Open-Meteo, opendata.swiss) und in Drittanbieter-Abhängigkeiten — bitte melde diese den jeweiligen Maintainern. Dependency-Advisories werden über Dependabot verfolgt.
