"""error_diagnostician.diagnose() — report-scoped KB lookup + context
enrichment, now parsing error_text through stack_trace_parser.py first
(same parser Docs' Decode tab uses) so a "Caused by:" root cause's own text
drives the KB search instead of the whole raw paste, and so a trace's own
frames can correlate back to exactly which of this report's services it
came from (frame_class_index)."""
from app.services.jar_analyser.error_diagnostician import diagnose


def _kb_entry(id: str, category: str, pattern: str) -> dict:
    return {
        "id": id, "category": category, "severity": "high", "pattern": pattern,
        "title": id, "plain_english": "", "causes": [], "fix_steps": [], "see_also": [],
    }


def _sub_dict(sub_report_id: str, service_name: str, db_key: str = "spring.datasource.url") -> dict:
    return {
        "sub_report_id": sub_report_id, "service_name": service_name, "filename": f"{service_name}.jar",
        "declared_port": None,
        "endpoints": [],
        "config_files": [{"filename": "application.yml", "keys": [
            {"key": db_key, "value": "jdbc:postgresql://db:5432/x", "is_placeholder": False},
        ]}],
        "migration_scripts": [],
    }


def test_plain_text_with_no_real_trace_falls_back_to_whole_blob_search():
    kb_entries = [_kb_entry("db-1", "Database/Flyway", r"connection refused")]
    sub_dicts = [_sub_dict("sub-a", "svc-a")]

    results = diagnose("something something connection refused", sub_dicts, kb_entries)

    assert len(results) == 1
    assert results[0]["kb_entry"]["id"] == "db-1"
    assert results[0]["matched_exception"] is None
    # No frame correlation possible for non-trace text - falls back to the
    # whole (single) report's sub_dicts, exactly like the old behaviour.
    assert len(results[0]["context_findings"]) == 1


def test_caused_by_root_cause_drives_kb_search_not_the_outer_wrapper():
    kb_entries = [_kb_entry("sql-1", "Database/Flyway", r"java\.sql\.SQLException")]
    sub_dicts = [_sub_dict("sub-a", "svc-a")]

    text = (
        "java.lang.RuntimeException: wrapped failure\n"
        "\tat com.x.A.a(A.java:1)\n"
        "Caused by: java.sql.SQLException: connection refused\n"
        "\tat com.x.B.b(B.java:2)\n"
    )
    results = diagnose(text, sub_dicts, kb_entries)

    assert len(results) == 1
    assert results[0]["kb_entry"]["id"] == "sql-1"
    assert results[0]["matched_exception"]["exception_class"] == "java.sql.SQLException"
    assert results[0]["matched_exception"]["kind"] == "caused_by"


def test_frame_correlation_scopes_context_findings_to_the_matching_service():
    kb_entries = [_kb_entry("sql-1", "Database/Flyway", r"java\.sql\.SQLException")]
    sub_dicts = [
        _sub_dict("sub-a", "svc-a", db_key="spring.datasource.url"),
        _sub_dict("sub-b", "svc-b", db_key="spring.datasource.url"),
    ]
    frame_class_index = {"com.dxc.svc_a.Repo": "sub-a"}

    text = (
        "java.sql.SQLException: connection refused\n"
        "\tat com.dxc.svc_a.Repo.query(Repo.java:10)\n"
    )
    results = diagnose(text, sub_dicts, kb_entries, frame_class_index=frame_class_index)

    assert len(results) == 1
    findings = results[0]["context_findings"]
    assert len(findings) == 1
    assert findings[0]["service"] == "svc-a"


def test_no_frame_correlation_falls_back_to_whole_report_scope():
    kb_entries = [_kb_entry("sql-1", "Database/Flyway", r"java\.sql\.SQLException")]
    sub_dicts = [_sub_dict("sub-a", "svc-a"), _sub_dict("sub-b", "svc-b")]

    text = "java.sql.SQLException: connection refused\n\tat com.unknown.Thing.go(Thing.java:1)\n"
    results = diagnose(text, sub_dicts, kb_entries, frame_class_index={})

    assert len(results) == 1
    assert len(results[0]["context_findings"]) == 2


def test_multiple_independent_incidents_each_searched_and_deduped():
    kb_entries = [_kb_entry("sql-1", "Database/Flyway", r"java\.sql\.SQLException")]
    sub_dicts = [_sub_dict("sub-a", "svc-a")]

    text = (
        "java.sql.SQLException: first incident\n"
        "\tat com.x.A.a(A.java:1)\n"
        "java.sql.SQLException: second incident\n"
        "\tat com.x.B.b(B.java:2)\n"
    )
    results = diagnose(text, sub_dicts, kb_entries)

    # Same KB entry matched by both incidents - deduped to one result, not two.
    assert len(results) == 1
    assert results[0]["kb_entry"]["id"] == "sql-1"


def test_no_kb_match_returns_empty_list():
    kb_entries = [_kb_entry("sql-1", "Database/Flyway", r"totally-unrelated-pattern")]
    sub_dicts = [_sub_dict("sub-a", "svc-a")]
    assert diagnose("java.lang.NullPointerException: boom", sub_dicts, kb_entries) == []


def test_findings_carry_sub_report_id_for_every_context_rule():
    # Regression: every context_* function must stamp sub_report_id onto its
    # own findings (not just _auth_context, historically the only one that
    # did) - Docs' Diagnose "Create Bug" action needs it on any finding shape
    # to reliably prefill which service a new bug should link to.
    ssl_sub_dict = {
        "sub_report_id": "sub-a", "service_name": "svc-a", "filename": "svc-a.jar",
        "declared_port": None, "endpoints": [], "migration_scripts": [],
        "config_files": [{"filename": "application.yml", "keys": [
            {"key": "server.ssl.trust-store", "value": "${TRUST_STORE}", "is_placeholder": True},
        ]}],
    }
    ssl_results = diagnose(
        "javax.net.ssl.SSLHandshakeException: boom", [ssl_sub_dict],
        [_kb_entry("ssl-1", "SSL/TLS", r"SSLHandshakeException")],
    )
    assert ssl_results[0]["context_findings"][0]["sub_report_id"] == "sub-a"

    db_results = diagnose(
        "java.sql.SQLException: boom", [_sub_dict("sub-a", "svc-a")],
        [_kb_entry("db-1", "Database/Flyway", r"java\.sql\.SQLException")],
    )
    assert db_results[0]["context_findings"][0]["sub_report_id"] == "sub-a"
