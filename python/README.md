# TheBrain MCP Server (Python/FastMCP)

A FastMCP server that gives AI agents read-write access to [TheBrain](https://www.thebrain.com/) personal knowledge graphs --- and pays for itself with Bitcoin Lightning micropayments.

## Features

- **49 MCP Tools**: Full CRUD on thoughts, links, attachments, notes, plus compound operations, billing, and auditing
- **BrainQuery (BQL)**: A Cypher-subset query language for pattern-based graph operations --- `MATCH`, `CREATE`, `SET`, `MERGE`, `DELETE` in one tool call
- **Tollbooth Monetization**: Pre-funded Lightning micropayments via BTCPay Server; zero payment friction during conversations
- **Multi-Tenant Credential Vault**: Per-user encrypted credential storage; passphrase-activated sessions
- **OpenTimestamps Bitcoin Anchoring**: Cryptographic proof-of-balance anchored to the Bitcoin blockchain
- **Rich Visual Properties**: Colors, styling, and graphical customization for thoughts and links
- **File Management**: Upload and manage images, documents, and web links as attachments

## Tollbooth --- API Monetization

> the Don't Pester Your Client (DPYC) API Monetization service for Entrepreneurial Bitcoin Advocates

thebrain-mcp is the first Tollbooth-powered MCP server. Tollbooth is the built-in monetization layer that lets operators charge for API usage without interrupting the client's workflow.

**How it works:**
- Clients pre-fund an `api_sats` balance via Lightning Network (BTCPay Server)
- Each tool call silently debits the balance --- no per-request payment prompts
- Free tools (auth, balance checks) are never gated
- If the balance runs low, a single `purchase_credits` call tops it up

**Key principles:**
- **DPYC (Don't Pester Your Client)** --- pre-funded balance means zero payment friction during conversations
- **Lightning-native** --- BTCPay Server + Lightning Network; no fiat rails, no bank details
- **Identity-first** --- layers on Horizon OAuth; never replaces auth with payment
- **Serverless-aware** --- ledger persists across ephemeral FastMCP Cloud deployments

See the [Tollbooth protocol flow diagram](../docs/diagrams/tollbooth-protocol-flow.svg) for the full architecture.

## Installation

### Prerequisites

- Python 3.12
- TheBrain API key ([Get one here](https://api.bra.in))

### Setup

1. Clone this repository:
```bash
cd python
```

2. Create a virtual environment:
```bash
python3.12 -m venv venv
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

### Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `THEBRAIN_API_KEY` | Yes | Operator's TheBrain API key (for vault access) |
| `THEBRAIN_DEFAULT_BRAIN_ID` | No | Default brain ID for STDIO mode |
| `THEBRAIN_API_URL` | No | TheBrain API base URL (default: `https://api.bra.in`) |
| `THEBRAIN_VAULT_BRAIN_ID` | No | Brain ID for the encrypted credential vault |
| `BTCPAY_HOST` | No | BTCPay Server URL for credit purchases |
| `BTCPAY_STORE_ID` | No | BTCPay store ID |
| `BTCPAY_API_KEY` | No | BTCPay API key with invoice + payout permissions |
| `BTCPAY_TIER_CONFIG` | No | JSON string mapping tier names to credit multipliers |
| `BTCPAY_USER_TIERS` | No | JSON string mapping user IDs to tier names |
| `SEED_BALANCE_SATS` | No | Free starter balance for new users (0 = disabled) |
| `NEON_DATABASE_URL` | No | NeonVault Postgres URL for commerce ledger persistence |
| `TOLLBOOTH_OTS_ENABLED` | No | Set to `"true"` to enable OpenTimestamps Bitcoin anchoring |
| `TOLLBOOTH_OTS_CALENDARS` | No | Comma-separated OTS calendar server URLs |
| `TOLLBOOTH_ROYALTY_ADDRESS` | No | Lightning Address for royalty payouts |
| `TOLLBOOTH_ROYALTY_PERCENT` | No | Royalty percentage (default: `0.02`) |
| `TOLLBOOTH_ROYALTY_MIN_SATS` | No | Minimum royalty payout in sats (default: `10`) |
| `CREDIT_TTL_SECONDS` | No | Credit expiration in seconds (default: `604800` = 7 days) |
| `DPYC_OPERATOR_NPUB` | No | Operator's Nostr public key for DPYC identity |
| `DPYC_AUTHORITY_NPUB` | No | Authority's Nostr public key |
| `TOLLBOOTH_NOSTR_AUDIT_ENABLED` | No | Enable Nostr audit trail |
| `TOLLBOOTH_NOSTR_OPERATOR_NSEC` | No | Operator's Nostr secret key for audit signing |
| `TOLLBOOTH_NOSTR_RELAYS` | No | Comma-separated Nostr relay URLs |
| `ATTACHMENT_SAFE_DIRECTORY` | No | Filesystem path for attachment storage (default: `/tmp/thebrain-attachments`) |

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

## Available Tools (49)

### Session & Auth (free)

| Tool | Description |
|------|-------------|
| `whoami` | Return the authenticated user's identity and OAuth claims |
| `register_credentials` | Encrypt and store TheBrain credentials in the operator's vault |
| `activate_session` | Decrypt credentials with your passphrase to start a session |
| `session_status` | Check current session state (active brain, vault, DPYC identity) |
| `upgrade_credentials` | Re-encrypt credentials with updated API key, brain ID, or npub |
| `activate_dpyc` | *(Deprecated)* Bind a Nostr npub to the current session |

### Brain Management (1 sat)

| Tool | Description |
|------|-------------|
| `list_brains` | List all available brains (free) |
| `get_brain` | Get brain details by ID |
| `set_active_brain` | Set the active brain for subsequent operations |
| `get_brain_stats` | Get comprehensive brain statistics (thought/link/attachment counts) |

### Thought Operations

| Tool | Cost | Description |
|------|------|-------------|
| `get_thought` | 1 sat | Retrieve thought details by ID |
| `get_thought_by_name` | 1 sat | Look up a thought by exact name |
| `search_thoughts` | 1 sat | Full-text search across the brain |
| `get_thought_graph` | 1 sat | Get a thought with all its connections (parents, children, jumps, siblings) |
| `get_thought_graph_paginated` | 10 sats | Paginated graph traversal for thoughts with many connections |
| `get_types` | 1 sat | List all thought types defined in the brain |
| `get_tags` | 1 sat | List all tags defined in the brain |
| `create_thought` | 5 sats | Create a thought with optional type, label, colors, and parent link |
| `update_thought` | 5 sats | Update thought properties (name, label, colors, type) |
| `delete_thought` | 5 sats | Delete a thought by ID |

### Link Operations

| Tool | Cost | Description |
|------|------|-------------|
| `get_link` | 1 sat | Get link details by ID |
| `create_link` | 5 sats | Create a link between two thoughts (child, parent, jump, sibling) |
| `update_link` | 5 sats | Modify link properties (name, color, thickness, direction) |
| `delete_link` | 5 sats | Remove a link by ID |

### Attachment Operations

| Tool | Cost | Description |
|------|------|-------------|
| `list_attachments` | 1 sat | List all attachments on a thought |
| `get_attachment` | 1 sat | Get attachment metadata by ID |
| `get_attachment_content` | 1 sat | Download attachment content (base64-encoded) |
| `add_file_attachment` | 5 sats | Attach a file or image to a thought |
| `add_url_attachment` | 5 sats | Attach a web URL to a thought |
| `delete_attachment` | 5 sats | Remove an attachment by ID |

### Note Operations

| Tool | Cost | Description |
|------|------|-------------|
| `get_note` | 1 sat | Retrieve a thought's note in markdown, HTML, or plain text |
| `create_or_update_note` | 5 sats | Create or replace a thought's note (markdown) |
| `append_to_note` | 5 sats | Append markdown content to an existing note |

### BrainQuery and Compound Operations

| Tool | Cost | Description |
|------|------|-------------|
| `brain_query` | 10 sats | Execute a BQL (Cypher-subset) query --- the primary tool for pattern-based graph operations |
| `morph_thought` | 5 sats | Atomically reparent and/or retype a thought in one operation |
| `scan_orphans` | 10 sats | Scan for orphaned thoughts with zero connections; optionally rescue them |
| `event_for_person` | 10 sats | Create an Event linked to a Person and a calendar Day in one action |
| `get_modifications` | 10 sats | View brain modification history (creates, deletes, renames, etc.) |

### Credit & Billing (free unless noted)

| Tool | Cost | Description |
|------|------|-------------|
| `purchase_credits` | free | Generate a Lightning invoice to top up your credit balance |
| `check_payment` | free | Check the status of a pending Lightning invoice |
| `check_balance` | free | View your current credit balance and session stats |
| `account_statement` | free | Detailed transaction history for the last N days |
| `account_statement_infographic` | 1 sat | Visual SVG infographic of your account activity |
| `restore_credits` | free | Recover credits from a paid invoice that was not credited |
| `test_low_balance_warning` | free | Simulate a low-balance warning (testing/debug) |
| `btcpay_status` | free | Check BTCPay Server connectivity and configuration |

### Operator & Auditing

| Tool | Cost | Description |
|------|------|-------------|
| `anchor_ledger` | free | Anchor all ledger balances to Bitcoin via OpenTimestamps (operator-only) |
| `get_anchor_proof` | 1 sat | Get a Merkle inclusion proof for your balance in a Bitcoin anchor |
| `list_anchors` | free | List recent Bitcoin anchor records with status and patron counts |

## BrainQuery (BQL)

`brain_query` is the marquee tool --- a Cypher-subset query language purpose-built for TheBrain. Agents and humans express graph operations in the same formalism:

```cypher
-- Find children of a thought
MATCH (n {name: "Projects"})-[:CHILD]->(m) RETURN m

-- Fuzzy search with similarity ranking
MATCH (n) WHERE n.name =~ "quarterly review" RETURN n

-- Create a thought under an existing parent
MATCH (p {name: "Ideas"}) CREATE (p)-[:CHILD]->(n {name: "New Concept"})

-- Variable-length path traversal (1-3 hops deep)
MATCH (root {name: "Company"})-[:CHILD*1..3]->(d) WHERE d.name CONTAINS "Budget" RETURN d

-- Upsert with conditional SET
MERGE (p {name: "Weekly Review"})
ON CREATE SET p.label = "Created by agent"
ON MATCH SET p.label = "Updated by agent"
RETURN p

-- Delete with preview (dry-run by default, confirm=true to execute)
MATCH (n {name: "Old Note"}) DELETE n
```

BQL supports `MATCH`, `CREATE`, `SET`, `MERGE`, `DELETE`, `WHERE` (with `AND`/`OR`/`NOT`/`XOR`, `IS NULL`/`IS NOT NULL`), variable-length paths (`*1..3`), multi-hop chains, wildcard and union relation types, and property existence checks.

Full grammar, resolution strategy, and examples: **[BRAINQUERY.md](BRAINQUERY.md)**

## DPYC Identity (Nostr npub)

As a Tollbooth Operator, thebrain-mcp needs a Nostr keypair for its identity on the DPYC Honor Chain. Generate one using the script in [tollbooth-dpyc](https://github.com/lonniev/tollbooth-dpyc):

```bash
pip install nostr-sdk
python -c "from nostr_sdk import Keys; k = Keys.generate(); print(f'DPYC_OPERATOR_NPUB={k.public_key().to_bech32()}'); print(f'nsec (back up!): {k.secret_key().to_bech32()}')"
```

Or clone tollbooth-dpyc and run `scripts/generate_nostr_keypair.py` for full output.

Add to your `.env`:

```
DPYC_OPERATOR_NPUB=npub1...
DPYC_AUTHORITY_NPUB=npub1...   # the Authority this Operator is registered with
```

Users provide their own npub at registration time via `register_credentials()`.

## Development

### Running Tests

```bash
cd python
venv/bin/pytest
```

### Type Checking

```bash
venv/bin/mypy src/thebrain_mcp
```

### Code Formatting

```bash
black src/ tests/
ruff check src/ tests/
```

## Known Limitations

- **TheBrain search index is incomplete**: The cloud search index covers a subset of thoughts (typically older/synced ones). Newer thoughts may not appear in `search_thoughts`. Use `get_thought_graph` traversal or BQL scoped paths for reliable access.
- **Graph endpoint caches stale link data**: Azure App Service caching can cause `get_thought_graph` to return deleted links or hide newly created links. The BQL planner tolerates this.
- **Visual styling issues**: Some visual properties (colors, link thickness) may not apply consistently due to TheBrain API limitations.
- **Large files**: Very large attachments may timeout.
- **Long notes**: Keep notes under 10,000 characters for best results.

## Prior Art & Attribution

The methods, algorithms, and implementations contained in this repository may represent original work by Lonnie VanZandt, first published on February 16, 2026. This public disclosure establishes prior art under U.S. patent law (35 U.S.C. 102).

All use, reproduction, or derivative work must comply with the Apache License 2.0 included in this repository and must provide proper attribution to the original author per the NOTICE file.

### How to Attribute

If you use or build upon this work, please include the following in your documentation or source:

    Based on original work by Lonnie VanZandt and Claude.ai
    Originally published: February 16, 2026
    Source: https://github.com/lonniev/thebrain-mcp
    Licensed under Apache License 2.0

Visit the technologist's virtual cafe for Bitcoin advocates and coffee aficionados at [stablecoin.myshopify.com](https://stablecoin.myshopify.com).

### Patent Notice

The author reserves all rights to seek patent protection for the novel methods and systems described herein. Public disclosure of this work establishes a priority date of February 16, 2026. Under the America Invents Act, the author retains a one-year grace period from the date of first public disclosure to file patent applications.

**Note to potential filers:** This public repository and its full Git history serve as evidence of prior art. Any patent application covering substantially similar methods filed after the publication date of this repository may be subject to invalidation under 35 U.S.C. 102(a).

## License

Apache License 2.0 - see [LICENSE](../LICENSE) and [NOTICE](../NOTICE) files for details.

## Support

- **TheBrain API Documentation**: https://api.bra.in
- **Issues**: https://github.com/lonniev/thebrain-mcp/issues
