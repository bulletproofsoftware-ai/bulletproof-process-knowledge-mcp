# Software Bill of Materials (SBOM)

This project is a single-file Python MCP server. Its dependency surface is the
six direct packages declared in [`requirements.txt`](../requirements.txt), plus
their transitive closure (pulled in at `pip install` time). Below is the
**direct** dependency inventory with license and version data.

## Direct dependencies

`requirements.txt` uses floor pins (`>=`). "Resolved" shows the latest version
available on PyPI at the time of writing (what a fresh `pip install` resolves to
for the floor).

| Package | Floor (requirements.txt) | Resolved | License | Role |
|---------|--------------------------|----------|---------|------|
| `mcp` | `>=1.0.0` | 1.28.1 | MIT | MCP server SDK (stdio transport, tool wiring) |
| `qdrant-client` | `>=1.7.0` | 1.18.0 | Apache-2.0 | Declared Qdrant client (runtime paths use REST via `requests`) |
| `sentence-transformers` | `>=2.2.0` | 5.6.1 | Apache-2.0 | Local embedding model (`all-MiniLM-L6-v2`, 384-dim) |
| `pydantic` | `>=2.0.0` | 2.13.4 | MIT | Tool-input validation |
| `pyyaml` (`PyYAML`) | `>=6.0` | 6.0.3 | MIT | Loads the knowledge `_schema.yaml` |
| `requests` | `>=2.31.0` | 2.34.2 | Apache-2.0 | HTTP calls to Qdrant and the optional audit bus |

### License distribution (direct)

| License | Count | Packages |
|---------|-------|----------|
| MIT | 3 | `mcp`, `pydantic`, `PyYAML` |
| Apache-2.0 | 3 | `qdrant-client`, `sentence-transformers`, `requests` |

Both MIT and Apache-2.0 are permissive and compatible with this project's
Apache-2.0 license.

## Transitive dependencies

`sentence-transformers` pulls in a substantial ML stack (`torch`,
`transformers`, `huggingface-hub`, `numpy`, `scikit-learn`, `scipy`, etc.), and
`mcp`/`pydantic` add async and typing helpers (`anyio`, `httpx`,
`pydantic-core`, `starlette`, …). These are permissively licensed
(predominantly MIT / Apache-2.0 / BSD) but the exact set depends on your
platform and Python version at install time.

To produce a full, resolved transitive SBOM in CycloneDX format on your target
platform:

```bash
pip install -r requirements.txt
pip install cyclonedx-bom
cyclonedx-py environment --output-format json > docs/process-knowledge-mcp.cyclonedx.json
```

> A committed CycloneDX artifact is intentionally omitted here: the transitive
> closure of the ML stack is large and platform-dependent (CPU vs. CUDA `torch`
> wheels differ), so a checked-in file would misrepresent any given deployment.
> Generate it in your build environment with the command above.

## Base image

The Docker image is built `FROM python:3.11-slim` (Debian slim). System build
dependencies (`build-essential`) are installed only to compile Python wheels and
are not required at runtime. The container runs as a non-root user
(`appuser`, UID 10001).

---

Apache-2.0 © 2026 bulletproofsoftware-ai. See [LICENSE](../LICENSE) and [NOTICE](../NOTICE).
