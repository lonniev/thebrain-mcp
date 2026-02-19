# thebrain-mcp

**The first city on the Lightning Turnpike.**

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12-green.svg)](https://www.python.org/)
[![FastMCP](https://img.shields.io/badge/FastMCP-Cloud-purple.svg)](https://www.fastmcp.com/)

An MCP server that gives AI agents read-write access to a personal knowledge graph — and pays for itself with Bitcoin Lightning micropayments.

> *The metaphors in this project are drawn with admiration from* The Phantom Tollbooth *by Norton Juster, illustrated by Jules Feiffer (1961). Milo, Tock, the Tollbooth, Dictionopolis, and Digitopolis are creations of Mr. Juster's extraordinary imagination. We just built the payment infrastructure.*

---

## The First City

Every turnpike needs its first city. Before the booths can collect fares and the authority can stamp purchase orders, someone has to build a destination worth driving to.

thebrain-mcp is that city — a [FastMCP](https://github.com/jlowin/fastmcp) service deployed on Horizon that bridges AI agents to [TheBrain](https://www.thebrain.com/), a personal knowledge graph of 9,000+ interconnected thoughts built over a decade. Every thought, link, attachment, and note operation maps directly to TheBrain's cloud API at [api.bra.in](https://api.bra.in).

It's also the proving ground for [Tollbooth](https://github.com/lonniev/tollbooth-dpyc) — the first MCP server where every tool call is metered via Bitcoin Lightning micropayments. Pre-fund, use, top up. No subscriptions, no API keys tied to billing accounts, no fiat payment processors. The novel contribution: an MCP server architecture where the operator monetizes AI agent access through Lightning micropayments without ever pestering the client mid-conversation.

## Tollbooth Credits

| Tier | Cost | Examples |
|------|------|----------|
| Read | 1 sat | `get_thought`, `search_thoughts`, `get_note` |
| Write | 5 sats | `create_thought`, `create_link`, `update_thought` |
| Heavy | 10 sats | `brain_query`, `get_modifications` |

Auth, balance checks, and credit purchases are always free. First-time users receive a seed balance on registration — enough to explore without purchasing credits up front.

## BrainQuery (BQL)

A Cypher-subset query language purpose-built for TheBrain. Agents and humans express graph operations in the same formalism — full CRUD via `MATCH`, `CREATE`, `SET`, `MERGE`, and `DELETE`.

```cypher
MATCH (n {name: "Projects"})-[:CHILD]->(m) RETURN m
MATCH (n) WHERE n.name =~ "quarterly review" RETURN n
MATCH (p {name: "Ideas"}) CREATE (p)-[:CHILD]->(n {name: "New Concept"})
MATCH (root {name: "Company"})-[:CHILD*1..3]->(d) WHERE d.name CONTAINS "Budget" RETURN d
```

Variable-length paths, multi-hop chains, compound `WHERE` with `AND`/`OR`/`NOT`/`XOR`, similarity search, and property existence checks. Full grammar in [python/BRAINQUERY.md](python/BRAINQUERY.md).

## Getting Started

### Connecting via Horizon MCP

Connect any MCP-compatible client (Claude Desktop, Cursor, your own agent) to the live endpoint:

```
https://personal-brain.fastmcp.app/mcp
```

No configuration needed — Horizon OAuth handles authentication automatically.

### First Connection Walkthrough

1. **`session_status`** — Check your current session state.
2. Get a TheBrain API key at [api.bra.in](https://api.bra.in) and find your brain ID in TheBrain's settings.
3. **`register_credentials(api_key, brain_id, passphrase)`** — Encrypts your credentials in the operator's vault. A seed balance is granted automatically.
4. **`list_brains`** → **`set_active_brain`** — Select which brain to work with.
5. **`brain_query`** — Start exploring your knowledge graph.

Returning users: call **`activate_session(passphrase)`** at the start of each session.

### Self-Hosting

For local installation, configuration, and the full tool reference, see [python/README.md](python/README.md).

To run your own instance, set these environment variables:

| Variable | Purpose | Example |
|----------|---------|---------|
| `THEBRAIN_API_KEY` | Operator's TheBrain API key (for vault access) | `your-thebrain-key` |
| `THEBRAIN_DEFAULT_BRAIN_ID` | Default brain ID for STDIO mode | `uuid-of-brain` |
| `THEBRAIN_API_URL` | TheBrain API base URL | `https://api.bra.in` (default) |
| `THEBRAIN_VAULT_BRAIN_ID` | Brain ID for the encrypted credential vault | `uuid-of-vault-brain` |
| `BTCPAY_HOST` | BTCPay Server URL for credit purchases | `https://btcpay.example.com` |
| `BTCPAY_STORE_ID` | BTCPay store ID | `AbCdEfGh1234` |
| `BTCPAY_API_KEY` | BTCPay API key with invoice + payout permissions | `your-btcpay-api-key` |
| `BTCPAY_TIER_CONFIG` | JSON string mapping tier names to credit multipliers | `{"default": {"credit_multiplier": 1}}` |
| `BTCPAY_USER_TIERS` | JSON string mapping user IDs to tier names | `{"user_01KGZY...": "vip"}` |
| `SEED_BALANCE_SATS` | Free starter balance for new users (0 to disable) | `500` |
| `TOLLBOOTH_ROYALTY_ADDRESS` | Lightning Address for 2% royalty payout | `tollbooth@btcpay.example.com` |
| `TOLLBOOTH_ROYALTY_PERCENT` | Royalty percentage | `0.02` (default) |
| `TOLLBOOTH_ROYALTY_MIN_SATS` | Minimum royalty payout in sats | `10` (default) |

## Architecture

The Tollbooth ecosystem is a three-party protocol spanning three repositories:

| Repo | Role |
|------|------|
| [tollbooth-authority](https://github.com/lonniev/tollbooth-authority) | The institution — tax collection, EdDSA signing, purchase order certification |
| [tollbooth-dpyc](https://github.com/lonniev/tollbooth-dpyc) | The booth — operator-side credit ledger, BTCPay client, tool gating |
| **thebrain-mcp** (this repo) | The first city — reference MCP server powered by Tollbooth |

See the [Three-Party Protocol diagram](https://github.com/lonniev/tollbooth-authority/blob/main/docs/diagrams/tollbooth-three-party-protocol.svg) for the full architecture. The [operator-side flow](docs/diagrams/tollbooth-protocol-flow.svg) is also available.

## Project Structure

```
thebrain-mcp/
├── python/                  # FastMCP server package
│   ├── src/thebrain_mcp/    # Server source, BQL engine, Tollbooth
│   ├── tests/               # Test suite (525+ tests)
│   ├── README.md            # Install, config, tools, usage
│   └── BRAINQUERY.md        # BQL grammar and reference
├── docs/
│   └── diagrams/            # Architecture and protocol flow diagrams
├── LICENSE                  # Apache License 2.0
└── NOTICE                   # Attribution notice
```

## Prior Art & Attribution

The methods, algorithms, and implementations contained in this repository may represent original work by Lonnie VanZandt, first published on February 16, 2026. This public disclosure establishes prior art under U.S. patent law (35 U.S.C. 102).

All use, reproduction, or derivative work must comply with the Apache License 2.0 included in this repository and must provide proper attribution to the original author per the [NOTICE](NOTICE) file.

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

## Further Reading

[The Phantom Tollbooth on the Lightning Turnpike](https://stablecoin.myshopify.com/blogs/our-value/the-phantom-tollbooth-on-the-lightning-turnpike) — the full story of how we're monetizing the monetization of AI APIs, and then fading to the background.

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE) for details.

---

*Because in the end, the tollbooth was never the destination. It was always just the beginning of the journey.*
