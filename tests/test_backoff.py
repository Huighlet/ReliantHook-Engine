"""
Unit tests for retry scheduling and Full Jitter algorithms.
"""

from relianthook.backoff import (
    compute_decorrelated_jitter,
    compute_exponential_backoff,
    compute_full_jitter_backoff,
)


def test_exponential_backoff_bounds():
    """Verify exponential scaling with maximum ceiling cap."""
    assert compute_exponential_backoff(0, base_backoff_sec=1.0, max_backoff_sec=60.0) == 1.0
    assert compute_exponential_backoff(1, base_backoff_sec=1.0, max_backoff_sec=60.0) == 2.0
    assert compute_exponential_backoff(2, base_backoff_sec=1.0, max_backoff_sec=60.0) == 4.0
    assert compute_exponential_backoff(3, base_backoff_sec=1.0, max_backoff_sec=60.0) == 8.0
    # Exceeding cap
    assert compute_exponential_backoff(10, base_backoff_sec=1.0, max_backoff_sec=60.0) == 60.0


def test_full_jitter_distribution():
    """Verify full jitter stays within [0, ceiling]."""
    for attempt in range(5):
        ceiling = compute_exponential_backoff(attempt, base_backoff_sec=2.0, max_backoff_sec=30.0)
        for _ in range(20):
            jittered = compute_full_jitter_backoff(attempt, base_backoff_sec=2.0, max_backoff_sec=30.0)
            assert 0.0 <= jittered <= ceiling


def test_decorrelated_jitter_bounds():
    """Verify decorrelated jitter remains within bounds."""
    prev = 2.0
    for _ in range(10):
        next_val = compute_decorrelated_jitter(prev, base_backoff_sec=1.0, max_backoff_sec=50.0)
        assert 1.0 <= next_val <= 50.0
        prev = next_val
