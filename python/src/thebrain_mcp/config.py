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


def get_settings() -> Settings:
    """Get application settings."""
    return Settings()  # type: ignore[call-arg]
