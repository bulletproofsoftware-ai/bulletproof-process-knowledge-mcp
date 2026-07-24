# Administrator guide

Operational reference for running `bulletproof-process-knowledge-mcp`:
configuration, the audit hook, and troubleshooting.

## Configuration (environment variables)

All configuration is via environment variables, read once into the `Config`
class at import time (`server.py`).

| Env var | Default | Purpose |
|---------|---------|---------|
| `QDRANT_URL` | `http://localhost:6334` | Qdrant HTTP REST base URL. (The Docker image overrides this to `http://qdrant:6333`.) |
| `QDRANT_API_KEY` | _(none)_ | Sent as the `api-key` header on every Qdrant request when set. |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Sentence-transformers model used to embed queries (384-dim). |
| `SCHEMA_PATH` | `/knowledge/_schema.yaml` | YAML schema used by `process_validate`. |
| `KNOWLEDGE_ROOT` | `/knowledge` | Source YAML root (read-only; informational). |
| `AUDIT_BUS_URL` | _(none)_ | If set, tool invocations are POSTed here as audit events. |
| `DUPLICATE_THRESHOLD` | `0.85` | Cosine score at/above which `process_validate` flags a potential duplicate. |

> The `QDRANT_URL` default (`:6334`) matches a REST endpoint on the operator's
> Qdrant. Docker deployments talk to the Qdrant service on `:6333`. Set this
> explicitly for your environment rather than relying on the default.

## The `process_knowledge` collection

The server assumes an existing Qdrant collection named **`process_knowledge`**
holding 384-dimension vectors (matching `all-MiniLM-L6-v2`). Each point's
payload is expected to carry at least:

- `id` — the human-facing record id (authoritative for `process_lookup`)
- `domain` — dotted domain string (e.g. `security.cis_controls`)
- `knowledge_type`, `name`, `status`, `tags`, `source_file`, `record`

Point IDs are deterministic UUID5 values from
`process_knowledge://{domain}/{record_id}`. **Ingestion is out of scope for this
server** — it never writes to the collection. Provisioning and populating
`process_knowledge` is done by a separate pipeline.

## Audit events (optional)

When `AUDIT_BUS_URL` is set, every tool call POSTs a JSON event:

```json
{
  "tool": "process_query",
  "arguments": { "...": "raw input args..." },
  "outcome": "ok",
  "detail": { "hits": 3 },
  "service": "process-knowledge-mcp"
}
```

`outcome` is one of: `ok`, `validation_error`, `backend_error`, `not_found`.
The POST has a 2-second timeout and is **fire-and-forget** — any failure
(including an unreachable bus) is swallowed and never blocks or fails the tool
response. Note that `arguments` echoes the raw tool input; if callers pass
sensitive text in `query`/`candidate`, that text reaches the audit bus. Point
`AUDIT_BUS_URL` only at a trusted sink.

## Security posture

- **Input validation:** all tool inputs pass through Pydantic models with
  length/range bounds (`query` ≤ 2000 chars, `limit` 1–50, etc.).
- **Error sanitization:** internal exceptions are converted to typed error
  responses. Backend error messages are truncated to 200 characters; stack
  traces are logged server-side, never returned to the caller.
- **Non-root container:** the Docker image runs as `appuser` (UID 10001).
- **No caller auth:** MCP stdio trusts the launching host. This server performs
  no authentication of MCP callers — do not expose it directly to untrusted
  networks. Secure the transport/host boundary at the deployment layer.
- **Secrets:** `QDRANT_API_KEY` is read from the environment and never logged.

## Operations

### Health / smoke check

There is no HTTP health endpoint (stdio transport). Use CLI test mode to confirm
the server can reach Qdrant:

```bash
python server.py query '{"query":"ping","limit":1}'
```

- A `results` array (possibly empty) ⇒ Qdrant reachable and collection present.
- `{"error":"backend_unavailable", ...}` ⇒ check `QDRANT_URL`, `QDRANT_API_KEY`,
  network, and that the `process_knowledge` collection exists.

### Logs

The server logs to stderr at `INFO` level
(`%(asctime)s %(levelname)s %(message)s`). The embedder load line
(`Loaded embedder: ...`) appears on first embed. Backend failures log a full
traceback server-side via `logger.exception`.

## Troubleshooting

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| `backend_unavailable` on every call | Wrong `QDRANT_URL`, Qdrant down, or missing collection | Verify URL/port; confirm `process_knowledge` exists in Qdrant. |
| First request hangs for ~30s+ | Embedding model downloading on demand (local install) | Pre-warm with any `query` call, or use the Docker image (model pre-baked). |
| `process_validate` reports `Unknown knowledge_type` | Schema not mounted / wrong `SCHEMA_PATH` | Mount `_schema.yaml` and point `SCHEMA_PATH` at it. |
| `process_validate` never flags duplicates | Backend down (duplicate search is skipped silently) or `DUPLICATE_THRESHOLD` too high | Confirm Qdrant reachable; lower the threshold if needed. |
| `MCP SDK not installed` on startup | `mcp` package missing | `pip install -r requirements.txt`. CLI test mode works without it. |
| Container runs as root | Old image | Rebuild; verify `docker run --rm --entrypoint sh <img> -c 'id -un'` → `appuser`. |

---

Apache-2.0 © 2026 bulletproofsoftware-ai. See [LICENSE](../LICENSE) and [NOTICE](../NOTICE).
