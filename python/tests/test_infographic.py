"""Tests for the SVG account statement infographic renderer."""

from __future__ import annotations

import pytest

from thebrain_mcp.infographic import render_account_infographic


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_data(**overrides) -> dict:
    """Build a sample account_statement_tool response."""
    data = {
        "success": True,
        "generated_at": "2026-02-22T23:53:48.296584+00:00",
        "statement_period_days": 30,
        "account_summary": {
            "balance_api_sats": 1110,
            "total_deposited_api_sats": 1111,
            "total_consumed_api_sats": 1,
            "total_expired_api_sats": 0,
        },
        "purchase_history": [],
        "active_tranches": [
            {
                "granted_at": "2026-02-22T23:52:41.999568+00:00",
                "original_sats": 1111,
                "remaining_sats": 1110,
                "invoice_id": "seed_balance_v1",
            }
        ],
        "tool_usage_all_time": [
            {"tool": "get_note", "calls": 1, "api_sats": 1},
        ],
        "daily_usage": [
            {
                "date": "2026-02-22",
                "total_calls": 1,
                "total_api_sats": 1,
                "tools": {"get_note": {"calls": 1, "api_sats": 1}},
            }
        ],
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRenderAccountInfographic:
    def test_returns_valid_svg(self) -> None:
        """Output is a well-formed SVG string."""
        svg = render_account_infographic(_sample_data())
        assert svg.startswith("<svg")
        assert svg.endswith("</svg>")
        assert 'xmlns="http://www.w3.org/2000/svg"' in svg

    def test_balance_displayed(self) -> None:
        """Hero balance appears in the output."""
        svg = render_account_infographic(_sample_data())
        assert "1,110" in svg

    def test_deposited_consumed_expired(self) -> None:
        """Metric cards show deposited, consumed, expired."""
        svg = render_account_infographic(_sample_data())
        assert "1,111" in svg      # deposited
        assert "DEPOSITED" in svg
        assert "CONSUMED" in svg
        assert "EXPIRED" in svg

    def test_tranche_rendered(self) -> None:
        """Active tranche row appears."""
        svg = render_account_infographic(_sample_data())
        assert "Seed (v1)" in svg
        assert "2026-02-22" in svg

    def test_tool_usage_rendered(self) -> None:
        """Tool usage table appears."""
        svg = render_account_infographic(_sample_data())
        assert "get_note" in svg
        assert "TOOL USAGE" in svg

    def test_footer_branding(self) -> None:
        """Footer includes DPYC branding."""
        svg = render_account_infographic(_sample_data())
        assert "DPYC" in svg
        assert "Tollbooth Protocol" in svg

    def test_health_gauge_percentage(self) -> None:
        """Balance health gauge shows correct percentage."""
        svg = render_account_infographic(_sample_data())
        assert "99.9% remaining" in svg

    def test_zero_balance(self) -> None:
        """Renders without error when balance is zero."""
        data = _sample_data()
        data["account_summary"]["balance_api_sats"] = 0
        data["account_summary"]["total_consumed_api_sats"] = 1111
        svg = render_account_infographic(data)
        assert "0.0% remaining" in svg

    def test_empty_tranches(self) -> None:
        """Handles no active tranches gracefully."""
        svg = render_account_infographic(_sample_data(active_tranches=[]))
        assert "No active tranches" in svg

    def test_empty_tool_usage(self) -> None:
        """Handles no tool usage gracefully."""
        svg = render_account_infographic(_sample_data(tool_usage_all_time=[]))
        assert "No usage yet" in svg

    def test_multiple_tools(self) -> None:
        """Multiple tool rows render correctly."""
        usage = [
            {"tool": "get_note", "calls": 10, "api_sats": 10},
            {"tool": "brain_query", "calls": 5, "api_sats": 50},
            {"tool": "create_thought", "calls": 3, "api_sats": 15},
        ]
        svg = render_account_infographic(_sample_data(tool_usage_all_time=usage))
        assert "get_note" in svg
        assert "brain_query" in svg
        assert "create_thought" in svg

    def test_multiple_tranches(self) -> None:
        """Multiple tranche rows render correctly."""
        tranches = [
            {
                "granted_at": "2026-02-20T10:00:00+00:00",
                "original_sats": 500,
                "remaining_sats": 200,
                "invoice_id": "inv-abc",
            },
            {
                "granted_at": "2026-02-22T10:00:00+00:00",
                "original_sats": 1000,
                "remaining_sats": 900,
                "invoice_id": "seed_balance_v1",
            },
        ]
        svg = render_account_infographic(_sample_data(active_tranches=tranches))
        assert "inv-abc" in svg
        assert "Seed (v1)" in svg

    def test_xml_escaping(self) -> None:
        """Special characters in tool names are XML-escaped."""
        usage = [{"tool": "get<note>", "calls": 1, "api_sats": 1}]
        svg = render_account_infographic(_sample_data(tool_usage_all_time=usage))
        assert "&lt;" in svg
        assert "&gt;" in svg
        # Must not contain raw < or > inside text elements (except SVG tags)

    def test_dynamic_height(self) -> None:
        """SVG height adjusts with more rows."""
        svg_short = render_account_infographic(_sample_data())
        usage_long = [
            {"tool": f"tool_{i}", "calls": i + 1, "api_sats": (i + 1) * 2}
            for i in range(10)
        ]
        svg_tall = render_account_infographic(
            _sample_data(tool_usage_all_time=usage_long)
        )
        # Extract height from viewBox
        import re

        def _height(svg: str) -> int:
            m = re.search(r'viewBox="0 0 \d+ (\d+)"', svg)
            assert m, "viewBox not found"
            return int(m.group(1))

        assert _height(svg_tall) > _height(svg_short)

    def test_expired_shown_in_red(self) -> None:
        """Non-zero expired uses red accent colour."""
        data = _sample_data()
        data["account_summary"]["total_expired_api_sats"] = 50
        svg = render_account_infographic(data)
        # The expired metric card should use the red colour
        assert "#e74c3c" in svg
