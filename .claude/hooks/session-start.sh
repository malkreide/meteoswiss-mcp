#!/usr/bin/env bash
#
# SessionStart-Hook: meldet, wie viele Commits der ausgecheckte Stand hinter
# dem Standard-Branch des Remotes liegt. Bei 0 schweigt er.
#
# Begruendung, Ausfallverhalten und die Gruende fuer die einzelnen
# Vorsichtsmassnahmen stehen in .claude/hooks/README.md.
#
# Oberste Regel: dieser Hook haelt die Session unter keinen Umstaenden auf.
# Kein Netz, kein Remote, detached HEAD, flatterndes DNS, fehlendes git —
# jeder dieser Faelle geht still durch. Deshalb steht hier bewusst KEIN
# `set -euo pipefail`: unter `set -e` wuerde jeder unbedachte Nicht-Null-
# Rueckgabewert das Skript mit genau dem Status beenden, den der Hook nie
# haben darf. Stattdessen prueft jeder Schritt seinen Rueckgabewert selbst
# und mündet im Zweifel in ein stilles Ende.

# Sekunden, die eine einzelne Netzoperation hoechstens dauern darf. Zwei
# Netzoperationen im schlechtesten Fall (ls-remote + fetch), also ist das
# Worst-Case-Budget das Doppelte.
CLONE_CHECK_TIMEOUT="${CLAUDE_CLONE_CHECK_TIMEOUT:-5}"

# git darf nicht nach Zugangsdaten fragen: ein Prompt ohne Terminal ist genau
# das Haengen, das dieser Hook vermeiden soll. `timeout` faengt das zwar ab,
# aber erst nach Ablauf der vollen Frist.
export GIT_TERMINAL_PROMPT=0
export GIT_ASKPASS=true
export SSH_ASKPASS=true
export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -o BatchMode=yes -o ConnectTimeout=3}"

# `timeout --kill-after`: ein git, das SIGTERM ignoriert (haengender
# TLS-Handshake), bekommt danach SIGKILL. Ohne das laeuft die Frist ins Leere.
#
# `--kill-after` ist allerdings GNU-coreutils. Ein `timeout` ohne dieses Flag
# wuerde bei jedem Aufruf am Argument scheitern — das fetch schluege immer
# fehl, und der Hook waere dauerhaft und lautlos wirkungslos. Genau diese
# Sorte Fehler (etwas geht still nie los und sieht dabei gesund aus) soll er
# ja gerade nicht selber haben. Also einmal probieren und sonst schlicht ohne.
if timeout --kill-after=2 1 true >/dev/null 2>&1; then
  _timeout_args=(--kill-after=2)
else
  _timeout_args=()
fi

run_with_timeout() {
  timeout "${_timeout_args[@]}" "$CLONE_CHECK_TIMEOUT" "$@"
}

check_clone_freshness() {
  # Im Projektverzeichnis arbeiten. Claude Code ruft Hooks zwar mit dem
  # Projektverzeichnis als cwd auf, aber wenn das je abweicht, soll der Hook
  # das richtige Repo pruefen statt still auszusteigen.
  [ -n "${CLAUDE_PROJECT_DIR:-}" ] && cd "$CLAUDE_PROJECT_DIR" 2>/dev/null

  command -v git >/dev/null 2>&1 || return 0
  # Ohne `timeout` gibt es keine belastbare Obergrenze fuer das fetch. Dann
  # lieber gar nicht pruefen als eine Session riskieren, die am Start haengt.
  command -v timeout >/dev/null 2>&1 || return 0

  git rev-parse --git-dir >/dev/null 2>&1 || return 0

  local remote
  if git remote get-url origin >/dev/null 2>&1; then
    remote=origin
  else
    remote="$(git remote 2>/dev/null | head -n 1)"
  fi
  [ -n "$remote" ] || return 0

  # Standard-Branch ermitteln, NICHT annehmen. Mindestens ein Repo im
  # Portfolio heisst seinen Standard-Branch `master`; die Annahme `main` hat
  # dort schon einmal einen Branch 15 Commits alt werden lassen, ohne dass
  # etwas gemeldet haette.
  #
  # Erst lokal (refs/remotes/<remote>/HEAD, beim Klonen gesetzt, kostet kein
  # Netz), dann als Rueckfall ls-remote.
  local branch
  branch="$(git symbolic-ref --quiet --short "refs/remotes/$remote/HEAD" 2>/dev/null)"
  branch="${branch#"$remote/"}"

  if [ -z "$branch" ]; then
    branch="$(run_with_timeout git ls-remote --symref "$remote" HEAD 2>/dev/null \
      | sed -n 's|^ref: refs/heads/\([^[:space:]]*\).*|\1|p' | head -n 1)"
  fi

  # Leerer Branch-Name: still aufhoeren. Ein `git fetch <remote>` ohne
  # Branch-Argument wuerde hier den Remote-HEAD holen und mit Status 0 enden —
  # der Hook meldete dann «alles aktuell», ohne das geprueft zu haben.
  [ -n "$branch" ] || return 0

  run_with_timeout git fetch --quiet "$remote" "$branch" >/dev/null 2>&1 || return 0

  # Gemeinsamer Vorfahre noetig, sonst ist die Zahl bedeutungslos: bei
  # unverwandten Historien und bei einem flachen Klon, dessen Grenze oberhalb
  # von HEAD liegt, zaehlt HEAD..FETCH_HEAD die ganze geholte Historie.
  #
  # Der Klon ist hier ueblicherweise flach — Claude Code auf dem Web klont so.
  # Ein pauschales «flach -> nicht pruefen» haette den Hook also genau in der
  # Umgebung stillgelegt, fuer die er gedacht ist (und tat es in der ersten
  # Fassung; die Gegenprobe hat es gezeigt). Entscheidend ist nicht, ob der
  # Klon flach ist, sondern ob die Grenze unterhalb des Vergleichspunkts
  # liegt — und genau das beantwortet merge-base.
  git merge-base HEAD FETCH_HEAD >/dev/null 2>&1 || return 0

  local behind
  behind="$(git rev-list --count HEAD..FETCH_HEAD 2>/dev/null)"
  # Nicht-numerisch oder leer faellt hier raus.
  case "$behind" in
    '' | *[!0-9]*) return 0 ;;
    0) return 0 ;;
  esac

  local commit_word="Commits"
  [ "$behind" = "1" ] && commit_word="Commit"

  printf '%s\n' \
    "⚠️  Der ausgecheckte Stand liegt $behind $commit_word hinter $remote/$branch." \
    "" \
    "Vor der Arbeit aktualisieren:" \
    "    git fetch $remote $branch && git merge FETCH_HEAD" \
    "" \
    "Grund: Ein veralteter Klon erzeugt eine rote CI, deren Ursache nicht im" \
    "Diff steht — die fehlenden Commits sind typischerweise genau die, die das" \
    "Gate eingefuehrt haben, an dem der Branch scheitert."
}

check_clone_freshness || true

# Unbedingt 0. Der Rueckgabewert von check_clone_freshness darf hier unter
# keinen Umstaenden durchschlagen.
exit 0
