"""CRL endpoint — generate and serve Certificate Revocation Lists."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_api_key
from app.models.ca import CertificateAuthority
from app.models.certificate import Certificate
from app.services.crypto_engine import CryptoEngine
from app.services.audit import audit_event

router = APIRouter(prefix="/api/v1/crl", tags=["CRL"])
crypto = CryptoEngine()


@router.get("/{ca_id}")
async def get_crl(
    ca_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> Response:
    ca = await db.get(CertificateAuthority, ca_id)
    if not ca:
        raise HTTPException(status_code=404, detail="CA not found")

    # Load CA key
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography import x509 as cx509

    ca_key_pem = crypto.decrypt_key_blob(ca.key_blob, settings.CERT_MASTER_KEY)
    ca_key = load_pem_private_key(ca_key_pem, password=None)
    ca_cert = cx509.load_pem_x509_certificate(ca.cert_pem.encode())

    # Get all revoked certs for this CA
    result = await db.execute(
        select(Certificate).where(
            Certificate.signing_ca_id == ca_id,
            Certificate.status == "revoked",
        )
    )
    revoked_certs = result.scalars().all()

    revoked_entries: list[tuple[int, datetime]] = []
    for cert in revoked_certs:
        serial_int = int(cert.serial, 16)
        revoked_at = cert.revoked_at or cert.created_at
        revoked_entries.append((serial_int, revoked_at))

    # Generate CRL
    crl_der = crypto.generate_crl(
        ca_cert=ca_cert,
        ca_key=ca_key,
        revoked_entries=revoked_entries,
    )

    await audit_event(
        db=db,
        event_type="CRL_DOWNLOAD",
        severity="INFO",
        request=request,
        subject_type="ca",
        subject_id=ca_id,
        detail={"revoked_count": len(revoked_entries)},
    )
    await db.commit()

    return Response(
        content=crl_der,
        media_type="application/pkix-crl",
        headers={"Content-Disposition": f'attachment; filename="{ca.cn}-crl.der"'},
    )
