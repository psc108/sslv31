"""API versioning middleware — adds version headers and deprecation notices."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


# Version registry: path prefix -> version info
_VERSIONS = {
    "/api/v1": {"version": "1.0", "status": "stable"},
    "/api/v2": {"version": "2.0", "status": "current"},
}

# Deprecated endpoints: path -> sunset date (ISO 8601)
_DEPRECATED: dict[str, str] = {}


class APIVersionMiddleware(BaseHTTPMiddleware):
    """Adds API-Version, Deprecation, and Sunset headers to responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        path = request.url.path

        # Add version header
        for prefix, info in _VERSIONS.items():
            if path.startswith(prefix):
                response.headers["X-API-Version"] = info["version"]
                response.headers["X-API-Status"] = info["status"]
                break

        # Add deprecation headers for deprecated endpoints
        for dep_path, sunset_date in _DEPRECATED.items():
            if path.startswith(dep_path):
                response.headers["Deprecation"] = "true"
                response.headers["Sunset"] = sunset_date
                response.headers["Link"] = '</api/v2>; rel="successor-version"'
                break

        return response
