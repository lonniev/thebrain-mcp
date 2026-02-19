# thebrain-mcp

An MCP server that gives AI agents read-write access to a personal knowledge graph — and pays for itself with Bitcoin Lightning micropayments.

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12-green.svg)](https://www.python.org/)
[![FastMCP](https://img.shields.io/badge/FastMCP-Cloud-purple.svg)](https://www.fastmcp.com/)

Built with [FastMCP](https://github.com/jlowin/fastmcp). Deployed on FastMCP Cloud over SSE. Connect at `https://personal-brain.fastmcp.app/mcp`.

---

## Tollbooth — the Don't Pester Your Client (DPYC) API Monetization service for Entrepreneurial Bitcoin Advocates

Tollbooth is the built-in monetization layer that gates AI agent access behind Bitcoin Lightning micropayments. No subscriptions, no API keys tied to billing accounts, no fiat payment processors.

**The flow:**

1. User authenticates via [Horizon OAuth](https://www.fastmcp.com/)
2. Purchases credits by paying a Lightning invoice through [BTCPay Server](https://btcpayserver.org/) — self-hosted, sovereign, no KYC
3. Every tool call is metered by the `@paid_tool` decorator against an `api_sats` balance
4. Balance is tracked in a serverless-aware ledger with opportunistic flush across ephemeral deployments

**Three pricing tiers:**

| Tier | Cost | Examples |
|------|------|----------|
| Read | 1 sat | `get_thought`, `search_thoughts`, `get_note` |
| Write | 5 sats | `create_thought`, `create_link`, `update_thought` |
| Heavy | 10 sats | `brain_query`, `get_modifications` |

Auth, balance checks, and credit purchases are always free.

This is the novel contribution: an MCP server architecture where the operator monetizes AI agent access through Lightning micropayments without ever pestering the client mid-conversation. Pre-fund, use, top up.

See the [Three-Party Protocol diagram](https://github.com/lonniev/tollbooth-authority/blob/main/docs/diagrams/tollbooth-three-party-protocol.svg) for the full architecture. The [operator-side flow](docs/diagrams/tollbooth-protocol-flow.svg) is also available.

## Built on TheBrain's PersonalBrain API

This project would not exist without [TheBrain](https://www.thebrain.com/) and its REST API at [api.bra.in](https://api.bra.in).

TheBrain is the knowledge management platform underneath — a personal knowledge graph of 9,000+ interconnected thoughts built over a decade. thebrain-mcp is the bridge that lets AI agents read, write, and query that graph through TheBrain's cloud API. Every thought, link, attachment, and note operation in this server maps directly to a TheBrain API endpoint.

The 30+ MCP tools exposed by this server cover thoughts, links, attachments, notes, search, types, tags, brain management, and modification history. Multi-tenant access is handled through an encrypted credential vault backed by Horizon OAuth.

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

Connect any MCP-compatible client to the live endpoint:

```
https://personal-brain.fastmcp.app/mcp
```

No configuration needed — Horizon OAuth handles authentication automatically.

**First-time setup:**

1. Get a TheBrain API key at [api.bra.in](https://api.bra.in)
2. On first connection, call `session_status` to check your session
3. Register with `register_credentials(api_key, brain_id, passphrase)` — a seed balance is granted automatically
4. Start exploring: `list_brains` → `set_active_brain` → `brain_query`

For local installation, configuration, and the full tool reference, see [python/README.md](python/README.md).

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

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE) for details.
