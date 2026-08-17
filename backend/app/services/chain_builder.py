"""Full certificate chain building and validation.

Walks the CA hierarchy from signing CA up to root, assembling the complete
chain for multi-level CA hierarchies (Root → Intermediate L1 → L2 → Leaf).
"""

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec, rsa, padding, ed25519
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ca import CertificateAuthority


async def build_chain(ca_id: str, db: AsyncSession) -> list[str]:
    """Walk CA hierarchy from ca_id up to root, returning list of PEM certs (signing CA first, root last)."""
    chain: list[str] = []
    visited: set[str] = set()
    current_id: str | None = ca_id

    while current_id:
        if current_id in visited:
            break  # Loop detection
        visited.add(current_id)

        ca = await db.get(CertificateAuthority, current_id)
        if not ca:
            break

        chain.append(ca.cert_pem)
        current_id = ca.parent_ca_id

    return chain


def assemble_chain_pem(leaf_pem: str, ca_chain: list[str], mode: str = "full") -> str:
    """Assemble chain PEM based on mode.

    Modes:
        full - leaf + all intermediates + root
        no_root - leaf + intermediates (no root)
        intermediates_only - intermediates only (no leaf, no root)
        leaf_only - leaf cert only
    """
    if mode == "leaf_only":
        return leaf_pem
    if mode == "intermediates_only":
        if len(ca_chain) <= 1:
            return ""
        return "".join(ca_chain[:-1])
    if mode == "no_root":
        if len(ca_chain) <= 1:
            return leaf_pem + "".join(ca_chain)
        return leaf_pem + "".join(ca_chain[:-1])
    # full (default)
    return leaf_pem + "".join(ca_chain)


def get_root_pem(ca_chain: list[str]) -> str:
    """Return the root CA PEM (last in chain)."""
    return ca_chain[-1] if ca_chain else ""


def validate_chain(chain_pems: list[str]) -> dict:
    """Validate a chain is cryptographically correct.

    chain_pems: ordered list [leaf_or_lowest_ca, ..., root]
    Returns dict with 'valid' bool and 'errors' list.
    """
    errors: list[str] = []
    certs: list[x509.Certificate] = []

    for i, pem in enumerate(chain_pems):
        try:
            certs.append(x509.load_pem_x509_certificate(pem.encode()))
        except Exception as e:
            errors.append(f"Certificate {i}: failed to parse — {e}")
            return {"valid": False, "errors": errors}

    for i in range(len(certs) - 1):
        child = certs[i]
        parent = certs[i + 1]

        # Issuer/subject match
        if child.issuer != parent.subject:
            errors.append(
                f"Certificate {i}: issuer '{child.issuer.rfc4514_string()}' "
                f"does not match parent subject '{parent.subject.rfc4514_string()}'"
            )
            continue

        # Signature verification
        parent_pub = parent.public_key()
        try:
            if isinstance(parent_pub, rsa.RSAPublicKey):
                parent_pub.verify(
                    child.signature,
                    child.tbs_certificate_bytes,
                    padding.PKCS1v15(),
                    child.signature_hash_algorithm,
                )
            elif isinstance(parent_pub, ec.EllipticCurvePublicKey):
                parent_pub.verify(
                    child.signature,
                    child.tbs_certificate_bytes,
                    ec.ECDSA(child.signature_hash_algorithm),
                )
            elif isinstance(parent_pub, ed25519.Ed25519PublicKey):
                parent_pub.verify(child.signature, child.tbs_certificate_bytes)
            else:
                errors.append(f"Certificate {i}: unsupported key type for verification")
        except Exception as e:
            errors.append(f"Certificate {i}: signature verification failed — {e}")

    # Root should be self-signed
    if certs:
        root = certs[-1]
        if root.issuer != root.subject:
            errors.append("Root certificate is not self-signed (issuer != subject)")

    return {"valid": len(errors) == 0, "errors": errors}
