"""
Unit tests for HMAC-SHA256 signatures, timestamp tolerance, and anti-replay protection.
"""

import time
import pytest

from relianthook.crypto import WebhookSecurityError, sign_payload, verify_signature


def test_signature_roundtrip_valid():
    """Verify that a freshly signed payload passes verification."""
    secret = "whsec_super_secret_test_key_123"
    body = '{"event":"payment.settled","amount":5000}'

    sig_header = sign_payload(body, secret)
    assert sig_header.startswith("t=")
    assert ",v1=" in sig_header

    assert verify_signature(body, sig_header, secret, tolerance_seconds=300) is True


def test_signature_tampered_payload_rejected():
    """Verify that altering even 1 character in the body causes signature rejection."""
    secret = "whsec_super_secret_test_key_123"
    body = '{"event":"payment.settled","amount":5000}'
    sig_header = sign_payload(body, secret)

    # Attacker alters amount from 5000 to 9000
    tampered_body = '{"event":"payment.settled","amount":9000}'

    with pytest.raises(WebhookSecurityError) as exc_info:
        verify_signature(tampered_body, sig_header, secret)

    assert "Signature mismatch" in str(exc_info.value)


def test_signature_expired_timestamp_rejected():
    """Verify that an expired signature (older than tolerance) is rejected."""
    secret = "whsec_super_secret_test_key_123"
    body = '{"event":"payment.settled"}'
    # Timestamp from 1 hour ago
    old_ts = int(time.time()) - 3600
    sig_header = sign_payload(body, secret, timestamp=old_ts)

    with pytest.raises(WebhookSecurityError) as exc_info:
        verify_signature(body, sig_header, secret, tolerance_seconds=300)

    assert "Timestamp out of tolerance bounds" in str(exc_info.value)


def test_malformed_signature_header_rejected():
    """Verify that malformed headers without 't=' or 'v1=' raise WebhookSecurityError."""
    with pytest.raises(WebhookSecurityError):
        verify_signature("{}", "invalid_header_format", "secret")
