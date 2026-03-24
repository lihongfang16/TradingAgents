"""
Mairui Data Provider for A-Share Stocks
Provides real-time quotes and K-line data via Mairui API

API Documentation: https://www.mairuiapi.com/hsdata

Key Endpoints:
- Stock list: /hslt/list/{licence}
- Realtime quote: /hsrl/ssjy/{code}/{licence}  (code = 6-digit, no suffix)
- K-line data: /hsstock/history/{code}.{market}/{period}/{adj}/{licence}?lt={count}
"""

import os
import requests
import pandas as pd
from typing import Optional, Dict, Any
from datetime import datetime


class MairuiProvider:
    """
    Mairui Data Provider for A-Share stocks
    API Documentation: https://www.mairuiapi.com/hsdata
    """
    
    BASE_URL = "https://api.mairuiapi.com"
    
    # Map friendly period names to Mairui API period codes for /hsstock/history/
    PERIOD_MAP = {
        # Minute bars: 5, 15, 30, 60
        '1m': '5',     # 1 minute -> 5 minutes (Mairui minimum is 5m)
        '5m': '5',
        '15m': '15',
        '30m': '30',
        '60m': '60',
        # Daily/Weekly/Monthly/Yearly
        'day': 'd',
        'daily': 'd',
        '1d': 'd',
        'week': 'w',
        'weekly': 'w',
        'month': 'm',
        'monthly': 'm',
        'year': 'y',
        'yearly': 'y',
    }
    
    def __init__(self, licence: Optional[str] = None):
        """
        Initialize MairuiProvider
        
        Args:
            licence: Mairui API licence key. If not provided, reads from MAIRUI_LICENCE env var.
        """
        if licence is None:
            licence = os.environ.get('MAIRUI_LICENCE')
        
        if not licence:
            raise ValueError("Mairui licence not provided and MAIRUI_LICENCE env var not set")
        
        self.licence = licence
    
    def _make_request(self, url: str) -> Optional[Any]:
        """
        Make HTTP GET request to Mairui API
        
        Args:
            url: Full URL for the request
            
        Returns:
            JSON response or None on error
        """
        try:
            response = requests.get(url, timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Mairui API request error: {e}")
            return None
        except ValueError as e:
            print(f"Mairui API JSON parse error: {e}")
            return None
    
    def _normalize_symbol_for_realtime(self, symbol: str) -> str:
        """
        Normalize symbol for realtime API (6-digit code only)
        
        Args:
            symbol: Stock symbol (e.g., '000001', '000001.SH', 'SH000001')
            
        Returns:
            6-digit code without exchange suffix
        """
        symbol = symbol.strip().upper()
        
        # Remove exchange suffixes
        for suffix in ['.SZ', '.SH', '.BJ', '.SHANGHAI', '.BEIJING']:
            if symbol.endswith(suffix):
                symbol = symbol[:-len(suffix)]
                break
        
        # Remove exchange prefixes
        for prefix in ['SZ', 'SH', 'BJ']:
            if symbol.startswith(prefix) and len(symbol) == 8:
                symbol = symbol[len(prefix):]
                break
        
        # Pad to 6 digits
        return symbol.zfill(6)
    
    def _normalize_symbol_for_kline(self, symbol: str) -> str:
        """
        Normalize symbol for K-line API (code.market format)
        
        Args:
            symbol: Stock symbol (e.g., '000001', '000001.SH', 'SH000001')
            
        Returns:
            Symbol in format like '000001.SZ' or '600519.SH'
        """
        symbol = symbol.strip().upper()
        
        exchange = ''
        code = symbol
        
        # Remove exchange suffixes
        for suffix in ['.SZ', '.SH', '.BJ', '.SHANGHAI', '.BEIJING']:
            if symbol.endswith(suffix):
                exchange = symbol[-2:].upper()
                code = symbol[:-3]
                break
        
        # Handle prefixes like SZ000001 or SH600519
        if not exchange:
            for prefix in ['SZ', 'SH', 'BJ']:
                if symbol.startswith(prefix) and len(symbol) == 8:
                    exchange = prefix
                    code = symbol[2:]
                    break
        
        # Pad to 6 digits
        code = code.zfill(6)
        
        # Default to SZ for codes starting with 0, 1, 3
        # Default to SH for codes starting with 6, 9
        if not exchange:
            if code.startswith(('0', '1', '3')):
                exchange = 'SZ'
            else:
                exchange = 'SH'
        
        return f"{code}.{exchange}"
    
    def _to_float(self, value: Any) -> Optional[float]:
        """Safe float conversion"""
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    
    def _parse_realtime_quote(self, data: Dict) -> Dict[str, Any]:
        """Parse realtime quote response to standardized dict"""
        if not data:
            return {}
        
        return {
            'name': data.get('name', ''),
            'symbol': data.get('code', ''),
            'price': self._to_float(data.get('p')),
            'change': self._to_float(data.get('ud')),
            'change_percent': self._to_float(data.get('pc')),
            'volume': self._to_float(data.get('v')),
            'open': self._to_float(data.get('o')),
            'high': self._to_float(data.get('h')),
            'low': self._to_float(data.get('l')),
            'pre_close': self._to_float(data.get('yc')),
            'amount': self._to_float(data.get('cje')),
            'turnover_rate': self._to_float(data.get('hs')),
            'pe_ratio': self._to_float(data.get('pe')),
            'total_market_cap': self._to_float(data.get('sz')),
            'float_market_cap': self._to_float(data.get('lt')),
            'amplitude': self._to_float(data.get('zf')),
            'timestamp': data.get('t', ''),
        }
    
    def _parse_kline(self, data: list) -> pd.DataFrame:
        """Parse K-line response to DataFrame"""
        if not data or not isinstance(data, list):
            return pd.DataFrame()
        
        records = []
        for item in data:
            if isinstance(item, dict):
                records.append({
                    'date': item.get('t', ''),
                    'open': self._to_float(item.get('o', 0)),
                    'close': self._to_float(item.get('c', 0)),
                    'high': self._to_float(item.get('h', 0)),
                    'low': self._to_float(item.get('l', 0)),
                    'volume': self._to_float(item.get('v', 0)),
                    'amount': self._to_float(item.get('a', 0)),
                    'pre_close': self._to_float(item.get('pc', 0)),
                })
        
        if not records:
            return pd.DataFrame()
        
        df = pd.DataFrame(records)
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        df = df.sort_index()
        
        return df
    
    def get_realtime_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get real-time quote data
        
        Args:
            symbol: Stock symbol (6-digit or with prefix/suffix)
            
        Returns:
            Dictionary with real-time quote data or None
        """
        code = self._normalize_symbol_for_realtime(symbol)
        url = f"{self.BASE_URL}/hsrl/ssjy/{code}/{self.licence}"
        
        data = self._make_request(url)
        
        if data is None or isinstance(data, dict) and 'detail' in data:
            return None
        
        return self._parse_realtime_quote(data)
    
    def get_kline(
        self,
        symbol: str,
        period: str = "day",
        count: int = 120,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        adjust: str = "none"  # none, forward, backward
    ) -> Optional[pd.DataFrame]:
        """
        Get K-line data
        
        Args:
            symbol: Stock symbol (6-digit or with prefix/suffix)
            period: K-line period ('1m', '5m', '15m', '30m', '60m', 'day', 'week', 'month', 'year')
            count: Number of records to retrieve (max 5 for minute bars, more for daily+)
            start_date: Start date (YYYY-MM-DD) - optional
            end_date: End date (YYYY-MM-DD) - optional
            adjust: Price adjustment ('none', 'forward', 'backward')
            
        Returns:
            DataFrame with columns: date(index), open, close, high, low, volume or None
        """
        symbol_market = self._normalize_symbol_for_kline(symbol)
        period = period.lower()
        
        # Get Mairui period code
        mairui_period = self.PERIOD_MAP.get(period)
        if mairui_period is None:
            print(f"Unsupported period: {period}, using 'day'")
            mairui_period = 'd'
        
        # Get adjustment code
        adj_map = {'none': 'n', 'forward': 'f', 'backward': 'b', 'fr': 'fr', 'br': 'br'}
        mairui_adj = adj_map.get(adjust.lower(), 'n')
        
        # Build URL: /hsstock/history/{code}.{market}/{period}/{adj}/{licence}
        url = f"{self.BASE_URL}/hsstock/history/{symbol_market}/{mairui_period}/{mairui_adj}/{self.licence}"
        
        # Add query parameters
        params = []
        if count:
            params.append(f"lt={min(count, 100)}")  # Limit max to 100
        if start_date:
            start_str = start_date.replace('-', '')
            params.append(f"st={start_str}")
        if end_date:
            end_str = end_date.replace('-', '')
            params.append(f"et={end_str}")
        
        if params:
            url += "?" + "&".join(params)
        
        data = self._make_request(url)
        
        if data is None or not isinstance(data, list):
            return None
        
        df = self._parse_kline(data)
        
        # Limit results if count is specified
        if count and not df.empty:
            df = df.tail(count)
        
        return df
    
    def get_stock_list(self) -> Optional[pd.DataFrame]:
        """
        Get list of all A-share stocks
        
        Returns:
            DataFrame with columns: dm (code), mc (name), jys (exchange)
        """
        url = f"{self.BASE_URL}/hslt/list/{self.licence}"
        
        data = self._make_request(url)
        
        if data is None or not isinstance(data, list):
            return None
        
        if not data:
            return pd.DataFrame()
        
        df = pd.DataFrame(data)
        if 'dm' in df.columns:
            df = df.rename(columns={'dm': 'code', 'mc': 'name', 'jys': 'exchange'})
        
        return df
    
    def get_fundamental_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get fundamental data from realtime quote
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Dictionary with basic info or None
        """
        quote = self.get_realtime_quote(symbol)
        
        if not quote:
            return None
        
        return {
            'symbol': symbol,
            'name': quote.get('name', ''),
            'market_cap': quote.get('total_market_cap'),
            'float_market_cap': quote.get('float_market_cap'),
            'pe_ratio': quote.get('pe_ratio'),
            'turnover_rate': quote.get('turnover_rate'),
            'source': 'mairui_realtime'
        }


def get_mairui_provider() -> MairuiProvider:
    """Convenience function to create MairuiProvider instance"""
    return MairuiProvider()


# Test function
if __name__ == "__main__":
    print("=" * 60)
    print("MairuiProvider Test")
    print("=" * 60)
    
    # Check if licence is available
    licence = os.environ.get('MAIRUI_LICENCE')
    if not licence:
        print("Using provided test licence...")
        licence = "BDF90534-E1FD-4F16-9CD4-B8F9275AE19F"
    
    try:
        provider = MairuiProvider(licence)
        
        # Test with known A-share stocks
        test_symbols = ["000001", "600519"]  # 平安银行, 贵州茅台
        
        for test_symbol in test_symbols:
            print(f"\n{'='*50}")
            print(f"Testing {test_symbol}")
            print(f"{'='*50}")
            
            print(f"\n1. Testing get_realtime_quote")
            quote = provider.get_realtime_quote(test_symbol)
            if quote:
                print(f"  Name: {quote.get('name')}")
                print(f"  Symbol: {quote.get('symbol')}")
                print(f"  Price: {quote.get('price')}")
                print(f"  Change: {quote.get('change')} ({quote.get('change_percent')}%)")
                print(f"  High/Low: {quote.get('high')}/{quote.get('low')}")
                print(f"  Volume: {quote.get('volume')}")
                print(f"  Amount: {quote.get('amount')}")
                print(f"  PE: {quote.get('pe_ratio')}")
            else:
                print("  Failed to get real-time quote")
            
            print(f"\n2. Testing get_kline (day, count=5)")
            df = provider.get_kline(test_symbol, period="day", count=5)
            if df is not None and not df.empty:
                print(f"  Retrieved {len(df)} records")
                print(df.tail())
            else:
                print("  Failed to get K-line data")
            
            print(f"\n3. Testing get_kline (week, count=3)")
            df = provider.get_kline(test_symbol, period="week", count=3)
            if df is not None and not df.empty:
                print(f"  Retrieved {len(df)} records")
                print(df.tail())
            else:
                print("  Failed to get weekly K-line data")
        
        print(f"\n{'='*50}")
        print("Testing get_stock_list")
        print(f"{'='*50}")
        df = provider.get_stock_list()
        if df is not None and not df.empty:
            print(f"  Retrieved {len(df)} stocks")
            print(df.head())
        else:
            print("  Failed to get stock list")
        
        print("\n" + "=" * 60)
        print("MairuiProvider test complete")
        print("=" * 60)
        
    except ValueError as e:
        print(f"\nError: {e}")
    except Exception as e:
        print(f"\nUnexpected error: {e}")
