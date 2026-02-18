"""Abstract persistence interface for commerce state (ledger storage).

Defines the VaultBackend Protocol that LedgerCache depends on.
Concrete implementations (e.g., PersonalBrainVault) live elsewhere.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class VaultBackend(Protocol):
    """Async persistence backend for user ledger data.

    Any object implementing these three methods can serve as the
    durable backing store for LedgerCache.
    """

    async def store_ledger(self, user_id: str, ledger_json: str) -> str: ...

    async def fetch_ledger(self, user_id: str) -> str | None: ...

    async def snapshot_ledger(
        self, user_id: str, ledger_json: str, timestamp: str
    ) -> str | None: ...
