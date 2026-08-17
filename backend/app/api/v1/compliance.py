"""Compliance & Advanced Reporting endpoints.

Automated compliance checking against CA/Browser Forum Baseline Requirements
and CIS PKI benchmarks. Stores historical results for trend tracking.
"""

import csv
import io
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import AuthContext, require_permission
from app.models.compliance import ComplianceScan
from app.services.compliance_scanner import run_br_scan, run_cis_scan, run_full_scan
from app.services.audit import audit_event

router = APIRouter(prefix="/api/v1/compliance", tags=["Compliance"])


@router.post("/scan")
async def run_compliance_scan(
    scan_type: str = Query("full", pattern="^(br|cis|full)$"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("audit:read")),
) -> dict:
    """Run a compliance scan and store results.

    scan_type: br (Baseline Requirements), cis (CIS Benchmark), full (both)
    """
    if scan_type == "br":
        result = await run_br_scan(db)
    elif scan_type == "cis":
        result = await run_cis_scan(db)
    else:
        result = await run_full_scan(db)

    now = datetime.now(timezone.utc)

    # Build summary
    summary = {
        "violations_by_rule": {},
        "warnings_by_rule": {},
    }
    for f in result.findings:
        bucket = "violations_by_rule" if f["severity"] == "violation" else "warnings_by_rule"
        rule = f["rule"]
        summary[bucket][rule] = summary[bucket].get(rule, 0) + 1

    # Store
    scan = ComplianceScan(
        scan_type=result.scan_type,
        status="completed",
        total_checked=result.total_checked,
        total_violations=result.violations,
        total_warnings=result.warnings,
        results_json=json.dumps(result.findings),
        summary_json=json.dumps(summary),
        scanned_at=now,
        tenant_id=auth.tenant_id,
    )
    db.add(scan)

    await audit_event(
        db=db, event_type="COMPLIANCE_SCAN", severity="INFO", request=request,
        subject_type="compliance", subject_id=scan.id,
        description=f"Compliance scan ({scan_type}): {result.violations} violations, {result.warnings} warnings",
    )
    await db.commit()

    return {
        "id": scan.id,
        "scan_type": result.scan_type,
        "scanned_at": now.isoformat(),
        "total_checked": result.total_checked,
        "total_violations": result.violations,
        "total_warnings": result.warnings,
        "summary": summary,
        "findings": result.findings,
    }


@router.get("/latest")
async def get_latest_scan(
    scan_type: str = Query("full", pattern="^(br|cis|full)$"),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("audit:read")),
) -> dict:
    """Get the most recent compliance scan results."""
    query = (
        select(ComplianceScan)
        .where(ComplianceScan.scan_type == scan_type)
        .order_by(ComplianceScan.scanned_at.desc())
        .limit(1)
    )
    scan = (await db.execute(query)).scalar_one_or_none()
    if not scan:
        return {"message": "No scan results found. Run a scan first.", "findings": []}

    return {
        "id": scan.id,
        "scan_type": scan.scan_type,
        "scanned_at": scan.scanned_at.isoformat() if scan.scanned_at else None,
        "total_checked": scan.total_checked,
        "total_violations": scan.total_violations,
        "total_warnings": scan.total_warnings,
        "summary": json.loads(scan.summary_json),
        "findings": json.loads(scan.results_json),
    }


@router.get("/history")
async def get_scan_history(
    scan_type: str = Query("full", pattern="^(br|cis|full)$"),
    limit: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("audit:read")),
) -> dict:
    """Get historical compliance scan results for trend tracking."""
    query = (
        select(ComplianceScan)
        .where(ComplianceScan.scan_type == scan_type)
        .order_by(ComplianceScan.scanned_at.desc())
        .limit(limit)
    )
    scans = (await db.execute(query)).scalars().all()

    items = []
    for s in scans:
        items.append({
            "id": s.id,
            "scanned_at": s.scanned_at.isoformat() if s.scanned_at else None,
            "total_checked": s.total_checked,
            "total_violations": s.total_violations,
            "total_warnings": s.total_warnings,
            "summary": json.loads(s.summary_json),
        })

    return {"scan_type": scan_type, "count": len(items), "scans": items}


@router.get("/export")
async def export_compliance_report(
    scan_id: str = Query(None),
    format: str = Query("csv", pattern="^(csv|json)$"),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("audit:read")),
) -> Response:
    """Export a compliance scan report as CSV or JSON.

    If scan_id is not provided, exports the latest full scan.
    """
    if scan_id:
        scan = await db.get(ComplianceScan, scan_id)
    else:
        query = (
            select(ComplianceScan)
            .where(ComplianceScan.scan_type == "full")
            .order_by(ComplianceScan.scanned_at.desc())
            .limit(1)
        )
        scan = (await db.execute(query)).scalar_one_or_none()

    if not scan:
        return Response(content="No scan results found", status_code=404)

    findings = json.loads(scan.results_json)

    if format == "json":
        export = {
            "report": "Compliance Scan Report",
            "scan_type": scan.scan_type,
            "scanned_at": scan.scanned_at.isoformat() if scan.scanned_at else None,
            "total_checked": scan.total_checked,
            "total_violations": scan.total_violations,
            "total_warnings": scan.total_warnings,
            "findings": findings,
        }
        return Response(
            content=json.dumps(export, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=compliance-{scan.scan_type}-{scan.id[:8]}.json"},
        )

    # CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Severity", "Rule", "Category", "Subject Type", "Subject", "CN", "Message"])
    for f in findings:
        writer.writerow([
            f.get("severity", ""),
            f.get("rule", ""),
            f.get("category", ""),
            f.get("subject_type", ""),
            f.get("subject", ""),
            f.get("subject_cn", ""),
            f.get("message", ""),
        ])
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=compliance-{scan.scan_type}-{scan.id[:8]}.csv"},
    )


@router.get("/rules")
async def list_compliance_rules(
    auth: AuthContext = Depends(require_permission("audit:read")),
) -> dict:
    """List all compliance rules checked by the scanner."""
    return {
        "br_rules": [
            {"id": "BR-6.3.2", "name": "Maximum Validity", "description": "Server certificates must not exceed 398 days validity"},
            {"id": "BR-6.1.5", "name": "Minimum Key Size", "description": "RSA ≥2048 bits, ECDSA ≥256 bits"},
            {"id": "BR-7.1.4.2.1", "name": "SAN Required", "description": "Server certificates must include Subject Alternative Name"},
            {"id": "BR-7.1", "name": "Serial Entropy", "description": "Serial numbers must contain ≥64 bits of entropy"},
            {"id": "BR-6.1.5-SHA1", "name": "SHA-1 Prohibited", "description": "SHA-1 signatures are prohibited"},
            {"id": "BR-3.2.2.6", "name": "Wildcard Restrictions", "description": "Bare wildcards (*.tld) are not allowed"},
        ],
        "cis_rules": [
            {"id": "CIS-CA-KEY", "name": "CA Key Strength", "description": "CA keys should be RSA ≥4096 or ECDSA ≥384"},
            {"id": "CIS-KEY-STORE", "name": "Key Storage", "description": "CA keys must be encrypted at rest"},
            {"id": "CIS-CRL", "name": "CRL/OCSP Available", "description": "PKI_BASE_URL must be configured for CRL/OCSP"},
            {"id": "CIS-AUDIT", "name": "Audit Logging", "description": "Audit logging must be active and recording events"},
        ],
    }
