# Software Bill of Materials (SBOM)

This project is a single-file Python MCP server. Its dependency surface is the
six direct packages declared in [`requirements.txt`](../requirements.txt), plus
their transitive closure (pulled in at `pip install` time). Below is the
**direct** dependency inventory with license and version data.

## Direct dependencies

`requirements.txt` uses **exact pins** (`==`). The full transitive tree — 55
packages — is pinned in [`requirements.lock.txt`](../requirements.lock.txt); a
fresh venv installed from that lockfile reproduces byte-identically.

| Package | Pinned | License | Role |
|---------|--------|---------|------|
| `mcp` | 1.28.1 | MIT | MCP server SDK (stdio transport, tool wiring) |
| `qdrant-client[fastembed]` | 1.18.0 | Apache-2.0 | Qdrant client; the `fastembed` extra supplies embeddings |
| `pydantic` | 2.13.4 | MIT | Tool-input validation |
| `pyyaml` (`PyYAML`) | 6.0.3 | MIT | Loads the knowledge `_schema.yaml` |
| `requests` | 2.34.2 | Apache-2.0 | HTTP calls to Qdrant and the optional audit bus |

Embeddings arrive through the `qdrant-client[fastembed]` extra rather than a
separate top-level dependency:

| Package | Pinned | License | Role |
|---------|--------|---------|------|
| `fastembed` | 0.8.0 | Apache-2.0 | ONNX-runtime embeddings (`all-MiniLM-L6-v2`, 384-dim) |
| `onnxruntime` | 1.28.0 | MIT | Inference engine |
| `tokenizers` | 0.23.1 | Apache-2.0 | Rust tokenizer |

### License distribution (direct)

| License | Count | Packages |
|---------|-------|----------|
| MIT | 3 | `mcp`, `pydantic`, `PyYAML` |
| Apache-2.0 | 2 | `qdrant-client`, `requests` |

Both MIT and Apache-2.0 are permissive and compatible with this project's
Apache-2.0 license.

## Why not `sentence-transformers`

Embeddings previously came from `sentence-transformers`, which pulls in `torch`
and `transformers`. That stack carried **13 vulnerabilities (8 HIGH / 5 MEDIUM)
with no fix available at any version** — CVE-2026-4538, CVE-2025-14921/-14924/
-14926/-14927/-14928/-14929/-14930 and others, covering *Deserialization of
Untrusted Data* and *Arbitrary Code Injection*. These are inherent
pickle/model-loading risks present in the newest releases, not defects awaiting
patches.

`fastembed` serves the **same model** on ONNX runtime with no torch in its
dependency tree, which removes all 13 findings. Vector output is unchanged:

| Property | Result |
|---|---|
| Dimensions | 384 (unchanged) |
| Cosine similarity vs previous vectors | **1.00000000** |
| Max element delta | 1.3e-07 (float32 rounding) |
| L2 norm | 1.000000 |

**Existing Qdrant collections remain valid — no re-indexing is required.**
The install also shrank from 71 packages to 55, and no longer downloads a
~2 GB torch wheel.

## Transitive dependencies

55 packages total, pinned in `requirements.lock.txt`. The heaviest contributors
are `onnxruntime` (inference), `tokenizers` (Rust), and `numpy`. Licensing is
predominantly MIT / Apache-2.0 / BSD.

To regenerate a resolved CycloneDX SBOM for your target platform:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.lock.txt
.venv/bin/pip install cyclonedx-bom
.venv/bin/cyclonedx-py environment .venv --output-format JSON \
  -o docs/process-knowledge-mcp.cyclonedx.json
```

> The dependency set is now pinned and platform-stable, so a committed
> CycloneDX artifact would be meaningful — unlike the previous ML stack, whose
> transitive closure varied by platform (CPU vs. CUDA `torch` wheels).

## Base image

The Docker image is built `FROM python:3.11-slim` (Debian slim). System build
dependencies (`build-essential`) are installed only to compile Python wheels and
are not required at runtime. The container runs as a non-root user
(`appuser`, UID 10001).

---

Apache-2.0 © 2026 bulletproofsoftware-ai. See [LICENSE](../LICENSE) and [NOTICE](../NOTICE).
