# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Behoben — Browser-Clients kamen am Preflight nicht vorbei

Spec `2026-07-28` routet eine Streamable-HTTP-Anfrage ueber `Mcp-Method`,
`Mcp-Name` und `Mcp-Protocol-Version`. Die CORS-Freigabeliste nannte davon nur
den letzten, und den in der Schreibweise `MCP-Protocol-Version` — dazu
`Mcp-Session-Id`, den Header genau der Session-Mechanik, die dieselbe Revision
abgeschafft hat. Ein Browser darf einen nicht safelisteten Header nicht senden,
wenn der Server ihn nicht nennt: die Anfrage starb vor dem ersten MCP-Byte,
waehrend stdio und Python, fuer die kein Preflight gilt, weiterliefen. Deshalb
war nichts rot.

Die drei Header stehen jetzt als `CORS_ROUTING_HEADERS` beisammen;
`tests/test_cors.py` faehrt jeden einzeln gegen die zusammengebaute App und
haelt die Liste gegen die Konstanten aus `mcp.shared.inbound`.

### Hinzugefuegt — Frischehinweise auf den auflistenden Methoden

SEP-2549, Spec `2026-07-28`: `tools/list`, `resources/list`,
`resources/templates/list` und `server/discover` antworten mit `ttlMs` 300000
und `cacheScope` `public`. Das SDK setzt sonst «sofort veraltet, nie geteilt»
und laesst damit jeden Client bei jeder Verbindung neu auflisten — fuer
Verzeichnisse, die per Dekorator beim Import feststehen und nicht vom Aufrufer
abhaengen.

`resources/read` bleibt bewusst ohne Hinweis: das waere eine Zusicherung ueber
den Inhalt statt ueber das Verzeichnis.
`test_der_inhalt_einer_ressource_traegt_keinen_frischehinweis` faellt, wenn
jemand die Methode aufnimmt.


### Hinzugefuegt — die Gates laufen jetzt auch lokal und die Live-Tests ueberhaupt

**`.pre-commit-config.yaml`** faehrt dieselben fuenf Gates wie
`.github/workflows/ci.yml`. Alle Hooks sind `repo: local` mit
`language: system` — ein `ruff-pre-commit`-Repo braeuchte ein eigenes `rev:`,
also eine zweite ruff-Version neben dem Pin in `pyproject.toml`. Zwei Pins
laufen auseinander, und dann meldet das lokale Gate etwas anderes als die CI.
So bleibt `ruff==0.16.1` der einzige Pin im Repo.

Der Preis dafuer ist, dass `language: system` nimmt, was im PATH liegt.
**`scripts/check_ruff_pin.py`** gleicht das aus: er liest den Pin aus
`pyproject.toml`, vergleicht ihn mit `ruff --version` und bricht als erster
Hook mit einer Anleitung ab, wenn beides auseinanderfaellt. Beim Bau dieser
Aenderung hat er sofort zugeschlagen — im PATH lag ruff 0.15.8.

**`scripts/check_tool_hashes.py`** prueft den SEC-022-Snapshot ohne
Seiteneffekt: verglichen wird gegen stdout des Generators, nicht via
`--write`. Der bisherige CI-Weg schreibt die Datei und laesst sie im
Fehlerfall geaendert liegen. Ausserhalb von Python 3.13 ueberspringt er
sauber, weil der Hash an der Pydantic-Serialisierung haengt und dort
verlaesslich abweicht, ohne dass etwas kaputt waere — ein Gate, das
regelmaessig falsch anschlaegt, wird mit `--no-verify` umgangen und schuetzt
danach gar nichts mehr.

**`.github/workflows/live-tests.yml`** (DRIFT-005) faehrt taeglich um
05:17 UTC `pytest tests/ -m live` auf Python 3.13, dazu `workflow_dispatch`
fuer Laeufe von Hand. Die sechs `@pytest.mark.live`-Tests wurden bisher von
keinem Workflow gefahren: die CI schliesst sie per `-m "not live"` aus, und
einen `schedule`-Trigger gab es nicht. Genau diese Luecke ist die, durch die
ein Formatwechsel an der Quelle produktiv durchschlaegt, waehrend alle
Unit-Tests gruen bleiben. Ein roter Lauf wird genau einmal wiederholt — gegen
einen Netzaussetzer, nicht gegen einen echten Bruch; ein roter Lauf, dem
niemand glaubt, ist so wenig wert wie gar keiner.

### Hinzugefuegt — die Fixtures sind aufgezeichnet, nicht mehr ausgedacht

**`scripts/record_fixtures.py`** zeichnet von den drei Quellen auf — STAC
(`data.geo.admin.ch`), der MeteoSwiss-App-API und Open-Meteo — und schreibt
`tests/fixtures/*` samt `PROVENANCE.md` mit Quelle, **Aufzeichnungsdatum**,
Auswahlregel und SHA-256 je Datei. Ohne Datum ist «aufgezeichnet» nach zwei
Jahren von «ausgedacht» nicht mehr zu unterscheiden.

**Der wichtigste Befund betrifft den Asset-Selektor.** `_select_smn_now_asset`
lehnt bewusst jeden Fallback ab — im selben Asset-Dict liegen Tages-, Monats-,
Jahres- und Jahrzehnt-Historien, und «die als aktuelle Beobachtung auszugeben
waere schlimmer als ein sauberer Fehler», sagt sein Docstring. Die
handgeschriebene Fixture fuehrte **vier** Assets; die Quelle liefert **16**,
darunter `ogd-smn_klo_h_historical_1980-1989.csv` bis `…_2020-2029.csv`. Der
Selektor wurde also nie gegen die Ablenker geprueft, gegen die es ihn gibt. Das
STAC-Item wird deshalb **vollstaendig** aufgezeichnet, und das Skript bricht ab,
wenn die Quelle eines Tages keine Ablenker mehr liefert — dann prueft der
Selektor-Test naemlich nichts mehr.

**Die 10-Minuten-CSV hatte 7 Spalten, die Quelle hat 34** — und leere Zellen,
die die Vorgaengerin gar nicht kannte. Der Renderer geht damit korrekt um: Er
ueberspringt leere Werte, statt zu stuerzen oder eine Null zu erfinden. Gemessen
am 2026-08-07 fuer KLO liegt allerdings keine der leeren Zellen in den neun
Parametern, die der Server rendert — die stille Auslassung tritt hier also gar
nicht ein. Das steht hier als Messung, nicht als Befund.

Erwartungen werden durchgehend **aus der Fixture abgeleitet** statt
hingeschrieben. Bei Wetterdaten ist das keine Stilfrage: Eine feste Temperatur
waere beim naechsten Aufzeichnen falsch, ohne dass sich etwas Geprueftes
geaendert haette.

**Kein Befund am Produktivcode.** Wie in `zurich-opendata-mcp` und
`swiss-statistics-mcp` hat das Aufzeichnen hier nichts Kaputtes freigelegt.

**Am Rande, nicht behoben:** Die Live-Tests gegen den Geocoding-Dienst fallen
wechselnd mit `ConnectTimeout` aus — mal `test_live_school_check`, mal
`test_live_geocode_leutschenbach`, einzeln laufen sie durch. Eine fluechtige
Netzbedingung gegen eine Fremdquelle, nicht Gegenstand dieses PRs. Der PR-Lauf
der CI fuehrt `-m "not live"` und ist davon nicht betroffen.

Der Rahmen dazu steht im Skill [`mcp-data-fidelity`](https://github.com/malkreide/mcp-data-fidelity-skill)
unter Regel 5 und im Katalog-Check `OPS-009`.


### Fixed

- **Streamable-HTTP wies unter jedem echten Hostnamen mit 421 ab (SEC-005).**
  `_build_http_app()` gab `stateless_http` an die App weiter, aber nicht den
  Bind. Unter mcp 2.x ist `host` kein kosmetisches Argument: das SDK leitet
  daraus seine Host-Allow-List ab und aktiviert bei loopback-artigem Wert
  automatisch `127.0.0.1:*`. Da der Default `127.0.0.1` ist, traf das genau den
  Fall, den der Einstiegspunkt fürs Cloud-Deployment vorsieht —
  `MCP_HOST=0.0.0.0` mit `MCP_ALLOW_ANY_HOST=1`.

  Der Bind reist jetzt mit, und eine echte Allow-List entsteht aus dem neuen
  `MCP_ALLOWED_HOSTS`. Ohne diese Variable bleibt der Schutz auf einem
  Nicht-Loopback-Bind bewusst aus und der Aufrufer warnt — eine geratene Liste
  wäre genau der 421-Fall. Die per `MCP_ALLOWED_ORIGINS` konfigurierten
  CORS-Origins werden mit aufgenommen.

  Der optionale API-Key-Schutz ersetzt das nicht: er prüft, *wer* fragt, nicht
  *unter welchem Namen* der Server angesprochen wird — DNS-Rebinding zielt auf
  Letzteres.

  13 neue Tests, darunter der tragende Fall „richtiger Hostname, falscher Port"
  und einer, der festhält, dass `stateless_http` beim Ergänzen des neuen Kwargs
  nicht verloren geht — genau diese Fehlerklasse wird hier ja aufgeräumt.
  Mutationsgetestet: nimmt man den `host`-Kwarg wieder weg, fallen beide.

  Geprüft mit den wörtlichen CI-Kommandos: 136 passed / 6 deselected,
  `ruff check src/ tests/` clean.


## [0.6.1] - 2026-08-02

### Behoben

- **`structlog` hatte keine Obergrenze, und der Index fuehrt bereits einen Major
  oberhalb der Untergrenze.** Deklariert war `structlog>=24.0.0`; auf PyPI liegt
  `26.1.0`. Das Artefakt aendert sich nicht — die Antwort des Resolvers auf
  die naechste frische Installation schon, und genau so wurde
  `swiss-energy-mcp` 0.3.3 uninstallierbar, als `mcp` 2.0.0 das Modul entfernt
  hat, das es importierte.

  Neu `structlog>=24.0.0,<27`. Die Grenze ist gemessen, nicht geraten: dieses Paket installiert
  und importiert heute gegen `structlog 26.1.0`, die Obergrenze laesst also zu,
  was nachweislich funktioniert, und stoppt nur den naechsten, unbekannten
  Major.

Ein Abhaengigkeitsbereich erreicht die Nutzenden nur ueber ein neues
Release, daher der Versions-Bump. Am Code aendert sich nichts.

## [0.6.0] - 2026-07-30

Reparatur-Release. In `0.5.0` lieferten **drei der sechs Tools nichts** —
`meteo_current` für jede Station einen 404, `meteo_forecast` und
`meteo_school_check` gar keine Daten. Drei unabhängige Ursachen, zwei davon
Änderungen bei Datenquellen, eine ein Fehler im Server selbst. Alle drei sind
live gegen die echten APIs verifiziert.

Für Clients nicht breaking: Tool-Namen, Parameter und Rückgabetypen sind
unverändert. Einzig die Beschreibung von `meteo_forecast` wurde präzisiert
(siehe «Changed»), was `tool-hashes.json` ändert.

### Behoben

- **Ortsnamen mit Zusatz waren gar nicht auflösbar**
  ([#37](https://github.com/malkreide/meteoswiss-mcp/issues/37)). Die
  Geocoding-API kennt nur einzelne Ortsnamen und liefert für
  «Schulhaus Leutschenbach Zürich» nichts. `_geocode()` schickte den vollen
  String in *beiden* Versuchen — der «Fuzzy»-Retry liess nur die
  Sprachrestriktion weg und kürzte die Anfrage nie. Damit scheiterten auch die
  Beispiele, die die Tools selbst dokumentieren (`meteo_forecast`-Docstring und
  die `location`-Beschreibung von `meteo_school_check`).

  Neu werden bei Misserfolg führende Tokens nach und nach weggelassen —
  Schweizer Ortsangaben sind konventionell `Gattungswort… Ort Stadt`, das
  verallgemeinert also von spezifisch nach allgemein und endet bei der Stadt.
  Zusätzlich wird jedes führende Token einzeln probiert, **aber nur mit
  Namensprüfung**: «Leutschenbach» → `Leutschenbach` wird angenommen,
  «Schulhaus» → `Dübendorf / Schulhaus Wil` verworfen. Ohne diese Prüfung
  bekäme eine Zürcher Anfrage stillschweigend Wetter aus einer anderen
  Gemeinde — schlimmer als der bisherige harte Fehler.

  Live verifiziert:

  | Anfrage | Ergebnis |
  |---|---|
  | `Schulhaus Leutschenbach Zürich` | Leutschenbach, ZH (47.4175, 8.5648) |
  | `Sportanlage Heerenschürli Zürich` | Zurich, ZH (47.3667, 8.5500) |
  | `Zürich` / `Bern` | unverändert `exact`, ein einziger Request |

  `match_type` kennt dafür neu `"shortened"` — Aufrufende sehen damit, dass die
  Antwort allgemeiner ist als die Frage. Ein Volltreffer löst weiterhin genau
  einen Request aus; gekürzt wird nur, wenn der volle String scheitert.

- **`meteo_forecast` und `meteo_school_check` lieferten gar nichts mehr**
  ([#35](https://github.com/malkreide/meteoswiss-mcp/issues/35)). Open-Meteo hat
  die provider-eigenen Pfade abgeschafft; `/v1/meteoswiss` antwortet mit 404.
  Modelle werden neu über `models=` auf `/v1/forecast` gewählt.

  Ein reiner URL-Tausch reicht nicht, denn keines der MeteoSwiss-Modelle
  liefert, was die beiden Tools zusagen. Live gemessen für
  `meteoswiss_icon_seamless` (ICON-CH1 + ICON-CH2):

  - **Reichweite 5 Tage.** `forecast_days=16` liefert darüber hinaus nur
    Nullwerte — das ist der ICON-CH2-Horizont, kein Parameterproblem.
    `meteo_forecast` verspricht aber bis zu 16 Tage.
  - **Kein UV-Index**, auch nicht stündlich (0 von 72 Werten über 3 Tage).
    Open-Meteo bezieht UV aus CAMS, nicht aus dem Modelloutput.
    `meteo_school_check` warnt aber ab UV 6.

  Der Server holt deshalb neu **beide** Modelle und mischt sie entlang der
  Zeitachse: MeteoSwiss ICON gewinnt überall, wo es einen Wert hat, `None`
  fällt auf `best_match` zurück. Dieselbe Regel erledigt die 5-Tage-Grenze und
  die UV-Lücke. Gemischt wird bewusst über Zeitstempel statt Listenindizes —
  der ICON-Block ist kürzer, und ein Indexversatz würde Werte still auf den
  falschen Tag schieben.

  **Die Herkunft steht in jeder Antwort**, statt im Ungefähren zu bleiben: die
  Markdown-Fussnote und die JSON-Felder `modell` / `modell_details` weisen aus,
  welche Tage aus MeteoSwiss ICON stammen, ab wann `best_match` übernimmt und
  dass UV durchgehend von dort kommt. Fällt der ICON-Request aus, trägt
  `best_match` die Antwort allein — und sagt das ebenfalls, statt einen
  Totalausfall zu produzieren.

  Kein Test hätte das finden können: die Unit-Tests deckten ausschliesslich
  Geocoding-Fehlerpfade ab, der erfolgreiche Prognosepfad war komplett
  ungetestet. Neu 11 Tests für Merge-Logik (inklusive Zeitachsen-Versatz),
  Provenance-Label, den vollen Hybrid-Pfad in Markdown und JSON, den
  ICON-Ausfall und die UV-Herkunft in `meteo_school_check`.

### Changed

- **`meteo_forecast`-Beschreibung präzisiert** — sie nannte pauschal
  «MeteoSwiss ICON-CH1/CH2-EPS» und verschwieg damit, dass Tage jenseits von 5
  und der UV-Index aus `best_match` stammen. `tool-hashes.json` entsprechend neu
  generiert (Rug-Pull-Signal, SEC-022). Für Clients nicht breaking: Parameter
  und Rückgabetyp sind unverändert, `days` akzeptiert weiterhin 1–16.

- **`meteo_current` lieferte für jede Station 404**
  ([#33](https://github.com/malkreide/meteoswiss-mcp/issues/33)). Die STAC-Item-ID
  ist der nackte Stationscode in Kleinschreibung (`…/items/klo`); der Server
  stellte ihm die Collection-ID voran (`…/items/ch.meteoschweiz.ogd-smn-klo`).
  Live gegen die BGDI-API verifiziert: `/items/klo` → 200, die Präfix-Variante
  und die Grossschreibung → je 404. Die URL wurde an drei Stellen dupliziert
  (Fetch, Fehlermeldung, JSON-Provenance) — jetzt einmal in
  `_smn_stac_item_url()`.

  Beim Beheben kamen drei weitere Fehler zum Vorschein, die der 404 verdeckt
  hatte — sie hätten nach dem URL-Fix plausibel aussehende, aber falsche Daten
  geliefert:

  - **Die Asset-Auswahl konnte nie greifen.** Gesucht wurde nach `/now/` im
    Pfad, doch die Granularität steckt im Dateinamen
    (`ogd-smn_klo_t_now.csv`); ein Verzeichnis `/now/` existiert nicht. Der
    Fallback nahm daraufhin das *erste* CSV im Item — `d_historical`, also
    Tageswerte ab 1980, ausgegeben als «aktuelle Beobachtung». Neu wird gezielt
    `_t_now` gewählt, ersatzweise `_t_recent`; gibt es beides nicht, ist das ein
    Fehler statt eines stillen Griffs ins Archiv.
  - **Der Zeitstempel war immer `–`.** Gelesen wurde `time`/`Date`/`datum`, die
    OGD-CSV führt aber `reference_timestamp`.
  - **Die Zeile «Luftdruck (reduziert auf Meeresniveau)» blieb immer leer.**
    `prestah0` gibt es in der CSV nicht; der QNH-Wert heisst `pp0qnhs0`.

### Tests

Alle drei Fehler oben hatten einen Test, der sie hätte finden müssen, aber so
formuliert war, dass auch der Fehlerfall ihn erfüllte. Das ist das eigentliche
Thema dieses Releases:

- **`meteo_current` (live):** prüfte `"KLO" in result or "Zürich" in result` —
  beides steht auch in der Fallback-Fehlermeldung. Der Test lief also durch
  einen Totalausfall hindurch grün. Verlangt jetzt echte Messwerte.
- **`meteo_forecast` / `meteo_school_check`:** der erfolgreiche Prognosepfad war
  komplett ungetestet, abgedeckt waren nur Geocoding-Fehlerpfade. Zudem mockten
  die Tests die eigene Endpoint-Konstante — sie konnten das Abschalten upstream
  gar nicht bemerken.
- **`_geocode` (live):** prüfte nur einen Koordinatenbereich (8.4–8.7), den
  Dübendorf mit 8.62 ebenfalls erfüllt — der Fehlgriff auf eine andere Gemeinde
  wäre durchgewinkt worden. Verlangt jetzt den Ortsnamen im Ergebnis.

- **Cache-Isolation zwischen Tests.** Der TTL-Cache ist modul-global und
  überlebte den einzelnen Test. Ein Test sah dadurch Einträge eines früheren,
  umging sein eigenes respx-Mock und schlug je nach Ausführungsreihenfolge fehl
  — oder bestand aus dem falschen Grund. Eine autouse-Fixture räumt jetzt vor
  und nach jedem Test auf.

## [0.5.0] - 2026-07-30

Reparatur-Release für einen kaputten PyPI-Stand. `mcp` 2.0.0 erschien am
28.07.2026 und entfernte `mcp.server.fastmcp` — genau das Modul, das v0.4.0
importierte. Weil v0.4.0 keine Obergrenze auf `mcp` hatte, zog jede frische
Installation aus PyPI die 2.0.0 und scheiterte sofort beim Import. Das
betrifft `uvx meteoswiss-mcp` genauso wie `pip install meteoswiss-mcp`
([#31](https://github.com/malkreide/meteoswiss-mcp/issues/31)).

Der Code auf `main` war bereits migriert; dieses Release bringt die Korrektur
zu den Nutzenden. Für Clients ist nichts breaking — die 6 Tools, ihre Schemata
und das Wire-Format sind unverändert (`tool-hashes.json` bleibt gleich).

### Behoben

- **Frische Installationen starten wieder.** Der `ModuleNotFoundError: No
  module named 'mcp.server.fastmcp'` beim Start von `uvx meteoswiss-mcp` ist
  weg. Ursache war nicht der Code, sondern die Release-Lücke: der Fix lag seit
  #29/#30 auf `main`, aber PyPI führte weiterhin v0.4.0.

### Changed

- **Migration auf das `mcp`-Python-SDK 2.x** (#30). Der Server-Import wechselt
  von `mcp.server.fastmcp` auf `mcp.server.mcpserver`, `FastMCP` heisst neu
  `MCPServer`. Ohne Kompatibilitäts-Shim im SDK ist der Boden hart: der Pin
  lautet jetzt `mcp[cli]>=2.0.0,<3` statt `>=1.28.1`. Weitere Anpassungen im
  SDK, die mitgezogen werden mussten:
  - `mcp_types` snake_cased sämtliche Modell-Attribute (`inputSchema` →
    `input_schema`, `isError` → `is_error`, …). Das sind Pydantic-Aliase, das
    Wire-Format bleibt identisch.
  - `McpError` heisst `MCPError` und nimmt `(code, message, data=None)` direkt
    entgegen statt eine `ErrorData`-Instanz zu umschliessen.
  - `call_tool()` liefert ein `CallToolResult` statt des 1.x-Tupels
    `(content, structured)`.
  - `MCPServer.__init__` akzeptiert `host`/`port`/`stateless_http`/
    `transport_security` nicht mehr — das sind neu `run()`- bzw. App-Kwargs.
  - Der Lowlevel-Server ist als `_lowlevel_server` erreichbar und exponiert
    kein `request_handlers`-Mapping mehr.

  Gegen eine aufgezeichnete 1.x-Baseline verifiziert: die Suite besteht vor
  und nach der Migration exakt dieselben Tests, ohne neue Fehlschläge und ohne
  stillschweigend übersprungene Tests.

### Added

- **`serverInfo.version` im initialize-Handshake.** Der Server meldete bisher
  einen leeren Version-String — ausgerechnet die Angabe, die bei einem
  Bug-Report als Erstes gebraucht wird. Sie kommt neu aus der installierten
  Distribution (`importlib.metadata`), kann also nicht gegenüber dem Paket
  veralten; im Source-Checkout ohne Installation lautet sie `0.0.0+unknown`.

### Docs

- README (DE/EN) und CONTRIBUTING (DE/EN) sprachen weiterhin von «FastMCP» und
  nannten `mcp[cli]>=1.0.0` als SDK-Version — beides auf `MCPServer` bzw.
  `mcp[cli]>=2.0.0,<3` korrigiert.

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
