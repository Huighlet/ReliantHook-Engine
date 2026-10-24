# ReliantHook-Engine

Zero-Loss Webhook Dispatcher and End-of-Day (EOD) Settlement Reconciliation Engine.

Designed for high-volume payment gateways, aggregators, and core banking switches (such as Stripe, Paystack, Hubtel, and Zeepay). Built from first principles to guarantee at-least-once merchant notifications, anti-replay cryptographic signing, cascading failure isolation, and automated 3-way financial reconciliation.

---

## 1. Problem Statement: The Distributed Webhook Dilemma

In payment infrastructure, once a transaction is authorized at the network switch and committed to the double-entry ledger, notifying merchant endpoints via webhooks is the final critical mile. In real-world telecommunications:

```
+----------------------------------------------------------------------------------------------------+
|                               THE WEBHOOK FAILURE TAXONOMY                                         |
+----------------------------------------------------------------------------------------------------+
| Failure Mode              | Root Cause                             | Real-World Impact             |
+---------------------------+----------------------------------------+-------------------------------+
| The Thundering Herd       | Synchronous, deterministic retry loops | Recovering merchant endpoints |
|                           | without random time domain jitter      | immediately crash again       |
+---------------------------+----------------------------------------+-------------------------------+
| Worker Thread Starvation  | Unbounded retries to dead endpoints    | Aggregator thread pool blocks;|
|                           | without circuit breakers               | healthy merchants starved     |
+---------------------------+----------------------------------------+-------------------------------+
| Replay & Spoofing Attacks | Unauthenticated or unsalted HTTP POSTs | Malicious actors simulate     |
|                           | without constant-time HMAC check       | fraudulent payment credits    |
+---------------------------+----------------------------------------+-------------------------------+
| Settlement Blindspots     | Disconnected webhook delivery logs and | Customer debited, but merchant|
|                           | core accounting ledger states          | goods never delivered (dispute)|
+----------------------------------------------------------------------------------------------------+
```

---

## 2. Cryptographic Anti-Spoofing & Replay Protection

Every webhook payload is authenticated using an HMAC-SHA256 signature header (`v1`) salted with a monotonic Unix timestamp (`t`), matching tier-1 payment gateway standards:

```text
X-Webhook-Signature: t=1700000000,v1=9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08
```

### Signature Formulation

$$\text{Signature} = \text{HMAC-SHA256}\Big(\text{SecretKey}, \; \text{Timestamp} \parallel \text{"."} \parallel \text{RawPayloadBody}\Big)$$

1. **Replay Defense:** The verifier asserts $|t_{\text{current}} - t_{\text{header}}| \le \text{ToleranceSeconds}$ (default: 300 seconds). Expired requests are immediately rejected.
2. **Timing Attack Immunity:** Signatures are compared strictly using constant-time digest comparison (`hmac.compare_digest`), preventing timing-based side-channel leaks.

---

## 3. Thundering Herd Defense: Full Jitter Scheduling

When a downstream merchant server recovers after a brief network drop, naive exponential backoff causes all in-flight retries to strike the server at the exact same millisecond.

ReliantHook-Engine implements the **Full Jitter** algorithm:

$$T_{\text{ceiling}} = \min\Big(\text{MaxBackoff}, \; \text{BaseBackoff} \times 2^{\text{RetryAttempt}}\Big)$$

$$T_{\text{sleep}} = \mathcal{U}\Big(0, \; T_{\text{ceiling}}\Big)$$

Where $\mathcal{U}(a, b)$ is a uniform continuous random distribution, distributing retry traffic smoothly across the time domain.

---

## 4. Circuit Breaker Architecture

To prevent a single unresponsive merchant from exhausting dispatcher thread pools, each destination URL is isolated by an independent circuit breaker state machine:

```
                       [Normal Operation]
                             |
                   +---------v---------+
       +---------->|      CLOSED       |<----------+
       |           +-------------------+           |
       |                     |                     |
       | Probe               | Consecutive         | Probe
       | Succeeds            | Failures >= 5       | Succeeds
       |                     v                     |
       |           +-------------------+           |
       |           |       OPEN        |           |
       |           |   (Fast-Fails)    |           |
       |           +-------------------+           |
       |                     |                     |
       |                     | Cooldown (30s)      |
       |                     v                     |
       |           +-------------------+           |
       +-----------|     HALF-OPEN     |-----------+
                   |  (Single Probe)   |
                   +-------------------+
                             |
                             | Probe Fails
                             v
                         [Re-Open]
```

---

## 5. End-of-Day (EOD) 3-Way Settlement Reconciliation

Financial accuracy requires automated tripartite cross-auditing at cut-off:

```
                       3-WAY EOD RECONCILIATION
                                  |
            +---------------------+---------------------+
            |                     |                     |
            v                     v                     v
  [Switch Rail Logs]    [Core Ledger Records]   [Webhook Delivery Logs]
   (SwitchRail-8583)       (TitanLedger-Core)      (ReliantHook-Engine)
            \                     |                     /
             \                    |                    /
              +-------------------v-------------------+
              |      Settlement Reconciler Engine     |
              |   - Matched Records (Settled)         |
              |   - Missing in Ledger                 |
              |   - Missing in Switch                 |
              |   - Volume / Fee Variance             |
              |   - Undelivered Merchant Webhooks     |
              +---------------------------------------+
```

### Discrepancy Classification

* **`MATCHED`:** Cleared at switch, posted in ledger, webhook acknowledged with HTTP 2xx.
* **`MISSING_IN_LEDGER`:** Cleared at bank switch, but missing from internal ledger (severe financial exposure).
* **`MISSING_IN_SWITCH`:** Ledger entry exists without clearing switch trace (rogue state / unverified credit).
* **`VOLUME_MISMATCH`:** Cleared switch volume differs from internal ledger volume.
* **`UNDELIVERED_WEBHOOK`:** Money settled successfully, but merchant delivery failed (customer paid, goods unfulfilled).

---

## 6. Performance Benchmarks

Micro-benchmarks executed on commodity 64-bit hardware (Python 3.13):

```text
============================================================
RELIANTHOOK-ENGINE BENCHMARK: 50,000 EVENTS
============================================================
HMAC-SHA256 Generation:   81,147.3 signatures/sec (0.616s)
Synchronous Dispatch:     38,886.0 dispatches/sec (1.286s)
============================================================
```

---

## 7. Project Map

```
ReliantHook-Engine/
|-- relianthook/
|   |-- __init__.py         # Public exports and API surface
|   |-- crypto.py           # HMAC-SHA256 signing and timestamp replay verification
|   |-- models.py           # WebhookEvent, DeliveryAttempt, ReconciliationReport
|   |-- backoff.py          # Full Jitter and Decorrelated Jitter algorithms
|   |-- circuit.py          # Per-destination Circuit Breaker state machine
|   |-- dispatcher.py       # Thread-pooled webhook dispatcher with DLQ support
|   |-- reconciler.py       # 3-Way EOD Settlement Reconciler
|   |-- cli.py              # CLI for sign, verify, bench, and reconciliation audits
|-- tests/
|   |-- test_crypto.py      # HMAC validation, tampering checks, expired replay tests
|   |-- test_backoff.py     # Exponential bounds and jitter distribution tests
|   |-- test_circuit.py     # Circuit breaker state transitions and trip thresholds
|   |-- test_dispatcher.py  # Dispatch retries, DLQ escalation, and DLQ replay
|   |-- test_reconciler.py  # Clean reconciliation, missing ledger, and volume mismatch
|-- pyproject.toml          # Package metadata and CLI hook
|-- requirements.txt        # Frozen dependencies
|-- LICENSE                 # MIT License (Huighlet Eyram Zowonu)
|-- README.md               # Technical specification and architecture documentation
```

---

## 8. Installation & Quickstart

### Setup Environment

```bash
git clone https://github.com/Huighlet/ReliantHook-Engine.git
cd ReliantHook-Engine

python -m venv .venv
# Linux / macOS:
source .venv/bin/activate
# Windows:
.\.venv\Scripts\Activate.ps1

pip install -e .
```

### Python API Example

```python
from relianthook import (
    WebhookDispatcher,
    WebhookEvent,
    sign_payload,
    verify_signature,
    SettlementReconciler,
)

# 1. Initialize dispatcher
dispatcher = WebhookDispatcher(max_workers=8)

# 2. Register event
event = WebhookEvent(
    event_id="evt_pay_987654",
    destination_url="https://merchant.example.com/webhooks/payments",
    event_type="charge.success",
    payload='{"id": "ch_123", "amount": 25000, "currency": "GHS"}',
    secret_key="whsec_merchant_api_secret_key",
)

# 3. Dispatch event with automated HMAC signing and circuit protection
attempt = dispatcher.dispatch(event)
print(f"Status: {event.status} | Latency: {attempt.latency_ms:.2f}ms")

dispatcher.shutdown()
```

---

## 9. Turnkey REST API Server & Docker Deployment

ReliantHook-Engine includes an asynchronous, production-ready Webhook Gateway REST service and interactive developer UI.

### 1. Launch Server via CLI

```bash
# Start standalone service on port 8081
relianthook serve --host 0.0.0.0 --port 8081
```

Once running:
- **Interactive Swagger Documentation:** [`http://localhost:8081/docs`](http://localhost:8081/docs)
- **Engine Metrics & Liveness:** [`http://localhost:8081/health`](http://localhost:8081/health)
- **Dead-Letter Queue (DLQ):** [`http://localhost:8081/v1/dlq`](http://localhost:8081/v1/dlq)
- **Active Circuit Breaker States:** [`http://localhost:8081/v1/circuits`](http://localhost:8081/v1/circuits)

### 2. Standalone Container Execution (Docker)

```bash
# Build production image
docker build -t relianthook-engine:latest .

# Run container with mapped port
docker run -d --name relianthook-gateway -p 8081:8081 relianthook-engine:latest

# Verify health status
curl -s http://localhost:8081/health
```

### 3. REST API Usage Examples

**Publish and Dispatch Webhook:**
```bash
curl -X POST http://localhost:8081/v1/webhooks/publish \
  -H "Content-Type: application/json" \
  -d '{
    "destination_url": "https://httpbin.org/post",
    "event_type": "charge.success",
    "payload": {
      "transaction_id": "tx_998822",
      "amount": 25000,
      "currency": "GHS",
      "customer_email": "client@example.com"
    },
    "sync": true
  }'
```

**Query Dead-Letter Queue (DLQ):**
```bash
curl -s http://localhost:8081/v1/dlq
```

**Replay Dead-Letter Event:**
```bash
curl -X POST http://localhost:8081/v1/dlq/replay/evt_fail_test_001
```

---

## 10. CLI Usage

### 1. Compute HMAC-SHA256 Webhook Signature

```bash
relianthook sign --payload '{"amount": 5000}' --secret 'whsec_secret_key'
```

Output:
```text
============================================================
HMAC-SHA256 Webhook Signature Generated:
t=1700000000,v1=9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08
============================================================
```

### 2. Verify Incoming Webhook Signature

```bash
relianthook verify --payload '{"amount": 5000}' --sig 't=1700000000,v1=...' --secret 'whsec_secret_key'
```

### 3. Run Micro-Benchmarks

```bash
relianthook bench -n 50000
```

### 4. Execute 3-Way EOD Reconciliation Audit

```bash
relianthook reconcile
```

Output:
```text
============================================================
EOD RECONCILIATION REPORT [2026-10-24]
============================================================
Total Unique RRNs:       5
Fully Matched Records:   2
Discrepancies Detected:  3
Switch Cleared Volume:   100000 minor units
Ledger Recorded Volume:  93000 minor units
Volume Variance:         7000 minor units
Audit Clean:             False
------------------------------------------------------------
Discrepancy Breakdown:
  * [UNDELIVERED_WEBHOOK] RRN: RRN_003 - Financial settlement completed, but merchant webhook delivery failed.
  * [MISSING_IN_LEDGER] RRN: RRN_004 - Transaction cleared at bank switch but missing from internal ledger.
  * [MISSING_IN_SWITCH] RRN: RRN_005 - Transaction posted in internal ledger without clearing switch record.
============================================================
```

---

## 11. Test Suite Execution

Run the complete 22-case test suite covering HMAC verification, jitter distribution, circuit breaker trips, 3-way reconciliation, and REST endpoints:

```bash
pytest -v
```

All 22 test scenarios pass deterministically:
```text
tests/test_backoff.py::test_exponential_backoff_bounds PASSED
tests/test_backoff.py::test_full_jitter_distribution PASSED
tests/test_backoff.py::test_decorrelated_jitter_bounds PASSED
tests/test_circuit.py::test_circuit_breaker_lifecycle PASSED
tests/test_circuit.py::test_circuit_breaker_half_open_failure_reopens PASSED
tests/test_crypto.py::test_signature_roundtrip_valid PASSED
tests/test_crypto.py::test_signature_tampered_payload_rejected PASSED
tests/test_crypto.py::test_signature_expired_timestamp_rejected PASSED
tests/test_crypto.py::test_malformed_signature_header_rejected PASSED
tests/test_dispatcher.py::test_dispatcher_successful_delivery PASSED
tests/test_dispatcher.py::test_dispatcher_retry_and_dlq_escalation PASSED
tests/test_reconciler.py::test_reconciliation_clean_settlement PASSED
tests/test_reconciler.py::test_reconciliation_missing_in_ledger PASSED
tests/test_reconciler.py::test_reconciliation_missing_in_switch PASSED
tests/test_reconciler.py::test_reconciliation_volume_mismatch PASSED
tests/test_reconciler.py::test_reconciliation_undelivered_webhook PASSED
tests/test_server.py::test_health_check PASSED
tests/test_server.py::test_root_dashboard PASSED
tests/test_server.py::test_crypto_sign_and_verify PASSED
tests/test_server.py::test_publish_webhook_success PASSED
tests/test_server.py::test_publish_webhook_failure_and_dlq PASSED
tests/test_server.py::test_reconciliation_endpoint PASSED
```

---

## 12. License

MIT License. Copyright (c) 2026 Huighlet Eyram Zowonu.
