# thebrain-mcp

An MCP server that gives AI assistants full read-write access to [TheBrain](https://www.thebrain.com/) knowledge graphs. Built with Python and [FastMCP](https://github.com/jlowin/fastmcp), deployed on FastMCP Cloud over SSE.

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12-green.svg)](https://www.python.org/)
[![FastMCP](https://img.shields.io/badge/FastMCP-Cloud-purple.svg)](https://www.fastmcp.com/)

---

## What This Is

thebrain-mcp is a [Model Context Protocol](https://modelcontextprotocol.io/) server that bridges AI assistants and TheBrain's knowledge management platform. It exposes 25+ tools covering thoughts, links, attachments, notes, search, and brain management — everything an agent needs to read, create, organize, and query a personal knowledge graph.

The server includes two capabilities that go beyond basic API wrapping:

- **BrainQuery (BQL)** — a Cypher-subset query language purpose-built for TheBrain operations
- **Tollbooth** — a Lightning Network monetization layer for MCP servers

## BrainQuery (BQL)

BrainQuery is a shared formalism: agents and humans express graph operations in the same language, eliminating ambiguity about what an agent intends to do.

It implements the practical subset of [Cypher](https://neo4j.com/developer/cypher/) that maps onto TheBrain's API: `MATCH`, `CREATE`, `SET`, `MERGE`, and `DELETE`. Pattern matching supports variable-length paths, multi-hop chains, compound `WHERE` clauses with `AND`/`OR`/`NOT`/`XOR`, similarity search (`=~`), and property existence checks.

```cypher
-- Find children of a specific thought
MATCH (n {name: "Projects"})-[:CHILD]->(m) RETURN m

-- Fuzzy search across the brain
MATCH (n) WHERE n.name =~ "quarterly review" RETURN n

-- Create a thought under an existing parent
MATCH (p {name: "Ideas"}) CREATE (p)-[:CHILD]->(n {name: "New Concept"})

-- Variable-depth traversal
MATCH (root {name: "Company"})-[:CHILD*1..3]->(d) WHERE d.name CONTAINS "Budget" RETURN d
```

The full grammar, operator reference, and best practices are in [python/BRAINQUERY.md](python/BRAINQUERY.md).

## Tollbooth — API Monetization

> **Tollbooth: a Don't Pester Your Client (DPYC) API Monetization service for Entrepreneurial Bitcoin Advocates**

thebrain-mcp is the first Tollbooth-powered MCP server.

**DPYC** is a direct rebuke of the Know Your Customer (KYC) mantra. Think of Tollbooth as the cash-only lane on an EZPass highway: sure, you *can* subject yourself and your traffic to automated scrutiny, but with Tollbooth and Lightning Network currency, you can monetize with BTC and never have to divulge your bank or financial details. Pre-fund, use, top up. No identity interrogation required.

**How it works:**

1. Client pre-funds an `api_sats` balance via Lightning Network ([BTCPay Server](https://btcpayserver.org/))
2. Each tool call silently debits the balance — no per-request payment prompts
3. Free tools (auth, balance checks) are never gated
4. When the balance runs low, a single `purchase_credits` call tops it up

Zero friction during conversations. No fiat rails, no bank details — just [Bitcoin](https://bitcoin.org/) and [Lightning](https://lightning.network/).

See the [Tollbooth protocol flow diagram](docs/diagrams/tollbooth-protocol-flow.svg) for the full architecture.

## Standing on the Shoulders of Giants

This project exists because of the platforms, protocols, and communities that came before it.

**[TheBrain](https://www.thebrain.com/)** (formerly PersonalBrain) is the knowledge graph platform at the center of this server. Jerry Michalski and the TheBrain team have spent decades building a tool that treats associative linking as a first-class operation. Their cloud API made this integration possible.

**[Bitcoin](https://bitcoin.org/) and the [Lightning Network](https://lightning.network/)** provide the monetary backbone for Tollbooth. The ability to send and receive micropayments without intermediaries, account approvals, or identity disclosure is what makes DPYC possible — a payment philosophy that simply could not exist on fiat rails.

**[BTCPay Server](https://btcpayserver.org/)** handles the payment processing. Self-hosted, open-source, and sovereign — it sits between Tollbooth and the Lightning Network, providing invoice management without requiring a third-party payment processor.

**[Neo4j](https://neo4j.com/) and Cypher** are the syntactic ancestors of BrainQuery. BQL borrows Cypher's expressive pattern-matching syntax and adapts it to TheBrain's graph model. The readability of `MATCH (a)-[:CHILD]->(b)` is a direct inheritance from the Neo4j team's language design.

**[Anthropic](https://www.anthropic.com/) and [Claude](https://claude.ai/)** occupy a dual role here. Claude is both the primary AI consumer of this server and a co-creator of its codebase. The [Model Context Protocol](https://modelcontextprotocol.io/) that makes the entire integration possible is Anthropic's contribution to the open ecosystem of AI tool use.

**[Python](https://www.python.org/) and [FastMCP](https://github.com/jlowin/fastmcp)** are the implementation foundation. FastMCP turns a decorated Python module into a deployed MCP server with SSE transport, cloud hosting, and OAuth — dramatically reducing the distance between "I have an idea" and "it's running in production."

## Getting Started

For installation, configuration, available tools, and usage examples, see [python/README.md](python/README.md).

The live server is deployed on FastMCP Cloud and accessible to any MCP-compatible client.

## Project Structure

```
thebrain-mcp/
├── python/                  # Python/FastMCP server package
│   ├── src/thebrain_mcp/    # Server source code
│   ├── tests/               # Test suite
│   ├── README.md            # Install, config, tools, usage
│   └── BRAINQUERY.md        # BQL grammar and reference
├── docs/
│   └── diagrams/            # Architecture diagrams
├── LICENSE                  # Apache License 2.0
└── NOTICE                   # Attribution notice
```

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE) for details.
