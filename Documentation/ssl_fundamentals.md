
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
The client has a pre-installed list of Certificate Authority (CA) certificates it trusts. If the server's certificate was signed by one of these CAs (or by an intermediate CA that chains back to one), the client trusts it. That's it — trust is just "signed by someone in my list."

---

### 0.2 Certificate Anatomy

A certificate is a structured data file containing:

```
┌─────────────────────────────────────────────────────────┐
│ X.509 v3 Certificate                                     │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Version: 3                                              │
│  Serial Number: 0a:1b:2c:3d:... (unique per CA)         │
│                                                          │
│  Subject: CN=api.example.com, O=MyOrg, C=GB             │
│    └─ "Who this certificate is for"                      │
│                                                          │
│  Issuer: CN=Internal Root CA, O=MyOrg                    │
│    └─ "Who signed this certificate"                      │
│                                                          │
│  Validity:                                               │
│    Not Before: 2025-01-01 00:00:00 UTC                   │
│    Not After:  2025-12-31 23:59:59 UTC                   │
│                                                          │
│  Public Key: RSA 2048-bit                                │
│    └─ The server's public key (anyone can see this)      │
│                                                          │
│  Extensions:                                             │
│    Subject Alternative Name (SAN):                       │
│      DNS: api.example.com                                │
│      DNS: *.example.com                                  │
│      IP: 10.0.1.50                                       │
│      └─ "What hostnames/IPs this cert is valid for"      │
│                                                          │
│    Key Usage: digitalSignature, keyEncipherment          │
│      └─ "What operations this key can perform"           │
│                                                          │
│    Extended Key Usage: serverAuth                        │
│      └─ "What role this cert serves (TLS server)"        │
│                                                          │
│    Basic Constraints: CA:FALSE                           │
│      └─ "This is a leaf cert, cannot sign other certs"   │
│                                                          │
│    Authority Key Identifier: (fingerprint of issuer)     │
│      └─ "Which CA key signed this"                       │
│                                                          │
├─────────────────────────────────────────────────────────┤
│  Signature: (CA's digital signature over all the above)  │
│    └─ "Proof that the issuer approved this certificate"  │
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
│ CN=DigiCert Root      │  Validity: 20-30 years.
│ CA:TRUE, pathLen=2    │  Key: RSA 4096 (kept offline in HSM)
└──────────┬───────────┘
           │ signs
┌──────────▼───────────┐
│ Intermediate CA       │  Signed by root. Does the daily signing work.
│ CN=DigiCert SHA2      │  Validity: 5-10 years.
│ CA:TRUE, pathLen=0    │  Key: RSA 4096
└──────────┬───────────┘
           │ signs
┌──────────▼───────────┐
│ Leaf Certificate      │  Signed by intermediate. This is YOUR cert.
│ CN=api.example.com    │  Validity: 398 days max.
│ CA:FALSE              │  Key: RSA 2048 or ECDSA P-256
└──────────────────────┘
```

**Why intermediates exist:**
- The root CA's private key is extremely valuable — if compromised, ALL certificates under it are compromised
- By using intermediates, the root key can be kept offline (air-gapped, in an HSM)
- If an intermediate is compromised, only IT can be revoked without replacing the root
- Different intermediates can serve different purposes (one for servers, one for email, etc.)

**What "chain of trust" means in practice:**
When your server presents its certificate, it MUST also send the intermediate(s). The client then:
1. Checks leaf was signed by intermediate (signature verification)
2. Checks intermediate was signed by root (signature verification)
3. Checks root is in its trust store

If any link is missing or broken, you get `PKIX path building failed` (Java) or `unable to verify the first certificate` (OpenSSL).

**Cross-signing:**
Some CAs have their intermediate signed by MULTIPLE roots. This lets old clients (with old root stores) still trust new intermediates. Let's Encrypt used this with DST Root CA X3 → ISRG Root X1.

---

### 0.4 Common Failure Modes

A visual guide to what went wrong based on the error:

```
TLS Connection Attempt
        │
        ▼
┌─ Can connect to host? ──── NO ──▶ "Connection refused" / "Connection timed out"
│       │                            Cause: wrong port, firewall, service down
│      YES
│       │
│       ▼
├─ Server sends cert? ─────── NO ──▶ "SSL: Unsupported or unrecognized SSL message"
│       │                            Cause: connecting to non-TLS port (HTTP not HTTPS)
│      YES
│       │
│       ▼
├─ Cert signed by trusted CA? ─ NO ▶ "PKIX path building failed" / "certificate unknown"
│       │                            Cause: CA not in client's trust store
│      YES                           Fix: import root CA into truststore
│       │
│       ▼
├─ Chain complete? ──────── NO ──▶ "unable to verify the first certificate"
│       │                            Cause: intermediate CA missing from chain
│      YES                           Fix: use chain.pem (not just cert.pem)
│       │
│       ▼
├─ Cert not expired? ───── NO ──▶ "certificate has expired" / "timestamp check failed"
│       │                            Cause: leaf or intermediate expired
│      YES                           Fix: renew; check ALL certs in chain
│       │
│       ▼
├─ Hostname matches SAN? ── NO ──▶ "hostname verification failed" / "No SANs matching"
│       │                            Cause: cert doesn't cover this hostname
│      YES                           Fix: re-issue with correct DNS/IP SANs
│       │
│       ▼
├─ TLS version compatible? ─ NO ──▶ "handshake_failure" / "protocol version"
│       │                            Cause: client offers TLS 1.0, server requires 1.2+
│      YES                           Fix: upgrade client or adjust server config
│       │
│       ▼
├─ Cipher suite match? ──── NO ──▶ "handshake_failure" / "no shared cipher"
│       │                            Cause: no overlap in supported ciphers
│      YES                           Fix: check cipher configuration on both ends
│       │
│       ▼
├─ Client cert required? ── YES and missing ──▶ "certificate_required"
│       │                            Cause: mTLS enabled, client didn't send cert
│      OK                            Fix: configure client keystore
│       │
│       ▼
  ✅ Connection Established
```

---

### 0.5 Certificate Lifecycle

Every certificate goes through these stages:

```
Generation ──▶ Active Use ──▶ Renewal Window ──▶ Expiry ──▶ Dead
                                     │
                              (30 days before)
                                     │
                              Renew here ──▶ New cert takes over
```

**Timeline for a 398-day certificate:**

| Day | Event | Action Required |
|-----|-------|-----------------|
| 0 | Certificate issued | Deploy to server |
| 1-338 | Active use | None — monitoring only |
| 338 | 60 days to expiry | INFO alert; plan renewal |
| 368 | 30 days to expiry | WARNING alert; renew now |
| 391 | 7 days to expiry | CRITICAL alert; emergency renewal |
| 398 | Certificate expires | **Service breaks** if not renewed |

**What happens when a cert expires:**
- Clients refuse to connect (hard failure, not graceful)
- No warning to end users — just "connection failed"
- The server keeps running but nobody can reach it over TLS
- In a microservices estate, one expired intermediate can take down dozens of services

**Revocation vs Expiry:**
- **Expiry** is automatic — the cert becomes invalid after its `Not After` date
- **Revocation** is manual — you actively mark a cert as untrusted before it expires (e.g. key compromised)
- Revocation is checked via CRL (Certificate Revocation List) or OCSP (Online Certificate Status Protocol)
- In practice, many clients don't check revocation (or cache it), so revocation is a "best effort" control

---

### 0.6 Mutual TLS (mTLS) Explained

Normal TLS: only the **server** proves its identity.
Mutual TLS: **both** server AND client prove their identity.

```
Normal TLS:                          Mutual TLS (mTLS):
                                     
Client ──▶ Server                    Client ◀──▶ Server
  │          │                         │            │
  │  "Show me your cert"               │  "Show me your cert"
  │◀──── Server cert ────│             │◀──── Server cert ────│
  │                                    │
  │  "OK I trust you"                  │  "Now show ME yours"
  │                                    │──── Client cert ────▶│
  │                                    │
                                       │  Both verified ✓
```

**When to use mTLS:**
- Service-to-service communication (microservices calling each other)
- Zero-trust networks (every connection authenticated, not just the server)
- API access where API keys aren't sufficient
- Replacing VPN for service connectivity

**What you need for mTLS:**
- Server: normal server certificate + a truststore containing the client's CA
- Client: a **client certificate** (with `clientAuth` EKU) + the server's CA in its truststore

**mTLS in this tool:**
1. Issue a **Server (TLS)** cert for the server
2. Issue a **Client (mTLS)** cert for each client
3. Configure server to require client certs (e.g. Nginx `ssl_verify_client on`)
4. Configure client with its cert + key (e.g. Java keystore)

---

### 0.7 Internal CA vs Public CA

| Aspect | Public CA (DigiCert, Let's Encrypt) | Internal CA (this tool) |
|--------|-------------------------------------|------------------------|
| **Trusted by** | Every browser and OS automatically | Only systems where you've imported the root CA |
| **Cost** | Free (LE) to expensive (EV certs) | Free |
| **Validation** | Domain ownership verified externally | You control everything |
| **Max validity** | 398 days (enforced) | Whatever you set (no browser enforcement) |
| **Issuance speed** | Minutes to days | Instant |
| **Use case** | Public-facing websites, APIs | Internal services, dev/staging, mTLS, testing |
| **Revocation** | CRL/OCSP infrastructure provided | You manage your own CRL |
| **Trust distribution** | Automatic (pre-installed) | Manual (scripts, GPO, deployment tooling) |

**Decision guide:**

- **Public-facing website/API → Public CA** (Let's Encrypt for free, commercial for EV/OV)
- **Internal service-to-service → Internal CA** (this tool)
- **Development/staging → Internal CA** (this tool)
- **AWS ALB (public) → ACM** (free, auto-renewing)
- **AWS ALB (internal) → Internal CA** (this tool) + import into ACM
- **mTLS between services → Internal CA** (this tool — you control both ends)

**The trust distribution problem:**
The main drawback of an internal CA is that you must get the root CA certificate into every client's trust store. This means:
- Every Linux server: `update-ca-certificates`
- Every Windows machine: GPO or manual import
- Every Java app: import into `cacerts` or custom truststore
- Every developer's browser: manual import
- Every Docker container: bake into the image or mount

This tool generates platform-specific scripts to automate this, but it's still an operational overhead that public CAs don't have.

---

### 0.8 SSL/TLS Glossary

| Term | Meaning |
|------|---------|
| **SSL** | Secure Sockets Layer — the predecessor to TLS. SSL 3.0 was the last version (1996). Deprecated and insecure. When people say "SSL cert" they almost always mean a TLS certificate. |
| **TLS** | Transport Layer Security — the current standard. TLS 1.2 (2008) and TLS 1.3 (2018) are the only versions considered secure. |
| **X.509** | The standard format for digital certificates. When you hear "X.509 certificate" it means a standard TLS/SSL certificate. |
| **PEM** | Privacy-Enhanced Mail — a Base64 text encoding for certificates and keys. Starts with `-----BEGIN CERTIFICATE-----`. The most common format on Linux. |
| **DER** | Distinguished Encoding Rules — binary encoding of the same data as PEM. Common on Windows. A PEM file is just a DER file run through Base64 with headers. |
| **PKCS#1** | RSA-specific key format. Header: `-----BEGIN RSA PRIVATE KEY-----`. Legacy format. |
| **PKCS#7** | Certificate chain format (also called P7B/CMS). Contains certs but no private keys. Used by Windows and some CAs for chain delivery. |
| **PKCS#8** | Generic private key format (any algorithm). Header: `-----BEGIN PRIVATE KEY-----`. Preferred modern format. |
| **PKCS#12 / PFX** | Binary format bundling cert + key + chain in one password-protected file. Extension: `.p12` or `.pfx`. Used by Windows, Java, and browsers. |
| **JKS** | Java KeyStore — Java's proprietary store format. Being replaced by PKCS#12. |
| **CSR** | Certificate Signing Request — a file you send to a CA asking them to sign a certificate. Contains your public key and subject info, signed by your private key to prove ownership. |
| **CA** | Certificate Authority — an entity that signs certificates. Can be public (DigiCert) or private (your own root CA). |
| **Root CA** | The top of the trust chain. Self-signed. Pre-installed in trust stores. |
| **Intermediate CA** | Sits between root and leaf. Signs leaf certs on behalf of the root. Allows root key to stay offline. |
| **Leaf certificate** | The end-entity cert — your server's certificate. Cannot sign other certs (CA:FALSE). |
| **CN** | Common Name — a field in the certificate subject. Historically used for the hostname but now IGNORED by modern clients in favour of SANs. |
| **SAN** | Subject Alternative Name — the extension listing all hostnames and IPs the cert is valid for. The ONLY field used for hostname verification today. |
| **EKU** | Extended Key Usage — specifies what the cert can be used for: `serverAuth` (TLS server), `clientAuth` (mTLS client), `codeSigning`, etc. |
| **CRL** | Certificate Revocation List — a file published by the CA listing all revoked certificate serial numbers. Clients can download and check it. |
| **OCSP** | Online Certificate Status Protocol — a real-time alternative to CRL. Client asks the CA "is this cert revoked?" and gets a signed yes/no response. |
| **HSTS** | HTTP Strict Transport Security — a header that tells browsers to always use HTTPS for this domain. Not a certificate feature, but related. |
| **Certificate Pinning** | Hardcoding which certificate or CA a client should expect. Prevents trust store compromise. Used in mobile apps and high-security environments. |
| **SNI** | Server Name Indication — a TLS extension that lets the client tell the server which hostname it's connecting to. Allows multiple certs on one IP. |
| **ALPN** | Application-Layer Protocol Negotiation — TLS extension for agreeing on HTTP/2 vs HTTP/1.1 during handshake. |
| **Key Usage** | Extension defining what cryptographic operations the key can perform: `digitalSignature`, `keyEncipherment`, `keyCertSign`, etc. |
| **Path Length** | A constraint on CA certificates limiting how many levels of sub-CAs can exist below it. `pathLen=0` means this CA can only sign leaf certs, not other CAs. |
| **Trust Store** | A file or database containing the CA certificates a system trusts. Different per platform: `/etc/ssl/certs/` (Linux), `Cert:\LocalMachine\Root` (Windows), `cacerts` (Java). |
| **Key Store** | A file containing a private key and certificate (the server's own identity). Different from a trust store (which contains CAs it trusts). |
| **Fernet** | A symmetric encryption scheme (AES-128-CBC + HMAC-SHA256) used in this tool to encrypt stored private keys. |
| **HKDF** | HMAC-based Key Derivation Function — used in this tool to derive the backup encryption key from the master key. |

---

