"""Per-user credit ledger for tool-call metering.

Pure data model — no I/O. All api_sats values are integer API credits
(not real Bitcoin satoshis). Real BTC amounts use ``amount_sats`` and
only appear in invoice/BTCPay contexts.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 3


# ---------------------------------------------------------------------------
# ToolUsage
# ---------------------------------------------------------------------------


@dataclass
class ToolUsage:
    """Aggregate usage counter for a single tool."""

    calls: int = 0
    api_sats: int = 0

    def to_dict(self) -> dict[str, int]:
        return {"calls": self.calls, "api_sats": self.api_sats}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolUsage:
        return cls(
            calls=int(data.get("calls", 0)),
            # Migration: accept old "sats" key or new "api_sats"
            api_sats=int(data.get("api_sats", data.get("sats", 0))),
        )


# ---------------------------------------------------------------------------
# InvoiceRecord
# ---------------------------------------------------------------------------


@dataclass
class InvoiceRecord:
    """Append-only record of a single BTCPay invoice."""

    invoice_id: str
    amount_sats: int  # Real BTC satoshis (never rename to api_sats)
    api_sats_credited: int = 0  # Multiplied credits granted
    multiplier: int = 1
    status: str = "Pending"  # Pending | Settled | Expired | Invalid
    created_at: str = ""  # ISO datetime
    settled_at: str | None = None
    btcpay_status: str | None = None  # Raw BTCPay status string

    def to_dict(self) -> dict[str, Any]:
        return {
            "invoice_id": self.invoice_id,
            "amount_sats": self.amount_sats,
            "api_sats_credited": self.api_sats_credited,
            "multiplier": self.multiplier,
            "status": self.status,
            "created_at": self.created_at,
            "settled_at": self.settled_at,
            "btcpay_status": self.btcpay_status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InvoiceRecord:
        return cls(
            invoice_id=str(data.get("invoice_id", "")),
            amount_sats=int(data.get("amount_sats", 0)),
            api_sats_credited=int(data.get("api_sats_credited", 0)),
            multiplier=int(data.get("multiplier", 1)),
            status=str(data.get("status", "Pending")),
            created_at=str(data.get("created_at", "")),
            settled_at=data.get("settled_at"),
            btcpay_status=data.get("btcpay_status"),
        )


# ---------------------------------------------------------------------------
# UserLedger
# ---------------------------------------------------------------------------


@dataclass
class UserLedger:
    """Per-user credit balance and usage tracking.

    All balance/cost values are in api_sats (integer API credits).
    ``debit()`` returns False on insufficient balance (not exceptional).
    ``from_json()`` returns a fresh ledger on corrupt data (never blocks a user).
    """

    balance_api_sats: int = 0
    total_deposited_api_sats: int = 0
    total_consumed_api_sats: int = 0
    pending_invoices: list[str] = field(default_factory=list)
    credited_invoices: list[str] = field(default_factory=list)
    last_deposit_at: str | None = None
    daily_log: dict[str, dict[str, ToolUsage]] = field(default_factory=dict)
    history: dict[str, ToolUsage] = field(default_factory=dict)
    invoices: dict[str, InvoiceRecord] = field(default_factory=dict)

    # -- invoice record helpers ------------------------------------------------

    def record_invoice_created(
        self, invoice_id: str, amount_sats: int, multiplier: int, created_at: str,
    ) -> None:
        """Record a newly created invoice (Pending status)."""
        self.invoices[invoice_id] = InvoiceRecord(
            invoice_id=invoice_id,
            amount_sats=amount_sats,
            multiplier=multiplier,
            status="Pending",
            created_at=created_at,
            btcpay_status="New",
        )

    def record_invoice_settled(
        self,
        invoice_id: str,
        api_sats_credited: int,
        settled_at: str,
        btcpay_status: str = "Settled",
    ) -> None:
        """Update an existing invoice record to Settled with credit info.

        Creates a retroactive record if the invoice wasn't tracked at creation
        (e.g. invoices created before this feature was deployed).
        """
        rec = self.invoices.get(invoice_id)
        if rec:
            rec.status = "Settled"
            rec.api_sats_credited = api_sats_credited
            rec.settled_at = settled_at
            rec.btcpay_status = btcpay_status
        else:
            self.invoices[invoice_id] = InvoiceRecord(
                invoice_id=invoice_id,
                amount_sats=0,  # Unknown — wasn't tracked at creation
                api_sats_credited=api_sats_credited,
                multiplier=0,  # Unknown
                status="Settled",
                created_at="",  # Unknown
                settled_at=settled_at,
                btcpay_status=btcpay_status,
            )

    def record_invoice_terminal(
        self, invoice_id: str, status: str, btcpay_status: str,
    ) -> None:
        """Update an existing invoice record to a terminal state (Expired/Invalid)."""
        rec = self.invoices.get(invoice_id)
        if rec:
            rec.status = status
            rec.btcpay_status = btcpay_status

    # -- mutations ------------------------------------------------------------

    def debit(self, tool_name: str, api_sats: int) -> bool:
        """Deduct ``api_sats`` from balance. Returns False if insufficient."""
        if api_sats < 0:
            return False
        if self.balance_api_sats < api_sats:
            return False

        self.balance_api_sats -= api_sats
        self.total_consumed_api_sats += api_sats

        today = date.today().isoformat()
        day_log = self.daily_log.setdefault(today, {})
        usage = day_log.setdefault(tool_name, ToolUsage())
        usage.calls += 1
        usage.api_sats += api_sats

        agg = self.history.setdefault(tool_name, ToolUsage())
        agg.calls += 1
        agg.api_sats += api_sats

        return True

    def credit_deposit(self, api_sats: int, invoice_id: str) -> None:
        """Add credits from a settled invoice."""
        self.balance_api_sats += api_sats
        self.total_deposited_api_sats += api_sats
        self.last_deposit_at = date.today().isoformat()
        if invoice_id in self.pending_invoices:
            self.pending_invoices.remove(invoice_id)
        if invoice_id not in self.credited_invoices:
            self.credited_invoices.append(invoice_id)

    def rollback_debit(self, tool_name: str, api_sats: int) -> None:
        """Undo a previous debit (e.g. tool call failed)."""
        self.balance_api_sats += api_sats
        self.total_consumed_api_sats -= api_sats

        today = date.today().isoformat()
        day_log = self.daily_log.get(today, {})
        usage = day_log.get(tool_name)
        if usage:
            usage.calls = max(0, usage.calls - 1)
            usage.api_sats = max(0, usage.api_sats - api_sats)

        agg = self.history.get(tool_name)
        if agg:
            agg.calls = max(0, agg.calls - 1)
            agg.api_sats = max(0, agg.api_sats - api_sats)

    def rotate_daily_log(self, retention_days: int = 30) -> None:
        """Fold daily entries older than ``retention_days`` into ``history``."""
        cutoff = (date.today() - timedelta(days=retention_days)).isoformat()
        expired_keys = [d for d in self.daily_log if d < cutoff]
        for day_key in expired_keys:
            for tool_name, usage in self.daily_log[day_key].items():
                # daily_log entries are already counted in history via debit(),
                # so we only remove the daily entry — no double-counting.
                pass
            del self.daily_log[day_key]

    # -- serialization --------------------------------------------------------

    def to_json(self) -> str:
        """Serialize to JSON string with schema version."""
        return json.dumps({
            "v": _SCHEMA_VERSION,
            "balance_api_sats": self.balance_api_sats,
            "total_deposited_api_sats": self.total_deposited_api_sats,
            "total_consumed_api_sats": self.total_consumed_api_sats,
            "pending_invoices": self.pending_invoices,
            "credited_invoices": self.credited_invoices,
            "last_deposit_at": self.last_deposit_at,
            "daily_log": {
                day: {tool: u.to_dict() for tool, u in tools.items()}
                for day, tools in self.daily_log.items()
            },
            "history": {
                tool: u.to_dict() for tool, u in self.history.items()
            },
            "invoices": {
                iid: rec.to_dict() for iid, rec in self.invoices.items()
            },
        })

    @classmethod
    def from_json(cls, data: str) -> UserLedger:
        """Deserialize from JSON. Returns fresh ledger on corrupt/missing data.

        Handles migration from v1 (``*_sats``) to v2 (``*_api_sats``) keys.
        """
        try:
            obj = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Ledger data is corrupt; returning fresh ledger.")
            return cls()

        if not isinstance(obj, dict):
            logger.warning("Ledger data is not a dict; returning fresh ledger.")
            return cls()

        daily_log: dict[str, dict[str, ToolUsage]] = {}
        raw_daily = obj.get("daily_log", {})
        if isinstance(raw_daily, dict):
            for day, tools in raw_daily.items():
                if isinstance(tools, dict):
                    daily_log[day] = {
                        t: ToolUsage.from_dict(u)
                        for t, u in tools.items()
                        if isinstance(u, dict)
                    }

        history: dict[str, ToolUsage] = {}
        raw_history = obj.get("history", {})
        if isinstance(raw_history, dict):
            history = {
                t: ToolUsage.from_dict(u)
                for t, u in raw_history.items()
                if isinstance(u, dict)
            }

        invoices: dict[str, InvoiceRecord] = {}
        raw_invoices = obj.get("invoices", {})
        if isinstance(raw_invoices, dict):
            for iid, rec_data in raw_invoices.items():
                if isinstance(rec_data, dict):
                    invoices[iid] = InvoiceRecord.from_dict(rec_data)

        # Migration: accept v1 keys (*_sats) or v2 keys (*_api_sats)
        def _get_int(new_key: str, old_key: str) -> int:
            return int(obj.get(new_key, obj.get(old_key, 0)))

        return cls(
            balance_api_sats=_get_int("balance_api_sats", "balance_sats"),
            total_deposited_api_sats=_get_int("total_deposited_api_sats", "total_deposited_sats"),
            total_consumed_api_sats=_get_int("total_consumed_api_sats", "total_consumed_sats"),
            pending_invoices=list(obj.get("pending_invoices", [])),
            credited_invoices=list(obj.get("credited_invoices", [])),
            last_deposit_at=obj.get("last_deposit_at"),
            daily_log=daily_log,
            history=history,
            invoices=invoices,
        )
