# Installation Guide

## Quick Start

1. **Navigate to the Python directory:**
```bash
cd python
```

2. **Create and activate a virtual environment:**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install the package in development mode:**
```bash
pip install -e .
```

4. **Install development dependencies (optional):**
```bash
pip install -e ".[dev]"
```

5. **Set up your environment:**
```bash
cp .env.example .env
# Edit .env and add your THEBRAIN_API_KEY
```

## Verify Installation

Run the basic example:
```bash
python examples/basic_usage.py
```

Or run tests:
```bash
pytest
```

## Configure Claude Desktop

1. Find your Claude Desktop config file:
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

2. Add the TheBrain MCP server configuration:
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

3. Replace `/absolute/path/to/thebrain-mcp/python` with the actual path

4. Replace `your_api_key_here` with your TheBrain API key

5. Restart Claude Desktop

## Alternative: Install as Package

If you want to install the package system-wide:

```bash
pip install .
```

Then you can use `thebrain-mcp` command directly:

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

## Troubleshooting

### "Module not found" errors
Make sure you're in the `python` directory and have activated your virtual environment.

### "THEBRAIN_API_KEY not set" errors
Check that your `.env` file exists and contains the API key, or that it's set in your Claude Desktop config.

### Type checking fails
Install mypy and development dependencies:
```bash
pip install -e ".[dev]"
mypy src/thebrain_mcp
```
