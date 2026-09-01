"""Security headers middleware for HTTP response hardening."""

from typing import Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Security headers middleware to add security-related HTTP headers.
    
    Adds standard security headers:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY
    - X-XSS-Protection: 1; mode=block
    - Strict-Transport-Security: max-age=31536000; includeSubDomains
    - Referrer-Policy: strict-origin-when-cross-origin
    - Content-Security-Policy: configurable (default: default-src 'self')
    """

    #: Swagger UI's own HTML (`/v1/docs`) ships as a page that pulls its JS
    #: and CSS from jsdelivr rather than bundling them, and FastAPI writes the
    #: `SwaggerUIBundle({...})` call as an inline `<script>` rather than a
    #: file — `default-src 'self'` makes both a blank page, not an error,
    #: since a blocked script fails silently. `'unsafe-inline'` is scoped to
    #: these paths alone; every other response, including `/v1/openapi.json`
    #: itself, keeps the strict default with no inline exception.
    DOCS_PATHS = ("/v1/docs", "/redoc")
    DOCS_CSP_POLICY = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src 'self' data: https://fastapi.tiangolo.com; "
        "connect-src 'self'"
    )

    def __init__(
        self,
        app,
        csp_policy: str = "default-src 'self'",
        hsts_max_age: int = 31536000,
        hsts_include_subdomains: bool = True,
    ):
        super().__init__(app)
        self.csp_policy = csp_policy
        self.hsts_max_age = hsts_max_age
        self.hsts_include_subdomains = hsts_include_subdomains

    def _build_hsts_header(self) -> str:
        """Build HSTS header value."""
        parts = [f"max-age={self.hsts_max_age}"]
        if self.hsts_include_subdomains:
            parts.append("includeSubDomains")
        return "; ".join(parts)

    def _build_security_headers(self, csp_policy: str) -> dict[str, str]:
        """Build all security headers."""
        hsts = self._build_hsts_header()
        return {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Strict-Transport-Security": hsts,
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Content-Security-Policy": csp_policy,
        }

    async def dispatch(self, request: Request, call_next) -> Response:
        """Process request and add security headers to response."""
        response = await call_next(request)

        csp_policy = (
            self.DOCS_CSP_POLICY
            if request.url.path in self.DOCS_PATHS
            else self.csp_policy
        )
        for header, value in self._build_security_headers(csp_policy).items():
            response.headers[header] = value

        return response