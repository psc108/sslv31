"""Infra-requirements plan — Stages 1-3 synthesis modules + Stage 5 aggregator."""
from app.services.jar_analyser.iam_requirements import compute_iam_requirements
from app.services.jar_analyser.database_requirements import compute_database_requirements
from app.services.jar_analyser.messaging_requirements import compute_messaging_requirements
from app.services.jar_analyser.infra_requirements import compute_infra_requirements


def _cfg(*keys):
    return [{"keys": [{"key": k, "value": v, "is_encrypted": False, "is_placeholder": v.startswith("${")} for k, v in keys]}]


# ---------------------------------------------------------------------------
# IAM
# ---------------------------------------------------------------------------

def test_iam_aggregates_roles_and_authorities_across_services():
    sub_reports = [
        {"service_name": "catalog", "endpoints": [
            {"http_method": "GET", "full_path": "/x", "security": {"parsed_auth": {"roles": ["ADMIN"], "authorities": []}}},
        ], "config_files": []},
        {"service_name": "customers", "endpoints": [
            {"http_method": "GET", "full_path": "/y", "security": {"parsed_auth": {"roles": ["ADMIN"], "authorities": []}}},
        ], "config_files": []},
    ]
    result = compute_iam_requirements(sub_reports)
    role = next(r for r in result["requirements"] if r["name"] == "ADMIN")
    assert role["kind"] == "role"
    assert role["reference_count"] == 2
    assert role["services"] == ["catalog", "customers"]


def test_iam_no_connection_config_produces_explicit_gap():
    sub_reports = [{"service_name": "catalog", "endpoints": [], "config_files": []}]
    result = compute_iam_requirements(sub_reports)
    assert result["connection"]["auth_url"] is None
    assert any("external IAM service" in g for g in result["known_gaps"])


def test_iam_connection_facts_extracted_when_literal():
    sub_reports = [{
        "service_name": "keystone-client", "endpoints": [],
        "config_files": _cfg(("openstack.auth.url", "https://keystone.example.com:5000/v3"),
                              ("openstack.credentials.project-name", "cps")),
    }]
    result = compute_iam_requirements(sub_reports)
    assert result["connection"]["auth_host"] == "keystone.example.com"
    assert result["connection"]["project_name"] == "cps"


def test_iam_public_and_unsecured_counts():
    sub_reports = [{"service_name": "x", "config_files": [], "endpoints": [
        {"http_method": "GET", "full_path": "/a", "security": {"parsed_auth": {"public": True}}},
        {"http_method": "GET", "full_path": "/b", "security": None},
    ]}]
    result = compute_iam_requirements(sub_reports)
    assert result["summary"]["public_endpoint_count"] == 1
    assert result["summary"]["unsecured_endpoint_count"] == 1


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def test_database_groups_tables_under_resolved_database_name():
    sub_reports = [{
        "service_name": "ticketing",
        "config_files": _cfg(("spring.datasource.url", "jdbc:mysql://db-host:3306/ticketing_db")),
        "migration_scripts": [{"tables_affected": ["ticket", "ticket_comment"]}],
    }]
    result = compute_database_requirements(sub_reports)
    req = result["requirements"][0]
    assert req["database_name"] == "ticketing_db"
    assert req["tables"] == ["ticket", "ticket_comment"]
    assert req["services"] == ["ticketing"]


def test_database_externally_parameterized_url_falls_back_to_unnamed_gap():
    sub_reports = [{
        "service_name": "blob-store",
        "config_files": _cfg(("spring.datasource.url", "${parts.blob-store.db.url}")),
        "migration_scripts": [{"tables_affected": ["blob_table"]}],
    }]
    result = compute_database_requirements(sub_reports)
    assert result["requirements"] == []
    assert any("blob-store" in g for g in result["known_gaps"])
    assert "spring.datasource.url" in result["per_service"]["blob-store"]["externally_parameterized_keys"]


def test_database_collision_detected_when_two_services_share_db_name():
    sub_reports = [
        {"service_name": "svc-a", "config_files": _cfg(("spring.datasource.url", "jdbc:mysql://h/shared_db")),
         "migration_scripts": [{"tables_affected": ["a_table"]}]},
        {"service_name": "svc-b", "config_files": _cfg(("spring.datasource.url", "jdbc:mysql://h/shared_db")),
         "migration_scripts": [{"tables_affected": ["b_table"]}]},
    ]
    result = compute_database_requirements(sub_reports)
    assert len(result["collisions"]) == 1
    assert result["collisions"][0]["services"] == ["svc-a", "svc-b"]


def test_database_is_mysql_detected_via_db_type_even_with_placeholder_url():
    sub_reports = [{
        "service_name": "catalog",
        "config_files": _cfg(("db.type", "mysql"), ("spring.datasource.url", "${parts.catalog.db.url}")),
        "migration_scripts": [],
    }]
    result = compute_database_requirements(sub_reports)
    assert result["per_service"]["catalog"]["is_mysql"] is True


# ---------------------------------------------------------------------------
# Messaging
# ---------------------------------------------------------------------------

def test_messaging_topology_role_and_connection_facts():
    sub_reports = [{
        "service_name": "blob-store",
        "config_files": _cfg(("event.rabbitmq.virtualHost", "/"), ("event.rabbitmq.addresses", "mq.example.com:443")),
        "event_files": [{"published": [{}, {}], "consumed": []}],
    }]
    result = compute_messaging_requirements(sub_reports)
    req = result["requirements"][0]
    assert req["virtual_host"] == "/"
    assert req["address"] == "mq.example.com:443"
    assert req["port"] == 443
    assert "publisher" in req["role"]


def test_messaging_missing_exchange_queue_data_yields_reliability_gap():
    sub_reports = [{
        "service_name": "catalog",
        "config_files": _cfg(("event.rabbitmq.virtualHost", "/")),
        "event_files": [{"published": [{"entity": "x"}], "consumed": []}],
    }]
    result = compute_messaging_requirements(sub_reports)
    assert any("not derivable" in g for g in result["known_gaps"])


def test_messaging_surfaces_exchange_queue_when_present():
    sub_reports = [{
        "service_name": "svc",
        "config_files": [],
        "event_files": [{"published": [{"exchange": "orders.exchange"}],
                          "consumed": [{"queue": "orders.queue", "routing_key": "orders.created"}]}],
    }]
    result = compute_messaging_requirements(sub_reports)
    req = result["requirements"][0]
    assert req["exchanges"] == ["orders.exchange"]
    assert req["queues"] == ["orders.queue"]
    assert req["routing_keys"] == ["orders.created"]
    assert not any("not derivable" in g for g in result["known_gaps"])


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

def test_aggregator_combines_all_three_sections():
    sub_reports = [{
        "service_name": "svc", "config_files": [], "endpoints": [], "migration_scripts": [], "event_files": [],
    }]
    result = compute_infra_requirements(sub_reports)
    assert set(result.keys()) == {"iam", "database", "messaging"}
