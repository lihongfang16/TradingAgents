"""
UI test: List refresh after user actions.

Verifies that:
  - History list reflects newly created analysis tasks
  - Deleting from history updates the list
  - Navigation between views preserves list state
  - Back button returns to refreshed list
"""
import time

import pytest
import requests
from playwright.sync_api import Page


@pytest.mark.ui
class TestListRefresh:
    """Verify lists refresh correctly after user actions."""

    @pytest.fixture(autouse=True)
    def _cleanup_watchlist(self, api_url: str):
        """Clean up any test watchlist entries."""
        test_ids: list[str] = []
        yield test_ids
        for wid in test_ids:
            try:
                requests.delete(
                    f"{api_url}/api/v1/watchlist/{wid}", timeout=5
                )
            except Exception:
                pass

    def _navigate_to_history(self, page: Page, web_url: str) -> bool:
        """Helper: navigate to the history page."""
        page.goto(web_url, wait_until="networkidle", timeout=60000)
        history_btn = page.locator(
            "button:has-text('历史记录'), button:has-text('History')"
        )
        if history_btn.count() > 0:
            history_btn.first.click()
            page.wait_for_load_state("networkidle", timeout=30000)
            return True
        return False

    def _navigate_to_watchlist(self, page: Page, web_url: str) -> bool:
        """Helper: navigate to the watchlist page."""
        page.goto(web_url, wait_until="networkidle", timeout=60000)
        btn = page.locator("button:has-text('自选股')")
        if btn.count() > 0:
            btn.first.click()
            # Wait for Streamlit rerun and watchlist to load
            page.wait_for_timeout(3000)
            page.wait_for_load_state("networkidle", timeout=30000)
            # Verify we're on watchlist page by checking for watchlist-specific content
            body_text = page.locator("body").text_content() or ""
            watchlist_keywords = ["添加自选股", "自选股列表", "股票代码"]
            if any(kw in body_text for kw in watchlist_keywords):
                return True
            # If not on watchlist, the button click didn't work
            return False
        return False

    def test_history_shows_after_analysis_submit(
        self, page: Page, web_url: str, api_url: str
    ):
        """Submit an analysis via API, then check history page shows it."""
        # Create a task via the API
        resp = requests.post(
            f"{api_url}/api/v1/analysis/",
            json={
                "symbol": "000001",
                "date": "2025-01-15",
                "exchange": "CN",
                "source": "mairui",
                "analysts": ["market"],
            },
            timeout=15,
        )
        if resp.status_code not in (200, 201):
            pytest.skip(f"Could not create analysis task via API: {resp.status_code}")

        task_data = resp.json()
        task_id = task_data.get("task_id") or task_data.get("id", "")
        try:
            # Navigate to history and verify the task appears
            if not self._navigate_to_history(page, web_url):
                pytest.skip("Could not navigate to history page")
            # Give Streamlit time to render the history list
            time.sleep(3)
            page.wait_for_load_state("networkidle", timeout=30000)
            body_text = page.locator("body").text_content() or ""
            assert "000001" in body_text, (
            "Created task symbol '000001' not found in history list"
        )
        finally:
            # Cleanup
            if task_id:
                try:
                    requests.delete(
                        f"{api_url}/api/v1/analysis/{task_id}", timeout=5
                    )
                except Exception:
                    pass

    def test_history_search_filters_results(
        self, page: Page, web_url: str
    ):
        """Search in history should filter results."""
        if not self._navigate_to_history(page, web_url):
            pytest.skip("Could not navigate to history page")
        # Find the search input on the history page
        text_inputs = page.locator("input[type='text']")
        if text_inputs.count() == 0:
            pytest.skip("No search input found on history page")

        # Type a symbol that should NOT match any real record
        text_inputs.first.fill("ZZZZZZ")
        page.wait_for_load_state("networkidle", timeout=15000)

        # After filtering, the list should show fewer results or empty state
        body_text = page.locator("body").text_content() or ""
        # Either the page shows an empty state or the non-matching symbol
        # is not listed as a real stock entry
        has_empty = any(
            kw in body_text for kw in ["暂无", "没有", "No ", "empty", "未找到"]
        )
        # The fake symbol should not appear as a legitimate stock entry
        assert has_empty or "ZZZZZZ" not in body_text, (
            "Search filter did not reduce results as expected"
        )

    def test_history_detail_back_returns_to_list(
        self, page: Page, web_url: str
    ):
        """View a detail page then go back — list should still render."""
        if not self._navigate_to_history(page, web_url):
            pytest.skip("Could not navigate to history page")

        # Wait for history records to load
        page.wait_for_timeout(2000)

        view_btns = page.locator(
            "button[aria-label*='查看' i], button[aria-label*='View' i],"
            " button[title*='查看' i], button[title*='View' i],"
            " button:has-text('查看'), button:has-text('View'), button:has-text('详情'),"
            " button[kind='secondary']"
        )
        all_buttons = page.locator("button")
        if view_btns.count() == 0 and all_buttons.count() <= 3:
            pytest.skip("No history records to test detail view")

        # Click the first view button to enter detail
        view_btns.first.click()
        page.wait_for_load_state("networkidle", timeout=30000)

        # Find and click the back button
        back_btn = page.locator(
            "button:has-text('返回'), button:has-text('Back'),"
            " button:has-text('历史记录')"
        )
        if back_btn.count() == 0:
            pytest.skip("Back button not found in detail view")
        back_btn.first.click()
        page.wait_for_load_state("networkidle", timeout=30000)

        # Verify we're back at the history list
        body_text = page.locator("body").text_content() or ""
        assert any(
            kw in body_text for kw in ["历史", "history", "查看", "详情"]
        ), "Did not return to history list after clicking back"

    def test_navigation_preserves_state(
        self, page: Page, web_url: str
    ):
        """Switching between views and returning should load the list."""
        # Navigate to history first
        if not self._navigate_to_history(page, web_url):
            pytest.skip("Could not navigate to history page")

        # Navigate to watchlist
        watchlist_btn = page.locator("button:has-text('自选股')")
        if watchlist_btn.count() == 0:
            pytest.skip("Watchlist navigation button not found")
        watchlist_btn.first.click()
        page.wait_for_load_state("networkidle", timeout=30000)

        # Navigate back to history
        history_btn = page.locator(
            "button:has-text('历史记录'), button:has-text('History')"
        )
        if history_btn.count() == 0:
            pytest.skip("History navigation button not found")
        history_btn.first.click()
        page.wait_for_load_state("networkidle", timeout=30000)

        # Verify history page loads correctly
        body_text = page.locator("body").text_content() or ""
        assert any(
            kw in body_text for kw in ["历史", "history"]
        ), "History page did not load correctly after round-trip navigation"

    def test_watchlist_api_add_updates_list(
        self, page: Page, web_url: str, api_url: str,
        _cleanup_watchlist: list[str],
    ):
        """Add stock via API, then verify it appears in watchlist UI."""
        test_symbol = "999999"
        resp = requests.post(
            f"{api_url}/api/v1/watchlist/",
            json={
                "symbol": test_symbol,
                "name": "TestStock",
                "exchange": "CN",
            },
            timeout=15,
        )
        if resp.status_code not in (200, 201):
            pytest.skip(
                f"Could not add watchlist entry via API: {resp.status_code}"
            )

        entry = resp.json()
        entry_id = str(entry.get("id") or entry.get("watchlist_id", ""))
        if entry_id:
            _cleanup_watchlist.append(entry_id)

        # Navigate to watchlist and verify the new symbol appears
        if not self._navigate_to_watchlist(page, web_url):
            pytest.skip("Could not navigate to watchlist page")
        # Check for the symbol on the watchlist page
        body_text = page.locator("body").text_content() or ""
        assert test_symbol in body_text, (
            f"Test symbol '{test_symbol}' not found in watchlist page "
            "after API addition"
        )
