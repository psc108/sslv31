"""RabbitMQ infrastructure diagnostic analyser."""
from __future__ import annotations

import re
from typing import Any

from app.services.infra_diagnostics.infra_analyser_base import (
    _finding, _missing_required, build_summary, dedupe_sort, run_shared_passes,
)
from app.services.infra_diagnostics.rabbitmq_questionnaire import get_questionnaire


def analyse(
    responses: dict[str, str],
    report_context: dict | None = None,
) -> dict[str, Any]:
    sections = get_questionnaire()
    findings, cert_results, port_results, log_findings = run_shared_passes(responses, sections)

    findings += _check_broker_status(responses)
    findings += _check_ssl_config(responses)
    findings += _check_vhost(responses)
    findings += _check_permissions(responses)
    findings += _check_queues(responses)

    if report_context:
        findings += _cross_reference(responses, report_context)

    findings = dedupe_sort(findings)
    missing = _missing_required(responses, sections)

    return {
        "service":          "rabbitmq",
        "cert_results":     cert_results,
        "port_results":     port_results,
        "log_findings":     log_findings,
        "config_issues":    [],
        "findings":         findings,
        "missing_required": missing,
        "summary":          build_summary(findings, cert_results, port_results, log_findings, responses, sections),
        "ai_summary":       None,
    }


# ---------------------------------------------------------------------------

def _check_broker_status(responses: dict[str, str]) -> list[dict]:
    text = responses.get("rabbitmq.broker_status", "")
    if not text.strip():
        return []
    findings = []
    if re.search(r"memory_alarm", text, re.IGNORECASE):
        findings.append(_finding(
            category="Capacity", severity="critical", source="service_check", service="rabbitmq",
            message="RabbitMQ memory alarm is active. The broker is blocking publishers.",
            item_id="rabbitmq.broker_status",
            causes=["Broker memory usage has exceeded the vm_memory_high_watermark threshold."],
            fix_steps=["Increase vm_memory_high_watermark in rabbitmq.conf.",
                       "Reduce memory usage by consuming queued messages.",
                       "Add more RAM to the broker node."],
        ))
    if re.search(r"disk_free_alarm", text, re.IGNORECASE):
        findings.append(_finding(
            category="Capacity", severity="critical", source="service_check", service="rabbitmq",
            message="RabbitMQ disk free alarm is active. The broker is blocking publishers.",
            item_id="rabbitmq.broker_status",
            fix_steps=["Free disk space on the broker node.",
                       "Increase disk_free_limit in rabbitmq.conf."],
        ))
    # Check RabbitMQ application is actually running
    if text.strip() and not re.search(r"\{rabbit,", text):
        findings.append(_finding(
            category="Service", severity="critical", source="service_check", service="rabbitmq",
            message="RabbitMQ application does not appear to be running on this node.",
            item_id="rabbitmq.broker_status",
            fix_steps=["rabbitmqctl start_app", "systemctl restart rabbitmq-server"],
        ))
    return findings


def _check_ssl_config(responses: dict[str, str]) -> list[dict]:
    text = responses.get("rabbitmq.ssl_config", "")
    if not text.strip():
        return []
    findings = []
    if not re.search(r"ssl|tls", text, re.IGNORECASE):
        findings.append(_finding(
            category="SSL/TLS", severity="high", source="service_check", service="rabbitmq",
            message="No SSL/TLS listener found in RabbitMQ environment. AMQPS connections will fail.",
            item_id="rabbitmq.ssl_config",
            fix_steps=["Configure SSL in rabbitmq.conf: listeners.ssl.default = 5671",
                       "Set ssl_options.cacertfile, ssl_options.certfile, ssl_options.keyfile."],
        ))
    else:
        if not re.search(r"verify_peer|verify,\s*verify_peer", text, re.IGNORECASE):
            findings.append(_finding(
                category="SSL/TLS", severity="medium", source="service_check", service="rabbitmq",
                message="RabbitMQ SSL verify mode is not set to verify_peer. Client certificate verification is disabled.",
                item_id="rabbitmq.ssl_config",
                fix_steps=["Set ssl_options.verify = verify_peer in rabbitmq.conf."],
            ))
        if re.search(r"fail_if_no_peer_cert.*false", text, re.IGNORECASE):
            findings.append(_finding(
                category="SSL/TLS", severity="low", source="service_check", service="rabbitmq",
                message="fail_if_no_peer_cert is false — mTLS is not enforced.",
                item_id="rabbitmq.ssl_config",
                fix_steps=["Set ssl_options.fail_if_no_peer_cert = true to enforce mTLS."],
            ))
    return findings


def _check_vhost(responses: dict[str, str]) -> list[dict]:
    vhost_list = responses.get("rabbitmq.vhost_list", "")
    target_vhost = responses.get("rabbitmq.param.vhost", "").strip()
    if not vhost_list.strip() or not target_vhost:
        return []
    # Normalise: strip leading slash for comparison
    vhost_norm = target_vhost.lstrip("/")
    if target_vhost not in vhost_list and vhost_norm not in vhost_list:
        return [_finding(
            category="Configuration", severity="critical", source="service_check", service="rabbitmq",
            message=f"Vhost '{target_vhost}' does not exist on this broker. All connections to this vhost will fail.",
            item_id="rabbitmq.vhost_list",
            fix_steps=[f"rabbitmqctl add_vhost {target_vhost}",
                       f"rabbitmqctl set_permissions -p {target_vhost} <user> '.*' '.*' '.*'"],
        )]
    return []


def _check_permissions(responses: dict[str, str]) -> list[dict]:
    user_list = responses.get("rabbitmq.user_list", "")
    perms = responses.get("rabbitmq.permissions", "")
    target_vhost = responses.get("rabbitmq.param.vhost", "").strip()
    findings = []

    # We don't know the service username from the questionnaire alone —
    # check that the permissions list is non-empty as a proxy
    if perms.strip() and re.search(r"^\s*$", perms, re.MULTILINE):
        findings.append(_finding(
            category="Auth", severity="critical", source="service_check", service="rabbitmq",
            message=f"No permissions found on vhost '{target_vhost}'. Service connections will be refused.",
            item_id="rabbitmq.permissions",
            fix_steps=[f"rabbitmqctl set_permissions -p {target_vhost} <user> '.*' '.*' '.*'"],
        ))
    elif perms.strip():
        # Check for empty configure/write/read patterns (three consecutive empty strings)
        if re.search(r"\t\t\t|\s{3,}\s{3,}\s{3,}", perms):
            findings.append(_finding(
                category="Auth", severity="high", source="service_check", service="rabbitmq",
                message="A user on the target vhost has empty configure/write/read permission patterns.",
                item_id="rabbitmq.permissions",
                fix_steps=[f"rabbitmqctl set_permissions -p {target_vhost} <user> '.*' '.*' '.*'"],
            ))
    return findings


def _check_queues(responses: dict[str, str]) -> list[dict]:
    text = responses.get("rabbitmq.queue_list", "")
    if not text.strip():
        return []
    findings = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        name = parts[0]
        try:
            messages = int(parts[1])
            consumers = int(parts[2])
        except (ValueError, IndexError):
            continue
        if consumers == 0 and messages > 0:
            findings.append(_finding(
                category="Messaging", severity="high", source="service_check", service="rabbitmq",
                message=f"Queue '{name}' has {messages} messages and 0 consumers. Messages will accumulate.",
                item_id="rabbitmq.queue_list",
                fix_steps=["Check the consumer service is running and connected.",
                           "Inspect the dead-letter queue for rejected messages."],
            ))
        elif messages > 10000:
            findings.append(_finding(
                category="Messaging", severity="medium", source="service_check", service="rabbitmq",
                message=f"Queue '{name}' has high message depth ({messages}). Consumer may be slow or stopped.",
                item_id="rabbitmq.queue_list",
            ))
    return findings


def _cross_reference(responses: dict[str, str], ctx: dict) -> list[dict]:
    findings = []
    param_vhost = responses.get("rabbitmq.param.vhost", "").strip()
    config_vhost = ctx.get("rabbitmq_vhost", "")
    if param_vhost and config_vhost and param_vhost != config_vhost:
        findings.append(_finding(
            category="Configuration", severity="high", source="cross_reference", service="rabbitmq",
            message=f"Application is configured for vhost '{config_vhost}' but the vhost being diagnosed is '{param_vhost}'.",
            item_id="rabbitmq.param.vhost",
        ))

    ssl_enabled = ctx.get("rabbitmq_ssl_enabled")
    ssl_config = responses.get("rabbitmq.ssl_config", "")
    if ssl_enabled and ssl_config and not re.search(r"ssl|tls", ssl_config, re.IGNORECASE):
        findings.append(_finding(
            category="SSL/TLS", severity="critical", source="cross_reference", service="rabbitmq",
            message="Application config has spring.rabbitmq.ssl.enabled=true but broker has no SSL listener configured.",
            item_id="rabbitmq.ssl_config",
        ))

    config_port = ctx.get("rabbitmq_port")
    amqps_text = responses.get("rabbitmq.port_amqps", "")
    amqp_text = responses.get("rabbitmq.port_amqp", "")
    if config_port == 5672 and amqp_text and "5672" not in amqp_text and amqps_text and "5671" in amqps_text:
        findings.append(_finding(
            category="Configuration", severity="high", source="cross_reference", service="rabbitmq",
            message="Application is connecting on plain AMQP port 5672 but only AMQPS port 5671 is open.",
            item_id="rabbitmq.port_amqp",
            fix_steps=["Update spring.rabbitmq.port=5671 and enable spring.rabbitmq.ssl.enabled=true."],
        ))
    return findings
