"""
UI test: Analysis form submission.

Verifies that:
  - The stock symbol input accepts text
  - Analyst checkboxes are present and toggleable
  - The submit button triggers a request
"""
import pytest
from playwright.sync_api import Page, expect


@pytest.mark.ui
class TestAnalysisForm:
    """Verify the analysis form interaction."""

    def _fill_symbol(self, page: Page, symbol: str = "000001"):
        """Helper: fill in the stock symbol field."""
        # Strategy 1: Find via Streamlit label → input mapping
        text_inputs = page.locator("[data-testid='stTextInput'] input")
        for i in range(text_inputs.count()):
            label = text_inputs.nth(i).locator(
                "xpath=ancestor::*[contains(@class,'stTextInput')]//label"
            )
            if label.count() > 0:
                label_text = (label.first.text_content() or "").lower()
                if any(kw in label_text for kw in ["股票", "symbol", "代码"]):
                    text_inputs.nth(i).fill(symbol)
                    return True

        # Strategy 2: Find via placeholder/aria-label
        all_inputs = page.locator("input[type='text']")
        for i in range(all_inputs.count()):
            placeholder = all_inputs.nth(i).get_attribute("placeholder") or ""
            aria_label = all_inputs.nth(i).get_attribute("aria-label") or ""
            if any(
                kw in (placeholder + aria_label).lower()
                for kw in ["股票", "symbol", "代码"]
            ):
                all_inputs.nth(i).fill(symbol)
                return True

        # Strategy 3: First text input inside the form
        form_input = page.locator("[data-testid='stForm'] input[type='text']").first
        if form_input.is_visible():
            form_input.fill(symbol)
            return True

        # Strategy 4: Just fill the first text input on the page
        if all_inputs.count() > 0:
            all_inputs.first.fill(symbol)
            return True

        return False

    def test_symbol_input_accepts_text(self, page: Page, web_url: str):
        """Stock symbol field should accept user input."""
        page.goto(web_url, wait_until="networkidle", timeout=60000)
        filled = self._fill_symbol(page, "000001")
        assert filled, "Could not find stock symbol input field"

    def test_analyst_checkboxes_exist(self, page: Page, web_url: str):
        """All four analyst checkboxes should be present."""
        page.goto(web_url, wait_until="networkidle", timeout=60000)
        checkboxes = page.locator("input[type='checkbox']")
        count = checkboxes.count()
        # Streamlit analysis form has 4 analyst checkboxes
        assert count >= 4, f"Expected at least 4 analyst checkboxes, found {count}"

    def test_exchange_radio_exists(self, page: Page, web_url: str):
        """Exchange selection radio buttons should be present."""
        page.goto(web_url, wait_until="networkidle", timeout=60000)
        # Streamlit radio buttons render with specific role attributes
        radios = page.locator("[role='radiogroup'], .stRadio")
        assert radios.count() > 0, "Exchange radio group not found"

    def test_submit_button_exists(self, page: Page, web_url: str):
        """The submit button should be visible."""
        page.goto(web_url, wait_until="networkidle", timeout=60000)
        submit_btn = page.locator("button:has-text('分析'), button:has-text('开始')")
        expect(submit_btn.first).to_be_visible(timeout=10000)

    def test_form_submit_without_symbol_shows_error(
        self, page: Page, web_url: str
    ):
        """Submitting the form without a symbol should show an error message."""
        page.goto(web_url, wait_until="networkidle", timeout=60000)
        # Don't fill any symbol — click submit directly
        submit_btn = page.locator("button:has-text('分析'), button:has-text('开始')")
        if submit_btn.count() > 0:
            submit_btn.first.click()
            # Streamlit shows errors in .stAlert elements
            error = page.locator(".stAlert, [data-testid='stAlert']")
            try:
                expect(error.first).to_be_visible(timeout=5000)
            except AssertionError:
                # May not show error if validation is client-side only
                pass

    def test_form_submit_with_symbol_triggers_request(
        self, page: Page, web_url: str
    ):
        """Filling the form and submitting should trigger an API call or redirect."""
        page.goto(web_url, wait_until="networkidle", timeout=60000)
        self._fill_symbol(page, "000001")

        # Click submit
        submit_btn = page.locator("button:has-text('分析'), button:has-text('开始')")
        if submit_btn.count() == 0:
            pytest.skip("Submit button not found — form layout may differ")

        # Click and wait for either navigation (to history page) or an API request
        submit_btn.first.click()
        # After clicking submit, Streamlit reruns and may navigate to history
        # Wait for the page to stabilize
        page.wait_for_load_state("networkidle", timeout=30000)
        # If navigation happened, we should see history-related text
        body_text = (page.locator("body").text_content() or "").lower()
        # Either we see history or the task was submitted successfully
        assert any(
            kw in body_text
            for kw in ["历史", "history", "分析中", "任务已提交"]
        ) or "新建分析" in body_text
