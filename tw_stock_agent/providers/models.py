"""Immutable intermediate data records produced by providers.

These dataclasses standardise the internal contract between a provider and
StockService.  They are NOT the Pydantic response models consumed by MCP
tools — those live in tw_stock_agent.models.stock_models.  Converting a
record to a plain dict via .to_dict() yields exactly the shape that
StockService currently passes to MCPResponseFormatter.
"""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class StockInfoRecord:
    """Basic stock information record."""

    stock_code: str
    name: str
    type: Optional[str]
    isin: Optional[str]
    start_date: Optional[str]
    market: Optional[str]
    industry: Optional[str]
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "name": self.name,
            "type": self.type,
            "isin": self.isin,
            "start_date": self.start_date,
            "market": self.market,
            "industry": self.industry,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class PriceRecord:
    """Single day OHLCV record."""

    date: str  # ISO date string, e.g. "2026-03-19"
    open: float
    high: float
    low: float
    close: float
    volume: int
    change: Optional[float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "change": self.change,
        }


@dataclass(frozen=True)
class RealtimeRecord:
    """Real-time quote record."""

    stock_code: str
    name: Optional[str]
    current_price: Optional[float]
    open: Optional[float]
    high: Optional[float]
    low: Optional[float]
    volume: Optional[int]
    updated_at: str
    market_status: str  # "open" | "closed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "name": self.name,
            "current_price": self.current_price,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "volume": self.volume,
            "updated_at": self.updated_at,
            "market_status": self.market_status,
        }


@dataclass(frozen=True)
class BestFourPointsRecord:
    """Best Four Points analysis record."""

    stock_code: str
    buy_points: Any
    sell_points: Any
    analysis: Any
    updated_at: str
    data_points: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "buy_points": self.buy_points,
            "sell_points": self.sell_points,
            "analysis": self.analysis,
            "updated_at": self.updated_at,
            "data_points": self.data_points,
        }
