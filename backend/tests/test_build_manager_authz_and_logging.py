"""Stage 2 of the Build Manager hardening plan — authorization bar fixes and
silent-failure logging.
"""
import logging

import pytest

from app.api.v1.build_manager import router


def _find_route(path: str, method: str):
    for r in router.routes:
        if r.path == path and method in r.methods:
            return r
    raise AssertionError(f"route not found: {method} {path}")


def _allowed_roles_of(route) -> tuple[str, ...]:
    """Introspect the require_role(...) dependency actually wired to a route."""
    for dep in route.dependant.dependencies:
        fn = dep.call
        freevars = getattr(fn.__code__, "co_freevars", ())
        if "allowed_roles" in freevars:
            idx = freevars.index("allowed_roles")
            return fn.__closure__[idx].cell_contents
    raise AssertionError(f"no require_role dependency found on {route.path}")


def test_destroy_env_requires_admin_only():
    route = _find_route("/api/v1/build/environments/{env_id}/destroy", "POST")
    assert _allowed_roles_of(route) == ("admin",)


def test_rebuild_environment_requires_admin_only():
    route = _find_route("/api/v1/build/environments/{env_id}/rebuild", "POST")
    assert _allowed_roles_of(route) == ("admin",)


def test_delete_host_still_admin_only_precedent_unchanged():
    """The precedent these two were aligned to — confirm it wasn't disturbed."""
    route = _find_route("/api/v1/build/hosts/{host_id}", "DELETE")
    assert _allowed_roles_of(route) == ("admin",)


# ---------------------------------------------------------------------------
# Silent-failure logging
# ---------------------------------------------------------------------------

def test_corrupt_pkg_cache_manifest_fragment_is_logged(tmp_path, monkeypatch, caplog):
    from app.services.build_manager import pkg_cache_service as svc

    monkeypatch.setattr(svc, "CACHE_DIR", tmp_path)
    apt_dir = tmp_path / "apt"
    apt_dir.mkdir()
    frag_path = tmp_path / "manifest-apt.json"
    frag_path.write_text("{not valid json")

    with caplog.at_level(logging.ERROR):
        result = svc._os_cache_status("Debian")

    assert result["status"] in ("incomplete", "empty")
    assert any("manifest-apt.json" in r.message or "manifest fragment" in r.message for r in caplog.records)


def test_corrupt_pkg_cache_top_level_manifest_is_logged(tmp_path, monkeypatch, caplog):
    from app.services.build_manager import pkg_cache_service as svc

    monkeypatch.setattr(svc, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(svc, "MANIFEST_PATH", tmp_path / "manifest.json")
    (tmp_path / "manifest.json").write_text("{not valid json")

    with caplog.at_level(logging.ERROR):
        svc.get_cache_status()

    assert any("manifest" in r.message.lower() for r in caplog.records)


@pytest.mark.usefixtures("setup_db")
async def test_malformed_job_row_is_dropped_and_logged(client, caplog, monkeypatch):
    from datetime import datetime, timezone
    from app.core.database import async_session
    from app.models.build_manager import BMJob
    import app.api.v1.build_manager as bm_api

    good_id = "11111111-1111-1111-1111-111111111111"
    bad_id = "22222222-2222-2222-2222-222222222222"

    async with async_session() as session:
        session.add(BMJob(id=good_id, name="good-job", created_at=datetime.now(timezone.utc)))
        session.add(BMJob(id=bad_id, name="bad-job", created_at=datetime.now(timezone.utc)))
        await session.commit()

    real_job_to_dict = bm_api._job_to_dict

    def _flaky_job_to_dict(job):
        if job.id == bad_id:
            raise ValueError("simulated corrupt row")
        return real_job_to_dict(job)

    monkeypatch.setattr(bm_api, "_job_to_dict", _flaky_job_to_dict)

    with caplog.at_level(logging.ERROR):
        resp = await client.get("/api/v1/build/jobs")

    assert resp.status_code == 200
    ids = [j["id"] for j in resp.json()]
    assert good_id in ids
    assert bad_id not in ids
    assert any(bad_id in r.message for r in caplog.records)
