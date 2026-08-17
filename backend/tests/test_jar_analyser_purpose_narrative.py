"""Stage 6 — Perceived Purpose narrative synthesis (purpose_narrative.py)."""
from types import SimpleNamespace

from app.services.jar_analyser.purpose_narrative import compute_purpose_narrative


def _sr(**overrides):
    base = dict(
        service_name="ticketing",
        group_name="core",
        endpoints=[],
        dependencies=[],
        dto_schemas=[],
        migration_scripts=[],
        event_files=[],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_empty_sub_report_yields_only_platform_categorisation():
    stmts = compute_purpose_narrative(_sr())
    categories = [s["category"] for s in stmts]
    assert categories == ["platform_categorisation"]
    assert stmts[0]["is_inference"] is False


def test_authored_text_is_marked_as_fact_not_inference():
    sr = _sr(endpoints=[{"doc_summary": "Exports blob binary data", "doc_description": None,
                          "controller_simple": "X", "security": None}])
    stmts = compute_purpose_narrative(sr)
    authored = next(s for s in stmts if s["category"] == "authored_intent")
    assert authored["is_inference"] is False
    assert "Exports blob binary data" in authored["evidence"]


def test_authored_text_prefers_summary_over_verbose_description():
    sr = _sr(endpoints=[{"doc_summary": "Exports blob binary data",
                          "doc_description": "Exports blob binary data.\n\n##### Roles allowed\n* EXPORT_IMPORT_USER",
                          "controller_simple": "X", "security": None}])
    stmts = compute_purpose_narrative(sr)
    authored = next(s for s in stmts if s["category"] == "authored_intent")
    assert authored["evidence"] == ["Exports blob binary data"]


def test_authored_text_strips_markdown_headings_and_examples():
    long_desc = (
        "Propagates CPS customer to SNOW. Searches the **u_cps_customers** mapping table.\n\n"
        "##### Example request body\n```\n{ \"domain\": {} }\n```"
    )
    sr = _sr(endpoints=[{"doc_summary": None, "doc_description": long_desc,
                          "controller_simple": "X", "security": None}])
    stmts = compute_purpose_narrative(sr)
    authored = next(s for s in stmts if s["category"] == "authored_intent")
    snippet = authored["evidence"][0]
    assert "Example request body" not in snippet
    assert "```" not in snippet
    assert "u_cps_customers" in snippet
    assert "**" not in snippet


def test_domain_vocabulary_extracted_from_dto_class_names():
    sr = _sr(dto_schemas=[{"simple_name": "TicketDto"}, {"simple_name": "TicketCommentDto"}])
    stmts = compute_purpose_narrative(sr)
    vocab = next((s for s in stmts if s["category"] == "domain_vocabulary"), None)
    assert vocab is not None
    assert vocab["is_inference"] is True
    assert "Based on the following static evidence" in vocab["text"]
    terms = [t["term"] for t in vocab["evidence"]]
    assert "ticket" in terms
    assert "dto" not in terms  # structural stopword excluded


def test_event_topology_publisher_role():
    sr = _sr(event_files=[{"published": [{"entity": "ticket"}] * 4, "consumed": []}])
    stmts = compute_purpose_narrative(sr)
    topo = next(s for s in stmts if s["category"] == "event_topology")
    assert "publisher" in topo["text"]


def test_event_topology_consumer_role():
    sr = _sr(event_files=[{"published": [], "consumed": [{"entity": "order"}] * 4}])
    stmts = compute_purpose_narrative(sr)
    topo = next(s for s in stmts if s["category"] == "event_topology")
    assert "downstream adapter" in topo["text"]


def test_db_ownership_from_migration_scripts():
    sr = _sr(migration_scripts=[{"tables_affected": ["ticket", "ticket_comment"]}])
    stmts = compute_purpose_narrative(sr)
    ownership = next(s for s in stmts if s["category"] == "db_ownership")
    assert "ticket" in ownership["text"]
    assert "system of record" in ownership["text"]


def test_cloud_sdk_dependency_fingerprint():
    sr = _sr(dependencies=[{"category": "cloud_sdk", "group_id": "software.amazon.awssdk",
                             "artifact_id": "aws-java-sdk-s3", "filename": "aws-java-sdk-s3-1.0.jar"}])
    stmts = compute_purpose_narrative(sr)
    dep = next(s for s in stmts if s["category"] == "dependency_fingerprint")
    assert "AWS" in dep["text"]


def test_auth_posture_admin_gated():
    sr = _sr(endpoints=[
        {"controller_simple": "X", "doc_summary": None, "doc_description": None,
         "security": {"parsed_auth": {"public": False, "roles": ["ADMIN"], "authorities": [], "authenticated_only": False}}},
    ])
    stmts = compute_purpose_narrative(sr)
    posture = next(s for s in stmts if s["category"] == "auth_posture")
    assert "administrative" in posture["text"]


def test_non_cloud_dependency_is_not_fingerprinted():
    sr = _sr(dependencies=[{"category": "database", "group_id": "org.postgresql", "artifact_id": "postgresql", "filename": "postgresql.jar"}])
    stmts = compute_purpose_narrative(sr)
    assert not any(s["category"] == "dependency_fingerprint" for s in stmts)
