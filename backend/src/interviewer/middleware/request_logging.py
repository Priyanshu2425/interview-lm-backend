"""Request logging middleware with structured logging and correlation IDs."""

import time
import uuid
import logging
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Enhanced request logging middleware with structured logging and performance tracking.
    
    Adds:
    - X-Request-ID header for correlation
    - X-Process-Time header for timing
    - Structured log entries with method, path, status, duration, client IP
    """

    def __init__(self, app, log_requests: bool = True, log_responses: bool = False):
        super().__init__(app)
        self.log_requests = log_requests
        self.log_responses = log_responses

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request headers."""
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()

        if request.client:
            return request.client.host

        return "unknown"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and log details with request correlation."""
        # Generate request ID for correlation
        request_id = str(uuid.uuid4())
        start_time = time.time()

        # Extract client info
        client_ip = self._get_client_ip(request)
        user_agent = request.headers.get("User-Agent", "Unknown")

        # Log request start
        if self.log_requests:
            query_str = "?" + "&".join(f"{k}={v}" for k, v in request.query_params.items()) if request.query_params else ""
            logger.info(
                "Request started: %s %s%s from %s (UA: %s)",
                request.method,
                request.url.path,
                query_str,
                client_ip,
                user_agent[:200],
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "query_params": dict(request.query_params),
                    "client_ip": client_ip,
                    "user_agent": user_agent[:200],
                },
            )

        # Process request
        try:
            response = await call_next(request)
        except Exception as e:
            # Log request error
            process_time = time.time() - start_time
            logger.error(
                "Request failed with exception: %s %s from %s - %s: %s",
                request.method,
                request.url.path,
                client_ip,
                type(e).__name__,
                str(e),
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(process_time * 1000, 2),
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "client_ip": client_ip,
                },
            )
            raise

        # Calculate processing time
        process_time = time.time() - start_time
        status_code = response.status_code

        # Log request completion
        log_data = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": status_code,
            "duration_ms": round(process_time * 1000, 2),
            "client_ip": client_ip,
        }

        # Log at different levels based on status code (if logging enabled)
        if self.log_requests:
            if status_code >= 500:
                logger.error(
                    "Request completed with server error: %s %s from %s - %d",
                    request.method,
                    request.url.path,
                    client_ip,
                    status_code,
                    extra=log_data,
                )
            elif status_code >= 400:
                logger.warning(
                    "Request completed with client error: %s %s from %s - %d",
                    request.method,
                    request.url.path,
                    client_ip,
                    status_code,
                    extra=log_data,
                )
            else:
                logger.info(
                    "Request completed successfully: %s %s from %s - %d",
                    request.method,
                    request.url.path,
                    client_ip,
                    status_code,
                    extra=log_data,
                )

        # Log response details if configured or error
        if self.log_responses or status_code >= 400:
            logger.debug(
                "Response details: %s %s from %s - %d",
                request.method,
                request.url.path,
                client_ip,
                status_code,
                extra=log_data,
            )

        # Add correlation headers to response
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = f"{process_time:.3f}"

        return response