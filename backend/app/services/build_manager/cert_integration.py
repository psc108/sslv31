"""Certificate integration for Build Manager environments.

Issues, exports, and renews TLS certificates for EC2 and on-premises hosts
by calling the SSL Cert Manager crypto engine directly (in-process — no HTTP
round-trip, same pattern as base_provisioner._issue_cert).

Called after `tofu apply` for AWS environments (private IPs known only then),
or at environment creation time for on-premises/Docker (IPs known upfront).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.build_manager import BMEnvironmentCert

logger = logging.getLogger(__name__)

# Roles that never need a TLS cert
_NO_CERT_ROLES = {"bastion"}

CERTS_BASE = Path("/data/environments")


def requires_cert(service_role: str) -> bool:
    return service_role not in _NO_CERT_ROLES


def build_sans_for_host(
    host: dict,
    private_ip: str,
    tofu_outputs: dict | None = None,
    aws_config: dict | None = None,
    san_include_localhost: bool = True,
) -> tuple[list[str], list[str]]:
    """Return (dns_sans, ip_sans) for a host.

    For AWS environments, tofu_outputs and aws_config are provided so that
    NLB-exposed services get the NLB DNS names in their SANs.
    For on-premises/Docker, pass tofu_outputs=None.
    """
    service_role = host.get("service_role", "generic")
    if not requires_cert(service_role):
        return [], []

    hostname = host["role"]
    dns_sans: list[str] = [hostname]
    ip_sans: list[str] = [private_ip] if private_ip else []

    if san_include_localhost:
        dns_sans.append("localhost")
        ip_sans.append("127.0.0.1")

    if tofu_outputs and aws_config:
        nlb_cfg = aws_config.get("load_balancers", {}).get("nlb", {})
        nlb_enabled = nlb_cfg.get("enabled", True)
        nlb_aws_dns = tofu_outputs.get("nlb_dns_name")
        route53_nlb = tofu_outputs.get("route53_nlb_fqdn")

        if nlb_enabled and nlb_aws_dns:
            if service_role == "mysql" and nlb_cfg.get("expose_mysql"):
                dns_sans.append(nlb_aws_dns)
                if route53_nlb:
                    dns_sans.append(route53_nlb)
            if service_role == "rabbitmq" and nlb_cfg.get("expose_rabbitmq"):
                dns_sans.append(nlb_aws_dns)
                if route53_nlb:
                    dns_sans.append(route53_nlb)

    return dns_sans, ip_sans


async def issue_environment_certs(
    db: AsyncSession,
    environment_id: str,
    environment_name: str,
    hosts: list[dict],
    ip_map: dict[str, str],
    signing_ca_id: str | None,
    validity_days: int = 365,
    tofu_outputs: dict | None = None,
    aws_config: dict | None = None,
    san_include_localhost: bool = True,
) -> dict[str, str]:
    """Issue server certs for all TLS-serving hosts.

    ip_map: {role -> ip/hostname}
    Returns {role -> serial}.
    """
    from app.services.build_manager.base_provisioner import _issue_cert

    serials: dict[str, str] = {}

    for host in hosts:
        service_role = host.get("service_role", "generic")
        if not requires_cert(service_role):
            continue

        role = host["role"]
        private_ip = ip_map.get(role, "")
        dns_sans, ip_sans = build_sans_for_host(
            host, private_ip, tofu_outputs, aws_config, san_include_localhost
        )

        cn = role
        sans = [f"DNS:{d}" for d in dns_sans] + [f"IP:{i}" for i in ip_sans]

        cert_pem, key_pem, serial = await _issue_cert(
            db=db,
            cn=cn,
            sans=sans,
            profile="server",
            validity_days=validity_days,
            preferred_ca_id=signing_ca_id,
        )

        # Look up expiry from the just-created Certificate row
        from app.models.certificate import Certificate
        cert_row = await db.execute(select(Certificate).where(Certificate.serial == serial))
        cert_obj = cert_row.scalar_one_or_none()
        expires_at = cert_obj.expires_at if cert_obj else None

        env_cert = BMEnvironmentCert(
            id=str(uuid.uuid4()),
            environment_id=environment_id,
            cert_serial=serial,
            role=role,
            cert_type="server",
            issued_at=datetime.now(timezone.utc),
        )
        # Set optional extra columns if they exist on the model
        if hasattr(env_cert, "expires_at"):
            env_cert.expires_at = expires_at
        if hasattr(env_cert, "san_dns"):
            env_cert.san_dns = json.dumps(dns_sans)
        if hasattr(env_cert, "san_ip"):
            env_cert.san_ip = json.dumps(ip_sans)

        db.add(env_cert)

        # Write cert files to disk
        host_dir = CERTS_BASE / environment_name / "certs" / role
        host_dir.mkdir(parents=True, exist_ok=True)
        (host_dir / "server.crt").write_text(cert_pem)
        key_path = host_dir / "server.key"
        key_path.write_text(key_pem)
        key_path.chmod(0o600)

        # fullchain = cert + CA chain
        from app.services.build_manager.base_provisioner import _get_ca_chain
        try:
            ca_chain = await _get_ca_chain(db, signing_ca_id)
            (host_dir / "fullchain.pem").write_text(cert_pem + "\n" + ca_chain)
        except Exception:
            (host_dir / "fullchain.pem").write_text(cert_pem)

        serials[role] = serial
        logger.info("Issued cert for %s/%s serial=%s", environment_name, role, serial)

    await db.commit()
    return serials


async def export_trust_bundle(
    db: AsyncSession,
    environment_name: str,
    signing_ca_id: str | None,
) -> None:
    """Write ca-chain.pem and truststore.jks to the environment certs directory."""
    from app.services.build_manager.base_provisioner import _get_ca_chain

    certs_dir = CERTS_BASE / environment_name / "certs"
    certs_dir.mkdir(parents=True, exist_ok=True)

    ca_chain = await _get_ca_chain(db, signing_ca_id)
    (certs_dir / "ca-chain.pem").write_text(ca_chain)

    # Build JKS trust store via keytool if available
    _build_jks_truststore(certs_dir, ca_chain)


def _build_jks_truststore(certs_dir: Path, ca_chain_pem: str) -> None:
    """Build truststore.jks from the CA chain PEM using keytool."""
    import subprocess
    import tempfile

    jks_path = certs_dir / "truststore.jks"
    if jks_path.exists():
        jks_path.unlink()

    # Split chain into individual certs
    pem_blocks: list[str] = []
    current: list[str] = []
    for line in ca_chain_pem.splitlines():
        current.append(line)
        if "-----END CERTIFICATE-----" in line:
            pem_blocks.append("\n".join(current))
            current = []

    if not pem_blocks:
        return

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            for i, pem in enumerate(pem_blocks):
                cert_file = os.path.join(tmpdir, f"ca-{i}.pem")
                with open(cert_file, "w") as f:
                    f.write(pem)
                subprocess.run(
                    [
                        "keytool", "-importcert",
                        "-noprompt",
                        "-trustcacerts",
                        "-alias", f"certmanager-ca-{i}",
                        "-file", cert_file,
                        "-keystore", str(jks_path),
                        "-storepass", "changeit",
                    ],
                    check=True,
                    capture_output=True,
                )
    except Exception as exc:
        logger.warning("Could not build JKS truststore: %s", exc)


def get_cert_dir(environment_name: str, role: str) -> Path:
    return CERTS_BASE / environment_name / "certs" / role


def get_ca_chain_path(environment_name: str) -> Path:
    return CERTS_BASE / environment_name / "certs" / "ca-chain.pem"


def get_truststore_path(environment_name: str) -> Path:
    return CERTS_BASE / environment_name / "certs" / "truststore.jks"
