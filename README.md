# bulletproof-process-knowledge-mcp

MCP server exposing the `process_knowledge` Qdrant collection through three tools:

![bulletproof-process-knowledge-mcp — overview](docs/media/infographic.png)

> Deep-dive docs live in [`docs/`](docs/); generated media (infographic, slide deck, video overview, briefing report) live in [`media/`](media/).

| Tool | Purpose |
|------|---------|
| `process_query` | Semantic search over the process knowledge base |
| `process_lookup` | Exact-id record lookup |
| `process_validate` | Validate a candidate record + detect duplicates |

## Quick Start

The server is **read-only** — it queries an existing `process_knowledge` Qdrant
collection and never writes to it. [`ingest.py`](ingest.py) is the companion
writer that creates and populates that collection, and
[`examples/knowledge/`](examples/knowledge/) holds a working corpus you can use
to verify the whole path end to end.

```bash
pip install -r requirements.txt

# 1. Start Qdrant (skip if you already run one)
docker run -d --name qdrant -p 6333:6333 qdrant/qdrant

# 2. Inspect what would be written — contacts nothing
python ingest.py --knowledge-root examples/knowledge --dry-run

# 3. Create the collection and load the example records
python ingest.py --knowledge-root examples/knowledge

# 4. Query it
export SCHEMA_PATH=examples/knowledge/_schema.yaml
python server.py query  '{"query":"disable root ssh access","limit":3}'
python server.py lookup '{"id":"SEC-CIS-001","domain":"security.cis_controls"}'
```

Then replace `examples/knowledge/` with your own YAML and re-run `ingest.py`.
Re-ingesting is idempotent: point ids are derived deterministically from
`{domain}/{id}`, so a record with an unchanged domain and id is updated in
place. Use `--recreate` to drop and rebuild the collection from scratch.

### Authoring knowledge

Each YAML file holds a `records:` list; files beginning with `_` (such as
`_schema.yaml`) are skipped by the ingester. Four knowledge types are supported
— `rule`, `sop`, `edge_case` and `decision_tree` — and
[`examples/knowledge/_schema.yaml`](examples/knowledge/_schema.yaml) declares
the fields each one requires. `process_validate` enforces exactly that schema,
so edit it to match your own conventions.

## Configuration

| Env var | Default | Notes |
|---------|---------|-------|
| `QDRANT_URL` | `http://localhost:6333` | Qdrant HTTP REST endpoint |
| `QDRANT_API_KEY` | _(none)_ | Optional bearer key |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | 384-dim |
| `SCHEMA_PATH` | `/knowledge/_schema.yaml` | Knowledge schema for validation |
| `KNOWLEDGE_ROOT` | `/knowledge` | Source YAML root (read-only) |
| `AUDIT_BUS_URL` | _(none)_ | Optional POST endpoint for tool invocation events |
| `DUPLICATE_THRESHOLD` | `0.85` | Cosine similarity above this flags potential duplicate |

## Running

### Local (stdio for MCP host)
```
pip install -r requirements.txt
python server.py
```

### Docker
```
docker build -t process-knowledge-mcp .
docker run --rm -i \
  -e QDRANT_URL=http://localhost:6333 \
  -e QDRANT_API_KEY="$QDRANT_API_KEY" \
  -v /path/to/knowledge:/knowledge:ro \
  process-knowledge-mcp
```

### CLI test mode
```
python server.py query  '{"query":"docker security","limit":3}'
python server.py lookup '{"id":"SEC-CIS-001"}'
python server.py validate '{"candidate":{"id":"DEV-NEW-001","knowledge_type":"rule","name":"x","condition":"y","action":"z","domain":"development.testing","source":"manual","effective_date":"2026-05-01","status":"active"},"target_domain":"development"}'
```

## Tests

The test suite is fully offline — no Qdrant, no network, and no embedding model
required. It covers the ingest/server point-id contract, the shipped examples,
and `process_validate`'s behaviour when the backend is unreachable.

```bash
pip install pytest
python -m pytest
```

## MCP Host Registration

Add to `mcp.json` or equivalent host config:
```json
{
  "process-knowledge": {
    "command": "docker",
    "args": ["exec", "-i", "process-knowledge-mcp", "python", "/app/server.py"]
  }
}
```

Or stdio direct:
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


## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
