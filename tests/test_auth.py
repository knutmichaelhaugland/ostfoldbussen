"""Enhetstester: passordhash, session-cookie og CSRF."""

import time
import unittest

from app import auth


class PasswordTests(unittest.TestCase):
    def test_hash_and_verify(self):
        stored = auth.hash_password("riktig passord", iterations=1000)
        self.assertTrue(stored.startswith("pbkdf2_sha256$1000$"))
        self.assertTrue(auth.verify_password("riktig passord", stored))
        self.assertFalse(auth.verify_password("feil passord", stored))

    def test_hash_is_salted(self):
        first = auth.hash_password("x", iterations=1000)
        second = auth.hash_password("x", iterations=1000)
        self.assertNotEqual(first, second)

    def test_malformed_hash_fails(self):
        for stored in ("", "plaintext", "pbkdf2_sha256$abc$x$y", "scrypt$1$a$b"):
            self.assertFalse(auth.verify_password("x", stored))

    def test_extreme_pbkdf2_iterations_fail_closed(self):
        stored = auth.hash_password("x", iterations=1000)
        for iterations in ("0", "-1", "2000001", "999999999999"):
            bad = stored.replace("$1000$", f"${iterations}$", 1)
            self.assertFalse(auth.verify_password("x", bad), iterations)
        self.assertTrue(auth.verify_password("x", stored))


class SessionTests(unittest.TestCase):
    secret = "unit-test-session-secret-0123456789abcdef"

    def test_roundtrip(self):
        token = auth.sign_session(self.secret, "admin", ttl_s=60)
        self.assertEqual(auth.verify_session(self.secret, token), "admin")

    def test_tampered_payload_rejected(self):
        token = auth.sign_session(self.secret, "admin", ttl_s=60)
        body, signature = token.split(".", 1)
        self.assertIsNone(auth.verify_session(self.secret, body + "x." + signature))
        flipped = ("A" if signature[0] != "A" else "B") + signature[1:]
        self.assertNotEqual(flipped, signature)
        self.assertIsNone(auth.verify_session(self.secret, body + "." + flipped))

    def test_wrong_secret_rejected(self):
        token = auth.sign_session(self.secret, "admin", ttl_s=60)
        self.assertIsNone(auth.verify_session("annen-hemmelighet-0123456789abcdef", token))

    def test_expired_rejected(self):
        token = auth.sign_session(self.secret, "admin", ttl_s=10, now=time.time() - 100)
        self.assertIsNone(auth.verify_session(self.secret, token))

    def test_garbage_rejected(self):
        for token in ("", "abc", "a.b.c", "abc.def", "é.signature"):
            self.assertIsNone(auth.verify_session(self.secret, token))


class CsrfTests(unittest.TestCase):
    secret = "unit-test-csrf-secret-0123456789abcdef"

    def test_roundtrip(self):
        token = auth.sign_csrf(self.secret)
        self.assertTrue(auth.verify_csrf(self.secret, token))

    def test_tampered(self):
        token = auth.sign_csrf(self.secret)
        self.assertFalse(auth.verify_csrf(self.secret, token + "x"))
        self.assertFalse(auth.verify_csrf(self.secret, ""))

    def test_expired(self):
        token = auth.sign_csrf(self.secret, now=time.time() - 7200)
        self.assertFalse(auth.verify_csrf(self.secret, token, max_age_s=3600))


if __name__ == "__main__":
    unittest.main()
