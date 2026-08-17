"""OCSP Responder service — RFC 6960 compliant.

Parses DER-encoded OCSP requests, looks up certificate status,
and returns signed OCSP responses.
"""

from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes
from cryptography.x509 import ocsp, CertificateBuilder, Name, NameAttribute, BasicConstraints
from cryptography.x509.oid import NameOID

# Cached throwaway key for building mock certs (avoids key generation per request)
_PLACEHOLDER_KEY = ec.generate_private_key(ec.SECP256R1())


def parse_ocsp_request(der_data: bytes) -> ocsp.OCSPRequest:
    """Parse a DER-encoded OCSP request."""
    return ocsp.load_der_ocsp_request(der_data)


def build_successful_response(
    serial_number: int,
    ca_cert: x509.Certificate,
    ca_key: PrivateKeyTypes,
    is_revoked: bool = False,
    revocation_time: datetime | None = None,
    revocation_reason: str | None = None,
    next_update_seconds: int = 86400,
    responder_cert: x509.Certificate | None = None,
    responder_key: PrivateKeyTypes | None = None,
) -> bytes:
    """Build a signed OCSP response for a known certificate.

    If responder_cert/responder_key are provided, uses delegated OCSP signing.
    Otherwise falls back to signing with the CA key directly.
    """
    now = datetime.now(timezone.utc)

    cert_status = ocsp.OCSPCertStatus.REVOKED if is_revoked else ocsp.OCSPCertStatus.GOOD
    rev_time = revocation_time if is_revoked else None

    # Map reason string to x509.ReasonFlags
    reason_flag = None
    if is_revoked and revocation_reason:
        _reason_map = {
            "unspecified": x509.ReasonFlags.unspecified,
            "key_compromise": x509.ReasonFlags.key_compromise,
            "ca_compromise": x509.ReasonFlags.ca_compromise,
            "affiliation_changed": x509.ReasonFlags.affiliation_changed,
            "superseded": x509.ReasonFlags.superseded,
            "cessation_of_operation": x509.ReasonFlags.cessation_of_operation,
            "certificate_hold": x509.ReasonFlags.certificate_hold,
            "privilege_withdrawn": x509.ReasonFlags.privilege_withdrawn,
        }
        reason_flag = _reason_map.get(revocation_reason)

    # Determine signing identity
    signing_key = responder_key if responder_key else ca_key
    signing_cert = responder_cert if responder_cert else ca_cert

    # Build a placeholder cert with the target serial (library needs cert object)
    mock_cert = _build_serial_cert(serial_number, ca_cert.subject)

    builder = (
        ocsp.OCSPResponseBuilder()
        .add_response(
            cert=mock_cert,
            issuer=ca_cert,
            algorithm=hashes.SHA256(),
            cert_status=cert_status,
            this_update=now,
            next_update=now + timedelta(seconds=next_update_seconds),
            revocation_time=rev_time,
            revocation_reason=reason_flag,
        )
        .responder_id(ocsp.OCSPResponderEncoding.HASH, signing_cert)
    )

    # Include responder cert in response if using delegation
    if responder_cert:
        builder = builder.certificates([responder_cert])

    hash_algo = None if isinstance(signing_key, ed25519.Ed25519PrivateKey) else hashes.SHA256()
    return builder.sign(signing_key, hash_algo).public_bytes(serialization.Encoding.DER)


def build_error_response(status: ocsp.OCSPResponseStatus) -> bytes:
    """Build an unsuccessful OCSP response (malformed, unauthorized, internal error)."""
    return ocsp.OCSPResponseBuilder.build_unsuccessful(
        status
    ).public_bytes(serialization.Encoding.DER)


def _build_serial_cert(serial: int, issuer_name: Name) -> x509.Certificate:
    """Minimal cert with given serial + issuer for OCSP response builder."""
    now = datetime.now(timezone.utc)
    return (
        CertificateBuilder()
        .subject_name(Name([NameAttribute(NameOID.COMMON_NAME, "ocsp-ref")]))
        .issuer_name(issuer_name)
        .public_key(_PLACEHOLDER_KEY.public_key())
        .serial_number(serial)
        .not_valid_before(now)
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(BasicConstraints(ca=False, path_length=None), critical=False)
        .sign(_PLACEHOLDER_KEY, hashes.SHA256())
    )
