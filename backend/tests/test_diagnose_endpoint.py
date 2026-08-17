"""Integration coverage for POST /api/v1/jar-analyser/reports/{report_id}/diagnose
— confirms the report-scoped frame -> service correlation (_build_frame_class_index)
actually wires up end-to-end against a real seeded report, not just diagnose()'s
own unit tests against hand-built dicts."""
import json
import uuid

from app.core.database import async_session
from app.models.jar_analyser import AnalysisReport, JarConfigFile, JarStringConstant, JarUpload, SubReport


async def _seed_report_with_two_services() -> tuple[str, str, str]:
    """One report with two sub-reports, each with its own DB config key and
    its own known class (via JarStringConstant) — lets a pasted trace naming
    only one of those classes prove the endpoint scopes context_findings to
    just that one service, not both."""
    async with async_session() as db:
        upload = JarUpload(
            filename="bundle.jar", original_name="bundle.jar",
            sha256=uuid.uuid4().hex.ljust(64, "0"), md5=uuid.uuid4().hex[:32].ljust(32, "0"),
            size_bytes=1, stored_path="/tmp/bundle.jar", status="analysing",
        )
        db.add(upload)
        await db.flush()

        report = AnalysisReport(upload_id=upload.id, status="completed", analyser_version="test")
        db.add(report)
        await db.flush()

        sub_a = SubReport(parent_report_id=report.id, filename="svc-a.jar", service_name="svc-a")
        sub_b = SubReport(parent_report_id=report.id, filename="svc-b.jar", service_name="svc-b")
        db.add_all([sub_a, sub_b])
        await db.flush()

        keys = json.dumps([{"key": "spring.datasource.url", "value": "jdbc:postgresql://db:5432/x", "is_placeholder": False}])
        db.add(JarConfigFile(sub_report_id=sub_a.id, filename="application.yml", path_in_jar="BOOT-INF/classes/application.yml", keys_json=keys))
        db.add(JarConfigFile(sub_report_id=sub_b.id, filename="application.yml", path_in_jar="BOOT-INF/classes/application.yml", keys_json=keys))
        db.add(JarStringConstant(sub_report_id=sub_a.id, class_name="com.dxc.svc_a.repo.Repo", value="some log message"))
        await db.commit()
        return report.id, sub_a.id, sub_b.id


async def _make_kb_doc(client, *, pattern: str) -> str:
    # Category must be the literal "Database/Flyway" string - that's the
    # exact key _CONTEXT_RULES looks up to route to _db_context/_db_actions
    # rather than falling back to the generic _http_context.
    lib = await client.post("/api/v1/docs/libraries", json={"name": "Database/Flyway"})
    library_id = lib.json()["id"]
    shelf = await client.post("/api/v1/docs/shelves", json={"library_id": library_id, "name": f"Errors {uuid.uuid4().hex[:8]}"})
    content = f"**Severity:** high\n**Pattern:** `{pattern}`\n\nExplanation.\n"
    doc = await client.post("/api/v1/docs", json={"shelf_id": shelf.json()["id"], "name": f"SQLException {uuid.uuid4().hex[:8]}", "content": content})
    return doc.json()["id"]


async def test_diagnose_scopes_context_findings_to_the_service_named_in_the_trace(client):
    report_id, sub_a_id, sub_b_id = await _seed_report_with_two_services()
    await _make_kb_doc(client, pattern=r"java\.sql\.SQLException")

    text = (
        "java.lang.RuntimeException: outer wrapper\n"
        "\tat com.x.A.a(A.java:1)\n"
        "Caused by: java.sql.SQLException: connection refused\n"
        "\tat com.dxc.svc_a.repo.Repo.query(Repo.java:10)\n"
    )
    resp = await client.post(f"/api/v1/jar-analyser/reports/{report_id}/diagnose", json={"error_text": text})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["total"] == 1
    result = body["results"][0]
    assert result["matched_exception"]["exception_class"] == "java.sql.SQLException"
    findings = result["context_findings"]
    assert len(findings) == 1
    assert findings[0]["service"] == "svc-a"


async def test_diagnose_with_no_frame_match_falls_back_to_whole_report(client):
    report_id, sub_a_id, sub_b_id = await _seed_report_with_two_services()
    await _make_kb_doc(client, pattern=r"java\.sql\.SQLException")

    text = "java.sql.SQLException: connection refused\n\tat com.totally.unrelated.Thing.go(Thing.java:1)\n"
    resp = await client.post(f"/api/v1/jar-analyser/reports/{report_id}/diagnose", json={"error_text": text})
    assert resp.status_code == 200
    findings = resp.json()["results"][0]["context_findings"]
    assert len(findings) == 2
