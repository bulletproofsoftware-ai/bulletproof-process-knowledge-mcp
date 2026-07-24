# Installation

`bulletproof-process-knowledge-mcp` is a single-file Python MCP server
(`server.py`). It speaks MCP over **stdio** and requires a reachable
[Qdrant](https://qdrant.tech) instance that already contains a
`process_knowledge` collection.

## Prerequisites

- **Python 3.11+** (the Docker image pins `python:3.11-slim`; CI compiles under 3.12).
- **A Qdrant instance** reachable over HTTP REST with a `process_knowledge`
  collection populated with 384-dimension vectors.
- On first run the server downloads the `sentence-transformers/all-MiniLM-L6-v2`
  model (~90 MB). The Docker image pre-bakes it at build time.

## Option A — Local (stdio)

```bash
pip install -r requirements.txt
python server.py
```

`python server.py` with no arguments enters the MCP stdio loop and blocks
waiting for a host. To exercise it without an MCP host, use the CLI test mode
(see below).

### Direct dependencies

From `requirements.txt` (floor pins; see [SBOM.md](SBOM.md) for resolved versions):

```
mcp>=1.0.0
qdrant-client>=1.7.0
sentence-transformers>=2.2.0
pydantic>=2.0.0
pyyaml>=6.0
requests>=2.31.0
```

> Note: the server talks to Qdrant over raw HTTP via `requests`; `qdrant-client`
> is declared as a dependency but the runtime query paths in `server.py` use the
> REST API directly.

## Option B — Docker

```bash
docker build -t process-knowledge-mcp .

docker run --rm -i \
  -e QDRANT_URL=http://qdrant:6333 \
  -e QDRANT_API_KEY="$QDRANT_API_KEY" \
  -v /path/to/knowledge:/knowledge:ro \
  process-knowledge-mcp
```

The image:

- is based on `python:3.11-slim`,
- pre-downloads the embedding model at build time (first request does not hang),
- runs as a **non-root** user (`appuser`, UID 10001),
- defaults `QDRANT_URL` to `http://qdrant:6333` (override for your network).

Mount your knowledge YAML root read-only at `/knowledge` so the schema
(`/knowledge/_schema.yaml`) is available to `process_validate`. The server never
writes to this mount.

### Verify the container runs as non-root

```bash
docker run --rm --entrypoint sh process-knowledge-mcp -c 'id -un'
# -> appuser
```

## Verifying the install (CLI test mode)

`server.py` accepts a one-shot CLI subcommand (`query`, `lookup`, `validate`)
for smoke-testing without an MCP host. These call the same code paths as the
MCP tools:

```bash
python server.py query  '{"query":"docker security","limit":3}'
python server.py lookup '{"id":"SEC-CIS-001"}'
python server.py validate '{"candidate":{"id":"DEV-NEW-001","knowledge_type":"rule","name":"x","condition":"y","action":"z","domain":"development.testing","source":"manual","effective_date":"2026-05-01","status":"active"},"target_domain":"development"}'
```

If Qdrant is unreachable, `query`/`lookup` return a typed
`{"error":"backend_unavailable", ...}` response rather than a stack trace.
`validate` still performs schema checks even with the backend down (duplicate
detection is skipped silently).

## Registering with an MCP host

Add one of the following to your host's MCP config (e.g. `mcp.json`).

**Via a running Docker container:**

```json
{
  "process-knowledge": {
    "command": "docker",
    "args": ["exec", "-i", "process-knowledge-mcp", "python", "/app/server.py"]
  }
}
```

**Direct stdio:**

```json
{
  "process-knowledge": {
    "command": "python",
    "args": ["/path/to/bulletproof-process-knowledge-mcp/server.py"],
    "env": {
      "QDRANT_URL": "http://localhost:6333",
      "QDRANT_API_KEY": "<secret>",
      "SCHEMA_PATH": "/path/to/knowledge/_schema.yaml"
    }
  }
}
```

See [ADMINISTRATOR.md](ADMINISTRATOR.md) for the full environment-variable
reference and operational guidance.

---

Apache-2.0 © 2026 bulletproofsoftware-ai. See [LICENSE](../LICENSE) and [NOTICE](../NOTICE).
