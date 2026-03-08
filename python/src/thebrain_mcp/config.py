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

    btcpay_host: str | None = None
    btcpay_store_id: str | None = None
    btcpay_api_key: str | None = None
    btcpay_tier_config: str | None = None
    btcpay_user_tiers: str | None = None

    seed_balance_sats: int = 0  # 0 = disabled (current behavior)

    credit_ttl_seconds: int | None = 604800  # 7 days; None = no expiration

    # NeonVault (replaces TheBrainVault for commerce ledger persistence)
    neon_database_url: str | None = None

    # Nostr audit (optional — enabled when all 3 are set)
    tollbooth_nostr_audit_enabled: str | None = None
    tollbooth_nostr_operator_nsec: str | None = None
    tollbooth_nostr_relays: str | None = None

    # DPYC registry cache TTL (URL comes from tollbooth-dpyc DEFAULT_REGISTRY_URL)
    dpyc_registry_cache_ttl_seconds: int = 300

    # Attachment security
    attachment_safe_directory: str = "/tmp/thebrain-attachments"

    # OpenTimestamps Bitcoin anchoring
    tollbooth_ots_enabled: str | None = None  # "true" to enable
    tollbooth_ots_calendars: str | None = None  # Comma-separated URLs

    # Constraint Engine (opt-in)
    constraints_enabled: bool = False
    constraints_config: str | None = None  # JSON string

    def to_tollbooth_config(self) -> "TollboothConfig":
        """Build a TollboothConfig for passing to tollbooth library tools."""
        from tollbooth.config import TollboothConfig
        return TollboothConfig(
            constraints_enabled=self.constraints_enabled,
            constraints_config=self.constraints_config,
        )


def get_settings() -> Settings:
    """Get application settings."""
    return Settings()  # type: ignore[call-arg]
