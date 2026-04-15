"""Persona signal aggregator — synthesizes 6 persona signals into a summary report."""
import logging
from typing import Any, Callable, Dict

from langchain_core.messages import AIMessage

logger = logging.getLogger(__name__)


def create_persona_aggregator(llm) -> Callable:
    """Create a persona aggregator node that synthesizes all persona signals.
    
    Args:
        llm: LLM instance (kept for interface consistency; aggregator is rule-based).
    
    Returns:
        LangGraph node function.
    """
    
    def aggregator_node(state: Dict[str, Any]) -> Dict[str, Any]:
        signals = state.get("persona_signals", {})
        
        if not signals:
            logger.warning("⚠️ Persona Aggregator: No persona signals found")
            return {
                "messages": [],
                "persona_report": "## Persona Vote Summary\nNo persona signals available.",
            }
        
        # Build individual signal summaries
        summary_parts = []
        for name, signal in signals.items():
            if not isinstance(signal, dict):
                continue
            summary_parts.append(
                f"### {name}\n"
                f"- Signal: {signal.get('signal', 'N/A')}\n"
                f"- Confidence: {signal.get('confidence', 0)}/100\n"
                f"- Reasoning: {signal.get('reasoning', 'N/A')}\n"
            )
        
        # Count votes
        bullish = sum(1 for s in signals.values() if isinstance(s, dict) and s.get("signal") == "bullish")
        bearish = sum(1 for s in signals.values() if isinstance(s, dict) and s.get("signal") == "bearish")
        neutral = sum(1 for s in signals.values() if isinstance(s, dict) and s.get("signal") == "neutral")
        total = len(signals)
        avg_confidence = sum(
            s.get("confidence", 0) for s in signals.values() if isinstance(s, dict)
        ) / max(total, 1)
        
        # Weighted signal (bullish=+1, bearish=-1, neutral=0)
        weighted_score = bullish - bearish
        if weighted_score > 0:
            consensus = "偏多 (Bullish Lean)"
        elif weighted_score < 0:
            consensus = "偏空 (Bearish Lean)"
        else:
            consensus = "中性 (Neutral)"
        
        vote_summary = (
            f"## Persona Vote Summary\n"
            f"- Consensus: **{consensus}** (加权得分: {weighted_score:+d})\n"
            f"- Bullish: {bullish}/{total} | Bearish: {bearish}/{total} | Neutral: {neutral}/{total}\n"
            f"- Average Confidence: {avg_confidence:.0f}/100\n\n"
        )
        
        persona_report = vote_summary + "\n".join(summary_parts)
        
        logger.info(
            "✅ Persona Aggregator: %s (B:%d/%d BE:%d/%d N:%d/%d avg_conf:%.0f)",
            consensus, bullish, total, bearish, total, neutral, total, avg_confidence,
        )
        
        return {
            "messages": [],
            "persona_report": persona_report,
        }
    
    return aggregator_node
