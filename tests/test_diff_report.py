"""Unit tests for webapi.services.diff_report.DiffReportGenerator"""

from __future__ import annotations

import unittest
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from webapi.services.diff_report import DiffReportGenerator


# ---------------------------------------------------------------------------
# Helpers — build lightweight AnalysisTask-like objects without touching DB
# ---------------------------------------------------------------------------

def _make_task(
    task_id: str,
    symbol: str = "000001",
    decision: Optional[str] = None,
    confidence: Optional[int] = None,
    llm_streams: Optional[Dict[str, str]] = None,
    result: Optional[Dict[str, Any]] = None,
    created_at: Optional[datetime] = None,
) -> MagicMock:
    """Create a mock AnalysisTask with the right attributes."""
    task = MagicMock()
    task.task_id = task_id
    task.symbol = symbol
    task.decision = decision
    task.confidence = confidence
    task.llm_streams = llm_streams or {}
    task.result = result or {}
    task.created_at = created_at or datetime(2026, 4, 2, 14, 30, 0)
    return task


def _make_db(*tasks: MagicMock) -> MagicMock:
    """Create a mock SQLAlchemy Session that returns tasks by task_id."""
    db = MagicMock()
    task_map = {t.task_id: t for t in tasks}

    def _query_side_effect(model):
        q = MagicMock()
        q.filter.side_effect = lambda *args: q
        q.first.side_effect = lambda: None
        # We'll override below using a custom approach
        return q

    # Actually we need a better approach: install per-call first() returns
    call_idx = [0]
    task_list = list(tasks)

    def _query(model):
        q = MagicMock()
        mock_filter = MagicMock()
        q.filter.return_value = mock_filter

        def _first():
            idx = call_idx[0]
            call_idx[0] += 1
            if idx < len(task_list):
                return task_list[idx]
            return None

        mock_filter.first.side_effect = _first
        return q

    db.query = MagicMock(side_effect=_query)
    return db


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_STREAMS_BEFORE: Dict[str, str] = {
    "market_analyst": (
        "## Market Analysis Report\n\n"
        "当前价格：4.03\n\n"
        "技术指标显示RSI为45，处于中性区域。"
        "MACD柱状图略有缩短，短期动能偏弱。\n\n"
        "成交量较前一交易日下降15%，市场观望情绪浓厚。"
        "20日均线位于4.10附近，股价在均线下方运行。"
    ),
    "social_analyst": (
        "## Sentiment Analysis\n\n"
        "社交媒体情绪得分为0.62，偏正面。"
        "投资者讨论热度中等，主要关注公司年报业绩。"
    ),
    "news_analyst": (
        "## News Analysis\n\n"
        "近期无重大新闻事件。行业整体平稳运行。"
    ),
    "fundamentals_analyst": (
        "## Fundamentals Report\n\n"
        "市盈率15.2，低于行业平均18.5。"
        "净资产收益率18.3%，现金流良好。"
    ),
    "research_debate": "### bull_history\n看多理由：估值低\n\n### bear_history\n看空理由：宏观不确定",
    "trader": "## Trader Plan\n建议持有，等待突破4.10阻力位。",
    "portfolio_manager": "## Final Decision\nHOLD，置信度75%。",
}

_STREAMS_AFTER: Dict[str, str] = {
    "market_analyst": (
        "## Market Analysis Report\n\n"
        "当前价格：4.15\n\n"
        "技术指标显示RSI为55，进入偏强区域。"
        "MACD金叉形成，短期动能增强。\n\n"
        "成交量较前一交易日增长22%，资金积极流入。"
        "5日均线向上穿越20日均线，形成金叉信号。"
    ),
    "social_analyst": (
        "## Sentiment Analysis\n\n"
        "社交媒体情绪得分为0.75，明显偏正面。"
        "投资者讨论热度上升，关注新产品发布。"
    ),
    "news_analyst": (
        "## News Analysis\n\n"
        "近期无重大新闻事件。行业整体平稳运行。"
    ),
    "fundamentals_analyst": (
        "## Fundamentals Report\n\n"
        "市盈率15.2，低于行业平均18.5。"
        "净资产收益率18.3%，现金流良好。"
    ),
    "research_debate": "### bull_history\n看多理由：估值低、技术突破\n\n### bear_history\n看空理由：宏观不确定",
    "trader": "## Trader Plan\n建议买入，突破4.10阻力位确认。",
    "portfolio_manager": "## Final Decision\nBUY，置信度88%。",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDiffReportGenerator(unittest.TestCase):
    """Test cases for DiffReportGenerator."""

    def setUp(self):
        self.gen = DiffReportGenerator()

    # ------------------------------------------------------------------
    # Test 1: generate diff between two completed tasks
    # ------------------------------------------------------------------
    def test_generate_diff_between_two_completed_tasks(self):
        """Full diff: two tasks with different data should produce a rich report."""
        task1 = _make_task(
            task_id="task-001",
            decision="HOLD",
            confidence=75,
            llm_streams=_STREAMS_BEFORE,
            result={"signal": "HOLD"},
            created_at=datetime(2026, 4, 2, 14, 30),
        )
        task2 = _make_task(
            task_id="task-002",
            decision="BUY",
            confidence=88,
            llm_streams=_STREAMS_AFTER,
            result={"signal": "BUY"},
            created_at=datetime(2026, 4, 2, 15, 45),
        )
        db = _make_db(task1, task2)

        report = self.gen.generate("task-001", "task-002", db)

        # Top-level structure
        self.assertIn("analysts", report)
        self.assertIn("decision", report)
        self.assertIn("confidence", report)
        self.assertIn("timestamp_range", report)

        # Timestamp range
        self.assertEqual(report["timestamp_range"], "14:30 → 15:45")

        # Decision
        self.assertEqual(report["decision"]["signal_before"], "HOLD")
        self.assertEqual(report["decision"]["signal_after"], "BUY")
        self.assertTrue(report["decision"]["signal_changed"])

        # Confidence
        self.assertEqual(report["confidence"]["before"], 75)
        self.assertEqual(report["confidence"]["after"], 88)
        self.assertEqual(report["confidence"]["delta"], 13)

        # Analysts — market_analyst should show change
        ma = report["analysts"]["market_analyst"]
        self.assertTrue(ma["changed"])
        self.assertEqual(ma["change_type"], "content_changed")
        self.assertAlmostEqual(ma["price_before"], 4.03)
        self.assertAlmostEqual(ma["price_after"], 4.15)
        self.assertIn("diff_summary", ma)
        self.assertTrue(len(ma["diff_summary"]) <= 500 + 3)  # 500 + "..."
        self.assertTrue(len(ma["old_preview"]) <= 200 + 3)
        self.assertTrue(len(ma["new_preview"]) <= 200 + 3)

        # news_analyst — identical content
        na = report["analysts"]["news_analyst"]
        self.assertFalse(na["changed"])
        self.assertEqual(na["change_type"], "unchanged")

        # fundamentals_analyst — identical content
        fa = report["analysts"]["fundamentals_analyst"]
        self.assertFalse(fa["changed"])
        self.assertEqual(fa["change_type"], "unchanged")

    # ------------------------------------------------------------------
    # Test 2: same task diff returns empty/minimal
    # ------------------------------------------------------------------
    def test_same_task_diff_returns_empty(self):
        """Comparing a task with itself should yield no changes."""
        task = _make_task(
            task_id="task-same",
            decision="HOLD",
            confidence=60,
            llm_streams=_STREAMS_BEFORE,
            result={"signal": "HOLD"},
            created_at=datetime(2026, 4, 2, 14, 0),
        )
        db = _make_db(task, task)

        report = self.gen.generate("task-same", "task-same", db)

        # Decision should not have changed
        self.assertFalse(report["decision"]["signal_changed"])

        # Confidence delta should be 0
        self.assertEqual(report["confidence"]["delta"], 0)

        # All analysts should be unchanged
        for _key, entry in report["analysts"].items():
            self.assertFalse(
                entry["changed"],
                f"Analyst {_key} should be unchanged when diffing same task",
            )

    # ------------------------------------------------------------------
    # Test 3: asymmetric analyst coverage
    # ------------------------------------------------------------------
    def test_asymmetric_analyst_coverage(self):
        """One task has 2 analysts, the other has 4."""
        streams_few: Dict[str, str] = {
            "market_analyst": "Market report for 000001. 当前价格：10.50",
            "fundamentals_analyst": "Fundamentals: PE 12.0",
        }
        streams_many: Dict[str, str] = {
            "market_analyst": "Market report for 000001. 当前价格：10.80",
            "social_analyst": "Sentiment score 0.8",
            "news_analyst": "Breaking news: earnings beat",
            "fundamentals_analyst": "Fundamentals: PE 12.0, ROE 20%",
        }

        task1 = _make_task(
            task_id="task-few",
            decision="HOLD",
            confidence=50,
            llm_streams=streams_few,
            created_at=datetime(2026, 4, 2, 10, 0),
        )
        task2 = _make_task(
            task_id="task-many",
            decision="BUY",
            confidence=70,
            llm_streams=streams_many,
            created_at=datetime(2026, 4, 2, 11, 0),
        )
        db = _make_db(task1, task2)

        report = self.gen.generate("task-few", "task-many", db)

        # market_analyst — present in both, content differs
        ma = report["analysts"]["market_analyst"]
        self.assertTrue(ma["changed"])
        self.assertEqual(ma["change_type"], "content_changed")
        self.assertAlmostEqual(ma["price_before"], 10.50)
        self.assertAlmostEqual(ma["price_after"], 10.80)

        # social_analyst — only in task2 (added)
        sa = report["analysts"]["social_analyst"]
        self.assertTrue(sa["changed"])
        self.assertEqual(sa["change_type"], "added")
        self.assertFalse(sa["old_preview"])  # no old text
        self.assertTrue(sa["new_preview"])

        # news_analyst — only in task2 (added)
        na = report["analysts"]["news_analyst"]
        self.assertTrue(na["changed"])
        self.assertEqual(na["change_type"], "added")

        # fundamentals_analyst — present in both, content differs
        fa = report["analysts"]["fundamentals_analyst"]
        self.assertTrue(fa["changed"])
        self.assertEqual(fa["change_type"], "content_changed")

        # Verify no unexpected keys
        for key in report["analysts"]:
            self.assertIn(key, streams_many.keys() | streams_few.keys())

    # ------------------------------------------------------------------
    # Test 4: task not found raises ValueError
    # ------------------------------------------------------------------
    def test_task_not_found_raises(self):
        """ValueError when a task_id does not exist."""
        db = _make_db()  # no tasks
        with self.assertRaises(ValueError):
            self.gen.generate("nonexistent-1", "nonexistent-2", db)

    # ------------------------------------------------------------------
    # Test 5: signal extracted from result dict (string signal)
    # ------------------------------------------------------------------
    def test_signal_from_result_string(self):
        """Signal is extracted from result['signal'] string."""
        task = _make_task(
            task_id="t1",
            result={"signal": "OVERWEIGHT"},
            decision=None,  # decision column is None
        )
        db = _make_db(task, task)
        report = self.gen.generate("t1", "t1", db)
        self.assertEqual(report["decision"]["signal_before"], "OVERWEIGHT")

    # ------------------------------------------------------------------
    # Test 6: signal extracted from result dict (dict signal)
    # ------------------------------------------------------------------
    def test_signal_from_result_dict(self):
        """Signal is extracted from result['signal']['decision'] dict."""
        task = _make_task(
            task_id="t2",
            result={"signal": {"decision": "SELL"}},
            decision="BUY",  # result takes priority
        )
        db = _make_db(task, task)
        report = self.gen.generate("t2", "t2", db)
        self.assertEqual(report["decision"]["signal_before"], "SELL")

    # ------------------------------------------------------------------
    # Test 7: diff truncation
    # ------------------------------------------------------------------
    def test_long_diff_truncated(self):
        """Diffs longer than 500 chars are truncated."""
        long_old = "Line " + "\n".join(f"Different line {i}" for i in range(200))
        long_new = "Line " + "\n".join(f"Changed line {i}" for i in range(200))

        task1 = _make_task(
            task_id="t-long-1",
            llm_streams={"market_analyst": long_old},
            decision="HOLD",
        )
        task2 = _make_task(
            task_id="t-long-2",
            llm_streams={"market_analyst": long_new},
            decision="BUY",
        )
        db = _make_db(task1, task2)
        report = self.gen.generate("t-long-1", "t-long-2", db)

        ds = report["analysts"]["market_analyst"]["diff_summary"]
        self.assertTrue(len(ds) <= 503)  # 500 + "..."
        self.assertTrue(ds.endswith("..."))

    # ------------------------------------------------------------------
    # Test 8: preview truncation
    # ------------------------------------------------------------------
    def test_preview_truncated(self):
        """Previews longer than 200 chars are truncated."""
        long_text = "X" * 500
        task1 = _make_task(
            task_id="t-prev-1",
            llm_streams={"market_analyst": long_text},
            decision="HOLD",
        )
        task2 = _make_task(
            task_id="t-prev-2",
            llm_streams={"market_analyst": "short"},
            decision="HOLD",
        )
        db = _make_db(task1, task2)
        report = self.gen.generate("t-prev-1", "t-prev-2", db)

        self.assertTrue(len(report["analysts"]["market_analyst"]["old_preview"]) <= 203)
        self.assertTrue(report["analysts"]["market_analyst"]["old_preview"].endswith("..."))

    # ------------------------------------------------------------------
    # Test 9: confidence with None values
    # ------------------------------------------------------------------
    def test_confidence_none(self):
        """When confidence is None, delta is None."""
        task1 = _make_task("t-c1", confidence=None)
        task2 = _make_task("t-c2", confidence=50)
        db = _make_db(task1, task2)
        report = self.gen.generate("t-c1", "t-c2", db)
        self.assertIsNone(report["confidence"]["delta"])

    # ------------------------------------------------------------------
    # Test 10: timestamp with None created_at
    # ------------------------------------------------------------------
    def test_timestamp_none_fallback(self):
        """Missing timestamps produce '??:?' fallback."""
        task1 = _make_task("t-ts1", created_at=None)
        task1.created_at = None  # override the default
        task2 = _make_task("t-ts2", created_at=None)
        task2.created_at = None  # override the default
        db = _make_db(task1, task2)
        report = self.gen.generate("t-ts1", "t-ts2", db)
        self.assertEqual(report["timestamp_range"], "??:?? → ??:??")


if __name__ == "__main__":
    unittest.main()
