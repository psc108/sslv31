"""Structured View category rules API — Improvements Plan Stage 13.

CRUD for the heading -> category badge mapping StructuredView.tsx uses to
render Structured View. Global, not tenant-scoped (see CategoryRule's own
docstring in app/models/docs.py) — every authenticated role can read the
list (every viewer needs it to render), only admins can change it, since a
bad pattern affects every tenant's rendering at once.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import AuthContext, require_role
from app.services.audit import audit_event
from app.models.docs import CategoryRule

router = APIRouter(prefix="/api/v1/category-rules", tags=["category-rules"])

_READ_ROLES = ("admin", "operator", "auditor", "readonly")
_WRITE_ROLES = ("admin",)


def _validate_pattern(pattern: str) -> str:
    try:
        re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        raise HTTPException(status_code=422, detail=f"Invalid regular expression: {e}")
    return pattern


class CategoryRuleCreate(BaseModel):
    pattern: str = Field(min_length=1, max_length=256)
    label: str = Field(min_length=1, max_length=32)
    # Defaults to "after everything else" — appended at the end of the
    # existing match order, matching how the old hardcoded array grew.
    sort_order: int | None = None

    @field_validator("pattern")
    @classmethod
    def _check_pattern(cls, v: str) -> str:
        return _validate_pattern(v)


class CategoryRuleUpdate(BaseModel):
    pattern: str | None = Field(default=None, min_length=1, max_length=256)
    label: str | None = Field(default=None, min_length=1, max_length=32)
    sort_order: int | None = None

    @field_validator("pattern")
    @classmethod
    def _check_pattern(cls, v: str | None) -> str | None:
        return _validate_pattern(v) if v is not None else v


def _rule_dict(r: CategoryRule) -> dict[str, Any]:
    return {
        "id": r.id, "pattern": r.pattern, "label": r.label, "sort_order": r.sort_order,
        "created_by": r.created_by, "created_at": r.created_at.isoformat(),
    }


@router.get("")
async def list_category_rules(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_READ_ROLES)),
) -> list[dict[str, Any]]:
    rows = (await db.execute(select(CategoryRule).order_by(CategoryRule.sort_order))).scalars().all()
    return [_rule_dict(r) for r in rows]


@router.post("", status_code=201)
async def create_category_rule(
    body: CategoryRuleCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> dict[str, Any]:
    sort_order = body.sort_order
    if sort_order is None:
        max_order = (await db.execute(select(func.max(CategoryRule.sort_order)))).scalar()
        sort_order = (max_order or 0) + 1

    rule = CategoryRule(pattern=body.pattern, label=body.label, sort_order=sort_order, created_by=auth.username)
    db.add(rule)
    await db.flush()
    await audit_event(
        db=db, event_type="CATEGORY_RULE_CREATED", severity="INFO", request=request,
        subject_type="category_rule", subject_id=rule.id,
        detail={"pattern": rule.pattern, "label": rule.label}, description=f"Category rule created: {rule.label}",
    )
    await db.commit()
    return _rule_dict(rule)


async def _get_rule_or_404(db: AsyncSession, rule_id: str) -> CategoryRule:
    rule = (await db.execute(select(CategoryRule).where(CategoryRule.id == rule_id))).scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Category rule not found")
    return rule


@router.patch("/{rule_id}")
async def update_category_rule(
    rule_id: str,
    body: CategoryRuleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> dict[str, Any]:
    rule = await _get_rule_or_404(db, rule_id)
    if body.pattern is not None:
        rule.pattern = body.pattern
    if body.label is not None:
        rule.label = body.label
    if body.sort_order is not None:
        rule.sort_order = body.sort_order
    await audit_event(
        db=db, event_type="CATEGORY_RULE_UPDATED", severity="INFO", request=request,
        subject_type="category_rule", subject_id=rule.id,
        detail={"pattern": rule.pattern, "label": rule.label}, description=f"Category rule updated: {rule.label}",
    )
    await db.commit()
    await db.refresh(rule)
    return _rule_dict(rule)


@router.delete("/{rule_id}", status_code=204)
async def delete_category_rule(
    rule_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> None:
    rule = await _get_rule_or_404(db, rule_id)
    await audit_event(
        db=db, event_type="CATEGORY_RULE_DELETED", severity="WARNING", request=request,
        subject_type="category_rule", subject_id=rule.id,
        detail={"pattern": rule.pattern, "label": rule.label}, description=f"Category rule deleted: {rule.label}",
    )
    await db.delete(rule)
    await db.commit()
