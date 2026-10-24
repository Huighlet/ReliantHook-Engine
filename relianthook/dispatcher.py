"""
ReliantHook-Engine Resilient Webhook Dispatcher.
Thread-pooled HTTP dispatching with HMAC-SHA256 headers, circuit breaker isolation,
Full Jitter retries, and Dead-Letter Queue (DLQ) escalation.
"""

from __future__ import annotations

import concurrent.futures
import threading
import time
import urllib.request
import urllib.error
from typing import Callable, Dict, List, Optional

from relianthook.backoff import compute_full_jitter_backoff
from relianthook.circuit import CircuitBreakerOpenError, CircuitBreakerRegistry
from relianthook.crypto import sign_payload
from relianthook.models import DeliveryAttempt, DeliveryStatus, WebhookEvent

# Transport function signature: (url, headers, body) -> (status_code, response_text)
TransportCallable = Callable[[str, Dict[str, str], str], tuple[int, str]]


def default_urllib_transport(url: str, headers: Dict[str, str], body: str) -> tuple[int, str]:
    """Default HTTP transport using standard library urllib."""
    data_bytes = body.encode("utf-8")
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            return resp.status, content
    except urllib.error.HTTPError as e:
        content = e.read().decode("utf-8", errors="replace")
        return e.code, content
    except Exception as e:
        raise ConnectionError(f"Network transport error: {e}") from e


class WebhookDispatcher:
    """
    High-Throughput Webhook Dispatch Coordinator.
    """
    def __init__(
        self,
        max_workers: int = 16,
        circuit_registry: Optional[CircuitBreakerRegistry] = None,
        transport: Optional[TransportCallable] = None,
        base_backoff_sec: float = 1.0,
        max_backoff_sec: float = 60.0,
    ) -> None:
        self.max_workers = max_workers
        self.circuits = circuit_registry or CircuitBreakerRegistry()
        self.transport = transport or default_urllib_transport
        self.base_backoff = base_backoff_sec
        self.max_backoff = max_backoff_sec

        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self._events: Dict[str, WebhookEvent] = {}
        self._dlq: Dict[str, WebhookEvent] = {}
        self._lock = threading.Lock()

        # Telemetry counters
        self._total_dispatched = 0
        self._total_delivered = 0
        self._total_failed_attempts = 0

    def dispatch(self, event: WebhookEvent) -> DeliveryAttempt:
        """
        Synchronously attempt single dispatch of a webhook event.
        Calculates HMAC, tests circuit breaker, invokes transport, and records telemetry.
        """
        endpoint = event.destination_url
        breaker = self.circuits.get(endpoint)

        with self._lock:
            self._total_dispatched += 1
            self._events[event.event_id] = event

        # Check circuit breaker
        try:
            breaker.allow_request()
        except CircuitBreakerOpenError as e:
            attempt = DeliveryAttempt(
                attempt_number=event.retry_count + 1,
                http_status_code=None,
                latency_ms=0.0,
                error_message=str(e),
            )
            event.record_attempt(attempt)
            self._handle_retry_or_dlq(event)
            return attempt

        # Compute HMAC-SHA256 signature header
        sig_header = sign_payload(event.payload, event.secret_key)
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "ReliantHook-Engine/1.0",
            "X-Webhook-Id": event.event_id,
            "X-Webhook-Event": event.event_type,
            "X-Webhook-Signature": sig_header,
        }

        t0 = time.perf_counter()
        status_code = None
        error_msg = None

        try:
            status_code, _ = self.transport(endpoint, headers, event.payload)
            latency_ms = (time.perf_counter() - t0) * 1000.0

            if 200 <= status_code < 300:
                breaker.record_success()
                with self._lock:
                    self._total_delivered += 1
            else:
                breaker.record_failure()
                error_msg = f"Non-2xx HTTP response: {status_code}"
                with self._lock:
                    self._total_failed_attempts += 1

        except Exception as exc:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            breaker.record_failure()
            error_msg = str(exc)
            with self._lock:
                self._total_failed_attempts += 1

        attempt = DeliveryAttempt(
            attempt_number=event.retry_count + 1,
            http_status_code=status_code,
            latency_ms=latency_ms,
            error_message=error_msg,
        )
        event.record_attempt(attempt)
        self._handle_retry_or_dlq(event)
        return attempt

    def _handle_retry_or_dlq(self, event: WebhookEvent) -> None:
        """Schedule next backoff retry or escalate to Dead-Letter Queue."""
        if event.status == DeliveryStatus.FAILED_RETRYING:
            delay = compute_full_jitter_backoff(
                retry_attempt=event.retry_count,
                base_backoff_sec=self.base_backoff,
                max_backoff_sec=self.max_backoff,
            )
            event.next_attempt_at = time.time() + delay
        elif event.status == DeliveryStatus.DEAD_LETTER:
            with self._lock:
                self._dlq[event.event_id] = event

    def dispatch_async(self, event: WebhookEvent) -> concurrent.futures.Future:
        """Enqueue event for non-blocking asynchronous dispatch."""
        return self._executor.submit(self.dispatch, event)

    def replay_dlq_event(self, event_id: str) -> DeliveryAttempt:
        """Replay an unresolvable event from the Dead-Letter Queue."""
        with self._lock:
            event = self._dlq.get(event_id)
            if event is None:
                raise KeyError(f"Event '{event_id}' not found in Dead-Letter Queue.")
            del self._dlq[event_id]
            event.retry_count = 0
            event.status = DeliveryStatus.PENDING

        return self.dispatch(event)

    def get_dlq_events(self) -> List[WebhookEvent]:
        with self._lock:
            return list(self._dlq.values())

    def get_telemetry(self) -> dict:
        """Retrieve aggregated engine telemetry."""
        with self._lock:
            return {
                "total_dispatched": self._total_dispatched,
                "total_delivered": self._total_delivered,
                "total_failed_attempts": self._total_failed_attempts,
                "dlq_count": len(self._dlq),
                "active_events": len(self._events),
            }

    def shutdown(self, wait: bool = True) -> None:
        """Cleanly terminate worker threads."""
        self._executor.shutdown(wait=wait)
