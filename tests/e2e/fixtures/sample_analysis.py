"""
Sample test data fixtures for TradingAgents E2E tests.
"""


# Valid Chinese A-share symbols
VALID_SYMBOLS = {
    "CN": ["000001", "600036", "601398", "000858", "600519"],
}

# Expected API response fields for an AnalysisResponse
ANALYSIS_RESPONSE_FIELDS = [
    "task_id",
    "status",
    "symbol",
    "message",
]

# Valid analyst options
VALID_ANALYSTS = ["market", "news", "fundamentals", "social"]

# Valid exchange options
VALID_EXCHANGES = ["CN", "US", "HK"]

# Valid source options
VALID_SOURCES = ["mairui", "ashare", "akshare", "baostock"]
