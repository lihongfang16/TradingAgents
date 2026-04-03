"""
Shared fixtures and configuration for TradingAgents E2E tests.
"""
import os
import time
from typing import Dict, Any, Generator

import pytest
import requests


# ---------------------------------------------------------------------------
# Environment / URL configuration
# ---------------------------------------------------------------------------
# Both API and Web UI should run on localhost for E2E tests
TEST_API_URL = os.getenv("TEST_API_URL", "http://localhost:8000")
TEST_WEB_URL = os.getenv("TEST_WEB_URL", "http://localhost:8501")


@pytest.fixture(scope="session")
def api_url() -> str:
    """Base URL for the API server."""
    return TEST_API_URL


@pytest.fixture(scope="session")
def web_url() -> str:
    """Base URL for the Streamlit web UI."""
    return TEST_WEB_URL


@pytest.fixture(scope="session")
def base_url(web_url: str) -> str:
    """Playwright base_url fixture used by pytest-playwright."""
    return web_url


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def wait_for_api(api_url: str, timeout: int = 30, interval: int = 2) -> bool:
    """Block until the API health endpoint responds 200 or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(f"{api_url}/health", timeout=5)
            if resp.status_code == 200:
                return True
        except requests.ConnectionError:
            pass
        time.sleep(interval)
    return False


def wait_for_web(web_url: str, timeout: int = 60, interval: int = 3) -> bool:
    """Block until the Streamlit web UI responds 200 or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(web_url, timeout=10)
            if resp.status_code == 200:
                return True
        except requests.ConnectionError:
            pass
        time.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# Session-scoped connectivity check
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def _ensure_api_reachable(api_url: str):
    """Fail fast if the API is not reachable."""
    if not wait_for_api(api_url):
        pytest.exit(f"API server at {api_url} is not reachable. Aborting tests.")


@pytest.fixture(scope="session", autouse=True)
def _ensure_web_reachable(web_url: str):
    """Fail fast if the Web UI is not reachable."""
    if not wait_for_web(web_url):
        pytest.exit(f"Web UI at {web_url} is not reachable. Aborting tests.")


# ---------------------------------------------------------------------------
# Sample payloads
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_analysis_payload() -> Dict[str, Any]:
    """Valid payload for creating a single-stock analysis."""
    return {
        "symbol": "000001",
        "date": "2025-01-15",
        "exchange": "CN",
        "source": "mairui",
        "analysts": ["market", "news"],
    }


@pytest.fixture()
def sample_batch_payload() -> Dict[str, Any]:
    """Valid payload for a batch analysis request."""
    return {
        "symbols": ["000001", "600036"],
        "date": "2025-01-15",
        "exchange": "CN",
        "source": "mairui",
        "analysts": ["market"],
    }


# ---------------------------------------------------------------------------
# Cleanup helper – deletes a task via API if it exists
# ---------------------------------------------------------------------------

@pytest.fixture()
def cleanup_task(api_url: str):
    """Yield a cleanup function that attempts to delete a task.

    Usage::

        cleanup = cleanup_task(api_url)
        cleanup(task_id)
    """
    deleted_ids = []

    def _cleanup(task_id: str):
        deleted_ids.append(task_id)
        try:
            requests.delete(f"{api_url}/api/v1/analysis/{task_id}", timeout=5)
        except Exception:
            pass  # best-effort

    yield _cleanup
