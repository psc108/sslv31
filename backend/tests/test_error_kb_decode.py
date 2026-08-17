"""Integration coverage for POST /api/v1/docs/error-kb/decode — the missing
link between stack_trace_parser.py and the existing Error KB search
(error_kb.search_kb / docs_error_kb.build_kb_entries), plus the frame ->
known-analysed-service cross-reference (_lookup_known_classes)."""
import uuid

from app.core.database import async_session
from app.models.jar_analyser import AnalysisReport, JarDecompiledClass, JarStringConstant, JarUpload, SubReport


async def _seed_known_class(*, class_name_dotted: str, service_name: str, decompiled: bool = False) -> tuple[str, str]:
    """Directly inserts an AnalysisReport/SubReport/JarStringConstant row set
    for one class — a real upload+analyse pipeline is far more than this
    endpoint's own cross-reference query needs to be exercised against."""
    async with async_session() as db:
        upload = JarUpload(
            filename="sample.jar", original_name="sample.jar",
            sha256=uuid.uuid4().hex.ljust(64, "0"), md5=uuid.uuid4().hex[:32].ljust(32, "0"),
            size_bytes=1, stored_path="/tmp/sample.jar", status="analysing",
        )
        db.add(upload)
        await db.flush()

        report = AnalysisReport(upload_id=upload.id, status="completed", analyser_version="test")
        db.add(report)
        await db.flush()

        sub = SubReport(parent_report_id=report.id, filename="service.jar", service_name=service_name)
        db.add(sub)
        await db.flush()

        db.add(JarStringConstant(sub_report_id=sub.id, class_name=class_name_dotted, value="some log message"))
        if decompiled:
            db.add(JarDecompiledClass(
                sub_report_id=sub.id, class_name=class_name_dotted.replace(".", "/"),
                package_name=class_name_dotted.rsplit(".", 1)[0], simple_name=class_name_dotted.rsplit(".", 1)[-1],
                source="class body",
            ))
        await db.commit()
        return report.id, sub.id


async def _make_kb_doc(client, *, category: str, title: str, pattern: str) -> str:
    lib = await client.post("/api/v1/docs/libraries", json={"name": f"{category} {uuid.uuid4().hex[:8]}"})
    assert lib.status_code == 201, lib.text
    library_id = lib.json()["id"]
    shelf = await client.post("/api/v1/docs/shelves", json={"library_id": library_id, "name": "Errors"})
    assert shelf.status_code == 201, shelf.text
    content = f"**Severity:** high\n**Pattern:** `{pattern}`\n\nSome plain-English explanation.\n"
    doc = await client.post("/api/v1/docs", json={"shelf_id": shelf.json()["id"], "name": title, "content": content})
    assert doc.status_code == 201, doc.text
    return doc.json()["id"]


async def test_decode_matches_each_exception_in_chain_independently(client):
    npe_doc_id = await _make_kb_doc(
        client, category="Java",
        title=f"NPE {uuid.uuid4().hex[:8]}", pattern=r"java\.lang\.NullPointerException",
    )

    text = (
        'java.lang.NullPointerException: Cannot invoke "String.length()" because "s" is null\n'
        "\tat com.x.A.a(A.java:1)\n"
        "Caused by: java.sql.SQLException: connection refused\n"
        "\tat com.x.B.b(B.java:2)\n"
    )
    resp = await client.post("/api/v1/docs/error-kb/decode", json={"text": text})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["total_exceptions"] == 2
    root, caused_by = body["exceptions"]

    assert root["kind"] == "root"
    assert root["exception_class"] == "java.lang.NullPointerException"
    assert root["is_likely_root_cause"] is False
    assert len(root["frames"]) == 1
    assert root["frames"][0]["class_name"] == "com.x.A"
    assert root["frames"][0]["is_application_frame"] is True
    assert root["frames"][0]["known_in"] == []
    assert [m["doc_id"] for m in root["kb_matches"]] == [npe_doc_id]

    assert caused_by["kind"] == "caused_by"
    assert caused_by["exception_class"] == "java.sql.SQLException"
    assert caused_by["is_likely_root_cause"] is True
    assert caused_by["kb_matches"] == []


async def test_decode_cross_references_frame_against_known_analysed_service(client):
    report_id, sub_id = await _seed_known_class(
        class_name_dotted="com.dxc.ecs.fulfillment.service.ServiceDesignService",
        service_name="fulfillment", decompiled=False,
    )
    text = (
        "java.lang.NullPointerException: boom\n"
        "\tat com.dxc.ecs.fulfillment.service.ServiceDesignService.build(ServiceDesignService.java:42)\n"
        "\tat org.springframework.web.method.support.InvocableHandlerMethod.invoke(InvocableHandlerMethod.java:205)\n"
    )
    resp = await client.post("/api/v1/docs/error-kb/decode", json={"text": text})
    assert resp.status_code == 200, resp.text
    frames = resp.json()["exceptions"][0]["frames"]

    own_frame, framework_frame = frames
    assert own_frame["is_application_frame"] is True
    assert own_frame["known_in"] == [{
        "sub_report_id": sub_id, "report_id": report_id,
        "service_name": "fulfillment", "filename": "service.jar", "decompiled": False,
    }]

    assert framework_frame["is_application_frame"] is False
    assert framework_frame["known_in"] == []


async def test_decode_marks_known_class_as_decompiled_when_source_available(client):
    report_id, sub_id = await _seed_known_class(
        class_name_dotted="com.dxc.ecs.customers.service.ContractService",
        service_name="customers", decompiled=True,
    )
    text = "java.lang.Exception: boom\n\tat com.dxc.ecs.customers.service.ContractService.lookup(ContractService.java:10)\n"
    resp = await client.post("/api/v1/docs/error-kb/decode", json={"text": text})
    assert resp.status_code == 200
    match = resp.json()["exceptions"][0]["frames"][0]["known_in"][0]
    assert match["decompiled"] is True
    assert match["sub_report_id"] == sub_id


async def test_decode_unknown_class_has_empty_known_in(client):
    text = "java.lang.Exception: boom\n\tat com.totally.unrelated.Nothing.here(Nothing.java:1)\n"
    resp = await client.post("/api/v1/docs/error-kb/decode", json={"text": text})
    assert resp.status_code == 200
    assert resp.json()["exceptions"][0]["frames"][0]["known_in"] == []


async def test_decode_empty_text_rejected(client):
    resp = await client.post("/api/v1/docs/error-kb/decode", json={"text": ""})
    assert resp.status_code == 422


async def test_decode_text_with_no_recognisable_trace_returns_empty_exceptions(client):
    resp = await client.post("/api/v1/docs/error-kb/decode", json={"text": "just a plain log line, nothing structured"})
    assert resp.status_code == 200
    assert resp.json() == {"total_exceptions": 0, "exceptions": []}


async def test_decode_bumps_kb_usage_count(client):
    doc_id = await _make_kb_doc(
        client, category="Java",
        title=f"OOM {uuid.uuid4().hex[:8]}", pattern=r"OutOfMemoryError",
    )
    text = "java.lang.OutOfMemoryError: Java heap space\n\tat com.x.A.a(A.java:1)\n"
    resp = await client.post("/api/v1/docs/error-kb/decode", json={"text": text})
    assert resp.status_code == 200

    usage = await client.get("/api/v1/docs/error-kb/usage")
    assert usage.status_code == 200
    entry = next(e for e in usage.json()["entries"] if e["doc_id"] == doc_id)
    assert entry["match_count"] >= 1
