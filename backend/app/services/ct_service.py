"""Certificate Transparency service — Merkle tree, SCT generation, log operations."""

import hashlib
import hmac as _hmac
import json
from datetime import datetime, timezone

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ct_log import CTLogEntry, CTTreeHead


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _leaf_hash(entry_data: bytes) -> str:
    """RFC 6962 §2.1: H(0x00 || leaf_data)."""
    return _sha256(b"\x00" + entry_data)


def _node_hash(left: str, right: str) -> str:
    """RFC 6962 §2.1: H(0x01 || left || right)."""
    return _sha256(b"\x01" + bytes.fromhex(left) + bytes.fromhex(right))


def compute_merkle_root(leaf_hashes: list[str]) -> str:
    """Compute Merkle tree root from ordered leaf hashes."""
    if not leaf_hashes:
        return _sha256(b"")
    nodes = list(leaf_hashes)
    while len(nodes) > 1:
        next_level = []
        for i in range(0, len(nodes), 2):
            if i + 1 < len(nodes):
                next_level.append(_node_hash(nodes[i], nodes[i + 1]))
            else:
                next_level.append(nodes[i])
        nodes = next_level
    return nodes[0]


def _hmac_sign(payload: str) -> str:
    """HMAC-SHA256 sign using the app's master key."""
    return _hmac.new(
        settings.CERT_MASTER_KEY[:32].encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()


def generate_sct(cert_der_hash: str, log_index: int, timestamp: datetime) -> dict:
    """Generate a Signed Certificate Timestamp."""
    ts_ms = int(timestamp.timestamp() * 1000)
    log_id = _sha256(settings.CERT_MASTER_KEY[:16].encode())
    sig_payload = f"{log_id}|{ts_ms}|{cert_der_hash}"
    signature = _hmac_sign(sig_payload)

    return {
        "version": 1,
        "log_id": log_id,
        "timestamp": ts_ms,
        "log_index": log_index,
        "signature": signature,
    }


async def submit_to_ct_log(
    db: AsyncSession,
    cert_pem: str,
    cert_serial: str,
    issuer_ca_id: str | None,
    tenant_id: str,
) -> dict:
    """Submit a certificate to the internal CT log. Returns the SCT."""
    cert_obj = x509.load_pem_x509_certificate(cert_pem.encode())
    cert_der = cert_obj.public_bytes(Encoding.DER)
    cert_der_hash = _sha256(cert_der)

    cn = ""
    cn_attrs = cert_obj.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
    if cn_attrs:
        cn = cn_attrs[0].value

    sans = []
    try:
        san_ext = cert_obj.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        for dns in san_ext.value.get_values_for_type(x509.DNSName):
            sans.append({"type": "dns", "value": dns})
        for ip in san_ext.value.get_values_for_type(x509.IPAddress):
            sans.append({"type": "ip", "value": str(ip)})
    except x509.ExtensionNotFound:
        pass

    # Get next log index
    result = await db.execute(select(func.max(CTLogEntry.log_index)))
    max_idx = result.scalar() or 0
    next_index = max_idx + 1

    now = datetime.now(timezone.utc)

    # Compute leaf hash — use naive UTC for consistent hashing (SQLite strips tz)
    now_naive = now.replace(tzinfo=None)
    entry_data = f"{next_index}|{now_naive.isoformat()}|{cert_der_hash}|{cert_serial}".encode()
    leaf = _leaf_hash(entry_data)

    # Generate SCT
    sct = generate_sct(cert_der_hash, next_index, now)

    entry = CTLogEntry(
        log_index=next_index,
        cert_serial=cert_serial,
        cert_der_hash=cert_der_hash,
        issuer_ca_id=issuer_ca_id,
        subject_cn=cn,
        san_json=json.dumps(sans),
        leaf_hash=leaf,
        timestamp=now,
        sct_json=json.dumps(sct),
        tenant_id=tenant_id,
    )
    db.add(entry)

    return sct


async def get_tree_head(db: AsyncSession) -> dict:
    """Compute and return the current Signed Tree Head."""
    result = await db.execute(
        select(CTLogEntry.leaf_hash).order_by(CTLogEntry.log_index)
    )
    leaves = [row[0] for row in result.all()]

    tree_size = len(leaves)
    root_hash = compute_merkle_root(leaves) if leaves else _sha256(b"")
    now = datetime.now(timezone.utc)
    ts_str = now.isoformat()
    signature = _hmac_sign(f"{tree_size}|{ts_str}|{root_hash}")

    return {
        "tree_size": tree_size,
        "root_hash": root_hash,
        "timestamp": ts_str,
        "signature": signature,
    }


async def verify_tree_consistency(db: AsyncSession) -> dict:
    """Verify the Merkle tree is consistent (no gaps, valid leaf hashes)."""
    result = await db.execute(
        select(CTLogEntry).order_by(CTLogEntry.log_index)
    )
    entries = result.scalars().all()

    issues = []
    expected_index = 1

    for entry in entries:
        if entry.log_index != expected_index:
            issues.append(f"Gap at index {expected_index} (found {entry.log_index})")
        expected_index = entry.log_index + 1

    # Verify leaf hashes
    for entry in entries:
        # SQLite stores naive datetimes; ensure consistent format for hash
        ts = entry.timestamp
        if ts.tzinfo is not None:
            ts = ts.replace(tzinfo=None)
        ts_iso = ts.isoformat()
        entry_data = f"{entry.log_index}|{ts_iso}|{entry.cert_der_hash}|{entry.cert_serial}".encode()
        expected_leaf = _leaf_hash(entry_data)
        if entry.leaf_hash != expected_leaf:
            issues.append(f"Leaf hash mismatch at index {entry.log_index}")

    # Compute root
    leaves = [e.leaf_hash for e in entries]
    computed_root = compute_merkle_root(leaves) if leaves else _sha256(b"")

    # Compare with last stored tree head
    last_head_result = await db.execute(
        select(CTTreeHead).order_by(desc(CTTreeHead.timestamp)).limit(1)
    )
    stored_head = last_head_result.scalar_one_or_none()

    root_matches = True
    if stored_head and stored_head.tree_size == len(entries):
        if stored_head.root_hash != computed_root:
            issues.append("Root hash does not match stored tree head — possible tampering")
            root_matches = False

    return {
        "total_entries": len(entries),
        "computed_root": computed_root,
        "issues": issues,
        "consistent": len(issues) == 0,
        "root_matches_stored": root_matches,
    }


async def detect_anomalies(db: AsyncSession, tenant_id: str | None = None) -> list[dict]:
    """Detect anomalous certificates in the CT log."""
    from app.models.ca import CertificateAuthority

    alerts = []

    query = select(CTLogEntry).order_by(desc(CTLogEntry.timestamp)).limit(500)
    if tenant_id:
        query = query.where(CTLogEntry.tenant_id == tenant_id)

    result = await db.execute(query)
    entries = result.scalars().all()

    # Wildcard certs
    for entry in entries:
        if entry.subject_cn.startswith("*."):
            alerts.append({
                "type": "wildcard_cert",
                "severity": "medium",
                "log_index": entry.log_index,
                "cert_serial": entry.cert_serial,
                "subject_cn": entry.subject_cn,
                "timestamp": entry.timestamp.isoformat(),
                "message": f"Wildcard certificate issued: {entry.subject_cn}",
            })

    # Certs from unknown CAs
    ca_ids_result = await db.execute(select(CertificateAuthority.id))
    known_ca_ids = {row[0] for row in ca_ids_result.all()}

    for entry in entries:
        if entry.issuer_ca_id and entry.issuer_ca_id not in known_ca_ids:
            alerts.append({
                "type": "unknown_issuer",
                "severity": "high",
                "log_index": entry.log_index,
                "cert_serial": entry.cert_serial,
                "subject_cn": entry.subject_cn,
                "timestamp": entry.timestamp.isoformat(),
                "message": f"Certificate issued by unknown CA: {entry.issuer_ca_id}",
            })

    return alerts
