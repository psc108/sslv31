"""SSH connectivity service for Build Manager."""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

SSH_KEY_PATH = Path("/data/ssh/id_ed25519")


@dataclass
class SSHTestResult:
    success: bool
    message: str
    latency_ms: float | None = None
    host_key_fingerprint: str | None = None


def _rejects_as_ssh_option(value: str) -> bool:
    """True if `value` starts with '-' and so could be interpreted by the
    `ssh`/`ssh-keyscan` CLI as a flag rather than a literal hostname/username
    (a distinct injection class from shell metacharacter injection — still
    worth rejecting even once shell interpolation is removed)."""
    return value.startswith("-")


async def test_ssh_connectivity(
    host: str, port: int = 22, user: str = "root", timeout: int = 10,
    auth_method: str = "shared_key", credential_encrypted: str | None = None,
) -> SSHTestResult:
    """Test SSH connectivity to a host by running a simple command.

    auth_method/credential_encrypted select the per-host credential (Build
    Manager Hardening Plan, Stage 5) — defaults preserve the original
    shared-key behaviour for hosts that haven't opted into their own.
    """
    if _rejects_as_ssh_option(host) or _rejects_as_ssh_option(user):
        return SSHTestResult(success=False, message="Invalid host or user")

    from app.services.build_manager.ssh_credentials import SSHCredential

    async with SSHCredential(auth_method, credential_encrypted) as cred:
        sshpass_prefix = cred.sshpass_prefix()
        args = [
            *sshpass_prefix,
            "ssh", "-o", "StrictHostKeyChecking=no", "-o", f"ConnectTimeout={timeout}",
        ]
        if sshpass_prefix:
            # BatchMode=yes suppresses the interactive password prompt sshpass
            # relies on — must be off for password auth. Restrict to password
            # auth explicitly so a host with both a key and this password set
            # doesn't silently fall back to the wrong credential.
            args += ["-o", "PreferredAuthentications=password", "-o", "PubkeyAuthentication=no"]
        else:
            args += ["-o", "BatchMode=yes"]
        args += cred.key_args()
        args += ["-p", str(port), f"{user}@{host}", "echo", "OK"]

        start = asyncio.get_event_loop().time()
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 5)
            elapsed = (asyncio.get_event_loop().time() - start) * 1000

            if proc.returncode == 0 and b"OK" in stdout:
                fingerprint = await _get_host_fingerprint(host, port)
                return SSHTestResult(
                    success=True,
                    message="Connection successful",
                    latency_ms=round(elapsed, 1),
                    host_key_fingerprint=fingerprint,
                )
            else:
                err = stderr.decode().strip() or "Connection failed"
                return SSHTestResult(success=False, message=err)

        except asyncio.TimeoutError:
            return SSHTestResult(success=False, message=f"Connection timed out after {timeout}s")
        except Exception as e:
            return SSHTestResult(success=False, message=str(e))


async def _get_host_fingerprint(host: str, port: int) -> str | None:
    """Get SSH host key fingerprint."""
    if _rejects_as_ssh_option(host):
        return None
    try:
        keyscan = await asyncio.create_subprocess_exec(
            "ssh-keyscan", "-p", str(port), "-t", "ed25519", host,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        keyscan_out, _ = await asyncio.wait_for(keyscan.communicate(), timeout=5)
        if keyscan.returncode != 0 or not keyscan_out:
            return None

        keygen = await asyncio.create_subprocess_exec(
            "ssh-keygen", "-lf", "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(keygen.communicate(input=keyscan_out), timeout=5)
        if keygen.returncode == 0 and stdout:
            return stdout.decode().strip().split()[1] if stdout else None
    except Exception:
        logger.exception("Failed to get SSH host key fingerprint for %s:%s", host, port)
    return None


async def generate_ssh_keypair() -> tuple[str, str]:
    """Generate an Ed25519 SSH keypair for Ansible. Returns (private_path, public_key)."""
    SSH_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)

    if SSH_KEY_PATH.exists():
        pub = SSH_KEY_PATH.with_suffix(".pub").read_text().strip()
        return str(SSH_KEY_PATH), pub

    proc = await asyncio.create_subprocess_exec(
        "ssh-keygen", "-t", "ed25519", "-f", str(SSH_KEY_PATH), "-N", "", "-C", "buildmanager@certmanager",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()

    pub = SSH_KEY_PATH.with_suffix(".pub").read_text().strip()
    return str(SSH_KEY_PATH), pub


def get_public_key() -> str | None:
    """Return the public key if it exists."""
    pub_path = SSH_KEY_PATH.with_suffix(".pub")
    if pub_path.exists():
        return pub_path.read_text().strip()
    return None
