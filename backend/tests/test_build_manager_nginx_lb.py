"""nginx_lb product — TLS-terminating, multi-service reverse-proxy load
balancer used as both frontend-lb and backend-lb.

Modeled directly on the real application's own frontend-lb/backend-lb nginx
configs (captured via the JAR Analyser, jar_type "nginx_installer"): both
terminate client-facing TLS with their own cert, then re-encrypt outbound
(proxy_pass https://, not http://) to each named upstream service, rather
than a passthrough tunnel. One reusable catalogue product is used for both
roles — the real app deploys the exact same nginx_installer artifact for
both, just with a different .conf — so these tests confirm the same product
can be configured independently per host role.
"""
import uuid

import pytest


def test_nginx_lb_product_has_expected_upstream_schema():
    from app.services.build_manager.catalogue_service import SEED_PRODUCTS

    nginx_lb = next(p for p in SEED_PRODUCTS if p["name"] == "nginx_lb")
    assert nginx_lb["cert_requirements"]["server_tls"] is True

    upstreams_field = next(f for f in nginx_lb["config_schema"] if f["key"] == "lb_upstreams")
    assert upstreams_field["type"] == "list"
    assert upstreams_field["required"] is True
    item_keys = {f["key"] for f in upstreams_field["item_schema"]}
    assert item_keys == {"name", "path", "host", "port"}

    versions = {v["version"]: v for v in nginx_lb["versions"]}
    assert versions["1"]["ansible_role"] == "nginx_lb"


@pytest.mark.usefixtures("setup_db")
async def test_seeded_full_stack_and_custom_specs_pass_validation_with_nginx_lb(client):
    """A template using nginx_lb twice — once per host role, each with its
    own independent lb_upstreams list — must pass validate_spec() cleanly.
    This is the actual shape the Full Stack template will use once the LB
    tier is folded in (frontend-lb fronting frontend, backend-lb fronting
    backend)."""
    resp = await client.post("/api/v1/build/templates", json={
        "name": f"nginx-lb-pair-test-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [
            {"role": "backend", "products": [
                {"product": "python", "version": "3.12", "vars": {}},
                {"product": "uvicorn", "version": "0.32", "vars": {}},
            ], "certs": ["server_tls"]},
            {"role": "frontend-lb", "products": [
                {"product": "nginx_lb", "version": "1", "vars": {"lb_upstreams": [
                    {"name": "backend", "path": "/api/", "host": "backend", "port": 8000},
                ]}},
            ], "certs": ["server_tls"]},
            {"role": "backend-lb", "products": [
                {"product": "nginx_lb", "version": "1", "vars": {"lb_upstreams": [
                    {"name": "backend", "path": "/api/", "host": "backend", "port": 8000},
                ]}},
            ], "certs": ["server_tls"]},
        ]},
    })
    assert resp.status_code == 201, resp.text


@pytest.mark.usefixtures("setup_db")
async def test_nginx_lb_resolves_independent_vars_per_host_role(client):
    """The whole point of using one product for both roles: frontend-lb and
    backend-lb must each get the nginx_lb ansible_role with their own
    distinct lb_upstreams, not a shared/merged config."""
    from app.services.build_manager.base_provisioner import provision_environment

    resp = await client.post("/api/v1/build/templates", json={
        "name": f"nginx-lb-independent-vars-test-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [
            {"role": "frontend-lb", "products": [
                {"product": "nginx_lb", "version": "1", "vars": {"lb_upstreams": [
                    {"name": "portal-ui", "path": "/", "host": "portal-ui", "port": 8080},
                    {"name": "backend", "path": "/api/", "host": "backend", "port": 8000},
                ]}},
            ], "certs": ["server_tls"]},
            {"role": "backend-lb", "products": [
                {"product": "nginx_lb", "version": "1", "vars": {"lb_upstreams": [
                    {"name": "backend", "path": "/api/", "host": "backend", "port": 8000},
                ]}},
            ], "certs": ["server_tls"]},
        ]},
    })
    assert resp.status_code == 201, resp.text
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/ca", json={
        "subject": {"cn": f"Nginx LB Test Root {uuid.uuid4().hex[:8]}"},
        "key_algo": "RSA", "key_size": 2048, "validity_days": 30,
    })
    ca_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"nginx-lb-independent-vars-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
        "variables": {"signing_ca_id": ca_id},
    })
    assert resp.status_code == 201, resp.text
    env_id = resp.json()["id"]

    from app.core.database import async_session
    async with async_session() as db:
        provision_data = await provision_environment(db, env_id)

    frontend_lb_product = provision_data["host_products"]["frontend-lb"][0]
    backend_lb_product = provision_data["host_products"]["backend-lb"][0]

    assert frontend_lb_product["ansible_role"] == "nginx_lb"
    assert backend_lb_product["ansible_role"] == "nginx_lb"

    frontend_lb_upstreams = frontend_lb_product["vars"]["lb_upstreams"]
    backend_lb_upstreams = backend_lb_product["vars"]["lb_upstreams"]
    assert len(frontend_lb_upstreams) == 2
    assert len(backend_lb_upstreams) == 1
    assert frontend_lb_upstreams != backend_lb_upstreams
