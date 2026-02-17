"""Credit management tools: purchase_credits, check_payment, check_balance, btcpay_status."""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from thebrain_mcp.btcpay_client import BTCPayClient, BTCPayAuthError, BTCPayError
from thebrain_mcp.config import Settings
from thebrain_mcp.ledger_cache import LedgerCache

logger = logging.getLogger(__name__)

# Default credit multiplier for users not in tier config
_DEFAULT_MULTIPLIER = 1


def _get_tier_info(
    user_id: str,
    tier_config_json: str | None,
    user_tiers_json: str | None,
) -> tuple[str, int]:
    """Look up tier name and credit multiplier for a user.

    Returns (tier_name, multiplier).
    """
    if not tier_config_json or not user_tiers_json:
        return "default", _DEFAULT_MULTIPLIER

    try:
        tier_config = json.loads(tier_config_json)
        user_tiers = json.loads(user_tiers_json)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Invalid tier config JSON; using default multiplier.")
        return "default", _DEFAULT_MULTIPLIER

    tier_name = user_tiers.get(user_id, "default")
    tier = tier_config.get(tier_name, tier_config.get("default", {}))
    return tier_name, int(tier.get("credit_multiplier", _DEFAULT_MULTIPLIER))


def _get_multiplier(
    user_id: str,
    tier_config_json: str | None,
    user_tiers_json: str | None,
) -> int:
    """Look up credit multiplier for a user based on tier config."""
    _, multiplier = _get_tier_info(user_id, tier_config_json, user_tiers_json)
    return multiplier


async def purchase_credits_tool(
    btcpay: BTCPayClient,
    cache: LedgerCache,
    user_id: str,
    amount_sats: int,
    tier_config_json: str | None = None,
    user_tiers_json: str | None = None,
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

    # Record pending invoice — flush immediately so the invoice survives cache loss
    ledger = await cache.get(user_id)
    ledger.pending_invoices.append(invoice_id)
    cache.mark_dirty(user_id)
    if not await cache.flush_user(user_id):
        logger.warning("Failed to flush pending invoice %s for %s.", invoice_id, user_id)

    tier_name, multiplier = _get_tier_info(user_id, tier_config_json, user_tiers_json)
    expected_credits = amount_sats * multiplier

    result: dict[str, Any] = {
        "success": True,
        "invoice_id": invoice_id,
        "amount_sats": amount_sats,
        "checkout_link": checkout_link,
        "expiration": expiry,
        "tier": tier_name,
        "multiplier": multiplier,
        "expected_credits": expected_credits,
        "message": (
            f"Invoice created for {amount_sats:,} sats.\n\n"
            f"Pay here: {checkout_link}\n"
            f"Expires: {expiry}\n"
            f"Tier: {tier_name} ({multiplier}x) — "
            f"you will receive {expected_credits:,} credits on settlement.\n\n"
            f'After paying, call check_payment with invoice_id: "{invoice_id}"'
        ),
    }
    return result


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
        if invoice_id in ledger.credited_invoices:
            # Already credited — true idempotency check
            result["message"] = "Payment already credited."
            result["credits_granted"] = 0
        else:
            # Credit the user — flush immediately so credits survive cache loss
            amount_str = invoice.get("amount", "0")
            amount_sats = int(float(amount_str))
            multiplier = _get_multiplier(user_id, tier_config_json, user_tiers_json)
            credited = amount_sats * multiplier
            ledger.credit_deposit(credited, invoice_id)
            cache.mark_dirty(user_id)
            if not await cache.flush_user(user_id):
                logger.error(
                    "CRITICAL: Failed to flush %d credits for %s (invoice %s). "
                    "Credits are in memory but may be lost on restart.",
                    credited, user_id, invoice_id,
                )
            result["credits_granted"] = credited
            result["multiplier"] = multiplier
            result["message"] = f"Payment settled! {credited:,} credits added to your balance."

    elif status == "Expired":
        if invoice_id in ledger.pending_invoices:
            ledger.pending_invoices.remove(invoice_id)
            cache.mark_dirty(user_id)
            await cache.flush_user(user_id)
        result["message"] = "Invoice expired. Create a new one with purchase_credits."

    elif status == "Invalid":
        if invoice_id in ledger.pending_invoices:
            ledger.pending_invoices.remove(invoice_id)
            cache.mark_dirty(user_id)
            await cache.flush_user(user_id)
        result["message"] = "Payment invalid."

    else:
        result["message"] = f"Unknown invoice status: {status}"

    result["balance_sats"] = ledger.balance_sats
    return result


async def check_balance_tool(
    cache: LedgerCache,
    user_id: str,
    tier_config_json: str | None = None,
    user_tiers_json: str | None = None,
) -> dict[str, Any]:
    """Return the user's current credit balance and usage summary."""
    ledger = await cache.get(user_id)
    today = date.today().isoformat()

    tier_name, multiplier = _get_tier_info(user_id, tier_config_json, user_tiers_json)

    result: dict[str, Any] = {
        "success": True,
        "tier": tier_name,
        "multiplier": multiplier,
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


async def restore_credits_tool(
    btcpay: BTCPayClient,
    cache: LedgerCache,
    user_id: str,
    invoice_id: str,
    tier_config_json: str | None = None,
    user_tiers_json: str | None = None,
) -> dict[str, Any]:
    """Restore credits from a paid invoice that was lost due to cache/vault issues.

    Verifies the invoice is Settled with BTCPay, then credits the balance.
    Idempotent via credited_invoices — won't double-credit.
    """
    # Check idempotency first
    ledger = await cache.get(user_id)
    if invoice_id in ledger.credited_invoices:
        return {
            "success": True,
            "invoice_id": invoice_id,
            "credits_granted": 0,
            "balance_sats": ledger.balance_sats,
            "message": "Invoice already credited — no duplicate credits applied.",
        }

    # Verify with BTCPay
    try:
        invoice = await btcpay.get_invoice(invoice_id)
    except BTCPayError as e:
        return {"success": False, "error": f"BTCPay error: {e}"}

    status = invoice.get("status", "Unknown")
    if status != "Settled":
        return {
            "success": False,
            "error": f"Invoice status is '{status}', not 'Settled'. Cannot restore.",
            "invoice_id": invoice_id,
        }

    # Credit the balance
    amount_str = invoice.get("amount", "0")
    amount_sats = int(float(amount_str))
    multiplier = _get_multiplier(user_id, tier_config_json, user_tiers_json)
    credited = amount_sats * multiplier

    ledger.credit_deposit(credited, invoice_id)
    cache.mark_dirty(user_id)
    if not await cache.flush_user(user_id):
        logger.error(
            "CRITICAL: Failed to flush restored %d credits for %s (invoice %s).",
            credited, user_id, invoice_id,
        )

    return {
        "success": True,
        "invoice_id": invoice_id,
        "amount_sats": amount_sats,
        "multiplier": multiplier,
        "credits_granted": credited,
        "balance_sats": ledger.balance_sats,
        "message": f"Restored {credited:,} credits from invoice {invoice_id}.",
    }


async def btcpay_status_tool(
    settings: Settings,
    btcpay: BTCPayClient | None,
) -> dict[str, Any]:
    """Report BTCPay configuration state and connectivity for diagnostics."""
    result: dict[str, Any] = {
        "btcpay_host": settings.btcpay_host or None,
        "btcpay_store_id": settings.btcpay_store_id or None,
        "btcpay_api_key_status": "present" if settings.btcpay_api_key else "missing",
    }

    # Tier config
    if settings.btcpay_tier_config:
        try:
            tiers = json.loads(settings.btcpay_tier_config)
            result["tier_config"] = f"{len(tiers)} tier(s)"
        except (json.JSONDecodeError, TypeError):
            result["tier_config"] = "invalid JSON"
    else:
        result["tier_config"] = "missing"

    # User tiers
    if settings.btcpay_user_tiers:
        try:
            users = json.loads(settings.btcpay_user_tiers)
            result["user_tiers"] = f"{len(users)} user(s)"
        except (json.JSONDecodeError, TypeError):
            result["user_tiers"] = "invalid JSON"
    else:
        result["user_tiers"] = "missing"

    # Connectivity checks — only if all 3 connection vars present and client available
    connection_vars_present = bool(
        settings.btcpay_host and settings.btcpay_store_id and settings.btcpay_api_key
    )

    if connection_vars_present and btcpay is not None:
        # Health check
        try:
            await btcpay.health_check()
            result["server_reachable"] = True
        except BTCPayError:
            result["server_reachable"] = False
        except Exception:
            result["server_reachable"] = False

        # Store check
        try:
            store = await btcpay.get_store()
            result["store_name"] = store.get("name", "unknown")
        except BTCPayAuthError:
            result["store_name"] = "unauthorized"
        except BTCPayError:
            result["store_name"] = None
        except Exception:
            result["store_name"] = None
    else:
        result["server_reachable"] = None
        result["store_name"] = None

    return result
