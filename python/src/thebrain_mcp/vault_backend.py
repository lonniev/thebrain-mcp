"""Re-export: tollbooth.vault_backend → thebrain_mcp.vault_backend (backward compat shim)."""

from tollbooth.vault_backend import *  # noqa: F401, F403
from tollbooth.vault_backend import VaultBackend  # explicit for type checkers
