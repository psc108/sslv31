"""Python subprocess wrapper for Java keytool — JKS and PKCS#12 store operations."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.core.config import settings


class KeytoolError(Exception):
    pass


class KeytoolWrapper:
    """Wraps Java keytool for KeyStore and TrustStore operations."""

    def __init__(self) -> None:
        self._keytool_path = self._find_keytool()

    def _find_keytool(self) -> str | None:
        # Check JDK_HOME first
        if settings.JDK_HOME:
            candidate = Path(settings.JDK_HOME) / "bin" / "keytool"
            if candidate.exists():
                return str(candidate)

        # Check PATH
        keytool = shutil.which("keytool")
        if keytool:
            return keytool

        # Common Linux paths
        for path in [
            "/usr/lib/jvm/java-17-openjdk-amd64/bin/keytool",
            "/usr/lib/jvm/java-17-openjdk/bin/keytool",
            "/usr/bin/keytool",
        ]:
            if Path(path).exists():
                return path

        return None

    @property
    def available(self) -> bool:
        return self._keytool_path is not None

    def _run(self, args: list[str], stdin_data: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
        if not self._keytool_path:
            raise KeytoolError("keytool not found. Install JDK 17 or set JDK_HOME.")

        cmd = [self._keytool_path] + args
        try:
            result = subprocess.run(
                cmd,
                input=stdin_data,
                capture_output=True,
                timeout=30,
            )
            if result.returncode != 0:
                raise KeytoolError(
                    f"keytool failed (exit {result.returncode}): {result.stderr.decode(errors='replace')}"
                )
            return result
        except subprocess.TimeoutExpired as e:
            raise KeytoolError("keytool timed out after 30 seconds") from e
        except FileNotFoundError as e:
            raise KeytoolError(f"keytool not found at {self._keytool_path}") from e

    def create_keystore(
        self,
        cert_pem: bytes,
        key_pem: bytes,
        chain_pem: bytes,
        password: str,
        alias: str = "server",
    ) -> bytes:
        """Create a JKS KeyStore containing the private key and certificate chain.

        Uses PKCS#12 as intermediate format since keytool cannot directly import PEM keys.
        """
        if len(password) < 12:
            raise KeytoolError("KeyStore password must be at least 12 characters")

        tmp_dir = tempfile.mkdtemp(prefix="certmgr_")
        try:
            p12_path = os.path.join(tmp_dir, "keystore.p12")
            jks_path = os.path.join(tmp_dir, "keystore.jks")

            # Write PEM files
            combined_pem = key_pem + cert_pem + chain_pem
            pem_path = os.path.join(tmp_dir, "combined.pem")
            cert_path = os.path.join(tmp_dir, "cert.pem")
            key_path = os.path.join(tmp_dir, "key.pem")
            chain_path = os.path.join(tmp_dir, "chain.pem")

            with open(cert_path, "wb") as f:
                f.write(cert_pem)
            with open(key_path, "wb") as f:
                f.write(key_pem)
            with open(chain_path, "wb") as f:
                f.write(chain_pem)

            # Create PKCS#12 via openssl (keytool can't import raw PEM keys)
            subprocess.run(
                [
                    "openssl", "pkcs12", "-export",
                    "-in", cert_path,
                    "-inkey", key_path,
                    "-certfile", chain_path,
                    "-out", p12_path,
                    "-name", alias,
                    "-passout", f"pass:{password}",
                ],
                capture_output=True,
                timeout=30,
                check=True,
            )

            # Convert PKCS#12 to JKS
            self._run([
                "-importkeystore",
                "-srckeystore", p12_path,
                "-srcstoretype", "PKCS12",
                "-srcstorepass", password,
                "-destkeystore", jks_path,
                "-deststoretype", "JKS",
                "-deststorepass", password,
                "-noprompt",
            ])

            with open(jks_path, "rb") as f:
                return f.read()
        finally:
            # Secure cleanup — wipe temp files
            for root, dirs, files in os.walk(tmp_dir):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    size = os.path.getsize(fpath)
                    with open(fpath, "wb") as f:
                        f.write(b"\x00" * size)
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def create_truststore(
        self,
        ca_certs: list[tuple[str, bytes]],  # list of (alias, cert_pem_bytes)
        password: str,
        store_type: str = "JKS",
    ) -> bytes:
        """Create a TrustStore containing one or more CA certificates."""
        if store_type not in ("JKS", "PKCS12"):
            raise KeytoolError(f"Unsupported store type: {store_type}")

        tmp_dir = tempfile.mkdtemp(prefix="certmgr_ts_")
        try:
            store_ext = ".jks" if store_type == "JKS" else ".p12"
            store_path = os.path.join(tmp_dir, f"truststore{store_ext}")

            for alias, cert_pem in ca_certs:
                cert_file = os.path.join(tmp_dir, f"{alias}.pem")
                with open(cert_file, "wb") as f:
                    f.write(cert_pem)

                self._run([
                    "-importcert",
                    "-alias", alias,
                    "-file", cert_file,
                    "-keystore", store_path,
                    "-storetype", store_type,
                    "-storepass", password,
                    "-noprompt",
                ])

            with open(store_path, "rb") as f:
                return f.read()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def verify_store(self, store_bytes: bytes, password: str, store_type: str = "JKS") -> dict:
        """Verify a store is readable and return its contents summary."""
        if not self._keytool_path:
            raise KeytoolError("keytool not found")

        tmp_dir = tempfile.mkdtemp(prefix="certmgr_v_")
        try:
            store_ext = ".jks" if store_type == "JKS" else ".p12"
            store_path = os.path.join(tmp_dir, f"store{store_ext}")

            with open(store_path, "wb") as f:
                f.write(store_bytes)

            result = self._run([
                "-list",
                "-keystore", store_path,
                "-storetype", store_type,
                "-storepass", password,
            ])

            output = result.stdout.decode(errors="replace")
            entry_count = output.count("Entry type:")
            return {
                "valid": True,
                "store_type": store_type,
                "entries": entry_count,
                "raw_output": output,
            }
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
