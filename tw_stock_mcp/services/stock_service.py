import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from tw_stock_mcp.exceptions import (
    CacheError,
    ErrorCode,
    ErrorSeverity,
    ExternalAPIError,
    InvalidStockCodeError,
    StockDataUnavailableError,
    StockNotFoundError,
    TwStockAgentError,
)
from tw_stock_mcp.providers.base import StockDataProvider
from tw_stock_mcp.providers.factory import create_provider
from tw_stock_mcp.services.cache_service import CacheConfig, CacheService
from tw_stock_mcp.utils.connection_pool import HTTPConnectionPool, get_global_pool
from tw_stock_mcp.utils.error_handler import with_async_error_handling, with_retry
from tw_stock_mcp.utils.performance_monitor import get_global_monitor
from tw_stock_mcp.utils.validation import StockCodeValidator

logger = logging.getLogger("tw-stock-agent.stock_service")


class StockService:
    """股票資料服務，負責從外部 Provider 抓取資料並提供快取功能。

    Provider 透過建構子注入，預設由 create_provider() 依設定建立。
    切換資料來源只需傳入不同的 provider 實例，其餘邏輯不變。
    """

    def __init__(
        self,
        cache_config: Optional[CacheConfig] = None,
        http_pool: Optional[HTTPConnectionPool] = None,
        provider: Optional[StockDataProvider] = None,
    ) -> None:
        """初始化股票服務。

        Args:
            cache_config: 快取配置，None 時使用預設配置。
            http_pool: HTTP 連線池，None 時使用全域池。
            provider: 資料來源 Provider。None 時由 create_provider() 依
                      STOCK_DATA_PROVIDER 環境變數建立。
        """
        self.cache = CacheService(config=cache_config)
        self.cache_ttl = {
            "stock_data": 86400,        # 24 小時
            "price_data": 1800,         # 30 分鐘
            "realtime": 60,             # 1 分鐘
            "best_four_points": 3600,   # 1 小時
        }
        self._http_pool = http_pool
        self._performance_monitor = get_global_monitor()
        self._provider: StockDataProvider = provider or create_provider()
        self._best_four_points_provider: Optional[StockDataProvider] = None

    # ------------------------------------------------------------------
    # HTTP pool
    # ------------------------------------------------------------------

    async def _get_http_pool(self) -> HTTPConnectionPool:
        if self._http_pool is None:
            self._http_pool = await get_global_pool()
        return self._http_pool

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _get_cached_data(self, key: str) -> Optional[Dict[str, Any]]:
        try:
            return self.cache.get(key)
        except Exception as e:
            logger.warning("Cache get failed for key %s: %s", key, e)
            return None

    def _set_cached_data(
        self,
        key: str,
        data: Dict[str, Any],
        ttl: int,
        tags: Optional[List[str]] = None,
    ) -> None:
        try:
            self.cache.set(key, data, expire=ttl, tags=tags)
        except Exception as e:
            logger.warning("Cache set failed for key %s: %s", key, e)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @with_async_error_handling(operation="fetch_stock_data")
    @with_retry(max_retries=2, base_delay=1.0)
    async def fetch_stock_data(self, stock_code: str) -> dict[str, Any]:
        """抓取股票基本資料。

        Args:
            stock_code: 股票代號

        Returns:
            股票基本資料

        Raises:
            InvalidStockCodeError: 股票代號格式錯誤
            StockNotFoundError: 找不到股票
            StockDataUnavailableError: 股票資料無法取得
        """
        self._performance_monitor.record_request()
        validated_code = StockCodeValidator.validate_stock_code(stock_code)

        cache_key = f"stock_data_{validated_code}"
        cached = self._get_cached_data(cache_key)
        if cached:
            return cached

        try:
            data = await self._provider.get_stock_info(validated_code)
        except (StockNotFoundError, StockDataUnavailableError):
            self._performance_monitor.record_error()
            raise

        tags = ["stock_data", data.get("market", ""), data.get("type", "")]
        self._set_cached_data(cache_key, data, self.cache_ttl["stock_data"], tags)
        return data

    @with_async_error_handling(operation="fetch_price_data")
    @with_retry(max_retries=2, base_delay=1.0)
    async def fetch_price_data(
        self, stock_code: str, days: int = 30
    ) -> list[dict[str, Any]]:
        """抓取股票價格資料。

        Args:
            stock_code: 股票代號
            days: 資料天數

        Returns:
            價格資料列表

        Raises:
            InvalidStockCodeError: 股票代號格式錯誤
            StockDataUnavailableError: 價格資料無法取得
        """
        self._performance_monitor.record_request()
        validated_code = StockCodeValidator.validate_stock_code(stock_code)

        if days <= 0 or days > 3650:
            from tw_stock_mcp.exceptions import RangeValidationError

            raise RangeValidationError(
                field_name="days", value=days, min_value=1, max_value=3650
            )

        cache_key = f"price_data_{validated_code}_{days}"
        cached = self._get_cached_data(cache_key)
        if cached:
            if isinstance(cached, dict) and "data" in cached:
                return cached["data"]
            return cached

        try:
            data = await self._provider.get_price_history(validated_code, days)
        except StockDataUnavailableError:
            self._performance_monitor.record_error()
            raise

        cache_data = {
            "data": data,
            "metadata": {
                "stock_code": validated_code,
                "days": days,
                "actual_records": len(data),
            },
        }
        tags = ["price_data", f"stock_{validated_code}", f"days_{days}"]
        self._set_cached_data(
            cache_key, cache_data, self.cache_ttl["price_data"], tags
        )
        return data

    @with_async_error_handling(operation="get_best_four_points")
    @with_retry(max_retries=2, base_delay=1.0)
    async def get_best_four_points(self, stock_code: str) -> dict[str, Any]:
        """獲取四大買賣點分析。

        Args:
            stock_code: 股票代號

        Returns:
            四大買賣點分析結果

        Raises:
            InvalidStockCodeError: 股票代號格式錯誤
            StockDataUnavailableError: 分析資料無法取得
        """
        self._performance_monitor.record_request()
        validated_code = StockCodeValidator.validate_stock_code(stock_code)

        cache_key = f"best_four_points_{validated_code}"
        cached = self._get_cached_data(cache_key)
        if cached:
            return cached

        try:
            data = await self._provider.get_best_four_points(validated_code)
        except StockDataUnavailableError:
            data = await self._get_best_four_points_with_fallback(validated_code)

        tags = ["best_four_points", f"stock_{validated_code}", "analysis"]
        self._set_cached_data(
            cache_key, data, self.cache_ttl["best_four_points"], tags
        )
        return data

    async def _get_best_four_points_with_fallback(
        self, stock_code: str
    ) -> dict[str, Any]:
        """Fallback to twstock for analytics-only capabilities."""
        self._performance_monitor.record_error()

        if self._provider.__class__.__name__ == "TwstockProvider":
            raise StockDataUnavailableError(
                stock_code=stock_code,
                data_type="analysis data",
                message="Best Four Points analysis is unavailable for this stock",
            )

        if self._best_four_points_provider is None:
            self._best_four_points_provider = create_provider(name="twstock")

        logger.info(
            "Falling back to twstock provider for Best Four Points: %s", stock_code
        )
        return await self._best_four_points_provider.get_best_four_points(stock_code)

    @with_async_error_handling(operation="get_realtime_data")
    @with_retry(max_retries=1, base_delay=0.5)
    async def get_realtime_data(self, stock_code: str) -> dict[str, Any]:
        """獲取即時股票資訊。

        Args:
            stock_code: 股票代號

        Returns:
            即時股票資訊

        Raises:
            InvalidStockCodeError: 股票代號格式錯誤
            StockNotFoundError: 找不到股票
            StockDataUnavailableError: 即時資料無法取得
            StockMarketClosedError: 股市休市
        """
        self._performance_monitor.record_request()
        validated_code = StockCodeValidator.validate_stock_code(stock_code)

        cache_key = f"realtime_{validated_code}"
        cached = self._get_cached_data(cache_key)
        if cached:
            return cached

        try:
            data = await self._provider.get_realtime_data(validated_code)
        except (StockNotFoundError, StockDataUnavailableError):
            self._performance_monitor.record_error()
            raise

        tags = ["realtime", f"stock_{validated_code}", "live_data"]
        self._set_cached_data(cache_key, data, self.cache_ttl["realtime"], tags)
        return data

    # ------------------------------------------------------------------
    # Batch operations
    # ------------------------------------------------------------------

    @with_async_error_handling(operation="fetch_multiple_stocks_data")
    async def fetch_multiple_stocks_data(
        self, stock_codes: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """批量獲取多支股票的基本資料。"""
        if not stock_codes:
            from tw_stock_mcp.exceptions import ParameterValidationError

            raise ParameterValidationError(
                parameter_name="stock_codes",
                parameter_value=stock_codes,
                expected_format="Non-empty list of stock codes",
            )

        validated_codes = StockCodeValidator.validate_multiple_codes(
            stock_codes, strict=False
        )
        cache_keys = [f"stock_data_{code}" for code in validated_codes]

        try:
            cached_results = self.cache.get_bulk(cache_keys)
        except Exception as e:
            logger.warning("Bulk cache get failed: %s", e)
            cached_results = {}

        results: Dict[str, Dict[str, Any]] = {}
        missing_codes: List[str] = []

        for i, code in enumerate(validated_codes):
            cached = cached_results.get(cache_keys[i])
            if cached:
                results[code] = cached
            else:
                missing_codes.append(code)

        if missing_codes:
            fresh_results = await asyncio.gather(
                *[self.fetch_stock_data(code) for code in missing_codes],
                return_exceptions=True,
            )
            for code, result in zip(missing_codes, fresh_results):
                if isinstance(result, Exception):
                    logger.error("獲取股票 %s 資料時出錯: %s", code, result)
                    results[code] = (
                        {**result.to_dict(), "stock_code": code}
                        if isinstance(result, TwStockAgentError)
                        else {"stock_code": code, "error": str(result), "error_code": "FETCH_FAILED"}
                    )
                else:
                    results[code] = result

        return results

    @with_async_error_handling(operation="fetch_multiple_realtime_data")
    async def fetch_multiple_realtime_data(
        self, stock_codes: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """批量獲取多支股票的即時資料。"""
        if not stock_codes:
            from tw_stock_mcp.exceptions import ParameterValidationError

            raise ParameterValidationError(
                parameter_name="stock_codes",
                parameter_value=stock_codes,
                expected_format="Non-empty list of stock codes",
            )

        validated_codes = StockCodeValidator.validate_multiple_codes(
            stock_codes, strict=False
        )
        cache_keys = [f"realtime_{code}" for code in validated_codes]

        try:
            cached_results = self.cache.get_bulk(cache_keys)
        except Exception as e:
            logger.warning("Bulk cache get failed: %s", e)
            cached_results = {}

        results: Dict[str, Dict[str, Any]] = {}
        missing_codes: List[str] = []

        for i, code in enumerate(validated_codes):
            cached = cached_results.get(cache_keys[i])
            if cached:
                results[code] = cached
            else:
                missing_codes.append(code)

        if missing_codes:
            fresh_results = await asyncio.gather(
                *[self.get_realtime_data(code) for code in missing_codes],
                return_exceptions=True,
            )
            for code, result in zip(missing_codes, fresh_results):
                if isinstance(result, Exception):
                    logger.error("獲取股票 %s 即時資料時出錯: %s", code, result)
                    results[code] = (
                        {**result.to_dict(), "stock_code": code}
                        if isinstance(result, TwStockAgentError)
                        else {"stock_code": code, "error": str(result), "error_code": "FETCH_FAILED"}
                    )
                else:
                    results[code] = result

        return results

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def invalidate_stock_cache(self, stock_code: str) -> int:
        return self.cache.delete_by_pattern(f"%{stock_code}%")

    def invalidate_cache_by_type(self, cache_type: str) -> int:
        return self.cache.delete_by_tags([cache_type])

    def invalidate_market_cache(self, market: str) -> int:
        return self.cache.delete_by_tags([market])

    async def warm_popular_stocks_cache(
        self, stock_codes: List[str]
    ) -> Dict[str, int]:
        """預熱熱門股票的快取資料。"""
        warm_data: Dict[str, Any] = {}

        for code in stock_codes:
            try:
                data = await self._provider.get_stock_info(code)
                warm_data[f"stock_data_{code}"] = data
            except Exception as e:
                logger.error("準備股票 %s 預熱資料時出錯: %s", code, e)

        warmed_count = self.cache.warm_cache(warm_data, self.cache_ttl["stock_data"])
        return {
            "total_requested": len(stock_codes),
            "successfully_warmed": warmed_count,
            "cache_hit_improvement": (
                warmed_count / len(stock_codes) if stock_codes else 0
            ),
        }

    def get_cache_statistics(self) -> Dict[str, Any]:
        stats = self.cache.get_stats()
        return {
            "hit_rate": stats.hit_rate,
            "total_hits": stats.hits,
            "total_misses": stats.misses,
            "total_sets": stats.sets,
            "total_deletes": stats.deletes,
            "total_cleanups": stats.cleanups,
            "total_size_bytes": stats.total_size,
            "cache_breakdown": {
                "stock_data": len(self.cache.get_keys_by_tags(["stock_data"])),
                "price_data": len(self.cache.get_keys_by_tags(["price_data"])),
                "realtime": len(self.cache.get_keys_by_tags(["realtime"])),
                "best_four_points": len(
                    self.cache.get_keys_by_tags(["best_four_points"])
                ),
            },
        }

    def cleanup_old_cache(self, older_than_hours: int = 24) -> Dict[str, int]:
        return {"expired_cleaned": self.cache.cleanup_expired(), "lru_evicted": 0}

    @with_async_error_handling(operation="refresh_stock_cache")
    async def refresh_stock_cache(self, stock_code: str) -> Dict[str, Any]:
        validated_code = StockCodeValidator.validate_stock_code(stock_code)
        invalidated = self.invalidate_stock_cache(validated_code)

        results = await asyncio.gather(
            self.fetch_stock_data(validated_code),
            self.get_realtime_data(validated_code),
            self.get_best_four_points(validated_code),
            self.fetch_price_data(validated_code, days=30),
            return_exceptions=True,
        )

        return {
            "stock_code": validated_code,
            "invalidated_count": invalidated,
            "refreshed_data": {
                "stock_data": not isinstance(results[0], Exception),
                "realtime": not isinstance(results[1], Exception),
                "best_four_points": not isinstance(results[2], Exception),
                "price_data": not isinstance(results[3], Exception),
            },
            "errors": [
                r.to_dict() if isinstance(r, TwStockAgentError) else {"message": str(r)}
                for r in results
                if isinstance(r, Exception)
            ],
        }

    def backup_cache(self, backup_path: str) -> bool:
        return self.cache.backup_cache(backup_path)

    def restore_cache(self, backup_path: str) -> bool:
        return self.cache.restore_cache(backup_path)

    def get_performance_metrics(self) -> Dict[str, Any]:
        metrics: Dict[str, Any] = {
            "cache_stats": self.get_cache_statistics(),
            "performance_summary": (
                self._performance_monitor.get_performance_summary()
                if self._performance_monitor
                else None
            ),
        }
        if self._http_pool:
            metrics["http_pool"] = self._http_pool.get_metrics()
        return metrics

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """關閉股票服務和快取連線。"""
        if self._http_pool:
            await self._http_pool.close()
        self.cache.close()

        # Close provider if it exposes a close() method (e.g. FinMindProvider)
        close_fn = getattr(self._provider, "close", None)
        if callable(close_fn):
            await close_fn()

        logger.info("股票服務已關閉")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.close())
            else:
                loop.run_until_complete(self.close())
        except RuntimeError:
            self.cache.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
