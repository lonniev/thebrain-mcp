"""Credit management tools: purchase_credits, check_payment, check_balance."""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from thebrain_mcp.btcpay_client import BTCPayClient, BTCPayError
from thebrain_mcp.ledger_cache import LedgerCache

logger = logging.getLogger(__name__)

# Default credit multiplier for users not in tier config
_DEFAULT_MULTIPLIER = 1


def _get_multiplier(
    user_id: str,
    tier_config_json: str | None,
    user_tiers_json: str | None,
) -> int:
    """Look up credit multiplier for a user based on tier config."""
    if not tier_config_json or not user_tiers_json:
        return _DEFAULT_MULTIPLIER

    try:
        tier_config = json.loads(tier_config_json)
        user_tiers = json.loads(user_tiers_json)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Invalid tier config JSON; using default multiplier.")
        return _DEFAULT_MULTIPLIER

    tier_name = user_tiers.get(user_id, "default")
    tier = tier_config.get(tier_name, tier_config.get("default", {}))
    return int(tier.get("credit_multiplier", _DEFAULT_MULTIPLIER))


async def purchase_credits_tool(
    btcpay: BTCPayClient,
    cache: LedgerCache,
    user_id: str,
    amount_sats: int,
) -> dict[str, Any]:
    """Create a BTCPay invoice and record it as pending in the user's ledger."""
    if amount_sats <= 0:
        return {"success": False, "error": "amount_sats must be positive."}

    try:
        invoice = await btcpay.create_invoice(
            amount_sats,
            metadata={"user_id": user_id, "purpose": "credit_purchase"},
        )
    except BTCPayError as e:
        return {"success": False, "error": f"BTCPay error: {e}"}

    invoice_id = invoice.get("id", "")
    checkout_link = invoice.get("checkoutLink", "")
    expiry = invoice.get("expirationTime", "")

    # Record pending invoice
    ledger = await cache.get(user_id)
    ledger.pending_invoices.append(invoice_id)
    cache.mark_dirty(user_id)

    return {
        "success": True,
        "invoice_id": invoice_id,
        "amount_sats": amount_sats,
        "checkout_link": checkout_link,
        "expiration": expiry,
        "message": (
            f"Invoice created for {amount_sats:,} sats.\n\n"
            f"Pay here: {checkout_link}\n"
            f"Expires: {expiry}\n\n"
            f'After paying, call check_payment with invoice_id: "{invoice_id}"'
        ),
    }


async def check_payment_tool(
    btcpay: BTCPayClient,
    cache: LedgerCache,
    user_id: str,
    invoice_id: str,
    tier_config_json: str | None = None,
    user_tiers_json: str | None = None,
) -> dict[str, Any]:
    """Poll BTCPay invoice status. Credit balance on settlement (idempotent)."""
    try:
        invoice = await btcpay.get_invoice(invoice_id)
    except BTCPayError as e:
        return {"success": False, "error": f"BTCPay error: {e}"}

    status = invoice.get("status", "Unknown")
    additional = invoice.get("additionalStatus", "")
    ledger = await cache.get(user_id)

    result: dict[str, Any] = {
        "success": True,
        "invoice_id": invoice_id,
        "status": status,
    }
    if additional:
        result["additional_status"] = additional

    if status == "New":
        result["message"] = "Invoice created, awaiting payment."

    elif status == "Processing":
        result["message"] = "Payment seen, waiting for confirmation."

    elif status == "Settled":
        if invoice_id in ledger.pending_invoices:
            # Credit the user
            amount_str = invoice.get("amount", "0")
            amount_sats = int(float(amount_str))
            multiplier = _get_multiplier(user_id, tier_config_json, user_tiers_json)
            credited = amount_sats * multiplier
            ledger.credit_deposit(credited, invoice_id)
            cache.mark_dirty(user_id)
            result["credits_granted"] = credited
            result["multiplier"] = multiplier
            result["message"] = f"Payment settled! {credited:,} credits added to your balance."
        else:
            result["message"] = "Payment already credited."
            result["credits_granted"] = 0

    elif status == "Expired":
        if invoice_id in ledger.pending_invoices:
            ledger.pending_invoices.remove(invoice_id)
            cache.mark_dirty(user_id)
        result["message"] = "Invoice expired. Create a new one with purchase_credits."

    elif status == "Invalid":
        if invoice_id in ledger.pending_invoices:
            ledger.pending_invoices.remove(invoice_id)
            cache.mark_dirty(user_id)
        result["message"] = "Payment invalid."

    else:
        result["message"] = f"Unknown invoice status: {status}"

    result["balance_sats"] = ledger.balance_sats
    return result


async def check_balance_tool(
    cache: LedgerCache,
    user_id: str,
) -> dict[str, Any]:
    """Return the user's current credit balance and usage summary."""
    ledger = await cache.get(user_id)
    today = date.today().isoformat()

    result: dict[str, Any] = {
        "success": True,
        "balance_sats": ledger.balance_sats,
        "total_deposited_sats": ledger.total_deposited_sats,
        "total_consumed_sats": ledger.total_consumed_sats,
        "pending_invoices": len(ledger.pending_invoices),
        "last_deposit_at": ledger.last_deposit_at,
    }

    # Include today's usage if available
    today_log = ledger.daily_log.get(today)
    if today_log:
        result["today_usage"] = {
            tool: {"calls": u.calls, "sats": u.sats}
            for tool, u in today_log.items()
        }

    return result
