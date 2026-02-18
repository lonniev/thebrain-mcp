"""Re-export: tollbooth.btcpay_client → thebrain_mcp.btcpay_client (backward compat shim)."""

from tollbooth.btcpay_client import *  # noqa: F401, F403
from tollbooth.btcpay_client import (  # explicit for type checkers
    BTCPayClient,
    BTCPayError,
    BTCPayAuthError,
    BTCPayConnectionError,
    BTCPayNotFoundError,
    BTCPayServerError,
    BTCPayTimeoutError,
    BTCPayValidationError,
    sats_to_btc_string,
)
