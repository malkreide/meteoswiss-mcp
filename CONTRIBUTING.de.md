# Mitwirken bei meteoswiss-mcp

🇬🇧 [English version](CONTRIBUTING.md)

Danke für dein Interesse an einem Beitrag! Dieser Server ist Teil des [Swiss Public Data MCP Portfolios](https://github.com/malkreide/swiss-public-data-mcp).

---

## Issues melden

Nutze [GitHub Issues](https://github.com/malkreide/meteoswiss-mcp/issues), um Fehler zu melden oder Features vorzuschlagen.

Bitte gib an:
- Python-Version und Betriebssystem
- Vollständige Fehlermeldung oder Beschreibung des unerwarteten Verhaltens
- Schritte zur Reproduktion

---

## Pull Requests

1. Forke das Repository
2. Richte die Dev-Umgebung und die lokalen Gates ein:
   `pip install -e ".[dev]" && pre-commit install`
   Die Hooks fahren dieselben Prüfungen wie die CI, mit der in
   `pyproject.toml` gepinnten `ruff`-Version — dieser Pin ist die einzige
   Quelle der Wahrheit, und der erste Hook bricht ab, wenn das `ruff` in
   deinem `PATH` ein anderes ist.
3. Erstelle einen Feature-Branch: `git checkout -b feat/dein-feature`
4. Nimm deine Änderungen vor und ergänze Tests
5. Stelle sicher, dass alle Tests bestehen: `PYTHONPATH=src pytest tests/ -m "not live"`
6. Committe mit [Conventional Commits](https://www.conventionalcommits.org/): `feat: add new tool`
7. Pushe und öffne einen Pull Request gegen `main`

---

## Code-Stil

- Python 3.11+
- [Ruff](https://github.com/astral-sh/ruff) für Linting und Formatierung
- Type-Hints für alle öffentlichen Funktionen erforderlich
- Tests für neue Tools erforderlich (`tests/test_server.py`)
- Folge den bestehenden `MCPServer`- / Pydantic-v2-Mustern in `server.py`

---

## Datenquellen

Dieser Server nutzt offene Schweizer Wetter- und Klima-APIs — alle ohne Authentifizierung:

| Quelle | Dokumentation |
|--------|--------------|
| BGDI STAC API (MeteoSwiss OGD) | [data.geo.admin.ch](https://data.geo.admin.ch/api/stac/v1) |
| Open-Meteo (MeteoSwiss ICON) | [open-meteo.com](https://open-meteo.com/) |
| opendata.swiss | [opendata.swiss](https://opendata.swiss/) |

Beim Hinzufügen neuer Datenquellen gilt das **No-Auth-First**-Prinzip: Phase 1 nutzt ausschliesslich offene, authentifizierungsfreie Endpunkte. Authentifizierte APIs werden in späteren Phasen mit Graceful Degradation eingeführt.

---

## Die Live-Suite: wann sie läuft, und wer ein rotes Ergebnis sieht

**Kadenz:** täglich 05:17 UTC, dazu jederzeit von Hand über *Actions → Live Tests → Run
workflow*. Siehe [`.github/workflows/live-tests.yml`](.github/workflows/live-tests.yml).

**Wer es sieht:** **Niemand automatisch.** Ein Fehlschlag erzeugt hier *kein* Issue und keine
Benachrichtigung — nur einen roten Lauf im Actions-Tab und eine Erklärung im
Job-Summary. Wer den Tab nicht öffnet, erfährt nichts.

Das ist die schwächste Stelle dieses Gates und bewusst so dokumentiert, statt
sie zu beschönigen: Andere Server des Portfolios legen bei Rot ein Issue an. Der
erste Lauf wird einmal wiederholt, bevor er rot meldet, damit ein einzelner
Netzaussetzer keinen Fehlalarm erzeugt.

**Ein roter Live-Lauf heisst nicht zwingend «unser Fehler».** Er heisst: Der
Vertrag mit der Quelle hat sich geändert, oder die Quelle ist gerade aus. Beides
gehört gesehen, nur das Erste gehört gefixt. Bitte den Lauf lesen, bevor der Job
deaktiviert wird — so stirbt dieser Check, und er ist der einzige im Repo, der
einer falschen Grundannahme über die MeteoSchweiz-Quellen widersprechen kann. Jeder andere Test
prüft gegen eine Fixture, und die Fixture ist aus derselben Annahme geschrieben
wie der Code.

## Lizenz

Mit deinem Beitrag erklärst du dich einverstanden, dass deine Beiträge unter der [MIT-Lizenz](LICENSE) lizenziert werden.
