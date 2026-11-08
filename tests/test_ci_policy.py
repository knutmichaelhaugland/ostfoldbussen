"""Release- og CI-policy: pinning, tidsgrenser, minsteprivilegium og skanning."""

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


class CiPolicyTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_all_external_actions_are_full_sha_pinned(self):
        uses = re.findall(r"^\s*-?\s*uses:\s*([^\s#]+)", self.text, re.MULTILINE)
        self.assertGreaterEqual(len(uses), 4)
        for action in uses:
            if action.startswith("./"):
                continue
            self.assertRegex(action, r"^[^@]+@[0-9a-f]{40}$", action)

    def test_all_jobs_have_timeouts(self):
        lines = self.text.splitlines()
        jobs_start = next(i for i, line in enumerate(lines) if line.strip() == "jobs:")
        lines = lines[jobs_start + 1:]
        job_keys = [i for i, line in enumerate(lines) if re.match(r"^  [a-zA-Z0-9_-]+:$", line)]
        self.assertGreaterEqual(len(job_keys), 4)
        for start in job_keys:
            end = next((i for i in job_keys if i > start), len(lines))
            self.assertTrue(any("timeout-minutes:" in line for line in lines[start:end]))

    def test_concurrency_cancels_only_pull_requests(self):
        self.assertIn("concurrency:", self.text)
        self.assertIn("cancel-in-progress: ${{ github.event_name == 'pull_request' }}", self.text)

    def test_permissions_are_read_only(self):
        self.assertIn("permissions:\n  contents: read", self.text)
        self.assertNotRegex(self.text, r"contents:\s*write")

    def test_external_pr_docker_build_is_isolated(self):
        self.assertIn("runs-on: ubuntu-latest", self.text)
        self.assertNotIn("self-hosted", self.text)
        docker_section = self.text.split("docker-build:", 1)[1].split("\n  secret-scan:", 1)[0]
        self.assertNotIn("secrets.", docker_section)

    def test_gitleaks_is_pinned_and_primary(self):
        self.assertIn("gitleaks/gitleaks-action@ff98106e4c7b2bc287b24eaf42907196329070c7", self.text)
        self.assertIn("Gitleaks (hovedkontroll", self.text)
        self.assertIn("fetch-depth: 0", self.text)

    def test_compose_app_binds_container_interface(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("HOST: 0.0.0.0", compose)
        self.assertIn('127.0.0.1:8000:8000', compose)

    def test_dependabot_tracks_actions_and_docker(self):
        dependabot = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        self.assertIn('package-ecosystem: "github-actions"', dependabot)
        self.assertIn('package-ecosystem: "docker"', dependabot)

    def test_docker_images_are_digest_pinned(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertRegex(dockerfile, r'PYTHON_IMAGE=.*@sha256:[0-9a-f]{64}')
        self.assertNotIn(":latest", dockerfile)
        for name in ("docker-compose.yml", "docker-compose.public.yml"):
            compose = (ROOT / name).read_text(encoding="utf-8")
            self.assertRegex(compose, r"caddy:[^\s]+@sha256:[0-9a-f]{64}")
            self.assertNotIn(":latest", compose)


class SupplementalSecretScanTests(unittest.TestCase):
    def test_scan_fails_on_synthetic_secret_and_passes_clean_tree(self):
        tool = ROOT / "tools" / "project_secret_scan.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Bygges av biter slik at testkilden ikke selv ser ut som en lekkasje
            # for Gitleaks; det syntetiske innholdet havner bare i temp-mappen.
            name = "OPENAI_API_" + "KEY"
            value = "sk-" + "syntetisk-hemmelighet-" + "1234567890"
            (root / ".env").write_text(f"{name}={value}\n", encoding="utf-8")
            failed = subprocess.run([sys.executable, str(tool), str(root)],
                                    capture_output=True, text=True)
            self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
            (root / ".env").unlink()
            clean = subprocess.run([sys.executable, str(tool), str(root)],
                                   capture_output=True, text=True)
            self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)
