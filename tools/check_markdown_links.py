#!/usr/bin/env python3
"""Kontroller lokale Markdown-lenker uten tredjepartsavhengigheter.

Eksterne URL-er, mailto og ankre sjekkes ikke. Kjøres fra repo-roten i CI.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    broken: list[tuple[str, str, str]] = []
    for md in sorted(ROOT.rglob("*.md")):
        if any(part in {".git", "state"} for part in md.parts):
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except OSError as exc:
            broken.append((str(md.relative_to(ROOT)), "", str(exc)))
            continue
        for match in LINK.finditer(text):
            raw = match.group(1).strip()
            if not raw or raw.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target = raw.split("#", 1)[0]
            if not target:
                continue
            resolved = (md.parent / target).resolve()
            try:
                resolved.relative_to(ROOT)
            except ValueError:
                broken.append((str(md.relative_to(ROOT)), raw, "utenfor repo"))
                continue
            if not resolved.exists():
                broken.append((str(md.relative_to(ROOT)), raw, "mangler"))
    if broken:
        print(f"FEIL: {len(broken)} ødelagte lokale Markdown-lenker")
        for source, target, reason in broken:
            print(f"  {source}: {target} ({reason})")
        return 1
    print("OK: alle lokale Markdown-lenker peker på eksisterende filer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
