"""Stage 2 of the infra-requirements plan — MySQL / database provisioning
requirements.

Combines connection facts (host/port/database name — only when a literal
value is present, see connection_facts.py) with Flyway-derived table
ownership (already extracted per-service, see flyway.py / Stage 6's DB
ownership evidence) into a per-database-name rollup: "database `mydb` should
contain tables: X, Y (created by service Z's migrations)". Also runs a cheap
cross-service collision check and states explicitly what this tool cannot
determine (grant scoping).
"""
from __future__ import annotations

from app.services.jar_analyser.connection_facts import extract_connection_facts


def _is_mysql(db) -> bool:
    if db.db_type and db.db_type.lower() == "mysql":
        return True
    if db.driver_class and "mysql" in db.driver_class.lower():
        return True
    if db.url and "mysql" in db.url.lower():
        return True
    return False


def compute_database_requirements(sub_reports: list[dict]) -> dict:
    per_service: dict[str, dict] = {}
    by_db_name: dict[str, dict] = {}
    unnamed_tables: dict[str, list[str]] = {}

    for sr in sub_reports:
        svc = sr.get("service_name") or sr.get("filename")
        keys = [k for cfg in sr.get("config_files", []) for k in cfg.get("keys", [])]
        db = extract_connection_facts(keys).database if keys else None

        tables: set[str] = set()
        for ms in sr.get("migration_scripts", []):
            tables.update(ms.get("tables_affected") or [])

        if db is None and not tables:
            continue

        per_service[svc] = {
            "is_mysql": bool(db and _is_mysql(db)),
            "db_type": db.db_type if db else None,
            "host": db.host if db else None,
            "port": db.port if db else None,
            "database_name": db.database_name if db else None,
            "username": db.username if db else None,
            "max_pool_size": db.max_pool_size if db else None,
            "externally_parameterized_keys": db.externally_parameterized_keys if db else [],
            "tables": sorted(tables),
        }

        if db and db.database_name:
            entry = by_db_name.setdefault(db.database_name, {"tables": set(), "services": set()})
            entry["tables"].update(tables)
            entry["services"].add(svc)
        elif tables:
            unnamed_tables[svc] = sorted(tables)

    requirements = [
        {"database_name": name, "services": sorted(info["services"]), "tables": sorted(info["tables"])}
        for name, info in sorted(by_db_name.items())
    ]

    collisions = [
        {
            "database_name": name,
            "services": sorted(info["services"]),
            "note": "Multiple services declare the same database name — confirm this is intentional sharing, "
                    "not an accidental collision.",
        }
        for name, info in sorted(by_db_name.items())
        if len(info["services"]) > 1
    ]

    known_gaps = [
        "Whether each service's database user should be scoped only to its own tables or shared across "
        "services is a security-policy decision this tool cannot make — the table ownership above is the "
        "raw input to that decision, not a recommendation.",
    ]
    if unnamed_tables:
        detail = "; ".join(f"{svc} ({len(t)} tables)" for svc, t in sorted(unnamed_tables.items()))
        known_gaps.append(
            "The following services own Flyway-defined tables, but their database name is externally "
            "parameterised (no literal value in this bundle), so they could not be grouped under a named "
            "database: " + detail
        )

    return {
        "requirements": requirements,
        "per_service": per_service,
        "collisions": collisions,
        "known_gaps": known_gaps,
    }
