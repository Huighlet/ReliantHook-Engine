"""
ReliantHook-Engine Circuit Breaker Pattern.
Prevents cascading worker thread starvation by fast-failing traffic to failing merchant endpoints.
"""

from __future__ import annotations

import enum
import threading
import time
from typing import Dict


class CircuitState(enum.StrEnum):
    """Lifecycle state of an endpoint circuit breaker."""
    CLOSED = "CLOSED"          # Normal operation: deliveries allowed
    OPEN = "OPEN"              # Tripped: deliveries fast-failed
    HALF_OPEN = "HALF_OPEN"    # Probe testing recovery


class CircuitBreakerOpenError(Exception):
    """Raised when an attempt is made against an endpoint with an OPEN circuit."""


class CircuitBreaker:
    """
    State machine monitoring failure rates for a single destination endpoint.
    """
    def __init__(
        self,
        endpoint_id: str,
        failure_threshold: int = 5,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self.endpoint_id = endpoint_id
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at: float = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._evaluate_state_transition()
            return self._state

    def _evaluate_state_transition(self) -> None:
        """Evaluate if an OPEN circuit has passed its cooldown period."""
        if self._state == CircuitState.OPEN:
            elapsed = time.time() - self._opened_at
            if elapsed >= self.cooldown_seconds:
                self._state = CircuitState.HALF_OPEN

    def allow_request(self) -> bool:
        """
        Check if request should be allowed through.
        Raises CircuitBreakerOpenError if circuit is tripped in OPEN state.
        """
        with self._lock:
            self._evaluate_state_transition()

            if self._state == CircuitState.OPEN:
                raise CircuitBreakerOpenError(
                    f"Circuit Breaker for endpoint '{self.endpoint_id}' is OPEN. Fast-failing delivery."
                )
            return True

    def record_success(self) -> None:
        """Reset failure counts on successful HTTP response."""
        with self._lock:
            self._consecutive_failures = 0
            self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Increment failure count and trip to OPEN if threshold reached."""
        with self._lock:
            self._consecutive_failures += 1
            if self._state == CircuitState.HALF_OPEN or self._consecutive_failures >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = time.time()


class CircuitBreakerRegistry:
    """Thread-safe registry mapping destination endpoints to CircuitBreakers."""
    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 30.0) -> None:
        self.default_threshold = failure_threshold
        self.default_cooldown = cooldown_seconds
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

    def get(self, endpoint_url: str) -> CircuitBreaker:
        """Retrieve or create CircuitBreaker for a given endpoint."""
        with self._lock:
            if endpoint_url not in self._breakers:
                self._breakers[endpoint_url] = CircuitBreaker(
                    endpoint_id=endpoint_url,
                    failure_threshold=self.default_threshold,
                    cooldown_seconds=self.default_cooldown,
                )
            return self._breakers[endpoint_url]
