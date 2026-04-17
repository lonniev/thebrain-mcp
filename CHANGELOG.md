# Changelog

All notable changes to this project will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.10.0] — 2026-04-13

- security: add proof parameter to all tools with npub

## [1.9.24] — 2026-04-12

- chore: pin tollbooth-dpyc>=0.5.0 — Horizon OAuth removed from wheel

## [1.9.23] — 2026-04-11

- chore: pin tollbooth-dpyc>=0.4.9 — credential validator fix

## [1.9.22] — 2026-04-11

- chore: pin tollbooth-dpyc>=0.4.8 — ncred fix, courier diagnostics

## [1.9.21] — 2026-04-11

- chore: pin tollbooth-dpyc>=0.4.6

## [1.9.20] — 2026-04-11

- chore: pin tollbooth-dpyc>=0.4.0
- remove stale whoami tool — superseded by brain_session_status
- chore: pin tollbooth-dpyc>=0.3.3
- chore: pin tollbooth-dpyc>=0.3.2 — lazy MCP name resolution
- chore: pin tollbooth-dpyc>=0.3.1 — function name MCP stamping
- chore: pin tollbooth-dpyc>=0.3.0 — single tool identity model
- chore: pin tollbooth-dpyc>=0.2.16
- fix: remove Horizon OAuth and STDIO mode — npub-keyed sessions only
- chore: pin tollbooth-dpyc>=0.2.15 for closed-door billing gate
- chore: pin tollbooth-dpyc>=0.2.14
- chore: pin tollbooth-dpyc>=0.2.13
- fix: lint — import ordering
- feat: UUID-keyed internals — paid_tool and registry use UUID, not short names
- chore: pin tollbooth-dpyc>=0.2.11
- chore: pin tollbooth-dpyc>=0.2.10
- chore: pin tollbooth-dpyc>=0.2.9
- chore: pin tollbooth-dpyc>=0.2.8
- chore: pin tollbooth-dpyc>=0.2.7
- chore: pin tollbooth-dpyc>=0.2.6 for reset_pricing_model
- chore: pin tollbooth-dpyc>=0.2.5
- chore: pin tollbooth-dpyc>=0.2.4 for security fix + legacy UUID fallback
- chore: pin tollbooth-dpyc>=0.2.3 for pricing cache invalidation
- fix: lint — import ordering, unused import
- feat: UUID-based tool identity — TOOL_COSTS → TOOL_REGISTRY
- fix: mock flush_user returns True in invoice persistence tests
- chore: pin tollbooth-dpyc>=0.2.0 — clean Neon schema isolation
- chore: pin tollbooth-dpyc>=0.1.191 — don't break credential vault
- chore: pin tollbooth-dpyc>=0.1.190 — schema-qualify all vault queries
- chore: pin tollbooth-dpyc>=0.1.189 — parse schema from URL, not SHOW
- chore: pin tollbooth-dpyc>=0.1.186 — operator-schema-qualified vault tables
- chore: pin tollbooth-dpyc>=0.1.183
- chore: pin tollbooth-dpyc>=0.1.182
- chore: pin tollbooth-dpyc>=0.1.181
- chore: pin tollbooth-dpyc>=0.1.180 — Neon search_path fix
- chore: pin tollbooth-dpyc>=0.1.179 — Neon direct endpoint fix
- chore: pin tollbooth-dpyc>=0.1.178
- chore: pin tollbooth-dpyc>=0.1.177 for runtime identity diagnostics
- chore: pin tollbooth-dpyc>=0.1.176 for flush read-back verification
- chore: pin tollbooth-dpyc>=0.1.175 for vault endpoint diagnostic
- chore: pin tollbooth-dpyc>=0.1.174 for credit persistence reporting
- chore: pin tollbooth-dpyc>=0.1.173 for onboarding late-attach fix
- chore: pin tollbooth-dpyc>=0.1.171 — don't cache empty ledgers on cold start
- chore: pin tollbooth-dpyc>=0.1.170 for cold start fixes
- chore: pin tollbooth-dpyc>=0.1.169 for session_status lifecycle
- feat: use wheel's themed infographic, delete local copy, pin >=0.1.167
- fix: DRY cleanup — remove dead shim, fix operator_id → npub in actor
- fix: add onboarding status methods to actor, fix stale tests
- chore: pin tollbooth-dpyc>=0.1.165 for demurrage constraint rename
- chore: pin tollbooth-dpyc>=0.1.164 for tranche_expiration constraint
- chore: pin tollbooth-dpyc>=0.1.163 for authority_client npub fix
- chore: pin tollbooth-dpyc>=0.1.162 for patron onboarding status
- fix: pin tollbooth-dpyc>=0.1.161 (v0.1.160 never published)
- chore: pin tollbooth-dpyc>=0.1.160
- fix: lifecycle-aware session guidance for all patron-facing states

## [1.9.19] — 2026-03-29

- chore: pin tollbooth-dpyc>=0.1.159, bump to v1.9.18
- refactor: adopt @runtime.paid_tool(), SessionCache, annotate 32 npub params
- fix: forget_credentials clears in-memory sessions via on_forget callback
- fix: revoke_patron_session clears both in-memory and vault
- fix: add _ensure_session to set_active_brain and brain_query (F821)
- fix: hard patron credential gate — no operator API fallback
- chore: bump tollbooth-dpyc to >=0.1.154 (patron forget_credentials)
- fix: security — list_brains requires npub, filters internal brains
- refactor: strip fastmcp.json to nsec-only
- fix: natural language for patron onboarding prompts, not error messages
- fix: global active_brain_id only for STDIO — per-session in Horizon
- chore: bump tollbooth-dpyc to >=0.1.152
- chore: require Python >=3.12 (matches Horizon)
- chore: force Horizon cold start for v0.1.150
- chore: bump tollbooth-dpyc to >=0.1.150
- chore: bump tollbooth-dpyc to >=0.1.149
- chore: bump tollbooth-dpyc to >=0.1.148 (late vault attachment)
- chore: bump tollbooth-dpyc to >=0.1.147
- chore: bump tollbooth-dpyc to >=0.1.146 (no time-based DM filter)
- chore: bump tollbooth-dpyc to >=0.1.145 (courier diagnostics)
- refactor: DRY thebrain-mcp — use wheel core, add session persistence
- chore: bump tollbooth-dpyc to >=0.1.144
- chore: bump tollbooth-dpyc to >=0.1.143
- chore: bump tollbooth-dpyc to >=0.1.138
- chore: bump tollbooth-dpyc to >=0.1.137
- chore: bump tollbooth-dpyc to >=0.1.136
- chore: bump tollbooth-dpyc to >=0.1.135
- chore: bump tollbooth-dpyc to >=0.1.134
- chore: bump tollbooth-dpyc to >=0.1.132
- chore: bump tollbooth-dpyc to >=0.1.131
- chore: bump tollbooth-dpyc to >=0.1.129
- chore: bump tollbooth-dpyc to >=0.1.128
- fix: sort imports in test_credit_tools (I001)
- chore: bump tollbooth-dpyc to >=0.1.127
- refactor: dual credential templates, nsec-only Settings
- refactor: npub required in tool descriptions + dead code cleanup
- feat: credential field descriptions for user guidance
- fix: sort imports in test_credit_tools (I001)
- fix: import _get_multiplier and _get_tier_info from tollbooth wheel
- fix: ruff lint cleanup — unused imports + formatting
- ci: add ruff lint step to CI workflow
- chore: bump tollbooth-dpyc to >=0.1.109
- feat: restore operator-specific Secure Courier greeting
- chore: bump tollbooth-dpyc to >=0.1.108 (infographic restored)
- chore: bump tollbooth-dpyc to >=0.1.107
- fix: delete tests for DPYC boilerplate moved to wheel
- fix: tool catalog expected set matches actual 22 tools
- fix: tool catalog count is 22 (includes onboarding + notarization)
- fix: update tests and imports after OperatorRuntime refactor
- refactor: use OperatorRuntime + register_standard_tools
- refactor: npub is required on all credit tools — no session cache
- refactor: _ensure_dpyc_session accepts explicit npub override

## [1.9.18] — 2026-03-22

- fix: update catalog completeness test for 21 tools (notarization + remove get_tax_rate)

## [1.9.17] — 2026-03-22

- chore: bump version to 1.9.17 for release
- chore: bump tollbooth-dpyc to >=0.1.100 (notarization catalog + remove get_tax_rate)
- chore: bump tollbooth-dpyc to >=0.1.98 (cache migration for perpetual tranches)
- chore: sync uv.lock
- chore: bump tollbooth-dpyc to >=0.1.96 for pricing model bridge
- fix: update test mocks for certify → certify_credits rename
- chore: bump tollbooth-dpyc to >=0.1.95 for certify_credits rename
- refactor: rename certifier.certify() to certify_credits()
- chore: bump tollbooth-dpyc to >=0.1.94 for rollback tranche expiry
- chore: nudge deploy for tollbooth-dpyc v0.1.93 PyPI release
- fix: add missing ACCENT_GOLD color constant to infographic palette
- chore: bump tollbooth-dpyc to >=0.1.93
- chore: add fastmcp.json for Horizon deployment config
- chore: nudge deploy for tollbooth-dpyc v0.1.92 release
- Merge pull request #159 from lonniev/chore/bump-tollbooth-0.1.92
- chore: bump tollbooth-dpyc to >=0.1.92 for ACL support
- fix: extract operator_proof from model_json instead of separate tool arg (#158)
- feat: gate anchor_ledger and set_pricing_model as RESTRICTED, bump to 1.9.16

## [1.9.15] — 2026-03-14

- chore: bump tollbooth-dpyc to >=0.1.91
- feat: gate set_pricing_model to operator-only (Step 0C)
- fix: pricing store bypasses AuditedVault wrapper (#157)
- Merge pull request #156 from lonniev/feat/pricing-crud-tools
- feat: wire pricing CRUD tools for operator self-service
- chore: bump tollbooth-dpyc to >=0.1.83 (#155)

## [1.9.13] — 2026-03-09

- chore: bump tollbooth-dpyc to >=0.1.82, version 1.9.13 (#154)
- chore: bump tollbooth-dpyc to >=0.1.81, version 1.9.12 (#153)

## [1.9.11] — 2026-03-08

- chore: bump version to 1.9.11
- Merge pull request #152 from lonniev/refactor/lookup-cache-path
- refactor: remove redundant dpyc_registry_url config

## [1.9.10] — 2026-03-07

- chore: bump version to 1.9.10
- docs: patron npub hints + fix 15 test failures (#151)

## [1.9.9] — 2026-03-07

- Merge pull request #150 from lonniev/feat/invoice-dm-delivery
- feat: wire invoice DM delivery via Secure Courier
- chore: bump version to 1.9.8 (#149)

## [1.9.8] — 2026-03-07

- feat: add EXPIRES column to account statement infographic (#148)

## [1.9.7] — 2026-03-07

- fix: remove legacy royalty payout + fix tax incidence (#147)
- Merge pull request #146 from lonniev/feat/constraint-gate
- feat: wire ConstraintGate into debit flow (opt-in, off by default)
- chore: update README for current architecture (#145)
- Merge pull request #144 from lonniev/chore/ecosystem-links
- chore: pin tollbooth-dpyc>=0.1.74 for ECOSYSTEM_LINKS
- chore: add ecosystem_links to service_status response
- Merge pull request #143 from lonniev/chore/pin-073
- chore: trigger FastMCP Cloud redeploy for tollbooth-dpyc 0.1.73
- Merge pull request #142 from lonniev/feat/pin-trademark
- chore: pin tollbooth-dpyc>=0.1.72 + trademark notices
- chore: trigger FastMCP Cloud redeploy for tollbooth-dpyc 0.1.71
- chore: trigger FastMCP Cloud redeploy for tollbooth-dpyc 0.1.70
- chore: trigger FastMCP Cloud redeploy for tollbooth-dpyc 0.1.70
- feat: auto-restore DPYC identity from vault on cold start (#141)
- chore: trigger FastMCP Cloud redeploy for tollbooth-dpyc 0.1.69
- docs: update README for v1.9.6 features

## [1.9.6] — 2026-03-04

- Merge pull request #140 from lonniev/feat/credential-card-dm
- feat: consume OPERATOR_BASE_CATALOG from tollbooth-dpyc

## [1.9.5] — 2026-03-03

- chore: trigger FastMCP Cloud redeploy for v1.9.5
- Merge pull request #139 from lonniev/feat/oracle-delegation
- docs: bump version to 1.9.5, add Oracle tools to READMEs
- feat: wire 5 Oracle delegation tools via MCP-to-MCP routing
- chore: bump tollbooth-dpyc pin to >=0.1.67 (#138)
- chore: trigger FastMCP Cloud redeploy for tollbooth-dpyc 0.1.66

## [1.9.4] — 2026-03-03

- Merge pull request #137 from lonniev/feat/auto-certify-purchase
- feat: auto-certify purchase_credits via server-to-server OAuth

## [1.9.3] — 2026-03-03

- Merge pull request #136 from lonniev/feat/slug-prefixing
- feat: slug-prefix all MCP tools with "brain_" to avoid name collisions
- feat: BrainOperator protocol conformance (#135)
- Merge pull request #134 from lonniev/fix/ci-test-failures
- fix: align test imports with tollbooth-dpyc API changes
- Merge pull request #133 from lonniev/chore/bump-tollbooth-dpyc-0.1.62
- chore: bump tollbooth-dpyc to >=0.1.62
- Merge pull request #132 from lonniev/feat/dynamic-relay-negotiation
- feat: dynamic relay negotiation for Secure Courier
- Merge pull request #131 from lonniev/feat/qr-credential-card
- feat: wire QR credential card into receive_credentials tool
- Merge pull request #130 from lonniev/chore/bump-tollbooth-dpyc-0.1.59
- chore: bump tollbooth-dpyc to >=0.1.59
- Merge pull request #129 from lonniev/chore/bump-tollbooth-dpyc-0.1.58
- chore: bump tollbooth-dpyc to >=0.1.58
- Merge pull request #128 from lonniev/chore/bump-tollbooth-dpyc-0.1.57
- chore: bump tollbooth-dpyc to >=0.1.57
- chore: bump tollbooth-dpyc to >=0.1.56 (#127)
- chore: bump tollbooth-dpyc to >=0.1.55 (#126)
- chore: bump tollbooth-dpyc to >=0.1.54 (#125)

## [1.9.1] — 2026-03-01

- fix: unwrap AuditedVault via _inner, not _vault (v1.9.1) (#124)

## [1.9.0] — 2026-03-01

- feat: Secure Courier + NeonCredentialVault, drop PersonalBrainVault (v1.9.0) (#123)
- Merge pull request #122 from lonniev/chore/bump-tollbooth-dpyc-0.1.52
- chore: bump tollbooth-dpyc to >=0.1.52
- Merge pull request #121 from lonniev/fix/delete-link-verified

## [1.8.1] — 2026-03-01

- fix: delete_link_verified distinguishes ghost links from API refusals (v1.8.1)

## [1.8.0] — 2026-03-01

- chore: force redeploy after NSEC-only identity migration
- Merge pull request #120 from lonniev/feat/nsec-only-registry-resolution
- NSEC-only registry resolution: derive authority npub at runtime (v1.8.0)
- Merge pull request #119 from lonniev/feat/python-readme-update
- Rewrite python/README.md to reflect current 49-tool surface
- Bump tollbooth-dpyc minimum to >=0.1.44 (bare-key repair) (#118)
- Bump tollbooth-dpyc minimum to >=0.1.43 (lenient JSON parsing) (#117)
- Bump tollbooth-dpyc minimum to >=0.1.42 (smart-quote sanitization) (#116)
- Bump tollbooth-dpyc minimum to >=0.1.41 (anti-replay poison slug) (#115)
- Bump tollbooth-dpyc minimum to >=0.1.40 (dual-protocol DM + timestamp fix) (#114)
- Bump tollbooth-dpyc minimum to >=0.1.39 (base64 padding fix) (#113)
- Bump tollbooth-dpyc minimum to >=0.1.38 (NIP-17 gift-wrapped DMs) (#112)

## [1.7.0] — 2026-02-27

- Bump version to 1.7.0 (#111)
- Fix morpher and BQL DELETE failing on stale graph cache ghost links (#110)
- Bump tollbooth-dpyc minimum to >=0.1.37 (ConstraintGate middleware) (#109)
- Bump tollbooth-dpyc minimum to >=0.1.35 (SecureCourierService) (#108)
- Merge pull request #107 from lonniev/fix/dep-bump-0.1.34
- Bump tollbooth-dpyc minimum to >=0.1.34 (relay diagnostics + DM notifications)
- Merge pull request #106 from lonniev/fix/zero-cost-session
- Ensure auth/identity tools are zero-cost and add bootstrap deadlock tests
- Merge pull request #105 from lonniev/fix/dep-bump-0.1.33
- Bump tollbooth-dpyc minimum to >=0.1.33 (conversational DM + NIP-17)
- Merge pull request #104 from lonniev/fix/dep-bump-0.1.32
- Bump tollbooth-dpyc minimum to >=0.1.32 (welcome DM + profile)
- Bump tollbooth-dpyc minimum to >=0.1.31 (credential vaulting) (#103)
- Merge pull request #102 from lonniev/fix/dep-bump-0.1.29
- Bump tollbooth-dpyc minimum to >=0.1.29 (Secure Courier)
- Merge pull request #101 from lonniev/fix/dep-bump-0.1.28
- Bump tollbooth-dpyc minimum to >=0.1.28 (NIP-44 encrypted audit)
- Merge pull request #100 from lonniev/fix/dep-bump-0.1.27
- Bump tollbooth-dpyc minimum to >=0.1.27 (Nostr-only)

## [1.6.0] — 2026-02-25

- Merge pull request #99 from lonniev/feat/nostr-only
- Remove authority_public_key — Nostr-only certificate verification
- Merge pull request #98 from lonniev/feat/nostr-certificate
- Wire authority_npub into purchase_credits for Nostr certificate support
- Merge pull request #97 from lonniev/feat/whowhen
- Fix three pre-existing test failures in CI
- Add event_for_person tool to create Event+Person+Day in one action
- Merge pull request #96 from lonniev/feat/concurrent-orphanage
- Parallelize scan_orphans with asyncio.gather to avoid FastMCP Cloud timeout
- Merge pull request #95 from lonniev/feat/orphanage
- Add scan_orphans tool to find and rescue unreachable thoughts
- Merge pull request #94 from lonniev/feat/morpher
- Merge pull request #93 from lonniev/fix/uuid-validation
- Add morph_thought tool for atomic reparent/retype
- Add UUID validation to all API client methods (M-4 security fix)
- Merge pull request #92 from lonniev/fix/security-hardening
- Add path traversal protection, whoami cleanup, and crypto floor bump
- Add .mcp.json to .gitignore
- Merge pull request #91 from lonniev/refactor/certify-credits-rename
- Update references from certify_purchase to certify_credits
- Fix env var passthrough by removing :- default syntax in .fastmcp.yaml
- Trigger redeploy for OTS env var pickup
- Trigger redeploy for OTS Bitcoin anchoring tools

## [1.5.0] — 2026-02-23

- Merge pull request #90 from lonniev/feat/ots-bitcoin-anchoring
- Add OTS Bitcoin anchoring MCP tools (anchor_ledger, get_anchor_proof, list_anchors)
- Merge pull request #89 from lonniev/chore/bump-tollbooth-0.1.22
- Bump tollbooth-dpyc to >=0.1.22
- Trigger redeploy for NeonVault env vars
- Merge pull request #88 from lonniev/feat/neonvault-cutover
- Cut over commerce vault from TheBrainVault to NeonVault + AuditedVault
- Merge pull request #87 from lonniev/chore/bump-tollbooth-0.1.21
- Bump tollbooth-dpyc to >=0.1.21
- Merge pull request #86 from lonniev/chore/bump-tollbooth-0.1.20
- Bump tollbooth-dpyc to >=0.1.20
- Merge pull request #85 from lonniev/chore/bump-tollbooth-0.1.19
- Bump tollbooth-dpyc dependency to >=0.1.19
- Merge pull request #84 from lonniev/fix/pin-tollbooth-0.1.18
- Pin tollbooth-dpyc >= 0.1.18 for vault dedup fix

## [1.4.0] — 2026-02-22

- Merge pull request #83 from lonniev/feat/account-statement-infographic
- Add account_statement_infographic MCP tool (SVG)
- Merge pull request #82 from lonniev/feat/account-statement
- Add account_statement MCP tool for customer purchase/usage reports
- Merge pull request #81 from lonniev/feat/tranche-credit-expiration
- Adopt tranche-based credit expiration from tollbooth-dpyc 0.1.16
- Merge pull request #80 from lonniev/refactor/remove-refresh-config
- Remove refresh_config tool — Horizon redeploy makes it unnecessary
- Merge pull request #79 from lonniev/pin/tollbooth-dpyc-0.1.15
- Pin tollbooth-dpyc>=0.1.15 for soft-delete vault support
- Merge pull request #78 from lonniev/fix/full-uuid-tool-intent
- Add Full UUIDs Required section to server instructions
- Merge pull request #77 from lonniev/fix/pin-tollbooth-0.1.14
- Pin tollbooth-dpyc >= 0.1.14 for child-based vault discovery fix
- Merge pull request #76 from lonniev/fix/pin-tollbooth-0.1.13
- Pin tollbooth-dpyc>=0.1.13 for Azure affinity fix
- Merge pull request #75 from lonniev/refactor/link-based-vault
- Slim CredentialVault to delegate to TheBrainVault with separate vault homes
- Add seed balance recovery to activate_session (#74)
- Merge pull request #73 from lonniev/feat/use-shared-vault
- Use canonical TheBrainVault from tollbooth-dpyc
- Merge pull request #72 from lonniev/fix/restore-credits-cache-key
- Fix credit cache key mismatch in restore_credits and test_low_balance_warning
- Force redeploy to pick up cleaned BTCPay API key
- Force redeploy to fix BTCPay API key auth
- Force redeploy to pick up updated tier env vars
- Merge pull request #71 from lonniev/fix/pin-tollbooth-dpyc-0.1.10
- Pin tollbooth-dpyc >= 0.1.10 for payout processor detection
- Merge pull request #70 from lonniev/fix/pin-tollbooth-dpyc-0.1.9
- Pin tollbooth-dpyc >= 0.1.9 for DPYP protocol versioning
- Merge pull request #69 from lonniev/fix/expose-certificate-param
- Make certificate a required parameter in purchase_credits

## [1.3.0] — 2026-02-20

- Merge pull request #68 from lonniev/feat/upgrade-credentials
- Add upgrade_credentials tool for legacy vault migration
- Merge pull request #67 from lonniev/fix/fastmcp-3-compat
- Fix FastMCP 3.0 compatibility in tests
- Merge pull request #66 from lonniev/feat/npub-primary-identity
- Make npub the sole DPYC identity for all credit operations
- Merge pull request #65 from lonniev/feat/dpyc-identity-and-registry
- Wire DPYC identity into credit operations and session management
- Merge pull request #64 from lonniev/feat/nostr-keypair-docs
- Add DPYC identity (Nostr npub) section to README
- Merge pull request #63 from lonniev/feat/vault-flush-durability
- Vault caching, shutdown timeout, reconciliation hook
- Merge pull request #62 from lonniev/feat/enforce-certificate-trust-chain
- Enforce Authority certificate trust chain in purchase_credits
- Pin tollbooth-dpyc >= 0.1.5 (requires purchase_tax_credits_tool)
- Merge pull request #61 from lonniev/feat/split-purchase-tools
- Switch to purchase_tax_credits_tool (uncertified path)
- Merge pull request #60 from lonniev/feat/version-provenance
- Augment btcpay_status versions with thebrain-mcp package version
- Redeploy to pick up tollbooth-dpyc 0.1.3 with bare base64 keys
- Merge pull request #59 from lonniev/fix/remove-authority-url
- Remove authority_url scaffolding (dead code)
- Redeploy to pick up tollbooth-dpyc 0.1.2 with authority_config support
- Merge pull request #58 from lonniev/feat/wire-authority-config-status
- Wire authority_config into btcpay_status diagnostic output
- Redeploy to pick up tollbooth-dpyc 0.1.1 with mandatory Authority certificate verification
- Merge pull request #57 from lonniev/feat/hero-banner
- Add hero banner SVG showing Claude-to-PersonalBrain data flow
- Merge pull request #56 from lonniev/feat/readme-and-tool-metadata
- Add narrative README voice, env var table, and rich credit tool docstrings
- Merge pull request #55 from lonniev/feat/arch-diagram-link
- Point to canonical three-party protocol diagram in tollbooth-authority
- Merge pull request #54 from lonniev/fix/tollbooth-pypi-dep
- Switch tollbooth-dpyc dependency from git URL to PyPI
- Merge pull request #53 from lonniev/refactor/tollbooth-import
- Import Tollbooth from tollbooth-dpyc package (Task 42 Phase 2)
- Merge pull request #52 from lonniev/refactor/vault-backend-protocol
- Dependency-inject persistence layer via VaultBackend Protocol (Task 46)
- Trigger redeploy for new BTCPay API key with payout permissions
- Trigger redeploy to pick up corrected BTCPAY_API_KEY

## [1.2.0] — 2026-02-18

- Merge pull request #51 from lonniev/feat/hard-gate-royalty-permissions
- Enforce hard gate on royalty payout permissions (Task 44)
- Fix create_payout: BTC decimal amount, payoutMethodId field, BTC-LN default
- Fix BTCPay payout permission check: cancreatenonapprovedpullpayments
- Trigger redeploy for TOLLBOOTH_ROYALTY_* env vars
- Merge pull request #50 from lonniev/feat/3-party-royalty-payout
- Prove 3-party royalty payout via BTCPay Store Payouts API
- Merge pull request #49 from lonniev/feat/daily-ledger-snapshots
- Store daily ledger snapshots as separate child thoughts
- Merge pull request #48 from lonniev/feat/test-low-balance-warning
- Add .claude/ and scripts/ to .gitignore
- Revise README to enhance Tollbooth description
- Merge pull request #47 from lonniev/feat/test-low-balance-warning
- Add server onboarding instructions and update README getting started
- Merge pull request #46 from lonniev/feat/test-low-balance-warning
- Add test_low_balance_warning operator diagnostic tool
- Merge pull request #45 from lonniev/feat/low-balance-agent-hint
- Add low-balance warning guidance to server instructions
- Merge pull request #44 from lonniev/feat/low-balance-warning
- Add low-balance warning with top-up nudge and purchase cap
- Merge pull request #43 from lonniev/feat/seed-balance-config
- Add SEED_BALANCE_SATS to FastMCP Cloud config passthrough
- Merge pull request #42 from lonniev/feat/seed-balance
- Seed new users with starter api_sats balance on registration
- Merge pull request #41 from lonniev/fix/root-readme-rewrite
- Rewrite root README to lead with Tollbooth and TheBrain API
- Merge pull request #40 from lonniev/feat/root-readme
- Add root README.md as repository landing page
- Merge pull request #39 from lonniev/feat/tollbooth-branding
- Brand monetization layer as Tollbooth in GitHub docs
- Merge pull request #38 from lonniev/fix/opportunistic-flush
- Add opportunistic request-driven flush for serverless environments
- Merge pull request #37 from lonniev/feat/invoice-persistence
- Add invoice persistence to UserLedger for audit and credit restoration
- Merge pull request #36 from lonniev/feat/license-and-prior-art
- Add Apache 2.0 license, NOTICE, and prior art attribution
- Merge pull request #35 from lonniev/feat/ledger-hardening
- Add ledger hardening: graceful shutdown, health metrics, monitoring
- Merge pull request #34 from lonniev/refactor/api-sats-rename
- Rename internal credit fields from *_sats to *_api_sats
- Merge pull request #33 from lonniev/fix/ledger-durability
- Add restore_credits tool and credited_invoices idempotency tracking
- Fix ledger credits vanishing: flush to vault on credit-critical paths
- Merge pull request #32 from lonniev/feat/tool-gating-middleware
- Add tool gating middleware to debit credits before paid tool execution
- Trigger redeploy
- Merge pull request #31 from lonniev/feat/btcpay-status-tool
- Add btcpay_status diagnostic tool for config and connectivity checks
- Merge pull request #30 from lonniev/feat/ledger-snapshots
- Add timestamped ledger snapshots before config reset
- Merge pull request #29 from lonniev/feat/refresh-config-tool
- Add refresh_config tool for hot-reloading env vars without redeploy
- Trigger redeploy for updated Horizon env vars
- Add BTCPay env vars to .fastmcp.yaml for Horizon passthrough
- Merge pull request #28 from lonniev/feat/vip-tier-visibility
- Merge pull request #27 from lonniev/feat/bql-path-scoping-guidance
- Show tier name and credit multiplier in purchase_credits and check_balance
- Add path-scoping guidance to BQL tool metadata and reference docs
- Merge pull request #26 from lonniev/fix/diagram-trigger-wallet
- Add Balance Gate trigger and Lightning wallet UX to protocol diagram
- Merge pull request #25 from lonniev/fix/update-protocol-diagram
- Update BTCPay protocol flow diagram to match Phase 1 implementation
- Merge pull request #24 from lonniev/feat/credit-tools
- Task 21 D/E/F: purchase_credits, check_payment, check_balance tools
- Merge pull request #23 from lonniev/refactor/remove-upstream-js
- Remove upstream JS codebase, keep Python-only repo
- Merge pull request #22 from lonniev/feat/ledger-cache
- Task 21C: LedgerCache — in-memory LRU with write-behind flush
- Merge pull request #21 from lonniev/feat/btcpay-credit-foundation
- Task 21 A+B: BTCPay Greenfield client and UserLedger model
- Merge pull request #20 from lonniev/feat/docs-diagrams
- Add docs/diagrams directory with BTCPay protocol flow SVG
- Merge pull request #19 from lonniev/revert/task-19-x402-probe
- Revert "Task 19: x402 Payment Probe Tool"
- Merge pull request #18 from lonniev/feature/task-19-payment-probe
- Add x402 payment probe endpoint to test Horizon 402 pass-through
- Merge pull request #17 from lonniev/fix/keyword-in-strings
- Fix reserved keywords falsely rejected inside quoted strings

## [1.1.0] — 2026-02-14

- Release 1.1.0

## [1.0.0-prior-art] — 2026-02-16

- Merge pull request #35 from lonniev/feat/ledger-hardening
- Add ledger hardening: graceful shutdown, health metrics, monitoring
- Merge pull request #34 from lonniev/refactor/api-sats-rename
- Rename internal credit fields from *_sats to *_api_sats
- Merge pull request #33 from lonniev/fix/ledger-durability
- Add restore_credits tool and credited_invoices idempotency tracking
- Fix ledger credits vanishing: flush to vault on credit-critical paths
- Merge pull request #32 from lonniev/feat/tool-gating-middleware
- Add tool gating middleware to debit credits before paid tool execution
- Trigger redeploy
- Merge pull request #31 from lonniev/feat/btcpay-status-tool
- Add btcpay_status diagnostic tool for config and connectivity checks
- Merge pull request #30 from lonniev/feat/ledger-snapshots
- Add timestamped ledger snapshots before config reset
- Merge pull request #29 from lonniev/feat/refresh-config-tool
- Add refresh_config tool for hot-reloading env vars without redeploy
- Trigger redeploy for updated Horizon env vars
- Add BTCPay env vars to .fastmcp.yaml for Horizon passthrough
- Merge pull request #28 from lonniev/feat/vip-tier-visibility
- Merge pull request #27 from lonniev/feat/bql-path-scoping-guidance
- Show tier name and credit multiplier in purchase_credits and check_balance
- Add path-scoping guidance to BQL tool metadata and reference docs
- Merge pull request #26 from lonniev/fix/diagram-trigger-wallet
- Add Balance Gate trigger and Lightning wallet UX to protocol diagram
- Merge pull request #25 from lonniev/fix/update-protocol-diagram
- Update BTCPay protocol flow diagram to match Phase 1 implementation
- Merge pull request #24 from lonniev/feat/credit-tools
- Task 21 D/E/F: purchase_credits, check_payment, check_balance tools
- Merge pull request #23 from lonniev/refactor/remove-upstream-js
- Remove upstream JS codebase, keep Python-only repo
- Merge pull request #22 from lonniev/feat/ledger-cache
- Task 21C: LedgerCache — in-memory LRU with write-behind flush
- Merge pull request #21 from lonniev/feat/btcpay-credit-foundation
- Task 21 A+B: BTCPay Greenfield client and UserLedger model
- Merge pull request #20 from lonniev/feat/docs-diagrams
- Add docs/diagrams directory with BTCPay protocol flow SVG
- Merge pull request #19 from lonniev/revert/task-19-x402-probe
- Revert "Task 19: x402 Payment Probe Tool"
- Merge pull request #18 from lonniev/feature/task-19-payment-probe
- Add x402 payment probe endpoint to test Horizon 402 pass-through
- Merge pull request #17 from lonniev/fix/keyword-in-strings
- Fix reserved keywords falsely rejected inside quoted strings
- Merge pull request #16 from lonniev/chore/trigger-deploy
- Bump version to 1.1.0 to trigger deploy
- Merge pull request #15 from lonniev/task-16-wildcard-relations
- Add wildcard and union relation types to BrainQuery
- Merge pull request #14 from lonniev/feat/delete-operations
- Add DELETE and DETACH DELETE support to BrainQuery
- Merge pull request #13 from lonniev/feat/merge-upsert
- Add MERGE (upsert) support to BrainQuery
- Merge pull request #12 from lonniev/feat/set-properties
- Add SET clause for updating thought properties in BrainQuery
- Merge pull request #11 from lonniev/feat/is-null-operators
- Add IS NULL / IS NOT NULL property existence checks to BrainQuery
- Merge pull request #10 from lonniev/fix/bare-not-traversal
- Fix bare NOT on traversal targets with type labels
- Merge pull request #9 from lonniev/task-14-tool-intent-metadata
- Update tool descriptions with operational intent and selection guide
- Merge pull request #8 from lonniev/feat/compound-where-clauses
- Add NOT and XOR operators to compound WHERE clauses
- Add compound WHERE clauses (AND/OR) to BrainQuery
- Merge pull request #7 from lonniev/feat/variable-length-paths
- Add Python CI workflow for the MCP server
- Add variable-length paths and multi-hop chains to BrainQuery
- Merge pull request #6 from lonniev/feat/name-matching-modes
- Add BrainQuery name matching modes: STARTS WITH, ENDS WITH, =~
- Add brain_query tool with lazy import to prevent startup crash
- Merge pull request #4 from lonniev/feat/brainquery-planner
- Implement BrainQuery planner and executor
- Merge pull request #3 from lonniev/feat/brainquery-parser
- Implement BrainQuery parser with lark
- Merge pull request #2 from lonniev/feat/brainquery-grammar
- Add BrainQuery grammar specification
- Merge pull request #1 from lonniev/feat/paginated-graph-traversal
- Add get_thought_graph_paginated tool for cursor-based graph traversal
- Refactor credential vault into single-responsibility CredentialVault class
- Clean up diagnostics, document search index limitation
- Make Attachment.name optional to fix get_thought_graph
- Add debug_api_call tool to trace raw search/nameExact requests
- Handle 404 as not-found in get_thought_by_name
- Debug get_thought_by_name: handle list response, expose errors
- Add nameExact lookup, fix SearchResult model to match API spec
- Fix JSON Patch: send bare array, not wrapped object
- Add multi-tenant credential vault
- Decode JWT and capture FastMCP Cloud headers in whoami
- Make whoami diagnostic: probe all auth paths and transport info
- Fix whoami: call get_access_token() at runtime, not import time
- Add whoami diagnostic tool to inspect OAuth claims
- Move .fastmcp.yaml to python directory for auto-deployment
- Add FastMCP deployment config for auto-deployment
- Add requirements-deploy.txt for local installation
- Fix remote deployment: explicit dependencies in requirements.txt
- Ensure settings loaded when getting brain ID
- Fix: Defer settings loading to runtime for remote deployment
- Add requirements.txt for remote deployment
- Add Python FastMCP implementation
- Add test GitHub Action workflow
- Add MIT license and update README with realistic limitations
- Add comprehensive documentation and configuration files
- Fix JSON Patch format for update operations
- Fix critical bug: Authorization header was being overwritten by custom headers
- Fix MCP tool result format - use direct string in text field, not nested object
- Initial commit: TheBrain MCP Server v1.0.0

