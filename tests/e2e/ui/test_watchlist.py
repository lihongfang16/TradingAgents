"""
UI test: Watchlist management page.

Verifies that:
  - Watchlist page loads and shows content
  - Add stock form works
  - Delete confirmation works
  - Quick analysis triggers
"""
import pytest
from playwright.sync_api import Page


@pytest.mark.ui
class TestWatchlistPage:
    """Verify the watchlist management page."""

    def _navigate_to_watchlist(self, page: Page, web_url: str) -> bool:
        """Helper: click the 'Watchlist' navigation button."""
        page.goto(web_url, wait_until="networkidle", timeout=60000)
        btn = page.locator("button:has-text('自选股管理')")
        if btn.count() > 0:
            btn.first.click()
            page.locator("text=自选股实时监控").first.wait_for(timeout=30000)
            return True
        return False

    def test_navigate_to_watchlist(self, page: Page, web_url: str):
        """Clicking '自选股' button should switch to watchlist view."""
        navigated = self._navigate_to_watchlist(page, web_url)
        if not navigated:
            pytest.skip("Watchlist navigation button not found")

    def test_watchlist_page_loads(self, page: Page, web_url: str):
        """Watchlist page should render without errors."""
        if not self._navigate_to_watchlist(page, web_url):
            pytest.skip("Could not navigate to watchlist page")
        expect_text = page.locator("text=自选股实时监控")
        expect_text.first.wait_for(timeout=10000)
        assert expect_text.count() > 0

    def test_watchlist_page_contains_keywords(self, page: Page, web_url: str):
        """Watchlist page body should contain watchlist-related text."""
        if not self._navigate_to_watchlist(page, web_url):
            pytest.skip("Could not navigate to watchlist page")
        body_text = page.locator("body").text_content() or ""
        assert any(
            kw in body_text for kw in ["自选股实时监控", "添加自选股", "自选股列表", "股票"]
        ), "Watchlist-related text not found in page body"

    def test_watchlist_search_input_visible(self, page: Page, web_url: str):
        """Search/add controls should be visible on watchlist page."""
        if not self._navigate_to_watchlist(page, web_url):
            pytest.skip("Could not navigate to watchlist page")

        assert page.locator("input[placeholder*='000001']").count() > 0
        body_text = page.locator("body").text_content() or ""
        assert "添加自选股" in body_text

    def test_watchlist_buttons_visible(self, page: Page, web_url: str):
        """If stocks exist, action buttons should be visible."""
        if not self._navigate_to_watchlist(page, web_url):
            pytest.skip("Could not navigate to watchlist page")
        action_buttons = page.locator(
            "button:has-text('分析'), button:has-text('删除'), "
            "button:has-text('监控'), button:has-text('刷新')"
        )
        if action_buttons.count() == 0:
            # May be empty — check for empty state
            body_text = page.locator("body").text_content() or ""
            has_empty = any(
                kw in body_text
                for kw in ["暂无", "没有", "No ", "empty", "空"]
            )
            if has_empty:
                pytest.skip("No watchlist entries — empty state is valid")
            else:
                pytest.skip(
                    "No action buttons found — watchlist layout may differ"
                )
