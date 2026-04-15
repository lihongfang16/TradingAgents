"""Base classes and utilities for persona agents."""
import re
import json
import logging
from typing import Dict, Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PersonaSignal(BaseModel):
    """Structured output from a persona agent analysis."""
    signal: Literal["bullish", "bearish", "neutral"] = Field(
        description="Investment signal direction"
    )
    confidence: int = Field(
        ge=0, le=100,
        description="Confidence level 0-100"
    )
    reasoning: str = Field(
        description="Brief explanation of the signal (under 200 chars)"
    )
    key_metrics: Dict[str, float] = Field(
        default_factory=dict,
        description="Quantitative scores that drove the decision"
    )


DEFAULT_SIGNAL = PersonaSignal(
    signal="neutral",
    confidence=50,
    reasoning="Failed to parse LLM output",
    key_metrics={}
)


def _coerce_key_metrics(raw: Any) -> Dict[str, float]:
    """Coerce key_metrics values to float, dropping unconvertible entries.

    Handles common LLM mistakes:
    - String values like 'steady_non_accelerating' → dropped
    - Chinese text like '护城河评级': '★★★★★' → dropped
    - Nested dicts like {'value': 21.27, 'assessment': '...'} → extract 'value'
    - None / empty → dropped
    """
    if not isinstance(raw, dict):
        return {}

    result: Dict[str, float] = {}
    for key, val in raw.items():
        if isinstance(val, (int, float)):
            result[key] = float(val)
        elif isinstance(val, dict):
            # Try to extract a numeric "value" field from nested dicts
            if "value" in val and isinstance(val["value"], (int, float)):
                result[key] = float(val["value"])
        elif isinstance(val, str):
            # Try to parse numeric strings (e.g. "21.27")
            try:
                result[key] = float(val)
            except ValueError:
                pass  # Drop non-numeric strings
        # None, bool, list etc. → silently dropped
    return result


def _extract_signal_from_text(text: str) -> str:
    """Infer signal direction from freeform text using keyword matching."""
    text_lower = text.lower()

    bullish_keywords = [
        "bullish", "buy", "strong buy", "overweight", "undervalued",
        "growth", "opportunity", "attractive", "positive outlook",
        "看涨", "买入", "增持", "低估", "机会", "看好", "积极",
    ]
    bearish_keywords = [
        "bearish", "sell", "strong sell", "underweight", "overvalued",
        "risk", "decline", "negative", "avoid", "concern",
        "看跌", "卖出", "减持", "高估", "风险", "担忧", "负面",
    ]

    bull_score = sum(1 for kw in bullish_keywords if kw in text_lower)
    bear_score = sum(1 for kw in bearish_keywords if kw in text_lower)

    if bull_score > bear_score:
        return "bullish"
    elif bear_score > bull_score:
        return "bearish"
    return "neutral"


def _extract_confidence_from_text(text: str) -> int:
    """Try to extract a confidence number (0-100) from freeform text."""
    # Look for patterns like "confidence: 75", "置信度: 80%", etc.
    patterns = [
        r'confidence[:\s]+(\d{1,3})',
        r'conf[:\s]+(\d{1,3})',
        r'置信度[:\s]+(\d{1,3})',
        r'(\d{1,3})%\s*confident',
        r'(\d{1,3})/100',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            return min(max(val, 0), 100)
    return 50


def parse_persona_signal(text: str, persona_name: str = "unknown") -> Dict[str, Any]:
    """Parse LLM output into a structured PersonaSignal dict.

    Multi-level parsing strategy:
    1. Extract JSON from markdown code blocks → validate with PersonaSignal
    2. Parse entire text as JSON → validate
    3. Regex extraction of individual fields
    4. Freeform text keyword analysis fallback

    Args:
        text: Raw LLM response text
        persona_name: Name of the persona (for logging)

    Returns:
        Dict with signal, confidence, reasoning, key_metrics keys
    """
    if not text or not text.strip():
        logger.warning(f"[{persona_name}] Empty LLM response, using default signal")
        return DEFAULT_SIGNAL.model_dump()

    # ── Level 1a: JSON from markdown code blocks ────────────────────
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1).strip())
            data["key_metrics"] = _coerce_key_metrics(data.get("key_metrics", {}))
            signal = PersonaSignal(**data)
            return signal.model_dump()
        except Exception as e:
            logger.warning(f"[{persona_name}] L1a (markdown JSON) parse failed: {e}")

    # ── Level 1b: Try parsing entire text as JSON ───────────────────
    try:
        data = json.loads(text.strip())
        data["key_metrics"] = _coerce_key_metrics(data.get("key_metrics", {}))
        signal = PersonaSignal(**data)
        return signal.model_dump()
    except Exception:
        pass

    # ── Level 2: Regex extraction ───────────────────────────────────
    signal_match = re.search(r'"?signal"?\s*:\s*"?(bullish|bearish|neutral)"?', text, re.IGNORECASE)
    confidence_match = re.search(r'"?confidence"?\s*:\s*(\d+)', text)
    reasoning_match = re.search(r'"?reasoning"?\s*:\s*"([^"]+)"', text)

    if signal_match:
        try:
            return PersonaSignal(
                signal=signal_match.group(1).lower(),
                confidence=int(confidence_match.group(1)) if confidence_match else 50,
                reasoning=reasoning_match.group(1) if reasoning_match else "Extracted via regex",
                key_metrics={},
            ).model_dump()
        except Exception as e:
            logger.warning(f"[{persona_name}] L2 (regex) parse failed: {e}")

    # ── Level 3: Freeform text keyword analysis ─────────────────────
    signal = _extract_signal_from_text(text)
    confidence = _extract_confidence_from_text(text)

    # Extract a short reasoning from the text (first 200 chars)
    # Strip any JSON-like fragments for cleaner text
    clean_text = re.sub(r'[{}\[\]"]', '', text).strip()
    reasoning = clean_text[:200] if clean_text else "Signal inferred from text keywords"

    logger.warning(
        f"[{persona_name}] L3 (keyword fallback): signal={signal}, confidence={confidence}"
    )
    return PersonaSignal(
        signal=signal,
        confidence=confidence,
        reasoning=reasoning,
        key_metrics={},
    ).model_dump()


def format_quantitative_summary(**score_dicts) -> str:
    """Format multiple scoring dicts into a readable summary for LLM prompt.
    
    Args:
        **score_dicts: Named score dicts, e.g., value=calc_value_metrics(...), health=...
    
    Returns:
        Formatted string with all scores
    """
    parts = []
    for name, scores in score_dicts.items():
        if scores:
            lines = [f"  {k}: {v:.2f}" if isinstance(v, float) else f"  {k}: {v}" for k, v in scores.items()]
            parts.append(f"### {name}\n" + "\n".join(lines))
    return "\n\n".join(parts)