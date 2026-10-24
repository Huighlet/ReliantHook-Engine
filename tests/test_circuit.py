"""
Unit tests for the Circuit Breaker pattern.
"""

import time
import pytest

from relianthook.circuit import CircuitBreaker, CircuitBreakerOpenError, CircuitState


def test_circuit_breaker_lifecycle():
    """Verify state transitions: CLOSED -> OPEN -> HALF_OPEN -> CLOSED."""
    cb = CircuitBreaker("https://api.merchant.com", failure_threshold=3, cooldown_seconds=0.1)
    assert cb.state == CircuitState.CLOSED
    assert cb.allow_request() is True

    # 1. Record 2 failures (below threshold)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED

    # 2. Third failure trips the breaker to OPEN
    cb.record_failure()
    assert cb.state == CircuitState.OPEN

    # 3. In OPEN state, requests are fast-failed
    with pytest.raises(CircuitBreakerOpenError):
        cb.allow_request()

    # 4. Wait for cooldown
    time.sleep(0.12)
    assert cb.state == CircuitState.HALF_OPEN

    # 5. Successful probe resets circuit to CLOSED
    assert cb.allow_request() is True
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


def test_circuit_breaker_half_open_failure_reopens():
    """Verify that a failure in HALF_OPEN immediately trips back to OPEN."""
    cb = CircuitBreaker("https://api.failing.com", failure_threshold=2, cooldown_seconds=0.1)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN

    time.sleep(0.12)
    assert cb.state == CircuitState.HALF_OPEN

    # Probe fails
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
