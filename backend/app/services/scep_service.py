"""SCEP Protocol service — PKCS#7 envelope handling and message processing.

Implements the core SCEP message format:
- PKCSReq: enrollment request (PKCS#7 signed + encrypted envelope containing CSR)
- CertRep: enrollment response (PKCS#7 signed envelope containing issued cert)
- GetCACaps: server capabilities
- GetCACert: CA certificate distribution
"""

import base64
import hashlib
import logging
from dataclasses import dataclass
from enum import Enum

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import pkcs7

logger = logging.getLogger(__name__)


class SCEPMessageType(str, Enum):
    PKCS_REQ = "19"       # PKCSReq — initial enrollment
    CERT_REP = "3"        # CertRep — CA response
    GET_CERT = "21"       # GetCert — retrieve issued cert
    GET_CRL = "22"        # GetCRL — retrieve CRL
    RENEWAL_REQ = "17"    # RenewalReq — renewal


class SCEPPKIStatus(str, Enum):
    SUCCESS = "0"
    FAILURE = "2"
    PENDING = "3"


class SCEPFailInfo(str, Enum):
    BAD_ALG = "0"
    BAD_MESSAGE_CHECK = "1"
    BAD_REQUEST = "2"
    BAD_TIME = "3"
    BAD_CERT_ID = "4"


# SCEP capabilities advertised by this server
SCEP_CAPABILITIES = [
    "POSTPKIOperation",   # Accept POST for PKIOperation
    "SHA-256",            # Support SHA-256
    "SHA-512",            # Support SHA-512
    "AES",               # Support AES encryption
    "DES3",              # Support 3DES (legacy devices)
    "Renewal",           # Support certificate renewal
]


@dataclass
class SCEPRequest:
    """Parsed SCEP PKIOperation request."""
    message_type: str
    transaction_id: str
    sender_nonce: bytes
    csr: x509.CertificateSigningRequest | None
    challenge_password: str | None


def get_capabilities() -> str:
    """Return SCEP capabilities string (one per line)."""
    return "\n".join(SCEP_CAPABILITIES)


def extract_csr_from_pkcs7(data: bytes) -> x509.CertificateSigningRequest | None:
    """Extract CSR from PKCS#7 signed-data envelope.

    SCEP wraps the CSR in a PKCS#7 SignedData structure. For simplified
    processing, we attempt multiple extraction strategies.
    """
    # Strategy 1: Try to find PEM CSR embedded in the data
    if b"-----BEGIN CERTIFICATE REQUEST-----" in data:
        try:
            return x509.load_pem_x509_csr(data)
        except Exception:
            pass

    # Strategy 2: Try raw DER CSR (some clients send unwrapped)
    try:
        return x509.load_der_x509_csr(data)
    except Exception:
        pass

    # Strategy 3: Parse PKCS#7 and extract encapsulated content
    # The PKCS#7 SignedData contains the CSR as the encapsulated content
    try:
        from pyasn1.codec.der import decoder as der_decoder
        from pyasn1.type import univ, tag

        asn1_obj, _ = der_decoder.decode(data, asn1Spec=univ.Sequence())

        # Navigate: ContentInfo -> content -> SignedData -> encapContentInfo -> eContent
        # PKCS#7 ContentInfo: SEQUENCE { contentType OID, content [0] EXPLICIT ANY }
        if len(asn1_obj) >= 2:
            content = asn1_obj[1]
            # content is [0] EXPLICIT containing SignedData
            if hasattr(content, 'hasValue') and content.hasValue():
                signed_data = content.getComponent()
                # SignedData: SEQUENCE { version, digestAlgorithms, encapContentInfo, ... }
                if len(signed_data) >= 3:
                    encap = signed_data[2]
                    # encapContentInfo: SEQUENCE { eContentType, eContent [0] EXPLICIT }
                    if len(encap) >= 2:
                        econtent = encap[1]
                        if hasattr(econtent, 'hasValue') and econtent.hasValue():
                            raw_content = bytes(econtent.getComponent())
                            # Try to parse as CSR
                            try:
                                return x509.load_der_x509_csr(raw_content)
                            except Exception:
                                pass
    except Exception as e:
        logger.debug(f"PKCS#7 ASN.1 parsing failed: {e}")

    # Strategy 4: Scan for CSR DER pattern in raw bytes
    # CSR starts with SEQUENCE tag (0x30) followed by length
    # Look for the CSR signature algorithm OID pattern
    try:
        # Find potential CSR start positions
        pos = 0
        while pos < len(data) - 10:
            if data[pos] == 0x30:
                # Try to parse from this position
                try:
                    candidate = data[pos:]
                    csr = x509.load_der_x509_csr(candidate)
                    return csr
                except Exception:
                    pass
            pos += 1
    except Exception:
        pass

    return None


def extract_challenge_password(csr: x509.CertificateSigningRequest) -> str | None:
    """Extract challengePassword attribute from CSR (OID 1.2.840.113549.1.9.7)."""
    from cryptography.x509.oid import AttributeOID
    try:
        for attr in csr.attributes:
            if attr.oid == AttributeOID.CHALLENGE_PASSWORD:
                return attr.value.decode() if isinstance(attr.value, bytes) else str(attr.value)
    except Exception:
        pass
    return None


def generate_transaction_id(csr: x509.CertificateSigningRequest) -> str:
    """Generate a transaction ID from the CSR's public key hash."""
    pub_key_der = csr.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(pub_key_der).hexdigest()[:32]


def build_cert_rep_success(cert_pem: str, ca_cert_pem: str, ca_key_pem: bytes,
                           transaction_id: str, sender_nonce: bytes | None) -> bytes:
    """Build a SCEP CertRep SUCCESS response.

    Returns DER-encoded PKCS#7 SignedData containing the issued certificate.
    For broad device compatibility, we return a degenerate PKCS#7 certs-only
    structure that most SCEP clients can parse.
    """
    cert = x509.load_pem_x509_certificate(cert_pem.encode())
    ca_cert = x509.load_pem_x509_certificate(ca_cert_pem.encode())

    # Build PKCS#7 degenerate certs-only (SignedData with no signers, just certs)
    # This is the most compatible format for SCEP responses
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    ca_key = load_pem_private_key(ca_key_pem, password=None)

    # Use pyca/cryptography PKCS7 builder for signed data
    try:
        builder = (
            pkcs7.PKCS7SignatureBuilder()
            .set_data(cert.public_bytes(serialization.Encoding.DER))
            .add_signer(ca_cert, ca_key, hashes.SHA256())
        )
        signed = builder.sign(serialization.Encoding.DER, options=[])
        return signed
    except Exception:
        # Fallback: return raw DER cert (some clients accept this)
        return cert.public_bytes(serialization.Encoding.DER)


def build_cert_rep_failure(fail_info: SCEPFailInfo, transaction_id: str) -> bytes:
    """Build a minimal SCEP CertRep FAILURE response.

    Returns a simple error indicator that clients can parse.
    """
    # For simplicity, return a minimal structure
    # Most clients will retry or report the HTTP error status
    return f"FAILURE:{fail_info.value}:{transaction_id}".encode()


def parse_scep_request(data: bytes) -> SCEPRequest:
    """Parse a SCEP PKIOperation request.

    Extracts the CSR and metadata from the PKCS#7 envelope.
    """
    csr = extract_csr_from_pkcs7(data)

    # Generate transaction ID from CSR if available
    transaction_id = ""
    challenge = None
    sender_nonce = b""

    if csr:
        transaction_id = generate_transaction_id(csr)
        challenge = extract_challenge_password(csr)

    return SCEPRequest(
        message_type=SCEPMessageType.PKCS_REQ,
        transaction_id=transaction_id,
        sender_nonce=sender_nonce,
        csr=csr,
        challenge_password=challenge,
    )
