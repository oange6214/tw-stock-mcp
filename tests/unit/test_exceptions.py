"""
Tests for the custom exception system.

This module tests all custom exceptions, error codes, contexts,
and error handling utilities.
"""

import pytest
from datetime import datetime
from typing import Any, Dict

from tw_stock_mcp.exceptions import (
    # Base exceptions
    TwStockAgentError,
    ErrorCode,
    ErrorSeverity,
    ErrorContext,
    create_error_response,
    
    # Stock exceptions
    StockError,
    StockNotFoundError,
    InvalidStockCodeError,
    StockDataUnavailableError,
    StockMarketClosedError,
    
    # API exceptions
    APIError,
    RateLimitError,
    DataSourceUnavailableError,
    ExternalAPIError,
    TimeoutError,
    
    # Cache exceptions
    CacheError,
    CacheConnectionError,
    CacheKeyError,
    CacheSerializationError,
    
    # MCP exceptions
    MCPError,
    MCPValidationError,
    MCPResourceError,
    MCPToolError,
    
    # Validation exceptions
    ValidationError,
    ParameterValidationError,
    DataFormatError,
    TypeValidationError,
    StockCodeValidationError,
)


class TestErrorContext:
    """Test ErrorContext functionality."""
    
    def test_default_context_creation(self):
        """Test creating ErrorContext with defaults."""
        context = ErrorContext()
        
        assert context.correlation_id is not None
        assert isinstance(context.timestamp, datetime)
        assert context.stock_code is None
        assert context.operation is None
        assert context.user_id is None
        assert context.request_id is None
        assert context.additional_data == {}
    
    def test_context_with_parameters(self):
        """Test creating ErrorContext with specific parameters."""
        context = ErrorContext(
            stock_code="2330",
            operation="fetch_stock_data",
            user_id="test_user",
            request_id="req_123",
            additional_data={"key": "value"}
        )
        
        assert context.stock_code == "2330"
        assert context.operation == "fetch_stock_data"
        assert context.user_id == "test_user"
        assert context.request_id == "req_123"
        assert context.additional_data == {"key": "value"}


class TestTwStockAgentError:
    """Test base TwStockAgentError functionality."""
    
    def test_basic_error_creation(self):
        """Test creating basic error."""
        error = TwStockAgentError("Test error message")
        
        assert str(error) == "UNKNOWN_ERROR: Test error message"
        assert error.message == "Test error message"
        assert error.error_code == ErrorCode.UNKNOWN_ERROR
        assert error.severity == ErrorSeverity.MEDIUM
        assert error.context is not None
        assert error.cause is None
        assert error.suggestions == []
    
    def test_error_with_all_parameters(self):
        """Test creating error with all parameters."""
        context = ErrorContext(stock_code="2330")
        cause = ValueError("Original error")
        suggestions = ["Try again", "Check parameters"]
        
        error = TwStockAgentError(
            message="Test error",
            error_code=ErrorCode.VALIDATION_ERROR,
            severity=ErrorSeverity.HIGH,
            context=context,
            cause=cause,
            suggestions=suggestions,
            custom_field="custom_value"
        )
        
        assert error.message == "Test error"
        assert error.error_code == ErrorCode.VALIDATION_ERROR
        assert error.severity == ErrorSeverity.HIGH
        assert error.context.stock_code == "2330"
        assert error.cause == cause
        assert error.suggestions == suggestions
        assert error.context.additional_data["custom_field"] == "custom_value"
    
    def test_to_dict(self):
        """Test converting error to dictionary."""
        error = TwStockAgentError(
            message="Test error",
            error_code=ErrorCode.STOCK_NOT_FOUND,
            severity=ErrorSeverity.HIGH,
            suggestions=["Check stock code"]
        )
        error.context.stock_code = "2330"
        
        error_dict = error.to_dict()
        
        assert error_dict["error"] is True
        assert error_dict["error_code"] == "STOCK_NOT_FOUND"
        assert error_dict["message"] == "Test error"
        assert error_dict["severity"] == "high"
        assert error_dict["stock_code"] == "2330"
        assert error_dict["suggestions"] == ["Check stock code"]
        assert "timestamp" in error_dict
        assert "correlation_id" in error_dict
    
    def test_to_mcp_error(self):
        """Test converting error to MCP format."""
        error = TwStockAgentError(
            message="Test error",
            error_code=ErrorCode.MCP_VALIDATION_ERROR
        )
        
        mcp_error = error.to_mcp_error()
        
        assert "error" in mcp_error
        assert mcp_error["error"]["code"] == "MCP_VALIDATION_ERROR"
        assert mcp_error["error"]["message"] == "Test error"
        assert "data" in mcp_error["error"]


class TestStockExceptions:
    """Test stock-specific exceptions."""
    
    def test_stock_not_found_error(self):
        """Test StockNotFoundError."""
        error = StockNotFoundError("2330")
        
        assert error.error_code == ErrorCode.STOCK_NOT_FOUND
        assert error.severity == ErrorSeverity.MEDIUM
        assert error.context.stock_code == "2330"
        assert "not found" in error.message.lower()
        assert len(error.suggestions) > 0
    
    def test_invalid_stock_code_error(self):
        """Test InvalidStockCodeError."""
        error = InvalidStockCodeError("INVALID")
        
        assert error.error_code == ErrorCode.INVALID_STOCK_CODE
        assert error.severity == ErrorSeverity.HIGH
        assert error.context.stock_code == "INVALID"
        assert "invalid stock code" in error.message.lower()
        assert any("4-6 digit" in suggestion for suggestion in error.suggestions)
    
    def test_stock_data_unavailable_error(self):
        """Test StockDataUnavailableError."""
        error = StockDataUnavailableError("2330", "price data")
        
        assert error.error_code == ErrorCode.STOCK_DATA_UNAVAILABLE
        assert error.severity == ErrorSeverity.MEDIUM
        assert error.context.stock_code == "2330"
        assert "price data" in error.message.lower()
        assert len(error.suggestions) > 0
    
    def test_stock_market_closed_error(self):
        """Test StockMarketClosedError."""
        error = StockMarketClosedError("2330")
        
        assert error.error_code == ErrorCode.STOCK_MARKET_CLOSED
        assert error.severity == ErrorSeverity.LOW
        assert error.context.stock_code == "2330"
        assert "market is closed" in error.message.lower()
        assert any("market hours" in suggestion.lower() for suggestion in error.suggestions)


class TestAPIExceptions:
    """Test API-related exceptions."""
    
    def test_rate_limit_error(self):
        """Test RateLimitError."""
        error = RateLimitError("test_api", retry_after=60)
        
        assert error.error_code == ErrorCode.RATE_LIMIT_EXCEEDED
        assert error.severity == ErrorSeverity.MEDIUM
        assert error.context.additional_data["api_name"] == "test_api"
        assert error.context.additional_data["retry_after"] == 60
        assert "rate limit exceeded" in error.message.lower()
        assert "60 seconds" in error.suggestions[0]
    
    def test_external_api_error(self):
        """Test ExternalAPIError."""
        error = ExternalAPIError("test_api", 500, "Internal Server Error")
        
        assert error.error_code == ErrorCode.EXTERNAL_API_ERROR
        assert error.severity == ErrorSeverity.HIGH
        assert error.context.additional_data["api_name"] == "test_api"
        assert error.context.additional_data["status_code"] == 500
        assert "HTTP 500" in error.message
    
    def test_timeout_error(self):
        """Test TimeoutError."""
        error = TimeoutError("test_api", 30.0, "fetch_data")
        
        assert error.error_code == ErrorCode.API_TIMEOUT
        assert error.severity == ErrorSeverity.MEDIUM
        assert error.context.additional_data["api_name"] == "test_api"
        assert error.context.additional_data["timeout_seconds"] == 30.0
        assert "timed out after 30.0 seconds" in error.message


class TestValidationExceptions:
    """Test validation exceptions."""
    
    def test_parameter_validation_error(self):
        """Test ParameterValidationError."""
        error = ParameterValidationError(
            "stock_code",
            "INVALID",
            "4-6 digit format"
        )
        
        assert error.error_code == ErrorCode.PARAMETER_INVALID
        assert error.severity == ErrorSeverity.MEDIUM
        assert error.context.additional_data["field_name"] == "stock_code"
        assert error.context.additional_data["field_value"] == "INVALID"
        assert "4-6 digit format" in error.message
    
    def test_type_validation_error(self):
        """Test TypeValidationError."""
        error = TypeValidationError(
            "days",
            "int",
            "str",
            "30"
        )
        
        assert error.error_code == ErrorCode.TYPE_ERROR
        assert error.severity == ErrorSeverity.MEDIUM
        assert error.context.additional_data["field_name"] == "days"
        assert error.context.additional_data["expected_type"] == "int"
        assert error.context.additional_data["received_type"] == "str"
        assert "expected int, got str" in error.message
    
    def test_stock_code_validation_error(self):
        """Test StockCodeValidationError."""
        error = StockCodeValidationError("ABC123")
        
        assert error.error_code == ErrorCode.INVALID_STOCK_CODE
        assert error.severity == ErrorSeverity.HIGH
        assert error.context.additional_data["field_name"] == "stock_code"
        assert error.context.additional_data["field_value"] == "ABC123"
        assert any("2330" in suggestion for suggestion in error.suggestions)


class TestMCPExceptions:
    """Test MCP-specific exceptions."""
    
    def test_mcp_validation_error(self):
        """Test MCPValidationError."""
        error = MCPValidationError(
            "stock_code",
            "string",
            123,
            "get_stock_data"
        )
        
        assert error.error_code == ErrorCode.MCP_VALIDATION_ERROR
        assert error.context.additional_data["parameter"] == "stock_code"
        assert error.context.additional_data["expected_type"] == "string"
        assert error.context.additional_data["received_value"] == 123
    
    def test_mcp_error_to_response(self):
        """Test MCPError to MCP response conversion."""
        error = MCPError(
            "Test MCP error",
            mcp_method="get_stock_data",
            request_id="req_123"
        )
        
        response = error.to_mcp_response()
        
        assert response["jsonrpc"] == "2.0"
        assert "error" in response
        assert response["error"]["message"] == "Test MCP error"
        assert response["id"] == "req_123"
        assert "data" in response["error"]


class TestCacheExceptions:
    """Test cache-related exceptions."""
    
    def test_cache_connection_error(self):
        """Test CacheConnectionError."""
        error = CacheConnectionError("redis")
        
        assert error.error_code == ErrorCode.CACHE_CONNECTION_ERROR
        assert error.severity == ErrorSeverity.HIGH
        assert error.context.additional_data["cache_backend"] == "redis"
        assert "redis" in error.message
    
    def test_cache_key_error(self):
        """Test CacheKeyError."""
        error = CacheKeyError("invalid_key", "get")
        
        assert error.error_code == ErrorCode.CACHE_KEY_ERROR
        assert error.severity == ErrorSeverity.MEDIUM
        assert error.context.additional_data["cache_key"] == "invalid_key"
        assert error.context.operation == "get"


class TestErrorResponseCreation:
    """Test error response creation utilities."""
    
    def test_create_error_response_with_tw_stock_mcp_error(self):
        """Test creating error response from TwStockAgentError."""
        error = StockNotFoundError("2330")
        response = create_error_response(error)
        
        assert response["error"] is True
        assert response["error_code"] == "STOCK_NOT_FOUND"
        assert response["stock_code"] == "2330"
        assert "correlation_id" in response
    
    def test_create_error_response_with_generic_exception(self):
        """Test creating error response from generic exception."""
        error = ValueError("Invalid value")
        response = create_error_response(error, include_traceback=False)
        
        assert response["error"] is True
        assert response["error_code"] == "INTERNAL_ERROR"
        assert response["message"] == "Invalid value"
        assert "traceback" not in response
    
    def test_create_error_response_with_traceback(self):
        """Test creating error response with traceback."""
        error = ValueError("Invalid value")
        response = create_error_response(error, include_traceback=True)
        
        assert response["error"] is True
        assert "traceback" in response


@pytest.mark.asyncio
class TestErrorIntegration:
    """Integration tests for error handling."""
    
    async def test_error_chaining(self):
        """Test error chaining and cause tracking."""
        original_error = ValueError("Original error")
        
        wrapped_error = StockDataUnavailableError(
            "2330",
            "stock data",
            "Failed to fetch data",
            cause=original_error
        )
        
        assert wrapped_error.cause == original_error
        
        error_dict = wrapped_error.to_dict()
        assert "cause" in error_dict
        assert error_dict["cause"]["type"] == "ValueError"
        assert error_dict["cause"]["message"] == "Original error"
    
    async def test_error_context_enrichment(self):
        """Test error context enrichment."""
        error = TwStockAgentError("Base error")
        
        # Enrich with additional context
        error.context.stock_code = "2330"
        error.context.operation = "fetch_data"
        error.context.additional_data["api_call"] = "twstock.get"
        
        error_dict = error.to_dict()
        
        assert error_dict["stock_code"] == "2330"
        assert error_dict["operation"] == "fetch_data"
        assert error_dict["additional_data"]["api_call"] == "twstock.get"
    
    async def test_error_severity_mapping(self):
        """Test error severity affects response format."""
        # Test different severities
        low_error = StockMarketClosedError("2330")
        medium_error = StockNotFoundError("2330")
        high_error = InvalidStockCodeError("INVALID")
        
        assert low_error.severity == ErrorSeverity.LOW
        assert medium_error.severity == ErrorSeverity.MEDIUM
        assert high_error.severity == ErrorSeverity.HIGH
        
        # Test that severity is preserved in error responses
        low_dict = low_error.to_dict()
        medium_dict = medium_error.to_dict()
        high_dict = high_error.to_dict()
        
        assert low_dict["severity"] == "low"
        assert medium_dict["severity"] == "medium"
        assert high_dict["severity"] == "high"