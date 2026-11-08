"""Release-gate for Git-/Docker-hygiene.

Testene kjører mot den committede kandidaten i CI. De bruker Git, men ingen
tredjepartsavhengigheter. Hensikten er å gjøre det vanskelig å committe lokale
databaser, backupfiler, logger eller hemmeligheter ved et uhell.
"""
from __future__ import annotations

import io
import re
import subprocess
import tarfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GIT_MUST_IGNORE = (
    "state/lib/app.db",
    "state/lib/app.db-wal",
    "state/lib/app.db-shm",
    "state/backups/app-2026-11-08.db",
    "backups/app.db",
    "backup/app.db",
    "app.db",
    "data/app.db",
    "data/app.sqlite",
    "app.db-wal",
    "app.db-shm",
    "logs/app.log",
    "app.log",
    ".coverage",
    "coverage.xml",
    "htmlcov/index.html",
    ".pytest_cache/x",
    ".mypy_cache/x",
    "secrets.env",
    "app.crt",
    "app.p12",
    "app.pfx",
    "app.jks",
    "id_rsa",
    "id_ed25519",
    ".netrc",
    ".htpasswd",
    "credentials.json",
    "app.db.bak",
    "app.db-old.age",
)
DOCKER_MUST_MATCH = (
    "state",
    "backups",
    "secrets",
    "logs",
    "tmp",
    ".venv",
    "venv",
    "**/*.db",
    "**/*.db-wal",
    "**/*.db-shm",
    "**/*.sqlite",
    "**/*.sqlite3",
    "**/*.bak",
    "**/*.age",
    "**/*.enc",
    "**/*.gpg",
    "**/*.log",
    "**/*.pem",
    "**/*.key",
    "**/*.crt",
    "**/*.p12",
    "**/*.pfx",
    "**/*.jks",
    "secrets.env",
    "id_rsa",
    "id_ed25519",
    ".netrc",
    ".htpasswd",
    "credentials.json",
    ".coverage",
    "htmlcov",
    ".pytest_cache",
)
FORBIDDEN_TRACKED = re.compile(
    r"(^|/)(state|backups?|logs?|secrets?)/|"
    r"\.(db|db-wal|db-shm|db-journal|sqlite3?|sqlite-wal|sqlite-shm|"
    r"pem|key|crt|p12|pfx|jks|age|gpg|enc|bak|backup|log|pyo)$",
    re.I,
)


class RepoHygieneTests(unittest.TestCase):
    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True
        )

    def test_gitignore_protects_operational_data(self):
        for path in GIT_MUST_IGNORE:
            self.assertEqual(
                self.git("check-ignore", "--no-index", "-q", path).returncode,
                0,
                f".gitignore beskytter ikke {path}",
            )

    def test_env_example_stays_committable(self):
        self.assertNotEqual(
            self.git("check-ignore", "--no-index", "-q", ".env.example").returncode,
            0,
        )

    def test_dockerignore_has_depth_aware_patterns(self):
        patterns = {
            line.strip()
            for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        for pattern in DOCKER_MUST_MATCH:
            self.assertIn(pattern, patterns, f".dockerignore mangler {pattern}")

    def test_no_operational_files_tracked(self):
        tracked = self.git("ls-files").stdout.splitlines()
        bad = [path for path in tracked if FORBIDDEN_TRACKED.search(path)]
        self.assertEqual(bad, [])
        modes = self.git("ls-files", "-s").stdout.splitlines()
        self.assertFalse([line for line in modes if line.startswith("120000")],
                         "symlink er sporet")

    def test_no_oversized_tracked_files(self):
        paths = [p for p in self.git("ls-files").stdout.splitlines()
                 if (ROOT / p).is_file()]
        self.assertEqual([p for p in paths if (ROOT / p).stat().st_size > 1_048_576], [])

    def test_archive_equals_tracked_tree(self):
        result = subprocess.run(
            ["git", "archive", "--format=tar", "HEAD"],
            cwd=ROOT, capture_output=True, check=True,
        )
        names = sorted(
            member.name
            for member in tarfile.open(fileobj=io.BytesIO(result.stdout))
            if member.isfile()
        )
        self.assertEqual(names, sorted(self.git("ls-files").stdout.splitlines()))

    def test_hygiene_tool_is_tracked_and_wired(self):
        tracked = self.git("ls-files").stdout.splitlines()
        self.assertIn("tools/check_repo_hygiene.py", tracked)
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("check_repo_hygiene.py", ci)
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertNotIn("COPY . .", dockerfile)
        self.assertRegex(dockerfile, r"COPY (--from=\S+ )?app \./app")


if __name__ == "__main__":
    unittest.main()
