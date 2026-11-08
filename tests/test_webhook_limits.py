"""Regresjon for leverandørspesifikke webhook-grenser."""

import tempfile
import unittest

from app import server as server_module
from tests.helpers import RunningApp


class WebhookBodyLimitTests(unittest.TestCase):
    def test_inmobile_body_limit_is_32_kib(self):
        overrides = {"inmobile_webhook_enabled": True}
        with tempfile.TemporaryDirectory() as tmp, RunningApp(tmp, overrides) as app:
            body = b"x" * (server_module.INMOBILE_WEBHOOK_MAX_BODY + 1)
            response = app.request("POST", "/api/webhooks/inmobile", body=body,
                                   headers={"Content-Type": "application/json"})
        self.assertEqual(response.status, 413)

