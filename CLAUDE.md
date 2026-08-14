# CLAUDE.md

## Vor der Arbeit

Klon-Aktualität prüfen: `git fetch origin main && git rev-list --count HEAD..origin/main`
Ein veralteter Klon erzeugt eine rote CI, deren Ursache nicht im Diff steht.
Am 3.8.2026 zweimal passiert — beide Male fehlten genau die Commits, die
das Gate einführten, an dem der Branch scheiterte.

Gates lokal fahren, mit der GEPINNTEN ruff-Version aus der CI. Eine andere
Version meldet Abweichungen, die niemand verursacht hat.

## Tests

Gegenprobe ist Pflicht. Ein Test, der grün bleibt, wenn man die
Implementierung entfernt, prüft nichts. Jede neue Zusicherung einzeln
neutralisieren und zeigen, dass genau die zugehörigen Tests fallen.

Zwei Fallen, die beide grün blieben:

- Eine Fake-Uhr, die nur beim Schlafen vorrückt, kann eine Zusicherung über
  echte Zeit nicht widerlegen.
- `monkeypatch.setattr(modul.asyncio, "sleep", ...)` greift ins Modul
  `asyncio` selbst und entschärft die Mechanik im ganzen Prozess. Patche
  einen Modul-Alias (`_sleep = asyncio.sleep`), nicht das fremde Modul.

Handgeschriebene Fixtures kodieren die Annahme des Autors und können sie
nicht widerlegen. Mindestens eine aufgezeichnete Antwort pro externem
Endpunkt, mit Aufnahmedatum.

## Wenn etwas rot ist

Roter Live-Test: erst die Quelle abfragen, dann einordnen. Nicht aus der
Fehlermeldung schliessen. Am 3.8.2026 hiess «nicht gefunden» nicht, dass der
Datensatz weg war, sondern dass die Quelle die Schreibweise ihrer Kopfzeile
gewechselt hatte — vier von sechs Datensätzen produktiv kaputt, alle
Unit-Tests grün.

PR ohne jeden Check ist selten ein Repo ohne CI, meistens ein
Merge-Konflikt: GitHub berechnet dafür keinen Merge-Commit und startet nichts.

Ein Codex-Review auf einem PR wird beantwortet oder behoben, nie ignoriert.

---

## Dieses Repo

**ruff:** `ruff==0.16.1`, gepinnt in `pyproject.toml` unter
`[project.optional-dependencies] dev`. Das ist der einzige Pin im Repo — CI
und `.pre-commit-config.yaml` installieren bzw. rufen daraus, keiner von
beiden nennt eine eigene Version. Deshalb sind die Hooks `repo: local` /
`language: system` und nicht `ruff-pre-commit` (das bräuchte ein zweites
`rev:`). Dass das ruff im PATH wirklich der Pin ist, prüft
`scripts/check_ruff_pin.py` als erster Hook.

Einrichten: `pip install -e ".[dev]" && pre-commit install`

**Gate-Befehle, wörtlich aus `.github/workflows/ci.yml`** (Matrix: Python
3.11 / 3.12 / 3.13):

```bash
PYTHONPATH=src pytest tests/ -m "not live"
ruff check src/ tests/
ruff format --check src/ tests/
grep -rnE '^\s*print\s*\(' src/          # muss LEER sein (OBS-004)
python scripts/tool_hashes.py --write    # danach: git diff --exit-code tool-hashes.json (SEC-022)
```

`ruff check` und `ruff format --check` sind zwei eigenständige Gates; grün
beim einen sagt nichts über das andere. Der Hash-Guard läuft nur auf 3.13,
weil die Pydantic-Serialisierung versionsabhängig ist — auf 3.11 weicht der
Hash ab, ohne dass etwas kaputt wäre. `pre-commit` fährt dieselben fünf
Gates; nur `scripts/` ist von keinem der beiden ruff-Gates erfasst.

**Live-Tests:** `.github/workflows/live-tests.yml`, täglich 05:17 UTC plus
`workflow_dispatch`, fährt `PYTHONPATH=src pytest tests/ -m live` auf 3.13
(DRIFT-005). Ein Fehlschlag wird einmal wiederholt — gegen Netzaussetzer,
nicht gegen echte Brüche. `schedule` greift nur auf `main`; auf einem Branch
lässt sich der Workflow nur von Hand auslösen.
