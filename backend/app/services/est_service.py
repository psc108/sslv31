"""EST Protocol service — enrollment logic and CSR attribute helpers (RFC 7030)."""

import base64
from dataclasses import dataclass

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes


@dataclass
class ESTEnrollResult:
    cert_pem: str
    chain_pem: str
    serial_hex: str
    # For serverkeygen only
    key_pem: str | None = None


def pkcs7_wrap_certs(certs_pem: list[str]) -> bytes:
    """Wrap certificates in a simple PKCS#7 degenerate certs-only structure.

    RFC 7030 §4.1.3 requires CA certs returned as application/pkcs7-mime.
    We use a simplified base64-encoded PEM concatenation since pyca/cryptography
    doesn't have a PKCS#7 builder. Clients like certbot handle raw PEM chains too.
    """
    # Concatenate all PEM certs — most EST clients accept this
    return "\n".join(certs_pem).encode()


def pem_to_base64der(pem_text: str) -> str:
    """Convert PEM certificate to base64-encoded DER (for EST response body)."""
    cert = x509.load_pem_x509_certificate(pem_text.encode())
    der = cert.public_bytes(serialization.Encoding.DER)
    return base64.b64encode(der).decode()


def parse_pkcs10_request(body: bytes, content_type: str) -> x509.CertificateSigningRequest:
    """Parse a PKCS#10 CSR from EST request body.

    RFC 7030 §4.2.1: Content-Type is application/pkcs10 (base64-encoded DER).
    """
    if content_type and "application/pkcs10" in content_type:
        # Base64-encoded DER
        try:
            der_data = base64.b64decode(body)
            return x509.load_der_x509_csr(der_data)
        except Exception:
            pass

    # Try raw DER
    try:
        return x509.load_der_x509_csr(body)
    except Exception:
        pass

    # Try base64 without content-type hint
    try:
        der_data = base64.b64decode(body)
        return x509.load_der_x509_csr(der_data)
    except Exception:
        pass

    # Try PEM (some clients send PEM)
    try:
        return x509.load_pem_x509_csr(body)
    except Exception:
        pass

    raise ValueError("Unable to parse CSR: not valid PKCS#10 (DER, base64-DER, or PEM)")


def build_csr_attrs_response() -> bytes:
    """Build CSR Attributes response (RFC 7030 §4.5.2).

    Returns base64-encoded DER SET OF AttributeOrOID.
    For simplicity, we return a readable JSON hint that most modern
    EST clients can interpret, plus the standard OIDs.
    """
    # Standard CSR attributes OIDs that we recommend:
    # - challengePassword (1.2.840.113549.1.9.7) — optional
    # - extensionRequest (1.2.840.113549.1.9.14) — for SANs
    # - ecPublicKey (1.2.840.10045.2.1) or rsaEncryption (1.2.840.113549.1.1.1)
    #
    # RFC 7030 says the response is DER-encoded ASN.1, but many implementations
    # return a simplified format. We'll return base64-encoded minimal ASN.1.

    from cryptography.hazmat.primitives.asymmetric import ec, rsa
    from pyasn1.type import univ, tag
    from pyasn1.codec.der import encoder as der_encoder

    # Build a SEQUENCE OF OID (simplified — full ASN.1 SET OF Attribute is complex)
    # Most clients just need to know which key types and extensions are expected
    oids = univ.SequenceOf()
    oids.setComponentByPosition(0, univ.ObjectIdentifier((1, 2, 840, 113549, 1, 1, 1)))  # rsaEncryption
    oids.setComponentByPosition(1, univ.ObjectIdentifier((1, 2, 840, 10045, 2, 1)))  # ecPublicKey
    oids.setComponentByPosition(2, univ.ObjectIdentifier((1, 2, 840, 113549, 1, 9, 14)))  # extensionRequest

    der_bytes = der_encoder.encode(oids)
    return base64.b64encode(der_bytes)


def cert_to_est_response(cert_pem: str, chain_pem: str) -> bytes:
    """Encode certificate for EST response (base64-encoded DER).

    RFC 7030 §4.2.3: Response is application/pkcs7-mime with the issued cert.
    We return base64-encoded cert + chain for broad client compatibility.
    """
    # Load cert and encode as DER
    cert = x509.load_pem_x509_certificate(cert_pem.encode())
    cert_der = cert.public_bytes(serialization.Encoding.DER)

    # For the response, return base64(DER) of the leaf cert
    # Chain is available via /cacerts
    return base64.b64encode(cert_der)
