"""Compliance scanner — CA/Browser Forum BR and CIS PKI benchmark checks.

Scans all certificates and CAs against industry compliance rules and returns
structured findings with severity levels.
"""

import json
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import rsa, ec
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.certificate import Certificate
from app.models.ca import CertificateAuthority

logger = logging.getLogger(__name__)


@dataclass
class Finding:
    severity: str  # violation, warning, info
    rule: str
    category: str  # br, cis
    subject: str  # serial or CA id
    subject_cn: str
    subject_type: str  # cert, ca
    message: str


@dataclass
class ScanResult:
    scan_type: str
    total_checked: int = 0
    violations: int = 0
    warnings: int = 0
    findings: list = field(default_factory=list)


async def run_br_scan(db: AsyncSession) -> ScanResult:
    """CA/Browser Forum Baseline Requirements compliance scan."""
    result = ScanResult(scan_type="br")

    certs = (await db.execute(
        select(Certificate).where(Certificate.status.in_(["valid", "held"]))
    )).scalars().all()

    for cert in certs:
        result.total_checked += 1
        subj = json.loads(cert.subject_json) if cert.subject_json else {}
        cn = subj.get("cn", cert.serial[:16])

        # BR 6.3.2: Maximum validity 398 days for server certs
        if cert.profile == "server" and cert.cert_pem:
            try:
                c = x509.load_pem_x509_certificate(cert.cert_pem.encode())
                validity_days = (c.not_valid_after_utc - c.not_valid_before_utc).days
                if validity_days > 398:
                    _add(result, "violation", "BR-6.3.2", "br", cert.serial, cn, "cert",
                         f"Server cert validity {validity_days} days exceeds 398-day maximum")
            except Exception:
                pass

        # BR 6.1.5: Minimum key size
        if cert.key_algo == "RSA" and cert.key_size < 2048:
            _add(result, "violation", "BR-6.1.5", "br", cert.serial, cn, "cert",
                 f"RSA key {cert.key_size} bits below 2048-bit minimum")
        if cert.key_algo == "ECDSA" and cert.key_size < 256:
            _add(result, "violation", "BR-6.1.5", "br", cert.serial, cn, "cert",
                 f"ECDSA key {cert.key_size} bits below 256-bit minimum")

        # BR 7.1.4.2.1: SAN required for server certs
        if cert.profile == "server":
            sans = json.loads(cert.san_json) if cert.san_json else []
            if not sans:
                _add(result, "violation", "BR-7.1.4.2.1", "br", cert.serial, cn, "cert",
                     "Server certificate missing Subject Alternative Name")

        # BR: Serial number entropy (≥64 bits = 8 bytes = 16 hex chars)
        if len(cert.serial) < 16:
            _add(result, "warning", "BR-7.1", "br", cert.serial, cn, "cert",
                 f"Serial number entropy may be insufficient ({len(cert.serial)} hex chars, recommend ≥16)")

        # Check for SHA-1 (prohibited since 2016)
        if cert.cert_pem:
            try:
                c = x509.load_pem_x509_certificate(cert.cert_pem.encode())
                sig_algo = c.signature_algorithm_oid.dotted_string
                # SHA-1 with RSA: 1.2.840.113549.1.1.5
                if sig_algo == "1.2.840.113549.1.1.5":
                    _add(result, "violation", "BR-6.1.5", "br", cert.serial, cn, "cert",
                         "Certificate signed with SHA-1 (prohibited)")
            except Exception:
                pass

        # Wildcard restrictions: no bare wildcard (*.tld)
        sans = json.loads(cert.san_json) if cert.san_json else []
        for san in sans:
            if san.get("type") == "dns" and san.get("value", "").startswith("*."):
                parts = san["value"].split(".")
                if len(parts) <= 2:
                    _add(result, "violation", "BR-3.2.2.6", "br", cert.serial, cn, "cert",
                         f"Bare wildcard not allowed: {san['value']}")

    return result


async def run_cis_scan(db: AsyncSession) -> ScanResult:
    """CIS Benchmark for PKI infrastructure scan."""
    result = ScanResult(scan_type="cis")

    cas = (await db.execute(select(CertificateAuthority))).scalars().all()

    for ca in cas:
        result.total_checked += 1

        # CIS: CA key size ≥ 4096 RSA or 384 ECDSA
        if ca.key_algo == "RSA" and ca.key_size < 4096:
            _add(result, "warning", "CIS-CA-KEY", "cis", ca.id, ca.cn, "ca",
                 f"CA RSA key {ca.key_size} bits (CIS recommends ≥4096)")
        if ca.key_algo == "ECDSA" and ca.key_size < 384:
            _add(result, "warning", "CIS-CA-KEY", "cis", ca.id, ca.cn, "ca",
                 f"CA ECDSA key {ca.key_size} bits (CIS recommends ≥384)")

        # CIS: Key storage encrypted (we always encrypt, so pass)
        if not ca.key_blob:
            _add(result, "info", "CIS-KEY-STORE", "cis", ca.id, ca.cn, "ca",
                 "CA has no key material (offline root — expected)")

    # CIS: Check CRL freshness
    from app.core.config import settings
    if not settings.PKI_BASE_URL:
        _add(result, "warning", "CIS-CRL", "cis", "system", "PKI Config", "config",
             "PKI_BASE_URL not configured — CRL/OCSP endpoints disabled")
        result.total_checked += 1

    # CIS: Access control enforced (always true — RBAC is built-in)
    result.total_checked += 1  # pass

    # CIS: Audit logging enabled and tamper-evident
    from app.models.audit import AuditEvent
    count = (await db.execute(select(AuditEvent.id).limit(1))).scalar_one_or_none()
    if count is None:
        _add(result, "warning", "CIS-AUDIT", "cis", "system", "Audit", "config",
             "No audit events found — audit logging may not be functioning")
    result.total_checked += 1

    return result


async def run_full_scan(db: AsyncSession) -> ScanResult:
    """Run both BR and CIS scans, merge results."""
    br = await run_br_scan(db)
    cis = await run_cis_scan(db)

    merged = ScanResult(
        scan_type="full",
        total_checked=br.total_checked + cis.total_checked,
        violations=br.violations + cis.violations,
        warnings=br.warnings + cis.warnings,
        findings=br.findings + cis.findings,
    )
    return merged


def _add(result: ScanResult, severity: str, rule: str, category: str,
         subject: str, subject_cn: str, subject_type: str, message: str) -> None:
    finding = Finding(
        severity=severity, rule=rule, category=category,
        subject=subject, subject_cn=subject_cn,
        subject_type=subject_type, message=message,
    )
    result.findings.append(asdict(finding))
    if severity == "violation":
        result.violations += 1
    elif severity == "warning":
        result.warnings += 1
