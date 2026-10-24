"""
ReliantHook-Engine Domain Models.
Structured data representations for Webhook Events, Delivery Telemetry, and Settlement Records.
"""

from __future__ import annotations

import dataclasses
import enum
import time
from typing import Any, List, Optional


class DeliveryStatus(enum.StrEnum):
    """Lifecycle status of a webhook dispatch event."""
    PENDING = "PENDING"
    IN_FLIGHT = "IN_FLIGHT"
    DELIVERED = "DELIVERED"
    FAILED_RETRYING = "FAILED_RETRYING"
    DEAD_LETTER = "DEAD_LETTER"


@dataclasses.dataclass(slots=True)
class DeliveryAttempt:
    """Telemetry capture for an individual HTTP delivery attempt."""
    attempt_number: int
    http_status_code: Optional[int]
    latency_ms: float
    error_message: Optional[str]
    timestamp_ns: int = dataclasses.field(default_factory=time.time_ns)

    @property
    def is_success(self) -> bool:
        """HTTP 2xx denotes successful acknowledgement."""
        return self.http_status_code is not None and 200 <= self.http_status_code < 300


@dataclasses.dataclass(slots=True)
class WebhookEvent:
    """Webhook dispatch entity with delivery history and retry schedule."""
    event_id: str
    destination_url: str
    event_type: str
    payload: str
    secret_key: str
    status: DeliveryStatus = DeliveryStatus.PENDING
    max_retries: int = 5
    retry_count: int = 0
    next_attempt_at: float = 0.0
    attempts: List[DeliveryAttempt] = dataclasses.field(default_factory=list)
    created_at_ns: int = dataclasses.field(default_factory=time.time_ns)

    def record_attempt(self, attempt: DeliveryAttempt) -> None:
        """Append attempt telemetry and update execution status."""
        self.attempts.append(attempt)
        if attempt.is_success:
            self.status = DeliveryStatus.DELIVERED
        else:
            self.retry_count += 1
            if self.retry_count >= self.max_retries:
                self.status = DeliveryStatus.DEAD_LETTER
            else:
                self.status = DeliveryStatus.FAILED_RETRYING


class DiscrepancyType(enum.StrEnum):
    """Classification of reconciliation variance between Switch, Ledger, and Webhook."""
    MATCHED = "MATCHED"
    MISSING_IN_LEDGER = "MISSING_IN_LEDGER"
    MISSING_IN_SWITCH = "MISSING_IN_SWITCH"
    UNDELIVERED_WEBHOOK = "UNDELIVERED_WEBHOOK"
    VOLUME_MISMATCH = "VOLUME_MISMATCH"


@dataclasses.dataclass(slots=True, frozen=True)
class SettlementRecord:
    """Internal clearing record uniting Switch, Ledger, and Webhook audit traces."""
    tx_id: str
    rrn: str
    amount: int  # in minor units (e.g. pesewas)
    fee: int
    currency: str
    cleared_at_switch: bool
    settled_in_ledger: bool
    webhook_delivered: bool


@dataclasses.dataclass(slots=True)
class ReconciliationReport:
    """Comprehensive End-of-Day (EOD) audit verification summary."""
    reconciliation_date: str
    total_records: int
    matched_count: int
    discrepancy_count: int
    net_switch_volume: int
    net_ledger_volume: int
    volume_variance: int
    discrepancies: List[dict[str, Any]] = dataclasses.field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        """True if zero discrepancies exist and volumes balance perfectly."""
        return self.discrepancy_count == 0 and self.volume_variance == 0
