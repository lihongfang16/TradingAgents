"""
Ashare Data Provider for A-Share Stocks
Implements dual-core failover (Sina + Tencent)
Ashare is a single-file library for easy A-share data access
"""

import os
import sys
import json
import pandas as pd
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from decimal import Decimal

# Import Ashare from the local module
# Ashare is a single-file library from https://github.com/mpquant/Ashare
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Ashare source code embedded for portability
# Source: https://raw.githubusercontent.com/mpquant/Ashare/main/Ashare.py

def get_price_sina(code, end_date='', count=10, frequency='1d'):  # 日线
    """
    获取新浪股票价格数据
    
    Sina API scale parameter accepts:
      - minute data: 1, 5, 15, 30, 60 (minutes)
      - daily: 240 (special value for daily bars)
      - weekly: 1200 (special value for weekly bars)
    
    We handle 'day'/'1d' and 'week'/'1w' specially to avoid
    the broken frequency→minutes mapping that previously mapped
    'day' → '240m' → 240 (correct) but 'week' → '1200m' → 1200 (broken).
    """
    frequency = frequency.lower()
    
    # Map friendly names to Sina scale values
    freq_to_scale = {
        '1d': 240,
        'day': 240,
        'daily': 240,
        '1w': 1200,
        'week': 1200,
        'weekly': 1200,
        '1m': 1,
        '5m': 5,
        '15m': 15,
        '30m': 30,
        '60m': 60,
    }
    
    scale = freq_to_scale.get(frequency)
    if scale is None:
        # Try parsing as raw minute value
        try:
            scale = int(frequency.replace('m', ''))
        except ValueError:
            scale = 240  # default to daily
    
    # Determine market prefix
    code = code.strip()
    if code.startswith(('600', '601', '602', '603', '605', '688', '689')):
        code = 'sh' + code
    elif code.startswith(('000', '001', '002', '003', '300', '301', '303')):
        code = 'sz' + code
    elif code.startswith(('4', '8')):
        code = 'bj' + code
    
    import requests
    
    # Sina has two API formats; try the newer one first, fall back to legacy
    urls = [
        f"https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData?symbol={code}&scale={scale}&ma=no&datalen={count}",
        f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketDataService.getKLineData?symbol={code}&scale={scale}&ma=no&datalen={count}",
    ]
    
    for url in urls:
        try:
            response = requests.get(url, timeout=30)
            text = response.text.strip()
            
            if not text or 'File not found' in text:
                continue
            
            # JSONP format: various wrappers around JSON array data
            # Common formats:
            #   =( [ { ... }, ... ] );
            #   callback=( [ { ... }, ... ] );
            #   /*<script>...</script>*/=( [ { ... }, ... ] );
            # Strategy: find the first [ and last ] and extract JSON array
            
            bracket_start = text.find('[')
            bracket_end = text.rfind(']')
            
            if bracket_start == -1 or bracket_end == -1 or bracket_end <= bracket_start:
                continue
            
            json_str = text[bracket_start:bracket_end + 1]
            
            data = json.loads(json_str)
            
            if not data or not isinstance(data, list):
                continue
            
            df = pd.DataFrame(data)
            
            # Normalize column names (Sina uses camelCase)
            col_map = {
                'day': 'day', 'd': 'day',
                'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close',
                'volume': 'volume', 'vol': 'volume',
            }
            df.rename(columns={k: v for k, v in col_map.items() if k in df.columns}, inplace=True)
            
            if 'day' not in df.columns:
                continue
            
            df['day'] = pd.to_datetime(df['day'])
            df.set_index('day', inplace=True)
            
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # Keep only OHLCV columns
            ohlcv = [c for c in ['open', 'high', 'low', 'close', 'volume'] if c in df.columns]
            df = df[ohlcv]
            
            return df.sort_index()
        except Exception as e:
            continue
    
    return None


def get_price_tencent(code, end_date='', count=10, frequency='1d'):
    """
    获取腾讯股票价格数据
    """
    frequency = frequency.lower()
    
    # Determine market prefix
    code = code.strip()
    if code.startswith(('600', '601', '602', '603', '605', '688', '689')):
        code = 'sh' + code
    elif code.startswith(('000', '001', '002', '003', '300', '301', '303')):
        code = 'sz' + code
    elif code.startswith(('4', '8')):
        code = 'bj' + code
    
    import requests
    
    # Map frequency
    freq_map = {
        '1d': 'day',
        'day': 'day',
        '1w': 'week',
        'week': 'week',
        '1m': 'month',
        'month': 'month',
        '1m': '1m',
        '5m': '5m',
        '15m': '15m',
        '30m': '30m',
        '60m': '60m'
    }
    
    freq = freq_map.get(frequency, 'day')
    
    # Tencent API for minute data is different
    if freq in ['1m', '5m', '15m', '30m', '60m']:
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},{freq},,{count},qfq"
    else:
        # For daily/weekly/monthly, the qfq key format is 'qfq{freq}' e.g. 'qfqday'
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},{freq},,,{count},qfq"
    
    try:
        response = requests.get(url, timeout=30)
        data = response.json()
        
        # Safety: ensure response is a dict
        if not isinstance(data, dict):
            return None
        
        # Parse response — try multiple key formats
        stock_data = data.get('data', {})
        if not isinstance(stock_data, dict):
            return None
        stock_data = stock_data.get(code, {})
        
        # Try keys in order of likelihood
        possible_keys = [
            f'qfq{freq}',     # e.g. 'qfqday' (most common for daily)
            f'{code}qfq{freq}',
            f'{code}{freq}',
            freq,
        ]
        
        kline_data = None
        for key in possible_keys:
            kline_data = stock_data.get(key)
            if kline_data:
                break
        
        if not kline_data:
            return None
        
        # Convert to DataFrame
        df_data = []
        for item in kline_data:
            if isinstance(item, list) and len(item) >= 5:
                df_data.append({
                    'date': item[0],
                    'open': float(item[1]),
                    'close': float(item[2]),
                    'low': float(item[3]),
                    'high': float(item[4]),
                    'volume': float(item[5]) if len(item) > 5 else 0
                })
        
        df = pd.DataFrame(df_data)
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        df.rename(columns={
            'open': 'open',
            'high': 'high',
            'low': 'low',
            'close': 'close',
            'volume': 'volume'
        }, inplace=True)
        
        return df
        
    except Exception as e:
        logger.warning(f"Tencent data fetch error: {e}")
        return None


class AshareProvider:
    """
    Ashare Data Provider for A-Share stocks with dual-core failover
    Supports Sina and Tencent data sources with automatic fallback
    """
    
    def __init__(self, primary_source: str = "sina"):
        """
        Initialize AshareProvider
        
        Args:
            primary_source: Primary data source ('sina' or 'tencent')
        """
        self.primary_source = primary_source.lower()
        self.sources = [self.primary_source]
        
        # Add secondary source
        if self.primary_source == "sina":
            self.sources.append("tencent")
        else:
            self.sources.append("sina")
    
    def _normalize_symbol(self, symbol: str) -> str:
        """
        Normalize symbol to 6-digit format
        
        Args:
            symbol: Stock symbol (e.g., '000001', '000001.SZ', 'SZ000001')
            
        Returns:
            Normalized 6-digit symbol
        """
        symbol = symbol.strip().upper()
        
        # Remove exchange suffixes
        for suffix in ['.SZ', '.SH', '.BJ']:
            if symbol.endswith(suffix):
                symbol = symbol[:-3]
                break
        
        # Remove exchange prefixes
        for prefix in ['SZ', 'SH', 'BJ']:
            if symbol.startswith(prefix):
                symbol = symbol[2:]
                break
        
        return symbol
    
    def _get_market_from_symbol(self, symbol: str) -> str:
        """
        Determine market from symbol
        
        Args:
            symbol: 6-digit stock symbol
            
        Returns:
            Market code ('sh', 'sz', or 'bj')
        """
        if symbol.startswith(('600', '601', '602', '603', '605', '688', '689')):
            return 'sh'
        elif symbol.startswith(('000', '001', '002', '003', '300', '301', '303')):
            return 'sz'
        elif symbol.startswith(('4', '8')):
            return 'bj'
        else:
            return 'sz'  # Default to Shenzhen
    
    def get_kline(self, symbol: str, period: str = "day", limit: int = 120) -> Optional[pd.DataFrame]:
        """
        Get K-line data with dual-core failover
        
        Args:
            symbol: Stock symbol (6-digit or with prefix)
            period: K-line period ('1m', '5m', '15m', '30m', '60m', 'day', 'week', 'month')
            limit: Number of records to retrieve
            
        Returns:
            DataFrame with columns: [open, high, low, close, volume] or None
        """
        symbol = self._normalize_symbol(symbol)
        period = period.lower()
        
        # Map period to Ashare format
        period_map = {
            '1m': '1m',
            '5m': '5m',
            '15m': '15m',
            '30m': '30m',
            '60m': '60m',
            '1d': 'day',
            'day': 'day',
            'daily': 'day',
            '1w': 'week',
            'week': 'week',
            'weekly': 'week',
            '1mo': 'month',
            'month': 'month',
            'monthly': 'month'
        }
        
        ashare_period = period_map.get(period, 'day')
        
        # Try each source
        for source in self.sources:
            try:
                if source == "sina":
                    df = get_price_sina(symbol, count=limit, frequency=ashare_period)
                else:
                    df = get_price_tencent(symbol, count=limit, frequency=ashare_period)
                
                if df is not None and not df.empty:
                    # Standardize column names
                    df = df.rename(columns={
                        'open': 'open',
                        'high': 'high',
                        'low': 'low',
                        'close': 'close',
                        'volume': 'volume'
                    })
                    
                    # Ensure numeric types
                    for col in ['open', 'high', 'low', 'close', 'volume']:
                        if col in df.columns:
                            df[col] = pd.to_numeric(df[col], errors='coerce')
                    
                    return df
                    
            except Exception as e:
                logger.warning(f"Ashare {source} error for {symbol}: {e}")
                continue
        
        logger.warning(f"All Ashare sources failed for {symbol}")
        return None
    
    def get_daily_hist(self, symbol: str, days: int = 120) -> Optional[pd.DataFrame]:
        """
        Get daily historical data
        
        Args:
            symbol: Stock symbol
            days: Number of days of history
            
        Returns:
            DataFrame with OHLCV data or None
        """
        return self.get_kline(symbol, period="day", limit=days)
    
    def get_realtime_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get real-time quote data
        Uses Tencent's real-time API (most reliable for quotes)
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Dictionary with real-time quote data or None
        """
        symbol = self._normalize_symbol(symbol)
        
        # Use Tencent for real-time quotes (more reliable)
        import requests
        
        # Add market prefix
        market = self._get_market_from_symbol(symbol)
        full_code = f"{market}{symbol}"
        
        url = f"https://qt.gtimg.cn/q={full_code}"
        
        try:
            response = requests.get(url, timeout=10)
            response.encoding = 'gbk'
            
            # Parse Tencent quote format
            # Format: v_sz000001="1~平安银行~000001~..."
            data_str = response.text.strip()
            
            if not data_str or '~' not in data_str:
                return None
            
            # Extract data between quotes
            start = data_str.find('"') + 1
            end = data_str.rfind('"')
            data_content = data_str[start:end]
            
            parts = data_content.split('~')
            if len(parts) < 45:
                return None
            
            return {
                'symbol': symbol,
                'name': parts[1],
                'price': Decimal(parts[3]),
                'change': Decimal(parts[4]),
                'change_percent': Decimal(parts[5]),
                'open': Decimal(parts[5]),
                'high': Decimal(parts[33]),
                'low': Decimal(parts[34]),
                'prev_close': Decimal(parts[4]) - Decimal(parts[5]) if parts[4] and parts[5] else Decimal('0'),
                'volume': int(parts[36]) if parts[36].isdigit() else 0,
                'amount': Decimal(parts[37]) if parts[37] else Decimal('0'),
                'bid1_price': Decimal(parts[9]),
                'bid1_volume': int(parts[10]) if parts[10].isdigit() else 0,
                'ask1_price': Decimal(parts[19]),
                'ask1_volume': int(parts[20]) if parts[20].isdigit() else 0,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
        except Exception as e:
            logger.warning(f"Ashare real-time quote error: {e}")
            return None
    
    def get_fundamental_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get fundamental data
        Note: Ashare doesn't provide fundamental data directly
        Returns basic info from real-time quote
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Dictionary with basic info or None
        """
        quote = self.get_realtime_quote(symbol)
        
        if not quote:
            return None
        
        # Return basic info (Ashare doesn't have detailed fundamentals)
        return {
            'symbol': symbol,
            'name': quote.get('name', ''),
            'market_cap': None,  # Not available in free API
            'pe_ratio': None,
            'pb_ratio': None,
            'dividend_yield': None,
            'eps': None,
            'source': 'ashare_basic'
        }


# Test function
if __name__ == "__main__":
    provider = AshareProvider()
    
    # Test with a known A-share stock
    test_symbol = "000001"  # 平安银行
    
    print("=" * 60)
    print("AshareProvider Test")
    print("=" * 60)
    
    # Test K-line
    print(f"\n1. Testing get_kline for {test_symbol}")
    df = provider.get_kline(test_symbol, period="day", limit=5)
    if df is not None:
        print(f"✓ K-line data retrieved: {len(df)} records")
        print(df.head())
    else:
        print("✗ Failed to get K-line data")
    
    # Test real-time quote
    print(f"\n2. Testing get_realtime_quote for {test_symbol}")
    quote = provider.get_realtime_quote(test_symbol)
    if quote:
        print(f"✓ Real-time quote retrieved:")
        print(f"  Name: {quote.get('name')}")
        print(f"  Price: {quote.get('price')}")
        print(f"  Change: {quote.get('change')} ({quote.get('change_percent')}%)")
    else:
        print("✗ Failed to get real-time quote")
    
    # Test 创业板 stock
    print(f"\n3. Testing 创业板 stock (301188)")
    df = provider.get_kline("301188", period="day", limit=3)
    if df is not None:
        print(f"✓ 创业板 K-line retrieved: {len(df)} records")
    else:
        print("✗ Failed to get 创业板 data")
    
    print("\n" + "=" * 60)
    print("AshareProvider test complete")
    print("=" * 60)
