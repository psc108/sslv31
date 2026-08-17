"""OCSP Signing Delegation — RFC 6960 §4.2.2.2.

Generates short-lived OCSP signing certificates per CA so the CA private key
is not used for high-frequency OCSP response signing.
"""

import logging
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from app.core.config import settings
from app.services.crypto_engine import CryptoEngine

logger = logging.getLogger(__name__)

OCSP_CERT_VALIDITY_DAYS = 30
OCSP_CERT_RENEW_BEFORE_DAYS = 7

crypto = CryptoEngine()


def generate_ocsp_signing_cert(
    ca_cert: x509.Certificate,
    ca_key,
) -> tuple[x509.Certificate, bytes, bytes]:
    """Generate a dedicated OCSP signing certificate signed by the CA.

    Returns: (ocsp_cert, ocsp_key_pem, ocsp_cert_pem)
    """
    # Use ECDSA P-256 for OCSP signing (fast, small signatures)
    ocsp_key = ec.generate_private_key(ec.SECP256R1())

    now = datetime.now(timezone.utc)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, f"OCSP Responder - {ca_cert.subject.rfc4514_string()}"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SSL Certificate Manager"),
    ])

    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(ocsp_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=OCSP_CERT_VALIDITY_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.OCSP_SIGNING]),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=False,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        # id-pkix-ocsp-nocheck: tells clients not to check revocation of this cert
        .add_extension(
            x509.OCSPNoCheck(),
            critical=False,
        )
    )

    # Sign with CA key
    from cryptography.hazmat.primitives.asymmetric import ed25519
    hash_algo = None if isinstance(ca_key, ed25519.Ed25519PrivateKey) else hashes.SHA256()
    ocsp_cert = builder.sign(ca_key, hash_algo)

    # Export
    ocsp_key_pem = ocsp_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    ocsp_cert_pem = ocsp_cert.public_bytes(serialization.Encoding.PEM)

    return ocsp_cert, ocsp_key_pem, ocsp_cert_pem


def needs_renewal(ocsp_cert_expires: datetime | None) -> bool:
    """Check if the OCSP cert needs renewal (expired or within renewal window)."""
    if not ocsp_cert_expires:
        return True
    exp = ocsp_cert_expires
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    threshold = datetime.now(timezone.utc) + timedelta(days=OCSP_CERT_RENEW_BEFORE_DAYS)
    return exp <= threshold


async def ensure_ocsp_cert(ca, db) -> None:
    """Ensure the CA has a valid OCSP signing cert. Generate/renew if needed."""
    if not needs_renewal(ca.ocsp_cert_expires):
        return

    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    ca_key_pem = crypto.decrypt_key_blob(ca.key_blob, settings.CERT_MASTER_KEY)
    ca_key = load_pem_private_key(ca_key_pem, password=None)
    ca_cert = x509.load_pem_x509_certificate(ca.cert_pem.encode())

    ocsp_cert, ocsp_key_pem, ocsp_cert_pem = generate_ocsp_signing_cert(ca_cert, ca_key)

    # Encrypt the OCSP key for storage
    ocsp_key_blob = crypto.encrypt_key_blob(ocsp_key_pem, settings.CERT_MASTER_KEY)

    ca.ocsp_cert_pem = ocsp_cert_pem.decode()
    ca.ocsp_key_blob = ocsp_key_blob
    ca.ocsp_cert_expires = ocsp_cert.not_valid_after_utc

    await db.commit()
    logger.info(f"OCSP signing cert generated for CA '{ca.cn}', expires {ca.ocsp_cert_expires.isoformat()}")


def get_ocsp_signing_materials(ca) -> tuple | None:
    """Get the OCSP signing cert and key for a CA. Returns (ocsp_cert, ocsp_key) or None."""
    if not ca.ocsp_cert_pem or not ca.ocsp_key_blob:
        return None

    # Check expiry
    if ca.ocsp_cert_expires:
        exp = ca.ocsp_cert_expires
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= datetime.now(timezone.utc):
            return None  # Expired, fall back to CA key

    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    ocsp_cert = x509.load_pem_x509_certificate(ca.ocsp_cert_pem.encode())
    ocsp_key_pem = crypto.decrypt_key_blob(ca.ocsp_key_blob, settings.CERT_MASTER_KEY)
    ocsp_key = load_pem_private_key(ocsp_key_pem, password=None)

    return ocsp_cert, ocsp_key
