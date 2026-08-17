"""Certificate tools endpoints — decode, remote check, chain verify, key match, convert, P12 build."""

import json
import ssl
import socket
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from app.core.security import require_api_key
from app.services.crypto_engine import CryptoEngine

router = APIRouter(prefix="/api/v1/tools", tags=["Tools"])
crypto = CryptoEngine()


@router.post("/decode")
async def decode_certificate(
    cert_pem: str = Form(None),
    cert_file: UploadFile | None = File(None),
    _: str = Depends(require_api_key),
) -> dict:
    """Decode any PEM or DER certificate and return its details."""
    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives import hashes, serialization

    # Get cert bytes from form field or file upload
    if cert_file:
        cert_bytes = await cert_file.read()
    elif cert_pem:
        cert_bytes = cert_pem.encode()
    else:
        raise HTTPException(status_code=422, detail="Provide cert_pem or cert_file")

    # Parse
    try:
        if b"-----BEGIN CERTIFICATE-----" in cert_bytes:
            cert_obj = cx509.load_pem_x509_certificate(cert_bytes)
        elif b"-----BEGIN CERTIFICATE REQUEST-----" in cert_bytes or b"-----BEGIN NEW CERTIFICATE REQUEST-----" in cert_bytes:
            raise HTTPException(status_code=422, detail="This is a CSR (Certificate Signing Request), not a certificate. Use the CSR Manager to inspect it.")
        else:
            # Try DER certificate first
            try:
                cert_obj = cx509.load_der_x509_certificate(cert_bytes)
            except Exception as der_err:
                # Try PKCS#12 — extract the leaf cert
                try:
                    from cryptography.hazmat.primitives.serialization import pkcs12
                    p12 = pkcs12.load_pkcs12(cert_bytes, password=None)
                    if p12.cert is None:
                        raise ValueError("No certificate found in PKCS#12")
                    cert_obj = p12.cert.certificate
                except HTTPException:
                    raise
                except Exception:
                    # Try as DER CSR
                    try:
                        cx509.load_der_x509_csr(cert_bytes)
                        raise HTTPException(status_code=422, detail="This is a CSR (Certificate Signing Request), not a certificate. Use the CSR Manager to inspect it.")
                    except HTTPException:
                        raise
                    except Exception:
                        raise HTTPException(status_code=422, detail=f"Failed to parse certificate: {der_err}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse certificate: {e}")

    # Subject
    subject = {}
    for attr in cert_obj.subject:
        subject[attr.oid._name] = attr.value

    # Issuer
    issuer = {}
    for attr in cert_obj.issuer:
        issuer[attr.oid._name] = attr.value

    # SANs
    sans = []
    try:
        san_ext = cert_obj.extensions.get_extension_for_class(cx509.SubjectAlternativeName)
        for dns in san_ext.value.get_values_for_type(cx509.DNSName):
            sans.append({"type": "dns", "value": dns})
        for ip in san_ext.value.get_values_for_type(cx509.IPAddress):
            sans.append({"type": "ip", "value": str(ip)})
        for email in san_ext.value.get_values_for_type(cx509.RFC822Name):
            sans.append({"type": "email", "value": email})
        for uri in san_ext.value.get_values_for_type(cx509.UniformResourceIdentifier):
            sans.append({"type": "uri", "value": uri})
    except cx509.ExtensionNotFound:
        pass

    # Extensions
    extensions = []
    for ext in cert_obj.extensions:
        extensions.append({
            "oid": ext.oid.dotted_string,
            "name": ext.oid._name,
            "critical": ext.critical,
            "value": str(ext.value),
        })

    # Key info
    pub_key = cert_obj.public_key()
    from cryptography.hazmat.primitives.asymmetric import rsa, ec, ed25519
    if isinstance(pub_key, rsa.RSAPublicKey):
        key_algo, key_size = "RSA", pub_key.key_size
    elif isinstance(pub_key, ec.EllipticCurvePublicKey):
        key_algo, key_size = "ECDSA", pub_key.key_size
    elif isinstance(pub_key, ed25519.Ed25519PublicKey):
        key_algo, key_size = "Ed25519", 256
    else:
        key_algo, key_size = "Unknown", 0

    now = datetime.now(timezone.utc)
    days_remaining = (cert_obj.not_valid_after_utc - now).days

    return {
        "subject": subject,
        "subject_rfc4514": cert_obj.subject.rfc4514_string(),
        "issuer": issuer,
        "issuer_rfc4514": cert_obj.issuer.rfc4514_string(),
        "serial": format(cert_obj.serial_number, "x"),
        "san": sans,
        "not_valid_before": cert_obj.not_valid_before_utc.isoformat(),
        "not_valid_after": cert_obj.not_valid_after_utc.isoformat(),
        "days_remaining": days_remaining,
        "is_expired": days_remaining <= 0,
        "key_algo": key_algo,
        "key_size": key_size,
        "signature_algorithm": cert_obj.signature_algorithm_oid._name,
        "is_ca": False,
        "extensions": extensions,
        "fingerprints": {
            "sha256": cert_obj.fingerprint(hashes.SHA256()).hex(),
            "sha1": cert_obj.fingerprint(hashes.SHA1()).hex(),
        },
    }


@router.post("/decode-csr")
async def decode_csr(
    csr_pem: str = Form(None),
    csr_file: UploadFile | None = File(None),
    _: str = Depends(require_api_key),
) -> dict:
    """Decode a PEM or DER CSR and return its details."""
    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives.asymmetric import rsa, ec, ed25519
    from cryptography.hazmat.primitives.serialization import Encoding

    if csr_file:
        csr_bytes = await csr_file.read()
    elif csr_pem:
        csr_bytes = csr_pem.encode()
    else:
        raise HTTPException(status_code=422, detail="Provide csr_pem or csr_file")

    try:
        if b"-----BEGIN" in csr_bytes:
            csr_obj = cx509.load_pem_x509_csr(csr_bytes)
        else:
            csr_obj = cx509.load_der_x509_csr(csr_bytes)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse CSR: {e}")

    # Subject
    subject = {attr.oid._name: attr.value for attr in csr_obj.subject}

    # SANs (from extensions in the CSR)
    sans = []
    try:
        san_ext = csr_obj.extensions.get_extension_for_class(cx509.SubjectAlternativeName)
        for dns in san_ext.value.get_values_for_type(cx509.DNSName):
            sans.append({"type": "dns", "value": dns})
        for ip in san_ext.value.get_values_for_type(cx509.IPAddress):
            sans.append({"type": "ip", "value": str(ip)})
        for email in san_ext.value.get_values_for_type(cx509.RFC822Name):
            sans.append({"type": "email", "value": email})
        for uri in san_ext.value.get_values_for_type(cx509.UniformResourceIdentifier):
            sans.append({"type": "uri", "value": uri})
    except cx509.ExtensionNotFound:
        pass

    # Key info
    pub_key = csr_obj.public_key()
    if isinstance(pub_key, rsa.RSAPublicKey):
        key_algo, key_size = "RSA", pub_key.key_size
    elif isinstance(pub_key, ec.EllipticCurvePublicKey):
        key_algo, key_size = "ECDSA", pub_key.key_size
    elif isinstance(pub_key, ed25519.Ed25519PublicKey):
        key_algo, key_size = "Ed25519", 256
    else:
        key_algo, key_size = "Unknown", 0

    # Checks
    checks = []
    checks.append({
        "check": "Signature valid",
        "pass": csr_obj.is_signature_valid,
        "detail": "CSR self-signature is cryptographically valid" if csr_obj.is_signature_valid else "Signature verification failed — CSR may be corrupt or tampered",
    })
    checks.append({
        "check": "CN present",
        "pass": bool(subject.get("commonName")),
        "detail": "CN = " + subject.get("commonName", "(missing)"),
    })
    checks.append({
        "check": "Key size adequate",
        "pass": key_size >= 2048,
        "detail": key_algo + " " + str(key_size) + "-bit" + (" \u2713" if key_size >= 2048 else " — minimum 2048-bit RSA recommended"),
    })
    checks.append({
        "check": "SANs present",
        "pass": len(sans) > 0,
        "detail": str(len(sans)) + " SAN(s) found" if sans else "No SANs — required for Server TLS (RFC 2818); browsers will reject CN-only certs",
    })

    return {
        "subject": subject,
        "subject_rfc4514": csr_obj.subject.rfc4514_string(),
        "san": sans,
        "key_algo": key_algo,
        "key_size": key_size,
        "signature_valid": csr_obj.is_signature_valid,
        "checks": checks,
        "pem": csr_obj.public_bytes(Encoding.PEM).decode(),
    }


def _fetch_remote_cert(hostname: str, port: int, ctx: ssl.SSLContext) -> bytes | None:
    """Blocking function to fetch a remote TLS certificate."""
    with socket.create_connection((hostname, port), timeout=10) as sock:
        with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
            return ssock.getpeercert(binary_form=True)


# This endpoint's connection is made from the backend container's own network
# namespace, not the browser's — so "localhost"/127.0.0.1/::1 here means the
# certmanager container itself, never wherever Docker published a port on the
# real host (e.g. a Build Manager environment's RabbitMQ management UI on
# host port 15671). host.docker.internal is Docker Desktop's (and, with
# extra_hosts: host-gateway, plain Linux Docker's) route back to that real
# host, so a localhost check that can't connect directly is retried through
# it before giving up — falls straight through to the original error where
# it isn't set up.
_LOCALHOST_ALIASES = {"localhost", "127.0.0.1", "::1"}
_DOCKER_HOST_GATEWAY = "host.docker.internal"


@router.post("/remote-check")
async def remote_certificate_check(
    hostname: str = Form(...),
    port: int = Form(443),
    _: str = Depends(require_api_key),
) -> dict:
    """Connect to a remote server and retrieve its TLS certificate chain."""
    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.serialization import Encoding

    resolved_via = None
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        # Run blocking socket call in thread pool to avoid blocking async loop
        import asyncio
        loop = asyncio.get_event_loop()
        try:
            der_cert = await loop.run_in_executor(None, _fetch_remote_cert, hostname, port, ctx)
        except (socket.timeout, ConnectionRefusedError, OSError) as direct_err:
            if hostname.lower() not in _LOCALHOST_ALIASES:
                raise
            try:
                der_cert = await loop.run_in_executor(None, _fetch_remote_cert, _DOCKER_HOST_GATEWAY, port, ctx)
            except Exception:
                raise direct_err  # neither route worked — report the original, more familiar failure
            resolved_via = _DOCKER_HOST_GATEWAY

        if not der_cert:
            raise HTTPException(status_code=422, detail="No certificate received from server")

        cert_obj = cx509.load_der_x509_certificate(der_cert)

    except socket.timeout:
        raise HTTPException(status_code=422, detail=f"Connection to {hostname}:{port} timed out")
    except socket.gaierror:
        raise HTTPException(status_code=422, detail=f"DNS resolution failed for {hostname}")
    except ConnectionRefusedError:
        raise HTTPException(status_code=422, detail=f"Connection refused: {hostname}:{port}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Connection failed: {e}")

    # Decode
    subject = {}
    for attr in cert_obj.subject:
        subject[attr.oid._name] = attr.value

    issuer = {}
    for attr in cert_obj.issuer:
        issuer[attr.oid._name] = attr.value

    sans = []
    try:
        san_ext = cert_obj.extensions.get_extension_for_class(cx509.SubjectAlternativeName)
        for dns in san_ext.value.get_values_for_type(cx509.DNSName):
            sans.append({"type": "dns", "value": dns})
        for ip in san_ext.value.get_values_for_type(cx509.IPAddress):
            sans.append({"type": "ip", "value": str(ip)})
    except cx509.ExtensionNotFound:
        pass

    now = datetime.now(timezone.utc)
    days_remaining = (cert_obj.not_valid_after_utc - now).days

    # Check if hostname matches SANs
    hostname_match = any(
        s["value"] == hostname or
        (s["value"].startswith("*.") and hostname.endswith(s["value"][1:]))
        for s in sans if s["type"] == "dns"
    )

    return {
        "hostname": hostname,
        "port": port,
        "subject": subject,
        "issuer": issuer,
        "serial": format(cert_obj.serial_number, "x"),
        "san": sans,
        "not_valid_before": cert_obj.not_valid_before_utc.isoformat(),
        "not_valid_after": cert_obj.not_valid_after_utc.isoformat(),
        "days_remaining": days_remaining,
        "is_expired": days_remaining <= 0,
        "hostname_match": hostname_match,
        "signature_algorithm": cert_obj.signature_algorithm_oid._name,
        "fingerprints": {
            "sha256": cert_obj.fingerprint(hashes.SHA256()).hex(),
            "sha1": cert_obj.fingerprint(hashes.SHA1()).hex(),
        },
        "pem": cert_obj.public_bytes(Encoding.PEM).decode(),
        "resolved_via": resolved_via,
    }


@router.post("/verify-chain")
async def verify_certificate_chain(
    cert_pem: str = Form(...),
    chain_pem: str = Form(...),
    _: str = Depends(require_api_key),
) -> dict:
    """Verify a certificate chain is complete and valid."""
    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives.asymmetric import padding, ec, ed25519, rsa
    from cryptography.hazmat.primitives import hashes

    def _get_verify_args(pub_key, child_cert):
        """Return the correct verify() arguments based on key type."""
        if isinstance(pub_key, rsa.RSAPublicKey):
            return (padding.PKCS1v15(), child_cert.signature_hash_algorithm)
        elif isinstance(pub_key, ec.EllipticCurvePublicKey):
            return (ec.ECDSA(child_cert.signature_hash_algorithm),)
        elif isinstance(pub_key, ed25519.Ed25519PublicKey):
            return ()
        return ()

    results = []

    try:
        leaf = cx509.load_pem_x509_certificate(cert_pem.encode())
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid leaf certificate: {e}")

    # Parse chain certs
    chain_certs = []
    pem_data = chain_pem.encode()
    while b"-----BEGIN CERTIFICATE-----" in pem_data:
        try:
            cert = cx509.load_pem_x509_certificate(pem_data)
            chain_certs.append(cert)
            end = pem_data.find(b"-----END CERTIFICATE-----") + len(b"-----END CERTIFICATE-----")
            pem_data = pem_data[end:]
        except Exception:
            break

    if not chain_certs:
        raise HTTPException(status_code=422, detail="No valid certificates found in chain")

    # Verify: leaf signed by first chain cert, each chain cert signed by next
    all_certs = [leaf] + chain_certs
    valid = True

    for i in range(len(all_certs) - 1):
        child = all_certs[i]
        parent = all_certs[i + 1]

        child_name = child.subject.get_attributes_for_oid(cx509.oid.NameOID.COMMON_NAME)
        parent_name = parent.subject.get_attributes_for_oid(cx509.oid.NameOID.COMMON_NAME)

        # Check issuer matches parent subject
        issuer_match = child.issuer == parent.subject

        # Check signature
        sig_valid = False
        try:
            parent.public_key().verify(
                child.signature,
                child.tbs_certificate_bytes,
                *_get_verify_args(parent.public_key(), child),
            )
            sig_valid = True
        except Exception as e:
            pass

        step_valid = issuer_match and sig_valid
        if not step_valid:
            valid = False

        results.append({
            "child": child_name[0].value if child_name else "Unknown",
            "parent": parent_name[0].value if parent_name else "Unknown",
            "valid": step_valid,
            "issuer_match": issuer_match,
            "signature_valid": sig_valid,
        })

    # Check if root is self-signed
    root = all_certs[-1]
    root_name = root.subject.get_attributes_for_oid(cx509.oid.NameOID.COMMON_NAME)
    is_self_signed = root.issuer == root.subject

    return {
        "valid": valid,
        "chain_length": len(all_certs),
        "results": results,
        "root_is_self_signed": is_self_signed,
        "root_cn": root_name[0].value if root_name else "Unknown",
    }


@router.post("/key-match")
async def check_key_certificate_match(
    cert_file: UploadFile = File(...),
    key_file: UploadFile = File(...),
    key_password: str | None = Form(None),
    _: str = Depends(require_api_key),
) -> dict:
    """Check if a private key matches a certificate (same public key)."""
    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives.serialization import (
        load_pem_private_key, load_der_private_key, Encoding, PublicFormat,
    )

    cert_bytes = await cert_file.read()
    key_bytes = await key_file.read()

    # Parse cert
    try:
        if b"-----BEGIN CERTIFICATE-----" in cert_bytes:
            cert_obj = cx509.load_pem_x509_certificate(cert_bytes)
        else:
            cert_obj = cx509.load_der_x509_certificate(cert_bytes)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid certificate: {e}")

    # Parse key
    pwd = key_password.encode() if key_password else None
    try:
        if b"-----BEGIN" in key_bytes:
            key = load_pem_private_key(key_bytes, password=pwd)
        else:
            key = load_der_private_key(key_bytes, password=pwd)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid key: {e}")

    # Compare public keys
    cert_pub = cert_obj.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    key_pub = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)

    match = cert_pub == key_pub

    # Get cert CN for context
    cn_attrs = cert_obj.subject.get_attributes_for_oid(cx509.oid.NameOID.COMMON_NAME)
    cn = cn_attrs[0].value if cn_attrs else "Unknown"

    return {
        "match": match,
        "certificate_cn": cn,
        "certificate_serial": format(cert_obj.serial_number, "x"),
        "message": "Key and certificate match ✓" if match else "Key does NOT match certificate ✗",
    }


@router.post("/convert")
async def convert_certificate_format(
    cert_file: UploadFile = File(...),
    output_format: str = Form(...),  # pem, der
    _: str = Depends(require_api_key),
) -> Response:
    """Convert a certificate between PEM and DER formats."""
    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives.serialization import Encoding

    cert_bytes = await cert_file.read()

    # Detect input format and parse
    try:
        if b"-----BEGIN CERTIFICATE-----" in cert_bytes:
            cert_obj = cx509.load_pem_x509_certificate(cert_bytes)
            input_format = "pem"
        else:
            cert_obj = cx509.load_der_x509_certificate(cert_bytes)
            input_format = "der"
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid certificate: {e}")

    # Convert
    if output_format == "pem":
        output = cert_obj.public_bytes(Encoding.PEM)
        media_type = "application/x-pem-file"
        ext = "pem"
    elif output_format == "der":
        output = cert_obj.public_bytes(Encoding.DER)
        media_type = "application/x-x509-ca-cert"
        ext = "der"
    else:
        raise HTTPException(status_code=422, detail="output_format must be 'pem' or 'der'")

    cn_attrs = cert_obj.subject.get_attributes_for_oid(cx509.oid.NameOID.COMMON_NAME)
    cn = (cn_attrs[0].value if cn_attrs else "certificate").replace(" ", "_")

    return Response(
        content=output,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{cn}.{ext}"'},
    )


@router.post("/build-p12")
async def build_pkcs12(
    cert_file: UploadFile = File(...),
    key_file: UploadFile = File(...),
    chain_file: UploadFile | None = File(None),
    key_password: str | None = Form(None),
    p12_password: str = Form(""),
    friendly_name: str = Form("certificate"),
    _: str = Depends(require_api_key),
) -> Response:
    """Build a PKCS#12 (.p12) file from separate cert + key + optional chain files."""
    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives.serialization import (
        load_pem_private_key, load_der_private_key, pkcs12, Encoding,
        BestAvailableEncryption, NoEncryption,
    )

    cert_bytes = await cert_file.read()
    key_bytes = await key_file.read()
    chain_bytes = await chain_file.read() if chain_file else None

    # Parse cert
    try:
        if b"-----BEGIN CERTIFICATE-----" in cert_bytes:
            cert_obj = cx509.load_pem_x509_certificate(cert_bytes)
        else:
            cert_obj = cx509.load_der_x509_certificate(cert_bytes)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid certificate: {e}")

    # Parse key
    pwd = key_password.encode() if key_password else None
    try:
        if b"-----BEGIN" in key_bytes:
            key = load_pem_private_key(key_bytes, password=pwd)
        else:
            key = load_der_private_key(key_bytes, password=pwd)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid key: {e}")

    # Parse chain
    chain_certs = None
    if chain_bytes:
        chain_certs = []
        remaining = chain_bytes
        while b"-----BEGIN CERTIFICATE-----" in remaining:
            try:
                c = cx509.load_pem_x509_certificate(remaining)
                chain_certs.append(c)
                end = remaining.find(b"-----END CERTIFICATE-----") + len(b"-----END CERTIFICATE-----")
                remaining = remaining[end:]
            except Exception:
                break

    # Build P12
    enc = BestAvailableEncryption(p12_password.encode()) if p12_password else NoEncryption()
    p12_bytes = pkcs12.serialize_key_and_certificates(
        friendly_name.encode(),
        key,
        cert_obj,
        chain_certs,
        enc,
    )

    cn_attrs = cert_obj.subject.get_attributes_for_oid(cx509.oid.NameOID.COMMON_NAME)
    cn = (cn_attrs[0].value if cn_attrs else "certificate").replace(" ", "_")

    return Response(
        content=p12_bytes,
        media_type="application/x-pkcs12",
        headers={"Content-Disposition": f'attachment; filename="{cn}.p12"'},
    )
