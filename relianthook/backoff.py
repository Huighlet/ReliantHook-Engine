"""
ReliantHook-Engine Retry Scheduling & Jitter Algorithms.
Prevents the Thundering Herd problem using Full Jitter and Decorrelated Jitter algorithms.
"""

from __future__ import annotations

import random


def compute_exponential_backoff(
    retry_attempt: int,
    base_backoff_sec: float = 1.0,
    max_backoff_sec: float = 300.0,
) -> float:
    """
    Standard deterministic exponential backoff: base * 2^retry.
    """
    exponent = max(0, retry_attempt)
    raw = base_backoff_sec * (2 ** exponent)
    return min(max_backoff_sec, raw)


def compute_full_jitter_backoff(
    retry_attempt: int,
    base_backoff_sec: float = 1.0,
    max_backoff_sec: float = 300.0,
) -> float:
    """
    Full Jitter Algorithm (AWS / Google SRE Standard):
      Sleep = random(0, min(max_backoff, base * 2^retry))
    Evenly distributes retry load across time, eliminating synchronized retry spikes.
    """
    ceiling = compute_exponential_backoff(retry_attempt, base_backoff_sec, max_backoff_sec)
    return random.uniform(0.0, ceiling)


def compute_decorrelated_jitter(
    previous_backoff_sec: float,
    base_backoff_sec: float = 1.0,
    max_backoff_sec: float = 300.0,
) -> float:
    """
    Decorrelated Jitter Algorithm:
      Sleep = min(max_backoff, random(base, prev_sleep * 3))
    Provides smooth progressive backoff without strict power-of-two lockstep.
    """
    ceiling = previous_backoff_sec * 3.0
    val = random.uniform(base_backoff_sec, max(base_backoff_sec, ceiling))
    return min(max_backoff_sec, val)
