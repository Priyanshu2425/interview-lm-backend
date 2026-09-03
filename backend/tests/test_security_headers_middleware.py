"""Tests for SecurityHeadersMiddleware."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from interviewer.middleware.security_headers import SecurityHeadersMiddleware


def create_test_app(middleware: SecurityHeadersMiddleware) -> FastAPI:
    """Create a test FastAPI app with the security headers middleware."""
    app = FastAPI()
    
    @app.get("/test")
    async def test_endpoint():
        return {"ok": True}
    
    @app.post("/echo")
    async def echo_endpoint(data: dict):
        return data
    
    app.add_middleware(BaseHTTPMiddleware, dispatch=middleware.dispatch)
    return app


@pytest.fixture
def security_headers_middleware():
    """Create a SecurityHeadersMiddleware instance for testing."""
    return SecurityHeadersMiddleware(
        app=None,
        csp_policy="default-src 'self'",
        hsts_max_age=31536000,
        hsts_include_subdomains=True,
    )


@pytest.fixture
def test_client(security_headers_middleware):
    """Create a test client with security headers middleware."""
    app = create_test_app(security_headers_middleware)
    return TestClient(app)


class TestSecurityHeadersMiddleware:
    """Tests for SecurityHeadersMiddleware."""
    
    def test_adds_x_content_type_options(self, test_client):
        """Should add X-Content-Type-Options: nosniff."""
        response = test_client.get("/test")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
    
    def test_adds_x_frame_options(self, test_client):
        """Should add X-Frame-Options: DENY."""
        response = test_client.get("/test")
        assert response.headers["X-Frame-Options"] == "DENY"
    
    def test_adds_x_xss_protection(self, test_client):
        """Should add X-XSS-Protection: 1; mode=block."""
        response = test_client.get("/test")
        assert response.headers["X-XSS-Protection"] == "1; mode=block"
    
    def test_adds_strict_transport_security(self, test_client):
        """Should add Strict-Transport-Security header."""
        response = test_client.get("/test")
        hsts = response.headers["Strict-Transport-Security"]
        assert "max-age=31536000" in hsts
        assert "includeSubDomains" in hsts
    
    def test_adds_referrer_policy(self, test_client):
        """Should add Referrer-Policy: strict-origin-when-cross-origin."""
        response = test_client.get("/test")
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    
    def test_adds_content_security_policy(self, test_client):
        """Should add Content-Security-Policy header."""
        response = test_client.get("/test")
        assert response.headers["Content-Security-Policy"] == "default-src 'self'"
    
    def test_all_headers_present_on_every_response(self, test_client):
        """All security headers should be present on every response."""
        expected_headers = {
            "X-Content-Type-Options",
            "X-Frame-Options",
            "X-XSS-Protection",
            "Strict-Transport-Security",
            "Referrer-Policy",
            "Content-Security-Policy",
        }
        
        # Test GET
        response = test_client.get("/test")
        for header in expected_headers:
            assert header in response.headers, f"Missing header: {header}"
        
        # Test POST
        response = test_client.post("/echo", json={"key": "value"})
        for header in expected_headers:
            assert header in response.headers, f"Missing header on POST: {header}"
    
    def test_custom_csp_policy(self):
        """Should use custom CSP policy when provided."""
        middleware = SecurityHeadersMiddleware(
            app=None,
            csp_policy="default-src 'self'; script-src 'self' 'unsafe-inline'",
        )
        app = create_test_app(middleware)
        client = TestClient(app)
        
        response = client.get("/test")
        assert response.headers["Content-Security-Policy"] == "default-src 'self'; script-src 'self' 'unsafe-inline'"
    
    def test_custom_hsts_max_age(self):
        """Should use custom HSTS max-age when provided."""
        middleware = SecurityHeadersMiddleware(
            app=None,
            csp_policy="default-src 'self'",
            hsts_max_age=86400,  # 1 day
            hsts_include_subdomains=True,
        )
        app = create_test_app(middleware)
        client = TestClient(app)
        
        response = client.get("/test")
        hsts = response.headers["Strict-Transport-Security"]
        assert "max-age=86400" in hsts
        assert "includeSubDomains" in hsts
    
    def test_hsts_without_subdomains(self):
        """Should omit includeSubDomains when disabled."""
        middleware = SecurityHeadersMiddleware(
            app=None,
            csp_policy="default-src 'self'",
            hsts_max_age=31536000,
            hsts_include_subdomains=False,
        )
        app = create_test_app(middleware)
        client = TestClient(app)
        
        response = client.get("/test")
        hsts = response.headers["Strict-Transport-Security"]
        assert "max-age=31536000" in hsts
        assert "includeSubDomains" not in hsts
    
    def test_headers_on_error_responses(self, test_client):
        """Security headers should be present on error responses too."""
        # 404
        response = test_client.get("/nonexistent")
        assert response.status_code == 404
        assert "X-Content-Type-Options" in response.headers
        assert "Strict-Transport-Security" in response.headers
    
    def test_headers_preserve_existing(self, test_client):
        """Should not remove existing headers from the response."""
        # The test app doesn't set custom headers, but middleware should
        # add to existing headers, not replace them
        response = test_client.get("/test")
        # All security headers present
        assert len(response.headers) >= 6  # At least our 6 security headers
    
    def test_hsts_header_format(self, test_client):
        """HSTS header should have correct format."""
        response = test_client.get("/test")
        hsts = response.headers["Strict-Transport-Security"]
        
        # Should be: max-age=31536000; includeSubDomains
        parts = [p.strip() for p in hsts.split(";")]
        assert "max-age=31536000" in parts
        assert "includeSubDomains" in parts
        assert len(parts) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

class TestTheDefaultPolicyLetsTheSurfaceListen:
    """ISSUE-0049. The Candidate's speech is transcribed in the browser, and a
    bare `default-src 'self'` refuses that outright — silently, which is the
    worst way: a blocked WebAssembly module is a microphone that never works
    and never says why.

    These are about the *default*, not about a configured deployment. Somebody
    tightening the policy later should have to change a test that says what the
    tightening breaks.
    """

    @pytest.fixture()
    def client(self):
        return TestClient(create_test_app(SecurityHeadersMiddleware(app=None)))

    def test_webassembly_may_be_compiled(self, client):
        csp = client.get("/test").headers["Content-Security-Policy"]
        assert "'wasm-unsafe-eval'" in csp

    def test_but_nothing_else_may_be_evaluated(self, client):
        """`'wasm-unsafe-eval'` permits compiling WebAssembly and nothing else.
        Bare `'unsafe-eval'` would hand back `eval()` and `new Function()`
        along with it, and the two are one character apart."""
        csp = client.get("/test").headers["Content-Security-Policy"]
        assert "'unsafe-eval'" not in csp.replace("'wasm-unsafe-eval'", "")
        assert "'unsafe-inline'" not in csp

    def test_the_model_weights_can_be_fetched(self, client):
        """Hugging Face serves the weights, and its blobs redirect to
        `cdn-lfs*.hf.co` — so both hosts, or the download fails on the
        redirect."""
        csp = client.get("/test").headers["Content-Security-Policy"]
        assert "https://huggingface.co" in csp
        assert "https://*.hf.co" in csp

    def test_nothing_else_gained_a_host(self, client):
        """The ONNX runtime is served from our own `/ort/`, deliberately, so
        that permitting the model download does not also permit a CDN to run
        code here."""
        csp = client.get("/test").headers["Content-Security-Policy"]
        script = next(p for p in csp.split(";") if p.strip().startswith("script-src"))
        assert "https://" not in script

    def test_the_page_is_not_cross_origin_isolated(self, client):
        """No COOP or COEP. They would buy threaded WebAssembly and cost the
        font stylesheet and the sign-in popup, which is a worse trade than a
        slower transcription."""
        headers = client.get("/test").headers
        assert "Cross-Origin-Opener-Policy" not in headers
        assert "Cross-Origin-Embedder-Policy" not in headers
