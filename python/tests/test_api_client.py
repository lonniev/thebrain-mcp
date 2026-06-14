"""Tests for TheBrain API client."""

import httpx
import pytest

from thebrain_mcp.api.client import TheBrainAPI, _format_http_error


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


def _http_status_error(status: int, body: str) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://api.bra.in/search/x")
    response = httpx.Response(status, text=body, request=request)
    return httpx.HTTPStatusError("err", request=request, response=response)


def test_format_http_error_empty_body_5xx_self_describes() -> None:
    """An empty-body upstream 5xx names TheBrain as the source, not this server."""
    msg = _format_http_error("GET", "/search/brain", _http_status_error(500, ""))
    assert "upstream" in msg.lower()
    assert "api.bra.in" in msg
    # must not read like a local index needs rebuilding
    assert "no local index" in msg.lower()
    assert "/search" in msg


def test_format_http_error_preserves_body_when_present() -> None:
    """A 4xx with a real body keeps the detail rather than masking it."""
    msg = _format_http_error("GET", "/thoughts/brain", _http_status_error(404, "not found"))
    assert "404" in msg
    assert "not found" in msg


def test_format_http_error_empty_body_4xx_labels_emptiness() -> None:
    """A non-5xx empty body still says which call produced it."""
    msg = _format_http_error("POST", "/search/brain", _http_status_error(405, ""))
    assert "405" in msg
    assert "empty body" in msg.lower()
