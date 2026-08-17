"""Base provisioner — issues certs and generates Ansible vars for base host provisioning."""

import json
import logging
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.build_manager import BMEnvironment, BMEnvironmentCert, BMTemplateVersion

logger = logging.getLogger(__name__)


async def provision_environment(db: AsyncSession, environment_id: str) -> dict:
    """Issue certs for all hosts in an environment and return Ansible extra_vars."""
    result = await db.execute(
        select(BMEnvironment).where(BMEnvironment.id == environment_id)
    )
    env = result.scalar_one_or_none()
    if not env:
        raise ValueError("Environment not found")

    ver_result = await db.execute(
        select(BMTemplateVersion).where(
            BMTemplateVersion.template_id == env.template_id,
            BMTemplateVersion.version == env.template_version,
        )
    )
    version = ver_result.scalar_one_or_none()
    if not version:
        raise ValueError("Template version not found")

    spec = json.loads(version.spec)
    ip_allocations = json.loads(env.ip_allocations) if env.ip_allocations else {}
    variables = json.loads(env.variables) if env.variables else {}
    domain = variables.get("domain", spec.get("variables", {}).get("domain", "internal"))
    signing_ca_id = variables.get("signing_ca_id")

    ca_chain_pem = await _get_ca_chain(db, signing_ca_id)

    host_vars = {}
    host_products = {}

    # Detect a mysql+adminer pairing once, up front, so both hosts' vars can
    # get sensible cross-product defaults below (opt-in remote root access
    # for mysql, and pointing Adminer's default Server field at the paired
    # mysql host instead of its otherwise-useless 127.0.0.1 role default) —
    # a fresh mysql install only ever grants 'root'@'localhost', so without
    # this an Adminer host on a separate container can never reach it no
    # matter what password is configured.
    mysql_role = next(
        (h["role"] for h in spec.get("hosts", [])
         if any(_product_name(p) == "mysql" for p in h.get("products", []))),
        None,
    )
    adminer_role = next(
        (h["role"] for h in spec.get("hosts", [])
         if any(_product_name(p) == "adminer" for p in h.get("products", []))),
        None,
    )

    for host_def in spec.get("hosts", []):
        role = host_def["role"]
        hostname = ip_allocations.get(role, f"target-{role}")
        cn = f"{role}.{domain}"

        sans = [f"DNS:{cn}", f"DNS:target-{role}", "DNS:localhost", "IP:127.0.0.1"]
        if hostname and hostname != f"target-{role}":
            sans.append(f"IP:{hostname}" if _is_ip(hostname) else f"DNS:{hostname}")

        cert_pem, key_pem, serial = await _issue_cert(
            db=db, cn=cn, sans=sans, profile="server",
            validity_days=host_def.get("cert", {}).get("validity_days", 365),
            preferred_ca_id=signing_ca_id,
        )

        env_cert = BMEnvironmentCert(
            id=str(uuid.uuid4()),
            environment_id=environment_id,
            cert_serial=serial,
            role=role,
            cert_type="server",
            issued_at=datetime.now(timezone.utc),
        )
        db.add(env_cert)

        # Create cert binding for lifecycle tracking
        from app.services.build_manager.cert_lifecycle import create_binding_from_cert
        await create_binding_from_cert(db, environment_id, serial, role, "server")

        host_vars[role] = {
            "server_cert_pem": cert_pem,
            "server_key_pem": key_pem,
            "truststore_password": secrets.token_urlsafe(16),
            "keystore_password": secrets.token_urlsafe(16),
        }

        # Issue client certificate if host spec defines client_certs
        client_certs_spec = host_def.get("client_certs", [])
        if client_certs_spec:
            client_cn = f"{role}-client.{domain}"
            client_sans = [f"DNS:{client_cn}", "DNS:localhost"]
            client_cert_pem, client_key_pem, client_serial = await _issue_cert(
                db=db, cn=client_cn, sans=client_sans, profile="client",
                validity_days=host_def.get("cert", {}).get("validity_days", 365),
                preferred_ca_id=signing_ca_id,
            )
            env_client_cert = BMEnvironmentCert(
                id=str(uuid.uuid4()),
                environment_id=environment_id,
                cert_serial=client_serial,
                role=role,
                cert_type="client",
                issued_at=datetime.now(timezone.utc),
            )
            db.add(env_client_cert)
            await create_binding_from_cert(db, environment_id, client_serial, role, "client")
            host_vars[role]["client_cert_pem"] = client_cert_pem
            host_vars[role]["client_key_pem"] = client_key_pem

        # Collect products for this host role
        products = host_def.get("products", [])
        if products:
            from app.services.build_manager.orchestrator import resolve_execution_order, get_dependency_catalogue
            raw_products = []
            for p in products:
                product_name = _product_name(p)
                if not product_name:
                    continue
                merged_vars = {**p.get("vars", {}), **_get_product_config(variables, role, product_name)}
                merged_vars = _apply_mysql_adminer_pairing_defaults(
                    product_name, merged_vars, mysql_role, adminer_role, ip_allocations,
                )
                raw_products.append({
                    "ansible_role": product_name,
                    "vars": _resolve_cross_host_refs(merged_vars, ip_allocations),
                })
            # Resolve dependency order
            catalogue = await get_dependency_catalogue(db)
            host_products[role] = resolve_execution_order(raw_products, catalogue)

    await db.commit()
    return {"ca_chain_pem": ca_chain_pem, "host_vars": host_vars, "host_products": host_products}


async def _get_ca_chain(db: AsyncSession, signing_ca_id: str | None = None) -> str:
    """Get the CA chain PEM from SSL Cert Manager's database."""
    from app.models.ca import CertificateAuthority

    if signing_ca_id:
        # Build chain from the selected CA up to root
        chain_parts = []
        current_id = signing_ca_id
        while current_id:
            result = await db.execute(
                select(CertificateAuthority).where(CertificateAuthority.id == current_id)
            )
            ca = result.scalar_one_or_none()
            if not ca or not ca.cert_pem:
                break
            chain_parts.append(ca.cert_pem.strip())
            current_id = ca.parent_ca_id
        if chain_parts:
            return "\n".join(chain_parts)

    # Fallback: return all CAs
    result = await db.execute(
        select(CertificateAuthority).order_by(CertificateAuthority.parent_ca_id.desc())
    )
    cas = result.scalars().all()
    if not cas:
        raise ValueError("No CA found in SSL Cert Manager. Create a CA first.")

    chain_parts = []
    for ca in cas:
        if ca.cert_pem:
            chain_parts.append(ca.cert_pem.strip())
    return "\n".join(chain_parts)


async def _issue_cert(
    db: AsyncSession, cn: str, sans: list[str], profile: str = "server", validity_days: int = 365,
    preferred_ca_id: str | None = None,
) -> tuple[str, str, str]:
    """Issue a certificate via SSL Cert Manager's internal crypto engine.

    Returns (cert_pem, key_pem, serial_hex).
    """
    from app.models.ca import CertificateAuthority
    from app.models.certificate import Certificate
    from app.services.crypto_engine import CryptoEngine, SubjectInfo, SANEntry

    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, load_pem_private_key
    from cryptography import x509 as cx509

    crypto = CryptoEngine()

    # Find signing CA — use preferred if specified, otherwise auto-select
    if preferred_ca_id:
        result = await db.execute(
            select(CertificateAuthority)
            .where(CertificateAuthority.id == preferred_ca_id, CertificateAuthority.key_blob.isnot(None))
        )
        ca = result.scalar_one_or_none()
        if not ca:
            raise ValueError(f"Selected signing CA '{preferred_ca_id}' not found or has no key")
    else:
        # Auto-select: prefer intermediate, skip CAs with restrictive Name Constraints
        result = await db.execute(
            select(CertificateAuthority)
            .where(CertificateAuthority.key_blob.isnot(None))
            .order_by(CertificateAuthority.parent_ca_id.desc())
        )
        all_cas = result.scalars().all()
        ca = None
        for candidate in all_cas:
            ca_cert_obj = cx509.load_pem_x509_certificate(candidate.cert_pem.encode())
            try:
                nc = ca_cert_obj.extensions.get_extension_for_class(cx509.NameConstraints)
                permitted = nc.value.permitted_subtrees or []
                if permitted and not _sans_permitted(sans, permitted):
                    continue
            except cx509.ExtensionNotFound:
                pass
            ca = candidate
            break
        if not ca:
            raise ValueError("No CA with signing key found that permits the requested SANs")

    ca_key_pem_bytes = crypto.decrypt_key_blob(ca.key_blob, settings.CERT_MASTER_KEY)
    ca_key = load_pem_private_key(ca_key_pem_bytes, password=None)
    ca_cert = cx509.load_pem_x509_certificate(ca.cert_pem.encode())

    # Generate leaf keypair
    key = crypto.generate_keypair("RSA", 2048)

    # Parse SANs
    san_entries = []
    for san in sans:
        if san.startswith("DNS:"):
            san_entries.append(SANEntry(type="dns", value=san[4:]))
        elif san.startswith("IP:"):
            san_entries.append(SANEntry(type="ip", value=san[3:]))

    subject = SubjectInfo(cn=cn)

    cert = crypto.issue_certificate(
        profile=profile,
        subject=subject,
        san_list=san_entries,
        key=key,
        signing_ca_key=ca_key,
        signing_ca_cert=ca_cert,
        validity_days=validity_days,
        signing_ca_id=ca.id,
    )

    cert_pem = cert.public_bytes(Encoding.PEM).decode()
    key_pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    serial_hex = format(cert.serial_number, "x")

    # Store in SSL Cert Manager's certificate table
    key_blob = crypto.encrypt_key_blob(
        key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()),
        settings.CERT_MASTER_KEY,
    )

    db_cert = Certificate(
        id=str(uuid.uuid4()),
        serial=serial_hex,
        profile=profile,
        subject_json=json.dumps({"cn": cn}),
        san_json=json.dumps(sans),
        key_algo="RSA",
        key_size=2048,
        cert_pem=cert_pem,
        key_blob=key_blob,
        chain_pem=ca.cert_pem,
        signing_ca_id=ca.id,
        status="valid",
        expires_at=cert.not_valid_after_utc,
        tags=json.dumps(["build-manager", "auto-issued"]),
    )
    db.add(db_cert)

    return cert_pem, key_pem, serial_hex


def _is_ip(value: str) -> bool:
    parts = value.split(".")
    if len(parts) == 4:
        return all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)
    return ":" in value


def _sans_permitted(sans: list[str], permitted_subtrees) -> bool:
    """Check if all SANs are allowed by the CA's Name Constraints permitted subtrees."""
    from cryptography.x509 import DNSName, IPAddress

    for san in sans:
        if san.startswith("DNS:"):
            dns_val = san[4:]
            # Check against permitted DNS names
            dns_ok = False
            for subtree in permitted_subtrees:
                if isinstance(subtree.value, DNSName):
                    pattern = subtree.value.value  # e.g. ".alpha.internal"
                    if pattern.startswith("."):
                        if dns_val.endswith(pattern) or dns_val == pattern[1:]:
                            dns_ok = True
                            break
                    elif dns_val == pattern:
                        dns_ok = True
                        break
            if not dns_ok:
                return False
        # IP SANs and other types: if no IP constraints exist, they're implicitly allowed
        # (Name Constraints only restrict the types listed in permitted subtrees)
    return True


def _get_product_config(variables: dict, role: str, product_name: str) -> dict:
    """Extract product config from environment variables.

    The UI stores config as: variables.product_config.<role>.<product_name> = {key: value}
    """
    pc = variables.get("product_config", {})
    return pc.get(role, {}).get(product_name, {})


def _product_name(p: dict) -> str:
    return p.get("ansible_role", p.get("product_name", p.get("product", "")))


def _apply_mysql_adminer_pairing_defaults(
    product_name: str, merged_vars: dict, mysql_role: str | None, adminer_role: str | None, ip_allocations: dict,
) -> dict:
    """When mysql and adminer are both present in the same spec, default two
    vars that would otherwise silently make Adminer unable to reach mysql —
    without these, a fresh mysql install only grants 'root'@'localhost' (no
    remote host, regardless of password) and Adminer's Server field defaults
    to 127.0.0.1 (itself, not the mysql host). Only fills in values the user
    hasn't already set explicitly."""
    if product_name == "mysql" and adminer_role and "mysql_allow_remote_root" not in merged_vars:
        merged_vars = {**merged_vars, "mysql_allow_remote_root": True}
    if product_name == "adminer" and mysql_role and "adminer_default_server" not in merged_vars:
        mysql_host = ip_allocations.get(mysql_role, f"target-{mysql_role}")
        merged_vars = {**merged_vars, "adminer_default_server": mysql_host}
    return merged_vars


def _resolve_cross_host_refs(product_vars: dict, ip_allocations: dict) -> dict:
    """Rewrite cross-host references baked into a template's product vars
    (nfs_mounts[].src's "<role>:<path>" host part, lb_upstreams[].host) to
    each referenced role's *actual* container name for this environment,
    not the literal role name the template author wrote.

    Every seeded template assumes "role name == container name" (true only
    when no Host Mapping override is used — the "no network pool" auto-
    detect path every host in this codebase's own test builds relied on).
    Found via a real live build: mapping roles to the pre-existing target-*
    fixture containers via Host Mapping (e.g. pkg-cache -> target-pkg-cache)
    left nfs_mounts.src still reading the literal "pkg-cache:/srv/nfs-export"
    — a hostname nothing on docker_bm-net actually answers to — so mysql's
    "Mount NFS shares" task failed with "Failed to resolve server pkg-cache".
    ip_allocations already maps every role to whatever container name it was
    actually assigned, so this is a no-op (identity mapping) for every
    environment that doesn't override the default naming."""
    result = dict(product_vars)

    nfs_mounts = result.get("nfs_mounts")
    if isinstance(nfs_mounts, list):
        new_mounts = []
        for m in nfs_mounts:
            m = dict(m)
            src = m.get("src", "")
            host_part, sep, rest = src.partition(":")
            actual = ip_allocations.get(host_part)
            if sep and actual and actual != host_part:
                m["src"] = f"{actual}:{rest}"
            new_mounts.append(m)
        result["nfs_mounts"] = new_mounts

    lb_upstreams = result.get("lb_upstreams")
    if isinstance(lb_upstreams, list):
        new_upstreams = []
        for u in lb_upstreams:
            u = dict(u)
            actual = ip_allocations.get(u.get("host", ""))
            if actual and actual != u.get("host"):
                u["host"] = actual
            new_upstreams.append(u)
        result["lb_upstreams"] = new_upstreams

    return result
