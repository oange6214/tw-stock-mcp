"""
Stock-specific exception classes for Taiwan Stock Agent.

This module contains exceptions related to stock operations,
including stock code validation, data availability, and market status.
"""

from typing import Optional

from .base import ErrorCode, ErrorContext, ErrorSeverity, TwStockAgentError


class StockError(TwStockAgentError):
    """Base exception for stock-related errors."""
    
    def __init__(
        self,
        message: str,
        stock_code: Optional[str] = None,
        error_code: ErrorCode = ErrorCode.STOCK_DATA_UNAVAILABLE,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        context: Optional[ErrorContext] = None,
        **kwargs
    ) -> None:
        if context is None:
            context = ErrorContext()
        if stock_code:
            context.stock_code = stock_code
        
        super().__init__(
            message=message,
            error_code=error_code,
            severity=severity,
            context=context,
            **kwargs
        )


class StockNotFoundError(StockError):
    """Exception raised when a stock is not found."""
    
    def __init__(
        self,
        stock_code: str,
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            message = f"Stock with code '{stock_code}' was not found"
        
        super().__init__(
            message=message,
            stock_code=stock_code,
            error_code=ErrorCode.STOCK_NOT_FOUND,
            severity=ErrorSeverity.MEDIUM,
            suggestions=[
                "Verify the stock code is correct",
                "Check if the stock is listed on Taiwan stock exchanges",
                "Try searching for the company name instead",
                "Ensure the stock code follows Taiwan format (4-6 digits)"
            ],
            **kwargs
        )


class InvalidStockCodeError(StockError):
    """Exception raised when stock code format is invalid."""
    
    def __init__(
        self,
        stock_code: str,
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            message = f"Invalid stock code format: '{stock_code}'. Taiwan stock codes must be 4-6 digits."
        
        super().__init__(
            message=message,
            stock_code=stock_code,
            error_code=ErrorCode.INVALID_STOCK_CODE,
            severity=ErrorSeverity.HIGH,
            suggestions=[
                "Use 4-6 digit stock codes (e.g., '2330' for TSMC)",
                "Remove any letters or special characters",
                "Check Taiwan Stock Exchange for valid stock codes",
                "Common codes: 2330 (TSMC), 2317 (Hon Hai), 1301 (台塑)"
            ],
            **kwargs
        )


class StockDataUnavailableError(StockError):
    """Exception raised when stock data is temporarily unavailable."""
    
    def __init__(
        self,
        stock_code: str,
        data_type: str = "stock data",
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            message = f"{data_type.title()} for stock '{stock_code}' is currently unavailable"
        
        super().__init__(
            message=message,
            stock_code=stock_code,
            error_code=ErrorCode.STOCK_DATA_UNAVAILABLE,
            severity=ErrorSeverity.MEDIUM,
            suggestions=[
                "Try again in a few minutes",
                "Check if the stock market is open",
                "Verify the stock is actively traded",
                "Contact support if the issue persists"
            ],
            data_type=data_type,
            **kwargs
        )


class StockMarketClosedError(StockError):
    """Exception raised when trying to access real-time data during market closure."""
    
    def __init__(
        self,
        stock_code: Optional[str] = None,
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            if stock_code:
                message = f"Real-time data for stock '{stock_code}' is unavailable - market is closed"
            else:
                message = "Real-time stock data is unavailable - market is closed"
        
        super().__init__(
            message=message,
            stock_code=stock_code,
            error_code=ErrorCode.STOCK_MARKET_CLOSED,
            severity=ErrorSeverity.LOW,
            suggestions=[
                "Taiwan stock market hours: 9:00 AM - 1:30 PM (GMT+8)",
                "Use historical data instead",
                "Check market calendar for holidays",
                "Try again during market hours"
            ],
            **kwargs
        )


class StockDelistedError(StockError):
    """Exception raised when a stock has been delisted."""
    
    def __init__(
        self,
        stock_code: str,
        delisting_date: Optional[str] = None,
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            msg = f"Stock '{stock_code}' has been delisted"
            if delisting_date:
                msg += f" on {delisting_date}"
            message = msg
        
        super().__init__(
            message=message,
            stock_code=stock_code,
            error_code=ErrorCode.STOCK_DELISTED,
            severity=ErrorSeverity.MEDIUM,
            suggestions=[
                "Check Taiwan Stock Exchange for delisting announcements",
                "Look for replacement or successor companies",
                "Use historical data only",
                "Contact your broker for more information"
            ],
            delisting_date=delisting_date,
            **kwargs
        )


class StockSuspendedError(StockError):
    """Exception raised when a stock is suspended from trading."""
    
    def __init__(
        self,
        stock_code: str,
        suspension_reason: Optional[str] = None,
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            msg = f"Stock '{stock_code}' is suspended from trading"
            if suspension_reason:
                msg += f" due to: {suspension_reason}"
            message = msg
        
        super().__init__(
            message=message,
            stock_code=stock_code,
            error_code=ErrorCode.STOCK_DATA_UNAVAILABLE,
            severity=ErrorSeverity.MEDIUM,
            suggestions=[
                "Check Taiwan Stock Exchange announcements",
                "Monitor for resumption of trading",
                "Review suspension reasons",
                "Consider alternative investments"
            ],
            suspension_reason=suspension_reason,
            **kwargs
        )