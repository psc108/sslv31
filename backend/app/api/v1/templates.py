"""Certificate Templates — CRUD and enforcement."""

import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_api_key, require_permission, AuthContext
from app.models.template import CertificateTemplate
from app.services.audit import audit_event

router = APIRouter(prefix="/api/v1/templates", tags=["Templates"])


# --- Schemas ---

class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, pattern="^[a-z0-9-]+$")
    display_name: str = Field(..., min_length=1, max_length=128)
    description: str = ""
    allowed_key_algos: list[str] = ["RSA", "ECDSA", "Ed25519"]
    min_key_size: int = Field(2048, ge=1024, le=8192)
    max_validity_days: int = Field(398, ge=1, le=7300)
    allowed_san_types: list[str] = ["dns", "ip", "email", "uri"]
    require_san: bool = False
    key_usage: list[str] = []
    extended_key_usage: list[str] = []
    allowed_cn_pattern: str = ""
    require_org: bool = False
    require_approval: bool = False
    escrow_key: bool = False


class TemplateUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    allowed_key_algos: list[str] | None = None
    min_key_size: int | None = Field(None, ge=1024, le=8192)
    max_validity_days: int | None = Field(None, ge=1, le=7300)
    allowed_san_types: list[str] | None = None
    require_san: bool | None = None
    key_usage: list[str] | None = None
    extended_key_usage: list[str] | None = None
    allowed_cn_pattern: str | None = None
    require_org: bool | None = None
    require_approval: bool | None = None
    escrow_key: bool | None = None


# --- Endpoints ---

@router.get("")
async def list_templates(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> list[dict]:
    result = await db.execute(
        select(CertificateTemplate).order_by(CertificateTemplate.is_builtin.desc(), CertificateTemplate.name)
    )
    templates = result.scalars().all()
    return [_serialize(t) for t in templates]


@router.get("/{template_id}")
async def get_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> dict:
    t = await db.get(CertificateTemplate, template_id)
    if not t:
        # Try by name
        result = await db.execute(
            select(CertificateTemplate).where(CertificateTemplate.name == template_id)
        )
        t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    return _serialize(t)


@router.post("", status_code=201)
async def create_template(
    body: TemplateCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("templates:manage")),
) -> dict:
    # Check name uniqueness
    existing = await db.execute(
        select(CertificateTemplate).where(CertificateTemplate.name == body.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Template '{body.name}' already exists")

    template = CertificateTemplate(
        name=body.name,
        display_name=body.display_name,
        description=body.description,
        allowed_key_algos=json.dumps(body.allowed_key_algos),
        min_key_size=body.min_key_size,
        max_validity_days=body.max_validity_days,
        allowed_san_types=json.dumps(body.allowed_san_types),
        require_san=body.require_san,
        key_usage=json.dumps(body.key_usage),
        extended_key_usage=json.dumps(body.extended_key_usage),
        allowed_cn_pattern=body.allowed_cn_pattern,
        require_org=body.require_org,
        require_approval=body.require_approval,
        escrow_key=body.escrow_key,
        is_builtin=False,
    )
    db.add(template)

    await audit_event(
        db=db, event_type="TEMPLATE_CREATED", severity="INFO", request=request,
        subject_type="template", subject_id=body.name,
        description=f"Certificate template created: {body.display_name}",
    )
    await db.commit()
    await db.refresh(template)
    return _serialize(template)


@router.put("/{template_id}")
async def update_template(
    template_id: str,
    body: TemplateUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("templates:manage")),
) -> dict:
    t = await db.get(CertificateTemplate, template_id)
    if not t:
        result = await db.execute(
            select(CertificateTemplate).where(CertificateTemplate.name == template_id)
        )
        t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")

    if body.display_name is not None:
        t.display_name = body.display_name
    if body.description is not None:
        t.description = body.description
    if body.allowed_key_algos is not None:
        t.allowed_key_algos = json.dumps(body.allowed_key_algos)
    if body.min_key_size is not None:
        t.min_key_size = body.min_key_size
    if body.max_validity_days is not None:
        t.max_validity_days = body.max_validity_days
    if body.allowed_san_types is not None:
        t.allowed_san_types = json.dumps(body.allowed_san_types)
    if body.require_san is not None:
        t.require_san = body.require_san
    if body.key_usage is not None:
        t.key_usage = json.dumps(body.key_usage)
    if body.extended_key_usage is not None:
        t.extended_key_usage = json.dumps(body.extended_key_usage)
    if body.allowed_cn_pattern is not None:
        t.allowed_cn_pattern = body.allowed_cn_pattern
    if body.require_org is not None:
        t.require_org = body.require_org
    if body.require_approval is not None:
        t.require_approval = body.require_approval
    if body.escrow_key is not None:
        t.escrow_key = body.escrow_key

    await audit_event(
        db=db, event_type="TEMPLATE_UPDATED", severity="INFO", request=request,
        subject_type="template", subject_id=t.name,
        description=f"Certificate template updated: {t.display_name}",
    )
    await db.commit()
    await db.refresh(t)
    return _serialize(t)


@router.delete("/{template_id}")
async def delete_template(
    template_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("templates:manage")),
) -> dict:
    t = await db.get(CertificateTemplate, template_id)
    if not t:
        result = await db.execute(
            select(CertificateTemplate).where(CertificateTemplate.name == template_id)
        )
        t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    if t.is_builtin:
        raise HTTPException(status_code=403, detail="Cannot delete built-in templates")

    await audit_event(
        db=db, event_type="TEMPLATE_DELETED", severity="WARNING", request=request,
        subject_type="template", subject_id=t.name,
        description=f"Certificate template deleted: {t.display_name}",
    )
    await db.delete(t)
    await db.commit()
    return {"status": "deleted", "name": t.name}


# --- Enforcement ---

async def enforce_template(
    template_name: str,
    key_algo: str,
    key_size: int,
    validity_days: int,
    san_list: list[dict],
    subject_cn: str,
    subject_o: str,
    db: AsyncSession,
) -> None:
    """Validate request against template constraints. Raises HTTPException on violation."""
    result = await db.execute(
        select(CertificateTemplate).where(CertificateTemplate.name == template_name)
    )
    template = result.scalar_one_or_none()
    if not template:
        return  # No template = no enforcement

    errors: list[str] = []

    # Key algorithm
    allowed_algos = json.loads(template.allowed_key_algos)
    if key_algo not in allowed_algos:
        errors.append(f"Key algorithm '{key_algo}' not allowed. Permitted: {allowed_algos}")

    # Key size
    if key_algo == "RSA" and key_size < template.min_key_size:
        errors.append(f"Key size {key_size} below minimum {template.min_key_size}")

    # Validity
    if validity_days > template.max_validity_days:
        errors.append(f"Validity {validity_days} days exceeds template maximum of {template.max_validity_days} days")

    # SAN requirement
    if template.require_san and not san_list:
        errors.append("Template requires at least one SAN entry")

    # SAN types
    allowed_san_types = json.loads(template.allowed_san_types)
    if allowed_san_types:
        for san in san_list:
            san_type = san.get("type", san.get("type", ""))
            if san_type not in allowed_san_types:
                errors.append(f"SAN type '{san_type}' not allowed. Permitted: {allowed_san_types}")
                break

    # CN pattern
    if template.allowed_cn_pattern:
        try:
            if not re.match(template.allowed_cn_pattern, subject_cn):
                errors.append(f"CN '{subject_cn}' does not match required pattern: {template.allowed_cn_pattern}")
        except re.error:
            pass  # Invalid regex in template — skip

    # Organisation required
    if template.require_org and not subject_o:
        errors.append("Template requires Organisation (O) field")

    if errors:
        raise HTTPException(status_code=422, detail={"template_violations": errors})


# --- Helpers ---

def _serialize(t: CertificateTemplate) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "display_name": t.display_name,
        "description": t.description,
        "allowed_key_algos": json.loads(t.allowed_key_algos),
        "min_key_size": t.min_key_size,
        "max_validity_days": t.max_validity_days,
        "allowed_san_types": json.loads(t.allowed_san_types),
        "require_san": t.require_san,
        "key_usage": json.loads(t.key_usage),
        "extended_key_usage": json.loads(t.extended_key_usage),
        "allowed_cn_pattern": t.allowed_cn_pattern,
        "require_org": t.require_org,
        "require_approval": t.require_approval,
        "escrow_key": t.escrow_key,
        "is_builtin": t.is_builtin,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }
