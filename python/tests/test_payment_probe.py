"""Tests for x402 payment probe endpoint (Task 19)."""

import os
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from thebrain_mcp.server import mcp


@pytest.fixture()
def client():
    """Create a test client for the FastMCP HTTP app."""
    app = mcp.http_app(stateless_http=True)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Custom route: /x402/payment-probe
# ---------------------------------------------------------------------------


class TestPaymentProbeRoute:
    """Tests for the /x402/payment-probe custom HTTP route."""

    def test_returns_402_without_payment_header(self, client: TestClient) -> None:
        resp = client.get("/x402/payment-probe")
        assert resp.status_code == 402

    def test_402_body_has_x402_version(self, client: TestClient) -> None:
        resp = client.get("/x402/payment-probe")
        body = resp.json()
        assert body["x402Version"] == 1

    def test_402_body_has_error_message(self, client: TestClient) -> None:
        resp = client.get("/x402/payment-probe")
        body = resp.json()
        assert "error" in body
        assert "Payment required" in body["error"]

    def test_402_body_has_accepts_array(self, client: TestClient) -> None:
        resp = client.get("/x402/payment-probe")
        body = resp.json()
        assert "accepts" in body
        assert isinstance(body["accepts"], list)
        assert len(body["accepts"]) == 1

    def test_402_accepts_has_required_fields(self, client: TestClient) -> None:
        resp = client.get("/x402/payment-probe")
        accept = resp.json()["accepts"][0]
        assert accept["scheme"] == "exact"
        assert accept["network"] == "base-sepolia"
        assert accept["maxAmountRequired"] == "1000"
        assert accept["asset"] == "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
        assert accept["resource"] == "/x402/payment-probe"
        assert "payTo" in accept
        assert "description" in accept
        assert accept["maxTimeoutSeconds"] == 300

    def test_returns_200_with_payment_header(self, client: TestClient) -> None:
        resp = client.get(
            "/x402/payment-probe", headers={"X-PAYMENT": "test-token"}
        )
        assert resp.status_code == 200

    def test_200_body_has_success_status(self, client: TestClient) -> None:
        resp = client.get(
            "/x402/payment-probe", headers={"X-PAYMENT": "test-token"}
        )
        body = resp.json()
        assert body["status"] == "ok"
        assert body["x402Version"] == 1

    def test_200_has_payment_response_header(self, client: TestClient) -> None:
        resp = client.get(
            "/x402/payment-probe", headers={"X-PAYMENT": "test-token"}
        )
        assert "x-payment-response" in resp.headers

    def test_post_method_works(self, client: TestClient) -> None:
        resp = client.post("/x402/payment-probe")
        assert resp.status_code == 402

    def test_post_with_payment_header(self, client: TestClient) -> None:
        resp = client.post(
            "/x402/payment-probe", headers={"X-PAYMENT": "test-token"}
        )
        assert resp.status_code == 200

    def test_pay_to_from_env_var(self, client: TestClient) -> None:
        test_addr = "0x1234567890abcdef1234567890abcdef12345678"
        with patch.dict(os.environ, {"X402_PAY_TO": test_addr}):
            resp = client.get("/x402/payment-probe")
            accept = resp.json()["accepts"][0]
            assert accept["payTo"] == test_addr

    def test_default_pay_to_when_no_env(self, client: TestClient) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("X402_PAY_TO", None)
            resp = client.get("/x402/payment-probe")
            accept = resp.json()["accepts"][0]
            assert accept["payTo"] == "0x0000000000000000000000000000000000000000"
