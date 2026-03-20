"""Market data service for Taiwan stock market overview endpoints."""

import logging
from datetime import datetime
from typing import Any, Optional

from tw_stock_agent.exceptions import ExternalAPIError, StockDataUnavailableError
from tw_stock_agent.services.stock_service import StockService
from tw_stock_agent.utils.connection_pool import HTTPConnectionPool, get_global_pool

logger = logging.getLogger("tw-stock-agent.market_service")

TWSE_MI_INDEX_URL = "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX"


class MarketService:
    """Fetch market-wide summary data from official market endpoints."""

    def __init__(
        self,
        stock_service: StockService,
        http_pool: Optional[HTTPConnectionPool] = None,
    ) -> None:
        self._stock_service = stock_service
        self._http_pool = http_pool

    async def _get_http_pool(self) -> HTTPConnectionPool:
        if self._http_pool is None:
            self._http_pool = await get_global_pool()
        return self._http_pool

    async def get_market_overview(self) -> dict[str, Any]:
        """Return a normalized market overview.

        The preferred source is the TWSE open data market index endpoint.
        If that fails, fall back to ETF proxy data so the MCP contract
        still returns a meaningful market summary instead of crashing.
        """
        try:
            data = await self._fetch_twse_market_overview()
            data["reference_stock"] = "TWSE_MI_INDEX"
            return data
        except Exception as exc:
            logger.warning("Falling back to proxy market overview: %s", exc)
            return await self._build_proxy_market_overview(str(exc))

    async def _fetch_twse_market_overview(self) -> dict[str, Any]:
        pool = await self._get_http_pool()
        try:
            rows = await pool.get_json(TWSE_MI_INDEX_URL)
        except Exception as exc:
            raise ExternalAPIError(
                api_name="TWSE_MI_INDEX",
                status_code=503,
                message=f"Failed to fetch TWSE market overview: {exc}",
            ) from exc

        if not isinstance(rows, list) or not rows:
            raise StockDataUnavailableError(
                stock_code="market",
                data_type="market overview",
                message="TWSE market overview endpoint returned no rows",
            )

        taiex_row = self._find_row(
            rows,
            value_keywords=["發行量加權股價指數", "TAIEX", "加權指數"],
        )
        breadth_row = self._find_row(
            rows,
            value_keywords=["上漲", "下跌", "平盤"],
            require_all=False,
        )
        turnover_row = self._find_row(
            rows,
            value_keywords=["總成交金額", "成交金額", "總成交股數", "成交股數"],
            require_all=False,
        )

        taiex_value = self._extract_numeric(
            taiex_row,
            ["收盤指數", "最新指數", "價格指數值", "指數"],
            allow_value_scan=True,
        )
        # 漲跌點數 field stores magnitude only; sign is in the 漲跌 field ("+"/"-").
        change_points_magnitude = self._extract_numeric(
            taiex_row,
            ["漲跌點數", "價格指數漲跌點數"],
        )
        change_direction = str(taiex_row.get("漲跌", "+")).strip() if taiex_row else "+"
        if change_points_magnitude is not None:
            change_points = (
                -change_points_magnitude if change_direction == "-" else change_points_magnitude
            )
        else:
            change_points = None
        change_percentage = self._extract_numeric(
            taiex_row,
            ["漲跌百分比", "漲跌比率", "報酬指數漲跌百分比"],
        )

        if taiex_value is None:
            raise StockDataUnavailableError(
                stock_code="market",
                data_type="market overview",
                message="Unable to parse TAIEX value from TWSE market overview",
            )

        total_volume = self._extract_numeric(
            turnover_row,
            ["總成交股數", "成交股數", "成交量", "總成交量"],
            as_int=True,
        )
        total_turnover = self._extract_numeric(
            turnover_row,
            ["總成交金額", "成交金額"],
        )
        advancing = self._extract_numeric(
            breadth_row,
            ["上漲(漲停)", "上漲家數", "上漲"],
            as_int=True,
        )
        declining = self._extract_numeric(
            breadth_row,
            ["下跌(跌停)", "下跌家數", "下跌"],
            as_int=True,
        )
        unchanged = self._extract_numeric(
            breadth_row,
            ["持平", "平盤", "未變動家數"],
            as_int=True,
        )

        return {
            "date": datetime.now().isoformat(),
            "taiex": {
                "index_name": "TAIEX",
                "current_value": taiex_value,
                "change_points": change_points,
                "change_percentage": change_percentage,
            },
            "volume": total_volume,
            "turnover": {"amount": total_turnover, "currency": "TWD"}
            if total_turnover is not None
            else None,
            "advancing_stocks": advancing,
            "declining_stocks": declining,
            "unchanged_stocks": unchanged,
            "updated_at": datetime.now().isoformat(),
            "market_status": self._infer_market_status(),
        }

    async def _build_proxy_market_overview(self, reason: str) -> dict[str, Any]:
        """Fallback market overview using 0050 recent price history.

        Uses fetch_price_data (multi-day window) instead of get_realtime_data
        (today-only) because FinMind's TaiwanStockPrice dataset is updated with
        a 1–3 hour delay after market close, making today-only queries fail
        during and shortly after trading hours.
        """
        try:
            prices = await self._stock_service.fetch_price_data("0050", 10)
            if not prices:
                raise StockDataUnavailableError(
                    stock_code="market",
                    data_type="market overview",
                    message=f"0050 price history returned no records. TWSE error: {reason}",
                )
            latest = prices[-1]  # most recent available trading day
            return {
                "date": latest.get("date", datetime.now().isoformat()),
                "taiex": {
                    "index_name": "0050_PROXY",
                    "current_value": latest.get("close"),
                },
                "volume": latest.get("volume"),
                "updated_at": datetime.now().isoformat(),
                "market_status": self._infer_market_status(),
                "reference_stock": "0050",
                "metadata_note": (
                    f"Fallback via 0050 price history (most recent date: {latest.get('date')}). "
                    f"TWSE MI_INDEX error: {reason}"
                ),
            }
        except StockDataUnavailableError:
            raise
        except Exception as exc:
            raise StockDataUnavailableError(
                stock_code="market",
                data_type="market overview",
                message=(
                    f"Both TWSE MI_INDEX and 0050 proxy failed. "
                    f"TWSE error: {reason}. Proxy error: {exc}"
                ),
            ) from exc

    def _find_row(
        self,
        rows: list[dict[str, Any]],
        value_keywords: list[str],
        require_all: bool = False,
    ) -> Optional[dict[str, Any]]:
        for row in rows:
            haystack = " ".join(str(value) for value in row.values())
            if require_all and all(keyword in haystack for keyword in value_keywords):
                return row
            if not require_all and any(keyword in haystack for keyword in value_keywords):
                return row
        return None

    def _extract_numeric(
        self,
        row: Optional[dict[str, Any]],
        candidate_keys: list[str],
        as_int: bool = False,
        allow_value_scan: bool = False,
    ) -> Optional[float | int]:
        if not row:
            return None

        for row_key, row_value in row.items():
            if any(
                candidate_key == row_key or candidate_key in row_key
                for candidate_key in candidate_keys
            ):
                value = self._normalize_numeric(row_value, as_int=as_int)
                if value is not None:
                    return value

        if allow_value_scan:
            for value in row.values():
                normalized = self._normalize_numeric(value, as_int=as_int)
                if normalized is not None:
                    return normalized
        return None

    def _normalize_numeric(
        self, value: Any, as_int: bool = False
    ) -> Optional[float | int]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value) if as_int else float(value)

        text = str(value).strip().replace(",", "").replace("%", "")
        if not text or text in {"--", "---", "N/A"}:
            return None

        try:
            number = float(text)
        except ValueError:
            return None
        return int(number) if as_int else number

    def _infer_market_status(self) -> str:
        hour = datetime.now().hour
        return "open" if 9 <= hour <= 13 else "closed"
