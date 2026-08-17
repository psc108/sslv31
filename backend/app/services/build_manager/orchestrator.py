"""Orchestrator service — dependency resolution (DAG) and execution order for builds."""

import json
from collections import defaultdict, deque

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.build_manager import (
    BMEnvironment, BMEnvironmentCert, BMJob, BMProduct, BMProductVersion, BMTemplateVersion,
)


def resolve_execution_order(host_products: list[dict], catalogue: dict[str, list[str]]) -> list[dict]:
    """Resolve product execution order using topological sort on dependency graph.

    Args:
        host_products: [{ansible_role: str, vars: dict}, ...]
        catalogue: {product_name: [dependency_names]} from the product catalogue

    Returns:
        Reordered host_products list respecting dependencies.
    """
    roles = {p["ansible_role"]: p for p in host_products}
    # Build adjacency: dependency -> dependant (dependency must run first)
    graph: dict[str, set[str]] = defaultdict(set)
    in_degree: dict[str, int] = {r: 0 for r in roles}

    for role_name in roles:
        deps = catalogue.get(role_name, [])
        for dep in deps:
            if dep in roles:
                graph[dep].add(role_name)
                in_degree[role_name] = in_degree.get(role_name, 0) + 1

    # Kahn's algorithm
    queue = deque(r for r, d in in_degree.items() if d == 0)
    ordered = []
    while queue:
        node = queue.popleft()
        ordered.append(node)
        for neighbour in graph[node]:
            in_degree[neighbour] -= 1
            if in_degree[neighbour] == 0:
                queue.append(neighbour)

    # Append any remaining (circular deps — shouldn't happen, but safe)
    for role_name in roles:
        if role_name not in ordered:
            ordered.append(role_name)

    return [roles[r] for r in ordered if r in roles]


async def get_dependency_catalogue(db: AsyncSession) -> dict[str, list[str]]:
    """Build a {product_name: [dependency_names]} lookup from the catalogue."""
    result = await db.execute(select(BMProduct))
    products = result.scalars().all()
    catalogue: dict[str, list[str]] = {}
    for p in products:
        deps = json.loads(p.dependencies) if p.dependencies else []
        # Map product name to its ansible role names (they're usually the same)
        catalogue[p.name] = deps
    return catalogue


def build_execution_dag(spec: dict, catalogue: dict[str, list[str]]) -> dict:
    """Build a DAG representation of the full environment execution plan.

    Returns a dict suitable for frontend visualisation:
    {
        "phases": [
            {"name": "Base Provisioning", "hosts": ["all"]},
            {"name": "Products", "hosts": [
                {"role": "db-01", "order": ["erlang", "rabbitmq"]},
                ...
            ]}
        ],
        "dependencies": [{"from": "erlang", "to": "rabbitmq", "host": "mq-01"}]
    }
    """
    hosts_phase = []
    all_deps = []

    for host_def in spec.get("hosts", []):
        role = host_def["role"]
        products = host_def.get("products", [])
        if not products:
            hosts_phase.append({"role": role, "order": []})
            continue

        host_products = [
            {"ansible_role": p.get("ansible_role", p.get("product_name", p.get("product", ""))), "vars": p.get("vars", {})}
            for p in products
            if p.get("ansible_role") or p.get("product_name") or p.get("product")
        ]

        ordered = resolve_execution_order(host_products, catalogue)
        order_names = [p["ansible_role"] for p in ordered]
        hosts_phase.append({"role": role, "order": order_names})

        # Collect dependency edges for this host
        for p in products:
            role_name = p.get("ansible_role", p.get("product_name", p.get("product", "")))
            deps = catalogue.get(role_name, [])
            for dep in deps:
                if dep in order_names:
                    all_deps.append({"from": dep, "to": role_name, "host": role})

    return {
        "phases": [
            {"name": "Base Provisioning", "targets": "all"},
            {"name": "Product Deployment", "hosts": hosts_phase},
        ],
        "dependencies": all_deps,
    }


async def get_dashboard_stats(db: AsyncSession) -> dict:
    """Aggregate stats for the Build Manager dashboard."""
    # Environment counts by status
    env_result = await db.execute(
        select(BMEnvironment.status, func.count(BMEnvironment.id))
        .group_by(BMEnvironment.status)
    )
    env_counts = dict(env_result.all())

    # Total certs and expiring soon
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    threshold = now + timedelta(days=30)

    cert_total = await db.execute(
        select(func.count(BMEnvironmentCert.id))
        .where(BMEnvironmentCert.revoked_at.is_(None))
    )
    total_active_certs = cert_total.scalar() or 0

    # Expiring certs (check via the Certificate table)
    from app.models.certificate import Certificate
    expiring_result = await db.execute(
        select(func.count(Certificate.id))
        .where(
            Certificate.status == "valid",
            Certificate.expires_at <= threshold,
            Certificate.expires_at > now,
            Certificate.tags.contains("build-manager"),
        )
    )
    expiring_certs = expiring_result.scalar() or 0

    # Recent jobs
    jobs_result = await db.execute(
        select(BMJob)
        .order_by(BMJob.created_at.desc())
        .limit(5)
    )
    recent_jobs = jobs_result.scalars().all()

    # Products count
    product_count = await db.execute(select(func.count(BMProduct.id)))

    return {
        "environments": {
            "total": sum(env_counts.values()),
            "active": env_counts.get("active", 0),
            "pending": env_counts.get("pending", 0),
            "failed": env_counts.get("failed", 0),
            "degraded": env_counts.get("degraded", 0),
        },
        "certificates": {
            "active": total_active_certs,
            "expiring_soon": expiring_certs,
        },
        "products": product_count.scalar() or 0,
        "recent_jobs": [
            {
                "id": j.id,
                "name": j.name,
                "status": j.status,
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "finished_at": j.finished_at.isoformat() if j.finished_at else None,
            }
            for j in recent_jobs
        ],
    }
