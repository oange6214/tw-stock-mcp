"""FinMindProvider — fetches Taiwan stock data from the FinMind API.

FinMind dataset mapping:
    get_stock_info      -> TaiwanStockInfo
    get_price_history   -> TaiwanStockPrice
    get_realtime_data   -> TaiwanStockPrice (most recent record, same day)
    get_best_four_points -> raises StockDataUnavailableError
                           (BFP is computed analytics, not a FinMind dataset)

Authentication:
    Set FINMIND_API_TOKEN env var or pass api_token to the constructor.
    Without a token the API still works but is rate-limited to 30 req/day.

FinMind API docs: https://finmindtrade.com/analysis/#/Announcement/api
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import aiohttp

from tw_stock_agent.exceptions import (
    ExternalAPIError,
    StockDataUnavailableError,
    StockNotFoundError,
)

from .models import PriceRecord, RealtimeRecord, StockInfoRecord

logger = logging.getLogger("tw-stock-agent.providers.finmind")

FINMIND_BASE_URL = "https://api.finmindtrade.com/api/v4/data"


class FinMindProvider:
    """Fetches Taiwan stock data from the FinMind REST API.

    The provider lazily creates an aiohttp.ClientSession on first use and
    reuses it across calls.  Call close() (or use as an async context manager)
    to release the underlying TCP connections.
    """

    def __init__(self, api_token: Optional[str] = None) -> None:
        self._api_token = api_token  # None → unauthenticated (rate-limited)
        self._session: Optional[aiohttp.ClientSession] = None

    # ------------------------------------------------------------------
    # StockDataProvider interface
    # ------------------------------------------------------------------

    async def get_stock_info(self, stock_code: str) -> dict[str, Any]:
        """Fetch basic stock info from TaiwanStockInfo dataset."""
        params = {
            "dataset": "TaiwanStockInfo",
            "data_id": stock_code,
        }
        raw = await self._request(params)
        records = raw.get("data", [])

        if not records:
            raise StockNotFoundError(
                stock_code=stock_code,
                message=f"Stock code '{stock_code}' not found in FinMind TaiwanStockInfo",
            )

        row = records[0]
        record = StockInfoRecord(
            stock_code=stock_code,
            name=row.get("stock_name"),
            type=row.get("type"),
            isin=row.get("isin_code"),
            start_date=row.get("date"),
            market=row.get("market"),
            industry=row.get("industry_category"),
            updated_at=datetime.now().isoformat(),
        )
        return record.to_dict()

    async def get_price_history(
        self, stock_code: str, days: int
    ) -> list[dict[str, Any]]:
        """Fetch OHLCV history from TaiwanStockPrice dataset."""
        end_date = datetime.now().date()
        # Request a larger window to account for non-trading days
        start_date = end_date - timedelta(days=days * 2)

        params = {
            "dataset": "TaiwanStockPrice",
            "data_id": stock_code,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }
        raw = await self._request(params)
        rows = raw.get("data", [])

        if not rows:
            raise StockDataUnavailableError(
                stock_code=stock_code,
                data_type="price data",
                message="No price data returned by FinMind for the requested range",
            )

        # Keep only the last `days` records (already sorted ascending by date)
        recent = rows[-days:] if len(rows) > days else rows

        return [
            PriceRecord(
                date=row["date"],
                open=float(row.get("open", 0) or 0),
                high=float(row.get("max", 0) or 0),
                low=float(row.get("min", 0) or 0),
                close=float(row.get("close", 0) or 0),
                volume=int(row.get("Trading_Volume", 0) or 0),
                change=float(row["spread"]) if row.get("spread") is not None else None,
            ).to_dict()
            for row in recent
        ]

    async def get_realtime_data(self, stock_code: str) -> dict[str, Any]:
        """Return the most recent price record as a best-effort real-time quote.

        FinMind does not provide a dedicated real-time endpoint on the free
        tier.  We fetch today's (or the latest available) price record and
        surface it as real-time data.  The market_status field reflects
        whether the market is currently open based on the local clock.
        """
        today = datetime.now().date().isoformat()
        params = {
            "dataset": "TaiwanStockPrice",
            "data_id": stock_code,
            "start_date": today,
            "end_date": today,
        }
        raw = await self._request(params)
        rows = raw.get("data", [])

        if not rows:
            raise StockNotFoundError(
                stock_code=stock_code,
                message=f"No price data found for '{stock_code}' today via FinMind",
            )

        row = rows[-1]
        current_hour = datetime.now().hour
        market_status = "open" if 9 <= current_hour <= 13 else "closed"

        record = RealtimeRecord(
            stock_code=stock_code,
            name=row.get("stock_name"),
            current_price=float(row.get("close", 0) or 0),
            open=float(row.get("open", 0) or 0),
            high=float(row.get("max", 0) or 0),
            low=float(row.get("min", 0) or 0),
            volume=int(row.get("Trading_Volume", 0) or 0),
            updated_at=datetime.now().isoformat(),
            market_status=market_status,
        )
        return record.to_dict()

    async def get_best_four_points(self, stock_code: str) -> dict[str, Any]:
        """Not supported by FinMind — raises StockDataUnavailableError."""
        raise StockDataUnavailableError(
            stock_code=stock_code,
            data_type="best_four_points",
            message=(
                "FinMind provider does not support Best Four Points analysis. "
                "Switch to the twstock provider (STOCK_DATA_PROVIDER=twstock) "
                "or use a composite provider."
            ),
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Release the underlying aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> "FinMindProvider":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _request(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a GET request against the FinMind API.

        Injects the API token when available and converts HTTP / API errors
        into the project's typed exception hierarchy.
        """
        if self._api_token:
            params = {**params, "token": self._api_token}

        session = await self._get_session()
        try:
            async with session.get(
                FINMIND_BASE_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    raise ExternalAPIError(
                        api_name="FinMind",
                        message=f"HTTP {resp.status} from FinMind API",
                        status_code=resp.status,
                    )
                data: dict[str, Any] = await resp.json()

        except aiohttp.ClientError as exc:
            raise ExternalAPIError(
                api_name="FinMind",
                message=f"Network error calling FinMind API: {exc}",
            ) from exc

        # FinMind returns {"status": 200, "msg": "success", "data": [...]}
        status = data.get("status", 0)
        if status != 200:
            msg = data.get("msg", "Unknown error")
            logger.error("FinMind API error: status=%s msg=%s", status, msg)
            raise ExternalAPIError(
                api_name="FinMind",
                message=f"FinMind API returned status {status}: {msg}",
                status_code=status,
            )

        return data
