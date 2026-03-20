"""Provider Protocol — the contract every data source must satisfy."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class StockDataProvider(Protocol):
    """Abstract contract for stock data sources.

    All providers must implement these four async methods.
    Return types are plain dicts so StockService remains the single
    normalisation boundary before data reaches MCPResponseFormatter.

    Raised exceptions must be instances of the project's typed exception
    hierarchy (StockNotFoundError, StockDataUnavailableError, etc.) so that
    callers need no provider-specific error handling.
    """

    async def get_stock_info(self, stock_code: str) -> dict[str, Any]:
        """Return basic stock information.

        Required keys in returned dict:
            stock_code, name, type, isin, start_date, market, industry, updated_at
        Raises:
            StockNotFoundError: code does not exist in the exchange.
            StockDataUnavailableError: data temporarily unavailable.
        """
        ...

    async def get_price_history(
        self, stock_code: str, days: int
    ) -> list[dict[str, Any]]:
        """Return OHLCV records for the most recent *days* trading days.

        Each record must contain:
            date (ISO str), open, high, low, close (float),
            volume (int), change (float | None)
        Raises:
            StockDataUnavailableError: data temporarily unavailable.
        """
        ...

    async def get_realtime_data(self, stock_code: str) -> dict[str, Any]:
        """Return the latest real-time quote.

        Required keys:
            stock_code, name, current_price, open, high, low,
            volume, updated_at, market_status
        Raises:
            StockNotFoundError: code not found.
            StockDataUnavailableError: data temporarily unavailable.
            StockMarketClosedError: market is closed.
        """
        ...

    async def get_best_four_points(self, stock_code: str) -> dict[str, Any]:
        """Return Best Four Points (四大買賣點) analysis.

        Required keys:
            stock_code, buy_points, sell_points, analysis, updated_at, data_points
        Note:
            Providers that cannot compute this natively should raise
            StockDataUnavailableError with a descriptive message rather than
            silently returning empty data.
        Raises:
            StockDataUnavailableError: analysis unavailable for this provider.
        """
        ...
