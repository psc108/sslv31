"""Kubernetes cert-manager webhook issuer endpoints.

Implements the cert-manager external issuer webhook protocol so that
cert-manager can request certificates from this CA automatically.

Endpoints:
- POST /api/v1/k8s/sign         — Sign a CSR (cert-manager calls this)
- GET  /api/v1/k8s/config       — Current issuer configuration
- PUT  /api/v1/k8s/config       — Update issuer configuration
- GET  /api/v1/k8s/manifests    — Download example K8s manifests
- GET  /api/v1/k8s/health       — Issuer health (no auth, for K8s probes)
"""

import base64
import json
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import AuthContext, get_auth_context, require_permission
from app.models.ca import CertificateAuthority
from app.models.certificate import Certificate
from app.services.crypto_engine import CryptoEngine, SANEntry
from app.services.chain_builder import build_chain, assemble_chain_pem
from app.services.serial_allocator import allocate_serial_safe
from app.services.audit import audit_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/k8s", tags=["Kubernetes cert-manager"])
crypto = CryptoEngine()

# In-memory config (persisted via settings/env in production)
_issuer_config: dict = {
    "ca_id": "",
    "profile": "server",
    "validity_days": 90,
    "allowed_namespaces": [],  # empty = all
    "allowed_dns_patterns": [],  # empty = all
    "enabled": True,
}


# --- Request/Response Models ---

class SignRequest(BaseModel):
    """cert-manager webhook sign request."""
    csr: str  # base64-encoded PEM or DER CSR
    namespace: str = ""
    resource_name: str = ""
    duration: str = ""  # e.g. "2160h" (90 days)
    is_ca: bool = False


class SignResponse(BaseModel):
    """cert-manager webhook sign response."""
    certificate: str  # base64-encoded PEM cert
    ca: str  # base64-encoded PEM CA chain


class IssuerConfig(BaseModel):
    ca_id: str = ""
    profile: str = "server"
    validity_days: int = 90
    allowed_namespaces: list[str] = []
    allowed_dns_patterns: list[str] = []
    enabled: bool = True


# --- Helper Functions ---

def _parse_duration(duration: str) -> int | None:
    """Parse Go-style duration (e.g. '2160h') to days."""
    if not duration:
        return None
    duration = duration.strip()
    if duration.endswith("h"):
        try:
            hours = int(duration[:-1])
            return max(1, hours // 24)
        except ValueError:
            return None
    if duration.endswith("d"):
        try:
            return int(duration[:-1])
        except ValueError:
            return None
    return None


async def _resolve_signing_ca(db: AsyncSession) -> CertificateAuthority:
    """Find the CA configured for K8s issuer."""
    ca_id = _issuer_config.get("ca_id", "")
    if ca_id:
        ca = await db.get(CertificateAuthority, ca_id)
        if ca and ca.key_blob:
            return ca

    # Fallback: first CA with a key
    result = await db.execute(
        select(CertificateAuthority)
        .where(CertificateAuthority.key_blob.isnot(None))
        .order_by(CertificateAuthority.is_root.asc())
        .limit(1)
    )
    ca = result.scalar_one_or_none()
    if not ca:
        raise HTTPException(status_code=503, detail="No CA available for signing")
    return ca


def _check_namespace(namespace: str) -> None:
    """Validate namespace is allowed."""
    allowed = _issuer_config.get("allowed_namespaces", [])
    if allowed and namespace and namespace not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Namespace '{namespace}' not allowed by issuer policy",
        )


def _check_dns_patterns(dns_names: list[str]) -> None:
    """Validate DNS names against allowed patterns."""
    patterns = _issuer_config.get("allowed_dns_patterns", [])
    if not patterns:
        return
    for dns in dns_names:
        if not any(_dns_matches(dns, p) for p in patterns):
            raise HTTPException(
                status_code=403,
                detail=f"DNS name '{dns}' not allowed by issuer policy",
            )


def _dns_matches(name: str, pattern: str) -> bool:
    """Simple wildcard match: *.example.com matches foo.example.com."""
    if pattern.startswith("*."):
        suffix = pattern[1:]  # .example.com
        return name.endswith(suffix) or name == pattern[2:]
    return name == pattern


# --- Endpoints ---

@router.get("/health")
async def k8s_issuer_health() -> dict:
    """Health check for K8s liveness/readiness probes. No auth required."""
    return {"status": "ok", "enabled": _issuer_config.get("enabled", True)}


@router.post("/sign")
async def k8s_sign(
    body: SignRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> SignResponse:
    """Sign a CSR submitted by cert-manager.

    This is the core webhook endpoint. cert-manager sends a base64-encoded CSR,
    and we return the signed certificate + CA chain.
    """
    if not _issuer_config.get("enabled", True):
        raise HTTPException(status_code=503, detail="K8s issuer is disabled")

    # Decode CSR
    try:
        csr_bytes = base64.b64decode(body.csr)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 CSR")

    # Parse CSR (PEM or DER)
    from cryptography import x509 as cx509
    try:
        if b"-----BEGIN" in csr_bytes:
            csr = cx509.load_pem_x509_csr(csr_bytes)
        else:
            csr = cx509.load_der_x509_csr(csr_bytes)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse CSR: {e}")

    if not csr.is_signature_valid:
        raise HTTPException(status_code=400, detail="CSR signature invalid")

    # Policy checks
    _check_namespace(body.namespace)

    # Extract subject and SANs
    from cryptography.x509.oid import NameOID
    cn_attrs = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    cn = cn_attrs[0].value if cn_attrs else "k8s-cert"

    san_list: list[SANEntry] = []
    dns_names: list[str] = []
    try:
        san_ext = csr.extensions.get_extension_for_class(cx509.SubjectAlternativeName)
        for dns in san_ext.value.get_values_for_type(cx509.DNSName):
            san_list.append(SANEntry(type="dns", value=dns))
            dns_names.append(dns)
        for ip in san_ext.value.get_values_for_type(cx509.IPAddress):
            san_list.append(SANEntry(type="ip", value=str(ip)))
        for uri in san_ext.value.get_values_for_type(cx509.UniformResourceIdentifier):
            san_list.append(SANEntry(type="uri", value=uri))
    except cx509.ExtensionNotFound:
        pass

    _check_dns_patterns(dns_names)

    # Determine validity
    validity_days = _parse_duration(body.duration) or _issuer_config.get("validity_days", 90)
    validity_days = min(validity_days, settings.MAX_CERT_DAYS)

    # Sign
    ca = await _resolve_signing_ca(db)
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography.x509 import (
        CertificateBuilder, BasicConstraints, KeyUsage,
        SubjectKeyIdentifier, AuthorityKeyIdentifier,
        ExtendedKeyUsage, SubjectAlternativeName,
        CRLDistributionPoints, DistributionPoint,
        AuthorityInformationAccess, AccessDescription, AuthorityInformationAccessOID,
    )
    from cryptography.x509.oid import ExtendedKeyUsageOID
    from cryptography.hazmat.primitives import hashes

    ca_key_pem = crypto.decrypt_key_blob(ca.key_blob, settings.CERT_MASTER_KEY)
    ca_key = load_pem_private_key(ca_key_pem, password=None)
    ca_cert = cx509.load_pem_x509_certificate(ca.cert_pem.encode())

    serial_int = await allocate_serial_safe(ca.id, db)
    profile = _issuer_config.get("profile", "server")

    now = datetime.now(timezone.utc)
    builder = (
        CertificateBuilder()
        .subject_name(cx509.Name([cx509.NameAttribute(cx509.oid.NameOID.COMMON_NAME, cn)]))
        .issuer_name(ca_cert.subject)
        .public_key(csr.public_key())
        .serial_number(serial_int)
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=validity_days))
        .add_extension(BasicConstraints(ca=body.is_ca, path_length=None if not body.is_ca else 0), critical=True)
        .add_extension(
            KeyUsage(
                key_cert_sign=body.is_ca, crl_sign=body.is_ca,
                digital_signature=True, key_encipherment=(profile == "server"),
                content_commitment=False, data_encipherment=False,
                key_agreement=False, encipher_only=False, decipher_only=False,
            ), critical=True,
        )
        .add_extension(SubjectKeyIdentifier.from_public_key(csr.public_key()), critical=False)
        .add_extension(AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()), critical=False)
    )

    # EKU
    if profile == "server":
        builder = builder.add_extension(ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
    elif profile == "client":
        builder = builder.add_extension(ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
    else:
        builder = builder.add_extension(
            ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)

    # SANs
    if san_list:
        san_names = crypto._build_san_extension(san_list)
        builder = builder.add_extension(SubjectAlternativeName(san_names), critical=False)

    # CDP/AIA
    if settings.PKI_BASE_URL:
        cdp_url = f"{settings.PKI_BASE_URL}/api/v1/pki/crl/{ca.id}"
        dp = DistributionPoint(full_name=[cx509.UniformResourceIdentifier(cdp_url)],
                               relative_name=None, crl_issuer=None, reasons=None)
        builder = builder.add_extension(CRLDistributionPoints([dp]), critical=False)
        aia = AuthorityInformationAccess([
            AccessDescription(AuthorityInformationAccessOID.OCSP,
                              cx509.UniformResourceIdentifier(f"{settings.PKI_BASE_URL}/api/v1/pki/ocsp")),
            AccessDescription(AuthorityInformationAccessOID.CA_ISSUERS,
                              cx509.UniformResourceIdentifier(f"{settings.PKI_BASE_URL}/api/v1/pki/ca/{ca.id}/cert")),
        ])
        builder = builder.add_extension(aia, critical=False)

    digest = crypto._get_digest("sha256", ca_key)
    cert_obj = builder.sign(ca_key, digest)

    cert_pem_bytes = crypto.export_cert_pem(cert_obj)
    serial_hex = format(cert_obj.serial_number, "x")

    # Build chain
    ca_chain = await build_chain(ca.id, db)
    chain_pem = assemble_chain_pem(cert_pem_bytes.decode(), ca_chain, mode="full")

    # Store certificate record
    placeholder_key = crypto.encrypt_key_blob(b"K8S_CERT_MANAGER_NO_KEY", settings.CERT_MASTER_KEY)
    certificate = Certificate(
        serial=serial_hex,
        profile=profile,
        subject_json=json.dumps({"cn": cn}),
        san_json=json.dumps([{"type": s.type, "value": s.value} for s in san_list]),
        key_algo=_detect_key_algo(csr.public_key()),
        key_size=_detect_key_size(csr.public_key()),
        cert_pem=cert_pem_bytes.decode(),
        key_blob=placeholder_key,
        chain_pem=chain_pem,
        signing_ca_id=ca.id,
        status="valid",
        expires_at=cert_obj.not_valid_after_utc,
        tags=json.dumps(["k8s-cert-manager", body.namespace or "default"]),
    )
    db.add(certificate)

    await audit_event(
        db=db, event_type="K8S_CERT_ISSUED", severity="INFO", request=request,
        subject_type="cert", subject_id=serial_hex,
        description=f"K8s cert-manager: {cn} ns={body.namespace} resource={body.resource_name}",
    )
    await db.commit()

    # Return cert + CA chain
    ca_pem = "\n".join(ca_chain) if ca_chain else ca.cert_pem
    if not ca_chain:
        ca_pem = ca.cert_pem

    return SignResponse(
        certificate=base64.b64encode(cert_pem_bytes).decode(),
        ca=base64.b64encode(ca_pem.encode()).decode(),
    )


@router.get("/config")
async def get_issuer_config(
    auth: AuthContext = Depends(require_permission("ca:read")),
) -> IssuerConfig:
    """Get current K8s issuer configuration."""
    return IssuerConfig(**_issuer_config)


@router.put("/config")
async def update_issuer_config(
    body: IssuerConfig,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("ca:create")),
) -> IssuerConfig:
    """Update K8s issuer configuration. Admin only."""
    # Validate CA exists if specified
    if body.ca_id:
        ca = await db.get(CertificateAuthority, body.ca_id)
        if not ca:
            raise HTTPException(status_code=404, detail="CA not found")

    _issuer_config.update(body.model_dump())

    await audit_event(
        db=db, event_type="K8S_CONFIG_UPDATED", severity="INFO", request=request,
        subject_type="config", subject_id="k8s-issuer",
        description=f"K8s issuer config updated: ca={body.ca_id} profile={body.profile}",
    )
    await db.commit()

    return IssuerConfig(**_issuer_config)


@router.get("/manifests")
async def get_manifests(
    auth: AuthContext = Depends(require_permission("ca:read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Generate example Kubernetes manifests for cert-manager integration."""
    base_url = settings.BASE_URL.rstrip("/")
    ca_id = _issuer_config.get("ca_id", "<your-ca-id>")

    # ClusterIssuer manifest
    cluster_issuer = f"""apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: internal-ca
spec:
  # Option 1: Use the webhook issuer (this endpoint)
  # Requires the cert-manager-webhook-certmanager deployment
  webhook:
    url: {base_url}/api/v1/k8s/sign
    caBundle: <base64-ca-cert>
    headers:
      X-API-Key: <your-api-key>
"""

    # Certificate resource example
    certificate_example = """apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: my-app-tls
  namespace: default
spec:
  secretName: my-app-tls-secret
  issuerRef:
    name: internal-ca
    kind: ClusterIssuer
  commonName: my-app.default.svc.cluster.local
  dnsNames:
    - my-app.default.svc.cluster.local
    - my-app.default.svc
    - my-app
  duration: 2160h    # 90 days
  renewBefore: 360h  # 15 days before expiry
"""

    # Webhook deployment
    webhook_deployment = f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: cert-manager-webhook-certmanager
  namespace: cert-manager
spec:
  replicas: 1
  selector:
    matchLabels:
      app: cert-manager-webhook-certmanager
  template:
    metadata:
      labels:
        app: cert-manager-webhook-certmanager
    spec:
      containers:
        - name: webhook
          image: ghcr.io/your-org/cert-manager-webhook-certmanager:latest
          env:
            - name: CERTMANAGER_URL
              value: "{base_url}"
            - name: CERTMANAGER_API_KEY
              valueFrom:
                secretKeyRef:
                  name: certmanager-credentials
                  key: api-key
            - name: CERTMANAGER_CA_ID
              value: "{ca_id}"
          ports:
            - containerPort: 8443
              name: https
          livenessProbe:
            httpGet:
              path: /health
              port: 8443
              scheme: HTTPS
          readinessProbe:
            httpGet:
              path: /health
              port: 8443
              scheme: HTTPS
---
apiVersion: v1
kind: Service
metadata:
  name: cert-manager-webhook-certmanager
  namespace: cert-manager
spec:
  ports:
    - port: 443
      targetPort: 8443
  selector:
    app: cert-manager-webhook-certmanager
"""

    # Secret for API key
    secret_manifest = """apiVersion: v1
kind: Secret
metadata:
  name: certmanager-credentials
  namespace: cert-manager
type: Opaque
stringData:
  api-key: <your-api-key>
"""

    # ACME alternative (if available)
    acme_issuer = f"""# Alternative: Use ACME protocol (if ACME endpoint is enabled)
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: internal-ca-acme
spec:
  acme:
    server: {base_url}/.well-known/acme-directory
    privateKeySecretRef:
      name: internal-ca-account-key
    solvers:
      - http01:
          ingress:
            class: nginx
"""

    # Helm values
    helm_values = f"""# values.yaml for cert-manager-webhook-certmanager Helm chart
replicaCount: 2

certmanager:
  url: "{base_url}"
  caId: "{ca_id}"
  profile: "server"
  validityDays: 90

credentials:
  apiKeySecretName: certmanager-credentials
  apiKeySecretKey: api-key

resources:
  requests:
    cpu: 50m
    memory: 64Mi
  limits:
    cpu: 200m
    memory: 128Mi

podDisruptionBudget:
  enabled: true
  minAvailable: 1
"""

    return {
        "cluster_issuer": cluster_issuer,
        "certificate_example": certificate_example,
        "webhook_deployment": webhook_deployment,
        "secret": secret_manifest,
        "acme_issuer": acme_issuer,
        "helm_values": helm_values,
    }


# --- Utility ---

def _detect_key_algo(pub_key) -> str:
    from cryptography.hazmat.primitives.asymmetric import rsa, ec, ed25519
    if isinstance(pub_key, rsa.RSAPublicKey):
        return "RSA"
    elif isinstance(pub_key, ec.EllipticCurvePublicKey):
        return "ECDSA"
    elif isinstance(pub_key, ed25519.Ed25519PublicKey):
        return "Ed25519"
    return "Unknown"


def _detect_key_size(pub_key) -> int:
    from cryptography.hazmat.primitives.asymmetric import rsa, ec
    if isinstance(pub_key, rsa.RSAPublicKey):
        return pub_key.key_size
    elif isinstance(pub_key, ec.EllipticCurvePublicKey):
        return pub_key.curve.key_size
    return 256
