"""Unit tests for turning-point detection helpers."""

from webapi.services.scheduler_service import detect_turning_point, should_use_high_frequency


def test_detect_turning_point_signal_reversal():
    is_turning, reason, importance = detect_turning_point(
        current_result={"signal": "SELL", "confidence": 0.85, "risk_level": "high"},
        previous_result={"signal": "BUY", "confidence": 0.70, "risk_level": "low"},
    )

    assert is_turning is True
    assert importance >= 0.9
    assert "信号转变" in reason


def test_detect_turning_point_confidence_jump():
    is_turning, reason, importance = detect_turning_point(
        current_result={"signal": "BUY", "confidence": 0.88, "risk_level": "medium"},
        previous_result={"signal": "BUY", "confidence": 0.60, "risk_level": "medium"},
    )

    assert is_turning is True
    assert "置信度突破" in reason
    assert importance >= 0.6


def test_detect_turning_point_market_alert():
    is_turning, reason, importance = detect_turning_point(
        current_result={
            "signal": "HOLD",
            "confidence": 0.55,
            "risk_level": "medium",
            "market_alert": "市场异常波动，需立即关注",
        },
        previous_result={"signal": "HOLD", "confidence": 0.56, "risk_level": "medium"},
    )

    assert is_turning is True
    assert "市场警报" in reason
    assert importance >= 0.95


def test_should_use_high_frequency_requires_more_data():
    assert should_use_high_frequency([
        {"signal": "BUY", "confidence": 0.80, "risk_level": "medium"},
        {"signal": "BUY", "confidence": 0.81, "risk_level": "medium"},
    ], stable_threshold=3) is True
