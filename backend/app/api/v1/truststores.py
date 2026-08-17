"""TrustStore endpoints — build and download Java truststores."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_api_key
from app.models.ca import CertificateAuthority
from app.models.truststore import TrustStore
from app.api.v1.schemas import TrustStoreCreateRequest, TrustStoreResponse
from app.services.keytool_wrapper import KeytoolWrapper, KeytoolError
from app.services.audit import audit_event

router = APIRouter(prefix="/api/v1/truststore", tags=["TrustStores"])
keytool = KeytoolWrapper()


@router.post("", response_model=TrustStoreResponse, status_code=201)
async def create_truststore(
    body: TrustStoreCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> TrustStoreResponse:
    if not keytool.available:
        raise HTTPException(status_code=503, detail="keytool not available. Install JDK 17.")

    if body.store_type == "JKS" and len(body.password) < 12:
        raise HTTPException(status_code=422, detail="JKS password must be at least 12 characters")

    # Load CA certificates
    ca_certs: list[tuple[str, bytes]] = []
    for ca_id in body.ca_ids:
        ca = await db.get(CertificateAuthority, ca_id)
        if not ca:
            raise HTTPException(status_code=404, detail=f"CA not found: {ca_id}")
        alias = ca.cn.lower().replace(" ", "-").replace(".", "-")
        ca_certs.append((alias, ca.cert_pem.encode()))

    # Build truststore
    try:
        store_bytes = keytool.create_truststore(
            ca_certs=ca_certs,
            password=body.password,
            store_type=body.store_type,
        )
    except KeytoolError as e:
        raise HTTPException(status_code=500, detail=f"TrustStore generation failed: {e}")

    # Verify
    try:
        keytool.verify_store(store_bytes, body.password, body.store_type)
    except KeytoolError as e:
        raise HTTPException(status_code=500, detail=f"TrustStore verification failed: {e}")

    # Persist
    ts = TrustStore(
        name=body.name,
        store_type=body.store_type,
        ca_ids_json=json.dumps(body.ca_ids),
        blob=store_bytes,
    )
    db.add(ts)

    await audit_event(
        db=db,
        event_type="TRUSTSTORE_CREATED",
        severity="INFO",
        request=request,
        subject_type="truststore",
        subject_id=ts.id,
        detail={"name": body.name, "store_type": body.store_type, "ca_count": len(body.ca_ids)},
        description=f"TrustStore created: {body.name} ({body.store_type})",
    )

    await db.commit()
    await db.refresh(ts)

    return TrustStoreResponse(
        id=ts.id,
        name=ts.name,
        store_type=ts.store_type,
        ca_ids_json=ts.ca_ids_json,
        created_at=ts.created_at,
    )


@router.get("/{truststore_id}")
async def download_truststore(
    truststore_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> Response:
    ts = await db.get(TrustStore, truststore_id)
    if not ts:
        raise HTTPException(status_code=404, detail="TrustStore not found")

    ext = ".jks" if ts.store_type == "JKS" else ".p12"
    filename = f"{ts.name}{ext}"

    await audit_event(
        db=db,
        event_type="TRUSTSTORE_DOWNLOAD",
        severity="INFO",
        request=request,
        subject_type="truststore",
        subject_id=truststore_id,
        detail={"store_type": ts.store_type},
    )
    await db.commit()

    return Response(
        content=ts.blob,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
