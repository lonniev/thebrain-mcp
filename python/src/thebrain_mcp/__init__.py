"""TheBrain MCP Server - FastMCP server for TheBrain API."""

from importlib.metadata import PackageNotFoundError, version as _pkg_version


def _resolve_version() -> str:
    """Single source of truth: pyproject [project].version. Installed metadata
    first, with a from-source pyproject.toml fallback for deploys that run the
    checkout without installing it."""
    try:
        return _pkg_version("thebrain-mcp")
    except PackageNotFoundError:
        pass
    try:
        import tomllib
        from pathlib import Path
        for parent in Path(__file__).resolve().parents:
            pp = parent / "pyproject.toml"
            if pp.is_file():
                with pp.open("rb") as fh:
                    return tomllib.load(fh)["project"]["version"]
    except Exception:
        pass
    return "0.0.0"


__version__ = _resolve_version()
