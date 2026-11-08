#!/usr/bin/env python3
"""Regresjonskontroll: alle installasjonsblokker må generere secrets før chown."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FENCE = re.compile(r"```(?:bash|sh)?\s*\n(.*?)```", re.DOTALL)


def main() -> int:
    errors: list[str] = []
    checked = 0
    for path in sorted(ROOT.rglob("*.md")):
        if ".git" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if "|| true" in text:
            errors.append(f"{path.relative_to(ROOT)}: bruker '|| true' i sikkerhetsoppsett")
        for block in FENCE.findall(text):
            if "sudo chown -R 10001" not in block:
                continue
            checked += 1
            auth = block.find("python3 -m app auth-hash")
            if auth == -1:
                auth = block.find("python3 -c \"import secrets")
            chown = block.find("sudo chown -R 10001")
            chmod_secrets = block.find("chmod 600 state/secrets/*")
            chmod_env = block.find("chmod 600 .env")
            if auth == -1 or auth > chown:
                errors.append(
                    f"{path.relative_to(ROOT)}: chown 10001 før secret-generering"
                )
            if chmod_secrets == -1 or chmod_secrets > chown:
                errors.append(
                    f"{path.relative_to(ROOT)}: chown 10001 før chmod 600 secrets"
                )
            if "cp .env.example .env" in block and chmod_env == -1:
                errors.append(f"{path.relative_to(ROOT)}: mangler chmod 600 .env")
    if errors:
        print("QUICKSTART-PERMISJON FEIL:")
        for error in errors:
            print(f"  {error}")
        return 1
    print(f"OK: {checked} installasjonsblokker genererer secrets før uid 10001-eierskap")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
