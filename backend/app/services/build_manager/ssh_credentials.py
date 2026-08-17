"""Per-host SSH credential resolution — Build Manager Hardening Plan, Stage 5.

Every host previously used one shared SSH key with no alternative
(build_manager/__init__.py's SSH_KEY_PATH, referenced directly by
health_service.py and ansible_runner.py). This module resolves a host's
*actual* auth method (shared_key / private_key / password) into the
argv fragments needed to connect to it, decrypting credential material
only for the duration of one connection attempt.

Private keys must exist as a file for the `ssh`/`ansible-playbook` CLI's
`-i`/`--private-key` flag — decrypted key material is written to a mode-0600
temp file for the lifetime of the SSHCredential context and removed
immediately after, mirroring the existing pattern for Ansible's vault
extra-vars temp file (ansible_runner.py).

Password auth uses `sshpass` (already an image dependency, docker/Dockerfile)
rather than switching Ansible's connection plugin, so the same argv-building
logic works identically for both the direct SSH calls in this module's
callers and the Ansible invocation in ansible_runner.py.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from app.services.build_manager.secrets_service import decrypt_value

SHARED_SSH_KEY_PATH = Path("/data/ssh/id_ed25519")


class SSHCredential:
    """Resolved credential material for one connection attempt.

    Use as an async context manager so any temp private-key file is always
    cleaned up, even on error:

        async with SSHCredential(host.ssh_auth_method, host.ssh_credential_encrypted) as cred:
            argv = [*cred.sshpass_prefix(), "ssh", *cred.key_args(), ...]
    """

    def __init__(self, auth_method: str, credential_encrypted: str | None):
        self.auth_method = auth_method if auth_method in ("private_key", "password") else "shared_key"
        self._encrypted = credential_encrypted
        self._key_path: Path | None = None

    async def __aenter__(self) -> "SSHCredential":
        if self.auth_method == "private_key" and self._encrypted:
            key_material = decrypt_value(self._encrypted)
            fd, path = tempfile.mkstemp(prefix="bm_ssh_key_")
            os.close(fd)
            self._key_path = Path(path)
            self._key_path.write_text(key_material)
            self._key_path.chmod(0o600)
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._key_path is not None:
            self._key_path.unlink(missing_ok=True)
            self._key_path = None

    def sshpass_prefix(self) -> list[str]:
        """Argv prefix for password auth (empty list otherwise)."""
        if self.auth_method == "password" and self._encrypted:
            password = decrypt_value(self._encrypted)
            return ["sshpass", "-p", password]
        return []

    def key_args(self) -> list[str]:
        """`-i <path>` args — the per-host key if private_key auth, else the
        shared key (existing behaviour), else nothing."""
        if self.auth_method == "private_key" and self._key_path is not None:
            return ["-i", str(self._key_path)]
        if self.auth_method == "shared_key" and SHARED_SSH_KEY_PATH.exists():
            return ["-i", str(SHARED_SSH_KEY_PATH)]
        return []

    def ansible_private_key_file(self) -> str | None:
        """Path to use for ansible_ssh_private_key_file, if this host needs
        one materialised (private_key auth only — shared_key relies on
        ansible-playbook's global --private-key flag, password auth needs
        no key file at all)."""
        if self.auth_method == "private_key" and self._key_path is not None:
            return str(self._key_path)
        return None

    def ansible_password(self) -> str | None:
        if self.auth_method == "password" and self._encrypted:
            return decrypt_value(self._encrypted)
        return None
