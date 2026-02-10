"""Pytest configuration and fixtures."""

import pytest

from thebrain_mcp.api.client import TheBrainAPI


@pytest.fixture
def mock_api_key() -> str:
    """Provide a mock API key for testing."""
    return "test_api_key_123"


@pytest.fixture
def api_client(mock_api_key: str) -> TheBrainAPI:
    """Provide a TheBrain API client for testing."""
    return TheBrainAPI(mock_api_key)
