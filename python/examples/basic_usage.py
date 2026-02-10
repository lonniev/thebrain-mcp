"""Basic usage example for TheBrain MCP server."""

import asyncio
import os

from thebrain_mcp.api.client import TheBrainAPI


async def main() -> None:
    """Demonstrate basic API usage."""
    # Get API key from environment
    api_key = os.getenv("THEBRAIN_API_KEY")
    if not api_key:
        print("Error: THEBRAIN_API_KEY environment variable not set")
        return

    # Initialize API client
    async with TheBrainAPI(api_key) as api:
        # List all brains
        print("\n=== Listing Brains ===")
        brains = await api.list_brains()
        for brain in brains:
            print(f"Brain: {brain.name} (ID: {brain.id})")

        if not brains:
            print("No brains found")
            return

        # Use the first brain
        brain_id = brains[0].id
        print(f"\n=== Using Brain: {brains[0].name} ===")

        # Get brain statistics
        print("\n=== Brain Statistics ===")
        stats = await api.get_brain_stats(brain_id)
        print(f"Thoughts: {stats.thoughts}")
        print(f"Links: {stats.links}")
        print(f"Notes: {stats.notes}")

        # Search for thoughts
        print("\n=== Searching Thoughts ===")
        results = await api.search_thoughts(brain_id, "project", max_results=5)
        for result in results:
            thought = result.source_thought
            if thought:
                print(f"Found: {thought.name}")

        # Create a new thought
        print("\n=== Creating Thought ===")
        result = await api.create_thought(
            brain_id,
            {
                "name": "Test Thought from Python",
                "kind": 1,
                "acType": 0,
            },
        )
        thought_id = result["id"]
        print(f"Created thought with ID: {thought_id}")

        # Add a note to the thought
        print("\n=== Adding Note ===")
        await api.create_or_update_note(
            brain_id,
            thought_id,
            "# Test Note\n\nThis is a test note created from Python!",
        )
        print("Note added successfully")

        # Get the note back
        print("\n=== Reading Note ===")
        note = await api.get_note(brain_id, thought_id)
        print(f"Note content:\n{note.markdown}")

        # Clean up - delete the test thought
        print("\n=== Cleaning Up ===")
        await api.delete_thought(brain_id, thought_id)
        print("Test thought deleted")


if __name__ == "__main__":
    asyncio.run(main())
