"""Unit tests for watchlist scheduler service."""

# pyright: reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownMemberType=false

from webapi.services.scheduler_service import SchedulerService, should_use_high_frequency


def test_scheduler_test_mode_registers_expected_jobs(monkeypatch):
    monkeypatch.setenv("SCHEDULER_TEST_MODE", "true")
    monkeypatch.setenv("SCHEDULER_INTERVAL_MINUTES", "1")
    monkeypatch.setenv("SCHEDULER_HIGH_FREQUENCY_INTERVAL_MINUTES", "1")

    service = SchedulerService()
    service.start(persist=False)
    try:
        jobs = service.get_jobs()
        job_ids = {job["id"] for job in jobs}
        assert "watchlist_full_analysis" in job_ids
        assert "watchlist_morning_quick" in job_ids
        assert "watchlist_afternoon_quick" in job_ids
        assert "watchlist_high_freq_batch" in job_ids
    finally:
        service.stop(persist=False)


def test_should_use_high_frequency_returns_false_when_results_stable():
    recent_results = [
        {"signal": "BUY", "confidence": 0.82, "risk_level": "medium"},
        {"signal": "BUY", "confidence": 0.85, "risk_level": "medium"},
        {"signal": "BUY", "confidence": 0.84, "risk_level": "medium"},
    ]

    assert should_use_high_frequency(recent_results, stable_threshold=3) is False


def test_should_use_high_frequency_returns_true_when_risk_changes():
    recent_results = [
        {"signal": "BUY", "confidence": 0.82, "risk_level": "medium"},
        {"signal": "BUY", "confidence": 0.84, "risk_level": "high"},
        {"signal": "BUY", "confidence": 0.83, "risk_level": "medium"},
    ]

    assert should_use_high_frequency(recent_results, stable_threshold=3) is True
