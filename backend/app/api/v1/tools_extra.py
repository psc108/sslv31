"""Additional tool endpoints — chain expiry, java debug commands, openssl commands, calendar export, keystore builder."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.core.security import require_api_key

router = APIRouter(prefix="/api/v1/tools", tags=["Tools"])


# ============================================================
# Feature 3: Certificate Expiry Chain Check
# ============================================================

@router.post("/chain-expiry-check")
async def chain_expiry_check(
    chain_pem: str = Form(None),
    chain_file: UploadFile | None = File(None),
    _: str = Depends(require_api_key),
) -> dict:
    """Check every certificate in a chain for validity — catches expired intermediates."""
    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives import hashes

    if chain_file:
        data = await chain_file.read()
    elif chain_pem:
        data = chain_pem.encode()
    else:
        raise HTTPException(status_code=422, detail="Provide chain_pem or chain_file")

    if b"-----BEGIN CERTIFICATE-----" not in data:
        raise HTTPException(status_code=422, detail="No PEM certificates found in input")

    # Parse all certs from the PEM bundle
    certs = []
    remaining = data
    while b"-----BEGIN CERTIFICATE-----" in remaining:
        try:
            cert = cx509.load_pem_x509_certificate(remaining)
            certs.append(cert)
            end = remaining.find(b"-----END CERTIFICATE-----") + len(b"-----END CERTIFICATE-----")
            remaining = remaining[end:]
        except Exception:
            break

    if not certs:
        raise HTTPException(status_code=422, detail="Could not parse any certificates")

    now = datetime.now(timezone.utc)
    results = []
    overall = "pass"
    weakest_link = None
    weakest_days = None

    for i, cert in enumerate(certs):
        cn_attrs = cert.subject.get_attributes_for_oid(cx509.oid.NameOID.COMMON_NAME)
        cn = cn_attrs[0].value if cn_attrs else f"Certificate #{i+1}"
        issuer_attrs = cert.issuer.get_attributes_for_oid(cx509.oid.NameOID.COMMON_NAME)
        issuer_cn = issuer_attrs[0].value if issuer_attrs else "Unknown"

        days_remaining = (cert.not_valid_after_utc - now).days
        not_yet_valid = cert.not_valid_before_utc > now

        if days_remaining <= 0:
            status = "expired"
            overall = "fail"
        elif not_yet_valid:
            status = "not_yet_valid"
            overall = "fail"
        elif days_remaining <= 7:
            status = "critical"
            if overall != "fail":
                overall = "fail"
        elif days_remaining <= 30:
            status = "warning"
            if overall == "pass":
                overall = "warn"
        elif days_remaining <= 60:
            status = "expiring_soon"
            if overall == "pass":
                overall = "warn"
        else:
            status = "valid"

        if weakest_days is None or days_remaining < weakest_days:
            weakest_days = days_remaining
            weakest_link = cn

        is_ca = False
        try:
            bc = cert.extensions.get_extension_for_class(cx509.BasicConstraints)
            is_ca = bc.value.ca
        except cx509.ExtensionNotFound:
            pass

        results.append({
            "position": i + 1,
            "cn": cn,
            "issuer_cn": issuer_cn,
            "is_ca": is_ca,
            "type": "Root CA" if (is_ca and cert.issuer == cert.subject) else "Intermediate CA" if is_ca else "Leaf",
            "not_valid_before": cert.not_valid_before_utc.isoformat(),
            "not_valid_after": cert.not_valid_after_utc.isoformat(),
            "days_remaining": days_remaining,
            "status": status,
            "fingerprint_sha256": cert.fingerprint(hashes.SHA256()).hex(),
        })

    return {
        "overall": overall,
        "total_certs": len(certs),
        "weakest_link": weakest_link,
        "weakest_days_remaining": weakest_days,
        "certificates": results,
    }


# ============================================================
# Feature 1: Java Debug Command Generator
# ============================================================

@router.post("/java-debug-command")
async def java_debug_command(
    service: str = Form("generic"),
    hostname: str = Form("localhost"),
    port: int = Form(443),
    truststore_path: str = Form("/opt/app/ssl/truststore.p12"),
    truststore_password: str = Form("changeit"),
    truststore_type: str = Form("PKCS12"),
    keystore_path: str = Form(""),
    keystore_password: str = Form(""),
    java_version: int = Form(17),
    issue_type: str = Form("connection"),
    _: str = Depends(require_api_key),
) -> dict:
    """Generate Java debug commands and flags for TLS troubleshooting."""

    # Debug flag recommendations based on issue type
    debug_flags = {
        "connection": "ssl:handshake",
        "trust": "ssl:trustmanager",
        "hostname": "ssl:handshake:verbose",
        "client_cert": "ssl:keymanager:handshake",
        "session": "ssl:session",
        "full": "ssl",
    }

    debug_value = debug_flags.get(issue_type, "ssl:handshake")

    # Build JVM args
    jvm_args = [
        f"-Djavax.net.debug={debug_value}",
        f"-Djavax.net.ssl.trustStore={truststore_path}",
        f"-Djavax.net.ssl.trustStorePassword={truststore_password}",
        f"-Djavax.net.ssl.trustStoreType={truststore_type}",
    ]

    if keystore_path:
        jvm_args.extend([
            f"-Djavax.net.ssl.keyStore={keystore_path}",
            f"-Djavax.net.ssl.keyStorePassword={keystore_password}",
            f"-Djavax.net.ssl.keyStoreType={truststore_type}",
        ])

    if java_version >= 11:
        jvm_args.append("-Dhttps.protocols=TLSv1.2,TLSv1.3")
    else:
        jvm_args.append("-Dhttps.protocols=TLSv1.2")

    # Service-specific recommendations
    service_notes = {
        "mysql": "MySQL JDBC: Add useSSL=true&requireSSL=true&verifyServerCertificate=true to connection URL",
        "rabbitmq": "RabbitMQ: Ensure Spring property spring.rabbitmq.ssl.enabled=true and port=5671",
        "generic": "Generic HTTPS: These flags apply to any outgoing HTTPS connection from this JVM",
        "spring-boot": "Spring Boot: Add these to JAVA_OPTS or application startup script",
    }

    # Build openssl equivalent command
    openssl_cmd = f"openssl s_client -connect {hostname}:{port} -CAfile {truststore_path}"
    if keystore_path:
        openssl_cmd += f" -cert <client-cert.pem> -key <client-key.pem>"
    openssl_cmd += " -servername " + hostname

    # What to look for in output
    look_for = {
        "connection": [
            "SEARCH: 'Found trusted certificate' = trust chain OK",
            "SEARCH: 'PKIX path building failed' = CA not in truststore",
            "SEARCH: 'handshake_failure' = TLS version or cipher mismatch",
        ],
        "trust": [
            "SEARCH: 'adding as trusted cert' = shows which CAs are loaded",
            "SEARCH: 'found trust anchor' = chain validated successfully",
            "SEARCH: 'PKIX path building failed' = no valid chain to trusted root",
        ],
        "hostname": [
            "SEARCH: 'No subject alternative names matching' = cert missing SAN",
            "SEARCH: 'Certificate identity check' = shows hostname being verified",
            "SEARCH: 'HTTPS hostname wrong' = mismatch between URL and cert",
        ],
        "client_cert": [
            "SEARCH: 'found key for' = client key loaded from keystore",
            "SEARCH: 'CertificateRequest' = server is requesting client cert",
            "SEARCH: 'No key found' = keystore doesn't contain a matching key",
        ],
        "session": [
            "SEARCH: 'Session established' = TLS session created successfully",
            "SEARCH: 'Resuming session' = session ticket/cache reuse",
        ],
        "full": [
            "Full debug output — very verbose. Pipe to file: java ... 2>&1 | tee ssl-debug.log",
        ],
    }

    # Build the full command
    full_command = "java \\\n  " + " \\\n  ".join(jvm_args) + " \\\n  -jar app.jar"

    # Quick test command (uses Java's built-in SSL client)
    test_command = (
        f"java {' '.join(jvm_args)} "
        f"-cp . -Dhost={hostname} -Dport={port} "
        "sun.security.ssl.SSLSocketImpl 2>&1 | head -100"
    )

    # Alternative: keytool verify
    keytool_verify = f"keytool -list -v -keystore {truststore_path} -storepass {truststore_password} -storetype {truststore_type}"

    return {
        "jvm_args": jvm_args,
        "full_command": full_command,
        "openssl_equivalent": openssl_cmd,
        "keytool_verify": keytool_verify,
        "debug_flag": debug_value,
        "issue_type": issue_type,
        "look_for": look_for.get(issue_type, []),
        "service_note": service_notes.get(service, ""),
        "tips": [
            "Redirect stderr to a file for analysis: java ... 2> ssl-debug.log",
            f"Debug output is on STDERR, not STDOUT",
            "For Spring Boot, set JAVA_OPTS in your systemd unit or startup script",
            f"Java {java_version}: TLS 1.3 {'supported' if java_version >= 11 else 'NOT supported (upgrade JDK)'}",
        ],
    }


# ============================================================
# Feature 8: OpenSSL Command Generator
# ============================================================

@router.post("/openssl-commands")
async def openssl_commands(
    hostname: str = Form(""),
    port: int = Form(443),
    cert_cn: str = Form("certificate"),
    service: str = Form("generic"),
    has_chain: bool = Form(True),
    has_key: bool = Form(True),
    mtls: bool = Form(False),
    _: str = Depends(require_api_key),
) -> dict:
    """Generate openssl commands for verifying, inspecting, and testing certificates."""

    cn_safe = cert_cn.replace(" ", "_").replace("*", "wildcard")
    commands = {}

    # Inspect commands
    commands["inspect"] = {
        "label": "Inspect Certificate",
        "commands": [
            {"desc": "View full certificate details", "cmd": f"openssl x509 -in {cn_safe}-cert.pem -text -noout"},
            {"desc": "View subject only", "cmd": f"openssl x509 -in {cn_safe}-cert.pem -subject -noout"},
            {"desc": "View SANs only", "cmd": f"openssl x509 -in {cn_safe}-cert.pem -noout -ext subjectAltName"},
            {"desc": "View expiry date", "cmd": f"openssl x509 -in {cn_safe}-cert.pem -enddate -noout"},
            {"desc": "View serial number", "cmd": f"openssl x509 -in {cn_safe}-cert.pem -serial -noout"},
            {"desc": "View fingerprint (SHA-256)", "cmd": f"openssl x509 -in {cn_safe}-cert.pem -fingerprint -sha256 -noout"},
        ],
    }

    # Verify commands
    verify_cmds = []
    if has_chain:
        verify_cmds.append({"desc": "Verify leaf against chain", "cmd": f"openssl verify -CAfile root-ca.pem -untrusted {cn_safe}-chain.pem {cn_safe}-cert.pem"})
        verify_cmds.append({"desc": "Verify full chain", "cmd": f"openssl verify -CAfile root-ca.pem {cn_safe}-chain.pem"})
    verify_cmds.append({"desc": "Verify against system trust", "cmd": f"openssl verify {cn_safe}-cert.pem"})
    commands["verify"] = {"label": "Verify Chain", "commands": verify_cmds}

    # Key match commands
    if has_key:
        commands["key_match"] = {
            "label": "Verify Key Matches Certificate",
            "commands": [
                {"desc": "Certificate modulus (MD5)", "cmd": f"openssl x509 -noout -modulus -in {cn_safe}-cert.pem | openssl md5"},
                {"desc": "Key modulus (MD5)", "cmd": f"openssl rsa -noout -modulus -in {cn_safe}-key.pem | openssl md5"},
                {"desc": "Both MD5 values must match ↑", "cmd": "# If they don't match, the key is not for this certificate"},
            ],
        }

    # Connection test commands
    if hostname:
        conn_cmds = [
            {"desc": "Basic connection test", "cmd": f"openssl s_client -connect {hostname}:{port} -servername {hostname}"},
        ]
        if has_chain:
            conn_cmds.append({"desc": "Test with explicit CA trust", "cmd": f"openssl s_client -connect {hostname}:{port} -CAfile root-ca.pem -servername {hostname}"})
        conn_cmds.append({"desc": "Show server certificate chain", "cmd": f"openssl s_client -connect {hostname}:{port} -showcerts -servername {hostname} 2>/dev/null | openssl x509 -text -noout"})
        conn_cmds.append({"desc": "Check TLS version negotiated", "cmd": f"openssl s_client -connect {hostname}:{port} -tls1_2 -servername {hostname} 2>/dev/null | grep 'Protocol\\|Cipher'"})
        conn_cmds.append({"desc": "Test TLS 1.3 specifically", "cmd": f"openssl s_client -connect {hostname}:{port} -tls1_3 -servername {hostname} 2>/dev/null | grep 'Protocol\\|Cipher'"})

        if mtls:
            conn_cmds.append({"desc": "Test with client certificate (mTLS)", "cmd": f"openssl s_client -connect {hostname}:{port} -cert {cn_safe}-cert.pem -key {cn_safe}-key.pem -CAfile root-ca.pem -servername {hostname}"})

        commands["connection"] = {"label": "Connection Testing", "commands": conn_cmds}

    # Expiry check commands
    commands["expiry"] = {
        "label": "Expiry Monitoring",
        "commands": [
            {"desc": "Check if cert expires within 30 days", "cmd": f"openssl x509 -in {cn_safe}-cert.pem -checkend 2592000 -noout && echo 'OK' || echo 'EXPIRING SOON'"},
            {"desc": "Check remote server cert expiry", "cmd": f"echo | openssl s_client -connect {hostname or 'HOST'}:{port} -servername {hostname or 'HOST'} 2>/dev/null | openssl x509 -noout -enddate"},
            {"desc": "Days until expiry (script-friendly)", "cmd": f"echo $(( ($(date -d \"$(openssl x509 -in {cn_safe}-cert.pem -enddate -noout | cut -d= -f2)\" +%s) - $(date +%s)) / 86400 )) days"},
        ],
    }

    # Convert commands
    commands["convert"] = {
        "label": "Format Conversion",
        "commands": [
            {"desc": "PEM → DER", "cmd": f"openssl x509 -in {cn_safe}-cert.pem -outform DER -out {cn_safe}-cert.der"},
            {"desc": "DER → PEM", "cmd": f"openssl x509 -in {cn_safe}-cert.der -inform DER -outform PEM -out {cn_safe}-cert.pem"},
            {"desc": "PEM → PKCS12 (with key)", "cmd": f"openssl pkcs12 -export -in {cn_safe}-cert.pem -inkey {cn_safe}-key.pem -certfile root-ca.pem -out {cn_safe}.p12 -name {cn_safe}"},
            {"desc": "Extract cert from PKCS12", "cmd": f"openssl pkcs12 -in {cn_safe}.p12 -clcerts -nokeys -out {cn_safe}-cert.pem"},
            {"desc": "Extract key from PKCS12", "cmd": f"openssl pkcs12 -in {cn_safe}.p12 -nocerts -out {cn_safe}-key.pem"},
            {"desc": "Remove key passphrase", "cmd": f"openssl rsa -in {cn_safe}-key.pem -out {cn_safe}-key-nopass.pem"},
        ],
    }

    # Service-specific commands
    service_cmds = {
        "nginx": [
            {"desc": "Test Nginx config after cert change", "cmd": "nginx -t"},
            {"desc": "Reload Nginx (no downtime)", "cmd": "systemctl reload nginx"},
            {"desc": "Check Nginx is serving correct cert", "cmd": f"echo | openssl s_client -connect {hostname or 'HOST'}:{port} -servername {hostname or 'HOST'} 2>/dev/null | openssl x509 -noout -subject -dates"},
        ],
        "mysql": [
            {"desc": "Check MySQL SSL status", "cmd": "mysql -u root -e \"SHOW VARIABLES LIKE '%ssl%';\""},
            {"desc": "Check current connection cipher", "cmd": "mysql -u root -e \"SHOW STATUS LIKE 'Ssl_cipher';\""},
            {"desc": "Test MySQL TLS connection", "cmd": f"mysql -h {hostname or 'HOST'} -u user --ssl-ca=root-ca.pem --ssl-mode=VERIFY_IDENTITY -e 'SELECT 1'"},
        ],
        "rabbitmq": [
            {"desc": "Check RabbitMQ TLS listeners", "cmd": "rabbitmq-diagnostics listeners"},
            {"desc": "Test AMQPS connection", "cmd": f"openssl s_client -connect {hostname or 'HOST'}:5671 -CAfile root-ca.pem"},
            {"desc": "RabbitMQ TLS status", "cmd": "rabbitmqctl eval 'ssl:versions().'"},
        ],
        "java": [
            {"desc": "List truststore contents", "cmd": f"keytool -list -keystore truststore.p12 -storetype PKCS12 -storepass changeit"},
            {"desc": "List keystore contents (verbose)", "cmd": f"keytool -list -v -keystore keystore.p12 -storetype PKCS12 -storepass changeit"},
            {"desc": "Import CA into JVM cacerts", "cmd": f"keytool -importcert -alias internal-ca -file root-ca.pem -keystore $JAVA_HOME/lib/security/cacerts -storepass changeit -noprompt"},
            {"desc": "Test Java TLS connection (debug)", "cmd": f"java -Djavax.net.debug=ssl:handshake -Djavax.net.ssl.trustStore=truststore.p12 -Djavax.net.ssl.trustStoreType=PKCS12 -Djavax.net.ssl.trustStorePassword=changeit -jar app.jar"},
        ],
        "keystone": [
            {"desc": "Test Keystone HTTPS endpoint", "cmd": f"curl --cacert root-ca.pem https://{hostname or 'HOST'}:5000/v3/"},
            {"desc": "Check Apache SSL config", "cmd": "apachectl -S | grep -i ssl"},
            {"desc": "OpenStack CLI with CA", "cmd": f"openstack --os-cacert root-ca.pem --os-auth-url https://{hostname or 'HOST'}:5000/v3 token issue"},
        ],
    }

    if service in service_cmds:
        commands["service_specific"] = {"label": f"Service: {service.title()}", "commands": service_cmds[service]}

    return {
        "hostname": hostname,
        "port": port,
        "cert_cn": cert_cn,
        "service": service,
        "commands": commands,
    }



# ============================================================
# Feature 6: Certificate Renewal Calendar Export
# ============================================================

@router.get("/calendar.ics", response_class=Response)
async def export_calendar_ics(
    _: str = Depends(require_api_key),
) -> Response:
    """Export all certificate expiry dates as an ICS calendar file."""
    from sqlalchemy import select
    from app.core.database import async_session
    from app.models.certificate import Certificate
    import json

    async with async_session() as db:
        result = await db.execute(
            select(Certificate).where(Certificate.status == "valid")
        )
        certs = result.scalars().all()

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//SSL Certificate Manager//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:SSL Certificate Expiry",
    ]

    for cert in certs:
        subject = json.loads(cert.subject_json)
        cn = subject.get("cn", cert.serial[:16])
        san_list = json.loads(cert.san_json) if cert.san_json else []
        san_summary = ", ".join(s.get("value", "") for s in san_list[:3])

        # Create events at 30, 14, and 7 days before expiry
        for days_before in [30, 14, 7]:
            from datetime import timedelta
            event_date = cert.expires_at - timedelta(days=days_before)
            if event_date < datetime.now(timezone.utc):
                continue  # Don't create past events

            date_str = event_date.strftime("%Y%m%dT090000Z")
            uid = f"{cert.serial}-{days_before}d@certmanager"

            lines.extend([
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTART:{date_str}",
                f"DTEND:{date_str}",
                f"SUMMARY:SSL Cert Expiring: {cn} ({days_before}d remaining)",
                f"DESCRIPTION:Certificate: {cn}\\nSerial: {cert.serial}\\nSANs: {san_summary}\\nExpires: {cert.expires_at.isoformat()}\\nProfile: {cert.profile}",
                "STATUS:CONFIRMED",
                f"CATEGORIES:SSL,{'URGENT' if days_before <= 7 else 'WARNING'}",
                "END:VEVENT",
            ])

    lines.append("END:VCALENDAR")

    ics_content = "\r\n".join(lines)
    return Response(
        content=ics_content.encode(),
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="ssl-cert-expiry.ics"'},
    )


@router.get("/expiry-feed.json")
async def export_expiry_feed(
    _: str = Depends(require_api_key),
) -> list[dict]:
    """Export all certificate expiry data as JSON for monitoring integration."""
    from sqlalchemy import select
    from app.core.database import async_session
    from app.models.certificate import Certificate
    import json

    async with async_session() as db:
        result = await db.execute(
            select(Certificate).where(Certificate.status.in_(["valid", "expired"]))
        )
        certs = result.scalars().all()

    now = datetime.now(timezone.utc)
    feed = []
    for cert in certs:
        subject = json.loads(cert.subject_json)
        san_list = json.loads(cert.san_json) if cert.san_json else []
        tags = json.loads(cert.tags) if cert.tags else []
        days_remaining = (cert.expires_at - now).days

        feed.append({
            "serial": cert.serial,
            "cn": subject.get("cn", ""),
            "sans": [s.get("value", "") for s in san_list],
            "profile": cert.profile,
            "key_algo": cert.key_algo,
            "status": cert.status,
            "expires_at": cert.expires_at.isoformat(),
            "days_remaining": days_remaining,
            "signing_ca_id": cert.signing_ca_id,
            "tags": tags,
            "created_at": cert.created_at.isoformat(),
        })

    # Sort by days remaining (most urgent first)
    feed.sort(key=lambda x: x["days_remaining"])
    return feed


# ============================================================
# Feature 5: PEM → KeyStore Converter
# ============================================================

@router.post("/build-keystore")
async def build_keystore(
    cert_file: UploadFile = File(...),
    key_file: UploadFile = File(...),
    chain_file: UploadFile | None = File(None),
    key_password: str | None = Form(None),
    store_type: str = Form("PKCS12"),
    store_password: str = Form(...),
    alias: str = Form("server"),
    _: str = Depends(require_api_key),
) -> Response:
    """Build a Java KeyStore (.jks or .p12) from PEM cert + key + optional chain."""
    from app.services.keytool_wrapper import KeytoolWrapper, KeytoolError

    keytool = KeytoolWrapper()
    if not keytool.available:
        raise HTTPException(status_code=503, detail="keytool not available. Install JDK 17.")

    if store_type not in ("JKS", "PKCS12"):
        raise HTTPException(status_code=422, detail="store_type must be JKS or PKCS12")

    if store_type == "JKS" and len(store_password) < 12:
        raise HTTPException(status_code=422, detail="JKS password must be at least 12 characters")

    cert_bytes = await cert_file.read()
    key_bytes = await key_file.read()
    chain_bytes = await chain_file.read() if chain_file else b""

    # If key is encrypted, decrypt it first
    if key_password and b"ENCRYPTED" in key_bytes:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key, Encoding, PrivateFormat, NoEncryption
        try:
            key_obj = load_pem_private_key(key_bytes, password=key_password.encode())
            key_bytes = key_obj.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Failed to decrypt key: {e}")

    try:
        if store_type == "JKS":
            store_bytes = keytool.create_keystore(
                cert_pem=cert_bytes,
                key_pem=key_bytes,
                chain_pem=chain_bytes,
                password=store_password,
                alias=alias,
            )
            ext = "jks"
        else:
            # PKCS12 — build directly with cryptography library (faster, no keytool needed)
            from cryptography import x509 as cx509
            from cryptography.hazmat.primitives.serialization import (
                load_pem_private_key, pkcs12, BestAvailableEncryption,
            )

            cert_obj = cx509.load_pem_x509_certificate(cert_bytes)
            key_obj = load_pem_private_key(key_bytes, password=None)

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

            store_bytes = pkcs12.serialize_key_and_certificates(
                alias.encode(),
                key_obj,
                cert_obj,
                chain_certs,
                BestAvailableEncryption(store_password.encode()),
            )
            ext = "p12"

    except KeytoolError as e:
        raise HTTPException(status_code=500, detail=f"KeyStore generation failed: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build keystore: {e}")

    return Response(
        content=store_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{alias}-keystore.{ext}"'},
    )


# ============================================================
# Feature 2: TrustStore Merger
# ============================================================

@router.post("/merge-truststores")
async def merge_truststores(
    files: list[UploadFile] = File(...),
    output_type: str = Form("PKCS12"),
    output_password: str = Form("changeit"),
    _: str = Depends(require_api_key),
) -> Response:
    """Merge multiple truststores or PEM bundles into a single truststore file."""
    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives.serialization import pkcs12, Encoding
    from app.services.keytool_wrapper import KeytoolWrapper, KeytoolError

    if output_type not in ("JKS", "PKCS12"):
        raise HTTPException(status_code=422, detail="output_type must be JKS or PKCS12")

    if not files:
        raise HTTPException(status_code=422, detail="At least one file is required")

    # Collect all unique CA certificates from all input files
    all_certs: dict[str, tuple[str, bytes]] = {}  # fingerprint -> (alias, pem_bytes)
    file_summaries = []

    for upload in files:
        data = await upload.read()
        certs_from_file = 0

        if b"-----BEGIN CERTIFICATE-----" in data:
            # PEM file — extract all certs
            remaining = data
            while b"-----BEGIN CERTIFICATE-----" in remaining:
                try:
                    cert = cx509.load_pem_x509_certificate(remaining)
                    fp = cert.fingerprint(__import__("cryptography.hazmat.primitives.hashes", fromlist=["SHA256"]).SHA256()).hex()
                    if fp not in all_certs:
                        cn_attrs = cert.subject.get_attributes_for_oid(cx509.oid.NameOID.COMMON_NAME)
                        cn = cn_attrs[0].value if cn_attrs else f"cert-{fp[:8]}"
                        alias = cn.lower().replace(" ", "-").replace(".", "-")[:50]
                        all_certs[fp] = (alias, cert.public_bytes(Encoding.PEM))
                        certs_from_file += 1
                    end = remaining.find(b"-----END CERTIFICATE-----") + len(b"-----END CERTIFICATE-----")
                    remaining = remaining[end:]
                except Exception:
                    break
        else:
            # Try as DER single cert
            try:
                cert = cx509.load_der_x509_certificate(data)
                from cryptography.hazmat.primitives import hashes as h
                fp = cert.fingerprint(h.SHA256()).hex()
                if fp not in all_certs:
                    cn_attrs = cert.subject.get_attributes_for_oid(cx509.oid.NameOID.COMMON_NAME)
                    cn = cn_attrs[0].value if cn_attrs else f"cert-{fp[:8]}"
                    alias = cn.lower().replace(" ", "-")[:50]
                    all_certs[fp] = (alias, cert.public_bytes(Encoding.PEM))
                    certs_from_file += 1
            except Exception:
                # Try as JKS/PKCS12 — extract via keytool
                # For simplicity, skip binary stores for now and note in summary
                file_summaries.append({"file": upload.filename, "certs": 0, "note": "Binary store format — extract PEM certs first"})
                continue

        file_summaries.append({"file": upload.filename, "certs": certs_from_file})

    if not all_certs:
        raise HTTPException(status_code=422, detail="No certificates found in any uploaded file")

    # Build merged truststore
    keytool = KeytoolWrapper()

    if output_type == "PKCS12":
        # Build PKCS12 truststore using keytool (supports multiple trusted cert entries)
        if not keytool.available:
            raise HTTPException(status_code=503, detail="keytool required for truststore generation")

        ca_list = [(alias, pem) for alias, pem in all_certs.values()]
        try:
            store_bytes = keytool.create_truststore(ca_list, output_password, "PKCS12")
        except KeytoolError as e:
            raise HTTPException(status_code=500, detail=f"Merge failed: {e}")
        ext = "p12"
    else:
        if not keytool.available:
            raise HTTPException(status_code=503, detail="keytool required for JKS generation")

        ca_list = [(alias, pem) for alias, pem in all_certs.values()]
        try:
            store_bytes = keytool.create_truststore(ca_list, output_password, "JKS")
        except KeytoolError as e:
            raise HTTPException(status_code=500, detail=f"Merge failed: {e}")
        ext = "jks"

    return Response(
        content=store_bytes,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="merged-truststore.{ext}"',
            "X-Cert-Count": str(len(all_certs)),
        },
    )


# ============================================================
# Feature 4: Connection Tester (Full TLS Handshake)
# ============================================================

@router.post("/connection-test")
async def connection_test(
    hostname: str = Form(...),
    port: int = Form(443),
    truststore_file: UploadFile | None = File(None),
    client_cert_file: UploadFile | None = File(None),
    client_key_file: UploadFile | None = File(None),
    client_key_password: str | None = Form(None),
    tls_version: str = Form("auto"),
    sni_hostname: str = Form(""),
    _: str = Depends(require_api_key),
) -> dict:
    """Simulate a full TLS handshake with optional custom trust and client cert."""
    import ssl
    import socket
    import asyncio
    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives import hashes, serialization
    import tempfile
    import os

    sni = sni_hostname or hostname
    result = {
        "hostname": hostname,
        "port": port,
        "sni": sni,
        "success": False,
        "tls_version_requested": tls_version,
    }

    # Build SSL context
    if tls_version == "tlsv1.2":
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLSv2)
    elif tls_version == "tlsv1.3":
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    else:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    # Custom trust
    trust_source = "system"
    if truststore_file:
        trust_data = await truststore_file.read()
        if trust_data:
            tmp_ca = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
            tmp_ca.write(trust_data)
            tmp_ca.close()
            try:
                ctx.load_verify_locations(tmp_ca.name)
                trust_source = "custom"
            except Exception as e:
                os.unlink(tmp_ca.name)
                result["error"] = f"Failed to load truststore: {e}"
                result["trust_error"] = True
                return result
            finally:
                if os.path.exists(tmp_ca.name):
                    os.unlink(tmp_ca.name)
    else:
        ctx.load_default_certs()

    # Client cert (mTLS)
    client_cert_used = False
    tmp_cert_path = None
    tmp_key_path = None
    if client_cert_file and client_key_file:
        cert_data = await client_cert_file.read()
        key_data = await client_key_file.read()
        if cert_data and key_data:
            tmp_cert = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
            tmp_cert.write(cert_data)
            tmp_cert.close()
            tmp_cert_path = tmp_cert.name

            tmp_key = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
            tmp_key.write(key_data)
            tmp_key.close()
            tmp_key_path = tmp_key.name

            try:
                pwd = client_key_password.encode() if client_key_password else None
                ctx.load_cert_chain(tmp_cert_path, tmp_key_path, password=pwd)
                client_cert_used = True
            except Exception as e:
                result["error"] = f"Failed to load client certificate: {e}"
                result["client_cert_error"] = True
                return result
            finally:
                if tmp_cert_path and os.path.exists(tmp_cert_path):
                    os.unlink(tmp_cert_path)
                if tmp_key_path and os.path.exists(tmp_key_path):
                    os.unlink(tmp_key_path)

    # Attempt connection
    def _do_connect():
        try:
            with socket.create_connection((hostname, port), timeout=10) as sock:
                with ctx.wrap_socket(sock, server_hostname=sni) as ssock:
                    return {
                        "success": True,
                        "tls_version": ssock.version(),
                        "cipher": ssock.cipher(),
                        "der_cert": ssock.getpeercert(binary_form=True),
                    }
        except ssl.SSLCertVerificationError as e:
            return {"success": False, "error_type": "trust_failure", "error": str(e)}
        except ssl.SSLError as e:
            return {"success": False, "error_type": "ssl_error", "error": str(e)}
        except socket.timeout:
            return {"success": False, "error_type": "timeout", "error": f"Connection to {hostname}:{port} timed out"}
        except socket.gaierror:
            return {"success": False, "error_type": "dns", "error": f"DNS resolution failed for {hostname}"}
        except ConnectionRefusedError:
            return {"success": False, "error_type": "refused", "error": f"Connection refused: {hostname}:{port}"}
        except Exception as e:
            return {"success": False, "error_type": "unknown", "error": str(e)}

    loop = asyncio.get_event_loop()
    conn_result = await loop.run_in_executor(None, _do_connect)

    result["success"] = conn_result.get("success", False)
    result["trust_source"] = trust_source
    result["client_cert_used"] = client_cert_used

    if result["success"]:
        result["tls_version_negotiated"] = conn_result.get("tls_version")
        cipher = conn_result.get("cipher")
        if cipher:
            result["cipher_suite"] = cipher[0]
            result["cipher_protocol"] = cipher[1]
            result["cipher_bits"] = cipher[2]

        # Decode server cert
        der_cert = conn_result.get("der_cert")
        if der_cert:
            cert_obj = cx509.load_der_x509_certificate(der_cert)
            cn_attrs = cert_obj.subject.get_attributes_for_oid(cx509.oid.NameOID.COMMON_NAME)

            sans = []
            try:
                san_ext = cert_obj.extensions.get_extension_for_class(cx509.SubjectAlternativeName)
                for dns in san_ext.value.get_values_for_type(cx509.DNSName):
                    sans.append(dns)
                for ip in san_ext.value.get_values_for_type(cx509.IPAddress):
                    sans.append(str(ip))
            except cx509.ExtensionNotFound:
                pass

            now = datetime.now(timezone.utc)
            result["server_certificate"] = {
                "cn": cn_attrs[0].value if cn_attrs else "Unknown",
                "issuer": cert_obj.issuer.rfc4514_string(),
                "serial": format(cert_obj.serial_number, "x"),
                "not_valid_after": cert_obj.not_valid_after_utc.isoformat(),
                "days_remaining": (cert_obj.not_valid_after_utc - now).days,
                "sans": sans,
                "hostname_match": any(
                    s == hostname or (s.startswith("*.") and hostname.endswith(s[1:]))
                    for s in sans
                ),
                "fingerprint_sha256": cert_obj.fingerprint(hashes.SHA256()).hex(),
            }

        result["verification"] = {
            "trust": "passed",
            "hostname": "passed" if result.get("server_certificate", {}).get("hostname_match") else "failed",
        }
    else:
        result["error"] = conn_result.get("error", "Unknown error")
        result["error_type"] = conn_result.get("error_type", "unknown")

        # Map to Java-equivalent error
        java_errors = {
            "trust_failure": "javax.net.ssl.SSLHandshakeException: PKIX path building failed",
            "ssl_error": "javax.net.ssl.SSLHandshakeException",
            "timeout": "java.net.SocketTimeoutException",
            "dns": "java.net.UnknownHostException",
            "refused": "java.net.ConnectException: Connection refused",
        }
        result["java_equivalent_error"] = java_errors.get(result["error_type"], "javax.net.ssl.SSLException")

    return result


# ============================================================
# Feature 7: Bulk Certificate Import
# ============================================================

@router.post("/bulk-import")
async def bulk_import_certificates(
    files: list[UploadFile] = File(...),
    tags: str = Form(""),
    source: str = Form("bulk-import"),
    _: str = Depends(require_api_key),
) -> dict:
    """Import multiple existing certificates into the inventory."""
    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives import hashes
    from sqlalchemy import select
    from app.core.database import async_session
    from app.models.certificate import Certificate
    import json
    import uuid

    tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()] if tags else []
    results = []
    imported = 0
    skipped = 0
    failed = 0

    async with async_session() as db:
        for upload in files:
            data = await upload.read()
            filename = upload.filename or "unknown"

            if not data:
                results.append({"file": filename, "status": "failed", "reason": "Empty file"})
                failed += 1
                continue

            # Parse certificate
            try:
                if b"-----BEGIN CERTIFICATE-----" in data:
                    cert_obj = cx509.load_pem_x509_certificate(data)
                    cert_pem = data.decode()
                else:
                    cert_obj = cx509.load_der_x509_certificate(data)
                    from cryptography.hazmat.primitives.serialization import Encoding
                    cert_pem = cert_obj.public_bytes(Encoding.PEM).decode()
            except Exception as e:
                results.append({"file": filename, "status": "failed", "reason": f"Parse error: {e}"})
                failed += 1
                continue

            serial_hex = format(cert_obj.serial_number, "x")

            # Check for duplicate
            existing = await db.execute(
                select(Certificate).where(Certificate.serial == serial_hex)
            )
            if existing.scalar_one_or_none():
                results.append({"file": filename, "status": "skipped", "reason": "Duplicate (serial already exists)", "serial": serial_hex})
                skipped += 1
                continue

            # Extract subject
            subject = {}
            oid_map = {
                cx509.oid.NameOID.COMMON_NAME: "cn",
                cx509.oid.NameOID.ORGANIZATION_NAME: "o",
                cx509.oid.NameOID.ORGANIZATIONAL_UNIT_NAME: "ou",
                cx509.oid.NameOID.COUNTRY_NAME: "c",
                cx509.oid.NameOID.STATE_OR_PROVINCE_NAME: "st",
                cx509.oid.NameOID.LOCALITY_NAME: "l",
            }
            for attr in cert_obj.subject:
                field = oid_map.get(attr.oid)
                if field:
                    subject[field] = attr.value

            # Extract SANs
            san_list = []
            try:
                san_ext = cert_obj.extensions.get_extension_for_class(cx509.SubjectAlternativeName)
                for dns in san_ext.value.get_values_for_type(cx509.DNSName):
                    san_list.append({"type": "dns", "value": dns})
                for ip in san_ext.value.get_values_for_type(cx509.IPAddress):
                    san_list.append({"type": "ip", "value": str(ip)})
            except cx509.ExtensionNotFound:
                pass

            # Detect key info from public key
            from cryptography.hazmat.primitives.asymmetric import rsa, ec, ed25519
            pub_key = cert_obj.public_key()
            if isinstance(pub_key, rsa.RSAPublicKey):
                key_algo, key_size = "RSA", pub_key.key_size
            elif isinstance(pub_key, ec.EllipticCurvePublicKey):
                key_algo, key_size = "ECDSA", pub_key.key_size
            elif isinstance(pub_key, ed25519.Ed25519PublicKey):
                key_algo, key_size = "Ed25519", 256
            else:
                key_algo, key_size = "Unknown", 0

            # Determine status
            now = datetime.now(timezone.utc)
            if cert_obj.not_valid_after_utc < now:
                status = "expired"
            else:
                status = "valid"

            # Create record (no private key — import is cert-only)
            cert_record = Certificate(
                id=str(uuid.uuid4()),
                serial=serial_hex,
                profile="imported",
                subject_json=json.dumps(subject),
                san_json=json.dumps(san_list),
                key_algo=key_algo,
                key_size=key_size,
                cert_pem=cert_pem,
                key_blob=b"",  # No key available for imported certs
                chain_pem=cert_pem,
                signing_ca_id=None,
                status=status,
                expires_at=cert_obj.not_valid_after_utc,
                tags=json.dumps(tag_list + [source]),
            )
            db.add(cert_record)
            imported += 1
            results.append({
                "file": filename,
                "status": "imported",
                "serial": serial_hex,
                "cn": subject.get("cn", ""),
                "expires_at": cert_obj.not_valid_after_utc.isoformat(),
            })

        await db.commit()

    return {
        "summary": {
            "imported": imported,
            "skipped": skipped,
            "failed": failed,
            "total_files": len(files),
        },
        "results": results,
    }
