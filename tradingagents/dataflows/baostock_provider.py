"""
BaoStock A-share data provider
提供 A 股历史 K 线数据，支持多种复权方式
"""
from typing import Optional, Dict, List, Any
import logging
import pandas as pd
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class BaoStockProvider:
    """BaoStock 数据提供器"""
    
    def __init__(self):
        self._bs = None
        self._logged_in = False
        self._initialize()
    
    def _initialize(self):
        """初始化 BaoStock"""
        try:
            import baostock as bs
            self._bs = bs
            logger.info("✅ BaoStock 库加载成功")
        except ImportError:
            logger.error("❌ BaoStock 未安装，请运行: pip install baostock")
            self._bs = None
    
    def is_available(self) -> bool:
        """检查 BaoStock 是否可用"""
        return self._bs is not None
    
    def login(self) -> bool:
        """
        登录 BaoStock
        
        Returns:
            bool: 是否登录成功
        """
        if not self.is_available():
            return False
        
        try:
            result = self._bs.login()
            if result.error_code == "0":
                self._logged_in = True
                logger.info("✅ BaoStock 登录成功")
                return True
            else:
                logger.error(f"❌ BaoStock 登录失败: {result.error_msg}")
                return False
        except Exception as e:
            logger.error(f"❌ BaoStock 登录异常: {e}")
            return False
    
    def logout(self):
        """登出 BaoStock"""
        if self._logged_in and self._bs:
            try:
                self._bs.logout()
                self._logged_in = False
                logger.info("✅ BaoStock 登出成功")
            except Exception as e:
                logger.warning(f"⚠️ BaoStock 登出异常: {e}")
    
    def _ensure_login(self) -> bool:
        """确保已登录"""
        if not self._logged_in:
            return self.login()
        return True
    
    def _convert_symbol(self, symbol: str) -> str:
        """
        转换股票代码为 BaoStock 格式
        
        Args:
            symbol: 股票代码，如 "000001"
            
        Returns:
            BaoStock 格式，如 "sz.000001" 或 "sh.600000"
        """
        symbol = str(symbol).zfill(6)
        if symbol.startswith(("0", "3")):
            return f"sz.{symbol}"
        else:
            return f"sh.{symbol}"
    
    def get_kline(
        self,
        symbol: str,
        frequency: str = "d",
        count: int = 120,
        adjustflag: str = "3"
    ) -> Optional[pd.DataFrame]:
        """
        获取 K 线数据
        
        Args:
            symbol: 股票代码，如 "000001"
            frequency: 频率
                - "d": 日线
                - "w": 周线
                - "m": 月线
                - "5": 5分钟线
                - "15": 15分钟线
                - "30": 30分钟线
                - "60": 60分钟线
            count: 获取条数
            adjustflag: 复权类型
                - "1": 后复权
                - "2": 前复权
                - "3": 不复权（默认）
                
        Returns:
            DataFrame: K 线数据，列包括 date, open, high, low, close, volume, amount
        """
        if not self._ensure_login():
            return None
        
        try:
            bs_symbol = self._convert_symbol(symbol)
            
            # 计算起始日期
            end_date = datetime.now().strftime("%Y-%m-%d")
            
            # 根据条数估算起始日期
            if frequency in ["d", "w", "m"]:
                # 日线、周线、月线
                if frequency == "d":
                    start_date = (datetime.now() - timedelta(days=count * 1.5)).strftime("%Y-%m-%d")
                elif frequency == "w":
                    start_date = (datetime.now() - timedelta(weeks=count * 1.5)).strftime("%Y-%m-%d")
                else:  # month
                    start_date = (datetime.now() - timedelta(days=count * 30 * 1.5)).strftime("%Y-%m-%d")
            else:
                # 分钟线，获取最近几个交易日
                start_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
            
            # 查询数据
            rs = self._bs.query_history_k_data_plus(
                bs_symbol,
                "date,open,high,low,close,volume,amount",
                start_date=start_date,
                end_date=end_date,
                frequency=frequency,
                adjustflag=adjustflag
            )
            
            if rs.error_code != "0":
                logger.error(f"❌ BaoStock 查询失败: {rs.error_msg}")
                return None
            
            # 转换为 DataFrame
            data_list = []
            while (rs.error_code == "0") & rs.next():
                row = rs.get_row_data()
                data_list.append({
                    "date": row[0],
                    "open": float(row[1]) if row[1] else None,
                    "high": float(row[2]) if row[2] else None,
                    "low": float(row[3]) if row[3] else None,
                    "close": float(row[4]) if row[4] else None,
                    "volume": int(float(row[5])) if row[5] else None,
                    "amount": float(row[6]) if row[6] else None,
                })
            
            if not data_list:
                logger.warning(f"⚠️ BaoStock: 未找到数据 {symbol}")
                return None
            
            df = pd.DataFrame(data_list)
            
            # 限制条数
            df = df.tail(count)
            
            # 标准化列名
            df = df.rename(columns={
                "date": "time"
            })
            
            logger.info(f"✅ BaoStock: 获取 {symbol} K 线 {len(df)} 条")
            return df
            
        except Exception as e:
            logger.error(f"❌ BaoStock: 获取 K 线失败 {symbol}: {e}")
            return None
    
    def get_daily_hist(
        self,
        symbol: str,
        days: int = 120,
        adjustflag: str = "2"
    ) -> Optional[pd.DataFrame]:
        """
        获取历史日线数据（简化接口）
        
        Args:
            symbol: 股票代码
            days: 获取天数
            adjustflag: 复权类型，默认"2"前复权
            
        Returns:
            DataFrame: 历史数据
        """
        return self.get_kline(symbol, frequency="d", count=days, adjustflag=adjustflag)
    
    def get_stock_basic_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        获取股票基本信息
        
        Args:
            symbol: 股票代码
            
        Returns:
            Dict: 股票基本信息
        """
        if not self._ensure_login():
            return None
        
        try:
            bs_symbol = self._convert_symbol(symbol)
            
            # 查询证券基本资料
            rs = self._bs.query_stock_basic(code=bs_symbol)
            
            if rs.error_code != "0":
                logger.error(f"❌ BaoStock 查询基本信息失败: {rs.error_msg}")
                return None
            
            # 获取第一条数据
            if rs.next():
                data = rs.get_row_data()
                return {
                    "symbol": symbol,
                    "code": data[0],
                    "code_name": data[1],
                    "ipo_date": data[2],
                    "out_date": data[3],
                    "type": data[4],
                    "status": data[5],
                }
            else:
                return None
                
        except Exception as e:
            logger.error(f"❌ BaoStock: 获取基本信息失败 {symbol}: {e}")
            return None
    
    def __del__(self):
        """析构时登出"""
        self.logout()
