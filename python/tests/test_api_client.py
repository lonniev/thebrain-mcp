"""Tests for TheBrain API client."""

import pytest

from thebrain_mcp.api.client import TheBrainAPI


def test_api_client_initialization(mock_api_key: str) -> None:
    """Test API client initialization."""
    client = TheBrainAPI(mock_api_key)
    assert client.api_key == mock_api_key
    assert client.base_url == "https://api.bra.in"


def test_api_client_custom_base_url(mock_api_key: str) -> None:
    """Test API client with custom base URL."""
    custom_url = "https://custom.api.bra.in"
    client = TheBrainAPI(mock_api_key, custom_url)
    assert client.base_url == custom_url


@pytest.mark.asyncio
async def test_api_client_context_manager(mock_api_key: str) -> None:
    """Test API client as async context manager."""
    async with TheBrainAPI(mock_api_key) as client:
        assert client.api_key == mock_api_key
    # Client should be closed after exiting context
