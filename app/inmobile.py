"""inMobile webhook: signaturverifisering og tolerant payload-uttrekk.

Signaturen er ECDSA P-256 / SHA-256 over:
    X-Inmobile-Request-Id + X-Inmobile-Request-Timestamp + rå body
Public key er base64-kodet DER (SPKI). Verifisering gjøres med openssl CLI.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from urllib.parse import parse_qs

MAX_SKEW_S = 300
MAX_REQUEST_ID_LEN = 256
MAX_KEY_ID_LEN = 128
MAX_SIGNATURE_HEADER_LEN = 8192
MESSAGE_KEYS = ("message", "text", "body", "content", "smstext", "messagetext")
SENDER_KEYS = ("sender", "from", "msisdn", "phonenumber", "phone", "mobile",
               "originator", "fromnumber", "number")


def _norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _walk(value, out: dict) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            out.setdefault(_norm_key(key), item)
            _walk(item, out)
    elif isinstance(value, list):
        for item in value:
            _walk(item, out)


def extract_sms(body: bytes, content_type: str) -> dict:
    """Returner {message, sender, fields}. Tomme felt hvis ukjent format."""
    fields: dict = {}
    text = body.decode("utf-8", "replace")
    if "json" in (content_type or "") or text.lstrip().startswith(("{", "[")):
        try:
            parsed = json.loads(text)
            _walk(parsed, fields)
        except json.JSONDecodeError:
            pass
    if not fields:
        try:
            for key, values in parse_qs(text).items():
                fields[_norm_key(key)] = values[0] if values else ""
        except Exception:
            pass
    message = ""
    sender = ""
    for candidate in MESSAGE_KEYS:
        value = fields.get(candidate)
        if isinstance(value, str) and value.strip():
            message = value.strip()
            break
    for candidate in SENDER_KEYS:
        value = fields.get(candidate)
        if isinstance(value, str) and value.strip():
            sender = value.strip()
            break
    return {
        "message": message,
        "sender": sender,
        "fields": sorted(fields.keys()),
    }


def verify_signature(headers: dict, raw_body: bytes, key_id: str,
                     public_key_b64: str, now: datetime | None = None) -> tuple[bool, str]:
    lower = {str(k).lower(): v for k, v in headers.items()}
    version = lower.get("x-inmobile-signature-version", "")
    timestamp_text = lower.get("x-inmobile-request-timestamp", "")
    request_id = lower.get("x-inmobile-request-id", "")
    signature_b64 = lower.get("x-inmobile-signature", "")
    request_key_id = lower.get("x-inmobile-signature-keyid", "")

    if not all((version, timestamp_text, request_id, signature_b64, request_key_id)):
        return False, "missing_signature_headers"
    if (len(request_id) > MAX_REQUEST_ID_LEN
            or len(request_key_id) > MAX_KEY_ID_LEN
            or len(signature_b64) > MAX_SIGNATURE_HEADER_LEN):
        return False, "header_too_long"
    if version != "1":
        return False, "unsupported_signature_version"
    if key_id and request_key_id.lower() != key_id.strip().lower():
        return False, "unknown_signature_key"
    try:
        timestamp = datetime.strptime(timestamp_text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return False, "invalid_timestamp"
    now = now or datetime.now(timezone.utc)
    if abs((now - timestamp).total_seconds()) > MAX_SKEW_S:
        return False, "stale_timestamp"

    payload = request_id.encode() + timestamp_text.encode() + raw_body
    pem = ("-----BEGIN PUBLIC KEY-----\n" + public_key_b64.strip() + "\n"
           "-----END PUBLIC KEY-----\n")
    try:
        signature = __import__("base64").b64decode(signature_b64, validate=True)
    except Exception:
        return False, "invalid_signature_encoding"

    with tempfile.TemporaryDirectory() as tmp:
        pub_path = f"{tmp}/pub.pem"
        sig_path = f"{tmp}/sig.bin"
        data_path = f"{tmp}/payload.bin"
        with open(pub_path, "w", encoding="ascii") as f:
            f.write(pem)
        with open(sig_path, "wb") as f:
            f.write(signature)
        with open(data_path, "wb") as f:
            f.write(payload)
        try:
            result = subprocess.run(
                ["openssl", "dgst", "-sha256", "-verify", pub_path,
                 "-signature", sig_path, data_path],
                capture_output=True, text=True, timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return False, "verify_unavailable"
    if result.returncode != 0:
        return False, "invalid_signature"
    return True, "valid"
