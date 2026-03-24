# TradingAgents A-Share Learnings

## 2026-03-23: market_analyst.py A-Share Adaptation

### Architecture Insight
- `market_analyst.py` is a **prompt-based LLM agent node**, not a direct data processor
- A-share data routing already handled at tool level via `route_to_vendor()` → `china_manager.get_kline()`
- The right place to add A-share specifics is in the **system prompt context**, not in data processing

### Implementation Approach
- Added `_get_price_limit(symbol)` helper for ±10%/±20% detection
- Added `_get_a_share_context(symbol)` to build A-share specific prompt context
- Context includes: 涨跌停限制, T+1 rules, trading hours, real-time quote alerts
- Real-time quote fetched via `china_manager.get_realtime_quote()` for 涨跌停 detection
- No changes needed to tool infrastructure — routing already works

### Key Findings
- `china_manager` singleton is in `interface.py` — import directly
- `is_a_share()` also in `interface.py` — handles SZ/SH/BJ prefixes
- 创业板 (301xxx, 303xxx) and 科创板 (688xxx) have ±20% limits
- Quote dict keys vary by provider: `change_percent`, `pct_chg`, `涨跌幅`
