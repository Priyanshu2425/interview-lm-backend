"""Tests for RequestLoggingMiddleware."""

import logging
import re
from io import StringIO
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from interviewer.middleware.request_logging import RequestLoggingMiddleware


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


def create_test_app(middleware: RequestLoggingMiddleware) -> FastAPI:
    """Create a test FastAPI app with the request logging middleware."""
    app = FastAPI()
    
    @app.get("/test")
    async def test_endpoint():
        return {"ok": True}
    
    @app.get("/error")
    async def error_endpoint():
        raise ValueError("Test error")
    
    @app.post("/echo")
    async def echo_endpoint(data: dict):
        return data
    
    app.add_middleware(BaseHTTPMiddleware, dispatch=middleware.dispatch)
    return app


@pytest.fixture
def log_capture():
    """Capture log output for testing."""
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.DEBUG)
    
    logger = logging.getLogger("interviewer.middleware.request_logging")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.propagate = False
    
    yield stream
    
    logger.removeHandler(handler)


@pytest.fixture
def request_logging_middleware():
    """Create a RequestLoggingMiddleware instance for testing."""
    return RequestLoggingMiddleware(
        app=None,
        log_requests=True,
        log_responses=False,
    )


@pytest.fixture
def test_client(request_logging_middleware, log_capture):
    """Create a test client with request logging middleware."""
    app = create_test_app(request_logging_middleware)
    return TestClient(app)


class TestRequestLoggingMiddleware:
    """Tests for RequestLoggingMiddleware."""
    
    def test_generates_request_id(self, test_client, log_capture):
        """Should generate X-Request-ID header."""
        response = test_client.get("/test")
        assert response.status_code == 200
        assert "X-Request-ID" in response.headers
        # Validate UUID format
        request_id = response.headers["X-Request-ID"]
        assert re.match(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
            request_id
        )
    
    def test_adds_process_time_header(self, test_client, log_capture):
        """Should add X-Process-Time header."""
        response = test_client.get("/test")
        assert response.status_code == 200
        assert "X-Process-Time" in response.headers
        # Should be a valid float
        process_time = float(response.headers["X-Process-Time"])
        assert process_time >= 0
    
    def test_logs_request_start(self, test_client, log_capture):
        """Should log request start."""
        test_client.get("/test", headers={"User-Agent": "TestAgent/1.0"})
        
        logs = log_capture.getvalue()
        assert "Request started" in logs
        assert "/test" in logs
        assert "TestAgent/1.0" in logs
    
    def test_logs_request_completion(self, test_client, log_capture):
        """Should log request completion."""
        test_client.get("/test")
        
        logs = log_capture.getvalue()
        assert "Request completed successfully" in logs
        assert "/test" in logs
        assert "200" in logs
    
    def test_logs_client_error(self, test_client, log_capture):
        """Should log 4xx as warning."""
        test_client.get("/nonexistent")
        
        logs = log_capture.getvalue()
        assert "Request completed with client error" in logs
        assert "404" in logs
    
    def test_logs_server_error(self, test_client, log_capture):
        """Should log 5xx as error when exception is raised."""
        with pytest.raises(ValueError):
            test_client.get("/error")
        
        logs = log_capture.getvalue()
        assert "Request failed with exception" in logs
        assert "ValueError" in logs
        assert "Test error" in logs
    
    def test_logs_exception(self, test_client, log_capture):
        """Should log unhandled exceptions."""
        with pytest.raises(ValueError):
            test_client.get("/error")
        
        logs = log_capture.getvalue()
        assert "Request failed with exception" in logs
        assert "ValueError" in logs
        assert "Test error" in logs
    
    def test_logs_client_ip_from_x_forwarded_for(self, test_client, log_capture):
        """Should extract client IP from X-Forwarded-For."""
        test_client.get("/test", headers={"X-Forwarded-For": "203.0.113.195, 70.41.3.18"})
        
        logs = log_capture.getvalue()
        assert "203.0.113.195" in logs
    
    def test_logs_client_ip_from_x_real_ip(self, test_client, log_capture):
        """Should extract client IP from X-Real-IP."""
        test_client.get("/test", headers={"X-Real-IP": "198.51.100.1"})
        
        logs = log_capture.getvalue()
        assert "198.51.100.1" in logs
    
    def test_logs_query_params(self, test_client, log_capture):
        """Should log query parameters."""
        test_client.get("/test?foo=bar&baz=qux")
        
        logs = log_capture.getvalue()
        assert "foo" in logs
        assert "bar" in logs
        assert "baz" in logs
        assert "qux" in logs
    
    def test_logs_post_body(self, test_client, log_capture):
        """Should work with POST requests."""
        response = test_client.post("/echo", json={"key": "value"})
        assert response.status_code == 200
        
        logs = log_capture.getvalue()
        assert "POST" in logs
        assert "/echo" in logs
    
    def test_disabled_request_logging(self):
        """Should not log when log_requests=False."""
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.DEBUG)
        
        logger = logging.getLogger("interviewer.middleware.request_logging")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        logger.propagate = False
        
        middleware = RequestLoggingMiddleware(app=None, log_requests=False, log_responses=False)
        app = create_test_app(middleware)
        client = TestClient(app)
        
        client.get("/test")
        
        logs = stream.getvalue()
        assert "Request started" not in logs
        assert "Request completed" not in logs
        
        logger.removeHandler(handler)
    
    def test_log_responses_true_logs_body_on_error(self, log_capture):
        """Should log response details when log_responses=True on error."""
        middleware = RequestLoggingMiddleware(app=None, log_requests=True, log_responses=True)
        app = create_test_app(middleware)
        client = TestClient(app)
        
        client.get("/nonexistent")
        
        logs = log_capture.getvalue()
        assert "Response details" in logs
    
    def test_different_requests_have_different_ids(self, test_client, log_capture):
        """Each request should have a unique request ID."""
        response1 = test_client.get("/test")
        response2 = test_client.get("/test")
        
        assert response1.headers["X-Request-ID"] != response2.headers["X-Request-ID"]
    
    def test_process_time_is_reasonable(self, test_client, log_capture):
        """Process time should be reasonable (not negative, not huge)."""
        response = test_client.get("/test")
        process_time = float(response.headers["X-Process-Time"])
        
        # Should be positive and less than 10 seconds (generous bound)
        assert 0 <= process_time < 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])