"""Hemmeligheter fra fil (SECRETS_DIR) – foretrukket over env."""

import os
import tempfile
import unittest

from app.config import from_env


class SecretFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.secrets = os.path.join(self.tmp.name, "secrets")
        os.makedirs(self.secrets)
        with open(os.path.join(self.secrets, "session_secret"), "w") as f:
            f.write("file-session-secret-0123456789abcdef\n")
        with open(os.path.join(self.secrets, "pseudonym_salt"), "w") as f:
            f.write("file-pseudonym-salt-0123456789\n")
        with open(os.path.join(self.secrets, "admin_password_hash"), "w") as f:
            f.write("pbkdf2_sha256$260000$c2FsdA$aGFzaA==\n")
        with open(os.path.join(self.secrets, "llm_api_key"), "w") as f:
            f.write("scw-test-key\n")

    def tearDown(self):
        self.tmp.cleanup()

    def _env(self, **overrides):
        env = {
            "APP_ENV": "test",
            "SECRETS_DIR": self.secrets,
            "ADMIN_USER": "admin",
            "SESSION_SECRET": "env-value-should-lose-0123456789",
            "PSEUDONYM_SALT": "env-value-should-lose-0123456789",
            "ADMIN_PASSWORD_HASH": "pbkdf2_sha256$1$ZW52$aGFzaA==",
            "LLM_API_KEY": "env-key-should-lose",
        }
        env.update(overrides)
        return env

    def test_file_wins_over_env(self):
        config = from_env(self._env())
        self.assertEqual(config.session_secret, "file-session-secret-0123456789abcdef")
        self.assertEqual(config.pseudonym_salt, "file-pseudonym-salt-0123456789")
        self.assertEqual(config.llm_api_key, "scw-test-key")

    def test_missing_file_falls_back_to_env(self):
        os.remove(os.path.join(self.secrets, "llm_api_key"))
        config = from_env(self._env())
        self.assertEqual(config.llm_api_key, "env-key-should-lose")

    def test_explicit_file_override(self):
        path = os.path.join(self.tmp.name, "explicit_key")
        with open(path, "w") as f:
            f.write("explicit-key\n")
        config = from_env(self._env(LLM_API_KEY_FILE=path))
        self.assertEqual(config.llm_api_key, "explicit-key")


    def test_explicit_missing_file_fails_closed(self):
        from app.config import ConfigError
        with self.assertRaises(ConfigError):
            from_env(self._env(LLM_API_KEY_FILE=os.path.join(self.tmp.name, "missing")))
