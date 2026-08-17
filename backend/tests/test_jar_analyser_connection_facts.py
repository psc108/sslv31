"""Stage 4 of the infra-requirements plan — shared connection-fact extraction."""
from app.services.jar_analyser.connection_facts import extract_connection_facts


def _keys(*pairs):
    return [{"key": k, "value": v, "is_encrypted": False, "is_placeholder": False} for k, v in pairs]


def test_literal_mysql_url_resolves_host_port_and_db_name():
    keys = _keys(("spring.datasource.url", "jdbc:mysql://db-host:3306/mydb?useSSL=false"))
    facts = extract_connection_facts(keys)
    assert facts.database.host == "db-host"
    assert facts.database.port == 3306
    assert facts.database.database_name == "mydb"


def test_placeholder_url_with_no_default_is_externally_parameterized_not_resolved():
    keys = _keys(("spring.datasource.url", "${parts.blob-store.db.url}"))
    facts = extract_connection_facts(keys)
    assert facts.database.host is None
    assert facts.database.database_name is None
    assert "spring.datasource.url" in facts.database.externally_parameterized_keys


def test_placeholder_with_embedded_default_is_not_resolved_either():
    """A ${VAR:default} embedded default is a local-test fixture in real data,
    not deployment guidance — must never be surfaced as a resolved fact."""
    keys = _keys(("spring.datasource.url", "${test.db.url:jdbc:mysql://localhost/blob_store_user}"))
    facts = extract_connection_facts(keys)
    assert facts.database.host is None
    assert facts.database.url is None
    assert "spring.datasource.url" in facts.database.externally_parameterized_keys


def test_db_type_and_driver_class_are_literal_facts():
    keys = _keys(("db.type", "mysql"), ("spring.datasource.driver-class-name", "com.mysql.cj.jdbc.Driver"))
    facts = extract_connection_facts(keys)
    assert facts.database.db_type == "mysql"
    assert facts.database.driver_class == "com.mysql.cj.jdbc.Driver"


def test_product_specific_rabbitmq_convention_recognized():
    keys = _keys(
        ("event.rabbitmq.virtualHost", "/"),
        ("event.rabbitmq.addresses", "cps-rabbit-dev-eu.example.com:443"),
    )
    facts = extract_connection_facts(keys)
    assert facts.messaging.virtual_host == "/"
    assert facts.messaging.address == "cps-rabbit-dev-eu.example.com:443"
    assert facts.messaging.port == 443


def test_generic_spring_rabbitmq_convention_still_recognized():
    keys = _keys(("spring.rabbitmq.virtual-host", "/orders"), ("spring.rabbitmq.ssl.enabled", "true"))
    facts = extract_connection_facts(keys)
    assert facts.messaging.virtual_host == "/orders"
    assert facts.messaging.ssl_enabled is True


def test_iam_auth_url_and_project_extracted():
    keys = _keys(
        ("openstack.auth.url", "https://keystone.example.com:5000/v3"),
        ("openstack.credentials.project-name", "cps"),
    )
    facts = extract_connection_facts(keys)
    assert facts.iam.auth_host == "keystone.example.com"
    assert facts.iam.project_name == "cps"


def test_encrypted_value_is_not_resolved():
    keys = _keys(("spring.datasource.username", "ENC(abcd1234)"))
    facts = extract_connection_facts(keys)
    assert facts.database.username is None
    assert "spring.datasource.username" in facts.database.externally_parameterized_keys


def test_non_mysql_literal_datasource_url_does_not_resolve_host():
    """Scoped to mysql specifically, matching the original tool's precision."""
    keys = _keys(("spring.datasource.url", "jdbc:postgresql://db-host:5432/mydb"))
    facts = extract_connection_facts(keys)
    assert facts.database.host is None
