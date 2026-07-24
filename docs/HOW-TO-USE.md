# How to use

This server exposes exactly three MCP tools. Every tool input is validated with
[Pydantic](https://docs.pydantic.dev); invalid input returns a typed
`{"error":"invalid_arguments", "detail": [...]}` response rather than throwing.
Backend (Qdrant) failures return `{"error":"backend_unavailable", ...}`.

All examples below use the CLI test mode (`python server.py <cmd> '<json>'`),
which calls the identical dispatch path as the MCP tools. From an MCP host you
call them by tool name with the same argument object.

---

## `process_query` — semantic search

Embeds the query locally and runs a vector search against the `process_knowledge`
collection, returning the top-K matches ranked by cosine relevance.

**Arguments**

| Field | Type | Required | Constraints | Default |
|-------|------|----------|-------------|---------|
| `query` | string | yes | 1–2000 chars | — |
| `domain` | string | no | ≤ 200 chars; exact-match filter on the `domain` payload field | none (no filter) |
| `limit` | integer | no | 1–50 | 5 |

**Example**

```bash
python server.py query '{"query":"how do we harden docker containers","domain":"security.cis_controls","limit":3}'
```

**Response shape**

```json
{
  "results": [
    {
      "score": 0.83,
      "id": "SEC-CIS-001",
      "knowledge_type": "rule",
      "domain": "security.cis_controls",
      "name": "...",
      "status": "active",
      "tags": ["..."],
      "source_file": "...",
      "record": { "...": "full payload record..." }
    }
  ],
  "query": "how do we harden docker containers",
  "domain_filter": "security.cis_controls"
}
```

> The `domain` filter is an **exact** match on the stored `domain` value. To
> search a whole domain tree, omit `domain` (or query broadly) — `process_query`
> does not do prefix matching. (`process_validate` does use root-prefix matching
> internally for duplicate detection; see below.)

---

## `process_lookup` — exact-id lookup

Fetches a single record by its `id` payload field.

**Arguments**

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `id` | string | yes | 1–200 chars |
| `domain` | string | no | ≤ 200 chars; optional hint |

**Resolution strategy**

1. **Fast path** — if `domain` is supplied and contains a dot (an exact dotted
   domain, e.g. `security.cis_controls`), the server computes the deterministic
   UUID5 point id from `process_knowledge://{domain}/{id}` and does a direct
   point fetch.
2. **Authoritative path** — otherwise (or on a fast-path miss) it scrolls the
   collection filtering on the `id` payload field. If a non-dotted `domain` root
   is supplied, results are post-filtered to that root.

**Example**

```bash
python server.py lookup '{"id":"SEC-CIS-001","domain":"security.cis_controls"}'
```

**Response**

```json
{ "found": true, "id": "SEC-CIS-001", "record": { "...payload..." }, "point_id": "..." }
```

Not found:

```json
{ "found": false, "id": "SEC-CIS-001" }
```

---

## `process_validate` — schema + duplicate check

Validates a **candidate** record before it is written to the corpus. This does
two things:

1. **Schema validation** — determines the `knowledge_type` (explicit
   `knowledge_type`/`type`, or inferred from shape) and checks that all
   `required_fields` for that type (per `_schema.yaml`) are present.
2. **Duplicate / contradiction detection** — embeds the candidate's text
   (`name` + `condition` + `action` + `scenario` + `standard_behavior`) and
   searches the **whole** collection (no domain filter, so duplicates hiding in
   any sub-domain surface). Any hit at or above `DUPLICATE_THRESHOLD`
   (default 0.85 cosine) is reported, with an `in_target_scope` flag computed by
   root-prefix matching against `target_domain`.

**Arguments**

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `candidate` | object | yes | the record to validate |
| `target_domain` | string | yes | 1–200 chars; domain context (e.g. `security`) |

**Type inference** (used when `knowledge_type` is absent):

| Inferred type | Trigger |
|---------------|---------|
| `rule` | `condition` and `action` present |
| `decision_tree` | `root` is an object |
| `sop` | `steps` is a list |
| `edge_case` | `scenario`, `standard_behavior`, and `exception` all present |

**Example**

```bash
python server.py validate '{
  "candidate": {
    "id": "DEV-NEW-001", "knowledge_type": "rule", "name": "x",
    "condition": "y", "action": "z", "domain": "development.testing",
    "source": "manual", "effective_date": "2026-05-01", "status": "active"
  },
  "target_domain": "development"
}'
```

**Response shape**

```json
{
  "valid": true,
  "errors": [],
  "suggestions": [
    {
      "type": "potential_duplicate",
      "score": 0.91,
      "existing_id": "...",
      "existing_name": "...",
      "existing_domain": "development.testing",
      "in_target_scope": true,
      "advice": "Consider whether this candidate is a true duplicate or a refinement"
    },
    {
      "type": "domain_mismatch",
      "candidate_domain": "security.x",
      "target_domain": "development",
      "advice": "Candidate domain 'security.x' doesn't match target_domain root 'development'"
    }
  ],
  "knowledge_type": "rule"
}
```

- `valid` is `true` only when there are **zero** schema `errors`. Suggestions
  (duplicates / domain mismatches) are advisory and do **not** flip `valid` to
  false.
- If the schema file (`SCHEMA_PATH`) is missing or unparseable, `load_schema()`
  returns `{}`; unknown types then surface as an error. Keep the schema mounted.

---

## Error responses (all tools)

| Response | Meaning |
|----------|---------|
| `{"error":"invalid_arguments","detail":[...]}` | Pydantic rejected the input; `detail` lists field errors. |
| `{"error":"backend_unavailable","message":"..."}` | Qdrant call failed (network, auth, missing collection). Message is truncated to 200 chars — no stack trace is leaked. |
| `{"error":"unknown_tool","name":"..."}` | The dispatched tool name is not one of the three. |

---

Apache-2.0 © 2026 bulletproofsoftware-ai. See [LICENSE](../LICENSE) and [NOTICE](../NOTICE).
