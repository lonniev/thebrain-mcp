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


def get_settings() -> Settings:
    """Get application settings."""
    return Settings()  # type: ignore[call-arg]
