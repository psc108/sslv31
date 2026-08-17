"""Actuator/management endpoint exposure detection."""
from app.services.jar_analyser.actuator_exposure import compute_actuator_exposure


def _key(name, value, is_placeholder=False):
    return {"key": name, "value": value, "category": "actuator", "is_placeholder": is_placeholder, "is_encrypted": False}


def _sr(service_name="svc", declared_port=8080, keys=None, deps=None, jar_type="library"):
    return {
        "service_name": service_name,
        "declared_port": declared_port,
        "jar_type": jar_type,
        "installer_metadata": {},
        "dependencies": deps or [],
        "config_files": [{"keys": keys or []}],
    }


def test_no_actuator_evidence_yields_no_entry():
    result = compute_actuator_exposure([_sr(keys=[], deps=[])])
    assert result["services"] == []


def test_actuator_dependency_without_exposure_key_is_not_flagged():
    deps = [{"artifact_id": "spring-boot-starter-actuator", "filename": "spring-boot-starter-actuator-3.2.0.jar"}]
    result = compute_actuator_exposure([_sr(keys=[], deps=deps)])
    assert result["services"] == []


def test_only_health_exposed_is_not_flagged():
    keys = [_key("management.endpoints.web.exposure.include", "health,info")]
    result = compute_actuator_exposure([_sr(keys=keys)])
    assert result["services"] == []


def test_wildcard_exposure_same_port_and_proxied_is_high_risk():
    nginx_sr = {
        "service_name": "frontend-lb", "jar_type": "nginx_installer", "declared_port": None,
        "installer_metadata": {"nginx": {"service_dependencies": ["svc"], "upstreams": []}},
        "dependencies": [], "config_files": [],
    }
    keys = [_key("management.endpoints.web.exposure.include", "*")]
    result = compute_actuator_exposure([_sr(keys=keys), nginx_sr])
    entry = result["services"][0]
    assert entry["exposure_is_wildcard"] is True
    assert "env" in entry["sensitive_endpoints_exposed"]
    assert entry["risk"] == "high"


def test_sensitive_endpoints_same_port_unknown_proxy_is_medium_risk():
    keys = [_key("management.endpoints.web.exposure.include", "env,heapdump")]
    result = compute_actuator_exposure([_sr(keys=keys)])
    entry = result["services"][0]
    assert entry["sensitive_endpoints_exposed"] == ["env", "heapdump"]
    assert entry["externally_proxied"] is None
    assert entry["risk"] == "medium"


def test_separate_management_port_downgrades_to_low_risk():
    keys = [
        _key("management.endpoints.web.exposure.include", "env"),
        _key("management.server.port", "9001"),
    ]
    result = compute_actuator_exposure([_sr(declared_port=8080, keys=keys)])
    entry = result["services"][0]
    assert entry["same_port_as_app"] is False
    assert entry["management_port"] == 9001
    assert entry["risk"] == "low"


def test_shutdown_listed_but_not_enabled_is_not_flagged():
    keys = [_key("management.endpoints.web.exposure.include", "shutdown")]
    result = compute_actuator_exposure([_sr(keys=keys)])
    assert result["services"] == []


def test_shutdown_listed_and_enabled_is_flagged():
    keys = [
        _key("management.endpoints.web.exposure.include", "shutdown"),
        _key("management.endpoint.shutdown.enabled", "true"),
    ]
    result = compute_actuator_exposure([_sr(keys=keys)])
    entry = result["services"][0]
    assert "shutdown" in entry["sensitive_endpoints_exposed"]


def test_python_list_repr_format_parses_same_as_comma_separated():
    """Real-data finding: some bundles store this as a YAML list that ends up
    flattened to a Python-list-repr string, e.g. "['env', 'heapdump']"."""
    keys = [_key("management.endpoints.web.exposure.include", "['env', 'heapdump']")]
    result = compute_actuator_exposure([_sr(keys=keys)])
    entry = result["services"][0]
    assert entry["sensitive_endpoints_exposed"] == ["env", "heapdump"]


def test_python_list_repr_with_only_safe_endpoints_is_not_flagged():
    keys = [_key("management.endpoints.web.exposure.include", "['health', 'info', 'metrics']")]
    result = compute_actuator_exposure([_sr(keys=keys)])
    assert result["services"] == []


def test_placeholder_exposure_value_yields_unknown_risk_not_resolved():
    keys = [_key("management.endpoints.web.exposure.include", "${actuator.exposure}", is_placeholder=True)]
    result = compute_actuator_exposure([_sr(keys=keys)])
    entry = result["services"][0]
    assert entry["risk"] == "unknown"
    assert "sensitive_endpoints_exposed" not in entry
