import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class QuickstartPermissionTests(unittest.TestCase):
    def test_documented_order_is_safe(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_quickstart_permissions.py")],
            capture_output=True, text=True, cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
