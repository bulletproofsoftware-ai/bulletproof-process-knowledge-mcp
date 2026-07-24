# Technical Specification and Operational Manual: bulletproof-process-knowledge-mcp

## 1. System Overview and Architecture

The `bulletproof-process-knowledge-mcp` server provides a hardened, read-only interface for a Qdrant vector database. It facilitates the retrieval and validation of process-specific knowledge—such as rules, standard operating procedures (SOPs), and decision trees—via the Model Context Protocol (MCP). Architecturally, the server acts as a security and validation gateway, ensuring that LLM hosts can access authoritative process data without direct database exposure or mutation capabilities.

### Core Technology Stack

| Component | Technology | Implementation Detail |
| :--- | :--- | :--- |
| **Transport** | MCP stdio | Standard JSON-RPC over stdin/stdout for host communication. |
| **Embeddings** | sentence-transformers | Local execution of `all-MiniLM-L6-v2` (384-dimensional vectors). |
| **Backend** | Qdrant | Stateless interaction via HTTP REST API. Note: While `qdrant-client` is a declared dependency, the runtime uses the `requests` library for REST calls to maintain a lightweight footprint. |
| **Validation** | Pydantic | Strict input modeling with length, range, and type constraints. |

### Scope Boundaries

**In-Scope Capabilities**
*   **Semantic Search:** Vector-based retrieval using local embeddings.
*   **Exact-ID Lookup:** Deterministic point retrieval via unique identifiers.
*   **Schema Validation:** Structural verification of records against a YAML-defined schema.
*   **Type Inference:** Heuristic identification of knowledge types based on field presence.
*   **Duplicate Detection:** Identifying semantic overlaps using cosine similarity thresholds.
*   **Audit Logging:** Fire-and-forget reporting of tool execution to a trusted sink.

**Intentional Out-of-Scope Items**
*   **Data Ingestion:** The server is strictly read-and-validate; collection population is handled by external pipelines.
*   **Authentication:** Relies on the MCP host's trust model; no independent caller authentication is implemented.
*   **External Embedding APIs:** All vectorization is local to eliminate external API latency and dependency.

---

## 2. Core Tool Functionality

### 2.1. Semantic Search (`process_query`)
This tool performs vector searches against the `process_knowledge` collection. It embeds natural language queries locally and returns the top-K matches based on cosine relevance.

**Arguments and Constraints**
| Argument | Type | Required | Constraints | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **query** | string | Yes | 1–2000 chars | The natural language search term. |
| **domain** | string | No | ≤ 200 chars | **Exact-match** filter. No prefix matching is performed. |
| **limit** | integer | No | 1–50 (Default: 5) | Maximum number of results to return. |

*Operational Note:* Because the domain filter is an exact match, users wishing to search across a broad domain tree (e.g., all of `security.*`) should omit the domain filter and rely on semantic relevance or broad queries.

### 2.2. Exact-ID Lookup (`process_lookup`)
Retrieves a specific record from the corpus using a two-tiered resolution strategy.

*   **Fast Path:** If a dotted domain (e.g., `security.cis_controls`) is provided, the server derives a deterministic UUID5 point ID using the URI scheme `process_knowledge://{domain}/{record_id}`. This allows for a direct, high-speed point fetch.
*   **Authoritative Path:** If the fast path fails or no dotted domain is provided, the server performs a scroll operation across the collection filtering by the `id` payload field. 
*   **Domain Filtering:** If a non-dotted domain root is supplied, results are post-filtered to that specific root to ensure architectural alignment.

### 2.3. Schema & Duplicate Validation (`process_validate`)
A dual-purpose tool used to verify candidate records before they are committed to the corpus by external ingestion pipelines.

**Type Inference Triggers**
The server identifies the `knowledge_type` of a candidate record by evaluating its structure:

| Inferred Type | Trigger Condition |
| :--- | :--- |
| **rule** | `condition` and `action` fields are both present. |
| **decision_tree** | The root of the record is an object. |
| **sop** | `steps` field is present as a list. |
| **edge_case** | `scenario`, `standard_behavior`, and `exception` are all present. |

**Validation Logic and Flags**
*   **Schema Check:** The tool returns `valid: true` **only** if the candidate passes all structural requirements defined in the `_schema.yaml`.
*   **Duplicate Detection:** The server embeds the candidate's text (name, condition, action, etc.) and searches the collection. Hits at or above the `DUPLICATE_THRESHOLD` (default 0.85) are flagged.
*   **Advisory Nature:** Crucially, duplicate hits and domain mismatches (calculated via root-prefix matching) are **advisory**. They appear in the response but **do not** flip the `valid` flag to false.

---

## 3. Configuration and Environment Management

The server is configured via environment variables, which are loaded once at startup.

| Environment Variable | Default Value | Notes |
| :--- | :--- | :--- |
| **QDRANT_URL** | `http://localhost:6334` | Qdrant REST endpoint. Docker image overrides this to `http://qdrant:6333`. |
| **QDRANT_API_KEY** | *(None)* | Optional key sent as the `api-key` header for all requests. |
| **EMBEDDING_MODEL** | `sentence-transformers/all-MiniLM-L6-v2` | Used for 384-dim vectorization. |
| **SCHEMA_PATH** | `/knowledge/_schema.yaml` | Essential for `process_validate` schema enforcement. |
| **KNOWLEDGE_ROOT** | `/knowledge` | Read-only source directory (informational). |
| **AUDIT_BUS_URL** | *(None)* | POST endpoint for audit events. **Security Note:** Raw tool inputs are sent here. |
| **DUPLICATE_THRESHOLD**| `0.85` | Minimum cosine score to flag a duplicate record. |

**Configuration Guidance:**
*   **QDRANT_URL:** When deploying in containerized environments, explicitly set this to match your internal networking (e.g., `http://qdrant:6333`).
*   **AUDIT_BUS_URL:** This is a fire-and-forget mechanism with a 2-second timeout. Failure to reach the audit bus will not interrupt tool execution.

---

## 4. Deployment and Installation Procedures

### 4.1. Local Installation
*   **Prerequisites:** Python 3.11+ and a reachable Qdrant instance.
*   **Process:** 
    1. Install dependencies: `pip install -r requirements.txt`.
    2. **Note:** On the first request, the server will download the embedding model (~90MB). Expect a delay of 30s+ during this initial download.
*   **Execution:** `python server.py` enters the stdio loop for MCP hosts.

### 4.2. Docker Deployment
The Docker image is the recommended deployment method for production-grade environments.
*   **Pre-baked Models:** The embedding model is included in the image, eliminating first-request latency.
*   **Security:** Runs as a non-root user (`appuser`, UID 10001) by default.
*   **Read-Only Mount:** Mount the knowledge root as read-only: `-v /path/to/knowledge:/knowledge:ro`.

### 4.3. Host Registration
Add the following to your MCP host configuration (e.g., `mcp.json`):

**Docker Method:**
```json
"process-knowledge": {
  "command": "docker",
  "args": ["run", "-i", "--rm", "-e", "QDRANT_URL=http://host.docker.internal:6333", "-v", "/path/to/knowledge:/knowledge:ro", "bulletproof-process-knowledge-mcp"],
  "notes": "host.docker.internal is used when Qdrant is running on the host machine and the server is in a container."
}
```

**Stdio (Python) Method:**
```json
"process-knowledge": {
  "command": "python",
  "args": ["/path/to/server.py"],
  "env": {
    "QDRANT_URL": "http://localhost:6334",
    "SCHEMA_PATH": "/path/to/_schema.yaml"
  }
}
```

---

## 5. Operational Reference and Security Posture

### 5.1. Security Architecture
1.  **Input Validation:** Pydantic enforces strict bounds (e.g., query ≤ 2000 chars, limit 1–50).
2.  **Error Sanitization:** Internal exceptions are sanitized. Error messages returned to callers are truncated to **200 characters** to prevent information leakage.
3.  **Non-root Execution:** Docker images strictly utilize a non-root user (`appuser`).
4.  **MCP Trust Model:** No external network ports are exposed; the server relies on the security of the stdio transport.
5.  **Secret Handling:** `QDRANT_API_KEY` is never logged and is excluded from audit events.

### 5.2. Audit Logging
Audit events include the tool name, arguments, and outcome (`ok`, `validation_error`, `backend_error`, `not_found`). As tool inputs may contain sensitive natural language, the `AUDIT_BUS_URL` must point to a trusted internal sink.

### 5.3. Troubleshooting Guide

| Symptom | Likely Cause | Action |
| :--- | :--- | :--- |
| `backend_unavailable` error | Incorrect `QDRANT_URL` or missing collection. | Verify URL; confirm `process_knowledge` collection exists. |
| First request hangs >30s | Model download (Local install). | Use Docker or pre-warm with a dummy query. |
| `Unknown knowledge_type` | Schema missing or `SCHEMA_PATH` incorrect. | Verify `_schema.yaml` is mounted and accessible. |
| No duplicates flagged | Qdrant unreachable or high threshold. | Check Qdrant logs; verify `DUPLICATE_THRESHOLD`. |
| Container runs as root | Outdated image version. | Rebuild and verify with `docker run ... id -un` (should be `appuser`). |

---

## 6. Technical Appendix

### 6.1. Software Bill of Materials (SBOM)
Direct dependencies as of the current release:

| Package | Floor Version | Resolved Version | License | Role |
| :--- | :--- | :--- | :--- | :--- |
| **mcp** | >= 1.0.0 | 1.28.1 | MIT | MCP SDK & stdio transport. |
| **qdrant-client**| >= 1.7.0 | 1.18.0 | Apache-2.0 | Declared Qdrant dependency. |
| **sentence-transformers** | >= 2.2.0 | 5.6.1 | Apache-2.0 | Local vectorization logic. |
| **pydantic** | >= 2.0.0 | 2.13.4 | MIT | Data validation. |
| **PyYAML** | >= 6.0 | 6.0.3 | MIT | Schema file parsing. |
| **requests** | >= 2.31.0 | 2.34.2 | Apache-2.0 | Runtime REST communication. |

### 6.2. Error Response Reference
*   **`invalid_arguments`**: Input failed Pydantic validation (includes failure details).
*   **`backend_unavailable`**: Failed to reach Qdrant. Message is truncated to 200 chars.
*   **`unknown_tool`**: The tool name provided is not supported.

### 6.3. Health Verification
Use the CLI test mode for out-of-band verification:
*   `python server.py query '{"query": "test"}'`: Verifies Qdrant connectivity and embeddings.
*   `python server.py validate '{"candidate": {...}, "target_domain": "test"}'`: Verifies schema parsing. **Note:** This can run **offline** (without Qdrant), but duplicate detection will be skipped silently in that mode.