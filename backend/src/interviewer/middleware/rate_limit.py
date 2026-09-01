"""Rate limiting middleware using sliding window algorithm (in-memory)."""

import time
import logging
from collections import defaultdict, deque
from typing import Optional

from fastapi import Request, Response, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from interviewer.config import config

logger = logging.getLogger(__name__)

# Paths that are excluded from rate limiting
EXCLUDED_PATHS = {
    "/v1/health",
    "/v1/health/live",
    "/v1/docs",
    "/v1/openapi.json",
}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware using sliding window algorithm (in-memory).
    
    Supports a higher limit for workflow routes (e.g., /v1/sessions) only.
    """

    def __init__(
        self,
        app,
        enabled: bool = True,
        requests_per_minute: int = 100,
        window_seconds: int = 60,
        workflow_path_prefix: str = "/v1/sessions",
        workflow_requests_per_minute: int = 300,
    ):
        super().__init__(app)
        self.enabled = enabled
        self.requests_per_minute = requests_per_minute
        self.window_seconds = window_seconds
        self.workflow_path_prefix = workflow_path_prefix.rstrip("/")
        self.workflow_requests_per_minute = workflow_requests_per_minute
        
        # In-memory storage: client_ip -> deque of request timestamps
        self.client_requests: defaultdict[str, deque[float]] = defaultdict(deque)
        self.workflow_client_requests: defaultdict[str, deque[float]] = defaultdict(deque)
        
        # Periodic cleanup
        self.cleanup_interval = 300  # 5 minutes
        self.last_cleanup = time.time()

    def _is_excluded(self, path: str) -> bool:
        """Check if path should be excluded from rate limiting."""
        return path in EXCLUDED_PATHS or path.startswith("/v1/docs") or path.startswith("/v1/openapi")

    def _is_workflow_path(self, path: str) -> bool:
        """Check if path is under the workflow prefix and has a higher limit configured."""
        return path.startswith(self.workflow_path_prefix + "/") or path == self.workflow_path_prefix

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request headers."""
        # Check X-Forwarded-For (standard proxy header)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        # Check X-Real-IP (nginx proxy)
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        
        # Fall back to direct connection
        if request.client:
            return request.client.host
        
        return "unknown"

    def _cleanup_old_entries(self, current_time: float) -> None:
        """Remove old request timestamps to prevent memory growth."""
        cutoff_time = current_time - self.window_seconds * 2
        
        for requests_dict in (self.client_requests, self.workflow_client_requests):
            clients_to_remove = []
            for client_ip, requests in list(requests_dict.items()):
                while requests and requests[0] <= cutoff_time:
                    requests.popleft()
                if not requests:
                    clients_to_remove.append(client_ip)
            for client_ip in clients_to_remove:
                del requests_dict[client_ip]

    def _is_allowed(self, client_ip: str, current_time: float, is_workflow: bool) -> tuple[bool, int, int]:
        """
        Check if request is allowed based on rate limit.
        
        Returns:
            tuple: (allowed, limit, remaining)
        """
        if is_workflow:
            queue = self.workflow_client_requests[client_ip]
            limit = self.workflow_requests_per_minute
        else:
            queue = self.client_requests[client_ip]
            limit = self.requests_per_minute

        # Remove expired entries
        while queue and queue[0] <= current_time - self.window_seconds:
            queue.popleft()

        remaining = max(0, limit - len(queue))
        allowed = len(queue) < limit
        
        return allowed, limit, remaining

    def _record_request(self, client_ip: str, current_time: float, is_workflow: bool) -> None:
        """Record a request timestamp."""
        if is_workflow:
            self.workflow_client_requests[client_ip].append(current_time)
        else:
            self.client_requests[client_ip].append(current_time)

    async def dispatch(self, request: Request, call_next) -> Response:
        """Process request and apply rate limiting."""
        path = request.url.path
        
        # Skip rate limiting if disabled or path excluded
        if not self.enabled or self._is_excluded(path):
            return await call_next(request)
        
        is_workflow = self._is_workflow_path(path)
        client_ip = self._get_client_ip(request)
        current_time = time.time()

        # Periodic cleanup
        if current_time - self.last_cleanup > self.cleanup_interval:
            self._cleanup_old_entries(current_time)
            self.last_cleanup = current_time

        # Check rate limit
        allowed, limit, _ = self._is_allowed(client_ip, current_time, is_workflow)

        if not allowed:
            logger.warning(
                "Rate limit exceeded",
                extra={
                    "client_ip": client_ip,
                    "limit": limit,
                    "window_seconds": self.window_seconds,
                    "path": path,
                    "is_workflow": is_workflow,
                },
            )
            reset_time = int(current_time + self.window_seconds)
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "message": f"Too many requests. Limit: {limit} requests per {self.window_seconds} seconds",
                    "retry_after": self.window_seconds,
                },
                headers={
                    "Retry-After": str(self.window_seconds),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_time),
                },
            )

        # Record the request
        self._record_request(client_ip, current_time, is_workflow)

        # Calculate remaining AFTER recording
        if is_workflow:
            queue = self.workflow_client_requests[client_ip]
            limit = self.workflow_requests_per_minute
        else:
            queue = self.client_requests[client_ip]
            limit = self.requests_per_minute
        remaining = max(0, limit - len(queue))

        # Process request
        try:
            response = await call_next(request)
        except HTTPException:
            # Let FastAPI handle HTTP exceptions normally
            raise
        except Exception as exc:
            logger.error(
                "Unhandled exception in route handler",
                exc_info=exc,
                extra={"path": path, "method": request.method},
            )
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"},
            )

        # Add rate limit headers to response
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(current_time + self.window_seconds))

        return response