# OpenSpec Module: A-Share Data Layer

This specification defines the multi-source data failover system for Chinese A-share market data
within the TradingAgents framework.

---

## Overview

The A-Share Data Layer provides unified access to Chinese A-share stock market data through
 a priority-based failover chain of four data providers. It auto-detects
 A-share stock symbols and routes them to the appropriate data source, seamlessly
 integrating with the upstream analysis engine.

### Architecture

```
                          Tool Calls
                             │
                             ▼
                    route_to_vendor()
                             │
                    ┌────────┴──────────┐
                    │                   │
              is_a_share()?         Not A-share
                    │                   │
                    ▼                   ▼
            ChinaDataManager        Upstream vendors
                    │              (yfinance/AlphaVantage)
    ┌─────────┴──────────┴──────────┐
    │         │          │          │
  Mairui   Ashare    AkShare    BaoStock
  (primary)  (backup1)  (backup2)  (backup3)
```

### Priority Chain

| Priority | Provider | Type | API Key Required | Stability |
|----------|----------|------|-------------------|----------|
| 1 (Primary) | MairuiProvider | Licensed API | `MAIRUI_LICENCE` env var | ★★★★★ |
| 2 | AshareProvider | Sina + Tencent | None (free) | ★★★★ |
| 3 | AkShareProvider | akshare library | None (free) | ★★★ |
| 4 (Backup) | BaoStockProvider | baostock library | None (free) | ★★ |

### Symbol Normalization

`_normalize_symbol()` in `china_data_manager.py` handles all common A-share formats:

| Input Format | Normalized | Market |
|--------------|-----------|-------|
| `000001` | `sz000001` | Shenzhen (0xx prefix) |
| `SZ000001` | `sz000001` | Shenzhen |
| `000001.SZ` | `sz000001` | Shenzhen |
| `600000` | `sh600000` | Shanghai (6xx prefix) |
| `600000.SH` | `sh600000` | Shanghai |
| `sh600000` | `sh600000` | Shanghai |
| `4300047` | `bj4300047` | Beijing (4xx/8xx prefix) |

### Symbol Auto-Detection

`is_a_share()` in `interface.py` detects A-share symbols:

```python
def is_a_share(symbol: str) -> bool:
    """6-digit code starting with 0, 3, or 6."""
    # Supports: 000001, SZ000001, 600000.SH, sh600000, BJ430047
```

### Provider Interface

All providers implement consistent method signatures:

```python
class XxxProvider:
    def is_available(self) -> bool
    def get_realtime_quote(self, symbol: str) -> Optional[Dict[str, Any]]
    def get_kline(self, symbol: str, period: str = "day", limit: int = 120) -> Optional[pd.DataFrame]
    def get_fundamental_data(self, symbol: str) -> Optional[Dict[str, Any]]
```

### Adapter Wrappers

`interface.py` contains adapter functions that bridge tool function signatures to
ChinaDataManager method signatures:

| Adapter | Tool Function → ChinaDataManager Method |
|---------|----------------------------------------|
| `_china_get_stock_data()` | `get_stock_data()` → `china_manager.get_kline()` |
| `_china_get_indicators()` | `get_indicators()` → `china_manager.get_kline()` + stockstats |
| `_china_get_news()` | `get_news()` → `china_manager.get_realtime_quote()` |
| `_china_get_fundamentals()` | `get_fundamentals()` → `china_manager.get_fundamental_data()` |

### Routing Logic

`route_to_vendor()` in `interface.py` implements a 2-tier routing:

1. **A-share priority**: If `is_a_share(symbol)` and method has `"china"` in `VENDOR_METHODS`, use ChinaDataManager
2. **Global fallback**: Use upstream vendor routing (yfinance/AlphaVantage with fallback chain)

### Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `A_SHARE_DATA_SOURCE` | `mairui,ashare,akshare,baostock` | Comma-separated priority list |
| `MAIRUI_LICENCE` | (none) | Mairui API license key |

### Design Decisions

- **Why 4 providers?** Each provider has different strengths: Mairui for stability, Ashare for speed, AkShare for data richness, BaoStock for historical data reliability.
- **Why priority chain over single provider?** A-share data APIs are often rate-limited or unstable. Priority chain ensures graceful degradation.
- **Why adapter wrappers?** Tool functions have different signatures than ChinaDataManager methods. Adapters bridge the gap without modifying upstream tool definitions.

### Key Files

| File | Lines | Purpose |
|------|-------|---------|
| `china_data_manager.py` | 367 | `ChinaDataManager` class with failover logic |
| `mairui_provider.py` | 478 | Mairui API integration |
| `ashare_provider.py` | 522 | Sina + Tencent dual-core |
| `akshare_provider.py` | 316 | AkShare library wrapper |
| `baostock_provider.py` | 253 | BaoStock library wrapper |
| `interface.py` | 326 | Routing logic + adapters |
| `stockstats_utils.py` | 102 | Technical indicator calculations |

### Dependencies (A-share specific)
- `akshare` — A-share data library
- `baostock` — Historical A-share data
- `stockstats` — Technical indicator calculations from OHLCV data
- `pandas` — Data manipulation
- `requests` — HTTP API calls (Mairui)

---

*Last updated: 2026-03-28*
*Upstream reference: [Upstream Feature Inventory](../upstream-reference.md)*
