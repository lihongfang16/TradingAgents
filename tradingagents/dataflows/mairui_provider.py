"""
Mairui Data Provider for A-Share Stocks
Provides real-time quotes and K-line data via Mairui API
"""

import os
import requests
import pandas as pd
from typing import Optional, Dict, Any
from datetime import datetime


class MairuiProvider:
    """
    Mairui Data Provider for A-Share stocks
    API Documentation: https://api.mairuiapi.com
    """
    
    BASE_URL = "https://api.mairuiapi.com"
    
    # Map friendly period names to Mairui API klt values
    PERIOD_MAP = {
        # Minute bars
        '1m': '1',
        '5m': '5',
        '15m': '15',
        '30m': '30',
        '60m': '60',
        # Daily/Weekly/Monthly
        'day': '101',
        'daily': '101',
        '1d': '101',
        'week': '102',
        'weekly': '102',
        'month': '103',
        'monthly': '103',
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
    
    def _make_request(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict]:
        """
        Make HTTP GET request to Mairui API
        
        Args:
            endpoint: API endpoint path
            params: Query parameters (licence will be added automatically)
            
        Returns:
            JSON response as dict or None on error
        """
        url = f"{self.BASE_URL}{endpoint}"
        
        if params is None:
            params = {}
        
        params['licence'] = self.licence
        
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Mairui API request error: {e}")
            return None
        except ValueError as e:
            print(f"Mairui API JSON parse error: {e}")
            return None
    
    def _normalize_symbol(self, symbol: str) -> str:
        """
        Normalize symbol to 6-digit format
        
        Args:
            symbol: Stock symbol (e.g., '000001', '000001.SH', 'SH000001')
            
        Returns:
            Normalized 6-digit symbol
        """
        symbol = symbol.strip().upper()
        
        # Remove exchange suffixes
        for suffix in ['.SZ', '.SH', '.BJ', '.SHANGHAI', '.BEIJING']:
            if symbol.endswith(suffix):
                symbol = symbol[:-len(suffix)]
                break
        
        # Remove exchange prefixes
        for prefix in ['SZ', 'SH', 'BJ']:
            if symbol.startswith(prefix):
                symbol = symbol[len(prefix):]
                break
        
        # Pad to 6 digits
        symbol = symbol.zfill(6)
        
        return symbol
    
    def _to_float(self, value: Any) -> Optional[float]:
        """
        Safe float conversion
        
        Args:
            value: Value to convert
            
        Returns:
            Float value or None on conversion error
        """
        if value is None:
            return None
        
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    
    def _parse_quote(self, data: Dict) -> Dict[str, Any]:
        """
        Parse Mairui API quote response to standardized dict
        
        Args:
            data: Raw API response dict
            
        Returns:
            Standardized quote dictionary
        """
        if not data:
            return {}
        
        return {
            'name': data.get('name', ''),
            'symbol': data.get('code', ''),
            'price': self._to_float(data.get('price')),
            'change': self._to_float(data.get('zd', 0)),
            'change_percent': self._to_float(data.get('zdf', 0)),
            'volume': self._to_float(data.get('vol', 0)),
            'open': self._to_float(data.get('open', 0)),
            'high': self._to_float(data.get('high', 0)),
            'low': self._to_float(data.get('low', 0)),
            'pre_close': self._to_float(data.get('pcls', 0)),
        }
    
    def _parse_kline(self, data: list) -> pd.DataFrame:
        """
        Parse Mairui API K-line response to DataFrame
        
        Args:
            data: Raw API response list
            
        Returns:
            DataFrame with columns: date(index), open, close, high, low, volume
        """
        if not data or not isinstance(data, list):
            return pd.DataFrame()
        
        records = []
        for item in data:
            if isinstance(item, dict):
                records.append({
                    'date': item.get('date', ''),
                    'open': self._to_float(item.get('open', 0)),
                    'close': self._to_float(item.get('close', 0)),
                    'high': self._to_float(item.get('high', 0)),
                    'low': self._to_float(item.get('low', 0)),
                    'volume': self._to_float(item.get('vol', 0)),
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
            symbol: Stock symbol (6-digit or with prefix)
            
        Returns:
            Dictionary with real-time quote data or None
        """
        symbol = self._normalize_symbol(symbol)
        
        endpoint = f"/hsrl/ssgs/{symbol}"
        data = self._make_request(endpoint)
        
        if data is None:
            return None
        
        return self._parse_quote(data)
    
    def get_kline(
        self,
        symbol: str,
        period: str = "day",
        count: int = 120,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Optional[pd.DataFrame]:
        """
        Get K-line data
        
        Args:
            symbol: Stock symbol (6-digit or with prefix)
            period: K-line period ('1m', '5m', '15m', '30m', '60m', 'day', 'week', 'month')
            count: Number of records to retrieve
            start_date: Start date (YYYY-MM-DD), not used in Mairui API
            end_date: End date (YYYY-MM-DD), not used in Mairui API
            
        Returns:
            DataFrame with columns: date(index), open, close, high, low, volume or None
        """
        symbol = self._normalize_symbol(symbol)
        period = period.lower()
        
        # Get Mairui period code
        mairui_period = self.PERIOD_MAP.get(period)
        if mairui_period is None:
            print(f"Unsupported period: {period}, using 'day'")
            mairui_period = '101'
        
        endpoint = f"/hslt/kline/{symbol}"
        params = {'klt': mairui_period}
        
        data = self._make_request(endpoint, params)
        
        if data is None or not isinstance(data, list):
            return None
        
        df = self._parse_kline(data)
        
        # Limit results if count is specified
        if count and not df.empty:
            df = df.tail(count)
        
        return df
    
    def get_fundamental_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get fundamental data
        Note: Mairui API doesn't provide detailed fundamental data
        Returns basic info from real-time quote
        
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
            'market_cap': None,  # Not available in Mairui API
            'pe_ratio': None,
            'pb_ratio': None,
            'dividend_yield': None,
            'eps': None,
            'source': 'mairui_basic'
        }


def get_mairui_provider() -> MairuiProvider:
    """
    Convenience function to create MairuiProvider instance
    
    Returns:
        MairuiProvider instance
    """
    return MairuiProvider()


# Test function
if __name__ == "__main__":
    print("=" * 60)
    print("MairuiProvider Test")
    print("=" * 60)
    
    # Check if licence is available
    licence = os.environ.get('MAIRUI_LICENCE')
    if not licence:
        print("WARNING: MAIRUI_LICENCE env var not set")
        print("Set it with: export MAIRUI_LICENCE=your_licence_key")
        print("Using placeholder for testing...")
        # Use a test licence for demonstration
        licence = "TEST_LICENCE"
    
    try:
        provider = MairuiProvider(licence)
        
        # Test with a known A-share stock
        test_symbol = "000001"  # 平安银行
        
        print(f"\n1. Testing get_realtime_quote for {test_symbol}")
        quote = provider.get_realtime_quote(test_symbol)
        if quote:
            print(f"  Name: {quote.get('name')}")
            print(f"  Price: {quote.get('price')}")
            print(f"  Change: {quote.get('change')} ({quote.get('change_percent')}%)")
            print(f"  High/Low: {quote.get('high')}/{quote.get('low')}")
            print(f"  Volume: {quote.get('volume')}")
        else:
            print("  Failed to get real-time quote (check licence/API)")
        
        print(f"\n2. Testing get_kline for {test_symbol} (day)")
        df = provider.get_kline(test_symbol, period="day", count=5)
        if df is not None and not df.empty:
            print(f"  Retrieved {len(df)} records")
            print(df.tail())
        else:
            print("  Failed to get K-line data (check licence/API)")
        
        print(f"\n3. Testing get_kline for {test_symbol} (week)")
        df = provider.get_kline(test_symbol, period="week", count=3)
        if df is not None and not df.empty:
            print(f"  Retrieved {len(df)} records")
            print(df.tail())
        else:
            print("  Failed to get weekly K-line data")
        
        print(f"\n4. Testing get_kline for {test_symbol} (1m)")
        df = provider.get_kline(test_symbol, period="1m", count=5)
        if df is not None and not df.empty:
            print(f"  Retrieved {len(df)} records")
            print(df.tail())
        else:
            print("  Failed to get minute K-line data")
        
        print(f"\n5. Testing get_fundamental_data for {test_symbol}")
        fundamental = provider.get_fundamental_data(test_symbol)
        if fundamental:
            print(f"  Name: {fundamental.get('name')}")
            print(f"  Source: {fundamental.get('source')}")
        else:
            print("  Failed to get fundamental data")
        
        print("\n" + "=" * 60)
        print("MairuiProvider test complete")
        print("=" * 60)
        
    except ValueError as e:
        print(f"\nError: {e}")
        print("Please set MAIRUI_LICENCE environment variable with your API licence")
    except Exception as e:
        print(f"\nUnexpected error: {e}")
