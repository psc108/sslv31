"""Extract infrastructure parameter pre-fill values and cross-reference config from a JAR report.

Receives the list of sub-report dicts (same shape as _config_dict output in jar_analyser.py)
and returns two dicts:
  - prefill:  {parameter_item_id: value}  — pre-populate questionnaire parameter prompts
  - context:  flat dict of extracted config values for cross-reference checks

Key-pattern recognition is delegated to connection_facts.py, shared with the
"Infrastructure Requirements" report section, so the two systems never drift
apart on what a given config key means. Note: connection_facts.py recognises
a couple of real-world key patterns this function did not previously
recognise (e.g. this product's `event.rabbitmq.*` convention alongside the
generic Spring Boot `spring.rabbitmq.*` one) — an intentional, additive
improvement to prefill coverage, not a behaviour change to any key this
function already recognised.
"""
from __future__ import annotations

from typing import Any

from app.services.jar_analyser.connection_facts import extract_connection_facts


def extract(sub_dicts: list[dict]) -> tuple[dict[str, str], dict[str, Any]]:
    """Return (prefill, context) extracted from JAR report sub-report config data."""
    prefill: dict[str, str] = {}
    context: dict[str, Any] = {}

    for sub in sub_dicts:
        keys = [k for cfg in sub.get("config_files", []) for k in cfg.get("keys", [])]
        facts = extract_connection_facts(keys)

        # ── MySQL ────────────────────────────────────────────────────────────
        db = facts.database
        if db.url:
            context["datasource_url"] = db.url
        if db.host and "mysql.param.host" not in prefill:
            prefill["mysql.param.host"] = db.host
        if db.port is not None:
            context["datasource_port"] = db.port
        if db.username and "mysql.param.service_user" not in prefill:
            prefill["mysql.param.service_user"] = db.username
        if db.max_pool_size is not None:
            context["hikari_max_pool_size"] = db.max_pool_size

        # ── RabbitMQ ─────────────────────────────────────────────────────────
        mq = facts.messaging
        if mq.virtual_host:
            context["rabbitmq_vhost"] = mq.virtual_host
            if "rabbitmq.param.vhost" not in prefill:
                prefill["rabbitmq.param.vhost"] = mq.virtual_host
        if mq.ssl_enabled is not None:
            context["rabbitmq_ssl_enabled"] = mq.ssl_enabled
        if mq.port is not None:
            context["rabbitmq_port"] = mq.port

        # ── Keystone ─────────────────────────────────────────────────────────
        iam = facts.iam
        if iam.auth_url:
            context["keystone_auth_url"] = iam.auth_url
        if iam.auth_host and "keystone.param.keystone_host" not in prefill:
            prefill["keystone.param.keystone_host"] = iam.auth_host
            context["keystone_auth_host"] = iam.auth_host
        if iam.username and "keystone.param.service_user" not in prefill:
            prefill["keystone.param.service_user"] = iam.username
        if iam.project_name and "keystone.param.project" not in prefill:
            prefill["keystone.param.project"] = iam.project_name
            context["keystone_project"] = iam.project_name

    return prefill, context
