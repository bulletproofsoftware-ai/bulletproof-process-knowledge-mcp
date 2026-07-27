#!/usr/bin/env python3
"""Create and populate the `process_knowledge` Qdrant collection.

The MCP server in server.py is read-only — it never writes to Qdrant. This
script is the companion writer: it creates the collection with the vector
configuration the server expects and upserts knowledge records from YAML files.

It implements exactly the contract documented in docs/ADMINISTRATOR.md:

  * collection name  : process_knowledge
  * vector size      : 384 (sentence-transformers/all-MiniLM-L6-v2)
  * distance         : Cosine (the server treats scores as cosine similarity)
  * point id         : UUID5(NAMESPACE, "process_knowledge://{domain}/{id}")
  * payload          : id, domain, knowledge_type, name, status, tags,
                       source_file, record

Input format — one or more YAML files, each holding a `records:` list. Files
beginning with an underscore (such as _schema.yaml) are skipped.

Usage:
    python ingest.py --knowledge-root examples/knowledge
    python ingest.py --knowledge-root examples/knowledge --dry-run
    python ingest.py --knowledge-root examples/knowledge --recreate

Environment:
    QDRANT_URL       default http://localhost:6333
    QDRANT_API_KEY   optional
    EMBEDDING_MODEL  default sentence-transformers/all-MiniLM-L6-v2
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import requests
import yaml

# Must match server.py exactly, or the server cannot resolve the points we
# write by their deterministic ids.
COLLECTION = "process_knowledge"
NAMESPACE = uuid.UUID("c0c0c0c0-c0c0-c0c0-c0c0-c0c0c0c0c0c0")
VECTOR_SIZE = 384
DISTANCE = "Cosine"

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333").rstrip("/")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY") or None
EMBEDDING_MODEL = os.environ.get(
    "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)

_embedder = None


def headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if QDRANT_API_KEY:
        h["api-key"] = QDRANT_API_KEY
    return h


def embed(text: str) -> list[float]:
    """Embed text with the same model and normalization the server uses."""
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding

        _embedder = TextEmbedding(model_name=EMBEDDING_MODEL)
    # fastembed mean-pools and L2-normalizes internally, matching the server's
    # previous SentenceTransformer(..., normalize_embeddings=True) output.
    return next(iter(_embedder.embed([text]))).tolist()


def point_id(domain: str, record_id: str) -> str:
    """Deterministic point id — identical derivation to server.q_lookup()."""
    return str(uuid.uuid5(NAMESPACE, f"process_knowledge://{domain}/{record_id}"))


def embedding_text(record: dict[str, Any]) -> str:
    """Build the text that represents a record in vector space.

    Mirrors the field set process_validate concatenates when it searches for
    duplicates, so a candidate scores against records the same way regardless
    of which knowledge type it is.
    """
    parts = [
        record.get("name", ""),
        record.get("condition", ""),
        record.get("action", ""),
        record.get("scenario", ""),
        record.get("standard_behavior", ""),
    ]
    if isinstance(record.get("steps"), list):
        parts.extend(str(s) for s in record["steps"])
    return " ".join(p for p in parts if p).strip()


def load_records(root: Path) -> list[tuple[dict[str, Any], str]]:
    """Load (record, source_file) pairs from every YAML file under root."""
    out: list[tuple[dict[str, Any], str]] = []
    files = sorted(
        p
        for p in list(root.glob("*.yaml")) + list(root.glob("*.yml"))
        if not p.name.startswith("_")
    )
    if not files:
        raise SystemExit(f"no knowledge YAML files found in {root}")

    for path in files:
        data = yaml.safe_load(path.read_text()) or {}
        records = data.get("records")
        if not isinstance(records, list):
            print(f"  skip {path.name}: no 'records' list", file=sys.stderr)
            continue
        for rec in records:
            if not isinstance(rec, dict):
                print(f"  skip a non-mapping entry in {path.name}", file=sys.stderr)
                continue
            out.append((rec, path.name))
    return out


def validate(record: dict[str, Any], source_file: str) -> list[str]:
    """Check the fields the server's payload contract depends on."""
    problems = []
    for field in ("id", "domain", "knowledge_type", "name"):
        if not record.get(field):
            problems.append(f"{source_file}: record missing '{field}': {record!r:.120}")
    if not embedding_text(record):
        problems.append(
            f"{source_file}: record {record.get('id')!r} has no embeddable text "
            "(needs at least one of name/condition/action/scenario/"
            "standard_behavior/steps)"
        )
    return problems


def collection_exists() -> bool:
    r = requests.get(
        f"{QDRANT_URL}/collections/{COLLECTION}", headers=headers(), timeout=30
    )
    return r.status_code == 200


def create_collection(recreate: bool) -> None:
    if collection_exists():
        if not recreate:
            print(f"collection '{COLLECTION}' already exists — reusing it")
            return
        print(f"deleting existing collection '{COLLECTION}'")
        requests.delete(
            f"{QDRANT_URL}/collections/{COLLECTION}", headers=headers(), timeout=60
        ).raise_for_status()

    print(f"creating collection '{COLLECTION}' ({VECTOR_SIZE}-dim, {DISTANCE})")
    r = requests.put(
        f"{QDRANT_URL}/collections/{COLLECTION}",
        headers=headers(),
        json={"vectors": {"size": VECTOR_SIZE, "distance": DISTANCE}},
        timeout=60,
    )
    r.raise_for_status()

    # process_lookup filters on the payload `id` field and process_query filters
    # on `domain`; both need a payload index to match reliably at scale.
    for field in ("id", "domain"):
        requests.put(
            f"{QDRANT_URL}/collections/{COLLECTION}/index",
            headers=headers(),
            json={"field_name": field, "field_schema": "keyword"},
            timeout=60,
        )


def build_points(
    pairs: list[tuple[dict[str, Any], str]],
) -> list[dict[str, Any]]:
    points = []
    for record, source_file in pairs:
        domain = record["domain"]
        record_id = record["id"]
        points.append(
            {
                "id": point_id(domain, record_id),
                "vector": embed(embedding_text(record)),
                "payload": {
                    "id": record_id,
                    "domain": domain,
                    "knowledge_type": record["knowledge_type"],
                    "name": record["name"],
                    "status": record.get("status", "active"),
                    "tags": record.get("tags", []),
                    "source_file": source_file,
                    "record": record,
                },
            }
        )
    return points


def upsert(points: list[dict[str, Any]], batch_size: int = 64) -> None:
    for i in range(0, len(points), batch_size):
        batch = points[i : i + batch_size]
        r = requests.put(
            f"{QDRANT_URL}/collections/{COLLECTION}/points?wait=true",
            headers=headers(),
            json={"points": batch},
            timeout=120,
        )
        r.raise_for_status()
        print(f"  upserted {i + len(batch)}/{len(points)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create and populate the process_knowledge Qdrant collection."
    )
    parser.add_argument(
        "--knowledge-root",
        default=os.environ.get("KNOWLEDGE_ROOT", "examples/knowledge"),
        help="directory of knowledge YAML files (default: examples/knowledge)",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="delete and recreate the collection before ingesting",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="parse and validate records, print the plan, contact no server",
    )
    args = parser.parse_args(argv)

    root = Path(args.knowledge_root)
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2

    pairs = load_records(root)
    problems = [p for rec, src in pairs for p in validate(rec, src)]
    if problems:
        print("validation failed:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1

    print(f"loaded {len(pairs)} records from {root}")

    if args.dry_run:
        print("\ndry run — nothing will be written. Planned points:\n")
        for record, source_file in pairs:
            print(
                f"  {point_id(record['domain'], record['id'])}  "
                f"{record['id']:<16} {record['knowledge_type']:<14} "
                f"{record['domain']}  ({source_file})"
            )
        return 0

    create_collection(recreate=args.recreate)
    print(f"embedding {len(pairs)} records with {EMBEDDING_MODEL}")
    points = build_points(pairs)
    upsert(points)
    print(f"\ndone — {len(points)} records in '{COLLECTION}' at {QDRANT_URL}")
    print("verify with: python server.py query '{\"query\":\"ssh\",\"limit\":3}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
