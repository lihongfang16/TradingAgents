"""Robust parser for Portfolio Manager's final_trade_decision output.

Tries three strategies in order:
1. Extract JSON from markdown code block (```json ... ```)
2. Extract raw JSON object from text
3. Regex fallback for individual fields

All extracted data is normalized via ``normalize_signal`` from signal_extractor.
"""

import json
import re
from typing import Any, Dict, Optional

# Chinese + English rating patterns → standardized rating
_RATING_PATTERNS: list[tuple[str, str]] = [
    # Explicit 评级 lines with optional markdown bold
    (r'评级[：:]\s*\*{0,2}(买入|BUY)\*{0,2}', "BUY"),
    (r'评级[：:]\s*\*{0,2}(增持|OVERWEIGHT)\*{0,2}', "OVERWEIGHT"),
    (r'评级[：:]\s*\*{0,2}(持有|HOLD)\*{0,2}', "HOLD"),
    (r'评级[：:]\s*\*{0,2}(减持|UNDERWEIGHT)\*{0,2}', "UNDERWEIGHT"),
    (r'评级[：:]\s*\*{0,2}(卖出|SELL)\*{0,2}', "SELL"),
    # Broader patterns — signal keyword followed by parenthetical
    (r'(买入|BUY)\s*[\(（]', "BUY"),
    (r'(增持|OVERWEIGHT)\s*[\(（]', "OVERWEIGHT"),
    (r'(减持|UNDERWEIGHT)\s*[\(（]', "UNDERWEIGHT"),
    (r'(卖出|SELL)\s*[\(（]', "SELL"),
]

# Markdown code-block pattern
_JSON_BLOCK_RE = re.compile(r'```json\s*\n?(.*?)\n?\s*```', re.DOTALL)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_json_block(text: str) -> Optional[Dict[str, Any]]:
    """Extract JSON from ```json ... ``` code block."""
    match = _JSON_BLOCK_RE.search(text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass
    return None


def _extract_raw_json(text: str) -> Optional[Dict[str, Any]]:
    """Extract raw JSON object from text.

    Scans backwards from the end to find the last balanced ``{ … }`` pair,
    which is where the LLM typically places its structured output.
    """
    brace_count = 0
    start = None
    for i in range(len(text) - 1, -1, -1):
        if text[i] == '}':
            brace_count += 1
        elif text[i] == '{':
            brace_count -= 1
            if brace_count == 0:
                start = i
                break
    if start is not None:
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError:
            pass
    return None


def _regex_fallback(text: str) -> Dict[str, Any]:
    """Extract individual fields using regex when JSON parsing fails."""
    result: Dict[str, Any] = {}

    # --- rating ---
    for pattern, rating in _RATING_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            result["rating"] = rating
            result["action"] = rating
            break

    # --- price range ---
    price_match = re.search(r'(\d+\.?\d*)\s*[-~至—]\s*(\d+\.?\d*)', text)
    if price_match:
        result["price_range"] = f"{price_match.group(1)}-{price_match.group(2)}"

    # --- target shares ---
    shares_match = re.search(r'(\d{1,8})\s*股', text)
    if not shares_match:
        shares_match = re.search(r'(?:增持|减持|买入|卖出)\s*(\d{1,8})', text)
    if shares_match:
        result["target_shares"] = int(shares_match.group(1))

    return result


def _normalize_result(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize extracted data to standard 5-field format.

    Uses ``normalize_signal`` from signal_extractor for rating/action so
    that Chinese and English keywords are consistently mapped.
    """
    from webapi.utils.signal_extractor import normalize_signal

    normalized: Dict[str, Any] = {
        "rating": None,
        "action": None,
        "price_range": None,
        "target_shares": None,
        "reason": None,
    }

    if not isinstance(data, dict):
        return normalized

    # rating / action — try multiple possible keys
    raw_rating = data.get("rating") or data.get("action") or data.get("decision")
    if raw_rating:
        normalized["rating"] = normalize_signal(raw_rating)

    raw_action = data.get("action") or data.get("rating")
    if raw_action:
        normalized["action"] = normalize_signal(raw_action)

    # price_range
    if data.get("price_range"):
        normalized["price_range"] = str(data["price_range"])

    # target_shares
    if data.get("target_shares") is not None:
        try:
            normalized["target_shares"] = int(data["target_shares"])
        except (ValueError, TypeError):
            pass

    # reason
    if data.get("reason"):
        normalized["reason"] = str(data["reason"])

    return normalized


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_structured_decision(text: str) -> Dict[str, Any]:
    """Parse structured decision from LLM output text.

    Tries in order:
    1. Extract JSON from markdown code block (`````json ... `````)
    2. Extract raw JSON object from text
    3. Regex fallback for individual fields

    Args:
        text: The ``final_trade_decision`` text from Portfolio Manager

    Returns:
        Dict with keys: rating, action, price_range, target_shares, reason.
        Missing fields are ``None``.  Returns empty dict if *text* is falsy.
    """
    if not text or not isinstance(text, str):
        return {}

    # Strategy 1 — markdown JSON block
    result = _extract_json_block(text)
    if result and isinstance(result, dict):
        return _normalize_result(result)

    # Strategy 2 — raw JSON object
    result = _extract_raw_json(text)
    if result and isinstance(result, dict):
        return _normalize_result(result)

    # Strategy 3 — regex fallback
    result = _regex_fallback(text)
    return _normalize_result(result)
