"""Infrastructure Diagnostics REST API — Phase 1 + Phase 2."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import AuthContext, require_role
from app.models.jar_analyser import JarDiagnosticRun
from app.services.infra_diagnostics.infra_services import SERVICES

router = APIRouter(prefix="/api/v1/infra-diagnostics", tags=["infra-diagnostics"])


def _get_questionnaire_sections(service: str) -> list[dict]:
    if service == "mysql":
        from app.services.infra_diagnostics.mysql_questionnaire import get_questionnaire
    elif service == "rabbitmq":
        from app.services.infra_diagnostics.rabbitmq_questionnaire import get_questionnaire
    elif service == "keystone":
        from app.services.infra_diagnostics.keystone_questionnaire import get_questionnaire
    else:
        raise HTTPException(status_code=404, detail=f"Unknown service '{service}'")
    return get_questionnaire()


def _questionnaire_to_markdown(service: str, sections: list[dict]) -> str:
    meta = SERVICES[service]
    lines = [
        f"# Infrastructure Diagnostic Request — {meta.display_name}",
        "",
        f"Run each command on the **{meta.display_name}** server and paste the output into the",
        "Infrastructure Diagnostics tool.",
        "If a command is not available or not applicable, leave the field blank.",
        "",
    ]
    for sec in sections:
        lines.append(f"## {sec['title']}")
        lines.append(f"_{sec['description']}_")
        lines.append("")
        for item in sec["items"]:
            req = " *(required)*" if item.get("required") else ""
            lines.append(f"### {item['label']}{req}")
            lines.append(item["context"])
            lines.append("")
            if item.get("command"):
                lines.append("```bash")
                lines.append(item["command"])
                lines.append("```")
            lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# GET /services
# ---------------------------------------------------------------------------

@router.get("/services")
async def list_services(
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict]:
    """List supported infrastructure services with metadata."""
    result = []
    for svc_id, meta in SERVICES.items():
        sections = _get_questionnaire_sections(svc_id)
        question_count = sum(len(s["items"]) for s in sections)
        result.append({
            "id": meta.id,
            "display_name": meta.display_name,
            "description": meta.description,
            "icon": meta.icon,
            "section_count": len(sections),
            "question_count": question_count,
        })
    return result


# ---------------------------------------------------------------------------
# GET /{service}/questionnaire
# ---------------------------------------------------------------------------

@router.get("/{service}/questionnaire")
async def get_questionnaire(
    service: str,
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict:
    """Return the structured questionnaire for a service.

    Optional query param ?report_id= is accepted but ignored until Phase 2
    when the report context pre-fill is implemented.
    """
    if service not in SERVICES:
        raise HTTPException(status_code=404, detail=f"Unknown service '{service}'")
    meta = SERVICES[service]
    sections = _get_questionnaire_sections(service)
    return {
        "service": service,
        "display_name": meta.display_name,
        "total_sections": len(sections),
        "total_items": sum(len(s["items"]) for s in sections),
        "required_items": sum(1 for s in sections for i in s["items"] if i.get("required")),
        "sections": sections,
        "prefill": {},  # populated in Phase 2 when report_id is supplied
    }


# ---------------------------------------------------------------------------
# GET /{service}/questionnaire/markdown
# ---------------------------------------------------------------------------

@router.get("/{service}/questionnaire/markdown")
async def get_questionnaire_markdown(
    service: str,
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> PlainTextResponse:
    """Return the questionnaire as a Markdown document for offline use."""
    if service not in SERVICES:
        raise HTTPException(status_code=404, detail=f"Unknown service '{service}'")
    sections = _get_questionnaire_sections(service)
    content = _questionnaire_to_markdown(service, sections)
    filename = f"infra-diag-{service}.md"
    return PlainTextResponse(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# POST /{service}/analyse
# ---------------------------------------------------------------------------

class AnalyseRequest(BaseModel):
    responses: dict[str, str]
    label: str | None = None
    report_id: str | None = None


@router.post("/{service}/analyse", status_code=201)
async def analyse_responses(
    service: str,
    body: AnalyseRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Submit questionnaire responses, run analysis, persist and return findings."""
    if service not in SERVICES:
        raise HTTPException(status_code=404, detail=f"Unknown service '{service}'")
    if not body.responses:
        raise HTTPException(status_code=422, detail="responses must not be empty")

    # Load report context if report_id supplied
    report_context: dict | None = None
    prefill: dict[str, str] = {}
    if body.report_id:
        from app.models.jar_analyser import SubReport, JarConfigFile
        from app.services.infra_diagnostics.infra_report_context import extract
        from app.api.v1.jar_analyser import _config_dict
        subs = (await db.execute(
            select(SubReport).where(SubReport.parent_report_id == body.report_id)
        )).scalars().all()
        sub_dicts = []
        for sub in subs:
            cfgs = (await db.execute(
                select(JarConfigFile).where(JarConfigFile.sub_report_id == sub.id)
            )).scalars().all()
            sub_dicts.append({"service_name": sub.service_name, "config_files": [_config_dict(c) for c in cfgs]})
        prefill, report_context = extract(sub_dicts)

    # Run the service-specific analyser
    if service == "mysql":
        from app.services.infra_diagnostics.mysql_analyser import analyse
    elif service == "rabbitmq":
        from app.services.infra_diagnostics.rabbitmq_analyser import analyse
    else:
        from app.services.infra_diagnostics.keystone_analyser import analyse

    result = analyse(body.responses, report_context)

    # Persist as a JarDiagnosticRun (report_id nullable, bundle_filename = discriminator)
    run = JarDiagnosticRun(
        report_id=body.report_id,
        uploaded_by=auth.username,
        bundle_filename=f"[infra:{service}]",
        bundle_size_bytes=sum(len(v) for v in body.responses.values()),
        status="completed",
        run_label=body.label,
        report_data=json.dumps({
            "responses": body.responses,
            "report_id": body.report_id,
        }),
        summary_json=json.dumps(result["summary"]),
        findings_json=json.dumps(result["findings"]),
        cert_results_json=json.dumps(result["cert_results"]),
        port_results_json=json.dumps(result["port_results"]),
        rmq_summary_json=json.dumps({}),
        config_issues_json=json.dumps(result["config_issues"]),
        log_findings_json=json.dumps(result["log_findings"]),
        os_info="",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    return {
        "run_id": run.id,
        "service": service,
        "label": body.label,
        "created_at": run.uploaded_at.isoformat(),
        "missing_required": result["missing_required"],
        "summary": result["summary"],
        "findings": result["findings"],
        "cert_results": result["cert_results"],
        "port_results": result["port_results"],
        "log_findings": result["log_findings"],
        "ai_summary": None,
    }


# ---------------------------------------------------------------------------
# GET /runs  +  GET /runs/{run_id}
# ---------------------------------------------------------------------------

@router.get("/runs")
async def list_runs(
    service: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """List stored infrastructure diagnostic runs, newest first."""
    q = select(JarDiagnosticRun).where(
        JarDiagnosticRun.bundle_filename.like("[infra:%")
    )
    if service:
        q = q.where(JarDiagnosticRun.bundle_filename == f"[infra:{service}]")
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    rows = (await db.execute(
        q.order_by(JarDiagnosticRun.uploaded_at.desc())
         .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    return {
        "items": [_run_summary(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


@router.get("/runs/{run_id}/markdown")
async def get_run_markdown(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> PlainTextResponse:
    """Export a stored infrastructure diagnostic run as a Markdown document."""
    from app.services.infra_diagnostics.infra_markdown_export import render
    run = await _get_run_or_404(db, run_id)
    svc = (run.bundle_filename or "").removeprefix("[infra:").rstrip("]")
    meta = SERVICES[svc]
    sections = _get_questionnaire_sections(svc)
    rd = json.loads(run.report_data) if run.report_data else {}
    content = render(
        service=svc,
        display_name=meta.display_name,
        label=run.run_label,
        created_at=run.uploaded_at.isoformat() if run.uploaded_at else None,
        summary=json.loads(run.summary_json) if run.summary_json else {},
        findings=json.loads(run.findings_json) if run.findings_json else [],
        cert_results=json.loads(run.cert_results_json) if run.cert_results_json else [],
        port_results=json.loads(run.port_results_json) if run.port_results_json else [],
        log_findings=json.loads(run.log_findings_json) if run.log_findings_json else [],
        responses=rd.get("responses", {}),
        sections=sections,
    )
    filename = f"infra-diag-{svc}-{run_id[:8]}.md"
    return PlainTextResponse(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """Retrieve a stored infrastructure diagnostic run with full findings and responses."""
    run = await _get_run_or_404(db, run_id)
    d = _run_summary(run)
    rd = json.loads(run.report_data) if run.report_data else {}
    d.update({
        "responses":    rd.get("responses", {}),
        "findings":     json.loads(run.findings_json) if run.findings_json else [],
        "cert_results": json.loads(run.cert_results_json) if run.cert_results_json else [],
        "port_results": json.loads(run.port_results_json) if run.port_results_json else [],
        "log_findings": json.loads(run.log_findings_json) if run.log_findings_json else [],
        "ai_summary":   None,
    })
    return d


async def _get_run_or_404(db: AsyncSession, run_id: str) -> JarDiagnosticRun:
    r = (await db.execute(
        select(JarDiagnosticRun).where(
            JarDiagnosticRun.id == run_id,
            JarDiagnosticRun.bundle_filename.like("[infra:%"),
        )
    )).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="Run not found")
    return r


def _run_summary(r: JarDiagnosticRun) -> dict[str, Any]:
    svc = (r.bundle_filename or "").removeprefix("[infra:").rstrip("]")
    return {
        "run_id":     r.id,
        "service":    svc,
        "label":      r.run_label,
        "created_at": r.uploaded_at.isoformat() if r.uploaded_at else None,
        "summary":    json.loads(r.summary_json) if r.summary_json else {},
    }


# ---------------------------------------------------------------------------
# Reserved AI endpoints — 501 stubs (Part 8 of the design plan)
# ---------------------------------------------------------------------------

@router.post("/{service}/ai-chat", status_code=501, include_in_schema=False)
async def ai_chat_stub(service: str) -> dict:
    raise HTTPException(status_code=501, detail="AI agent integration not yet implemented")


@router.post("/runs/{run_id}/ai-analyse", status_code=501, include_in_schema=False)
async def ai_analyse_stub(run_id: str) -> dict:
    raise HTTPException(status_code=501, detail="AI agent integration not yet implemented")


@router.get("/runs/{run_id}/ai-summary", status_code=501, include_in_schema=False)
async def ai_summary_stub(run_id: str) -> dict:
    raise HTTPException(status_code=501, detail="AI agent integration not yet implemented")
