"""Tests for BTCPay Greenfield API client."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from thebrain_mcp.btcpay_client import (
    BTCPayAuthError,
    BTCPayClient,
    BTCPayConnectionError,
    BTCPayError,
    BTCPayNotFoundError,
    BTCPayServerError,
    BTCPayTimeoutError,
    BTCPayValidationError,
)


# ---------------------------------------------------------------------------
# Init / constructor
# ---------------------------------------------------------------------------


class TestBTCPayClientInit:
    def test_fields_stored(self) -> None:
        client = BTCPayClient("https://btcpay.example.com", "key123", "store-abc")
        assert client._store_id == "store-abc"
        assert str(client._client.base_url).rstrip("/") == "https://btcpay.example.com/api/v1"

    def test_trailing_slash_stripped(self) -> None:
        client = BTCPayClient("https://btcpay.example.com/", "key123", "store-abc")
        assert str(client._client.base_url).rstrip("/") == "https://btcpay.example.com/api/v1"

    def test_auth_header_format(self) -> None:
        client = BTCPayClient("https://btcpay.example.com", "my-api-key", "s1")
        assert client._client.headers["authorization"] == "token my-api-key"

    def test_timeout_configured(self) -> None:
        client = BTCPayClient("https://x.com", "k", "s")
        t = client._client.timeout
        assert t.connect == 5.0
        assert t.read == 15.0
        assert t.write == 10.0
        assert t.pool == 5.0


# ---------------------------------------------------------------------------
# Request methods (mocked transport)
# ---------------------------------------------------------------------------


def _mock_response(status: int = 200, json_data: dict | None = None) -> httpx.Response:
    resp = httpx.Response(
        status_code=status,
        json=json_data or {},
        request=httpx.Request("GET", "https://example.com"),
    )
    return resp


class TestBTCPayClientRequests:
    @pytest.mark.asyncio
    async def test_health_check(self) -> None:
        client = BTCPayClient("https://x.com", "k", "s")
        client._client.request = AsyncMock(
            return_value=_mock_response(200, {"synchronized": True})
        )
        result = await client.health_check()
        assert result == {"synchronized": True}
        client._client.request.assert_called_once_with("GET", "/health", json=None)

    @pytest.mark.asyncio
    async def test_get_store(self) -> None:
        client = BTCPayClient("https://x.com", "k", "my-store")
        client._client.request = AsyncMock(
            return_value=_mock_response(200, {"id": "my-store", "name": "Test"})
        )
        result = await client.get_store()
        assert result["id"] == "my-store"
        client._client.request.assert_called_once_with(
            "GET", "/stores/my-store", json=None
        )

    @pytest.mark.asyncio
    async def test_create_invoice_minimal(self) -> None:
        client = BTCPayClient("https://x.com", "k", "s1")
        client._client.request = AsyncMock(
            return_value=_mock_response(200, {"id": "inv-1"})
        )
        result = await client.create_invoice(1000)
        assert result["id"] == "inv-1"
        call_args = client._client.request.call_args
        assert call_args[0] == ("POST", "/stores/s1/invoices")
        payload = call_args[1]["json"]
        assert payload["amount"] == "1000"
        assert payload["currency"] == "SATS"
        assert "metadata" not in payload

    @pytest.mark.asyncio
    async def test_create_invoice_with_metadata(self) -> None:
        client = BTCPayClient("https://x.com", "k", "s1")
        client._client.request = AsyncMock(
            return_value=_mock_response(200, {"id": "inv-2"})
        )
        meta = {"user": "u1", "purpose": "credits"}
        result = await client.create_invoice(500, metadata=meta)
        assert result["id"] == "inv-2"
        payload = client._client.request.call_args[1]["json"]
        assert payload["metadata"] == meta

    @pytest.mark.asyncio
    async def test_get_invoice(self) -> None:
        client = BTCPayClient("https://x.com", "k", "s1")
        client._client.request = AsyncMock(
            return_value=_mock_response(200, {"id": "inv-3", "status": "Settled"})
        )
        result = await client.get_invoice("inv-3")
        assert result["status"] == "Settled"
        client._client.request.assert_called_once_with(
            "GET", "/stores/s1/invoices/inv-3", json=None
        )


# ---------------------------------------------------------------------------
# Exception mapping
# ---------------------------------------------------------------------------


class TestBTCPayExceptionMapping:
    @pytest.mark.asyncio
    async def test_401_raises_auth_error(self) -> None:
        client = BTCPayClient("https://x.com", "k", "s")
        client._client.request = AsyncMock(return_value=_mock_response(401))
        with pytest.raises(BTCPayAuthError) as exc_info:
            await client.health_check()
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_403_raises_auth_error(self) -> None:
        client = BTCPayClient("https://x.com", "k", "s")
        client._client.request = AsyncMock(return_value=_mock_response(403))
        with pytest.raises(BTCPayAuthError) as exc_info:
            await client.health_check()
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_404_raises_not_found(self) -> None:
        client = BTCPayClient("https://x.com", "k", "s")
        client._client.request = AsyncMock(return_value=_mock_response(404))
        with pytest.raises(BTCPayNotFoundError) as exc_info:
            await client.health_check()
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_422_raises_validation(self) -> None:
        client = BTCPayClient("https://x.com", "k", "s")
        client._client.request = AsyncMock(return_value=_mock_response(422))
        with pytest.raises(BTCPayValidationError) as exc_info:
            await client.health_check()
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_500_raises_server_error(self) -> None:
        client = BTCPayClient("https://x.com", "k", "s")
        client._client.request = AsyncMock(return_value=_mock_response(500))
        with pytest.raises(BTCPayServerError) as exc_info:
            await client.health_check()
        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_connect_error(self) -> None:
        client = BTCPayClient("https://x.com", "k", "s")
        client._client.request = AsyncMock(side_effect=httpx.ConnectError("DNS failed"))
        with pytest.raises(BTCPayConnectionError, match="DNS failed"):
            await client.health_check()

    @pytest.mark.asyncio
    async def test_timeout_error(self) -> None:
        client = BTCPayClient("https://x.com", "k", "s")
        client._client.request = AsyncMock(
            side_effect=httpx.ReadTimeout("read timed out")
        )
        with pytest.raises(BTCPayTimeoutError, match="read timed out"):
            await client.health_check()

    @pytest.mark.asyncio
    async def test_unknown_4xx_raises_base(self) -> None:
        client = BTCPayClient("https://x.com", "k", "s")
        client._client.request = AsyncMock(return_value=_mock_response(418))
        with pytest.raises(BTCPayError) as exc_info:
            await client.health_check()
        assert exc_info.value.status_code == 418
        assert type(exc_info.value) is BTCPayError


# ---------------------------------------------------------------------------
# get_api_key_info
# ---------------------------------------------------------------------------


class TestGetApiKeyInfo:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        client = BTCPayClient("https://x.com", "k", "s")
        client._client.request = AsyncMock(
            return_value=_mock_response(200, {
                "apiKey": "k",
                "permissions": ["btcpay.store.cancreateinvoice", "btcpay.store.canviewinvoices"],
            })
        )
        result = await client.get_api_key_info()
        assert "permissions" in result
        assert len(result["permissions"]) == 2
        client._client.request.assert_called_once_with("GET", "/api-keys/current", json=None)

    @pytest.mark.asyncio
    async def test_auth_error(self) -> None:
        client = BTCPayClient("https://x.com", "bad-key", "s")
        client._client.request = AsyncMock(return_value=_mock_response(401))
        with pytest.raises(BTCPayAuthError) as exc_info:
            await client.get_api_key_info()
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# create_payout
# ---------------------------------------------------------------------------


class TestCreatePayout:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        client = BTCPayClient("https://x.com", "k", "my-store")
        client._client.request = AsyncMock(
            return_value=_mock_response(200, {"id": "payout-1", "state": "AwaitingApproval"})
        )
        result = await client.create_payout("user@ln.addr", 100)
        assert result["id"] == "payout-1"
        assert result["state"] == "AwaitingApproval"
        call_args = client._client.request.call_args
        assert call_args[0] == ("POST", "/stores/my-store/payouts")
        payload = call_args[1]["json"]
        assert payload["destination"] == "user@ln.addr"
        assert payload["amount"] == "0.00000100"
        assert payload["payoutMethodId"] == "BTC-LN"

    @pytest.mark.asyncio
    async def test_custom_payment_method(self) -> None:
        client = BTCPayClient("https://x.com", "k", "s")
        client._client.request = AsyncMock(
            return_value=_mock_response(200, {"id": "payout-2"})
        )
        await client.create_payout("addr", 50, payout_method="BTC-CHAIN")
        payload = client._client.request.call_args[1]["json"]
        assert payload["payoutMethodId"] == "BTC-CHAIN"

    @pytest.mark.asyncio
    async def test_validation_error(self) -> None:
        client = BTCPayClient("https://x.com", "k", "s")
        client._client.request = AsyncMock(return_value=_mock_response(422))
        with pytest.raises(BTCPayValidationError) as exc_info:
            await client.create_payout("bad", 0)
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_auth_error(self) -> None:
        client = BTCPayClient("https://x.com", "k", "s")
        client._client.request = AsyncMock(return_value=_mock_response(403))
        with pytest.raises(BTCPayAuthError) as exc_info:
            await client.create_payout("addr", 100)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestBTCPayClientContextManager:
    @pytest.mark.asyncio
    async def test_async_with(self) -> None:
        async with BTCPayClient("https://x.com", "k", "s") as client:
            assert isinstance(client, BTCPayClient)
        assert client._client.is_closed

    @pytest.mark.asyncio
    async def test_close(self) -> None:
        client = BTCPayClient("https://x.com", "k", "s")
        assert not client._client.is_closed
        await client.close()
        assert client._client.is_closed
