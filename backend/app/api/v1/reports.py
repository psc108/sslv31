"""Compliance & Reporting endpoints — certificate inventory, weak keys, expiry forecast, audit export."""

import csv
import io
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_permission, AuthContext
from app.models.audit import AuditEvent
from app.models.certificate import Certificate
from app.models.ca import CertificateAuthority

router = APIRouter(prefix="/api/v1/reports", tags=["Reports"])


# --- Certificate Inventory ---

@router.get("/inventory")
async def certificate_inventory(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("audit:read")),
) -> dict:
    """Full certificate inventory with summary statistics."""
    certs = (await db.execute(select(Certificate))).scalars().all()

    now = datetime.now(timezone.utc)
    summary = {"total": 0, "valid": 0, "revoked": 0, "expired": 0, "held": 0}
    by_algo = {}
    by_profile = {}
    items = []

    for c in certs:
        summary["total"] += 1
        summary[c.status] = summary.get(c.status, 0) + 1
        by_algo[c.key_algo] = by_algo.get(c.key_algo, 0) + 1
        by_profile[c.profile] = by_profile.get(c.profile, 0) + 1

        subj = json.loads(c.subject_json) if c.subject_json else {}
        items.append({
            "serial": c.serial,
            "cn": subj.get("cn", ""),
            "profile": c.profile,
            "key_algo": c.key_algo,
            "key_size": c.key_size,
            "status": c.status,
            "expires_at": c.expires_at.isoformat() if c.expires_at else None,
            "signing_ca_id": c.signing_ca_id,
            "auto_renew": c.auto_renew,
        })

    return {
        "generated_at": now.isoformat(),
        "summary": summary,
        "by_algorithm": by_algo,
        "by_profile": by_profile,
        "certificates": items,
    }


# --- Weak Key Report ---

@router.get("/weak-keys")
async def weak_key_report(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("audit:read")),
) -> dict:
    """Identify certificates with weak cryptographic parameters."""
    certs = (await db.execute(
        select(Certificate).where(Certificate.status.in_(["valid", "held"]))
    )).scalars().all()

    cas = (await db.execute(select(CertificateAuthority))).scalars().all()

    findings = []

    for c in certs:
        issues = []
        if c.key_algo == "RSA" and c.key_size < 2048:
            issues.append(f"RSA key too small: {c.key_size} bits (minimum 2048)")
        if c.key_algo == "RSA" and c.key_size < 3072:
            issues.append(f"RSA key below recommended: {c.key_size} bits (recommend 3072+)")
        if c.key_algo == "ECDSA" and c.key_size < 256:
            issues.append(f"ECDSA key too small: {c.key_size} bits")
        if issues:
            subj = json.loads(c.subject_json) if c.subject_json else {}
            findings.append({
                "type": "certificate",
                "serial": c.serial,
                "cn": subj.get("cn", ""),
                "key_algo": c.key_algo,
                "key_size": c.key_size,
                "issues": issues,
            })

    for ca in cas:
        issues = []
        if ca.key_algo == "RSA" and ca.key_size < 4096:
            issues.append(f"CA RSA key below recommended: {ca.key_size} bits (recommend 4096)")
        if issues:
            findings.append({
                "type": "ca",
                "id": ca.id,
                "cn": ca.cn,
                "key_algo": ca.key_algo,
                "key_size": ca.key_size,
                "issues": issues,
            })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_findings": len(findings),
        "findings": findings,
    }


# --- Expiry Forecast ---

@router.get("/expiry-forecast")
async def expiry_forecast(
    days_30: int = Query(30, alias="window_30"),
    days_60: int = Query(60, alias="window_60"),
    days_90: int = Query(90, alias="window_90"),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("audit:read")),
) -> dict:
    """Certificates expiring within 30/60/90 day windows."""
    now = datetime.now(timezone.utc)
    # Make naive for SQLite comparison
    now_naive = now.replace(tzinfo=None)

    certs = (await db.execute(
        select(Certificate).where(
            Certificate.status.in_(["valid", "held"]),
            Certificate.expires_at > now_naive,
        )
    )).scalars().all()

    buckets = {"30_days": [], "60_days": [], "90_days": []}

    for c in certs:
        exp = c.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        days_left = (exp - now).days
        subj = json.loads(c.subject_json) if c.subject_json else {}
        entry = {
            "serial": c.serial,
            "cn": subj.get("cn", ""),
            "expires_at": c.expires_at.isoformat(),
            "days_remaining": days_left,
            "auto_renew": c.auto_renew,
        }
        if days_left <= 30:
            buckets["30_days"].append(entry)
        elif days_left <= 60:
            buckets["60_days"].append(entry)
        elif days_left <= 90:
            buckets["90_days"].append(entry)

    return {
        "generated_at": now.isoformat(),
        "summary": {k: len(v) for k, v in buckets.items()},
        "buckets": buckets,
    }


# --- Revocation Report ---

@router.get("/revocations")
async def revocation_report(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("audit:read")),
) -> dict:
    """All revoked and held certificates with reasons."""
    certs = (await db.execute(
        select(Certificate).where(Certificate.status.in_(["revoked", "held"]))
    )).scalars().all()

    items = []
    for c in certs:
        subj = json.loads(c.subject_json) if c.subject_json else {}
        items.append({
            "serial": c.serial,
            "cn": subj.get("cn", ""),
            "status": c.status,
            "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None,
            "held_at": c.held_at.isoformat() if c.held_at else None,
            "revocation_reason": c.revocation_reason,
            "profile": c.profile,
            "signing_ca_id": c.signing_ca_id,
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(items),
        "revoked": sum(1 for i in items if i["status"] == "revoked"),
        "held": sum(1 for i in items if i["status"] == "held"),
        "certificates": items,
    }


# --- Audit Log Export ---

@router.get("/audit-export")
async def audit_export(
    format: str = Query("json", pattern="^(json|csv|cef)$"),
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    limit: int = Query(10000, ge=1, le=100000),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("audit:read")),
) -> Response:
    """Export audit log in JSON, CSV, or CEF (Common Event Format) for SIEM integration."""
    query = select(AuditEvent).order_by(AuditEvent.timestamp.asc())
    if from_date:
        query = query.where(AuditEvent.timestamp >= from_date)
    if to_date:
        query = query.where(AuditEvent.timestamp <= to_date)
    query = query.limit(limit)

    events = (await db.execute(query)).scalars().all()

    if format == "json":
        items = [
            {
                "id": e.id,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                "event_type": e.event_type,
                "severity": e.severity,
                "operator": e.operator,
                "source_ip": e.source_ip,
                "subject_type": e.subject_type,
                "subject_id": e.subject_id,
                "description": e.description,
                "detail": e.detail_json,
                "hash": e.prev_hash,
            }
            for e in events
        ]
        return Response(
            content=json.dumps({"exported_at": datetime.now(timezone.utc).isoformat(), "count": len(items), "events": items}, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=audit-export.json"},
        )

    elif format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "timestamp", "event_type", "severity", "operator", "source_ip", "subject_type", "subject_id", "description", "hash"])
        for e in events:
            writer.writerow([
                e.id, e.timestamp.isoformat() if e.timestamp else "",
                e.event_type, e.severity, e.operator or "", e.source_ip or "",
                e.subject_type or "", e.subject_id or "", e.description or "", e.prev_hash or "",
            ])
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=audit-export.csv"},
        )

    else:  # CEF
        lines = []
        for e in events:
            # CEF:Version|Device Vendor|Device Product|Device Version|Signature ID|Name|Severity|Extensions
            sev = {"INFO": "3", "WARNING": "6", "ERROR": "8", "CRITICAL": "10"}.get(e.severity, "3")
            ext = f"src={e.source_ip or 'unknown'} suser={e.operator or 'system'} cs1={e.subject_id or ''} cs1Label=SubjectID msg={e.description or ''}"
            line = f"CEF:0|CertManager|SSLCertManager|1.0|{e.event_type}|{e.event_type}|{sev}|{ext}"
            lines.append(line)
        return Response(
            content="\n".join(lines),
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=audit-export.cef"},
        )


# --- Hash Chain Verification ---

@router.get("/audit-integrity")
async def verify_audit_integrity(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("audit:read")),
) -> dict:
    """Verify the tamper-evident hash chain of the audit log."""
    from app.services.audit import _compute_hash

    events = (await db.execute(
        select(AuditEvent).order_by(AuditEvent.id.asc())
    )).scalars().all()

    total = len(events)
    verified = 0
    broken_at = None
    prev_hash = "0" * 64

    for e in events:
        if e.prev_hash is None:
            # Legacy event without hash — skip
            verified += 1
            continue

        ts_naive = e.timestamp.isoformat() if e.timestamp else ""
        ts_aware = ts_naive + "+00:00" if ts_naive and "+" not in ts_naive else ts_naive
        sid_empty = e.subject_id or ""
        sid_none = str(e.subject_id)  # "None" if null

        # Try all combinations (old code used aware ts + raw subject_id;
        # new code uses naive ts + subject_id or "")
        matched = False
        for ts in (ts_naive, ts_aware):
            for sid in (sid_empty, sid_none):
                candidate = _compute_hash(e.event_type, sid, ts, prev_hash)
                if candidate == e.prev_hash:
                    matched = True
                    break
            if matched:
                break

        if matched:
            verified += 1
            prev_hash = e.prev_hash
        else:
            broken_at = e.id
            break

    return {
        "total_events": total,
        "verified": verified,
        "intact": broken_at is None,
        "broken_at_id": broken_at,
    }
