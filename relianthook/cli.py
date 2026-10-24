"""
ReliantHook-Engine CLI: Utilities for HMAC Signing, Signature Verification, Dispatch Benchmarking, and EOD Audits.
"""

from __future__ import annotations

import argparse
import json
import time

from relianthook.crypto import sign_payload, verify_signature
from relianthook.dispatcher import WebhookDispatcher
from relianthook.models import WebhookEvent
from relianthook.reconciler import SettlementReconciler


def cmd_sign(payload: str, secret: str) -> None:
    """Generate HMAC-SHA256 signature header for payload."""
    sig = sign_payload(payload, secret)
    print("=" * 60)
    print("HMAC-SHA256 Webhook Signature Generated:")
    print(sig)
    print("=" * 60)


def cmd_verify(payload: str, signature: str, secret: str, tolerance: int = 300) -> None:
    """Verify incoming signature header against payload."""
    try:
        verify_signature(payload, signature, secret, tolerance_seconds=tolerance)
        print("[SUCCESS] Signature is VALID. Payload content and timestamp verified.")
    except Exception as e:
        print(f"[FAILED] Verification Error: {e}")


def cmd_bench(count: int = 50_000) -> None:
    """Benchmark high-load HMAC-SHA256 generation and simulated dispatch throughput."""
    print("=" * 60)
    print(f"RELIANTHOOK-ENGINE BENCHMARK: {count:,} EVENTS")
    print("=" * 60)

    secret = "whsec_test_secret_key_9988776655"
    payload = json.dumps({
        "event": "charge.success",
        "data": {
            "id": "ch_123456789",
            "amount": 25000,
            "currency": "GHS",
            "customer": "cus_987654",
            "paid_at": 1700000000
        }
    })

    # 1. Benchmark HMAC-SHA256 Signature Generation
    t0 = time.perf_counter()
    for _ in range(count):
        _ = sign_payload(payload, secret)
    t_sign = time.perf_counter() - t0
    sign_tps = count / t_sign

    # 2. Benchmark Dispatcher Pipeline with Mock HTTP Transport
    def mock_transport(url, headers, body):
        return 200, '{"received": true}'

    dispatcher = WebhookDispatcher(max_workers=8, transport=mock_transport)
    t0 = time.perf_counter()
    for i in range(count):
        ev = WebhookEvent(
            event_id=f"evt_{i:07d}",
            destination_url="https://merchant.example.com/webhook",
            event_type="charge.success",
            payload=payload,
            secret_key=secret,
        )
        dispatcher.dispatch(ev)
    t_dispatch = time.perf_counter() - t0
    dispatch_tps = count / t_dispatch
    dispatcher.shutdown()

    print(f"HMAC-SHA256 Generation:   {sign_tps:,.1f} signatures/sec ({t_sign:.3f}s)")
    print(f"Synchronous Dispatch:     {dispatch_tps:,.1f} dispatches/sec ({t_dispatch:.3f}s)")
    print("=" * 60)


def cmd_reconcile() -> None:
    """Run demonstration 3-way End-of-Day settlement reconciliation audit."""
    print("Running End-of-Day (EOD) 3-Way Settlement Reconciliation Audit...")
    reconciler = SettlementReconciler()

    # Synthetic sample data demonstrating matching and discrepancy detection
    switch_records = [
        {"rrn": "RRN_001", "amount": 10000, "fee": 100, "status": "APPROVED"},
        {"rrn": "RRN_002", "amount": 25000, "fee": 250, "status": "APPROVED"},
        {"rrn": "RRN_003", "amount": 50000, "fee": 500, "status": "APPROVED"},
        {"rrn": "RRN_004", "amount": 15000, "fee": 150, "status": "APPROVED"}, # Missing in ledger!
    ]

    ledger_records = [
        {"rrn": "RRN_001", "amount": 10000, "status": "COMMITTED"},
        {"rrn": "RRN_002", "amount": 25000, "status": "COMMITTED"},
        {"rrn": "RRN_003", "amount": 50000, "status": "COMMITTED"},
        {"rrn": "RRN_005", "amount": 8000,  "status": "COMMITTED"}, # Missing in switch!
    ]

    webhook_records = [
        {"rrn": "RRN_001", "status": "DELIVERED"},
        {"rrn": "RRN_002", "status": "DELIVERED"},
        {"rrn": "RRN_003", "status": "FAILED_RETRYING"}, # Webhook not delivered!
    ]

    report = reconciler.reconcile("2026-10-24", switch_records, ledger_records, webhook_records)

    print("=" * 60)
    print(f"EOD RECONCILIATION REPORT [{report.reconciliation_date}]")
    print("=" * 60)
    print(f"Total Unique RRNs:       {report.total_records}")
    print(f"Fully Matched Records:   {report.matched_count}")
    print(f"Discrepancies Detected:  {report.discrepancy_count}")
    print(f"Switch Cleared Volume:   {report.net_switch_volume} minor units")
    print(f"Ledger Recorded Volume:  {report.net_ledger_volume} minor units")
    print(f"Volume Variance:         {report.volume_variance} minor units")
    print(f"Audit Clean:             {report.is_clean}")
    print("-" * 60)
    print("Discrepancy Breakdown:")
    for d in report.discrepancies:
        print(f"  * [{d['type']}] RRN: {d['rrn']} - {d['details']}")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(prog="relianthook", description="ReliantHook-Engine CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Sign
    sign_p = subparsers.add_parser("sign", help="Compute HMAC-SHA256 signature for payload")
    sign_p.add_argument("--payload", required=True, help="Payload string")
    sign_p.add_argument("--secret", required=True, help="Secret signing key")

    # Verify
    verify_p = subparsers.add_parser("verify", help="Verify webhook signature")
    verify_p.add_argument("--payload", required=True, help="Payload string")
    verify_p.add_argument("--sig", required=True, help="Signature header (t=...,v1=...)")
    verify_p.add_argument("--secret", required=True, help="Secret signing key")
    verify_p.add_argument("--tolerance", type=int, default=300, help="Timestamp tolerance in seconds")

    # Bench
    bench_p = subparsers.add_parser("bench", help="Run throughput benchmarks")
    bench_p.add_argument("-n", "--count", type=int, default=30000, help="Number of events")

    # Reconcile
    reconcile_p = subparsers.add_parser("reconcile", help="Execute sample 3-way settlement audit")

    # Serve
    serve_p = subparsers.add_parser("serve", help="Launch FastAPI Webhook Gateway REST service")
    serve_p.add_argument("--host", default="0.0.0.0", help="Binding host address")
    serve_p.add_argument("--port", type=int, default=8081, help="Binding port (default: 8081)")

    args = parser.parse_args()
    if args.command == "serve":
        from relianthook.server import serve
        serve(host=args.host, port=args.port)
    elif args.command == "sign":
        cmd_sign(args.payload, args.secret)
    elif args.command == "verify":
        cmd_verify(args.payload, args.sig, args.secret, args.tolerance)
    elif args.command == "bench":
        cmd_bench(args.count)
    elif args.command == "reconcile":
        cmd_reconcile()


if __name__ == "__main__":
    main()
