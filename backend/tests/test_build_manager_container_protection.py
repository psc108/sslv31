"""ssl-cert-manager is the only container Build Manager must never remove.

target-* fixture containers were previously also protected, but turned out
to be a real liability this session: several environments collided with
them (host ports already bound by a long-running fixture, roles Host-Mapped
to them carrying stale state from unrelated earlier builds) with no way to
clean them up short of a manual `docker rm -f` outside the app entirely.
They're ordinary, removable hosts now — nothing about their name is special.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.build_manager import container_manager


@pytest.mark.usefixtures("setup_db")
async def test_remove_container_refuses_ssl_cert_manager():
    removed = await container_manager.remove_container("ssl-cert-manager")
    assert removed is False


@pytest.mark.usefixtures("setup_db")
async def test_remove_container_no_longer_protects_target_star_names():
    mock_response = MagicMock(status_code=204)
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.delete = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    for name in ("target-frontend", "target-backend", "target-mysql", "target-rabbitmq", "target-keystone"):
        with patch.object(container_manager.httpx, "AsyncClient", return_value=mock_client):
            removed = await container_manager.remove_container(name)
        assert removed is True, f"{name} should be removable now, not protected"
