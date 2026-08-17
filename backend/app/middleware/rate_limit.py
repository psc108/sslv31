"""Rate limiting middleware — sliding window per-user and per-IP.

Returns 429 Too Many Requests with Retry-After header when limits are exceeded.
Configurable via environment variables.
"""

import time
from collections import defaultdict
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings


class _SlidingWindow:
    """Thread-safe sliding window counter."""

    def __init__(self):
        self._lock = Lock()
        # key -> list of timestamps
        self._windows: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """Check if request is allowed. Returns (allowed, retry_after_seconds)."""
        now = time.time()
        cutoff = now - window_seconds

        with self._lock:
            # Prune expired entries
            self._windows[key] = [t for t in self._windows[key] if t > cutoff]

            if len(self._windows[key]) >= limit:
                # Calculate when the oldest entry expires
                oldest = self._windows[key][0]
                retry_after = int(oldest + window_seconds - now) + 1
                return False, max(retry_after, 1)

            self._windows[key].append(now)
            return True, 0


# Global sliding window instance
_window = _SlidingWindow()

# Endpoint category patterns -> (limit, window_seconds)
_ENDPOINT_LIMITS: dict[str, tuple[int, int]] = {}


def _build_limits():
    """Build endpoint limits from settings (called once on first request)."""
    global _ENDPOINT_LIMITS
    _ENDPOINT_LIMITS = {
        "cert_issue": (settings.RATE_LIMIT_CERT_ISSUE, 60),
        "csr_generate": (settings.RATE_LIMIT_CSR_GENERATE, 60),
        "ocsp": (settings.RATE_LIMIT_OCSP, 1),
        "crl": (settings.RATE_LIMIT_CRL, 60),
        "login": (settings.RATE_LIMIT_LOGIN, 60),
        "export_key": (settings.RATE_LIMIT_EXPORT_KEY, 60),
        "general": (settings.RATE_LIMIT_GENERAL, 60),
        "job_polling": (settings.RATE_LIMIT_JOB_POLLING, 60),
    }


def _classify_endpoint(path: str, method: str) -> str | None:
    """Classify a request into a rate limit category. Returns None for exempt endpoints."""
    # Exempt endpoints
    if path in ("/api/v1/health", "/api/v1/diagnostics"):
        return None
    if path.startswith("/api/docs") or path.startswith("/api/openapi"):
        return None

    # Specific categories
    if path == "/api/v1/auth/login" and method == "POST":
        return "login"
    if path == "/api/v1/cert" and method == "POST":
        return "cert_issue"
    if path == "/api/v1/csr" and method == "POST":
        return "csr_generate"
    if path.startswith("/api/v1/ocsp"):
        return "ocsp"
    if path.startswith("/api/v1/crl"):
        return "crl"
    if "/export/" in path and "/key" in path:
        return "export_key"
    if path.startswith("/api/v1/export/") and method == "GET":
        return "export_key"
    # Build Manager's Jobs page live-polls list/detail/output at up to ~1s
    # intervals while a job is running/selected — a deliberately high-
    # frequency, cheap, read-only pattern that shouldn't share the general
    # budget meant for one-off calls. Only GET; submit/cancel/retry/delete
    # (POST/DELETE) are one-off actions and stay under "general".
    if path.startswith("/api/v1/build/jobs") and method == "GET":
        return "job_polling"

    # General API
    if path.startswith("/api/"):
        return "general"

    return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding window rate limiter per user/IP."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if not _ENDPOINT_LIMITS:
            _build_limits()

        path = request.url.path
        method = request.method
        category = _classify_endpoint(path, method)

        if category is None:
            return await call_next(request)

        limit, window = _ENDPOINT_LIMITS[category]
        if limit <= 0:
            # 0 = disabled
            return await call_next(request)

        # Determine rate limit key
        # For login/CRL/OCSP: use IP (no auth yet)
        # For authenticated endpoints: use username from auth header hint
        if category in ("login", "crl", "ocsp"):
            key = f"{category}:{_get_client_ip(request)}"
        else:
            # Try to extract identity from headers without full auth
            identity = _extract_identity_hint(request)
            key = f"{category}:{identity}"

        allowed, retry_after = _window.is_allowed(key, limit, window)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please slow down."},
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)


def _get_client_ip(request: Request) -> str:
    """Extract client IP from proxy headers or connection."""
    return (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )


def _extract_identity_hint(request: Request) -> str:
    """Extract a rate-limit identity without performing full auth.

    Falls back to IP if no auth header present.
    """
    # Check for API key
    api_key = request.headers.get("X-API-Key")
    if api_key:
        # Use last 8 chars as identity (don't expose full key)
        return f"key:{api_key[-8:]}"

    # Check for Bearer token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        # Use token hash prefix as identity
        import hashlib
        token = auth_header[7:]
        return f"tok:{hashlib.sha256(token.encode()).hexdigest()[:12]}"

    # Fall back to IP
    return f"ip:{_get_client_ip(request)}"
