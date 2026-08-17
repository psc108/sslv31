"""JAR analysis job orchestrator.

Runs the full analysis pipeline (Phase 1 + Phase 2) on an uploaded JAR
and persists the results via the persistence service.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.jar_analyser import JarUpload, AnalysisReport
from app.services.jar_analyser.detector import JarTypeDetector, JarType
from app.services.jar_analyser.manifest import ManifestParser
from app.services.jar_analyser.extractor import NestedJarExtractor
from app.services.jar_analyser.dependencies import DependencyExtractor
from app.services.jar_analyser.config_files import ConfigFileExtractor
from app.services.jar_analyser.installer_meta import InstallerMetadataParser
from app.services.jar_analyser.classfile import ClassFileParser
from app.services.jar_analyser.annotations import AnnotationScanner
from app.services.jar_analyser.endpoints import EndpointReconstructor
from app.services.jar_analyser.packages import PackageAnalyser
from app.services.jar_analyser.flyway import FlywayExtractor
from app.services.jar_analyser.events import EventDefinitionExtractor

log = logging.getLogger(__name__)

ANALYSER_VERSION = "1.0.0"


@dataclass
class SubReportData:
    filename: str
    installer_jar: str | None
    jar_path: Path
    size_bytes: int
    depth: int = 1
    warnings: list[str] = field(default_factory=list)
    # Populated by pipeline
    jar_type: str = "unknown"
    detection_confidence: float = 0.0
    manifest: dict = field(default_factory=dict)
    installer_metadata: dict = field(default_factory=dict)
    service_name: str | None = None
    declared_port: int | None = None
    application_name: str | None = None
    group_name: str | None = None
    install_path: str | None = None
    start_class: str | None = None
    spring_boot_version: str | None = None
    implementation_version: str | None = None
    package_structure: dict = field(default_factory=dict)
    class_file_versions: dict = field(default_factory=dict)
    endpoints: list[dict] = field(default_factory=list)
    scheduled_jobs: list[dict] = field(default_factory=list)
    dependencies: list[dict] = field(default_factory=list)
    config_files: list[dict] = field(default_factory=list)
    migration_scripts: list[dict] = field(default_factory=list)
    event_files: list[dict] = field(default_factory=list)
    dto_schemas: list[dict] = field(default_factory=list)
    config_examples: list[dict] = field(default_factory=list)
    workflows: list[dict] = field(default_factory=list)
    error_responses: list[dict] = field(default_factory=list)
    purpose_narrative: list[dict] = field(default_factory=list)
    string_constants: list[dict] = field(default_factory=list)
    outbound_integrations: list[dict] = field(default_factory=list)
    duration_ms: int = 0


@dataclass
class AnalysisJobResult:
    report_id: str
    jar_type: str
    detection_confidence: float
    manifest: dict
    summary: dict
    sub_reports: list[SubReportData]
    warnings: list[str]
    errors: list[str]
    duration_ms: int
    consistency_findings: list[dict] = field(default_factory=list)
    infra_requirements: dict = field(default_factory=dict)
    actuator_exposure: dict = field(default_factory=dict)


class AnalysisJob:
    """Orchestrates the full analysis pipeline for one uploaded JAR."""

    def __init__(self, upload: JarUpload, jar_path: Path, work_dir: Path):
        self.upload = upload
        self.jar_path = jar_path
        self.work_dir = work_dir
        self._warnings: list[str] = []
        self._errors: list[str] = []

    async def run(self, db: AsyncSession) -> str:
        """Run analysis, persist results, return report_id."""
        from app.services.jar_analyser.persistence import persist_report
        from sqlalchemy import select

        # Mark upload as analysing
        self.upload.status = "analysing"
        await db.commit()

        # Create pending report
        report = AnalysisReport(
            upload_id=self.upload.id,
            status="analysing",
            analyser_version=ANALYSER_VERSION,
            analysis_started_at=datetime.now(timezone.utc),
            tenant_id=self.upload.tenant_id,
        )
        db.add(report)
        await db.commit()

        t0 = time.monotonic()
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, self._run_sync
            )
            result.report_id = report.id
            await persist_report(db, report, self.upload, result)
            # persist_report already set report.status/upload.status and committed —
            # it may be "failed" if every sub-report failed to persist (total wipeout),
            # not just "completed", so don't blindly overwrite it here.

            if report.status == "completed":
                # Improvements Plan Stage 12 — automated cross-report bug
                # pattern scan. Best-effort by design (scan_for_related_bugs
                # never raises, see its own docstring) — a scan failure
                # must never fail an otherwise-successful analysis.
                from app.services.jar_analyser.bug_pattern_scan import scan_for_related_bugs
                related_bug_ids = await scan_for_related_bugs(db, report)
                report.related_bug_ids_json = json.dumps(related_bug_ids)
                await db.commit()
        except Exception as e:
            log.exception(f"Analysis failed for upload {self.upload.id}")
            report.status = "failed"
            report.errors_json = f'["{e}"]'
            report.analysis_completed_at = datetime.now(timezone.utc)
            self.upload.status = "failed"
            await db.commit()
            raise
        finally:
            NestedJarExtractor.cleanup(self.work_dir)

        return report.id

    def _run_sync(self) -> AnalysisJobResult:
        t0 = time.monotonic()
        warnings: list[str] = []
        errors: list[str] = []

        # --- ZIP bundle: treat each contained JAR as a top-level entry ---
        if self.jar_path.suffix.lower() == ".zip":
            return self._run_zip_bundle(t0)

        # --- Top-level detection ---
        detection = JarTypeDetector.detect(self.jar_path)
        manifest_info = ManifestParser.from_jar(self.jar_path)
        installer_meta = InstallerMetadataParser.from_jar(self.jar_path)

        manifest_dict = {
            "main_class": manifest_info.main_class,
            "start_class": manifest_info.start_class,
            "spring_boot_version": manifest_info.spring_boot_version,
            "implementation_title": manifest_info.implementation_title,
            "implementation_version": manifest_info.implementation_version,
            "implementation_vendor": manifest_info.implementation_vendor,
            "build_jdk": manifest_info.build_jdk,
            "built_by": manifest_info.built_by,
            "created_by": manifest_info.created_by,
            "all_attributes": manifest_info.all_attributes,
        }

        sub_reports: list[SubReportData] = []

        if detection.jar_type == JarType.JAR_OF_JARS:
            # Extract and analyse each nested installer JAR
            entries = NestedJarExtractor.extract(self.jar_path, self.work_dir)
            for entry in entries:
                try:
                    sr = self._analyse_installer_entry(entry)
                    sub_reports.append(sr)
                except Exception as e:
                    warnings.append(f"Failed to analyse {entry.filename}: {e}")
        else:
            # Single JAR — analyse directly
            sr = self._analyse_single_jar(
                jar_path=self.jar_path,
                filename=self.jar_path.name,
                installer_jar=None,
                size_bytes=self.jar_path.stat().st_size,
                depth=0,
            )
            sub_reports.append(sr)

        # Build summary
        total_endpoints = sum(len(sr.endpoints) for sr in sub_reports)
        total_deps = sum(len(sr.dependencies) for sr in sub_reports)
        total_configs = sum(sum(cf.get("key_count", 0) or 0 for cf in sr.config_files) for sr in sub_reports)
        total_migrations = sum(len(sr.migration_scripts) for sr in sub_reports)
        ports = sorted({sr.declared_port for sr in sub_reports if sr.declared_port})
        services = [sr.service_name for sr in sub_reports if sr.service_name]
        spring_versions = {sr.spring_boot_version for sr in sub_reports if sr.spring_boot_version}

        summary = {
            "nested_jar_count": len(sub_reports),
            "total_endpoint_count": total_endpoints,
            "total_dependency_count": total_deps,
            "total_config_key_count": total_configs,
            "total_migration_script_count": total_migrations,
            "services_detected": services,
            "ports_detected": ports,
            "spring_boot_version": next(iter(spring_versions), None),
            "has_ssl_config": any(
                (cf.get("ssl_key_count") or 0) > 0
                for sr in sub_reports for cf in sr.config_files
            ),
            "has_database_config": any(
                (cf.get("db_key_count") or 0) > 0
                for sr in sub_reports for cf in sr.config_files
            ),
            "has_rabbitmq_config": any(
                (cf.get("mq_key_count") or 0) > 0
                for sr in sub_reports for cf in sr.config_files
            ),
        }

        consistency_findings = self._compute_consistency_findings(sub_reports)
        infra_requirements = self._compute_infra_requirements(sub_reports)
        actuator_exposure = self._compute_actuator_exposure(sub_reports)

        duration_ms = int((time.monotonic() - t0) * 1000)
        return AnalysisJobResult(
            report_id="",  # filled in by caller
            jar_type=detection.jar_type.value,
            detection_confidence=detection.confidence,
            manifest=manifest_dict,
            summary=summary,
            sub_reports=sub_reports,
            warnings=warnings,
            errors=errors,
            duration_ms=duration_ms,
            consistency_findings=consistency_findings,
            infra_requirements=infra_requirements,
            actuator_exposure=actuator_exposure,
        )

    @staticmethod
    def _compute_consistency_findings(sub_reports: list[SubReportData]) -> list[dict]:
        """Stage 3 static cross-validation — see consistency_findings.py.
        Best-effort: a bug in a cross-check must never fail the analysis."""
        try:
            from dataclasses import asdict
            from app.services.jar_analyser.consistency_findings import compute_consistency_findings
            return compute_consistency_findings([asdict(sr) for sr in sub_reports])
        except Exception:
            log.exception("Consistency findings computation failed — continuing without them")
            return []

    @staticmethod
    def _compute_infra_requirements(sub_reports: list[SubReportData]) -> dict:
        """Infra-requirements plan — see infra_requirements.py.
        Best-effort: a bug here must never fail the analysis."""
        try:
            from dataclasses import asdict
            from app.services.jar_analyser.infra_requirements import compute_infra_requirements
            return compute_infra_requirements([asdict(sr) for sr in sub_reports])
        except Exception:
            log.exception("Infra requirements computation failed — continuing without them")
            return {}

    @staticmethod
    def _compute_actuator_exposure(sub_reports: list[SubReportData]) -> dict:
        """Actuator/management endpoint exposure — see actuator_exposure.py.
        Best-effort: a bug here must never fail the analysis."""
        try:
            from dataclasses import asdict
            from app.services.jar_analyser.actuator_exposure import compute_actuator_exposure
            return compute_actuator_exposure([asdict(sr) for sr in sub_reports])
        except Exception:
            log.exception("Actuator exposure computation failed — continuing without it")
            return {}

    def _run_zip_bundle(self, t0: float) -> AnalysisJobResult:
        """Handle a ZIP bundle containing multiple JARs."""
        warnings: list[str] = []
        errors: list[str] = []
        sub_reports: list[SubReportData] = []

        bundle_dir = self.work_dir / "bundle"
        bundle_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(self.jar_path) as zf:
            jar_entries = [
                name for name in zf.namelist()
                if name.lower().endswith((".jar", ".war")) and not name.startswith("__MACOSX")
            ]
            if not jar_entries:
                warnings.append("ZIP contained no .jar or .war files")
            for name in jar_entries:
                dest = bundle_dir / Path(name).name
                dest.write_bytes(zf.read(name))
                try:
                    sr = self._analyse_single_jar(
                        jar_path=dest,
                        filename=Path(name).name,
                        installer_jar=None,
                        size_bytes=dest.stat().st_size,
                        depth=1,
                    )
                    sub_reports.append(sr)
                except Exception as e:
                    warnings.append(f"Failed to analyse {name}: {e}")

        # Use first JAR's manifest for top-level fields
        first_manifest = sub_reports[0].manifest if sub_reports else {}
        total_endpoints = sum(len(sr.endpoints) for sr in sub_reports)
        total_deps = sum(len(sr.dependencies) for sr in sub_reports)
        total_configs = sum(sum(cf.get("key_count", 0) or 0 for cf in sr.config_files) for sr in sub_reports)
        total_migrations = sum(len(sr.migration_scripts) for sr in sub_reports)
        ports = sorted({sr.declared_port for sr in sub_reports if sr.declared_port})
        services = [sr.service_name for sr in sub_reports if sr.service_name]
        spring_versions = {sr.spring_boot_version for sr in sub_reports if sr.spring_boot_version}

        summary = {
            "nested_jar_count": len(sub_reports),
            "total_endpoint_count": total_endpoints,
            "total_dependency_count": total_deps,
            "total_config_key_count": total_configs,
            "total_migration_script_count": total_migrations,
            "services_detected": services,
            "ports_detected": ports,
            "spring_boot_version": next(iter(spring_versions), None),
            "has_ssl_config": any(
                (cf.get("ssl_key_count") or 0) > 0
                for sr in sub_reports for cf in sr.config_files
            ),
            "has_database_config": any(
                (cf.get("db_key_count") or 0) > 0
                for sr in sub_reports for cf in sr.config_files
            ),
            "has_rabbitmq_config": any(
                (cf.get("mq_key_count") or 0) > 0
                for sr in sub_reports for cf in sr.config_files
            ),
        }

        consistency_findings = self._compute_consistency_findings(sub_reports)
        infra_requirements = self._compute_infra_requirements(sub_reports)
        actuator_exposure = self._compute_actuator_exposure(sub_reports)

        duration_ms = int((time.monotonic() - t0) * 1000)
        return AnalysisJobResult(
            report_id="",
            jar_type="zip-bundle",
            detection_confidence=1.0,
            manifest=first_manifest,
            summary=summary,
            sub_reports=sub_reports,
            warnings=warnings,
            errors=errors,
            duration_ms=duration_ms,
            consistency_findings=consistency_findings,
            infra_requirements=infra_requirements,
            actuator_exposure=actuator_exposure,
        )

    def _analyse_installer_entry(self, entry) -> SubReportData:
        """Analyse one nested installer JAR entry from NestedJarExtractor."""
        jar_path = entry.fat_jar_path or entry.extracted_path
        size = entry.extracted_path.stat().st_size if entry.extracted_path.exists() else 0
        return self._analyse_single_jar(
            jar_path=jar_path,
            filename=entry.filename,
            installer_jar=entry.filename,
            size_bytes=size,
            depth=entry.depth,
            entry=entry,
        )

    def _analyse_single_jar(
        self,
        jar_path: Path,
        filename: str,
        installer_jar: str | None,
        size_bytes: int,
        depth: int,
        entry=None,
    ) -> SubReportData:
        t0 = time.monotonic()
        sr = SubReportData(
            filename=filename,
            installer_jar=installer_jar,
            jar_path=jar_path,
            size_bytes=size_bytes,
            depth=depth,
        )

        if not jar_path or not jar_path.exists():
            sr.warnings.append(f"JAR path not found: {jar_path}")
            return sr

        try:
            detection = JarTypeDetector.detect(jar_path)
            sr.jar_type = detection.jar_type.value
            sr.detection_confidence = detection.confidence
        except Exception as e:
            sr.warnings.append(f"Detection failed: {e}")
            return sr

        # Manifest
        try:
            minfo = ManifestParser.from_jar(jar_path)
            sr.manifest = {
                "main_class": minfo.main_class,
                "start_class": minfo.start_class,
                "spring_boot_version": minfo.spring_boot_version,
                "implementation_version": minfo.implementation_version,
                "build_jdk": minfo.build_jdk,
                "all_attributes": minfo.all_attributes,
            }
            sr.start_class = minfo.start_class
            sr.spring_boot_version = minfo.spring_boot_version
            sr.implementation_version = minfo.implementation_version
        except Exception as e:
            sr.warnings.append(f"Manifest parse failed: {e}")

        # Installer metadata (part.yml etc.)
        try:
            meta = InstallerMetadataParser.from_jar(jar_path)
            if meta.part_yml:
                p = meta.part_yml
                sr.service_name = p.name
                sr.install_path = p.install_path
                sr.group_name = p.group
                sr.installer_metadata = {
                    "name": p.name,
                    "install_path": p.install_path,
                    "group": p.group,
                    "firewall_ports": p.firewall_ports,
                    "templates": p.templates,
                    "build_info": p.build_info,
                }
        except Exception as e:
            sr.warnings.append(f"Installer metadata failed: {e}")

        # Frontend installers — Node.js/UI, no Java bytecode
        if sr.jar_type == "frontend_installer":
            try:
                from app.services.jar_analyser.bundle_analyser import FrontendAnalyser
                with __import__('zipfile').ZipFile(jar_path) as zf:
                    fa = FrontendAnalyser.from_jar(zf)
                sr.installer_metadata.update({
                    "frontend": {
                        "package_name": fa.package_name,
                        "package_version": fa.package_version,
                        "description": fa.description,
                        "framework": fa.framework,
                        "app_version": fa.app_version,
                        "node_scripts": fa.node_scripts,
                        "dependencies": fa.dependencies,
                        "dev_dependencies": fa.dev_dependencies,
                        "server_entry_points": fa.server_entry_points,
                        "api_urls": fa.api_urls,
                        "app_yml": fa.app_yml,
                        "env_vars": fa.env_vars,
                    }
                })
                for rf in fa.raw_files:
                    sr.config_files.append({
                        "filename": rf["filename"],
                        "path_in_jar": rf["path"],
                        "file_type": "yaml" if rf["filename"].endswith((".yml", ".yaml")) else "json",
                        "profile": None,
                        "content": rf["content"],
                        "key_count": len(fa.api_urls),
                        "encrypted_count": 0,
                        "placeholder_count": sum(1 for u in fa.api_urls if "${" in u.get("value", "")),
                        "ssl_key_count": 0,
                        "db_key_count": 0,
                        "mq_key_count": 0,
                        "keys": [{"key": u["key"], "value": u["value"],
                                   "is_encrypted": False, "is_placeholder": "${" in u["value"],
                                   "category": "other"} for u in fa.api_urls],
                    })
                # Store npm packages as dependency rows so the Dependencies tab works
                for dep in fa.npm_deps:
                    sr.dependencies.append({
                        "filename": dep["name"],
                        "group_id": "devDependency" if dep["dev"] else "dependency",
                        "artifact_id": dep["name"],
                        "version": dep["version"],
                        "category": "dev" if dep["dev"] else "npm",
                        "size_bytes": None,
                        "maven_coordinates": f"{dep['name']}@{dep['version']}",
                        "source_path": "package.json",
                        "manifest_title": None,
                        "manifest_vendor": None,
                        "coordinates_source": "package.json",
                    })
            except Exception as e:
                sr.warnings.append(f"Frontend analysis failed: {e}")
            sr.duration_ms = int((time.monotonic() - t0) * 1000)
            return sr

        # Nginx config-only installers
        if sr.jar_type == "nginx_installer":
            try:
                from app.services.jar_analyser.bundle_analyser import NginxAnalyser
                with __import__('zipfile').ZipFile(jar_path) as zf:
                    na = NginxAnalyser.from_jar(zf)
                sr.installer_metadata.update({
                    "nginx": {
                        "upstreams": [{"name": u.name, "servers": u.servers, "keepalive": u.keepalive}
                                       for u in na.upstreams],
                        "ha_upstreams": [{"name": u.name, "servers": u.servers}
                                          for u in na.ha_upstreams],
                        "server_blocks": [{"listen_ports": s.listen_ports, "server_names": s.server_names,
                                            "ssl": s.ssl, "locations": s.locations}
                                           for s in na.server_blocks],
                        "service_dependencies": na.service_dependencies,
                    }
                })
                for rf in na.raw_files:
                    sr.config_files.append({
                        "filename": rf["filename"],
                        "path_in_jar": rf["path"],
                        "file_type": "conf",
                        "profile": "ha" if rf["filename"].endswith(".ha") else None,
                        "content": rf["content"],
                        "key_count": len(na.upstreams),
                        "encrypted_count": 0,
                        "placeholder_count": rf["content"].count("${"),
                        "ssl_key_count": 1 if "ssl" in rf["content"].lower() else 0,
                        "db_key_count": 0,
                        "mq_key_count": 0,
                        "keys": [{"key": f"upstream.{u.name}", "value": ", ".join(u.servers),
                                   "is_encrypted": False, "is_placeholder": any("${" in s for s in u.servers),
                                   "category": "other"} for u in na.upstreams],
                    })
            except Exception as e:
                sr.warnings.append(f"Nginx analysis failed: {e}")
            sr.duration_ms = int((time.monotonic() - t0) * 1000)
            return sr

        # Monitoring config-only installers (Grafana / Prometheus)
        if sr.jar_type == "monitoring_installer":
            try:
                from app.services.jar_analyser.bundle_analyser import MonitoringAnalyser
                with __import__('zipfile').ZipFile(jar_path) as zf:
                    ma = MonitoringAnalyser.from_jar(zf)
                sr.installer_metadata.update({
                    "monitoring": {
                        "grafana_dashboards": [{"filename": d.filename, "title": d.title,
                                                 "panel_count": d.panel_count, "panel_titles": d.panel_titles}
                                                for d in ma.grafana_dashboards],
                        "grafana_datasources": [{"name": ds.name, "type": ds.type, "url": ds.url}
                                                 for ds in ma.grafana_datasources],
                        "grafana_ini": ma.grafana_ini,
                        "prometheus_jobs": [{"job_name": j.job_name, "metrics_path": j.metrics_path,
                                              "targets": j.targets, "scheme": j.scheme,
                                              "has_auth": j.has_auth, "has_tls": j.has_tls}
                                             for j in ma.prometheus_jobs],
                    }
                })
                for rf in ma.raw_files:
                    sr.config_files.append({
                        "filename": rf["filename"],
                        "path_in_jar": rf["path"],
                        "file_type": "yaml" if rf["filename"].endswith((".yml", ".yaml")) else
                                     "ini" if rf["filename"].endswith(".ini") else "json",
                        "profile": None,
                        "content": rf["content"],
                        "key_count": 0,
                        "encrypted_count": 0,
                        "placeholder_count": 0,
                        "ssl_key_count": 1 if "tls" in rf["content"].lower() or "ssl" in rf["content"].lower() else 0,
                        "db_key_count": 0,
                        "mq_key_count": 0,
                        "keys": [],
                    })
            except Exception as e:
                sr.warnings.append(f"Monitoring analysis failed: {e}")
            sr.duration_ms = int((time.monotonic() - t0) * 1000)
            return sr

        # Dependencies
        try:
            deps = DependencyExtractor.from_jar(jar_path)
            sr.dependencies = [
                {
                    "filename": d.filename,
                    "group_id": d.group_id,
                    "artifact_id": d.artifact_id,
                    "version": d.version,
                    "category": d.category,
                    "size_bytes": d.size_bytes,
                    "maven_coordinates": d.maven_coordinates,
                    "source_path": d.source_path,
                    "manifest_title": d.manifest_title,
                    "manifest_vendor": d.manifest_vendor,
                    "coordinates_source": d.coordinates_source,
                }
                for d in deps
            ]
        except Exception as e:
            sr.warnings.append(f"Dependency extraction failed: {e}")

        # Config files
        try:
            configs = ConfigFileExtractor.from_jar(jar_path)
            for cf in configs:
                if cf.declared_port and not sr.declared_port:
                    sr.declared_port = cf.declared_port
                if not sr.application_name:
                    for k in cf.keys:
                        if k.key == "spring.application.name":
                            sr.application_name = k.value
                            break
                sr.config_files.append({
                    "filename": cf.filename,
                    "path_in_jar": cf.path_in_jar,
                    "file_type": cf.file_type,
                    "profile": cf.profile,
                    "content": cf.content,
                    "key_count": cf.key_count,
                    "encrypted_count": cf.encrypted_count,
                    "placeholder_count": cf.placeholder_count,
                    "ssl_key_count": cf.ssl_key_count,
                    "db_key_count": cf.db_key_count,
                    "mq_key_count": cf.mq_key_count,
                    "keys": [{"key": k.key, "value": k.value, "is_encrypted": k.is_encrypted,
                               "is_placeholder": k.is_placeholder, "category": k.category}
                              for k in cf.keys],
                })
        except Exception as e:
            sr.warnings.append(f"Config extraction failed: {e}")

        # Flyway migrations
        try:
            scripts = FlywayExtractor.from_jar(jar_path)
            sr.migration_scripts = [
                {
                    "filename": s.filename,
                    "version": s.version,
                    "description": s.description,
                    "script_type": s.script_type,
                    "size_bytes": s.size_bytes,
                    "statement_count": s.statement_count,
                    "ddl_operations": s.ddl_operations,
                    "tables_affected": s.tables_affected,
                    "content": s.content,
                }
                for s in scripts
            ]
        except Exception as e:
            sr.warnings.append(f"Flyway extraction failed: {e}")

        # Event definitions
        try:
            events = EventDefinitionExtractor.from_jar(jar_path)
            sr.event_files = [
                {
                    "filename": ev.filename,
                    "path_in_jar": ev.path_in_jar,
                    "content": ev.content,
                    "published": [
                        {
                            "entity": p.entity,
                            "actions": p.actions,
                            "operation": p.operation,
                            "consumers": p.consumers,
                            "consumer_types": p.consumer_types,
                            "parameters": p.parameters,
                            "rules": p.rules,
                            "payload_class": p.payload_class,
                        }
                        for p in ev.published_events
                    ],
                    "consumed": [
                        {
                            "source_service": c.source_service,
                            "entity": c.entity,
                            "action": c.action,
                            "operation": c.operation,
                            "handler": c.handler,
                            "parameters": c.parameters,
                            "rules": c.rules,
                            "payload_class": c.payload_class,
                            "queue": c.queue,
                            "exchange": c.exchange,
                            "routing_key": c.routing_key,
                        }
                        for c in ev.consumed_events
                    ],
                }
                for ev in events
            ]
        except Exception as e:
            sr.warnings.append(f"Event extraction failed: {e}")

        # Bytecode analysis (Phase 2)
        try:
            scan = AnnotationScanner.scan_jar(jar_path)
            endpoints = EndpointReconstructor.reconstruct(scan.controllers)

            # String constants (log messages, exception text, doc comments,
            # etc.) — free, since scan.all_classes already parsed each
            # class's constant pool for annotations; only the resolved
            # CONSTANT_String values were being discarded until now. Same
            # class scope as everything else scan_jar() reached (app's own
            # code, minus framework packages) — see JarStringConstant's
            # model docstring.
            sr.string_constants = [
                {"class_name": c.java_class_name, "value": v}
                for c in scan.all_classes
                for v in c.string_constants
            ]

            # Outbound integrations (Feign clients + @Value URL/host config
            # keys) — see outbound_integrations.py's own module docstring.
            # config_lookup flattens every config key this same sub-report's
            # own config files set, so a placeholder like ${vra.api.url} can
            # be resolved against a value actually set in this bundle, not
            # just displayed as the bare key name.
            try:
                from app.services.jar_analyser.outbound_integrations import extract_outbound_integrations
                config_lookup = {
                    k["key"]: k["value"]
                    for cf in sr.config_files
                    for k in cf.get("keys", [])
                    if not k.get("is_placeholder")
                }
                sr.outbound_integrations = [
                    {
                        "kind": oi.kind, "class_name": oi.class_name, "target": oi.target,
                        "config_key": oi.config_key, "raw_value": oi.raw_value,
                        "resolved_value": oi.resolved_value,
                    }
                    for oi in extract_outbound_integrations(scan.all_classes, config_lookup)
                ]
            except Exception as e:
                sr.warnings.append(f"Outbound integration extraction failed: {e}")

            # Spring Cloud Gateway routes (YAML config + @Bean DSL)
            try:
                from app.services.jar_analyser.gateway import GatewayRouteExtractor
                gw_routes = GatewayRouteExtractor.from_jar(jar_path)
                if gw_routes:
                    endpoints = endpoints + gw_routes
            except Exception as gw_err:
                sr.warnings.append(f"Gateway route extraction failed: {gw_err}")

            sr.endpoints = [
                {
                    "controller_class": ep.controller_class,
                    "controller_simple": ep.controller_simple,
                    "http_method": ep.http_method,
                    "path": ep.path,
                    "full_path": ep.full_path,
                    "base_path": ep.base_path,
                    "method_name": ep.method_name,
                    "parameters": [
                        {"name": p.name, "location": p.location, "java_type": p.java_type,
                         "simple_type": p.simple_type, "required": p.required,
                         "default_value": p.default_value}
                        for p in ep.parameters
                    ],
                    "request_body": {
                        "name": ep.request_body.name, "location": ep.request_body.location,
                        "java_type": ep.request_body.java_type, "simple_type": ep.request_body.simple_type,
                        "required": ep.request_body.required,
                    } if ep.request_body else None,
                    "return_type": {
                        "java_type": ep.return_type.java_type,
                        "simple_type": ep.return_type.simple_type,
                        "generic_parameter": ep.return_type.generic_parameter,
                    } if ep.return_type else None,
                    "security": {
                        "annotation": ep.security.annotation,
                        "expression": ep.security.expression,
                        "parsed_auth": ep.security.parsed_auth,
                    } if ep.security else None,
                    "confidence": ep.confidence,
                    "source_annotation": ep.source_annotation,
                    "signature_key": ep.signature_key,
                    "deprecated": ep.deprecated,
                    "doc_summary": ep.doc_summary,
                    "doc_description": ep.doc_description,
                }
                for ep in endpoints
            ]
            sr.warnings.extend(scan.warnings)

            # Scheduled jobs (@Scheduled / @Schedules) — any class, not just controllers
            try:
                from app.services.jar_analyser.scheduled_jobs import extract_scheduled_jobs
                sr.scheduled_jobs = [
                    {
                        "declaring_class": job.declaring_class,
                        "declaring_class_simple": job.declaring_class_simple,
                        "method_name": job.method_name,
                        "cron": job.cron,
                        "fixed_rate_ms": job.fixed_rate_ms,
                        "fixed_delay_ms": job.fixed_delay_ms,
                        "initial_delay_ms": job.initial_delay_ms,
                        "zone": job.zone,
                        "is_config_driven": job.is_config_driven,
                        "display": job.display,
                    }
                    for job in extract_scheduled_jobs(scan.all_classes)
                ]
            except Exception as sched_err:
                sr.warnings.append(f"Scheduled job extraction failed: {sched_err}")

            # Package structure
            pkg = PackageAnalyser.analyse(scan.all_classes)
            sr.package_structure = {
                "root_packages": pkg.root_packages,
                "package_count": pkg.package_count,
                "class_count": pkg.class_count,
                "layer_summary": [
                    {"layer": ls.layer, "package": ls.package, "class_count": ls.class_count}
                    for ls in pkg.layer_summary
                ],
            }

            # Class file versions
            if scan.class_file_versions:
                from app.services.jar_analyser.classfile import _MAJOR_TO_JAVA
                mn = scan.min_class_version
                mx = scan.max_class_version
                sr.class_file_versions = {
                    "min": mn, "max": mx,
                    "java_version": _MAJOR_TO_JAVA.get(mx, str(mx)) if mx else None,
                }
        except Exception as e:
            sr.warnings.append(f"Bytecode analysis failed: {e}")

        # Workflow detection (Stage 3)
        try:
            from app.services.jar_analyser.workflows import WorkflowDetector
            detected = WorkflowDetector.detect(sr.endpoints)
            sr.workflows = [
                {
                    "name": wf.name,
                    "description": wf.description,
                    "category": wf.category,
                    "source": wf.source,
                    "steps": [
                        {
                            "name": s.name,
                            "method": s.method,
                            "path": s.path,
                            "description": s.description,
                            "input_from": s.input_from,
                            "output": s.output,
                            "query_params": s.query_params,
                            "body_fields": s.body_fields,
                            "poll_until": s.poll_until,
                            "endpoint_ref": s.endpoint_ref,
                        }
                        for s in wf.steps
                    ],
                }
                for wf in detected
            ]
        except Exception as e:
            sr.warnings.append(f"Workflow detection failed: {e}")

        # DTO schema extraction (Stage 1 + Stage 2 + Stage 5 payload classes)
        schemas: dict = {}
        polymorphic_info: dict = {}
        try:
            from app.services.jar_analyser.dto_scanner import DtoScanner, collect_seed_classes, scan_all_enums
            from app.services.jar_analyser.config_examples import CURATED_ROOT_SEEDS
            # Stage 1: endpoint-seeded DTO scan
            seeds = collect_seed_classes(sr.endpoints)
            # Stage 5: add event payload classes to seeds
            for ef in sr.event_files:
                for c in ef.get("consumed", []):
                    pc = c.get("payload_class")
                    if pc:
                        seeds.add(pc)
                for p in ef.get("published", []):
                    pc = p.get("payload_class")
                    if pc:
                        seeds.add(pc)
            # Curated config/design-document root classes (see config_examples.py)
            # — harmless no-op for jars that don't contain any of them, since
            # DtoScanner.scan() already skips classes it can't find silently.
            seeds |= CURATED_ROOT_SEEDS
            scanner = DtoScanner(jar_path)
            schemas, polymorphic_info = scanner.scan(seeds) if seeds else ({}, {})
            # Stage 2: sweep all enum classes in the JAR
            all_enums = scan_all_enums(jar_path)
            # Merge — endpoint-seeded schemas take precedence (may have richer data)
            for k, v in all_enums.items():
                if k not in schemas:
                    schemas[k] = v
            sr.dto_schemas = [
                {
                    "class_name": s.class_name,
                    "simple_name": s.simple_name,
                    "is_enum": s.is_enum,
                    "is_lombok": s.is_lombok,
                    "source_note": s.source_note,
                    "enum_values": s.enum_values,
                    "description": s.description,
                    "polymorphic_base": polymorphic_info.get(s.class_name, (None, None))[0],
                    "discriminator_value": polymorphic_info.get(s.class_name, (None, None))[1],
                    "fields": [
                        {
                            "name": f.name,
                            "json_name": f.json_name,
                            "java_type": f.java_type,
                            "simple_type": f.simple_type,
                            "openapi_type": f.openapi_type,
                            "openapi_format": f.openapi_format,
                            "required": f.required,
                            "nullable": f.nullable,
                            "constraints": f.constraints,
                            "is_collection": f.is_collection,
                            "collection_element_type": f.collection_element_type,
                            "is_map": f.is_map,
                            "json_ignored": f.json_ignored,
                            "is_enum_type": f.is_enum_type,
                            "description": f.description,
                            "default_value": f.default_value,
                        }
                        for f in s.fields
                    ],
                }
                for s in schemas.values()
            ]
        except Exception as e:
            sr.warnings.append(f"DTO schema extraction failed: {e}")

        # Config/design document examples — for any curated root class that
        # was actually reachable above (schemas/polymorphic_info from the DTO
        # stage), prefer a real bundled example if the jar ships one, else
        # synthesize a structurally-valid one. See config_examples.py.
        try:
            from app.services.jar_analyser.config_examples import (
                CURATED_ROOT_SEEDS, find_bundled_examples, synthesize_example,
            )
            present_roots = {r for r in CURATED_ROOT_SEEDS if r in schemas}
            if present_roots:
                bundled = find_bundled_examples(jar_path, present_roots, schemas)
                for root in present_roots:
                    if root in bundled:
                        sr.config_examples.append({
                            "root_class_name": root, "format": "yaml",
                            "source": "bundled", "content": bundled[root],
                        })
                        continue
                    synthesized = synthesize_example(root, schemas, polymorphic_info)
                    if synthesized:
                        sr.config_examples.append({
                            "root_class_name": root, "format": "yaml",
                            "source": "synthesized", "content": synthesized,
                        })
        except Exception as e:
            sr.warnings.append(f"Config example synthesis failed: {e}")

        # Honest confidence & opacity flagging (Stage 5) — needs sr.dto_schemas,
        # so must run after DTO extraction above.
        try:
            from app.services.jar_analyser.endpoint_confidence import refine_endpoint_confidence
            refine_endpoint_confidence(sr.endpoints, sr.dto_schemas)
        except Exception as e:
            sr.warnings.append(f"Endpoint confidence refinement failed: {e}")

        # Error response catalogue (Stage 6)
        try:
            from app.services.jar_analyser.error_catalogue import ErrorCatalogueExtractor
            error_handlers = ErrorCatalogueExtractor.from_jar(jar_path)
            sr.error_responses = [
                {
                    "http_status": e.http_status,
                    "exception_class": e.exception_class,
                    "response_schema_class": e.response_schema_class,
                    "scope": e.scope,
                    "controller_class": e.controller_class,
                    "fields": [],
                }
                for e in error_handlers
            ]
        except Exception as e:
            sr.warnings.append(f"Error catalogue extraction failed: {e}")

        # Perceived Purpose narrative (Stage 6) — needs endpoints, dependencies,
        # dto_schemas, migration_scripts and event_files, so must run last.
        try:
            from app.services.jar_analyser.purpose_narrative import compute_purpose_narrative
            sr.purpose_narrative = compute_purpose_narrative(sr)
        except Exception as e:
            sr.warnings.append(f"Purpose narrative synthesis failed: {e}")

        sr.duration_ms = int((time.monotonic() - t0) * 1000)
        return sr


def compute_hashes(data: bytes) -> tuple[str, str]:
    return (
        hashlib.sha256(data).hexdigest(),
        hashlib.md5(data).hexdigest(),
    )
