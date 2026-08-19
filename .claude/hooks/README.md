# SessionStart-Hook: Klon-Aktualität

`session-start.sh` meldet beim Sessionstart, wie viele Commits der
ausgecheckte Stand hinter dem Standard-Branch des Remotes liegt.
Bei 0 gibt er nichts aus.

Registriert in `../settings.json` unter `hooks.SessionStart`. JSON kennt keine
Kommentare, deshalb steht die Begründung hier und nicht dort.

## Warum

Ein veralteter Klon hat am 3.8.2026 **zweimal** eine rote CI erzeugt, deren
Ursache nicht im Diff stand. Beide Male fehlten dem Klon genau die Commits,
die das Gate einführten, an dem der Branch dann scheiterte — der Fehler stand
also in Dateien, die der Branch nie angefasst hatte. Die Fehlersuche lief
entsprechend an der falschen Stelle.

Die Prüfung kostet eine Sekunde (gemessen in dieser Umgebung: 1.0–1.2 s,
netzgebunden) und ersetzt eine Fehlersuche in den falschen Dateien. Sie ist die maschinelle Fassung des ersten Absatzes in `CLAUDE.md`
(«Vor der Arbeit»), der bis dahin nur als Bitte an den Leser existierte.

## Die drei Zusicherungen

### 1. Er blockiert die Session nie

Das ist die wichtigste Eigenschaft, wichtiger als die Prüfung selbst. Ein
Hook, der bei Netzproblemen die Arbeit anhält, wird nach dem zweiten Mal
abgeschaltet — und schützt danach gar nichts mehr. Ein Hook, der still
danebenliegt, schützt in der überwiegenden Mehrheit der Fälle weiter.

Deshalb geht jeder dieser Fälle **still** durch, mit Status 0 und ohne
Ausgabe:

| Fall | Behandlung |
| --- | --- |
| kein `git` im PATH | `command -v git` |
| kein `timeout` im PATH | `command -v timeout` — ohne belastbare Obergrenze wird gar nicht erst gefetcht |
| kein Git-Repo | `git rev-parse --git-dir` |
| kein gemeinsamer Vorfahre (unverwandte Historie, flacher Klon mit Grenze oberhalb von HEAD) | `git merge-base` |
| kein Remote konfiguriert | `git remote` leer |
| Standard-Branch nicht ermittelbar | leerer Branch-Name |
| Netz weg, DNS flattert, Auth fehlt | `git fetch` ≠ 0 |
| detached HEAD ohne gemeinsamen Vorfahren | `rev-list`-Ausgabe nicht numerisch |

Zwei Details, die dafür nötig sind:

- **Kein `set -euo pipefail`.** Unter `set -e` beendet jeder unbedachte
  Nicht-Null-Rückgabewert das Skript mit genau dem Status, den dieser Hook nie
  haben darf. Jeder Schritt prüft seinen Rückgabewert stattdessen selbst; die
  letzte Zeile ist ein unbedingtes `exit 0`.
- **`GIT_TERMINAL_PROMPT=0`** (plus `GIT_ASKPASS` / `BatchMode=yes`). Ein
  git, das ohne Terminal nach Zugangsdaten fragt, ist genau das Hängen, das
  hier vermieden werden soll. `timeout` fängt das zwar ab — aber erst nach
  Ablauf der vollen Frist.

### 2. Kurzes Timeout auf das Netz

`timeout --kill-after=2 5` je Netzoperation, überschreibbar mit
`CLAUDE_CLONE_CHECK_TIMEOUT`. Im schlechtesten Fall zwei Operationen
(`ls-remote` als Rückfall + `fetch`), also ~10 s Obergrenze; der Normalfall ist
eine Operation. `--kill-after` ist nicht kosmetisch: ein git, das in einem
TLS-Handshake hängt, ignoriert SIGTERM, und die Frist liefe ins Leere.

Zusätzlich steht in `settings.json` ein `"timeout": 20` als zweite,
unabhängige Grenze — falls die erste je danebengreift.

### 3. Der Standard-Branch wird ermittelt, nicht angenommen

Drei Server im Portfolio nennen ihren Standard-Branch `master`
(`openlex-mcp`, `swiss-courts-mcp`, `swisstopo-mcp`). Ein fest verdrahtetes
`main` scheitert dort — und genau diese Annahme hat schon einmal einen Branch
15 Commits alt werden lassen, ohne dass etwas gemeldet hätte.

Ermittelt wird zuerst lokal aus `refs/remotes/<remote>/HEAD` (beim Klonen
gesetzt, kostet kein Netz), als Rückfall per `git ls-remote --symref`.

Der leere Branch-Name wird dabei eigens abgefangen — das entspricht dem
`:?`-Schutz im `CLAUDE.md`-Schnipsel.

Dass das nötig ist, ist nachgemessen und nicht vermutet: naheliegend wäre die
Annahme, das Anführungszeichen in `git fetch "$remote" "$branch"` erledige das
schon, weil ein leeres Argument einen Fehler gäbe. Tut es nicht.

```
$ git fetch origin ""      # → holt den Remote-HEAD, rc=0
$ git fetch origin         # → dasselbe, rc=0
```

Beide Formen enden mit Status 0 und setzen FETCH_HEAD. Ohne den Guard käme der
Hook also durch, verglichen gegen den Remote-HEAD statt gegen den ermittelten
Standard-Branch, und meldete im Zweifel «alles aktuell». Ein falsches
Entwarnungssignal ist schlechter als gar keines.

## Flache Klone

Claude Code auf dem Web klont **flach**. Die erste Fassung dieses Hooks stieg
bei `--is-shallow-repository = true` pauschal aus — und war damit genau in der
Umgebung wirkungslos, für die er gebaut wurde. Die Gegenprobe (Stand künstlich
zurücksetzen, Meldung erwarten) hat das aufgedeckt; ohne sie wäre ein Hook
gemergt worden, der nie etwas meldet und dabei wie ein funktionierender
aussieht.

Entscheidend ist nicht, ob der Klon flach ist, sondern ob die Grenze
*unterhalb* des Vergleichspunkts liegt. Das beantwortet `git merge-base`:
gibt es einen gemeinsamen Vorfahren, ist `HEAD..FETCH_HEAD` exakt; gibt es
keinen, zählt es die ganze geholte Historie und die Zahl ist erfunden — dann
schweigt der Hook.

Gemessen an einem lokalen Fixture (Remote drei Commits voraus): mit Guard
exakte `3`, ohne Guard auf einer verwaisten Historie ein frei erfundenes `7`.

## Lokal ausprobieren

```bash
.claude/hooks/session-start.sh; echo "Status: $?"     # im aktuellen Repo
```

Der Status muss **immer** 0 sein. Die Ausfallpfade lassen sich einzeln
erzwingen, ohne das Repo anzufassen:

```bash
# Netz weg  -> still, Status 0
GIT_SSH_COMMAND=false .claude/hooks/session-start.sh; echo "Status: $?"

# Timeout greift -> still, Status 0
CLAUDE_CLONE_CHECK_TIMEOUT=0.001 .claude/hooks/session-start.sh; echo "Status: $?"

# kein Repo -> still, Status 0
(cd /tmp && "$OLDPWD/.claude/hooks/session-start.sh"); echo "Status: $?"

# Meldung provozieren: Stand künstlich zurücksetzen
git -c advice.detachedHead=false checkout --quiet HEAD~3
.claude/hooks/session-start.sh
git checkout --quiet -
```
