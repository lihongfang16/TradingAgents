"""Unit tests for decision_parser — JSON + regex fallback parser."""

import pytest
from webapi.utils.decision_parser import parse_structured_decision


class TestMarkdownJsonBlock:
    """Strategy 1: extract from ```json … ``` code block."""

    def test_basic_block(self):
        text = """分析报告内容...

评级：增持

```json
{
    "rating": "增持",
    "action": "增持",
    "price_range": "10.50-11.00",
    "target_shares": 500,
    "reason": "基于现有持仓成本10.50元"
}
```"""
        result = parse_structured_decision(text)
        assert result["rating"] == "OVERWEIGHT"
        assert result["action"] == "OVERWEIGHT"
        assert result["price_range"] == "10.50-11.00"
        assert result["target_shares"] == 500
        assert "10.50" in result["reason"]

    def test_english_rating_in_block(self):
        text = '```json\n{"rating": "SELL", "reason": "stop loss"}\n```'
        result = parse_structured_decision(text)
        assert result["rating"] == "SELL"

    def test_malformed_json_in_block_falls_through(self):
        """Malformed JSON in block → falls to strategy 2/3."""
        text = "```json\n{bad json}\n```\n建议增持500股"
        result = parse_structured_decision(text)
        # Should still extract via regex fallback
        assert result.get("target_shares") == 500


class TestRawJson:
    """Strategy 2: extract raw JSON object from text."""

    def test_json_at_end(self):
        text = '一些文本 {"rating": "减持", "price_range": "15.00-15.50", "target_shares": 200, "reason": "test"}'
        result = parse_structured_decision(text)
        assert result["rating"] == "UNDERWEIGHT"
        assert result["target_shares"] == 200

    def test_json_with_chinese_action(self):
        text = '结论 {"action": "买入", "reason": "基本面良好"}'
        result = parse_structured_decision(text)
        assert result["action"] == "BUY"
        assert result["reason"] == "基本面良好"

    def test_json_with_decision_key(self):
        text = '结果 {"decision": "持有"}'
        result = parse_structured_decision(text)
        assert result["rating"] == "HOLD"


class TestRegexFallback:
    """Strategy 3: regex field extraction."""

    def test_chinese_rating_and_shares(self):
        text = "建议增持500股，价格区间10.50至11.00元"
        result = parse_structured_decision(text)
        assert result.get("target_shares") == 500
        assert result.get("price_range") is not None
        assert "10.50" in result["price_range"]

    def test_rating_with_colon(self):
        text = "评级：卖出"
        result = parse_structured_decision(text)
        assert result.get("rating") == "SELL"

    def test_price_range_with_dash(self):
        text = "价格区间: 8.00-9.50"
        result = parse_structured_decision(text)
        assert result["price_range"] == "8.00-9.50"

    def test_shares_only(self):
        text = "建议操作：买入 1000股"
        result = parse_structured_decision(text)
        assert result.get("target_shares") == 1000


class TestEdgeCases:
    """Edge cases and error handling."""

    def test_empty_input(self):
        assert parse_structured_decision("") == {}

    def test_none_input(self):
        assert parse_structured_decision(None) == {}

    def test_non_string_input(self):
        assert parse_structured_decision(123) == {}

    def test_text_with_no_data(self):
        result = parse_structured_decision("这是一段普通文字，没有任何结构化信息")
        assert isinstance(result, dict)
        assert result["rating"] is None
        assert result["action"] is None
        assert result["price_range"] is None
        assert result["target_shares"] is None
        assert result["reason"] is None

    def test_all_five_fields_present(self):
        """Result dict always has exactly 5 keys."""
        result = parse_structured_decision("whatever")
        assert set(result.keys()) == {
            "rating", "action", "price_range", "target_shares", "reason"
        }

    def test_json_block_priority_over_raw(self):
        """Code block JSON should win over raw JSON later in text."""
        text = '''```json
{"rating": "BUY"}
```

Some text {"rating": "SELL"}'''
        result = parse_structured_decision(text)
        assert result["rating"] == "BUY"

    def test_malformed_raw_json_falls_to_regex(self):
        text = '评级：持有 {broken json}'
        result = parse_structured_decision(text)
        assert result["rating"] == "HOLD"
