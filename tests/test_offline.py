"""Offline unit tests — no Qdrant, no network, no embedding model.

These cover the parts of the server that must behave correctly when the vector
backend is unreachable, plus the ingest contract that has to stay byte-identical
to what the server expects.

Run with:  python -m pytest
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "examples" / "knowledge"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def server():
    return _load("_pk_server", "server.py")


@pytest.fixture(scope="module")
def ingest():
    return _load("_pk_ingest", "ingest.py")


# ---------------------------------------------------------------------------
# Ingest / server contract
# ---------------------------------------------------------------------------


class TestPointIdContract:
    """ingest.py must derive point ids exactly as server.q_lookup() does.

    If these drift, the server's UUID5 fast path silently misses every record
    the ingest script wrote.
    """

    def test_namespace_matches(self, server, ingest):
        assert ingest.NAMESPACE == server.NAMESPACE

    def test_collection_name_matches(self, server, ingest):
        assert ingest.COLLECTION == server.COLLECTION

    @pytest.mark.parametrize(
        ("domain", "record_id"),
        [
            ("security.cis_controls", "SEC-CIS-001"),
            ("development.release", "DEV-REL-001"),
            ("a.b.c", "ID-WITH-DASHES-123"),
        ],
    )
    def test_point_id_matches_server_derivation(self, server, ingest, domain, record_id):
        expected = str(
            uuid.uuid5(server.NAMESPACE, f"process_knowledge://{domain}/{record_id}")
        )
        assert ingest.point_id(domain, record_id) == expected

    def test_point_id_is_deterministic(self, ingest):
        first = ingest.point_id("security.cis_controls", "SEC-CIS-001")
        second = ingest.point_id("security.cis_controls", "SEC-CIS-001")
        assert first == second

    def test_distinct_records_get_distinct_ids(self, ingest):
        a = ingest.point_id("security.cis_controls", "SEC-CIS-001")
        b = ingest.point_id("security.cis_controls", "SEC-CIS-002")
        c = ingest.point_id("security.other", "SEC-CIS-001")
        assert len({a, b, c}) == 3

    def test_default_qdrant_url_agrees_with_server(self, monkeypatch):
        # Both must FALL BACK to Qdrant's standard HTTP REST port when
        # QDRANT_URL is unset. Reload with the variable removed so a value
        # exported in the developer's shell does not mask the default.
        monkeypatch.delenv("QDRANT_URL", raising=False)
        server = _load("_pk_server_nodefault", "server.py")
        ingest = _load("_pk_ingest_nodefault", "ingest.py")
        assert ingest.QDRANT_URL == "http://localhost:6333"
        assert server.Config.QDRANT_URL == "http://localhost:6333"

    def test_vector_size_matches_embedding_model(self, ingest):
        # all-MiniLM-L6-v2 produces 384-dim vectors.
        assert ingest.VECTOR_SIZE == 384
        assert "MiniLM-L6" in ingest.EMBEDDING_MODEL


# ---------------------------------------------------------------------------
# Shipped examples
# ---------------------------------------------------------------------------


class TestExamples:
    """The examples must actually load and satisfy their own schema."""

    def test_examples_directory_exists(self):
        assert EXAMPLES.is_dir(), "examples/knowledge/ is missing"

    def test_schema_file_exists(self):
        assert (EXAMPLES / "_schema.yaml").is_file()

    def test_records_load(self, ingest):
        pairs = ingest.load_records(EXAMPLES)
        assert len(pairs) >= 3, "expected several example records"

    def test_records_pass_ingest_validation(self, ingest):
        pairs = ingest.load_records(EXAMPLES)
        problems = [p for rec, src in pairs for p in ingest.validate(rec, src)]
        assert problems == [], f"example records failed validation: {problems}"

    def test_every_record_has_embeddable_text(self, ingest):
        for record, _ in ingest.load_records(EXAMPLES):
            assert ingest.embedding_text(record), f"{record['id']} embeds to nothing"

    def test_schema_underscore_file_is_not_ingested(self, ingest):
        # _schema.yaml must be skipped, not treated as a record file.
        ids = [rec["id"] for rec, _ in ingest.load_records(EXAMPLES)]
        assert "version" not in ids

    def test_examples_cover_each_knowledge_type(self, ingest):
        types = {rec["knowledge_type"] for rec, _ in ingest.load_records(EXAMPLES)}
        assert {"rule", "sop", "edge_case", "decision_tree"} <= types

    def test_example_types_all_declared_in_schema(self, server, ingest, monkeypatch):
        monkeypatch.setattr(
            server.Config, "SCHEMA_PATH", EXAMPLES / "_schema.yaml", raising=False
        )
        declared = set(server.load_schema().get("knowledge_types", {}))
        used = {rec["knowledge_type"] for rec, _ in ingest.load_records(EXAMPLES)}
        assert used <= declared

    def test_schema_required_fields_satisfied_by_examples(self, server, ingest, monkeypatch):
        monkeypatch.setattr(
            server.Config, "SCHEMA_PATH", EXAMPLES / "_schema.yaml", raising=False
        )
        schema = server.load_schema()
        for record, source in ingest.load_records(EXAMPLES):
            required = schema["knowledge_types"][record["knowledge_type"]][
                "required_fields"
            ]
            missing = [f for f in required if f not in record]
            assert not missing, f"{record['id']} in {source} missing {missing}"


# ---------------------------------------------------------------------------
# Type inference
# ---------------------------------------------------------------------------


class TestInferType:
    @pytest.mark.parametrize(
        ("candidate", "expected"),
        [
            ({"condition": "c", "action": "a"}, "rule"),
            ({"root": {"question": "q"}}, "decision_tree"),
            ({"steps": ["one", "two"]}, "sop"),
            (
                {"scenario": "s", "standard_behavior": "b", "exception": "e"},
                "edge_case",
            ),
            ({"name": "nothing identifying"}, None),
        ],
    )
    def test_infers_expected_type(self, server, candidate, expected):
        assert server._infer_type(candidate) == expected

    def test_shipped_examples_infer_their_declared_type(self, server, ingest):
        for record, _ in ingest.load_records(EXAMPLES):
            inferred = server._infer_type(record)
            assert inferred == record["knowledge_type"], (
                f"{record['id']} declares {record['knowledge_type']} "
                f"but infers as {inferred}"
            )


# ---------------------------------------------------------------------------
# Validation with the backend unavailable
# ---------------------------------------------------------------------------


class TestValidateOffline:
    """process_validate must still do schema work when Qdrant is unreachable.

    Duplicate detection needs the vector backend, but a missing backend must
    degrade to "no suggestions" rather than failing the whole call.
    """

    @pytest.fixture(autouse=True)
    def _point_at_dead_backend(self, server, monkeypatch):
        monkeypatch.setattr(
            server.Config, "SCHEMA_PATH", EXAMPLES / "_schema.yaml", raising=False
        )
        # Reserved, closed port — connections fail immediately.
        monkeypatch.setattr(
            server.Config, "QDRANT_URL", "http://127.0.0.1:1", raising=False
        )

    def _candidate(self, **overrides):
        base = {
            "id": "SEC-TEST-001",
            "knowledge_type": "rule",
            "name": "Test rule",
            "domain": "security.cis_controls",
            "condition": "a condition",
            "action": "an action",
            "source": "unit-test",
            "effective_date": "2026-01-01",
            "status": "active",
        }
        base.update(overrides)
        return base

    def test_complete_record_is_valid_without_backend(self, server):
        out = server.tool_process_validate(
            {"candidate": self._candidate(), "target_domain": "security"}
        )
        assert out["valid"] is True
        assert out["errors"] == []

    def test_no_suggestions_when_backend_is_down(self, server):
        out = server.tool_process_validate(
            {"candidate": self._candidate(), "target_domain": "security"}
        )
        # Duplicate detection is skipped, not fatal.
        assert out["suggestions"] == []

    def test_missing_required_field_is_reported(self, server):
        candidate = self._candidate()
        del candidate["action"]
        out = server.tool_process_validate(
            {"candidate": candidate, "target_domain": "security"}
        )
        assert out["valid"] is False
        assert any("action" in e for e in out["errors"])

    def test_unknown_knowledge_type_is_reported(self, server):
        out = server.tool_process_validate(
            {
                "candidate": self._candidate(knowledge_type="not_a_real_type"),
                "target_domain": "security",
            }
        )
        assert out["valid"] is False
        assert any("Unknown knowledge_type" in e for e in out["errors"])

    def test_invalid_arguments_are_rejected(self, server):
        out = server.tool_process_validate({"candidate": "not-a-mapping"})
        assert out["error"] == "invalid_arguments"


# ---------------------------------------------------------------------------
# Schema loader
# ---------------------------------------------------------------------------


class TestLoadSchema:
    def test_missing_schema_returns_empty_dict(self, server, monkeypatch, tmp_path):
        monkeypatch.setattr(
            server.Config, "SCHEMA_PATH", tmp_path / "absent.yaml", raising=False
        )
        assert server.load_schema() == {}

    def test_malformed_schema_returns_empty_dict(self, server, monkeypatch, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("{[not valid yaml")
        monkeypatch.setattr(server.Config, "SCHEMA_PATH", bad, raising=False)
        assert server.load_schema() == {}

    def test_example_schema_declares_all_four_types(self, server, monkeypatch):
        monkeypatch.setattr(
            server.Config, "SCHEMA_PATH", EXAMPLES / "_schema.yaml", raising=False
        )
        types = server.load_schema().get("knowledge_types", {})
        assert set(types) == {"rule", "decision_tree", "sop", "edge_case"}


# ---------------------------------------------------------------------------
# Audit emitter
# ---------------------------------------------------------------------------


class TestAuditOffline:
    def test_audit_is_noop_when_unconfigured(self, server, monkeypatch):
        monkeypatch.setattr(server.Config, "AUDIT_BUS_URL", None, raising=False)
        server.audit("process_query", {"query": "x"}, "ok")  # must not raise

    def test_audit_swallows_unreachable_bus(self, server, monkeypatch):
        monkeypatch.setattr(
            server.Config, "AUDIT_BUS_URL", "http://127.0.0.1:1/bus", raising=False
        )
        server.audit("process_query", {"query": "x"}, "ok")  # must not raise


# ---------------------------------------------------------------------------
# q_lookup domain scoping (round-2 adversarial review)
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AssertionError(f"unexpected status {self.status_code}")


def _point(record_id: str, domain: str) -> dict:
    return {"id": f"pt-{record_id}-{domain}", "payload": {"id": record_id, "domain": domain}}


@pytest.fixture()
def scroll_only(server, monkeypatch):
    """Force q_lookup down its scroll path and control what the scroll returns.

    The UUID5 fast path is made to miss so every test exercises the post-filter,
    which is where the domain constraint was being dropped.
    """

    def install(points: list[dict]):
        monkeypatch.setattr(
            server.requests, "get", lambda *a, **k: _FakeResponse({}, status_code=404)
        )
        monkeypatch.setattr(
            server.requests,
            "post",
            lambda *a, **k: _FakeResponse({"result": {"points": points}}),
        )

    return install


class TestQLookupDomainScoping:
    """A caller-supplied domain is a constraint, not a hint.

    q_lookup() used to fall through to points[0] whenever the domain post-filter
    matched nothing, handing back a record from an unrelated domain under the
    record id the caller asked for.
    """

    def test_returns_none_when_no_point_is_in_the_requested_root_domain(
        self, server, scroll_only
    ):
        scroll_only([_point("REQ-001", "security"), _point("REQ-001", "finance")])
        assert server.q_lookup("REQ-001", domain="engineering") is None

    def test_returns_none_when_no_point_is_in_the_requested_dotted_domain(
        self, server, scroll_only
    ):
        # Dotted domains skipped the post-filter entirely after the UUID5 miss.
        scroll_only([_point("REQ-001", "security"), _point("REQ-001", "finance")])
        assert server.q_lookup("REQ-001", domain="engineering.backend") is None

    def test_returns_the_matching_domain_not_the_first_point(self, server, scroll_only):
        scroll_only([_point("REQ-001", "finance"), _point("REQ-001", "engineering")])
        result = server.q_lookup("REQ-001", domain="engineering")
        assert result is not None
        assert result["payload"]["domain"] == "engineering"

    def test_sub_domains_still_satisfy_a_root_domain_request(self, server, scroll_only):
        scroll_only([_point("REQ-001", "finance"), _point("REQ-001", "engineering.backend")])
        result = server.q_lookup("REQ-001", domain="engineering")
        assert result is not None
        assert result["payload"]["domain"] == "engineering.backend"

    def test_prefix_collision_does_not_count_as_a_match(self, server, scroll_only):
        # "engineeringops" must not satisfy a request scoped to "engineering".
        scroll_only([_point("REQ-001", "engineeringops")])
        assert server.q_lookup("REQ-001", domain="engineering") is None

    def test_no_domain_still_returns_the_first_point(self, server, scroll_only):
        scroll_only([_point("REQ-001", "finance"), _point("REQ-001", "engineering")])
        result = server.q_lookup("REQ-001")
        assert result is not None
        assert result["payload"]["domain"] == "finance"

    def test_empty_scroll_returns_none(self, server, scroll_only):
        scroll_only([])
        assert server.q_lookup("REQ-001", domain="engineering") is None
