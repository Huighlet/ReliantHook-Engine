"""
ReliantHook-Engine Cryptographic Signatures & Timestamp Replay Protection.
Implements HMAC-SHA256 request signing with strict constant-time verification
and time-drift tolerance matching top-tier payment infrastructure standards.
"""

from __future__ import annotations

import hmac
import hashlib
import time
from typing import Optional


class WebhookSecurityError(Exception):
    """Raised when webhook signature verification fails or timestamps are expired."""


def sign_payload(
    payload_body: str | bytes,
    secret_key: str | bytes,
    timestamp: Optional[int] = None,
) -> str:
    """
    Generate standard HMAC-SHA256 signature header:
      Header Format: 't={timestamp},v1={hex_digest}'
      Signed Message: '{timestamp}.{payload_body}'
    """
    ts = timestamp if timestamp is not None else int(time.time())
    body_str = payload_body.decode("utf-8") if isinstance(payload_body, bytes) else payload_body
    secret_bytes = secret_key.encode("utf-8") if isinstance(secret_key, str) else secret_key

    signed_payload = f"{ts}.{body_str}".encode("utf-8")
    signature = hmac.new(secret_bytes, signed_payload, hashlib.sha256).hexdigest()

    return f"t={ts},v1={signature}"


def verify_signature(
    payload_body: str | bytes,
    signature_header: str,
    secret_key: str | bytes,
    tolerance_seconds: int = 300,
) -> bool:
    """
    Verify incoming webhook HMAC-SHA256 signature against replay attacks and tampering.

    Raises:
      - WebhookSecurityError: If timestamp is invalid/expired or signature does not match.
    """
    body_str = payload_body.decode("utf-8") if isinstance(payload_body, bytes) else payload_body
    secret_bytes = secret_key.encode("utf-8") if isinstance(secret_key, str) else secret_key

    # Parse header: 't=1700000000,v1=abcdef...'
    parts = signature_header.strip().split(",")
    header_data: dict[str, str] = {}
    for part in parts:
        if "=" in part:
            k, v = part.split("=", 1)
            header_data[k.strip()] = v.strip()

    if "t" not in header_data or "v1" not in header_data:
        raise WebhookSecurityError(f"Malformed signature header: '{signature_header}', expected 't=...,v1=...'")

    try:
        ts = int(header_data["t"])
    except ValueError:
        raise WebhookSecurityError(f"Invalid timestamp in header: '{header_data['t']}'")

    current_time = int(time.time())
    if tolerance_seconds > 0 and abs(current_time - ts) > tolerance_seconds:
        raise WebhookSecurityError(
            f"Timestamp out of tolerance bounds: payload timestamp {ts} differs from "
            f"current system time {current_time} by {abs(current_time - ts)}s (max: {tolerance_seconds}s)"
        )

    # Recompute expected signature
    signed_payload = f"{ts}.{body_str}".encode("utf-8")
    expected_sig = hmac.new(secret_bytes, signed_payload, hashlib.sha256).hexdigest()

    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(expected_sig, header_data["v1"]):
        raise WebhookSecurityError("Signature mismatch: payload content or secret key is invalid.")

    return True
