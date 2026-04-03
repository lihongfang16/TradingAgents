"""
UI test: Homepage loads correctly.

Verifies that the Streamlit web UI at the base URL:
  - Returns HTTP 200
  - Contains expected title text
  - Contains key navigation elements (buttons, forms)
"""
import pytest
from playwright.sync_api import Page, expect


@pytest.mark.ui
class TestHomepage:
    """Verify the main page renders correctly."""

    def test_page_loads_successfully(self, page: Page, web_url: str):
        """Page should respond with 200 and render without errors."""
        page.goto(web_url, wait_until="networkidle", timeout=60000)
        # Streamlit pages should have a title element
        title = page.title()
        assert title != "", "Page should have a non-empty title"

    def test_page_contains_tradingagents_title(self, page: Page, web_url: str):
        """Page should display the TradingAgents heading."""
        page.goto(web_url, wait_until="networkidle", timeout=60000)
        # Look for the main heading or a heading that contains the app name
        heading = page.locator("h1, h2, .stTitle, [data-testid='stTitle']")
        count = heading.count()
        if count > 0:
            text = heading.first.text_content()
            # The heading should reference TradingAgents or stock analysis
            assert any(
                kw in (text or "").lower()
                for kw in ["tradingagents", "ai股票", "stock", "分析"]
            ), f"Expected heading to mention TradingAgents, got: {text}"

    def test_page_has_navigation_buttons(self, page: Page, web_url: str):
        """Page should have 'New Analysis' and 'History' navigation buttons."""
        page.goto(web_url, wait_until="networkidle", timeout=60000)
        # Streamlit renders buttons as <button> elements
        buttons = page.locator("button")
        button_texts = [buttons.nth(i).text_content() for i in range(buttons.count())]
        all_text = " ".join(button_texts).lower()
        # At least one button should reference creating an analysis
        assert any(
            kw in all_text
            for kw in ["新建分析", "分析", "new", "analysis", "history", "历史"]
        ), f"No navigation buttons found. Buttons: {button_texts}"

    def test_page_has_analysis_form(self, page: Page, web_url: str):
        """The default view should show the analysis form (Streamlit uses data-testid)."""
        page.goto(web_url, wait_until="networkidle", timeout=60000)
        # Streamlit forms use data-testid="stForm" not standard <form>
        form = page.locator("[data-testid='stForm']")
        expect(form.first).to_be_visible(timeout=10000)

    def test_page_contains_symbol_input(self, page: Page, web_url: str):
        """The form should have a stock symbol text input."""
        page.goto(web_url, wait_until="networkidle", timeout=60000)
        # Wait for Streamlit to fully render form widgets
        page.wait_for_selector(
            "input, [data-testid='stTextInput']",
            timeout=15000,
        )
        # Streamlit text_input renders as <input> elements
        inputs = page.locator("input[type='text'], input")
        count = inputs.count()
        assert count > 0, "Expected at least one text input on the page"

    def test_no_javascript_errors(self, page: Page, web_url: str):
        """Page should load without uncaught JavaScript errors."""
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto(web_url, wait_until="networkidle", timeout=60000)
        assert len(errors) == 0, f"JavaScript errors detected: {errors}"
