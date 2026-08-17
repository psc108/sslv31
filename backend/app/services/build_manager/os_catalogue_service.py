"""Operating System Catalogue service — Enhancement Plan Stage 6.

Mirrors catalogue_service.py's product-catalogue CRUD/seed shape, applied to
base OS instead of products: a family-level entity (BMOSFamily) plus a
specific-version entity (BMOSVersion), admin-only mutation, any-authenticated
read, idempotent seed. Replaces three previously-hardcoded sources of truth
(BMTemplateBuilderPage's 4-tile grid, InventoryPage's OS_TYPES array,
HostCreate.os_type's backend regex).
"""
import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.build_manager import BMHost, BMOSFamily, BMOSVersion, BMTemplateVersion

# The 7 families this app already assumed existed (InventoryPage's old
# hardcoded OS_TYPES, HostCreate's old regex) — seeded as origin='builtin' so
# every pre-Stage-6 host/template keeps resolving to a real catalogue entry.
SEED_FAMILIES: list[dict[str, Any]] = [
    {"name": "ubuntu", "display_name": "Ubuntu", "icon": "🐧", "versions": [
        {"version": "24.04", "display_name": "24.04 LTS", "is_latest": True},
        {"version": "22.04", "display_name": "22.04 LTS", "is_latest": False},
    ]},
    {"name": "debian", "display_name": "Debian", "icon": "🌀", "versions": [
        {"version": "12", "display_name": "12 (Bookworm)", "is_latest": True},
    ]},
    {"name": "rhel", "display_name": "RHEL", "icon": "🎩", "versions": [
        {"version": "9", "display_name": "9", "is_latest": True},
        {"version": "8", "display_name": "8", "is_latest": False},
    ]},
    {"name": "centos", "display_name": "CentOS Stream", "icon": "🎩", "versions": [
        {"version": "9", "display_name": "9", "is_latest": True},
    ]},
    {"name": "almalinux", "display_name": "AlmaLinux", "icon": "🎩", "versions": [
        {"version": "9", "display_name": "9", "is_latest": True},
    ]},
    {"name": "rocky", "display_name": "Rocky Linux", "icon": "🪨", "versions": [
        {"version": "9", "display_name": "9", "is_latest": True},
    ]},
    {"name": "alpine", "display_name": "Alpine", "icon": "🏔️", "versions": [
        {"version": "3.19", "display_name": "3.19", "is_latest": True},
    ]},
]


async def list_families(db: AsyncSession) -> list[dict[str, Any]]:
    result = await db.execute(select(BMOSFamily).options(selectinload(BMOSFamily.versions)).order_by(BMOSFamily.display_name))
    return [_family_to_dict(f) for f in result.scalars().all()]


async def get_family(db: AsyncSession, family_id: str) -> dict[str, Any] | None:
    result = await db.execute(
        select(BMOSFamily).options(selectinload(BMOSFamily.versions)).where(BMOSFamily.id == family_id)
    )
    f = result.scalar_one_or_none()
    return _family_to_dict(f) if f else None


async def family_in_use(db: AsyncSession, family_name: str, version: str | None = None) -> bool:
    """True if any registered host or template spec references this OS family
    (optionally narrowed to one specific version)."""
    host_query = select(BMHost).where(BMHost.os_type == family_name)
    if version is not None:
        host_query = host_query.where(BMHost.os_version == version)
    if (await db.execute(host_query)).scalars().first():
        return True

    tv_result = await db.execute(select(BMTemplateVersion))
    for tv in tv_result.scalars().all():
        spec = json.loads(tv.spec)
        if spec.get("base_os") == family_name and (version is None or spec.get("base_os_version") == version):
            return True
    return False


async def seed_os_catalogue(db: AsyncSession) -> int:
    """Insert the built-in OS families/versions if not already present.
    Idempotent — safe to re-run (e.g. to recover a deleted builtin entry)."""
    added = 0
    for fdata in SEED_FAMILIES:
        existing = await db.execute(select(BMOSFamily).where(BMOSFamily.name == fdata["name"]))
        if existing.scalar_one_or_none():
            continue

        family = BMOSFamily(
            id=str(uuid.uuid4()), name=fdata["name"], display_name=fdata["display_name"],
            icon=fdata["icon"], origin="builtin",
        )
        db.add(family)

        for vdata in fdata["versions"]:
            db.add(BMOSVersion(
                id=str(uuid.uuid4()), os_family_id=family.id,
                version=vdata["version"], display_name=vdata["display_name"],
                is_latest=vdata.get("is_latest", False),
            ))
        added += 1

    if added:
        await db.commit()
    return added


def _family_to_dict(f: BMOSFamily) -> dict[str, Any]:
    return {
        "id": f.id,
        "name": f.name,
        "display_name": f.display_name,
        "icon": f.icon,
        "origin": f.origin,
        "versions": [_version_to_dict(v) for v in f.versions],
        "created_at": f.created_at.isoformat() if f.created_at else None,
    }


def _version_to_dict(v: BMOSVersion) -> dict[str, Any]:
    return {
        "id": v.id,
        "os_family_id": v.os_family_id,
        "version": v.version,
        "display_name": v.display_name,
        "eol_date": v.eol_date,
        "is_latest": v.is_latest,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }
