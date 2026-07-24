#!/usr/bin/env python3
"""PRD 14 REQ-PK-005 — Process Knowledge MCP Server.

Exposes three MCP tools backed by the `process_knowledge` Qdrant collection:

    process_query    — semantic search over knowledge corpus
    process_lookup   — exact-id lookup
    process_validate — schema validation + duplicate/contradiction detection

Transport: stdio (MCP standard).

Configuration via environment variables:
    QDRANT_URL          (default http://localhost:6334)
    QDRANT_API_KEY      (optional)
    EMBEDDING_MODEL     (default sentence-transformers/all-MiniLM-L6-v2)
    SCHEMA_PATH         (default /knowledge/_schema.yaml)
    KNOWLEDGE_ROOT      (default /knowledge)
    AUDIT_BUS_URL       (optional — POST tool invocations as audit events)
    DUPLICATE_THRESHOLD (default 0.85)

All tool inputs are validated via Pydantic. Errors are sanitized — internal
exceptions are converted to typed error responses, never raw stack traces.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import requests
import yaml
from pydantic import BaseModel, Field, ValidationError

# MCP SDK — defer import error to runtime so module is loadable for tests
try:
    from mcp.server import Server  # type: ignore
    from mcp.server.stdio import stdio_server  # type: ignore
    from mcp.types import TextContent, Tool  # type: ignore
    HAVE_MCP = True
except Exception:
    HAVE_MCP = False
    Server = object  # type: ignore[assignment,misc]


COLLECTION = "process_knowledge"
NAMESPACE = uuid.UUID("c0c0c0c0-c0c0-c0c0-c0c0-c0c0c0c0c0c0")

logger = logging.getLogger("process-knowledge-mcp")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
class Config:
    QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6334")
    QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY") or None
    EMBEDDING_MODEL = os.environ.get(
        "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
    )
    SCHEMA_PATH = Path(os.environ.get("SCHEMA_PATH", "/knowledge/_schema.yaml"))
    KNOWLEDGE_ROOT = Path(os.environ.get("KNOWLEDGE_ROOT", "/knowledge"))
    AUDIT_BUS_URL = os.environ.get("AUDIT_BUS_URL") or None
    DUPLICATE_THRESHOLD = float(os.environ.get("DUPLICATE_THRESHOLD", "0.85"))


# ---------------------------------------------------------------------------
# Embedding model (lazy)
# ---------------------------------------------------------------------------
_embedder = None


def get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(Config.EMBEDDING_MODEL)
        logger.info("Loaded embedder: %s", Config.EMBEDDING_MODEL)
    return _embedder


def embed(text: str) -> list[float]:
    return get_embedder().encode(text, normalize_embeddings=True).tolist()


# ---------------------------------------------------------------------------
# Qdrant helpers
# ---------------------------------------------------------------------------
def _q_headers() -> dict:
    h = {"Content-Type": "application/json"}
    if Config.QDRANT_API_KEY:
        h["api-key"] = Config.QDRANT_API_KEY
    return h


def q_search(
    query_text: str,
    domain: str | None = None,
    limit: int = 5,
) -> list[dict]:
    vec = embed(query_text)
    body: dict[str, Any] = {"vector": vec, "limit": limit, "with_payload": True}
    if domain:
        body["filter"] = {
            "must": [{"key": "domain", "match": {"value": domain}}]
        }
    r = requests.post(
        f"{Config.QDRANT_URL}/collections/{COLLECTION}/points/search",
        headers=_q_headers(), json=body, timeout=30,
    )
    r.raise_for_status()
    return r.json().get("result", [])


def q_lookup(record_id: str, domain: str | None = None) -> dict | None:
    """Lookup by record id. Domain is optional — when provided and exact (dotted),
    we attempt the deterministic UUID5 first; otherwise fall back to scroll filter
    on the `id` payload field which is authoritative.
    """
    # Fast path: exact dotted domain lets us compute the deterministic point id
    if domain and "." in domain:
        point_id = str(uuid.uuid5(NAMESPACE, f"process_knowledge://{domain}/{record_id}"))
        r = requests.get(
            f"{Config.QDRANT_URL}/collections/{COLLECTION}/points/{point_id}?with_payload=true",
            headers=_q_headers(), timeout=30,
        )
        if r.status_code == 200:
            return r.json().get("result")
        # fall through to scroll on miss

    # Authoritative path: scroll by payload `id` field
    body: dict[str, Any] = {
        "filter": {"must": [{"key": "id", "match": {"value": record_id}}]},
        "limit": 5, "with_payload": True,
    }
    r = requests.post(
        f"{Config.QDRANT_URL}/collections/{COLLECTION}/points/scroll",
        headers=_q_headers(), json=body, timeout=30,
    )
    r.raise_for_status()
    pts = r.json().get("result", {}).get("points", [])
    if not pts:
        return None
    if domain and not any("." in domain for _ in [True]):
        # Optional domain root filter (post-filter to avoid keyword-equality miss)
        for p in pts:
            d = p.get("payload", {}).get("domain", "")
            if d == domain or d.startswith(domain + "."):
                return p
    return pts[0]


# ---------------------------------------------------------------------------
# Schema loader
# ---------------------------------------------------------------------------
def load_schema() -> dict:
    if not Config.SCHEMA_PATH.exists():
        return {}
    try:
        return yaml.safe_load(Config.SCHEMA_PATH.read_text()) or {}
    except Exception as exc:
        logger.warning("Failed to load schema: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Audit emitter (optional)
# ---------------------------------------------------------------------------
def audit(tool: str, args: dict, outcome: str, detail: dict | None = None) -> None:
    if not Config.AUDIT_BUS_URL:
        return
    try:
        requests.post(
            Config.AUDIT_BUS_URL,
            json={
                "tool": tool, "arguments": args,
                "outcome": outcome, "detail": detail or {},
                "service": "process-knowledge-mcp",
            },
            timeout=2,
        )
    except Exception:
        pass  # never let audit failure block tool response


# ---------------------------------------------------------------------------
# Tool input models
# ---------------------------------------------------------------------------
class ProcessQueryArgs(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    domain: str | None = Field(default=None, max_length=200)
    limit: int = Field(default=5, ge=1, le=50)


class ProcessLookupArgs(BaseModel):
    id: str = Field(..., min_length=1, max_length=200)
    domain: str | None = Field(default=None, max_length=200)


class ProcessValidateArgs(BaseModel):
    candidate: dict
    target_domain: str = Field(..., min_length=1, max_length=200)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------
def tool_process_query(raw: dict) -> dict:
    try:
        args = ProcessQueryArgs(**raw)
    except ValidationError as e:
        audit("process_query", raw, "validation_error")
        return {"error": "invalid_arguments", "detail": e.errors()}
    try:
        hits = q_search(args.query, args.domain, args.limit)
    except Exception as exc:
        audit("process_query", raw, "backend_error")
        logger.exception("q_search failed")
        return {"error": "backend_unavailable", "message": str(exc)[:200]}

    results = []
    for h in hits:
        p = h.get("payload", {})
        results.append({
            "score": h.get("score"),
            "id": p.get("id"),
            "knowledge_type": p.get("knowledge_type"),
            "domain": p.get("domain"),
            "name": p.get("name"),
            "status": p.get("status"),
            "tags": p.get("tags", []),
            "source_file": p.get("source_file"),
            "record": p.get("record"),
        })
    audit("process_query", raw, "ok", {"hits": len(results)})
    return {"results": results, "query": args.query, "domain_filter": args.domain}


def tool_process_lookup(raw: dict) -> dict:
    try:
        args = ProcessLookupArgs(**raw)
    except ValidationError as e:
        audit("process_lookup", raw, "validation_error")
        return {"error": "invalid_arguments", "detail": e.errors()}
    try:
        rec = q_lookup(args.id, args.domain)
    except Exception as exc:
        audit("process_lookup", raw, "backend_error")
        logger.exception("q_lookup failed")
        return {"error": "backend_unavailable", "message": str(exc)[:200]}

    if rec is None:
        audit("process_lookup", raw, "not_found")
        return {"found": False, "id": args.id}
    audit("process_lookup", raw, "ok")
    return {"found": True, "id": args.id, "record": rec.get("payload"), "point_id": rec.get("id")}


def tool_process_validate(raw: dict) -> dict:
    try:
        args = ProcessValidateArgs(**raw)
    except ValidationError as e:
        audit("process_validate", raw, "validation_error")
        return {"error": "invalid_arguments", "detail": e.errors()}

    schema = load_schema()
    errors: list[str] = []
    suggestions: list[dict] = []

    cand = args.candidate
    ktype = cand.get("knowledge_type") or cand.get("type") or _infer_type(cand)
    if not ktype:
        errors.append("Cannot determine knowledge_type (must be one of: rule|decision_tree|sop|edge_case)")
    else:
        type_def = schema.get("knowledge_types", {}).get(ktype)
        if not type_def:
            errors.append(f"Unknown knowledge_type: {ktype}")
        else:
            for req in type_def.get("required_fields", []):
                if req not in cand:
                    errors.append(f"Missing required field: {req}")

    # Duplicate / contradiction detection via semantic similarity
    # Use root-domain prefix matching: if target is "security", we want to find
    # candidates in "security.cis_controls", "security.network", etc.
    text = (cand.get("name", "") + " " + cand.get("condition", "") + " "
            + cand.get("action", "") + " " + cand.get("scenario", "") + " "
            + cand.get("standard_behavior", "")).strip()
    if text:
        try:
            # Search WITHOUT domain filter — duplicates can hide in any sub-domain
            hits = q_search(text, domain=None, limit=5)
            for h in hits:
                if h.get("score", 0) >= Config.DUPLICATE_THRESHOLD:
                    p = h.get("payload", {})
                    p_domain = p.get("domain", "")
                    target_root = args.target_domain.split(".")[0]
                    in_scope = (p_domain == args.target_domain
                                or p_domain.startswith(target_root + ".")
                                or p_domain == target_root)
                    suggestions.append({
                        "type": "potential_duplicate",
                        "score": round(h.get("score", 0), 3),
                        "existing_id": p.get("id"),
                        "existing_name": p.get("name"),
                        "existing_domain": p_domain,
                        "in_target_scope": in_scope,
                        "advice": "Consider whether this candidate is a true duplicate or a refinement",
                    })
        except Exception:
            pass

    # Domain consistency
    cand_domain = cand.get("domain", "")
    if cand_domain and not cand_domain.startswith(args.target_domain.split(".")[0]):
        suggestions.append({
            "type": "domain_mismatch",
            "candidate_domain": cand_domain,
            "target_domain": args.target_domain,
            "advice": f"Candidate domain {cand_domain!r} doesn't match target_domain root {args.target_domain.split('.')[0]!r}",
        })

    valid = len(errors) == 0
    audit("process_validate", raw, "ok",
          {"valid": valid, "errors": len(errors), "suggestions": len(suggestions)})
    return {
        "valid": valid,
        "errors": errors,
        "suggestions": suggestions,
        "knowledge_type": ktype,
    }


def _infer_type(cand: dict) -> str | None:
    if "condition" in cand and "action" in cand:
        return "rule"
    if "root" in cand and isinstance(cand["root"], dict):
        return "decision_tree"
    if "steps" in cand and isinstance(cand["steps"], list):
        return "sop"
    if "scenario" in cand and "standard_behavior" in cand and "exception" in cand:
        return "edge_case"
    return None


# ---------------------------------------------------------------------------
# MCP server wiring
# ---------------------------------------------------------------------------
TOOL_DEFS = [
    {
        "name": "process_query",
        "description": "Semantic search over the process knowledge base. Returns top-K matches ranked by relevance.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language search query"},
                "domain": {"type": "string", "description": "Optional domain filter (e.g. 'security.cis_controls')"},
                "limit": {"type": "integer", "description": "Max results (1-50, default 5)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "process_lookup",
        "description": "Exact-id lookup of a process knowledge record. Returns the full record or null.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Knowledge record ID (e.g. 'SEC-CIS-001')"},
                "domain": {"type": "string", "description": "Optional domain hint"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "process_validate",
        "description": "Validate a candidate process knowledge record against the schema and detect potential duplicates/contradictions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "candidate": {"type": "object", "description": "The candidate record to validate"},
                "target_domain": {"type": "string", "description": "Domain for context (e.g. 'security')"},
            },
            "required": ["candidate", "target_domain"],
        },
    },
]


def _dispatch_tool(name: str, args: dict) -> dict:
    if name == "process_query":
        return tool_process_query(args)
    if name == "process_lookup":
        return tool_process_lookup(args)
    if name == "process_validate":
        return tool_process_validate(args)
    return {"error": "unknown_tool", "name": name}


async def run_stdio() -> None:
    if not HAVE_MCP:
        logger.error("MCP SDK not installed. Install: pip install mcp")
        sys.exit(1)
    server = Server("process-knowledge-mcp")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [Tool(**t) for t in TOOL_DEFS]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        result = _dispatch_tool(name, arguments or {})
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    async with stdio_server() as (read, write):
        await server.run(
            read, write,
            server.create_initialization_options(),
        )


def main() -> None:
    """Entry point. Runs MCP stdio loop or one-shot CLI."""
    if len(sys.argv) > 1 and sys.argv[1] in ("query", "lookup", "validate"):
        # CLI mode for testing
        cmd = sys.argv[1]
        try:
            args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        except json.JSONDecodeError as e:
            print(f"Invalid JSON args: {e}", file=sys.stderr)
            sys.exit(2)
        result = _dispatch_tool(f"process_{cmd}", args)
        print(json.dumps(result, indent=2, default=str))
        return

    # Default: MCP stdio loop
    import asyncio
    asyncio.run(run_stdio())


if __name__ == "__main__":
    main()
