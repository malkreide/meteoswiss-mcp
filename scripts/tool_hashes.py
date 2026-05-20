#!/usr/bin/env python3
"""Erzeugt einen reproduzierbaren Hash-Snapshot aller Tool-Definitionen.

Verwendung:
    python scripts/tool_hashes.py [--write]

Ohne `--write` wird nur das JSON nach stdout geschrieben (für CI-Diff-Checks).
Mit `--write` wird `tool-hashes.json` im Repo-Root überschrieben.

Hintergrund (SEC-022): bei Tool-Definition-Änderungen wird ein neuer Hash
fällig — der Maintainer signalisiert damit explizit, dass ein Re-Approval
beim Client nötig ist (Rug-Pull-Schutz).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from meteoswiss_mcp.server import mcp  # noqa: E402


def _hash_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


async def collect() -> dict[str, dict[str, str]]:
    """Hash über die rug-pull-relevanten Tool-Identitätsfelder.

    Bewusst aus dem Hash ausgenommen sind `annotations` — sie sind eher
    Hint-Metadaten und ihre Pydantic-Serialisierung schwankt zwischen
    Pydantic-Versionen (CI auf Python 3.13 fand abweichende Dumps).
    """
    tools = await mcp.list_tools()
    snapshot: dict[str, dict[str, str]] = {}
    for t in tools:
        canonical = json.dumps(
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.inputSchema,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        snapshot[t.name] = {
            "hash": _hash_text(canonical),
            "title": (t.annotations.title if t.annotations else "") or "",
        }
    return snapshot


def main() -> int:
    import asyncio

    snapshot = asyncio.run(collect())
    rendered = json.dumps(
        {"namespace": "meteoswiss_mcp", "tools": snapshot}, indent=2, ensure_ascii=False
    )
    if "--write" in sys.argv:
        (ROOT / "tool-hashes.json").write_text(rendered + "\n")
        print(f"wrote {ROOT / 'tool-hashes.json'} ({len(snapshot)} tools)")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
