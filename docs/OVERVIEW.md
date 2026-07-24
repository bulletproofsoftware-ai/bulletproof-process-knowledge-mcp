# Overview

`bulletproof-process-knowledge-mcp` is a [Model Context Protocol](https://modelcontextprotocol.io) (MCP)
server that exposes a curated **process-knowledge corpus** to MCP-capable hosts
(Claude Desktop, Claude Code, and any other MCP client). The corpus is stored as
a vector collection named `process_knowledge` in [Qdrant](https://qdrant.tech);
the server sits in front of it and offers three read/validate tools.

## What it does

The server turns a Qdrant collection of process-knowledge records (rules,
decision trees, standard operating procedures, and edge cases) into three
callable MCP tools:

| Tool | Purpose |
|------|---------|
| `process_query` | Semantic (vector) search over the knowledge base, returning the top-K most relevant records. |
| `process_lookup` | Exact-id lookup of a single record by its `id` (with an optional domain hint). |
| `process_validate` | Validate a candidate record against the knowledge schema and flag potential duplicates/contradictions before it is written. |

There is no write tool. This server is **read-and-validate only** — it never
mutates the collection. Ingesting records into Qdrant is the responsibility of a
separate pipeline; this server is the query/guard surface in front of it.

## How it fits together

```
┌────────────────┐   MCP (stdio)   ┌──────────────────────────┐   HTTP REST   ┌──────────┐
│  MCP host       │ ─────────────▶ │ process-knowledge-mcp     │ ────────────▶ │  Qdrant   │
│ (Claude, etc.)  │ ◀───────────── │  (server.py)              │ ◀──────────── │  :6333    │
└────────────────┘   tool results  └──────────────────────────┘   search/scroll└──────────┘
                                          │
                                          │ optional POST (fire-and-forget)
                                          ▼
                                   ┌──────────────┐
                                   │ Audit bus     │  (AUDIT_BUS_URL, optional)
                                   └──────────────┘
```

- **Transport:** MCP over **stdio** (the MCP standard). The host launches the
  process and speaks JSON-RPC over stdin/stdout.
- **Embeddings:** queries are embedded locally with a
  [sentence-transformers](https://www.sbert.net) model
  (`all-MiniLM-L6-v2`, 384 dimensions) — no external embedding API is called.
- **Backend:** Qdrant's HTTP REST API (`points/search`, `points/scroll`,
  `points/{id}`). The server does not use a persistent SDK connection; each call
  is a stateless HTTP request.
- **Audit (optional):** if `AUDIT_BUS_URL` is set, every tool invocation POSTs a
  small event (tool name, arguments, outcome). This is best-effort — an audit
  failure never blocks a tool response.

## Record model

The corpus recognises four `knowledge_type` values, each with a distinct shape
(inferred by `process_validate` when the field is absent):

| `knowledge_type` | Recognised by (heuristic) |
|------------------|----------------------------|
| `rule` | has `condition` **and** `action` |
| `decision_tree` | has a `root` object |
| `sop` | has a `steps` list |
| `edge_case` | has `scenario`, `standard_behavior`, **and** `exception` |

Records are namespaced by a dotted **domain** (e.g. `security.cis_controls`,
`development.testing`). Point IDs in Qdrant are deterministic UUID5 values
derived from `process_knowledge://{domain}/{record_id}`, which lets
`process_lookup` take a fast path when an exact dotted domain is supplied and
fall back to an authoritative payload-field scroll otherwise.

## What is intentionally out of scope

- **No ingestion / write path.** This server only reads and validates.
- **No authentication of MCP callers.** MCP stdio trusts the launching host;
  network exposure (if any) is the operator's responsibility.
- **No embedding API.** Embeddings are computed in-process; the only network
  dependency is Qdrant (and the optional audit bus).

## Documentation map

| Document | Audience |
|----------|----------|
| [INSTALL.md](INSTALL.md) | Getting the server running (local + Docker) |
| [HOW-TO-USE.md](HOW-TO-USE.md) | Calling the three tools; input/output shapes |
| [ADMINISTRATOR.md](ADMINISTRATOR.md) | Configuration, operations, audit, troubleshooting |
| [SBOM.md](SBOM.md) | Dependency inventory and licenses |
| [scan/scan-report.md](scan/scan-report.md) | Security scan results and remediation |

---

Apache-2.0 © 2026 bulletproofsoftware-ai. See [LICENSE](../LICENSE) and [NOTICE](../NOTICE).
