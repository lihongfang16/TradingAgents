"""
API health check tests.
"""
import pytest
import requests


@pytest.mark.api
class TestHealthEndpoint:
    """Tests for GET /health and GET / endpoints."""

    def test_root_returns_api_info(self, api_url: str):
        resp = requests.get(api_url, timeout=10)
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("name") == "TradingAgents API"
        assert "version" in body

    def test_health_returns_healthy(self, api_url: str):
        resp = requests.get(f"{api_url}/health", timeout=10)
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("status") == "healthy"

    def test_health_response_time(self, api_url: str):
        """Health endpoint should respond within 5 seconds."""
        resp = requests.get(f"{api_url}/health", timeout=10)
        assert resp.elapsed.total_seconds() < 5.0

    def test_health_content_type(self, api_url: str):
        resp = requests.get(f"{api_url}/health", timeout=10)
        assert "application/json" in resp.headers.get("content-type", "")
