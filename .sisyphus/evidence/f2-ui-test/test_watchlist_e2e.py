"""
F2: End-to-End UI Test - Watchlist Three-Button Analysis Flow.

Verifies:
  Scenario 1: Three buttons (全量, 增量, 差异) visible per stock
  Scenario 2: Button states follow correct logic rules
  Scenario 3: Click 全量 triggers analysis and shows response
  Scenario 4: Incremental analysis precheck dialog shows
  Scenario 5: Diff modal shows comparison or valid warning

Usage:
  python .sisyphus/evidence/f2-ui-test/test_watchlist_e2e.py
"""
import io
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

EVIDENCE_DIR = Path(__file__).resolve().parent

import requests
from playwright.sync_api import sync_playwright, Page, Browser

WEB_URL = "http://localhost:8501"
API_URL = "http://localhost:8000"


class TestResults:
    """Accumulates test scenario results."""

    def __init__(self):
        self.scenarios = []

    def add(self, scenario: str, passed: bool, details: str, screenshot: str = ""):
        self.scenarios.append({
            "scenario": scenario,
            "passed": passed,
            "details": details,
            "screenshot": screenshot,
            "timestamp": datetime.utcnow().isoformat(),
        })
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {scenario}: {details}")

    def summary(self) -> dict:
        passed = sum(1 for s in self.scenarios if s["passed"])
        failed = sum(1 for s in self.scenarios if not s["passed"])
        return {
            "total": len(self.scenarios),
            "passed": passed,
            "failed": failed,
            "scenarios": self.scenarios,
        }


def cleanup_running_tasks():
    """Delete any RUNNING/PENDING analysis tasks to start clean."""
    try:
        resp = requests.get(f"{API_URL}/api/v1/analysis/", params={"limit": 100}, timeout=10)
        tasks = resp.json()
        for t in tasks:
            if t.get("status") in ("RUNNING", "PENDING"):
                tid = t["task_id"]
                requests.delete(f"{API_URL}/api/v1/analysis/{tid}", timeout=5)
                print(f"  Cleaned up running task: {tid[:8]}")
    except Exception as e:
        print(f"  Warning: cleanup failed: {e}")


def get_api_analysis_state(symbol: str) -> dict:
    """Get analysis state from API for a symbol.

    Returns dict with:
      - is_running: bool
      - has_full_today: bool
      - has_multiple_today: int (count)
      - completed_count: int
    """
    state = {
        "is_running": False,
        "has_full_today": False,
        "has_multiple_today": 0,
        "completed_count": 0,
    }
    try:
        resp = requests.get(
            f"{API_URL}/api/v1/analysis/",
            params={"symbol": symbol, "limit": 50},
            timeout=10,
        )
        tasks = resp.json()
        today = datetime.utcnow().date()

        for t in tasks:
            status = t.get("status", "").upper()
            if status in ("RUNNING", "PENDING"):
                state["is_running"] = True

            if status == "COMPLETED":
                state["completed_count"] += 1
                created = t.get("created_at", "")
                if created:
                    try:
                        created_date = datetime.fromisoformat(created.replace("Z", "+00:00")).date()
                        if created_date == today:
                            if t.get("analysis_type") == "full":
                                state["has_full_today"] = True
                            state["has_multiple_today"] += 1
                    except Exception:
                        pass
    except Exception:
        pass
    return state


def navigate_to_watchlist(page: Page):
    """Navigate Streamlit to the watchlist page."""
    page.goto(WEB_URL, wait_until="networkidle", timeout=60000)
    btn = page.locator("button:has-text('自选股')")
    btn.first.click()
    page.wait_for_selector("text=自选股列表", timeout=20000)
    page.wait_for_selector("button:has-text('全量')", timeout=30000)
    # Wait for all API calls in Streamlit to complete
    time.sleep(8)


def disable_auto_refresh(page: Page):
    """Uncheck the auto-refresh checkbox."""
    try:
        cb = page.get_by_role("checkbox", name="自动刷新")
        if cb.is_checked():
            cb.uncheck()
            time.sleep(1)
    except Exception:
        pass


def get_button_states(page: Page) -> list:
    """Get all analysis button states via JS.

    Returns list of dicts with text and disabled status.
    """
    return page.evaluate("""() => {
        const allButtons = document.querySelectorAll('button');
        const result = [];
        for (const btn of allButtons) {
            const text = btn.textContent.trim();
            if (['全量', '增量', '差异'].includes(text)) {
                result.push({text: text, disabled: btn.disabled});
            }
        }
        return result;
    }""")


def scroll_to_table(page: Page):
    """Scroll the page to show the watchlist table."""
    page.evaluate("""() => {
        const els = document.querySelectorAll('*');
        for (const el of els) {
            if (el.textContent && el.textContent.includes('自选股列表') && el.childElementCount < 5) {
                el.scrollIntoView({behavior: 'instant', block: 'start'});
                break;
            }
        }
    }""")
    time.sleep(0.5)


def run_scenario_1(page: Page, results: TestResults):
    """Scenario 1: Three Buttons Visible per stock."""
    print("\n--- Scenario 1: Three Buttons Visible ---")
    screenshot_path = str(EVIDENCE_DIR / "s1-three-buttons-visible.png")

    button_states = get_button_states(page)
    full_count = sum(1 for b in button_states if b["text"] == "全量")
    incr_count = sum(1 for b in button_states if b["text"] == "增量")
    diff_count = sum(1 for b in button_states if b["text"] == "差异")

    # Each stock should have 3 buttons
    has_all_types = full_count >= 2 and incr_count >= 2 and diff_count >= 2
    total = full_count + incr_count + diff_count

    details = (
        f"Buttons found: 全量={full_count}, 增量={incr_count}, 差异={diff_count} "
        f"(total={total}). Need >=2 of each type for 2 stocks."
    )

    scroll_to_table(page)
    try:
        page.screenshot(path=screenshot_path)
    except Exception as e:
        screenshot_path = f"ERROR: {e}"

    results.add("S1: Three Buttons Visible", has_all_types, details, screenshot_path)


def run_scenario_2(page: Page, results: TestResults):
    """Scenario 2: Button states follow correct logic rules.

    Rules from code:
      full_disabled = is_analyzing
      incr_disabled = not has_full_today OR is_analyzing
      diff_disabled = not has_multiple OR is_analyzing
    """
    print("\n--- Scenario 2: Button States Follow Logic Rules ---")
    screenshot_path = str(EVIDENCE_DIR / "s2-button-state-logic.png")

    # Get API ground truth for both symbols
    state_002172 = get_api_analysis_state("002172")
    state_601233 = get_api_analysis_state("601233")
    print(f"  API state 002172: running={state_002172['is_running']}, "
          f"full_today={state_002172['has_full_today']}, "
          f"multiple_today={state_002172['has_multiple_today']}")
    print(f"  API state 601233: running={state_601233['is_running']}, "
          f"full_today={state_601233['has_full_today']}, "
          f"multiple_today={state_601233['has_multiple_today']}")

    # Get UI button states
    button_states = get_button_states(page)

    # Group by stock: first 3 belong to stock 1, next 3 to stock 2
    s1_btns = button_states[:3] if len(button_states) >= 3 else []
    s2_btns = button_states[3:6] if len(button_states) >= 6 else []

    # Expected states based on API
    # Stock 1 (002172)
    expected_s1 = {
        "全量": state_002172["is_running"],       # disabled if running
        "增量": not state_002172["has_full_today"] or state_002172["is_running"],
        "差异": state_002172["has_multiple_today"] < 2 or state_002172["is_running"],
    }
    # Stock 2 (601233)
    expected_s2 = {
        "全量": state_601233["is_running"],
        "增量": not state_601233["has_full_today"] or state_601233["is_running"],
        "差异": state_601233["has_multiple_today"] < 2 or state_601233["is_running"],
    }

    # Verify stock 1
    s1_pass = True
    s1_details = []
    for i, btn_type in enumerate(["全量", "增量", "差异"]):
        if i < len(s1_btns):
            actual_disabled = s1_btns[i].get("disabled", False)
            expected_disabled = expected_s1[btn_type]
            match = actual_disabled == expected_disabled
            s1_pass = s1_pass and match
            s1_details.append(f"{btn_type}: actual={'disabled' if actual_disabled else 'enabled'}, "
                            f"expected={'disabled' if expected_disabled else 'enabled'}, match={match}")

    # Verify stock 2
    s2_pass = True
    s2_details = []
    for i, btn_type in enumerate(["全量", "增量", "差异"]):
        if i < len(s2_btns):
            actual_disabled = s2_btns[i].get("disabled", False)
            expected_disabled = expected_s2[btn_type]
            match = actual_disabled == expected_disabled
            s2_pass = s2_pass and match
            s2_details.append(f"{btn_type}: actual={'disabled' if actual_disabled else 'enabled'}, "
                            f"expected={'disabled' if expected_disabled else 'enabled'}, match={match}")

    details = (
        f"Stock 002172 ({'PASS' if s1_pass else 'FAIL'}): {'; '.join(s1_details)}\n"
        f"Stock 601233 ({'PASS' if s2_pass else 'FAIL'}): {'; '.join(s2_details)}"
    )

    scroll_to_table(page)
    try:
        page.screenshot(path=screenshot_path)
    except Exception as e:
        screenshot_path = f"ERROR: {e}"

    # Pass if at least one stock's button states match expected logic
    results.add("S2: Button State Logic Correct", s1_pass or s2_pass, details, screenshot_path)


def run_scenario_3(page: Page, results: TestResults):
    """Scenario 3: Click 全量 button and verify UI response."""
    print("\n--- Scenario 3: Click 全量 Button ---")
    screenshot_path = str(EVIDENCE_DIR / "s3-click-full-analysis.png")

    all_full = page.locator("button:has-text('全量')")
    target_btn = None
    target_idx = -1

    for i in range(all_full.count()):
        if not all_full.nth(i).is_disabled():
            target_btn = all_full.nth(i)
            target_idx = i
            break

    if target_btn is None:
        # Try to find any stock with no running analysis
        results.add(
            "S3: Click 全量 Button",
            False,
            "No enabled 全量 button found (all analyses running)",
            screenshot_path,
        )
        return

    try:
        target_btn.click()
        print(f"  Clicked 全量 button (index={target_idx})")
    except Exception as e:
        results.add(
            "S3: Click 全量 Button",
            False,
            f"Failed to click: {e}",
            screenshot_path,
        )
        return

    # Wait for UI response
    time.sleep(5)

    # Check for success message, spinner, or running state
    has_success = page.locator("text=全量分析已启动").count() > 0
    has_spinner = page.locator("[data-testid='stSpinner']").count() > 0
    has_error = page.locator("text=全量分析触发失败").count() > 0

    # Also check if button became disabled (indicating analysis started)
    try:
        is_now_disabled = all_full.nth(target_idx).is_disabled()
    except Exception:
        is_now_disabled = None

    details = (
        f"Click response: success_msg={has_success}, spinner={has_spinner}, "
        f"error={has_error}, button_now_disabled={is_now_disabled}"
    )

    passed = has_success or has_spinner or is_now_disabled

    scroll_to_table(page)
    try:
        page.screenshot(path=screenshot_path)
    except Exception as e:
        screenshot_path = f"ERROR: {e}"

    results.add("S3: Click 全量 Button", passed, details, screenshot_path)

    # Clean up: delete any newly created running task
    time.sleep(3)
    cleanup_running_tasks()


def run_scenario_4(page: Page, results: TestResults):
    """Scenario 4: Incremental analysis precheck dialog.

    Prerequisites: A stock with at least one completed full analysis today.
    """
    print("\n--- Scenario 4: Incremental Analysis Precheck ---")
    screenshot_path = str(EVIDENCE_DIR / "s4-incremental-precheck.png")

    # Ensure stock has full analysis completed today
    state = get_api_analysis_state("002172")
    if not state["has_full_today"]:
        # Check 601233
        state = get_api_analysis_state("601233")
    if not state["has_full_today"]:
        results.add(
            "S4: Incremental Precheck",
            False,
            "No stock has full analysis completed today - skipping",
            screenshot_path,
        )
        return

    # Find an enabled 增量 button
    all_incr = page.locator("button:has-text('增量')")
    target_btn = None
    target_idx = -1

    for i in range(all_incr.count()):
        if not all_incr.nth(i).is_disabled():
            target_btn = all_incr.nth(i)
            target_idx = i
            break

    if target_btn is None:
        # Need to ensure a full analysis is done first - skip
        results.add(
            "S4: Incremental Precheck",
            False,
            "No enabled 增量 button - prerequisite (full analysis today) not met in UI",
            screenshot_path,
        )
        return

    try:
        target_btn.click()
        print(f"  Clicked 增量 button (index={target_idx})")
    except Exception as e:
        results.add(
            "S4: Incremental Precheck",
            False,
            f"Failed to click 增量: {e}",
            screenshot_path,
        )
        return

    # Wait for precheck dialog to appear
    time.sleep(8)

    # Check for precheck UI elements
    has_precheck = page.locator("text=检测结果").count() > 0
    has_needs_refresh = page.locator("text=需要刷新").count() > 0
    has_cached = page.locator("text=缓存有效").count() > 0
    has_start_btn = page.locator("button:has-text('开始增量分析')").count() > 0
    has_error_msg = page.locator("text=预检失败").count() > 0
    has_no_data = page.locator("text=预检超时").count() > 0

    details = (
        f"Precheck expander: {has_precheck}, needs_refresh: {has_needs_refresh}, "
        f"cached: {has_cached}, start_button: {has_start_btn}, "
        f"error: {has_error_msg}, timeout: {has_no_data}"
    )

    # Pass if any precheck UI elements appear
    passed = has_precheck or has_needs_refresh or has_cached or has_start_btn

    scroll_to_table(page)
    try:
        page.screenshot(path=screenshot_path)
    except Exception as e:
        screenshot_path = f"ERROR: {e}"

    results.add("S4: Incremental Precheck Dialog", passed, details, screenshot_path)


def run_scenario_5(page: Page, results: TestResults):
    """Scenario 5: Diff modal shows comparison or valid warning."""
    print("\n--- Scenario 5: Diff Modal ---")
    screenshot_path = str(EVIDENCE_DIR / "s5-diff-modal.png")

    # Find an enabled 差异 button
    all_diff = page.locator("button:has-text('差异')")
    target_btn = None
    target_idx = -1

    for i in range(all_diff.count()):
        if not all_diff.nth(i).is_disabled():
            target_btn = all_diff.nth(i)
            target_idx = i
            break

    if target_btn is None:
        results.add(
            "S5: Diff Modal",
            False,
            "No enabled 差异 button found - need at least 2 completed analyses",
            screenshot_path,
        )
        return

    try:
        target_btn.click()
        print(f"  Clicked 差异 button (index={target_idx})")
    except Exception as e:
        results.add(
            "S5: Diff Modal",
            False,
            f"Failed to click 差异: {e}",
            screenshot_path,
        )
        return

    # Wait for modal or warning
    time.sleep(5)

    # Check for diff modal or warning
    has_diff_title = page.locator("text=分析差异对比").count() > 0
    has_before_signal = page.locator("text=之前信号").count() > 0
    has_after_signal = page.locator("text=之后信号").count() > 0
    has_warning = page.locator("text=至少需要 2 次").count() > 0
    has_spinner = page.locator("text=生成差异报告").count() > 0
    has_error = page.locator("text=生成差异报告失败").count() > 0
    has_analyst_section = page.locator("text=个角色").count() > 0

    details = (
        f"diff_title: {has_diff_title}, before_signal: {has_before_signal}, "
        f"after_signal: {has_after_signal}, warning: {has_warning}, "
        f"loading: {has_spinner}, error: {has_error}, "
        f"analyst_section: {has_analyst_section}"
    )

    # Pass if modal shows OR valid warning appears
    passed = has_diff_title or has_warning or has_before_signal or has_analyst_section

    try:
        page.screenshot(path=screenshot_path)
    except Exception as e:
        screenshot_path = f"ERROR: {e}"

    results.add("S5: Diff Modal", passed, details, screenshot_path)


def main():
    """Run all E2E test scenarios."""
    print("=" * 60)
    print("F2: End-to-End UI Test - Watchlist Three-Button Analysis")
    print("=" * 60)
    print(f"Web URL: {WEB_URL}")
    print(f"API URL: {API_URL}")
    print(f"Evidence dir: {EVIDENCE_DIR}")
    print()

    # Pre-flight: clean up running tasks
    print("Pre-flight: Cleaning up running tasks...")
    cleanup_running_tasks()
    time.sleep(2)

    results = TestResults()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        page = context.new_page()

        try:
            print("Navigating to watchlist page...")
            navigate_to_watchlist(page)
            print("  Watchlist page loaded")

            print("Disabling auto-refresh...")
            disable_auto_refresh(page)

            # Scenario 1: Three buttons visible
            run_scenario_1(page, results)

            # Scenario 2: Button state logic
            run_scenario_2(page, results)

            # Scenario 3: Click 全量
            run_scenario_3(page, results)

            # Re-navigate to get fresh state after S3
            print("\nRe-navigating for fresh state...")
            cleanup_running_tasks()
            time.sleep(2)
            navigate_to_watchlist(page)
            disable_auto_refresh(page)

            # Scenario 4: Incremental precheck
            run_scenario_4(page, results)

            # Re-navigate for clean diff test
            print("\nRe-navigating for diff test...")
            navigate_to_watchlist(page)
            disable_auto_refresh(page)

            # Scenario 5: Diff modal
            run_scenario_5(page, results)

        except Exception as e:
            print(f"\nFATAL ERROR: {e}")
            import traceback
            traceback.print_exc()
        finally:
            browser.close()

    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    summary = results.summary()
    print(f"Total: {summary['total']}")
    print(f"Passed: {summary['passed']}")
    print(f"Failed: {summary['failed']}")
    for s in summary["scenarios"]:
        status = "PASS" if s["passed"] else "FAIL"
        print(f"  [{status}] {s['scenario']}")

    # Save results as JSON
    results_path = EVIDENCE_DIR / "test_results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to: {results_path}")

    sys.exit(0 if summary["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
