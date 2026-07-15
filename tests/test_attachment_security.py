"""Tests for attachment path traversal protection (H-1)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from thebrain_mcp.tools.attachments import (
    PathTraversalError,
    _validate_path_within,
    add_file_attachment_tool,
    get_attachment_content_tool,
)


class TestValidatePathWithin:
    def test_relative_path_within_safe_dir(self, tmp_path: Path) -> None:
        """Relative path inside safe directory is allowed."""
        safe_dir = str(tmp_path)
        (tmp_path / "file.txt").touch()
        result = _validate_path_within("file.txt", safe_dir)
        assert result == tmp_path / "file.txt"

    def test_nested_relative_path(self, tmp_path: Path) -> None:
        """Nested relative path inside safe directory is allowed."""
        safe_dir = str(tmp_path)
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "file.txt").touch()
        result = _validate_path_within("subdir/file.txt", safe_dir)
        assert result == sub / "file.txt"

    def test_traversal_blocked(self, tmp_path: Path) -> None:
        """Path with ../ that escapes safe directory is blocked."""
        safe_dir = str(tmp_path / "safe")
        (tmp_path / "safe").mkdir()
        with pytest.raises(PathTraversalError, match="resolves outside"):
            _validate_path_within("../etc/passwd", safe_dir)

    def test_absolute_path_outside_blocked(self, tmp_path: Path) -> None:
        """Absolute path outside safe directory is blocked."""
        safe_dir = str(tmp_path / "safe")
        (tmp_path / "safe").mkdir()
        with pytest.raises(PathTraversalError, match="resolves outside"):
            _validate_path_within("/etc/passwd", safe_dir)

    def test_absolute_path_inside_allowed(self, tmp_path: Path) -> None:
        """Absolute path within safe directory is allowed."""
        safe_dir = str(tmp_path)
        target = tmp_path / "file.txt"
        target.touch()
        result = _validate_path_within(str(target), safe_dir)
        assert result == target

    def test_symlink_escape_blocked(self, tmp_path: Path) -> None:
        """Symlink pointing outside safe directory is blocked."""
        safe_dir = tmp_path / "safe"
        safe_dir.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("secret")
        link = safe_dir / "sneaky_link"
        link.symlink_to(outside)
        with pytest.raises(PathTraversalError, match="resolves outside"):
            _validate_path_within("sneaky_link", str(safe_dir))

    def test_double_dot_in_middle_blocked(self, tmp_path: Path) -> None:
        """Path with ../ in the middle that escapes is blocked."""
        safe_dir = str(tmp_path / "safe")
        (tmp_path / "safe").mkdir()
        with pytest.raises(PathTraversalError, match="resolves outside"):
            _validate_path_within("subdir/../../etc/passwd", safe_dir)


class TestAddFileAttachmentPathValidation:
    @pytest.mark.asyncio
    async def test_traversal_returns_error(self, tmp_path: Path) -> None:
        """add_file_attachment_tool rejects traversal paths."""
        api = MagicMock()
        safe_dir = str(tmp_path / "safe")
        (tmp_path / "safe").mkdir()

        result = await add_file_attachment_tool(
            api, "brain-1", "thought-1", "../../../etc/passwd",
            safe_directory=safe_dir,
        )

        assert result["success"] is False
        assert "resolves outside" in result["error"]
        api.add_file_attachment.assert_not_called()

    @pytest.mark.asyncio
    async def test_valid_path_proceeds(self, tmp_path: Path) -> None:
        """add_file_attachment_tool allows valid paths within safe dir."""
        api = MagicMock()
        api.add_file_attachment = AsyncMock()
        safe_dir = str(tmp_path)
        test_file = tmp_path / "valid.txt"
        test_file.write_text("hello")

        result = await add_file_attachment_tool(
            api, "brain-1", "thought-1", "valid.txt",
            safe_directory=safe_dir,
        )

        assert result["success"] is True
        api.add_file_attachment.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_safe_directory_skips_validation(self) -> None:
        """Without safe_directory, path validation is skipped."""
        api = MagicMock()
        api.add_file_attachment = AsyncMock()

        # Create a temp file that exists
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"test")
            temp_path = f.name

        try:
            result = await add_file_attachment_tool(
                api, "brain-1", "thought-1", temp_path,
            )
            assert result["success"] is True
        finally:
            os.unlink(temp_path)


class TestGetAttachmentContentPathValidation:
    @pytest.mark.asyncio
    async def test_traversal_save_path_returns_error(self, tmp_path: Path) -> None:
        """get_attachment_content_tool rejects traversal in save_to_path."""
        api = MagicMock()
        api.get_attachment_content = AsyncMock(return_value=b"data")
        safe_dir = str(tmp_path / "safe")
        (tmp_path / "safe").mkdir()

        result = await get_attachment_content_tool(
            api, "brain-1", "att-1",
            save_to_path="../../../etc/evil",
            safe_directory=safe_dir,
        )

        assert result["success"] is False
        assert "resolves outside" in result["error"]

    @pytest.mark.asyncio
    async def test_valid_save_path_proceeds(self, tmp_path: Path) -> None:
        """get_attachment_content_tool allows valid save paths within safe dir."""
        api = MagicMock()
        api.get_attachment_content = AsyncMock(return_value=b"file content")
        safe_dir = str(tmp_path)

        result = await get_attachment_content_tool(
            api, "brain-1", "att-1",
            save_to_path="downloaded.bin",
            safe_directory=safe_dir,
        )

        assert result["success"] is True
        assert (tmp_path / "downloaded.bin").read_bytes() == b"file content"
