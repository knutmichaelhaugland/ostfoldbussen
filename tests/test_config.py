"""Enhetstester: konfigurasjon og fail-closed-validering."""

import os
import tempfile
import unittest

from app import config as config_module
from app.auth import hash_password
from tests.helpers import make_config

TEST_SESSION_SECRET = "secret-" + "0123456789abcdefghijklmnop"


class ConfigTests(unittest.TestCase):
    def test_test_config_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            self.assertEqual(config.entur_client_name, "ostfoldbussen-selfhosted")
            self.assertFalse(config.inmobile_outbound_enabled)
            self.assertFalse(config.llm_enabled)
            self.assertEqual(config.effective_min_transfer_s, 120)

    def test_missing_pseudonym_salt_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp, validate=False, pseudonym_salt="")
            with self.assertRaises(config_module.ConfigError):
                config.validate()

    def test_short_session_secret_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp, validate=False, session_secret="kort")
            with self.assertRaises(config_module.ConfigError):
                config.validate()

    def test_llm_enabled_without_key_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp, validate=False, llm_enabled=True)
            with self.assertRaises(config_module.ConfigError):
                config.validate()

    def test_short_message_hash_key_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp, validate=False, message_hash_key="kort")
            with self.assertRaises(config_module.ConfigError):
                config.validate()

    def test_invalid_scope_policy_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp, validate=False, scope_policy="anything")
            with self.assertRaises(config_module.ConfigError):
                config.validate()

    def test_env_parsing(self):
        env = {
            "PSEUDONYM_SALT": "salt-0123456789abcdef",
            "SESSION_SECRET": TEST_SESSION_SECRET,
            "ADMIN_USER": "admin",
            "ADMIN_PASSWORD_HASH": hash_password("x", iterations=1000),
            "INMOBILE_OUTBOUND_ENABLED": "false",
            "TRANSFER_SLACK_S": "480",
            "MAX_WALK_M": "500",
            "SCOPE_POLICY": "require_in_scope",
            "PORT": "9000",
        }
        config = config_module.from_env(env)
        self.assertEqual(config.transfer_slack_s, 480)
        self.assertEqual(config.max_walk_m, 500.0)
        self.assertEqual(config.scope_policy, "require_in_scope")
        self.assertEqual(config.port, 9000)
        self.assertFalse(config.inmobile_outbound_enabled)

    def test_bad_bool_rejected(self):
        env = {
            "PSEUDONYM_SALT": "salt-0123456789abcdef",
            "SESSION_SECRET": TEST_SESSION_SECRET,
            "ADMIN_USER": "admin",
            "ADMIN_PASSWORD_HASH": hash_password("x", iterations=1000),
            "INMOBILE_OUTBOUND_ENABLED": "kanskje",
        }
        with self.assertRaises(config_module.ConfigError):
            config_module.from_env(env)

    def test_env_file_does_not_override_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "app.env")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("A=fil\nB=fil\n")
            env = {"A": "miljo"}
            config_module.load_env_file(path, env)
            self.assertEqual(env["A"], "miljo")
            self.assertEqual(env["B"], "fil")

    def test_thresholds_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp, transfer_slack_s=300, minimum_transfer_s=600, max_walk_m=250)
            thresholds = config.thresholds()
            self.assertEqual(thresholds.transfer_slack_s, 300)
            self.assertEqual(thresholds.minimum_transfer_s, 600)
            self.assertEqual(thresholds.max_walk_m, 250)


if __name__ == "__main__":
    unittest.main()


class ProductionSafetyTests(unittest.TestCase):
    def test_production_requires_secure_cookie(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp, validate=False, app_env="production", cookie_secure=False)
            with self.assertRaises(config_module.ConfigError):
                config.validate()

    def test_production_inmobile_requires_key_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(
                tmp, validate=False, app_env="production", cookie_secure=True,
                inmobile_webhook_enabled=True,
            )
            with self.assertRaises(config_module.ConfigError):
                config.validate()

    def test_production_rejects_plain_http_llm(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(
                tmp, validate=False, app_env="production", cookie_secure=True,
                llm_enabled=True, llm_base_url="http://llm.example/v1",
                llm_model="m", llm_api_key="k",
            )
            with self.assertRaises(config_module.ConfigError):
                config.validate()

    def test_outbound_inmobile_requires_positive_daily_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(
                tmp, validate=False, inmobile_outbound_enabled=True,
                inmobile_api_key="k", inmobile_from="4700000000",
                daily_sms_limit=0,
            )
            with self.assertRaises(config_module.ConfigError):
                config.validate()


class SmtpProductionTransportTests(unittest.TestCase):
    def _config(self, tmp, **overrides):
        values = dict(
            app_env="production", cookie_secure=True,
            smtp_host="smtp.example.no", smtp_port=465,
            smtp_starttls=False,
        )
        values.update(overrides)
        return make_config(tmp, validate=False, **values)

    def test_port_465_without_starttls_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._config(tmp).validate()

    def test_port_465_with_starttls_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._config(tmp, smtp_starttls=True).validate()

    def test_port_587_without_starttls_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(config_module.ConfigError):
                self._config(tmp, smtp_port=587, smtp_starttls=False).validate()

    def test_port_587_with_starttls_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._config(tmp, smtp_port=587, smtp_starttls=True).validate()

    def test_other_port_without_starttls_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(config_module.ConfigError):
                self._config(tmp, smtp_port=25, smtp_starttls=False).validate()
