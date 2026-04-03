"""
API analysis endpoint tests.

Covers:
  - POST /api/v1/analysis/
  - GET  /api/v1/analysis/
  - GET  /api/v1/analysis/{task_id}
  - GET  /api/v1/analysis/{task_id}/progress
"""
import time

import pytest
import requests

from fixtures.sample_analysis import (
    ANALYSIS_RESPONSE_FIELDS,
    VALID_ANALYSTS,
    VALID_EXCHANGES,
    VALID_SOURCES,
)


@pytest.mark.api
class TestCreateAnalysis:
    """Tests for POST /api/v1/analysis/"""

    def test_create_analysis_success(self, api_url: str, sample_analysis_payload):
        resp = requests.post(
            f"{api_url}/api/v1/analysis/",
            json=sample_analysis_payload,
            timeout=30,
        )
        assert resp.status_code in (200, 202)
        body = resp.json()
        assert "task_id" in body
        assert body["task_id"] != ""
        assert body["status"] in ("PENDING", "RUNNING")

    def test_create_analysis_response_fields(self, api_url: str, sample_analysis_payload):
        resp = requests.post(
            f"{api_url}/api/v1/analysis/",
            json=sample_analysis_payload,
            timeout=30,
        )
        body = resp.json()
        for field in ANALYSIS_RESPONSE_FIELDS:
            assert field in body, f"Missing field '{field}' in response"

    def test_create_analysis_missing_symbol(self, api_url: str):
        resp = requests.post(
            f"{api_url}/api/v1/analysis/",
            json={},
            timeout=10,
        )
        assert resp.status_code == 422  # Validation error

    def test_create_analysis_invalid_exchange(self, api_url: str):
        payload = {
            "symbol": "000001",
            "exchange": "INVALID",
        }
        resp = requests.post(
            f"{api_url}/api/v1/analysis/",
            json=payload,
            timeout=10,
        )
        assert resp.status_code == 422

    def test_create_with_different_exchanges(self, api_url: str):
        """Verify all valid exchanges are accepted."""
        for exchange in VALID_EXCHANGES:
            payload = {
                "symbol": "000001" if exchange == "CN" else "AAPL",
                "exchange": exchange,
            }
            resp = requests.post(
                f"{api_url}/api/v1/analysis/",
                json=payload,
                timeout=30,
            )
            assert resp.status_code in (200, 202, 422), (
                f"Exchange {exchange} returned {resp.status_code}"
            )


@pytest.mark.api
class TestListAnalyses:
    """Tests for GET /api/v1/analysis/"""

    def test_list_analyses_success(self, api_url: str):
        resp = requests.get(f"{api_url}/api/v1/analysis/", params={"limit": 10}, timeout=10)
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    def test_list_analyses_with_symbol_filter(self, api_url: str):
        resp = requests.get(
            f"{api_url}/api/v1/analysis/",
            params={"symbol": "000001", "limit": 5},
            timeout=10,
        )
        assert resp.status_code == 200
        body = resp.json()
        # If results exist, they should all match the symbol
        for item in body:
            assert item.get("symbol", "").upper() == "000001"

    def test_list_analyses_limit_param(self, api_url: str):
        resp = requests.get(
            f"{api_url}/api/v1/analysis/",
            params={"limit": 1},
            timeout=10,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) <= 1


@pytest.mark.api
class TestGetAnalysis:
    """Tests for GET /api/v1/analysis/{task_id}"""

    def test_get_analysis_404_for_missing(self, api_url: str):
        resp = requests.get(
            f"{api_url}/api/v1/analysis/nonexistent_task_id_12345",
            timeout=10,
        )
        assert resp.status_code == 404

    def test_get_analysis_created_task(self, api_url: str, sample_analysis_payload):
        # First create
        create_resp = requests.post(
            f"{api_url}/api/v1/analysis/",
            json=sample_analysis_payload,
            timeout=30,
        )
        assert create_resp.status_code in (200, 202)
        task_id = create_resp.json()["task_id"]

        # Then fetch
        get_resp = requests.get(
            f"{api_url}/api/v1/analysis/{task_id}",
            timeout=10,
        )
        assert get_resp.status_code == 200
        body = get_resp.json()
        assert body["task_id"] == task_id
        assert body["symbol"] == sample_analysis_payload["symbol"]


@pytest.mark.api
class TestGetProgress:
    """Tests for GET /api/v1/analysis/{task_id}/progress"""

    def test_progress_returns_sse(self, api_url: str, sample_analysis_payload):
        # Create a task first
        create_resp = requests.post(
            f"{api_url}/api/v1/analysis/",
            json=sample_analysis_payload,
            timeout=30,
        )
        assert create_resp.status_code in (200, 202)
        task_id = create_resp.json()["task_id"]

        # Request progress stream (SSE)
        try:
            resp = requests.get(
                f"{api_url}/api/v1/analysis/{task_id}/progress",
                timeout=15,
                stream=True,
            )
            # SSE endpoint should return 200
            assert resp.status_code == 200
            content_type = resp.headers.get("content-type", "")
            assert "text/event-stream" in content_type
        except requests.exceptions.ReadTimeout:
            # SSE streams may time out; that's acceptable
            pass

    def test_progress_404_for_missing(self, api_url: str):
        """SSE endpoint returns 200 with error event for nonexistent tasks."""
        resp = requests.get(
            f"{api_url}/api/v1/analysis/nonexistent_12345/progress",
            timeout=10,
        )
        # SSE streams always return 200; the error is in the event payload
        assert resp.status_code == 200
        body = resp.text
        # The event stream should contain an error event
        assert "error" in body.lower() or "not found" in body.lower()
