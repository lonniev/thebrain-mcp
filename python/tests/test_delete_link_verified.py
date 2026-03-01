"""Tests for TheBrainAPI.delete_link_verified() — verify-after-failure pattern."""

from unittest.mock import AsyncMock, patch

import pytest

from thebrain_mcp.api.client import TheBrainAPI, TheBrainAPIError
from thebrain_mcp.api.models import Link

BRAIN = "00000000-0000-0000-0000-000000000001"
LINK = "00000000-0000-0000-0000-000000000002"


def _make_api() -> TheBrainAPI:
    """Create a TheBrainAPI with mocked HTTP client."""
    api = TheBrainAPI.__new__(TheBrainAPI)
    api.api_key = "test"
    api.base_url = "https://api.bra.in"
    api.client = AsyncMock()
    return api


class TestDeleteLinkVerifiedNormalSuccess:
    @pytest.mark.asyncio
    async def test_200_returns_success(self):
        """Normal delete (200) passes through directly."""
        api = _make_api()
        api.delete_link = AsyncMock(return_value={"success": True})

        result = await api.delete_link_verified(BRAIN, LINK)

        assert result == {"success": True}
        api.delete_link.assert_called_once_with(BRAIN, LINK)


class TestDeleteLinkVerifiedGhostLink:
    @pytest.mark.asyncio
    async def test_400_then_get_404_returns_ghost(self):
        """400 on delete + link not found = ghost link, tolerated."""
        api = _make_api()
        api.delete_link = AsyncMock(
            side_effect=TheBrainAPIError("HTTP 400: Bad Request")
        )
        api.get_link = AsyncMock(
            side_effect=TheBrainAPIError("HTTP 404: Not Found")
        )

        result = await api.delete_link_verified(BRAIN, LINK)

        assert result["success"] is True
        assert result["ghost"] is True
        api.get_link.assert_called_once_with(BRAIN, LINK)


class TestDeleteLinkVerifiedAPIRefusal:
    @pytest.mark.asyncio
    async def test_400_then_get_200_raises_with_desktop_message(self):
        """400 on delete + link still exists = API refuses, clear error."""
        api = _make_api()
        api.delete_link = AsyncMock(
            side_effect=TheBrainAPIError("HTTP 400: Bad Request")
        )
        link = Link.model_validate({
            "id": LINK, "brainId": BRAIN,
            "thoughtIdA": "00000000-0000-0000-0000-000000000003",
            "thoughtIdB": "00000000-0000-0000-0000-000000000004",
            "relation": 1,
        })
        api.get_link = AsyncMock(return_value=link)

        with pytest.raises(TheBrainAPIError, match="desktop"):
            await api.delete_link_verified(BRAIN, LINK)

        api.get_link.assert_called_once_with(BRAIN, LINK)


class TestDeleteLinkVerifiedNon400Propagates:
    @pytest.mark.asyncio
    async def test_500_error_propagates(self):
        """Non-400 errors pass through without verification."""
        api = _make_api()
        api.delete_link = AsyncMock(
            side_effect=TheBrainAPIError("HTTP 500: Internal Server Error")
        )
        api.get_link = AsyncMock()

        with pytest.raises(TheBrainAPIError, match="500"):
            await api.delete_link_verified(BRAIN, LINK)

        # Should NOT attempt get_link for non-400
        api.get_link.assert_not_called()

    @pytest.mark.asyncio
    async def test_403_error_propagates(self):
        """403 errors pass through without verification."""
        api = _make_api()
        api.delete_link = AsyncMock(
            side_effect=TheBrainAPIError("HTTP 403: Forbidden")
        )

        with pytest.raises(TheBrainAPIError, match="403"):
            await api.delete_link_verified(BRAIN, LINK)
