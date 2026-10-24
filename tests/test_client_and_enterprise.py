"""
Enterprise and Client SDK tests for ReliantHook-Engine.
Validates Pillar 1 (Enterprise Middleware & Metrics), Pillar 2 (DLQ Redrive & Reconciliation Export), and Pillar 3 (Client SDK).
"""

import pytest
from starlette.testclient import TestClient

from relianthook import server
from relianthook.client import ReliantHookClient


@pytest.fixture
def test_client() -> TestClient:
    return TestClient(server.app)


def test_prometheus_metrics_endpoint(test_client: TestClient):
    resp = test_client.get("/metrics")
    assert resp.status_code == 200
    text = resp.text
    assert "relianthook_dispatches_total" in text
    assert "relianthook_delivered_total" in text
    assert "relianthook_circuits_total" in text


def test_dlq_redrive_endpoint(test_client: TestClient):
    resp = test_client.post("/v1/dlq/redrive")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "REDRIVE_COMPLETED"
    assert "redriven_count" in data


def test_reconciliation_bundle_export(test_client: TestClient):
    payload = {
        "switch_records": [
            {"transaction_id": "tx_rec_1", "amount": 250.0, "currency": "USD", "response_code": "00"}
        ],
        "ledger_records": [
            {"transaction_id": "tx_rec_1", "amount": 250.0, "currency": "USD", "status": "COMMITTED"}
        ],
        "webhook_records": [
            {"transaction_id": "tx_rec_1", "status": "DELIVERED"}
        ],
    }
    resp = test_client.post("/v1/reconcile/export", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "bundle_id" in data
    assert "integrity_seal" in data
    assert data["report"]["is_clean"] is True
    assert data["report"]["volume_variance"] == 0.0


def test_relianthook_python_client_sdk(test_client: TestClient):
    client = ReliantHookClient(http_client=test_client)

    # 1. Sign and verify
    secret = "test_institutional_secret_key"
    payload_body = '{"event": "account.funded", "amount": 5000}'
    sig = client.sign(payload_body, secret)
    assert sig.startswith("t=")
    assert client.verify(payload_body, sig, secret) is True

    # 2. Query circuits
    circuits = client.get_circuits()
    assert "circuits" in circuits

    # 3. Query DLQ
    dlq = client.get_dlq()
    assert "events" in dlq

    # 4. Redrive DLQ via SDK
    redrive = client.redrive_dlq()
    assert redrive["status"] == "REDRIVE_COMPLETED"
    client.close()
