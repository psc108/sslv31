#!/usr/bin/env python3
"""One-off seed: broadens the Error KB (docs_error_kb.py) beyond the
existing Ansible/Spring/vRA-specific entries to cover the wider set of
runtime errors this LabTool's own golden-path templates can actually
produce - plain Java/JDK exceptions, Jackson/JSON, Spring Data/JPA,
outbound-client failures (Feign/connect/read-timeout - the runtime
counterpart to the JAR Analyser's static Outbound Integration Discovery
feature), and one category per non-Java product the Build Manager
installs (PostgreSQL, Redis, MongoDB, nginx, Node.js, HAProxy, Apache/PHP,
OpenLDAP, Docker) that wasn't already covered by the existing MySQL/
RabbitMQ/Keystone categories.

Same idempotent HTTP-API convention as migrate_kb_to_docs.py: reuses an
existing library/shelf by name, skips (409) a doc name that already
exists on its shelf. Safe to re-run.

Usage:
    BASE_URL=http://localhost API_KEY=... python backend/scripts/seed_wide_stack_error_kb.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE_URL = os.environ.get("BASE_URL", "http://localhost")
API_KEY = os.environ["API_KEY"]
API = f"{BASE_URL}/api/v1"


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict | list | None]:
    # RATE_LIMIT_GENERAL is 60/min (1 req/s average) - stay well under it.
    time.sleep(1.1)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method)
    req.add_header("X-API-Key", API_KEY)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        if e.code == 429:
            time.sleep(5)
            return call(method, path, body)
        return e.code, (json.loads(raw) if raw else None)


def render_kb_doc_content(
    severity: str, pattern: str, plain_english: str,
    causes: list[str], fix_steps: list[str], see_also_titles: list[str],
) -> str:
    """Mirrors app.services.docs_error_kb.render_kb_doc_content exactly -
    duplicated here (not imported) so this script stays a standalone HTTP
    client with no dependency on the backend's Python environment."""
    lines = [f"**Severity:** {severity}", f"**Pattern:** `{pattern}`", ""]
    if plain_english.strip():
        lines += [plain_english.strip(), ""]
    if causes:
        lines += ["## Likely Causes", ""]
        lines += [f"- {c}" for c in causes]
        lines += [""]
    if fix_steps:
        lines += ["## Fix Steps", ""]
        lines += [f"{i + 1}. {s}" for i, s in enumerate(fix_steps)]
        lines += [""]
    if see_also_titles:
        lines += ["## See Also", ""]
        lines += [f"- [[{t}]]" for t in see_also_titles]
        lines += [""]
    return "\n".join(lines).rstrip() + "\n"


ENTRIES: list[dict] = [
    # ---- Java/JDK Core ----
    dict(category="Java/JDK Core", severity="high", title="NullPointerException",
         pattern=r"java\.lang\.NullPointerException",
         plain_english="A method or field was accessed on a reference that was null at runtime - the JVM's most common runtime exception. Since Java 14+, the message usually names exactly which variable/method call was null (\"helpful NPE\").",
         causes=[
             "A field or local variable was never initialised before use (e.g. an @Autowired bean that wasn't actually wired because the class isn't a Spring-managed bean)",
             "An external call (DB query, REST call, map.get()) returned null and the result was used without a null check",
             "A chain of calls through several nested objects where one link (e.g. a lazy-loaded JPA relation) is null",
             "A collection or array element was expected to exist but was never populated or was removed earlier",
         ],
         fix_steps=[
             "Read the full message - Java 14+'s helpful-NPE text names the exact variable/method that was null",
             "Check the immediately preceding log lines for a failed lookup, missing config, or empty external response that explains why the value was never set",
             "Add an explicit null check or Optional at the boundary where the value first enters this code path, not deep inside it",
         ], see_also=[]),
    dict(category="Java/JDK Core", severity="medium", title="ClassCastException",
         pattern=r"java\.lang\.ClassCastException",
         plain_english="Code tried to cast an object to a type it isn't actually an instance of at runtime.",
         causes=[
             "Two different classloaders loaded the same class name (common when a jar is duplicated across a shared-lib folder and an app's own lib folder)",
             "A generic collection was populated via a raw type/unchecked cast, and a wrong concrete type ended up in it",
             "Deserialisation (Jackson etc.) produced a generic Map/List where a specific DTO type was expected, because target-type information was lost along the way",
         ], fix_steps=[], see_also=[]),
    dict(category="Java/JDK Core", severity="medium", title="ConcurrentModificationException",
         pattern=r"java\.util\.ConcurrentModificationException",
         plain_english="A collection (List/Map/Set) was structurally modified while being iterated.",
         causes=[
             "Removing/adding elements inside a for-each loop instead of using Iterator.remove() or Collection.removeIf()",
             "A second thread mutated a non-thread-safe collection while the first thread was iterating it",
         ], fix_steps=[], see_also=[]),
    dict(category="Java/JDK Core", severity="critical", title="OutOfMemoryError - Java heap space",
         pattern=r"java\.lang\.OutOfMemoryError:\s*Java heap space",
         plain_english="The JVM heap is exhausted and garbage collection can't free enough space to satisfy an allocation.",
         causes=[
             "-Xmx is set too low for the process's actual working set (especially inside a container - check it's sized relative to the container's cgroup memory limit, not host memory)",
             "A genuine memory leak: an unbounded cache, a listener/subscriber that's never unregistered, or a ThreadLocal that's never cleared",
             "A single request loading an unexpectedly large result set entirely into memory at once, because pagination/streaming was missing",
         ], fix_steps=[], see_also=["OOMKilled"]),
    dict(category="Java/JDK Core", severity="high", title="StackOverflowError",
         pattern=r"java\.lang\.StackOverflowError",
         plain_english="The call stack exceeded its maximum depth.",
         causes=[
             "Unbounded/unintended recursion, often from a missing or wrong base case",
             "Two objects' toString()/equals()/hashCode() calling each other - a common trap with Lombok-generated methods on both sides of a bidirectional JPA relationship",
         ], fix_steps=[], see_also=[]),
    dict(category="Java/JDK Core", severity="medium", title="ExecutionException / TimeoutException (java.util.concurrent)",
         pattern=r"java\.util\.concurrent\.(ExecutionException|TimeoutException)",
         plain_english="Thrown by Future.get()/CompletableFuture when the underlying async task either threw or didn't complete within the given timeout.",
         causes=[
             "For ExecutionException: the async task itself threw - the real cause is wrapped in .getCause(), check that, not this outer exception's own message",
             "For TimeoutException: a thread pool is saturated and the task was still queued (not yet running) when the timeout elapsed, which looks like slowness but is really pool exhaustion",
         ], fix_steps=[], see_also=[]),
    dict(category="Java/JDK Core", severity="high", title="ClassNotFoundException / NoClassDefFoundError",
         pattern=r"java\.lang\.(ClassNotFoundException|NoClassDefFoundError)",
         plain_english="A class that was present at compile time can't be found or loaded at runtime.",
         causes=[
             "A dependency jar is missing at runtime despite being present at compile time (a `provided`/`compileOnly` scope, or an excluded transitive dependency)",
             "Two jars on the classpath expect different major versions of the same shared dependency",
             "NoClassDefFoundError specifically: the class's own static initializer already threw once earlier (and was logged then) - every later reference now fails with this instead of the real root cause, so search backwards in the log for the first occurrence",
         ], fix_steps=[], see_also=[]),

    # ---- JSON/Jackson ----
    dict(category="JSON/Jackson", severity="medium", title="UnrecognizedPropertyException",
         pattern=r"com\.fasterxml\.jackson\.databind\.exc\.UnrecognizedPropertyException",
         plain_english="Incoming JSON has a field the target DTO class doesn't declare, and unknown-property tolerance isn't enabled.",
         causes=[
             "@JsonIgnoreProperties(ignoreUnknown = true) isn't set on the target class or the ObjectMapper's global config",
             "The API contract changed on one side (a field was added) without the consuming side's DTO being updated to match",
         ], fix_steps=[], see_also=[]),
    dict(category="JSON/Jackson", severity="medium", title="InvalidFormatException / MismatchedInputException",
         pattern=r"com\.fasterxml\.jackson\.databind\.exc\.(InvalidFormatException|MismatchedInputException)",
         plain_english="A JSON value's type or shape doesn't match what the target Java field expects.",
         causes=[
             "A string value (e.g. \"123\") was sent where a numeric/boolean field was expected without a lenient deserializer configured",
             "A JSON object was sent where an array was expected, or vice versa",
             "A date/time string doesn't match the format/pattern the target field's deserializer expects",
         ], fix_steps=[], see_also=[]),
    dict(category="JSON/Jackson", severity="high", title="JsonParseException / JsonEOFException",
         pattern=r"com\.fasterxml\.jackson\.core\.(JsonParseException|io\.JsonEOFException)",
         plain_english="The response/request body being parsed isn't valid (or complete) JSON at all.",
         causes=[
             "An upstream proxy/gateway returned an HTML error page or plain-text message instead of the expected JSON body - often accompanies a 502/504 from that same call",
             "The body was truncated because the connection dropped mid-stream, or a response-size limit cut it short",
         ], fix_steps=[], see_also=["502 Bad Gateway", "504 Gateway Timeout"]),

    # ---- Spring Data/JPA ----
    dict(category="Spring Data/JPA", severity="medium", title="DataIntegrityViolationException",
         pattern=r"org\.springframework\.dao\.DataIntegrityViolationException",
         plain_english="A database constraint was violated by the data being written - the Spring wrapper around a lower-level SQL constraint error.",
         causes=[
             "A NOT NULL, foreign-key, or CHECK constraint was violated by the actual row values (for the unique-key-specific case, see the Database/Flyway category's own entry)",
             "A column's max length was exceeded by the value being written",
         ], fix_steps=[], see_also=["Unique constraint violation"]),
    dict(category="Spring Data/JPA", severity="low", title="OptimisticLockException / ObjectOptimisticLockingFailureException",
         pattern=r"(javax|jakarta)\.persistence\.OptimisticLockException|org\.springframework\.orm\.ObjectOptimisticLockingFailureException",
         plain_english="Two concurrent requests loaded the same entity, and the @Version column changed between load and save on one of them.",
         causes=[
             "A genuine concurrent-edit race between two requests/users on the same row - often not a bug, just needs a retry or a clearer conflict message to the user",
             "A UI or batch consumer held a stale entity in memory for too long before submitting an update",
         ], fix_steps=[], see_also=[]),
    dict(category="Spring Data/JPA", severity="medium", title="EntityNotFoundException",
         pattern=r"(javax|jakarta)\.persistence\.EntityNotFoundException",
         plain_english="Code dereferenced a JPA-managed proxy whose backing row doesn't actually exist.",
         causes=[
             "A lazy relation's target row was deleted after the parent entity was loaded, and the proxy was only dereferenced later",
             "getReference()/getOne() was used (returns a lazy proxy without an immediate DB hit) against an id that doesn't exist, so the exception surfaces later, away from the actual lookup call",
         ], fix_steps=[], see_also=[]),
    dict(category="Spring Data/JPA", severity="medium", title="TransactionSystemException / UnexpectedRollbackException",
         pattern=r"org\.springframework\.transaction\.(TransactionSystemException|UnexpectedRollbackException)",
         plain_english="A transaction couldn't commit, or an outer transaction tried to commit one an inner method had already marked rollback-only.",
         causes=[
             "A bean-validation constraint failed at flush/commit time - check .getCause() for the underlying ConstraintViolationException",
             "An inner @Transactional method caught an exception without rethrowing it, which still marks the transaction rollback-only, so the outer method's later commit fails",
         ], fix_steps=[], see_also=[]),

    # ---- Outbound Clients (runtime counterpart to Outbound Integration Discovery) ----
    dict(category="Outbound Clients", severity="high", title="FeignException",
         pattern=r"feign\.FeignException",
         plain_english="A Feign-declared client call to another service failed - either a non-2xx response or a connectivity failure before any response arrived.",
         causes=[
             "The downstream service returned a non-2xx status - the status code is embedded in the exception message/type (FeignException.NotFound, .ServiceUnavailable, etc.)",
             "The downstream service is unreachable or hasn't finished starting, and Feign's own connect-timeout was hit before any response arrived at all",
         ], fix_steps=[
             "Check this jar's own Outbound Integration Discovery tab (JAR Analyser Section 38) for exactly which host/URL this client was configured to call",
         ], see_also=[]),
    dict(category="Outbound Clients", severity="high", title="Connection refused calling a downstream service",
         pattern=r"(java\.net\.ConnectException|Connection refused)",
         plain_english="A TCP connection attempt to another service was actively rejected.",
         causes=[
             "The downstream service/container isn't running yet, or hasn't finished starting - a startup-order race between two things installed in the same golden-path template",
             "Wrong host or port in this app's own config (see the Outbound Integration Discovery tab for the resolved config value actually baked into this jar)",
             "A firewall/security-group/network-pool rule is blocking the port between the two hosts",
         ], fix_steps=[], see_also=["FeignException"]),
    dict(category="Outbound Clients", severity="medium", title="Read timed out calling a downstream service",
         pattern=r"(SocketTimeoutException|Read timed out)",
         plain_english="A connection to another service was established, but no response arrived within the configured read timeout.",
         causes=[
             "The client's own read-timeout config is shorter than that downstream service's real p99 latency under load",
             "The downstream service is up but this specific request is slow (large payload, slow query, a GC pause) - check that service's own logs for the same timeframe",
         ], fix_steps=[], see_also=[]),

    # ---- PostgreSQL ----
    dict(category="PostgreSQL", severity="high", title="PostgreSQL connection refused",
         pattern=r"org\.postgresql\.util\.PSQLException.*[Cc]onnection.*refused",
         plain_english="The JDBC driver couldn't open a TCP connection to the PostgreSQL server at all.",
         causes=[
             "The postgresql service isn't started yet, or is still initialising on that host",
             "pg_hba.conf doesn't permit a connection from this client's host IP / user / database combination",
             "Wrong port in the JDBC URL (default 5432)",
         ], fix_steps=[], see_also=[]),
    dict(category="PostgreSQL", severity="high", title="FATAL: password authentication failed (postgres)",
         pattern=r"FATAL:\s*password authentication failed",
         plain_english="PostgreSQL rejected the supplied credentials.",
         causes=[
             "Wrong password in the app's config/secret",
             "pg_hba.conf's configured auth method for this host doesn't match what the client is sending (e.g. server expects scram-sha-256 but client sends md5)",
         ], fix_steps=[], see_also=[]),
    dict(category="PostgreSQL", severity="high", title="Remaining connection slots are reserved / too many connections",
         pattern=r"(remaining connection slots are reserved|too many connections)",
         plain_english="PostgreSQL's max_connections limit has been reached.",
         causes=[
             "A connection pool (HikariCP etc.) is leaking connections - opened but never closed/returned to the pool",
             "Too many separate app instances each open their own full-size pool against the same database, without a shared pooler (e.g. pgbouncer) in front",
         ], fix_steps=[], see_also=[]),
    dict(category="PostgreSQL", severity="medium", title="Relation does not exist (postgres)",
         pattern=r'relation "[^"]+" does not exist',
         plain_english="A query referenced a table/view that PostgreSQL can't find in the current search_path.",
         causes=[
             "A Flyway/Liquibase migration that creates this table hasn't run yet on this environment",
             "The app is connected to the wrong schema or database, or search_path is misconfigured",
         ], fix_steps=[], see_also=["Flyway migration failed or checksum mismatch"]),
    dict(category="PostgreSQL", severity="medium", title="Deadlock detected (postgres)",
         pattern=r"deadlock detected",
         plain_english="Two transactions were each waiting on a lock the other held, and PostgreSQL killed one to break the cycle.",
         causes=[
             "Two transactions acquire row locks in opposite orders (A-then-B in one, B-then-A in the other)",
             "A long-running transaction holds a row lock while blocked itself on a different resource that a second, shorter transaction is waiting on",
         ], fix_steps=[], see_also=["Database deadlock detected"]),

    # ---- Redis ----
    dict(category="Redis", severity="high", title="Could not connect to Redis",
         pattern=r"(io\.lettuce\.core\.RedisConnectionException|redis\.clients\.jedis\.exceptions\.JedisConnectionException)",
         plain_english="The Redis client couldn't establish or maintain a connection to the server.",
         causes=[
             "The redis service isn't running yet, or is still starting on that host",
             "Wrong host/port in the app's config",
             "A firewall between the app host and the redis host",
         ], fix_steps=[], see_also=[]),
    dict(category="Redis", severity="medium", title="Redis command timeout",
         pattern=r"RedisCommandTimeoutException",
         plain_english="A command was sent to Redis but no reply arrived within the client's configured timeout.",
         causes=[
             "Redis is under memory pressure and blocking on a slow command (e.g. KEYS against a large keyspace instead of SCAN)",
             "A network latency spike between app and redis host",
             "The redis instance's CPU is saturated by another client's workload sharing the same instance",
         ], fix_steps=[], see_also=[]),
    dict(category="Redis", severity="critical", title="OOM command not allowed",
         pattern=r"OOM command not allowed when used memory",
         plain_english="Redis has hit its maxmemory limit and its eviction policy won't free space for a write command.",
         causes=[
             "maxmemory-policy is set to noeviction and the keyspace has genuinely outgrown maxmemory",
             "Redis is being used as a primary datastore rather than a cache and has grown unbounded",
             "maxmemory itself is configured too low for the real working set",
         ], fix_steps=[], see_also=[]),
    dict(category="Redis", severity="low", title="WRONGTYPE Operation against a key",
         pattern=r"WRONGTYPE Operation against a key",
         plain_english="A command was issued for a different Redis data type than the one the key was actually created as.",
         causes=[
             "A key-naming collision between two features sharing the same Redis instance/keyspace (e.g. one uses SET, another later does LPUSH on the same key)",
         ], fix_steps=[], see_also=[]),

    # ---- MongoDB ----
    dict(category="MongoDB", severity="high", title="MongoTimeoutException - no server available",
         pattern=r"com\.mongodb\.MongoTimeoutException",
         plain_english="The MongoDB driver couldn't find any server to talk to within its server-selection timeout.",
         causes=[
             "mongod isn't running yet, or a replica set is still electing a primary",
             "Wrong host/port or replica-set name in the connection string",
             "A network partition between the app and the mongo host",
         ], fix_steps=[], see_also=[]),
    dict(category="MongoDB", severity="high", title="MongoDB authentication failed",
         pattern=r"MongoSecurityException",
         plain_english="MongoDB rejected the supplied credentials.",
         causes=[
             "Wrong username/password in the connection string",
             "The user wasn't created against the authSource database the connection string points at",
             "authMechanism mismatch (e.g. SCRAM-SHA-1 vs SCRAM-SHA-256)",
         ], fix_steps=[], see_also=[]),
    dict(category="MongoDB", severity="medium", title="E11000 duplicate key error",
         pattern=r"E11000 duplicate key error",
         plain_english="An insert/upsert violated a unique index.",
         causes=[
             "A genuine duplicate business-key submission, often a retried request without idempotency handling",
             "A race between two concurrent inserts of what's logically \"the same\" record",
         ], fix_steps=[], see_also=[]),
    dict(category="MongoDB", severity="medium", title="Not primary / NotWritablePrimary",
         pattern=r"(not master|NotWritablePrimary|NotPrimary)",
         plain_english="A write was attempted against a node that isn't the replica set's current primary.",
         causes=[
             "The client's read/write preference is misconfigured to allow routing writes to a secondary",
             "The replica set was mid-election (e.g. after a primary failover) when the write was attempted",
         ], fix_steps=[], see_also=[]),

    # ---- nginx ----
    dict(category="nginx", severity="high", title="502 Bad Gateway",
         pattern=r"502 Bad Gateway",
         plain_english="nginx received an invalid or no response from the upstream it proxied the request to.",
         causes=[
             "The upstream app process crashed, or hasn't started listening yet",
             "The upstream returned a malformed or oversized response header that nginx rejected",
             "The upstream refused the connection outright - wrong proxy_pass host/port",
         ], fix_steps=[], see_also=[]),
    dict(category="nginx", severity="high", title="504 Gateway Timeout",
         pattern=r"504 Gateway Time-?out",
         plain_english="nginx's upstream took longer than its configured timeout to respond.",
         causes=[
             "The upstream is genuinely slow for this request (DB query, GC pause) beyond proxy_read_timeout/proxy_connect_timeout",
             "A long-lived streaming/websocket connection hit a read-timeout tuned for ordinary short request/response traffic",
         ], fix_steps=[], see_also=[]),
    dict(category="nginx", severity="medium", title="Upstream sent too big header",
         pattern=r"upstream sent too big header",
         plain_english="The upstream's response headers exceeded nginx's proxy buffer size for header data.",
         causes=[
             "proxy_buffer_size/proxy_buffers is too small for the upstream's actual response headers - common with large auth cookies/JWTs or many Set-Cookie headers",
         ], fix_steps=[], see_also=[]),
    dict(category="nginx", severity="medium", title="Worker connections exceeded / too many open files",
         pattern=r"(worker_connections.*exceeded|Too many open files)",
         plain_english="nginx couldn't accept or open more connections than its own or the OS's configured limit.",
         causes=[
             "nginx's worker_connections directive, or the OS open-file-descriptor ulimit, is lower than actual concurrent connection load",
             "A slow or hung upstream is causing connections to pile up rather than complete quickly, exhausting the limit under otherwise-normal traffic",
         ], fix_steps=[], see_also=[]),
    dict(category="nginx", severity="high", title="SSL_do_handshake() failed (nginx)",
         pattern=r"SSL_do_handshake\(\) failed",
         plain_english="A TLS handshake with a client failed at the nginx frontend.",
         causes=[
             "The client offered a TLS version/cipher not permitted by ssl_protocols/ssl_ciphers",
             "A corrupted certificate/key pair, or a key that doesn't match the certificate, in the nginx config",
             "An SNI hostname with no matching server block's ssl_certificate",
         ], fix_steps=[], see_also=[]),

    # ---- Node.js ----
    dict(category="Node.js", severity="medium", title="EADDRINUSE - address already in use",
         pattern=r"EADDRINUSE",
         plain_english="The process tried to bind a port that's already bound by another process.",
         causes=[
             "A previous instance of the same app is still running and hasn't fully stopped",
             "Two services in the same deployment are configured with the same port",
         ], fix_steps=[], see_also=[]),
    dict(category="Node.js", severity="high", title="Cannot find module (MODULE_NOT_FOUND)",
         pattern=r"(MODULE_NOT_FOUND|Cannot find module)",
         plain_english="Node couldn't resolve a require()/import path to an actual file or installed package.",
         causes=[
             "node_modules wasn't installed or wasn't copied into the deployed image (a Docker layer-caching or .dockerignore mistake)",
             "package.json lists the dependency but `npm ci`/`npm install` was skipped in the build step",
             "A relative import path is wrong, or case-mismatched on a case-sensitive filesystem",
         ], fix_steps=[], see_also=[]),
    dict(category="Node.js", severity="medium", title="UnhandledPromiseRejection",
         pattern=r"UnhandledPromiseRejection",
         plain_english="A rejected Promise had no .catch() handler and no surrounding try/await caught it.",
         causes=[
             "An async function's rejected Promise was never awaited or .catch()'d",
             "A callback-style API was wrapped in a Promise, and an error path forgot to call reject()",
         ], fix_steps=[], see_also=[]),
    dict(category="Node.js", severity="high", title="ECONNREFUSED (Node.js)",
         pattern=r"ECONNREFUSED",
         plain_english="A TCP connection attempt from Node was actively rejected by the target host/port.",
         causes=[
             "The target service isn't listening yet - a startup-order race",
             "Wrong host/port in this app's own config",
         ], fix_steps=[], see_also=[]),
    dict(category="Node.js", severity="critical", title="JavaScript heap out of memory",
         pattern=r"JavaScript heap out of memory",
         plain_english="V8's heap is exhausted and can't satisfy an allocation.",
         causes=[
             "--max-old-space-size is too low for the actual working set (especially inside a memory-limited container)",
             "A genuine leak: event listeners never removed, or an ever-growing array/cache",
             "A single request processing an unexpectedly large payload entirely in memory instead of streaming it",
         ], fix_steps=[], see_also=[]),

    # ---- HAProxy ----
    dict(category="HAProxy", severity="high", title="Backend has no server available",
         pattern=r"(Server .* is DOWN|backend .* has no server available)",
         plain_english="Every server in a backend failed its health check, so HAProxy has nowhere to route the request.",
         causes=[
             "The app behind it isn't started, or the configured health-check path is wrong",
             "The health-check interval/timeout is too aggressive for a slow-starting app, flapping it in and out of rotation",
         ], fix_steps=[], see_also=[]),
    dict(category="HAProxy", severity="high", title="SSL handshake failure at HAProxy",
         pattern=r"SSL handshake failure",
         plain_english="A TLS handshake with a client failed at the HAProxy frontend.",
         causes=[
             "The client's TLS version/cipher isn't in ssl-default-bind-ciphers/ssl-min-ver",
             "The certificate chain in the haproxy .pem bundle is incomplete",
             "SNI routing sent the client to a frontend with no matching certificate",
         ], fix_steps=[], see_also=[]),
    dict(category="HAProxy", severity="medium", title="Timeout server exceeded",
         pattern=r"timeout server.*exceeded",
         plain_english="A backend server took longer than the `timeout server` directive to respond.",
         causes=[
             "The backend is genuinely slow for this request beyond the configured timeout",
             "A long-lived connection (websocket/SSE) hit a timeout tuned for short request/response traffic",
         ], fix_steps=[], see_also=[]),

    # ---- Apache/PHP ----
    dict(category="Apache/PHP", severity="high", title="PHP Fatal error: Allowed memory size exhausted",
         pattern=r"Allowed memory size of \d+ bytes exhausted",
         plain_english="A PHP script exceeded its configured memory_limit.",
         causes=[
             "memory_limit in php.ini is too low for the actual workload",
             "A script loads an entire large file/result set into memory instead of streaming it",
             "Runaway recursion or a loop building an ever-growing array",
         ], fix_steps=[], see_also=[]),
    dict(category="Apache/PHP", severity="high", title="PDOException - could not find driver / connection refused",
         pattern=r"PDOException.*(could not find driver|Connection refused)",
         plain_english="PHP's PDO layer couldn't load the DB driver, or couldn't reach the database server.",
         causes=[
             "The required PDO extension (pdo_mysql/pdo_pgsql) isn't enabled in php.ini",
             "The DB service isn't reachable yet at the configured host/port",
         ], fix_steps=[], see_also=[]),
    dict(category="Apache/PHP", severity="medium", title="Apache: (13)Permission denied / could not bind to address",
         pattern=r"\(13\)Permission denied|AH00072",
         plain_english="Apache couldn't bind its listening socket.",
         causes=[
             "Apache is trying to bind a privileged port (<1024) without root or the CAP_NET_BIND_SERVICE capability",
             "Another process already has that port bound",
             "SELinux is blocking the listen in its current context",
         ], fix_steps=[], see_also=[]),
    dict(category="Apache/PHP", severity="high", title="mod_ssl: error creating SSL context / no shared cipher",
         pattern=r"SSL_CTX_use_(certificate|PrivateKey)_file|no shared cipher",
         plain_english="Apache's mod_ssl couldn't load its certificate/key, or couldn't negotiate a cipher with a client.",
         causes=[
             "SSLCertificateFile/SSLCertificateKeyFile path is wrong, or the key doesn't match the certificate",
             "Client and server share no common cipher suite under the configured SSLCipherSuite/SSLProtocol",
         ], fix_steps=[], see_also=[]),

    # ---- OpenLDAP ----
    dict(category="OpenLDAP", severity="high", title="Invalid credentials (LDAP bind)",
         pattern=r"ldap_bind:\s*Invalid credentials",
         plain_english="An LDAP bind (login) attempt was rejected.",
         causes=[
             "Wrong bind DN or password in the app's config",
             "The bind account's password expired or was rotated without updating the app's stored secret",
         ], fix_steps=[], see_also=[]),
    dict(category="OpenLDAP", severity="high", title="Can't contact LDAP server",
         pattern=r"Can't contact LDAP server",
         plain_english="The LDAP client couldn't reach slapd at all.",
         causes=[
             "slapd isn't running, or is still starting on that host",
             "Wrong host/port in the client config (389 plain, 636 ldaps)",
             "A firewall blocking the LDAP port between hosts",
         ], fix_steps=[], see_also=[]),
    dict(category="OpenLDAP", severity="medium", title="No such object (LDAP)",
         pattern=r"ldap_.*:\s*No such object",
         plain_english="A search or bind referenced a DN that doesn't exist in this directory.",
         causes=[
             "The base DN, or a specific entry's DN, doesn't exist in this environment's directory",
             "A typo in the DN string - commonly a wrong dc= component copied between environments",
         ], fix_steps=[], see_also=[]),

    # ---- Docker/Containers ----
    dict(category="Docker/Containers", severity="critical", title="OOMKilled",
         pattern=r"OOMKilled",
         plain_english="The container's cgroup memory limit was exceeded and the kernel killed the process.",
         causes=[
             "The container's memory limit is lower than the process's real peak usage - check any in-process heap limit (e.g. JVM -Xmx) is sized relative to the container's own memory limit, not the host's",
             "A genuine leak inside the process eventually exceeds any limit given enough uptime",
         ], fix_steps=[], see_also=["OutOfMemoryError - Java heap space"]),
    dict(category="Docker/Containers", severity="high", title="exec format error",
         pattern=r"exec format error",
         plain_english="The container runtime tried to execute a binary built for a different CPU architecture.",
         causes=[
             "The image was built for a different architecture than the host it's being run on (e.g. arm64 image on an amd64 host, or vice versa)",
             "The entrypoint script is missing its shebang line, or isn't marked executable",
         ], fix_steps=[], see_also=[]),
    dict(category="Docker/Containers", severity="high", title="No space left on device",
         pattern=r"no space left on device",
         plain_english="The host or a mounted volume has run out of disk space.",
         causes=[
             "Docker's own storage driver has accumulated unpruned images/layers/volumes over time",
             "A container's writable layer or a bind-mounted volume filled up - often unbounded log file growth",
         ], fix_steps=[], see_also=[]),
    dict(category="Docker/Containers", severity="medium", title="Port is already allocated",
         pattern=r"port is already allocated",
         plain_english="Docker couldn't publish a container port because something already has it bound on the host.",
         causes=[
             "A stale container from a previous failed `up`/deploy still has that host port bound",
             "Two compose services are configured to publish the same host port",
         ], fix_steps=[], see_also=[]),
]


def get_or_create_library(name: str, existing: list[dict]) -> str:
    for lib in existing:
        if lib["name"] == name:
            return lib["id"]
    status, body = call("POST", "/docs/libraries", {"name": name})
    if status != 201:
        raise RuntimeError(f"Failed to create library {name!r}: {status} {body}")
    print(f"  + library {name!r}")
    return body["id"]


def get_or_create_shelf(library_id: str, name: str) -> str:
    status, shelves = call("GET", f"/docs/libraries/{library_id}/shelves")
    if status != 200:
        raise RuntimeError(f"Failed to list shelves for {library_id}: {status} {shelves}")
    for shelf in shelves:
        if shelf["name"] == name:
            return shelf["id"]
    status, body = call("POST", "/docs/shelves", {"library_id": library_id, "name": name})
    if status != 201:
        raise RuntimeError(f"Failed to create shelf {name!r}: {status} {body}")
    print(f"    + shelf {name!r}")
    return body["id"]


def main() -> None:
    status, existing_libraries = call("GET", "/docs/libraries")
    if status != 200:
        print(f"Failed to list existing libraries: {status} {existing_libraries}", file=sys.stderr)
        sys.exit(1)

    library_ids: dict[str, str] = {}
    shelf_ids: dict[str, str] = {}
    created, skipped, failed = 0, 0, 0

    for entry in ENTRIES:
        category = entry["category"]
        if category not in library_ids:
            library_ids[category] = get_or_create_library(category, existing_libraries)
            existing_libraries.append({"id": library_ids[category], "name": category})
        if category not in shelf_ids:
            shelf_ids[category] = get_or_create_shelf(library_ids[category], "Errors")

        content = render_kb_doc_content(
            entry["severity"], entry["pattern"], entry["plain_english"],
            entry.get("causes", []), entry.get("fix_steps", []), entry.get("see_also", []),
        )

        status, body = call("POST", "/docs", {
            "shelf_id": shelf_ids[category], "name": entry["title"], "content": content,
        })
        if status == 201:
            created += 1
            print(f"  [{category}] created: {entry['title']}")
        elif status == 409:
            skipped += 1
            print(f"  [{category}] already exists, skipped: {entry['title']}")
        else:
            failed += 1
            print(f"  [{category}] FAILED ({status}): {entry['title']} -> {body}", file=sys.stderr)

    print(f"\nDone: {created} created, {skipped} skipped (already existed), {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
