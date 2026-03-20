"""
Integration tests for the complete error handling system.

This module tests the error handling system end-to-end,
including interaction between components.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
import asyncio

from tw_stock_mcp.exceptions import (
    StockNotFoundError,
    InvalidStockCodeError,
    StockCodeValidationError,
    StockDataUnavailableError,
    RateLimitError,
    TwStockAgentError,
)
from tw_stock_mcp.utils.validation import StockCodeValidator
from tw_stock_mcp.utils.error_handler import ErrorEnricher, CircuitBreaker
from tw_stock_mcp.utils.mcp_error_handler import MCPErrorHandler
from tw_stock_mcp.services.stock_service import StockService
from tw_stock_mcp.tools.stock_tools import get_stock_data


class TestErrorHandlingIntegration:
    """Integration tests for error handling across components."""
    
    def test_stock_code_validation_to_exception_flow(self):
        """Test flow from validation to exception."""
        # Invalid stock code should raise proper exception
        with pytest.raises(StockCodeValidationError) as exc_info:
            StockCodeValidator.validate_stock_code("INVALID")
        
        error = exc_info.value
        assert error.error_code.value == "INVALID_STOCK_CODE"
        # Stock code is stored in additional_data for validation errors
        assert error.context.additional_data["field_value"] == "INVALID"
        assert len(error.suggestions) > 0
        
        # Convert to MCP error format
        mcp_error = error.to_mcp_error()
        assert mcp_error["error"]["code"] == "INVALID_STOCK_CODE"
    
    @pytest.mark.asyncio
    async def test_stock_service_error_propagation(self):
        """Test error propagation through StockService."""
        # Use a valid Taiwan stock code that doesn't exist for testing
        stock_service = StockService()
        
        # "9999" is in reserved range, so it should raise InvalidStockCodeError first
        with pytest.raises(InvalidStockCodeError) as exc_info:
            await stock_service.fetch_stock_data("9999")
        
        error = exc_info.value
        assert error.context.stock_code == "9999"
        assert error.context.operation == "fetch_stock_data"
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_integration(self):
        """Test circuit breaker with real error scenarios."""
        circuit_breaker = CircuitBreaker(failure_threshold=2, timeout_seconds=0.1)
        
        # Function that always fails
        async def failing_function():
            raise ConnectionError("Service unavailable")
        
        # First failure
        with pytest.raises(ConnectionError):
            await circuit_breaker.acall(failing_function)
        assert circuit_breaker.state == "CLOSED"
        
        # Second failure - should open circuit
        with pytest.raises(ConnectionError):
            await circuit_breaker.acall(failing_function)
        assert circuit_breaker.state == "OPEN"
        
        # Third call should be blocked by circuit breaker
        with pytest.raises(TwStockAgentError) as exc_info:
            await circuit_breaker.acall(failing_function)
        
        error = exc_info.value
        assert "Circuit breaker is OPEN" in error.message
        assert error.error_code.value == "DATA_SOURCE_UNAVAILABLE"
    
    @pytest.mark.asyncio
    async def test_mcp_tool_error_handling_integration(self):
        """Test complete MCP tool error handling flow."""
        # Mock StockService to raise an exception
        with patch('tw_stock_mcp.tools.stock_tools.stock_service') as mock_service:
            mock_service.fetch_stock_data = AsyncMock()
            mock_service.fetch_stock_data.side_effect = StockNotFoundError("2330")
            
            # Call the tool function
            with pytest.raises(StockNotFoundError) as exc_info:
                await get_stock_data("2330")
            
            error = exc_info.value
            
            # Handle the error through MCP handler
            mcp_response = MCPErrorHandler.handle_tool_error(
                error=error,
                tool_name="get_stock_data",
                parameters={"stock_code": "2330"}
            )
            
            assert "error" in mcp_response
            assert mcp_response["error"]["code"] == "STOCK_NOT_FOUND"
    
    @pytest.mark.asyncio
    async def test_validation_error_enrichment_chain(self):
        """Test error enrichment chain from validation through service."""
        # Test invalid stock code through the complete chain
        with pytest.raises(StockCodeValidationError) as exc_info:
            await get_stock_data("INVALID")
        
        error = exc_info.value
        
        # Enrich the error with additional context
        enriched_error = ErrorEnricher.enrich_error(
            error=error,
            operation="user_request",
            user_id="test_user",
            api_version="v1"
        )
        
        # Should be the same error instance, but enriched
        assert enriched_error is error
        assert error.context.operation == "user_request"
        assert error.context.user_id == "test_user"
        assert error.context.additional_data["api_version"] == "v1"
        
        # Convert to dict and verify all context is preserved
        error_dict = error.to_dict()
        assert error_dict["operation"] == "user_request"
        assert error_dict["user_id"] == "test_user"
        assert error_dict["additional_data"]["api_version"] == "v1"
    
    def test_error_serialization_roundtrip(self):
        """Test error serialization and deserialization."""
        import json
        
        # Create a complex error with full context
        error = StockDataUnavailableError(
            stock_code="2330",
            data_type="price data",
            message="API temporarily unavailable"
        )
        error.context.operation = "fetch_price_data"
        error.context.user_id = "test_user"
        error.context.additional_data = {
            "retry_count": 3,
            "api_endpoint": "/v1/stocks/2330/prices"
        }
        
        # Convert to dict
        error_dict = error.to_dict()
        
        # Serialize to JSON
        json_str = json.dumps(error_dict, ensure_ascii=False)
        
        # Deserialize back
        deserialized = json.loads(json_str)
        
        # Verify all data is preserved
        assert deserialized["error_code"] == "STOCK_DATA_UNAVAILABLE"
        assert deserialized["stock_code"] == "2330"
        assert deserialized["operation"] == "fetch_price_data"
        assert deserialized["user_id"] == "test_user"
        assert deserialized["additional_data"]["retry_count"] == 3
    
    @pytest.mark.asyncio
    async def test_rate_limiting_error_scenario(self):
        """Test rate limiting error scenario."""
        # Simulate rate limit error
        rate_limit_error = RateLimitError(
            api_name="twstock_api",
            retry_after=60,
            current_limit=100
        )
        
        # Enrich with context
        enriched_error = ErrorEnricher.enrich_error(
            error=rate_limit_error,
            operation="fetch_realtime_data",
            stock_code="2330"
        )
        
        # Convert to MCP response
        mcp_response = MCPErrorHandler.handle_tool_error(
            error=enriched_error,
            tool_name="get_realtime_data",
            parameters={"stock_code": "2330"}
        )
        
        # Verify proper error structure
        assert mcp_response["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert "60 seconds" in mcp_response["error"]["data"]["suggestions"][0]
    
    def test_error_correlation_tracking(self):
        """Test error correlation across multiple components."""
        # Create initial error
        original_error = ConnectionError("Network timeout")
        
        # Enrich through different components
        enriched_1 = ErrorEnricher.enrich_error(
            error=original_error,
            operation="api_call",
            stock_code="2330"
        )
        
        # Save correlation ID
        correlation_id = enriched_1.context.correlation_id
        
        # Further enrich the same error
        enriched_2 = ErrorEnricher.enrich_error(
            error=enriched_1,
            operation="service_layer",
            user_id="test_user"
        )
        
        # Should maintain the same correlation ID
        assert enriched_2.context.correlation_id == correlation_id
        assert enriched_2.context.operation == "service_layer"
        assert enriched_2.context.stock_code == "2330"
        assert enriched_2.context.user_id == "test_user"
    
    @pytest.mark.asyncio
    async def test_concurrent_error_handling(self):
        """Test error handling under concurrent operations."""
        async def failing_operation(stock_code: str):
            if stock_code == "INVALID":
                raise StockCodeValidationError(stock_code, "Invalid format - must be 4-6 digits")
            elif stock_code == "9999":
                raise InvalidStockCodeError(stock_code)  # Reserved range error
            else:
                return {"stock_code": stock_code, "status": "ok"}
        
        # Run multiple operations concurrently
        tasks = [
            failing_operation("2330"),
            failing_operation("INVALID"),
            failing_operation("1101"),
            failing_operation("9999"),
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Check results
        assert results[0]["status"] == "ok"  # 2330 success
        assert isinstance(results[1], StockCodeValidationError)  # INVALID
        assert results[2]["status"] == "ok"  # 1101 success
        assert isinstance(results[3], InvalidStockCodeError)  # 9999
        
        # Verify each error has unique correlation ID
        error_1 = results[1]
        error_2 = results[3]
        assert error_1.context.correlation_id != error_2.context.correlation_id
    
    def test_error_severity_escalation(self):
        """Test error severity escalation patterns."""
        # Start with low severity error
        low_error = StockDataUnavailableError(
            stock_code="2330",
            data_type="real-time data",
            message="Market is closed"
        )
        # This should have MEDIUM severity by default
        
        # Escalate to high severity by adding context
        high_context_error = ErrorEnricher.enrich_error(
            error=low_error,
            operation="critical_trading_decision",
            trading_session="active",
            escalation_reason="time_sensitive_operation"
        )
        
        # Error severity should be preserved but context indicates escalation
        assert high_context_error.severity.value == "medium"
        assert high_context_error.context.additional_data["escalation_reason"] == "time_sensitive_operation"
    
    @pytest.mark.asyncio
    async def test_error_recovery_patterns(self):
        """Test error recovery patterns."""
        call_count = 0
        
        async def flaky_operation():
            nonlocal call_count
            call_count += 1
            
            if call_count <= 2:
                raise StockDataUnavailableError(
                    stock_code="2330",
                    data_type="price data",
                    message="Temporary service unavailable"
                )
            return {"data": "recovered"}
        
        # Use circuit breaker with retry logic simulation
        circuit_breaker = CircuitBreaker(failure_threshold=3)
        
        # First two calls should fail
        with pytest.raises(StockDataUnavailableError):
            await circuit_breaker.acall(flaky_operation)
        
        with pytest.raises(StockDataUnavailableError):
            await circuit_breaker.acall(flaky_operation)
        
        # Third call should succeed (service recovered)
        result = await circuit_breaker.acall(flaky_operation)
        assert result["data"] == "recovered"
        assert circuit_breaker.state == "CLOSED"
        assert circuit_breaker.failure_count == 0


class TestErrorHandlingEdgeCases:
    """Test edge cases in error handling."""
    
    def test_nested_error_handling(self):
        """Test handling of nested exceptions."""
        # Create a chain of exceptions
        original = ValueError("Original error")
        wrapped = StockDataUnavailableError(
            stock_code="2330",
            data_type="nested test",
            cause=original
        )
        outer = TwStockAgentError(
            message="Outer error",
            cause=wrapped
        )
        
        # Convert to dict and verify cause chain is preserved
        error_dict = outer.to_dict()
        
        assert "cause" in error_dict
        assert error_dict["cause"]["type"] == "StockDataUnavailableError"
    
    def test_error_with_none_values(self):
        """Test error handling with None values."""
        error = TwStockAgentError(
            message="Test error",
            stock_code=None,
            operation=None
        )
        
        # Should handle None values gracefully
        error_dict = error.to_dict()
        
        # None values should not appear in dict
        assert "stock_code" not in error_dict
        assert "operation" not in error_dict
        assert error_dict["message"] == "Test error"
    
    def test_error_with_large_context(self):
        """Test error handling with large context data."""
        # Create error with large context
        large_data = {f"key_{i}": f"value_{i}" * 100 for i in range(100)}
        
        error = TwStockAgentError("Test error")
        error.context.additional_data.update(large_data)
        
        # Should handle large context without issues
        error_dict = error.to_dict()
        assert len(error_dict["additional_data"]) == 100
        
        # Should be serializable
        import json
        json_str = json.dumps(error_dict)
        assert len(json_str) > 10000  # Verify it's actually large


@pytest.mark.asyncio
class TestRealWorldScenarios:
    """Test real-world error scenarios."""
    
    async def test_market_closure_scenario(self):
        """Test handling of market closure scenarios."""
        from tw_stock_mcp.exceptions import StockMarketClosedError
        
        # Simulate market closed error
        error = StockMarketClosedError("2330")
        
        # Should have appropriate severity and suggestions
        assert error.severity == error.severity.LOW
        assert any("market hours" in suggestion.lower() for suggestion in error.suggestions)
        
        # Should format properly for MCP
        mcp_response = MCPErrorHandler.handle_tool_error(
            error=error,
            tool_name="get_realtime_data",
            parameters={"stock_code": "2330"}
        )
        
        assert mcp_response["error"]["code"] == "STOCK_MARKET_CLOSED"
    
    async def test_data_source_failure_scenario(self):
        """Test handling of external data source failures."""
        from tw_stock_mcp.exceptions import DataSourceUnavailableError
        
        # Simulate data source failure
        error = DataSourceUnavailableError(
            data_source="twstock_api",
            estimated_recovery="2023-12-01T15:00:00"
        )
        
        # Should include recovery information
        assert "twstock_api" in error.message
        assert error.context.additional_data["estimated_recovery"] == "2023-12-01T15:00:00"
        
        # Should suggest appropriate actions
        assert any("expected to recover" in suggestion for suggestion in error.suggestions)
    
    async def test_invalid_stock_portfolio_scenario(self):
        """Test handling of invalid stock codes in portfolio requests."""
        invalid_codes = ["INVALID", "999", "ABCD", "123456789"]
        
        errors = []
        for code in invalid_codes:
            try:
                StockCodeValidator.validate_stock_code(code)
            except (InvalidStockCodeError, StockCodeValidationError) as e:
                errors.append(e)
        
        # Should have caught all invalid codes
        assert len(errors) == len(invalid_codes)
        
        # All should be validation errors
        for error in errors:
            assert error.error_code.value in ["INVALID_STOCK_CODE", "VALIDATION_ERROR"]