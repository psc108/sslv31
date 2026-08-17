"""
P5-06: Synthetic log corpus generator.

Produces labelled (LogWindow, label) pairs across 9 scenario types that
mirror real Java microservice failure modes seen in production.

Scenario types
--------------
  healthy          — normal INFO-only flow, no errors
  warn_retry       — transient WARN + retry, resolves successfully
  oom              — OutOfMemoryError, GC overhead, heap exhaustion
  connection_refused — downstream service unreachable, ConnectException
  timeout_cascade  — upstream timeout triggering downstream failures
  auth_failure     — 401/403, token expiry, credential errors
  deadlock         — thread deadlock, lock acquisition timeout
  ssl_error        — SSL handshake failure, certificate chain errors
  db_timeout       — connection pool exhaustion, query timeout

Corpus composition (configurable via n_* params):
  healthy          : 300  (majority class — calibrates IF baseline)
  warn_retry       : 80
  oom              : 30   ← anomalous
  connection_refused: 35  ← anomalous
  timeout_cascade  : 35   ← anomalous
  auth_failure     : 25   ← anomalous
  deadlock         : 20   ← anomalous
  ssl_error        : 40   ← anomalous
  db_timeout       : 20   ← anomalous

Public API
----------
  from phase5.log_intelligence.synthetic_corpus import generate_corpus

  windows, labels = generate_corpus()
  # windows : list[LogWindow]
  # labels  : list[str]
"""

from __future__ import annotations

import random
import re
from datetime import datetime, timedelta

from .ingestion import ingest_lines

_BASE_TS = datetime(2026, 8, 13, 12, 0, 0)

# Logger abbreviations matching real Spring Boot logback output
_SVC   = "c.d.e.f.service.ServiceDesignService"
_REPO  = "c.d.e.f.repository.ServiceDesignRepository"
_SSL   = "c.d.e.f.security.SslContextFactory"
_DB    = "c.d.e.f.db.ConnectionPool"
_GW    = "c.d.e.f.gateway.ApiGatewayClient"
_AUTH  = "c.d.e.f.security.JwtAuthFilter"
_SCHED = "c.d.e.f.scheduler.ImportScheduler"
_LOCK  = "c.d.e.f.db.DistributedLockManager"


def _ts(base: datetime, offset_ms: int) -> str:
    t = base + timedelta(milliseconds=offset_ms)
    return t.strftime("%Y-%m-%d %H:%M:%S.") + f"{t.microsecond // 1000:03d}"


def _line(ts: str, level: str, thread: str, logger: str, mdc: str, msg: str) -> str:
    return f"{ts}  {level:<5} [{thread}] {logger} [{mdc}] : {msg}"


# ---------------------------------------------------------------------------
# Scenario builders
# ---------------------------------------------------------------------------

def _healthy(mdc: str, entity: str, base: datetime) -> list[str]:
    return [
        _line(_ts(base, 0),   "INFO",  "exec-1", _SVC,  mdc, f"Start import {entity}"),
        _line(_ts(base, 45),  "INFO",  "exec-1", _SVC,  mdc, f"Fetched 12 designs for {entity}"),
        _line(_ts(base, 110), "INFO",  "exec-1", _REPO, mdc, f"Persisted 12 records for {entity}"),
        _line(_ts(base, 125), "INFO",  "exec-1", _SVC,  mdc, f"Import complete {entity}"),
    ]


def _warn_retry(mdc: str, entity: str, base: datetime) -> list[str]:
    return [
        _line(_ts(base, 0),   "INFO",  "exec-2", _SVC,  mdc, f"Start import {entity}"),
        _line(_ts(base, 40),  "WARN",  "exec-2", _SVC,  mdc, f"Transient failure for {entity}, retrying (attempt 1/3)"),
        _line(_ts(base, 540), "WARN",  "exec-2", _SVC,  mdc, f"Transient failure for {entity}, retrying (attempt 2/3)"),
        _line(_ts(base, 1100),"INFO",  "exec-2", _SVC,  mdc, f"Import complete on retry for {entity}"),
    ]


def _oom(mdc: str, entity: str, base: datetime) -> list[str]:
    return [
        _line(_ts(base, 0),    "INFO",  "exec-3",    _SCHED, mdc, f"Scheduled batch import starting, {entity}"),
        _line(_ts(base, 200),  "WARN",  "exec-3",    _SCHED, mdc, "GC overhead limit exceeded — heap at 94%"),
        _line(_ts(base, 210),  "ERROR", "exec-3",    _SCHED, mdc, "java.lang.OutOfMemoryError: Java heap space"),
        _line(_ts(base, 211),  "ERROR", "exec-3",    _SCHED, mdc, "    at java.util.Arrays.copyOf(Arrays.java:3210)"),
        _line(_ts(base, 211),  "ERROR", "exec-3",    _SCHED, mdc, "    at com.dxc.ecs.fulfillment.scheduler.ImportScheduler.loadBatch(ImportScheduler.java:88)"),
        _line(_ts(base, 212),  "ERROR", "exec-3",    _SCHED, mdc, "    at com.dxc.ecs.fulfillment.scheduler.ImportScheduler.runImport(ImportScheduler.java:55)"),
        _line(_ts(base, 500),  "WARN",  "GC-thread", _SCHED, mdc, "Full GC triggered — pause 4200ms"),
        _line(_ts(base, 4700), "ERROR", "exec-3",    _SCHED, mdc, "Batch import aborted due to memory pressure"),
    ]


def _connection_refused(mdc: str, entity: str, base: datetime) -> list[str]:
    return [
        _line(_ts(base, 0),   "INFO",  "exec-4", _GW,  mdc, f"Calling downstream catalogue-service for {entity}"),
        _line(_ts(base, 50),  "ERROR", "exec-4", _GW,  mdc, "java.net.ConnectException: Connection refused: catalogue-service:8080"),
        _line(_ts(base, 51),  "ERROR", "exec-4", _GW,  mdc, "    at sun.nio.ch.Net.connect0(Native Method)"),
        _line(_ts(base, 51),  "ERROR", "exec-4", _GW,  mdc, "    at com.dxc.ecs.fulfillment.gateway.ApiGatewayClient.call(ApiGatewayClient.java:112)"),
        _line(_ts(base, 52),  "WARN",  "exec-4", _GW,  mdc, "Circuit breaker OPEN for catalogue-service after 3 consecutive failures"),
        _line(_ts(base, 53),  "ERROR", "exec-4", _SVC, mdc, f"Import aborted for {entity} — downstream unavailable"),
    ]


def _timeout_cascade(mdc: str, entity: str, base: datetime) -> list[str]:
    return [
        _line(_ts(base, 0),    "INFO",  "exec-5", _SVC, mdc, f"Start import {entity}"),
        _line(_ts(base, 100),  "INFO",  "exec-5", _GW,  mdc, "Calling pricing-service (timeout=5000ms)"),
        _line(_ts(base, 5100), "ERROR", "exec-5", _GW,  mdc, "java.util.concurrent.TimeoutException: pricing-service did not respond within 5000ms"),
        _line(_ts(base, 5101), "ERROR", "exec-5", _GW,  mdc, "    at com.dxc.ecs.fulfillment.gateway.ApiGatewayClient.awaitResponse(ApiGatewayClient.java:201)"),
        _line(_ts(base, 5102), "WARN",  "exec-5", _SVC, mdc, "Partial import — pricing data unavailable, falling back to cached values"),
        _line(_ts(base, 5200), "ERROR", "exec-5", _SVC, mdc, f"Import failed for {entity}: downstream timeout cascade"),
    ]


def _auth_failure(mdc: str, base: datetime) -> list[str]:
    return [
        _line(_ts(base, 0),  "INFO",  "http-1", _AUTH, mdc, "Validating JWT token for request"),
        _line(_ts(base, 5),  "WARN",  "http-1", _AUTH, mdc, "JWT token expired at 2026-08-13T11:58:00Z (now 12:00:01)"),
        _line(_ts(base, 6),  "ERROR", "http-1", _AUTH, mdc, "io.jsonwebtoken.ExpiredJwtException: JWT expired"),
        _line(_ts(base, 7),  "ERROR", "http-1", _AUTH, mdc, "    at io.jsonwebtoken.impl.DefaultJwtParser.parse(DefaultJwtParser.java:418)"),
        _line(_ts(base, 7),  "ERROR", "http-1", _AUTH, mdc, "    at com.dxc.ecs.fulfillment.security.JwtAuthFilter.doFilter(JwtAuthFilter.java:67)"),
        _line(_ts(base, 8),  "WARN",  "http-1", _AUTH, mdc, "Returning 401 Unauthorized — token refresh required"),
    ]


def _deadlock(mdc: str, entity: str, base: datetime) -> list[str]:
    return [
        _line(_ts(base, 0),    "INFO",  "exec-6", _LOCK, mdc, f"Acquiring distributed lock for {entity}"),
        _line(_ts(base, 30000),"ERROR", "exec-6", _LOCK, mdc, "Lock acquisition timeout after 30000ms — possible deadlock"),
        _line(_ts(base, 30001),"ERROR", "exec-6", _LOCK, mdc, "com.dxc.ecs.fulfillment.db.LockTimeoutException: Could not acquire lock on resource " + entity),
        _line(_ts(base, 30002),"ERROR", "exec-6", _LOCK, mdc, "    at com.dxc.ecs.fulfillment.db.DistributedLockManager.acquire(DistributedLockManager.java:144)"),
        _line(_ts(base, 30002),"ERROR", "exec-6", _LOCK, mdc, "    at com.dxc.ecs.fulfillment.service.ServiceDesignService.importServiceDesigns(ServiceDesignService.java:1001)"),
        _line(_ts(base, 30003),"WARN",  "exec-6", _LOCK, mdc, "Thread dump requested — 2 threads waiting on same lock"),
    ]


def _ssl_error(mdc: str, base: datetime) -> list[str]:
    return [
        _line(_ts(base, 0),  "INFO",  "http-2", _SSL, mdc, "Initiating TLS handshake with keystone-service:8443"),
        _line(_ts(base, 10), "ERROR", "http-2", _SSL, mdc, "javax.net.ssl.SSLHandshakeException: PKIX path building failed"),
        _line(_ts(base, 11), "ERROR", "http-2", _SSL, mdc, "    at sun.security.ssl.Alert.createSSLException(Alert.java:131)"),
        _line(_ts(base, 11), "ERROR", "http-2", _SSL, mdc, "    at com.dxc.ecs.fulfillment.security.SslContextFactory.createContext(SslContextFactory.java:88)"),
        _line(_ts(base, 12), "ERROR", "http-2", _SSL, mdc, "Caused by: sun.security.validator.ValidatorException: PKIX path building failed: unable to find valid certification path to requested target"),
        _line(_ts(base, 13), "WARN",  "http-2", _SSL, mdc, "TLS handshake failed — check truststore configuration"),
    ]


def _db_timeout(mdc: str, entity: str, base: datetime) -> list[str]:
    return [
        _line(_ts(base, 0),    "INFO",  "exec-7", _DB,   mdc, f"Acquiring DB connection for {entity}"),
        _line(_ts(base, 5000), "ERROR", "exec-7", _DB,   mdc, "Connection pool exhausted — all 20 connections in use"),
        _line(_ts(base, 5001), "ERROR", "exec-7", _DB,   mdc, "com.zaxxer.hikari.pool.HikariPool$PoolInitializationException: Connection is not available, request timed out after 5000ms"),
        _line(_ts(base, 5002), "ERROR", "exec-7", _DB,   mdc, "    at com.zaxxer.hikari.pool.HikariPool.getConnection(HikariPool.java:213)"),
        _line(_ts(base, 5002), "ERROR", "exec-7", _DB,   mdc, "    at com.dxc.ecs.fulfillment.db.ConnectionPool.acquire(ConnectionPool.java:214)"),
        _line(_ts(base, 5003), "ERROR", "exec-7", _REPO, mdc, f"Repository operation failed for {entity} — no DB connection"),
    ]


# ---------------------------------------------------------------------------
# Entity key generator
# ---------------------------------------------------------------------------

_PREFIXES = ["BLUEPRINT", "SERVICE", "OFFER", "PRODUCT", "CATALOGUE"]
_SUFFIXES = ["W2K25", "W2K26", "Q1K25", "Q2K26", "H1K27"]


def _entity(i: int) -> str:
    prefix = _PREFIXES[i % len(_PREFIXES)]
    suffix = _SUFFIXES[(i // len(_PREFIXES)) % len(_SUFFIXES)]
    return f"{prefix}:{suffix[0]}-{suffix}:{i + 1}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_corpus(
    n_healthy: int = 300,
    n_warn_retry: int = 80,
    n_oom: int = 30,
    n_connection_refused: int = 35,
    n_timeout_cascade: int = 35,
    n_auth_failure: int = 25,
    n_deadlock: int = 20,
    n_ssl_error: int = 40,
    n_db_timeout: int = 20,
    seed: int = 42,
) -> tuple[list, list[str]]:
    """
    Generate a labelled synthetic corpus.

    Returns
    -------
    windows : list[LogWindow]
    labels  : list[str]  — ground-truth scenario name per window
    """
    rng = random.Random(seed)
    all_lines: list[str] = []
    segments: list[tuple[int, int, str]] = []
    base = _BASE_TS
    counter = 0

    def _add(lines: list[str], label: str) -> None:
        nonlocal counter, base
        start = len(all_lines)
        all_lines.extend(lines)
        segments.append((start, len(all_lines), label))
        base = base + timedelta(seconds=rng.uniform(10, 60))
        counter += 1

    for i in range(n_healthy):
        _add(_healthy(f"req-h{i:04d}", _entity(i), base), "healthy")

    for i in range(n_warn_retry):
        _add(_warn_retry(f"req-w{i:04d}", _entity(i + n_healthy), base), "warn_retry")

    offset = n_healthy + n_warn_retry
    for i in range(n_oom):
        _add(_oom(f"req-oom{i:04d}", _entity(i + offset), base), "oom")

    offset += n_oom
    for i in range(n_connection_refused):
        _add(_connection_refused(f"req-cr{i:04d}", _entity(i + offset), base), "connection_refused")

    offset += n_connection_refused
    for i in range(n_timeout_cascade):
        _add(_timeout_cascade(f"req-tc{i:04d}", _entity(i + offset), base), "timeout_cascade")

    offset += n_timeout_cascade
    for i in range(n_auth_failure):
        _add(_auth_failure(f"req-af{i:04d}", base), "auth_failure")

    offset += n_auth_failure
    for i in range(n_deadlock):
        _add(_deadlock(f"req-dl{i:04d}", _entity(i + offset), base), "deadlock")

    offset += n_deadlock
    for i in range(n_ssl_error):
        _add(_ssl_error(f"req-ssl{i:04d}", base), "ssl_error")

    offset += n_ssl_error
    for i in range(n_db_timeout):
        _add(_db_timeout(f"req-db{i:04d}", _entity(i + offset), base), "db_timeout")

    windows = ingest_lines(all_lines, gap_seconds=8.0)

    # Map each window back to its label via MDC key
    mdc_to_label: dict[str, str] = {}
    for start, end, label in segments:
        for raw_line in all_lines[start:end]:
            m = re.search(r"\[([^\]]+)\]\s*:", raw_line)
            if m:
                mdc_to_label[m.group(1).strip()] = label

    labels = [mdc_to_label.get(w.key, "healthy") for w in windows]
    return windows, labels


# Anomalous scenario names — used by test_p506.py for metric calculation
ANOMALOUS_LABELS = frozenset({
    "oom", "connection_refused", "timeout_cascade",
    "auth_failure", "deadlock", "ssl_error", "db_timeout",
})
