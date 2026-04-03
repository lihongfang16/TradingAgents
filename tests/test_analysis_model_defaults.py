"""Unit tests for webapi/models/analysis.py Pydantic models."""

import unittest

from webapi.models.analysis import AnalysisRequest, BatchAnalysisRequest


class TestAnalysisRequestDefaults(unittest.TestCase):
    """Test AnalysisRequest default values."""

    def test_analysts_default_includes_social(self):
        """Full analysis must include all 4 analysts for incremental diff to be meaningful."""
        request = AnalysisRequest(symbol="000001")
        self.assertEqual(
            request.analysts,
            ["market", "news", "social", "fundamentals"],
            "Default analysts must include all 4: market, news, social, fundamentals",
        )
        self.assertEqual(len(request.analysts), 4)

    def test_analysts_can_be_overridden(self):
        """Explicit analysts list should override defaults."""
        request = AnalysisRequest(symbol="600000", analysts=["market"])
        self.assertEqual(request.analysts, ["market"])


class TestBatchAnalysisRequestDefaults(unittest.TestCase):
    """Test BatchAnalysisRequest default values."""

    def test_analysts_default_includes_social(self):
        """Batch analysis also defaults to all 4 analysts."""
        request = BatchAnalysisRequest(symbols=["000001", "600000"])
        self.assertEqual(
            request.analysts,
            ["market", "news", "social", "fundamentals"],
            "Default analysts must include all 4: market, news, social, fundamentals",
        )
        self.assertEqual(len(request.analysts), 4)


if __name__ == "__main__":
    unittest.main()
