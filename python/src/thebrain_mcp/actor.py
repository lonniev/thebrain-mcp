"""Concrete OperatorProtocol implementation for TheBrain MCP.

Thin delegation layer over existing server.py tool functions.
Hot-path methods delegate to server.py; cold-path methods that
reach the Authority or Oracle return delegation stubs.

The tool catalog inherits from ``OPERATOR_BASE_CATALOG`` — the
library-level single source of truth for tool metadata.  Brain-specific
commentary is added via operator-local extensions.

purchase_credits and check_payment are also delegation stubs —
the long-term design delegates all Lightning payment processing
to the Tollbooth Authority.
"""

from __future__ import annotations

import sys
from typing import Any

from tollbooth.actor_types import ToolPathInfo
from tollbooth.constants import ECOSYSTEM_LINKS
from tollbooth.operator_protocol import OPERATOR_BASE_CATALOG

_DELEGATION_MSG = (
    "Cold-path delegation not yet implemented. "
    "Connect to the {actor} MCP directly."
)


class BrainOperator:
    """Concrete OperatorProtocol implementation for TheBrain MCP.

    Hot-path methods delegate to server.py tool functions.
    Cold-path and delegation methods return stubs.
    """

    @property
    def slug(self) -> str:
        return "brain"

    @classmethod
    def tool_catalog(cls) -> list[ToolPathInfo]:
        return list(OPERATOR_BASE_CATALOG)

    # ── Hot-path (local ledger) ──────────────────────────────────

    async def check_balance(self, npub: str) -> dict[str, Any]:
        from thebrain_mcp.server import check_balance

        return await check_balance()

    async def account_statement(self, npub: str) -> dict[str, Any]:
        from thebrain_mcp.server import account_statement

        return await account_statement()

    async def account_statement_infographic(
        self, npub: str
    ) -> dict[str, Any]:
        from thebrain_mcp.server import account_statement_infographic

        return await account_statement_infographic()

    async def restore_credits(
        self, npub: str, invoice_id: str
    ) -> dict[str, Any]:
        from thebrain_mcp.server import restore_credits

        return await restore_credits(invoice_id=invoice_id)

    async def service_status(self) -> dict[str, Any]:
        import thebrain_mcp

        return {
            "success": True,
            "thebrain_mcp_version": thebrain_mcp.__version__,
            "python_version": sys.version,
            "ecosystem_links": ECOSYSTEM_LINKS,
        }

    async def get_operator_onboarding_status(self) -> dict[str, Any]:
        from thebrain_mcp.server import get_operator_onboarding_status

        return await get_operator_onboarding_status()

    async def get_patron_onboarding_status(self, patron_npub: str) -> dict[str, Any]:
        from thebrain_mcp.server import get_patron_onboarding_status

        return await get_patron_onboarding_status(patron_npub=patron_npub)

    # ── Hot-path (Secure Courier) ────────────────────────────────

    async def session_status(self) -> dict[str, Any]:
        """Delegate to server.py — checks session and DPYC identity."""
        from thebrain_mcp.server import session_status

        return await session_status()

    async def request_credential_channel(
        self, service: str, greeting: str, recipient_npub: str | None,
    ) -> dict[str, Any]:
        """Delegate to server.py — opens Secure Courier channel."""
        from thebrain_mcp.server import request_credential_channel

        return await request_credential_channel(
            service=service, recipient_npub=recipient_npub or "",
        )

    async def receive_credentials(
        self, sender_npub: str, service: str, credential_card: str,
    ) -> dict[str, Any]:
        """Delegate to server.py — receives credentials, sends card DM."""
        from thebrain_mcp.server import receive_credentials

        return await receive_credentials(
            sender_npub=sender_npub,
            service=service,
            credential_card=credential_card,
        )

    async def forget_credentials(
        self, sender_npub: str, service: str,
    ) -> dict[str, Any]:
        """Delegate to server.py — deletes vaulted credentials."""
        from thebrain_mcp.server import forget_credentials

        return await forget_credentials(sender_npub=sender_npub, service=service)

    # ── Delegation stubs (BTCPay via Authority) ──────────────────
    # DELEGATION_STUB

    async def purchase_credits(
        self, npub: str, amount_sats: int, certificate: str
    ) -> dict[str, Any]:
        """Delegate to server.py — auto-certifies via Authority."""
        from thebrain_mcp.server import purchase_credits

        return await purchase_credits(amount_sats=amount_sats)

    async def check_payment(
        self, npub: str, invoice_id: str
    ) -> dict[str, Any]:
        """Delegate to server.py — polls BTCPay invoice status."""
        from thebrain_mcp.server import check_payment

        return await check_payment(invoice_id=invoice_id)

    # ── Delegation stubs (Authority) ─────────────────────────────
    # DELEGATION_STUB

    async def certify_credits(
        self, npub: str, amount_sats: int
    ) -> dict[str, Any]:
        """(delegation, delegates to Authority) Not yet implemented."""
        return {  # DELEGATION_STUB
            "success": False,
            "error": _DELEGATION_MSG.format(actor="Authority"),
        }

    async def register_operator(self, npub: str) -> dict[str, Any]:
        """(delegation, delegates to Authority) Not yet implemented."""
        return {  # DELEGATION_STUB
            "success": False,
            "error": _DELEGATION_MSG.format(actor="Authority"),
        }

    async def operator_status(self) -> dict[str, Any]:
        """(delegation, delegates to Authority) Not yet implemented."""
        return {  # DELEGATION_STUB
            "success": False,
            "error": _DELEGATION_MSG.format(actor="Authority"),
        }

    # ── Delegation (Oracle — direct routing) ────────────────────

    async def lookup_member(self, npub: str) -> dict[str, Any] | str:
        """Delegate to server.py — routes to Oracle via MCP-to-MCP."""
        from thebrain_mcp.server import lookup_member

        return await lookup_member(npub=npub)

    async def how_to_join(self) -> str:
        """Delegate to server.py — routes to Oracle via MCP-to-MCP."""
        from thebrain_mcp.server import how_to_join

        return await how_to_join()

    async def get_tax_rate(self) -> dict[str, Any]:
        """Delegate to server.py — routes to Oracle via MCP-to-MCP."""
        from thebrain_mcp.server import get_tax_rate

        return await get_tax_rate()

    async def about(self) -> str:
        """Delegate to server.py — routes to Oracle via MCP-to-MCP."""
        from thebrain_mcp.server import dpyc_about

        return await dpyc_about()

    async def network_advisory(self) -> str:
        """Delegate to server.py — routes to Oracle via MCP-to-MCP."""
        from thebrain_mcp.server import network_advisory

        return await network_advisory()
