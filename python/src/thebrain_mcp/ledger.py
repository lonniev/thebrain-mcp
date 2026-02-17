"""Per-user credit ledger for tool-call metering.

Pure data model — no I/O. All amounts are in satoshis (integer arithmetic).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# ToolUsage
# ---------------------------------------------------------------------------


@dataclass
class ToolUsage:
    """Aggregate usage counter for a single tool."""

    calls: int = 0
    sats: int = 0

    def to_dict(self) -> dict[str, int]:
        return {"calls": self.calls, "sats": self.sats}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolUsage:
        return cls(
            calls=int(data.get("calls", 0)),
            sats=int(data.get("sats", 0)),
        )


# ---------------------------------------------------------------------------
# UserLedger
# ---------------------------------------------------------------------------


@dataclass
class UserLedger:
    """Per-user credit balance and usage tracking.

    All monetary values are in satoshis (integers only).
    ``debit()`` returns False on insufficient balance (not exceptional).
    ``from_json()`` returns a fresh ledger on corrupt data (never blocks a user).
    """

    balance_sats: int = 0
    total_deposited_sats: int = 0
    total_consumed_sats: int = 0
    pending_invoices: list[str] = field(default_factory=list)
    credited_invoices: list[str] = field(default_factory=list)
    last_deposit_at: str | None = None
    daily_log: dict[str, dict[str, ToolUsage]] = field(default_factory=dict)
    history: dict[str, ToolUsage] = field(default_factory=dict)

    # -- mutations ------------------------------------------------------------

    def debit(self, tool_name: str, sats: int) -> bool:
        """Deduct ``sats`` from balance. Returns False if insufficient."""
        if sats < 0:
            return False
        if self.balance_sats < sats:
            return False

        self.balance_sats -= sats
        self.total_consumed_sats += sats

        today = date.today().isoformat()
        day_log = self.daily_log.setdefault(today, {})
        usage = day_log.setdefault(tool_name, ToolUsage())
        usage.calls += 1
        usage.sats += sats

        agg = self.history.setdefault(tool_name, ToolUsage())
        agg.calls += 1
        agg.sats += sats

        return True

    def credit_deposit(self, sats: int, invoice_id: str) -> None:
        """Add credits from a settled invoice."""
        self.balance_sats += sats
        self.total_deposited_sats += sats
        self.last_deposit_at = date.today().isoformat()
        if invoice_id in self.pending_invoices:
            self.pending_invoices.remove(invoice_id)
        if invoice_id not in self.credited_invoices:
            self.credited_invoices.append(invoice_id)

    def rollback_debit(self, tool_name: str, sats: int) -> None:
        """Undo a previous debit (e.g. tool call failed)."""
        self.balance_sats += sats
        self.total_consumed_sats -= sats

        today = date.today().isoformat()
        day_log = self.daily_log.get(today, {})
        usage = day_log.get(tool_name)
        if usage:
            usage.calls = max(0, usage.calls - 1)
            usage.sats = max(0, usage.sats - sats)

        agg = self.history.get(tool_name)
        if agg:
            agg.calls = max(0, agg.calls - 1)
            agg.sats = max(0, agg.sats - sats)

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
            "balance_sats": self.balance_sats,
            "total_deposited_sats": self.total_deposited_sats,
            "total_consumed_sats": self.total_consumed_sats,
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
        })

    @classmethod
    def from_json(cls, data: str) -> UserLedger:
        """Deserialize from JSON. Returns fresh ledger on corrupt/missing data."""
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

        return cls(
            balance_sats=int(obj.get("balance_sats", 0)),
            total_deposited_sats=int(obj.get("total_deposited_sats", 0)),
            total_consumed_sats=int(obj.get("total_consumed_sats", 0)),
            pending_invoices=list(obj.get("pending_invoices", [])),
            credited_invoices=list(obj.get("credited_invoices", [])),
            last_deposit_at=obj.get("last_deposit_at"),
            daily_log=daily_log,
            history=history,
        )
