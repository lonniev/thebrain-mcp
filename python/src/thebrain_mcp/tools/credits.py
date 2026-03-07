"""Re-export: tollbooth.tools.credits → thebrain_mcp.tools.credits (backward compat shim)."""

from tollbooth.tools.credits import *  # noqa: F401, F403
from tollbooth.tools.credits import (  # explicit for type checkers + private names
    _get_multiplier,
    _get_tier_info,
    purchase_credits_tool,
    direct_purchase_tool,
    check_payment_tool,
    check_balance_tool,
    btcpay_status_tool,
    restore_credits_tool,
    compute_low_balance_warning,
    reconcile_pending_invoices,
)
