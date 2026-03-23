"""
AkShare A-share data provider
提供 A 股实时行情、历史 K 线、财务数据、新闻数据
"""
from typing import Optional, Dict, List, Any
import logging
import pandas as pd
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class AkShareProvider:
    """AkShare 数据提供器"""
    
    def __init__(self):
        self._ak = None
        self._initialize()
    
    def _initialize(self):
        """初始化 AkShare"""
        try:
            import akshare as ak
            self._ak = ak
            logger.info("✅ AkShare 初始化成功")
        except ImportError:
            logger.error("❌ AkShare 未安装，请运行: pip install akshare")
            self._ak = None
    
    def is_available(self) -> bool:
        """检查 AkShare 是否可用"""
        return self._ak is not None
    
    def _convert_symbol(self, symbol: str) -> str:
        """转换股票代码格式"""
        return str(symbol).zfill(6)
    
    def get_realtime_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        获取 A 股实时行情
        
        Args:
            symbol: 股票代码，如 "000001"
            
        Returns:
            Dict: {
                "symbol": str,
                "price": float,
                "change": float,
                "volume": int,
                "turnover": float,
                "open": float,
                "high": float,
                "low": float,
                "pre_close": float
            }
        """
        if not self.is_available():
            return None
        
        try:
            symbol = self._convert_symbol(symbol)
            
            # 获取全市场实时行情
            df = self._ak.stock_zh_a_spot_em()
            
            # 筛选指定股票
            row = df[df["代码"] == symbol]
            
            if row.empty:
                logger.warning(f"⚠️ AkShare: 未找到股票 {symbol}")
                return None
            
            result = {
                "symbol": symbol,
                "price": float(row["最新价"].values[0]) if pd.notna(row["最新价"].values[0]) else None,
                "change": float(row["涨跌幅"].values[0]) if pd.notna(row["涨跌幅"].values[0]) else None,
                "volume": int(row["成交量"].values[0]) if pd.notna(row["成交量"].values[0]) else None,
                "turnover": float(row["成交额"].values[0]) if pd.notna(row["成交额"].values[0]) else None,
                "open": float(row["今开"].values[0]) if pd.notna(row["今开"].values[0]) else None,
                "high": float(row["最高"].values[0]) if pd.notna(row["最高"].values[0]) else None,
                "low": float(row["最低"].values[0]) if pd.notna(row["最低"].values[0]) else None,
                "pre_close": float(row["昨收"].values[0]) if pd.notna(row["昨收"].values[0]) else None,
            }
            
            logger.info(f"✅ AkShare: 获取 {symbol} 实时行情成功")
            return result
            
        except Exception as e:
            logger.error(f"❌ AkShare: 获取实时行情失败 {symbol}: {e}")
            return None
    
    def get_daily_hist(self, symbol: str, days: int = 120) -> Optional[pd.DataFrame]:
        """
        获取历史日线数据
        
        Args:
            symbol: 股票代码
            days: 获取天数
            
        Returns:
            DataFrame: 历史数据
        """
        if not self.is_available():
            return None
        
        try:
            symbol = self._convert_symbol(symbol)
            
            # 计算起始日期
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
            
            # 获取历史数据
            df = self._ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq"  # 前复权
            )
            
            if df is None or df.empty:
                logger.warning(f"⚠️ AkShare: 未找到历史数据 {symbol}")
                return None
            
            # 标准化列名
            df = df.rename(columns={
                "日期": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount",
                "振幅": "amplitude",
                "涨跌幅": "pct_change",
                "涨跌额": "change",
                "换手率": "turnover"
            })
            
            logger.info(f"✅ AkShare: 获取 {symbol} 历史数据 {len(df)} 条")
            return df
            
        except Exception as e:
            logger.error(f"❌ AkShare: 获取历史数据失败 {symbol}: {e}")
            return None
    
    def get_fundamental_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        获取财务数据
        
        Args:
            symbol: 股票代码
            
        Returns:
            Dict: 财务指标
        """
        if not self.is_available():
            return None
        
        try:
            symbol = self._convert_symbol(symbol)
            
            # 获取个股信息
            df = self._ak.stock_individual_info_em(symbol=symbol)
            
            if df is None or df.empty:
                return None
            
            # 转换为字典
            info_dict = {}
            for _, row in df.iterrows():
                item = row.get("item", "")
                value = row.get("value", "")
                info_dict[item] = value
            
            # 提取关键指标
            result = {
                "symbol": symbol,
                "name": info_dict.get("股票简称", ""),
                "pe": self._safe_float(info_dict.get("市盈率")),
                "pb": self._safe_float(info_dict.get("市净率")),
                "total_mv": self._safe_float(info_dict.get("总市值")),
                "circulating_mv": self._safe_float(info_dict.get("流通市值")),
                "industry": info_dict.get("行业", ""),
            }
            
            logger.info(f"✅ AkShare: 获取 {symbol} 财务数据成功")
            return result
            
        except Exception as e:
            logger.error(f"❌ AkShare: 获取财务数据失败 {symbol}: {e}")
            return None
    
    def get_news(self, symbol: str, limit: int = 10) -> Optional[List[Dict[str, Any]]]:
        """
        获取新闻数据
        
        Args:
            symbol: 股票代码
            limit: 获取条数
            
        Returns:
            List[Dict]: 新闻列表
        """
        if not self.is_available():
            return None
        
        try:
            symbol = self._convert_symbol(symbol)
            
            # 获取新闻
            df = self._ak.stock_news_em(symbol=symbol)
            
            if df is None or df.empty:
                return []
            
            # 限制条数
            df = df.head(limit)
            
            # 转换为列表
            news_list = []
            for _, row in df.iterrows():
                news_list.append({
                    "title": row.get("标题", ""),
                    "content": row.get("内容", ""),
                    "source": row.get("来源", ""),
                    "time": row.get("发布时间", ""),
                    "url": row.get("链接", ""),
                })
            
            logger.info(f"✅ AkShare: 获取 {symbol} 新闻 {len(news_list)} 条")
            return news_list
            
        except Exception as e:
            logger.error(f"❌ AkShare: 获取新闻失败 {symbol}: {e}")
            return []
    
    def get_kline(self, symbol: str, period: str = "day", limit: int = 120) -> Optional[pd.DataFrame]:
        """
        获取 K 线数据（统一接口）
        
        Args:
            symbol: 股票代码
            period: 周期 (day/week/month)
            limit: 获取条数
            
        Returns:
            DataFrame: K 线数据
        """
        if not self.is_available():
            return None
        
        try:
            symbol = self._convert_symbol(symbol)
            
            # 周期映射
            period_map = {
                "day": "daily",
                "week": "weekly",
                "month": "monthly"
            }
            ak_period = period_map.get(period, "daily")
            
            # 计算日期范围
            if period == "day":
                days = limit
            elif period == "week":
                days = limit * 7
            else:  # month
                days = limit * 30
            
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
            
            # 获取数据
            df = self._ak.stock_zh_a_hist(
                symbol=symbol,
                period=ak_period,
                start_date=start_date,
                end_date=end_date,
                adjust="qfq"
            )
            
            if df is None or df.empty:
                return None
            
            # 限制条数
            df = df.tail(limit)
            
            # 标准化列名
            df = df.rename(columns={
                "日期": "time",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount",
            })
            
            return df
            
        except Exception as e:
            logger.error(f"❌ AkShare: 获取 K 线失败 {symbol}: {e}")
            return None
    
    def _safe_float(self, value) -> Optional[float]:
        """安全转换为 float"""
        try:
            if value is None or value == "" or pd.isna(value):
                return None
            return float(value)
        except (ValueError, TypeError):
            return None
