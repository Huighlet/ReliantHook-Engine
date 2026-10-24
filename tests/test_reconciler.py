"""
Unit tests for the 3-Way End-of-Day Settlement Reconciler.
"""

from relianthook.models import DiscrepancyType
from relianthook.reconciler import SettlementReconciler


def test_reconciliation_clean_settlement():
    """Verify that perfectly matched switch, ledger, and webhook records produce a clean audit report."""
    reconciler = SettlementReconciler()

    switch = [{"rrn": "RRN_01", "amount": 10000, "status": "APPROVED"}]
    ledger = [{"rrn": "RRN_01", "amount": 10000, "status": "COMMITTED"}]
    webhook = [{"rrn": "RRN_01", "status": "DELIVERED"}]

    report = reconciler.reconcile("2026-10-24", switch, ledger, webhook)
    assert report.is_clean is True
    assert report.total_records == 1
    assert report.matched_count == 1
    assert report.discrepancy_count == 0
    assert report.volume_variance == 0


def test_reconciliation_missing_in_ledger():
    """Verify detection when switch cleared money but ledger record is absent."""
    reconciler = SettlementReconciler()

    switch = [{"rrn": "RRN_02", "amount": 5000, "status": "APPROVED"}]
    ledger = []
    webhook = []

    report = reconciler.reconcile("2026-10-24", switch, ledger, webhook)
    assert report.is_clean is False
    assert report.discrepancy_count == 1
    assert report.discrepancies[0]["type"] == DiscrepancyType.MISSING_IN_LEDGER
    assert report.discrepancies[0]["rrn"] == "RRN_02"


def test_reconciliation_missing_in_switch():
    """Verify detection when ledger has entry without clearing switch authorization."""
    reconciler = SettlementReconciler()

    switch = []
    ledger = [{"rrn": "RRN_03", "amount": 7500, "status": "COMMITTED"}]
    webhook = [{"rrn": "RRN_03", "status": "DELIVERED"}]

    report = reconciler.reconcile("2026-10-24", switch, ledger, webhook)
    assert report.is_clean is False
    assert report.discrepancies[0]["type"] == DiscrepancyType.MISSING_IN_SWITCH


def test_reconciliation_volume_mismatch():
    """Verify detection when switch cleared amount differs from ledger amount."""
    reconciler = SettlementReconciler()

    switch = [{"rrn": "RRN_04", "amount": 10000, "status": "APPROVED"}]
    ledger = [{"rrn": "RRN_04", "amount": 9500, "status": "COMMITTED"}]
    webhook = [{"rrn": "RRN_04", "status": "DELIVERED"}]

    report = reconciler.reconcile("2026-10-24", switch, ledger, webhook)
    assert report.is_clean is False
    assert report.discrepancies[0]["type"] == DiscrepancyType.VOLUME_MISMATCH
    assert report.discrepancies[0]["variance"] == 500


def test_reconciliation_undelivered_webhook():
    """Verify detection when money settled at switch and ledger, but merchant webhook failed."""
    reconciler = SettlementReconciler()

    switch = [{"rrn": "RRN_05", "amount": 20000, "status": "APPROVED"}]
    ledger = [{"rrn": "RRN_05", "amount": 20000, "status": "COMMITTED"}]
    webhook = [{"rrn": "RRN_05", "status": "FAILED_RETRYING"}]

    report = reconciler.reconcile("2026-10-24", switch, ledger, webhook)
    assert report.is_clean is False
    assert report.discrepancies[0]["type"] == DiscrepancyType.UNDELIVERED_WEBHOOK
