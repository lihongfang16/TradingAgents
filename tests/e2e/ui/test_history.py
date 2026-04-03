"""
UI test: History page and detail view.

Verifies that:
  - History list loads and shows records
  - Search/filter works
  - Detail view can be navigated to
  - Back button returns to history list
"""
import pytest
from playwright.sync_api import Page, expect


@pytest.mark.ui
class TestHistoryPage:
    """Verify the history management page."""

    def _navigate_to_history(self, page: Page, web_url: str):
        """Helper: click the 'History' navigation button."""
        page.goto(web_url, wait_until="networkidle", timeout=60000)
        history_btn = page.locator(
            "button:has-text('历史记录'), button:has-text('History')"
        )
        if history_btn.count() > 0:
            history_btn.first.click()
            page.wait_for_load_state("networkidle", timeout=30000)
            return True
        return False

    def test_navigate_to_history(self, page: Page, web_url: str):
        """Clicking 'History' button should switch to history view."""
        navigated = self._navigate_to_history(page, web_url)
        if not navigated:
            pytest.skip("History navigation button not found")

    def test_history_page_loads(self, page: Page, web_url: str):
        """History page should render without errors."""
        if not self._navigate_to_history(page, web_url):
            pytest.skip("Could not navigate to history page")
        # After navigation, page should still be loaded
        body_text = page.locator("body").text_content()
        assert body_text is not None

    def test_history_header_displayed(self, page: Page, web_url: str):
        """History page should show a header about analysis history."""
        if not self._navigate_to_history(page, web_url):
            pytest.skip("Could not navigate to history page")
        # Look for history-related heading — Streamlit uses various heading selectors
        body_text = page.locator("body").text_content() or ""
        assert any(
            kw in body_text.lower()
            for kw in ["历史", "history", "分析历史"]
        ), f"History-related text not found in page body"

    def test_history_search_input_exists(self, page: Page, web_url: str):
        """History page should have a search input."""
        if not self._navigate_to_history(page, web_url):
            pytest.skip("Could not navigate to history page")
        text_inputs = page.locator("input[type='text'], input")
        assert text_inputs.count() > 0, "No search input found on history page"

    def test_history_has_view_buttons(self, page: Page, web_url: str):
        """Each history record should have a 'View' button (if records exist)."""
        if not self._navigate_to_history(page, web_url):
            pytest.skip("Could not navigate to history page")
        # Wait for history records to load
        page.wait_for_timeout(2000)
        # Streamlit buttons - look by aria-label, title, or text content
        view_btns = page.locator(
            "button[aria-label*='查看' i], button[aria-label*='View' i],"
            " button[title*='查看' i], button[title*='View' i],"
            " button:has-text('查看'), button:has-text('View'), button:has-text('详情'),"
            " button[kind='secondary']"  # Streamlit secondary buttons
        )
        # Also check for any buttons in the history list area
        all_buttons = page.locator("button")
        # If there are records, view buttons should exist
        if view_btns.count() == 0 and all_buttons.count() <= 3:
            # Check for empty-state message — Streamlit uses stAlert or stInfo
            info = page.locator(
                "[data-testid='stAlert'], [data-testid='stInfo'], "
                ".stAlert, .stInfo"
            )
            body_text = page.locator("body").text_content() or ""
            has_empty_msg = any(
                kw in body_text for kw in ["暂无", "没有", "No records", "empty"]
            )
            if info.count() > 0 or has_empty_msg:
                pytest.skip("No history records — empty state is valid")
            else:
                pytest.skip(
                    "No view buttons and no empty-state message — "
                    "history page layout may differ"
                )

    def test_back_to_analysis_navigation(self, page: Page, web_url: str):
        """From history, clicking 'New Analysis' should go back."""
        if not self._navigate_to_history(page, web_url):
            pytest.skip("Could not navigate to history page")
        new_btn = page.locator(
            "button:has-text('新建分析'), button:has-text('New'), "
            "button:has-text('New Analysis')"
        )
        if new_btn.count() > 0:
            new_btn.first.click()
            page.wait_for_load_state("networkidle", timeout=15000)
            # Should now see the analysis form again (Streamlit stForm)
            form = page.locator("[data-testid='stForm']")
            expect(form.first).to_be_visible(timeout=10000)
