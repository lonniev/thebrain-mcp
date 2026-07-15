"""Deployability smoke tests.

These guard the contract the post-merge deploy-verify workflow checks against a
live Horizon service: the wheel must import, the FastMCP app must fully
construct with its standard + domain tools registered, and the package must
report the same version as ``pyproject.toml``. A regression in any of these
manifests to deploy-verify as an "unreachable" service or a served-version
mismatch (see issue #172).
"""

import asyncio
from pathlib import Path

import tomllib

import thebrain_mcp
from thebrain_mcp.server import mcp

# The version deploy-verify expects the live service to report is the single
# source of truth in pyproject ``[project].version``.
_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _pyproject_version() -> str:
    with _PYPROJECT.open("rb") as fh:
        return str(tomllib.load(fh)["project"]["version"])


def test_reported_version_matches_pyproject() -> None:
    """The served ``__version__`` must equal the pyproject source of truth.

    A drift here (e.g. an unresolved ``0.0.0`` fallback) makes every
    deploy-verify probe report a version mismatch.
    """
    assert thebrain_mcp.__version__ == _pyproject_version()
    assert thebrain_mcp.__version__ != "0.0.0"


def test_server_artifact_builds_with_tools() -> None:
    """The deployable FastMCP app must construct and expose its tools.

    If the artifact failed to build at import/startup, deploy-verify sees the
    service as unreachable.
    """
    tools = {t.name for t in asyncio.run(mcp.list_tools())}
    # Standard DPYC tools from the tollbooth wheel + a domain-specific tool.
    for expected in ("brain_session_status", "brain_check_balance", "brain_brain_query"):
        assert expected in tools, f"missing registered tool: {expected}"
