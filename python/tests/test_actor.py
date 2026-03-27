"""Tests for BrainOperator protocol conformance."""

from tollbooth.actor_types import ToolPathInfo
from tollbooth.operator_protocol import OperatorProtocol

from thebrain_mcp.actor import BrainOperator


def test_isinstance_conformance():
    """BrainOperator satisfies OperatorProtocol at runtime."""
    assert isinstance(BrainOperator(), OperatorProtocol)


def test_dict_does_not_satisfy():
    """A plain dict must not satisfy OperatorProtocol."""
    assert not isinstance({}, OperatorProtocol)


def test_slug():
    """Slug is 'brain'."""
    assert BrainOperator().slug == "brain"


def test_tool_catalog_completeness():
    """Catalog has exactly 22 entries matching Protocol method names."""
    catalog = BrainOperator.tool_catalog()
    assert len(catalog) == 22

    for entry in catalog:
        assert isinstance(entry, ToolPathInfo)

    expected = {
        "check_balance",
        "account_statement",
        "account_statement_infographic",
        "restore_credits",
        "service_status",
        "session_status",
        "request_credential_channel",
        "receive_credentials",
        "forget_credentials",
        "purchase_credits",
        "check_payment",
        "certify_credits",
        "register_operator",
        "operator_status",
        "lookup_member",
        "how_to_join",
        "get_tax_rate",
        "about",
        "network_advisory",
    }
    actual = {e.tool_name for e in catalog}
    assert actual == expected


def test_tool_catalog_returns_copy():
    """tool_catalog() returns a fresh list each time."""
    a = BrainOperator.tool_catalog()
    b = BrainOperator.tool_catalog()
    assert a == b
    assert a is not b


async def test_service_status_returns_version():
    """service_status() returns version info without hitting server.py."""
    result = await BrainOperator().service_status()
    assert result["success"] is True
    assert "thebrain_mcp_version" in result
    assert "python_version" in result


async def test_delegation_stub_returns_error():
    """Delegation stubs return success=False with guidance message."""
    op = BrainOperator()
    result = await op.certify_credits(operator_id="npub1test", amount_sats=100)
    assert result["success"] is False
    assert "Authority" in result["error"]
