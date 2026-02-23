"""Configuration management for TheBrain MCP server."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """TheBrain MCP server settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    thebrain_api_key: str
    thebrain_default_brain_id: str | None = None
    thebrain_api_url: str = "https://api.bra.in"
    thebrain_vault_brain_id: str | None = None

    btcpay_host: str | None = None
    btcpay_store_id: str | None = None
    btcpay_api_key: str | None = None
    btcpay_tier_config: str | None = None
    btcpay_user_tiers: str | None = None

    seed_balance_sats: int = 0  # 0 = disabled (current behavior)

    tollbooth_royalty_address: str | None = None
    tollbooth_royalty_percent: float = 0.02
    tollbooth_royalty_min_sats: int = 10

    authority_public_key: str | None = None
    credit_ttl_seconds: int | None = 604800  # 7 days; None = no expiration

    # NeonVault (replaces TheBrainVault for commerce ledger persistence)
    neon_database_url: str | None = None

    # Nostr audit (optional — enabled when all 3 are set)
    tollbooth_nostr_audit_enabled: str | None = None
    tollbooth_nostr_operator_nsec: str | None = None
    tollbooth_nostr_relays: str | None = None

    # DPYC Nostr Identity
    dpyc_operator_npub: str | None = None
    dpyc_authority_npub: str | None = None


def get_settings() -> Settings:
    """Get application settings."""
    return Settings()  # type: ignore[call-arg]
