"""WCAG 2.2 AA-basis: språk, landemerker, skip-lenke, overskrifter, etiketter."""

import tempfile
import unittest

from tests.helpers import RunningApp


class PublicA11yTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = RunningApp(self.tmp.name)
        self.app.__enter__()

    def tearDown(self):
        self.app.__exit__()
        self.tmp.cleanup()

    def test_all_public_pages_have_language_and_landmarks(self):
        for path in ("/", "/slik-fungerer-det", "/om", "/personvern", "/data", "/kontakt", "/status"):
            page = self.app.get(path)
            self.assertEqual(page.status, 200, path)
            self.assertIn('lang="no"', page.text, path)
            self.assertIn("<main", page.text, path)
            self.assertIn('href="#main"', page.text, path)  # skip-lenke
            self.assertEqual(page.text.count("<h1"), 1, path)

    def test_admin_login_is_labelled(self):
        page = self.app.get("/admin")
        self.assertEqual(page.status, 200)
        self.assertIn('name="username"', page.text)
        self.assertIn('name="password"', page.text)
        self.assertIn("Logg inn", page.text)
