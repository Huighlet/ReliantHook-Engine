"""
Unit & Integration Tests for ReliantHook-Engine REST API Server.
"""

import pytest
from starlette.testclient import TestClient
from relianthook.server import app, dispatcher


@pytest.fixture
def client():
    # Inject a mock transport into dispatcher so test HTTP calls don't hit external networks
    def mock_transport(url, headers, body):
        if "fail.com" in url:
            return 500, '{"error": "Internal Server Error"}'
        return 200, '{"status": "ok"}'

    dispatcher.transport = mock_transport
    return TestClient(app)


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "HEALTHY"
    assert "telemetry" in data


def test_root_dashboard(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "ReliantHook-Engine Webhook Gateway" in response.text


def test_crypto_sign_and_verify(client):
    payload = '{"amount": 10000, "currency": "GHS"}'
    secret = "whsec_test_secret_123"

    # 1. Sign
    sign_resp = client.post("/v1/crypto/sign", json={"payload": payload, "secret_key": secret})
    assert sign_resp.status_code == 200
    sig_header = sign_resp.json()["signature_header"]
    assert "t=" in sig_header
    assert "v1=" in sig_header

    # 2. Verify Valid
    verify_resp = client.post("/v1/crypto/verify", json={
        "payload": payload,
        "signature": sig_header,
        "secret_key": secret,
        "tolerance_seconds": 300,
    })
    assert verify_resp.status_code == 200
    assert verify_resp.json()["valid"] is True

    # 3. Verify Invalid Signature
    verify_resp_bad = client.post("/v1/crypto/verify", json={
        "payload": payload,
        "signature": "t=123,v1=invalidsig",
        "secret_key": secret,
        "tolerance_seconds": 300,
    })
    assert verify_resp_bad.status_code == 200
    assert verify_resp_bad.json()["valid"] is False


def test_publish_webhook_success(client):
    payload = {"account_id": "acc_001", "balance": 45000}
    resp = client.post("/v1/webhooks/publish", json={
        "destination_url": "https://api.merchant.com/webhook",
        "event_type": "account.funded",
        "payload": payload,
        "sync": True,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "DELIVERED"
    assert data["latest_http_status"] == 200
    assert data["retry_count"] == 0

    # Query event
    event_id = data["event_id"]
    get_resp = client.get(f"/v1/webhooks/{event_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["event_id"] == event_id


def test_publish_webhook_failure_and_dlq(client):
    # Trigger repeated failures to force DLQ escalation
    event_id = "evt_fail_test_001"
    resp = client.post("/v1/webhooks/publish", json={
        "event_id": event_id,
        "destination_url": "https://fail.com/webhook",
        "event_type": "payment.failed",
        "payload": {"error": "test"},
        "max_retries": 1,
        "sync": True,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "DEAD_LETTER"

    # Verify presence in DLQ
    dlq_resp = client.get("/v1/dlq")
    assert dlq_resp.status_code == 200
    dlq_data = dlq_resp.json()
    assert any(e["event_id"] == event_id for e in dlq_data["events"])


def test_reconciliation_endpoint(client):
    switch_records = [
        {"rrn": "RRN_001", "amount": 10000, "fee": 100, "status": "APPROVED"},
        {"rrn": "RRN_002", "amount": 20000, "fee": 200, "status": "APPROVED"},
    ]
    ledger_records = [
        {"rrn": "RRN_001", "amount": 10000, "status": "COMMITTED"},
        {"rrn": "RRN_002", "amount": 20000, "status": "COMMITTED"},
    ]
    webhook_records = [
        {"rrn": "RRN_001", "status": "DELIVERED"},
        {"rrn": "RRN_002", "status": "DELIVERED"},
    ]
    resp = client.post("/v1/reconcile", json={
        "switch_records": switch_records,
        "ledger_records": ledger_records,
        "webhook_records": webhook_records,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_clean"] is True
    assert data["matched_count"] == 2
    assert data["discrepancy_count"] == 0
