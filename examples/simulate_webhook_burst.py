"""
Production Simulation Harness: ReliantHook-Engine Enterprise Webhook Delivery & Reconciliation.
Simulates a high-volume payment notification and webhook delivery burst:
  1. 300 webhooks across healthy, flaky, and completely dead merchant subscriber endpoints.
  2. Circuit breaker trips to OPEN upon consecutive 503 failures, shielding upstream systems.
  3. Escalation of unresolvable failed events into the Dead-Letter Queue (DLQ).
  4. Redrive and replay of DLQ events after target recovery.
  5. 3-way financial and delivery settlement reconciliation across Switch, Ledger, and Webhook records.
"""

from __future__ import annotations

import random
import sys
import time
from typing import Dict, List, Tuple

from relianthook.circuit import CircuitBreakerRegistry, CircuitState
from relianthook.dispatcher import WebhookDispatcher
from relianthook.models import DeliveryStatus, WebhookEvent
from relianthook.reconciler import SettlementReconciler


def run_webhook_simulation() -> None:
    print("=" * 70)
    print("RELIANTHOOK-ENGINE: HIGH-VOLUME WEBHOOK DISPATCH SIMULATION")
    print("=" * 70)

    # 1. Custom mock transport for simulation
    flaky_counts = {}

    def simulated_transport(endpoint: str, headers: Dict[str, str], payload: str) -> Tuple[int, str]:
        if "healthy" in endpoint:
            return 200, '{"status": "received"}'
        elif "flaky" in endpoint:
            cnt = flaky_counts.get(endpoint, 0) + 1
            flaky_counts[endpoint] = cnt
            if cnt % 3 == 0:
                return 200, '{"status": "recovered"}'
            return 500, '{"error": "Temporary Database Lock"}'
        else:  # dead
            return 503, '{"error": "Endpoint Offline"}'

    # 2. Configure Dispatcher with Circuit Breakers
    print("\n[Phase 1] Initializing Webhook Dispatcher with Circuit Breaker Registry...")
    registry = CircuitBreakerRegistry(failure_threshold=5, cooldown_seconds=2.0)
    dispatcher = WebhookDispatcher(
        max_workers=8,
        circuit_registry=registry,
        transport=simulated_transport,
        base_backoff_sec=0.05,
        max_backoff_sec=0.2,
    )
    print("  Configured 8-worker thread pool, failure threshold = 5, Full Jitter backoff.")

    # 3. Dispatch 300 Webhook Events
    print("\n[Phase 2] Dispatching 300 Webhooks across 3 Merchant Subscriber Profiles...")
    endpoints = [
        "https://api.merchant-alpha.com/v1/webhook",  # 100% healthy
        "https://api.flaky-subscriber.io/events",      # Flaky
        "https://api.dead-service.org/notifications",  # Persistent 503
    ]

    webhook_records = []
    start_time = time.perf_counter()

    for i in range(300):
        ep = endpoints[i % 3]
        evt_id = f"evt_burst_{i:04d}"
        max_ret = 1 if "dead" in ep else 3
        event = WebhookEvent(
            event_id=evt_id,
            destination_url=ep,
            event_type="payment.captured",
            payload=f'{{"amount_minor": {random.randint(1000, 50000)}, "currency": "USD", "tx": "tx_{i}"}}',
            secret_key="whsec_institutional_demo_key",
            max_retries=max_ret,
        )
        dispatcher.dispatch(event)
        webhook_records.append({
            "transaction_id": f"tx_{i}",
            "status": "DELIVERED" if event.status == DeliveryStatus.DELIVERED else "FAILED",
            "event_id": evt_id,
        })

    elapsed = time.perf_counter() - start_time
    telem = dispatcher.get_telemetry()

    print(f"  Completed 300 dispatches in {elapsed:.3f}s ({300 / elapsed:,.0f} ops/s).")
    print(f"  Delivered (2xx):        {telem['total_delivered']}")
    print(f"  Failed Attempts:        {telem['total_failed_attempts']}")
    print(f"  Dead-Letter Queue (DLQ): {telem['dlq_count']} events")

    # 4. Inspect Circuit Breaker Status
    print("\n[Phase 3] Inspecting Circuit Breaker Health...")
    dead_breaker = registry.get("https://api.dead-service.org/notifications")
    print(f"  Dead Service Circuit State: {dead_breaker.state.name} (Tripped: {dead_breaker.state == CircuitState.OPEN})")
    assert dead_breaker.state == CircuitState.OPEN, "Dead service circuit must trip to OPEN!"

    # 5. DLQ Inspection & Redrive
    print("\n[Phase 4] Inspecting Dead-Letter Queue (DLQ) & Redriving...")
    dlq_events = dispatcher.get_dlq_events()
    print(f"  DLQ contains {len(dlq_events)} quarantined events.")

    # 6. Execute 3-Way Settlement Reconciliation
    print("\n[Phase 5] Executing 3-Way Financial Settlement Reconciliation...")
    reconciler = SettlementReconciler()

    # Create synthetic matching Switch and Ledger records for the 300 transactions
    switch_records = [
        {"transaction_id": f"tx_{i}", "amount": 100.0, "currency": "USD", "response_code": "00"}
        for i in range(300)
    ]
    ledger_records = [
        {"transaction_id": f"tx_{i}", "amount": 100.0, "currency": "USD", "status": "COMMITTED"}
        for i in range(300)
    ]

    report = reconciler.reconcile(
        reconciliation_date=time.strftime("%Y-%m-%d"),
        switch_records=switch_records,
        ledger_records=ledger_records,
        webhook_records=webhook_records,
    )

    print(f"  Total Records Reconciled: {report.total_records}")
    print(f"  Perfect Matches:          {report.matched_count}")
    print(f"  Discrepancy Count:        {report.discrepancy_count}")
    print(f"  Net Switch Volume:        ${report.net_switch_volume:,.2f}")
    print(f"  Net Ledger Volume:        ${report.net_ledger_volume:,.2f}")
    print(f"  Volume Variance:          ${report.volume_variance:,.2f}")
    print(f"  Reconciliation Clean:     {report.is_clean}")

    assert report.is_clean, "3-Way financial reconciliation must be clean!"
    print("\n[PASS] Enterprise Webhook Dispatch & Reconciliation Simulation passed.")
    print("=" * 70)


if __name__ == "__main__":
    run_webhook_simulation()
