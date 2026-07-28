# Security Policy

This document describes how to report security vulnerabilities in
**bulletproof-process-knowledge-mcp** and the response commitments of the
maintainers.

## Supported Versions

| Version Range | Supported |
|---------------|-----------|
| `0.1.x` (initial release line) | Yes — receives security fixes |
| Any pre-release / branch builds | No — use only for testing |

When a new minor or major release ships, the previous minor remains supported
for 90 days for security fixes only.

## Reporting a Vulnerability

**Please do NOT open a public GitHub issue for security vulnerabilities.**
Public disclosure before a fix is available puts users at risk.

Report privately via a GitHub security advisory on this repository, or to the
security contact of the organization operating your deployment
(`security@<your-domain>`).

Include:

1. **Affected component** — e.g. `process_query`, `process_lookup`,
   `process_validate`, the audit emitter, or `ingest.py`
2. **Vulnerability class** — e.g. injection, information disclosure,
   denial of service
3. **Impact** — what an adversary can achieve
4. **Reproduction steps** — a minimal proof of concept
5. **Affected version(s)** — git SHA or release tag
6. **Suggested mitigation** (optional)

### Response Targets

| Stage | Target |
|-------|--------|
| Acknowledge receipt | 3 business days |
| Initial severity assessment | 7 business days |
| Fix or documented mitigation for High/Critical | 30 days |
| Public advisory after fix ships | 7 days |

We ask that you allow 90 days before public disclosure, or until a fix ships,
whichever comes first.

## Security Model

### Trust boundaries

- **No caller authentication.** The server speaks MCP over stdio and trusts the
  process that launched it. It performs no authentication or authorization of
  MCP callers. Do not expose it directly to an untrusted network; secure the
  host and transport boundary at the deployment layer.
- **Read-only against Qdrant.** `server.py` never writes to the collection. All
  writes go through `ingest.py`, which is run deliberately by an operator.
  Anyone who can run `ingest.py` with your `QDRANT_API_KEY` can rewrite or
  delete your knowledge corpus — `--recreate` drops the collection.
- **Knowledge records are trusted content.** The server returns record bodies
  verbatim to the MCP host, which typically feeds them to a language model.
  Treat write access to your knowledge YAML as equivalent to influence over
  model behaviour, and review changes accordingly.

### Audit bus caveat

When `AUDIT_BUS_URL` is set, every tool invocation POSTs an event whose
`arguments` field echoes the raw tool input. If callers pass sensitive text in
`query` or `candidate`, that text reaches the audit sink. Point `AUDIT_BUS_URL`
only at a trusted destination. Delivery is fire-and-forget with a 2-second
timeout; failures are swallowed and never block a tool response.

### Secrets

`QDRANT_API_KEY` is read from the environment and never logged. Supply it via
your MCP host configuration or container environment, not on the command line.

### Existing hardening

- **Input validation** — all tool inputs pass through Pydantic models with
  length and range bounds (`query` ≤ 2000 chars, `limit` 1–50).
- **Error sanitization** — internal exceptions become typed error responses;
  backend error messages are truncated to 200 characters and stack traces are
  logged server-side, never returned to the caller.
- **Non-root container** — the Docker image runs as `appuser` (UID 10001).
- **Graceful degradation** — if Qdrant is unreachable, `process_validate` still
  performs schema validation and simply returns no duplicate suggestions. This
  behaviour is covered by the offline test suite.

### Not in scope

- The security of Qdrant itself, or of the embedding model you configure
  (served via `fastembed`/ONNX runtime). Report those upstream.
- Correctness or trustworthiness of the knowledge records you ingest.

## Security Practices in This Repository

- Dependencies are declared with minimum-version constraints in
  `requirements.txt`; the direct dependency inventory with license data is
  documented in [`docs/SBOM.md`](docs/SBOM.md).
- CI runs the offline test suite on every push and blocks on failure.
- GitHub Actions are pinned to full commit SHAs.
- No credentials or environment-specific endpoints are committed.
