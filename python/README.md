# TheBrain MCP Server (Python/FastMCP)

A FastMCP server that enables AI assistants to interact with TheBrain's knowledge management system. This is a Python implementation using the FastMCP framework.

## Features

- **Complete TheBrain API Coverage**: 25+ tools for managing thoughts, links, attachments, and notes
- **Natural Language Interface**: Interact with TheBrain using plain English through Claude
- **Rich Visual Properties**: Support for colors, styling, and graphical customization
- **File Management**: Upload and manage images, documents, and web links
- **Full-Text Search**: Search across thoughts, notes, and attachments
- **Brain Management**: Switch between multiple brains seamlessly

## Installation

### Prerequisites

- Python 3.10 or higher
- TheBrain API key ([Get one here](https://api.bra.in))

### Setup

1. Clone this repository:
```bash
cd python
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -e .
```

4. Create a `.env` file:
```bash
cp .env.example .env
# Edit .env and add your THEBRAIN_API_KEY
```

## Configuration

### For Claude Desktop

Add to your Claude Desktop configuration (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "thebrain": {
      "command": "python",
      "args": ["-m", "thebrain_mcp.server"],
      "cwd": "/absolute/path/to/thebrain-mcp/python",
      "env": {
        "THEBRAIN_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

Alternatively, if you installed the package:

```json
{
  "mcpServers": {
    "thebrain": {
      "command": "thebrain-mcp",
      "env": {
        "THEBRAIN_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

## Available Tools

### Brain Management
- `list_brains` - List all available brains
- `get_brain` - Get brain details
- `set_active_brain` - Set the active brain for operations
- `get_brain_stats` - Get comprehensive brain statistics

### Thought Operations
- `create_thought` - Create thoughts with visual properties
- `get_thought` - Retrieve thought details
- `update_thought` - Update thought properties
- `delete_thought` - Delete a thought
- `search_thoughts` - Full-text search across the brain
- `get_thought_graph` - Get thought with all connections
- `get_types` - List all thought types
- `get_tags` - List all tags

### Link Operations
- `create_link` - Create links between thoughts with visual properties
- `update_link` - Modify link properties
- `get_link` - Get link details
- `delete_link` - Remove a link

### Attachment Operations
- `add_file_attachment` - Attach files/images to thoughts
- `add_url_attachment` - Attach web URLs
- `get_attachment` - Get attachment metadata
- `get_attachment_content` - Download attachment content
- `delete_attachment` - Remove attachments
- `list_attachments` - List thought attachments

### Note Operations
- `get_note` - Retrieve notes in markdown/html/text
- `create_or_update_note` - Create or update notes
- `append_to_note` - Append content to existing notes

### Advanced Features
- `get_modifications` - View brain modification history

## Usage Examples

### Basic Usage

```python
# In Claude Desktop or via MCP client:

# Set your active brain
"Set my active brain to My Knowledge Base"

# Create a project structure
"Create a project called 'Kitchen Renovation' with phases for planning, demolition, and installation"

# Add rich content
"Add a detailed note about the timeline to the planning phase"

# Search your brain
"Find all thoughts related to contractors"
```

## Development

### Running Tests

```bash
pytest
```

### Type Checking

```bash
mypy src/thebrain_mcp
```

### Code Formatting

```bash
black src/ tests/
ruff check src/ tests/
```

## Known Limitations

- **Visual styling issues**: Some visual properties (colors, link thickness) may not apply consistently due to TheBrain API limitations
- **Large files**: Very large attachments may timeout
- **Long notes**: Keep notes under 10,000 characters for best results

## License

MIT License - see [LICENSE](../LICENSE) file for details.

## Support

- **TheBrain API Documentation**: https://api.bra.in
- **Issues**: https://github.com/redmorestudio/thebrain-mcp/issues
- **Original Node.js version**: See parent directory

## Differences from Node.js Version

This Python implementation uses:
- **FastMCP** instead of MCP SDK for simpler tool registration
- **httpx** for modern async HTTP requests
- **Pydantic** for robust data validation and type safety
- **Type hints** throughout for better IDE support and static analysis
