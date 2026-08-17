"""Stage 5 of the Build Manager hardening plan — per-host SSH credentials.

Every host used to share one SSH key with no alternative. These tests cover
the new SSHCredential resolver (backend/app/services/build_manager/ssh_credentials.py),
its wiring into test_ssh_connectivity/_run_ssh_check, and the per-job
materialisation step in ansible_runner.py that turns the internal
_ssh_auth_method/_ssh_credential_encrypted hostvar markers into real
ansible_ssh_private_key_file/ansible_password values without ever writing
decrypted material into the long-lived inventory.
"""
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.services.build_manager.secrets_service import encrypt_value
from app.services.build_manager.ssh_credentials import SSHCredential


# --- SSHCredential ---

async def test_shared_key_credential_has_no_temp_file_and_uses_shared_key_args():
    async with SSHCredential("shared_key", None) as cred:
        assert cred.sshpass_prefix() == []
        assert cred.ansible_private_key_file() is None
        assert cred.ansible_password() is None


async def test_private_key_credential_materialises_and_cleans_up_temp_file():
    key_material = "-----BEGIN OPENSSH PRIVATE KEY-----\nfakekey\n-----END OPENSSH PRIVATE KEY-----\n"
    encrypted = encrypt_value(key_material)

    async with SSHCredential("private_key", encrypted) as cred:
        key_path = cred.ansible_private_key_file()
        assert key_path is not None
        p = Path(key_path)
        assert p.exists()
        assert p.read_text() == key_material
        assert oct(p.stat().st_mode)[-3:] == "600"
        assert cred.key_args() == ["-i", key_path]
        assert cred.sshpass_prefix() == []

    assert not Path(key_path).exists()  # cleaned up on context exit


async def test_password_credential_yields_sshpass_prefix_and_no_temp_file():
    encrypted = encrypt_value("hunter2")

    async with SSHCredential("password", encrypted) as cred:
        assert cred.sshpass_prefix() == ["sshpass", "-p", "hunter2"]
        assert cred.ansible_password() == "hunter2"
        assert cred.ansible_private_key_file() is None
        assert cred.key_args() == []  # no -i flag for password auth


async def test_unknown_auth_method_falls_back_to_shared_key():
    async with SSHCredential("nonsense", "irrelevant") as cred:
        assert cred.auth_method == "shared_key"


# --- test_ssh_connectivity / _run_ssh_check wiring ---

def _fake_process(returncode=0, communicate_result=(b"OK", b"")):
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=communicate_result)
    return proc


async def test_connectivity_check_password_auth_uses_sshpass_and_skips_batch_mode():
    from app.services.build_manager import test_ssh_connectivity as check_ssh_connectivity

    encrypted = encrypt_value("hunter2")
    with patch("app.services.build_manager.asyncio.create_subprocess_exec", new_callable=AsyncMock) as exec_mock:
        exec_mock.return_value = _fake_process()
        result = await check_ssh_connectivity(
            "10.0.0.5", port=22, user="root", timeout=1,
            auth_method="password", credential_encrypted=encrypted,
        )

    args = exec_mock.call_args_list[0].args
    assert args[0] == "sshpass"
    assert "-p" in args and "hunter2" in args
    assert "BatchMode=yes" not in " ".join(args)
    assert "PubkeyAuthentication=no" in args
    assert result.success is True


async def test_connectivity_check_private_key_auth_passes_materialised_key_path():
    key_material = "fake-private-key-material"
    encrypted = encrypt_value(key_material)
    seen_key_content = None

    def _capture_and_respond(*args, **kwargs):
        nonlocal seen_key_content
        if "-i" in args:
            # Read the key file *while the connection attempt is "in flight"*
            # (SSHCredential's temp file is only guaranteed to exist for the
            # lifetime of the `async with` block, so it must be read here).
            seen_key_content = Path(args[args.index("-i") + 1]).read_text()
        return _fake_process()

    with patch("app.services.build_manager.asyncio.create_subprocess_exec", new_callable=AsyncMock) as exec_mock:
        exec_mock.side_effect = _capture_and_respond
        result = await check_ssh_connectivity_wrapper(encrypted)

    args = exec_mock.call_args_list[0].args
    assert "-i" in args
    key_path = args[args.index("-i") + 1]
    assert seen_key_content == key_material
    assert not Path(key_path).exists()  # cleaned up after the call returns
    assert result.success is True


async def check_ssh_connectivity_wrapper(encrypted: str):
    from app.services.build_manager import test_ssh_connectivity as check_ssh_connectivity
    return await check_ssh_connectivity(
        "10.0.0.5", port=22, user="root", timeout=1,
        auth_method="private_key", credential_encrypted=encrypted,
    )


# --- inventory_service.py hostvar injection ---

@pytest.mark.usefixtures("setup_db")
async def test_inventory_omits_internal_fields_for_shared_key_hosts(client):
    resp = await client.post("/api/v1/build/hosts", json={
        "hostname": "shared-key-host", "ip": "10.0.0.10", "connection_type": "ssh",
    })
    assert resp.status_code == 201

    from app.core.database import async_session
    from app.services.build_manager.inventory_service import generate_ansible_inventory

    async with async_session() as db:
        inventory = await generate_ansible_inventory(db)
    hv = inventory["_meta"]["hostvars"]["shared-key-host"]
    assert "_ssh_auth_method" not in hv
    assert "_ssh_credential_encrypted" not in hv


@pytest.mark.usefixtures("setup_db")
async def test_inventory_includes_internal_fields_for_password_host(client):
    resp = await client.post("/api/v1/build/hosts", json={
        "hostname": "password-host", "ip": "10.0.0.11", "connection_type": "ssh",
        "ssh_auth_method": "password", "ssh_credential": "hunter2",
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()["ssh_auth_method"] == "password"
    assert resp.json()["ssh_credential_set"] is True
    assert "ssh_credential" not in resp.json()
    assert "ssh_credential_encrypted" not in resp.json()

    from app.core.database import async_session
    from app.services.build_manager.inventory_service import generate_ansible_inventory

    async with async_session() as db:
        inventory = await generate_ansible_inventory(db)
    hv = inventory["_meta"]["hostvars"]["password-host"]
    assert hv["_ssh_auth_method"] == "password"
    from app.services.build_manager.secrets_service import decrypt_value
    assert decrypt_value(hv["_ssh_credential_encrypted"]) == "hunter2"


@pytest.mark.usefixtures("setup_db")
async def test_update_host_to_shared_key_clears_stored_credential(client):
    resp = await client.post("/api/v1/build/hosts", json={
        "hostname": "revert-host", "ip": "10.0.0.12", "connection_type": "ssh",
        "ssh_auth_method": "password", "ssh_credential": "hunter2",
    })
    host_id = resp.json()["id"]

    resp = await client.put(f"/api/v1/build/hosts/{host_id}", json={"ssh_auth_method": "shared_key"})
    assert resp.status_code == 200
    assert resp.json()["ssh_auth_method"] == "shared_key"
    assert resp.json()["ssh_credential_set"] is False


# --- ansible_runner.py per-job credential materialisation ---

async def test_ansible_runner_materialises_and_cleans_up_credentials():
    from app.services.build_manager.ansible_runner import materialise_ssh_credentials

    key_material = "fake-private-key"
    password = "hunter2"
    inventory_data = {
        "_meta": {
            "hostvars": {
                "key-host": {
                    "ansible_host": "10.0.0.1",
                    "_ssh_auth_method": "private_key",
                    "_ssh_credential_encrypted": encrypt_value(key_material),
                },
                "pw-host": {
                    "ansible_host": "10.0.0.2",
                    "_ssh_auth_method": "password",
                    "_ssh_credential_encrypted": encrypt_value(password),
                },
                "shared-host": {
                    "ansible_host": "10.0.0.3",
                },
            }
        },
        "all": {"hosts": ["key-host", "pw-host", "shared-host"]},
    }

    credential_key_files = materialise_ssh_credentials(inventory_data, "test-job-1")

    hv = inventory_data["_meta"]["hostvars"]
    assert "_ssh_auth_method" not in hv["key-host"]
    assert "_ssh_credential_encrypted" not in hv["key-host"]
    assert Path(hv["key-host"]["ansible_ssh_private_key_file"]).read_text() == key_material
    assert oct(Path(hv["key-host"]["ansible_ssh_private_key_file"]).stat().st_mode)[-3:] == "600"
    assert hv["pw-host"]["ansible_password"] == password
    assert "ansible_ssh_private_key_file" not in hv["shared-host"]
    assert "ansible_password" not in hv["shared-host"]
    assert len(credential_key_files) == 1  # only the private_key host produced a temp file

    for key_path in credential_key_files:
        key_path.unlink(missing_ok=True)
    assert all(not p.exists() for p in credential_key_files)
