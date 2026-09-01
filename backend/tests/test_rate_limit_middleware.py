"""Tests for RateLimitMiddleware."""

import time
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from interviewer.middleware.rate_limit import RateLimitMiddleware, EXCLUDED_PATHS


class MockApp:
    """Mock app that returns a simple response."""
    
    def __init__(self):
        self.calls = []
    
    async def __call__(self, scope, receive, send):
        self.calls.append(scope)
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json")],
        })
        await send({
            "type": "http.response.body",
            "body": b'{"ok": true}',
        })


def create_test_app(middleware: RateLimitMiddleware) -> FastAPI:
    """Create a test FastAPI app with the rate limit middleware."""
    app = FastAPI()
    
    @app.get("/test")
    async def test_endpoint():
        return {"ok": True}
    
    @app.get("/v1/sessions/test")
    async def workflow_endpoint():
        return {"ok": True}
    
    @app.get("/v1/health")
    async def health_endpoint():
        return {"ok": True}
    
    # Add middleware manually since we're testing it directly
    app.add_middleware(BaseHTTPMiddleware, dispatch=middleware.dispatch)
    return app


@pytest.fixture
def rate_limit_middleware():
    """Create a RateLimitMiddleware instance for testing."""
    return RateLimitMiddleware(
        app=None,
        enabled=True,
        requests_per_minute=5,
        window_seconds=60,
        workflow_path_prefix="/v1/sessions",
        workflow_requests_per_minute=10,
    )


@pytest.fixture
def test_client(rate_limit_middleware):
    """Create a test client with rate limit middleware."""
    app = create_test_app(rate_limit_middleware)
    return TestClient(app)


class TestRateLimitMiddleware:
    """Tests for RateLimitMiddleware."""
    
    def test_allows_requests_under_limit(self, test_client):
        """Requests under the limit should succeed."""
        for i in range(5):
            response = test_client.get("/test", headers={"X-Forwarded-For": "192.168.1.1"})
            assert response.status_code == 200
            assert response.headers["X-RateLimit-Limit"] == "5"
            assert int(response.headers["X-RateLimit-Remaining"]) == 4 - i
    
    def test_blocks_requests_over_limit(self, test_client):
        """Requests over the limit should return 429."""
        # Make 5 requests (the limit)
        for _ in range(5):
            response = test_client.get("/test", headers={"X-Forwarded-For": "192.168.1.2"})
            assert response.status_code == 200
        
        # 6th request should be blocked
        response = test_client.get("/test", headers={"X-Forwarded-For": "192.168.1.2"})
        assert response.status_code == 429
        assert response.json()["error"] == "Rate limit exceeded"
        assert "Retry-After" in response.headers
        assert response.headers["X-RateLimit-Remaining"] == "0"
    
    def test_different_ips_have_separate_limits(self, test_client):
        """Different IPs should have separate rate limit counters."""
        # Use up limit for IP 1
        for _ in range(5):
            test_client.get("/test", headers={"X-Forwarded-For": "192.168.1.3"})
        
        # IP 2 should still work
        response = test_client.get("/test", headers={"X-Forwarded-For": "192.168.1.4"})
        assert response.status_code == 200
        assert response.headers["X-RateLimit-Remaining"] == "4"
    
    def test_workflow_path_has_higher_limit(self, test_client):
        """Workflow paths should have higher rate limit."""
        # Make 5 requests to regular path (should be at limit)
        for _ in range(5):
            response = test_client.get("/test", headers={"X-Forwarded-For": "192.168.1.5"})
            assert response.status_code == 200
        
        # Workflow path should still allow requests (limit is 10)
        for _ in range(10):
            response = test_client.get("/v1/sessions/test", headers={"X-Forwarded-For": "192.168.1.5"})
            assert response.status_code == 200
            assert response.headers["X-RateLimit-Limit"] == "10"
        
        # 11th request to workflow should be blocked
        response = test_client.get("/v1/sessions/test", headers={"X-Forwarded-For": "192.168.1.5"})
        assert response.status_code == 429
    
    def test_excluded_paths_not_rate_limited(self, test_client):
        """Excluded paths should not be rate limited."""
        # Health endpoint should never be rate limited
        for _ in range(100):
            response = test_client.get("/v1/health", headers={"X-Forwarded-For": "192.168.1.6"})
            assert response.status_code == 200
            # No rate limit headers on excluded paths
            assert "X-RateLimit-Limit" not in response.headers
    
    def test_rate_limit_headers_present(self, test_client):
        """Rate limit headers should be present on responses."""
        response = test_client.get("/test", headers={"X-Forwarded-For": "192.168.1.7"})
        assert response.status_code == 200
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers
    
    def test_429_response_has_retry_after(self, test_client):
        """429 response should have Retry-After header."""
        # Exhaust limit
        for _ in range(5):
            test_client.get("/test", headers={"X-Forwarded-For": "192.168.1.8"})
        
        response = test_client.get("/test", headers={"X-Forwarded-For": "192.168.1.8"})
        assert response.status_code == 429
        assert "Retry-After" in response.headers
        assert int(response.headers["Retry-After"]) > 0
    
    def test_disabled_rate_limit_allows_all(self):
        """Disabled rate limiting should allow all requests."""
        middleware = RateLimitMiddleware(
            app=None,
            enabled=False,
            requests_per_minute=1,
            window_seconds=60,
        )
        app = create_test_app(middleware)
        client = TestClient(app)
        
        # Should allow many requests even with limit of 1
        for _ in range(10):
            response = client.get("/test", headers={"X-Forwarded-For": "192.168.1.9"})
            assert response.status_code == 200
    
    def test_client_ip_from_x_real_ip(self, test_client):
        """Should use X-Real-IP when X-Forwarded-For not present."""
        response = test_client.get("/test", headers={"X-Real-IP": "10.0.0.1"})
        assert response.status_code == 200
        assert response.headers["X-RateLimit-Remaining"] == "4"
    
    def test_client_ip_fallback(self, test_client):
        """Should fall back to direct client IP."""
        # TestClient uses testclient as client host
        response = test_client.get("/test")
        assert response.status_code == 200
    
    def test_cleanup_old_entries(self, rate_limit_middleware):
        """Old entries should be cleaned up periodically."""
        current_time = time.time()
        
        # Add some old entries
        rate_limit_middleware.client_requests["192.168.1.10"].extend([
            current_time - 200,  # older than 2 * window (120s)
            current_time - 150,
        ])
        rate_limit_middleware.client_requests["192.168.1.11"].append(current_time - 10)  # recent
        
        # Trigger cleanup
        rate_limit_middleware._cleanup_old_entries(current_time)
        
        # Old entries should be removed
        assert "192.168.1.10" not in rate_limit_middleware.client_requests
        assert "192.168.1.11" in rate_limit_middleware.client_requests
    
    def test_is_workflow_path_detection(self, rate_limit_middleware):
        """Workflow path detection should work correctly."""
        assert rate_limit_middleware._is_workflow_path("/v1/sessions")
        assert rate_limit_middleware._is_workflow_path("/v1/sessions/abc")
        assert rate_limit_middleware._is_workflow_path("/v1/sessions/abc/turns")
        assert not rate_limit_middleware._is_workflow_path("/v1/session")
        assert not rate_limit_middleware._is_workflow_path("/v1/skills")
        assert not rate_limit_middleware._is_workflow_path("/test")
    
    def test_is_excluded_path(self, rate_limit_middleware):
        """Excluded path detection should work correctly."""
        assert rate_limit_middleware._is_excluded("/v1/health")
        assert rate_limit_middleware._is_excluded("/v1/health/live")
        assert rate_limit_middleware._is_excluded("/v1/docs")
        assert rate_limit_middleware._is_excluded("/v1/openapi.json")
        assert not rate_limit_middleware._is_excluded("/test")
        assert not rate_limit_middleware._is_excluded("/v1/sessions/test")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])