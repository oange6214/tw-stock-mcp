import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Optional

import aiohttp
import requests
from bs4 import BeautifulSoup

from tw_stock_mcp.utils.connection_pool import HTTPConnectionPool, get_global_pool
from tw_stock_mcp.utils.performance_monitor import get_global_monitor

logger = logging.getLogger("tw-stock-agent.data_fetcher")

class DataFetcher:
    """台灣股市資料抓取工具（支援連線池的非同步版本）"""
    
    def __init__(self, http_pool: Optional[HTTPConnectionPool] = None):
        # HTTP連線池
        self._http_pool = http_pool
        self._performance_monitor = get_global_monitor()
        
        # 設定請求頭
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache"
        }
        
        # 請求之間的延遲（秒）
        self.delay = 1.0  # Reduced delay with connection pooling
        # 上次請求時間
        self.last_request_time = 0
    
    async def _get_http_pool(self) -> HTTPConnectionPool:
        """獲取HTTP連線池"""
        if self._http_pool is None:
            self._http_pool = await get_global_pool()
        return self._http_pool
    
    async def _delay_request(self):
        """延遲請求，避免過於頻繁的API請求"""
        current_time = time.time()
        elapsed = current_time - self.last_request_time
        
        if elapsed < self.delay:
            await asyncio.sleep(self.delay - elapsed)
        
        self.last_request_time = time.time()
    
    async def fetch_stock_list(self) -> list[dict[str, Any]]:
        """
        抓取台灣上市上櫃股票列表
        
        Returns:
            股票列表，每個項目包含股票代號、名稱、市場別等
        """
        try:
            # Track request for performance monitoring
            self._performance_monitor.record_request()
            
            # 延遲請求
            await self._delay_request()
            
            # 取得HTTP連線池
            http_pool = await self._get_http_pool()
            
            url = "https://isin.twse.com.tw/isin/class_main.jsp?owncode=&stockname=&isincode=&market=1&issuetype=1&industry_code=&Page=1&chklike=Y"
            
            # 使用連線池進行請求
            html_content = await http_pool.get_text(url, encoding="big5", headers=self.headers)
            
            # 解析HTML表格
            soup = BeautifulSoup(html_content, "html.parser")
            table = soup.find("table", {"class": "h4"})
            
            stocks = []
            if table:
                rows = table.find_all("tr")
                for row in rows[1:]:  # 跳過標題行
                    cells = row.find_all("td")
                    if len(cells) >= 7:
                        # 解析每一列
                        stock_info = cells[0].text.strip().split("　")
                        if len(stock_info) >= 2:
                            stock_id = stock_info[0].strip()
                            stock_name = stock_info[1].strip()
                            
                            stocks.append({
                                "stock_id": stock_id,
                                "name": stock_name,
                                "market": "TWSE",  # 台灣證券交易所
                                "industry": cells[4].text.strip()
                            })
            
            logger.info(f"成功抓取 {len(stocks)} 支上市股票資料")
            return stocks
        
        except Exception as e:
            self._performance_monitor.record_error()
            logger.error(f"抓取股票列表時出錯: {e!s}")
            return []
    
    async def fetch_daily_price(self, stock_id: str, date: datetime) -> dict[str, Any] | None:
        """
        抓取指定日期的股票價格
        
        Args:
            stock_id: 股票代號
            date: 日期
            
        Returns:
            價格資料，包含開盤價、最高價、最低價、收盤價、成交量等
        """
        try:
            # Track request for performance monitoring
            self._performance_monitor.record_request()
            
            # 延遲請求
            await self._delay_request()
            
            # 取得HTTP連線池
            http_pool = await self._get_http_pool()
            
            date_str = date.strftime("%Y%m%d")
            url = f"https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={date_str}&stockNo={stock_id}"
            
            # 使用連線池進行請求
            data = await http_pool.get_json(url, headers=self.headers)
            
            if data["stat"] == "OK" and "data" in data:
                # 取得指定日期的資料
                target_date_str = date.strftime("%Y/%m/%d")
                for item in data["data"]:
                    if item[0] == target_date_str:
                        return {
                            "date": date.strftime("%Y-%m-%d"),
                            "open": float(item[3].replace(",", "")),
                            "high": float(item[4].replace(",", "")),
                            "low": float(item[5].replace(",", "")),
                            "close": float(item[6].replace(",", "")),
                            "volume": int(item[8].replace(",", ""))
                        }
            
            logger.debug(f"找不到股票 {stock_id} 在 {date_str} 的價格資料")
            return None
        
        except Exception as e:
            self._performance_monitor.record_error()
            logger.error(f"抓取股票 {stock_id} 在 {date_str} 的價格資料時出錯: {e!s}")
            return None
    
    async def fetch_monthly_price(self, stock_id: str, year: int, month: int) -> list[dict[str, Any]]:
        """
        抓取指定月份的股票價格
        
        Args:
            stock_id: 股票代號
            year: 年份
            month: 月份
            
        Returns:
            價格資料列表
        """
        try:
            # Track request for performance monitoring
            self._performance_monitor.record_request()
            
            # 延遲請求
            await self._delay_request()
            
            # 取得HTTP連線池
            http_pool = await self._get_http_pool()
            
            date_str = f"{year}{month:02d}01"  # 格式：YYYYMMDD
            url = f"https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={date_str}&stockNo={stock_id}"
            
            # 使用連線池進行請求
            data = await http_pool.get_json(url, headers=self.headers)
            
            if data["stat"] == "OK" and "data" in data:
                # 轉換所有日期的資料
                result = []
                for item in data["data"]:
                    # 轉換民國年為西元年
                    date_parts = item[0].split('/')
                    date_obj = datetime(int(date_parts[0]), int(date_parts[1]), int(date_parts[2]))
                    
                    result.append({
                        "date": date_obj.strftime("%Y-%m-%d"),
                        "open": float(item[3].replace(",", "")),
                        "high": float(item[4].replace(",", "")),
                        "low": float(item[5].replace(",", "")),
                        "close": float(item[6].replace(",", "")),
                        "volume": int(item[8].replace(",", ""))
                    })
                
                logger.info(f"成功抓取股票 {stock_id} 在 {year}年{month}月 的 {len(result)} 筆價格資料")
                return result
            
            logger.warning(f"抓取股票 {stock_id} 在 {year}年{month}月 的價格資料失敗，狀態: {data.get('stat')}")
            return []
        
        except Exception as e:
            self._performance_monitor.record_error()
            logger.error(f"抓取股票 {stock_id} 在 {year}年{month}月 的價格資料時出錯: {e!s}")
            return []
    
    async def fetch_institutional_trades(self, stock_id: str, date: datetime) -> dict[str, Any] | None:
        """
        抓取指定日期的三大法人買賣超資料
        
        Args:
            stock_id: 股票代號
            date: 日期
            
        Returns:
            三大法人買賣超資料
        """
        try:
            # Track request for performance monitoring
            self._performance_monitor.record_request()
            
            # 延遲請求
            await self._delay_request()
            
            # TODO: 實作抓取三大法人資料的邏輯
            # 這裡需要實際的API端點和解析邏輯
            
            # 示例返回
            return {
                "date": date.strftime("%Y-%m-%d"),
                "foreign_investors": 0,  # 外資買賣超（張）
                "investment_trust": 0,  # 投信買賣超（張）
                "dealers": 0,  # 自營商買賣超（張）
                "total": 0  # 合計買賣超（張）
            }
        except Exception as e:
            self._performance_monitor.record_error()
            logger.error(f"抓取股票 {stock_id} 在 {date.strftime('%Y-%m-%d')} 的法人資料時出錯: {e!s}")
            return None
    
    async def get_performance_metrics(self) -> dict[str, Any]:
        """獲取數據抓取器的性能指標"""
        metrics = {}
        
        if self._http_pool:
            metrics["http_pool"] = self._http_pool.get_metrics()
        
        if self._performance_monitor:
            metrics["performance_summary"] = self._performance_monitor.get_performance_summary()
        
        return metrics
    
    async def close(self) -> None:
        """關閉數據抓取器並清理資源"""
        if self._http_pool:
            await self._http_pool.close()
            self._http_pool = None
        logger.info("DataFetcher已關閉")
    
    async def __aenter__(self):
        """Async context manager entry"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()


# Backward compatible sync wrapper for legacy code
class SyncDataFetcher:
    """同步版本的DataFetcher，為了向後兼容"""
    
    def __init__(self):
        self._async_fetcher = DataFetcher()
        self._loop = None
    
    def _run_async(self, coro):
        """執行異步協程"""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If we're already in an async context, we can't use run_until_complete
                raise RuntimeError("SyncDataFetcher cannot be used within an async context. Use DataFetcher directly.")
            return loop.run_until_complete(coro)
        except RuntimeError:
            # No event loop, create a new one
            return asyncio.run(coro)
    
    def fetch_stock_list(self) -> list[dict[str, Any]]:
        """同步版本的抓取股票列表"""
        return self._run_async(self._async_fetcher.fetch_stock_list())
    
    def fetch_daily_price(self, stock_id: str, date: datetime) -> dict[str, Any] | None:
        """同步版本的抓取日價格"""
        return self._run_async(self._async_fetcher.fetch_daily_price(stock_id, date))
    
    def fetch_monthly_price(self, stock_id: str, year: int, month: int) -> list[dict[str, Any]]:
        """同步版本的抓取月價格"""
        return self._run_async(self._async_fetcher.fetch_monthly_price(stock_id, year, month))
    
    def fetch_institutional_trades(self, stock_id: str, date: datetime) -> dict[str, Any] | None:
        """同步版本的抓取法人資料"""
        return self._run_async(self._async_fetcher.fetch_institutional_trades(stock_id, date))
    
    def close(self) -> None:
        """關閉同步數據抓取器"""
        self._run_async(self._async_fetcher.close())
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()