"""
ReliantHook-Engine: Zero-Loss Webhook Dispatcher & EOD Settlement Reconciler.
"""

from relianthook.backoff import (
    compute_decorrelated_jitter,
    compute_exponential_backoff,
    compute_full_jitter_backoff,
)
from relianthook.circuit import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitBreakerRegistry,
    CircuitState,
)
from relianthook.crypto import WebhookSecurityError, sign_payload, verify_signature
from relianthook.dispatcher import WebhookDispatcher
from relianthook.models import (
    DeliveryAttempt,
    DeliveryStatus,
    DiscrepancyType,
    ReconciliationReport,
    SettlementRecord,
    WebhookEvent,
)
from relianthook.reconciler import SettlementReconciler

__version__ = "1.0.0"

__all__ = [
    "WebhookDispatcher",
    "WebhookEvent",
    "DeliveryAttempt",
    "DeliveryStatus",
    "DiscrepancyType",
    "SettlementRecord",
    "ReconciliationReport",
    "SettlementReconciler",
    "CircuitBreaker",
    "CircuitBreakerRegistry",
    "CircuitState",
    "CircuitBreakerOpenError",
    "sign_payload",
    "verify_signature",
    "WebhookSecurityError",
    "compute_exponential_backoff",
    "compute_full_jitter_backoff",
    "compute_decorrelated_jitter",
]
