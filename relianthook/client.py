"""
ReliantHook Client SDK: Idiomatic high-performance client for the ReliantHook-Engine Webhook Gateway.
Supports cryptographically signed webhook publishing, circuit breaker introspection, DLQ redrive, and 3-way reconciliation.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore


class ReliantHookClient:
    """
    Client for interacting with a live ReliantHook-Engine Webhook Gateway instance.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8081",
        api_key: Optional[str] = None,
        timeout_seconds: float = 10.0,
        http_client: Optional[Any] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        if http_client is not None:
            self._client = http_client
        elif httpx is not None:
            self._client = httpx.Client(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        else:
            self._client = None

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    def __enter__(self) -> ReliantHookClient:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def publish_webhook(
        self,
        destination_url: str,
        event_type: str,
        payload: Any,
        event_id: Optional[str] = None,
        secret_key: Optional[str] = None,
        max_retries: int = 5,
        sync: bool = True,
    ) -> Dict[str, Any]:
        """Publish and dispatch a resilient webhook event."""
        body = {
            "destination_url": destination_url,
            "event_type": event_type,
            "payload": payload,
            "event_id": event_id or f"evt_{uuid.uuid4().hex[:12]}",
            "max_retries": max_retries,
            "sync": sync,
        }
        if secret_key:
            body["secret_key"] = secret_key

        resp = self._client.post("/v1/webhooks/publish", json=body)
        resp.raise_for_status()
        return resp.json()

    def get_dlq(self) -> Dict[str, Any]:
        """Fetch all events currently held in the Dead-Letter Queue."""
        resp = self._client.get("/v1/dlq")
        resp.raise_for_status()
        return resp.json()

    def replay_dlq(self, event_id: str) -> Dict[str, Any]:
        """Manually trigger replay for a single dead-letter event."""
        resp = self._client.post(f"/v1/dlq/replay/{event_id}")
        resp.raise_for_status()
        return resp.json()

    def redrive_dlq(self) -> Dict[str, Any]:
        """Trigger bulk redrive of all eligible DLQ events."""
        resp = self._client.post("/v1/dlq/redrive")
        resp.raise_for_status()
        return resp.json()

    def get_circuits(self) -> Dict[str, Any]:
        """Query state and failure counters across all destination circuit breakers."""
        resp = self._client.get("/v1/circuits")
        resp.raise_for_status()
        return resp.json()

    def sign(self, payload: str, secret_key: str) -> str:
        """Generate timestamped RFC HMAC-SHA256 signature header."""
        resp = self._client.post("/v1/crypto/sign", json={"payload": payload, "secret_key": secret_key})
        resp.raise_for_status()
        return resp.json()["signature_header"]

    def verify(self, payload: str, signature: str, secret_key: str, tolerance_seconds: int = 300) -> bool:
        """Verify signature header against payload digest with drift window."""
        body = {
            "payload": payload,
            "signature": signature,
            "secret_key": secret_key,
            "tolerance_seconds": tolerance_seconds,
        }
        resp = self._client.post("/v1/crypto/verify", json=body)
        resp.raise_for_status()
        return resp.json()["valid"]

    def reconcile(
        self,
        switch_records: List[Dict[str, Any]],
        ledger_records: List[Dict[str, Any]],
        webhook_records: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Perform 3-way financial and delivery settlement reconciliation."""
        body = {
            "switch_records": switch_records,
            "ledger_records": ledger_records,
            "webhook_records": webhook_records or [],
        }
        resp = self._client.post("/v1/reconcile", json=body)
        resp.raise_for_status()
        return resp.json()

    def get_metrics(self) -> str:
        """Retrieve Prometheus metrics."""
        resp = self._client.get("/metrics")
        resp.raise_for_status()
        return resp.text
