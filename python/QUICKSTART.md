# Quick Start Guide - Running TheBrain MCP Server Locally

## Prerequisites

- Python 3.10 or higher (you have 3.12.10 ✓)
- TheBrain API key ([Get one here](https://api.bra.in))

## Step 1: Navigate to the Python Directory

```bash
cd /Users/lonniev/Development/GitHubPersonal/thebrain-mcp/python
```

## Step 2: Activate Virtual Environment

The virtual environment is already created. Activate it:

```bash
source venv/bin/activate
```

You should see `(venv)` in your terminal prompt.

## Step 3: Add Your API Key

Create a `.env` file with your TheBrain API key:

```bash
# Create .env file
cat > .env << 'EOF'
THEBRAIN_API_KEY=your_api_key_here
THEBRAIN_DEFAULT_BRAIN_ID=optional_brain_id
EOF
```

**Replace `your_api_key_here` with your actual TheBrain API key!**

Or edit manually:
```bash
nano .env  # or use your preferred editor
```

## Step 4: Test the Installation

Run the basic example to verify everything works:

```bash
python examples/basic_usage.py
```

This will:
- List your brains
- Show brain statistics
- Create a test thought
- Add a note to it
- Clean up (delete the test thought)

## Step 5: Run the MCP Server

Start the FastMCP server:

```bash
python -m thebrain_mcp.server
```

The server will start and wait for connections from Claude Desktop.

## Step 6: Configure Claude Desktop

### Find Your Claude Desktop Config

**macOS:**
```bash
open ~/Library/Application\ Support/Claude/
```

**Windows:**
```
%APPDATA%\Claude\
```

### Edit `claude_desktop_config.json`

Add this configuration:

```json
{
  "mcpServers": {
    "thebrain": {
      "command": "python",
      "args": ["-m", "thebrain_mcp.server"],
      "cwd": "/Users/lonniev/Development/GitHubPersonal/thebrain-mcp/python",
      "env": {
        "THEBRAIN_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

**Important:** Replace `your_api_key_here` with your actual API key.

If you already have other MCP servers configured, add the `thebrain` entry to the existing `mcpServers` object:

```json
{
  "mcpServers": {
    "existing-server": {
      ...
    },
    "thebrain": {
      "command": "python",
      "args": ["-m", "thebrain_mcp.server"],
      "cwd": "/Users/lonniev/Development/GitHubPersonal/thebrain-mcp/python",
      "env": {
        "THEBRAIN_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

## Step 7: Restart Claude Desktop

1. Quit Claude Desktop completely
2. Restart Claude Desktop
3. The TheBrain MCP server should now be available

## Step 8: Test in Claude Desktop

In Claude Desktop, try these commands:

```
List my brains
```

```
Set my active brain to [brain name]
```

```
Create a thought called "Test from Python MCP"
```

```
Search for thoughts about "project"
```

## Troubleshooting

### "Module not found" errors

Make sure you're in the right directory and virtual environment is activated:
```bash
cd /Users/lonniev/Development/GitHubPersonal/thebrain-mcp/python
source venv/bin/activate
```

### "THEBRAIN_API_KEY not set"

Check your `.env` file:
```bash
cat .env
```

Make sure it contains:
```
THEBRAIN_API_KEY=your_actual_key
```

### Server won't start in Claude Desktop

Check the Claude Desktop logs:
```bash
# macOS
tail -f ~/Library/Logs/Claude/mcp*.log

# Or check the Claude Desktop developer console
# Help → Toggle Developer Tools → Console tab
```

### Test the server manually

Run the server directly to see any errors:
```bash
python -m thebrain_mcp.server
```

Press Ctrl+C to stop.

## Running Tests

Run the unit tests:
```bash
pytest tests/ -v
```

Run a specific test:
```bash
pytest tests/test_api_client.py -v
```

## Development Mode

If you want to make changes and test them:

1. Edit the source files in `src/thebrain_mcp/`
2. Changes are immediately available (package installed with `-e` flag)
3. Restart the server to pick up changes

## Useful Commands

```bash
# List all installed packages
pip list

# Check package info
pip show thebrain-mcp

# Reinstall if needed
pip install -e .

# Run type checking (if mypy installed)
mypy src/thebrain_mcp

# Format code (if black installed)
black src/ tests/

# Deactivate virtual environment when done
deactivate
```

## Next Steps

- Read the [README.md](README.md) for detailed documentation
- Check [examples/basic_usage.py](examples/basic_usage.py) for API usage examples
- Review [TEST_RESULTS.md](TEST_RESULTS.md) for test coverage

## Getting Help

If you encounter issues:

1. Check the logs in Claude Desktop
2. Run the server manually to see errors
3. Verify your API key is correct
4. Make sure TheBrain is accessible at https://api.bra.in

## Summary

```bash
# 1. Navigate
cd /Users/lonniev/Development/GitHubPersonal/thebrain-mcp/python

# 2. Activate venv
source venv/bin/activate

# 3. Set API key
echo "THEBRAIN_API_KEY=your_key_here" > .env

# 4. Test
python examples/basic_usage.py

# 5. Configure Claude Desktop (see above)

# 6. Restart Claude Desktop and enjoy!
```

That's it! You're ready to use TheBrain with Claude through the Python MCP server. 🎉
