"""Source IP extraction middleware for audit logging."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SourceIPMiddleware(BaseHTTPMiddleware):
    """Extract client source IP from proxy headers and attach to request state."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        source_ip = (
            request.headers.get("X-Real-IP")
            or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or (request.client.host if request.client else "unknown")
        )
        request.state.source_ip = source_ip
        return await call_next(request)
