#!/usr/bin/env python3
"""Prüft ohne Seiteneffekt, ob ``tool-hashes.json`` noch aktuell ist (SEC-022).

Unterschied zu ``tool_hashes.py --write``: dieses Skript fasst die Arbeitskopie
nicht an. Ein Hook, der im Fehlerfall eine Datei umschreibt, hinterlässt eine
Änderung, die niemand gemacht hat — und die dann im nächsten ``git add -A``
mitfährt.

Der Hash hängt an der Pydantic-JSON-Schema-Serialisierung und damit an der
Python-Version; die CI prüft ihn deshalb nur auf der Produktions-Version (siehe
``ARG PYTHON_VERSION`` im Dockerfile). Auf einer anderen Version weicht er
verlässlich ab, ohne dass etwas kaputt wäre. Deshalb wird hier übersprungen
statt Alarm zu geben: ein Gate, das regelmässig falsch anschlägt, wird umgangen
und schützt danach gar nichts mehr.
"""

from __future__ import annotations

import difflib
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = REPO_ROOT / "tool-hashes.json"
GENERATOR = REPO_ROOT / "scripts" / "tool_hashes.py"
PINNED_PYTHON = (3, 13)


def main() -> int:
    have = sys.version_info[:2]
    if have != PINNED_PYTHON:
        print(
            f"übersprungen: der Hash ist Python-versionsabhängig, hier läuft "
            f"{have[0]}.{have[1]}, die CI prüft auf "
            f"{PINNED_PYTHON[0]}.{PINNED_PYTHON[1]}."
        )
        return 0

    result = subprocess.run([sys.executable, str(GENERATOR)], capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        print(f"{GENERATOR.name} konnte den Snapshot nicht erzeugen.", file=sys.stderr)
        return 1

    actual = result.stdout
    expected = SNAPSHOT.read_text(encoding="utf-8")
    if actual == expected:
        return 0

    diff = difflib.unified_diff(
        expected.splitlines(keepends=True),
        actual.splitlines(keepends=True),
        fromfile="tool-hashes.json (committed)",
        tofile="tool-hashes.json (aktuell)",
    )
    sys.stderr.writelines(diff)
    print(
        "\ntool-hashes.json ist veraltet. Nachziehen mit:\n"
        "    python3 scripts/tool_hashes.py --write",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
