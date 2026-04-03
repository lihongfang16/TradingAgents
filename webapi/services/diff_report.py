"""Diff Report Generator — compares two analysis tasks and produces a structured diff report.

Uses stdlib ``difflib`` only.  No LLM calls.
"""

from __future__ import annotations

import difflib
import re
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from webapi.models.database import AnalysisTask

# Maximum characters for each diff section text
_DIFF_MAX_CHARS = 500

# Maximum characters for old/new preview
_PREVIEW_MAX_CHARS = 200

# Keys in llm_streams that correspond to analyst-level outputs
_ANALYST_KEYS = [
    "market_analyst",
    "social_analyst",
    "news_analyst",
    "fundamentals_analyst",
]

# Keys for higher-level outputs (researcher / trader / manager)
_HIGH_LEVEL_KEYS = [
    "research_manager",
    "research_debate",
    "trader",
    "risk_debate",
    "portfolio_manager",
]

# All recognized stream keys
_ALL_STREAM_KEYS = _ANALYST_KEYS + _HIGH_LEVEL_KEYS

# Regex to extract a numeric price from text
_PRICE_RE = re.compile(r"(?:价格|price|当前价|最新价|收盘价|现价)[:\s：]*([\d.]+)", re.IGNORECASE)


class DiffReportGenerator:
    """Compare two completed analysis tasks and produce a structured diff.

    Usage::

        gen = DiffReportGenerator()
        report = gen.generate("task-a", "task-b", db_session)
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        task_id_1: str,
        task_id_2: str,
        db: Session,
    ) -> Dict[str, Any]:
        """Build a structured diff report between two analysis tasks.

        Parameters
        ----------
        task_id_1:
            The *earlier* (before) task ID.
        task_id_2:
            The *later* (after) task ID.
        db:
            SQLAlchemy session.

        Returns
        -------
        dict
            Structured report with keys ``analysts``, ``decision``,
            ``confidence``, ``timestamp_range``.
        """
        task_before = db.query(AnalysisTask).filter(AnalysisTask.task_id == task_id_1).first()
        task_after = db.query(AnalysisTask).filter(AnalysisTask.task_id == task_id_2).first()

        if task_before is None:
            raise ValueError(f"Task not found: {task_id_1}")
        if task_after is None:
            raise ValueError(f"Task not found: {task_id_2}")

        streams_before: Dict[str, str] = task_before.llm_streams or {}
        streams_after: Dict[str, str] = task_after.llm_streams or {}

        # ---------- analysts section ----------
        analysts_report: Dict[str, Any] = {}
        for key in _ALL_STREAM_KEYS:
            old_text = streams_before.get(key, "")
            new_text = streams_after.get(key, "")

            if not old_text and not new_text:
                # Neither task produced output for this agent — skip
                continue

            entry = self._diff_section(key, old_text, new_text)
            analysts_report[key] = entry

        # ---------- decision section ----------
        signal_before = self._extract_signal(task_before)
        signal_after = self._extract_signal(task_after)
        decision_report = {
            "signal_before": signal_before,
            "signal_after": signal_after,
            "signal_changed": signal_before != signal_after,
        }

        # ---------- confidence section ----------
        conf_before = task_before.confidence
        conf_after = task_after.confidence
        delta = None
        if conf_before is not None and conf_after is not None:
            delta = conf_after - conf_before
        confidence_report = {
            "before": conf_before,
            "after": conf_after,
            "delta": delta,
        }

        # ---------- timestamp range ----------
        ts_range = self._format_timestamp_range(task_before, task_after)

        return {
            "analysts": analysts_report,
            "decision": decision_report,
            "confidence": confidence_report,
            "timestamp_range": ts_range,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _diff_section(key: str, old_text: str, new_text: str) -> Dict[str, Any]:
        """Produce a diff entry for a single agent stream."""
        # Price extraction
        price_before = DiffReportGenerator._extract_price(old_text)
        price_after = DiffReportGenerator._extract_price(new_text)

        # Determine change type
        changed = False
        change_type = "unchanged"

        if old_text == new_text:
            change_type = "unchanged"
        elif not old_text and new_text:
            changed = True
            change_type = "added"
        elif old_text and not new_text:
            changed = True
            change_type = "removed"
        else:
            changed = True
            change_type = "content_changed"

        # Unified diff
        diff_summary = ""
        if changed and old_text and new_text:
            diff_lines = list(
                difflib.unified_diff(
                    old_text.splitlines(keepends=True),
                    new_text.splitlines(keepends=True),
                    fromfile=f"before/{key}",
                    tofile=f"after/{key}",
                    lineterm="",
                )
            )
            raw_diff = "\n".join(diff_lines)
            diff_summary = raw_diff[:_DIFF_MAX_CHARS] + ("..." if len(raw_diff) > _DIFF_MAX_CHARS else "")

        # Previews
        old_preview = ""
        new_preview = ""
        if old_text:
            old_preview = old_text[:_PREVIEW_MAX_CHARS] + ("..." if len(old_text) > _PREVIEW_MAX_CHARS else "")
        if new_text:
            new_preview = new_text[:_PREVIEW_MAX_CHARS] + ("..." if len(new_text) > _PREVIEW_MAX_CHARS else "")

        entry: Dict[str, Any] = {
            "changed": changed,
            "change_type": change_type,
            "old_preview": old_preview,
            "new_preview": new_preview,
        }

        # Price fields only when prices are present
        if price_before is not None:
            entry["price_before"] = price_before
        if price_after is not None:
            entry["price_after"] = price_after

        if diff_summary:
            entry["diff_summary"] = diff_summary

        return entry

    @staticmethod
    def _extract_price(text: str) -> Optional[float]:
        """Extract the first numeric price-like value from text."""
        if not text:
            return None
        match = _PRICE_RE.search(text[:1000])  # search first 1000 chars
        if match:
            try:
                return float(match.group(1))
            except (ValueError, IndexError):
                return None
        return None

    @staticmethod
    def _extract_signal(task: AnalysisTask) -> Optional[str]:
        """Extract the trading signal from a task.

        Priority: result JSON → decision column.
        """
        # From result JSON (llm_streams signal field)
        result = task.result
        if isinstance(result, dict):
            signal = result.get("signal")
            if signal:
                # signal could be a string or dict with "decision"
                if isinstance(signal, str):
                    return signal
                if isinstance(signal, dict):
                    return signal.get("decision")
        # Fallback to flat decision column
        return task.decision

    @staticmethod
    def _format_timestamp_range(task_before: AnalysisTask, task_after: AnalysisTask) -> str:
        """Format ``HH:MM → HH:MM`` from task timestamps."""
        def _fmt(dt: Optional[datetime]) -> str:
            if dt is None:
                return "??:??"
            return dt.strftime("%H:%M")

        return f"{_fmt(task_before.created_at)} → {_fmt(task_after.created_at)}"
