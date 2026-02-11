"""TheBrain API client using httpx."""

import json
import mimetypes
from pathlib import Path
from typing import Any

import httpx

from thebrain_mcp.api.models import (
    Attachment,
    Brain,
    BrainStats,
    Link,
    Modification,
    Note,
    SearchResult,
    Thought,
    ThoughtGraph,
)
from thebrain_mcp.utils.constants import MIME_TYPES


class TheBrainAPIError(Exception):
    """TheBrain API error."""

    pass


class TheBrainAPI:
    """TheBrain API client."""

    def __init__(self, api_key: str, base_url: str = "https://api.bra.in") -> None:
        """Initialize TheBrain API client.

        Args:
            api_key: TheBrain API key
            base_url: Base URL for TheBrain API
        """
        self.api_key = api_key
        self.base_url = base_url
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()

    async def __aenter__(self) -> "TheBrainAPI":
        """Async context manager entry."""
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Async context manager exit."""
        await self.close()

    async def _request(
        self,
        method: str,
        endpoint: str,
        json_data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Make HTTP request to TheBrain API.

        Args:
            method: HTTP method
            endpoint: API endpoint
            json_data: JSON request body
            files: Files for multipart upload
            params: Query parameters

        Returns:
            Response data (JSON, text, or bytes)

        Raises:
            TheBrainAPIError: If request fails
        """
        try:
            response = await self.client.request(
                method=method,
                url=endpoint,
                json=json_data,
                files=files,
                params=params,
            )
            response.raise_for_status()

            # Handle different response types
            content_type = response.headers.get("content-type", "")

            if "application/json" in content_type:
                return response.json()
            elif method == "DELETE" or response.status_code == 204:
                return {"success": True}
            elif "file-content" in endpoint:
                return response.content
            else:
                return response.text

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
            raise TheBrainAPIError(error_msg) from e
        except Exception as e:
            raise TheBrainAPIError(f"Request failed: {str(e)}") from e

    async def _patch(self, endpoint: str, operations: list[dict[str, Any]]) -> Any:
        """Send a JSON Patch request (bare array, application/json-patch+json)."""
        try:
            response = await self.client.request(
                method="PATCH",
                url=endpoint,
                content=json.dumps(operations),
                headers={"Content-Type": "application/json-patch+json"},
            )
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                return response.json()
            return response.text
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
            raise TheBrainAPIError(error_msg) from e
        except Exception as e:
            raise TheBrainAPIError(f"Request failed: {str(e)}") from e

    # Brain Management

    async def list_brains(self) -> list[Brain]:
        """List all brains."""
        data = await self._request("GET", "/brains")
        return [Brain.model_validate(brain) for brain in data]

    async def get_brain(self, brain_id: str) -> Brain:
        """Get brain details."""
        data = await self._request("GET", f"/brains/{brain_id}")
        return Brain.model_validate(data)

    async def get_brain_stats(self, brain_id: str) -> BrainStats:
        """Get brain statistics."""
        data = await self._request("GET", f"/brains/{brain_id}/statistics")
        return BrainStats.model_validate(data)

    async def get_brain_modifications(
        self,
        brain_id: str,
        max_logs: int | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> list[Modification]:
        """Get brain modification history."""
        params = {}
        if max_logs:
            params["maxLogs"] = max_logs
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        data = await self._request("GET", f"/brains/{brain_id}/modifications", params=params)
        return [Modification.model_validate(mod) for mod in data]

    # Thought Operations

    async def create_thought(self, brain_id: str, thought_data: dict[str, Any]) -> dict[str, Any]:
        """Create a new thought.

        Returns a dict with at least 'id' field. The API may return minimal data,
        so we return the raw response instead of validating as a full Thought.
        """
        data = await self._request("POST", f"/thoughts/{brain_id}", json_data=thought_data)
        return data

    async def get_thought(self, brain_id: str, thought_id: str) -> Thought:
        """Get thought details."""
        data = await self._request("GET", f"/thoughts/{brain_id}/{thought_id}")
        return Thought.model_validate(data)

    async def update_thought(
        self, brain_id: str, thought_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        """Update thought using JSON Patch (bare array format)."""
        patches = [
            {"op": "replace", "path": f"/{key}", "value": value}
            for key, value in updates.items()
        ]
        return await self._patch(f"/thoughts/{brain_id}/{thought_id}", patches)

    async def delete_thought(self, brain_id: str, thought_id: str) -> dict[str, bool]:
        """Delete a thought."""
        return await self._request("DELETE", f"/thoughts/{brain_id}/{thought_id}")

    async def get_thought_graph(
        self, brain_id: str, thought_id: str, include_siblings: bool = False
    ) -> ThoughtGraph:
        """Get thought with all connections."""
        params = {"includeSiblings": str(include_siblings).lower()}
        data = await self._request(
            "GET", f"/thoughts/{brain_id}/{thought_id}/graph", params=params
        )
        return ThoughtGraph.model_validate(data)

    async def search_thoughts(
        self,
        brain_id: str,
        query_text: str,
        max_results: int = 30,
        only_search_thought_names: bool = False,
    ) -> list[SearchResult]:
        """Search for thoughts."""
        params = {
            "queryText": query_text,
            "maxResults": max_results,
            "onlySearchThoughtNames": str(only_search_thought_names).lower(),
        }
        data = await self._request("GET", f"/search/{brain_id}", params=params)
        return [SearchResult.model_validate(result) for result in data]

    async def get_thought_by_name(self, brain_id: str, name_exact: str) -> Thought | None:
        """Get the first thought matching the name exactly.

        Returns None if no thought matches (API returns 404).
        """
        try:
            response = await self.client.request(
                method="GET",
                url=f"/thoughts/{brain_id}",
                params={"nameExact": name_exact},
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list):
                return Thought.model_validate(data[0]) if data else None
            return Thought.model_validate(data)
        except httpx.HTTPStatusError as e:
            raise TheBrainAPIError(f"HTTP {e.response.status_code}: {e.response.text}") from e
        except Exception as e:
            raise TheBrainAPIError(f"Request failed: {str(e)}") from e

    async def get_types(self, brain_id: str) -> list[Thought]:
        """Get all thought types."""
        data = await self._request("GET", f"/thoughts/{brain_id}/types")
        return [Thought.model_validate(t) for t in data]

    async def get_tags(self, brain_id: str) -> list[Thought]:
        """Get all tags."""
        data = await self._request("GET", f"/thoughts/{brain_id}/tags")
        return [Thought.model_validate(t) for t in data]

    # Link Operations

    async def create_link(self, brain_id: str, link_data: dict[str, Any]) -> dict[str, Any]:
        """Create a new link.

        Returns a dict with at least 'id' field. The API may return minimal data,
        so we return the raw response instead of validating as a full Link.
        """
        data = await self._request("POST", f"/links/{brain_id}", json_data=link_data)
        return data

    async def get_link(self, brain_id: str, link_id: str) -> Link:
        """Get link details."""
        data = await self._request("GET", f"/links/{brain_id}/{link_id}")
        return Link.model_validate(data)

    async def update_link(
        self, brain_id: str, link_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        """Update link using JSON Patch (bare array format)."""
        patches = [
            {"op": "replace", "path": f"/{key}", "value": value}
            for key, value in updates.items()
        ]
        return await self._patch(f"/links/{brain_id}/{link_id}", patches)

    async def delete_link(self, brain_id: str, link_id: str) -> dict[str, bool]:
        """Delete a link."""
        return await self._request("DELETE", f"/links/{brain_id}/{link_id}")

    # Attachment Operations

    async def add_file_attachment(
        self, brain_id: str, thought_id: str, file_path: str, file_name: str | None = None
    ) -> dict[str, Any]:
        """Add file attachment to thought."""
        path = Path(file_path)
        if not path.exists():
            raise TheBrainAPIError(f"File not found: {file_path}")

        # Determine MIME type
        mime_type = MIME_TYPES.get(path.suffix.lower())
        if not mime_type:
            mime_type, _ = mimetypes.guess_type(file_path)
        mime_type = mime_type or "application/octet-stream"

        actual_file_name = file_name or path.name

        with open(file_path, "rb") as f:
            files = {"file": (actual_file_name, f, mime_type)}
            return await self._request(
                "POST", f"/attachments/{brain_id}/{thought_id}/file", files=files
            )

    async def add_url_attachment(
        self, brain_id: str, thought_id: str, url: str, name: str | None = None
    ) -> dict[str, Any]:
        """Add URL attachment to thought."""
        params = {"url": url}
        if name:
            params["name"] = name
        return await self._request(
            "POST", f"/attachments/{brain_id}/{thought_id}/url", params=params
        )

    async def get_attachment(self, brain_id: str, attachment_id: str) -> Attachment:
        """Get attachment metadata."""
        data = await self._request("GET", f"/attachments/{brain_id}/{attachment_id}/metadata")
        return Attachment.model_validate(data)

    async def get_attachment_content(self, brain_id: str, attachment_id: str) -> bytes:
        """Get attachment content."""
        return await self._request("GET", f"/attachments/{brain_id}/{attachment_id}/file-content")

    async def delete_attachment(self, brain_id: str, attachment_id: str) -> dict[str, bool]:
        """Delete an attachment."""
        return await self._request("DELETE", f"/attachments/{brain_id}/{attachment_id}")

    async def list_attachments(self, brain_id: str, thought_id: str) -> list[Attachment]:
        """List all attachments for a thought."""
        data = await self._request("GET", f"/thoughts/{brain_id}/{thought_id}/attachments")
        return [Attachment.model_validate(att) for att in data]

    # Note Operations

    async def get_note(self, brain_id: str, thought_id: str, format: str = "markdown") -> Note:
        """Get note content."""
        endpoint = {
            "html": f"/notes/{brain_id}/{thought_id}/html",
            "text": f"/notes/{brain_id}/{thought_id}/text",
            "markdown": f"/notes/{brain_id}/{thought_id}",
        }.get(format, f"/notes/{brain_id}/{thought_id}")

        data = await self._request("GET", endpoint)
        return Note.model_validate(data)

    async def create_or_update_note(
        self, brain_id: str, thought_id: str, markdown: str
    ) -> dict[str, Any]:
        """Create or update a note."""
        return await self._request(
            "POST", f"/notes/{brain_id}/{thought_id}/update", json_data={"markdown": markdown}
        )

    async def append_to_note(
        self, brain_id: str, thought_id: str, markdown: str
    ) -> dict[str, Any]:
        """Append content to a note."""
        return await self._request(
            "POST", f"/notes/{brain_id}/{thought_id}/append", json_data={"markdown": markdown}
        )
