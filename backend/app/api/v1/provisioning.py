"""Environment Provisioning — API endpoints."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import AuthContext, require_permission
from app.models.provisioning_template import ProvisioningTemplate
from app.services.audit import audit_event
from app.services.provisioning_engine import (
    CIPHER_PROFILES,
    HostConfig,
    ProvisioningEngine,
    ProvisioningRequest,
)

router = APIRouter(prefix="/api/v1/provisioning", tags=["Provisioning"])


# --- Schemas ---

class HostInput(BaseModel):
    role: str = Field(..., pattern="^(mysql|rabbitmq|keystone|backend|frontend)$")
    fqdn: str = Field(..., min_length=1)
    ip: str = Field(..., min_length=1)


class GenerateRequest(BaseModel):
    env_name: str = Field(..., min_length=1, max_length=64)
    hosts: list[HostInput] = Field(..., min_length=1, max_length=5)
    ssl_passphrase: str = Field(..., min_length=6)
    encryption_key: str = Field(..., min_length=6)
    key_algo: str = Field("RSA", pattern="^(RSA|ECDSA)$")
    key_size: int = Field(2048, ge=2048, le=4096)
    ca_validity_days: int = Field(3650, ge=365, le=7300)
    cert_validity_days: int = Field(365, ge=30, le=3650)
    cipher_profile: str = Field("intermediate", pattern="^(modern|intermediate|legacy)$")
    base_path: str = Field("/opt/scripts/ssl")
    include_nopass: bool = True
    include_snippets: bool = True
    include_scripts: bool = True
    include_readmes: bool = True
    include_quicksetup: bool = True


class TemplateCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = ""
    config: GenerateRequest


class TemplateUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    config: GenerateRequest | None = None


# --- Generate ---

@router.post("/generate")
async def generate_bundle(
    body: GenerateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("provisioning:generate")),
):
    """Generate a complete SSL bundle ZIP for an SSP environment."""
    req = ProvisioningRequest(
        env_name=body.env_name,
        hosts=[HostConfig(role=h.role, fqdn=h.fqdn, ip=h.ip) for h in body.hosts],
        ssl_passphrase=body.ssl_passphrase,
        encryption_key=body.encryption_key,
        key_algo=body.key_algo,
        key_size=body.key_size,
        ca_validity_days=body.ca_validity_days,
        cert_validity_days=body.cert_validity_days,
        cipher_profile=body.cipher_profile,
        base_path=body.base_path,
        include_nopass=body.include_nopass,
        include_snippets=body.include_snippets,
        include_scripts=body.include_scripts,
        include_readmes=body.include_readmes,
        include_quicksetup=body.include_quicksetup,
    )

    try:
        engine = ProvisioningEngine()
        result = engine.generate(req)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

    await audit_event(
        db=db, event_type="PROVISIONING_GENERATED", severity="INFO", request=request,
        subject_type="environment", subject_id=body.env_name,
        description=f"SSL bundle generated: {result.cert_count} certs, {result.keystore_count} keystores",
    )
    await db.commit()

    import io
    return StreamingResponse(
        io.BytesIO(result.zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{body.env_name}-ssl.zip"'},
    )


# --- Cipher Profiles ---

@router.get("/cipher-profiles")
async def get_cipher_profiles(
    auth: AuthContext = Depends(require_permission("provisioning:generate")),
) -> dict:
    """Return available cipher profiles with descriptions."""
    return {"profiles": CIPHER_PROFILES}


# --- Template CRUD ---

@router.get("/templates")
async def list_templates(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("provisioning:generate")),
) -> list[dict]:
    result = await db.execute(
        select(ProvisioningTemplate).order_by(ProvisioningTemplate.name)
    )
    return [_serialize(t) for t in result.scalars().all()]


@router.get("/templates/{template_id}")
async def get_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("provisioning:generate")),
) -> dict:
    t = await _find_template(template_id, db)
    return _serialize(t)


@router.post("/templates", status_code=201)
async def create_template(
    body: TemplateCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("settings:manage")),
) -> dict:
    # Check uniqueness
    existing = await db.execute(
        select(ProvisioningTemplate).where(ProvisioningTemplate.name == body.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Template '{body.name}' already exists")

    t = ProvisioningTemplate(
        name=body.name,
        description=body.description,
        config_json=body.config.model_dump_json(),
        created_by=auth.username,
    )
    db.add(t)

    await audit_event(
        db=db, event_type="PROVISIONING_TEMPLATE_CREATED", severity="INFO", request=request,
        subject_type="provisioning_template", subject_id=body.name,
        description=f"Provisioning template created: {body.name}",
    )
    await db.commit()
    await db.refresh(t)
    return _serialize(t)


@router.put("/templates/{template_id}")
async def update_template(
    template_id: str,
    body: TemplateUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("settings:manage")),
) -> dict:
    t = await _find_template(template_id, db)

    if body.name is not None:
        # Check uniqueness if name changed
        if body.name != t.name:
            dup = await db.execute(
                select(ProvisioningTemplate).where(ProvisioningTemplate.name == body.name)
            )
            if dup.scalar_one_or_none():
                raise HTTPException(status_code=409, detail=f"Template '{body.name}' already exists")
        t.name = body.name
    if body.description is not None:
        t.description = body.description
    if body.config is not None:
        t.config_json = body.config.model_dump_json()

    await audit_event(
        db=db, event_type="PROVISIONING_TEMPLATE_UPDATED", severity="INFO", request=request,
        subject_type="provisioning_template", subject_id=t.name,
        description=f"Provisioning template updated: {t.name}",
    )
    await db.commit()
    await db.refresh(t)
    return _serialize(t)


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("settings:manage")),
) -> dict:
    t = await _find_template(template_id, db)
    name = t.name

    await audit_event(
        db=db, event_type="PROVISIONING_TEMPLATE_DELETED", severity="WARNING", request=request,
        subject_type="provisioning_template", subject_id=name,
        description=f"Provisioning template deleted: {name}",
    )
    await db.delete(t)
    await db.commit()
    return {"status": "deleted", "name": name}


# --- Helpers ---

async def _find_template(template_id: str, db: AsyncSession) -> ProvisioningTemplate:
    t = await db.get(ProvisioningTemplate, template_id)
    if not t:
        result = await db.execute(
            select(ProvisioningTemplate).where(ProvisioningTemplate.name == template_id)
        )
        t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Provisioning template not found")
    return t


def _serialize(t: ProvisioningTemplate) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "description": t.description,
        "config": json.loads(t.config_json),
        "created_by": t.created_by,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }
