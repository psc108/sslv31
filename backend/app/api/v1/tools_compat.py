"""Certificate compatibility checker — validates a certificate against service-specific requirements."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.core.security import require_api_key

router = APIRouter(prefix="/api/v1/tools", tags=["Tools"])


SERVICE_REQUIREMENTS = {
    "nginx": {
        "label": "Nginx",
        "pem_required": True,
        "chain_in_cert_file": True,
        "key_unencrypted": True,
        "supported_key_algos": ["RSA", "ECDSA", "Ed25519"],
        "min_key_size_rsa": 2048,
        "san_required": True,
        "eku_required": ["serverAuth"],
        "max_validity_days": None,
        "notes": "Nginx expects the full chain in the certificate file (leaf first). Key must be unencrypted.",
    },
    "mysql": {
        "label": "MySQL / MariaDB",
        "pem_required": True,
        "chain_in_cert_file": False,
        "key_unencrypted": True,
        "supported_key_algos": ["RSA", "ECDSA"],
        "min_key_size_rsa": 2048,
        "san_required": True,
        "eku_required": ["serverAuth"],
        "max_validity_days": None,
        "notes": "MySQL ssl_cert should be the leaf certificate only (not the full chain). Ed25519 is not supported.",
    },
    "rabbitmq": {
        "label": "RabbitMQ",
        "pem_required": True,
        "chain_in_cert_file": False,
        "key_unencrypted": True,
        "supported_key_algos": ["RSA", "ECDSA"],
        "min_key_size_rsa": 2048,
        "san_required": True,
        "eku_required": ["serverAuth"],
        "max_validity_days": None,
        "notes": "RabbitMQ uses separate certfile, keyfile, cacertfile. Ed25519 not supported by Erlang/OTP < 25.",
    },
    "java": {
        "label": "Java / Spring Boot",
        "pem_required": False,
        "chain_in_cert_file": True,
        "key_unencrypted": False,
        "supported_key_algos": ["RSA", "ECDSA", "Ed25519"],
        "min_key_size_rsa": 2048,
        "san_required": True,
        "eku_required": ["serverAuth"],
        "max_validity_days": None,
        "notes": "Java requires SANs (JSSE ignores CN for hostname verification). Ed25519 requires Java 15+. Prefer PKCS12 over JKS.",
    },
    "keycloak": {
        "label": "Keycloak",
        "pem_required": False,
        "chain_in_cert_file": True,
        "key_unencrypted": False,
        "supported_key_algos": ["RSA", "ECDSA"],
        "min_key_size_rsa": 2048,
        "san_required": True,
        "eku_required": ["serverAuth"],
        "max_validity_days": None,
        "notes": "Keycloak (Quarkus) supports PEM files directly or JKS/PKCS12 keystores. Ed25519 not supported.",
    },
    "keystone": {
        "label": "OpenStack Keystone",
        "pem_required": True,
        "chain_in_cert_file": True,
        "key_unencrypted": True,
        "supported_key_algos": ["RSA", "ECDSA"],
        "min_key_size_rsa": 2048,
        "san_required": True,
        "eku_required": ["serverAuth"],
        "max_validity_days": None,
        "notes": "Keystone runs behind Apache mod_wsgi. Requires PEM format, key unencrypted. Install CA system-wide for inter-service trust.",
    },
}


@router.post("/compatibility-check")
async def compatibility_check(
    cert_file: UploadFile = File(...),
    key_file: UploadFile | None = File(None),
    service: str = Form(...),
    expected_hostname: str = Form(""),
    _: str = Depends(require_api_key),
) -> dict:
    """Check if a certificate is compatible with a specific service's requirements."""
    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa, ec, ed25519
    from cryptography.x509.oid import ExtendedKeyUsageOID
    from datetime import datetime, timezone

    if service not in SERVICE_REQUIREMENTS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown service: {service}. Valid: {', '.join(SERVICE_REQUIREMENTS.keys())}",
        )

    reqs = SERVICE_REQUIREMENTS[service]
    checks = []

    # Read cert
    cert_bytes = await cert_file.read()
    if not cert_bytes:
        raise HTTPException(status_code=422, detail="Empty certificate file")

    # Parse certificate
    is_pem = b"-----BEGIN CERTIFICATE-----" in cert_bytes
    try:
        if is_pem:
            cert_obj = cx509.load_pem_x509_certificate(cert_bytes)
        else:
            cert_obj = cx509.load_der_x509_certificate(cert_bytes)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse certificate: {e}")

    # --- Check 1: Format ---
    if reqs["pem_required"]:
        if is_pem:
            checks.append({"check": "PEM format", "status": "pass", "detail": "Certificate is in PEM format"})
        else:
            checks.append({"check": "PEM format", "status": "fail", "detail": f"{reqs['label']} requires PEM format. This certificate is DER. Convert using the Format Converter tool."})
    else:
        checks.append({"check": "Format", "status": "pass", "detail": f"{reqs['label']} supports both PEM and binary formats (JKS/PKCS12)"})

    # --- Check 2: Key algorithm ---
    pub_key = cert_obj.public_key()
    if isinstance(pub_key, rsa.RSAPublicKey):
        key_algo, key_size = "RSA", pub_key.key_size
    elif isinstance(pub_key, ec.EllipticCurvePublicKey):
        key_algo, key_size = "ECDSA", pub_key.key_size
    elif isinstance(pub_key, ed25519.Ed25519PublicKey):
        key_algo, key_size = "Ed25519", 256
    else:
        key_algo, key_size = "Unknown", 0

    if key_algo in reqs["supported_key_algos"]:
        checks.append({"check": "Key algorithm", "status": "pass", "detail": f"{key_algo} {key_size}-bit is supported by {reqs['label']}"})
    else:
        checks.append({"check": "Key algorithm", "status": "fail", "detail": f"{key_algo} is NOT supported by {reqs['label']}. Supported: {', '.join(reqs['supported_key_algos'])}"})

    # --- Check 3: Key size ---
    if key_algo == "RSA":
        min_size = reqs["min_key_size_rsa"]
        if key_size >= min_size:
            checks.append({"check": "Key size", "status": "pass", "detail": f"RSA {key_size}-bit meets minimum ({min_size})"})
        else:
            checks.append({"check": "Key size", "status": "fail", "detail": f"RSA {key_size}-bit is below minimum {min_size}-bit"})
    else:
        checks.append({"check": "Key size", "status": "pass", "detail": f"{key_algo} {key_size}-bit — acceptable"})

    # --- Check 4: SAN present ---
    sans = []
    try:
        san_ext = cert_obj.extensions.get_extension_for_class(cx509.SubjectAlternativeName)
        for dns in san_ext.value.get_values_for_type(cx509.DNSName):
            sans.append({"type": "dns", "value": dns})
        for ip in san_ext.value.get_values_for_type(cx509.IPAddress):
            sans.append({"type": "ip", "value": str(ip)})
    except cx509.ExtensionNotFound:
        pass

    if reqs["san_required"]:
        if sans:
            checks.append({"check": "SAN present", "status": "pass", "detail": f"{len(sans)} SAN entries found"})
        else:
            checks.append({"check": "SAN present", "status": "fail", "detail": f"{reqs['label']} requires Subject Alternative Names. This cert has none — hostname verification will fail."})

    # --- Check 5: Hostname match ---
    if expected_hostname and sans:
        match = any(
            s["value"] == expected_hostname or
            (s["value"].startswith("*.") and expected_hostname.endswith(s["value"][1:]))
            for s in sans if s["type"] == "dns"
        )
        ip_match = any(s["value"] == expected_hostname for s in sans if s["type"] == "ip")
        if match or ip_match:
            checks.append({"check": "Hostname match", "status": "pass", "detail": f"'{expected_hostname}' matches a SAN entry"})
        else:
            san_values = [s["value"] for s in sans]
            checks.append({"check": "Hostname match", "status": "fail", "detail": f"'{expected_hostname}' does NOT match any SAN: {', '.join(san_values)}"})
    elif expected_hostname and not sans:
        checks.append({"check": "Hostname match", "status": "fail", "detail": "No SANs present — cannot match any hostname"})

    # --- Check 6: Extended Key Usage ---
    eku_oids = {
        "serverAuth": ExtendedKeyUsageOID.SERVER_AUTH,
        "clientAuth": ExtendedKeyUsageOID.CLIENT_AUTH,
    }
    try:
        eku_ext = cert_obj.extensions.get_extension_for_class(cx509.ExtendedKeyUsage)
        cert_ekus = list(eku_ext.value)
        for required_eku in reqs["eku_required"]:
            oid = eku_oids.get(required_eku)
            if oid and oid in cert_ekus:
                checks.append({"check": f"EKU: {required_eku}", "status": "pass", "detail": f"Extended Key Usage includes {required_eku}"})
            elif oid:
                checks.append({"check": f"EKU: {required_eku}", "status": "warn", "detail": f"Extended Key Usage does not include {required_eku}. Some strict clients may reject this."})
    except cx509.ExtensionNotFound:
        checks.append({"check": "Extended Key Usage", "status": "warn", "detail": "No EKU extension present. Most services accept this but it's not best practice."})

    # --- Check 7: Not expired ---
    now = datetime.now(timezone.utc)
    days_remaining = (cert_obj.not_valid_after_utc - now).days
    if days_remaining > 30:
        checks.append({"check": "Validity", "status": "pass", "detail": f"Certificate valid for {days_remaining} more days"})
    elif days_remaining > 0:
        checks.append({"check": "Validity", "status": "warn", "detail": f"Certificate expires in {days_remaining} days — renew soon"})
    else:
        checks.append({"check": "Validity", "status": "fail", "detail": f"Certificate EXPIRED {abs(days_remaining)} days ago"})

    # --- Check 8: Not a CA cert ---
    try:
        bc = cert_obj.extensions.get_extension_for_class(cx509.BasicConstraints)
        if bc.value.ca:
            checks.append({"check": "Not a CA", "status": "fail", "detail": "This is a CA certificate (CA:TRUE). Server certificates must have CA:FALSE."})
        else:
            checks.append({"check": "Not a CA", "status": "pass", "detail": "Certificate is a leaf certificate (CA:FALSE)"})
    except cx509.ExtensionNotFound:
        checks.append({"check": "Not a CA", "status": "pass", "detail": "No BasicConstraints — treated as leaf certificate"})

    # --- Check 9: Chain in cert file ---
    if reqs["chain_in_cert_file"] and is_pem:
        cert_count = cert_bytes.count(b"-----BEGIN CERTIFICATE-----")
        if cert_count > 1:
            checks.append({"check": "Chain included", "status": "pass", "detail": f"File contains {cert_count} certificates (full chain)"})
        else:
            checks.append({"check": "Chain included", "status": "warn", "detail": f"{reqs['label']} works best with the full chain in the cert file. This file has only 1 certificate. Use the chain.pem file from the bundle."})
    elif not reqs["chain_in_cert_file"] and is_pem:
        cert_count = cert_bytes.count(b"-----BEGIN CERTIFICATE-----")
        if cert_count == 1:
            checks.append({"check": "Leaf only", "status": "pass", "detail": f"{reqs['label']} expects the leaf certificate only (not chain). ✓"})
        else:
            checks.append({"check": "Leaf only", "status": "warn", "detail": f"{reqs['label']} expects only the leaf certificate in ssl_cert, but this file has {cert_count} certificates. Use cert.pem (not chain.pem)."})

    # --- Check 10: Key unencrypted (if key provided) ---
    key_bytes = None
    if key_file:
        key_bytes = await key_file.read()
        if key_bytes:
            if reqs["key_unencrypted"]:
                if b"ENCRYPTED" in key_bytes:
                    checks.append({"check": "Key unencrypted", "status": "fail", "detail": f"{reqs['label']} requires an unencrypted private key. This key is encrypted. Remove passphrase: openssl rsa -in key.pem -out key-nopass.pem"})
                else:
                    checks.append({"check": "Key unencrypted", "status": "pass", "detail": "Private key is unencrypted — compatible"})
            else:
                checks.append({"check": "Key encryption", "status": "pass", "detail": f"{reqs['label']} supports both encrypted and unencrypted keys"})

            # Verify key matches cert
            from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_der_private_key, Encoding, PublicFormat
            try:
                if b"-----BEGIN" in key_bytes:
                    key = load_pem_private_key(key_bytes, password=None)
                else:
                    key = load_der_private_key(key_bytes, password=None)
                cert_pub = cert_obj.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
                key_pub = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
                if cert_pub == key_pub:
                    checks.append({"check": "Key matches cert", "status": "pass", "detail": "Private key matches certificate public key"})
                else:
                    checks.append({"check": "Key matches cert", "status": "fail", "detail": "Private key does NOT match this certificate"})
            except Exception as e:
                checks.append({"check": "Key matches cert", "status": "warn", "detail": f"Could not verify key match: {e}"})

            # Key integrity check
            try:
                if b"-----BEGIN" in key_bytes:
                    loaded_key = load_pem_private_key(key_bytes, password=None)
                else:
                    loaded_key = load_der_private_key(key_bytes, password=None)
                # Attempt a test signature to verify key is usable
                from cryptography.hazmat.primitives.asymmetric import padding as asym_padding, utils as asym_utils
                test_data = b"integrity-check"
                if isinstance(loaded_key, rsa.RSAPrivateKey):
                    loaded_key.sign(test_data, asym_padding.PKCS1v15(), hashes.SHA256())
                elif isinstance(loaded_key, ec.EllipticCurvePrivateKey):
                    loaded_key.sign(test_data, ec.ECDSA(hashes.SHA256()))
                elif isinstance(loaded_key, ed25519.Ed25519PrivateKey):
                    loaded_key.sign(test_data)
                checks.append({"check": "Key integrity", "status": "pass", "detail": "Private key is mathematically valid and can produce signatures"})
            except Exception as e:
                checks.append({"check": "Key integrity", "status": "fail", "detail": f"Private key failed integrity check (corrupted or truncated): {e}"})

    # =============================================
    # ADVANCED CHECKS (cryptographic & quality)
    # =============================================

    chain_certs_in_file = []  # populated below if chain present

    # --- Check 11: Signature algorithm strength ---
    sig_algo = cert_obj.signature_algorithm_oid._name
    sig_hash = cert_obj.signature_hash_algorithm
    if sig_hash:
        hash_name = sig_hash.name.lower()
        if "sha1" in hash_name or "md5" in hash_name:
            checks.append({"check": "Signature algorithm", "status": "fail", "detail": f"Certificate uses {sig_algo} which is cryptographically weak. All modern services reject SHA-1/MD5 signed certificates."})
        elif "sha256" in hash_name or "sha384" in hash_name or "sha512" in hash_name:
            checks.append({"check": "Signature algorithm", "status": "pass", "detail": f"Signature algorithm: {sig_algo} — strong"})
        else:
            checks.append({"check": "Signature algorithm", "status": "warn", "detail": f"Signature algorithm: {sig_algo} — verify this is acceptable for your environment"})
    else:
        # Ed25519 has no separate hash
        checks.append({"check": "Signature algorithm", "status": "pass", "detail": f"Signature algorithm: {sig_algo}"})

    # --- Check 12: Not yet valid (future notBefore) ---
    if cert_obj.not_valid_before_utc > now:
        days_until_valid = (cert_obj.not_valid_before_utc - now).days
        checks.append({"check": "Not yet valid", "status": "fail", "detail": f"Certificate is not yet valid — notBefore is {days_until_valid} days in the future. Check system clock or certificate generation date."})
    else:
        checks.append({"check": "Not yet valid", "status": "pass", "detail": "Certificate notBefore date is in the past — currently valid"})

    # --- Check 13: Reasonable validity period ---
    total_validity_days = (cert_obj.not_valid_after_utc - cert_obj.not_valid_before_utc).days
    if total_validity_days > 398:
        checks.append({"check": "Validity period", "status": "warn", "detail": f"Certificate validity is {total_validity_days} days. Certificates >398 days are distrusted by browsers for public CAs. Acceptable for internal/private CA use."})
    elif total_validity_days < 30:
        checks.append({"check": "Validity period", "status": "warn", "detail": f"Certificate validity is only {total_validity_days} days — very short. Ensure renewal automation is in place."})
    else:
        checks.append({"check": "Validity period", "status": "pass", "detail": f"Validity period: {total_validity_days} days — reasonable"})

    # --- Check 14: CN also in SAN list ---
    cn_attrs = cert_obj.subject.get_attributes_for_oid(cx509.oid.NameOID.COMMON_NAME)
    if cn_attrs and sans:
        cn_value = cn_attrs[0].value
        cn_in_san = any(s["value"] == cn_value for s in sans)
        if cn_in_san:
            checks.append({"check": "CN in SAN", "status": "pass", "detail": f"CN '{cn_value}' is also listed in SANs — best practice"})
        else:
            checks.append({"check": "CN in SAN", "status": "warn", "detail": f"CN '{cn_value}' is NOT in the SAN list. Modern clients (Java, Chrome) ignore CN and only check SANs. Add it as a DNS SAN."})

    # --- Check 15: Wildcard validation ---
    for s in sans:
        if s["type"] == "dns" and "*" in s["value"]:
            if s["value"].count("*") > 1:
                checks.append({"check": "Wildcard depth", "status": "fail", "detail": f"SAN '{s['value']}' has multiple wildcards — invalid per RFC 6125"})
                break
            if not s["value"].startswith("*."):
                checks.append({"check": "Wildcard depth", "status": "fail", "detail": f"SAN '{s['value']}' has wildcard not at leftmost position — invalid"})
                break
            parts = s["value"].split(".")
            if len(parts) < 3:
                checks.append({"check": "Wildcard depth", "status": "warn", "detail": f"SAN '{s['value']}' is a top-level wildcard — may be rejected by some clients"})
                break
    else:
        # Only add pass if we have wildcards and none failed
        if any("*" in s["value"] for s in sans if s["type"] == "dns"):
            checks.append({"check": "Wildcard depth", "status": "pass", "detail": "Wildcard SANs are correctly formatted (single level)"})

    # --- Check 16: Key usage consistency for key type ---
    try:
        ku_ext = cert_obj.extensions.get_extension_for_class(cx509.KeyUsage)
        ku = ku_ext.value
        if key_algo == "RSA":
            if not ku.key_encipherment and not ku.digital_signature:
                checks.append({"check": "Key usage consistency", "status": "fail", "detail": "RSA server cert should have keyEncipherment or digitalSignature in Key Usage"})
            else:
                checks.append({"check": "Key usage consistency", "status": "pass", "detail": f"Key Usage appropriate for {key_algo} server certificate"})
        elif key_algo == "ECDSA":
            if not ku.digital_signature:
                checks.append({"check": "Key usage consistency", "status": "fail", "detail": "ECDSA server cert must have digitalSignature in Key Usage"})
            elif ku.key_encipherment:
                checks.append({"check": "Key usage consistency", "status": "warn", "detail": "ECDSA cert has keyEncipherment set — this is unusual (typically only for RSA). May cause issues with strict implementations."})
            else:
                checks.append({"check": "Key usage consistency", "status": "pass", "detail": "Key Usage appropriate for ECDSA server certificate"})
        else:
            checks.append({"check": "Key usage consistency", "status": "pass", "detail": f"Key Usage present for {key_algo}"})
    except cx509.ExtensionNotFound:
        checks.append({"check": "Key usage consistency", "status": "warn", "detail": "No Key Usage extension — some strict services may reject this"})

    # --- Check 17: Chain certificate validity (if chain present in file) ---
    if is_pem:
        chain_certs_in_file = []
        remaining = cert_bytes
        # Skip first cert (the leaf)
        first_end = remaining.find(b"-----END CERTIFICATE-----")
        if first_end >= 0:
            remaining = remaining[first_end + len(b"-----END CERTIFICATE-----"):]
        while b"-----BEGIN CERTIFICATE-----" in remaining:
            try:
                chain_cert = cx509.load_pem_x509_certificate(remaining)
                chain_certs_in_file.append(chain_cert)
                end_idx = remaining.find(b"-----END CERTIFICATE-----")
                remaining = remaining[end_idx + len(b"-----END CERTIFICATE-----"):]
            except Exception:
                break

        if chain_certs_in_file:
            all_chain_valid = True
            for i, cc in enumerate(chain_certs_in_file):
                cc_days = (cc.not_valid_after_utc - now).days
                cc_cn = ""
                cc_cn_attrs = cc.subject.get_attributes_for_oid(cx509.oid.NameOID.COMMON_NAME)
                if cc_cn_attrs:
                    cc_cn = cc_cn_attrs[0].value
                if cc_days <= 0:
                    checks.append({"check": f"Chain cert #{i+1} validity", "status": "fail", "detail": f"Chain certificate '{cc_cn}' is EXPIRED ({abs(cc_days)} days ago). The entire chain is invalid."})
                    all_chain_valid = False
                elif cc_days <= 30:
                    checks.append({"check": f"Chain cert #{i+1} validity", "status": "warn", "detail": f"Chain certificate '{cc_cn}' expires in {cc_days} days"})
            if all_chain_valid:
                checks.append({"check": "Chain validity", "status": "pass", "detail": f"All {len(chain_certs_in_file)} chain certificate(s) are within validity period"})

            # Chain order check
            prev_cert = cert_obj
            chain_order_ok = True
            for i, cc in enumerate(chain_certs_in_file):
                if prev_cert.issuer != cc.subject:
                    checks.append({"check": "Chain order", "status": "fail", "detail": f"Chain is out of order: cert #{i} issuer does not match cert #{i+1} subject. Expected issuer '{prev_cert.issuer.rfc4514_string()}' but got '{cc.subject.rfc4514_string()}'"})
                    chain_order_ok = False
                    break
                prev_cert = cc
            if chain_order_ok and chain_certs_in_file:
                checks.append({"check": "Chain order", "status": "pass", "detail": "Chain is in correct order (leaf → intermediate → root)"})

            # Root is self-signed check
            last_cert = chain_certs_in_file[-1]
            if last_cert.issuer == last_cert.subject:
                checks.append({"check": "Chain terminates at root", "status": "pass", "detail": "Chain terminates at a self-signed root certificate"})
            else:
                checks.append({"check": "Chain terminates at root", "status": "warn", "detail": "Chain does not terminate at a self-signed root. Some clients require the full chain to root."})

            # Cryptographic chain verification
            from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
            all_sigs_valid = True
            verify_chain = [cert_obj] + chain_certs_in_file
            for i in range(len(verify_chain) - 1):
                child = verify_chain[i]
                parent = verify_chain[i + 1]
                try:
                    parent_pub = parent.public_key()
                    if isinstance(parent_pub, rsa.RSAPublicKey):
                        parent_pub.verify(child.signature, child.tbs_certificate_bytes, asym_padding.PKCS1v15(), child.signature_hash_algorithm)
                    elif isinstance(parent_pub, ec.EllipticCurvePublicKey):
                        parent_pub.verify(child.signature, child.tbs_certificate_bytes, ec.ECDSA(child.signature_hash_algorithm))
                    elif isinstance(parent_pub, ed25519.Ed25519PublicKey):
                        parent_pub.verify(child.signature, child.tbs_certificate_bytes)
                except Exception:
                    all_sigs_valid = False
                    break
            if all_sigs_valid and len(verify_chain) > 1:
                checks.append({"check": "Chain signatures", "status": "pass", "detail": "All signatures in the chain are cryptographically valid"})
            elif not all_sigs_valid:
                checks.append({"check": "Chain signatures", "status": "fail", "detail": "Chain signature verification FAILED — a certificate was not signed by its claimed issuer"})

    # --- Check 18: RSA key size for CA certs in chain ---
    if is_pem and chain_certs_in_file:
        for i, cc in enumerate(chain_certs_in_file):
            cc_pub = cc.public_key()
            if isinstance(cc_pub, rsa.RSAPublicKey) and cc_pub.key_size < 4096:
                cc_cn_attrs = cc.subject.get_attributes_for_oid(cx509.oid.NameOID.COMMON_NAME)
                cc_cn = cc_cn_attrs[0].value if cc_cn_attrs else f"Chain cert #{i+1}"
                if cc_pub.key_size < 2048:
                    checks.append({"check": f"CA key size ({cc_cn})", "status": "fail", "detail": f"CA certificate '{cc_cn}' has RSA {cc_pub.key_size}-bit key — below minimum 2048"})
                elif cc_pub.key_size < 4096:
                    checks.append({"check": f"CA key size ({cc_cn})", "status": "warn", "detail": f"CA certificate '{cc_cn}' has RSA {cc_pub.key_size}-bit key — 4096-bit recommended for CA certificates"})

    # Summary
    pass_count = sum(1 for c in checks if c["status"] == "pass")
    warn_count = sum(1 for c in checks if c["status"] == "warn")
    fail_count = sum(1 for c in checks if c["status"] == "fail")

    if fail_count == 0 and warn_count == 0:
        summary = f"✓ Certificate is fully compatible with {reqs['label']}"
        overall = "pass"
    elif fail_count == 0:
        summary = f"Certificate is compatible with {reqs['label']} with {warn_count} warning(s)"
        overall = "warn"
    else:
        summary = f"Certificate has {fail_count} issue(s) that will prevent use with {reqs['label']}"
        overall = "fail"

    return {
        "service": service,
        "service_label": reqs["label"],
        "overall": overall,
        "summary": summary,
        "notes": reqs["notes"],
        "checks": checks,
        "pass_count": pass_count,
        "warn_count": warn_count,
        "fail_count": fail_count,
        "certificate": {
            "cn": cert_obj.subject.get_attributes_for_oid(cx509.oid.NameOID.COMMON_NAME)[0].value if cert_obj.subject.get_attributes_for_oid(cx509.oid.NameOID.COMMON_NAME) else "Unknown",
            "key_algo": key_algo,
            "key_size": key_size,
            "san_count": len(sans),
            "days_remaining": days_remaining,
        },
    }
