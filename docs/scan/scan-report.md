# Security Scan Report

This repository was scanned with **Code Hardener** using the `standard`
profile (12 code-appropriate scanners). All findings were remediated to zero
critical and zero high before publication.

## Result

| Metric | Value |
|--------|-------|
| **Score** | **1000 / 1000** (excellent) |
| **Critical** | **0** |
| **High** | **0** |
| **Medium** | **0** |
| **Low** | 4 (informational — see below) |
| Secrets (gitleaks) | **PASS** (0) |
| Profile | `standard` |
| Attestation | in-toto, `ed25519-local` signed |
| Scan ID | `e0f3fea6-d0ea-443f-b07c-f4dffa66fee4` |

## Scanners executed

`trivy`, `gitleaks`, `opengrep`, `checkov`, `grype`, `syft`,
`package-validator`, `ruff`, `actionlint`, `jscpd`, `typos`, plus file
inventory — all **pass**. `oxlint` was skipped (no JavaScript/TypeScript files
in this Python project; not applicable).

## Findings fixed (critical / high / medium)

The initial `standard` scan surfaced 2 HIGH and 2 MEDIUM findings. Every one was
fixed and confirmed gone on re-scan.

| Severity | Tool | Rule | Location | Fix |
|----------|------|------|----------|-----|
| HIGH | opengrep | `dockerfile.security.missing-user` | `Dockerfile` | Added a dedicated non-root user (`appuser`, UID 10001) created after the root-requiring apt/pip steps; the last `USER` in the image is now non-root. |
| HIGH | dockle | `DS-0002` (image user should not be root) | `Dockerfile` | Same fix — image runs as `appuser`. Verified: `docker run --rm --entrypoint sh <img> -c 'id -un'` → `appuser`, and the pre-baked embedding model loads and embeds (384-dim) as that user. |
| MEDIUM | opengrep | `github-actions-mutable-action-tag` | `.github/workflows/ci.yml` | Pinned `actions/checkout` to `11d5960a326750d5838078e36cf38b85af677262` (# v4). |
| MEDIUM | opengrep | `github-actions-mutable-action-tag` | `.github/workflows/ci.yml` | Pinned `actions/setup-python` to `a26af69be951a213d495a4c3e4e4022e16d87065` (# v5). |

The embedding-model download in the Docker build was moved to run **as
`appuser`** with `HF_HOME` under that user's home, so the model cache is readable
at runtime without root privileges.

## What remains (low-risk, not blocking)

The 4 remaining findings are all `low` and informational. They are documented
here honestly rather than suppressed:

| Rule | Location | Why it is safe to accept |
|------|----------|--------------------------|
| `SBOM-LICENSE-UNKNOWN` (×2) | `.github/workflows/ci.yml` | The scanner cannot resolve a license string for the two pinned GitHub Actions (`actions/checkout`, `actions/setup-python`). Both are official GitHub-maintained actions published under the MIT license; the "unknown" is a metadata-resolution gap, not a real compliance risk. Pinning them to SHAs is the recommended supply-chain hardening. |
| `LICENSE-Apache-2.0` | `LICENSE` | Advisory flag noting this project itself is Apache-2.0 (a `notice`-category license). This is the intended, declared license — no action needed. |
| `DS-0026` (no HEALTHCHECK) | `Dockerfile` | This is an **stdio** MCP server — it has no listening port or HTTP surface, so a container `HEALTHCHECK` has nothing meaningful to probe. Health is verified via the CLI smoke test (`python server.py query '{"query":"ping","limit":1}'`), documented in the administrator guide. |

## Artifacts

| Artifact | File |
|----------|------|
| Rich portal report (PDF) | [`bulletproof-process-knowledge-mcp-scan-report.pdf`](bulletproof-process-knowledge-mcp-scan-report.pdf) |
| Full findings report (Markdown) | [`scan-report-full.md`](scan-report-full.md) |
| SARIF | [`scan-report.sarif.json`](scan-report.sarif.json) |
| Signed attestation (in-toto) | [`attestation.json`](attestation.json) |

---

Apache-2.0 © 2026 bulletproofsoftware-ai. See [../LICENSE](../../LICENSE) and [../NOTICE](../../NOTICE).
