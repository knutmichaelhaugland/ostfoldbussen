"""Autentisering: PBKDF2-passordhash, HMAC-signert session-cookie og CSRF-token.

Ren stdlib. Constant-time sammenligning med hmac.compare_digest.
Ingen hemmeligheter logges eller sendes til klienten utover den signerte cookien.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

PBKDF2_ITERATIONS = 260_000
PBKDF2_MIN_ITERATIONS = 1
PBKDF2_MAX_ITERATIONS = 2_000_000
PBKDF2_PREFIX = "pbkdf2_sha256"
SESSION_MAX_AGE_S = 8 * 3600


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS, salt: bytes | None = None) -> str:
    if not password:
        raise ValueError("passord kan ikke være tomt")
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{PBKDF2_PREFIX}${iterations}${_b64url_encode(salt)}${_b64url_encode(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        prefix, iterations_raw, salt_raw, digest_raw = stored.split("$", 3)
    except (ValueError, AttributeError):
        return False
    if prefix != PBKDF2_PREFIX:
        return False
    try:
        iterations = int(iterations_raw)
        if not (PBKDF2_MIN_ITERATIONS <= iterations <= PBKDF2_MAX_ITERATIONS):
            return False
        salt = _b64url_decode(salt_raw)
        expected = _b64url_decode(digest_raw)
    except (ValueError, TypeError):
        return False
    # Avvis urimelige lagrede verdier før den dyre PBKDF2-beregningen.
    if not salt or not expected or len(salt) > 64 or len(expected) > 64:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt, iterations)
    return hmac.compare_digest(candidate, expected)


def _sign(secret: str, payload: bytes) -> str:
    return _b64url_encode(hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest())


def sign_session(secret: str, user: str, *, ttl_s: int = SESSION_MAX_AGE_S, now: float | None = None) -> str:
    now = time.time() if now is None else now
    payload = json.dumps(
        {"u": user, "iat": int(now), "exp": int(now) + int(ttl_s)}, separators=(",", ":")
    ).encode("utf-8")
    body = _b64url_encode(payload)
    return f"{body}.{_sign(secret, body.encode('ascii'))}"


def verify_session(secret: str, token: str, *, now: float | None = None) -> str | None:
    """Returner brukernavn ved gyldig og ikke utløpt token, ellers None."""
    if not token or "." not in token:
        return None
    body, signature = token.rsplit(".", 1)
    try:
        expected = _sign(secret, body.encode("ascii"))
    except (UnicodeEncodeError, ValueError, TypeError):
        return None
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(_b64url_decode(body))
        if not isinstance(payload, dict):
            return None
        expires = int(payload.get("exp", 0))
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    now = time.time() if now is None else now
    if expires <= int(now):
        return None
    user = payload.get("u")
    return str(user) if user else None


def sign_csrf(secret: str, *, now: float | None = None) -> str:
    now = int(time.time() if now is None else now)
    value = str(now)
    return f"{value}.{_b64url_encode(hmac.new(secret.encode(), value.encode(), hashlib.sha256).digest())}"


def verify_csrf(secret: str, token: str, *, max_age_s: int = 3600, now: float | None = None) -> bool:
    if not token or "." not in token:
        return False
    value, signature = token.split(".", 1)
    expected = _b64url_encode(hmac.new(secret.encode(), value.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        issued = int(value)
    except ValueError:
        return False
    now_i = int(time.time() if now is None else now)
    return 0 <= now_i - issued <= max_age_s
