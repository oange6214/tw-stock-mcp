"""TwstockProvider — wraps the twstock package as a StockDataProvider.

This is a direct extraction of the twstock-specific logic that previously
lived inside StockService.  The CircuitBreaker that was at module scope in
stock_service.py is now owned by this provider instance.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

import twstock
from twstock import BestFourPoint, Stock

from tw_stock_mcp.exceptions import (
    StockDataUnavailableError,
    StockMarketClosedError,
    StockNotFoundError,
)
from tw_stock_mcp.utils.error_handler import CircuitBreaker

from .models import (
    BestFourPointsRecord,
    PriceRecord,
    RealtimeRecord,
    StockInfoRecord,
)

logger = logging.getLogger("tw-stock-agent.providers.twstock")


class TwstockProvider:
    """Wraps the twstock package as a StockDataProvider.

    All external calls are guarded by a CircuitBreaker and run in a
    thread pool via asyncio.to_thread so the async event loop is never
    blocked by twstock's synchronous I/O.
    """

    def __init__(self) -> None:
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=3,
            timeout_seconds=30.0,
            expected_exception=(ConnectionError, TimeoutError, Exception),
        )

    # ------------------------------------------------------------------
    # StockDataProvider interface
    # ------------------------------------------------------------------

    async def get_stock_info(self, stock_code: str) -> dict[str, Any]:
        """Fetch basic stock information via twstock.codes."""
        try:
            stock_info = await self._circuit_breaker.acall(
                asyncio.to_thread, twstock.codes.get, stock_code
            )

            if not stock_info:
                raise StockNotFoundError(
                    stock_code=stock_code,
                    message=f"Stock code '{stock_code}' not found in Taiwan stock exchange",
                )

            record = StockInfoRecord(
                stock_code=stock_code,
                name=stock_info.name,
                type=stock_info.type,
                isin=stock_info.ISIN,
                start_date=stock_info.start,
                market=stock_info.market,
                industry=stock_info.group,
                updated_at=datetime.now().isoformat(),
            )
            return record.to_dict()

        except StockNotFoundError:
            raise
        except Exception as e:
            self._raise_unavailable(stock_code, "stock information", e)

    async def get_price_history(
        self, stock_code: str, days: int
    ) -> list[dict[str, Any]]:
        """Fetch historical OHLCV data via twstock.Stock."""
        try:
            stock = await self._circuit_breaker.acall(
                asyncio.to_thread, Stock, stock_code
            )
            await self._circuit_breaker.acall(
                asyncio.to_thread,
                stock.fetch_from,
                datetime.now().year,
                datetime.now().month,
            )

            if not stock.data:
                raise StockDataUnavailableError(
                    stock_code=stock_code,
                    data_type="price data",
                    message="No price data available for this stock",
                )

            recent = stock.data[-days:] if len(stock.data) > days else stock.data
            return [
                PriceRecord(
                    date=d.date.isoformat(),
                    open=d.open,
                    high=d.high,
                    low=d.low,
                    close=d.close,
                    volume=d.capacity,
                    change=d.change,
                ).to_dict()
                for d in recent
            ]

        except StockDataUnavailableError:
            raise
        except Exception as e:
            self._raise_unavailable(stock_code, "price data", e)

    async def get_realtime_data(self, stock_code: str) -> dict[str, Any]:
        """Fetch real-time quote via twstock.realtime."""
        try:
            realtime_data = await self._circuit_breaker.acall(
                asyncio.to_thread, twstock.realtime.get, stock_code
            )

            if not realtime_data:
                raise StockNotFoundError(
                    stock_code=stock_code,
                    message=f"No real-time data available for stock '{stock_code}'",
                )

            if not realtime_data.get("success", False):
                current_hour = datetime.now().hour
                if current_hour < 9 or current_hour > 14:
                    raise StockMarketClosedError(
                        stock_code=stock_code,
                        message="Taiwan stock market is closed. Trading hours: 9:00 AM - 1:30 PM (GMT+8)",
                    )
                raise StockDataUnavailableError(
                    stock_code=stock_code,
                    data_type="real-time data",
                    message="Real-time data temporarily unavailable",
                )

            rt = realtime_data.get("realtime", {})
            info = realtime_data.get("info", {})

            record = RealtimeRecord(
                stock_code=stock_code,
                name=info.get("name"),
                current_price=rt.get("latest_trade_price"),
                open=rt.get("open"),
                high=rt.get("high"),
                low=rt.get("low"),
                volume=rt.get("accumulate_trade_volume"),
                updated_at=datetime.now().isoformat(),
                market_status="open" if realtime_data.get("success") else "closed",
            )
            return record.to_dict()

        except (StockNotFoundError, StockDataUnavailableError, StockMarketClosedError):
            raise
        except Exception as e:
            self._raise_unavailable(stock_code, "real-time data", e)

    async def get_best_four_points(self, stock_code: str) -> dict[str, Any]:
        """Compute Best Four Points analysis via twstock.BestFourPoint."""
        try:
            stock = await self._circuit_breaker.acall(
                asyncio.to_thread, Stock, stock_code
            )
            bfp = await self._circuit_breaker.acall(
                asyncio.to_thread, BestFourPoint, stock
            )

            if not stock.data or len(stock.data) < 20:
                raise StockDataUnavailableError(
                    stock_code=stock_code,
                    data_type="analysis data",
                    message=(
                        "Insufficient historical data for Best Four Points analysis "
                        "(minimum 20 days required)"
                    ),
                )

            record = BestFourPointsRecord(
                stock_code=stock_code,
                buy_points=bfp.best_four_point_to_buy(),
                sell_points=bfp.best_four_point_to_sell(),
                analysis=bfp.best_four_point(),
                updated_at=datetime.now().isoformat(),
                data_points=len(stock.data),
            )
            return record.to_dict()

        except StockDataUnavailableError:
            raise
        except Exception as e:
            self._raise_unavailable(stock_code, "analysis data", e)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _raise_unavailable(
        self, stock_code: str, data_type: str, exc: Exception
    ) -> None:
        """Convert a generic exception to StockDataUnavailableError."""
        msg = str(exc)
        if "connection" in msg.lower() or "timeout" in msg.lower():
            raise StockDataUnavailableError(
                stock_code=stock_code,
                data_type=data_type,
                message=f"Unable to fetch {data_type} due to network issues: {msg}",
            ) from exc
        raise StockDataUnavailableError(
            stock_code=stock_code,
            data_type=data_type,
            message=f"Failed to fetch {data_type}: {msg}",
        ) from exc
