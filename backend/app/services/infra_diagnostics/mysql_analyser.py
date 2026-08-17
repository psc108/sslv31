"""MySQL infrastructure diagnostic analyser."""
from __future__ import annotations

import re
from typing import Any

from app.services.infra_diagnostics.infra_analyser_base import (
    _finding, _missing_required, build_summary, dedupe_sort, run_shared_passes,
)
from app.services.infra_diagnostics.mysql_questionnaire import get_questionnaire


def analyse(
    responses: dict[str, str],
    report_context: dict | None = None,
) -> dict[str, Any]:
    sections = get_questionnaire()
    findings, cert_results, port_results, log_findings = run_shared_passes(responses, sections)

    findings += _check_ssl_variables(responses)
    findings += _check_user_exists(responses)
    findings += _check_user_grants(responses)
    findings += _check_capacity(responses)
    findings += _check_replication(responses)

    if report_context:
        findings += _cross_reference(responses, report_context)

    findings = dedupe_sort(findings)
    missing = _missing_required(responses, sections)

    return {
        "service":          "mysql",
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

def _check_ssl_variables(responses: dict[str, str]) -> list[dict]:
    text = responses.get("mysql.ssl_variables", "")
    if not text.strip():
        return []
    findings = []
    if re.search(r"have_ssl\s+DISABLED", text, re.IGNORECASE):
        findings.append(_finding(
            category="SSL/TLS", severity="critical", source="service_check", service="mysql",
            message="MySQL SSL is disabled (have_ssl = DISABLED). Services configured for SSL connections will fail.",
            item_id="mysql.ssl_variables",
            causes=["MySQL was not started with SSL configuration.", "ssl_cert, ssl_key, ssl_ca are not set in my.cnf."],
            fix_steps=["Generate or obtain a server certificate and key.",
                       "Set ssl_cert, ssl_key, ssl_ca in /etc/mysql/my.cnf under [mysqld].",
                       "Restart MySQL: systemctl restart mysql",
                       "Verify: SHOW VARIABLES LIKE '%ssl%' — have_ssl should be YES."],
        ))
    elif re.search(r"have_ssl\s+YES", text, re.IGNORECASE):
        # SSL enabled but check cert paths are set
        if re.search(r"ssl_cert\s+\n|ssl_cert\s+$", text, re.MULTILINE):
            findings.append(_finding(
                category="SSL/TLS", severity="high", source="service_check", service="mysql",
                message="MySQL SSL is enabled but ssl_cert path is empty.",
                item_id="mysql.ssl_variables",
                fix_steps=["Set ssl_cert, ssl_key, ssl_ca in /etc/mysql/my.cnf and restart MySQL."],
            ))
    return findings


def _check_user_exists(responses: dict[str, str]) -> list[dict]:
    text = responses.get("mysql.user_exists", "")
    if not text.strip():
        return []
    findings = []
    # Empty result set — no rows returned
    if re.search(r"Empty set|0 rows", text, re.IGNORECASE):
        user = responses.get("mysql.param.service_user", "<service_user>")
        findings.append(_finding(
            category="Auth", severity="critical", source="service_check", service="mysql",
            message=f"Service account '{user}' does not exist in MySQL.",
            item_id="mysql.user_exists",
            causes=["Account was never created.", "Account was dropped.", "Wrong username in application config."],
            fix_steps=[f"Create the account: CREATE USER '{user}'@'%' IDENTIFIED BY '<password>';",
                       f"Then grant access: GRANT SELECT, INSERT, UPDATE, DELETE ON <db>.* TO '{user}'@'%';"],
        ))
        return findings
    if re.search(r"account_locked\s+Y\b", text, re.IGNORECASE):
        findings.append(_finding(
            category="Auth", severity="critical", source="service_check", service="mysql",
            message="Service account is locked (account_locked = Y).",
            item_id="mysql.user_exists",
            fix_steps=["Unlock: ALTER USER '<user>'@'<host>' ACCOUNT UNLOCK;"],
        ))
    if re.search(r"caching_sha2_password", text, re.IGNORECASE):
        findings.append(_finding(
            category="Auth", severity="high", source="service_check", service="mysql",
            message="Service account uses caching_sha2_password plugin which may be incompatible with older JDBC connectors.",
            item_id="mysql.user_exists",
            causes=["MySQL 8.x default auth plugin; older mysql-connector-java requires mysql_native_password."],
            fix_steps=["Option 1: ALTER USER '<user>'@'<host>' IDENTIFIED WITH mysql_native_password BY '<password>';",
                       "Option 2: Add allowPublicKeyRetrieval=true&useSSL=true to the JDBC URL.",
                       "Option 3: Upgrade mysql-connector-java to 8.x."],
        ))
    return findings


def _check_user_grants(responses: dict[str, str]) -> list[dict]:
    text = responses.get("mysql.user_grants", "")
    if not text.strip():
        return []
    findings = []
    if re.search(r"ERROR|No such grant|no grants", text, re.IGNORECASE):
        findings.append(_finding(
            category="Auth", severity="critical", source="service_check", service="mysql",
            message="No grants found for the service account.",
            item_id="mysql.user_grants",
            fix_steps=["GRANT SELECT, INSERT, UPDATE, DELETE ON <db>.* TO '<user>'@'<host>';"],
        ))
        return findings
    if re.search(r"GRANT USAGE ON \*\.\*", text, re.IGNORECASE) and not re.search(r"GRANT .+ ON \w+\.", text):
        findings.append(_finding(
            category="Auth", severity="critical", source="service_check", service="mysql",
            message="Service account has USAGE only — no database-level grants.",
            item_id="mysql.user_grants",
            fix_steps=["GRANT SELECT, INSERT, UPDATE, DELETE ON <db>.* TO '<user>'@'<host>';"],
        ))
        return findings
    for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        if not re.search(priv, text, re.IGNORECASE):
            sev = "high" if priv == "SELECT" else "medium"
            findings.append(_finding(
                category="Auth", severity=sev, source="service_check", service="mysql",
                message=f"Service account is missing {priv} privilege on the service database.",
                item_id="mysql.user_grants",
                fix_steps=[f"GRANT {priv} ON <db>.* TO '<user>'@'<host>';"],
            ))
    return findings


def _check_capacity(responses: dict[str, str]) -> list[dict]:
    max_text = responses.get("mysql.max_connections", "")
    cur_text = responses.get("mysql.threads_connected", "")
    if not max_text.strip() or not cur_text.strip():
        return []
    findings = []
    max_m = re.search(r"max_connections\s+(\d+)", max_text, re.IGNORECASE)
    cur_m = re.search(r"Threads_connected\s+(\d+)", cur_text, re.IGNORECASE)
    if max_m and cur_m:
        max_c, cur_c = int(max_m.group(1)), int(cur_m.group(1))
        if cur_c >= max_c:
            findings.append(_finding(
                category="Capacity", severity="critical", source="service_check", service="mysql",
                message=f"Connection pool exhausted: {cur_c}/{max_c} connections in use. New connections will be refused.",
                item_id="mysql.threads_connected",
                fix_steps=["SET GLOBAL max_connections = <higher_value>;",
                           "Also set max_connections in /etc/mysql/my.cnf for persistence.",
                           "Check for connection leaks: spring.datasource.hikari.leak-detection-threshold=30000"],
            ))
        elif cur_c >= max_c * 0.9:
            findings.append(_finding(
                category="Capacity", severity="high", source="service_check", service="mysql",
                message=f"Connection pool near exhaustion: {cur_c}/{max_c} connections in use (≥90%).",
                item_id="mysql.threads_connected",
                fix_steps=["Consider increasing max_connections.", "Review connection pool sizing."],
            ))
    return findings


def _check_replication(responses: dict[str, str]) -> list[dict]:
    text = responses.get("mysql.replication_status", "")
    if not text.strip() or re.search(r"Empty set|not a replica|no replication", text, re.IGNORECASE):
        return []
    findings = []
    lag_m = re.search(r"Seconds_Behind_(?:Source|Master)\s*:\s*(\d+)", text, re.IGNORECASE)
    if lag_m and int(lag_m.group(1)) > 60:
        findings.append(_finding(
            category="Replication", severity="medium", source="service_check", service="mysql",
            message=f"Replica is lagging {lag_m.group(1)} seconds behind source. Reads from replica may return stale data.",
            item_id="mysql.replication_status",
        ))
    if re.search(r"Replica_SQL_Running\s*:\s*No|Slave_SQL_Running\s*:\s*No", text, re.IGNORECASE):
        findings.append(_finding(
            category="Replication", severity="high", source="service_check", service="mysql",
            message="Replication SQL thread is stopped.",
            item_id="mysql.replication_status",
            fix_steps=["START REPLICA; (or START SLAVE; on older MySQL)", "Check Last_SQL_Error for the cause."],
        ))
    sql_err = re.search(r"Last_SQL_Error\s*:\s*(.+)", text)
    if sql_err and sql_err.group(1).strip():
        findings.append(_finding(
            category="Replication", severity="high", source="service_check", service="mysql",
            message=f"Replication SQL error: {sql_err.group(1).strip()[:200]}",
            item_id="mysql.replication_status",
        ))
    return findings


def _cross_reference(responses: dict[str, str], ctx: dict) -> list[dict]:
    findings = []
    ds_url = ctx.get("datasource_url", "")
    param_host = responses.get("mysql.param.host", "")

    if ds_url and param_host and param_host not in ("%", ""):
        url_host_m = re.search(r"mysql://([^:/]+)", ds_url)
        if url_host_m and url_host_m.group(1) not in (param_host, "localhost", "127.0.0.1"):
            findings.append(_finding(
                category="Configuration", severity="medium", source="cross_reference", service="mysql",
                message=f"Application datasource URL host ({url_host_m.group(1)}) differs from the host being diagnosed ({param_host}).",
                item_id="mysql.param.host",
            ))

    pool_size = ctx.get("hikari_max_pool_size")
    cur_text = responses.get("mysql.threads_connected", "")
    if pool_size and cur_text:
        cur_m = re.search(r"Threads_connected\s+(\d+)", cur_text, re.IGNORECASE)
        if cur_m and int(cur_m.group(1)) >= int(pool_size) * 0.9:
            findings.append(_finding(
                category="Capacity", severity="high", source="cross_reference", service="mysql",
                message=f"Current connections ({cur_m.group(1)}) are near the application's HikariCP pool size ({pool_size}).",
                item_id="mysql.threads_connected",
            ))
    return findings
