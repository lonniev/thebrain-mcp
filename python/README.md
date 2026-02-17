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

## Prior Art & Attribution

The methods, algorithms, and implementations contained in this repository may represent original work by Lonnie VanZandt, first published on February 16, 2026. This public disclosure establishes prior art under U.S. patent law (35 U.S.C. 102).

All use, reproduction, or derivative work must comply with the Apache License 2.0 included in this repository and must provide proper attribution to the original author per the NOTICE file.

### How to Attribute

If you use or build upon this work, please include the following in your documentation or source:

    Based on original work by Lonnie VanZandt and Claude.ai
    Originally published: February 16, 2026
    Source: https://github.com/lonniev/thebrain-mcp
    Licensed under Apache License 2.0

### Patent Notice

The author reserves all rights to seek patent protection for the novel methods and systems described herein. Public disclosure of this work establishes a priority date of February 16, 2026. Under the America Invents Act, the author retains a one-year grace period from the date of first public disclosure to file patent applications.

**Note to potential filers:** This public repository and its full Git history serve as evidence of prior art. Any patent application covering substantially similar methods filed after the publication date of this repository may be subject to invalidation under 35 U.S.C. 102(a).

## License

Apache License 2.0 - see [LICENSE](../LICENSE) and [NOTICE](../NOTICE) files for details.

## Support

- **TheBrain API Documentation**: https://api.bra.in
- **Issues**: https://github.com/lonniev/thebrain-mcp/issues
