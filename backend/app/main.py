import asyncio
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI

from app.core.config import settings

logger = logging.getLogger(__name__)


class ErrorBufferHandler(logging.Handler):
    """Logging handler that captures WARNING+ into the diagnostics error buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        from app.api.v1.diagnostics import log_error
        if record.levelno >= logging.WARNING:
            log_error(
                level=record.levelname,
                message=record.getMessage(),
                source=f"{record.pathname}:{record.lineno}" if record.pathname else record.name,
                context={"logger": record.name},
            )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup
    from app.core.database import init_db, async_session
    await init_db()

    # One-shot sweep for orphaned JAR Analyser decompile work directories
    # (crash/restart mid-run skips the run's own cleanup) — see
    # Documentation/jar_analyser_production_readiness_plan.md, Part D.
    from app.api.v1.jar_analyser import cleanup_stale_decompile_workdirs
    await cleanup_stale_decompile_workdirs()

    # Attach error buffer handler to root logger
    error_handler = ErrorBufferHandler()
    error_handler.setLevel(logging.WARNING)
    logging.getLogger().addHandler(error_handler)

    # Start background tasks
    tasks: list[asyncio.Task] = []  # type: ignore[type-arg]

    # Expiry scanner
    from app.services.expiry_scanner import run_expiry_scanner
    from app.core.database import async_session as session_factory
    tasks.append(asyncio.create_task(run_expiry_scanner(session_factory)))

    # OCSP cert renewal
    tasks.append(asyncio.create_task(_run_ocsp_cert_renewal()))

    # Scheduled backup
    if settings.BACKUP_ENABLED:
        tasks.append(asyncio.create_task(_run_scheduled_backup()))

    # Notification digest scheduler
    if settings.SMTP_ENABLED:
        from app.services.notification_service import run_digest_scheduler
        tasks.append(asyncio.create_task(run_digest_scheduler(session_factory)))

    # Daily compliance scan
    tasks.append(asyncio.create_task(_run_compliance_scan(session_factory)))

    # Build Manager environment TTL auto-destroy
    from app.services.build_manager.environment_service import run_environment_ttl_scheduler
    tasks.append(asyncio.create_task(run_environment_ttl_scheduler(session_factory)))

    # Build Manager secret rotation overdue scanner
    from app.services.build_manager.secrets_service import run_secret_rotation_scanner
    tasks.append(asyncio.create_task(run_secret_rotation_scanner(session_factory)))

    # Docs/Bugs Trash retention sweep (Improvements Plan Stage 7)
    from app.services.trash_sweep import run_trash_purge_scheduler
    tasks.append(asyncio.create_task(run_trash_purge_scheduler(session_factory)))

    logger.info("SSL Certificate Manager started")
    yield

    # Shutdown — cancel background tasks
    for task in tasks:
        task.cancel()
    logger.info("SSL Certificate Manager stopped")


async def _run_scheduled_backup() -> None:
    """Run automated backups at configured interval."""
    from app.services.backup_engine import create_backup
    interval = settings.BACKUP_INTERVAL_HOURS * 3600

    # Initial delay (don't backup immediately on startup)
    await asyncio.sleep(60)

    while True:
        try:
            filename, size, checksum = create_backup()
            logger.info(f"Scheduled backup complete: {filename} ({size} bytes)")
        except Exception as e:
            logger.error(f"Scheduled backup failed: {e}")
        await asyncio.sleep(interval)


async def _run_ocsp_cert_renewal() -> None:
    """Renew OCSP signing certs that are expiring within 7 days."""
    from app.core.database import async_session
    from app.models.ca import CertificateAuthority
    from app.services.ocsp_delegation import ensure_ocsp_cert
    from sqlalchemy import select

    # Initial delay
    await asyncio.sleep(30)

    while True:
        try:
            async with async_session() as db:
                result = await db.execute(select(CertificateAuthority))
                cas = result.scalars().all()
                for ca in cas:
                    if not ca.key_blob:
                        continue  # Skip offline CAs
                    try:
                        await ensure_ocsp_cert(ca, db)
                    except Exception as e:
                        logger.warning(f"OCSP cert renewal failed for CA '{ca.cn}': {e}")
        except Exception as e:
            logger.error(f"OCSP cert renewal task error: {e}")

        # Check every 6 hours
        await asyncio.sleep(6 * 3600)


async def _run_compliance_scan(session_factory) -> None:
    """Run daily automated compliance scan."""
    import json
    from datetime import datetime, timezone
    from app.services.compliance_scanner import run_full_scan
    from app.models.compliance import ComplianceScan

    # Initial delay — wait 2 minutes after startup
    await asyncio.sleep(120)

    while True:
        try:
            async with session_factory() as db:
                result = await run_full_scan(db)
                now = datetime.now(timezone.utc)
                summary = {"violations_by_rule": {}, "warnings_by_rule": {}}
                for f in result.findings:
                    bucket = "violations_by_rule" if f["severity"] == "violation" else "warnings_by_rule"
                    summary[bucket][f["rule"]] = summary[bucket].get(f["rule"], 0) + 1

                scan = ComplianceScan(
                    scan_type="full",
                    status="completed",
                    total_checked=result.total_checked,
                    total_violations=result.violations,
                    total_warnings=result.warnings,
                    results_json=json.dumps(result.findings),
                    summary_json=json.dumps(summary),
                    scanned_at=now,
                )
                db.add(scan)
                await db.commit()
                logger.info(f"Scheduled compliance scan: {result.violations} violations, {result.warnings} warnings")
        except Exception as e:
            logger.error(f"Scheduled compliance scan failed: {e}")

        # Run every 24 hours
        await asyncio.sleep(24 * 3600)


app = FastAPI(
    title="SSL Certificate Manager",
    description="Self-Signed Certificate Authority, Trust Store & CSR Tool",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

# Middleware
from app.middleware.api_version import APIVersionMiddleware
app.add_middleware(APIVersionMiddleware)
from app.middleware.rate_limit import RateLimitMiddleware
app.add_middleware(RateLimitMiddleware)
from app.middleware.source_ip import SourceIPMiddleware
app.add_middleware(SourceIPMiddleware)

# Register routers
from app.api.v1.ca import router as ca_router
from app.api.v1.certificates import router as cert_router
from app.api.v1.truststores import router as truststore_router
from app.api.v1.export import router as export_router
from app.api.v1.crl import router as crl_router
from app.api.v1.audit import router as audit_router
from app.api.v1.csr import router as csr_router
from app.api.v1.csr_renew import router as csr_renew_router
from app.api.v1.backup import router as backup_router
from app.api.v1.settings import router as settings_router
from app.api.v1.about import router as about_router
from app.api.v1.tools import router as tools_router
from app.api.v1.tools_compat import router as tools_compat_router
from app.api.v1.tools_extra import router as tools_extra_router
from app.api.v1.help import router as help_router
from app.api.v1.diagnostics import router as diagnostics_router
from app.api.v1.pki import router as pki_router
from app.api.v1.templates import router as templates_router
from app.api.v1.auth import router as auth_router
from app.api.v1.users import router as users_router
from app.api.v1.api_keys import router as api_keys_router
from app.api.v1.lifecycle import router as lifecycle_router
from app.api.v1.reports import router as reports_router
from app.api.v1.approvals import router as approvals_router
from app.api.v1.provisioning import router as provisioning_router
from app.api.v1.key_ceremony import router as key_ceremony_router
from app.api.v1.est import router as est_router
from app.api.v1.tenants import router as tenants_router
from app.api.v1.ct import router as ct_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.cross_cert import router as cross_cert_router
from app.api.v1.k8s_issuer import router as k8s_router
from app.api.v1.compliance import router as compliance_router
from app.api.v1.key_escrow import router as key_escrow_router
from app.api.v2 import router as v2_router
from app.api.v2.sdk import router as sdk_router
from app.api.v1.scep import router as scep_router
from app.api.v1.build_manager import router as build_manager_router
from app.api.v1.jar_analyser import router as jar_analyser_router
from app.api.v1.infra_diagnostics import router as infra_diagnostics_router
from app.api.v1.aws_credentials import router as aws_credentials_router
from app.api.v1.docs import router as docs_router
from app.api.v1.bug_tracker import router as bug_tracker_router
from app.api.v1.category_rules import router as category_rules_router
from app.api.v1.neural import router as neural_router

app.include_router(ca_router)
app.include_router(cert_router)
app.include_router(truststore_router)
app.include_router(export_router)
app.include_router(crl_router)
app.include_router(audit_router)
app.include_router(csr_router)
app.include_router(csr_renew_router)
app.include_router(backup_router)
app.include_router(settings_router)
app.include_router(about_router)
app.include_router(tools_router)
app.include_router(tools_compat_router)
app.include_router(tools_extra_router)
app.include_router(help_router)
app.include_router(diagnostics_router)
app.include_router(pki_router)
app.include_router(templates_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(api_keys_router)
app.include_router(lifecycle_router)
app.include_router(reports_router)
app.include_router(approvals_router)
app.include_router(provisioning_router)
app.include_router(key_ceremony_router)
app.include_router(est_router)
app.include_router(tenants_router)
app.include_router(ct_router)
app.include_router(notifications_router)
app.include_router(cross_cert_router)
app.include_router(k8s_router)
app.include_router(compliance_router)
app.include_router(key_escrow_router)
app.include_router(v2_router)
app.include_router(sdk_router)
app.include_router(scep_router)
app.include_router(build_manager_router)
app.include_router(jar_analyser_router)
app.include_router(infra_diagnostics_router)
app.include_router(aws_credentials_router)
app.include_router(docs_router)
app.include_router(bug_tracker_router)
app.include_router(category_rules_router)
app.include_router(neural_router)


@app.get("/api/v1/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint — exempt from API key auth."""
    from app.core.database import engine
    # Quick DB connectivity check
    try:
        async with engine.connect() as conn:
            await conn.execute(sa_text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"

    import shutil
    keytool_status = "ok" if shutil.which("keytool") else "unavailable"

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "version": settings.APP_VERSION,
        "database": db_status,
        "keytool": keytool_status,
    }


from sqlalchemy import text as sa_text
