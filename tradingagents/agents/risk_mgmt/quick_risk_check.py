import json
import re

# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportExplicitAny=false, reportGeneralTypeIssues=false, reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportDeprecated=false, reportMissingTypeArgument=false, reportUnusedImport=false, reportUnusedVariable=false, reportMissingParameterType=false, reportUnknownParameterType=false


def _extract_json_object(content: str) -> dict:
    """Extract a JSON object from LLM output with defensive fallbacks."""
    text = content.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    return {}


def create_quick_risk_check(llm):
    """Create a compact risk/investment synthesis node for fast mode."""

    def quick_risk_check_node(state) -> dict:
        market_report = state.get("market_report", "")
        sentiment_report = state.get("sentiment_report", "")
        news_report = state.get("news_report", "")
        fundamentals_report = state.get("fundamentals_report", "")
        company_name = state.get("company_of_interest", "")

        prompt = f"""你是快速分析模式下的风险检查器。请基于已有分析，快速给出可执行的投资计划与风险结论。

股票：{company_name}

市场分析：{market_report}
情绪分析：{sentiment_report}
新闻分析：{news_report}
基本面分析：{fundamentals_report}

只输出一个 JSON 对象，不要添加任何额外说明，格式如下：
{{
  "investment_plan": "给交易员的简洁执行计划，包含方向、仓位/节奏建议",
  "risk_level": "low 或 medium 或 high",
  "confidence": 0.0,
  "market_alert": "若无异常填空字符串",
  "risk_summary": "1-2 句中文总结主要风险与约束"
}}

要求：
- confidence 必须在 0 到 1 之间
- risk_level 只能是 low / medium / high
- investment_plan 与 risk_summary 要简洁、直接、可执行"""

        response = llm.invoke(prompt)
        payload = _extract_json_object(response.content)

        investment_plan = str(payload.get("investment_plan") or "基于当前市场信号谨慎执行，控制仓位并跟踪短期变化。")
        risk_level = str(payload.get("risk_level") or "medium").lower()
        if risk_level not in {"low", "medium", "high"}:
            risk_level = "medium"

        confidence = payload.get("confidence", 0.5)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(confidence, 1.0))

        market_alert = str(payload.get("market_alert") or "")
        risk_summary = str(payload.get("risk_summary") or "保持纪律，关注价格波动与流动性风险。")

        risk_snapshot = {
            "risk_level": risk_level,
            "confidence": confidence,
            "market_alert": market_alert,
            "risk_summary": risk_summary,
            "investment_plan": investment_plan,
        }
        risk_snapshot_text = json.dumps(risk_snapshot, ensure_ascii=False)

        risk_debate_state = {
            "history": f"Quick Risk Check: {risk_summary}",
            "aggressive_history": "",
            "conservative_history": "",
            "neutral_history": f"Quick Risk Check: {risk_summary}",
            "latest_speaker": "Quick Risk Check",
            "current_aggressive_response": "",
            "current_conservative_response": "",
            "current_neutral_response": risk_summary,
            "judge_decision": risk_snapshot_text,
            "count": 1,
        }

        return {
            "investment_plan": investment_plan,
            "risk_debate_state": risk_debate_state,
            "sender": "Quick Risk Check",
        }

    return quick_risk_check_node
