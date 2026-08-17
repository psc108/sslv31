"""Build Manager Jobs page rate-limit fix.

Reported by the user: the Jobs Monitor page kept failing to load with
"Failed to load jobs". Root cause: JobsPage.tsx's live output-streaming
loop (startStream/poll in JobsPage.tsx) polls GET /build/jobs/{id} and
GET /build/jobs/{id}/output together every ~1s while a job is
running/selected — 2 requests/second sustained — but every GET under
/api/ was classified as "general", whose budget (RATE_LIMIT_GENERAL,
default 60/60s = 1 req/s average) that single polling loop alone
structurally exceeds. Job list/detail/output GETs now get their own,
deliberately generous "job_polling" category instead of sharing the
general budget meant for one-off calls.
"""
from app.middleware.rate_limit import _classify_endpoint


def test_job_list_and_detail_gets_classified_as_job_polling():
    assert _classify_endpoint("/api/v1/build/jobs", "GET") == "job_polling"
    assert _classify_endpoint("/api/v1/build/jobs/abc-123", "GET") == "job_polling"
    assert _classify_endpoint("/api/v1/build/jobs/abc-123/output", "GET") == "job_polling"


def test_job_mutations_stay_under_general_not_job_polling():
    """Submit/cancel/retry/delete are one-off actions, not high-frequency
    polling — they should keep the tighter general budget."""
    assert _classify_endpoint("/api/v1/build/jobs", "POST") == "general"
    assert _classify_endpoint("/api/v1/build/jobs/abc-123/cancel", "POST") == "general"
    assert _classify_endpoint("/api/v1/build/jobs/abc-123/retry", "POST") == "general"
    assert _classify_endpoint("/api/v1/build/jobs/abc-123", "DELETE") == "general"


def test_unrelated_general_endpoints_unaffected():
    assert _classify_endpoint("/api/v1/build/environments", "GET") == "general"
    assert _classify_endpoint("/api/v1/build/templates", "GET") == "general"
