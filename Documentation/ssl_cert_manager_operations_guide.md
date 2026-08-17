# SSL Certificate Manager — Operations Guide

> **Version:** 3.3  
> **Date:** 2025-07-15  
> **Author:** Paul Scott

---

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Initial Setup & API Key](#2-initial-setup--api-key)
3. [Certificate Authorities](#3-certificate-authorities)
4. [Issuing Certificates](#4-issuing-certificates)
5. [CSR Management & External CAs](#5-csr-management--external-cas)
6. [Trust Store Builder](#6-trust-store-builder)
7. [Export & Download Formats](#7-export--download-formats)
8. [Trust Distribution (Platform Scripts)](#8-trust-distribution-platform-scripts)
9. [Certificate Revocation & CRL](#9-certificate-revocation--crl)
10. [Audit Log](#10-audit-log)
11. [Backups & Restore](#11-backups--restore)
12. [Monitoring & Expiry Alerts](#12-monitoring--expiry-alerts)
13. [Production Deployment](#13-production-deployment)
14. [Troubleshooting](#14-troubleshooting)
15. [Certificate Tools](#15-certificate-tools)
16. [Service Configuration Guides](#16-service-configuration-guides)
17. [Java SSL/TLS Deep Dive](#17-java-ssltls-deep-dive)
18. [Calendar & Monitoring Integration](#18-calendar--monitoring-integration)
19. [System Diagnostics & Troubleshooting Tools](#19-system-diagnostics--troubleshooting-tools)
20. [PKI Infrastructure (CDP, AIA & OCSP)](#20-pki-infrastructure-cdp-aia--ocsp)
21. [Access Control (RBAC)](#21-access-control-rbac)
22. [Certificate Lifecycle Management](#22-certificate-lifecycle-management)
23. [Compliance, Reporting & Governance](#23-compliance-reporting--governance)
24. [Environment Provisioning](#24-environment-provisioning)
25. [EST Protocol (RFC 7030)](#25-est-protocol-rfc-7030)
26. [Multi-Tenancy](#26-multi-tenancy)
27. [Certificate Transparency (Internal)](#27-certificate-transparency-internal)
28. [Email Notifications](#28-email-notifications)
29. [Cross-Certification & Bridge CA](#29-cross-certification--bridge-ca)
30. [Kubernetes cert-manager Integration](#30-kubernetes-cert-manager-integration)
31. [Advanced Reporting & Compliance](#31-advanced-reporting--compliance)

**Fundamentals (read first if new to SSL/TLS):**

0. [Understanding SSL/TLS](#0-understanding-ssltls)
    - [How TLS Actually Works](#01-how-tls-actually-works)
    - [Certificate Anatomy](#02-certificate-anatomy)
    - [The Chain of Trust](#03-the-chain-of-trust)
    - [Common Failure Modes](#04-common-failure-modes)
    - [Certificate Lifecycle](#05-certificate-lifecycle)
    - [Mutual TLS Explained](#06-mutual-tls-mtls-explained)
    - [Internal CA vs Public CA](#07-internal-ca-vs-public-ca)
    - [SSL/TLS Glossary](#08-ssltls-glossary)

---

## 0. Understanding SSL/TLS

This section explains the fundamentals of SSL/TLS and certificates. Read this before diving into the tool-specific sections if you want to understand *why* things work the way they do.

---

### 0.1 How TLS Actually Works

When a client (browser, Java app, curl) connects to a TLS-secured server, a **handshake** occurs before any application data is exchanged:

```
Client                                    Server
  │                                         │
  │──── ClientHello ──────────────────────▶│  "I support TLS 1.2/1.3, these ciphers"
  │                                         │
  │◀──── ServerHello ─────────────────────│  "Let's use TLS 1.3, this cipher"
  │◀──── Certificate ─────────────────────│  "Here's my certificate (+ chain)"
  │◀──── CertificateVerify ───────────────│  "Proof I own the private key"
  │                                         │
  │  Client verifies:                       │
  │  1. Is the cert signed by a trusted CA? │
  │  2. Is the hostname in the cert's SANs? │
  │  3. Is the cert not expired?            │
  │  4. Is the cert not revoked?            │
  │                                         │
  │──── Finished ─────────────────────────▶│  "I trust you, here's my key share"
  │                                         │
  │◀═══════ Encrypted Application Data ═══▶│
```

**Key points:**
- The server proves its identity by presenting a certificate AND proving it holds the matching private key
- The client decides whether to trust the server based on the certificate chain
- All of this happens BEFORE any HTTP request is sent
- If any verification step fails, the connection is immediately terminated

**What "trust" means technically:**
The client has a pre-installed list of CA certificates it trusts. If the server's certificate was signed by one of these CAs (or by an intermediate CA that chains back to one), the client trusts it. Trust is simply "signed by someone in my list."

---

### 0.2 Certificate Anatomy

A certificate is a structured data file containing:

```
┌─────────────────────────────────────────────────────────┐
│ X.509 v3 Certificate                                     │
├─────────────────────────────────────────────────────────┤
│  Subject: CN=api.example.com, O=MyOrg, C=GB             │
│    └─ "Who this certificate is for"                      │
│  Issuer: CN=Internal Root CA, O=MyOrg                    │
│    └─ "Who signed this certificate"                      │
│  Validity: Not Before / Not After                        │
│  Public Key: RSA 2048-bit                                │
│  Extensions:                                             │
│    SAN: DNS:api.example.com, IP:10.0.1.50                │
│    Key Usage: digitalSignature, keyEncipherment          │
│    Extended Key Usage: serverAuth                        │
│    Basic Constraints: CA:FALSE                           │
├─────────────────────────────────────────────────────────┤
│  Signature: (CA's digital signature)                     │
└─────────────────────────────────────────────────────────┘
```

**Which fields matter most:**

| Field | Why It Matters |
|-------|---------------|
| SAN | The ONLY field used for hostname verification (CN is ignored by modern clients) |
| Not After | When the cert expires — services break if this passes without renewal |
| Issuer | Must chain to a trusted CA or verification fails |
| Key Usage | Wrong values = connection rejected by strict clients |
| Basic Constraints | CA:TRUE on a leaf cert = security vulnerability |

---

### 0.3 The Chain of Trust

Certificates form a chain from the leaf (your server) back to a trusted root:

```
┌──────────────────────┐
│ Root CA               │  Self-signed. Pre-installed in browsers/OS.
│ CA:TRUE, pathLen=2    │  Validity: 20-30 years. Key: RSA 4096.
└──────────┬───────────┘
           │ signs
┌──────────▼───────────┐
│ Intermediate CA       │  Signed by root. Does the daily signing.
│ CA:TRUE, pathLen=0    │  Validity: 5-10 years. Key: RSA 4096.
└──────────┬───────────┘
           │ signs
┌──────────▼───────────┐
│ Leaf Certificate      │  YOUR cert. Validity: 398 days.
│ CA:FALSE              │  Key: RSA 2048 or ECDSA P-256.
└──────────────────────┘
```

**Why intermediates exist:**
- The root key is extremely valuable — if compromised, ALL certificates under it are compromised
- By using intermediates, the root key can be kept offline (air-gapped, in an HSM)
- If an intermediate is compromised, only it is revoked without replacing the root

**What "chain of trust" means in practice:**
When your server presents its certificate, it MUST also send the intermediate(s). The client then verifies each signature up to a root it trusts. If any link is missing: `PKIX path building failed`.

---

### 0.4 Common Failure Modes

```
TLS Connection Attempt
        │
        ▼
┌─ Can connect to host? ─── NO ─▶ "Connection refused / timed out"
│      YES                       Cause: wrong port, firewall, service down
│       │
├─ Server sends cert? ──── NO ─▶ "Unsupported SSL message"
│      YES                       Cause: connecting to non-TLS port
│       │
├─ Signed by trusted CA? ── NO ─▶ "PKIX path building failed"
│      YES                       Fix: import CA into truststore
│       │
├─ Chain complete? ────── NO ─▶ "unable to verify the first certificate"
│      YES                       Fix: use chain.pem not cert.pem
│       │
├─ Cert not expired? ──── NO ─▶ "certificate has expired"
│      YES                       Fix: renew; check ALL certs in chain
│       │
├─ Hostname matches SAN? ─ NO ─▶ "hostname verification failed"
│      YES                       Fix: re-issue with correct SANs
│       │
├─ TLS version OK? ───── NO ─▶ "handshake_failure"
│      YES                       Fix: upgrade client or server config
│       │
  ✅ Connection Established
```

---

### 0.5 Certificate Lifecycle

| Day | Event | Action |
|-----|-------|--------|
| 0 | Certificate issued | Deploy to server |
| 1-338 | Active use | Monitoring only |
| 338 | 60 days to expiry | INFO alert; plan renewal |
| 368 | 30 days to expiry | WARNING; renew now |
| 391 | 7 days to expiry | CRITICAL; emergency |
| 398 | Expires | **Service breaks** |

**What happens when a cert expires:** Clients refuse to connect. No graceful degradation. The server runs but nobody can reach it. One expired intermediate can take down dozens of services.

**Revocation vs Expiry:**
- Expiry is automatic (after Not After date)
- Revocation is manual (you mark it as untrusted before expiry)
- Many clients don't check revocation in practice

---

### 0.6 Mutual TLS (mTLS) Explained

**Normal TLS:** only the server proves its identity.
**Mutual TLS:** both server AND client prove their identity.

```
Normal TLS:              Mutual TLS:

Client ─▶ Server         Client ◀─▶ Server
  "Show me your cert"      "Show me your cert"
  ◀─ Server cert             ◀─ Server cert
  "OK I trust you"         "Now show ME yours"
                            ─▶ Client cert
                           Both verified ✓
```

**When to use mTLS:**
- Service-to-service communication
- Zero-trust networks
- API access where API keys aren't sufficient
- Replacing VPN for service connectivity

---

### 0.7 Internal CA vs Public CA

| Aspect | Public CA | Internal CA (this tool) |
|--------|-----------|------------------------|
| Trusted by | Every browser/OS | Only where you've imported the root |
| Cost | Free (LE) to expensive | Free |
| Max validity | 398 days (enforced) | Whatever you set |
| Issuance speed | Minutes to days | Instant |
| Use case | Public websites | Internal services, dev, mTLS |
| Trust distribution | Automatic | Manual (scripts provided) |

**Decision guide:**
- Public-facing → Public CA (Let's Encrypt / ACM)
- Internal service-to-service → Internal CA (this tool)
- Development/staging → Internal CA (this tool)
- mTLS → Internal CA (you control both ends)

---

### 0.8 SSL/TLS Glossary

| Term | Meaning |
|------|---------|
| **SSL** | Secure Sockets Layer — deprecated predecessor to TLS. "SSL cert" = TLS certificate. |
| **TLS** | Transport Layer Security — current standard. Use 1.2 or 1.3 only. |
| **X.509** | Standard format for certificates. |
| **PEM** | Base64 text encoding. Starts with `-----BEGIN CERTIFICATE-----`. Common on Linux. |
| **DER** | Binary encoding. Same data as PEM without Base64. Common on Windows. |
| **PKCS#8** | Generic private key format. Header: `-----BEGIN PRIVATE KEY-----`. |
| **PKCS#12/PFX** | Binary bundle: cert + key + chain, password-protected. Extension: `.p12`/`.pfx`. |
| **JKS** | Java KeyStore — proprietary format being replaced by PKCS#12. |
| **CSR** | Certificate Signing Request — sent to a CA to request signing. |
| **CA** | Certificate Authority — signs certificates. Public or private. |
| **Root CA** | Top of trust chain. Self-signed. Pre-installed in trust stores. |
| **Intermediate CA** | Signs leaf certs on behalf of root. Allows root key to stay offline. |
| **Leaf cert** | Your server's certificate. CA:FALSE. |
| **CN** | Common Name — IGNORED by modern clients. Use SANs instead. |
| **SAN** | Subject Alternative Name — the ONLY field used for hostname verification. |
| **EKU** | Extended Key Usage — serverAuth, clientAuth, codeSigning. |
| **CRL** | Certificate Revocation List — published list of revoked serials. |
| **OCSP** | Online Certificate Status Protocol — real-time revocation check. |
| **SNI** | Server Name Indication — TLS extension for multiple certs on one IP. |
| **mTLS** | Mutual TLS — both client and server present certificates. |
| **Trust Store** | CAs a system trusts. Different per platform. |
| **Key Store** | A server's own identity (private key + cert). |

---

## 1. Getting Started

### What This Tool Does

The SSL Certificate Manager is a web-based tool for generating, managing, and distributing X.509 certificates. It provides:

- A self-signed Certificate Authority (root + intermediate)
- Certificate issuance for TLS servers, mTLS clients, code signing, and email
- CSR generation for submission to external CAs (DigiCert, Sectigo, Let's Encrypt, etc.)
- Java KeyStore and TrustStore generation
- Platform-specific trust installation scripts (Linux, Windows, Java)
- Full audit trail of every operation

### Architecture

```
Browser (React SPA)
    │
    ▼ REST/JSON
FastAPI Backend (Python)
    │
    ├── Crypto Engine (pyca/cryptography)
    ├── Keytool Wrapper (JDK 17)
    └── SQLite Database (encrypted key storage)
```

### Development Quick Start

```bash
git clone <repo-url> && cd ssl
bash scripts/dev-setup.sh
```

This single command:
1. Creates a Python virtual environment and installs dependencies
2. Installs frontend Node.js packages
3. Generates secrets (CERT_MASTER_KEY and API_KEY) in `backend/.env`
4. Creates data directories
5. Runs database migrations
6. Starts both backend (port 8000) and frontend (port 3000)

---

## 2. Initial Setup & API Key

### Finding Your API Key

The API key is generated on first run and stored in `backend/.env`:

```bash
grep API_KEY backend/.env
```

### Configuring the Browser

1. Open http://localhost:3000
2. Navigate to **Settings** (bottom of sidebar)
3. Paste your API key into the field and click **Save**
4. All subsequent API calls from the browser will include this key

### API Key Rotation

If your API key is compromised or you want to rotate it as a security practice:

1. Go to **Settings**
2. Click **🔄 Rotate API Key**
3. Confirm the rotation
4. The new key is generated server-side; the old key is immediately invalidated
5. Your browser is automatically updated with the new key
6. **Important:** Update `backend/.env` (or `/etc/certmanager/certmanager.env` in production) with the new value — otherwise the application will reject requests after restart

Via API:
```bash
curl -sk -X POST -H "X-API-Key: $OLD_KEY" \
  https://localhost/api/v1/settings/rotate-api-key
```

Response:
```json
{
  "status": "rotated",
  "new_api_key": "new-key-value-here",
  "message": "Save this key immediately..."
}
```

Rotation is logged as a WARNING-severity audit event.

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `CERT_MASTER_KEY` | Yes | Fernet key for encrypting stored private keys |
| `API_KEY` | Yes | Legacy master API key (admin access) |
| `DATABASE_URL` | No | Database connection URL. If empty, uses SQLite at `DATA_DIR/certmanager.db`. For PostgreSQL: `postgresql+asyncpg://user:pass@host:5432/dbname` |
| `DB_POOL_SIZE` | No | PostgreSQL connection pool size (default: 20) |
| `DB_MAX_OVERFLOW` | No | Max overflow connections above pool size (default: 10) |
| `DATA_DIR` | No | Root data directory (default: `/var/lib/certmanager`) |
| `LOG_LEVEL` | No | DEBUG, INFO, WARNING, ERROR (default: INFO) |
| `MAX_CERT_DAYS` | No | Maximum leaf cert validity in days (default: 825) |
| `BACKUP_DIR` | No | Backup archive location |
| `BASE_URL` | No | Public URL for CRL distribution points |
| `PKI_BASE_URL` | No | Base URL for PKI endpoints (CDP, AIA, OCSP). If empty, extensions disabled |
| `CRL_VALIDITY_DAYS` | No | CRL validity period in days (default: 7) |
| `JWT_SECRET` | No | Secret for signing JWT tokens (defaults to CERT_MASTER_KEY if empty) |
| `JWT_EXPIRE_HOURS` | No | JWT token lifetime in hours (default: 24) |

| `LDAP_ENABLED` | No | Enable LDAP authentication (default: false) |
| `LDAP_URL` | No | LDAP server URL (e.g. `ldaps://dc.corp.internal:636`) |
| `LDAP_SEARCH_BASE` | No | Base DN for user search (e.g. `ou=People,dc=corp,dc=internal`) |
| `LDAP_SEARCH_FILTER` | No | User search filter (default: `(uid={username})`) |
| `LDAP_ROLE_ADMIN` | No | LDAP group DN that maps to admin role |
| `LDAP_ROLE_OPERATOR` | No | LDAP group DN that maps to operator role |
| `LDAP_ROLE_AUDITOR` | No | LDAP group DN that maps to auditor role |
| `LDAP_ROLE_DEFAULT` | No | Default role when no group matches (default: `readonly`) |

---

### Creating a Root CA

1. Navigate to **Certificate Authorities** in the sidebar
2. Click **+ Create CA**
3. Select **Root CA**
4. Fill in subject fields:
   - **Common Name** (required): e.g. `Internal Root CA`
   - Organisation, Country, etc. (optional)
5. Configure key options:
   - **Algorithm**: RSA (recommended for max compatibility), ECDSA, or Ed25519
   - **Key Size**: 4096 recommended for root CAs
   - **Validity**: 3650 days (10 years) is typical for roots
6. Click **Create CA**

### Creating an Intermediate CA

1. Same flow as above, but select **Intermediate CA**
2. Choose the **Parent CA** from the dropdown
3. Recommended: RSA 4096 or ECDSA P-384, 1825 days (5 years)

#### Name Constraints

Intermediate CAs can be restricted to only issue certificates for specific DNS domains:

```bash
curl -sk -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  https://localhost/api/v1/ca \
  -d '{
    "subject": {"cn": "Team Alpha CA", "o": "MyOrg"},
    "key_algo": "RSA", "key_size": 4096,
    "validity_days": 1825,
    "parent_ca_id": "<root-ca-id>",
    "path_length": 0,
    "name_constraints": {
      "permitted": [".alpha.internal", ".alpha.test"],
      "excluded": [".bad.alpha.internal"]
    },
    "policy_oid": "1.3.6.1.4.1.99999.1.1",
    "cps_url": "http://pki.internal/cps"
  }'
```

**Enforcement:** When issuing a certificate signed by a constrained CA, all DNS SANs and the CN are validated against the constraints. Violations are rejected with a 422 error.

**Certificate Policy OID:** If `policy_oid` and `cps_url` are set on a CA, all certificates issued by that CA will include a `CertificatePolicies` extension with the OID and CPS qualifier URL.

### CA Hierarchy

The CA page displays a tree visualisation:

```
🏛️ Internal Root CA (Root)
  └─ Production Issuing CA (Intermediate)
  └─ Development Issuing CA (Intermediate)
```

### Best Practices

- Issue leaf certificates from an **intermediate CA**, not directly from the root
- Root CA path length = 1, Intermediate path length = 0
- Store the root CA key offline once intermediates are created (future feature)
- RSA 4096 for CAs (longevity); RSA 2048 or ECDSA P-256 for leaf certs (performance)

---

## 4. Issuing Certificates

### Using the Certificate Wizard

Navigate to **Certificates → + Issue Certificate** (or the quick action on the Dashboard).

#### Step 1: Profile Selection

| Profile | Use Case | Key Usage | SAN Required |
|---------|----------|-----------|--------------|
| Server (TLS) | HTTPS endpoints, APIs | digitalSignature, keyEncipherment | Yes |
| Client (mTLS) | Service accounts, mutual TLS | digitalSignature | No |
| Code Signing | Binary/package signing | digitalSignature, contentCommitment | No |
| Email (S/MIME) | Email encryption | digitalSignature, keyEncipherment | Yes (email) |
| Custom | User-defined | User-selected | Optional |

#### Step 2: Subject Fields

- **Common Name** (required): the primary hostname or identity
- Organisation, Org Unit, Country, State, Locality (optional)

#### Step 3: Subject Alternative Names (SAN)

For **Server** profile, at least one SAN is mandatory (RFC 2818 / JSSE requirement).

Add entries using the tag editor:
- **DNS**: `api.example.com`, `*.example.com` (wildcard)
- **IP**: `10.0.1.50`, `172.20.108.10`
- **Email**: `admin@example.com` (for S/MIME)
- **URI**: `spiffe://cluster/svc/api` (for SPIFFE)

Tips:
- Paste comma-separated or newline-separated values for bulk entry
- Wildcards: only one level allowed (`*.example.com` ✓, `*.*.example.com` ✗)

#### Step 4: Key & Signing CA

- **Algorithm**: RSA 2048 (best compatibility) or ECDSA P-256 (faster, smaller)
- **Validity**: Max 825 days for leaf certs (Apple/Chrome policy)
- **Signing CA**: Select which CA signs this certificate

#### Step 5: Review & Issue

Review all settings. Click **Issue Certificate**. On success, download links appear immediately.

### Download Formats After Issuance

| Format | Button | Contents |
|--------|--------|----------|
| PEM | `PEM` | Leaf certificate only |
| DER | `DER` | Binary format (Windows) |
| Chain | `CHAIN` | Leaf + intermediate + root |
| Key | `KEY` | Private key (PEM) |
| PKCS#12 | `P12` | Certificate + key bundle |
| Bundle | `BUNDLE` | ZIP with all files + scripts + README |

### Certificate Detail / Inspector

Click any certificate row in the list to open the **Certificate Inspector**. This shows:

- **Status** — valid/revoked/expired with days remaining countdown
- **Subject** — all decoded fields (CN, O, OU, C, ST, L) with copy button
- **Issuer** — decoded issuer DN with copy button
- **SANs** — all Subject Alternative Names with type badges (DNS, IP, Email, URI)
- **Identifiers** — serial number (hex), SHA-256 fingerprint, SHA-1 fingerprint — all with copy-to-clipboard
- **Extensions** — every X.509 v3 extension with OID, name, critical flag, and value
- **PEM** — full certificate PEM with copy button
- **Export buttons** — PEM, DER, Chain, Key, P12, Bundle directly from the detail page

### Searching Certificates

The certificate list search bar matches against:
- Common Name (CN)
- Any SAN value (DNS names, IP addresses)
- Serial number

This means you can search for `10.0.1.50` to find all certificates that include that IP as a SAN, or `*.example.com` to find wildcard certs.

### Copy to Clipboard

Throughout the application, look for **Copy** buttons next to:
- Serial numbers
- Fingerprints (SHA-256, SHA-1)
- Subject/Issuer DNs
- PEM certificate content
- Spring Boot property snippets

Click to copy the value directly to your clipboard without downloading a file.

---

## 5. CSR Management & External CAs

The CSR Manager handles two workflows:

### Path A: Generate New Key + CSR

Use this when you need a fresh keypair and CSR to submit to an external CA.

1. Navigate to **CSR Manager → + New CSR**
2. Select **Generate New Key + CSR**
3. Fill in subject and SAN fields (matching what the external CA expects)
4. Choose algorithm and key size
5. Check **Store key** (so you can pair the signed cert later)
6. Click **Generate CSR**
7. Download the CSR in PEM format
8. Submit the CSR to your external CA (DigiCert, Sectigo, ADCS, etc.)

### Path C: Renew from Existing Certificate (Zero Input)

Use this when renewing an existing certificate — the tool extracts all subject and SAN details automatically.

**Option 1 — Upload a .p12/.pfx file (contains cert + key):**

1. Select **Renew from Existing Certificate**
2. Choose **PKCS#12 / .p12 / .pfx**
3. Upload your `.p12` file and enter its password
4. Click **Generate Renewal CSR**
5. The tool extracts CN, subject fields, and all SANs from the existing certificate, then generates a new CSR signed by the same private key — no manual input required

**Option 2 — Upload cert + key separately:**

1. Select **Renew from Existing Certificate**
2. Choose **Separate cert + key files**
3. Upload your existing certificate (.pem/.crt) and private key (.pem/.key)
4. Enter key passphrase if encrypted
5. Click **Generate Renewal CSR**

After generation, the success panel shows what was extracted:
- Original CN and subject fields
- All SANs carried over
- Original certificate's issuer and expiry date
- Verification results

Download the CSR and submit to your CA for renewal. The process is identical to a new issuance from the CA's perspective.

### Path B: Upload Existing Key + CSR

Use this when you already have a private key (from a server, HSM, or `openssl genrsa`).

1. Select **Upload Existing Key + CSR**
2. Click **Choose key file** — supports:
   - PEM (PKCS#1, PKCS#8, EC)
   - DER
   - PKCS#12 (.p12/.pfx)
3. Enter passphrase if the key is encrypted
4. Optionally check **Store key in database** (for later pairing)
5. Fill in subject and SAN fields
6. Click **Generate CSR**

### Importing the Signed Certificate

After your external CA returns the signed certificate:

1. Find the CSR in the CSR Manager list (status: **Pending**)
2. Click **Import Cert**
3. Upload the signed certificate (.pem, .crt, .cer, .der)
4. Optionally upload the CA chain / intermediate bundle
5. Click **Import Certificate**

The tool verifies the certificate's public key matches the CSR, then stores it in the certificate inventory paired with the private key. It can then be exported as PEM, P12, JKS, or bundle ZIP like any other certificate.

### Submission Instructions by CA

| CA | Method |
|----|--------|
| Let's Encrypt / ACME | `certbot certonly --csr <file>` |
| DigiCert / Sectigo | Paste PEM into web portal |
| Microsoft ADCS | `certreq -submit <file>` |
| Internal OpenSSL CA | `openssl ca -in <file> -out cert.pem` |

---

## 6. Trust Store Builder

### What It Does

Java applications (Spring Boot, Tomcat, RabbitMQ) maintain their own truststore separate from the OS. The Trust Store Builder creates a pre-populated JKS or PKCS#12 file containing your internal root CA.

### Building a TrustStore

1. Navigate to **Trust Stores**
2. Enter a **name** (e.g. `production-truststore`)
3. Select **Store Type**: JKS (legacy) or PKCS#12 (Java 9+, recommended)
4. Check the CA(s) to include
5. Set a **password** (minimum 12 characters for JKS)
6. Click **Build TrustStore**
7. Download the file and deploy alongside your Java application

### Spring Boot Configuration

After building, the tool shows the JVM properties:

```properties
-Djavax.net.ssl.trustStore=/path/to/truststore.jks
-Djavax.net.ssl.trustStorePassword=<password>
-Djavax.net.ssl.trustStoreType=JKS
```

For PKCS#12:
```properties
-Djavax.net.ssl.trustStoreType=PKCS12
```


---

## 7. Export & Download Formats

### Per-Certificate Export

From the **Certificate Inspector** page, use the export buttons or the API directly:

```
GET /api/v1/export/{serial}/{format}?chain_mode={mode}&platform={platform}
```

| Format | Extension | Use Case |
|--------|-----------|----------|
| `pem` | .pem | Leaf certificate only (Nginx, Apache, HAProxy) |
| `der` | .cer | Binary format (Windows double-click import) |
| `chain` | .pem | Certificate chain — respects `chain_mode` parameter |
| `key` | .pem | Private key (PKCS#8 PEM) — **handle with care** |
| `p12` | .p12 | PKCS#12 bundle (cert + key + full chain) |
| `pfx` | .pfx | Alias for P12 (Windows naming convention) |
| `p7b` | .p7b | PKCS#7 chain (no key) — Windows native format |
| `jks` | .jks | Java KeyStore with private key and full chain |
| `bundle` | .zip | Platform-structured ZIP — respects `platform` parameter |

### Full Chain Building

For multi-level CA hierarchies (Root → Intermediate L1 → Intermediate L2 → Leaf), the system automatically walks the CA hierarchy to build the complete chain. All chain-containing exports (chain, p12, pfx, p7b, jks, bundle) include the full path from leaf to root.

### Chain Mode Parameter

The `chain` export format accepts a `chain_mode` query parameter:

| Mode | Contents | Use Case |
|------|----------|----------|
| `full` (default) | Leaf + all intermediates + root | Complete verification |
| `no_root` | Leaf + intermediates only | Preferred for most TLS servers (clients have root in trust store) |
| `intermediates_only` | Intermediate CAs only (no leaf, no root) | Apache `SSLCertificateChainFile` (legacy) |
| `leaf_only` | Leaf certificate only | Same as `pem` format |

```bash
# Full chain (default)
curl -sk -H "X-API-Key: $API_KEY" \
  https://localhost/api/v1/export/<serial>/chain -o chain-full.pem

# Chain without root (preferred for Nginx ssl_certificate)
curl -sk -H "X-API-Key: $API_KEY" \
  "https://localhost/api/v1/export/<serial>/chain?chain_mode=no_root" -o chain.pem

# Intermediates only (Apache SSLCertificateChainFile)
curl -sk -H "X-API-Key: $API_KEY" \
  "https://localhost/api/v1/export/<serial>/chain?chain_mode=intermediates_only" -o intermediates.pem
```

### PKCS#7 (.p7b) Export

The P7B format is the native Windows chain format. It contains certificates without private keys and is importable via:
- Windows MMC: right-click → Import
- `certutil -addstore CA cert-chain.p7b`
- IIS: Complete Certificate Request wizard

```bash
curl -sk -H "X-API-Key: $API_KEY" \
  https://localhost/api/v1/export/<serial>/p7b -o cert-chain.p7b
```

### Chain Validation

Verify a stored certificate's chain is cryptographically correct:

```bash
curl -sk -H "X-API-Key: $API_KEY" \
  https://localhost/api/v1/export/validate-chain/<serial>

# Response:
# {"valid": true, "errors": [], "chain_length": 3}
```

Validation checks:
- Each certificate's issuer matches the next certificate's subject
- Each signature verifies against the parent's public key (RSA, ECDSA, Ed25519)
- Root certificate is self-signed
- No loops in the chain

### Platform-Structured Bundle

The `bundle` format generates a ZIP with platform-specific subdirectories. Use the `platform` parameter to include only specific platforms:

| Platform | Contents |
|----------|----------|
| `all` (default) | All platforms |
| `linux` | PEM files + multi-distro trust import script |
| `windows` | PFX, P7B, DER, PowerShell + batch import scripts |
| `java` | PKCS#12 keystore, JKS keystore, truststore, Spring Boot config, JVM opts |
| `macos` | PKCS#12, root CA PEM, Keychain import script |

```bash
# Full bundle (all platforms)
curl -sk -H "X-API-Key: $API_KEY" \
  https://localhost/api/v1/export/<serial>/bundle -o bundle.zip

# Windows-only bundle
curl -sk -H "X-API-Key: $API_KEY" \
  "https://localhost/api/v1/export/<serial>/bundle?platform=windows" -o windows-bundle.zip

# Java-only bundle
curl -sk -H "X-API-Key: $API_KEY" \
  "https://localhost/api/v1/export/<serial>/bundle?platform=java" -o java-bundle.zip
```

### Bundle ZIP Contents (All Platforms)

```
├── linux/
│   ├── cert.pem              Leaf certificate
│   ├── key.pem               Private key
│   ├── chain-full.pem        Leaf + intermediates + root
│   ├── chain-no-root.pem     Leaf + intermediates
│   ├── intermediates.pem     Intermediate CAs only
│   ├── root-ca.pem           Root CA certificate
│   └── trust-import.sh       Auto-detect distro and import root CA
├── windows/
│   ├── cert-with-key.pfx     PKCS#12 (cert + key + full chain)
│   ├── cert-chain.p7b        PKCS#7 chain (MMC/certutil import)
│   ├── root-ca.cer           Root CA in DER (double-click install)
│   ├── intermediates.p7b     Intermediate CAs in PKCS#7
│   ├── trust-import.ps1      PowerShell import script
│   └── trust-import.bat      Batch import script (certutil)
├── java/
│   ├── keystore.p12          PKCS#12 keystore (cert + key + chain)
│   ├── keystore.jks          JKS keystore (if keytool available)
│   ├── truststore.jks        TrustStore (CA certs only)
│   ├── spring-boot.properties Spring Boot SSL configuration
│   └── java-opts.txt         JVM arguments for SSL
├── macos/
│   ├── cert-with-key.p12     PKCS#12 (Keychain import)
│   ├── root-ca.pem           Root CA for trust import
│   └── trust-import.sh       Keychain trust import script
└── README.txt                Platform-specific usage instructions
```

### API Usage Examples

```bash
# Download PEM
curl -sk -H "X-API-Key: $API_KEY" \
  https://localhost/api/v1/export/<serial>/pem -o cert.pem

# Download PFX with full chain (Windows IIS)
curl -sk -H "X-API-Key: $API_KEY" \
  https://localhost/api/v1/export/<serial>/pfx -o cert.pfx

# Download P7B chain (Windows MMC)
curl -sk -H "X-API-Key: $API_KEY" \
  https://localhost/api/v1/export/<serial>/p7b -o chain.p7b

# Download JKS with full chain (Java/Tomcat)
curl -sk -H "X-API-Key: $API_KEY" \
  https://localhost/api/v1/export/<serial>/jks -o keystore.jks

# Validate chain integrity
curl -sk -H "X-API-Key: $API_KEY" \
  https://localhost/api/v1/export/validate-chain/<serial>
```

---

## 8. Trust Distribution (Platform Scripts)

After creating a Root CA, you need to distribute it to every system that will trust certificates issued by this tool.

### Linux (Debian / Ubuntu)

```bash
sudo cp root-ca.pem /usr/local/share/ca-certificates/internal-root-ca.crt
sudo update-ca-certificates
```

Or use the generated script:
```bash
sudo bash install-ca-debian.sh
```

### Linux (RHEL / Rocky / AlmaLinux)

```bash
sudo cp root-ca.pem /etc/pki/ca-trust/source/anchors/internal-root-ca.pem
sudo update-ca-trust extract
```

Or use the generated script:
```bash
sudo bash install-ca-rhel.sh
```

### Windows

Run as Administrator in PowerShell:
```powershell
Import-Certificate -FilePath .\root-ca.cer -CertStoreLocation Cert:\LocalMachine\Root
```

Or use the generated script:
```powershell
.\install-ca-windows.ps1
```

### Java / JVM

```bash
keytool -importcert -alias internal-root-ca \
  -file root-ca.pem \
  -keystore $JAVA_HOME/lib/security/cacerts \
  -storepass changeit -noprompt
```

### Browsers

- **Chrome**: Settings → Privacy & Security → Security → Manage certificates → Authorities → Import
- **Firefox**: Settings → Privacy & Security → View Certificates → Authorities → Import

### Verification

```bash
# Linux — verify a cert against system trust
openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt cert.pem

# Windows — verify
certutil -verify cert.der

# Java — list truststore contents
keytool -list -keystore $JAVA_HOME/lib/security/cacerts -storepass changeit | grep internal
```

---

## 9. Certificate Revocation & CRL

### Revoking a Certificate

1. Navigate to **Certificates**
2. Find the certificate (search by CN or filter by status)
3. Click **Revoke**
4. Select a **revocation reason** from the dropdown
5. Confirm the revocation

The certificate status changes to **Revoked** and cannot be un-revoked.

### Revocation Reason Codes (RFC 5280)

Every revocation includes a reason code that is embedded in the CRL and OCSP response. This tells relying parties *why* the certificate was revoked, enabling appropriate response (e.g. key compromise requires immediate distrust, while superseded is informational).

| Reason Code | Value | When to Use |
|-------------|:-----:|-------------|
| `unspecified` | 0 | Default — no specific reason given |
| `key_compromise` | 1 | Private key was leaked or stolen |
| `ca_compromise` | 2 | The signing CA's key was compromised |
| `affiliation_changed` | 3 | Subject's organisation changed |
| `superseded` | 4 | Replaced by a new certificate |
| `cessation_of_operation` | 5 | Service decommissioned permanently |
| `certificate_hold` | 6 | Temporary suspension (set automatically by hold) |
| `privilege_withdrawn` | 9 | Subject's access/privileges revoked |

#### Revoking with a Reason via API

```bash
# Revoke with reason (key compromise)
curl -sk -X DELETE -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  https://localhost/api/v1/cert/<serial> \
  -d '{"reason": "key_compromise"}'

# Revoke with reason (superseded)
curl -sk -X DELETE -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  https://localhost/api/v1/cert/<serial> \
  -d '{"reason": "superseded"}'

# Revoke without body (defaults to "unspecified")
curl -sk -X DELETE -H "X-API-Key: $API_KEY" \
  https://localhost/api/v1/cert/<serial>
```

Response:
```json
{"status": "revoked", "serial": "67b309a1dc46e2c5...", "reason": "key_compromise"}
```

#### CRL Reason Extension

The reason code is embedded as an `X509v3 CRL Reason Code` extension on each CRL entry:

```
Revoked Certificates:
    Serial Number: 67B309A1DC46E2C57CE00FCCD495D988
        Revocation Date: Jul  9 20:53:59 2026 GMT
        CRL entry extensions:
            X509v3 CRL Reason Code:
                Key Compromise
```

#### OCSP Reason

The OCSP responder also includes the revocation reason in its response. Clients that check OCSP (Java with `-Dcom.sun.net.ssl.checkRevocation=true`, browsers) will see the reason.

```bash
# Check OCSP status (includes reason)
curl -s http://pki.internal/api/v1/pki/ocsp/status/<serial>

# Response:
# {"serial":"...","status":"revoked","revoked_at":"...","revocation_reason":"key_compromise",...}
```

### Certificate Hold (Temporary Revocation)

If you need to temporarily suspend a certificate without permanently revoking it (e.g. during incident investigation), use **hold**:

```bash
# Place on hold (automatically sets reason to "certificate_hold")
curl -sk -X POST -H "X-API-Key: $API_KEY" \
  https://localhost/api/v1/cert/<serial>/hold

# Remove from hold (restore to valid, clears reason)
curl -sk -X POST -H "X-API-Key: $API_KEY" \
  https://localhost/api/v1/cert/<serial>/unhold
```

**Hold vs Revoke:**

| Action | Reversible | CRL Reason Code | Use Case |
|--------|:----------:|-----------------|----------|
| Hold | ✓ | `certificateHold` | Incident investigation, temporary suspension |
| Revoke (unspecified) | ✗ | `unspecified` | General revocation |
| Revoke (key_compromise) | ✗ | `keyCompromise` | Private key leaked |
| Revoke (superseded) | ✗ | `superseded` | Replaced by new cert |
| Revoke (cessation) | ✗ | `cessationOfOperation` | Service decommissioned |

A held certificate:
- Shows status `held` in the UI and API
- Appears in the CRL with reason `Certificate Hold`
- Returns `revoked` status via OCSP (with `certificate_hold` reason)
- Can be restored to `valid` at any time with unhold
- On unhold: removed from CRL, OCSP returns `good` again

A revoked certificate is permanent and cannot be un-revoked.

### Certificate Revocation List (CRL)

A CRL is automatically available for each CA:

```
GET /api/v1/crl/{ca_id}
```

The CRL is DER-encoded and contains all revoked serial numbers for that CA. It's regenerated on every request (live CRL).

### Public CRL Endpoint

When `PKI_BASE_URL` is configured, a public (no-auth) CRL endpoint is available:

```bash
# Download CRL (no API key required — public per RFC 5280)
curl -s http://pki.internal/api/v1/pki/crl/<ca-id> -o crl.der
```

This URL is automatically embedded as a CDP (CRL Distribution Point) extension in all newly issued certificates.

### Checking Revocation

```bash
# Download CRL (authenticated, legacy endpoint)
curl -sk -H "X-API-Key: $API_KEY" \
  https://localhost/api/v1/crl/<ca-id> -o crl.der

# Download CRL (public PKI endpoint — preferred)
curl -s http://pki.internal/api/v1/pki/crl/<ca-id> -o crl.der

# Inspect CRL
openssl crl -in crl.der -inform DER -text -noout

# Verify a cert against CRL
openssl verify -crl_check -CAfile root-ca.pem -CRLfile crl.pem cert.pem

# Check OCSP status (real-time, no CRL download needed)
openssl ocsp -issuer ca.pem -cert server.pem \
  -url http://pki.internal/api/v1/pki/ocsp -no_nonce
```

---

## 10. Audit Log

### What's Logged

Every write operation and download is recorded:

| Event Type | Severity | Trigger |
|-----------|----------|---------|
| `CA_CREATED` | INFO | New CA created |
| `CERT_ISSUED` | INFO | Certificate issued |
| `CERT_REVOKED` | WARNING | Certificate revoked |
| `CERT_IMPORTED` | INFO | External cert imported |
| `CSR_GENERATED` | INFO | CSR created |
| `CSR_SIGNED` | INFO | CSR signed by internal CA |
| `CERT_DOWNLOAD` | INFO | PEM/DER/chain downloaded |
| `KEY_DOWNLOAD` | WARNING | Private key downloaded |
| `P12_DOWNLOAD` | WARNING | PKCS#12 downloaded (contains key) |
| `JKS_DOWNLOAD` | WARNING | KeyStore downloaded |
| `TRUSTSTORE_DOWNLOAD` | INFO | TrustStore downloaded |
| `BACKUP_CREATED` | INFO | Backup archive generated |
| `BACKUP_DOWNLOAD` | WARNING | Backup archive downloaded |
| `API_KEY_ROTATED` | WARNING | API key rotated |
| `USER_LOGIN` | INFO | User authenticated via login |
| `USER_CREATED` | INFO | New user account created |
| `USER_UPDATED` | INFO | User account modified |
| `USER_DELETED` | WARNING | User account deleted |
| `PASSWORD_CHANGED` | WARNING | User password changed |
| `API_KEY_CREATED` | INFO | Scoped API key created |
| `API_KEY_REVOKED` | WARNING | Scoped API key revoked |
| `CERT_HELD` | WARNING | Certificate placed on hold (temporary revocation) |
| `CERT_UNHELD` | INFO | Certificate removed from hold |
| `CERT_RENEWED` | INFO | Certificate manually renewed |
| `CERT_AUTO_RENEWED` | INFO | Certificate automatically renewed by background task |
| `CERT_REQUEST_PENDING` | INFO | Certificate request queued for approval |
| `CERT_REQUEST_APPROVED` | INFO | Pending request approved by admin |
| `CERT_REQUEST_REJECTED` | WARNING | Pending request rejected by admin |

### Viewing the Audit Log

1. Navigate to **Audit Log** in the sidebar
2. Use tabs: **All Events** or **Download Events**
3. Filter by event type, subject ID, or date range
4. Click **Export CSV** for offline review or SIEM ingestion

### Repeated Download Detection

If the same private key material is downloaded 3+ times within 24 hours, an amber warning banner appears on the certificate detail page. This is informational — it does not block downloads.

### API Access

```bash
# Recent audit events
curl -sk -H "X-API-Key: $API_KEY" \
  "https://localhost/api/v1/audit?page=1&page_size=20"

# Filter by type
curl -sk -H "X-API-Key: $API_KEY" \
  "https://localhost/api/v1/audit?event_type=KEY_DOWNLOAD"
```


---

## 11. Backups & Restore

> Backup/restore is database-agnostic (SQLite, PostgreSQL, MySQL) — the same UI/API flow below works unchanged regardless of `DATABASE_URL`. If you're moving from SQLite to MySQL, see `Documentation/mysql_migration_runbook.md` for the full cutover procedure, schema-reproduction verification, and data export/import tooling.

### What's Backed Up

- SQLite database (all certificate metadata, encrypted key blobs, audit events)
- Self-cert directory (tool's own TLS certificate and root CA)

Backups are encrypted with AES-256-GCM using a key derived from `CERT_MASTER_KEY` via HKDF.

### Creating a Backup

**Via UI:**
1. Navigate to **Settings**
2. Click **Create Backup** in the Backups panel
3. Download the `.enc` file

**Via API:**
```bash
curl -sk -X POST -H "X-API-Key: $API_KEY" \
  https://localhost/api/v1/backup
```

**Automated:** Backups run automatically every 24 hours (configurable via `BACKUP_INTERVAL_HOURS`). Old backups are purged after `BACKUP_RETAIN_COUNT` (default: 5).

### Listing Backups

```bash
curl -sk -H "X-API-Key: $API_KEY" https://localhost/api/v1/backup
```

### Restoring from Backup

1. Stop the application
2. Run the restore CLI:

```bash
cd /opt/certmanager
sudo -u certmgr venv/bin/python -m app.restore \
  --archive /var/lib/certmanager/backups/backup-20250130T120000Z.enc
```

3. The tool:
   - Decrypts the archive using `CERT_MASTER_KEY`
   - Verifies SHA-256 checksum
   - Creates a safety backup of current state
   - Restores the database and self-certs
4. Start the application

### Verifying a Backup (Without Restoring)

```bash
venv/bin/python -m app.restore \
  --archive /path/to/backup.enc --verify-only
```

### Important Notes

- The same `CERT_MASTER_KEY` used to create the backup must be available to restore it
- If you lose `CERT_MASTER_KEY`, all encrypted key material is permanently unrecoverable
- Store `CERT_MASTER_KEY` securely outside the application (e.g. password manager, HSM, sealed envelope)

---

## 12. Monitoring & Expiry Alerts

### Health Endpoint

```bash
curl -s https://localhost/api/v1/health
```

Response:
```json
{
  "status": "ok",
  "version": "0.1.0",
  "database": "ok",
  "keytool": "ok"
}
```

No authentication required — suitable for monitoring tools (Nagios, Zabbix, UptimeRobot).

### Certificate Expiry Scanning

A background job runs every 24 hours (configurable: `EXPIRY_SCAN_INTERVAL_HOURS`) and checks all valid certificates against configurable thresholds:

| Days Remaining | Action |
|----------------|--------|
| ≤ 60 days | Certificate flagged; INFO audit event |
| ≤ 30 days | Amber warning badge on UI; WARNING audit event |
| ≤ 7 days | Critical badge on UI; WARNING audit event |
| 0 (expired) | Status changed to `expired` |

### Dashboard Widget

The Dashboard shows:
- Total active certificates
- Count expiring within 30 days
- Table of expiring certificates sorted by urgency

### Webhook Notifications

Set `NOTIFY_WEBHOOK_URL` to receive HTTP POST notifications when certificates cross expiry thresholds:

```bash
NOTIFY_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../xxx
```

Payload:
```json
{
  "event": "cert_expiry_warning",
  "severity": "WARNING",
  "certificate": {
    "serial": "abc123...",
    "cn": "api.example.com",
    "expires_at": "2025-03-15T00:00:00Z",
    "days_remaining": 28
  }
}
```

---

## 13. Production Deployment

### Database Options

The application supports two database backends:

| Backend | Use Case | Configuration |
|---------|----------|---------------|
| **SQLite** (default) | Single-instance, Docker, development | No config needed — uses `DATA_DIR/certmanager.db` |
| **PostgreSQL** | Multi-instance, high concurrency, production | Set `DATABASE_URL` environment variable |

#### PostgreSQL Deployment (Docker)

```bash
cd docker
docker compose -f docker-compose.postgres.yml up -d
```

This starts PostgreSQL 16 and the application with connection pooling. Set `POSTGRES_PASSWORD` in your environment or `.env` file:

```bash
POSTGRES_PASSWORD=your_secure_password docker compose -f docker-compose.postgres.yml up -d
```

#### PostgreSQL Deployment (Manual)

1. Create the database:
```sql
CREATE USER certmanager WITH PASSWORD 'your_password';
CREATE DATABASE certmanager OWNER certmanager;
```

2. Set the environment variable:
```bash
DATABASE_URL=postgresql+asyncpg://certmanager:your_password@db-host:5432/certmanager
```

3. Run migrations:
```bash
alembic upgrade head
```

#### Migrating from SQLite to PostgreSQL

If you have an existing SQLite deployment and want to move to PostgreSQL:

1. Ensure the PostgreSQL database exists and migrations have been run (`alembic upgrade head`)
2. Run the migration tool:

```bash
python -m app.tools.migrate_db \
  --from sqlite+aiosqlite:///data/certmanager.db \
  --to postgresql+asyncpg://certmanager:password@localhost:5432/certmanager
```

3. The tool copies all rows and verifies counts match
4. Update `DATABASE_URL` and restart the application

#### Connection Pool Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_POOL_SIZE` | 20 | Number of persistent connections |
| `DB_MAX_OVERFLOW` | 10 | Extra connections allowed under load |
| `DB_POOL_TIMEOUT` | 30 | Seconds to wait for a connection from the pool |
| `DB_STATEMENT_TIMEOUT` | 30000 | Query timeout in milliseconds (PostgreSQL only) |

---

### Target Platform

Ubuntu 22.04 or 24.04 LTS, managed as a systemd service with Nginx reverse proxy.

### Automated Installation

```bash
sudo bash scripts/install.sh
```

This handles: system user creation, package installation, venv setup, frontend build, bootstrap (root CA + listener cert + API key), Nginx config, systemd enable, and smoke test.

### Manual Installation Steps

1. **System prep**: Create `certmgr` user, install python3, openjdk-17, nginx, openssl
2. **Python venv**: `python3 -m venv /opt/certmanager/venv && pip install -r requirements.txt`
3. **Frontend build**: `cd frontend && npm ci && npm run build`
4. **Bootstrap pass 1**: Generate root CA + Nginx listener cert
5. **Nginx**: Install vhost config, reload
6. **Bootstrap pass 2**: Run migrations, import CA, generate API key
7. **systemd**: Enable and start service
8. **Smoke test**: Verify health endpoint returns 200

### Directory Layout (Production)

```
/opt/certmanager/           Application root
/etc/certmanager/           Configuration (secrets)
/var/lib/certmanager/       Persistent data (DB, certs, backups)
/var/log/certmanager/       Application logs
```

### Security Checklist

- [ ] `certmgr` user has no login shell (`/sbin/nologin`)
- [ ] `/etc/certmanager/certmanager.env` is mode 0640, owned root:certmgr
- [ ] `/var/lib/certmanager/` is mode 0700, owned certmgr:certmgr
- [ ] UFW configured: only 443/80 from internal network
- [ ] SSH key-only authentication
- [ ] Automatic security updates enabled
- [ ] CERT_MASTER_KEY stored securely outside the server

---

## 14. Troubleshooting

### Application Won't Start

| Symptom | Cause | Fix |
|---------|-------|-----|
| `CERT_MASTER_KEY is not a valid Fernet key` | Malformed or missing key in .env | Regenerate: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `API_KEY must be at least 16 characters` | Key too short | Regenerate: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `FATAL: Configuration error` | Missing required env vars | Check `backend/.env` exists and has both CERT_MASTER_KEY and API_KEY |
| Migration error on startup | Schema mismatch | Delete DB and re-run: `rm /tmp/certmanager/certmanager.db && alembic upgrade head` |

### API Returns 401

- Check API key is saved in Settings page
- Verify the key matches: `grep API_KEY backend/.env`
- Check browser DevTools → Network → Request Headers for `X-API-Key`

### Certificate Issuance Fails

| Error | Cause | Fix |
|-------|-------|-----|
| `Server certificates require at least one SAN` | No SAN entries added | Add at least one DNS or IP SAN |
| `RSA key size must be at least 2048` | Key size < 2048 | Select 2048 or higher |
| `Validity cannot exceed 825 days` | Requested too long | Reduce validity_days to ≤ 825 |
| `Signing CA not found` | Invalid CA ID | Create a CA first, then select it |

### Keytool Not Found

JKS/TrustStore features require Java 17. Install:
```bash
sudo apt install openjdk-17-jre-headless
```

If installed but not detected, set `JDK_HOME` in your `.env`:
```
JDK_HOME=/usr/lib/jvm/java-17-openjdk-amd64
```

### Frontend Proxy Errors

If the frontend shows network errors:
- Ensure backend is running on port 8000
- Check Vite proxy config in `frontend/vite.config.ts`
- Look at browser DevTools console for CORS or connection refused errors

### Import Certificate Fails

| Error | Cause | Fix |
|-------|-------|-----|
| `Certificate public key does not match CSR` | Wrong cert uploaded | Ensure the cert was issued for this specific CSR |
| `Invalid certificate file` | Corrupt or wrong format | Try converting: `openssl x509 -in cert.der -inform DER -out cert.pem -outform PEM` |

### Database Locked Errors

SQLite WAL mode handles most concurrency, but if you see "database is locked":
- Ensure only one instance of the application is running
- Check for zombie processes: `ps aux | grep uvicorn`
- Increase busy timeout (already set to 30s by default)

### Log Locations

| Log | Path (dev) | Path (production) |
|-----|------------|-------------------|
| Application | stdout | `/var/log/certmanager/app.log` |
| Nginx | — | `/var/log/nginx/access.log` |
| systemd | — | `journalctl -u certmanager` |

---

## 16. Service Configuration Guides

This section provides detailed instructions for configuring TLS certificates issued by this tool on common infrastructure services.

### Prerequisites (All Services)

Before configuring any service, ensure:
1. You have created a Root CA (and optionally an Intermediate CA) in this tool
2. You have issued a **Server (TLS)** certificate with appropriate SANs for the service hostname
3. You have downloaded the certificate files (use the **Bundle ZIP** for the most complete set)
4. You have distributed the Root CA to all clients that will connect to the service (see [Section 8](#8-trust-distribution-platform-scripts))

From the bundle ZIP you will typically use:
- `<cn>-cert.pem` — the server certificate
- `<cn>-key.pem` — the private key
- `<cn>-chain.pem` — full chain (server + intermediate + root)
- `root-ca.pem` — CA certificate (for client trust verification)

---

### 16.1 Nginx

#### Certificate Requirements

| Item | File | Notes |
|------|------|-------|
| Server certificate + chain | `<cn>-chain.pem` | Nginx wants the full chain in one file (leaf first, then intermediates, then root) |
| Private key | `<cn>-key.pem` | Must be unencrypted (no passphrase) for Nginx to start without interaction |
| Client CA (for mTLS) | `root-ca.pem` | Only needed if verifying client certificates |

#### Basic TLS Configuration

```nginx
server {
    listen 443 ssl;
    server_name api.example.internal;

    # Certificate and key
    ssl_certificate     /etc/nginx/ssl/api.example.internal-chain.pem;
    ssl_certificate_key /etc/nginx/ssl/api.example.internal-key.pem;

    # Protocol and cipher settings
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5:!RC4;
    ssl_prefer_server_ciphers on;

    # Session settings
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # OCSP stapling (if CRL/OCSP is configured)
    # ssl_stapling on;
    # ssl_stapling_verify on;
    # ssl_trusted_certificate /etc/nginx/ssl/root-ca.pem;

    location / {
        proxy_pass http://backend:8000;
    }
}

# HTTP to HTTPS redirect
server {
    listen 80;
    server_name api.example.internal;
    return 301 https://$host$request_uri;
}
```

#### Mutual TLS (mTLS) Configuration

```nginx
server {
    listen 443 ssl;
    server_name api.example.internal;

    ssl_certificate     /etc/nginx/ssl/api.example.internal-chain.pem;
    ssl_certificate_key /etc/nginx/ssl/api.example.internal-key.pem;

    # Client certificate verification
    ssl_client_certificate /etc/nginx/ssl/root-ca.pem;
    ssl_verify_client on;          # require client cert
    # ssl_verify_client optional;  # request but don't require
    ssl_verify_depth 2;            # allow root -> intermediate -> client

    location / {
        # Pass client cert info to backend
        proxy_set_header X-SSL-Client-CN $ssl_client_s_dn_cn;
        proxy_set_header X-SSL-Client-Verify $ssl_client_verify;
        proxy_pass http://backend:8000;
    }
}
```

#### Installation Steps

```bash
# Create directory
sudo mkdir -p /etc/nginx/ssl

# Copy files (from bundle ZIP)
sudo cp api.example.internal-chain.pem /etc/nginx/ssl/
sudo cp api.example.internal-key.pem /etc/nginx/ssl/
sudo cp root-ca.pem /etc/nginx/ssl/

# Set permissions
sudo chmod 644 /etc/nginx/ssl/*.pem
sudo chmod 600 /etc/nginx/ssl/*-key.pem
sudo chown root:root /etc/nginx/ssl/*

# Test configuration
sudo nginx -t

# Reload
sudo systemctl reload nginx

# Verify
curl -v --cacert root-ca.pem https://api.example.internal/
```

#### Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `cannot load certificate key` | Key file encrypted or wrong format | Ensure key has no passphrase: `openssl rsa -in key.pem -out key-nopass.pem` |
| `certificate chain is incomplete` | Missing intermediate in chain file | Use `<cn>-chain.pem` (not `<cn>-cert.pem`) |
| `SSL_CTX_use_PrivateKey` | Key doesn't match certificate | Use the Key Match tool to verify |

---

### 16.2 MySQL / MariaDB

#### Certificate Requirements

| Item | File | my.cnf variable |
|------|------|----------------|
| Server certificate | `<cn>-cert.pem` | `ssl_cert` |
| Private key | `<cn>-key.pem` | `ssl_key` |
| CA certificate | `root-ca.pem` | `ssl_ca` |

The SANs on the server certificate should include the MySQL server's hostname and/or IP address.

#### Server Configuration (my.cnf)

```ini
[mysqld]
# SSL/TLS configuration
ssl_cert = /etc/mysql/ssl/mysql-server-cert.pem
ssl_key  = /etc/mysql/ssl/mysql-server-key.pem
ssl_ca   = /etc/mysql/ssl/root-ca.pem

# Require TLS for all connections (optional but recommended)
require_secure_transport = ON

# TLS version restrictions
tls_version = TLSv1.2,TLSv1.3

# For mutual TLS (require client certificates)
# ssl_ca is used to verify client certs
# Then grant with: GRANT ... REQUIRE X509;
```

#### Client Configuration

```ini
[client]
ssl_ca   = /etc/mysql/ssl/root-ca.pem
ssl_mode = VERIFY_IDENTITY

# For mTLS (client certificate auth)
# ssl_cert = /etc/mysql/ssl/client-cert.pem
# ssl_key  = /etc/mysql/ssl/client-key.pem
```

#### Installation Steps

```bash
# Create directory
sudo mkdir -p /etc/mysql/ssl

# Copy files
sudo cp mysql-server-cert.pem /etc/mysql/ssl/
sudo cp mysql-server-key.pem /etc/mysql/ssl/
sudo cp root-ca.pem /etc/mysql/ssl/

# Set ownership (mysql user must read these)
sudo chown mysql:mysql /etc/mysql/ssl/*
sudo chmod 644 /etc/mysql/ssl/mysql-server-cert.pem
sudo chmod 644 /etc/mysql/ssl/root-ca.pem
sudo chmod 600 /etc/mysql/ssl/mysql-server-key.pem

# Restart MySQL
sudo systemctl restart mysql

# Verify SSL is active
mysql -u root -e "SHOW VARIABLES LIKE '%ssl%';"
mysql -u root -e "SHOW STATUS LIKE 'Ssl_cipher';"
```

#### Connection String Examples

```bash
# MySQL CLI with TLS
mysql -h db.example.internal -u app_user -p \
  --ssl-ca=/etc/mysql/ssl/root-ca.pem \
  --ssl-mode=VERIFY_IDENTITY

# Python (PyMySQL)
import pymysql
conn = pymysql.connect(
    host='db.example.internal',
    user='app_user',
    password='<password>',
    ssl={'ca': '/etc/mysql/ssl/root-ca.pem'}
)

# JDBC (Java)
jdbc:mysql://db.example.internal:3306/mydb?
  useSSL=true&
  requireSSL=true&
  verifyServerCertificate=true&
  trustCertificateKeyStoreUrl=file:/path/to/truststore.jks&
  trustCertificateKeyStorePassword=<password>
```

#### Require TLS Per User

```sql
-- Create user requiring TLS
CREATE USER 'app_user'@'%' IDENTIFIED BY '<password>' REQUIRE SSL;

-- Require specific client certificate (mTLS)
CREATE USER 'secure_user'@'%' IDENTIFIED BY '<password>' REQUIRE X509;

-- Require specific issuer
CREATE USER 'strict_user'@'%' IDENTIFIED BY '<password>'
  REQUIRE ISSUER '/CN=Internal Root CA/O=MyOrg';
```

#### Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `SSL connection error: SSL_CTX_use_certificate` | Cert format wrong or chain issue | Use leaf cert only (not chain) for `ssl_cert` |
| `ERROR 2026 (HY000): SSL connection error` | CA not trusted by client | Ensure client has `--ssl-ca` pointing to `root-ca.pem` |
| `certificate verify failed` | Hostname doesn't match SAN | Ensure cert has MySQL server's hostname as a DNS SAN |

---

### 16.3 RabbitMQ

#### Certificate Requirements

| Item | File | Config key |
|------|------|------------|
| Server certificate | `<cn>-cert.pem` | `ssl_options.certfile` |
| Private key | `<cn>-key.pem` | `ssl_options.keyfile` |
| CA certificate | `root-ca.pem` | `ssl_options.cacertfile` |

SANs should include the RabbitMQ node hostname (e.g. `rabbit.example.internal`).

#### Server Configuration (rabbitmq.conf)

```ini
# Enable TLS listener
listeners.ssl.default = 5671

# Certificate files
ssl_options.certfile   = /etc/rabbitmq/ssl/rabbit-cert.pem
ssl_options.keyfile    = /etc/rabbitmq/ssl/rabbit-key.pem
ssl_options.cacertfile = /etc/rabbitmq/ssl/root-ca.pem

# TLS version
ssl_options.versions.1 = tlsv1.2
ssl_options.versions.2 = tlsv1.3

# Verify clients (mTLS)
ssl_options.verify     = verify_peer
ssl_options.fail_if_no_peer_cert = true

# Disable plain TCP listener (force TLS)
# listeners.tcp = none
```

#### Management UI TLS (rabbitmq.conf)

```ini
# Management plugin over TLS
management.ssl.port       = 15671
management.ssl.certfile   = /etc/rabbitmq/ssl/rabbit-cert.pem
management.ssl.keyfile    = /etc/rabbitmq/ssl/rabbit-key.pem
management.ssl.cacertfile = /etc/rabbitmq/ssl/root-ca.pem
```

#### Installation Steps

```bash
# Create directory
sudo mkdir -p /etc/rabbitmq/ssl

# Copy files
sudo cp rabbit-cert.pem /etc/rabbitmq/ssl/
sudo cp rabbit-key.pem /etc/rabbitmq/ssl/
sudo cp root-ca.pem /etc/rabbitmq/ssl/

# Set ownership
sudo chown rabbitmq:rabbitmq /etc/rabbitmq/ssl/*
sudo chmod 644 /etc/rabbitmq/ssl/rabbit-cert.pem
sudo chmod 644 /etc/rabbitmq/ssl/root-ca.pem
sudo chmod 600 /etc/rabbitmq/ssl/rabbit-key.pem

# Restart RabbitMQ
sudo systemctl restart rabbitmq-server

# Verify TLS listener is active
sudo rabbitmq-diagnostics listeners
# Should show: Interface: [::], port: 5671, protocol: amqp/ssl

# Test connection
openssl s_client -connect rabbit.example.internal:5671 \
  -CAfile root-ca.pem
```

#### Client Connection Examples

```python
# Python (pika) with TLS
import ssl
import pika

context = ssl.create_default_context(cafile='/path/to/root-ca.pem')
# For mTLS:
# context.load_cert_chain('/path/to/client-cert.pem', '/path/to/client-key.pem')

connection = pika.BlockingConnection(
    pika.ConnectionParameters(
        host='rabbit.example.internal',
        port=5671,
        ssl_options=pika.SSLOptions(context),
        credentials=pika.PlainCredentials('user', 'pass'),
    )
)
```

```java
// Java (Spring Boot) application.properties
spring.rabbitmq.host=rabbit.example.internal
spring.rabbitmq.port=5671
spring.rabbitmq.ssl.enabled=true
spring.rabbitmq.ssl.trust-store=file:/path/to/truststore.jks
spring.rabbitmq.ssl.trust-store-password=<password>
spring.rabbitmq.ssl.trust-store-type=JKS
# For mTLS:
# spring.rabbitmq.ssl.key-store=file:/path/to/keystore.jks
# spring.rabbitmq.ssl.key-store-password=<password>
```

#### Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `{ssl_upgrade_error, {tls_alert, unknown_ca}}` | Client doesn't trust server CA | Import `root-ca.pem` into client's trust store |
| `{ssl_upgrade_error, {tls_alert, certificate_required}}` | mTLS enabled but client has no cert | Provide client cert or set `fail_if_no_peer_cert = false` |
| `{error, {not_started, rabbit}}` | Key file permissions wrong | Ensure `rabbitmq` user can read key file (0600, owned by rabbitmq) |

---

### 16.4 Java / Spring Boot (Keycloak / Generic)

Java applications use KeyStores and TrustStores rather than PEM files directly. Use the **Trust Store Builder** in this tool to generate these.

#### Concepts

| Store | Purpose | Contents |
|-------|---------|----------|
| **TrustStore** | CAs the application trusts | Root CA (and intermediate CA) certificates |
| **KeyStore** | This server's identity | Server private key + certificate chain |

#### Generating Stores with This Tool

1. **TrustStore**: Go to Trust Store Builder → select your Root CA → set password → download
2. **KeyStore**: Issue a certificate → download as JKS format (or use the bundle ZIP which includes `keystore.jks`)

#### JVM System Properties

```bash
# TrustStore (which CAs to trust)
-Djavax.net.ssl.trustStore=/opt/app/ssl/truststore.jks
-Djavax.net.ssl.trustStorePassword=<password>
-Djavax.net.ssl.trustStoreType=JKS

# KeyStore (this server's certificate)
-Djavax.net.ssl.keyStore=/opt/app/ssl/keystore.jks
-Djavax.net.ssl.keyStorePassword=<password>
-Djavax.net.ssl.keyStoreType=JKS
```

For PKCS#12 (recommended for Java 9+):
```bash
-Djavax.net.ssl.trustStoreType=PKCS12
-Djavax.net.ssl.keyStoreType=PKCS12
```

#### Spring Boot application.properties

```properties
# Server TLS (this app serves HTTPS)
server.port=8443
server.ssl.enabled=true
server.ssl.key-store=classpath:keystore.p12
server.ssl.key-store-password=<password>
server.ssl.key-store-type=PKCS12
server.ssl.key-alias=server

# Trust external services (outgoing connections)
server.ssl.trust-store=classpath:truststore.p12
server.ssl.trust-store-password=<password>
server.ssl.trust-store-type=PKCS12

# Require client certificates (mTLS)
server.ssl.client-auth=need
# server.ssl.client-auth=want  # request but don't require
```

#### Keycloak Specific Configuration

```bash
# Keycloak (Quarkus-based, v17+)
# Place in conf/keycloak.conf

https-certificate-file=/opt/keycloak/ssl/keycloak-cert.pem
https-certificate-key-file=/opt/keycloak/ssl/keycloak-key.pem
https-trust-store-file=/opt/keycloak/ssl/truststore.p12
https-trust-store-password=<password>

# Or using Java KeyStore
https-key-store-file=/opt/keycloak/ssl/keystore.jks
https-key-store-password=<password>

# Enable HTTPS
https-port=8443
http-enabled=false
```

#### Installation Steps (Generic Java App)

```bash
# Create directory
mkdir -p /opt/app/ssl

# Copy truststore and keystore from this tool's downloads
cp truststore.jks /opt/app/ssl/
cp keystore.jks /opt/app/ssl/

# Set permissions
chmod 600 /opt/app/ssl/*.jks
chown appuser:appuser /opt/app/ssl/*

# Verify keystore contents
keytool -list -v -keystore /opt/app/ssl/keystore.jks -storepass <password>

# Verify truststore contents
keytool -list -keystore /opt/app/ssl/truststore.jks -storepass <password>

# Start application with JVM properties
java -Djavax.net.ssl.trustStore=/opt/app/ssl/truststore.jks \
     -Djavax.net.ssl.trustStorePassword=<password> \
     -Djavax.net.ssl.keyStore=/opt/app/ssl/keystore.jks \
     -Djavax.net.ssl.keyStorePassword=<password> \
     -jar app.jar
```

#### Import CA into Default JVM TrustStore

To trust your internal CA system-wide for all Java apps on a host:

```bash
# Find the default cacerts
find $JAVA_HOME -name cacerts
# Usually: $JAVA_HOME/lib/security/cacerts

# Import root CA
keytool -importcert \
  -alias internal-root-ca \
  -file root-ca.pem \
  -keystore $JAVA_HOME/lib/security/cacerts \
  -storepass changeit \
  -noprompt

# Verify
keytool -list -keystore $JAVA_HOME/lib/security/cacerts \
  -storepass changeit | grep internal-root-ca
```

#### Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `PKIX path building failed` | CA not in truststore | Import root CA into truststore or JVM cacerts |
| `java.security.UnrecoverableKeyException` | Wrong keystore password | Verify password; regenerate keystore if lost |
| `Hostname verification failed` | Cert CN/SAN doesn't match hostname | Ensure cert has the service hostname as a DNS SAN |
| `DerInputStream.getLength(): lengthTag=109` | Wrong store type (JKS vs PKCS12) | Match `-Djavax.net.ssl.trustStoreType` to actual file format |
| `java.io.IOException: Invalid keystore format` | File corrupted or wrong format | Re-download from this tool; verify with `keytool -list` |

---

### 16.5 OpenStack Keystone

Keystone can be configured for TLS both on its public API endpoint and for secure communication with backend services.

#### Certificate Requirements

| Item | File | Config key |
|------|------|------------|
| Server certificate + chain | `<cn>-chain.pem` | Apache/Nginx vhost |
| Private key | `<cn>-key.pem` | Apache/Nginx vhost |
| CA certificate | `root-ca.pem` | `[ssl]` section for service-to-service |

SANs should include the Keystone endpoint hostname (e.g. `keystone.example.internal`, `identity.example.internal`).

#### Apache Configuration (Keystone typically runs behind Apache mod_wsgi)

```apache
<VirtualHost *:5000>
    ServerName keystone.example.internal

    SSLEngine on
    SSLCertificateFile      /etc/keystone/ssl/keystone-chain.pem
    SSLCertificateKeyFile   /etc/keystone/ssl/keystone-key.pem
    SSLCACertificateFile    /etc/keystone/ssl/root-ca.pem

    SSLProtocol             all -SSLv3 -TLSv1 -TLSv1.1
    SSLCipherSuite          HIGH:!aNULL:!MD5

    WSGIDaemonProcess keystone-public processes=5 threads=1 \
        user=keystone group=keystone display-name=%{GROUP}
    WSGIProcessGroup keystone-public
    WSGIScriptAlias / /usr/bin/keystone-wsgi-public
    WSGIApplicationGroup %{GLOBAL}
    WSGIPassAuthorization On

    <Directory /usr/bin>
        Require all granted
    </Directory>
</VirtualHost>
```

#### Keystone Configuration (keystone.conf)

```ini
[DEFAULT]
# Public endpoint URL (HTTPS)
public_endpoint = https://keystone.example.internal:5000

[ssl]
# For Keystone as a TLS client (calling other services)
certfile = /etc/keystone/ssl/keystone-cert.pem
keyfile = /etc/keystone/ssl/keystone-key.pem
ca_certs = /etc/keystone/ssl/root-ca.pem
```

#### OpenStack Service Catalogue (HTTPS endpoints)

```bash
# Update service endpoints to use HTTPS
openstack endpoint set --url https://keystone.example.internal:5000/v3 <endpoint_id>

# Or during creation
openstack endpoint create --region RegionOne \
  identity public https://keystone.example.internal:5000/v3
openstack endpoint create --region RegionOne \
  identity internal https://keystone.example.internal:5000/v3
openstack endpoint create --region RegionOne \
  identity admin https://keystone.example.internal:5000/v3
```

#### Other OpenStack Services (connecting to Keystone over TLS)

Every OpenStack service that authenticates against Keystone needs to trust your CA. In each service's config:

```ini
# nova.conf, neutron.conf, glance.conf, etc.
[keystone_authtoken]
auth_url = https://keystone.example.internal:5000
cafile = /etc/ssl/certs/root-ca.pem
# Or install root CA system-wide and use:
# cafile = /etc/ssl/certs/ca-certificates.crt

[ssl]
ca_file = /etc/ssl/certs/root-ca.pem
```

#### Installation Steps

```bash
# Create directory
sudo mkdir -p /etc/keystone/ssl

# Copy files
sudo cp keystone-chain.pem /etc/keystone/ssl/
sudo cp keystone-key.pem /etc/keystone/ssl/
sudo cp root-ca.pem /etc/keystone/ssl/

# Set permissions
sudo chown keystone:keystone /etc/keystone/ssl/*
sudo chmod 644 /etc/keystone/ssl/keystone-chain.pem
sudo chmod 644 /etc/keystone/ssl/root-ca.pem
sudo chmod 600 /etc/keystone/ssl/keystone-key.pem

# Install root CA system-wide (for all services on this host)
sudo cp root-ca.pem /usr/local/share/ca-certificates/internal-root-ca.crt
sudo update-ca-certificates

# Restart Apache
sudo systemctl restart apache2

# Verify
curl --cacert root-ca.pem https://keystone.example.internal:5000/v3/
openstack --os-cacert root-ca.pem token issue
```

#### OpenStack Client Configuration

```bash
# Environment variables (openrc)
export OS_AUTH_URL=https://keystone.example.internal:5000/v3
export OS_CACERT=/path/to/root-ca.pem

# Or in clouds.yaml
clouds:
  mycloud:
    auth:
      auth_url: https://keystone.example.internal:5000/v3
    cacert: /path/to/root-ca.pem
```

#### Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `SSL: CERTIFICATE_VERIFY_FAILED` | Service doesn't trust your CA | Add `cafile = /path/to/root-ca.pem` in service config or install CA system-wide |
| `ConnectTimeoutError` after switching to HTTPS | Firewall blocking 5000/tcp or endpoint URL wrong | Check endpoint URLs in catalogue; verify port is open |
| `SSLError: hostname doesn't match` | Cert SAN missing the hostname | Re-issue cert with correct SANs |
| `Unable to establish connection to https://...` | Apache not listening on HTTPS | Check `apachectl -S` shows the SSL vhost; verify mod_ssl enabled |

---

### 16.6 Quick Reference: Files Per Service

| Service | Cert File | Key File | CA File | Format | Notes |
|---------|-----------|----------|---------|--------|-------|
| Nginx | chain.pem | key.pem | root-ca.pem (mTLS only) | PEM | Chain must be leaf-first |
| MySQL | cert.pem | key.pem | root-ca.pem | PEM | Leaf cert only (not chain) for `ssl_cert` |
| RabbitMQ | cert.pem | key.pem | root-ca.pem | PEM | Owned by rabbitmq user |
| Java/Spring | keystore.jks/.p12 | (inside keystore) | truststore.jks/.p12 | JKS/PKCS12 | Use Trust Store Builder |
| Keycloak | cert.pem or keystore | key.pem or keystore | truststore.p12 | PEM or JKS/P12 | Quarkus config or JVM props |
| Keystone | chain.pem | key.pem | root-ca.pem | PEM | Apache vhost; install CA system-wide |

---

The **Tools** page (accessible via the sidebar) provides debugging and utility tools for working with certificates from any source — not just those issued by this tool.

### Decode Certificate

Decode any certificate to inspect its contents:
- **Upload a file** (.pem, .crt, .cer, .der) OR **paste PEM** text
- Shows: subject, issuer, serial, SANs, validity, key algorithm, fingerprints, extensions
- Useful for debugging TLS errors when you need to inspect a cert from any source

### Remote Server Certificate Check

Connect to any server and inspect its live TLS certificate:
1. Enter hostname (e.g. `google.com`, `api.internal.local`)
2. Enter port (default 443)
3. Click **Check**

Shows:
- Certificate subject and issuer
- All SANs with hostname match highlighting
- Expiry and days remaining
- Whether the hostname matches the certificate's SANs
- SHA-256 fingerprint

Useful for answering "what cert is this server actually presenting?" without needing `openssl s_client`.

### Verify Certificate Chain

Verify a certificate chain is complete and all signatures are valid:
- Upload or paste the **leaf certificate**
- Upload or paste the **CA chain** (intermediate + root PEM bundle)
- Tool checks each link: issuer DN match + cryptographic signature verification
- Shows pass/fail per chain link

Catches misconfigurations (missing intermediates, wrong chain order) before deploying to a server.

### Key / Certificate Match Checker

Confirm a private key matches a certificate:
- Upload both files
- Tool compares the public key embedded in each
- Reports match or mismatch

Prevents "key mismatch" errors when deploying certificates to servers.

### Format Converter (PEM ↔ DER)

Convert certificates between PEM (Base64 text) and DER (binary) formats:
- Upload a file in either format
- Select output format
- Download the converted file

### Build PKCS#12 (.p12)

Combine existing cert + key + chain into a password-protected .p12 bundle:
- Upload certificate file
- Upload private key file
- Optionally upload CA chain
- Set P12 export password
- Download the .p12 file

Useful when migrating certificates between systems or importing into Windows/Java without issuing anything new.

### Service Compatibility Check

Validate that a certificate meets all requirements for a specific service before deploying:

1. Select target service: **Nginx**, **MySQL/MariaDB**, **RabbitMQ**, **Java/Spring Boot**, **Keycloak**, or **OpenStack Keystone**
2. Upload the certificate file
3. Optionally upload the private key (enables encryption and key-match checks)
4. Optionally enter the expected hostname (enables SAN hostname match check)
5. Click **Check Compatibility**

The tool runs up to 18 service-specific and cryptographic integrity checks:

**Service-specific checks:**

| Check | What It Validates |
|-------|-------------------|
| PEM format | Does the service require PEM? |
| Key algorithm | Is RSA/ECDSA/Ed25519 supported? |
| Key size | Meets minimum 2048-bit for RSA? |
| SAN present | Has Subject Alternative Names? |
| Hostname match | Does a SAN match the expected service hostname? |
| Extended Key Usage | Has serverAuth EKU? |
| Validity | Not expired? Expiring soon? |
| Not a CA | Is CA:FALSE? |
| Chain in cert file | Full chain (Nginx) or leaf only (MySQL)? |
| Key unencrypted | No passphrase? (Nginx, MySQL, RabbitMQ) |
| Key matches cert | Public keys match? |
| Key integrity | Can the private key produce valid signatures? |

**Cryptographic quality checks:**

| Check | What It Validates |
|-------|-------------------|
| Signature algorithm | Reject SHA-1/MD5; pass SHA-256+ |
| Not yet valid | notBefore not in the future |
| Validity period | Warn >398 days or <30 days |
| CN in SAN | CN also present as a SAN entry (best practice) |
| Wildcard depth | Single-level wildcards only |
| Key usage consistency | Correct key usage for key type (RSA vs ECDSA) |
| Chain cert validity | All intermediates and root not expired |
| Chain order | Correct order: leaf → intermediate → root |
| Chain signatures | Cryptographic verification of every chain link |
| CA key size | Warn if CA certs use RSA < 4096 |

### Chain Expiry Check

Upload a full certificate chain and check every certificate for validity:
- Identifies the **weakest link** (cert closest to expiry)
- Shows each cert: CN, type (leaf/intermediate/root), issuer, days remaining
- Catches the invisible "expired intermediate" problem that breaks production

Input: Upload PEM chain file or paste PEM text.

### Connection Tester

Simulate a full TLS handshake to a remote server with custom trust:
1. Enter hostname and port
2. Optionally upload a custom CA file (PEM) for trust
3. Optionally upload client cert + key for mTLS testing
4. Click **Test Connection**

Reports:
- Success/failure with exact error
- TLS version negotiated
- Cipher suite selected
- Server certificate details (CN, issuer, SANs, expiry)
- Hostname match verification
- Java-equivalent error message (if failure)

Useful for answering: "Will my Java app be able to connect to this server with this truststore?"

### Java Debug Command Generator

Generate ready-to-use JVM debug flags for troubleshooting:
1. Select service type (MySQL, RabbitMQ, Spring Boot, generic)
2. Select issue type (connection failure, trust error, hostname mismatch, mTLS, session)
3. Enter connection details and truststore path
4. Click **Generate Commands**

Produces:
- Full `java` command with appropriate `-Djavax.net.debug` flags
- Equivalent `openssl s_client` command for comparison
- `keytool` command to verify truststore contents
- What to search for in the debug output
- Service-specific tips

### OpenSSL Command Generator

Generate a complete set of openssl commands for any certificate:
1. Enter hostname, port, and certificate CN
2. Select target service
3. Optionally enable mTLS commands

Produces grouped commands with copy buttons:
- **Inspect**: view subject, SANs, expiry, fingerprint
- **Verify**: chain verification against CA
- **Key match**: compare cert and key modulus
- **Connection test**: `s_client` commands with various flags
- **Expiry**: check scripts and monitoring one-liners
- **Convert**: PEM ↔ DER, build P12, extract from P12
- **Service-specific**: Nginx reload, MySQL status, RabbitMQ diagnostics, keytool commands

### Build KeyStore (PEM → JKS/P12)

Convert PEM files into a Java KeyStore:
- Upload certificate, private key, and optional CA chain
- Choose output type: PKCS#12 (recommended) or JKS
- Set password and alias
- Download ready-to-use keystore

### Merge TrustStores

Merge multiple PEM bundles or truststores into one:
- Upload multiple files (system cacerts export + your internal root CA)
- Deduplicates certificates automatically
- Produces a single truststore (JKS or PKCS#12)

Solves the #1 Java gotcha: custom truststore replacing all default trust.

### Bulk Certificate Import

Import multiple existing certificates into the inventory:
- Select multiple .pem/.crt/.cer/.der files
- Optionally apply tags and source label
- Deduplicates by serial number
- Reports per-file: imported, skipped (duplicate), or failed

Useful when migrating from another system or inventorying existing infrastructure.

---

## 15. API Quick Reference

All endpoints require `X-API-Key` header (except `/api/v1/health`).

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/health` | Health check (no auth) |
| POST | `/api/v1/auth/login` | Authenticate (returns JWT token) |
| GET | `/api/v1/auth/me` | Current user info |
| POST | `/api/v1/auth/change-password` | Change password (JWT auth only) |
| GET | `/api/v1/users` | List users (admin only) |
| POST | `/api/v1/users` | Create user (admin only) |
| PUT | `/api/v1/users/{id}` | Update user (admin only) |
| DELETE | `/api/v1/users/{id}` | Delete user (admin only) |
| GET | `/api/v1/api-keys` | List scoped API keys (admin only) |
| POST | `/api/v1/api-keys` | Create scoped API key (admin only) |
| DELETE | `/api/v1/api-keys/{id}` | Revoke scoped API key (admin only) |
| POST | `/api/v1/settings/rotate-api-key` | Rotate legacy API key (admin only) |
| POST | `/api/v1/ca` | Create CA |
| GET | `/api/v1/ca` | List CAs |
| GET | `/api/v1/ca/{id}` | CA detail |
| POST | `/api/v1/cert` | Issue certificate |
| GET | `/api/v1/cert` | List certificates |
| GET | `/api/v1/cert/{serial}` | Certificate detail |
| GET | `/api/v1/cert/{serial}/inspect` | Decoded certificate inspector |
| DELETE | `/api/v1/cert/{serial}` | Revoke certificate |
| POST | `/api/v1/cert/{serial}/hold` | Place certificate on hold (temporary revocation) |
| POST | `/api/v1/cert/{serial}/unhold` | Remove certificate from hold |
| POST | `/api/v1/cert/{serial}/renew` | Renew certificate (same or new key) |
| PATCH | `/api/v1/cert/{serial}/auto-renew` | Enable/disable auto-renewal |
| GET | `/api/v1/export/{serial}/{fmt}` | Export certificate (supports `chain_mode` and `platform` params) |
| GET | `/api/v1/export/validate-chain/{serial}` | Validate certificate chain cryptographically |
| POST | `/api/v1/truststore` | Build truststore |
| GET | `/api/v1/truststore/{id}` | Download truststore |
| GET | `/api/v1/crl/{ca_id}` | Download CRL |
| POST | `/api/v1/csr` | Generate CSR (new key) |
| POST | `/api/v1/csr/upload` | Generate CSR (existing key) |
| POST | `/api/v1/csr/renew` | Generate CSR from existing cert (auto-extract) |
| GET | `/api/v1/csr` | List CSRs |
| POST | `/api/v1/csr/{id}/sign` | Sign CSR with internal CA |
| POST | `/api/v1/csr/{id}/import-cert` | Import externally signed cert |
| GET | `/api/v1/csr/{id}/export/{fmt}` | Export CSR |
| DELETE | `/api/v1/csr/{id}` | Delete CSR |
| GET | `/api/v1/audit` | Audit log (paginated) |
| POST | `/api/v1/backup` | Create backup |
| GET | `/api/v1/backup` | List backups |
| GET | `/api/v1/backup/{filename}` | Download backup |
| DELETE | `/api/v1/backup/{filename}` | Delete backup |
| POST | `/api/v1/tools/decode` | Decode any certificate (file or PEM) |
| POST | `/api/v1/tools/remote-check` | Check remote server's TLS cert |
| POST | `/api/v1/tools/verify-chain` | Verify certificate chain |
| POST | `/api/v1/tools/key-match` | Check if key matches certificate |
| POST | `/api/v1/tools/convert` | Convert PEM ↔ DER |
| POST | `/api/v1/tools/build-p12` | Build PKCS#12 from cert + key |
| POST | `/api/v1/tools/compatibility-check` | Check cert compatibility with a service |
| POST | `/api/v1/tools/chain-expiry-check` | Check all certs in a chain for expiry |
| POST | `/api/v1/tools/connection-test` | Full TLS handshake simulation |
| POST | `/api/v1/tools/java-debug-command` | Generate Java TLS debug commands |
| POST | `/api/v1/tools/openssl-commands` | Generate openssl commands |
| POST | `/api/v1/tools/build-keystore` | Build JKS/P12 from PEM files |
| POST | `/api/v1/tools/merge-truststores` | Merge multiple truststores |
| POST | `/api/v1/tools/bulk-import` | Bulk import certificates |
| GET | `/api/v1/tools/calendar.ics` | Export expiry dates as ICS calendar |
| GET | `/api/v1/tools/expiry-feed.json` | Export expiry data as JSON feed |
| GET | `/api/v1/diagnostics` | System diagnostics (full environment info) |
| GET | `/api/v1/diagnostics/recent-errors` | Recent application errors (in-memory buffer) |
| POST | `/api/v1/diagnostics/clear-errors` | Clear error buffer |
| GET | `/api/v1/pki/crl/{ca_id}` | Public CRL download (no auth) |
| GET | `/api/v1/pki/ca/{ca_id}/cert` | Public CA cert download (no auth, DER) |
| GET | `/api/v1/pki/info` | PKI status and endpoint URLs |
| POST | `/api/v1/pki/ocsp` | OCSP responder — POST (no auth, RFC 6960) |
| GET | `/api/v1/pki/ocsp/{base64_request}` | OCSP responder — GET (no auth, RFC 6960) |
| GET | `/api/v1/pki/ocsp/status/{serial}` | OCSP status — readable JSON (no auth) |
| GET | `/api/v1/pki/ocsp/staple/{serial}` | OCSP staple generation (auth required) |
| GET | `/api/v1/settings/pki` | Get PKI settings |
| PUT | `/api/v1/settings/pki` | Update PKI settings |
| GET | `/api/v1/approvals` | List pending/approved/rejected requests |
| POST | `/api/v1/approvals/{id}/review` | Approve or reject a pending request (admin) |
| GET | `/api/v1/reports/inventory` | Certificate inventory report |
| GET | `/api/v1/reports/weak-keys` | Weak cryptographic key report |
| GET | `/api/v1/reports/expiry-forecast` | 30/60/90 day expiry forecast |
| GET | `/api/v1/reports/revocations` | Revocation report |
| GET | `/api/v1/reports/audit-export` | Audit log export (JSON/CSV/CEF) |
| GET | `/api/v1/reports/audit-integrity` | Verify audit hash chain integrity |
| POST | `/api/v1/provisioning/generate` | Generate environment SSL bundle (admin, operator) |
| POST | `/api/v1/provisioning/templates` | Save provisioning template (admin) |
| GET | `/api/v1/provisioning/templates` | List provisioning templates |
| GET | `/api/v1/provisioning/templates/{id}` | Load provisioning template |
| PUT | `/api/v1/provisioning/templates/{id}` | Update provisioning template (admin) |
| DELETE | `/api/v1/provisioning/templates/{id}` | Delete provisioning template (admin) |
| GET | `/api/v1/provisioning/cipher-profiles` | List available cipher profiles |
| POST | `/api/v1/ca/import` | Import external CA (cert only, no key) |
| POST | `/api/v1/ca/{id}/signing-session` | Start signing session (temporary key upload) |
| GET | `/api/v1/ca/{id}/signing-session` | Check signing session status |
| DELETE | `/api/v1/ca/{id}/signing-session` | End signing session |
| POST | `/api/v1/ca/{id}/signing-session/sign-intermediate` | Sign intermediate CA during session |
| PUT | `/api/v1/ca/{id}/serial-format` | Configure serial number format (admin) |
| GET | `/api/v1/ca/{id}/serial-format` | Get serial number format configuration |
| GET | `/.well-known/est/cacerts` | EST: CA certificate distribution (no auth) |
| POST | `/.well-known/est/simpleenroll` | EST: Initial enrollment (CSR → cert) |
| POST | `/.well-known/est/simplereenroll` | EST: Re-enrollment (renewal) |
| GET | `/.well-known/est/csrattrs` | EST: CSR attributes (no auth) |
| POST | `/.well-known/est/serverkeygen` | EST: Server-side key generation |

---


---

## 17. Java SSL/TLS Deep Dive

This section covers the practical knowledge needed to avoid the common Java SSL pitfalls that cost engineering teams hours of debugging. It goes beyond basic configuration into the "why it fails" and "how to fix it" territory.

---

### 17.1 How Java TLS Trust Works

Java does **not** use the operating system's certificate store. It maintains its own trust independently:

```
┌─────────────────────────────────────────────────────┐
│ JVM Process                                          │
│                                                      │
│  ┌─────────────────────────────────────────────┐    │
│  │ JSSE (Java Secure Socket Extension)          │    │
│  │                                              │    │
│  │  TrustManager ← loads from TrustStore        │    │
│  │  KeyManager   ← loads from KeyStore          │    │
│  │  HostnameVerifier ← checks SANs only         │    │
│  └─────────────────────────────────────────────┘    │
│                                                      │
│  TrustStore resolution order:                        │
│    1. javax.net.ssl.trustStore (JVM property)        │
│    2. $JAVA_HOME/lib/security/cacerts (default)      │
│    3. NO FALLBACK to OS trust store                  │
└─────────────────────────────────────────────────────┘
```

**Key implication:** Installing a CA into Linux's `/usr/local/share/ca-certificates/` does NOTHING for Java applications. You must either:
- Import into `$JAVA_HOME/lib/security/cacerts` (affects all Java apps on that host)
- Provide a custom truststore via `-Djavax.net.ssl.trustStore` (affects only that app)

---

### 17.2 Hostname Verification (The #1 Java SSL Problem)

Since Java 7, JSSE enforces **RFC 2818 strictly**: it checks ONLY the Subject Alternative Name (SAN) extension. The Common Name (CN) field is completely ignored.

**This means:**

```
Certificate with:
  Subject: CN=api.example.com
  SAN: (empty)

Result: javax.net.ssl.SSLPeerUnverifiedException:
  Hostname 'api.example.com' not verified
```

Even though the CN matches, Java refuses because there's no SAN.

**The fix:** Every server certificate MUST have at least one DNS SAN entry. This tool enforces this automatically for the Server profile.

**Wildcard matching rules in Java:**

| SAN | Matches | Does NOT Match |
|-----|---------|----------------|
| `*.example.com` | `api.example.com`, `www.example.com` | `example.com`, `a.b.example.com` |
| `api.example.com` | `api.example.com` only | `API.example.com` (case-sensitive in some versions) |

**IP address matching:** Java requires IP SANs as `iPAddress` type, not DNS type. Using `DNS:10.0.1.50` will NOT match connections to `10.0.1.50`. Use `IP:10.0.1.50`.

---

### 17.3 The cacerts File

Every JDK/JRE ships with a default truststore at:

```
$JAVA_HOME/lib/security/cacerts
```

- Default password: `changeit`
- Format: JKS (Java 8 and below) or PKCS12 (Java 9+)
- Contains: ~100 public CA certificates (same as browsers)
- Does NOT contain your internal/self-signed CAs

**Finding cacerts on your system:**

```bash
# Find all cacerts files (multiple JDKs may be installed)
find / -name cacerts -path "*/security/*" 2>/dev/null

# Check which Java is actually running your app
ls -la /proc/<PID>/exe
# Then look for cacerts relative to that binary

# Common locations:
# /usr/lib/jvm/java-17-openjdk-amd64/lib/security/cacerts
# /usr/lib/jvm/java-11-openjdk-amd64/lib/security/cacerts
# /etc/ssl/certs/java/cacerts (Debian symlink)
```

**Importing your internal CA:**

```bash
# Import (must run as root or the user owning cacerts)
keytool -importcert \
  -alias internal-root-ca \
  -file root-ca.pem \
  -keystore $JAVA_HOME/lib/security/cacerts \
  -storepass changeit \
  -noprompt

# Verify import
keytool -list \
  -keystore $JAVA_HOME/lib/security/cacerts \
  -storepass changeit \
  -alias internal-root-ca

# List all entries (pipe to grep to find yours)
keytool -list \
  -keystore $JAVA_HOME/lib/security/cacerts \
  -storepass changeit | grep -i internal
```

**Warning:** When you upgrade the JDK package, the cacerts file may be REPLACED, removing your custom CA. Solutions:
- Use a separate truststore (`-Djavax.net.ssl.trustStore`) instead of modifying cacerts
- Use a post-install hook in your deployment to re-import
- Use Debian's `update-ca-certificates` which manages the Java cacerts symlink

---

### 17.4 Custom TrustStore vs cacerts (When to Use Which)

| Approach | Use When | Pros | Cons |
|----------|----------|------|------|
| Modify cacerts | All Java apps on this host need your CA | Simple; no per-app config | Lost on JDK upgrade; affects all apps; requires root |
| Custom truststore (JVM prop) | App needs specific CAs only | Isolated; portable; no root needed | Must include ALL needed CAs (public + internal) or app can't reach public HTTPS endpoints |
| Custom truststore (programmatic) | Different connections need different trust | Most flexible | Code complexity |

**Critical gotcha with custom truststores:**

If you set `-Djavax.net.ssl.trustStore=/path/to/my-truststore.jks`, Java uses ONLY that file. The default cacerts is completely ignored. This means if your truststore only contains your internal CA, the app cannot connect to public HTTPS services (AWS APIs, Docker registries, etc.).

**Solution: Merge public + internal CAs into your truststore:**

```bash
# Start from a copy of cacerts (includes all public CAs)
cp $JAVA_HOME/lib/security/cacerts /opt/app/ssl/truststore.jks

# Add your internal CA
keytool -importcert \
  -alias internal-root-ca \
  -file root-ca.pem \
  -keystore /opt/app/ssl/truststore.jks \
  -storepass changeit \
  -noprompt
```

Or use this tool's Trust Store Builder + manually merge with cacerts.

---

### 17.5 JKS vs PKCS12

| Feature | JKS | PKCS12 |
|---------|-----|--------|
| Default in | Java 8 and below | Java 9+ |
| Standard | Proprietary (Oracle) | Industry standard (RFC 7292) |
| Cross-platform | Java only | Windows, macOS, browsers, OpenSSL, Java |
| Encryption | Weak (PBE/MD5/DES) | Strong (AES-256-CBC) |
| Recommendation | Avoid for new deployments | **Use this** |

**Detecting format:**

```bash
# This works for both formats
keytool -list -keystore store.jks -storepass <password>
# Look for "Keystore type:" in output

# If you get "Invalid keystore format" try:
keytool -list -keystore store.p12 -storetype PKCS12 -storepass <password>
```

**Converting JKS → PKCS12:**

```bash
keytool -importkeystore \
  -srckeystore old-keystore.jks \
  -srcstoretype JKS \
  -srcstorepass <old-password> \
  -destkeystore new-keystore.p12 \
  -deststoretype PKCS12 \
  -deststorepass <new-password>
```

**Java 9+ default behaviour:**

Java 9 changed the default keystore type to PKCS12. If your app reads `javax.net.ssl.trustStoreType` defaulting to "JKS" but your file is PKCS12, you'll get:

```
java.io.IOException: Invalid keystore format
```

Fix: explicitly set `-Djavax.net.ssl.trustStoreType=PKCS12`

---

### 17.6 Debugging Java SSL (javax.net.debug)

The single most useful debugging tool for Java SSL issues:

```bash
# Full SSL debug output (verbose — thousands of lines)
java -Djavax.net.debug=ssl -jar app.jar

# Just handshake (most useful for diagnosing connection failures)
java -Djavax.net.debug=ssl:handshake -jar app.jar

# Handshake + certificate chain
java -Djavax.net.debug=ssl:handshake:verbose -jar app.jar

# Trust manager decisions (which CAs are being checked)
java -Djavax.net.debug=ssl:trustmanager -jar app.jar

# Session details
java -Djavax.net.debug=ssl:session -jar app.jar
```

**What to look for in the output:**

```
# Successful trust:
"Found trusted certificate"
"CertificateVerify: ... verified"

# Trust failure (PKIX path building failed):
"PKIX path building failed"
"unable to find valid certification path to requested target"
# → Your CA is not in the truststore

# Hostname verification failure:
"No subject alternative names matching IP address X.X.X.X found"
"Hostname X not verified"
# → Certificate missing required SAN

# Certificate expired:
"NotAfter: ..."
"PKIX path validation failed: ... timestamp check failed"
# → Check all certs in chain, not just leaf

# Wrong keystore password:
"java.security.UnrecoverableKeyException: Password verification failed"
```

**Spring Boot debug logging (alternative):**

```properties
# application.properties
logging.level.javax.net.ssl=DEBUG
logging.level.sun.security.ssl=DEBUG
```

---

### 17.7 Mutual TLS (mTLS) in Java

For services that require client certificates (RabbitMQ with `verify_peer`, internal APIs):

**Server side (requiring client certs):**

```properties
# Spring Boot
server.ssl.client-auth=need
server.ssl.trust-store=classpath:truststore.p12
server.ssl.trust-store-password=<password>
```

**Client side (presenting a client cert):**

```bash
# JVM properties — sets the client's identity for ALL outgoing connections
-Djavax.net.ssl.keyStore=/path/to/client-keystore.p12
-Djavax.net.ssl.keyStorePassword=<password>
-Djavax.net.ssl.keyStoreType=PKCS12
```

**Programmatic (per-connection, e.g. different keystores for different services):**

```java
// Load client keystore
KeyStore clientKs = KeyStore.getInstance("PKCS12");
clientKs.load(new FileInputStream("/path/to/client.p12"), "password".toCharArray());

KeyManagerFactory kmf = KeyManagerFactory.getInstance("SunX509");
kmf.init(clientKs, "password".toCharArray());

// Load truststore
KeyStore trustKs = KeyStore.getInstance("PKCS12");
trustKs.load(new FileInputStream("/path/to/truststore.p12"), "password".toCharArray());

TrustManagerFactory tmf = TrustManagerFactory.getInstance("SunX509");
tmf.init(trustKs);

// Create SSL context
SSLContext ctx = SSLContext.getInstance("TLS");
ctx.init(kmf.getKeyManagers(), tmf.getTrustManagers(), null);

// Use with HttpsURLConnection
HttpsURLConnection conn = (HttpsURLConnection) url.openConnection();
conn.setSSLSocketFactory(ctx.getSocketFactory());

// Or with Apache HttpClient
CloseableHttpClient client = HttpClients.custom()
    .setSSLContext(ctx)
    .build();
```

**Creating a client keystore with this tool:**
1. Issue a **Client (mTLS)** profile certificate
2. Download as `.p12` (PKCS#12) — this is your client keystore
3. Configure the client application with the P12 as its keyStore

---

### 17.8 SNI (Server Name Indication) Issues

SNI allows multiple TLS certificates on one IP. Java supports SNI since Java 7, but some configurations break it:

**Problem:** Java HTTP clients may not send SNI, causing the server to return the wrong certificate.

**Common causes:**
- Connecting by IP address (SNI requires a hostname)
- Using `HttpURLConnection` with IP-based URLs
- Older Java versions with SNI disabled

**Fix for IP-based connections:**

If you must connect by IP, the server certificate needs an IP SAN (`IP:10.0.1.50`), and you may need to disable SNI:

```java
// Disable SNI for a specific connection (Java 8+)
SSLParameters params = sslSocket.getSSLParameters();
params.setServerNames(Collections.emptyList());
sslSocket.setSSLParameters(params);
```

**Fix for hostname-based connections that still fail:**

```java
// Explicitly set the expected hostname for SNI
SSLParameters params = sslSocket.getSSLParameters();
params.setServerNames(Arrays.asList(new SNIHostName("api.example.com")));
sslSocket.setSSLParameters(params);
```

---

### 17.9 Certificate Reload Without Restart

By default, Java loads keystores/truststores once at startup. Certificate changes require a restart. For long-running services this is problematic.

**Option 1: Scheduled restart (simplest)**

```bash
# Cron job: restart service weekly after cert renewal
0 2 * * 0 systemctl restart myapp
```

**Option 2: File-watching TrustManager (Spring Boot 2.7+)**

```yaml
# application.yml — auto-reload on file change
server:
  ssl:
    bundle: "web"

spring:
  ssl:
    bundle:
      pem:
        web:
          reload-on-update: true
          keystore:
            certificate: /opt/app/ssl/cert.pem
            private-key: /opt/app/ssl/key.pem
          truststore:
            certificate: /opt/app/ssl/root-ca.pem
```

**Option 3: Programmatic reload (any Java app)**

```java
// Implement a reloadable TrustManager
public class ReloadableTrustManager implements X509TrustManager {
    private volatile X509TrustManager delegate;
    private final Path trustStorePath;
    private final char[] password;

    public void reload() throws Exception {
        KeyStore ks = KeyStore.getInstance("PKCS12");
        ks.load(Files.newInputStream(trustStorePath), password);
        TrustManagerFactory tmf = TrustManagerFactory.getInstance("SunX509");
        tmf.init(ks);
        delegate = (X509TrustManager) tmf.getTrustManagers()[0];
    }

    @Override
    public void checkServerTrusted(X509Certificate[] chain, String authType)
            throws CertificateException {
        delegate.checkServerTrusted(chain, authType);
    }
    // ... other methods delegate similarly
}
```

---

### 17.10 Connection Pooling and TLS

HTTP connection pools (Apache HttpClient, OkHttp, Spring WebClient) reuse TLS sessions. This creates subtle issues:

**Problem:** After certificate rotation, pooled connections still use the old session. New connections pick up the new cert, but existing ones don't.

**Symptoms:**
- "Works on restart but fails after a few hours" (old sessions expire)
- Intermittent failures (mix of old and new sessions in pool)

**Solutions:**

```java
// Apache HttpClient — set max connection lifetime
PoolingHttpClientConnectionManager cm = new PoolingHttpClientConnectionManager(
    300, TimeUnit.SECONDS  // evict connections older than 5 minutes
);

// OkHttp — set connection pool timeout
OkHttpClient client = new OkHttpClient.Builder()
    .connectionPool(new ConnectionPool(5, 5, TimeUnit.MINUTES))
    .build();

// Spring WebClient — configure connection provider
ConnectionProvider provider = ConnectionProvider.builder("custom")
    .maxLifeTime(Duration.ofMinutes(5))
    .build();
```

---

### 17.11 Multi-Service TLS Configuration

When a Java application connects to multiple internal services (database, message queue, API), each with its own certificate:

**Scenario:** App connects to MySQL (cert A), RabbitMQ (cert B), and an internal API (cert C), all using your internal CA.

**Simplest solution:** One truststore containing your root CA. Since all services use certs signed by the same CA, one trust anchor covers everything:

```bash
-Djavax.net.ssl.trustStore=/opt/app/ssl/truststore.p12  # contains internal root CA
```

**When services use DIFFERENT CAs (e.g. some internal, some external):**

```bash
# Merge all needed CAs into one truststore
keytool -importcert -alias internal-ca -file internal-root-ca.pem \
  -keystore truststore.p12 -storetype PKCS12 -storepass <pw> -noprompt
keytool -importcert -alias external-ca -file external-ca.pem \
  -keystore truststore.p12 -storetype PKCS12 -storepass <pw> -noprompt
```

**When you need DIFFERENT client certs for different services (mTLS):**

You cannot use JVM properties for this (they apply globally). Use programmatic SSLContext per connection — see Section 17.7.

---

### 17.12 Common Java SSL Errors — Complete Reference

| Error | Root Cause | Fix |
|-------|-----------|-----|
| `PKIX path building failed: unable to find valid certification path to requested target` | Server's CA not in client's truststore | Import CA into truststore or cacerts |
| `PKIX path validation failed: java.security.cert.CertPathValidatorException: timestamp check failed` | A certificate in the chain has expired (check ALL certs, not just leaf) | Renew the expired cert; check intermediate CA expiry too |
| `SSLPeerUnverifiedException: Hostname 'X' not verified` | Certificate missing DNS SAN for that hostname | Re-issue cert with correct SANs; CN is NOT checked |
| `No subject alternative names matching IP address X.X.X.X found` | Connecting by IP but cert has no IP SAN | Add IP SAN to cert, or connect by hostname instead |
| `java.security.UnrecoverableKeyException: Password verification failed` | Wrong keystore password | Check password; common mistake: truststore password used for keystore or vice versa |
| `java.io.IOException: Invalid keystore format` | File is PKCS12 but Java expects JKS (or vice versa) | Set `-Djavax.net.ssl.trustStoreType=PKCS12` explicitly |
| `DerInputStream.getLength(): lengthTag=109, too big` | Trying to read PEM as DER, or corrupted file | Ensure file isn't truncated; try converting format |
| `java.io.IOException: Keystore was tampered with, or password was incorrect` | Wrong password OR wrong file OR corrupted store | Verify: `keytool -list -keystore file -storepass <pw>` |
| `SSLHandshakeException: Received fatal alert: handshake_failure` | TLS version mismatch, cipher suite mismatch, or client cert required but not provided | Enable debug: `-Djavax.net.debug=ssl:handshake`; check TLS version and cipher compatibility |
| `SSLHandshakeException: Received fatal alert: certificate_unknown` | Server doesn't trust client cert's CA (mTLS) | Import client CA into server's truststore |
| `SSLHandshakeException: Received fatal alert: bad_certificate` | Client cert is expired, wrong EKU, or key doesn't match | Check client cert validity and extensions |
| `SocketException: Connection reset` | TLS version rejected by server (e.g. TLSv1.0 disabled) | Force TLS 1.2+: `-Dhttps.protocols=TLSv1.2,TLSv1.3` |
| `NoSuchAlgorithmException: Ed25519` | Java version too old for Ed25519 | Ed25519 requires Java 15+; use ECDSA P-256 for Java 11 |
| `SSLException: Unsupported or unrecognized SSL message` | Connecting to non-TLS port, or HTTP instead of HTTPS | Verify port is TLS-enabled; check URL scheme |
| `CertificateException: No name matching X found` | Hostname verifier can't match (similar to SANs issue) | Check certificate SANs; ensure exact match or valid wildcard |
| `PKIX path building failed: ... CertPathReviewerError` | Intermediate CA missing from chain | Include full chain (leaf + intermediate) in keystore |

---

### 17.13 Java Version Compatibility Matrix

| Feature | Java 8 | Java 11 | Java 15 | Java 17 | Java 21 |
|---------|--------|---------|---------|---------|---------|
| TLS 1.2 | ✓ | ✓ | ✓ | ✓ | ✓ |
| TLS 1.3 | ✗ (backport in 8u261) | ✓ | ✓ | ✓ | ✓ |
| PKCS12 default truststore | ✗ (JKS) | ✓ | ✓ | ✓ | ✓ |
| Ed25519 certificates | ✗ | ✗ | ✓ | ✓ | ✓ |
| ECDSA P-256/P-384 | ✓ | ✓ | ✓ | ✓ | ✓ |
| RSA 2048/4096 | ✓ | ✓ | ✓ | ✓ | ✓ |
| SNI support | ✓ | ✓ | ✓ | ✓ | ✓ |
| ALPN (HTTP/2) | ✗ (8u252+) | ✓ | ✓ | ✓ | ✓ |
| Disabled TLS 1.0/1.1 | ✗ | ✗ | ✓ | ✓ | ✓ |
| SHA-1 certs disabled | ✗ | Partial | ✓ | ✓ | ✓ |

**Recommendation:** Use Java 17 LTS minimum. ECDSA P-256 for certificates if all clients are Java 11+.

---

### 17.14 Spring Boot SSL Configuration Patterns

#### Pattern 1: Simple HTTPS server

```properties
server.port=8443
server.ssl.enabled=true
server.ssl.key-store=file:/opt/app/ssl/keystore.p12
server.ssl.key-store-password=${SSL_KEYSTORE_PASSWORD}
server.ssl.key-store-type=PKCS12
server.ssl.key-alias=server
```

#### Pattern 2: HTTPS + custom truststore (for calling other internal services)

```properties
server.ssl.trust-store=file:/opt/app/ssl/truststore.p12
server.ssl.trust-store-password=${SSL_TRUSTSTORE_PASSWORD}
server.ssl.trust-store-type=PKCS12
```

#### Pattern 3: mTLS (require client certificates)

```properties
server.ssl.client-auth=need
# 'need' = require; 'want' = request but allow anonymous; 'none' = disabled
```

#### Pattern 4: WebClient with custom SSL (for calling other services)

```java
@Bean
public WebClient secureWebClient() throws Exception {
    KeyStore trustStore = KeyStore.getInstance("PKCS12");
    trustStore.load(new FileInputStream("/opt/app/ssl/truststore.p12"), 
        "password".toCharArray());

    TrustManagerFactory tmf = TrustManagerFactory.getInstance(
        TrustManagerFactory.getDefaultAlgorithm());
    tmf.init(trustStore);

    SslContext sslContext = SslContextBuilder.forClient()
        .trustManager(tmf)
        .build();

    HttpClient httpClient = HttpClient.create()
        .secure(spec -> spec.sslContext(sslContext));

    return WebClient.builder()
        .clientConnector(new ReactorClientHttpConnector(httpClient))
        .build();
}
```

#### Pattern 5: RestTemplate with custom SSL

```java
@Bean
public RestTemplate secureRestTemplate() throws Exception {
    SSLContext sslContext = SSLContextBuilder.create()
        .loadTrustMaterial(
            new File("/opt/app/ssl/truststore.p12"),
            "password".toCharArray())
        .build();

    HttpClient httpClient = HttpClients.custom()
        .setSSLContext(sslContext)
        .build();

    return new RestTemplate(
        new HttpComponentsClientHttpRequestFactory(httpClient));
}
```

---

### 17.15 Checklist: Deploying Java App with Internal CA

Use this checklist every time you deploy a Java application that needs to trust your internal CA or present a TLS certificate:

- [ ] **Certificate has DNS SANs** (not just CN) matching the service hostname
- [ ] **TrustStore includes your internal root CA** (and public CAs if the app calls external services)
- [ ] **TrustStore type matches JVM property** (`-Djavax.net.ssl.trustStoreType` = actual format)
- [ ] **KeyStore type matches JVM property** (same for keyStore)
- [ ] **Passwords are correct** (trustStorePassword ≠ keyStorePassword if they differ)
- [ ] **No certificate in the chain is expired** (check intermediates too, not just leaf)
- [ ] **Key algorithm is supported by Java version** (Ed25519 → Java 15+; ECDSA → Java 11+)
- [ ] **File permissions allow the Java process user to read the stores** (but not world-readable)
- [ ] **Connection pool lifetime configured** if certificate rotation is expected
- [ ] **Debug flag documented** for future troubleshooting: `-Djavax.net.debug=ssl:handshake`

---


## 18. Calendar & Monitoring Integration

### ICS Calendar Export

Export all certificate expiry dates as an ICS calendar file that can be imported into Outlook, Google Calendar, or Apple Calendar:

```bash
curl -sk -H "X-API-Key: $API_KEY" \
  https://localhost/api/v1/tools/calendar.ics -o ssl-cert-expiry.ics
```

The calendar contains events at 30, 14, and 7 days before each certificate expires. Each event includes:
- Certificate CN
- Serial number
- SANs
- Expiry date
- Profile

Import the `.ics` file into your calendar application for automatic reminders.

### JSON Expiry Feed

For integration with monitoring tools (Prometheus, Zabbix, custom scripts):

```bash
curl -sk -H "X-API-Key: $API_KEY" \
  https://localhost/api/v1/tools/expiry-feed.json
```

Returns a JSON array sorted by urgency (most urgent first):

```json
[
  {
    "serial": "abc123...",
    "cn": "api.example.com",
    "sans": ["api.example.com", "10.0.1.50"],
    "profile": "server",
    "key_algo": "RSA",
    "status": "valid",
    "expires_at": "2025-03-15T00:00:00",
    "days_remaining": 28,
    "signing_ca_id": "uuid...",
    "tags": ["production", "aws"],
    "created_at": "2024-03-15T00:00:00"
  }
]
```

### Monitoring Script Example

```bash
#!/bin/bash
# Check for certs expiring within 14 days
CRITICAL=$(curl -s -H "X-API-Key: $API_KEY" \
  https://localhost/api/v1/tools/expiry-feed.json \
  | python3 -c "import sys,json; data=json.load(sys.stdin); print(sum(1 for c in data if c['days_remaining'] <= 14))")

if [ "$CRITICAL" -gt 0 ]; then
  echo "CRITICAL: $CRITICAL certificates expiring within 14 days"
  exit 2
fi
echo "OK: No urgent certificate renewals"
exit 0
```

### Prometheus Integration (Future)

The JSON feed can be scraped by a custom exporter or used with `json_exporter`:

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'cert-manager'
    metrics_path: /api/v1/tools/expiry-feed.json
    static_configs:
      - targets: ['certs.internal:443']
```

---


## 19. System Diagnostics & Troubleshooting Tools

### System Diagnostics Page

Navigate to **Diagnostics** in the sidebar to view live application state:

**System Info:**
- Operating system and version
- Python version
- Hostname
- Application uptime

**Dependencies:**
- OpenSSL version
- Java version
- Keytool availability and path

**Health Checks:**
- Database connectivity
- Keytool availability
- Data directory writable
- Backup directory writable

**Storage:**
- Data directory size and free disk space
- Database size
- Backup count and last backup timestamp

**Certificate Inventory:**
- Total certificates by status (valid, expired, revoked, expiring soon)
- Total CAs

**Configuration (non-secret):**
- All configured paths, intervals, and limits

Access via API:
```bash
curl -sk -H "X-API-Key: $API_KEY" https://localhost/api/v1/diagnostics | python3 -m json.tool
```

---

### Recent Errors Panel

The Diagnostics page shows a live feed of application errors and warnings — no SSH required.

**How it works:**
- A custom logging handler captures all WARNING and ERROR level log messages into an in-memory ring buffer (last 200 entries)
- The panel auto-refreshes every 15 seconds
- Each entry shows: severity level, timestamp, message, and source file/line number
- "Clear all" button resets the buffer

**Typical errors you'll see:**
- `keytool failed` — JKS/truststore generation issues
- `PKIX path building failed` — chain verification failures
- `Expiry scanner error` — database or connectivity issues during background scan
- `Backup failed` — disk space or permission issues

Access via API:
```bash
# Get last 20 errors
curl -sk -H "X-API-Key: $API_KEY" \
  https://localhost/api/v1/diagnostics/recent-errors?limit=20

# Clear the buffer
curl -sk -X POST -H "X-API-Key: $API_KEY" \
  https://localhost/api/v1/diagnostics/clear-errors
```

**Note:** The error buffer is in-memory only — it resets on application restart. For persistent error history, use the Audit Log (which records all operations) or configure external log shipping.

---

### Certificate Troubleshooter

In the **Tools** page, the **Troubleshooter** tab provides guided debugging for common TLS issues.

**How to use:**
1. Open Tools → Troubleshooter (it's the default tab)
2. Select the error you're experiencing from the cards
3. Follow the guided diagnosis:
   - Plain-English explanation of what the error means
   - Causes ranked by likelihood (high / medium / low)
   - Check commands for each cause (with copy buttons)
   - Fix instructions
   - Links to relevant tools in this application

**Supported scenarios:**

| Scenario | Typical Error Message |
|----------|----------------------|
| Connection refused | `Connection refused`, `Connection timed out` |
| Certificate not trusted | `PKIX path building failed`, `certificate unknown` |
| Hostname mismatch | `Hostname not verified`, `No SANs matching` |
| Certificate expired | `certificate has expired`, `timestamp check failed` |
| Key mismatch | `SSL_CTX_use_PrivateKey`, key modulus doesn't match |
| Client cert required | `certificate_required`, `bad_certificate` |
| Handshake failure | `handshake_failure`, `protocol version` |
| Invalid keystore | `Invalid keystore format`, `DerInputStream.getLength` |

Each scenario includes:
- Diagnostic openssl/keytool/java commands ready to copy-paste
- Which tool in this application to use for further investigation (Remote Check, Connection Test, Key Match, Chain Expiry, etc.)
- Link to the relevant Help section for deeper reading

---


## 20. PKI Infrastructure (CDP, AIA & OCSP)

This section covers the PKI infrastructure features that make certificates issued by this tool work with standard TLS clients (Java, curl, browsers, Nginx) without manual trust configuration beyond importing the root CA.

---

### 20.1 Overview

When `PKI_BASE_URL` is configured, all newly issued certificates automatically include:

- **CRL Distribution Point (CDP)** — URL where relying parties can download the CRL to check revocation
- **Authority Information Access (AIA)** — URLs for the OCSP responder and CA certificate download
- **OCSP Responder** — Real-time certificate revocation status (RFC 6960)

These extensions are standard X.509 v3 fields that TLS clients use to validate certificates without manual configuration.

```
┌─────────────────────────────────────────────────────────────┐
│ Certificate Extensions (embedded in every issued cert)       │
├─────────────────────────────────────────────────────────────┤
│  CRL Distribution Points:                                    │
│    URI: http://pki.internal/api/v1/pki/crl/{ca_id}          │
│                                                              │
│  Authority Information Access:                               │
│    OCSP: http://pki.internal/api/v1/pki/ocsp                │
│    CA Issuers: http://pki.internal/api/v1/pki/ca/{ca_id}/cert│
└─────────────────────────────────────────────────────────────┘
```

---

### 20.2 Configuration

#### Via Settings Page (UI)

1. Navigate to **Settings**
2. Find the **PKI Infrastructure** section
3. Enter the **PKI Base URL** — this must be reachable by all relying parties (e.g. `http://pki.internal`)
4. Set **CRL Validity** (default: 7 days)
5. Click **Save PKI Settings**

The settings panel shows live endpoint URLs when enabled.

#### Via API

```bash
# Get current PKI settings
curl -sk -H "X-API-Key: $API_KEY" https://localhost/api/v1/settings/pki

# Enable PKI extensions
curl -sk -X PUT -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  https://localhost/api/v1/settings/pki \
  -d '{"pki_base_url": "http://pki.internal", "crl_validity_days": 7}'

# Disable PKI extensions
curl -sk -X PUT -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  https://localhost/api/v1/settings/pki \
  -d '{"pki_base_url": "", "crl_validity_days": 7}'
```

#### Via Environment Variable

Set in `backend/.env` or `/etc/certmanager/certmanager.env`:

```bash
PKI_BASE_URL=http://pki.internal
CRL_VALIDITY_DAYS=7
```

**Important:** The `PKI_BASE_URL` must be reachable by all systems that will validate certificates. Use HTTP (not HTTPS) to avoid a chicken-and-egg problem — the PKI endpoints themselves cannot require a certificate that depends on the PKI being available.

---

### 20.3 Public PKI Endpoints

These endpoints are **unauthenticated** (no API key required) — this is by design per RFC 5280 and RFC 6960. Relying parties must be able to check revocation without credentials.

| Endpoint | Content-Type | Purpose |
|----------|-------------|---------|
| `GET /api/v1/pki/crl/{ca_id}` | `application/pkix-crl` | CRL download (DER format) |
| `GET /api/v1/pki/ca/{ca_id}/cert` | `application/x-x509-ca-cert` | CA certificate download (DER) |
| `GET /api/v1/pki/info` | `application/json` | PKI status and endpoint URLs |
| `POST /api/v1/pki/ocsp` | `application/ocsp-response` | OCSP responder (RFC 6960) |
| `GET /api/v1/pki/ocsp/{base64}` | `application/ocsp-response` | OCSP responder GET method |
| `GET /api/v1/pki/ocsp/status/{serial}` | `application/json` | Readable OCSP status |

---

### 20.4 OCSP Responder

The built-in OCSP responder provides real-time certificate revocation status. It is RFC 6960 compliant and works with standard tools (openssl, Java, browsers).

#### How It Works

1. Client sends a DER-encoded OCSP request containing the certificate serial number
2. Responder looks up the serial in the database
3. Returns a signed OCSP response: `good`, `revoked`, or `unauthorized` (unknown)
4. Response is signed by the issuing CA's key

#### Testing with OpenSSL

```bash
# Check OCSP status of a certificate
openssl ocsp \
  -issuer ca.pem \
  -cert server.pem \
  -url http://pki.internal/api/v1/pki/ocsp \
  -no_nonce

# Expected output for a valid cert:
# Response verify OK
# server.pem: good
#   This Update: Jul  9 15:26:37 2026 GMT
#   Next Update: Jul 16 15:26:37 2026 GMT

# Expected output for a revoked cert:
# server.pem: revoked
#   This Update: Jul  9 15:27:02 2026 GMT
#   Next Update: Jul 16 15:27:02 2026 GMT
#   Revocation Time: Jul  9 15:26:56 2026 GMT
```

#### Testing with curl (Readable Output)

```bash
# Quick status check (no crypto needed)
curl -s http://pki.internal/api/v1/pki/ocsp/status/<serial>

# Response:
# {"serial":"abc123...","status":"valid","revoked_at":null,"expires_at":"2027-07-09T15:20:57","signing_ca_id":"uuid..."}
```

#### Java OCSP Verification

Java automatically checks OCSP when the certificate contains an AIA extension with an OCSP URL. Enable OCSP checking in Java:

```bash
# Enable OCSP checking (Java 8+)
-Dcom.sun.security.enableCRLDP=true
-Dcom.sun.net.ssl.checkRevocation=true

# Or programmatically:
Security.setProperty("ocsp.enable", "true");
```

With certificates issued by this tool (when `PKI_BASE_URL` is set), Java will automatically:
1. Read the AIA extension from the certificate
2. Send an OCSP request to the embedded URL
3. Verify the signed response
4. Reject the connection if the certificate is revoked

---

### 20.5 OCSP Stapling

OCSP stapling allows the server to pre-fetch the OCSP response and include it in the TLS handshake, avoiding the client needing to contact the OCSP responder directly.

#### Generating a Staple File

```bash
# Download pre-signed OCSP response (requires API key)
curl -sk -H "X-API-Key: $API_KEY" \
  https://localhost/api/v1/pki/ocsp/staple/<serial> \
  -o /etc/nginx/ssl/ocsp-response.der
```

#### Nginx OCSP Stapling Configuration

```nginx
server {
    listen 443 ssl;
    server_name api.example.internal;

    ssl_certificate     /etc/nginx/ssl/server-chain.pem;
    ssl_certificate_key /etc/nginx/ssl/server-key.pem;

    # OCSP stapling with pre-fetched response
    ssl_stapling on;
    ssl_stapling_verify on;
    ssl_stapling_file /etc/nginx/ssl/ocsp-response.der;
    ssl_trusted_certificate /etc/nginx/ssl/root-ca.pem;

    # Or let Nginx fetch from the OCSP responder directly:
    # ssl_stapling on;
    # ssl_stapling_verify on;
    # ssl_trusted_certificate /etc/nginx/ssl/root-ca.pem;
    # resolver 8.8.8.8;  # DNS resolver for OCSP URL lookup
}
```

#### Automating Staple Refresh

```bash
#!/bin/bash
# Cron job: refresh OCSP staple every 12 hours
SERIAL="your-cert-serial-hex"
API_KEY="your-api-key"

curl -sk -H "X-API-Key: $API_KEY" \
  https://localhost/api/v1/pki/ocsp/staple/$SERIAL \
  -o /etc/nginx/ssl/ocsp-response.der

nginx -s reload
```

Add to crontab:
```
0 */12 * * * /opt/scripts/refresh-ocsp-staple.sh
```

---

### 20.6 CRL Distribution

The CRL endpoint generates a fresh CRL on every request containing all revoked certificates for that CA.

#### CRL Characteristics

- Format: DER (binary)
- Signed by the CA key
- Contains: all revoked serial numbers with revocation timestamps
- `This Update`: current time
- `Next Update`: current time + `CRL_VALIDITY_DAYS`
- Cache-Control header set to half the validity period

#### Inspecting a CRL

```bash
# Download and inspect
curl -s http://pki.internal/api/v1/pki/crl/<ca-id> -o crl.der
openssl crl -in crl.der -inform DER -text -noout

# Output shows:
# Certificate Revocation List (CRL):
#   Issuer: CN=Internal Root CA, O=MyOrg
#   Last Update: Jul 9 15:20:00 2026 GMT
#   Next Update: Jul 16 15:20:00 2026 GMT
# Revoked Certificates:
#   Serial Number: A99EE35D4802327722B0F7B316BA7E27
#     Revocation Date: Jul 9 15:26:56 2026 GMT
```

#### Verifying a Certificate Against the CRL

```bash
# Convert CRL to PEM for openssl verify
openssl crl -in crl.der -inform DER -out crl.pem -outform PEM

# Verify certificate with CRL check
openssl verify -crl_check -CAfile root-ca.pem -CRLfile crl.pem server-cert.pem
```

---

### 20.7 Certificate Detail — OCSP Status Indicator

The Certificate Inspector page (click any certificate in the list) now shows a real-time **OCSP Status** indicator:

- **GOOD** (green) — Certificate is valid and not revoked
- **REVOKED** (red) — Certificate has been revoked, with revocation timestamp
- **UNKNOWN** (grey) — Certificate not found in this CA's database

The indicator polls every 60 seconds for live status updates. This is useful for confirming that revocation has propagated immediately after revoking a certificate.

---

### 20.8 Architecture Notes

- **Public endpoints are unauthenticated** — this is required by RFC 5280 (CRL) and RFC 6960 (OCSP). Relying parties must be able to check revocation without credentials.
- **AIA/CDP URLs must be stable** — once embedded in a certificate, these URLs cannot be changed. Plan your `PKI_BASE_URL` carefully before issuing production certificates.
- **Use HTTP, not HTTPS** for PKI endpoints — avoids circular dependency (can't validate a cert if the validation endpoint itself requires a cert from the same CA).
- **OCSP responses are signed by a delegated OCSP signing certificate** — a short-lived (30-day) ECDSA P-256 cert with `id-kp-OCSPSigning` EKU and `id-pkix-ocsp-nocheck` extension. The CA private key is NOT used for routine OCSP signing. Falls back to CA key only if the delegated cert is unavailable.
- **CRL is generated fresh per request** — suitable for low-to-medium traffic. For high-traffic environments, consider caching with a reverse proxy (Nginx, Varnish) using the `Cache-Control` header.
- **Certificates issued before enabling PKI_BASE_URL** will NOT contain CDP/AIA extensions. Only newly issued certificates include them.

---

### 20.9 OCSP Signing Delegation (RFC 6960 §4.2.2.2)

The OCSP responder uses a dedicated signing certificate per CA instead of the CA private key. This reduces CA key exposure and follows RFC 6960 best practices.

#### How It Works

1. Each CA automatically gets a dedicated OCSP signing certificate (ECDSA P-256, 30-day validity)
2. The OCSP signing cert has:
   - **EKU**: `id-kp-OCSPSigning` (1.3.6.1.5.5.7.3.9)
   - **OCSPNoCheck**: tells clients not to check revocation of the OCSP cert itself
   - **KeyUsage**: digitalSignature only
3. OCSP responses include the signing cert so clients can verify without the CA key
4. A background task renews OCSP certs 7 days before expiry (checks every 6 hours)
5. If no valid OCSP cert exists, falls back to CA key signing (backward compatible)

#### Manual Generation

Force-regenerate the OCSP signing cert for a CA:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/pki/ca/{ca_id}/ocsp-cert \
  -H "X-API-Key: $API_KEY"
```

Response:
```json
{
  "status": "generated",
  "ca_id": "af74b53b-...",
  "ocsp_cert_subject": "O=SSL Certificate Manager,CN=OCSP Responder - ...",
  "expires": "2025-02-08T12:00:00+00:00",
  "validity_days": 30
}
```

#### Verification

OCSP responses now include the responder certificate. Verify with:

```bash
# The response should show "Responder Id" as the OCSP cert (not the CA)
openssl ocsp -respin response.der -text | grep -A2 "Responder Id"
```

---

### 20.10 CA Key Ceremony & Offline Root

Enterprise PKI keeps root CA keys offline (air-gapped). The root is only brought online to sign intermediate CA certificates. This feature supports importing externally-generated CA certificates without their private keys and using temporary signing sessions for intermediate CA creation.

#### Importing an External Root CA

Import a root CA certificate without its private key:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/ca/import \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"cert_pem": "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----"}'
```

Response:
```json
{
  "id": "6d43f60c-...",
  "cn": "External Offline Root",
  "is_root": true,
  "has_key": false,
  "key_algo": "RSA",
  "key_size": 4096,
  "path_length": 2,
  "expires_at": "2046-07-05T08:31:11",
  "message": "CA imported without private key. Use signing session to sign intermediates."
}
```

**Validation:**
- Certificate must have `BasicConstraints CA:TRUE`
- Key algorithm and size are extracted from the public key
- Subject fields (CN, O, OU, C, ST, L) are extracted automatically
- Self-signed detection determines `is_root`

**Limitations of offline CAs:**
- Cannot issue certificates directly (no key)
- CRL endpoint returns `409 Conflict`
- OCSP responder returns `unauthorized` for certs signed by this CA
- OCSP signing cert cannot be generated
- Used as trust anchor for chain building only

#### Starting a Signing Session

Temporarily upload the root key to sign intermediate CAs:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/ca/{ca_id}/signing-session \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "key_pem": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----",
    "key_password": null,
    "timeout_minutes": 15
  }'
```

Response:
```json
{
  "status": "active",
  "ca_id": "6d43f60c-...",
  "ca_cn": "External Offline Root",
  "started_by": "admin",
  "timeout_minutes": 15,
  "expires_at": "2026-07-10T08:51:25+00:00"
}
```

**Security properties:**
- Key is held in memory only — never written to disk or database
- Key/cert public key match is validated before session starts
- Session auto-expires after timeout (configurable 1–60 minutes, default 15)
- Requires `ca:create` permission (admin only)
- Audit events: `CA_SIGNING_SESSION_START`, `CA_SIGNING_SESSION_END`

#### Signing an Intermediate During a Session

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/ca/{ca_id}/signing-session/sign-intermediate \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "subject_cn": "Production Intermediate CA",
    "subject_o": "MyOrg",
    "subject_c": "GB",
    "key_algo": "RSA",
    "key_size": 4096,
    "validity_days": 3650,
    "path_length": 0
  }'
```

The intermediate CA:
- Gets its own generated key (stored encrypted in database)
- Is signed by the offline root's temporarily-uploaded key
- Can issue certificates normally (it has `has_key: true`)
- Shows `source: ceremony` in the CA list

#### Checking Session Status

```bash
curl -s http://127.0.0.1:8000/api/v1/ca/{ca_id}/signing-session \
  -H "X-API-Key: $API_KEY"

# Response (active):
# {"status": "active", "remaining_seconds": 847, ...}

# Response (expired/none):
# {"status": "inactive", "ca_id": "..."}
```

#### Ending a Session Early

```bash
curl -s -X DELETE http://127.0.0.1:8000/api/v1/ca/{ca_id}/signing-session \
  -H "X-API-Key: $API_KEY"
```

Immediately removes the key from memory.

#### Key Ceremony Audit Events

| Event | Severity | When |
|-------|----------|------|
| `KEY_CEREMONY` | INFO | CA imported (offline root) |
| `KEY_CEREMONY` | WARN | Intermediate signed during session |
| `CA_SIGNING_SESSION_START` | WARN | Key uploaded to memory |
| `CA_SIGNING_SESSION_END` | INFO | Session ended (manual or timeout) |

#### Configuration

```bash
# Default signing session timeout (minutes)
SIGNING_SESSION_TIMEOUT_MINUTES=15
```

#### CA Source Values

| Source | Meaning |
|--------|---------|
| `user` | Created normally via the UI/API |
| `bootstrap` | Auto-created during initial setup |
| `imported` | Imported without key (offline root) |
| `ceremony` | Created during a signing session |

---

### 20.11 Serial Number Management

Certificate serial numbers can be configured per CA with three allocation strategies. This provides compliance with organisational numbering policies and aids certificate inventory management.

#### Serial Formats

| Format | Structure | Example (hex) | Use Case |
|--------|-----------|---------------|----------|
| `random` (default) | 128-bit cryptographically random | `a7f3b2c1...` (32 hex chars) | Maximum unpredictability; recommended for public-facing certs |
| `sequential` | Counter (upper 64 bits) + random (lower 64 bits) | `0000000000000001...` | Auditable ordering; easy to spot gaps |
| `timestamp` | Date (upper) + counter (mid) + random (lower) | `20260710...` | Date-sortable; useful for forensics |

All formats produce unique, positive integers suitable for X.509 serial numbers per RFC 5280 §4.1.2.2.

#### Configuring Serial Format per CA

```bash
# Set sequential format with optional prefix
curl -s -X PUT -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/ca/<ca_id>/serial-format \
  -d '{"format": "sequential", "prefix": "PROD"}'

# Set timestamp format
curl -s -X PUT -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/ca/<ca_id>/serial-format \
  -d '{"format": "timestamp"}'

# Reset to random (default)
curl -s -X PUT -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/ca/<ca_id>/serial-format \
  -d '{"format": "random"}'
```

#### Querying Current Configuration

```bash
curl -s -H "X-API-Key: $API_KEY" \
  http://127.0.0.1:8000/api/v1/ca/<ca_id>/serial-format

# Response:
# {"ca_id": "...", "format": "sequential", "prefix": "PROD", "next_value": 5}
```

#### Collision Detection

The allocator checks for serial collisions against the certificate database before issuance. If a collision is detected (extremely unlikely with 128-bit random), it retries up to 3 times with a new value. A WARNING is logged on any collision.

#### How It Works

1. When a certificate is issued, the system checks the CA's configured serial format
2. If no configuration exists, defaults to `random` (128-bit)
3. For `sequential` and `timestamp` formats, an atomic counter is maintained per CA in the `serial_counters` table
4. The generated serial is passed to the crypto engine before certificate signing
5. The counter increments within the same database transaction as certificate creation (atomic)

#### RBAC

| Action | Admin | Operator | Auditor | ReadOnly |
|--------|:-----:|:--------:|:-------:|:--------:|
| Configure serial format | ✓ | ✗ | ✗ | ✗ |
| View serial format | ✓ | ✓ | ✓ | ✓ |

---

### 20.12 Troubleshooting PKI

| Issue | Cause | Fix |
|-------|-------|-----|
| Certificates don't have CDP/AIA extensions | `PKI_BASE_URL` not set when cert was issued | Set PKI_BASE_URL in Settings, then re-issue the certificate |
| OCSP returns `unauthorized` | Certificate serial not found in database | Verify the serial matches; cert may have been issued by a different CA |
| OCSP returns `malformed_request` | Invalid DER data sent to endpoint | Ensure you're sending a proper OCSP request (use `openssl ocsp -reqout`) |
| Java ignores OCSP | OCSP checking not enabled in JVM | Add `-Dcom.sun.security.enableCRLDP=true -Dcom.sun.net.ssl.checkRevocation=true` |
| CRL download fails | Wrong CA ID in URL | Check the CA ID from the certificate's CDP extension or the CA list |
| `PKI_BASE_URL` not reachable | DNS/network issue | Ensure all relying parties can resolve and reach the URL; use `curl` to test |
| OCSP staple rejected by client | Staple expired (older than `Next Update`) | Refresh the staple file more frequently (cron every 12h) |
| OCSP response verification fails | Delegated cert expired or not included | Run `POST /api/v1/pki/ca/{id}/ocsp-cert` to regenerate |

---


## 21. Access Control (RBAC)

This section covers user accounts, role-based permissions, JWT authentication, and scoped API keys.

---

### 21.1 Authentication Methods

The application supports three authentication methods, checked in this order:

| Method | Header | Use Case |
|--------|--------|----------|
| JWT Bearer Token | `Authorization: Bearer <token>` | User login sessions (browser, API clients) |
| Scoped API Key | `X-API-Key: <key>` | CI/CD pipelines, automation, service accounts |
| Legacy Master Key | `X-API-Key: <key>` | Backward compatibility (always admin role) |

**JWT tokens** are issued by the `/api/v1/auth/login` endpoint and expire after 24 hours (configurable via `JWT_EXPIRE_HOURS`).

**Scoped API keys** are created by admins, have an assigned role, and optionally expire after a set number of days.

**The legacy master key** (from `API_KEY` in `.env`) always grants admin access and cannot be scoped or expired. It exists for backward compatibility and initial setup.

---

### 21.2 Default Credentials

On first run, a default admin user is created:

| Username | Password | Role |
|----------|----------|------|
| `admin` | `admin` | Admin (full access) |

> ⚠️ **Change the default password immediately** after first login via the UI or API.

**Changing the password via API:**

```bash
# Login to get a token
TOKEN=$(curl -s http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

# Change password
curl -s http://localhost:8000/api/v1/auth/change-password \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"current_password":"admin","new_password":"YourSecurePassword123!"}'
```

**Changing the password via UI:**
1. Log in with `admin` / `admin`
2. Navigate to **Users & Keys** (admin only)
3. Click **Edit** on the admin user
4. Enter a new password (minimum 8 characters)
5. Click **Update**

---

### 21.3 Roles & Permissions

Four roles are available, each with a fixed set of permissions:

| Action | Admin | Operator | Auditor | ReadOnly |
|--------|:-----:|:--------:|:-------:|:--------:|
| Create/delete CA | ✓ | ✗ | ✗ | ✗ |
| Issue certificate | ✓ | ✓ | ✗ | ✗ |
| Revoke certificate | ✓ | ✓ | ✗ | ✗ |
| Export with private key | ✓ | ✓ | ✗ | ✗ |
| Sign CSR | ✓ | ✓ | ✗ | ✗ |
| View certificates | ✓ | ✓ | ✓ | ✓ |
| View audit log | ✓ | ✓ | ✓ | ✗ |
| Manage users & API keys | ✓ | ✗ | ✗ | ✗ |
| Manage templates | ✓ | ✓ | ✗ | ✗ |
| System settings | ✓ | ✗ | ✗ | ✗ |
| Backup/restore | ✓ | ✗ | ✗ | ✗ |

**Role descriptions:**

- **Admin** — Full access. Can manage users, CAs, settings, and backups. Intended for PKI administrators.
- **Operator** — Can issue and revoke certificates, sign CSRs, manage templates. Cannot create CAs or manage users. Intended for day-to-day certificate operations.
- **Auditor** — Read-only access to certificates plus audit log visibility. Cannot issue, revoke, or export private keys. Intended for compliance and security review.
- **ReadOnly** — Can only view certificates and CAs. No audit log access. Intended for developers who need to check certificate details.

---

### 21.4 User Management

#### Creating Users (Admin Only)

**Via UI:**
1. Navigate to **Users & Keys**
2. Click **+ Create User**
3. Fill in username, email, password (min 8 chars), and role
4. Click **Create**

**Via API:**

```bash
curl -s http://localhost:8000/api/v1/users \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "operator1",
    "email": "ops@example.com",
    "password": "SecurePass123!",
    "role": "operator"
  }'
```

#### Updating Users

```bash
# Change role
curl -s -X PUT http://localhost:8000/api/v1/users/<user_id> \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"role": "auditor"}'

# Disable account
curl -s -X PUT http://localhost:8000/api/v1/users/<user_id> \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"active": false}'

# Reset password
curl -s -X PUT http://localhost:8000/api/v1/users/<user_id> \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"password": "NewPassword123!"}'
```

#### Deleting Users

```bash
curl -s -X DELETE http://localhost:8000/api/v1/users/<user_id> \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

The default `admin` user cannot be deleted (returns 403).

---

### 21.5 Scoped API Keys

Scoped API keys provide non-interactive authentication for automation, CI/CD pipelines, and service accounts. Each key has an assigned role and optional expiry.

#### Creating a Scoped API Key

**Via UI:**
1. Navigate to **Users & Keys**
2. Scroll to **Scoped API Keys**
3. Click **+ Create Key**
4. Enter name, role, and optional expiry (days)
5. Click **Create Key**
6. **Copy the key immediately** — it is shown only once

**Via API:**

```bash
curl -s http://localhost:8000/api/v1/api-keys \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ci-pipeline",
    "role": "operator",
    "expires_in_days": 90
  }'
```

Response includes the `key` field — save it immediately:

```json
{
  "id": "uuid...",
  "name": "ci-pipeline",
  "key_prefix": "olyGwm0E",
  "role": "operator",
  "key": "olyGwm0EuPY_rJoM1qNG4EE93gF5VmF-L68Zx3gm9Lw",
  "expires_at": "2026-10-07T16:37:38",
  "created_by": "admin"
}
```

#### Using a Scoped API Key

```bash
# Use in X-API-Key header (same as legacy key)
curl -s http://localhost:8000/api/v1/cert \
  -H "X-API-Key: olyGwm0EuPY_rJoM1qNG4EE93gF5VmF-L68Zx3gm9Lw"
```

The key's role determines what operations are permitted. An operator-scoped key can issue certificates but cannot create CAs or manage users.

#### Revoking a Key

```bash
curl -s -X DELETE http://localhost:8000/api/v1/api-keys/<key_id> \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Revoked keys are immediately rejected on all subsequent requests.

#### Key Rotation Strategy

For zero-downtime key rotation:
1. Create a new key with the same role
2. Update the consuming service/pipeline to use the new key
3. Verify the new key works
4. Revoke the old key

The overlap period (both keys active) allows graceful migration.

---

### 21.6 Login Flow (Browser)

1. Navigate to `http://127.0.0.1` — the login page is shown
2. Enter username and password (or switch to API Key tab)
3. On success, a JWT token is stored in the browser's localStorage
4. All subsequent API calls include the token as `Authorization: Bearer <token>`
5. Token expires after 24 hours — user is redirected to login

**API Key mode** (legacy): paste the master API key or a scoped key on the login page. This stores the key in localStorage and uses `X-API-Key` header for all requests.

---

### 21.7 Session Security

- **JWT tokens** are signed with HMAC-SHA256 using `JWT_SECRET` (or `CERT_MASTER_KEY` if JWT_SECRET is not set)
- **Passwords** are hashed with Argon2id (memory-hard, resistant to GPU attacks)
- **API keys** are stored as SHA-256 hashes in the database — the raw key is never stored
- **Token expiry** is enforced server-side — expired tokens are rejected immediately
- **Disabled accounts** cannot authenticate even with a valid token

---

### 21.8 Audit Trail

All authentication and user management events are recorded in the audit log:

| Event | Severity | Description |
|-------|----------|-------------|
| `USER_LOGIN` | INFO | Successful login (records username and IP) |
| `USER_CREATED` | INFO | New user account created |
| `USER_UPDATED` | INFO | User account modified (role, email, active) |
| `USER_DELETED` | WARNING | User account deleted |
| `PASSWORD_CHANGED` | WARNING | Password changed (records which user) |
| `API_KEY_CREATED` | INFO | Scoped API key created (records name and role) |
| `API_KEY_REVOKED` | WARNING | Scoped API key revoked |

All write operations also record the acting user (from JWT `username` claim or API key name) in the audit event.

---

### 21.9 Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `401 Missing or invalid authentication` | No token/key provided, or token expired | Log in again or provide a valid API key |
| `401 Invalid username or password` | Wrong credentials | Check username and password; passwords are case-sensitive |
| `401 API key expired` | Scoped key past its expiry date | Create a new key and revoke the expired one |
| `403 Permission denied: ca:create` | User's role lacks the required permission | Use an admin account for CA operations |
| `403 Account disabled` | User account set to inactive | Admin must re-enable: `PUT /users/{id}` with `{"active": true}` |
| `403 Cannot delete the default admin user` | Attempted to delete the built-in admin | This is by design — the admin user cannot be removed |
| Token not accepted after restart | `JWT_SECRET` changed between restarts | Ensure `JWT_SECRET` (or `CERT_MASTER_KEY`) is consistent across restarts |
| Legacy API key stopped working | Key was rotated via `/settings/rotate-api-key` | Use the new key returned by the rotation endpoint |
| `429 Too Many Requests` | Rate limit exceeded | Wait for `Retry-After` seconds, then retry |
| `423 Account locked` | Too many failed login attempts | Wait for lockout to expire (default 15 minutes) or admin unlocks via DB |

---

### 21.10 Rate Limiting & Brute Force Protection

The API enforces per-endpoint rate limits using a sliding window algorithm. Exceeding the limit returns `429 Too Many Requests` with a `Retry-After` header indicating how many seconds to wait.

#### Rate Limit Categories

| Category | Default Limit | Scope | Env Variable |
|----------|---------------|-------|--------------|
| Certificate issuance | 10/min | Per user | `RATE_LIMIT_CERT_ISSUE` |
| CSR generation | 20/min | Per user | `RATE_LIMIT_CSR_GENERATE` |
| OCSP responder | 100/sec | Global | `RATE_LIMIT_OCSP` |
| CRL download | 10/min | Per IP | `RATE_LIMIT_CRL` |
| Login attempts | 5/min | Per IP | `RATE_LIMIT_LOGIN` |
| Export (with key) | 10/min | Per user | `RATE_LIMIT_EXPORT_KEY` |
| General API | 60/min | Per user | `RATE_LIMIT_GENERAL` |

**Exempt endpoints:** `/api/v1/health`, `/api/v1/diagnostics`, `/api/docs`

Set any limit to `0` to disable that category.

#### Brute Force Protection

Failed login attempts are tracked per user account:

- After **5 consecutive failures** (configurable: `LOGIN_MAX_ATTEMPTS`), the account is locked for **15 minutes** (configurable: `LOGIN_LOCKOUT_MINUTES`)
- Locked accounts receive `423 Locked` with a `Retry-After` header
- Successful login resets the failure counter
- Lockout is checked *before* password verification (prevents timing attacks)
- An `AUTH_LOCKOUT` audit event is recorded when an account is locked

#### Configuration (Environment Variables)

```bash
# Rate limits (set to 0 to disable)
RATE_LIMIT_CERT_ISSUE=10
RATE_LIMIT_CSR_GENERATE=20
RATE_LIMIT_OCSP=100
RATE_LIMIT_CRL=10
RATE_LIMIT_LOGIN=5
RATE_LIMIT_EXPORT_KEY=10
RATE_LIMIT_GENERAL=60

# Brute force
LOGIN_MAX_ATTEMPTS=5
LOGIN_LOCKOUT_MINUTES=15
```

#### Unlocking a Locked Account

If an account is locked and you need immediate access:

```bash
# Via sqlite3 inside the container
docker exec ssl-cert-manager sqlite3 /data/certmanager.db \
  "UPDATE users SET failed_attempts=0, locked_until=NULL WHERE username='admin';"
```

Then restart the container (or wait for the lockout to expire naturally).

---


### 21.11 LDAP / Active Directory Authentication

Enterprise users can authenticate with existing corporate credentials via LDAP or Active Directory. Local accounts continue to work alongside LDAP (hybrid mode).

#### How It Works

1. User enters username/password on the login page
2. System tries **local authentication first** (existing user accounts)
3. If local auth fails and LDAP is enabled, tries **LDAP bind authentication**
4. On successful LDAP auth, a shadow user record is created/updated in the local database
5. LDAP group memberships are mapped to application roles on each login
6. The local `admin` account always works regardless of LDAP status (break-glass)

#### Configuration

Configure via the **Settings → LDAP / Active Directory** section in the UI, or via environment variables:

```bash
# Enable LDAP
LDAP_ENABLED=true
LDAP_URL=ldaps://dc.corp.internal:636

# Service account for user search (optional — leave empty for anonymous bind)
LDAP_BIND_DN=cn=svc-pki,ou=Service,dc=corp,dc=internal
LDAP_BIND_PASSWORD=service_account_password

# User lookup
LDAP_SEARCH_BASE=ou=People,dc=corp,dc=internal
LDAP_SEARCH_FILTER=(uid={username})
# For Active Directory:
# LDAP_SEARCH_FILTER=(sAMAccountName={username})

# Alternative: direct bind (no search needed)
# LDAP_USER_DN_TEMPLATE=uid={username},ou=People,dc=corp,dc=internal

# TLS
LDAP_TLS_CA_CERT=/etc/ssl/certs/ldap-ca.pem
LDAP_STARTTLS=false
LDAP_TIMEOUT=10

# Group-to-role mapping
LDAP_GROUP_ATTRIBUTE=memberOf
LDAP_ROLE_ADMIN=cn=pki-admins,ou=Groups,dc=corp,dc=internal
LDAP_ROLE_OPERATOR=cn=pki-operators,ou=Groups,dc=corp,dc=internal
LDAP_ROLE_AUDITOR=cn=pki-auditors,ou=Groups,dc=corp,dc=internal
LDAP_ROLE_DEFAULT=readonly
```

#### Group-to-Role Mapping

LDAP group memberships are checked on every login. The highest-privilege matching group wins:

| Priority | Group DN Setting | Mapped Role |
|:--------:|-----------------|-------------|
| 1 (highest) | `LDAP_ROLE_ADMIN` | admin |
| 2 | `LDAP_ROLE_OPERATOR` | operator |
| 3 | `LDAP_ROLE_AUDITOR` | auditor |
| 4 (default) | — | `LDAP_ROLE_DEFAULT` (readonly) |

If a user is a member of both `pki-admins` and `pki-operators`, they get `admin`.

#### Shadow User Records

When an LDAP user logs in for the first time, a local user record is created with:
- `auth_source = "ldap"` (distinguishes from local accounts)
- Role from LDAP group mapping
- Email from LDAP `mail` attribute (if available)
- Password hash set to a placeholder (cannot be used for local login)

On subsequent logins, the role is updated from LDAP groups (in case group membership changed).

#### Testing the Connection

Use the **Test Connection** button in Settings, or via API:

```bash
curl -sk -X POST -H "X-API-Key: $API_KEY" \
  https://localhost/api/v1/settings/ldap/test
```

Returns server info (vendor, naming contexts) on success, or error details on failure.

#### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/settings/ldap` | Get LDAP configuration (passwords masked) |
| PUT | `/api/v1/settings/ldap` | Update LDAP settings (admin only) |
| POST | `/api/v1/settings/ldap/test` | Test LDAP connectivity (admin only) |
| GET | `/api/v1/auth/auth-info` | Public — returns `{"ldap_enabled": true/false}` |

#### Security Notes

- Always use `ldaps://` (TLS) or STARTTLS — never plain `ldap://` in production
- The service account password is stored in memory only (from env var or settings update)
- LDAP users cannot change their password via this application (use your directory's tools)
- API keys remain local — they are not LDAP-backed
- Account lockout applies to LDAP users the same as local users

#### Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `LDAP library not available` | `ldap3` package not installed | Add `ldap3>=2.9.0` to requirements and rebuild |
| `LDAP connection failed: invalid server address` | URL unreachable | Verify LDAP_URL is correct and network allows connection |
| `User not found in LDAP` | Search filter doesn't match | Check LDAP_SEARCH_FILTER — use `(sAMAccountName={username})` for AD |
| LDAP user gets wrong role | Group DN doesn't match exactly | Group comparison is case-insensitive but DN must be exact |
| Local admin can't log in | Should never happen | Local auth is tried first; admin account always works |
| `LDAP not enabled` | LDAP_ENABLED=false or LDAP_URL empty | Set both in Settings or environment |

---


## 22. Certificate Lifecycle Management

This section covers certificate renewal, auto-renewal, temporary hold, and renewal chain tracking.

---

### 22.1 Certificate Renewal

Renewal creates a new certificate with the same subject, SANs, profile, and tags as the original. You can choose to reuse the existing private key or generate a fresh one.

#### When to Renew

- Certificate approaching expiry (30–60 days before)
- Key rotation policy requires periodic new keys
- After a security incident where you want a new key but same identity

#### Manual Renewal via API

```bash
# Renew with same key (fastest — no client reconfiguration needed)
curl -sk -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  https://localhost/api/v1/cert/<serial>/renew \
  -d '{"validity_days": 365, "new_key": false}'

# Renew with new key (more secure — old key material is retired)
curl -sk -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  https://localhost/api/v1/cert/<serial>/renew \
  -d '{"validity_days": 365, "new_key": true}'
```

Response:
```json
{
  "status": "renewed",
  "old_serial": "4b767d2b764416f3...",
  "new_serial": "4b9f2972b4ae9b7a...",
  "new_key": false,
  "expires_at": "2027-07-09T17:22:41+00:00"
}
```

#### What Renewal Preserves

| Field | Preserved | Notes |
|-------|:---------:|-------|
| Subject (CN, O, OU, C, ST, L) | ✓ | Exact copy |
| SANs | ✓ | All DNS, IP, email, URI entries |
| Profile | ✓ | server, client, code_sign, email, custom |
| Tags | ✓ | All labels carried over |
| Signing CA | ✓ | Same CA signs the renewal |
| Key algorithm & size | ✓ | RSA 2048 stays RSA 2048 |
| Auto-renew flag | ✓ | Inherited by the new certificate |
| Private key | Optional | `new_key: false` reuses; `new_key: true` generates fresh |

#### What Changes

- New serial number
- New validity period (from now + validity_days)
- New CDP/AIA URLs (if PKI_BASE_URL is set)
- `renewed_from` field links to the old serial
- Old certificate gets `renewed_to` field pointing to the new serial

#### Same Key vs New Key

| Approach | Pros | Cons |
|----------|------|------|
| Same key (`new_key: false`) | No client reconfiguration; instant rollout | Old key material still in use |
| New key (`new_key: true`) | Better security posture; key rotation | Must redeploy key to all servers using it |

**Recommendation:** Use same key for routine renewals. Use new key after security incidents or per policy (e.g. annual key rotation).

---

### 22.2 Auto-Renewal

Certificates can be configured to automatically renew when they approach expiry. The background expiry scanner handles this.

#### Enabling Auto-Renewal

```bash
# Enable
curl -sk -X PATCH -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  https://localhost/api/v1/cert/<serial>/auto-renew \
  -d '{"auto_renew": true}'

# Disable
curl -sk -X PATCH -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  https://localhost/api/v1/cert/<serial>/auto-renew \
  -d '{"auto_renew": false}'
```

#### How Auto-Renewal Works

1. The background expiry scanner runs every `EXPIRY_SCAN_INTERVAL_HOURS` (default: 24 hours)
2. For each valid certificate with `auto_renew: true`:
   - If 30 days or fewer remain before expiry
   - AND the certificate has not already been renewed (`renewed_to` is empty)
   - AND the certificate was signed by an internal CA
   - AND the certificate has a stored private key
3. A new certificate is issued with:
   - Same private key (no key rotation)
   - Same validity period as the original (capped at `MAX_CERT_DAYS`)
   - Same subject, SANs, profile, and tags
4. The old certificate's `renewed_to` is set to the new serial
5. An `CERT_AUTO_RENEWED` audit event is recorded

#### Requirements for Auto-Renewal

- Certificate must be signed by an internal CA (not externally signed)
- Certificate must have a stored private key (`key_blob` not null)
- `auto_renew` flag must be `true`
- Certificate must not already have a successor (`renewed_to` must be null)

#### Limitations

- Auto-renewal uses the **same key** — it does not generate new keys
- Auto-renewal does not deploy the new certificate to servers — you must retrieve and deploy it
- The new certificate is created but the old one remains valid until it expires naturally
- If the signing CA has expired or been deleted, auto-renewal will fail (logged as an error)

#### Monitoring Auto-Renewals

Check the audit log for `CERT_AUTO_RENEWED` events:

```bash
curl -sk -H "X-API-Key: $API_KEY" \
  "https://localhost/api/v1/audit?event_type=CERT_AUTO_RENEWED"
```

Set up a webhook (`NOTIFY_WEBHOOK_URL`) to receive notifications when auto-renewals occur, so you can trigger deployment pipelines.

---

### 22.3 Renewal Chain Tracking

Every certificate tracks its predecessor and successor:

- `renewed_from` — serial number of the certificate this was renewed from
- `renewed_to` — serial number of the certificate that replaced this one

This creates a linked chain showing the full history of a certificate identity:

```
cert-v1 (expired)
  └─ renewed_to → cert-v2 (expired)
                    └─ renewed_to → cert-v3 (valid, auto_renew=true)
```

#### Viewing the Chain

The certificate list API includes `renewed_from` and `renewed_to` fields:

```bash
curl -sk -H "X-API-Key: $API_KEY" \
  "https://localhost/api/v1/cert?search=api.example.com"
```

Each entry shows:
```json
{
  "serial": "4b9f2972...",
  "status": "valid",
  "auto_renew": true,
  "renewed_from": "4b767d2b...",
  "renewed_to": null
}
```

---

### 22.4 Certificate Hold

Hold is a temporary revocation — the certificate is suspended but can be restored to valid status.

#### Use Cases

- **Incident investigation** — suspect a key compromise but not confirmed yet
- **Maintenance window** — temporarily disable a service's certificate
- **Compliance hold** — suspend pending audit review

#### Hold vs Revoke Decision Guide

| Situation | Action |
|-----------|--------|
| Confirmed key compromise | **Revoke** (permanent) |
| Suspected compromise, investigating | **Hold** (temporary) |
| Decommissioning a service | **Revoke** (permanent) |
| Temporary maintenance | **Hold** (temporary) |
| Employee departure (their client cert) | **Revoke** (permanent) |
| Service migration in progress | **Hold** (temporary) |

#### API

```bash
# Hold
curl -sk -X POST -H "X-API-Key: $API_KEY" \
  https://localhost/api/v1/cert/<serial>/hold

# Unhold
curl -sk -X POST -H "X-API-Key: $API_KEY" \
  https://localhost/api/v1/cert/<serial>/unhold
```

#### Status Transitions

```
valid ──hold──▶ held ──unhold──▶ valid
  │                                 │
  └──revoke──▶ revoked (permanent)  └──revoke──▶ revoked (permanent)
  │
  └──(expiry)──▶ expired
```

A held certificate:
- Cannot be held again (409 error)
- Cannot be renewed while held (must unhold first)
- Can be permanently revoked (hold → revoke is allowed)
- Shows `held_at` timestamp in the API response

---

### 22.5 Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `Cannot renew externally-signed certificates` | Certificate was imported from an external CA | Only internally-signed certs can be renewed |
| `No stored key — cannot renew` | Key was not stored at issuance time | Re-issue the certificate with key storage enabled |
| `Signing CA no longer exists` | The CA that signed the original was deleted | Cannot renew — must issue a new cert from a different CA |
| `Validity cannot exceed N days` | Requested validity exceeds `MAX_CERT_DAYS` | Reduce validity_days in the renewal request |
| Auto-renewal not triggering | Certificate doesn't meet all requirements | Check: `auto_renew=true`, has stored key, signed by internal CA, `renewed_to` is null |
| Auto-renewal failed (in logs) | CA expired or deleted, or DB error | Check recent errors in Diagnostics; verify signing CA is still valid |

---


## 23. Compliance, Reporting & Governance

This section covers compliance reports, certificate policy enforcement, the approval workflow, name constraints, and tamper-evident audit logging.

---

### 23.1 Compliance Reports

Navigate to **Reports** in the sidebar to access compliance dashboards. All reports require `audit:read` permission (admin, operator, or auditor roles).

#### Certificate Inventory

Full inventory of all certificates with summary statistics:
- Total count by status (valid, revoked, expired, held)
- Breakdown by key algorithm (RSA, ECDSA, Ed25519)
- Breakdown by profile (server, client, code_sign, email, custom)
- Exportable as JSON

```bash
curl -sk -H "X-API-Key: $API_KEY" https://localhost/api/v1/reports/inventory
```

#### Weak Key Report

Identifies certificates and CAs with weak cryptographic parameters:
- RSA keys below 2048 bits (critical)
- RSA keys below 3072 bits (recommended minimum)
- ECDSA keys below 256 bits
- CA keys below 4096 bits RSA

```bash
curl -sk -H "X-API-Key: $API_KEY" https://localhost/api/v1/reports/weak-keys
```

#### Expiry Forecast

Certificates expiring within 30, 60, and 90 day windows:
- Color-coded urgency (red/amber/blue)
- Shows auto-renew status for each certificate
- Helps plan renewal campaigns

```bash
curl -sk -H "X-API-Key: $API_KEY" https://localhost/api/v1/reports/expiry-forecast
```

#### Revocation Report

All revoked and held certificates with dates and reasons:

```bash
curl -sk -H "X-API-Key: $API_KEY" https://localhost/api/v1/reports/revocations
```

---

### 23.2 Audit Log Export

Export the full audit trail in three formats for compliance review or SIEM integration.

#### Formats

| Format | Use Case | Content-Type |
|--------|----------|--------------|
| JSON | Structured analysis, integrity verification | `application/json` |
| CSV | Spreadsheet review, manual audit | `text/csv` |
| CEF | SIEM integration (Splunk, QRadar, ArcSight) | `text/plain` |

#### API

```bash
# JSON export (includes hash chain)
curl -sk -H "X-API-Key: $API_KEY" \
  "https://localhost/api/v1/reports/audit-export?format=json" -o audit.json

# CSV export
curl -sk -H "X-API-Key: $API_KEY" \
  "https://localhost/api/v1/reports/audit-export?format=csv" -o audit.csv

# CEF export (for SIEM)
curl -sk -H "X-API-Key: $API_KEY" \
  "https://localhost/api/v1/reports/audit-export?format=cef" -o audit.cef

# With date range filter
curl -sk -H "X-API-Key: $API_KEY" \
  "https://localhost/api/v1/reports/audit-export?format=json&from_date=2026-01-01&to_date=2026-07-01"
```

#### CEF Format

Each line follows the Common Event Format standard:

```
CEF:0|CertManager|SSLCertManager|1.0|CERT_ISSUED|CERT_ISSUED|3|src=172.18.0.1 suser=admin cs1=abc123 cs1Label=SubjectID msg=Certificate issued: api.example.com (server)
```

---

### 23.3 Tamper-Evident Audit Log

Every audit event includes a SHA-256 hash that chains to the previous event, creating a tamper-evident log. If any event is modified or deleted, the chain breaks.

#### How It Works

Each event's hash is computed as:
```
SHA-256(previous_hash | timestamp | event_type | subject_id)
```

This creates an append-only chain where any modification to historical events is detectable.

#### Verifying Integrity

```bash
# Via API
curl -sk -H "X-API-Key: $API_KEY" https://localhost/api/v1/reports/audit-integrity

# Response:
# {"total_events": 42, "verified": 42, "intact": true, "broken_at_id": null}
```

Via the UI: Navigate to **Reports → Integrity Check** and click **Run Integrity Check**.

If the chain is broken, the response includes `broken_at_id` indicating the first event where the chain diverges. Events created before the hash chain feature was deployed are treated as legacy (always pass).

---

### 23.4 Name Constraints

Name constraints restrict which DNS domains an intermediate CA can issue certificates for. This prevents scope creep and enforces organisational boundaries.

#### Configuration

Set name constraints when creating an intermediate CA:

```json
{
  "name_constraints": {
    "permitted": [".alpha.internal", ".alpha.test"],
    "excluded": [".bad.alpha.internal"]
  }
}
```

#### Enforcement

When issuing a certificate signed by a constrained CA:
1. All DNS SANs are checked against permitted subtrees
2. All DNS SANs are checked against excluded subtrees
3. The CN is also checked (if it looks like a DNS name)
4. Violations return HTTP 422 with specific error messages

**Permitted:** If specified, every DNS name must end with one of the permitted suffixes.
**Excluded:** If specified, no DNS name may end with any excluded suffix.

#### X.509 Extension

The `NameConstraints` extension is embedded in the intermediate CA certificate (critical). This means TLS clients that perform path validation will also enforce the constraints independently of this tool.

#### Example

```
CA: Team Alpha CA
  Permitted: .alpha.internal, .alpha.test
  Excluded: .bad.alpha.internal

✓ app.alpha.internal       — matches .alpha.internal
✓ db.alpha.test            — matches .alpha.test
✗ evil.example.com         — not within any permitted subtree
✗ hack.bad.alpha.internal  — matches excluded subtree
```

---

### 23.5 Certificate Policy OIDs

CAs can be configured with a Certificate Policy OID and CPS (Certificate Practice Statement) URL. All certificates issued by that CA will include a `CertificatePolicies` X.509 extension.

#### Configuration

Set when creating a CA:
```json
{
  "policy_oid": "1.3.6.1.4.1.99999.1.1",
  "cps_url": "http://pki.internal/cps"
}
```

#### What It Does

- Embeds the OID in every issued certificate's `CertificatePolicies` extension
- Includes the CPS URL as a policy qualifier
- Allows relying parties to look up the organisation's certificate practices
- Required by some compliance frameworks (e.g. WebTrust, ETSI)

---

### 23.6 Approval Workflow

Templates can require admin approval before certificate issuance. When a non-admin user requests a certificate using such a template, the request is queued instead of issued immediately.

#### Enabling Approval on a Template

```bash
# Create a template with approval required
curl -sk -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  https://localhost/api/v1/templates \
  -d '{
    "name": "restricted-server",
    "display_name": "Restricted Server TLS",
    "require_approval": true,
    "max_validity_days": 365,
    "require_san": true
  }'

# Or update an existing template
curl -sk -X PUT -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  https://localhost/api/v1/templates/restricted-server \
  -d '{"require_approval": true}'
```

#### How It Works

1. **Operator** submits a certificate request using a template with `require_approval: true`
2. Request is queued (HTTP 202 returned with `request_id`)
3. **Admin** reviews the request in the Approvals page (or via API)
4. Admin **approves** → certificate is issued and stored
5. Or admin **rejects** → request is marked rejected with an optional note

**Admins bypass approval** — they can issue directly even with restricted templates.

#### API

```bash
# List pending requests
curl -sk -H "X-API-Key: $API_KEY" https://localhost/api/v1/approvals

# List all requests (including approved/rejected)
curl -sk -H "X-API-Key: $API_KEY" "https://localhost/api/v1/approvals?status_filter=all"

# Approve a request
curl -sk -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  https://localhost/api/v1/approvals/<request_id>/review \
  -d '{"action": "approve", "note": "Verified with team lead"}'

# Reject a request
curl -sk -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  https://localhost/api/v1/approvals/<request_id>/review \
  -d '{"action": "reject", "note": "Wrong domain — use .internal suffix"}'
```

#### UI

Navigate to **Approvals** in the sidebar to see the pending queue. Click **Review** on any pending request to approve or reject with an optional note.

---

### 23.7 Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| Report returns empty | No certificates match the criteria | Issue some certificates first |
| Audit integrity shows `broken_at_id` | Database was manually modified | Investigate the event at that ID; hash chain cannot be repaired |
| CEF export not accepted by SIEM | Format version mismatch | Verify your SIEM accepts CEF:0 format |
| Name constraint rejection | SAN doesn't match CA's permitted subtrees | Use a CA without constraints, or add the domain to permitted list |
| Approval not triggered | Template doesn't have `require_approval: true` | Update the template |
| Admin still gets queued | Should not happen — admins bypass approval | Verify the user's role is `admin` (not `operator`) |
| Policy OID not in certificate | CA doesn't have `policy_oid` set | Update the CA (requires re-creation — OID is set at CA creation time) |

---

## 24. Environment Provisioning

The Environment Provisioning feature generates a complete SSL certificate bundle for an SSP (Shared Services Platform) deployment across 5 machines in a single operation.

---

### 24.1 Overview

A wizard-driven workflow that creates:
- A dedicated internal CA for the environment
- Server certificates for each machine (MySQL, RabbitMQ, Keystone, Backend, Frontend)
- Client certificates for mTLS (Backend, Frontend)
- PKCS#12 keystores and truststores per machine
- Encrypted private keys (BouncyCastle-compatible) and unencrypted `.key.nopass` variants
- Config snippets for each service (ready to paste)
- Deployment scripts (distribute via SSH, verify installation)
- Pre-filled `quicksetup-ssl.properties` with Jasypt-encrypted passwords

---

### 24.2 Architecture

**5 machines, single CA trust model:**

| Machine | Server Cert | Client Cert | mTLS Role |
|---------|:-----------:|:-----------:|-----------|
| MySQL | ✓ | — | Server (verifies client certs from Backend) |
| RabbitMQ | ✓ | — | Server (verifies client certs from Backend/Frontend) |
| Keystone | ✓ | — | Server only (token auth handles identity) |
| Backend | ✓ | ✓ | Server + Client (calls MySQL, RabbitMQ, Frontend) |
| Frontend | ✓ | ✓ | Server + Client (calls Backend, RabbitMQ) |

**mTLS connection matrix:**

```
                  MySQL    RabbitMQ    Keystone    Backend    Frontend
MySQL             —        —           —           accepts    —
RabbitMQ          —        —           —           accepts    accepts
Keystone          —        —           —           serves     —
Backend           connects connects    connects    —          accepts
Frontend          —        connects    —           connects   —
```

- **accepts** = verifies client cert (mTLS server side)
- **connects** = presents client cert (mTLS client side)
- **serves** = server TLS only (no client cert required)

All truststores contain only the environment CA cert — since every certificate is issued by the same CA, this provides universal trust within the environment.

---

### 24.3 Password Encryption (Jasypt)

The provisioning engine encrypts passwords using `PBEWITHSHA256AND256BITAES-CBC-BC` — the same algorithm used by Jasypt with BouncyCastle in your Spring Boot services.

**How it works:**
1. You provide a plaintext password (e.g., `changeit`) and an encryption key (e.g., `ecssecret`)
2. The engine derives a 256-bit AES key and IV using PKCS#12 v1 KDF (SHA-256, 1000 iterations)
3. Encrypts with AES-256-CBC
4. Outputs Base64-encoded `salt + ciphertext` wrapped in `ENC(...)`

**Example:**
```
Input:  plaintext = "changeit", key = "ecssecret"
Output: ENC(sAyPK8FIwtMFRtJot99dGvo1TKccMQnD/DKvLYvhD94=)
```

The encrypted values are directly compatible with Java Jasypt `StandardPBEStringEncryptor` configured with:
```java
encryptor.setAlgorithm("PBEWITHSHA256AND256BITAES-CBC-BC");
encryptor.setPassword("ecssecret");
encryptor.setKeyObtentionIterations(1000);
```

**Spring Boot Jasypt configuration:**
```yaml
jasypt:
  encryptor:
    algorithm: PBEWITHSHA256AND256BITAES-CBC-BC
    provider-name: BC
    key-obtention-iterations: 1000
```

The `propertiesEncryptionKey` from `setup.properties` is the Jasypt master password.

---

### 24.4 Bundle Structure

The generated ZIP contains:

```
{env-name}-ssl/
├── ca/
│   ├── ca.pem                          CA certificate (PEM)
│   ├── ca.der                          CA certificate (DER)
│   └── README.md
├── mysql/
│   ├── certs/
│   │   ├── server-cert.pem             Server certificate
│   │   ├── server.key                  Private key (encrypted PKCS#8)
│   │   ├── server.key.nopass           Private key (unencrypted)
│   │   └── ca.pem                      CA cert (for trust)
│   ├── stores/
│   │   ├── keystore.p12                Server identity keystore
│   │   └── truststore.p12             Trust store (CA cert)
│   ├── config/
│   │   └── ssl.cnf.snippet             MySQL SSL configuration
│   └── README.md
├── rabbitmq/
│   ├── certs/
│   │   ├── server-cert.pem
│   │   ├── server.key
│   │   ├── server.key.nopass
│   │   └── ca.pem
│   ├── config/
│   │   └── rabbitmq-ssl.conf.snippet   RabbitMQ TLS + mTLS config
│   └── README.md
├── keystone/
│   ├── certs/
│   │   ├── server-cert.pem
│   │   ├── server.key
│   │   ├── server.key.nopass
│   │   └── ca.pem
│   ├── config/
│   │   └── apache-ssl.conf.snippet     Apache VirtualHost SSL config
│   └── README.md
├── backend/
│   ├── certs/
│   │   ├── server-cert.pem             Server certificate
│   │   ├── server.key                  Server key (encrypted)
│   │   ├── server.key.nopass           Server key (plain)
│   │   ├── client-cert.pem             Client certificate (for mTLS)
│   │   ├── client.key                  Client key (encrypted)
│   │   ├── client.key.nopass           Client key (plain)
│   │   └── ca.pem
│   ├── stores/
│   │   ├── server-keystore.p12         Server identity
│   │   ├── client-keystore.p12         Client identity (outbound mTLS)
│   │   └── truststore.p12             Trust store
│   ├── config/
│   │   └── application-ssl.yml.snippet Spring Boot SSL config
│   └── README.md
├── frontend/
│   ├── (same structure as backend)
│   └── README.md
├── scripts/
│   ├── distribute-certs.sh             SCP distribution script
│   └── verify-certs.sh                 Verification script
├── quicksetup-ssl.properties           Pre-filled SSL properties
└── DEPLOYMENT-GUIDE.md                 Step-by-step deployment
```

---

### 24.5 Certificate SANs

Every certificate includes these Subject Alternative Names:
- The machine's FQDN (e.g., `ssp-backend.mycompany.com`)
- The machine's IP address (e.g., `10.0.1.13`)
- `localhost`
- `127.0.0.1`

The `localhost` and `127.0.0.1` entries allow services to communicate locally (health checks, same-machine calls) without certificate validation failures.

---

### 24.6 Cipher Profiles

Three profiles are available:

| Profile | TLS Versions | Minimum Client | Use When |
|---------|-------------|----------------|----------|
| **Modern** | 1.3 only | Java 11, OpenSSL 1.1.1 | All clients are recent. Best security. |
| **Intermediate** | 1.2 + 1.3 | Java 8u292+, OpenSSL 1.0.2 | Mix of modern and older clients. Recommended. |
| **Legacy** | 1.1 + 1.2 + 1.3 | Java 7, OpenSSL 0.9.8 | Must support very old clients. Not recommended. |

---

### 24.7 File Deployment

Default base path: `/opt/scripts/ssl/`

The generated `distribute-certs.sh` script uses passwordless SSH to copy files to each machine:

```bash
# Run from jumpserver (where the ZIP was extracted)
chmod +x scripts/distribute-certs.sh
./scripts/distribute-certs.sh
```

The script:
1. Creates directory structure on each machine
2. Copies certs, keys, and stores via SCP
3. Sets permissions (`600` for keys/stores, `644` for certs)
4. Distributes the CA cert to all machines

Verify deployment:
```bash
chmod +x scripts/verify-certs.sh
./scripts/verify-certs.sh
```

---

### 24.8 API Usage

Generate a bundle via the API:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/provisioning/generate \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "env_name": "ssp-prod",
    "hosts": [
      {"role": "mysql", "fqdn": "mysql.mycompany.com", "ip": "10.0.1.10"},
      {"role": "rabbitmq", "fqdn": "rabbitmq.mycompany.com", "ip": "10.0.1.11"},
      {"role": "keystone", "fqdn": "keystone.mycompany.com", "ip": "10.0.1.12"},
      {"role": "backend", "fqdn": "ssp-backend.mycompany.com", "ip": "10.0.1.13"},
      {"role": "frontend", "fqdn": "ssp-frontend.mycompany.com", "ip": "10.0.1.14"}
    ],
    "ssl_passphrase": "changeit",
    "encryption_key": "ecssecret",
    "key_algo": "RSA",
    "key_size": 2048,
    "ca_validity_days": 3650,
    "cert_validity_days": 365,
    "cipher_profile": "intermediate",
    "base_path": "/opt/scripts/ssl",
    "include_nopass": true,
    "include_snippets": true,
    "include_scripts": true,
    "include_readmes": true,
    "include_quicksetup": true
  }' --output ssp-prod-ssl.zip
```

Response: ZIP file download (application/zip).

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `env_name` | string | required | Environment name (used as CA CN prefix and folder name) |
| `hosts` | array | required | 5 host objects with `role`, `fqdn`, `ip` |
| `ssl_passphrase` | string | required | Password for keystores and encrypted keys |
| `encryption_key` | string | required | Jasypt master password (`propertiesEncryptionKey`) |
| `key_algo` | string | `RSA` | Key algorithm: `RSA` or `ECDSA` |
| `key_size` | int | `2048` | Key size: 2048, 4096 (RSA) or 256, 384 (ECDSA) |
| `ca_validity_days` | int | `3650` | CA certificate validity |
| `cert_validity_days` | int | `365` | Leaf certificate validity |
| `cipher_profile` | string | `intermediate` | Cipher suite profile: `modern`, `intermediate`, `legacy` |
| `base_path` | string | `/opt/scripts/ssl` | Target path on machines |
| `include_nopass` | bool | `true` | Include unencrypted `.key.nopass` files |
| `include_snippets` | bool | `true` | Include service config snippets |
| `include_scripts` | bool | `true` | Include distribute/verify scripts |
| `include_readmes` | bool | `true` | Include per-machine README files |
| `include_quicksetup` | bool | `true` | Include quicksetup-ssl.properties |

---

### 24.9 Generated Config Snippets

Each snippet is production-ready and copy-paste compatible. Cipher suites, TLS versions, and paths are automatically populated based on your wizard selections.

**MySQL (`ssl.cnf.snippet`):**
```ini
[mysqld]
ssl-ca=/opt/scripts/ssl/mysql/certs/ca.pem
ssl-cert=/opt/scripts/ssl/mysql/certs/server-cert.pem
ssl-key=/opt/scripts/ssl/mysql/certs/server.key.nopass
require_secure_transport=ON
tls_version=TLSv1.2,TLSv1.3
ssl-cipher=ECDHE-RSA-AES256-GCM-SHA384:ECDHE-RSA-AES128-GCM-SHA256:...

[client]
ssl-ca=/opt/scripts/ssl/mysql/certs/ca.pem
ssl-mode=VERIFY_IDENTITY
```

Also includes: SQL user grants with `REQUIRE X509`, JDBC URL with full SSL parameters, verification commands.

**RabbitMQ (`rabbitmq-ssl.conf.snippet`):**
```ini
listeners.tcp = none
listeners.ssl.default = 5671
ssl_options.cacertfile = /opt/scripts/ssl/rabbitmq/certs/ca.pem
ssl_options.certfile = /opt/scripts/ssl/rabbitmq/certs/server-cert.pem
ssl_options.keyfile = /opt/scripts/ssl/rabbitmq/certs/server.key.nopass
ssl_options.verify = verify_peer
ssl_options.fail_if_no_peer_cert = true
ssl_options.ciphers.1 = TLS_AES_256_GCM_SHA384
ssl_options.ciphers.2 = ...
```

Also includes: management UI SSL (port 15671), inter-node TLS (clustering), STOMP/MQTT over TLS sections (commented), verification commands.

**Spring Boot (`application-ssl.yml.snippet`):**
```yaml
server:
  port: 8443
  ssl:
    enabled: true
    key-store: file:/opt/scripts/ssl/backend/stores/server-keystore.p12
    key-store-type: PKCS12
    key-store-password: ENC(generated_value)
    client-auth: need
    trust-store: file:/opt/scripts/ssl/backend/stores/truststore.p12
    trust-store-password: ENC(generated_value)
    enabled-protocols: TLSv1.2,TLSv1.3
    ciphers: TLS_AES_256_GCM_SHA384,...
```

Also includes: Jasypt config, Spring SSL Bundles (3.1+), datasource SSL with mTLS JDBC URL, RabbitMQ SSL connection, Keystone/Backend connection config, JVM arguments.

**Apache/Keystone (`apache-ssl.conf.snippet`):**
```apache
<VirtualHost *:5000>
    SSLEngine on
    SSLCertificateFile /opt/scripts/ssl/keystone/certs/server-cert.pem
    SSLCertificateKeyFile /opt/scripts/ssl/keystone/certs/server.key.nopass
    SSLCACertificateFile /opt/scripts/ssl/keystone/certs/ca.pem
    SSLProtocol all -SSLv3 -TLSv1 -TLSv1.1
    SSLCipherSuite ECDHE-RSA-AES256-GCM-SHA384:...
</VirtualHost>
```

Also includes: HSTS header, security headers, required Apache modules, verification commands.

**quicksetup-ssl.properties:**

Contains all SSL-related properties for `buildProperties_p3.py`:
- SSL enabled flags, passphrase (plain + ENC), cipher suites, protocols
- Jasypt algorithm and master key
- All 5 hostnames and IPs
- Database JDBC URL with full SSL + mTLS parameters
- RabbitMQ SSL keystore/truststore paths and passwords
- Keystone HTTPS endpoint
- All certificate file paths

---

### 24.10 Cipher Profiles API

Retrieve available cipher profiles with descriptions:

```bash
curl -s -H "X-API-Key: $API_KEY" \
  http://127.0.0.1:8000/api/v1/provisioning/cipher-profiles
```

Response:
```json
{
  "profiles": {
    "modern": {
      "label": "Modern (TLS 1.3 only)",
      "description": "Best security. Requires Java 11+, OpenSSL 1.1.1+.",
      "protocols": "TLSv1.3",
      "ciphers": "TLS_AES_256_GCM_SHA384,...",
      "openssl_ciphers": "TLS_AES_256_GCM_SHA384:..."
    },
    "intermediate": { ... },
    "legacy": { ... }
  }
}
```

---

### 24.11 Reusable Templates

Wizard configurations can be saved as templates via the API. Next time you provision a new environment (staging, DR, etc.), load the template, update hostnames/IPs, and regenerate.

**Create a template:**

```bash
curl -s -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/provisioning/templates \
  -d '{
    "name": "standard-dev",
    "description": "Standard dev environment",
    "config": {
      "env_name": "dev",
      "hosts": [
        {"role": "mysql", "fqdn": "mysql.dev.local", "ip": "10.0.1.10"},
        {"role": "rabbitmq", "fqdn": "rabbit.dev.local", "ip": "10.0.1.11"},
        {"role": "keystone", "fqdn": "keystone.dev.local", "ip": "10.0.1.12"},
        {"role": "backend", "fqdn": "backend.dev.local", "ip": "10.0.1.13"},
        {"role": "frontend", "fqdn": "frontend.dev.local", "ip": "10.0.1.14"}
      ],
      "ssl_passphrase": "changeit",
      "encryption_key": "ecssecret"
    }
  }'
```

**List templates:**

```bash
curl -s -H "X-API-Key: $API_KEY" \
  http://127.0.0.1:8000/api/v1/provisioning/templates
```

**Load a template (by ID or name):**

```bash
curl -s -H "X-API-Key: $API_KEY" \
  http://127.0.0.1:8000/api/v1/provisioning/templates/standard-dev
```

**Update a template:**

```bash
curl -s -X PUT -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/provisioning/templates/standard-dev \
  -d '{"description": "Updated description"}'
```

**Delete a template:**

```bash
curl -s -X DELETE -H "X-API-Key: $API_KEY" \
  http://127.0.0.1:8000/api/v1/provisioning/templates/standard-dev
```

**What templates store:**
- Full configuration (env name, hosts, key algo, validity, cipher profile, options, base path)
- Passwords and hostnames ARE stored in the template (unlike the wizard UI which will prompt fresh)
- Created-by user and timestamps

---

### 24.12 RBAC

| Action | Admin | Operator | Auditor | ReadOnly |
|--------|:-----:|:--------:|:-------:|:--------:|
| Generate bundle | ✓ | ✓ | ✗ | ✗ |
| View cipher profiles | ✓ | ✓ | ✗ | ✗ |
| List/load templates | ✓ | ✓ | ✗ | ✗ |
| Create/update/delete templates | ✓ | ✗ | ✗ | ✗ |

All provisioning operations are recorded in the audit trail.

---

### 24.13 Frontend Wizard

The **Provisioning** page (accessible from the sidebar) provides a 4-step wizard for generating SSL bundles without using the API directly.

#### Step 1 — Environment & Security

- **Environment Name** — used as the ZIP filename and CA CN prefix
- **Key Algorithm** — RSA (2048/3072/4096) or ECDSA (P-256/P-384)
- **CA Validity** — how long the environment CA is valid (365–7300 days)
- **Cert Validity** — how long leaf certificates are valid (30–3650 days)
- **SSL Passphrase** — password for all keystores and truststores (🎲 auto-generate button)
- **Jasypt Encryption Key** — master password for `ENC(...)` values (🎲 auto-generate button)
- **Cipher Profile** — radio buttons with inline descriptions (Modern / Intermediate / Legacy)

#### Step 2 — Hosts

5 rows for MySQL, RabbitMQ, Keystone, Backend, and Frontend. Each row requires:
- **FQDN** — fully qualified domain name (e.g., `mysql.prod.internal`)
- **IP** — IPv4 address (validated format)

Both are added as SANs on the generated certificates along with `localhost` and `127.0.0.1`.

#### Step 3 — Options

Toggle which optional outputs to include in the ZIP:

| Option | Default | Description |
|--------|:-------:|-------------|
| Unencrypted keys (.key.nopass) | ✓ | Plain PKCS#8 keys for services that cannot use encrypted keys |
| Config snippets | ✓ | MySQL, RabbitMQ, Keystone, Spring Boot SSL configuration |
| Deployment scripts | ✓ | distribute-certs.sh and verify-certs.sh |
| Per-machine READMEs | ✓ | Instructions for each machine role |
| Quicksetup properties | ✓ | quicksetup-ssl.properties with ENC(...) values |

Also configurable: **Base Path** — the target directory on remote machines (default `/opt/scripts/ssl`).

#### Step 4 — Review & Generate

- Summary grid showing all configuration choices
- Host table with role, FQDN, and IP
- Bundle contents preview (cert count, keystore count, CA)
- mTLS connection matrix showing which services connect to which
- **Generate & Download ZIP** button with loading spinner

On success, the browser downloads the ZIP file directly.

#### Template Save/Load

At the top of the page:
- **Load template** dropdown — select a saved template to populate all wizard fields
- **Save** button — save the current wizard state as a named template for reuse

Templates store the full configuration including hosts, passwords, and options. Useful for provisioning multiple environments (dev, staging, prod) with the same structure but different hostnames.

---

### 24.14 Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `ENC(...)` value not decrypted at runtime | Wrong `propertiesEncryptionKey` | Verify the encryption key matches between generation and `setup.properties` |
| Keystore password rejected | Password mismatch | Ensure `javaSecurityPassword` matches what was entered in the wizard |
| mTLS handshake fails | Client cert not trusted | Verify the target service's truststore contains the environment CA cert |
| `PKIX path building failed` | Truststore missing or wrong path | Check `trust-store` path in `application-ssl.yml` |
| Certificate hostname mismatch | Connecting via unexpected hostname | Ensure the FQDN/IP used to connect matches a SAN in the cert |
| RabbitMQ rejects connection | `fail_if_no_peer_cert = true` but no client cert presented | Configure the connecting service to present its client keystore |
| MySQL SSL connection refused | `require_secure_transport=ON` but client not using SSL | Add SSL parameters to JDBC URL or `my.cnf` client section |
| Wizard "Next" button disabled | Required fields not filled | Step 1: env name + passphrase (≥6 chars) + encryption key (≥6 chars). Step 2: all 5 hosts need FQDN + IP |
| ZIP download fails | API returns error blob | Check the red error message on Step 4; common cause: backend not running or auth expired |
| Invalid FQDN format (red border) | Hostname contains invalid characters | Use only alphanumeric, hyphens, and dots. Must start/end with alphanumeric |
| Duplicate FQDN/IP error | Two hosts share the same FQDN or IP | Each machine must have a unique FQDN and unique IP address |

### 24.15 Testing & Validation

The provisioning feature includes a comprehensive test suite (`backend/tests/test_provisioning.py`) with 53 tests covering:

**ZIP Structure (15 tests):** Verifies all expected files are present — CA, server certs, client certs, keystores, truststores, config snippets, scripts, READMEs, quicksetup properties, and deployment guide.

**Certificate Validation (7 tests):** CA is self-signed with `CA:TRUE`, all server certs contain correct SANs (FQDN + IP + localhost + 127.0.0.1), all issued certs chain to the generated CA, DER matches PEM.

**Key Validation (5 tests):** Encrypted keys require passphrase, open with correct passphrase, `.key.nopass` opens without passphrase, nopass matches encrypted key (same public numbers), key matches certificate.

**Keystore Validation (4 tests):** Server keystores open with correct password and contain CA chain, truststores contain CA cert with no private key, client keystores open correctly.

**Jasypt Encryption (3 tests):** Quicksetup contains `ENC(...)` values, all encrypted values decrypt correctly with the provided encryption key, Spring Boot snippets contain encrypted values.

**Config Snippets (4 tests):** MySQL snippet has correct paths, RabbitMQ has listener config, Spring Boot has keystore references, frontend differs from backend.

**Options (3 tests):** Disabling nopass/snippets/scripts correctly excludes those files, single-host generation works.

**Cipher Profiles (2 tests):** Modern profile produces TLS 1.3 ciphers, legacy profile includes backward-compatible ciphers.

**API Endpoints (10 tests):** Generate returns valid ZIP, validation rejects missing env_name/short passphrase/invalid role/invalid cipher profile/empty hosts, cipher profiles endpoint works, template CRUD lifecycle, duplicate template name returns 409, unauthenticated requests return 401.

Run tests inside the container:
```bash
docker exec ssl-cert-manager /opt/certmanager/venv/bin/python -m pytest tests/test_provisioning.py -v
```

**Frontend Validation:**
- FQDN format: must match `^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*$`
- IP format: valid IPv4 with each octet 0-255
- Duplicate detection: red border + error message for duplicate FQDNs or IPs
- Password strength indicator: Weak / Fair / Good / Strong / Excellent
- "Next" button disabled until all validations pass

---


## 25. EST Protocol (RFC 7030)

Enrollment over Secure Transport (EST) enables automated certificate provisioning for devices and services. It is the modern replacement for SCEP and is supported by Cisco IOS-XE, Windows 10+, certbot, Traefik, and many embedded platforms.

---

### 25.1 Overview

EST provides a standard HTTP-based protocol for devices to:
- Discover CA certificates (trust bootstrap)
- Enroll for a new certificate (submit CSR, receive signed cert)
- Re-enroll (renew an existing certificate)
- Request server-side key generation (device cannot generate keys)

All endpoints are under `/.well-known/est/` as per RFC 7030 §3.2.2.

---

### 25.2 Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/.well-known/est/cacerts` | GET | None | CA certificate distribution |
| `/.well-known/est/simpleenroll` | POST | Required | Initial enrollment (CSR → cert) |
| `/.well-known/est/simplereenroll` | POST | Required | Re-enrollment (renewal) |
| `/.well-known/est/csrattrs` | GET | None | CSR attributes the server expects |
| `/.well-known/est/serverkeygen` | POST | Required | Server-side key generation |

---

### 25.3 Authentication

EST enrollment endpoints require authentication. Three methods are supported:

| Method | Header | Use Case |
|--------|--------|----------|
| API Key | `X-API-Key: <key>` | Automation, CI/CD pipelines |
| Bearer Token | `Authorization: Bearer <jwt>` | User-initiated enrollment |
| HTTP Basic (over TLS) | `Authorization: Basic <b64>` | Device enrollment (via standard EST clients) |

**Note:** The `/cacerts` and `/csrattrs` endpoints are public (no auth required) — devices need these to bootstrap trust before they can authenticate.

---

### 25.4 Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `EST_CA_ID` | (empty) | CA ID to use for EST enrollment. If empty, auto-selects the first available CA with a key. |

Set in `backend/.env` or environment:

```bash
# Use a specific CA for EST enrollment
EST_CA_ID=c9d6be88-7b70-4ae7-8c24-5cf456935b61
```

If not set, the system selects the first non-root CA with a key, or falls back to the first root CA with a key.

---

### 25.5 Client Examples

#### certbot

```bash
# Enroll using certbot with EST server
certbot certonly --server http://pki.internal/.well-known/est \
  --standalone --preferred-challenges http \
  -d myservice.internal
```

#### curl (Manual Enrollment)

```bash
# 1. Get CA certificates (trust bootstrap)
curl -s http://pki.internal/.well-known/est/cacerts | base64 -d > ca-chain.pem

# 2. Generate a CSR
openssl req -new -newkey rsa:2048 -nodes \
  -keyout device.key -out device.csr \
  -subj '/CN=device01.internal' \
  -addext 'subjectAltName=DNS:device01.internal'

# 3. Enroll (submit CSR, receive cert)
CSR_B64=$(openssl req -in device.csr -outform DER | base64 -w0)
curl -s -X POST http://pki.internal/.well-known/est/simpleenroll \
  -H 'Content-Type: application/pkcs10' \
  -H 'X-API-Key: <your-api-key>' \
  -d "$CSR_B64" | base64 -d > device.der

# 4. Convert to PEM
openssl x509 -inform DER -in device.der -out device.pem

# 5. Verify
openssl x509 -in device.pem -noout -subject -issuer -dates
```

#### OpenSSL (Re-enrollment)

```bash
# Re-enroll with existing key (renewal)
CSR_B64=$(openssl req -new -key device.key \
  -subj '/CN=device01.internal' \
  -addext 'subjectAltName=DNS:device01.internal' \
  -outform DER | base64 -w0)

curl -s -X POST http://pki.internal/.well-known/est/simplereenroll \
  -H 'Content-Type: application/pkcs10' \
  -H 'X-API-Key: <your-api-key>' \
  -d "$CSR_B64" | base64 -d | openssl x509 -inform DER -out device-renewed.pem
```

#### Server-Side Key Generation

```bash
# Device submits CSR for subject info, server generates the key
CSR_B64=$(openssl req -new -newkey rsa:2048 -nodes \
  -keyout /dev/null -subj '/CN=iot-sensor-42' \
  -addext 'subjectAltName=DNS:iot-sensor-42.internal' \
  -outform DER 2>/dev/null | base64 -w0)

curl -s -X POST http://pki.internal/.well-known/est/serverkeygen \
  -H 'Content-Type: application/pkcs10' \
  -H 'X-API-Key: <your-api-key>' \
  -d "$CSR_B64" -o keygen-response.mime

# Response is multipart/mixed containing the private key and certificate
```

---

### 25.6 How It Works

```
Device/Service                    EST Server (this tool)
  │                                      │
  │── GET /cacerts ─────────────────────▶│  (get CA certs for trust)
  │◀── CA certificate chain ────────────│
  │                                      │
  │── POST /simpleenroll ───────────────▶│  (submit PKCS#10 CSR)
  │   + Authentication header            │
  │   + Base64-encoded DER CSR           │
  │                                      │
  │   Server validates:                  │
  │   1. Authentication (API key/JWT)    │
  │   2. CSR signature valid             │
  │   3. Resolves EST CA                 │
  │   4. Issues certificate              │
  │   5. Stores in certificate table     │
  │   6. Records audit event             │
  │                                      │
  │◀── Base64-encoded DER cert ─────────│
  │                                      │
  │   Device installs cert + key         │
```

---

### 25.7 Issued Certificate Properties

Certificates issued via EST:
- Use the CSR's public key (client retains the private key)
- Include all SANs from the CSR
- Get `server` profile with `serverAuth` EKU
- Include CDP and AIA extensions (if `PKI_BASE_URL` is configured)
- Are tagged `est-enrolled` (or `est-keygen` for server-generated keys)
- Validity: min(`MAX_CERT_DAYS`, 365) days
- Are stored in the same certificate table as all other certificates

---

### 25.8 Audit Events

| Event | Severity | Description |
|-------|----------|-------------|
| `EST_ENROLL` | INFO | Certificate issued via EST simpleenroll |
| `EST_REENROLL` | INFO | Certificate renewed via EST simplereenroll |
| `EST_KEYGEN` | WARNING | Server-side key generated (key material created and returned to client) |

All events record the authenticated user/key and source IP.

---

### 25.9 Security Considerations

- **Always use TLS** for EST in production — the protocol assumes transport security
- **Server-keygen** (`/serverkeygen`) returns private key material over the network — use only when the device cannot generate keys locally
- **Rate limiting** applies to EST endpoints (same as certificate issuance limits)
- **Template enforcement** is not applied to EST requests by default — EST uses the `server` profile
- **Unauthenticated endpoints** (`/cacerts`, `/csrattrs`) are public by design — they contain no sensitive data

---

### 25.10 Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `401 Missing or invalid authentication` | No API key or token provided | Add `X-API-Key` or `Authorization: Bearer` header |
| `400 Unable to parse CSR` | CSR not in expected format | Ensure CSR is base64-encoded DER (not raw PEM) |
| `400 CSR signature verification failed` | CSR was modified after signing | Regenerate the CSR |
| `503 No CA available for EST enrollment` | No CA with a key exists | Create a CA or set `EST_CA_ID` to a valid CA |
| Response is empty/garbled | Client not decoding base64 | Response body is base64-encoded DER — decode with `base64 -d` then convert with `openssl x509 -inform DER` |
| certbot fails | certbot expects ACME, not EST | Use `--server` flag with the EST directory URL; certbot EST support varies by version |

---


## 26. Multi-Tenancy

Multi-tenancy isolates CA hierarchies, certificates, and audit events by team or department. Each tenant has its own view of the PKI — users in one tenant cannot see or manage another tenant's resources.

---

### 26.1 Overview

- **Tenant** — an isolated namespace (team, department, project)
- **Default tenant** — all existing data belongs to the `default` tenant for backward compatibility
- **Global admin** — can operate across all tenants (legacy API key and admin-role users)
- **Tenant member** — a user assigned to one or more tenants; sees only their tenant's resources

```
┌─────────────────────────────────────────────────────┐
│ Global Admin (cross-tenant)                          │
├─────────────────────────────────────────────────────┤
│                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────┐  │
│  │ Tenant:      │  │ Tenant:      │  │ Tenant:  │  │
│  │ default      │  │ team-alpha   │  │ team-beta│  │
│  │              │  │              │  │          │  │
│  │ CAs          │  │ CAs          │  │ CAs      │  │
│  │ Certificates │  │ Certificates │  │ Certs    │  │
│  │ CSRs         │  │ CSRs         │  │ CSRs     │  │
│  │ Audit events │  │ Audit events │  │ Audit    │  │
│  └──────────────┘  └──────────────┘  └──────────┘  │
└─────────────────────────────────────────────────────┘
```

---

### 26.2 Tenant Scoping

All list endpoints are automatically filtered by the active tenant:

| Resource | Scoped |
|----------|:------:|
| Certificate Authorities | ✓ |
| Certificates | ✓ |
| CSRs | ✓ |
| Trust Stores | ✓ |
| Audit Events | ✓ |
| API Keys | ✓ |
| Pending Requests | ✓ |

**Global admins** see all resources across all tenants (no filtering applied).

---

### 26.3 Selecting the Active Tenant

The active tenant is determined by (in priority order):

1. **`X-Tenant` header** — slug of the desired tenant (e.g., `X-Tenant: team-alpha`)
2. **JWT `tenant_id` claim** — set at login time from the user's first membership
3. **Default** — `default` tenant if nothing else specified

```bash
# List CAs in team-alpha tenant
curl -s -H "X-API-Key: $API_KEY" -H "X-Tenant: team-alpha" \
  http://127.0.0.1:8000/api/v1/ca

# List CAs in default tenant (no header needed)
curl -s -H "X-API-Key: $API_KEY" http://127.0.0.1:8000/api/v1/ca
```

**Frontend:** The sidebar shows a tenant dropdown when multiple tenants exist. Selecting a tenant stores it in localStorage and sends `X-Tenant` on all API requests.

---

### 26.4 Tenant Management (Global Admin Only)

#### Create a Tenant

```bash
curl -s -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/tenants \
  -d '{"name": "Team Alpha", "slug": "team-alpha", "description": "Alpha team PKI"}'
```

Slug must be lowercase alphanumeric with hyphens only.

#### List Tenants

```bash
curl -s -H "X-API-Key: $API_KEY" http://127.0.0.1:8000/api/v1/tenants
```

Non-admin users only see tenants they belong to.

#### Update a Tenant

```bash
curl -s -X PUT -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/tenants/<tenant_id> \
  -d '{"name": "New Name", "description": "Updated description"}'
```

#### Delete a Tenant

```bash
curl -s -X DELETE -H "X-API-Key: $API_KEY" \
  http://127.0.0.1:8000/api/v1/tenants/<tenant_id>
```

Deletion is blocked if the tenant still has CAs. Move or delete resources first. The `default` tenant cannot be deleted.

---

### 26.5 Membership Management

#### Add a User to a Tenant

```bash
curl -s -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/tenants/<tenant_id>/members \
  -d '{"user_id": "<user-uuid>", "tenant_role": "operator"}'
```

The `tenant_role` field is optional — if set, it overrides the user's global role within that tenant.

#### List Members

```bash
curl -s -H "X-API-Key: $API_KEY" \
  http://127.0.0.1:8000/api/v1/tenants/<tenant_id>/members
```

#### Remove a Member

```bash
curl -s -X DELETE -H "X-API-Key: $API_KEY" \
  http://127.0.0.1:8000/api/v1/tenants/<tenant_id>/members/<user_id>
```

---

### 26.6 RBAC

| Action | Global Admin | Tenant Admin | Operator | ReadOnly |
|--------|:------------:|:------------:|:--------:|:--------:|
| Create/delete tenants | ✓ | ✗ | ✗ | ✗ |
| Manage tenant members | ✓ | ✗ | ✗ | ✗ |
| View all tenants | ✓ | ✗ | ✗ | ✗ |
| View own tenants | ✓ | ✓ | ✓ | ✓ |
| Create CA (within tenant) | ✓ | ✓ | ✗ | ✗ |
| Issue cert (within tenant) | ✓ | ✓ | ✓ | ✗ |

**Global admin** = admin-role user or legacy API key. Can see and operate on all tenants.

---

### 26.7 Frontend Tenant Switcher

When multiple tenants exist, a dropdown appears in the sidebar below the application title:

- Shows all tenants the user belongs to
- Selecting a tenant reloads the page with the new context
- The selection persists in localStorage across sessions
- Hidden when only one tenant exists (backward compatible)

The **Tenants** page (admin only, in sidebar) provides:
- Tenant list with member counts
- Create/delete tenants
- View and manage members per tenant

---

### 26.8 Migration & Backward Compatibility

- All existing data is assigned to the `default` tenant during migration
- All existing users are added as members of the `default` tenant
- The legacy API key operates as global admin (sees all tenants)
- No configuration changes required — single-tenant deployments work identically
- The `X-Tenant` header is optional — omitting it uses the default tenant

---

### 26.9 Audit Events

| Event | Severity | Description |
|-------|----------|-------------|
| `TENANT_CREATED` | INFO | New tenant created |
| `TENANT_UPDATED` | INFO | Tenant name/description changed |
| `TENANT_DELETED` | WARNING | Tenant removed |
| `TENANT_MEMBER_ADDED` | INFO | User added to tenant |
| `TENANT_MEMBER_REMOVED` | INFO | User removed from tenant |

All audit events include `tenant_id` — the audit log is tenant-scoped (non-admin users only see their tenant's events).

---

### 26.10 Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `404 Tenant 'xxx' not found` | X-Tenant header has wrong slug | Check slug with `GET /api/v1/tenants` |
| `403 Not a member of this tenant` | Non-admin user trying to access a tenant they don't belong to | Add user to tenant via membership API |
| `403 This operation requires global admin privileges` | Non-admin trying to create/delete tenants | Only admin-role users can manage tenants |
| `409 Tenant has N CA(s)` | Trying to delete tenant with resources | Delete or move CAs first |
| `409 Tenant slug already exists` | Duplicate slug | Choose a different slug |
| Tenant switcher not showing | Only one tenant exists | Create additional tenants for it to appear |
| New CA not visible | Created in wrong tenant | Check X-Tenant header; verify with `GET /api/v1/auth/me` to see active tenant_id |

---


## 27. Certificate Transparency (Internal)

An internal Certificate Transparency log provides an append-only, tamper-evident record of all issued certificates. Unlike the audit log (which records operations), the CT log is a cryptographic Merkle tree that enables independent verification of certificate issuance.

---

### 27.1 Overview

Every certificate issued by this tool is automatically submitted to the internal CT log. Each entry receives a Signed Certificate Timestamp (SCT) proving it was logged at a specific time.

**Key properties:**
- **Append-only** — entries cannot be modified or deleted without breaking the Merkle tree
- **Verifiable** — anyone with read access can verify tree consistency
- **Searchable** — query by domain, CA, or time range
- **Anomaly detection** — automatic alerts for wildcard certs, unknown issuers

---

### 27.2 How It Works

```
Certificate Issuance
        │
        ▼
┌─────────────────────────────────────┐
│ CT Log Submission                    │
│                                      │
│  1. Compute SHA-256 of cert DER      │
│  2. Allocate next log index          │
│  3. Compute leaf hash (RFC 6962)     │
│  4. Generate SCT (HMAC-signed)       │
│  5. Store entry in ct_log_entries    │
└─────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────┐
│ Merkle Tree                          │
│                                      │
│  Leaf hashes form a binary tree:     │
│                                      │
│         root_hash                    │
│        /         \                   │
│    H(L1+L2)    H(L3+L4)            │
│    /    \       /    \              │
│   L1    L2    L3    L4             │
└─────────────────────────────────────┘
```

**Leaf hash:** `SHA-256(0x00 || entry_data)` where entry_data = `index|timestamp|cert_der_hash|serial`

**Node hash:** `SHA-256(0x01 || left_hash || right_hash)`

---

### 27.3 API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/v1/ct/entries` | Required | Query CT log entries (paginated, filterable) |
| GET | `/api/v1/ct/entries/{log_index}` | Required | Get single entry by index |
| GET | `/api/v1/ct/sth` | Required | Get current Signed Tree Head |
| POST | `/api/v1/ct/verify` | audit:read | Verify Merkle tree consistency |
| GET | `/api/v1/ct/anomalies` | audit:read | Detect anomalous certificates |
| GET | `/api/v1/ct/stats` | Required | CT log statistics |

---

### 27.4 Querying the Log

```bash
# List all entries (paginated)
curl -s -H "X-API-Key: $API_KEY" \
  "http://127.0.0.1:8000/api/v1/ct/entries?page=1&page_size=25"

# Search by domain
curl -s -H "X-API-Key: $API_KEY" \
  "http://127.0.0.1:8000/api/v1/ct/entries?domain=*.corp.internal"

# Filter by CA
curl -s -H "X-API-Key: $API_KEY" \
  "http://127.0.0.1:8000/api/v1/ct/entries?ca_id=<ca-uuid>"

# Filter by date (ISO 8601)
curl -s -H "X-API-Key: $API_KEY" \
  "http://127.0.0.1:8000/api/v1/ct/entries?since=2026-01-01"
```

Response:
```json
{
  "items": [
    {
      "log_index": 1,
      "cert_serial": "814fde8552f3b71c...",
      "cert_der_hash": "e324d4a4773b92db...",
      "issuer_ca_id": "c9d6be88-...",
      "subject_cn": "app1.corp.internal",
      "san": [{"type": "dns", "value": "app1.corp.internal"}],
      "leaf_hash": "4170151afd4712dd...",
      "timestamp": "2026-07-10T12:59:44",
      "sct": {
        "version": 1,
        "log_id": "78fd7ceb91d177ba...",
        "timestamp": 1783688384642,
        "log_index": 1,
        "signature": "88b72228825b2ff7..."
      }
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 25
}
```

---

### 27.5 Signed Tree Head (STH)

The STH represents the current state of the Merkle tree:

```bash
curl -s -H "X-API-Key: $API_KEY" http://127.0.0.1:8000/api/v1/ct/sth
```

Response:
```json
{
  "tree_size": 2,
  "root_hash": "17b68df23b5a4070...",
  "timestamp": "2026-07-10T13:26:14+00:00",
  "signature": "1399ab007be75bc7..."
}
```

The signature is an HMAC-SHA256 over `tree_size|timestamp|root_hash` using the application's master key.

---

### 27.6 Tree Verification

Verify the Merkle tree is consistent (no gaps, no tampered entries):

```bash
curl -s -X POST -H "X-API-Key: $API_KEY" \
  http://127.0.0.1:8000/api/v1/ct/verify
```

Response:
```json
{
  "total_entries": 2,
  "computed_root": "17b68df23b5a4070...",
  "issues": [],
  "consistent": true,
  "root_matches_stored": true
}
```

**Checks performed:**
- No gaps in log index sequence (1, 2, 3, ...)
- Each leaf hash matches recomputed hash from stored data
- Computed root matches last stored tree head (if available)

If `consistent: false`, the `issues` array describes what's wrong.

---

### 27.7 Anomaly Detection

Scan the CT log for suspicious certificates:

```bash
curl -s -H "X-API-Key: $API_KEY" http://127.0.0.1:8000/api/v1/ct/anomalies
```

Response:
```json
{
  "alerts": [
    {
      "type": "wildcard_cert",
      "severity": "medium",
      "log_index": 2,
      "cert_serial": "39111beaff6db9aa...",
      "subject_cn": "*.wildcard.corp.internal",
      "timestamp": "2026-07-10T13:21:35",
      "message": "Wildcard certificate issued: *.wildcard.corp.internal"
    }
  ],
  "count": 1
}
```

**Anomaly types detected:**

| Type | Severity | Trigger |
|------|----------|---------|
| `wildcard_cert` | Medium | Certificate CN starts with `*.` |
| `unknown_issuer` | High | Certificate signed by a CA not in the database |

---

### 27.8 Frontend CT Log Viewer

Navigate to **CT Log** in the sidebar to access the viewer:

- **Log Entries tab** — searchable, paginated table of all logged certificates
- **Verify Tree tab** — one-click Merkle tree consistency check
- **Anomalies tab** — scan for suspicious certificates

The tree head summary (size, root hash, last update) is always visible at the top.

---

### 27.9 Tenant Scoping

CT log entries are tenant-scoped:
- Non-admin users only see entries from their active tenant
- Global admins see all entries across all tenants
- The `tenant_id` is set at submission time based on the issuing user's context

---

### 27.10 Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| CT log empty | No certificates issued since feature was deployed | Issue a certificate — it's automatically logged |
| Leaf hash mismatch | Entry was created before a timestamp fix | Delete the affected entry and re-verify |
| `consistent: false` with gaps | Database was manually modified | CT log is append-only — gaps indicate tampering or data loss |
| Anomaly false positive (wildcard) | Legitimate wildcard cert | Expected — review and dismiss |
| SCT signature invalid | Master key changed since entry was created | SCTs are signed with the current master key — key rotation invalidates old signatures |

---


---

## 28. Email Notifications

Email notifications alert users to certificate expiry, issuance, approval requests, and security events without requiring dashboard monitoring.

---

### 28.1 Overview

The notification system supports:
- **7 event types**: expiry warning, cert issued, approval required, approval decision, security event, auto-renewal, CA ceremony
- **Per-user subscriptions** with optional CA or tag filters
- **Digest mode**: batch notifications into a daily summary email
- **Mandatory notifications**: admin-set subscriptions users cannot disable
- **SMTP configuration** via UI or environment variables

---

### 28.2 SMTP Configuration

#### Environment Variables

```bash
SMTP_ENABLED=true
SMTP_HOST=smtp.corp.internal
SMTP_PORT=587
SMTP_USER=certmanager@corp.internal
SMTP_PASSWORD=<credential>
SMTP_FROM=PKI Alerts <pki@corp.internal>
SMTP_TLS=starttls   # starttls, ssl, none
NOTIFICATION_DIGEST_HOUR=8  # UTC hour for daily digest
```

#### Via API (Admin Only)

```bash
# Get current SMTP settings
curl -s -H "X-API-Key: $API_KEY" http://localhost:8000/api/v1/notifications/smtp

# Update SMTP settings
curl -s -X PUT -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/notifications/smtp \
  -d '{"enabled": true, "host": "smtp.corp.internal", "port": 587, "user": "pki", "password": "secret", "from_address": "pki@corp.internal", "tls": "starttls"}'

# Test SMTP connectivity
curl -s -X POST -H "X-API-Key: $API_KEY" http://localhost:8000/api/v1/notifications/smtp/test

# Send test email to current user
curl -s -X POST -H "X-API-Key: $API_KEY" http://localhost:8000/api/v1/notifications/smtp/test-email
```

---

### 28.3 Notification Events

| Event Type | Trigger | Default Recipients |
|------------|---------|-------------------|
| `expiry_warning` | Certificate crosses expiry threshold (60/30/7/0 days) | Subscribed users |
| `cert_issued` | New certificate issued | Subscribed users |
| `approval_required` | Certificate request queued for approval | Admins |
| `approval_decision` | Request approved or rejected | Requester |
| `security_event` | Key compromise, account lockout, etc. | All admins |
| `auto_renewal` | Certificate auto-renewed by background task | Certificate owner |

---

### 28.4 User Preferences

Users manage their own notification subscriptions:

```bash
# List my preferences
curl -s -H "X-API-Key: $API_KEY" http://localhost:8000/api/v1/notifications/preferences

# Subscribe to expiry warnings
curl -s -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/notifications/preferences \
  -d '{"event_type": "expiry_warning"}'

# Subscribe with CA filter (only certs from specific CA)
curl -s -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/notifications/preferences \
  -d '{"event_type": "cert_issued", "filter_ca_id": "<ca-uuid>"}'

# Enable digest mode (daily summary instead of immediate)
curl -s -X PUT -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/notifications/preferences/<pref_id> \
  -d '{"digest_mode": true}'

# Disable a subscription
curl -s -X PUT -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/notifications/preferences/<pref_id> \
  -d '{"enabled": false}'

# Delete a subscription
curl -s -X DELETE -H "X-API-Key: $API_KEY" \
  http://localhost:8000/api/v1/notifications/preferences/<pref_id>
```

---

### 28.5 Mandatory Notifications (Admin)

Admins can create subscriptions that users cannot disable:

```bash
curl -s -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/notifications/mandatory \
  -d '{"user_id": "<user-uuid>", "event_type": "security_event"}'
```

Mandatory notifications show a "mandatory" badge in the UI and cannot be toggled off or deleted by the user.

---

### 28.6 Digest Mode

When digest mode is enabled for a subscription, notifications are queued instead of sent immediately. A background task sends a daily summary email at the configured hour (UTC).

- Default digest hour: 08:00 UTC (configurable via `NOTIFICATION_DIGEST_HOUR`)
- Digest email lists all queued notifications from the past 24 hours
- Each item shows the subject line of the original notification

---

### 28.7 Frontend

Navigate to **Notifications** (📧) in the sidebar:

- **My Preferences** tab: view active subscriptions, toggle on/off, switch between immediate and digest mode, subscribe to new events
- **SMTP Settings** tab (admin only): configure SMTP host/port/credentials, test connection, send test email

---

### 28.8 Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| No emails sent | `SMTP_ENABLED=false` or `SMTP_HOST` empty | Enable SMTP in Settings or environment |
| SMTP test fails | Wrong host/port/credentials | Verify SMTP settings; check firewall allows outbound on port 587/465 |
| User not receiving emails | No email address on user account | Set email via `PUT /api/v1/users/{id}` |
| Digest not sending | Background task not running | Check container logs for "Digest scheduler" messages |
| Notifications not triggering | No matching preferences | User must subscribe to the event type |
| `SMTP_TLS` error | Wrong TLS mode for server | Try `ssl` (port 465) or `starttls` (port 587) |

---


## 29. Cross-Certification & Bridge CA

Cross-certification enables trust between independent CA hierarchies. During CA migrations, acquisitions, or multi-organisation trust, two independent roots need to trust each other without replacing either.

---

### 29.1 Overview

A cross-certificate is issued by your local CA for an external CA's public key. Clients trusting your CA can then validate certificates issued by the external CA — without importing the external root directly.

```
Root A (local)              Root B (external)
  |                           |
  |-- cross-signs ---------->|  (Root A issues cert for Root B's key)
  |                           |
  Clients trusting A          Can now validate
  via their existing          certs from B
  trust store                 through the cross-cert
```

**Use cases:**
- CA migration (old root → new root, both valid during transition)
- Acquisitions (trust partner's PKI without full merge)
- Multi-org trust (federated services across organisations)
- Temporary trust bridges (time-limited, revocable)

---

### 29.2 Creating a Cross-Certificate

#### Via UI

1. Navigate to **Cross-Certification** in the sidebar
2. Click **+ Cross-Sign CA**
3. Select the **Signing CA** (your local CA that will issue the cross-cert)
4. Paste the **External CA Certificate** (PEM format)
5. Set **Validity** (typically shorter than either root — e.g., 2 years)
6. Set **Path Length** (0 = external CA cannot issue sub-CAs through this bridge)
7. Optionally add **Name Constraints** (limit which domains the external CA can issue for)
8. Select **Direction** (outbound = we trust them; inbound = they trust us)
9. Click **Issue Cross-Certificate**

#### Via API

```bash
curl -s -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/cross-certs/<local-ca-id>/cross-sign \
  -d '{
    "external_ca_pem": "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----",
    "validity_days": 730,
    "path_length": 0,
    "direction": "outbound",
    "name_constraints": {
      "permitted": [".partner.com", ".vendor.internal"],
      "excluded": [".internal"]
    }
  }'
```

Response:
```json
{
  "id": "uuid...",
  "serial": "60eb2af0d49e778802f24f79007372c5",
  "issuing_ca_cn": "Test Root CA",
  "external_ca_cn": "External Partner CA",
  "direction": "outbound",
  "expires_at": "2028-07-09T16:21:39+00:00",
  "cross_cert_pem": "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----\n"
}
```

---

### 29.3 Name Constraints on Cross-Certificates

Name constraints limit what the cross-signed CA can issue certificates for. This is critical for security — without constraints, the external CA could issue certificates for any domain.

| Constraint | Effect |
|-----------|--------|
| `permitted: [".partner.com"]` | External CA can only issue for `*.partner.com` |
| `excluded: [".internal"]` | External CA cannot issue for `*.internal` |
| No constraints | External CA can issue for anything (dangerous) |

**Best practice:** Always add name constraints unless you fully trust the external CA for all domains.

---

### 29.4 Trust Bridge Dashboard

The Cross-Certification page shows:
- **Active Trust Bridges** — all current cross-certifications with direction, expiry, and constraints
- **Revoked Trust Bridges** — terminated relationships (for audit)

Each bridge shows:
- Issuing CA → External CA (with direction arrow)
- Serial number
- Expiry date
- Whether name constraints are applied
- Export and Revoke buttons

---

### 29.5 Revoking a Trust Bridge

To terminate a trust relationship:

```bash
curl -s -X POST -H "X-API-Key: $API_KEY" \
  http://127.0.0.1:8000/api/v1/cross-certs/<cross-cert-id>/revoke
```

Revocation:
- Sets status to `revoked` with timestamp
- Records `CROSS_CERT_REVOKED` audit event (WARNING severity)
- The cross-certificate should also be added to the issuing CA's CRL for full revocation propagation

---

### 29.6 Exporting Cross-Certificates

Export the cross-certificate and chain for distribution to relying parties:

```bash
curl -s -H "X-API-Key: $API_KEY" \
  http://127.0.0.1:8000/api/v1/cross-certs/<cross-cert-id>/export
```

Response:
```json
{
  "cross_cert_pem": "...",
  "external_ca_pem": "...",
  "chain_pem": "...",
  "issuing_ca_pem": "..."
}
```

The `chain_pem` contains the cross-certificate followed by the issuing CA certificate — this is what clients need to validate certificates from the external CA.

---

### 29.7 Distributing Cross-Certificates

Clients need the cross-certificate in their trust path. Distribution options:

**Option 1: Include in server's chain file**
```bash
# Server presents: leaf + intermediate + cross-cert + local root
cat server.pem intermediate.pem cross-cert.pem root.pem > full-chain.pem
```

**Option 2: Import into client trust store**
```bash
# Import cross-cert into Java truststore
keytool -importcert -alias partner-bridge \
  -file cross-cert.pem \
  -keystore truststore.jks \
  -storepass changeit -noprompt
```

**Option 3: AIA (Authority Information Access)**
If the external CA's certificates include an AIA extension pointing to the cross-certificate URL, clients can fetch it automatically during path building.

---

### 29.8 Direction

| Direction | Meaning | Who Benefits |
|-----------|---------|-------------|
| **Outbound** | We trust them | Our clients can validate their certs |
| **Inbound** | They trust us | Their clients can validate our certs |

For full bidirectional trust, create two cross-certificates (one in each direction). Each organisation issues a cross-cert for the other's CA.

---

### 29.9 API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/cross-certs/{ca_id}/cross-sign` | Issue cross-certificate (admin only) |
| GET | `/api/v1/cross-certs` | List all cross-certifications |
| GET | `/api/v1/cross-certs/{id}` | Get cross-cert details (includes PEM) |
| POST | `/api/v1/cross-certs/{id}/revoke` | Revoke trust bridge (admin only) |
| GET | `/api/v1/cross-certs/{id}/export` | Export cross-cert + chain |

---

### 29.10 Audit Events

| Event | Severity | Description |
|-------|----------|-------------|
| `CROSS_CERT_ISSUED` | INFO | Cross-certificate created |
| `CROSS_CERT_REVOKED` | WARNING | Trust bridge terminated |

---

### 29.11 RBAC

| Action | Admin | Operator | Auditor | ReadOnly |
|--------|:-----:|:--------:|:-------:|:--------:|
| Issue cross-certificate | ✓ | ✗ | ✗ | ✗ |
| Revoke cross-certificate | ✓ | ✗ | ✗ | ✗ |
| View cross-certificates | ✓ | ✓ | ✓ | ✓ |
| Export cross-certificate | ✓ | ✓ | ✓ | ✓ |

---

### 29.12 Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `External certificate is not a CA` | Uploaded cert has `CA:FALSE` | Only CA certificates can be cross-signed |
| `CA has no private key` | Selected an offline root | Use a CA that has a key, or start a signing session |
| Cross-cert not trusted by clients | Cross-cert not in client's trust path | Include in chain file or import into truststore |
| Name constraint violation | External CA issued cert outside permitted domains | This is working correctly — the constraint is enforced by clients |
| `Invalid PEM certificate` | Pasted text is not a valid PEM certificate | Ensure the full PEM including headers is pasted |

---


---

## 30. Kubernetes cert-manager Integration

> Automated TLS for Kubernetes workloads via cert-manager webhook issuer.

### 30.1 Overview

This CA acts as a cert-manager external issuer. When a `Certificate` resource is created in Kubernetes, cert-manager generates a CSR and sends it to this CA's webhook endpoint for signing. The signed certificate is stored in a Kubernetes Secret and automatically renewed before expiry.

**Two integration options:**

| Option | How | Pros | Cons |
|--------|-----|------|------|
| **Webhook Issuer** | Adapter calls `POST /api/v1/k8s/sign` | Full policy control, namespace/DNS restrictions | Requires webhook deployment |
| **ACME Issuer** | cert-manager's built-in ACME client | No webhook needed, standard protocol | Requires ACME endpoint (Medium Stage 1) |

### 30.2 Architecture

```
┌─────────────────────────────────────────────────────┐
│  Kubernetes Cluster                                  │
│                                                      │
│  ┌──────────────┐    CSR    ┌───────────────────┐   │
│  │ cert-manager │ ────────> │ Webhook Adapter   │   │
│  │  controller  │ <──────── │ (sidecar/deploy)  │   │
│  └──────────────┘   cert    └───────────────────┘   │
│         │                           │                │
│         ▼                           │ HTTPS          │
│  ┌──────────────┐                   │                │
│  │ K8s Secret   │                   ▼                │
│  │ (tls.crt +   │           ┌───────────────────┐   │
│  │  tls.key)    │           │ SSL Cert Manager  │   │
│  └──────────────┘           │ POST /api/v1/k8s/ │   │
│                             │      sign         │   │
└─────────────────────────────┴───────────────────┘   │
```

### 30.3 Configuration

#### Via UI

Navigate to **Kubernetes** in the sidebar. Configure:

- **Signing CA** — which CA signs K8s certificates
- **Profile** — server, client, or code_sign
- **Validity** — default certificate lifetime (days)
- **Allowed Namespaces** — restrict which namespaces can request certs
- **Allowed DNS Patterns** — restrict DNS names (supports wildcards like `*.svc.cluster.local`)

#### Via API

```bash
# Get current config
curl -H "X-API-Key: $KEY" http://pki.internal/api/v1/k8s/config

# Update config
curl -X PUT -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  http://pki.internal/api/v1/k8s/config \
  -d '{
    "ca_id": "c9d6be88-7b70-4ae7-8c24-5cf456935b61",
    "profile": "server",
    "validity_days": 90,
    "allowed_namespaces": ["production", "staging"],
    "allowed_dns_patterns": ["*.svc.cluster.local", "*.internal.corp"],
    "enabled": true
  }'
```

### 30.4 Deployment Steps

#### Step 1: Create API Key Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: certmanager-credentials
  namespace: cert-manager
type: Opaque
stringData:
  api-key: <your-api-key>
```

#### Step 2: Deploy Webhook Adapter

The webhook adapter is a lightweight service that translates cert-manager's signing requests into API calls to this CA. Deploy it in the `cert-manager` namespace.

See the **Manifests** tab in the Kubernetes page for the full deployment YAML.

#### Step 3: Create ClusterIssuer

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: internal-ca
spec:
  webhook:
    url: https://pki.internal/api/v1/k8s/sign
    caBundle: <base64-encoded-ca-cert>
    headers:
      X-API-Key: <from-secret>
```

#### Step 4: Request Certificates

```yaml
apiVersion: cert-manager.io/v1
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
  renewBefore: 360h  # renew 15 days before expiry
```

### 30.5 Sign Endpoint

```
POST /api/v1/k8s/sign
```

**Request body:**

| Field | Type | Description |
|-------|------|-------------|
| `csr` | string | Base64-encoded PEM or DER CSR |
| `namespace` | string | Requesting namespace (for policy) |
| `resource_name` | string | Certificate resource name (for audit) |
| `duration` | string | Requested validity (Go duration, e.g. "2160h") |
| `is_ca` | bool | Whether to issue a CA certificate |

**Response:**

```json
{
  "certificate": "<base64-PEM-cert>",
  "ca": "<base64-PEM-CA-chain>"
}
```

### 30.6 Policy Enforcement

| Policy | Effect |
|--------|--------|
| Namespace allowlist | Rejects CSRs from unlisted namespaces |
| DNS pattern allowlist | Rejects CSRs with DNS names not matching patterns |
| Validity cap | Server-side max (settings.MAX_CERT_DAYS) overrides requested duration |
| Profile | Controls KeyUsage and EKU extensions |
| Enabled flag | Disables all signing when false |

### 30.7 Health Endpoint

```
GET /api/v1/k8s/health
```

No authentication required. Returns:

```json
{"status": "ok", "enabled": true}
```

Use as Kubernetes liveness/readiness probe for the webhook adapter.

### 30.8 Monitoring

All certificates issued via cert-manager are tagged `k8s-cert-manager` and the requesting namespace. They appear in:

- Certificate list (filterable by tag)
- Expiry monitoring
- Audit log (event type: `K8S_CERT_ISSUED`)
- CT log (if enabled)

### 30.9 RBAC

| Action | Required Permission |
|--------|-------------------|
| Sign CSR | Authenticated (any role with API key) |
| View config | `ca:read` |
| Update config | `ca:create` (admin) |
| View manifests | `ca:read` |

### 30.10 Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| 503 "No CA available" | No CA with key material | Create a CA or set `ca_id` in config |
| 403 "Namespace not allowed" | Namespace not in allowlist | Add namespace to config or clear allowlist |
| 403 "DNS name not allowed" | DNS doesn't match patterns | Add pattern to config or clear patterns |
| 400 "CSR signature invalid" | Corrupted CSR | Check cert-manager logs for CSR generation errors |
| 503 "Issuer disabled" | Enabled flag is false | Set enabled=true in config |
| cert-manager timeout | Network connectivity | Ensure cluster can reach CA API endpoint |


---

## 31. Advanced Reporting & Compliance

> Automated compliance checking against CA/Browser Forum Baseline Requirements and CIS PKI benchmarks.

### 31.1 Overview

The compliance scanner automatically checks all certificates and CA infrastructure against industry standards:

- **CA/Browser Forum Baseline Requirements (BR)** — rules for publicly-trusted certificates (applied to internal certs as best practice)
- **CIS PKI Benchmark** — infrastructure security controls for CA operations

Scans run daily (background task) and can be triggered on-demand. Results are stored historically for trend tracking and auditor export.

### 31.2 Running a Scan

#### Via UI

Navigate to **Compliance** in the sidebar. Select scan type and click "Run Scan".

#### Via API

```bash
# Full scan (BR + CIS)
curl -X POST -H "X-API-Key: $KEY" \
  "http://pki.internal/api/v1/compliance/scan?scan_type=full"

# BR only
curl -X POST -H "X-API-Key: $KEY" \
  "http://pki.internal/api/v1/compliance/scan?scan_type=br"

# CIS only
curl -X POST -H "X-API-Key: $KEY" \
  "http://pki.internal/api/v1/compliance/scan?scan_type=cis"
```

### 31.3 BR Rules Checked

| Rule | Name | Check |
|------|------|-------|
| BR-6.3.2 | Maximum Validity | Server certs ≤398 days |
| BR-6.1.5 | Minimum Key Size | RSA ≥2048, ECDSA ≥256 |
| BR-7.1.4.2.1 | SAN Required | Server certs must have SAN |
| BR-7.1 | Serial Entropy | ≥64 bits (16 hex chars) |
| BR-6.1.5-SHA1 | SHA-1 Prohibited | No SHA-1 signatures |
| BR-3.2.2.6 | Wildcard Restrictions | No bare wildcards (*.tld) |

### 31.4 CIS Rules Checked

| Rule | Name | Check |
|------|------|-------|
| CIS-CA-KEY | CA Key Strength | RSA ≥4096, ECDSA ≥384 |
| CIS-KEY-STORE | Key Storage | Keys encrypted at rest |
| CIS-CRL | CRL/OCSP Available | PKI_BASE_URL configured |
| CIS-AUDIT | Audit Logging | Audit events being recorded |

### 31.5 Scan Results

Each finding has:

| Field | Description |
|-------|-------------|
| severity | `violation` (must fix), `warning` (should fix), `info` |
| rule | Rule identifier (e.g. BR-6.3.2) |
| category | `br` or `cis` |
| subject | Certificate serial or CA ID |
| subject_cn | Common Name for identification |
| message | Readable description |

### 31.6 Historical Tracking

Scan results are stored in the database. The History tab shows:

- Trend chart (violations/warnings over time)
- Table of all past scans with counts
- Useful for demonstrating compliance improvement to auditors

### 31.7 Exporting Reports

```bash
# Export as CSV (for auditors)
curl -H "X-API-Key: $KEY" \
  "http://pki.internal/api/v1/compliance/export?format=csv" -o report.csv

# Export as JSON (for automation)
curl -H "X-API-Key: $KEY" \
  "http://pki.internal/api/v1/compliance/export?format=json" -o report.json

# Export specific scan
curl -H "X-API-Key: $KEY" \
  "http://pki.internal/api/v1/compliance/export?scan_id=<id>&format=csv"
```

### 31.8 Scheduled Scans

A full compliance scan runs automatically every 24 hours (background task). Results are stored for historical tracking. No configuration needed — it starts automatically.

### 31.9 API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/compliance/scan` | POST | Run a scan (query: scan_type) |
| `/api/v1/compliance/latest` | GET | Get most recent scan results |
| `/api/v1/compliance/history` | GET | Historical scan results |
| `/api/v1/compliance/export` | GET | Export report (CSV/JSON) |
| `/api/v1/compliance/rules` | GET | List all rules checked |

### 31.10 RBAC

All compliance endpoints require `audit:read` permission (Admin, Operator, Auditor roles).

### 31.11 Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| No scan results | Never scanned | Click "Run Scan" or wait for daily auto-scan |
| 0 items checked | No valid certificates | Issue some certificates first |
| False positive on validity | Internal cert with long validity | Expected for internal CAs — BR rules are advisory |
| CIS-CRL warning | PKI_BASE_URL not set | Configure PKI_BASE_URL in settings |


## 32. Key Escrow & Recovery

Key escrow provides recoverable encryption keys for email S/MIME and data-at-rest certificates. When an employee leaves or loses access, encrypted emails and files become unrecoverable without key escrow.

---

### 32.1 Overview

**Key principle:** Signing keys (server TLS, code signing) are NEVER escrowed — non-repudiation requires sole possession. Only encryption keys (email, data encryption) are escrowed.

```
Certificate Issuance
        │
        ▼
┌─ Profile = email or template.escrow_key = true?
│      YES                    NO
│       │                      └─ Normal flow (no escrow)
│       ▼
│  Encrypt key with RECOVERY KEY (separate from CERT_MASTER_KEY)
│  Store in key_escrow table
│       │
│       ▼
│  Certificate issued normally
│  Key available for recovery if needed
```

---

### 32.2 Escrow Policy

| Profile | Auto-Escrow | Reason |
|---------|:-----------:|--------|
| `email` | ✓ | Encryption keys must be recoverable |
| `client` | Template-dependent | Only if template has `escrow_key: true` |
| `server` | ✗ Never | Signing key — non-repudiation |
| `code_sign` | ✗ Never | Signing key — non-repudiation |

Templates can override the default by setting `escrow_key: true`:

```bash
# Create a template with escrow enabled
curl -s -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/templates \
  -d '{
    "name": "data-encryption",
    "display_name": "Data Encryption",
    "escrow_key": true,
    "max_validity_days": 730
  }'
```

---

### 32.3 Recovery Key Configuration

The recovery key is a separate Fernet key used exclusively for encrypting escrowed keys. This separation means:
- Compromising `CERT_MASTER_KEY` does NOT expose escrowed keys
- Compromising the recovery key does NOT expose operational certificate keys

```bash
# Generate a recovery key
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Set in environment
KEY_ESCROW_RECOVERY_KEY=<generated-fernet-key>
```

If `KEY_ESCROW_RECOVERY_KEY` is not set, a key is derived from `CERT_MASTER_KEY` (functional but less secure — single point of compromise).

**Production recommendation:** Store the recovery key in an HSM, KMS, or split it using Shamir's Secret Sharing.

---

### 32.4 Recovery Workflow (M-of-N Approval)

Key recovery requires multiple admin approvals to prevent single-person key extraction:

```
Admin A                    System                    Admin B
  │                          │                          │
  │── Request Recovery ────▶│                          │
  │   (serial + justification)                         │
  │                          │                          │
  │◀── Status: pending ─────│                          │
  │    (needs 2 approvals)   │                          │
  │                          │                          │
  │                          │◀── Approve ─────────────│
  │                          │    (Admin B approves)    │
  │                          │                          │
  │── Approve ─────────────▶│                          │
  │   ✗ REJECTED             │                          │
  │   (cannot self-approve)  │                          │
  │                          │                          │
  │                          │◀── Approve ─────────────│
  │                          │    (Admin C approves)    │
  │                          │                          │
  │◀── Status: approved ────│                          │
  │    download_token: xxx   │                          │
  │    expires: 1 hour       │                          │
  │                          │                          │
  │── Download Key ─────────▶│                          │
  │   (token required)       │                          │
  │◀── PEM key ─────────────│                          │
  │                          │                          │
  │   Status: completed      │                          │
```

**Configuration:**

```bash
# Number of admin approvals required (default: 2)
KEY_RECOVERY_APPROVALS_REQUIRED=2
```

**Constraints:**
- The requester cannot approve their own request
- Download link expires after 1 hour
- Each request can only be downloaded once (status changes to `completed`)
- All operations are fully audited

---

### 32.5 API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/key-escrow/escrowed` | List all escrowed keys |
| GET | `/api/v1/key-escrow/requests` | List recovery requests |
| POST | `/api/v1/key-escrow/requests` | Create recovery request |
| POST | `/api/v1/key-escrow/requests/{id}/action` | Approve or deny |
| GET | `/api/v1/key-escrow/requests/{id}/download?token=xxx` | Download recovered key |
| GET | `/api/v1/key-escrow/policy` | View escrow policy |

All endpoints require `settings:manage` permission (admin only).

#### Create Recovery Request

```bash
curl -s -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/key-escrow/requests \
  -d '{
    "certificate_serial": "5c54d7ef2309f7adea4c5ebe38e66f4f",
    "justification": "Employee departed, need to recover encrypted emails for legal compliance"
  }'
```

#### Approve/Deny

```bash
# Approve (must be a different admin than the requester)
curl -s -X POST -H "Authorization: Bearer $OTHER_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/key-escrow/requests/<request_id>/action \
  -d '{"action": "approve"}'

# Deny
curl -s -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/key-escrow/requests/<request_id>/action \
  -d '{"action": "deny"}'
```

#### Download Recovered Key

```bash
curl -s -H "X-API-Key: $API_KEY" \
  "http://127.0.0.1:8000/api/v1/key-escrow/requests/<request_id>/download?token=<download_token>"
```

---

### 32.6 Audit Events

| Event | Severity | When |
|-------|----------|------|
| `KEY_RECOVERY_REQUESTED` | WARNING | Recovery request created |
| `KEY_RECOVERY_APPROVED` | WARNING | Admin approved a request |
| `KEY_RECOVERY_DENIED` | WARNING | Admin denied a request |
| `KEY_RECOVERY_COMPLETED` | CRITICAL | Key was downloaded |

---

### 32.7 Frontend

Navigate to **Key Escrow** (🔑) in the sidebar (admin only). Three tabs:

- **Escrowed Keys** — table of all escrowed keys with CN, serial, profile, date
- **Recovery Requests** — pending/approved/denied requests with approve/deny/download buttons
- **Policy** — current escrow configuration and security notes

---

### 32.8 Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `No escrowed key found for serial` | Certificate wasn't escrowed (wrong profile or template) | Only email profile or templates with `escrow_key: true` are escrowed |
| `Cannot approve your own recovery request` | Same user requested and tried to approve | A different admin must approve |
| `Download link has expired` | More than 1 hour since approval | Create a new recovery request |
| `Already approved by this user` | Same admin tried to approve twice | Need a different admin for the second approval |
| Key decryption fails | Recovery key changed since escrow | Recovery key must remain consistent; rotate carefully |

---


---

## 33. API Versioning & SDK

### 33.1 API Versions

The application serves two API versions simultaneously:

| Version | Prefix | Status | Description |
|---------|--------|--------|-------------|
| v1 | `/api/v1/` | Stable | Original API — all existing integrations work unchanged |
| v2 | `/api/v2/` | Current | Enhanced envelope format, SDK generation, version info |

Both versions are fully functional. v1 will never be removed without a deprecation period (minimum 12 months with `Sunset` header).

### 33.2 Version Headers

Every API response includes version headers:

```
X-API-Version: 1.0
X-API-Status: stable
```

When an endpoint is deprecated:
```
Deprecation: true
Sunset: Sat, 01 Jan 2028 00:00:00 GMT
Link: </api/v2>; rel="successor-version"
```

### 33.3 v2 Envelope Format

v2 endpoints return a consistent envelope:

```json
{
  "data": { ... },
  "meta": { "api_version": "2.0" },
  "errors": []
}
```

### 33.4 v2 Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/v2/version` | API version info and deprecation schedule |
| `GET /api/v2/changelog` | Version changelog |
| `GET /api/v2/health` | Enhanced health with component status |
| `GET /api/v2/me` | Current user (envelope format) |
| `GET /api/v2/sdk/python` | Download Python SDK source |
| `GET /api/v2/sdk/cli` | Download CLI tool source |
| `GET /api/v2/sdk/bash` | Curl/bash examples |
| `GET /api/v2/sdk/openapi-url` | OpenAPI spec URL and generator commands |

### 33.5 Python SDK

Download from the API or the UI (API & SDK page):

```python
from certmanager_sdk import CertManagerClient

with CertManagerClient(api_key="your-key") as client:
    # Health check
    print(client.health())

    # List CAs
    cas = client.list_cas()

    # Issue certificate
    cert = client.issue_cert(
        signing_ca_id=cas[0]["id"],
        cn="app.internal",
        san=[{"type": "dns", "value": "app.internal"}],
    )

    # Export
    p12 = client.export_cert(cert["serial"], fmt="p12")
    open("app.p12", "wb").write(p12)
```

**Requirements:** `pip install httpx`

### 33.6 CLI Tool

```bash
# Install dependencies
pip install typer[all] rich httpx

# Configure
python certmanager_cli.py configure --url https://pki.internal --api-key YOUR_KEY

# Commands
python certmanager_cli.py health
python certmanager_cli.py cas
python certmanager_cli.py issue app.internal --ca CA_ID --profile server
python certmanager_cli.py list --profile server --status valid
python certmanager_cli.py export SERIAL --fmt p12 -o app.p12
python certmanager_cli.py revoke SERIAL --reason superseded
python certmanager_cli.py renew SERIAL
```

### 33.7 OpenAPI Auto-Generation

The full OpenAPI 3.1 spec is available at `/api/openapi.json`. Use with any code generator:

```bash
# Python
openapi-python-client generate --url https://pki.internal/api/openapi.json

# TypeScript
npx openapi-typescript https://pki.internal/api/openapi.json -o types.ts

# Go
oapi-codegen -package certmanager https://pki.internal/api/openapi.json > client.go

# Java
openapi-generator-cli generate -i https://pki.internal/api/openapi.json -g java -o sdk-java/
```

### 33.8 Versioning Policy

1. **No breaking changes in v1** — new fields may be added but never removed
2. **Deprecation notice** — minimum 12 months before removal, with `Sunset` header
3. **v2 is additive** — v1 endpoints continue to work alongside v2
4. **SDK regeneration** — SDK source is always generated from the live OpenAPI spec


---

## 34. SCEP Protocol (Legacy Device Enrollment)

### 34.1 Overview

SCEP (Simple Certificate Enrollment Protocol) provides certificate enrollment for legacy network devices that don't support modern protocols like EST or ACME. Common SCEP clients include Cisco IOS routers, ASA firewalls, VPN concentrators, MikroTik routers, and embedded systems.

### 34.2 Configuration

Enable SCEP via environment variables:

```env
SCEP_ENABLED=true
SCEP_CA_ID=                        # CA ID for signing (empty = auto-select)
SCEP_CHALLENGE_PASSWORD=SecretPass  # Shared enrollment secret
SCEP_PROFILE=server                 # Certificate profile
SCEP_MAX_VALIDITY_DAYS=365          # Maximum cert validity
```

### 34.3 Endpoints

| Operation | Method | URL | Auth |
|-----------|--------|-----|------|
| GetCACaps | GET | `/scep?operation=GetCACaps` | None |
| GetCACert | GET | `/scep?operation=GetCACert` | None |
| PKIOperation | GET/POST | `/scep?operation=PKIOperation` | Challenge password |

Legacy path (for older devices): `/cgi-bin/pkiclient.exe`

### 34.4 Capabilities

The server advertises these capabilities via GetCACaps:

- `POSTPKIOperation` — Accept POST for enrollment
- `SHA-256` / `SHA-512` — Supported hash algorithms
- `AES` / `DES3` — Supported encryption algorithms
- `Renewal` — Certificate renewal supported

### 34.5 Enrollment Flow

```
Device                          SCEP Server
  |                                  |
  |-- GetCACaps ------------------>  |  (discover capabilities)
  |<-- capabilities list ----------  |
  |                                  |
  |-- GetCACert ------------------>  |  (download CA certificate)
  |<-- CA cert (DER) -------------  |
  |                                  |
  |-- PKIOperation (CSR) -------->  |  (submit enrollment request)
  |   (includes challenge password)  |
  |<-- Signed certificate ---------  |  (PKCS#7 response)
  |                                  |
```

### 34.6 Device Configuration Examples

**Cisco IOS / IOS-XE:**
```
crypto pki trustpoint INTERNAL-CA
  enrollment url http://pki.internal/cgi-bin/pkiclient.exe
  subject-name CN=router01.internal,O=Corp
  revocation-check crl
  rsakeypair INTERNAL-CA 2048
  password <challenge-password>
!
crypto pki authenticate INTERNAL-CA
crypto pki enroll INTERNAL-CA
```

**Linux (sscep):**
```bash
# Get CA certificate
sscep getca -u http://pki.internal/cgi-bin/pkiclient.exe -c ca.pem

# Generate key and CSR
openssl req -new -newkey rsa:2048 -nodes -keyout device.key \
  -out device.csr -subj "/CN=device01.internal"

# Enroll
sscep enroll -u http://pki.internal/cgi-bin/pkiclient.exe \
  -c ca.pem -k device.key -r device.csr \
  -l device.pem -p <challenge-password>
```

### 34.7 Security Considerations

- **Challenge password** — Always configure a strong challenge password in production
- **Network access** — Restrict SCEP endpoint access to trusted networks (firewall rules)
- **Rate limiting** — SCEP requests are rate-limited by the general API rate limiter
- **Audit trail** — All enrollment attempts (success and failure) are logged
- **Deprecation path** — Migrate devices to EST when firmware supports it
- **Template restriction** — SCEP uses the configured profile; cannot issue CA certs

### 34.8 Monitoring

SCEP events in the audit log:
- `SCEP_ENROLL` — Successful enrollment
- `SCEP_CHALLENGE_FAILED` — Challenge password validation failed

Filter certificates by tag: `scep-enrolled`

---

## 35. About Page

Reached via the "ℹ️ About" link in the sidebar footer, just above the current-user/logout area — visible in every mode (Certificates, Build Manager, JAR Analyser, Docs), since it's global to the whole install rather than scoped to any one app.

Its purpose is a single place crediting every open-source product LabTool is built on: the backend/frontend language runtimes, every pip and npm dependency actually shipped (not dev-only tooling), the bundled Java decompilers (CFR, Vineflower) and the JRE that runs them, Ansible/OpenTofu (Build Manager's automation engines), and the base Docker images — each with the **exact version currently deployed**, not just the `>=`/`^` constraint from `requirements.txt`/`package.json`. It's plain markdown, rendered the same way Docs content is.

- **Anyone signed in can read it** (admin, operator, auditor, readonly).
- **Only admins can edit it** — a "✏️ Edit" button appears next to the heading for admins only, opening a plain markdown textarea with Save/Cancel.
- A "Last updated by ... on ..." line appears below the content once it's been edited at least once, so it's obvious whether the page reflects a recent dependency change or has gone stale.
- **🕐 History** — every overwrite (a manual Edit, a Regenerate, or a Restore) archives the *previous* content first, so nothing is ever destroyed. History lists every archived snapshot (source badge, who/when, content length), newest first. Click a row to expand it inline and see exactly what that action changed (a line-by-line +/- diff, added/removed counts) — it's automatically compared against whatever content replaced it (the next snapshot, or the current live page if it's the newest one on file), so there's nothing to pick manually. Admins get a "⏪ Restore" button per snapshot — restoring archives the *current* content first too, so a restore is itself undoable, not a one-way trip. A brand-new install with no edits yet shows an empty list rather than a placeholder entry.
- **📋 Changelog** — a structured "Package: 1.2.3 → 1.3.0" version-change log, same from/to shape as JAR Analyser's own dependency diffs (`JarDiffReport`), but computed automatically every time Regenerate runs rather than needing two reports picked by hand. Only Regenerate populates this (a manual Edit has no structured per-package data to diff) — each run compares freshly-detected versions against the last Regenerate's, records a row for anything that moved, and shows a green "+" badge the first time a package is ever detected versus an amber "~" badge for an actual version change. Running Regenerate twice in a row with nothing installed-side changed adds zero new rows — it's a real diff, not a log of every run.
- **⬇ Markdown / ⬇ PDF export** — two buttons next to Edit, available to every role that can read the page. Markdown returns the raw content verbatim (`about.md`); PDF renders it through the same markdown → HTML → WeasyPrint pipeline Docs' own PDF export uses (`about.pdf`, with a "Last updated by ..." line under the title). Meant for feeding into a license-scanning tool or attaching to a compliance/production-readiness review without needing to log in and copy-paste.
- **🔄 Regenerate** — a third admin-only button, next to Edit. Rebuilds the whole page from versions detected live against the running container, rather than an admin transcribing `pip freeze` output by hand: backend package versions come from `importlib.metadata` (the exact venv this process is running in, checked fresh on every click — it isn't cached from build time), frontend package versions come from parsing `frontend/package-lock.json` (copied into the image at build time specifically for this), and the bundled tools' versions come from running `java -version` / `nginx -v` / `tofu version` / `ansible-galaxy collection list` (`ansible-core`'s own version also comes from `importlib.metadata`, since it's a pip package) plus a small `bundled_tool_versions.json` baked in at Docker build time from the CFR/Vineflower download ARGs — those two are the one thing that can't be detected live, since they're plain jars with no version flag. A confirmation dialog warns it overwrites the current content (including any hand-added notes) before proceeding. See `backend/app/services/about_generator.py` for the full detection logic.
  - **What Regenerate can't do**: it only re-detects *versions* for dependencies the generator already knows to look for — the surrounding prose (each dependency's one-line description, section headings) is fixed in code. Adding a genuinely new dependency (not just upgrading an existing one) still needs a code change to `about_generator.py` (or a manual Edit) before Regenerate will pick it up.
- **Keeping it current**: whenever a dependency is added or removed (not just upgraded — Regenerate handles upgrades automatically), an admin should update `about_generator.py` (to teach Regenerate about the new dependency) or edit the page by hand for a one-off change. There's still no automated *trigger* — nothing runs Regenerate on a schedule or on deploy, so a stale page is still possible if nobody clicks the button after a dependency bump. The page's own closing note says as much.

API: `GET /api/v1/about` / `GET /api/v1/about/export/markdown` / `GET /api/v1/about/export/pdf` / `GET /api/v1/about/history` / `GET /api/v1/about/history/{id}` / `GET /api/v1/about/history/{id}/diff` / `GET /api/v1/about/changelog` (any authenticated role) / `PUT /api/v1/about` / `POST /api/v1/about/regenerate` / `POST /api/v1/about/history/{id}/restore` (admin only; PUT takes body `{"content": "..."}`, regenerate and restore take no body).
