"""JAR Analyser — Version Diff Engine."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.jar_analyser import (
    AnalysisReport, SubReport,
    JarEndpoint, JarDependency, JarConfigFile,
    JarMigrationScript, JarEventFile, JarDiffReport, JarDtoSchema,
)


class DiffEngine:
    """Compare two AnalysisReports and produce a JarDiffReport."""

    def __init__(self, report_a: AnalysisReport, report_b: AnalysisReport,
                 label_a: str | None = None, label_b: str | None = None):
        self.report_a = report_a
        self.report_b = report_b
        self.label_a = label_a or report_a.implementation_version or report_a.id[:8]
        self.label_b = label_b or report_b.implementation_version or report_b.id[:8]

    async def compute(self, db: AsyncSession) -> JarDiffReport:
        subs_a = await self._load_subs(db, self.report_a.id)
        subs_b = await self._load_subs(db, self.report_b.id)

        map_a = {s.service_name or s.filename: s for s in subs_a}
        map_b = {s.service_name or s.filename: s for s in subs_b}

        all_services = sorted(set(map_a) | set(map_b))
        service_diffs: list[dict] = []
        warnings: list[str] = []

        totals: dict[str, Any] = {
            "services_added": 0, "services_removed": 0, "services_changed": 0,
            "endpoints_added": 0, "endpoints_removed": 0, "endpoints_changed": 0,
            "dependencies_added": 0, "dependencies_removed": 0, "dependencies_version_changed": 0,
            "config_keys_added": 0, "config_keys_removed": 0, "config_keys_changed": 0,
            "migration_scripts_added": 0, "migration_scripts_removed": 0,
            "events_added": 0, "events_removed": 0,
            "security_changes": 0,
            "schema_fields_added": 0, "schema_fields_removed": 0, "schema_fields_type_changed": 0,
            "breaking_changes": 0, "breaking_change_details": [],
            "db_columns_added": 0, "db_columns_dropped": 0, "db_tables_added": 0, "db_tables_dropped": 0,
        }

        for svc in all_services:
            sub_a = map_a.get(svc)
            sub_b = map_b.get(svc)

            if sub_a is None:
                totals["services_added"] += 1
                service_diffs.append({"service_name": svc, "change": "ADDED"})
                continue
            if sub_b is None:
                totals["services_removed"] += 1
                service_diffs.append({"service_name": svc, "change": "REMOVED"})
                continue

            ep_diffs = await self._diff_endpoints(db, sub_a, sub_b, svc, totals)
            dep_diffs = await self._diff_dependencies(db, sub_a, sub_b, svc, totals)
            cfg_diffs = await self._diff_config(db, sub_a, sub_b, svc, totals)
            mig_diffs, mig_warns = await self._diff_migrations(db, sub_a, sub_b, svc, totals)
            event_diffs = await self._diff_events(db, sub_a, sub_b, svc, totals)
            schema_diffs = await self._diff_schemas(db, sub_a, sub_b, svc, totals)
            warnings.extend(mig_warns)

            db_schema_diffs = await self._diff_schemas_db(db, sub_a, sub_b, svc, totals)

            has_changes = any([ep_diffs, dep_diffs, cfg_diffs, mig_diffs, event_diffs, schema_diffs, db_schema_diffs,
                               sub_a.declared_port != sub_b.declared_port,
                               sub_a.spring_boot_version != sub_b.spring_boot_version,
                               sub_a.implementation_version != sub_b.implementation_version])

            if has_changes:
                totals["services_changed"] += 1
                port_change = None
                if sub_a.declared_port != sub_b.declared_port:
                    port_change = {"from": sub_a.declared_port, "to": sub_b.declared_port}
                version_change = None
                if sub_a.implementation_version != sub_b.implementation_version:
                    version_change = {"from": sub_a.implementation_version, "to": sub_b.implementation_version}

                service_diffs.append({
                    "service_name": svc,
                    "change": "CHANGED",
                    "port_change": port_change,
                    "version_change": version_change,
                    "spring_boot_version_change": (
                        {"from": sub_a.spring_boot_version, "to": sub_b.spring_boot_version}
                        if sub_a.spring_boot_version != sub_b.spring_boot_version else None
                    ),
                    "endpoint_diffs": ep_diffs,
                    "dependency_diffs": dep_diffs,
                    "config_diffs": cfg_diffs,
                    "migration_diffs": mig_diffs,
                    "event_diffs": event_diffs,
                    "schema_diffs": schema_diffs,
                    "db_schema_diffs": db_schema_diffs,
                })

        diff_doc = {
            "report_a": {
                "report_id": self.report_a.id,
                "version": self.report_a.implementation_version,
                "label": self.label_a,
            },
            "report_b": {
                "report_id": self.report_b.id,
                "version": self.report_b.implementation_version,
                "label": self.label_b,
            },
            "service_diffs": service_diffs,
        }

        diff_report = JarDiffReport(
            id=str(uuid.uuid4()),
            report_a_id=self.report_a.id,
            report_b_id=self.report_b.id,
            label_a=self.label_a,
            label_b=self.label_b,
            created_at=datetime.now(timezone.utc),
            summary_json=json.dumps(totals),
            diff_json=json.dumps(diff_doc),
            warnings_json=json.dumps(warnings) if warnings else None,
        )
        db.add(diff_report)
        await db.commit()
        await db.refresh(diff_report)
        return diff_report

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------

    async def _load_subs(self, db: AsyncSession, report_id: str) -> list[SubReport]:
        r = await db.execute(select(SubReport).where(SubReport.parent_report_id == report_id))
        return list(r.scalars().all())

    async def _load_endpoints(self, db: AsyncSession, sub_id: str) -> list[JarEndpoint]:
        r = await db.execute(select(JarEndpoint).where(JarEndpoint.sub_report_id == sub_id))
        return list(r.scalars().all())

    async def _load_dependencies(self, db: AsyncSession, sub_id: str) -> list[JarDependency]:
        r = await db.execute(select(JarDependency).where(JarDependency.sub_report_id == sub_id))
        return list(r.scalars().all())

    async def _load_config(self, db: AsyncSession, sub_id: str) -> list[JarConfigFile]:
        r = await db.execute(select(JarConfigFile).where(JarConfigFile.sub_report_id == sub_id))
        return list(r.scalars().all())

    async def _load_migrations(self, db: AsyncSession, sub_id: str) -> list[JarMigrationScript]:
        r = await db.execute(select(JarMigrationScript).where(JarMigrationScript.sub_report_id == sub_id))
        return list(r.scalars().all())

    async def _load_events(self, db: AsyncSession, sub_id: str) -> list[JarEventFile]:
        r = await db.execute(select(JarEventFile).where(JarEventFile.sub_report_id == sub_id))
        return list(r.scalars().all())

    async def _load_schemas(self, db: AsyncSession, sub_id: str) -> list[JarDtoSchema]:
        r = await db.execute(select(JarDtoSchema).where(JarDtoSchema.sub_report_id == sub_id))
        return list(r.scalars().all())

    # ------------------------------------------------------------------
    # Diff helpers
    # ------------------------------------------------------------------

    async def _diff_endpoints(self, db: AsyncSession, sub_a: SubReport, sub_b: SubReport,
                               svc: str, totals: dict) -> list[dict]:
        eps_a = {e.signature_key: e for e in await self._load_endpoints(db, sub_a.id)}
        eps_b = {e.signature_key: e for e in await self._load_endpoints(db, sub_b.id)}
        diffs: list[dict] = []

        for key in set(eps_a) - set(eps_b):
            totals["endpoints_removed"] += 1
            e = eps_a[key]
            diffs.append({"change": "REMOVED", "service": svc,
                          "http_method": e.http_method, "path": e.full_path})

        for key in set(eps_b) - set(eps_a):
            totals["endpoints_added"] += 1
            e = eps_b[key]
            diffs.append({"change": "ADDED", "service": svc,
                          "http_method": e.http_method, "path": e.full_path})

        for key in set(eps_a) & set(eps_b):
            ea, eb = eps_a[key], eps_b[key]
            detail = self._compare_endpoints(ea, eb)
            if detail:
                totals["endpoints_changed"] += 1
                if detail.get("security_changed"):
                    totals["security_changes"] += 1
                    sc = detail["security_changed"]
                    # Treat any security expression change as potentially breaking
                    if sc.get("from") is None or sc.get("to") is None:
                        totals["breaking_changes"] += 1
                        totals["breaking_change_details"].append(
                            f"{svc} {ea.http_method} {ea.full_path}: security expression changed "
                            f"{sc.get('from')!r} → {sc.get('to')!r}"
                        )
                diffs.append({"change": "CHANGED", "service": svc,
                               "http_method": ea.http_method, "path": ea.full_path,
                               "detail": detail})

        return diffs

    def _compare_endpoints(self, ea: JarEndpoint, eb: JarEndpoint) -> dict | None:
        detail: dict[str, Any] = {}

        params_a = json.loads(ea.parameters_json) if ea.parameters_json else []
        params_b = json.loads(eb.parameters_json) if eb.parameters_json else []
        names_a = {p["name"] for p in params_a if "name" in p}
        names_b = {p["name"] for p in params_b if "name" in p}
        added = [p for p in params_b if p.get("name") in names_b - names_a]
        removed = [p for p in params_a if p.get("name") in names_a - names_b]
        if added:
            detail["parameters_added"] = added
        if removed:
            detail["parameters_removed"] = removed

        sec_a = json.loads(ea.security_json) if ea.security_json else None
        sec_b = json.loads(eb.security_json) if eb.security_json else None
        expr_a = sec_a.get("expression") if sec_a else None
        expr_b = sec_b.get("expression") if sec_b else None
        if expr_a != expr_b:
            detail["security_changed"] = {
                "from": expr_a, "to": expr_b, "importance": "HIGH"
            }

        rt_a = json.loads(ea.return_type_json) if ea.return_type_json else None
        rt_b = json.loads(eb.return_type_json) if eb.return_type_json else None
        if rt_a != rt_b:
            detail["return_type_changed"] = {"from": rt_a, "to": rt_b}

        if ea.controller_class != eb.controller_class:
            detail["controller_changed"] = {"from": ea.controller_class, "to": eb.controller_class}

        return detail if detail else None

    async def _diff_dependencies(self, db: AsyncSession, sub_a: SubReport, sub_b: SubReport,
                                  svc: str, totals: dict) -> list[dict]:
        def _key(d: JarDependency) -> str:
            return f"{d.group_id or ''}:{d.artifact_id or ''}"

        deps_a = {_key(d): d for d in await self._load_dependencies(db, sub_a.id)}
        deps_b = {_key(d): d for d in await self._load_dependencies(db, sub_b.id)}
        diffs: list[dict] = []

        for k in set(deps_a) - set(deps_b):
            totals["dependencies_removed"] += 1
            d = deps_a[k]
            diffs.append({"change": "REMOVED", "service": svc,
                          "maven_coordinates": k, "version": d.version})

        for k in set(deps_b) - set(deps_a):
            totals["dependencies_added"] += 1
            d = deps_b[k]
            diffs.append({"change": "ADDED", "service": svc,
                          "maven_coordinates": k, "version": d.version})

        for k in set(deps_a) & set(deps_b):
            da, db_ = deps_a[k], deps_b[k]
            if da.version != db_.version:
                totals["dependencies_version_changed"] += 1
                diffs.append({"change": "CHANGED", "service": svc,
                               "maven_coordinates": k,
                               "version_from": da.version, "version_to": db_.version})

        return diffs

    async def _diff_config(self, db: AsyncSession, sub_a: SubReport, sub_b: SubReport,
                            svc: str, totals: dict) -> list[dict]:
        cfgs_a = {c.filename: c for c in await self._load_config(db, sub_a.id)}
        cfgs_b = {c.filename: c for c in await self._load_config(db, sub_b.id)}
        diffs: list[dict] = []

        all_files = set(cfgs_a) | set(cfgs_b)
        for fname in all_files:
            ca = cfgs_a.get(fname)
            cb = cfgs_b.get(fname)

            keys_a: dict[str, Any] = {}
            keys_b: dict[str, Any] = {}
            if ca and ca.keys_json:
                keys_a = {k["key"]: k["value"] for k in json.loads(ca.keys_json) if "key" in k}
            if cb and cb.keys_json:
                keys_b = {k["key"]: k["value"] for k in json.loads(cb.keys_json) if "key" in k}

            for k in set(keys_b) - set(keys_a):
                totals["config_keys_added"] += 1
                diffs.append({"change": "ADDED", "service": svc, "file": fname, "key": k,
                               "value": keys_b[k]})
            for k in set(keys_a) - set(keys_b):
                totals["config_keys_removed"] += 1
                diffs.append({"change": "REMOVED", "service": svc, "file": fname, "key": k})
            for k in set(keys_a) & set(keys_b):
                if keys_a[k] != keys_b[k]:
                    totals["config_keys_changed"] += 1
                    diffs.append({"change": "CHANGED", "service": svc, "file": fname, "key": k,
                                  "value_from": keys_a[k], "value_to": keys_b[k]})

        return diffs

    async def _diff_migrations(self, db: AsyncSession, sub_a: SubReport, sub_b: SubReport,
                                svc: str, totals: dict) -> tuple[list[dict], list[str]]:
        migs_a = {m.version: m for m in await self._load_migrations(db, sub_a.id) if m.version}
        migs_b = {m.version: m for m in await self._load_migrations(db, sub_b.id) if m.version}
        diffs: list[dict] = []
        warnings: list[str] = []

        for v in set(migs_b) - set(migs_a):
            totals["migration_scripts_added"] += 1
            m = migs_b[v]
            diffs.append({"change": "ADDED", "service": svc, "version": v,
                          "filename": m.filename, "description": m.description})

        for v in set(migs_a) - set(migs_b):
            totals["migration_scripts_removed"] += 1
            m = migs_a[v]
            warnings.append(
                f"Migration script {m.filename} present in {self.label_a} but not {self.label_b} "
                f"— verify migration order"
            )
            diffs.append({"change": "REMOVED", "service": svc, "version": v,
                          "filename": m.filename, "warning": True})

        return diffs, warnings

    async def _diff_events(self, db: AsyncSession, sub_a: SubReport, sub_b: SubReport,
                            svc: str, totals: dict) -> list[dict]:
        """
        Diff published and consumed events between two versions.
        Key: (type, source_service_or_entity, entity, action)
        """
        def _event_keys(ev_file: JarEventFile) -> set[tuple]:
            keys: set[tuple] = set()
            for pub in json.loads(ev_file.published_json or "[]"):
                for action in (pub.get("actions") or []):
                    keys.add(("published", pub.get("entity", ""), action))
            for con in json.loads(ev_file.consumed_json or "[]"):
                keys.add(("consumed", con.get("source_service") or "",
                          con.get("entity") or "", con.get("action") or ""))
            return keys

        evs_a: set[tuple] = set()
        evs_b: set[tuple] = set()
        for ef in await self._load_events(db, sub_a.id):
            evs_a |= _event_keys(ef)
        for ef in await self._load_events(db, sub_b.id):
            evs_b |= _event_keys(ef)

        diffs: list[dict] = []
        for key in evs_b - evs_a:
            totals["events_added"] += 1
            diffs.append({"change": "ADDED", "service": svc, "event_key": key})
        for key in evs_a - evs_b:
            totals["events_removed"] += 1
            diffs.append({"change": "REMOVED", "service": svc, "event_key": key})
        return diffs

    async def _diff_schemas_db(self, db: AsyncSession, sub_a: SubReport, sub_b: SubReport,
                                svc: str, totals: dict) -> list[dict]:
        """Reconstruct schema from migrations on both sides and diff at column level."""
        from app.services.jar_analyser.schema_reconstructor import reconstruct_schema, diff_schemas

        migs_a = [{
            "version": m.version, "content": m.content or ""
        } for m in await self._load_migrations(db, sub_a.id)]
        migs_b = [{
            "version": m.version, "content": m.content or ""
        } for m in await self._load_migrations(db, sub_b.id)]

        if not migs_a and not migs_b:
            return []

        schema_a = reconstruct_schema(migs_a)
        schema_b = reconstruct_schema(migs_b)
        changes = diff_schemas(schema_a, schema_b)

        for c in changes:
            if c["change"] == "TABLE_ADDED":
                totals["db_tables_added"] += 1
            elif c["change"] == "TABLE_DROPPED":
                totals["db_tables_dropped"] += 1
            elif c["change"] == "COLUMN_ADDED":
                totals["db_columns_added"] += 1
                if c["risk"] == "high":
                    totals["breaking_changes"] += 1
                    totals["breaking_change_details"].append(
                        f"{svc}.{c['table']}.{c['column']}: NOT NULL column added without default"
                    )
            elif c["change"] == "COLUMN_DROPPED":
                totals["db_columns_dropped"] += 1
                totals["breaking_changes"] += 1
                totals["breaking_change_details"].append(
                    f"{svc}.{c['table']}.{c['column']}: column dropped"
                )
            elif c["change"] == "TYPE_CHANGED":
                totals["breaking_changes"] += 1
                totals["breaking_change_details"].append(
                    f"{svc}.{c['table']}.{c['column']}: type changed "
                    f"{c['detail'].get('from')} → {c['detail'].get('to')}"
                )

        return changes

    # Impact classification per the dev plan
    # Returns: 'breaking' | 'potentially_breaking' | 'none' | 'review'
    @staticmethod
    def _field_change_impact(change: str, field: dict | None, context: str) -> str:
        """
        change: ADDED | REMOVED | TYPE_CHANGED | ENUM_VALUE_ADDED | ENUM_VALUE_REMOVED
        context: request | response | enum
        """
        if change == "ADDED":
            required = field.get("required", False) if field else False
            if context == "request" and required:
                return "breaking"
            return "none"
        if change == "REMOVED":
            if context == "response":
                return "potentially_breaking"
            return "breaking"
        if change == "TYPE_CHANGED":
            return "breaking"
        if change == "ENUM_VALUE_REMOVED":
            return "breaking"
        if change == "ENUM_VALUE_ADDED":
            return "none"
        return "none"

    async def _diff_schemas(self, db: AsyncSession, sub_a: SubReport, sub_b: SubReport,
                             svc: str, totals: dict) -> list[dict]:
        schemas_a = {s.class_name: s for s in await self._load_schemas(db, sub_a.id)}
        schemas_b = {s.class_name: s for s in await self._load_schemas(db, sub_b.id)}

        diffs: list[dict] = []

        for class_name in set(schemas_a) & set(schemas_b):
            sa = schemas_a[class_name]
            sb = schemas_b[class_name]
            simple = sa.simple_name
            field_diffs: list[dict] = []

            if sa.is_enum and sb.is_enum:
                vals_a = {v.get("serialised_as", v.get("name", "")) for v in
                          (json.loads(sa.enum_values_json) if sa.enum_values_json else [])}
                vals_b = {v.get("serialised_as", v.get("name", "")) for v in
                          (json.loads(sb.enum_values_json) if sb.enum_values_json else [])}
                for v in vals_b - vals_a:
                    impact = self._field_change_impact("ENUM_VALUE_ADDED", None, "enum")
                    field_diffs.append({"field": v, "change": "ENUM_VALUE_ADDED", "impact": impact})
                for v in vals_a - vals_b:
                    impact = self._field_change_impact("ENUM_VALUE_REMOVED", None, "enum")
                    field_diffs.append({"field": v, "change": "ENUM_VALUE_REMOVED", "impact": impact})
                    if impact == "breaking":
                        totals["breaking_changes"] += 1
                        totals["breaking_change_details"].append(f"{simple}.{v}: enum value removed")
            else:
                fields_a = {f["json_name"]: f for f in (json.loads(sa.fields_json) if sa.fields_json else [])
                            if not f.get("json_ignored")}
                fields_b = {f["json_name"]: f for f in (json.loads(sb.fields_json) if sb.fields_json else [])
                            if not f.get("json_ignored")}

                # Infer context from class name heuristic
                name_lower = simple.lower()
                if any(x in name_lower for x in ("request", "command", "body", "input", "form")):
                    ctx = "request"
                elif any(x in name_lower for x in ("response", "dto", "result", "view", "output")):
                    ctx = "response"
                else:
                    ctx = "request"  # conservative default

                for fname in set(fields_b) - set(fields_a):
                    totals["schema_fields_added"] += 1
                    f = fields_b[fname]
                    impact = self._field_change_impact("ADDED", f, ctx)
                    field_diffs.append({
                        "field": fname, "change": "ADDED",
                        "type": f.get("openapi_type", "unknown"),
                        "required": f.get("required", False),
                        "impact": impact,
                    })
                    if impact == "breaking":
                        totals["breaking_changes"] += 1
                        totals["breaking_change_details"].append(
                            f"{simple}.{fname}: required field added to {ctx}"
                        )

                for fname in set(fields_a) - set(fields_b):
                    totals["schema_fields_removed"] += 1
                    f = fields_a[fname]
                    impact = self._field_change_impact("REMOVED", f, ctx)
                    field_diffs.append({
                        "field": fname, "change": "REMOVED",
                        "type": f.get("openapi_type", "unknown"),
                        "required": f.get("required", False),
                        "impact": impact,
                    })
                    if impact in ("breaking", "potentially_breaking"):
                        totals["breaking_changes"] += 1
                        totals["breaking_change_details"].append(
                            f"{simple}.{fname}: field removed from {ctx}"
                        )

                for fname in set(fields_a) & set(fields_b):
                    fa, fb = fields_a[fname], fields_b[fname]
                    type_a = fa.get("openapi_type", "")
                    type_b = fb.get("openapi_type", "")
                    if type_a != type_b:
                        totals["schema_fields_type_changed"] += 1
                        impact = self._field_change_impact("TYPE_CHANGED", fb, ctx)
                        field_diffs.append({
                            "field": fname, "change": "TYPE_CHANGED",
                            "type_from": type_a, "type_to": type_b,
                            "impact": impact,
                        })
                        if impact == "breaking":
                            totals["breaking_changes"] += 1
                            totals["breaking_change_details"].append(
                                f"{simple}.{fname}: type changed {type_a} → {type_b}"
                            )

            if field_diffs:
                diffs.append({
                    "class_name": class_name,
                    "simple_name": simple,
                    "is_enum": sa.is_enum,
                    "field_diffs": field_diffs,
                })

        return diffs
