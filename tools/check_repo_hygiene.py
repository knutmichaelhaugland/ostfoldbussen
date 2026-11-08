#!/usr/bin/env python3
"""Maskinell kontroll av Git- og Docker-hygiene for RC-kandidaten."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_GIT_IGNORES = (
    "state/lib/app.db",
    "state/backups/app.db",
    "state/secrets/session_secret",
    "backups/app.db",
    "app.db",
    "app.db-wal",
    "app.db-shm",
    "data/app.sqlite",
    "logs/app.log",
    ".coverage",
    ".venv/lib/python.pyc",
    "cache/app.enc",
    ".env",
)
REQUIRED_DOCKER_PATTERNS = (
    "state", "backups", "secrets", "logs", "**/*.db", "**/*.db-wal",
    "**/*.db-shm", "**/*.sqlite", "**/*.sqlite3", "**/*.bak", "**/*.age",
    "**/*.enc", "**/*.gpg", "**/*.log", "**/*.pem", "**/*.key",
    "**/*.crt", "**/*.p12", "**/*.pfx", "**/*.jks", "secrets.env",
    "id_rsa", "id_ed25519", ".netrc", ".htpasswd", "credentials.json",
    ".coverage", "htmlcov", ".pytest_cache",
)


def git_ignored(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", path],
        cwd=ROOT, check=False,
    )
    return result.returncode == 0


def main() -> int:
    errors: list[str] = []
    for path in REQUIRED_GIT_IGNORES:
        if not git_ignored(path):
            errors.append(f".gitignore beskytter ikke: {path}")
    docker = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    patterns = [line.strip() for line in docker.splitlines()
                if line.strip() and not line.lstrip().startswith("#")]
    for pattern in REQUIRED_DOCKER_PATTERNS:
        if pattern not in patterns:
            errors.append(f".dockerignore mangler mønster: {pattern}")
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.splitlines()
    for path in tracked:
        if path.endswith((".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3",
                          ".enc", ".age", ".gpg", ".pem", ".key")):
            errors.append(f"sporet drifts-/hemmelighetsfil: {path}")
    if errors:
        print("REPO-HYGIENE FEIL:")
        for error in errors:
            print(f"  {error}")
        return 1
    print(f"OK: {len(REQUIRED_GIT_IGNORES)} Git-stier og "
          f"{len(REQUIRED_DOCKER_PATTERNS)} Docker-mønstre kontrollert")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
