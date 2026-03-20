"""Enhanced Pydantic models for stock data responses with Taiwan market-specific features."""

import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    Field,
    computed_field,
    field_validator,
    model_validator,
    ConfigDict
)

# Taiwan timezone for consistent timestamp handling
TAIWAN_TZ = ZoneInfo("Asia/Taipei")


class ResponseMetadata(BaseModel):
    """Standardized metadata for all responses."""
    
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid"
    )
    
    source: str = Field(default="tw-stock-agent", description="Data source identifier")
    version: str = Field(default="1.0", description="Response format version")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(TAIWAN_TZ),
        description="Response generation timestamp"
    )
    has_error: bool = Field(default=False, description="Whether response contains errors")
    data_type: str = Field(..., description="Type of data in response")
    record_count: Optional[int] = Field(None, description="Number of records in response")
    cache_info: Optional[Dict[str, Any]] = Field(None, description="Cache information")
    
    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: datetime) -> datetime:
        """Ensure timestamp is in Taiwan timezone."""
        if v.tzinfo is None:
            return v.replace(tzinfo=TAIWAN_TZ)
        return v.astimezone(TAIWAN_TZ)


class BaseStockResponse(BaseModel):
    """Base response model with common fields for all stock responses."""
    
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        populate_by_name=True,  # Allow field aliases
        json_encoders={
            datetime: lambda v: v.isoformat(),
            Decimal: lambda v: float(v)
        },
        extra="forbid"
    )
    
    stock_code: str = Field(
        ...,
        description="Stock code (股票代號)",
        example="2330",
        alias="stockCode"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(TAIWAN_TZ),
        description="Last update timestamp (更新時間)",
        alias="updatedAt"
    )
    error: Optional[str] = Field(
        None,
        description="Error message if any (錯誤訊息)"
    )
    metadata: ResponseMetadata = Field(
        default_factory=lambda: ResponseMetadata(data_type="stock_data")
    )
    
    @field_validator("stock_code")
    @classmethod
    def validate_stock_code(cls, v: str) -> str:
        """Validate Taiwan stock code format."""
        if not v:
            raise ValueError("Stock code cannot be empty")
        
        # Remove any spaces or special characters
        v = re.sub(r'[^0-9A-Z]', '', v.upper())
        
        # Taiwan stock codes are typically 4-6 digits
        if re.match(r'^\d{4,6}$', v):
            return v
        
        # Some special codes for ETFs or REITs
        if re.match(r'^[0-9]{4,6}[A-Z]?$', v):
            return v
            
        raise ValueError(f"Invalid Taiwan stock code format: {v}")
    
    @field_validator("updated_at")
    @classmethod
    def validate_updated_at(cls, v: datetime) -> datetime:
        """Ensure updated_at is in Taiwan timezone."""
        if v.tzinfo is None:
            return v.replace(tzinfo=TAIWAN_TZ)
        return v.astimezone(TAIWAN_TZ)
    
    @model_validator(mode='after')
    def update_metadata(self) -> 'BaseStockResponse':
        """Update metadata based on response state."""
        if self.error:
            self.metadata.has_error = True
        return self
    
    @computed_field
    @property
    def formatted_timestamp(self) -> str:
        """ISO formatted timestamp string."""
        return self.updated_at.isoformat()
    
    @computed_field
    @property
    def is_valid_trading_hours(self) -> bool:
        """Check if timestamp is within Taiwan trading hours."""
        # Taiwan stock market: 9:00-13:30, Monday-Friday
        if self.updated_at.weekday() >= 5:  # Weekend
            return False
        
        time_part = self.updated_at.time()
        from datetime import time
        return time(9, 0) <= time_part <= time(13, 30)


class TWDAmount(BaseModel):
    """Model for Taiwan Dollar amounts with proper formatting."""
    
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True
    )
    
    amount: Decimal = Field(..., description="Amount in TWD")
    currency: str = Field(default="TWD", description="Currency code")
    
    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: Union[float, int, str, Decimal]) -> Decimal:
        """Validate and convert amount to Decimal."""
        if v is None:
            raise ValueError("Amount cannot be None")
        
        try:
            decimal_amount = Decimal(str(v))
            if decimal_amount < 0:
                raise ValueError("Amount cannot be negative")
            return decimal_amount.quantize(Decimal('0.01'))  # Round to 2 decimal places
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid amount format: {v}") from e
    
    @computed_field
    @property
    def formatted_amount(self) -> str:
        """Format amount with thousand separators."""
        return f"NT${self.amount:,.2f}"
    
    @computed_field
    @property
    def amount_float(self) -> float:
        """Convert to float for backward compatibility."""
        return float(self.amount)


class StockDataResponse(BaseStockResponse):
    """Enhanced response model for stock basic data."""
    
    name: Optional[str] = Field(
        None,
        description="Company name (公司名稱)",
        example="台積電",
        alias="companyName"
    )
    name_en: Optional[str] = Field(
        None,
        description="English company name",
        alias="companyNameEn"
    )
    stock_type: Optional[str] = Field(
        None,
        description="Stock type (股票類型)",
        example="股票",
        alias="type"
    )
    isin_code: Optional[str] = Field(
        None,
        description="ISIN code (ISIN代碼)",
        alias="isin"
    )
    listing_date: Optional[datetime] = Field(
        None,
        description="Listing date (上市日期)",
        alias="startDate"
    )
    market_type: Optional[str] = Field(
        None,
        description="Market type (市場別)",
        example="上市",
        alias="market"
    )
    industry_category: Optional[str] = Field(
        None,
        description="Industry category (產業別)",
        example="半導體業",
        alias="industry"
    )
    market_cap: Optional[TWDAmount] = Field(
        None,
        description="Market capitalization",
        alias="marketCap"
    )
    
    def __init__(self, **data):
        # Handle backward compatibility for field names
        if 'type' in data and 'stock_type' not in data:
            data['stock_type'] = data.pop('type')
        if 'start_date' in data and 'listing_date' not in data:
            start_date = data.pop('start_date')
            if start_date:
                try:
                    data['listing_date'] = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    pass
        
        super().__init__(**data)
    
    @field_validator("listing_date")
    @classmethod
    def validate_listing_date(cls, v: Optional[Union[str, datetime]]) -> Optional[datetime]:
        """Validate and convert listing date."""
        if v is None:
            return None
        
        if isinstance(v, str):
            try:
                # Handle various date formats
                if 'T' in v:  # ISO format
                    return datetime.fromisoformat(v.replace('Z', '+00:00')).astimezone(TAIWAN_TZ)
                else:  # Date only
                    return datetime.strptime(v, '%Y-%m-%d').replace(tzinfo=TAIWAN_TZ)
            except ValueError as e:
                raise ValueError(f"Invalid date format: {v}") from e
        
        return v.astimezone(TAIWAN_TZ) if v.tzinfo else v.replace(tzinfo=TAIWAN_TZ)
    
    @computed_field
    @property
    def years_listed(self) -> Optional[int]:
        """Calculate years since listing."""
        if not self.listing_date:
            return None
        
        years = (datetime.now(TAIWAN_TZ) - self.listing_date).days // 365
        return max(0, years)
    
    @computed_field
    @property
    def is_recently_listed(self) -> bool:
        """Check if stock was listed within the last year."""
        if not self.listing_date:
            return False
        
        days_since_listing = (datetime.now(TAIWAN_TZ) - self.listing_date).days
        return days_since_listing <= 365


class PriceDataPoint(BaseModel):
    """Enhanced individual price data point with Taiwan market features."""
    
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        populate_by_name=True,
        json_encoders={
            datetime: lambda v: v.isoformat(),
            Decimal: lambda v: float(v)
        }
    )
    
    trading_date: datetime = Field(
        ...,
        description="Trading date (交易日期)",
        alias="date"
    )
    open_price: Optional[TWDAmount] = Field(
        None,
        description="Opening price (開盤價)",
        alias="open"
    )
    high_price: Optional[TWDAmount] = Field(
        None,
        description="Highest price (最高價)",
        alias="high"
    )
    low_price: Optional[TWDAmount] = Field(
        None,
        description="Lowest price (最低價)",
        alias="low"
    )
    close_price: Optional[TWDAmount] = Field(
        None,
        description="Closing price (收盤價)",
        alias="close"
    )
    volume: Optional[int] = Field(
        None,
        description="Trading volume (成交量)",
        ge=0
    )
    turnover: Optional[TWDAmount] = Field(
        None,
        description="Trading turnover (成交金額)"
    )
    price_change: Optional[Decimal] = Field(
        None,
        description="Price change (漲跌幅)",
        alias="change"
    )
    
    def __init__(self, **data):
        # Handle backward compatibility and type conversion
        for price_field in ['open', 'high', 'low', 'close']:
            if price_field in data and data[price_field] is not None:
                value = data[price_field]
                if not isinstance(value, dict):
                    data[price_field] = {'amount': value}
        
        if 'date' in data and isinstance(data['date'], str):
            try:
                data['trading_date'] = datetime.fromisoformat(data['date'].replace('Z', '+00:00'))
                data.pop('date', None)
            except ValueError:
                try:
                    data['trading_date'] = datetime.strptime(data['date'], '%Y-%m-%d')
                    data.pop('date', None)
                except ValueError:
                    pass
        
        super().__init__(**data)
    
    @field_validator("trading_date")
    @classmethod
    def validate_trading_date(cls, v: Union[str, datetime]) -> datetime:
        """Validate and convert trading date."""
        if isinstance(v, str):
            try:
                if 'T' in v:
                    return datetime.fromisoformat(v.replace('Z', '+00:00')).astimezone(TAIWAN_TZ)
                else:
                    return datetime.strptime(v, '%Y-%m-%d').replace(tzinfo=TAIWAN_TZ)
            except ValueError as e:
                raise ValueError(f"Invalid date format: {v}") from e
        
        return v.astimezone(TAIWAN_TZ) if v.tzinfo else v.replace(tzinfo=TAIWAN_TZ)
    
    @computed_field
    @property
    def price_change_percentage(self) -> Optional[float]:
        """Calculate price change percentage."""
        if not self.price_change or not self.close_price or not self.open_price:
            return None
        
        if self.open_price.amount == 0:
            return None
        
        return float((self.price_change / self.open_price.amount) * 100)
    
    @computed_field
    @property
    def is_limit_up(self) -> bool:
        """Check if price hit daily limit up (Taiwan: 10%)."""
        percentage = self.price_change_percentage
        return percentage is not None and percentage >= 9.99  # Account for rounding
    
    @computed_field
    @property
    def is_limit_down(self) -> bool:
        """Check if price hit daily limit down (Taiwan: 10%)."""
        percentage = self.price_change_percentage
        return percentage is not None and percentage <= -9.99  # Account for rounding
    
    @computed_field
    @property
    def trading_range(self) -> Optional[Decimal]:
        """Calculate trading range (high - low)."""
        if not self.high_price or not self.low_price:
            return None
        return self.high_price.amount - self.low_price.amount
    
    @computed_field
    @property
    def average_price(self) -> Optional[Decimal]:
        """Calculate average price (OHLC/4)."""
        prices = []
        for price_field in [self.open_price, self.high_price, self.low_price, self.close_price]:
            if price_field:
                prices.append(price_field.amount)
        
        if not prices:
            return None
        
        return sum(prices) / len(prices)


class PriceHistoryResponse(BaseStockResponse):
    """Enhanced response model for price history data."""
    
    period: str = Field(
        ...,
        description="Time period (時間區間)",
        example="1mo"
    )
    data: List[PriceDataPoint] = Field(
        default_factory=list,
        description="Price data points (價格資料)"
    )
    requested_days: Optional[int] = Field(
        None,
        description="Number of days requested",
        alias="requestedDays"
    )
    actual_records: Optional[int] = Field(
        None,
        description="Actual number of records returned",
        alias="actualRecords"
    )
    
    def __init__(self, **data):
        super().__init__(**data)
        self.metadata.data_type = "price_history"
        self.metadata.record_count = len(self.data)
    
    @field_validator("period")
    @classmethod
    def validate_period(cls, v: str) -> str:
        """Validate period format."""
        valid_periods = {'1d', '5d', '1mo', '3mo', '6mo', '1y', 'ytd', 'max'}
        if v not in valid_periods:
            raise ValueError(f"Invalid period. Must be one of: {', '.join(valid_periods)}")
        return v
    
    @computed_field
    @property
    def price_summary(self) -> Optional[Dict[str, Any]]:
        """Calculate price summary statistics."""
        if not self.data:
            return None
        
        prices = []
        volumes = []
        
        for point in self.data:
            if point.close_price:
                prices.append(point.close_price.amount)
            if point.volume:
                volumes.append(point.volume)
        
        if not prices:
            return None
        
        return {
            "min_price": float(min(prices)),
            "max_price": float(max(prices)),
            "avg_price": float(sum(prices) / len(prices)),
            "total_volume": sum(volumes) if volumes else None,
            "avg_volume": sum(volumes) / len(volumes) if volumes else None,
            "trading_days": len(self.data)
        }
    
    @computed_field
    @property
    def overall_change(self) -> Optional[Dict[str, Any]]:
        """Calculate overall change for the period."""
        if len(self.data) < 2:
            return None
        
        first_price = None
        last_price = None
        
        # Find first valid price
        for point in self.data:
            if point.close_price:
                first_price = point.close_price.amount
                break
        
        # Find last valid price
        for point in reversed(self.data):
            if point.close_price:
                last_price = point.close_price.amount
                break
        
        if not first_price or not last_price or first_price == 0:
            return None
        
        change_amount = last_price - first_price
        change_percentage = float((change_amount / first_price) * 100)
        
        return {
            "period_start_price": float(first_price),
            "period_end_price": float(last_price),
            "change_amount": float(change_amount),
            "change_percentage": change_percentage,
            "is_positive": change_amount > 0
        }


class RealtimeDataResponse(BaseStockResponse):
    """Enhanced response model for realtime stock data."""
    
    company_name: Optional[str] = Field(
        None,
        description="Company name (股票名稱)",
        alias="name"
    )
    current_price: Optional[TWDAmount] = Field(
        None,
        description="Current price (現在價格)",
        alias="currentPrice"
    )
    opening_price: Optional[TWDAmount] = Field(
        None,
        description="Opening price (開盤價)",
        alias="open"
    )
    highest_price: Optional[TWDAmount] = Field(
        None,
        description="Highest price (最高價)",
        alias="high"
    )
    lowest_price: Optional[TWDAmount] = Field(
        None,
        description="Lowest price (最低價)",
        alias="low"
    )
    trading_volume: Optional[int] = Field(
        None,
        description="Trading volume (成交量)",
        alias="volume",
        ge=0
    )
    bid_price: Optional[TWDAmount] = Field(
        None,
        description="Best bid price (最佳買價)",
        alias="bidPrice"
    )
    ask_price: Optional[TWDAmount] = Field(
        None,
        description="Best ask price (最佳賣價)",
        alias="askPrice"
    )
    bid_size: Optional[int] = Field(
        None,
        description="Bid size (買張數)",
        alias="bidSize",
        ge=0
    )
    ask_size: Optional[int] = Field(
        None,
        description="Ask size (賣張數)",
        alias="askSize",
        ge=0
    )
    market_status: Optional[str] = Field(
        None,
        description="Market status (市場狀態)",
        alias="marketStatus"
    )
    
    def __init__(self, **data):
        # Handle backward compatibility
        for price_field in ['current_price', 'open', 'high', 'low', 'bid_price', 'ask_price']:
            field_name = price_field
            if price_field == 'open':
                field_name = 'opening_price'
            elif price_field == 'high':
                field_name = 'highest_price'
            elif price_field == 'low':
                field_name = 'lowest_price'
            # current_price, bid_price, ask_price stay the same
            
            if price_field in data and data[price_field] is not None:
                value = data[price_field]
                if not isinstance(value, dict):
                    data[field_name] = {'amount': value}
                if price_field != field_name:  # Only remove if field name changed
                    data.pop(price_field, None)
        
        super().__init__(**data)
        self.metadata.data_type = "realtime_data"
    
    @field_validator("market_status")
    @classmethod
    def validate_market_status(cls, v: Optional[str]) -> Optional[str]:
        """Validate market status."""
        if v is None:
            return None
        
        valid_statuses = {
            'open', 'closed', 'pre_market', 'after_hours', 
            'opening_auction', 'closing_auction', 'trading_halt'
        }
        
        v_lower = v.lower().replace(' ', '_')
        if v_lower not in valid_statuses:
            return 'unknown'
        
        return v_lower
    
    @computed_field
    @property
    def price_change_from_open(self) -> Optional[Dict[str, Any]]:
        """Calculate price change from opening."""
        if not self.current_price or not self.opening_price or self.opening_price.amount == 0:
            return None
        
        change_amount = self.current_price.amount - self.opening_price.amount
        change_percentage = float((change_amount / self.opening_price.amount) * 100)
        
        return {
            "change_amount": float(change_amount),
            "change_percentage": change_percentage,
            "is_positive": change_amount > 0,
            "formatted_change": f"{'+' if change_amount >= 0 else ''}{change_amount:.2f}"
        }
    
    @computed_field
    @property
    def bid_ask_spread(self) -> Optional[Dict[str, Any]]:
        """Calculate bid-ask spread."""
        if not self.bid_price or not self.ask_price:
            return None
        
        spread_amount = self.ask_price.amount - self.bid_price.amount
        mid_price = (self.ask_price.amount + self.bid_price.amount) / 2
        spread_percentage = float((spread_amount / mid_price) * 100) if mid_price > 0 else None
        
        return {
            "spread_amount": float(spread_amount),
            "spread_percentage": spread_percentage,
            "mid_price": float(mid_price)
        }
    
    @computed_field
    @property
    def is_actively_trading(self) -> bool:
        """Check if stock is actively trading."""
        return (
            self.market_status == 'open' and
            self.current_price is not None and
            self.trading_volume is not None and
            self.trading_volume > 0
        )


class TradingSignal(BaseModel):
    """Model for trading signals with enhanced information."""
    
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True
    )
    
    signal_type: str = Field(..., description="Signal type (buy/sell)")
    confidence: float = Field(..., description="Signal confidence (0-1)", ge=0, le=1)
    price_target: Optional[TWDAmount] = Field(None, description="Target price")
    stop_loss: Optional[TWDAmount] = Field(None, description="Stop loss price")
    time_horizon: Optional[str] = Field(None, description="Time horizon for signal")
    reasoning: Optional[str] = Field(None, description="Signal reasoning")
    
    @field_validator("signal_type")
    @classmethod
    def validate_signal_type(cls, v: str) -> str:
        """Validate signal type."""
        valid_types = {'buy', 'sell', 'hold', 'strong_buy', 'strong_sell'}
        if v.lower() not in valid_types:
            raise ValueError(f"Invalid signal type. Must be one of: {', '.join(valid_types)}")
        return v.lower()


class BestFourPointsResponse(BaseStockResponse):
    """Enhanced response model for Best Four Points analysis."""
    
    buy_signals: List[TradingSignal] = Field(
        default_factory=list,
        description="Buy signals (買點)",
        alias="buyPoints"
    )
    sell_signals: List[TradingSignal] = Field(
        default_factory=list,
        description="Sell signals (賣點)",
        alias="sellPoints"
    )
    technical_analysis: Optional[Dict[str, Any]] = Field(
        None,
        description="Technical analysis results (技術分析結果)",
        alias="analysis"
    )
    overall_recommendation: Optional[str] = Field(
        None,
        description="Overall trading recommendation",
        alias="overallRecommendation"
    )
    risk_assessment: Optional[Dict[str, Any]] = Field(
        None,
        description="Risk assessment information",
        alias="riskAssessment"
    )
    
    def __init__(self, **data):
        # Handle backward compatibility
        if 'buy_points' in data:
            data['buy_signals'] = data.pop('buy_points', [])
        if 'sell_points' in data:
            data['sell_signals'] = data.pop('sell_points', [])
        if 'analysis' in data:
            data['technical_analysis'] = data.pop('analysis')
        
        super().__init__(**data)
        self.metadata.data_type = "technical_analysis"
        self.metadata.record_count = len(self.buy_signals) + len(self.sell_signals)
    
    @field_validator("overall_recommendation")
    @classmethod
    def validate_recommendation(cls, v: Optional[str]) -> Optional[str]:
        """Validate overall recommendation."""
        if v is None:
            return None
        
        valid_recommendations = {
            'strong_buy', 'buy', 'hold', 'sell', 'strong_sell'
        }
        
        if v.lower() not in valid_recommendations:
            return 'hold'  # Default to hold for invalid values
        
        return v.lower()
    
    @computed_field
    @property
    def signal_summary(self) -> Dict[str, Any]:
        """Summary of all trading signals."""
        buy_count = len([s for s in self.buy_signals if s.signal_type in ['buy', 'strong_buy']])
        sell_count = len([s for s in self.sell_signals if s.signal_type in ['sell', 'strong_sell']])
        
        avg_buy_confidence = (
            sum(s.confidence for s in self.buy_signals) / len(self.buy_signals)
            if self.buy_signals else 0
        )
        
        avg_sell_confidence = (
            sum(s.confidence for s in self.sell_signals) / len(self.sell_signals)
            if self.sell_signals else 0
        )
        
        return {
            "total_signals": len(self.buy_signals) + len(self.sell_signals),
            "buy_signals_count": buy_count,
            "sell_signals_count": sell_count,
            "average_buy_confidence": round(avg_buy_confidence, 2),
            "average_sell_confidence": round(avg_sell_confidence, 2),
            "signal_bias": "bullish" if buy_count > sell_count else "bearish" if sell_count > buy_count else "neutral"
        }


class MarketIndexData(BaseModel):
    """Model for market index information."""
    
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True
    )
    
    index_name: str = Field(..., description="Index name")
    current_value: Decimal = Field(..., description="Current index value")
    change_points: Optional[Decimal] = Field(None, description="Change in points")
    change_percentage: Optional[float] = Field(None, description="Change percentage")
    
    @computed_field
    @property
    def formatted_value(self) -> str:
        """Format index value with thousand separators."""
        return f"{self.current_value:,.2f}"


class MarketOverviewResponse(BaseModel):
    """Enhanced response model for market overview."""
    
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        populate_by_name=True,
        json_encoders={
            datetime: lambda v: v.isoformat(),
            Decimal: lambda v: float(v)
        }
    )
    
    trading_date: datetime = Field(
        ...,
        description="Trading date (交易日期)",
        alias="date"
    )
    taiex_index: Optional[MarketIndexData] = Field(
        None,
        description="TAIEX index data (台股加權指數)",
        alias="taiex"
    )
    total_volume: Optional[int] = Field(
        None,
        description="Total market volume (總成交量)",
        alias="volume",
        ge=0
    )
    total_turnover: Optional[TWDAmount] = Field(
        None,
        description="Total market turnover (總成交金額)",
        alias="turnover"
    )
    advancing_stocks: Optional[int] = Field(
        None,
        description="Number of advancing stocks (上漲家數)",
        ge=0
    )
    declining_stocks: Optional[int] = Field(
        None,
        description="Number of declining stocks (下跌家數)",
        ge=0
    )
    unchanged_stocks: Optional[int] = Field(
        None,
        description="Number of unchanged stocks (平盤家數)",
        ge=0
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(TAIWAN_TZ),
        description="Last update timestamp (更新時間)",
        alias="updatedAt"
    )
    market_status: Optional[str] = Field(
        None,
        description="Current market status (市場狀態)"
    )
    reference_stock: Optional[str] = Field(
        None,
        description="Reference stock for market data"
    )
    error: Optional[str] = Field(
        None,
        description="Error message if any (錯誤訊息)"
    )
    metadata: ResponseMetadata = Field(
        default_factory=lambda: ResponseMetadata(data_type="market_overview")
    )
    
    def __init__(self, **data):
        # Handle backward compatibility
        if 'date' in data and isinstance(data['date'], str):
            try:
                data['trading_date'] = datetime.fromisoformat(data['date'].replace('Z', '+00:00'))
                data.pop('date', None)
            except ValueError:
                try:
                    data['trading_date'] = datetime.strptime(data['date'], '%Y-%m-%d')
                    data.pop('date', None)
                except ValueError:
                    pass
        
        # Handle TAIEX value conversion
        if 'taiex' in data and not isinstance(data['taiex'], dict):
            if data['taiex'] is not None:
                data['taiex_index'] = {
                    'index_name': 'TAIEX',
                    'current_value': data['taiex']
                }
            data.pop('taiex', None)
        
        super().__init__(**data)
    
    @field_validator("trading_date")
    @classmethod
    def validate_trading_date(cls, v: Union[str, datetime]) -> datetime:
        """Validate and convert trading date."""
        if isinstance(v, str):
            try:
                if 'T' in v:
                    return datetime.fromisoformat(v.replace('Z', '+00:00')).astimezone(TAIWAN_TZ)
                else:
                    return datetime.strptime(v, '%Y-%m-%d').replace(tzinfo=TAIWAN_TZ)
            except ValueError as e:
                raise ValueError(f"Invalid date format: {v}") from e
        
        return v.astimezone(TAIWAN_TZ) if v.tzinfo else v.replace(tzinfo=TAIWAN_TZ)
    
    @field_validator("updated_at")
    @classmethod
    def validate_updated_at(cls, v: datetime) -> datetime:
        """Ensure updated_at is in Taiwan timezone."""
        if v.tzinfo is None:
            return v.replace(tzinfo=TAIWAN_TZ)
        return v.astimezone(TAIWAN_TZ)
    
    @model_validator(mode='after')
    def update_metadata(self) -> 'MarketOverviewResponse':
        """Update metadata based on response state."""
        if self.error:
            self.metadata.has_error = True
        return self
    
    @computed_field
    @property
    def total_trading_stocks(self) -> Optional[int]:
        """Calculate total number of stocks that traded."""
        counts = [self.advancing_stocks, self.declining_stocks, self.unchanged_stocks]
        valid_counts = [c for c in counts if c is not None]
        
        if not valid_counts:
            return None
        
        return sum(valid_counts)
    
    @computed_field
    @property
    def market_sentiment(self) -> Optional[str]:
        """Determine market sentiment based on advancing/declining stocks."""
        if not self.advancing_stocks or not self.declining_stocks:
            return None
        
        if self.advancing_stocks > self.declining_stocks * 1.5:
            return "very_bullish"
        elif self.advancing_stocks > self.declining_stocks:
            return "bullish"
        elif self.declining_stocks > self.advancing_stocks * 1.5:
            return "very_bearish"
        elif self.declining_stocks > self.advancing_stocks:
            return "bearish"
        else:
            return "neutral"
    
    @computed_field
    @property
    def is_trading_day(self) -> bool:
        """Check if the date is a trading day (weekday)."""
        return self.trading_date.weekday() < 5  # Monday = 0, Friday = 4
    
    @computed_field
    @property
    def formatted_timestamp(self) -> str:
        """ISO formatted timestamp string."""
        return self.updated_at.isoformat()


# Backward compatibility exports
__all__ = [
    "StockDataResponse",
    "PriceDataPoint",
    "PriceHistoryResponse",
    "RealtimeDataResponse",
    "BestFourPointsResponse",
    "MarketOverviewResponse",
    "BaseStockResponse",
    "ResponseMetadata",
    "TWDAmount",
    "TradingSignal",
    "MarketIndexData",
    "TAIWAN_TZ"
]