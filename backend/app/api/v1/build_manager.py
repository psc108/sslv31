"""Build Manager API — Inventory, Templates, Environments, Jobs."""

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import StreamingResponse, Response, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import AuthContext, require_role
from app.models.build_manager import (
    BMHost, BMHostGroup, BMHostGroupMember, BMHostVar,
    BMTemplate, BMTemplateVersion, BMEnvironment, BMEnvironmentCert,
    BMJob, BMJobLog, BMProduct, BMProductVersion, BMProductConfig,
    BMNetworkPool, BMCertBinding, BMSecret, BMHealthCheck, BMConfigFile, BMConfigFileVersion,
    BMOSFamily, BMOSVersion,
)
from app.models.bug_tracker import Bug
from app.services.audit import audit_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/build", tags=["build-manager"])


# --- Schemas ---

class HostCreate(BaseModel):
    hostname: str = Field(..., min_length=1, max_length=255)
    ip: str = Field(..., min_length=1, max_length=45)
    connection_type: str = Field(default="docker", pattern="^(docker|ssh)$")
    container_name: str = Field(default="")
    port: int = Field(default=22, ge=1, le=65535)
    ssh_user: str = Field(default="root", max_length=64)
    # No longer a fixed enum — admins can add their own OS family via the
    # catalogue (Enhancement Plan Stage 6), so the backend can't hardcode
    # the valid set at deploy time. Matches HostUpdate.os_type, which never
    # had this restriction (a pre-existing inconsistency this closes).
    os_type: str = Field(default="ubuntu", max_length=32)  # matches BMHost.os_type's column width
    os_version: str = Field(default="24.04", max_length=32)
    service_role: str = Field(default="generic", pattern="^(frontend|backend|mysql|rabbitmq|keystone|generic)$")
    tags: str = Field(default="")
    group_ids: list[str] = Field(default_factory=list)
    ssh_auth_method: str = Field(default="shared_key", pattern="^(shared_key|private_key|password)$")
    ssh_credential: str | None = Field(default=None, description="Private key PEM or password — encrypted at rest, never returned by the API")


class HostUpdate(BaseModel):
    hostname: str | None = None
    ip: str | None = None
    connection_type: str | None = None
    container_name: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    ssh_user: str | None = None
    os_type: str | None = None
    os_version: str | None = None
    service_role: str | None = None
    tags: str | None = None
    group_ids: list[str] | None = None
    ssh_auth_method: str | None = Field(default=None, pattern="^(shared_key|private_key|password)$")
    ssh_credential: str | None = Field(default=None, description="Private key PEM or password — encrypted at rest, never returned by the API; omit to leave unchanged")


class HostVarSet(BaseModel):
    key: str = Field(..., min_length=1, max_length=128)
    value: str = Field(default="")
    encrypted: bool = False


class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="")


class GroupUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


# --- Host Endpoints ---

@router.get("/hosts")
async def list_hosts(
    group: str | None = Query(None),
    tag: str | None = Query(None),
    service_role: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> list[dict[str, Any]]:
    query = select(BMHost).options(
        selectinload(BMHost.group_memberships).selectinload(BMHostGroupMember.group)
    )
    if tag:
        query = query.where(BMHost.tags.contains(tag))
    if service_role:
        query = query.where(BMHost.service_role == service_role)

    result = await db.execute(query)
    hosts = result.scalars().all()

    # Filter by group if specified
    if group:
        grp = await db.execute(select(BMHostGroup).where(BMHostGroup.name == group))
        grp_obj = grp.scalar_one_or_none()
        if not grp_obj:
            return []
        members = await db.execute(
            select(BMHostGroupMember.host_id).where(BMHostGroupMember.group_id == grp_obj.id)
        )
        member_ids = {r[0] for r in members.all()}
        hosts = [h for h in hosts if h.id in member_ids]

    return [_host_to_dict(h) for h in hosts]


@router.post("/hosts", status_code=201)
async def create_host(
    body: HostCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    from app.services.build_manager.secrets_service import encrypt_value

    host = BMHost(
        id=str(uuid.uuid4()),
        hostname=body.hostname,
        ip=body.ip,
        connection_type=body.connection_type,
        container_name=body.container_name,
        port=body.port,
        ssh_user=body.ssh_user,
        os_type=body.os_type,
        os_version=body.os_version,
        service_role=body.service_role,
        tags=body.tags,
        tenant_id=auth.tenant_id,
        ssh_auth_method=body.ssh_auth_method,
        ssh_credential_encrypted=encrypt_value(body.ssh_credential) if body.ssh_credential else None,
    )
    db.add(host)

    # Add to groups
    for gid in body.group_ids:
        db.add(BMHostGroupMember(host_id=host.id, group_id=gid))

    await audit_event(
        db=db, event_type="BM_HOST_CREATED", severity="INFO", request=request,
        subject_type="bm_host", subject_id=host.id,
        detail={"hostname": host.hostname, "connection_type": host.connection_type, "ssh_auth_method": host.ssh_auth_method},
        description=f"Build Manager host created: {host.hostname}",
    )
    await db.commit()

    # Re-fetch with relationships loaded
    return await get_host(host.id, db, auth)


@router.get("/hosts/{host_id}")
async def get_host(
    host_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    host = await _get_host_or_404(db, host_id)
    return _host_to_dict(host)


@router.put("/hosts/{host_id}")
async def update_host(
    host_id: str,
    body: HostUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    host = await _get_host_or_404(db, host_id)

    for field in ("hostname", "ip", "connection_type", "container_name", "port", "ssh_user", "os_type", "os_version", "service_role", "tags"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(host, field, val)

    if body.ssh_auth_method is not None:
        host.ssh_auth_method = body.ssh_auth_method
        if body.ssh_auth_method == "shared_key":
            host.ssh_credential_encrypted = None
    if body.ssh_credential is not None:
        from app.services.build_manager.secrets_service import encrypt_value
        host.ssh_credential_encrypted = encrypt_value(body.ssh_credential)

    if body.group_ids is not None:
        await db.execute(delete(BMHostGroupMember).where(BMHostGroupMember.host_id == host_id))
        for gid in body.group_ids:
            db.add(BMHostGroupMember(host_id=host_id, group_id=gid))

    await audit_event(
        db=db, event_type="BM_HOST_UPDATED", severity="INFO", request=request,
        subject_type="bm_host", subject_id=host_id,
        detail={"hostname": host.hostname},
        description=f"Build Manager host updated: {host.hostname}",
    )
    await db.commit()

    # Re-fetch with relationships loaded
    return await get_host(host_id, db, auth)


@router.delete("/hosts/{host_id}", status_code=204)
async def delete_host(
    host_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> None:
    host = await _get_host_or_404(db, host_id)
    await audit_event(
        db=db, event_type="BM_HOST_DELETED", severity="WARNING", request=request,
        subject_type="bm_host", subject_id=host_id,
        detail={"hostname": host.hostname},
        description=f"Build Manager host deleted: {host.hostname}",
    )
    await db.delete(host)
    await db.commit()


@router.post("/hosts/{host_id}/test")
async def test_host_connectivity(
    host_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    host = await _get_host_or_404(db, host_id)

    from app.services.build_manager import test_ssh_connectivity
    result = await test_ssh_connectivity(
        host.ip, host.port, host.ssh_user,
        auth_method=host.ssh_auth_method, credential_encrypted=host.ssh_credential_encrypted,
    )

    # Host-key verification (TOFU pinning, Enhancement Plan Stage 9) — only
    # meaningful for registered SSH-type hosts; Docker-hosted containers are
    # recreated fresh on every build and have no stable identity to pin.
    host_key_ok, host_key_message = True, None
    if result.success and host.connection_type == "ssh":
        from app.services.build_manager.host_key_service import verify_or_pin_host_key
        host_key_ok, host_key_message = await verify_or_pin_host_key(db, host)

    overall_success = result.success and host_key_ok

    # Update host status
    host.status = "online" if overall_success else "offline"
    if overall_success:
        host.last_seen = datetime.now(timezone.utc)
    await db.commit()

    return {
        "host_id": host_id,
        "hostname": host.hostname,
        "success": overall_success,
        "message": host_key_message if (result.success and not host_key_ok) else result.message,
        "latency_ms": result.latency_ms,
        "host_key_fingerprint": result.host_key_fingerprint,
        "host_key_status": host_key_message,
    }


@router.post("/hosts/{host_id}/accept-host-key")
async def accept_host_key(
    host_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Explicitly re-pin a host to its currently-observed SSH host key
    (Enhancement Plan Stage 9) — used once a changed key has been confirmed
    legitimate out-of-band, e.g. the host was reinstalled. Admin-only since
    this overrides a security block."""
    host = await _get_host_or_404(db, host_id)
    if host.connection_type != "ssh":
        raise HTTPException(status_code=422, detail="Host key pinning only applies to SSH-type hosts")

    from app.services.build_manager.host_key_service import accept_new_host_key
    try:
        new_key = await accept_new_host_key(db, host)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    await audit_event(
        db=db, event_type="BM_HOST_KEY_ACCEPTED", severity="WARNING", request=request,
        subject_type="bm_host", subject_id=host_id,
        detail={"hostname": host.hostname},
        description=f"Build Manager host key re-accepted for: {host.hostname}",
    )
    await db.commit()
    return {"host_id": host_id, "hostname": host.hostname, "pinned_host_key": new_key, "pinned_at": host.host_key_pinned_at.isoformat()}


# --- Host Variables ---

@router.get("/hosts/{host_id}/vars")
async def list_host_vars(
    host_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> list[dict[str, Any]]:
    await _get_host_or_404(db, host_id)
    result = await db.execute(select(BMHostVar).where(BMHostVar.host_id == host_id))
    return [
        {"id": v.id, "key": v.key, "value": "***" if v.encrypted else v.value, "encrypted": v.encrypted}
        for v in result.scalars().all()
    ]


@router.post("/hosts/{host_id}/vars", status_code=201)
async def set_host_var(
    host_id: str,
    body: HostVarSet,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    await _get_host_or_404(db, host_id)
    from app.services.build_manager.secrets_service import encrypt_value
    stored_value = encrypt_value(body.value) if body.encrypted else body.value

    # Upsert
    existing = await db.execute(
        select(BMHostVar).where(BMHostVar.host_id == host_id, BMHostVar.key == body.key)
    )
    var = existing.scalar_one_or_none()
    if var:
        var.value = stored_value
        var.encrypted = body.encrypted
    else:
        var = BMHostVar(id=str(uuid.uuid4()), host_id=host_id, key=body.key, value=stored_value, encrypted=body.encrypted)
        db.add(var)

    # Never log the actual value, even when unencrypted — matching the
    # existing "no secret material in audit detail" discipline.
    await audit_event(
        db=db, event_type="BM_HOST_VAR_SET", severity="INFO", request=request,
        subject_type="bm_host_var", subject_id=var.id,
        detail={"host_id": host_id, "key": body.key, "encrypted": body.encrypted},
        description=f"Build Manager host variable '{body.key}' set on host {host_id}",
    )
    await db.commit()
    return {"id": var.id, "key": var.key, "value": "***" if var.encrypted else var.value, "encrypted": var.encrypted}


@router.get("/hosts/{host_id}/vars/{var_key}/reveal")
async def reveal_host_var(
    host_id: str,
    var_key: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Decrypt and return an encrypted host var's real value — admin-only,
    matching the same bar as revealing a secret's plaintext (GET /secrets/{id})."""
    await _get_host_or_404(db, host_id)
    result = await db.execute(
        select(BMHostVar).where(BMHostVar.host_id == host_id, BMHostVar.key == var_key)
    )
    var = result.scalar_one_or_none()
    if not var:
        raise HTTPException(status_code=404, detail="Host variable not found")
    if not var.encrypted:
        return {"id": var.id, "key": var.key, "value": var.value, "encrypted": False}
    from cryptography.fernet import InvalidToken
    from app.services.build_manager.secrets_service import decrypt_value
    try:
        value = decrypt_value(var.value)
    except InvalidToken:
        # Pre-existing row from before this value was actually encrypted at
        # rest (the "encrypted" flag used to be display-only) — the stored
        # value is legacy plaintext, not ciphertext.
        logger.warning("Host var %s on host %s is flagged encrypted but is not valid Fernet ciphertext — returning as legacy plaintext", var_key, host_id)
        value = var.value
    return {"id": var.id, "key": var.key, "value": value, "encrypted": True}


@router.delete("/hosts/{host_id}/vars/{var_key}", status_code=204)
async def delete_host_var(
    host_id: str,
    var_key: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> None:
    await _get_host_or_404(db, host_id)
    await audit_event(
        db=db, event_type="BM_HOST_VAR_DELETED", severity="INFO", request=request,
        subject_type="bm_host_var", subject_id=host_id,
        detail={"host_id": host_id, "key": var_key},
        description=f"Build Manager host variable '{var_key}' deleted from host {host_id}",
    )
    await db.execute(delete(BMHostVar).where(BMHostVar.host_id == host_id, BMHostVar.key == var_key))
    await db.commit()


# --- Group Endpoints ---

@router.get("/groups")
async def list_groups(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    result = await db.execute(select(BMHostGroup).options(selectinload(BMHostGroup.members)))
    return [
        {"id": g.id, "name": g.name, "description": g.description, "member_count": len(g.members)}
        for g in result.scalars().all()
    ]


@router.post("/groups", status_code=201)
async def create_group(
    body: GroupCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    group = BMHostGroup(id=str(uuid.uuid4()), name=body.name, description=body.description, tenant_id=auth.tenant_id)
    db.add(group)
    await audit_event(
        db=db, event_type="BM_HOST_GROUP_CREATED", severity="INFO", request=request,
        subject_type="bm_host_group", subject_id=group.id,
        detail={"name": group.name},
        description=f"Build Manager host group created: {group.name}",
    )
    await db.commit()
    return {"id": group.id, "name": group.name, "description": group.description, "member_count": 0}


@router.put("/groups/{group_id}")
async def update_group(
    group_id: str,
    body: GroupUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    result = await db.execute(select(BMHostGroup).where(BMHostGroup.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    if body.name is not None:
        group.name = body.name
    if body.description is not None:
        group.description = body.description
    await audit_event(
        db=db, event_type="BM_HOST_GROUP_UPDATED", severity="INFO", request=request,
        subject_type="bm_host_group", subject_id=group_id,
        detail={"name": group.name},
        description=f"Build Manager host group updated: {group.name}",
    )
    await db.commit()
    return {"id": group.id, "name": group.name, "description": group.description}


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(
    group_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> None:
    result = await db.execute(select(BMHostGroup).where(BMHostGroup.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    await audit_event(
        db=db, event_type="BM_HOST_GROUP_DELETED", severity="WARNING", request=request,
        subject_type="bm_host_group", subject_id=group_id,
        detail={"name": group.name},
        description=f"Build Manager host group deleted: {group.name}",
    )
    await db.delete(group)
    await db.commit()


@router.post("/groups/{group_id}/members", status_code=201)
async def add_group_member(
    group_id: str,
    request: Request,
    host_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, str]:
    # Verify both exist
    await _get_host_or_404(db, host_id)
    grp = await db.execute(select(BMHostGroup).where(BMHostGroup.id == group_id))
    if not grp.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Group not found")

    existing = await db.execute(
        select(BMHostGroupMember).where(
            BMHostGroupMember.host_id == host_id, BMHostGroupMember.group_id == group_id
        )
    )
    if not existing.scalar_one_or_none():
        db.add(BMHostGroupMember(host_id=host_id, group_id=group_id))
        await audit_event(
            db=db, event_type="BM_HOST_GROUP_MEMBER_ADDED", severity="INFO", request=request,
            subject_type="bm_host_group", subject_id=group_id,
            detail={"host_id": host_id},
            description=f"Host {host_id} added to Build Manager group {group_id}",
        )
        await db.commit()
    return {"status": "added"}


@router.delete("/groups/{group_id}/members/{host_id}", status_code=204)
async def remove_group_member(
    group_id: str,
    host_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> None:
    await audit_event(
        db=db, event_type="BM_HOST_GROUP_MEMBER_REMOVED", severity="INFO", request=request,
        subject_type="bm_host_group", subject_id=group_id,
        detail={"host_id": host_id},
        description=f"Host {host_id} removed from Build Manager group {group_id}",
    )
    await db.execute(
        delete(BMHostGroupMember).where(
            BMHostGroupMember.host_id == host_id, BMHostGroupMember.group_id == group_id
        )
    )
    await db.commit()


# --- Inventory Export ---

@router.get("/inventory")
async def get_ansible_inventory(
    group: str | None = Query(None),
    tag: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    from app.services.build_manager.inventory_service import generate_ansible_inventory
    return await generate_ansible_inventory(db, group_name=group, tag=tag)


# --- Network Pools ---

class NetworkPoolCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    cidr: str = Field(..., min_length=1, max_length=45)
    gateway: str = Field(default="")
    dns_servers: str = Field(default="")
    reserved: list[str] = Field(default_factory=list)  # IPs or ranges like "192.168.50.1-192.168.50.5"
    description: str = Field(default="")


class NetworkPoolUpdate(BaseModel):
    name: str | None = None
    cidr: str | None = None
    gateway: str | None = None
    dns_servers: str | None = None
    reserved: list[str] | None = None
    description: str | None = None


@router.get("/network-pools/docker-networks")
async def list_docker_networks(
    auth: AuthContext = Depends(require_role("admin")),
) -> list[dict[str, Any]]:
    """Inspect Docker networks via Engine API (Unix socket)."""
    import httpx

    transport = httpx.AsyncHTTPTransport(uds="/var/run/docker.sock")
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://docker") as client:
            resp = await client.get("/networks", timeout=5)
            if resp.status_code != 200:
                return []
            data = resp.json()
    except Exception:
        logger.exception("Failed to list Docker networks via Engine API")
        return []

    networks = []
    for net in data:
        name = net.get("Name", "")
        ipam_configs = net.get("IPAM", {}).get("Config") or []
        if not ipam_configs:
            continue
        cidr = ipam_configs[0].get("Subnet", "")
        gateway = ipam_configs[0].get("Gateway", "")
        if not cidr:
            continue

        # Extract allocated container IPs
        allocated = []
        for cid, cinfo in (net.get("Containers") or {}).items():
            ipv4 = cinfo.get("IPv4Address", "")
            if ipv4:
                allocated.append(ipv4.split("/")[0])

        networks.append({
            "name": name,
            "cidr": cidr,
            "gateway": gateway,
            "allocated_ips": allocated,
        })

    return networks


@router.post("/network-pools/docker-networks", status_code=201)
async def create_docker_network(
    request: Request,
    name: str = Body(..., min_length=1),
    subnet: str = Body(default=""),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Create a Docker bridge network. If subnet is empty Docker picks one automatically."""
    import httpx

    payload: dict[str, Any] = {
        "Name": name,
        "Driver": "bridge",
        "CheckDuplicate": True,
        "Options": {"com.docker.network.bridge.enable_ip_masquerade": "true"},
    }
    if subnet:
        payload["IPAM"] = {"Driver": "default", "Config": [{"Subnet": subnet}]}

    transport = httpx.AsyncHTTPTransport(uds="/var/run/docker.sock")
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://docker") as client:
            resp = await client.post("/networks/create", json=payload, timeout=10)
            if resp.status_code not in (200, 201):
                detail = resp.json().get("message", resp.text)
                raise HTTPException(status_code=400, detail=detail)
            net_id = resp.json().get("Id", "")
            # Inspect to get auto-assigned gateway/subnet
            insp = await client.get(f"/networks/{net_id}", timeout=5)
            insp.raise_for_status()
            data = insp.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Docker socket error: {exc}")

    ipam_configs = data.get("IPAM", {}).get("Config") or []
    cidr = ipam_configs[0].get("Subnet", "") if ipam_configs else ""
    gateway = ipam_configs[0].get("Gateway", "") if ipam_configs else ""

    await audit_event(
        db=db, event_type="BM_DOCKER_NETWORK_CREATED", severity="INFO", request=request,
        subject_type="docker_network", subject_id=name[:64],
        detail={"name": name, "cidr": cidr},
        description=f"Docker network created via Build Manager: {name}",
    )
    await db.commit()
    return {"name": name, "cidr": cidr, "gateway": gateway, "allocated_ips": []}


@router.get("/network-pools")
async def list_network_pools(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    result = await db.execute(select(BMNetworkPool).order_by(BMNetworkPool.name))
    return [_pool_to_dict(p) for p in result.scalars().all()]


@router.post("/network-pools", status_code=201)
async def create_network_pool(
    body: NetworkPoolCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, Any]:
    import ipaddress
    try:
        ipaddress.ip_network(body.cidr, strict=False)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid CIDR: {body.cidr}")

    pool = BMNetworkPool(
        id=str(uuid.uuid4()),
        name=body.name,
        cidr=body.cidr,
        gateway=body.gateway,
        dns_servers=body.dns_servers,
        reserved=json.dumps(body.reserved),
        description=body.description,
        tenant_id=auth.tenant_id,
    )
    db.add(pool)
    await audit_event(
        db=db, event_type="BM_NETWORK_POOL_CREATED", severity="INFO", request=request,
        subject_type="bm_network_pool", subject_id=pool.id,
        detail={"name": pool.name, "cidr": pool.cidr},
        description=f"Build Manager network pool created: {pool.name}",
    )
    await db.commit()
    return _pool_to_dict(pool)


@router.put("/network-pools/{pool_id}")
async def update_network_pool(
    pool_id: str,
    body: NetworkPoolUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, Any]:
    result = await db.execute(select(BMNetworkPool).where(BMNetworkPool.id == pool_id))
    pool = result.scalar_one_or_none()
    if not pool:
        raise HTTPException(status_code=404, detail="Network pool not found")
    if body.name is not None:
        pool.name = body.name
    if body.cidr is not None:
        import ipaddress
        try:
            ipaddress.ip_network(body.cidr, strict=False)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid CIDR: {body.cidr}")
        pool.cidr = body.cidr
    if body.gateway is not None:
        pool.gateway = body.gateway
    if body.dns_servers is not None:
        pool.dns_servers = body.dns_servers
    if body.reserved is not None:
        pool.reserved = json.dumps(body.reserved)
    if body.description is not None:
        pool.description = body.description
    await audit_event(
        db=db, event_type="BM_NETWORK_POOL_UPDATED", severity="INFO", request=request,
        subject_type="bm_network_pool", subject_id=pool_id,
        detail={"name": pool.name},
        description=f"Build Manager network pool updated: {pool.name}",
    )
    await db.commit()
    return _pool_to_dict(pool)


@router.delete("/network-pools/{pool_id}", status_code=204)
async def delete_network_pool(
    pool_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> None:
    result = await db.execute(select(BMNetworkPool).where(BMNetworkPool.id == pool_id))
    pool = result.scalar_one_or_none()
    if not pool:
        raise HTTPException(status_code=404, detail="Network pool not found")
    await audit_event(
        db=db, event_type="BM_NETWORK_POOL_DELETED", severity="WARNING", request=request,
        subject_type="bm_network_pool", subject_id=pool_id,
        detail={"name": pool.name},
        description=f"Build Manager network pool deleted: {pool.name}",
    )
    await db.delete(pool)
    await db.commit()


@router.get("/network-pools/{pool_id}/available")
async def get_available_ips(
    pool_id: str,
    count: int = Query(default=20, le=100),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Return the next N available IPs from the pool (excluding allocated and reserved)."""
    import ipaddress
    from app.services.build_manager.environment_service import compute_available_pool_ips

    result = await db.execute(select(BMNetworkPool).where(BMNetworkPool.id == pool_id))
    pool = result.scalar_one_or_none()
    if not pool:
        raise HTTPException(status_code=404, detail="Network pool not found")

    network = ipaddress.ip_network(pool.cidr, strict=False)
    reserved_raw = json.loads(pool.reserved) if pool.reserved else []
    reserved_ips = {network.network_address, network.broadcast_address}
    if pool.gateway:
        try:
            reserved_ips.add(ipaddress.ip_address(pool.gateway))
        except ValueError:
            pass
    for entry in reserved_raw:
        if "-" in entry:
            parts = entry.split("-")
            try:
                start = ipaddress.ip_address(parts[0].strip())
                end = ipaddress.ip_address(parts[1].strip())
                current = start
                while current <= end:
                    reserved_ips.add(current)
                    current = ipaddress.ip_address(int(current) + 1)
            except ValueError:
                pass
        else:
            try:
                reserved_ips.add(ipaddress.ip_address(entry.strip()))
            except ValueError:
                pass

    host_result = await db.execute(select(BMHost.ip))
    allocated_ips = set()
    for row in host_result.all():
        try:
            allocated_ips.add(ipaddress.ip_address(row[0]))
        except ValueError:
            pass

    available = await compute_available_pool_ips(db, pool, count)

    return {
        "pool_id": pool_id,
        "pool_name": pool.name,
        "cidr": pool.cidr,
        "gateway": pool.gateway,
        "total_hosts": network.num_addresses - 2,  # minus network + broadcast
        "reserved_count": len(reserved_ips),
        "allocated_count": len(allocated_ips & set(network.hosts())),
        "available": available,
    }


def _pool_to_dict(p: BMNetworkPool) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "cidr": p.cidr,
        "gateway": p.gateway,
        "dns_servers": p.dns_servers,
        "reserved": json.loads(p.reserved) if p.reserved else [],
        "description": p.description,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


# --- SSH Key ---

@router.get("/ssh-key")
async def get_ssh_public_key(
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, Any]:
    from app.services.build_manager import get_public_key, generate_ssh_keypair
    pub = get_public_key()
    if not pub:
        _, pub = await generate_ssh_keypair()
    return {"public_key": pub}


# --- Helpers ---

async def _get_host_or_404(db: AsyncSession, host_id: str) -> BMHost:
    result = await db.execute(
        select(BMHost).options(
            selectinload(BMHost.group_memberships).selectinload(BMHostGroupMember.group)
        ).where(BMHost.id == host_id)
    )
    host = result.scalar_one_or_none()
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")
    return host


def _host_to_dict(host: BMHost) -> dict[str, Any]:
    groups = []
    if host.group_memberships:
        groups = [{"id": m.group_id, "name": m.group.name} for m in host.group_memberships if m.group]
    return {
        "id": host.id,
        "hostname": host.hostname,
        "ip": host.ip,
        "connection_type": host.connection_type,
        "container_name": host.container_name,
        "ansible_host": host.container_name if host.connection_type == "docker" and host.container_name else host.ip,
        "port": host.port,
        "ssh_user": host.ssh_user,
        "os_type": host.os_type,
        "os_version": host.os_version,
        "service_role": host.service_role,
        "tags": host.tags,
        "status": host.status,
        "last_seen": host.last_seen.isoformat() if host.last_seen else None,
        "groups": groups,
        "created_at": host.created_at.isoformat() if host.created_at else None,
        "ssh_auth_method": host.ssh_auth_method,
        "ssh_credential_set": bool(host.ssh_credential_encrypted),
        "host_key_pinned": bool(host.pinned_host_key),
        "host_key_pinned_at": host.host_key_pinned_at.isoformat() if host.host_key_pinned_at else None,
    }


# ============================================================
# TEMPLATES
# ============================================================

class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="")
    tags: str = Field(default="")  # JSON array or comma-separated
    spec: dict = Field(...)
    change_note: str = Field(default="Initial version")


class TemplateUpdate(BaseModel):
    spec: dict = Field(...)
    change_note: str = Field(..., min_length=1)


@router.get("/templates")
async def list_templates(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(BMTemplate).options(selectinload(BMTemplate.versions))
    )
    templates = result.scalars().all()
    out = []
    for t in templates:
        current = next((v for v in t.versions if v.is_current), None)
        out.append({
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "tags": t.tags,
            "origin": t.origin,
            "version_count": len(t.versions),
            "current_version": current.version if current else 0,
            "current_spec": json.loads(current.spec) if current else {},
            "created_by": t.created_by,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })
    return out


@router.post("/templates", status_code=201)
async def create_template(
    body: TemplateCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    from app.services.build_manager.template_service import validate_spec, create_template as svc_create
    from app.services.build_manager.catalogue_service import check_template_spec_conflicts
    errors = validate_spec(body.spec)
    errors += await check_template_spec_conflicts(db, body.spec)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})

    try:
        template = await svc_create(
            db, name=body.name, description=body.description, tags=body.tags,
            spec=body.spec, change_note=body.change_note,
            created_by=auth.username, tenant_id=auth.tenant_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    await audit_event(
        db=db, event_type="BM_TEMPLATE_CREATED", severity="INFO", request=request,
        subject_type="bm_template", subject_id=template.id,
        detail={"name": template.name},
        description=f"Build Manager template created: {template.name}",
    )
    await db.commit()
    current = next((v for v in template.versions if v.is_current), None)
    return _template_to_dict(template, current)


@router.get("/templates/{template_id}")
async def get_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    from app.services.build_manager.template_service import get_template_with_current
    template, current = await get_template_with_current(db, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return _template_to_dict(template, current)


@router.put("/templates/{template_id}")
async def update_template(
    template_id: str,
    body: TemplateUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    from app.services.build_manager.template_service import validate_spec, save_new_version, get_template_with_current
    from app.services.build_manager.catalogue_service import check_template_spec_conflicts

    # Verify template exists
    template, _ = await get_template_with_current(db, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    errors = validate_spec(body.spec)
    errors += await check_template_spec_conflicts(db, body.spec)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})

    new_ver = await save_new_version(
        db, template_id=template_id, spec=body.spec,
        change_note=body.change_note, created_by=auth.username,
    )
    await audit_event(
        db=db, event_type="BM_TEMPLATE_UPDATED", severity="INFO", request=request,
        subject_type="bm_template", subject_id=template_id,
        detail={"name": template.name, "new_version": new_ver.version},
        description=f"Build Manager template '{template.name}' updated to version {new_ver.version}",
    )
    await db.commit()
    # Expire session cache to get fresh data
    db.expire_all()
    # Re-fetch
    template, current = await get_template_with_current(db, template_id)
    return _template_to_dict(template, current)


@router.get("/templates/{template_id}/versions")
async def list_template_versions(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(BMTemplateVersion)
        .where(BMTemplateVersion.template_id == template_id)
        .order_by(BMTemplateVersion.version.desc())
    )
    versions = result.scalars().all()
    return [
        {
            "id": v.id,
            "version": v.version,
            "change_note": v.change_note,
            "is_current": v.is_current,
            "created_by": v.created_by,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in versions
    ]


@router.get("/templates/{template_id}/versions/{version}")
async def get_template_version(
    template_id: str,
    version: int,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    result = await db.execute(
        select(BMTemplateVersion)
        .where(BMTemplateVersion.template_id == template_id, BMTemplateVersion.version == version)
    )
    v = result.scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail="Version not found")
    return {
        "id": v.id,
        "version": v.version,
        "spec": json.loads(v.spec),
        "change_note": v.change_note,
        "is_current": v.is_current,
        "created_by": v.created_by,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


@router.get("/templates/{template_id}/versions/{version}/export")
async def export_template_version(
    template_id: str,
    version: int,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    from app.services.build_manager.template_service import export_as_yaml
    result = await db.execute(
        select(BMTemplate).options(selectinload(BMTemplate.versions))
        .where(BMTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    ver = next((v for v in template.versions if v.version == version), None)
    if not ver:
        raise HTTPException(status_code=404, detail="Version not found")
    yaml_content = export_as_yaml(template, ver)
    return {"yaml": yaml_content, "filename": f"{template.name}_v{version}.yaml"}


@router.post("/templates/import", status_code=201)
async def import_template(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    from app.services.build_manager.template_service import parse_yaml_import, validate_spec, create_template as svc_create, save_new_version, get_template_with_current
    from app.services.build_manager.catalogue_service import check_template_spec_conflicts

    content = await file.read()
    doc, err = parse_yaml_import(content.decode("utf-8"))
    if err:
        raise HTTPException(status_code=422, detail=err)

    spec = doc["spec"]
    errors = validate_spec(spec)
    errors += await check_template_spec_conflicts(db, spec)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})

    # Check if template with this name already exists
    existing = await db.execute(select(BMTemplate).where(BMTemplate.name == doc["name"]))
    tmpl = existing.scalar_one_or_none()

    if tmpl:
        # Add as new version
        new_ver = await save_new_version(
            db, template_id=tmpl.id, spec=spec,
            change_note=doc.get("change_note", "Imported from YAML"),
            created_by=auth.username,
        )
        await audit_event(
            db=db, event_type="BM_TEMPLATE_IMPORTED", severity="INFO", request=request,
            subject_type="bm_template", subject_id=tmpl.id,
            detail={"name": doc["name"], "new_version": new_ver.version},
            description=f"Build Manager template '{doc['name']}' imported as version {new_ver.version}",
        )
        await db.commit()
        template, current = await get_template_with_current(db, tmpl.id)
        return _template_to_dict(template, current)
    else:
        # Create new template
        template = await svc_create(
            db, name=doc["name"], description=doc.get("description", ""),
            tags="", spec=spec,
            change_note=doc.get("change_note", "Imported from YAML"),
            created_by=auth.username, tenant_id=auth.tenant_id,
        )
        await audit_event(
            db=db, event_type="BM_TEMPLATE_IMPORTED", severity="INFO", request=request,
            subject_type="bm_template", subject_id=template.id,
            detail={"name": template.name},
            description=f"Build Manager template '{template.name}' imported from YAML",
        )
        await db.commit()
        current = next((v for v in template.versions if v.is_current), None)
        return _template_to_dict(template, current)


@router.post("/templates/seed")
async def seed_templates_endpoint(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Seed the curated golden-path reference templates (idempotent)."""
    from app.services.build_manager.template_service import seed_golden_path_templates
    added = await seed_golden_path_templates(db, created_by=auth.username, tenant_id=auth.tenant_id)
    return {"templates_added": added}


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(
    template_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> None:
    # Check no active environments
    envs = await db.execute(
        select(BMEnvironment)
        .where(BMEnvironment.template_id == template_id, BMEnvironment.status.notin_(["destroyed"]))
    )
    if envs.scalars().first():
        raise HTTPException(status_code=409, detail="Cannot delete template with active environments")

    result = await db.execute(select(BMTemplate).where(BMTemplate.id == template_id))
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    await audit_event(
        db=db, event_type="BM_TEMPLATE_DELETED", severity="WARNING", request=request,
        subject_type="bm_template", subject_id=template_id,
        detail={"name": template.name},
        description=f"Build Manager template deleted: {template.name}",
    )
    await db.delete(template)
    await db.commit()


def _template_to_dict(template: BMTemplate, current: BMTemplateVersion | None) -> dict[str, Any]:
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "tags": template.tags,
        "origin": template.origin,
        "version_count": len(template.versions) if template.versions else 0,
        "current_version": current.version if current else 0,
        "current_spec": json.loads(current.spec) if current else {},
        "current_change_note": current.change_note if current else "",
        "created_by": template.created_by,
        "created_at": template.created_at.isoformat() if template.created_at else None,
    }


# ============================================================
# ENVIRONMENTS
# ============================================================

class EnvironmentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    template_id: str = Field(...)
    template_version: int | None = Field(default=None)  # None = use current
    ip_overrides: dict[str, str] = Field(default_factory=dict)
    variables: dict[str, Any] = Field(default_factory=dict)
    ttl_hours: float | None = Field(default=None, gt=0, description="Auto-destroy this environment this many hours after creation. Omit for no expiry.")


@router.get("/environments")
async def list_environments(
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    query = select(BMEnvironment).options(selectinload(BMEnvironment.template))
    if status:
        query = query.where(BMEnvironment.status == status)
    result = await db.execute(query.order_by(BMEnvironment.created_at.desc()))
    envs = result.scalars().all()
    return [_env_to_dict(e) for e in envs]


@router.post("/environments", status_code=201)
async def create_environment(
    body: EnvironmentCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    from app.services.build_manager.environment_service import instantiate_environment

    # Resolve version
    version = body.template_version
    if version is None:
        result = await db.execute(
            select(BMTemplateVersion)
            .where(BMTemplateVersion.template_id == body.template_id, BMTemplateVersion.is_current == True)
        )
        current = result.scalar_one_or_none()
        if not current:
            raise HTTPException(status_code=404, detail="No current version found for template")
        version = current.version

    try:
        env = await instantiate_environment(
            db, name=body.name, template_id=body.template_id, version=version,
            ip_overrides=body.ip_overrides or None,
            variable_overrides=body.variables or None,
            created_by=auth.username, tenant_id=auth.tenant_id,
            ttl_hours=body.ttl_hours,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    await audit_event(
        db=db, event_type="BM_ENVIRONMENT_CREATED", severity="INFO", request=request,
        subject_type="bm_environment", subject_id=env.id,
        detail={"name": env.name, "template_id": body.template_id, "template_version": version, "ttl_hours": body.ttl_hours},
        description=f"Build Manager environment created: {env.name}",
    )
    await db.commit()

    # Re-fetch with template
    result = await db.execute(
        select(BMEnvironment).options(selectinload(BMEnvironment.template))
        .where(BMEnvironment.id == env.id)
    )
    return _env_to_dict(result.scalar_one())


@router.get("/environments/{env_id}")
async def get_environment(
    env_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    result = await db.execute(
        select(BMEnvironment).options(
            selectinload(BMEnvironment.template),
            selectinload(BMEnvironment.certs),
        ).where(BMEnvironment.id == env_id)
    )
    env = result.scalar_one_or_none()
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")
    d = _env_to_dict(env)
    d["certs"] = [
        {"id": c.id, "cert_serial": c.cert_serial, "role": c.role, "cert_type": c.cert_type,
         "issued_at": c.issued_at.isoformat() if c.issued_at else None,
         "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None}
        for c in env.certs
    ]
    return d


class EnvironmentVariablesUpdate(BaseModel):
    variables: dict[str, Any] = Field(...)


@router.patch("/environments/{env_id}/variables")
async def update_environment_variables(
    env_id: str,
    body: EnvironmentVariablesUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Update an environment's stored variables (product_config, expose_ports,
    etc.) — e.g. changing a product's admin password after creation, or
    overriding ansible_timeout_minutes for just this environment without
    editing the shared template (which every other environment built from
    it would also inherit). Takes effect on the next Build/Rebuild; this
    endpoint only updates what's stored, it doesn't touch the running hosts.
    Full replacement (matching the same {product_config, expose_ports,
    signing_ca_id, nfs_volumes} shape POST /environments already accepts),
    not a deep merge — the caller is expected to have fetched the current
    variables first."""
    from app.services.build_manager.template_service import ALLOWED_ANSIBLE_TIMEOUT_MINUTES

    result = await db.execute(select(BMEnvironment).where(BMEnvironment.id == env_id))
    env = result.scalar_one_or_none()
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")
    if env.status == "provisioning":
        raise HTTPException(status_code=409, detail="Cannot update variables while a build is in progress")

    timeout_override = body.variables.get("ansible_timeout_minutes")
    if timeout_override is not None and timeout_override not in ALLOWED_ANSIBLE_TIMEOUT_MINUTES:
        raise HTTPException(
            status_code=422,
            detail=f"ansible_timeout_minutes must be one of {sorted(ALLOWED_ANSIBLE_TIMEOUT_MINUTES)}, got {timeout_override!r}",
        )

    env.variables = json.dumps(body.variables)
    await audit_event(
        db=db, event_type="BM_ENVIRONMENT_VARIABLES_UPDATED", severity="INFO", request=request,
        subject_type="bm_environment", subject_id=env_id,
        detail={"name": env.name},
        description=f"Variables updated for Build Manager environment: {env.name} (rebuild to apply)",
    )
    await db.commit()

    result = await db.execute(
        select(BMEnvironment).options(selectinload(BMEnvironment.template))
        .where(BMEnvironment.id == env_id)
    )
    return _env_to_dict(result.scalar_one())


@router.post("/environments/{env_id}/preflight")
async def preflight_environment(
    env_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """Fast readiness check per registered SSH host — no side effects, safe
    to call before actually committing to a build."""
    from app.services.build_manager.preflight_service import run_preflight_checks
    try:
        return await run_preflight_checks(db, env_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


async def _ensure_docker_hosts_ready(db: AsyncSession, env: BMEnvironment) -> None:
    """Create/start Docker containers for all Docker-type hosts in this
    environment's template, if any. Shared by build_environment and
    rebuild_environment — rebuild previously skipped this entirely, on the
    assumption the target infrastructure already exists, which is wrong for
    Docker-hosted hosts whenever their container isn't currently running
    (never successfully created, removed by `destroy`, host reboot without
    persistent containers, manual cleanup, etc.) — found via a real rebuild
    failing with "Could not resolve hostname" because nothing recreated it."""
    from app.services.build_manager.container_manager import ensure_containers_for_environment

    ver_result = await db.execute(
        select(BMTemplateVersion).where(
            BMTemplateVersion.template_id == env.template_id,
            BMTemplateVersion.version == env.template_version,
        )
    )
    tv = ver_result.scalar_one_or_none()
    if not tv:
        return

    spec = json.loads(tv.spec)
    inv_host_ids = [h["inventory_host_id"] for h in spec.get("hosts", []) if h.get("inventory_host_id")]
    docker_hosts = []
    if inv_host_ids:
        inv_result = await db.execute(select(BMHost).where(BMHost.id.in_(inv_host_ids)))
        inv_hosts_by_id = {h.id: h for h in inv_result.scalars().all()}
        for host_def in spec.get("hosts", []):
            inv_host = inv_hosts_by_id.get(host_def.get("inventory_host_id", ""))
            if inv_host and inv_host.connection_type == "docker" and inv_host.container_name:
                docker_hosts.append({
                    "role": host_def["role"], "container_name": inv_host.container_name,
                    "connection_type": inv_host.connection_type,
                    "base_os": spec.get("base_os", "ubuntu"),
                })
    else:
        # No inventory_host_id — detect containers from ip_allocations
        import ipaddress as _ipa
        ip_allocs = json.loads(env.ip_allocations) if env.ip_allocations else {}
        for role, addr in ip_allocs.items():
            try:
                _ipa.ip_address(addr)
            except ValueError:
                # Not a valid IP — treat as container name
                docker_hosts.append({
                    "role": role, "container_name": addr, "connection_type": "docker",
                    "base_os": spec.get("base_os", "ubuntu"),
                })

    # Every nfs_server host needs a *named Docker volume* bound at its export
    # path — not just for cross-rebuild persistence, but because the export
    # simply doesn't work at all otherwise. Live-testing found the kernel NFS
    # server refuses to export a 9p-backed host-path bind (Docker Desktop for
    # Windows shares host drives via 9p) AND, separately, refuses to export
    # a bare container's own overlay2 root filesystem too — "does not support
    # NFS export" either way. A named volume lives on Docker's own managed
    # disk instead (real ext4/xfs), which exports correctly. So this always
    # provides one: the user-supplied name from variables.nfs_volumes if
    # given (for persistence across rebuilds), else an auto-generated one
    # scoped to this environment+role (deterministic, so a rebuild reuses the
    # same auto volume too). /srv/nfs-export must match the nfs_exports[0].path
    # baked into the seeded templates' specs.
    nfs_server_roles = {
        h["role"] for h in spec.get("hosts", [])
        if any(p.get("product") == "nfs_server" for p in h.get("products", []))
    }
    nfs_volumes = json.loads(env.variables or "{}").get("nfs_volumes", {})
    for dh in docker_hosts:
        if dh["role"] not in nfs_server_roles:
            continue
        volume_name = nfs_volumes.get(dh["role"]) or f"nfs-auto-{env.id[:8]}-{dh['role']}"
        # Docker Desktop auto-translates anything path-shaped (drive
        # letters, slashes/backslashes) into a host-path bind instead
        # of creating a named volume — found via a real build where a
        # user pasted a Windows path here, which silently became a
        # 9p-backed bind and reproduced the exact "does not support
        # NFS export" failure the named-volume design exists to avoid.
        # Reject anything that isn't a legal Docker volume name so
        # this fails fast with a clear reason, not a cryptic
        # exportfs error ten minutes into a build.
        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$", volume_name):
            raise ValueError(
                f"Storage Volume Name '{volume_name}' for role '{dh['role']}' is not a valid "
                "Docker volume name (it looks like a filesystem path). Use a short name like "
                "'my-nfs-data' instead — Docker will create the volume automatically; it isn't "
                "a host directory you need to create yourself."
            )
        dh["extra_binds"] = [f"{volume_name}:/srv/nfs-export"]

    # Shared package cache, Docker-volume variant: a single named Docker
    # volume bound at /mnt/pkg-cache on both the seed host (pkg_cache_seed
    # product — writes the downloaded .deb files there) and every consumer
    # host (local_repo product — reads from it). No network filesystem
    # needed here — every "host" in a Docker-fallback template is already a
    # container on this same Docker engine, so a named volume gives them all
    # the same directory directly. This is a lab-only shortcut, not what the
    # golden-path Full Stack template uses (that one uses real NFS — see the
    # nfs_server_roles block above — since real on-prem/AWS hosts won't
    # share a Docker daemon); it's still here for any simpler custom template
    # that wants the shared-cache convenience without standing up NFS.
    # Explicitly skipped for any host that already has nfs_server or
    # nfs_client — those are opting into the real-NFS design instead, and
    # binding an unused Docker volume at the same path a moment before
    # Ansible's nfs_client role mounts the real export there would just be
    # confusing clutter (an empty, never-read volume sitting underneath).
    pkg_cache_roles = {
        h["role"] for h in spec.get("hosts", [])
        if any(p.get("product") in ("pkg_cache_seed", "local_repo") for p in h.get("products", []))
        and not any(p.get("product") in ("nfs_server", "nfs_client") for p in h.get("products", []))
    }
    if pkg_cache_roles:
        volume_name = json.loads(env.variables or "{}").get("pkg_cache_volume") or f"pkg-cache-{env.id[:8]}"
        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$", volume_name):
            raise ValueError(
                f"Package Cache Volume Name '{volume_name}' is not a valid Docker volume name "
                "(it looks like a filesystem path). Use a short name instead."
            )
        for dh in docker_hosts:
            if dh["role"] in pkg_cache_roles:
                dh["extra_binds"] = [*dh.get("extra_binds", []), f"{volume_name}:/mnt/pkg-cache"]

    # Host-port publishing: union of (a) the template's own baked-in default
    # (host_def["expose_ports"] — e.g. the golden-path frontend-lb/rabbitmq
    # ports, always applied) and (b) this environment's own per-role opt-in
    # checkbox (variables.expose_ports, from the Environments page — for
    # roles with no template-level default, e.g. backend-lb "in another
    # environment"), expanded to that role's product(s) default_ports.
    # RESERVED_HOST_PORTS (80, 8000) are always excluded: both are
    # permanently owned by the ssl-cert-manager container's own -p flags, so
    # no other host container can ever publish either. Found via a real live
    # build: opting in "backend" (uvicorn's default_ports includes 8000)
    # created a container requesting host port 8000 — a guaranteed conflict
    # with ssl-cert-manager itself — whose failed start left Docker's
    # network-endpoint setup half-done (container running, but with zero
    # network attachment at all), not just a rejected port binding.
    from app.services.build_manager.template_service import RESERVED_HOST_PORTS
    hosts_by_role = {h["role"]: h for h in spec.get("hosts", [])}
    expose_opt_in = json.loads(env.variables or "{}").get("expose_ports", {})
    for dh in docker_hosts:
        host_def = hosts_by_role.get(dh["role"], {})
        ports: set[int] = set(host_def.get("expose_ports", []))
        if expose_opt_in.get(dh["role"]):
            product_names = [p.get("product") for p in host_def.get("products", []) if p.get("product")]
            if product_names:
                prod_result = await db.execute(select(BMProduct).where(BMProduct.name.in_(product_names)))
                for prod in prod_result.scalars().all():
                    ports.update(json.loads(prod.default_ports or "[]"))
        ports -= RESERVED_HOST_PORTS
        if ports:
            dh["expose_ports"] = {str(p): str(p) for p in sorted(ports)}

    # Detect host-port collisions across this environment's own Docker
    # hosts — e.g. an nginx frontend and its nginx_lb both defaulting to
    # exposing 443 (both products' catalogue default_ports include it, and
    # the Environments page auto-opts in every role with any default_ports
    # at all). Only one container can ever actually bind a given host port;
    # letting both request it used to fail silently deep into the build —
    # whichever container lost the race was left in Docker's "Created"
    # state, never actually running, but nothing surfaced that until
    # Ansible's "Gathering Facts" for that host — often 20+ minutes later,
    # after every earlier host in the serial:1 build order had already
    # finished — hit "Could not resolve hostname". Caught here instead,
    # immediately and with a clear reason.
    host_port_owners: dict[str, list[str]] = {}
    for dh in docker_hosts:
        for host_port in dh.get("expose_ports", {}).values():
            host_port_owners.setdefault(host_port, []).append(dh["role"])
    conflicts = {port: roles for port, roles in host_port_owners.items() if len(roles) > 1}
    if conflicts:
        detail = "; ".join(f"port {port} requested by {', '.join(roles)}" for port, roles in sorted(conflicts.items()))
        raise ValueError(
            f"Multiple Docker hosts in this environment want to publish the same host port ({detail}). "
            "Only one container can bind a given host port — uncheck 'Expose Ports' for all but one of them."
        )

    if docker_hosts:
        await ensure_containers_for_environment(docker_hosts)


@router.post("/environments/{env_id}/build")
async def build_environment(
    env_id: str,
    request: Request,
    force: bool = Query(default=False, description="Skip pre-flight readiness checks and build anyway"),
    dry_run: bool = Query(default=False, description="Run with --check --diff instead of applying changes. Note: command/shell tasks often report inaccurately under check mode."),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Trigger a full build for the environment (issues certs + runs site.yml)."""
    from app.services.build_manager.base_provisioner import provision_environment as do_provision
    from app.services.build_manager.ansible_runner import submit_job
    from app.services.build_manager.preflight_service import run_preflight_checks

    result = await db.execute(
        select(BMEnvironment).options(selectinload(BMEnvironment.template))
        .where(BMEnvironment.id == env_id)
    )
    env = result.scalar_one_or_none()
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")
    if env.status not in ("pending", "active", "degraded", "failed"):
        raise HTTPException(status_code=409, detail=f"Cannot build environment in '{env.status}' state")

    if not force:
        preflight = await run_preflight_checks(db, env_id)
        if not preflight["ready"]:
            raise HTTPException(status_code=422, detail={"preflight": preflight})

    try:
        await _ensure_docker_hosts_ready(db, env)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Issue certs and generate vars (same as provision)
    try:
        provision_data = await do_provision(db, env_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    env_variables = json.loads(env.variables) if env.variables else {}

    # Export the downloadable CA chain PEM / JKS trust store bundle to
    # /data/environments/{name}/certs/ — previously this only ever happened
    # as a side effect of POST .../certs/renew, so a plain Build/Rebuild
    # left that directory missing entirely and both download buttons on the
    # environment's Certificates tab 404'd until someone gratuitously
    # revoked+reissued every cert just to trigger it.
    from app.services.build_manager.cert_integration import export_trust_bundle
    await export_trust_bundle(db, env.name, env_variables.get("signing_ca_id"))

    extra_vars = {
        "ca_chain_pem": provision_data["ca_chain_pem"],
        "extra_trusted_ca_pem": env_variables.get("extra_trusted_ca_pem", ""),
        "environment_id": env_id,
        "host_products": provision_data.get("host_products", {}),
    }
    for role, hvars in provision_data.get("host_vars", {}).items():
        for k, v in hvars.items():
            extra_vars[f"{role}_{k}"] = v

    from app.services.build_manager.template_service import resolve_ansible_timeout_seconds
    ver_result = await db.execute(
        select(BMTemplateVersion).where(
            BMTemplateVersion.template_id == env.template_id,
            BMTemplateVersion.version == env.template_version,
        )
    )
    tv = ver_result.scalar_one_or_none()
    timeout_seconds = resolve_ansible_timeout_seconds(json.loads(tv.spec), env_variables) if tv else None

    # A dry-run doesn't actually change anything on the targets, so the
    # environment's own lifecycle status is left untouched — only the job
    # record (and its --check --diff output) reflects the dry-run.
    if not dry_run:
        env.status = "provisioning"
    await audit_event(
        db=db, event_type="BM_ENVIRONMENT_BUILD_TRIGGERED", severity="INFO", request=request,
        subject_type="bm_environment", subject_id=env_id,
        detail={"name": env.name},
        description=f"Build triggered for Build Manager environment: {env.name}",
    )
    await db.commit()

    job = await submit_job(
        db, name=f"Build environment: {env.name}",
        playbook="site.yml", job_type="provision",
        environment_id=env.id,
        extra_vars=extra_vars,
        created_by=auth.username, tenant_id=auth.tenant_id,
        dry_run=dry_run, timeout_seconds=timeout_seconds,
    )
    return {"environment_id": env.id, "job_id": job.id, "status": "provisioning"}


@router.post("/environments/{env_id}/destroy")
async def destroy_env(
    env_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, Any]:
    from app.services.build_manager.environment_service import destroy_environment

    # destroy_environment() resolves and removes this environment's Docker
    # containers itself now, so both this endpoint and TTL auto-destroy
    # clean up containers the same way — no duplicated lookup needed here.
    try:
        env = await destroy_environment(db, env_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    await audit_event(
        db=db, event_type="BM_ENVIRONMENT_DESTROYED", severity="WARNING", request=request,
        subject_type="bm_environment", subject_id=env_id,
        detail={"name": env.name},
        description=f"Build Manager environment destroyed: {env.name}",
    )
    await db.commit()

    return {"id": env.id, "name": env.name, "status": env.status}


@router.post("/environments/{env_id}/rebuild")
async def rebuild_environment(
    env_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Revoke old certs, re-issue, and rebuild from same template version."""
    from app.services.build_manager.base_provisioner import provision_environment as do_provision
    from app.services.build_manager.ansible_runner import submit_job

    result = await db.execute(
        select(BMEnvironment).options(selectinload(BMEnvironment.certs))
        .where(BMEnvironment.id == env_id)
    )
    env = result.scalar_one_or_none()
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")

    # Ensure Docker containers exist for all Docker-type hosts — rebuild
    # previously assumed the target infrastructure was already there, which
    # doesn't hold for a Docker-hosted host whose container isn't currently
    # running (never successfully created, removed, host reboot, manual
    # cleanup, etc.); found via a real rebuild failing with "Could not
    # resolve hostname" because nothing recreated it.
    try:
        await _ensure_docker_hosts_ready(db, env)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Revoke existing certs
    now = datetime.now(timezone.utc)
    for cert in env.certs:
        if not cert.revoked_at:
            cert.revoked_at = now
    await audit_event(
        db=db, event_type="BM_ENVIRONMENT_REBUILD_TRIGGERED", severity="WARNING", request=request,
        subject_type="bm_environment", subject_id=env_id,
        detail={"name": env.name},
        description=f"Rebuild triggered for Build Manager environment: {env.name}",
    )
    await db.commit()

    # Re-issue certs
    try:
        provision_data = await do_provision(db, env.id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    env_variables = json.loads(env.variables) if env.variables else {}

    # Export the downloadable CA chain PEM / JKS trust store bundle — see
    # build_environment's identical call for why this is needed here too
    # (previously only ever generated as a side effect of certs/renew).
    from app.services.build_manager.cert_integration import export_trust_bundle
    await export_trust_bundle(db, env.name, env_variables.get("signing_ca_id"))

    extra_vars = {
        "ca_chain_pem": provision_data["ca_chain_pem"],
        "extra_trusted_ca_pem": env_variables.get("extra_trusted_ca_pem", ""),
        "environment_id": env.id,
        "host_products": provision_data.get("host_products", {}),
    }
    for role, hvars in provision_data.get("host_vars", {}).items():
        for k, v in hvars.items():
            extra_vars[f"{role}_{k}"] = v

    from app.services.build_manager.template_service import resolve_ansible_timeout_seconds
    ver_result = await db.execute(
        select(BMTemplateVersion).where(
            BMTemplateVersion.template_id == env.template_id,
            BMTemplateVersion.version == env.template_version,
        )
    )
    tv = ver_result.scalar_one_or_none()
    timeout_seconds = resolve_ansible_timeout_seconds(json.loads(tv.spec), env_variables) if tv else None

    env.status = "provisioning"
    env.destroyed_at = None
    await db.commit()

    job = await submit_job(
        db, name=f"Rebuild environment: {env.name}",
        playbook="site.yml", job_type="provision",
        environment_id=env.id,
        extra_vars=extra_vars,
        created_by=auth.username, tenant_id=auth.tenant_id,
        timeout_seconds=timeout_seconds,
    )
    return {"environment_id": env.id, "job_id": job.id, "status": "provisioning"}


@router.get("/environments/{env_id}/certs")
async def list_environment_certs(
    env_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(BMEnvironmentCert).where(BMEnvironmentCert.environment_id == env_id)
    )
    return [
        {"id": c.id, "cert_serial": c.cert_serial, "role": c.role, "cert_type": c.cert_type,
         "issued_at": c.issued_at.isoformat() if c.issued_at else None,
         "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None}
        for c in result.scalars().all()
    ]


def _env_to_dict(env: BMEnvironment) -> dict[str, Any]:
    return {
        "id": env.id,
        "name": env.name,
        "template_id": env.template_id,
        "template_name": env.template.name if env.template else None,
        "template_version": env.template_version,
        "status": env.status,
        "ip_allocations": json.loads(env.ip_allocations) if env.ip_allocations else {},
        "variables": json.loads(env.variables) if env.variables else {},
        "created_by": env.created_by,
        "created_at": env.created_at.isoformat() if env.created_at else None,
        "destroyed_at": env.destroyed_at.isoformat() if env.destroyed_at else None,
        "expires_at": env.expires_at.isoformat() if env.expires_at else None,
    }


# ============================================================
# JOBS
# ============================================================

class JobCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    playbook: str = Field(..., min_length=1)
    job_type: str = Field(default="ansible")
    environment_id: str | None = Field(default=None)
    inventory_filter: str = Field(default="")
    extra_vars: dict = Field(default_factory=dict)
    dry_run: bool = Field(default=False, description="Run with --check --diff instead of applying changes. Note: command/shell tasks often report inaccurately under check mode.")


@router.get("/jobs")
async def list_jobs(
    status: str | None = Query(None),
    environment_id: str | None = Query(None),
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    query = select(BMJob).order_by(BMJob.created_at.desc()).limit(limit)
    if status:
        query = query.where(BMJob.status == status)
    if environment_id:
        query = query.where(BMJob.environment_id == environment_id)
    result = await db.execute(query)
    jobs = []
    for j in result.scalars().all():
        try:
            jobs.append(_job_to_dict(j))
        except Exception:
            logger.exception("Failed to serialise job %s — dropping from list", getattr(j, "id", "?"))
    return jobs


@router.post("/jobs", status_code=201)
async def create_job(
    body: JobCreate,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    from app.services.build_manager.ansible_runner import submit_job
    job = await submit_job(
        db, name=body.name, playbook=body.playbook, job_type=body.job_type,
        environment_id=body.environment_id, inventory_filter=body.inventory_filter,
        extra_vars=body.extra_vars, created_by=auth.username, tenant_id=auth.tenant_id,
        dry_run=body.dry_run,
    )
    return _job_to_dict(job)


async def _job_related_bugs_summary(db: AsyncSession, job: BMJob, auth: AuthContext) -> list[dict[str, Any]] | None:
    """Resolves Improvements Plan Stage 21's related_bug_ids_json to real
    bug summaries, best-first — the Build Manager equivalent of
    jar_analyser.py's own _related_bugs_summary, same shape: None means
    "not yet scanned," [] means "scanned, nothing found." Tenant-filtered
    defensively even though the ids stored were already scoped to the
    job's own tenant at scan time."""
    if job.related_bug_ids_json is None:
        return None
    ids = json.loads(job.related_bug_ids_json)
    if not ids:
        return []
    query = select(Bug).where(Bug.id.in_(ids), Bug.deleted_at.is_(None))
    if not auth.is_global_admin:
        query = query.where(Bug.tenant_id == auth.tenant_id)
    bugs = (await db.execute(query)).scalars().all()
    rank_index = {bid: i for i, bid in enumerate(ids)}
    ranked = sorted(bugs, key=lambda b: rank_index.get(b.id, len(ids)))
    return [{"id": b.id, "title": b.title, "status": b.status, "severity": b.severity} for b in ranked]


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    result = await db.execute(select(BMJob).where(BMJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    d = _job_to_dict(job)
    d["related_bugs"] = await _job_related_bugs_summary(db, job, auth)
    return d


@router.get("/jobs/{job_id}/output")
async def get_job_output(
    job_id: str,
    after: int = Query(default=0, description="Return lines after this count (for incremental fetch)"),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    result = await db.execute(
        select(BMJobLog).where(BMJobLog.job_id == job_id).order_by(BMJobLog.timestamp)
    )
    logs = result.scalars().all()
    total = len(logs)
    lines_to_return = logs[after:] if after > 0 else logs
    return {
        "job_id": job_id,
        "total_lines": total,
        "lines": [
            {"timestamp": l.timestamp.isoformat() if l.timestamp else None, "stream": l.stream, "line": l.line}
            for l in lines_to_return
        ],
    }


@router.get("/jobs/{job_id}/diagnose")
async def diagnose_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """Match this job's own failure output against the Error KB (the same
    pattern-matching engine JAR Analyser's own Diagnose action and the
    Docs Search tab's pattern mode already use) - surfaced in the manual
    "Report Bug" flow so a known Ansible failure comes with real causes/
    fix steps, not just the coarse exit-code hint. A real, user-initiated
    lookup (the New Bug form calls this once, when opened from a job), so
    unlike Stage 21's automated scan or Stage 22's auto-filer, this DOES
    count toward Error KB usage tracking (Improvements Plan Stage 16),
    matching JAR Analyser's own diagnose_error."""
    result = await db.execute(select(BMJob).where(BMJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    log_rows = (await db.execute(
        select(BMJobLog.line).where(BMJobLog.job_id == job_id).order_by(BMJobLog.timestamp)
    )).scalars().all()

    from app.services.build_manager.bug_pattern_scan import diagnose_job_failure
    results = await diagnose_job_failure(db, job, list(log_rows))

    from app.services.docs_error_kb import record_kb_matches
    await record_kb_matches(db, [r["id"] for r in results])
    await db.commit()

    return {"job_id": job.id, "total": len(results), "results": results}


@router.get("/jobs/{job_id}/stream")
async def stream_job_output(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
):
    """SSE stream of job output — real-time log lines."""
    # Verify job exists
    result = await db.execute(select(BMJob).where(BMJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        from app.core.database import async_session
        seen = 0
        while True:
            async with async_session() as session:
                # Get job status
                job_result = await session.execute(select(BMJob).where(BMJob.id == job_id))
                current_job = job_result.scalar_one_or_none()
                if not current_job:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'Job not found'})}\n\n"
                    break

                # Get new log lines
                count_result = await session.execute(
                    select(func.count()).select_from(BMJobLog).where(BMJobLog.job_id == job_id)
                )
                total = count_result.scalar() or 0

                if total > seen:
                    log_result = await session.execute(
                        select(BMJobLog).where(BMJobLog.job_id == job_id)
                        .order_by(BMJobLog.timestamp)
                        .offset(seen)
                    )
                    new_lines = log_result.scalars().all()
                    for line in new_lines:
                        event = {
                            "type": "log",
                            "timestamp": line.timestamp.isoformat() if line.timestamp else None,
                            "stream": line.stream,
                            "line": line.line,
                        }
                        yield f"data: {json.dumps(event)}\n\n"
                    seen = total

                # Send status update
                status_event = {
                    "type": "status",
                    "status": current_job.status,
                    "exit_code": current_job.exit_code,
                    "started_at": current_job.started_at.isoformat() if current_job.started_at else None,
                    "finished_at": current_job.finished_at.isoformat() if current_job.finished_at else None,
                }
                yield f"data: {json.dumps(status_event)}\n\n"

                # Stop if job is done
                if current_job.status in ("success", "failed", "cancelled"):
                    yield f"data: {json.dumps({'type': 'done', 'status': current_job.status, 'exit_code': current_job.exit_code})}\n\n"
                    break

            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/jobs/{job_id}/cancel")
async def cancel_job_endpoint(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    from app.services.build_manager.ansible_runner import cancel_job
    try:
        job = await cancel_job(db, job_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _job_to_dict(job)


@router.post("/jobs/{job_id}/retry", status_code=201)
async def retry_job(
    job_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Re-submit a failed job. If it recorded which hosts actually failed,
    limit the retry to just those hosts — otherwise (e.g. the failure was
    before any host-level result, such as a playbook syntax error) fall back
    to a full re-run, same as the original job's own inventory_filter."""
    from app.services.build_manager.ansible_runner import submit_job

    result = await db.execute(select(BMJob).where(BMJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "failed":
        raise HTTPException(status_code=409, detail=f"Can only retry a failed job (current status: '{job.status}')")

    failed_hosts = json.loads(job.failed_hosts) if job.failed_hosts else []
    inventory_filter = ",".join(failed_hosts) if failed_hosts else job.inventory_filter

    new_job = await submit_job(
        db, name=f"Retry: {job.name}", playbook=job.playbook, job_type=job.job_type,
        environment_id=job.environment_id, inventory_filter=inventory_filter,
        extra_vars=json.loads(job.extra_vars) if job.extra_vars else {},
        created_by=auth.username, tenant_id=auth.tenant_id,
        dry_run=job.dry_run,
    )
    await audit_event(
        db=db, event_type="BM_JOB_RETRIED", severity="INFO", request=request,
        subject_type="bm_job", subject_id=new_job.id,
        detail={"retried_from_job_id": job_id, "limited_to_hosts": failed_hosts},
        description=f"Build Manager job retried: {job.name} (limited to {len(failed_hosts)} failed host(s))" if failed_hosts
                    else f"Build Manager job retried in full: {job.name}",
    )
    await db.commit()
    return _job_to_dict(new_job)


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> None:
    result = await db.execute(select(BMJob).where(BMJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == "running":
        raise HTTPException(status_code=409, detail="Cannot delete a running job")
    await db.delete(job)
    await db.commit()


def _job_to_dict(job: BMJob) -> dict[str, Any]:
    duration = None
    if job.started_at and job.finished_at:
        duration = (job.finished_at - job.started_at).total_seconds()
    return {
        "id": job.id,
        "name": job.name,
        "job_type": job.job_type,
        "status": job.status,
        "playbook": job.playbook,
        "environment_id": job.environment_id,
        "inventory_filter": job.inventory_filter,
        "exit_code": job.exit_code,
        "duration_seconds": duration,
        "dry_run": job.dry_run,
        "failed_hosts": json.loads(job.failed_hosts) if job.failed_hosts else [],
        "auto_retry_count": job.auto_retry_count,
        "timeout_seconds": job.timeout_seconds,
        "created_by": job.created_by,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "build_snapshot": json.loads(job.build_snapshot_json) if job.build_snapshot_json else None,
    }


# ============================================================
# PROVISIONING
# ============================================================


@router.post("/environments/{env_id}/provision")
async def provision_environment(
    env_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Alias for build — issues certs + runs full site.yml (base + products)."""
    return await build_environment(env_id, request, force=False, dry_run=False, db=db, auth=auth)


@router.get("/environments/{env_id}/provision-status")
async def get_provision_status(
    env_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """Get provisioning status — certs issued, JKS status per host."""
    result = await db.execute(
        select(BMEnvironmentCert).where(BMEnvironmentCert.environment_id == env_id)
    )
    certs = result.scalars().all()

    return {
        "environment_id": env_id,
        "total_certs": len(certs),
        "active_certs": len([c for c in certs if not c.revoked_at]),
        "revoked_certs": len([c for c in certs if c.revoked_at]),
        "certs": [
            {
                "role": c.role,
                "cert_type": c.cert_type,
                "cert_serial": c.cert_serial,
                "issued_at": c.issued_at.isoformat() if c.issued_at else None,
                "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None,
            }
            for c in certs
        ],
    }


# ============================================================
# PRODUCT CATALOGUE
# ============================================================


class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=255)
    category: str = Field(default="utility")
    description: str = Field(default="")
    icon: str = Field(default="📦", max_length=8)
    default_ports: list[int] = Field(default_factory=list)
    cert_requirements: dict = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    deployment_targets: list[str] = Field(default_factory=lambda: ["ec2"])


class ProductUpdate(BaseModel):
    display_name: str | None = None
    category: str | None = None
    description: str | None = None
    icon: str | None = None
    default_ports: list[int] | None = None
    cert_requirements: dict | None = None
    dependencies: list[str] | None = None
    deployment_targets: list[str] | None = None


class ProductVersionCreate(BaseModel):
    version: str = Field(..., min_length=1, max_length=32)
    ansible_role: str = Field(default="")
    default_vars: dict = Field(default_factory=dict)
    supported_os: list[dict] = Field(default_factory=list)
    conflicts_with: list[dict] = Field(default_factory=list)
    requires: list[dict] = Field(default_factory=list)
    release_date: str | None = None
    eol_date: str | None = None
    is_latest: bool = False
    aws_defaults: dict | None = None


class ProductVersionUpdate(BaseModel):
    ansible_role: str | None = None
    default_vars: dict | None = None
    supported_os: list[dict] | None = None
    conflicts_with: list[dict] | None = None
    requires: list[dict] | None = None
    release_date: str | None = None
    eol_date: str | None = None
    is_latest: bool | None = None
    aws_defaults: dict | None = None


class CompatibilityCheck(BaseModel):
    base_os: str = Field(...)
    base_os_version: str = Field(...)
    # [{"role": "host-01", "selections": [{"product_id": "...", "version_id": "..."}]}]
    # Host-grouped (not a flat selection list) so conflicts_with can be
    # checked per host — two conflicting products only actually collide
    # if provisioned onto the same machine.
    hosts: list[dict] = Field(...)


class TemplateBuildRequest(BaseModel):
    base_os: str = Field(...)
    base_os_version: str = Field(...)
    hosts: list[dict] = Field(...)  # [{"role": "...", "products": [{"version_id": "...", "vars": {}}]}]
    network: dict | None = None
    certificates: dict | None = None
    aws: dict | None = None
    template_name: str = Field(..., min_length=1, max_length=255)
    template_description: str = Field(default="")
    template_tags: str = Field(default="")
    change_note: str = Field(default="Created via Template Builder")
    ansible_timeout_minutes: int = Field(default=30)


@router.get("/catalogue")
async def list_products(
    category: str | None = Query(None),
    deployment_target: str | None = Query(None, description="Filter by deployment target: ec2, rds, s3"),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    from app.services.build_manager.catalogue_service import get_products_by_target
    if deployment_target:
        products = await get_products_by_target(db, deployment_target)
        if category:
            products = [p for p in products if p.category == category]
        products.sort(key=lambda p: (p.category, p.display_name))
        return [_product_to_dict(p) for p in products]
    query = select(BMProduct).options(selectinload(BMProduct.versions))
    if category:
        query = query.where(BMProduct.category == category)
    result = await db.execute(query.order_by(BMProduct.category, BMProduct.display_name))
    products = result.scalars().all()
    return [_product_to_dict(p) for p in products]


@router.get("/catalogue/{product_id}")
async def get_product(
    product_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    result = await db.execute(
        select(BMProduct).options(selectinload(BMProduct.versions))
        .where(BMProduct.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return _product_to_dict(product)


@router.post("/catalogue", status_code=201)
async def create_product(
    body: ProductCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, Any]:
    product = BMProduct(
        id=str(uuid.uuid4()),
        name=body.name,
        display_name=body.display_name,
        category=body.category,
        description=body.description,
        icon=body.icon,
        default_ports=json.dumps(body.default_ports),
        cert_requirements=json.dumps(body.cert_requirements),
        dependencies=json.dumps(body.dependencies),
        deployment_targets=json.dumps(body.deployment_targets),
        is_builtin=False,
    )
    db.add(product)
    await audit_event(
        db=db, event_type="BM_PRODUCT_CREATED", severity="INFO", request=request,
        subject_type="bm_product", subject_id=product.id,
        detail={"name": product.name},
        description=f"Build Manager catalogue product created: {product.name}",
    )
    await db.commit()
    return await get_product(product.id, db, auth)


@router.put("/catalogue/{product_id}")
async def update_product(
    product_id: str,
    body: ProductUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, Any]:
    result = await db.execute(
        select(BMProduct).options(selectinload(BMProduct.versions))
        .where(BMProduct.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if body.display_name is not None:
        product.display_name = body.display_name
    if body.category is not None:
        product.category = body.category
    if body.description is not None:
        product.description = body.description
    if body.icon is not None:
        product.icon = body.icon
    if body.default_ports is not None:
        product.default_ports = json.dumps(body.default_ports)
    if body.cert_requirements is not None:
        product.cert_requirements = json.dumps(body.cert_requirements)
    if body.dependencies is not None:
        product.dependencies = json.dumps(body.dependencies)
    if body.deployment_targets is not None:
        product.deployment_targets = json.dumps(body.deployment_targets)

    await audit_event(
        db=db, event_type="BM_PRODUCT_UPDATED", severity="INFO", request=request,
        subject_type="bm_product", subject_id=product_id,
        detail={"name": product.name},
        description=f"Build Manager catalogue product updated: {product.name}",
    )
    await db.commit()
    return await get_product(product_id, db, auth)


@router.delete("/catalogue/{product_id}", status_code=204)
async def delete_product(
    product_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> None:
    result = await db.execute(
        select(BMProduct).where(BMProduct.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    # Check if any product configs reference versions of this product
    ver_ids = await db.execute(
        select(BMProductVersion.id).where(BMProductVersion.product_id == product_id)
    )
    ids = [r[0] for r in ver_ids.all()]
    if ids:
        configs = await db.execute(
            select(BMProductConfig).where(BMProductConfig.product_version_id.in_(ids))
        )
        if configs.scalars().first():
            raise HTTPException(status_code=409, detail="Cannot delete product with active deployments")
    await audit_event(
        db=db, event_type="BM_PRODUCT_DELETED", severity="WARNING", request=request,
        subject_type="bm_product", subject_id=product_id,
        detail={"name": product.name},
        description=f"Build Manager catalogue product deleted: {product.name}",
    )
    await db.delete(product)
    await db.commit()


@router.post("/catalogue/{product_id}/versions", status_code=201)
async def add_product_version(
    product_id: str,
    body: ProductVersionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, Any]:
    # Verify product exists
    result = await db.execute(select(BMProduct).where(BMProduct.id == product_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Product not found")

    # If marking as latest, unmark others
    if body.is_latest:
        await db.execute(
            select(BMProductVersion)
            .where(BMProductVersion.product_id == product_id, BMProductVersion.is_latest == True)
        )
        existing_latest = await db.execute(
            select(BMProductVersion)
            .where(BMProductVersion.product_id == product_id, BMProductVersion.is_latest == True)
        )
        for pv in existing_latest.scalars().all():
            pv.is_latest = False

    pv = BMProductVersion(
        id=str(uuid.uuid4()),
        product_id=product_id,
        version=body.version,
        ansible_role=body.ansible_role,
        default_vars=json.dumps(body.default_vars),
        supported_os=json.dumps(body.supported_os),
        conflicts_with=json.dumps(body.conflicts_with),
        requires=json.dumps(body.requires),
        release_date=body.release_date,
        eol_date=body.eol_date,
        is_latest=body.is_latest,
        aws_defaults=json.dumps(body.aws_defaults) if body.aws_defaults is not None else None,
    )
    db.add(pv)
    await audit_event(
        db=db, event_type="BM_PRODUCT_VERSION_CREATED", severity="INFO", request=request,
        subject_type="bm_product_version", subject_id=pv.id,
        detail={"product_id": product_id, "version": pv.version},
        description=f"Build Manager catalogue product version created: {product_id} v{pv.version}",
    )
    await db.commit()
    return _version_to_dict(pv)


@router.put("/catalogue/versions/{version_id}")
async def update_product_version(
    version_id: str,
    body: ProductVersionUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, Any]:
    result = await db.execute(
        select(BMProductVersion).where(BMProductVersion.id == version_id)
    )
    pv = result.scalar_one_or_none()
    if not pv:
        raise HTTPException(status_code=404, detail="Product version not found")

    if body.ansible_role is not None:
        pv.ansible_role = body.ansible_role
    if body.default_vars is not None:
        pv.default_vars = json.dumps(body.default_vars)
    if body.supported_os is not None:
        pv.supported_os = json.dumps(body.supported_os)
    if body.conflicts_with is not None:
        pv.conflicts_with = json.dumps(body.conflicts_with)
    if body.requires is not None:
        pv.requires = json.dumps(body.requires)
    if body.release_date is not None:
        pv.release_date = body.release_date
    if body.eol_date is not None:
        pv.eol_date = body.eol_date
    if body.is_latest is not None:
        if body.is_latest:
            # Unmark others
            others = await db.execute(
                select(BMProductVersion)
                .where(BMProductVersion.product_id == pv.product_id, BMProductVersion.is_latest == True, BMProductVersion.id != version_id)
            )
            for other in others.scalars().all():
                other.is_latest = False
        pv.is_latest = body.is_latest
    if body.aws_defaults is not None:
        pv.aws_defaults = json.dumps(body.aws_defaults)

    await audit_event(
        db=db, event_type="BM_PRODUCT_VERSION_UPDATED", severity="INFO", request=request,
        subject_type="bm_product_version", subject_id=version_id,
        detail={"product_id": pv.product_id, "version": pv.version},
        description=f"Build Manager catalogue product version updated: {version_id}",
    )
    await db.commit()
    return _version_to_dict(pv)


@router.delete("/catalogue/versions/{version_id}", status_code=204)
async def delete_product_version(
    version_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> None:
    result = await db.execute(
        select(BMProductVersion).where(BMProductVersion.id == version_id)
    )
    pv = result.scalar_one_or_none()
    if not pv:
        raise HTTPException(status_code=404, detail="Product version not found")
    # Check usage
    configs = await db.execute(
        select(BMProductConfig).where(BMProductConfig.product_version_id == version_id)
    )
    if configs.scalars().first():
        raise HTTPException(status_code=409, detail="Cannot delete version with active deployments")
    await audit_event(
        db=db, event_type="BM_PRODUCT_VERSION_DELETED", severity="WARNING", request=request,
        subject_type="bm_product_version", subject_id=version_id,
        detail={"product_id": pv.product_id, "version": pv.version},
        description=f"Build Manager catalogue product version deleted: {version_id}",
    )
    await db.delete(pv)
    await db.commit()


@router.post("/catalogue/check-compatibility")
async def check_compat(
    body: CompatibilityCheck,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    from app.services.build_manager.catalogue_service import check_compatibility
    return await check_compatibility(db, body.base_os, body.base_os_version, body.hosts)


@router.post("/catalogue/seed")
async def seed_catalogue_endpoint(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, Any]:
    from app.services.build_manager.catalogue_service import seed_catalogue
    return await seed_catalogue(db)


@router.post("/catalogue/build-template", status_code=201)
async def build_template_from_catalogue(
    body: TemplateBuildRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Template Builder: convert product selections into a saved template."""
    from app.services.build_manager.catalogue_service import build_template_spec, check_template_spec_conflicts
    from app.services.build_manager.template_service import validate_spec, create_template as svc_create

    spec = await build_template_spec(
        db, base_os=body.base_os, base_os_version=body.base_os_version,
        hosts=body.hosts, network=body.network, certificates=body.certificates,
        ansible_timeout_minutes=body.ansible_timeout_minutes,
        aws=body.aws,
    )

    errors = validate_spec(spec)
    errors += await check_template_spec_conflicts(db, spec)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})

    try:
        template = await svc_create(
            db, name=body.template_name, description=body.template_description,
            tags=body.template_tags, spec=spec, change_note=body.change_note,
            created_by=auth.username, tenant_id=auth.tenant_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    current = next((v for v in template.versions if v.is_current), None)
    return _template_to_dict(template, current)


def _product_to_dict(p: BMProduct) -> dict[str, Any]:
    versions = []
    if p.versions:
        versions = [_version_to_dict(v) for v in p.versions]
    return {
        "id": p.id,
        "name": p.name,
        "display_name": p.display_name,
        "category": p.category,
        "description": p.description,
        "icon": p.icon,
        "default_ports": json.loads(p.default_ports) if p.default_ports else [],
        "cert_requirements": json.loads(p.cert_requirements) if p.cert_requirements else {},
        "dependencies": json.loads(p.dependencies) if p.dependencies else [],
        "deployment_targets": json.loads(p.deployment_targets) if p.deployment_targets else ["ec2"],
        "is_builtin": p.is_builtin,
        "version_count": len(versions),
        "versions": versions,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _version_to_dict(v: BMProductVersion) -> dict[str, Any]:
    return {
        "id": v.id,
        "product_id": v.product_id,
        "version": v.version,
        "ansible_role": v.ansible_role,
        "default_vars": json.loads(v.default_vars) if v.default_vars else {},
        "config_schema": json.loads(v.config_schema) if v.config_schema else [],
        "supported_os": json.loads(v.supported_os) if v.supported_os else [],
        "conflicts_with": json.loads(v.conflicts_with) if v.conflicts_with else [],
        "requires": json.loads(v.requires) if v.requires else [],
        "release_date": v.release_date,
        "eol_date": v.eol_date,
        "is_latest": v.is_latest,
        "aws_defaults": json.loads(v.aws_defaults) if v.aws_defaults else None,
    }


# ============================================================
# OPERATING SYSTEM CATALOGUE (Enhancement Plan Stage 6)
# ============================================================

class OSFamilyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, pattern="^[a-z0-9_.-]+$")
    display_name: str = Field(..., min_length=1, max_length=128)
    icon: str = Field(default="🐧", max_length=8)


class OSFamilyUpdate(BaseModel):
    display_name: str | None = None
    icon: str | None = None


class OSVersionCreate(BaseModel):
    version: str = Field(..., min_length=1, max_length=32)
    display_name: str = Field(..., min_length=1, max_length=64)
    eol_date: str | None = None
    is_latest: bool = False


class OSVersionUpdate(BaseModel):
    display_name: str | None = None
    eol_date: str | None = None
    is_latest: bool | None = None


@router.get("/os-catalogue")
async def list_os_families(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    from app.services.build_manager.os_catalogue_service import list_families
    return await list_families(db)


@router.get("/os-catalogue/{family_id}")
async def get_os_family(
    family_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    from app.services.build_manager.os_catalogue_service import get_family
    family = await get_family(db, family_id)
    if not family:
        raise HTTPException(status_code=404, detail="OS family not found")
    return family


@router.post("/os-catalogue", status_code=201)
async def create_os_family(
    body: OSFamilyCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, Any]:
    from app.services.build_manager.os_catalogue_service import get_family

    existing = await db.execute(select(BMOSFamily).where(BMOSFamily.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"OS family '{body.name}' already exists")

    family = BMOSFamily(
        id=str(uuid.uuid4()), name=body.name, display_name=body.display_name,
        icon=body.icon, origin="user",
    )
    db.add(family)
    await audit_event(
        db=db, event_type="BM_OS_FAMILY_CREATED", severity="INFO", request=request,
        subject_type="bm_os_family", subject_id=family.id,
        detail={"name": family.name},
        description=f"Build Manager OS family created: {family.name}",
    )
    await db.commit()
    return await get_family(db, family.id)


@router.put("/os-catalogue/{family_id}")
async def update_os_family(
    family_id: str,
    body: OSFamilyUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, Any]:
    from app.services.build_manager.os_catalogue_service import get_family

    result = await db.execute(select(BMOSFamily).where(BMOSFamily.id == family_id))
    family = result.scalar_one_or_none()
    if not family:
        raise HTTPException(status_code=404, detail="OS family not found")

    if body.display_name is not None:
        family.display_name = body.display_name
    if body.icon is not None:
        family.icon = body.icon

    await audit_event(
        db=db, event_type="BM_OS_FAMILY_UPDATED", severity="INFO", request=request,
        subject_type="bm_os_family", subject_id=family_id,
        detail={"name": family.name},
        description=f"Build Manager OS family updated: {family.name}",
    )
    await db.commit()
    return await get_family(db, family_id)


@router.delete("/os-catalogue/{family_id}", status_code=204)
async def delete_os_family(
    family_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> None:
    from app.services.build_manager.os_catalogue_service import family_in_use

    result = await db.execute(select(BMOSFamily).where(BMOSFamily.id == family_id))
    family = result.scalar_one_or_none()
    if not family:
        raise HTTPException(status_code=404, detail="OS family not found")
    if await family_in_use(db, family.name):
        raise HTTPException(status_code=409, detail="Cannot delete an OS family referenced by a host or template")

    await audit_event(
        db=db, event_type="BM_OS_FAMILY_DELETED", severity="WARNING", request=request,
        subject_type="bm_os_family", subject_id=family_id,
        detail={"name": family.name, "origin": family.origin},
        description=f"Build Manager OS family deleted: {family.name}",
    )
    await db.delete(family)
    await db.commit()


@router.post("/os-catalogue/{family_id}/versions", status_code=201)
async def add_os_version(
    family_id: str,
    body: OSVersionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, Any]:
    result = await db.execute(select(BMOSFamily).where(BMOSFamily.id == family_id))
    family = result.scalar_one_or_none()
    if not family:
        raise HTTPException(status_code=404, detail="OS family not found")

    if body.is_latest:
        others = await db.execute(select(BMOSVersion).where(BMOSVersion.os_family_id == family_id, BMOSVersion.is_latest == True))
        for other in others.scalars().all():
            other.is_latest = False

    version = BMOSVersion(
        id=str(uuid.uuid4()), os_family_id=family_id, version=body.version,
        display_name=body.display_name, eol_date=body.eol_date, is_latest=body.is_latest,
    )
    db.add(version)
    await audit_event(
        db=db, event_type="BM_OS_VERSION_CREATED", severity="INFO", request=request,
        subject_type="bm_os_version", subject_id=version.id,
        detail={"family": family.name, "version": version.version},
        description=f"Build Manager OS version created: {family.name} {version.version}",
    )
    await db.commit()
    return _os_version_to_dict(version)


@router.put("/os-catalogue/versions/{version_id}")
async def update_os_version(
    version_id: str,
    body: OSVersionUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, Any]:
    result = await db.execute(select(BMOSVersion).where(BMOSVersion.id == version_id))
    version = result.scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="OS version not found")

    if body.display_name is not None:
        version.display_name = body.display_name
    if body.eol_date is not None:
        version.eol_date = body.eol_date
    if body.is_latest is not None:
        if body.is_latest:
            others = await db.execute(
                select(BMOSVersion).where(BMOSVersion.os_family_id == version.os_family_id, BMOSVersion.is_latest == True, BMOSVersion.id != version_id)
            )
            for other in others.scalars().all():
                other.is_latest = False
        version.is_latest = body.is_latest

    await audit_event(
        db=db, event_type="BM_OS_VERSION_UPDATED", severity="INFO", request=request,
        subject_type="bm_os_version", subject_id=version_id,
        detail={"version": version.version},
        description=f"Build Manager OS version updated: {version_id}",
    )
    await db.commit()
    return _os_version_to_dict(version)


@router.delete("/os-catalogue/versions/{version_id}", status_code=204)
async def delete_os_version(
    version_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> None:
    from app.services.build_manager.os_catalogue_service import family_in_use

    result = await db.execute(
        select(BMOSVersion).options(selectinload(BMOSVersion.family)).where(BMOSVersion.id == version_id)
    )
    version = result.scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="OS version not found")
    if await family_in_use(db, version.family.name, version.version):
        raise HTTPException(status_code=409, detail="Cannot delete an OS version referenced by a host or template")

    await audit_event(
        db=db, event_type="BM_OS_VERSION_DELETED", severity="WARNING", request=request,
        subject_type="bm_os_version", subject_id=version_id,
        detail={"family": version.family.name, "version": version.version},
        description=f"Build Manager OS version deleted: {version.family.name} {version.version}",
    )
    await db.delete(version)
    await db.commit()


@router.post("/os-catalogue/seed")
async def seed_os_catalogue_endpoint(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, Any]:
    from app.services.build_manager.os_catalogue_service import seed_os_catalogue
    added = await seed_os_catalogue(db)
    return {"families_added": added}


def _os_version_to_dict(v: BMOSVersion) -> dict[str, Any]:
    return {
        "id": v.id,
        "os_family_id": v.os_family_id,
        "version": v.version,
        "display_name": v.display_name,
        "eol_date": v.eol_date,
        "is_latest": v.is_latest,
    }


# ============================================================
# PLATFORM DETECTION
# ============================================================


@router.get("/platform")
async def get_platform_info(
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """Detect deployment platform (docker, on-prem, aws)."""
    import os
    from pathlib import Path as _Path

    is_docker = _Path("/.dockerenv").exists() or os.environ.get("container") == "docker"

    # Check for AWS metadata (IMDSv2)
    is_aws = False
    if not is_docker:
        try:
            import httpx
            r = httpx.put(
                "http://169.254.169.254/latest/api/token",
                headers={"X-aws-ec2-metadata-token-ttl-seconds": "1"},
                timeout=1,
            )
            is_aws = r.status_code == 200
        except Exception as e:
            # Expected on every non-AWS host — debug only, not an error.
            logger.debug("AWS IMDS probe failed (expected off-EC2): %s", e)

    if is_docker:
        platform = "docker"
    elif is_aws:
        platform = "aws"
    else:
        platform = "on-prem"

    return {"platform": platform, "expose_ports_applicable": is_docker}


# ============================================================
# CA SELECTION FOR BUILD
# ============================================================


@router.get("/signing-cas")
async def list_signing_cas(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> list[dict[str, Any]]:
    """List CAs suitable for signing build manager certs, with recommendation."""
    from app.models.ca import CertificateAuthority
    from cryptography import x509 as cx509
    from datetime import datetime, timezone

    result = await db.execute(select(CertificateAuthority))
    all_cas = result.scalars().all()

    now = datetime.now(timezone.utc)
    candidates = []

    for ca in all_cas:
        # Must have a signing key
        if not ca.key_blob:
            continue
        # Must not be expired
        if ca.expires_at and ca.expires_at.replace(tzinfo=timezone.utc) < now:
            continue

        # Parse Name Constraints
        name_constraints = None
        warnings = []
        try:
            ca_cert = cx509.load_pem_x509_certificate(ca.cert_pem.encode())
            try:
                nc_ext = ca_cert.extensions.get_extension_for_class(cx509.NameConstraints)
                permitted = nc_ext.value.permitted_subtrees or []
                if permitted:
                    patterns = []
                    for subtree in permitted:
                        try:
                            patterns.append(subtree.value.value)
                        except (AttributeError, TypeError):
                            try:
                                patterns.append(subtree.value)
                            except (AttributeError, TypeError):
                                patterns.append(str(subtree))
                    name_constraints = patterns
                    if patterns:
                        warnings.append(f"Name Constraints: only permits {', '.join(str(p) for p in patterns)}")
                    else:
                        warnings.append("Has Name Constraints (restricts issuance)")
            except cx509.ExtensionNotFound:
                pass
        except Exception:
            logger.exception("Could not parse certificate while checking CA signing capability")
            warnings.append("Could not parse certificate")
            continue

        # Determine if this CA can sign for localhost/arbitrary hostnames
        can_sign_any = name_constraints is None

        candidates.append({
            "id": ca.id,
            "cn": ca.cn if hasattr(ca, 'cn') else "",
            "is_root": ca.parent_ca_id is None,
            "key_algo": ca.key_algo,
            "key_size": ca.key_size,
            "expires_at": ca.expires_at.isoformat() if ca.expires_at else None,
            "name_constraints": name_constraints,
            "can_sign_any": can_sign_any,
            "warnings": warnings,
            "cert_count": ca.cert_count if hasattr(ca, 'cert_count') else 0,
        })

    # Score and sort: prefer intermediates without constraints, then roots without constraints
    for c in candidates:
        score = 0
        if c["can_sign_any"]:
            score += 10
        if not c["is_root"]:
            score += 5  # prefer intermediates
        c["score"] = score

    candidates.sort(key=lambda x: x["score"], reverse=True)

    # Mark the top scorer as recommended
    if candidates:
        candidates[0]["recommended"] = True
    for c in candidates[1:]:
        c["recommended"] = False

    return candidates


# ============================================================
# TLS VERIFICATION
# ============================================================


@router.post("/environments/{env_id}/verify")
async def verify_environment_tls(
    env_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Run TLS verification checks on all products in the environment."""
    from app.services.build_manager.ansible_runner import submit_job

    result = await db.execute(
        select(BMEnvironment).options(selectinload(BMEnvironment.template))
        .where(BMEnvironment.id == env_id)
    )
    env = result.scalar_one_or_none()
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")
    if env.status not in ("active", "degraded", "failed"):
        raise HTTPException(status_code=409, detail=f"Cannot verify environment in '{env.status}' state")

    # Build extra_vars with host_products (needed by verify.yml)
    variables = json.loads(env.variables) if env.variables else {}
    ver_result = await db.execute(
        select(BMTemplateVersion).where(
            BMTemplateVersion.template_id == env.template_id,
            BMTemplateVersion.version == env.template_version,
        )
    )
    version = ver_result.scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="Template version not found")

    spec = json.loads(version.spec)
    host_products = {}
    for host_def in spec.get("hosts", []):
        role = host_def["role"]
        products = host_def.get("products", [])
        if products:
            from app.services.build_manager.base_provisioner import _get_product_config
            host_products[role] = [
                {
                    "ansible_role": p.get("ansible_role", p.get("product_name", p.get("product", ""))),
                    "vars": {**p.get("vars", {}), **_get_product_config(variables, role, p.get("ansible_role", p.get("product_name", p.get("product", ""))))},
                }
                for p in products
                if p.get("ansible_role") or p.get("product_name") or p.get("product")
            ]

    extra_vars = {
        "host_products": host_products,
        "environment_id": env_id,
    }

    job = await submit_job(
        db, name=f"TLS Verify: {env.name}",
        playbook="verify.yml", job_type="verify",
        environment_id=env.id,
        extra_vars=extra_vars,
        created_by=auth.username, tenant_id=auth.tenant_id,
    )
    return {"environment_id": env.id, "job_id": job.id, "status": "running"}


@router.get("/environments/{env_id}/verify-results")
async def get_verify_results(
    env_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """Parse TLS verification results from the most recent verify job."""
    # Find the latest verify job for this environment
    result = await db.execute(
        select(BMJob)
        .where(BMJob.environment_id == env_id, BMJob.job_type == "verify")
        .order_by(BMJob.created_at.desc())
        .limit(1)
    )
    job = result.scalar_one_or_none()
    if not job:
        return {"available": False, "message": "No verification has been run yet"}

    if job.status == "running" or job.status == "pending":
        return {"available": False, "status": job.status, "job_id": job.id, "message": "Verification in progress"}

    # Parse TLS_RESULT lines from job output
    log_result = await db.execute(
        select(BMJobLog).where(BMJobLog.job_id == job.id).order_by(BMJobLog.timestamp)
    )
    logs = log_result.scalars().all()

    results = []
    current_host = ""
    for log in logs:
        line = log.line or ""
        # Parse host from "ok: [hostname]" lines
        if line.startswith("ok: [") or line.startswith("changed: ["):
            host_match = re.match(r"(?:ok|changed): \[([^\]]+)\]", line)
            if host_match:
                current_host = host_match.group(1)
        # Parse TLS_RESULT JSON from debug output (may appear in various formats)
        if "TLS_RESULT:" in line:
            # Extract all TLS_RESULT occurrences from the line
            for match in re.finditer(r'TLS_RESULT:(\{[^}]+\})', line):
                try:
                    raw = match.group(1)
                    # Ansible debug output stores escaped quotes as \"
                    unescaped = raw.replace('\\"', '"')
                    data = json.loads(unescaped)
                    data["host"] = current_host
                    results.append(data)
                except json.JSONDecodeError:
                    pass

    # Summary
    total = len(results)
    passed = sum(1 for r in results if r.get("status") == "ok")
    failed = sum(1 for r in results if r.get("status") == "failed")
    warnings = sum(1 for r in results if r.get("status") == "warning")

    return {
        "available": True,
        "job_id": job.id,
        "job_status": job.status,
        "ran_at": job.finished_at.isoformat() if job.finished_at else None,
        "summary": {"total": total, "passed": passed, "failed": failed, "warnings": warnings},
        "results": results,
    }


# ============================================================
# ORCHESTRATOR & DASHBOARD
# ============================================================


@router.get("/dashboard-stats")
async def get_dashboard_stats_endpoint(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
):
    """Aggregated stats for the Build Manager dashboard."""
    from app.services.build_manager.orchestrator import get_dashboard_stats
    return await get_dashboard_stats(db)


@router.get("/environments/{environment_id}/execution-order")
async def get_execution_order(
    environment_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
):
    """Get the DAG execution order for an environment's products."""
    from app.services.build_manager.orchestrator import build_execution_dag, get_dependency_catalogue

    result = await db.execute(
        select(BMEnvironment).where(BMEnvironment.id == environment_id)
    )
    env = result.scalar_one_or_none()
    if not env:
        raise HTTPException(404, "Environment not found")

    ver_result = await db.execute(
        select(BMTemplateVersion).where(
            BMTemplateVersion.template_id == env.template_id,
            BMTemplateVersion.version == env.template_version,
        )
    )
    version = ver_result.scalar_one_or_none()
    if not version:
        raise HTTPException(404, "Template version not found")

    spec = json.loads(version.spec)
    catalogue = await get_dependency_catalogue(db)
    dag = build_execution_dag(spec, catalogue)
    return dag


@router.get("/catalogue/defaults/{product_name}")
async def get_product_defaults(
    product_name: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
):
    """Get default vars and config schema for a product (latest version)."""
    result = await db.execute(
        select(BMProductVersion)
        .options(selectinload(BMProductVersion.product))
        .join(BMProduct)
        .where(BMProduct.name == product_name, BMProductVersion.is_latest == True)
    )
    pv = result.scalar_one_or_none()
    if not pv:
        raise HTTPException(404, f"Product '{product_name}' not found")

    return {
        "product": pv.product.name,
        "display_name": pv.product.display_name,
        "version": pv.version,
        "ansible_role": pv.ansible_role,
        "default_vars": json.loads(pv.default_vars) if pv.default_vars else {},
        "config_schema": json.loads(pv.config_schema) if pv.config_schema else [],
        "default_ports": json.loads(pv.product.default_ports) if pv.product.default_ports else [],
        "cert_requirements": json.loads(pv.product.cert_requirements) if pv.product.cert_requirements else {},
        "dependencies": json.loads(pv.product.dependencies) if pv.product.dependencies else [],
    }


# ============================================================
# HELP
# ============================================================


# ============================================================
# CERTIFICATE LIFECYCLE (Stage 11)
# ============================================================


@router.get("/certs/bindings")
async def list_cert_bindings(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    """List all cert bindings across environments."""
    from app.services.build_manager.cert_lifecycle import list_all_bindings
    return await list_all_bindings(db)


@router.get("/certs/expiring")
async def list_expiring_certs(
    days: int = Query(default=30, le=365),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    """List cert bindings expiring within threshold (active environments only)."""
    from app.services.build_manager.cert_lifecycle import get_expiring_bindings
    return await get_expiring_bindings(db, days)


@router.get("/pki-posture")
async def get_pki_posture_endpoint(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """PKI posture dashboard (Enhancement Plan Stage 11) — aggregates cert/CA
    chain topology, expiry risk, key strength, auto-renew status, and secret
    rotation staleness across every non-destroyed environment into a single
    view. Pure aggregation over existing facts, no new data model."""
    from app.services.build_manager.pki_posture_service import get_pki_posture
    return await get_pki_posture(db)


@router.get("/pki-posture/export/json")
async def export_pki_posture_json(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> Response:
    """One-click compliance export (Enhancement Plan Stage 12) — same data
    as GET /pki-posture, as a downloadable attachment rather than an inline
    API response."""
    import json
    from app.services.build_manager.pki_posture_service import get_pki_posture
    posture = await get_pki_posture(db)
    return Response(
        content=json.dumps(posture, indent=2), media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="pki-compliance-report.json"'},
    )


@router.get("/pki-posture/export/csv")
async def export_pki_posture_csv(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> PlainTextResponse:
    from app.services.build_manager.pki_posture_service import get_pki_posture
    from app.services.build_manager.compliance_export import posture_to_csv
    posture = await get_pki_posture(db)
    return PlainTextResponse(
        content=posture_to_csv(posture), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="pki-compliance-report.csv"'},
    )


@router.get("/pki-posture/export/markdown")
async def export_pki_posture_markdown(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> PlainTextResponse:
    from app.services.build_manager.pki_posture_service import get_pki_posture
    from app.services.build_manager.compliance_export import posture_to_markdown
    posture = await get_pki_posture(db)
    return PlainTextResponse(
        content=posture_to_markdown(posture), media_type="text/markdown",
        headers={"Content-Disposition": 'attachment; filename="pki-compliance-report.md"'},
    )


@router.get("/pki-posture/export/pdf")
async def export_pki_posture_pdf(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> Response:
    from app.services.build_manager.pki_posture_service import get_pki_posture
    from app.services.build_manager.compliance_export import posture_to_pdf
    posture = await get_pki_posture(db)
    return Response(
        content=posture_to_pdf(posture), media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="pki-compliance-report.pdf"'},
    )


@router.get("/environments/{env_id}/bindings")
async def list_env_bindings(
    env_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    """List cert bindings for a specific environment."""
    from app.services.build_manager.cert_lifecycle import list_environment_bindings
    return await list_environment_bindings(db, env_id)


@router.post("/certs/bindings/{binding_id}/renew")
async def renew_cert_binding(
    binding_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Manually renew a cert binding — re-issue with same CN/SANs."""
    from app.services.build_manager.cert_lifecycle import renew_binding
    try:
        result = await renew_binding(db, binding_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await audit_event(
        db=db, event_type="BM_CERT_BINDING_RENEWED", severity="INFO", request=request,
        subject_type="bm_cert_binding", subject_id=binding_id,
        detail={},
        description=f"Build Manager cert binding renewed: {binding_id}",
    )
    await db.commit()
    return result


@router.post("/certs/bindings/{binding_id}/rotate")
async def rotate_cert_binding(
    binding_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Rotate a cert binding — new key pair + new cert."""
    from app.services.build_manager.cert_lifecycle import rotate_binding
    try:
        result = await rotate_binding(db, binding_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await audit_event(
        db=db, event_type="BM_CERT_BINDING_ROTATED", severity="WARNING", request=request,
        subject_type="bm_cert_binding", subject_id=binding_id,
        detail={},
        description=f"Build Manager cert binding rotated: {binding_id}",
    )
    await db.commit()
    return result


@router.patch("/certs/bindings/{binding_id}/auto-renew")
async def toggle_binding_auto_renew(
    binding_id: str,
    request: Request,
    enabled: bool = Query(...),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Toggle auto-renew for a cert binding."""
    from app.services.build_manager.cert_lifecycle import toggle_auto_renew
    try:
        result = await toggle_auto_renew(db, binding_id, enabled)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await audit_event(
        db=db, event_type="BM_CERT_AUTO_RENEW_TOGGLED", severity="INFO", request=request,
        subject_type="bm_cert_binding", subject_id=binding_id,
        detail={"enabled": enabled},
        description=f"Build Manager cert binding auto-renew set to {enabled}: {binding_id}",
    )
    await db.commit()
    return result


@router.post("/certs/auto-renew-check")
async def trigger_auto_renew_check(
    request: Request,
    threshold_days: int = Query(default=30, le=365),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Manually trigger the auto-renewal check for all expiring bindings."""
    from app.services.build_manager.cert_lifecycle import check_and_auto_renew
    renewed = await check_and_auto_renew(db, threshold_days)
    await audit_event(
        db=db, event_type="BM_AUTO_RENEW_CHECK_TRIGGERED", severity="INFO", request=request,
        subject_type="bm_cert_binding", subject_id="bulk",
        detail={"threshold_days": threshold_days, "renewed_count": len(renewed)},
        description=f"Build Manager bulk auto-renew check triggered, {len(renewed)} bindings renewed",
    )
    await db.commit()
    return {"renewed_count": len(renewed), "renewed": renewed}

# ============================================================
# SECRETS MANAGEMENT (Stage 12)
# ============================================================


class SecretCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    value: str = Field(..., min_length=1)
    category: str = Field(default="custom")
    linked_service: str = Field(default="")
    description: str = Field(default="")
    rotate_every_days: int | None = Field(default=None, gt=0, description="Optional rotation policy — flags the secret as overdue in the UI and fires one notification, never auto-rotates")


class SecretUpdate(BaseModel):
    value: str | None = None
    category: str | None = None
    linked_service: str | None = None
    description: str | None = None
    rotate_every_days: int | None = Field(default=None, gt=0)
    clear_rotation_policy: bool = Field(default=False, description="Set true to remove an existing rotation policy (rotate_every_days is otherwise ignored if omitted)")


@router.get("/secrets")
async def list_secrets_endpoint(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> list[dict[str, Any]]:
    """List all secrets (names only, no values)."""
    from app.services.build_manager.secrets_service import list_secrets
    return await list_secrets(db)


@router.get("/secrets/{secret_id}")
async def get_secret_endpoint(
    secret_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Retrieve a secret including decrypted value (admin only)."""
    from app.services.build_manager.secrets_service import get_secret
    try:
        return await get_secret(db, secret_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/secrets")
async def create_secret_endpoint(
    body: SecretCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Store a new encrypted secret."""
    from app.services.build_manager.secrets_service import create_secret
    try:
        result = await create_secret(
            db, name=body.name, value=body.value, category=body.category,
            linked_service=body.linked_service, description=body.description,
            created_by=auth.username, tenant_id=auth.tenant_id,
            rotate_every_days=body.rotate_every_days,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    # Never log the secret value itself, only identifying metadata.
    await audit_event(
        db=db, event_type="BM_SECRET_CREATED", severity="INFO", request=request,
        subject_type="bm_secret", subject_id=result["id"],
        detail={"name": body.name, "category": body.category},
        description=f"Build Manager secret created: {body.name}",
    )
    await db.commit()
    return result


@router.put("/secrets/{secret_id}")
async def update_secret_endpoint(
    secret_id: str,
    body: SecretUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Update a secret's value or metadata."""
    from app.services.build_manager.secrets_service import update_secret
    try:
        result = await update_secret(
            db, secret_id, value=body.value, category=body.category,
            linked_service=body.linked_service, description=body.description,
            rotate_every_days=body.rotate_every_days,
            rotate_every_days_set=(body.rotate_every_days is not None or body.clear_rotation_policy),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await audit_event(
        db=db, event_type="BM_SECRET_UPDATED", severity="INFO", request=request,
        subject_type="bm_secret", subject_id=secret_id,
        detail={"name": result["name"], "value_changed": body.value is not None},
        description=f"Build Manager secret updated: {result['name']}",
    )
    await db.commit()
    return result


@router.post("/secrets/{secret_id}/rotate")
async def rotate_secret_endpoint(
    secret_id: str,
    body: SecretCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Rotate a secret (provide new value)."""
    from app.services.build_manager.secrets_service import rotate_secret
    try:
        result = await rotate_secret(db, secret_id, body.value)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await audit_event(
        db=db, event_type="BM_SECRET_ROTATED", severity="WARNING", request=request,
        subject_type="bm_secret", subject_id=secret_id,
        detail={"name": result["name"]},
        description=f"Build Manager secret rotated: {result['name']}",
    )
    await db.commit()
    return result


@router.delete("/secrets/{secret_id}")
async def delete_secret_endpoint(
    secret_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, str]:
    """Delete a secret."""
    from app.services.build_manager.secrets_service import delete_secret
    result = await db.execute(select(BMSecret.name).where(BMSecret.id == secret_id))
    secret_name = result.scalar_one_or_none()
    if secret_name is None:
        raise HTTPException(status_code=404, detail="Secret not found")
    try:
        await delete_secret(db, secret_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await audit_event(
        db=db, event_type="BM_SECRET_DELETED", severity="WARNING", request=request,
        subject_type="bm_secret", subject_id=secret_id,
        detail={"name": secret_name},
        description=f"Build Manager secret deleted: {secret_name}",
    )
    await db.commit()
    return {"status": "deleted"}


# ============================================================
# HEALTH & OBSERVABILITY (Stage 13)
# ============================================================


@router.get("/health/all")
async def get_all_health_endpoint(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    """Get health check results across all active environments."""
    from app.services.build_manager.health_service import get_all_health
    return await get_all_health(db)


@router.get("/environments/{env_id}/health")
async def get_env_health(
    env_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    """Get cached health results for a specific environment."""
    from app.services.build_manager.health_service import get_health_results
    return await get_health_results(db, env_id)


@router.post("/environments/{env_id}/health-check")
async def trigger_health_check(
    env_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Trigger health checks for all hosts in an environment."""
    from app.services.build_manager.health_service import run_health_checks
    try:
        results = await run_health_checks(db, env_id)
        healthy = sum(1 for r in results if r["status"] == "healthy")
        return {"total": len(results), "healthy": healthy, "degraded": len(results) - healthy, "results": results}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/environments/{env_id}/drift")
async def get_drift_report_endpoint(
    env_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """Get drift report — compare deployed state vs template spec."""
    from app.services.build_manager.health_service import get_drift_report
    try:
        return await get_drift_report(db, env_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ============================================================
# HELP (continued)
# ============================================================

from pathlib import Path

# Registry of all help guides.  Each entry: id (used in ?guide= param),
# label (shown in the UI tab), filename (under Documentation/).
_HELP_GUIDES = [
    {"id": "bm",  "label": "Build Manager", "filename": "build_manager_operations_guide.md"},
    {"id": "aws", "label": "AWS",           "filename": "build_manager_operations_guide-aws.md"},
]


def _doc_root() -> Path:
    candidates = [
        Path(__file__).resolve().parent.parent.parent.parent / "Documentation",
        Path("/opt/certmanager/Documentation"),
    ]
    for p in candidates:
        if p.is_dir():
            return p
    return candidates[0]


def _parse_sections(content: str) -> list[dict]:
    """Parse ## headings into section dicts with id/title/content."""
    sections: list[dict] = []
    current: dict | None = None
    fallback = 100

    for line in content.split("\n"):
        m = re.match(r"^## (\d+)\.\s+(.+)$", line)
        if m:
            if current:
                sections.append(current)
            current = {"id": m.group(1), "title": m.group(2).strip(), "content": ""}
            continue
        m2 = re.match(r"^## (.+)$", line)
        if m2:
            if current:
                sections.append(current)
            fallback += 1
            current = {"id": str(fallback), "title": m2.group(1).strip(), "content": ""}
            continue
        if current:
            current["content"] += line + "\n"

    if current:
        sections.append(current)
    return sections


@router.get("/help/guides")
async def list_help_guides(
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict]:
    """List all available help guides with availability status."""
    doc_root = _doc_root()
    return [
        {
            "id": g["id"],
            "label": g["label"],
            "available": (doc_root / g["filename"]).exists(),
        }
        for g in _HELP_GUIDES
    ]


@router.get("/help/sections")
async def get_bm_help_sections(
    guide: str = Query(default="bm", description="Guide ID — see GET /help/guides"),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict:
    guide_meta = next((g for g in _HELP_GUIDES if g["id"] == guide), None)
    if not guide_meta:
        return {"available": False, "guide": guide, "sections": [], "error": f"Unknown guide '{guide}'"}
    path = _doc_root() / guide_meta["filename"]
    if not path.exists():
        return {"available": False, "guide": guide, "sections": [], "error": f"{guide_meta['filename']} not found"}
    sections = _parse_sections(path.read_text(encoding="utf-8"))
    return {
        "available": True,
        "guide": guide,
        "label": guide_meta["label"],
        "total_sections": len(sections),
        "sections": [{"id": s["id"], "title": s["title"]} for s in sections],
    }


@router.get("/help/sections/{section_id}")
async def get_bm_help_section(
    section_id: str,
    guide: str = Query(default="bm", description="Guide ID — see GET /help/guides"),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict:
    guide_meta = next((g for g in _HELP_GUIDES if g["id"] == guide), None)
    if not guide_meta:
        return {"available": False, "content": "", "error": f"Unknown guide '{guide}'"}
    path = _doc_root() / guide_meta["filename"]
    if not path.exists():
        return {"available": False, "content": "", "error": f"{guide_meta['filename']} not found"}
    sections = _parse_sections(path.read_text(encoding="utf-8"))
    for s in sections:
        if s["id"] == section_id:
            return {"available": True, "guide": guide, "id": s["id"], "title": s["title"], "content": s["content"].strip()}
    return {"available": False, "content": "", "error": f"Section {section_id} not found in guide '{guide}'"}


# ============================================================
# CONFIG EDITOR (Stage 1)
# ============================================================


@router.get("/editor/files")
async def list_editor_files(
    category: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> list[dict[str, Any]]:
    """List all registered config files with metadata."""
    from app.services.build_manager.config_editor_service import list_files
    return await list_files(db, category)


@router.get("/editor/files/{file_id}")
async def read_editor_file(
    file_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Read file content + metadata."""
    from app.services.build_manager.config_editor_service import read_file
    try:
        return await read_file(db, file_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/editor/files/{file_id}/metadata")
async def get_editor_file_metadata(
    file_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Get file metadata without content."""
    from app.services.build_manager.config_editor_service import get_file_metadata
    try:
        return await get_file_metadata(db, file_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/editor/seed")
async def seed_editor_registry(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Seed the file registry with known config files."""
    from app.services.build_manager.config_editor_service import seed_file_registry
    count = await seed_file_registry(db)
    return {"files_added": count}


@router.put("/editor/files/{file_id}")
async def save_editor_file(
    file_id: str,
    request: Request,
    content: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Save file content (validates first, creates backup)."""
    from app.services.build_manager.config_editor_service import save_file
    try:
        result = await save_file(db, file_id, content, auth.username)
        if not result["saved"]:
            raise HTTPException(status_code=422, detail={"errors": result["errors"]})
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    path_result = await db.execute(select(BMConfigFile.path).where(BMConfigFile.id == file_id))
    file_path = path_result.scalar_one_or_none() or file_id
    await audit_event(
        db=db, event_type="BM_CONFIG_FILE_SAVED", severity="WARNING", request=request,
        subject_type="bm_config_file", subject_id=file_id,
        detail={"path": file_path, "version": result.get("version")},
        description=f"Build Manager config file saved: {file_path}",
    )
    await db.commit()
    return result


@router.post("/editor/files/{file_id}/validate")
async def validate_editor_file(
    file_id: str,
    content: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Validate file content without saving."""
    from app.services.build_manager.config_editor_service import validate_file
    try:
        return await validate_file(db, file_id, content)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/editor/files/{file_id}/history")
async def get_editor_file_history(
    file_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> list[dict[str, Any]]:
    """List version history for a file."""
    from app.services.build_manager.config_editor_service import get_file_history
    return await get_file_history(db, file_id)


@router.get("/editor/files/{file_id}/history/{version}")
async def get_editor_file_version(
    file_id: str,
    version: int,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Get a specific version's content."""
    from app.services.build_manager.config_editor_service import get_file_version
    try:
        return await get_file_version(db, file_id, version)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/editor/files/{file_id}/restore/{version}")
async def restore_editor_file_version(
    file_id: str,
    version: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Restore a file to a previous version."""
    from app.services.build_manager.config_editor_service import restore_file
    try:
        result = await restore_file(db, file_id, version, auth.username)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    path_result = await db.execute(select(BMConfigFile.path).where(BMConfigFile.id == file_id))
    file_path = path_result.scalar_one_or_none() or file_id
    await audit_event(
        db=db, event_type="BM_CONFIG_FILE_RESTORED", severity="WARNING", request=request,
        subject_type="bm_config_file", subject_id=file_id,
        detail={"path": file_path, "restored_from_version": version},
        description=f"Build Manager config file restored to version {version}: {file_path}",
    )
    await db.commit()
    return result


@router.get("/editor/files/{file_id}/diff")
async def diff_editor_file_versions(
    file_id: str,
    v1: int = Query(...),
    v2: int = Query(...),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Get unified diff between two versions."""
    from app.services.build_manager.config_editor_service import diff_versions
    try:
        return await diff_versions(db, file_id, v1, v2)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/editor/files/{file_id}/help")
async def get_editor_file_help(
    file_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Get contextual help for a file."""
    from app.services.build_manager.config_editor_service import read_file
    from app.services.build_manager.config_editor_help import get_file_help
    try:
        file_data = await read_file(db, file_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return get_file_help(file_data["path"])



# CONFIG EDITOR — SCAFFOLDS (Stage 6)

@router.get("/editor/scaffolds")
async def list_editor_scaffolds(
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> list[dict[str, Any]]:
    """List available file scaffolds."""
    from app.services.build_manager.config_editor_scaffolds import list_scaffolds
    return list_scaffolds()


@router.post("/editor/scaffolds/{scaffold_id}/create")
async def create_from_editor_scaffold(
    scaffold_id: str,
    request: Request,
    variables: dict[str, str] = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Create files from a scaffold template."""
    from app.services.build_manager.config_editor_scaffolds import create_from_scaffold
    try:
        result = await create_from_scaffold(db, scaffold_id, variables)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await audit_event(
        db=db, event_type="BM_CONFIG_FILE_SCAFFOLDED", severity="INFO", request=request,
        subject_type="bm_config_file", subject_id=scaffold_id,
        detail={"scaffold_id": scaffold_id, "files_created": result.get("files_created")},
        description=f"Build Manager files created from scaffold: {scaffold_id}",
    )
    await db.commit()
    return result


# CONFIG EDITOR — FILE ACTIONS (Stage 7)

@router.get("/editor/files/{file_id}/actions")
async def get_editor_file_actions(
    file_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> list[dict[str, Any]]:
    """Get available post-save actions for a file."""
    from app.services.build_manager.config_editor_actions import get_file_actions
    try:
        return await get_file_actions(db, file_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/editor/files/{file_id}/actions/{action_id}")
async def execute_editor_file_action(
    file_id: str,
    action_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Execute a post-save action on a file."""
    from app.services.build_manager.config_editor_actions import execute_action
    try:
        result = await execute_action(db, file_id, action_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await audit_event(
        db=db, event_type="BM_CONFIG_FILE_ACTION_EXECUTED", severity="WARNING", request=request,
        subject_type="bm_config_file", subject_id=file_id,
        detail={"action_id": action_id},
        description=f"Build Manager config file action '{action_id}' executed on file {file_id}",
    )
    await db.commit()
    return result


# ============================================================
# PACKAGE CACHE
# ============================================================

@router.get("/pkg-cache/status")
async def get_pkg_cache_status(
    auth: AuthContext = Depends(require_role("admin", "operator")),
):
    """Return current package cache status for all OS families."""
    from app.services.build_manager.pkg_cache_service import get_cache_status
    return get_cache_status()


@router.post("/pkg-cache/sync")
async def sync_pkg_cache(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
    ubuntu_host: str = Body("", embed=True),
    rhel_host: str = Body("", embed=True),
    alpine_host: str = Body("", embed=True),
):
    """Submit a package cache sync job for one or more OS families.
    Pass inventory hostnames for each OS family to sync.
    Omit a host to skip that OS family (binaries are always synced).
    """
    from app.services.build_manager.pkg_cache_service import submit_cache_sync
    job = await submit_cache_sync(
        db,
        created_by=auth.username,
        ubuntu_host=ubuntu_host,
        rhel_host=rhel_host,
        alpine_host=alpine_host,
    )
    return {"job_id": job.id, "status": job.status, "message": f"Package cache sync job submitted: {job.name}"}


# ---------------------------------------------------------------------------
# AWS Credential Management
# ---------------------------------------------------------------------------

class AwsCredentialsBody(BaseModel):
    access_key_id: str = Field(..., min_length=1)
    secret_access_key: str = Field(..., min_length=1)
    session_token: str = Field(default="")
    region: str = Field(default="eu-west-2")


@router.post("/aws/credentials", status_code=204)
async def set_aws_credentials(
    body: AwsCredentialsBody,
    auth: AuthContext = Depends(require_role("admin", "operator")),
):
    """Store STS temporary credentials in memory (never persisted to DB)."""
    from app.services.build_manager.aws_credentials import set_credentials
    set_credentials(
        access_key_id=body.access_key_id,
        secret_access_key=body.secret_access_key,
        session_token=body.session_token,
        region=body.region,
    )


@router.delete("/aws/credentials", status_code=204)
async def clear_aws_credentials(
    auth: AuthContext = Depends(require_role("admin", "operator")),
):
    """Wipe stored AWS credentials from memory."""
    from app.services.build_manager.aws_credentials import clear_credentials
    clear_credentials()


@router.post("/aws/validate-credentials")
async def validate_aws_credentials(
    auth: AuthContext = Depends(require_role("admin", "operator")),
):
    """Validate stored credentials via STS get-caller-identity."""
    from app.services.build_manager.aws_credentials import validate_credentials
    result = validate_credentials()
    if not result["valid"]:
        raise HTTPException(400, detail=result.get("error", "Credential validation failed"))
    return result


@router.get("/aws/credential-status")
async def get_aws_credential_status(
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
):
    """Return current credential status without re-validating."""
    from app.services.build_manager.aws_credentials import get_status
    return get_status()


# ---------------------------------------------------------------------------
# AWS Environment Lifecycle (OpenTofu)
# ---------------------------------------------------------------------------

async def _get_aws_env(db: AsyncSession, env_id: str) -> tuple:
    """Return (BMEnvironment, spec_dict, aws_config_dict) or raise 404/400."""
    from sqlalchemy import select
    from app.models.build_manager import BMEnvironment, BMTemplateVersion

    result = await db.execute(select(BMEnvironment).where(BMEnvironment.id == env_id))
    env = result.scalar_one_or_none()
    if not env:
        raise HTTPException(404, "Environment not found")

    ver = await db.execute(
        select(BMTemplateVersion).where(
            BMTemplateVersion.template_id == env.template_id,
            BMTemplateVersion.version == env.template_version,
        )
    )
    version = ver.scalar_one_or_none()
    if not version:
        raise HTTPException(404, "Template version not found")

    spec = json.loads(version.spec)
    aws = spec.get("aws")
    if not aws:
        raise HTTPException(400, "Not an AWS environment — template spec has no 'aws' block")

    return env, spec, aws


def _require_aws_credentials():
    """Raise 400 if no valid AWS credentials are stored."""
    from app.services.build_manager.aws_credentials import get_status
    status = get_status()
    if not status.get("valid"):
        raise HTTPException(400, "AWS credentials not configured or not validated — paste credentials first")
    return status


async def _check_signing_ca(db: AsyncSession, spec: dict, env_variables: dict) -> None:
    """Step 3.4 - verify a usable signing CA exists before tofu plan.

    Raises HTTPException(422) if no CA is available or the explicitly
    configured ca_id is invalid/expired.
    """
    from app.models.ca import CertificateAuthority
    from datetime import datetime, timezone

    ca_id = env_variables.get("signing_ca_id") or spec.get("certificates", {}).get("ca_id")
    now = datetime.now(timezone.utc)

    if ca_id:
        result = await db.execute(select(CertificateAuthority).where(CertificateAuthority.id == ca_id))
        ca = result.scalar_one_or_none()
        if not ca:
            raise HTTPException(422, f"Signing CA '{ca_id}' not found - update the environment signing_ca_id variable")
        if not ca.key_blob:
            raise HTTPException(422, f"Signing CA '{ca_id}' has no private key - cannot issue certificates")
        expires = ca.expires_at
        if expires:
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires < now:
                raise HTTPException(422, f"Signing CA '{ca_id}' is expired - select a valid CA")
    else:
        result = await db.execute(select(CertificateAuthority))
        cas = result.scalars().all()
        usable = [
            ca for ca in cas
            if ca.key_blob and (
                not ca.expires_at or
                (ca.expires_at.replace(tzinfo=timezone.utc) if ca.expires_at.tzinfo is None else ca.expires_at) > now
            )
        ]
        if not usable:
            raise HTTPException(
                422,
                "No usable signing CA found - create a CA in SSL Cert Manager first, "
                "then set signing_ca_id in the environment variables",
            )


@router.post("/environments/{env_id}/plan", status_code=202)
async def plan_environment(
    env_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
):
    """Run tofu init + tofu plan for an AWS environment (no changes applied)."""
    from app.services.build_manager.aws_credentials import get_status
    from app.services.build_manager.tofu_workspace import init_workspace, write_var_file, get_workspace_dir
    from app.services.build_manager.tofu_template_generator import generate_tf_files
    from app.services.build_manager.tofu_runner import submit_tofu_job, TOFU_PLAN_TIMEOUT

    cred_status = _require_aws_credentials()
    env, spec, aws = await _get_aws_env(db, env_id)

    # Step 3.4 - CA pre-flight check
    env_variables = json.loads(env.variables) if env.variables else {}
    await _check_signing_ca(db, spec, env_variables)

    ssh_public_key = Path("/data/ssh/id_ed25519.pub").read_text().strip()
    account_id = cred_status.get("account_id", "")

    tf_files = generate_tf_files(spec, env.name, ssh_public_key, account_id)
    workspace = init_workspace(env.name, tf_files)

    # tofu init then tofu plan chained as a single job via shell -c
    cmd = [
        "sh", "-c",
        f"tofu init -input=false && tofu plan -input=false -out={workspace}/tfplan"
    ]
    job = await submit_tofu_job(
        db=db,
        name=f"Plan: {env.name}",
        job_type="tofu_plan",
        environment_id=env_id,
        workspace_dir=workspace,
        tofu_cmd=cmd,
        created_by=auth.username,
        timeout_seconds=TOFU_PLAN_TIMEOUT,
    )
    return {"job_id": job.id, "status": job.status}


@router.post("/environments/{env_id}/apply", status_code=202)
async def apply_environment(
    env_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
):
    """Run tofu apply using the saved plan for an AWS environment."""
    from app.services.build_manager.tofu_workspace import get_workspace_dir, plan_exists
    from app.services.build_manager.tofu_runner import submit_tofu_job, TOFU_APPLY_TIMEOUT

    _require_aws_credentials()
    env, spec, aws = await _get_aws_env(db, env_id)

    workspace = get_workspace_dir(env.name)
    if not workspace.exists():
        raise HTTPException(400, "No workspace found — run Plan first")
    if not plan_exists(env.name):
        raise HTTPException(400, "No saved plan found — run Plan first")

    cmd = ["tofu", "apply", "-input=false", "-auto-approve", str(workspace / "tfplan")]
    job = await submit_tofu_job(
        db=db,
        name=f"Apply: {env.name}",
        job_type="tofu_apply",
        environment_id=env_id,
        workspace_dir=workspace,
        tofu_cmd=cmd,
        created_by=auth.username,
        timeout_seconds=TOFU_APPLY_TIMEOUT,
    )
    return {"job_id": job.id, "status": job.status}


@router.post("/environments/{env_id}/tofu-destroy", status_code=202)
async def destroy_environment_aws(
    env_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
):
    """Run tofu destroy for an AWS environment.

    Deliberately separate from the existing /destroy endpoint (which handles
    Docker/on-prem). AWS destroy runs tofu first; DB row is only removed after
    successful completion.
    """
    from app.services.build_manager.tofu_workspace import get_workspace_dir
    from app.services.build_manager.tofu_runner import submit_tofu_job, TOFU_DESTROY_TIMEOUT

    _require_aws_credentials()
    env, spec, aws = await _get_aws_env(db, env_id)

    workspace = get_workspace_dir(env.name)
    if not workspace.exists():
        raise HTTPException(400, "No workspace found — nothing to destroy")

    var_file = workspace / "terraform.tfvars.json"
    cmd = ["tofu", "destroy", "-input=false", "-auto-approve", f"-var-file={var_file}"]
    job = await submit_tofu_job(
        db=db,
        name=f"Destroy: {env.name}",
        job_type="tofu_destroy",
        environment_id=env_id,
        workspace_dir=workspace,
        tofu_cmd=cmd,
        created_by=auth.username,
        timeout_seconds=TOFU_DESTROY_TIMEOUT,
    )
    return {"job_id": job.id, "status": job.status}


@router.get("/environments/{env_id}/outputs")
async def get_environment_outputs(
    env_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
):
    """Return tofu output -json for an AWS environment."""
    from app.services.build_manager.tofu_workspace import get_workspace_dir, workspace_exists
    from app.services.build_manager.tofu_runner import run_tofu_output

    env, spec, aws = await _get_aws_env(db, env_id)

    if not workspace_exists(env.name):
        return {}

    try:
        return await run_tofu_output(get_workspace_dir(env.name))
    except Exception as exc:
        raise HTTPException(500, f"tofu output failed: {exc}")


# ---------------------------------------------------------------------------
# Phase 3 — Certificate Integration endpoints
# ---------------------------------------------------------------------------

@router.get("/environments/{env_id}/certs")
async def list_environment_certs(
    env_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
):
    """List all certificates issued for an environment."""
    from sqlalchemy import select as _select
    from app.models.build_manager import BMEnvironmentCert as _BMEnvCert
    from app.models.certificate import Certificate as _Cert
    import json as _json
    from datetime import datetime, timezone

    result = await db.execute(
        _select(_BMEnvCert)
        .where(_BMEnvCert.environment_id == env_id)
        .order_by(_BMEnvCert.issued_at.desc())
    )
    certs = result.scalars().all()

    now = datetime.now(timezone.utc)
    out = []
    for c in certs:
        expires_at = getattr(c, "expires_at", None)
        # Normalise to aware datetime for comparison
        if expires_at and expires_at.tzinfo is None:
            from datetime import timezone as _tz
            expires_at = expires_at.replace(tzinfo=_tz.utc)

        if c.revoked_at:
            status = "revoked"
        elif expires_at is None:
            status = "unknown"
        elif expires_at < now:
            status = "expired"
        elif (expires_at - now).days <= 30:
            status = "expiring_soon"
        else:
            status = "valid"

        out.append({
            "id": c.id,
            "cert_serial": c.cert_serial,
            "role": c.role,
            "cert_type": c.cert_type,
            "issued_at": c.issued_at.isoformat() if c.issued_at else None,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None,
            "san_dns": _json.loads(c.san_dns) if getattr(c, "san_dns", None) else [],
            "san_ip": _json.loads(c.san_ip) if getattr(c, "san_ip", None) else [],
            "status": status,
            "days_remaining": (expires_at - now).days if expires_at and expires_at > now else None,
        })
    return out


@router.post("/environments/{env_id}/certs/renew", status_code=202)
async def renew_environment_certs(
    env_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
):
    """Re-issue all active certs for an environment with the same SANs."""
    from sqlalchemy import select as _select
    from app.models.build_manager import BMEnvironment as _BMEnv, BMEnvironmentCert as _BMEnvCert
    from app.models.certificate import Certificate as _Cert
    from app.services.build_manager.cert_integration import issue_environment_certs, export_trust_bundle
    import json as _json

    env_result = await db.execute(_select(_BMEnv).where(_BMEnv.id == env_id))
    env = env_result.scalar_one_or_none()
    if not env:
        raise HTTPException(404, "Environment not found")

    variables = _json.loads(env.variables) if env.variables else {}
    signing_ca_id = variables.get("signing_ca_id")
    ip_allocations = _json.loads(env.ip_allocations) if env.ip_allocations else {}

    # Get template spec for host list
    from sqlalchemy import select as _sel
    from app.models.build_manager import BMTemplateVersion as _BMTVer
    ver_result = await db.execute(
        _sel(_BMTVer).where(
            _BMTVer.template_id == env.template_id,
            _BMTVer.version == env.template_version,
        )
    )
    version = ver_result.scalar_one_or_none()
    if not version:
        raise HTTPException(404, "Template version not found")
    spec = _json.loads(version.spec)

    # Revoke existing active certs
    from datetime import datetime, timezone
    existing = await db.execute(
        _select(_BMEnvCert).where(
            _BMEnvCert.environment_id == env_id,
            _BMEnvCert.revoked_at.is_(None),
        )
    )
    for old_cert in existing.scalars().all():
        cert_row = await db.execute(_select(_Cert).where(_Cert.serial == old_cert.cert_serial))
        cert_obj = cert_row.scalar_one_or_none()
        if cert_obj and cert_obj.status == "valid":
            cert_obj.status = "revoked"
            cert_obj.revoked_at = datetime.now(timezone.utc)
            cert_obj.revocation_reason = "superseded"
        old_cert.revoked_at = datetime.now(timezone.utc)
    await db.commit()

    serials = await issue_environment_certs(
        db=db,
        environment_id=env_id,
        environment_name=env.name,
        hosts=spec.get("hosts", []),
        ip_map=ip_allocations,
        signing_ca_id=signing_ca_id,
        validity_days=spec.get("certificates", {}).get("validity_days", 365),
    )
    await export_trust_bundle(db, env.name, signing_ca_id)

    # Step 3.9 - submit cert_renew Ansible job to deploy new certs to hosts
    from app.services.build_manager.ansible_runner import submit_job as _submit_job
    renew_job = await _submit_job(
        db,
        name=f"Cert renew: {env.name}",
        playbook="cert-deploy.yml",
        job_type="cert_renew",
        environment_id=env_id,
        extra_vars={"environment_name": env.name},
        created_by="system",
        tenant_id="00000000-0000-0000-0000-000000000001",
    )

    return {"renewed": len(serials), "serials": serials, "job_id": renew_job.id}


@router.get("/environments/{env_id}/certs/trust-bundle")
async def download_trust_bundle(
    env_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
):
    """Download the CA chain PEM for an environment."""
    from sqlalchemy import select as _select
    from app.models.build_manager import BMEnvironment as _BMEnv
    from app.services.build_manager.cert_integration import get_ca_chain_path
    from fastapi.responses import FileResponse
    import json as _json

    env_result = await db.execute(_select(_BMEnv).where(_BMEnv.id == env_id))
    env = env_result.scalar_one_or_none()
    if not env:
        raise HTTPException(404, "Environment not found")

    ca_path = get_ca_chain_path(env.name)
    if not ca_path.exists():
        raise HTTPException(404, "Trust bundle not yet generated — build the environment first")

    return FileResponse(
        path=str(ca_path),
        media_type="application/x-pem-file",
        filename=f"{env.name}-ca-chain.pem",
    )


@router.get("/environments/{env_id}/certs/truststore.jks")
async def download_truststore(
    env_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
):
    """Download the Java trust store (JKS) for an environment."""
    from sqlalchemy import select as _select
    from app.models.build_manager import BMEnvironment as _BMEnv
    from app.services.build_manager.cert_integration import get_truststore_path
    from fastapi.responses import FileResponse
    import json as _json

    env_result = await db.execute(_select(_BMEnv).where(_BMEnv.id == env_id))
    env = env_result.scalar_one_or_none()
    if not env:
        raise HTTPException(404, "Environment not found")

    jks_path = get_truststore_path(env.name)
    if not jks_path.exists():
        raise HTTPException(404, "Trust store not yet generated — build the environment first")

    return FileResponse(
        path=str(jks_path),
        media_type="application/octet-stream",
        filename=f"{env.name}-truststore.jks",
    )

# ---------------------------------------------------------------------------
# Phase 6 — Alarm Webhook (SNS → Build Manager)
# ---------------------------------------------------------------------------

@router.post("/aws/alarm-webhook", status_code=200)
async def aws_alarm_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Receive SNS alarm notifications and update environment health status.

    SNS sends either a SubscriptionConfirmation (first delivery) or a
    Notification.  Both are plain JSON bodies — no auth header is used
    because the endpoint URL itself is the shared secret (it contains the
    environment-specific path).  SNS subscription confirmation is handled
    automatically by the endpoint_auto_confirms = true flag in the tofu
    module; this handler just records the event and updates status.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    msg_type = body.get("Type", "")

    # SNS subscription confirmation — nothing to do, AWS confirms automatically
    if msg_type == "SubscriptionConfirmation":
        logger.info("SNS subscription confirmation received for TopicArn=%s", body.get("TopicArn"))
        return {"status": "confirmed"}

    if msg_type != "Notification":
        return {"status": "ignored", "type": msg_type}

    # Parse the inner Message (JSON string inside the SNS envelope)
    try:
        message = json.loads(body.get("Message", "{}"))
    except Exception:
        message = {}

    alarm_name = message.get("AlarmName", "")
    new_state = message.get("NewStateValue", "")   # OK | ALARM | INSUFFICIENT_DATA
    topic_arn = body.get("TopicArn", "")

    # Derive environment name from alarm name prefix: "<env_name>-<host>-<metric>"
    # or from the SNS topic name: "<env_name>-alarms"
    env_name = ""
    if alarm_name:
        # alarm names are always "<env_name>-<rest>" — take everything before the
        # second hyphen-separated segment that matches a known alarm suffix
        parts = alarm_name.split("-")
        # Walk backwards to find the env prefix: stop at known alarm suffixes
        known_suffixes = {
            "cpu-high", "memory-high", "disk-high", "status-check",
            "5xx-high", "target-5xx-high", "latency-high", "unhealthy-hosts",
            "rds-cpu-high", "rds-connections-high", "rds-storage-low",
        }
        for i in range(len(parts), 0, -1):
            suffix = "-".join(parts[i:])
            if suffix in known_suffixes:
                env_name = "-".join(parts[:i - 1]) if i > 1 else parts[0]
                break
    if not env_name and topic_arn:
        # topic ARN ends with "<env_name>-alarms"
        topic_name = topic_arn.split(":")[-1]
        if topic_name.endswith("-alarms"):
            env_name = topic_name[: -len("-alarms")]

    if not env_name:
        logger.warning("Could not derive environment name from alarm webhook: alarm=%s topic=%s", alarm_name, topic_arn)
        return {"status": "ok", "env_resolved": False}

    # Look up the environment
    result = await db.execute(
        select(BMEnvironment).where(BMEnvironment.name == env_name)
    )
    env = result.scalar_one_or_none()
    if not env:
        logger.warning("Alarm webhook: environment '%s' not found in DB", env_name)
        return {"status": "ok", "env_resolved": False}

    # Update health status
    if new_state == "ALARM" and env.status == "active":
        env.status = "degraded"
        await audit_event(
            db=db, event_type="BM_AWS_ALARM_FIRED", severity="WARNING", request=request,
            subject_type="bm_environment", subject_id=env.id,
            detail={"alarm_name": alarm_name, "new_state": new_state, "env_name": env_name},
            description=f"AWS alarm fired for environment {env_name}: {alarm_name}",
        )
    elif new_state == "OK" and env.status == "degraded":
        env.status = "active"
        await audit_event(
            db=db, event_type="BM_AWS_ALARM_RESOLVED", severity="INFO", request=request,
            subject_type="bm_environment", subject_id=env.id,
            detail={"alarm_name": alarm_name, "new_state": new_state, "env_name": env_name},
            description=f"AWS alarm resolved for environment {env_name}: {alarm_name}",
        )

    await db.commit()
    return {"status": "ok", "env_name": env_name, "alarm": alarm_name, "state": new_state}
