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
`[project.optional-dependencies] dev`. Die CI installiert daraus
(`pip install -e ".[dev]"`), pinnt selbst nichts. Eine
`.pre-commit-config.yaml` existiert nicht — der Pin steht nur an dieser
einen Stelle (Befund 1).

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
beim einen sagt nichts über das andere. Der Hash-Guard läuft nur auf 3.13.

**Live-Tests:** kein geplanter Workflow. `.github/workflows/` kennt nur
`push`/`pull_request` (ci.yml) und `release` (publish.yml) — keinen
`schedule`/cron-Trigger. Die 6 `@pytest.mark.live`-Tests in
`tests/test_server.py` werden per `-m "not live"` ausgeschlossen und sonst
nie gefahren (Befund 2, DRIFT-005).
