"""
ReliantHook-Engine End-of-Day (EOD) 3-Way Settlement Reconciler.
Cross-audits clearing switch traces, core ledger entries, and webhook delivery logs
to detect floating funds, missing ledger posts, and undelivered merchant notifications.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from relianthook.models import DiscrepancyType, ReconciliationReport, SettlementRecord


class SettlementReconciler:
    """
    3-Way Financial Settlement Reconciliation Engine.
    """
    def __init__(self) -> None:
        pass

    def reconcile(
        self,
        reconciliation_date: str,
        switch_records: List[Dict[str, Any]],
        ledger_records: List[Dict[str, Any]],
        webhook_records: List[Dict[str, Any]],
    ) -> ReconciliationReport:
        """
        Execute 3-way reconciliation across Switch, Ledger, and Webhooks.

        Expected record keys:
          - switch_records:  {'rrn': str, 'amount': int, 'fee': int, 'status': str}
          - ledger_records:  {'rrn': str, 'amount': int, 'status': str}
          - webhook_records: {'rrn': str, 'status': str}  # e.g. DELIVERED
        """
        # Index records by RRN (Retrieval Reference Number)
        switch_map = {r["rrn"]: r for r in switch_records if "rrn" in r}
        ledger_map = {r["rrn"]: r for r in ledger_records if "rrn" in r}
        webhook_map = {r["rrn"]: r for r in webhook_records if "rrn" in r}

        all_rrns = set(switch_map.keys()) | set(ledger_map.keys()) | set(webhook_map.keys())

        matched_count = 0
        net_switch_volume = sum(r.get("amount", 0) for r in switch_records)
        net_ledger_volume = sum(r.get("amount", 0) for r in ledger_records)
        discrepancies: List[dict[str, Any]] = []

        for rrn in sorted(all_rrns):
            in_switch = rrn in switch_map
            in_ledger = rrn in ledger_map
            in_webhook = rrn in webhook_map

            switch_entry = switch_map.get(rrn)
            ledger_entry = ledger_map.get(rrn)
            webhook_entry = webhook_map.get(rrn)

            # Case 1: Missing in Ledger (Cleared on switch, but no ledger post)
            if in_switch and not in_ledger:
                discrepancies.append({
                    "rrn": rrn,
                    "type": DiscrepancyType.MISSING_IN_LEDGER,
                    "amount": switch_entry.get("amount", 0),
                    "details": "Transaction cleared at bank switch but missing from internal ledger.",
                })
                continue

            # Case 2: Missing in Switch (Posted in ledger, but no clearing switch authorization)
            if in_ledger and not in_switch:
                discrepancies.append({
                    "rrn": rrn,
                    "type": DiscrepancyType.MISSING_IN_SWITCH,
                    "amount": ledger_entry.get("amount", 0),
                    "details": "Transaction posted in internal ledger without clearing switch record.",
                })
                continue

            # Case 3: Volume / Amount Mismatch
            if in_switch and in_ledger:
                s_amt = switch_entry.get("amount", 0)
                l_amt = ledger_entry.get("amount", 0)
                if s_amt != l_amt:
                    discrepancies.append({
                        "rrn": rrn,
                        "type": DiscrepancyType.VOLUME_MISMATCH,
                        "switch_amount": s_amt,
                        "ledger_amount": l_amt,
                        "variance": s_amt - l_amt,
                        "details": f"Amount mismatch: Switch cleared {s_amt}, Ledger recorded {l_amt}.",
                    })
                    continue

            # Case 4: Undelivered Webhook (Money settled, but merchant was not notified)
            webhook_status = webhook_entry.get("status") if webhook_entry else None
            if in_switch and in_ledger:
                if not in_webhook or webhook_status != "DELIVERED":
                    discrepancies.append({
                        "rrn": rrn,
                        "type": DiscrepancyType.UNDELIVERED_WEBHOOK,
                        "amount": ledger_entry.get("amount", 0),
                        "webhook_status": webhook_status or "NOT_TRIGGERED",
                        "details": "Financial settlement completed, but merchant webhook delivery failed.",
                    })
                    continue

            # Case 5: Fully Matched & Reconciled
            matched_count += 1

        volume_variance = net_switch_volume - net_ledger_volume

        return ReconciliationReport(
            reconciliation_date=reconciliation_date,
            total_records=len(all_rrns),
            matched_count=matched_count,
            discrepancy_count=len(discrepancies),
            net_switch_volume=net_switch_volume,
            net_ledger_volume=net_ledger_volume,
            volume_variance=volume_variance,
            discrepancies=discrepancies,
        )
