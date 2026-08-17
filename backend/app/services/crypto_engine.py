"""Crypto engine wrapping pyca/cryptography for all X.509 operations."""

import os
import json
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs12 as _pkcs12
from cryptography.hazmat.primitives.asymmetric import rsa, ec, ed25519, types
from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes
from cryptography.x509 import (
    CertificateBuilder,
    CertificateSigningRequestBuilder,
    Name,
    SubjectAlternativeName,
    BasicConstraints,
    KeyUsage,
    ExtendedKeyUsage,
    AuthorityKeyIdentifier,
    SubjectKeyIdentifier,
    CRLDistributionPoints,
)
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID


@dataclass
class SubjectInfo:
    cn: str
    o: str = ""
    ou: str = ""
    c: str = ""
    st: str = ""
    l: str = ""


@dataclass
class SANEntry:
    type: str  # dns, ip, email, uri
    value: str


DIGEST_MAP: dict[str, type[hashes.HashAlgorithm]] = {
    "sha256": hashes.SHA256,
    "sha384": hashes.SHA384,
    "sha512": hashes.SHA512,
}

PROFILE_KEY_USAGE: dict[str, dict[str, bool]] = {
    "root_ca": {
        "key_cert_sign": True,
        "crl_sign": True,
        "digital_signature": False,
        "key_encipherment": False,
        "content_commitment": False,
    },
    "intermediate": {
        "key_cert_sign": True,
        "crl_sign": True,
        "digital_signature": True,
        "key_encipherment": False,
        "content_commitment": False,
    },
    "server": {
        "key_cert_sign": False,
        "crl_sign": False,
        "digital_signature": True,
        "key_encipherment": True,
        "content_commitment": False,
    },
    "client": {
        "key_cert_sign": False,
        "crl_sign": False,
        "digital_signature": True,
        "key_encipherment": False,
        "content_commitment": False,
    },
    "code_sign": {
        "key_cert_sign": False,
        "crl_sign": False,
        "digital_signature": True,
        "key_encipherment": False,
        "content_commitment": True,
    },
    "email": {
        "key_cert_sign": False,
        "crl_sign": False,
        "digital_signature": True,
        "key_encipherment": True,
        "content_commitment": False,
    },
}

PROFILE_EKU: dict[str, list] = {
    "server": [ExtendedKeyUsageOID.SERVER_AUTH],
    "client": [ExtendedKeyUsageOID.CLIENT_AUTH],
    "code_sign": [ExtendedKeyUsageOID.CODE_SIGNING],
    "email": [ExtendedKeyUsageOID.EMAIL_PROTECTION],
}


class CryptoEngine:
    """Core cryptographic operations for certificate management."""

    def generate_keypair(self, algo: str, key_size: int) -> PrivateKeyTypes:
        algo_upper = algo.upper()
        if algo_upper == "RSA":
            if key_size not in (2048, 3072, 4096):
                raise ValueError(f"RSA key size must be 2048, 3072, or 4096. Got: {key_size}")
            return rsa.generate_private_key(public_exponent=65537, key_size=key_size)
        elif algo_upper == "ECDSA":
            curves: dict[int, ec.EllipticCurve] = {
                256: ec.SECP256R1(),
                384: ec.SECP384R1(),
                521: ec.SECP521R1(),
            }
            curve = curves.get(key_size)
            if curve is None:
                raise ValueError(f"ECDSA key size must be 256, 384, or 521. Got: {key_size}")
            return ec.generate_private_key(curve)
        elif algo_upper == "ED25519":
            return ed25519.Ed25519PrivateKey.generate()
        else:
            raise ValueError(f"Unsupported algorithm: {algo}")

    def _build_name(self, subject: SubjectInfo) -> Name:
        attrs = []
        attrs.append(x509.NameAttribute(NameOID.COMMON_NAME, subject.cn))
        if subject.o:
            attrs.append(x509.NameAttribute(NameOID.ORGANIZATION_NAME, subject.o))
        if subject.ou:
            attrs.append(x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, subject.ou))
        if subject.c:
            attrs.append(x509.NameAttribute(NameOID.COUNTRY_NAME, subject.c))
        if subject.st:
            attrs.append(x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, subject.st))
        if subject.l:
            attrs.append(x509.NameAttribute(NameOID.LOCALITY_NAME, subject.l))
        return Name(attrs)

    def _build_san_extension(self, san_list: list[SANEntry]) -> list[x509.GeneralName]:
        names: list[x509.GeneralName] = []
        for entry in san_list:
            if entry.type == "dns":
                names.append(x509.DNSName(entry.value))
            elif entry.type == "ip":
                import ipaddress
                names.append(x509.IPAddress(ipaddress.ip_address(entry.value)))
            elif entry.type == "email":
                names.append(x509.RFC822Name(entry.value))
            elif entry.type == "uri":
                names.append(x509.UniformResourceIdentifier(entry.value))
        return names

    def _get_digest(self, digest: str, key: PrivateKeyTypes) -> hashes.HashAlgorithm | None:
        # Ed25519 uses None for digest (it's built-in)
        if isinstance(key, ed25519.Ed25519PrivateKey):
            return None
        algo_class = DIGEST_MAP.get(digest)
        if algo_class is None:
            raise ValueError(f"Unsupported digest: {digest}. Use sha256, sha384, or sha512.")
        return algo_class()

    def _random_serial(self) -> int:
        return int.from_bytes(os.urandom(16), byteorder="big")

    def create_root_ca(
        self,
        subject: SubjectInfo,
        key: PrivateKeyTypes,
        validity_days: int,
        path_length: int = 1,
        digest: str = "sha256",
    ) -> x509.Certificate:
        name = self._build_name(subject)
        now = datetime.now(timezone.utc)

        builder = (
            CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(self._random_serial())
            .not_valid_before(now)
            .not_valid_after(now + timedelta(days=validity_days))
            .add_extension(
                BasicConstraints(ca=True, path_length=path_length), critical=True
            )
            .add_extension(
                KeyUsage(
                    key_cert_sign=True,
                    crl_sign=True,
                    digital_signature=False,
                    key_encipherment=False,
                    content_commitment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
            )
            .add_extension(
                AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False
            )
        )

        return builder.sign(key, self._get_digest(digest, key))

    def create_intermediate_ca(
        self,
        subject: SubjectInfo,
        key: PrivateKeyTypes,
        parent_ca_key: PrivateKeyTypes,
        parent_ca_cert: x509.Certificate,
        validity_days: int,
        path_length: int = 0,
        digest: str = "sha256",
        name_constraints: dict | None = None,
    ) -> x509.Certificate:
        name = self._build_name(subject)
        now = datetime.now(timezone.utc)

        builder = (
            CertificateBuilder()
            .subject_name(name)
            .issuer_name(parent_ca_cert.subject)
            .public_key(key.public_key())
            .serial_number(self._random_serial())
            .not_valid_before(now)
            .not_valid_after(now + timedelta(days=validity_days))
            .add_extension(
                BasicConstraints(ca=True, path_length=path_length), critical=True
            )
            .add_extension(
                KeyUsage(
                    key_cert_sign=True,
                    crl_sign=True,
                    digital_signature=True,
                    key_encipherment=False,
                    content_commitment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
            )
            .add_extension(
                AuthorityKeyIdentifier.from_issuer_public_key(
                    parent_ca_cert.public_key()
                ),
                critical=False,
            )
        )

        # Name Constraints extension
        if name_constraints:
            permitted = name_constraints.get("permitted", [])
            excluded = name_constraints.get("excluded", [])
            permitted_subtrees = [x509.DNSName(d) for d in permitted] if permitted else None
            excluded_subtrees = [x509.DNSName(d) for d in excluded] if excluded else None
            if permitted_subtrees or excluded_subtrees:
                builder = builder.add_extension(
                    x509.NameConstraints(permitted_subtrees, excluded_subtrees), critical=True
                )

        return builder.sign(parent_ca_key, self._get_digest(digest, parent_ca_key))

    def issue_certificate(
        self,
        profile: str,
        subject: SubjectInfo,
        san_list: list[SANEntry],
        key: PrivateKeyTypes,
        signing_ca_key: PrivateKeyTypes,
        signing_ca_cert: x509.Certificate,
        validity_days: int,
        digest: str = "sha256",
        signing_ca_id: str | None = None,
        pki_base_url: str = "",
        policy_oid: str | None = None,
        cps_url: str | None = None,
        serial_number: int | None = None,
    ) -> x509.Certificate:
        if profile == "server" and not san_list:
            raise ValueError("Server certificates require at least one SAN entry (RFC 2818)")

        name = self._build_name(subject)
        now = datetime.now(timezone.utc)

        # Key usage from profile
        ku_config = PROFILE_KEY_USAGE.get(profile, PROFILE_KEY_USAGE["server"])

        builder = (
            CertificateBuilder()
            .subject_name(name)
            .issuer_name(signing_ca_cert.subject)
            .public_key(key.public_key())
            .serial_number(serial_number if serial_number is not None else self._random_serial())
            .not_valid_before(now)
            .not_valid_after(now + timedelta(days=validity_days))
            .add_extension(
                BasicConstraints(ca=False, path_length=None), critical=True
            )
            .add_extension(
                KeyUsage(
                    key_cert_sign=ku_config.get("key_cert_sign", False),
                    crl_sign=ku_config.get("crl_sign", False),
                    digital_signature=ku_config.get("digital_signature", False),
                    key_encipherment=ku_config.get("key_encipherment", False),
                    content_commitment=ku_config.get("content_commitment", False),
                    data_encipherment=False,
                    key_agreement=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
            )
            .add_extension(
                AuthorityKeyIdentifier.from_issuer_public_key(
                    signing_ca_cert.public_key()
                ),
                critical=False,
            )
        )

        # Extended Key Usage
        eku_oids = PROFILE_EKU.get(profile)
        if eku_oids:
            builder = builder.add_extension(ExtendedKeyUsage(eku_oids), critical=False)

        # SAN
        if san_list:
            san_names = self._build_san_extension(san_list)
            builder = builder.add_extension(
                SubjectAlternativeName(san_names), critical=False
            )

        # CDP (CRL Distribution Point)
        if pki_base_url and signing_ca_id:
            from cryptography.x509 import DistributionPoint, UniformResourceIdentifier as URI
            cdp_url = f"{pki_base_url}/api/v1/pki/crl/{signing_ca_id}"
            dp = DistributionPoint(
                full_name=[x509.UniformResourceIdentifier(cdp_url)],
                relative_name=None,
                crl_issuer=None,
                reasons=None,
            )
            builder = builder.add_extension(
                CRLDistributionPoints([dp]), critical=False
            )

        # AIA (Authority Information Access)
        if pki_base_url and signing_ca_id:
            from cryptography.x509 import AuthorityInformationAccessOID
            from cryptography.x509 import AccessDescription
            aia_descriptions = [
                AccessDescription(
                    AuthorityInformationAccessOID.OCSP,
                    x509.UniformResourceIdentifier(f"{pki_base_url}/api/v1/pki/ocsp"),
                ),
                AccessDescription(
                    AuthorityInformationAccessOID.CA_ISSUERS,
                    x509.UniformResourceIdentifier(f"{pki_base_url}/api/v1/pki/ca/{signing_ca_id}/cert"),
                ),
            ]
            from cryptography.x509 import AuthorityInformationAccess
            builder = builder.add_extension(
                AuthorityInformationAccess(aia_descriptions), critical=False
            )

        # Certificate Policies
        if policy_oid:
            from cryptography.x509 import CertificatePolicies, PolicyInformation, UserNotice
            qualifiers = None
            if cps_url:
                qualifiers = [cps_url]
            pi = PolicyInformation(x509.ObjectIdentifier(policy_oid), qualifiers)
            builder = builder.add_extension(
                CertificatePolicies([pi]), critical=False
            )

        return builder.sign(signing_ca_key, self._get_digest(digest, signing_ca_key))

    # --- Export methods ---

    def export_pem(
        self, cert: x509.Certificate, key: PrivateKeyTypes | None = None, passphrase: str | None = None
    ) -> bytes:
        cert_pem = cert.public_bytes(serialization.Encoding.PEM)
        if key is None:
            return cert_pem

        enc: serialization.KeySerializationEncryption
        if passphrase:
            enc = serialization.BestAvailableEncryption(passphrase.encode())
        else:
            enc = serialization.NoEncryption()

        key_pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=enc,
        )
        return key_pem + cert_pem

    def export_cert_pem(self, cert: x509.Certificate) -> bytes:
        return cert.public_bytes(serialization.Encoding.PEM)

    def export_key_pem(self, key: PrivateKeyTypes, passphrase: str | None = None) -> bytes:
        enc: serialization.KeySerializationEncryption
        if passphrase:
            enc = serialization.BestAvailableEncryption(passphrase.encode())
        else:
            enc = serialization.NoEncryption()

        return key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=enc,
        )

    def export_der(self, cert: x509.Certificate) -> bytes:
        return cert.public_bytes(serialization.Encoding.DER)

    def export_pkcs12(
        self,
        cert: x509.Certificate,
        key: PrivateKeyTypes,
        chain: list[x509.Certificate] | None = None,
        password: str | None = None,
        friendly_name: str = "certificate",
    ) -> bytes:
        pwd = password.encode() if password else None
        cas = chain if chain else None
        return _pkcs12.serialize_key_and_certificates(
            friendly_name.encode(),
            key,
            cert,
            cas,
            serialization.BestAvailableEncryption(pwd) if pwd else serialization.NoEncryption(),
        )

    # --- Cross-Certification ---

    def create_cross_certificate(
        self,
        external_ca_cert: x509.Certificate,
        signing_ca_key: PrivateKeyTypes,
        signing_ca_cert: x509.Certificate,
        validity_days: int,
        path_length: int = 0,
        name_constraints: dict | None = None,
        digest: str = "sha256",
    ) -> x509.Certificate:
        """Issue a cross-certificate: local CA signs external CA's public key.

        The resulting certificate asserts that the local CA trusts the external CA.
        Clients trusting the local CA can now validate certs from the external CA.
        """
        now = datetime.now(timezone.utc)

        builder = (
            CertificateBuilder()
            .subject_name(external_ca_cert.subject)
            .issuer_name(signing_ca_cert.subject)
            .public_key(external_ca_cert.public_key())
            .serial_number(self._random_serial())
            .not_valid_before(now)
            .not_valid_after(now + timedelta(days=validity_days))
            .add_extension(
                BasicConstraints(ca=True, path_length=path_length), critical=True
            )
            .add_extension(
                KeyUsage(
                    key_cert_sign=True,
                    crl_sign=True,
                    digital_signature=False,
                    key_encipherment=False,
                    content_commitment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                SubjectKeyIdentifier.from_public_key(external_ca_cert.public_key()), critical=False
            )
            .add_extension(
                AuthorityKeyIdentifier.from_issuer_public_key(
                    signing_ca_cert.public_key()
                ),
                critical=False,
            )
        )

        # Name Constraints to limit what the cross-signed CA can issue
        if name_constraints:
            permitted = name_constraints.get("permitted", [])
            excluded = name_constraints.get("excluded", [])
            permitted_subtrees = [x509.DNSName(d) for d in permitted] if permitted else None
            excluded_subtrees = [x509.DNSName(d) for d in excluded] if excluded else None
            if permitted_subtrees or excluded_subtrees:
                builder = builder.add_extension(
                    x509.NameConstraints(permitted_subtrees, excluded_subtrees), critical=True
                )

        return builder.sign(signing_ca_key, self._get_digest(digest, signing_ca_key))

    # --- CRL ---

    # RFC 5280 §5.3.1 reason codes
    CRL_REASON_MAP: dict[str, x509.ReasonFlags] = {
        "unspecified": x509.ReasonFlags.unspecified,
        "key_compromise": x509.ReasonFlags.key_compromise,
        "ca_compromise": x509.ReasonFlags.ca_compromise,
        "affiliation_changed": x509.ReasonFlags.affiliation_changed,
        "superseded": x509.ReasonFlags.superseded,
        "cessation_of_operation": x509.ReasonFlags.cessation_of_operation,
        "certificate_hold": x509.ReasonFlags.certificate_hold,
        "privilege_withdrawn": x509.ReasonFlags.privilege_withdrawn,
        "remove_from_crl": x509.ReasonFlags.remove_from_crl,
    }

    def generate_crl(
        self,
        ca_cert: x509.Certificate,
        ca_key: PrivateKeyTypes,
        revoked_entries: list[tuple[int, datetime, str | None]],
        validity_days: int = 30,
        digest: str = "sha256",
    ) -> bytes:
        now = datetime.now(timezone.utc)
        builder = (
            x509.CertificateRevocationListBuilder()
            .issuer_name(ca_cert.subject)
            .last_update(now)
            .next_update(now + timedelta(days=validity_days))
        )

        for entry in revoked_entries:
            serial, revocation_date = entry[0], entry[1]
            reason_str = entry[2] if len(entry) > 2 else None

            revoked_builder = (
                x509.RevokedCertificateBuilder()
                .serial_number(serial)
                .revocation_date(revocation_date)
            )

            # Add CRLReason extension if reason is provided and not "unspecified"
            if reason_str and reason_str in self.CRL_REASON_MAP:
                revoked_builder = revoked_builder.add_extension(
                    x509.CRLReason(self.CRL_REASON_MAP[reason_str]), critical=False
                )

            builder = builder.add_revoked_certificate(revoked_builder.build())

        crl = builder.sign(ca_key, self._get_digest(digest, ca_key))
        return crl.public_bytes(serialization.Encoding.DER)

    # --- CSR ---

    def generate_csr(
        self,
        subject: SubjectInfo,
        san_list: list[SANEntry],
        key: PrivateKeyTypes,
        digest: str = "sha256",
    ) -> x509.CertificateSigningRequest:
        name = self._build_name(subject)
        builder = CertificateSigningRequestBuilder().subject_name(name)

        if san_list:
            san_names = self._build_san_extension(san_list)
            builder = builder.add_extension(
                SubjectAlternativeName(san_names), critical=False
            )

        return builder.sign(key, self._get_digest(digest, key))

    def csr_from_existing_key(
        self,
        key_bytes: bytes,
        passphrase: str | None,
        subject: SubjectInfo,
        san_list: list[SANEntry],
        digest: str = "sha256",
    ) -> x509.CertificateSigningRequest:
        pwd = passphrase.encode() if passphrase else None
        key = serialization.load_pem_private_key(key_bytes, password=pwd)
        return self.generate_csr(subject, san_list, key, digest)

    def verify_csr(self, csr: x509.CertificateSigningRequest) -> dict[str, str]:
        results: dict[str, str] = {}

        # Signature valid
        if csr.is_signature_valid:
            results["signature"] = "pass"
        else:
            results["signature"] = "fail"

        # CN present
        cn_attrs = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        if cn_attrs and cn_attrs[0].value:
            results["cn_present"] = "pass"
        else:
            results["cn_present"] = "fail"

        # Key size check
        pub_key = csr.public_key()
        if isinstance(pub_key, rsa.RSAPublicKey):
            size = pub_key.key_size
            if size >= 2048:
                results["key_size"] = "pass"
            elif size >= 1024:
                results["key_size"] = "warn"
            else:
                results["key_size"] = "fail"
        else:
            results["key_size"] = "pass"

        return results

    def export_csr_pem(self, csr: x509.CertificateSigningRequest) -> bytes:
        return csr.public_bytes(serialization.Encoding.PEM)

    def export_csr_der(self, csr: x509.CertificateSigningRequest) -> bytes:
        return csr.public_bytes(serialization.Encoding.DER)

    # --- Key encryption ---

    def encrypt_key_blob(self, key_pem: bytes, master_key: str) -> bytes:
        f = Fernet(master_key.encode())
        return f.encrypt(key_pem)

    def decrypt_key_blob(self, blob: bytes, master_key: str) -> bytes:
        f = Fernet(master_key.encode())
        return f.decrypt(blob)
