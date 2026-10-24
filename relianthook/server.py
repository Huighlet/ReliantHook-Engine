"""
ReliantHook-Engine Production Webhook Gateway Server.
FastAPI microservice offering HMAC signing, resilient dispatch, Dead-Letter Queue (DLQ)
inspection & replay, circuit breaker health telemetry, and settlement reconciliation.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from relianthook.circuit import CircuitBreakerRegistry, CircuitState
from relianthook.crypto import sign_payload, verify_signature
from relianthook.dispatcher import WebhookDispatcher
from relianthook.models import DeliveryStatus, WebhookEvent
from relianthook.reconciler import SettlementReconciler


# ---------------------------------------------------------
# Request / Response Pydantic Models
# ---------------------------------------------------------

class WebhookPublishRequest(BaseModel):
    destination_url: str = Field(..., description="Target merchant/subscriber HTTP endpoint.")
    event_type: str = Field(..., description="Domain event category, e.g. 'payment.authorized'.")
    payload: Any = Field(..., description="JSON-serializable payload or raw string.")
    event_id: Optional[str] = Field(None, description="Idempotent event identifier. Generated if omitted.")
    secret_key: Optional[str] = Field("whsec_live_institutional_secret_key_8821", description="HMAC-SHA256 signing secret.")
    max_retries: int = Field(5, ge=1, le=10, description="Max delivery attempts before DLQ escalation.")
    sync: bool = Field(True, description="If True, dispatch synchronously; if False, enqueue to threadpool.")


class WebhookPublishResponse(BaseModel):
    event_id: str
    destination_url: str
    event_type: str
    status: str
    retry_count: int
    attempts_count: int
    latest_http_status: Optional[int]
    latest_error: Optional[str]
    latency_ms: Optional[float]


class SignRequest(BaseModel):
    payload: str
    secret_key: str


class VerifyRequest(BaseModel):
    payload: str
    signature: str
    secret_key: str
    tolerance_seconds: int = 300


class ReconcileRequest(BaseModel):
    switch_records: List[Dict[str, Any]]
    ledger_records: List[Dict[str, Any]]
    webhook_records: Optional[List[Dict[str, Any]]] = None


# ---------------------------------------------------------
# Application Initialization
# ---------------------------------------------------------

app = FastAPI(
    title="ReliantHook-Engine Webhook Gateway",
    description="Institutional, zero-loss webhook dispatch microservice with circuit breaker protection, HMAC-SHA256 security, and DLQ replay.",
    version="1.0.0",
)

circuit_registry = CircuitBreakerRegistry(
    failure_threshold=5,
    cooldown_seconds=15.0,
)

dispatcher = WebhookDispatcher(
    max_workers=16,
    circuit_registry=circuit_registry,
    base_backoff_sec=0.5,
    max_backoff_sec=10.0,
)


@app.get("/", response_class=HTMLResponse)
def root_dashboard():
    """Interactive Developer Dashboard and Quickstart."""
    telem = dispatcher.get_telemetry()
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>ReliantHook-Engine Webhook Gateway</title>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace; background: #0b0f19; color: #f3f4f6; margin: 0; padding: 40px; }}
            .container {{ max-width: 900px; margin: 0 auto; background: #111827; border: 1px solid #1f2937; border-radius: 8px; padding: 32px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
            h1 {{ color: #60a5fa; margin-top: 0; font-size: 26px; font-weight: 600; letter-spacing: -0.5px; }}
            p {{ color: #9ca3af; font-size: 14px; line-height: 1.6; }}
            .metrics {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin: 24px 0; }}
            .metric-card {{ background: #1f2937; padding: 16px; border-radius: 6px; border-left: 3px solid #3b82f6; }}
            .metric-card.alert {{ border-left-color: #ef4444; }}
            .metric-label {{ font-size: 11px; text-transform: uppercase; color: #9ca3af; letter-spacing: 0.5px; }}
            .metric-val {{ font-size: 24px; font-weight: 700; color: #f9fafb; margin-top: 4px; }}
            .btn {{ display: inline-block; padding: 10px 18px; border-radius: 6px; background: #2563eb; color: #ffffff; text-decoration: none; font-size: 13px; font-weight: 600; }}
            .btn:hover {{ background: #1d4ed8; }}
            code {{ background: #1f2937; padding: 2px 6px; border-radius: 4px; color: #93c5fd; }}
            pre {{ background: #030712; padding: 16px; border-radius: 6px; color: #a7f3d0; font-size: 13px; overflow-x: auto; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>ReliantHook-Engine Webhook Gateway</h1>
            <p>Institutional webhook dispatcher featuring HMAC-SHA256 headers, per-destination circuit breakers, full-jitter exponential backoff, dead-letter queueing, and 3-way financial reconciliation.</p>
            
            <div class="metrics">
                <div class="metric-card">
                    <div class="metric-label">Dispatched</div>
                    <div class="metric-val">{telem['total_dispatched']:,}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Delivered</div>
                    <div class="metric-val">{telem['total_delivered']:,}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Failed Attempts</div>
                    <div class="metric-val">{telem['total_failed_attempts']:,}</div>
                </div>
                <div class="metric-card {'alert' if telem['dlq_count'] > 0 else ''}">
                    <div class="metric-label">Dead-Letter Queue</div>
                    <div class="metric-val">{telem['dlq_count']:,}</div>
                </div>
            </div>

            <p><a href="/docs" class="btn">Explore OpenAPI / Swagger Documentation &rarr;</a></p>

            <h3>Quick Ingest Example:</h3>
            <pre>curl -X POST http://localhost:8081/v1/webhooks/publish \\
  -H "Content-Type: application/json" \\
  -d '{{
    "destination_url": "https://httpbin.org/post",
    "event_type": "payment.settled",
    "payload": {{"transaction_id": "tx_883192", "amount": 54000, "currency": "GHS"}}
  }}'</pre>
        </div>
    </body>
    </html>
    """


@app.get("/health")
def health_check():
    """Liveness probe & telemetry summary."""
    return {
        "status": "HEALTHY",
        "timestamp_ns": time.time_ns(),
        "telemetry": dispatcher.get_telemetry(),
    }


@app.post("/v1/webhooks/publish", response_model=WebhookPublishResponse)
def publish_webhook(req: WebhookPublishRequest):
    """
    Publish and dispatch a webhook event with HMAC-SHA256 signature and circuit breaker protection.
    """
    event_id = req.event_id or f"evt_{uuid.uuid4().hex[:12]}"
    payload_str = req.payload if isinstance(req.payload, str) else json.dumps(req.payload)

    event = WebhookEvent(
        event_id=event_id,
        destination_url=req.destination_url,
        event_type=req.event_type,
        payload=payload_str,
        secret_key=req.secret_key or "whsec_default",
        max_retries=req.max_retries,
    )

    if req.sync:
        attempt = dispatcher.dispatch(event)
        return WebhookPublishResponse(
            event_id=event.event_id,
            destination_url=event.destination_url,
            event_type=event.event_type,
            status=event.status.value,
            retry_count=event.retry_count,
            attempts_count=len(event.attempts),
            latest_http_status=attempt.http_status_code,
            latest_error=attempt.error_message,
            latency_ms=round(attempt.latency_ms, 2) if attempt.latency_ms else 0.0,
        )
    else:
        dispatcher.dispatch_async(event)
        return WebhookPublishResponse(
            event_id=event.event_id,
            destination_url=event.destination_url,
            event_type=event.event_type,
            status=event.status.value,
            retry_count=0,
            attempts_count=0,
            latest_http_status=None,
            latest_error=None,
            latency_ms=None,
        )


@app.get("/v1/webhooks/{event_id}")
def get_webhook(event_id: str):
    """Retrieve event lifecycle state and complete delivery attempt history."""
    with dispatcher._lock:
        event = dispatcher._events.get(event_id)
        if not event:
            raise HTTPException(status_code=404, detail=f"Webhook event '{event_id}' not found.")
        
        return {
            "event_id": event.event_id,
            "destination_url": event.destination_url,
            "event_type": event.event_type,
            "status": event.status.value,
            "retry_count": event.retry_count,
            "max_retries": event.max_retries,
            "created_at_ns": event.created_at_ns,
            "attempts": [
                {
                    "attempt_number": a.attempt_number,
                    "http_status_code": a.http_status_code,
                    "latency_ms": round(a.latency_ms, 2),
                    "error_message": a.error_message,
                    "is_success": a.is_success,
                    "timestamp_ns": a.timestamp_ns,
                }
                for a in event.attempts
            ],
        }


@app.get("/v1/dlq")
def get_dead_letter_queue():
    """Retrieve all failed events currently in the Dead-Letter Queue."""
    dlq_events = dispatcher.get_dlq_events()
    return {
        "count": len(dlq_events),
        "events": [
            {
                "event_id": e.event_id,
                "destination_url": e.destination_url,
                "event_type": e.event_type,
                "retry_count": e.retry_count,
                "status": e.status.value,
                "created_at_ns": e.created_at_ns,
            }
            for e in dlq_events
        ],
    }


@app.post("/v1/dlq/replay/{event_id}")
def replay_dlq(event_id: str):
    """Trigger manual replay of an event from the Dead-Letter Queue."""
    try:
        attempt = dispatcher.replay_dlq_event(event_id)
        return {
            "replayed": True,
            "event_id": event_id,
            "attempt_number": attempt.attempt_number,
            "http_status_code": attempt.http_status_code,
            "is_success": attempt.is_success,
            "error_message": attempt.error_message,
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Event '{event_id}' not found in DLQ.")


@app.get("/v1/circuits")
def get_circuits():
    """Inspect state, failure counters, and trip thresholds across all circuit breakers."""
    results = {}
    with circuit_registry._lock:
        for endpoint, breaker in circuit_registry._breakers.items():
            results[endpoint] = {
                "state": breaker.state.value,
                "consecutive_failures": breaker._consecutive_failures,
                "failure_threshold": breaker.failure_threshold,
                "cooldown_seconds": breaker.cooldown_seconds,
                "opened_at": breaker._opened_at,
            }
    return {"circuits": results}


@app.post("/v1/crypto/sign")
def sign_crypto(req: SignRequest):
    """Generate RFC HMAC-SHA256 timestamped signature header."""
    header = sign_payload(req.payload, req.secret_key)
    return {"signature_header": header}


@app.post("/v1/crypto/verify")
def verify_crypto(req: VerifyRequest):
    """Verify incoming HMAC signature header against payload with drift tolerance."""
    try:
        valid = verify_signature(
            payload_body=req.payload,
            signature_header=req.signature,
            secret_key=req.secret_key,
            tolerance_seconds=req.tolerance_seconds,
        )
        return {"valid": valid, "detail": "Signature matches cryptographic payload digest."}
    except Exception as e:
        return {"valid": False, "detail": str(e)}


@app.post("/v1/reconcile")
def run_reconciliation(req: ReconcileRequest):
    """Execute 3-way financial reconciliation across Switch, Ledger, and Webhook logs."""
    reconciler = SettlementReconciler()
    report = reconciler.reconcile(
        reconciliation_date=time.strftime("%Y-%m-%d"),
        switch_records=req.switch_records,
        ledger_records=req.ledger_records,
        webhook_records=req.webhook_records or [],
    )
    return {
        "reconciliation_date": report.reconciliation_date,
        "total_records": report.total_records,
        "matched_count": report.matched_count,
        "discrepancy_count": report.discrepancy_count,
        "net_switch_volume": report.net_switch_volume,
        "net_ledger_volume": report.net_ledger_volume,
        "volume_variance": report.volume_variance,
        "is_clean": report.is_clean,
        "discrepancies": report.discrepancies,
    }


def serve(host: str = "0.0.0.0", port: int = 8081):
    """Entry point for standalone execution."""
    import uvicorn
    uvicorn.run("relianthook.server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    serve()
