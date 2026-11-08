"""Prosjektspesifikk, supplerende hemmelighetsskanning.

Gitleaks er hovedkontrollen. Denne skanningen fanger enkle, kjente mønstre i
kildetreet og er bevisst ikke markedsført som full historikkdekning.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SECRET_FILE_NAMES = {".env", "secrets.env"}
SECRET_SUFFIXES = {".pem", ".key"}
TEXT_PATHS = [".env", ".env.example", "secrets.env", "app", "deploy", "docs", "README.md"]
SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules"}

AWS_KEY = re.compile(r"AKIA[0-9A-Z]{16}")
PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
ASSIGNMENT = re.compile(
    r"(?i)\b(?:API[_-]?KEY|AUTH[_-]?TOKEN|ACCESS[_-]?KEY|PRIVATE[_-]?KEY|"
    r"CLIENT[_-]?SECRET|PASSWORD|SESSION[_-]?SECRET|PSEUDONYM[_-]?SALT)\b"
    r"\s*[=:]\s*[\"']?([A-Za-z0-9_./+=-]{12,})"
)


def _iter_files(root: Path):
    for name in TEXT_PATHS:
        path = root / name
        if path.is_file():
            yield path
        elif path.is_dir():
            for child in path.rglob("*"):
                if any(part in SKIP_DIRS for part in child.parts):
                    continue
                if child.is_file() and child.suffix in {".py", ".md", ".yml", ".yaml", ".env", ".txt", ".sh", ""}:
                    yield child


def scan(root: Path) -> list[str]:
    findings: list[str] = []
    for path in _iter_files(root):
        rel = path.relative_to(root)
        if path.name in SECRET_FILE_NAMES or path.suffix in SECRET_SUFFIXES:
            findings.append(f"{rel}: forbudt hemmelighetsfil")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            if AWS_KEY.search(line) or PRIVATE_KEY.search(line):
                findings.append(f"{rel}:{line_no}: nøkkelmønster")
                continue
            # Generiske env-assignments sjekkes bare i .env-filer; kode kan
            # inneholde variabelnavn uten å være en hemmelighet. Gitleaks dekker
            # kode og historikk.
            if path.name in {".env", ".env.example", "secrets.env"}:
                match = ASSIGNMENT.search(line)
                if match and "${{" not in line and "example" not in match.group(1).lower():
                    findings.append(f"{rel}:{line_no}: mulig fylt hemmelighet")
    return findings


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    root = Path(argv[0]) if argv else Path.cwd()
    findings = scan(root)
    if findings:
        print("FEIL: supplerende hemmelighetsskanning fant:")
        for finding in findings:
            print(f"  {finding}")
        return 1
    print("OK: supplerende hemmelighetsskanning (Gitleaks er hovedkontroll)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
