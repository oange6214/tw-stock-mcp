"""
Taiwan Stock Agent Exception System

This module provides a comprehensive exception hierarchy for the Taiwan Stock Agent MCP server.
All exceptions include error codes, context data, and structured error responses.
"""

from .base import (
    TwStockAgentError,
    ErrorCode,
    ErrorSeverity,
    ErrorContext,
    create_error_response,
)
from .stock_exceptions import (
    StockError,
    StockNotFoundError,
    InvalidStockCodeError,
    StockDataUnavailableError,
    StockMarketClosedError,
)
from .api_exceptions import (
    APIError,
    RateLimitError,
    DataSourceUnavailableError,
    ExternalAPIError,
    TimeoutError,
)
from .cache_exceptions import (
    CacheError,
    CacheConnectionError,
    CacheKeyError,
    CacheSerializationError,
)
from .mcp_exceptions import (
    MCPError,
    MCPValidationError,
    MCPResourceError,
    MCPToolError,
)
from .validation_exceptions import (
    ValidationError,
    ParameterValidationError,
    DataFormatError,
    TypeValidationError,
    EnumValidationError,
    RangeValidationError,
    RequiredParameterMissingError,
    StockCodeValidationError,
)

__all__ = [
    # Base
    "TwStockAgentError",
    "ErrorCode",
    "ErrorSeverity", 
    "ErrorContext",
    "create_error_response",
    # Stock specific
    "StockError",
    "StockNotFoundError",
    "InvalidStockCodeError",
    "StockDataUnavailableError",
    "StockMarketClosedError",
    # API related
    "APIError",
    "RateLimitError",
    "DataSourceUnavailableError",
    "ExternalAPIError",
    "TimeoutError",
    # Cache related
    "CacheError",
    "CacheConnectionError",
    "CacheKeyError",
    "CacheSerializationError",
    # MCP protocol
    "MCPError",
    "MCPValidationError",
    "MCPResourceError",
    "MCPToolError",
    # Validation
    "ValidationError",
    "ParameterValidationError",
    "DataFormatError",
    "TypeValidationError",
    "EnumValidationError",
    "RangeValidationError",
    "RequiredParameterMissingError",
    "StockCodeValidationError",
]