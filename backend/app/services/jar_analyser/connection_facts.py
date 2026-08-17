"""Shared structured extraction of database/messaging/IAM connection facts
from config file keys.

Used by both the static "Infrastructure Requirements" report section
(infra_requirements.py) and the live "Infra Diagnostics" questionnaire
prefill (infra_diagnostics/infra_report_context.py) — keeping this in one
place means the two systems never drift apart on what
"spring.datasource.username" or "openstack.auth.url" means.

Real-data note (confirmed against actual installer bundles): a service's
"real" deployment profile almost always externalises connection details
completely — e.g. `spring.datasource.url: ${parts.blob-store.db.url}` with no
default — while a separate test-profile config for the same service often
has a literal, resolvable value for local test runs, e.g.
`${test.db.url:jdbc:mysql://localhost/blob_store_user}`. Both are Spring
placeholder syntax and neither is safe to present as a deployment
requirement: the production placeholder has no value to show, and the test
placeholder's embedded default is a local-test fixture, not deployment
guidance. So this module never resolves a literal out of a `${...}` value
(with or without a default) — it only records that the key is present and
externally parameterised, which is itself a useful fact ("this service needs
X supplied at install time").
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_PLACEHOLDER_START = re.compile(r"^\$\{")


def _is_literal(val: str) -> bool:
    """Same rule infra_report_context.py has always applied: an encrypted
    marker or an unresolved Spring placeholder carries no value safe to
    present as fact, embedded default or not (see module docstring)."""
    return bool(val) and not val.startswith("ENC(") and not _PLACEHOLDER_START.match(val)


@dataclass
class DatabaseFacts:
    db_type: str | None = None
    driver_class: str | None = None
    url: str | None = None
    host: str | None = None
    port: int | None = None
    database_name: str | None = None
    username: str | None = None
    max_pool_size: int | None = None
    externally_parameterized_keys: list[str] = field(default_factory=list)


@dataclass
class MessagingFacts:
    virtual_host: str | None = None
    address: str | None = None
    port: int | None = None
    ssl_enabled: bool | None = None
    externally_parameterized_keys: list[str] = field(default_factory=list)


@dataclass
class IamFacts:
    auth_url: str | None = None
    auth_host: str | None = None
    username: str | None = None
    project_name: str | None = None
    externally_parameterized_keys: list[str] = field(default_factory=list)


@dataclass
class ConnectionFacts:
    database: DatabaseFacts = field(default_factory=DatabaseFacts)
    messaging: MessagingFacts = field(default_factory=MessagingFacts)
    iam: IamFacts = field(default_factory=IamFacts)


# Key patterns are substring/exact-match on the dotted key name, mirroring the
# precision of the original infra_report_context.py logic — broad category
# matches (config_files.py's "database"/"messaging" categorisation) are
# deliberately not used here since they also catch unrelated keys (e.g.
# spring.jpa.properties.hibernate.jdbc.batch_size is category=database but
# carries no connection information).
_DB_URL_SUBSTR = "datasource.url"
_DB_USER_KEYS = ("spring.datasource.username", "datasource.username")
_DB_TYPE_KEYS = ("db.type",)
_DB_DRIVER_SUBSTR = "datasource.driver-class-name"
_DB_POOL_SUBSTR = "hikari.maximum-pool-size"

# spring.rabbitmq.* is the generic Spring Boot convention; event.rabbitmq.* is
# this product's own convention, confirmed present in real bundles where the
# generic keys never appear at all — recognising both is a genuine, additive
# improvement over the original (Spring-Boot-only) key list.
_MQ_VHOST_KEYS = ("spring.rabbitmq.virtual-host", "rabbitmq.virtual-host", "event.rabbitmq.virtualHost")
_MQ_ADDRESS_KEYS = ("event.rabbitmq.addresses",)
_MQ_SSL_KEYS = ("spring.rabbitmq.ssl.enabled", "rabbitmq.ssl.enabled")
_MQ_PORT_KEYS = ("spring.rabbitmq.port", "rabbitmq.port")

_IAM_AUTH_URL_KEYS = ("openstack.auth.url", "spring.security.oauth2.resourceserver.jwt.issuer-uri",
                      "openstack.credentials.auth-url", "os.auth.url")
_IAM_USER_KEYS = ("openstack.credentials.username", "openstack.username", "os.username", "openstack.auth.username")
_IAM_PROJECT_KEYS = ("openstack.credentials.project-name", "openstack.project", "os.project-name",
                     "openstack.auth.project-name")

_JDBC_HOST_RE = re.compile(r"mysql://([^:/]+)")
_JDBC_PORT_RE = re.compile(r"mysql://[^:/]+:(\d+)")
_JDBC_DB_NAME_RE = re.compile(r"mysql://[^/]+/([\w.-]+?)(?:[?;]|$)")
_ADDRESS_PORT_RE = re.compile(r":(\d+)")
_AUTH_HOST_RE = re.compile(r"https?://([^:/]+)")


def _note(bucket: list[str], key: str) -> None:
    if key not in bucket:
        bucket.append(key)


def extract_connection_facts(keys: list[dict]) -> ConnectionFacts:
    """Extract structured connection facts from one service's config keys
    (the `keys` list on a JarConfigFile / `_config_dict()` dict)."""
    facts = ConnectionFacts()
    for k in keys:
        key = k.get("key") or ""
        val = k.get("value") or ""
        if not val:
            continue
        _apply_key(key, val, facts)
    return facts


def _apply_key(key: str, val: str, facts: ConnectionFacts) -> None:
    literal = _is_literal(val)

    # ── MySQL / database ────────────────────────────────────────────────────
    if key in _DB_TYPE_KEYS and literal:
        facts.database.db_type = val
    if _DB_DRIVER_SUBSTR in key and literal:
        facts.database.driver_class = val
    if _DB_URL_SUBSTR in key:
        if literal and "mysql" in val.lower():
            facts.database.url = val
            if m := _JDBC_HOST_RE.search(val):
                facts.database.host = m.group(1)
            if m := _JDBC_PORT_RE.search(val):
                facts.database.port = int(m.group(1))
            if m := _JDBC_DB_NAME_RE.search(val):
                facts.database.database_name = m.group(1)
        elif not literal:
            _note(facts.database.externally_parameterized_keys, key)
    if key in _DB_USER_KEYS:
        if literal:
            facts.database.username = val
        else:
            _note(facts.database.externally_parameterized_keys, key)
    if _DB_POOL_SUBSTR in key and literal:
        try:
            facts.database.max_pool_size = int(val)
        except ValueError:
            pass

    # ── RabbitMQ ────────────────────────────────────────────────────────────
    if key in _MQ_VHOST_KEYS:
        if literal:
            facts.messaging.virtual_host = val
        else:
            _note(facts.messaging.externally_parameterized_keys, key)
    if key in _MQ_ADDRESS_KEYS:
        if literal:
            facts.messaging.address = val
            if m := _ADDRESS_PORT_RE.search(val):
                facts.messaging.port = int(m.group(1))
        else:
            _note(facts.messaging.externally_parameterized_keys, key)
    if key in _MQ_SSL_KEYS and literal:
        facts.messaging.ssl_enabled = val.lower() in ("true", "1", "yes")
    if key in _MQ_PORT_KEYS and literal:
        try:
            facts.messaging.port = int(val)
        except ValueError:
            pass

    # ── IAM / Keystone ──────────────────────────────────────────────────────
    if key in _IAM_AUTH_URL_KEYS:
        if literal:
            facts.iam.auth_url = val
            if m := _AUTH_HOST_RE.search(val):
                facts.iam.auth_host = m.group(1)
        else:
            _note(facts.iam.externally_parameterized_keys, key)
    if key in _IAM_USER_KEYS:
        if literal:
            facts.iam.username = val
        else:
            _note(facts.iam.externally_parameterized_keys, key)
    if key in _IAM_PROJECT_KEYS:
        if literal:
            facts.iam.project_name = val
        else:
            _note(facts.iam.externally_parameterized_keys, key)
