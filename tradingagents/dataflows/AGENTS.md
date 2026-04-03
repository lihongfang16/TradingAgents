# tradingagents/dataflows/ — Data Source Layer

## OVERVIEW

Multi-provider data abstraction with A-share-specific failover chain. Auto-routes symbols via `is_a_share()` detection to Chinese data providers or global providers (yfinance/AlphaVantage).

## STRUCTURE

```
dataflows/
├── interface.py            # route_to_vendor(), is_a_share(), TOOLS_CATEGORIES routing
├── china_data_manager.py   # ChinaDataManager singleton — unified A-share API with failover
├── config.py               # Data source configuration from env vars
├── mairui_provider.py      # MairuiProvider — licensed API, highest priority
├── ashare_provider.py      # AshareProvider — Sina+Tencent dual-core failover
├── akshare_provider.py     # AkShareProvider — akshare library (stock_zh_a_spot_em, etc.)
├── baostock_provider.py    # BaoStockProvider — baostock library, historical data backup
├── y_finance.py            # Yahoo Finance stock data + fundamentals
├── yfinance_news.py        # Yahoo Finance news
├── alpha_vantage*.py       # AlphaVantage stock/indicator/fundamentals/news (5 files)
├── stockstats_utils.py     # Technical indicator calculations via stockstats
├── utils.py                # Shared utilities
└── data_cache/             # Local file cache (gitignored)
```

## FAILOVER ARCHITECTURE

```
A-share symbol detected (6-digit, starts 0/3/6)
    ↓
ChinaDataManager.get_kline() / get_realtime_quote() / get_fundamental_data()
    ↓
MairuiProvider  →  (fail)  →  AshareProvider  →  (fail)  →  AkShareProvider  →  (fail)  →  BaoStockProvider
```

Override: `A_SHARE_DATA_SOURCE` env var forces a specific provider.

## SYMBOL NORMALIZATION

`_normalize_symbol()` handles all common formats:
- `000001`, `SZ000001`, `000001.SZ`, `600000.SH`, `sh600000`
- Shanghai: 6xx prefix → `sh`
- Shenzhen: 0xx/3xx prefix → `sz`
- Beijing: 4xx/8xx prefix → `bj`

## WHERE TO LOOK

| Task | Location |
|------|----------|
| Add new A-share provider | New file → register in `china_data_manager.py` `_failover_*` methods |
| Change failover order | `china_data_manager.py` — provider list in each `_failover_*` method |
| Add new tool category | `interface.py` → add to `TOOLS_CATEGORIES` and `VENDOR_METHODS` |
| Configure data source | `config.py` reads `A_SHARE_DATA_SOURCE`, `MAIRUI_LICENCE` env vars |
| Fix symbol routing | `interface.py` `route_to_vendor()` + `is_a_share()` |

## CONVENTIONS

- All providers implement consistent method signatures: `get_kline()`, `get_realtime_quote()`, `get_fundamental_data()`
- `data_cache/` stores API responses locally (gitignored)
- BaoStock requires login/logout lifecycle (`bs.login()` / `bs.logout()`)
- AkShare uses `stock_zh_a_*` functions (East Money sourced)

## NOTES

- Mairui requires `MAIRUI_LICENCE` env var — failover skips if missing
- Ashare uses Sina realtime API (primary) + Tencent (fallback) — no API key needed
- `stockstats_utils.py` calculates technical indicators (MACD, RSI, etc.) from kline data
- AlphaVantage has `AlphaVantageRateLimitError` for graceful fallback
