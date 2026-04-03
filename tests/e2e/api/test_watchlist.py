"""
Watchlist API endpoint tests.

Covers:
  - POST   /api/v1/watchlist/                        (create entry)
  - GET    /api/v1/watchlist/                        (list entries)
  - GET    /api/v1/watchlist/{watchlist_id}          (get single entry)
  - PUT    /api/v1/watchlist/{watchlist_id}          (update entry)
  - DELETE /api/v1/watchlist/{watchlist_id}          (delete entry)
  - GET    /api/v1/watchlist/analysis                (list analyses)
  - GET    /api/v1/watchlist/alerts                  (turning-point alerts)
  - POST   /api/v1/watchlist/detect-turning          (detect turning points)
  - POST   /api/v1/watchlist/{watchlist_id}/quick-analyze (quick analysis)
 - GET    /api/v1/watchlist/scheduler/status        (scheduler status)
"""

# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportExplicitAny=false, reportGeneralTypeIssues=false, reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportDeprecated=false, reportMissingTypeArgument=false, reportUnusedImport=false, reportUnusedVariable=false, reportMissingParameterType=false, reportUnknownParameterType=false, reportUnusedCallResult=false
import pytest
import requests

# Minimal fields every WatchlistResponse must contain
WATCHLIST_RESPONSE_FIELDS = [
    "id", "symbol", "name", "exchange", "added_at",
    "is_active", "turning_detection_enabled", "confidence_jump_threshold",
]


def _watchlist_available(api_url: str) -> bool:
    """Check whether the watchlist API is registered (returns True on 200)."""
    try:
        resp = requests.get(f"{api_url}/api/v1/watchlist/", timeout=5)
        return resp.status_code != 404
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def cleanup_watchlist(api_url: str):
    """Delete any watchlist entries created during a test (best-effort)."""
    created_ids: list[int] = []

    def _track(watchlist_id: int):
        created_ids.append(watchlist_id)

    yield _track

    for wid in created_ids:
        try:
            requests.delete(f"{api_url}/api/v1/watchlist/{wid}", timeout=5)
        except Exception:
            pass


def _create_entry(api_url: str, symbol: str = "000001", name: str = "平安银行",
                  exchange: str = "CN") -> requests.Response:
    """Helper to create a watchlist entry; return the response."""
    return requests.post(
        f"{api_url}/api/v1/watchlist/",
        json={"symbol": symbol, "name": name, "exchange": exchange},
        timeout=10,
    )


# ===========================================================================
# CREATE
# ===========================================================================

@pytest.mark.api
class TestCreateWatchlist:
    """Tests for POST /api/v1/watchlist/"""

    @pytest.fixture(autouse=True)
    def _require_watchlist(self, api_url: str):
        if not _watchlist_available(api_url):
            pytest.skip("Watchlist API not available on this server")

    def test_create_success(self, api_url: str, cleanup_watchlist):
        resp = _create_entry(api_url)
        assert resp.status_code == 201
        body = resp.json()
        assert "id" in body
        assert body["symbol"] == "000001"
        assert body["name"] == "平安银行"
        assert body["exchange"] == "CN"
        assert body["is_active"] is True
        cleanup_watchlist(body["id"])

    def test_create_response_fields(self, api_url: str, cleanup_watchlist):
        resp = _create_entry(api_url)
        assert resp.status_code == 201
        body = resp.json()
        for field in WATCHLIST_RESPONSE_FIELDS:
            assert field in body, f"Missing field '{field}' in response"
        cleanup_watchlist(body["id"])

    def test_create_duplicate_returns_409(self, api_url: str, cleanup_watchlist):
        resp1 = _create_entry(api_url)
        assert resp1.status_code == 201
        cleanup_watchlist(resp1.json()["id"])

        resp2 = _create_entry(api_url)
        assert resp2.status_code == 409

    def test_create_missing_symbol_returns_422(self, api_url: str):
        resp = requests.post(
            f"{api_url}/api/v1/watchlist/",
            json={"name": "No Symbol"},
            timeout=10,
        )
        assert resp.status_code == 422


# ===========================================================================
# LIST
# ===========================================================================

@pytest.mark.api
class TestListWatchlist:
    """Tests for GET /api/v1/watchlist/"""

    @pytest.fixture(autouse=True)
    def _require_watchlist(self, api_url: str):
        if not _watchlist_available(api_url):
            pytest.skip("Watchlist API not available on this server")

    def test_list_returns_200(self, api_url: str):
        resp = requests.get(f"{api_url}/api/v1/watchlist/", timeout=10)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_with_active_only(self, api_url: str, cleanup_watchlist):
        entry = _create_entry(api_url)
        assert entry.status_code == 201
        entry_id = entry.json()["id"]
        cleanup_watchlist(entry_id)

        resp = requests.get(
            f"{api_url}/api/v1/watchlist/",
            params={"active_only": True},
            timeout=10,
        )
        assert resp.status_code == 200
        for item in resp.json():
            assert item["is_active"] is True

    def test_list_includes_created_entry(self, api_url: str, cleanup_watchlist):
        entry = _create_entry(api_url, symbol="600036", name="招商银行")
        assert entry.status_code == 201
        cleanup_watchlist(entry.json()["id"])

        resp = requests.get(f"{api_url}/api/v1/watchlist/", timeout=10)
        symbols = [item["symbol"] for item in resp.json()]
        assert "600036" in symbols


# ===========================================================================
# GET SINGLE
# ===========================================================================

@pytest.mark.api
class TestGetWatchlist:
    """Tests for GET /api/v1/watchlist/{watchlist_id}"""

    @pytest.fixture(autouse=True)
    def _require_watchlist(self, api_url: str):
        if not _watchlist_available(api_url):
            pytest.skip("Watchlist API not available on this server")

    def test_get_existing_entry(self, api_url: str, cleanup_watchlist):
        entry = _create_entry(api_url)
        entry_id = entry.json()["id"]
        cleanup_watchlist(entry_id)

        resp = requests.get(f"{api_url}/api/v1/watchlist/{entry_id}", timeout=10)
        assert resp.status_code == 200
        assert resp.json()["id"] == entry_id
        assert resp.json()["symbol"] == "000001"

    def test_get_nonexistent_returns_404(self, api_url: str):
        resp = requests.get(f"{api_url}/api/v1/watchlist/999999999", timeout=10)
        assert resp.status_code == 404


# ===========================================================================
# UPDATE
# ===========================================================================

@pytest.mark.api
class TestUpdateWatchlist:
    """Tests for PUT /api/v1/watchlist/{watchlist_id}"""

    @pytest.fixture(autouse=True)
    def _require_watchlist(self, api_url: str):
        if not _watchlist_available(api_url):
            pytest.skip("Watchlist API not available on this server")

    def test_update_name(self, api_url: str, cleanup_watchlist):
        entry = _create_entry(api_url)
        entry_id = entry.json()["id"]
        cleanup_watchlist(entry_id)

        resp = requests.put(
            f"{api_url}/api/v1/watchlist/{entry_id}",
            json={"name": "新名称"},
            timeout=10,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "新名称"

    def test_update_deactivate(self, api_url: str, cleanup_watchlist):
        entry = _create_entry(api_url)
        entry_id = entry.json()["id"]
        cleanup_watchlist(entry_id)

        resp = requests.put(
            f"{api_url}/api/v1/watchlist/{entry_id}",
            json={"is_active": False},
            timeout=10,
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    def test_update_nonexistent_returns_404(self, api_url: str):
        resp = requests.put(
            f"{api_url}/api/v1/watchlist/999999999",
            json={"name": "ghost"},
            timeout=10,
        )
        assert resp.status_code == 404


# ===========================================================================
# DELETE
# ===========================================================================

@pytest.mark.api
class TestDeleteWatchlist:
    """Tests for DELETE /api/v1/watchlist/{watchlist_id}"""

    @pytest.fixture(autouse=True)
    def _require_watchlist(self, api_url: str):
        if not _watchlist_available(api_url):
            pytest.skip("Watchlist API not available on this server")

    def test_delete_existing(self, api_url: str):
        entry = _create_entry(api_url)
        entry_id = entry.json()["id"]

        resp = requests.delete(f"{api_url}/api/v1/watchlist/{entry_id}", timeout=10)
        assert resp.status_code == 204

        # Verify it's gone
        get_resp = requests.get(f"{api_url}/api/v1/watchlist/{entry_id}", timeout=10)
        assert get_resp.status_code == 404

    def test_delete_nonexistent_returns_404(self, api_url: str):
        resp = requests.delete(f"{api_url}/api/v1/watchlist/999999999", timeout=10)
        assert resp.status_code == 404


# ===========================================================================
# ANALYSES & ALERTS (read-only listing endpoints)
# ===========================================================================

@pytest.mark.api
class TestListAnalyses:
    """Tests for GET /api/v1/watchlist/analysis"""

    @pytest.fixture(autouse=True)
    def _require_watchlist(self, api_url: str):
        if not _watchlist_available(api_url):
            pytest.skip("Watchlist API not available on this server")

    def test_list_analyses_returns_200(self, api_url: str):
        resp = requests.get(f"{api_url}/api/v1/watchlist/analysis", timeout=10)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_analyses_with_limit(self, api_url: str):
        resp = requests.get(
            f"{api_url}/api/v1/watchlist/analysis",
            params={"limit": 5},
            timeout=10,
        )
        assert resp.status_code == 200
        assert len(resp.json()) <= 5

    def test_list_analyses_filter_by_watchlist_id(self, api_url: str, cleanup_watchlist):
        entry = _create_entry(api_url)
        entry_id = entry.json()["id"]
        cleanup_watchlist(entry_id)

        resp = requests.get(
            f"{api_url}/api/v1/watchlist/analysis",
            params={"watchlist_id": entry_id},
            timeout=10,
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


@pytest.mark.api
class TestGetAlerts:
    """Tests for GET /api/v1/watchlist/alerts"""

    @pytest.fixture(autouse=True)
    def _require_watchlist(self, api_url: str):
        if not _watchlist_available(api_url):
            pytest.skip("Watchlist API not available on this server")

    def test_alerts_returns_200(self, api_url: str):
        resp = requests.get(f"{api_url}/api/v1/watchlist/alerts", timeout=10)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_alerts_with_limit(self, api_url: str):
        resp = requests.get(
            f"{api_url}/api/v1/watchlist/alerts",
            params={"limit": 10},
            timeout=10,
        )
        assert resp.status_code == 200
        assert len(resp.json()) <= 10


# ===========================================================================
# DETECT TURNING POINTS
# ===========================================================================

@pytest.mark.api
class TestDetectTurning:
    """Tests for POST /api/v1/watchlist/detect-turning"""

    @pytest.fixture(autouse=True)
    def _require_watchlist(self, api_url: str):
        if not _watchlist_available(api_url):
            pytest.skip("Watchlist API not available on this server")

    def test_signal_change_is_turning(self, api_url: str):
        """A BUY→SELL signal change should be detected as a turning point."""
        payload = {
            "current_result": {
                "signal": "SELL",
                "confidence": 0.85,
                "risk_level": "high",
            },
            "previous_result": {
                "signal": "BUY",
                "confidence": 0.70,
                "risk_level": "low",
            },
        }
        resp = requests.post(
            f"{api_url}/api/v1/watchlist/detect-turning",
            json=payload,
            timeout=10,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_turning"] is True
        assert body["importance_score"] >= 0.5
        assert "reason" in body

    def test_no_change_is_not_turning(self, api_url: str):
        """Identical signals should not be a turning point."""
        payload = {
            "current_result": {
                "signal": "HOLD",
                "confidence": 0.50,
                "risk_level": "medium",
            },
            "previous_result": {
                "signal": "HOLD",
                "confidence": 0.50,
                "risk_level": "medium",
            },
        }
        resp = requests.post(
            f"{api_url}/api/v1/watchlist/detect-turning",
            json=payload,
            timeout=10,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_turning"] is False

    def test_confidence_jump_with_config(self, api_url: str):
        """A large confidence jump with custom threshold triggers detection."""
        payload = {
            "current_result": {
                "signal": "HOLD",
                "confidence": 0.90,
                "risk_level": "medium",
            },
            "previous_result": {
                "signal": "HOLD",
                "confidence": 0.60,
                "risk_level": "medium",
            },
            "config": {"confidence_jump": 0.15},
        }
        resp = requests.post(
            f"{api_url}/api/v1/watchlist/detect-turning",
            json=payload,
            timeout=10,
        )
        assert resp.status_code == 200
        body = resp.json()
        # Confidence jumped 0.30 above threshold and >0.8 → turning
        assert body["is_turning"] is True

    def test_missing_body_returns_422(self, api_url: str):
        resp = requests.post(
            f"{api_url}/api/v1/watchlist/detect-turning",
            json={},
            timeout=10,
        )
        assert resp.status_code == 422


# ===========================================================================
# QUICK ANALYZE
# ===========================================================================

@pytest.mark.api
class TestQuickAnalyze:
    """Tests for POST /api/v1/watchlist/{watchlist_id}/quick-analyze"""

    @pytest.fixture(autouse=True)
    def _require_watchlist(self, api_url: str):
        if not _watchlist_available(api_url):
            pytest.skip("Watchlist API not available on this server")

    def test_quick_analyze_returns_202(self, api_url: str, cleanup_watchlist):
        entry = _create_entry(api_url)
        entry_id = entry.json()["id"]
        cleanup_watchlist(entry_id)

        resp = requests.post(
            f"{api_url}/api/v1/watchlist/{entry_id}/quick-analyze",
            timeout=30,
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["task_id"]
        assert body["status"] in {"PENDING", "RUNNING"}
        assert body["result"]["watchlist_id"] == entry_id
        assert body["result"]["analysis_type"] == "quick"

    def test_quick_analyze_nonexistent_returns_404(self, api_url: str):
        resp = requests.post(
            f"{api_url}/api/v1/watchlist/999999999/quick-analyze",
            timeout=10,
        )
        assert resp.status_code == 404


# ===========================================================================
# ANALYSIS HISTORY (K-line Signal Overlay)
# ===========================================================================

@pytest.mark.api
class TestAnalysisHistory:
    """Tests for GET /api/v1/watchlist/{id}/analysis-history"""

    @pytest.fixture(autouse=True)
    def _require_watchlist(self, api_url: str):
        if not _watchlist_available(api_url):
            pytest.skip("Watchlist API not available on this server")

    def test_analysis_history_returns_200(self, api_url: str, cleanup_watchlist):
        entry = _create_entry(api_url)
        entry_id = entry.json()["id"]
        cleanup_watchlist(entry_id)

        resp = requests.get(
            f"{api_url}/api/v1/watchlist/{entry_id}/analysis-history",
            timeout=10,
        )
        assert resp.status_code == 200
        body = resp.json()
        # API returns wrapped response with items list
        assert isinstance(body, dict)
        assert "items" in body
        assert "watchlist_id" in body
        assert "symbol" in body
        assert "total" in body
        assert "has_more" in body
        assert isinstance(body["items"], list)

    def test_analysis_history_respects_limit(self, api_url: str, cleanup_watchlist):
        entry = _create_entry(api_url, symbol="600036", name="招商银行")
        if entry.status_code != 201:
            pytest.skip("Unable to create watchlist entry for limit test")
        entry_id = entry.json()["id"]
        cleanup_watchlist(entry_id)

        resp = requests.get(
            f"{api_url}/api/v1/watchlist/{entry_id}/analysis-history",
            params={"limit": 2},
            timeout=10,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) <= 2

    def test_analysis_history_nonexistent_returns_404(self, api_url: str):
        resp = requests.get(
            f"{api_url}/api/v1/watchlist/999999999/analysis-history",
            timeout=10,
        )
        assert resp.status_code == 404


# ===========================================================================
# SCHEDULER STATUS
# ===========================================================================

@pytest.mark.api
class TestSchedulerStatus:
    """Tests for GET /api/v1/watchlist/scheduler/status"""

    @pytest.fixture(autouse=True)
    def _require_watchlist(self, api_url: str):
        if not _watchlist_available(api_url):
            pytest.skip("Watchlist API not available on this server")

    def test_scheduler_status_returns_200(self, api_url: str):
        resp = requests.get(f"{api_url}/api/v1/watchlist/scheduler/status", timeout=10)
        assert resp.status_code == 200
        body = resp.json()
        assert "is_running" in body
        assert "active_jobs" in body
        assert isinstance(body["is_running"], bool)
        assert isinstance(body["active_jobs"], int)
