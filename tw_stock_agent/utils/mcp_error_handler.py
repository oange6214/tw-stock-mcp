"""
MCP-specific error handling utilities for Taiwan Stock Agent.

This module provides utilities for converting internal exceptions to
proper MCP protocol responses and handling MCP-specific error scenarios.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from mcp.server.fastmcp import FastMCP

from ..exceptions import (
    ErrorCode,
    ErrorSeverity,
    MCPError,
    MCPValidationError,
    TwStockAgentError,
    create_error_response,
)

logger = logging.getLogger("tw-stock-agent.mcp_error_handler")


class MCPErrorHandler:
    """Handles conversion of internal errors to MCP protocol responses."""
    
    @staticmethod
    def handle_tool_error(
        error: Exception,
        tool_name: str,
        parameters: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Handle errors from MCP tool execution.
        
        Args:
            error: Exception that occurred
            tool_name: Name of the tool that failed
            parameters: Tool parameters that were used
            request_id: MCP request ID
            
        Returns:
            MCP-compatible error response
        """
        # Convert to TwStockAgentError if needed
        if not isinstance(error, TwStockAgentError):
            tw_error = TwStockAgentError(
                message=f"Tool '{tool_name}' execution failed: {str(error)}",
                error_code=ErrorCode.MCP_TOOL_ERROR,
                severity=ErrorSeverity.HIGH,
                cause=error
            )
            tw_error.context.operation = f"tool_execution_{tool_name}"
            tw_error.context.request_id = request_id
            if parameters:
                tw_error.context.additional_data["tool_parameters"] = parameters
        else:
            tw_error = error
            if not tw_error.context.operation:
                tw_error.context.operation = f"tool_execution_{tool_name}"
            if request_id and not tw_error.context.request_id:
                tw_error.context.request_id = request_id
        
        # Log the error
        logger.error(
            f"MCP tool error in '{tool_name}': {str(error)}",
            extra={
                "tool_name": tool_name,
                "error_code": tw_error.error_code.value,
                "correlation_id": tw_error.context.correlation_id,
                "parameters": parameters
            },
            exc_info=True
        )
        
        return tw_error.to_mcp_error()
    
    @staticmethod
    def handle_resource_error(
        error: Exception,
        resource_uri: str,
        request_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Handle errors from MCP resource access.
        
        Args:
            error: Exception that occurred
            resource_uri: URI of the resource that failed
            request_id: MCP request ID
            
        Returns:
            MCP-compatible error response
        """
        # Convert to TwStockAgentError if needed
        if not isinstance(error, TwStockAgentError):
            tw_error = TwStockAgentError(
                message=f"Resource access failed for '{resource_uri}': {str(error)}",
                error_code=ErrorCode.MCP_RESOURCE_ERROR,
                severity=ErrorSeverity.MEDIUM,
                cause=error
            )
            tw_error.context.operation = f"resource_access"
            tw_error.context.request_id = request_id
            tw_error.context.additional_data["resource_uri"] = resource_uri
        else:
            tw_error = error
            if not tw_error.context.operation:
                tw_error.context.operation = "resource_access"
            if request_id and not tw_error.context.request_id:
                tw_error.context.request_id = request_id
        
        # Log the error
        logger.error(
            f"MCP resource error for '{resource_uri}': {str(error)}",
            extra={
                "resource_uri": resource_uri,
                "error_code": tw_error.error_code.value,
                "correlation_id": tw_error.context.correlation_id
            },
            exc_info=True
        )
        
        return tw_error.to_mcp_error()
    
    @staticmethod
    def handle_validation_error(
        error: Exception,
        parameter_name: str,
        parameter_value: Any,
        tool_name: Optional[str] = None,
        request_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Handle parameter validation errors for MCP tools.
        
        Args:
            error: Validation exception
            parameter_name: Name of invalid parameter
            parameter_value: Value that failed validation
            tool_name: Name of the tool (if applicable)
            request_id: MCP request ID
            
        Returns:
            MCP-compatible error response
        """
        # Create specific validation error
        if isinstance(error, TwStockAgentError):
            validation_error = error
        else:
            validation_error = MCPValidationError(
                parameter=parameter_name,
                received_value=parameter_value,
                mcp_method=tool_name,
                message=str(error)
            )
            validation_error.context.request_id = request_id
        
        # Log the validation error
        logger.warning(
            f"MCP validation error for parameter '{parameter_name}': {str(error)}",
            extra={
                "parameter_name": parameter_name,
                "parameter_value": parameter_value,
                "tool_name": tool_name,
                "error_code": validation_error.error_code.value,
                "correlation_id": validation_error.context.correlation_id
            }
        )
        
        return validation_error.to_mcp_error()
    
    @staticmethod
    def create_success_response(
        data: Any,
        request_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a successful MCP response.
        
        Args:
            data: Response data
            request_id: MCP request ID
            metadata: Additional metadata
            
        Returns:
            MCP-compatible success response
        """
        response = {
            "jsonrpc": "2.0",
            "result": data,
            "id": request_id
        }
        
        if metadata:
            if isinstance(data, dict):
                response["result"]["_metadata"] = metadata
            else:
                response["_metadata"] = metadata
        
        return response


def mcp_error_handler(tool_name: str):
    """
    Decorator for MCP tool functions to handle errors properly.
    
    Args:
        tool_name: Name of the MCP tool
        
    Returns:
        Decorated function with error handling
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                # Extract request ID from kwargs if available
                request_id = kwargs.get('request_id')
                
                # Handle the error and return proper MCP response
                error_response = MCPErrorHandler.handle_tool_error(
                    error=e,
                    tool_name=tool_name,
                    parameters=kwargs,
                    request_id=request_id
                )
                
                # For MCP tools, we typically want to raise the error
                # so the MCP framework can handle it properly
                if isinstance(e, TwStockAgentError):
                    raise e
                else:
                    # Convert to appropriate MCP error
                    mcp_error = MCPError(
                        message=str(e),
                        mcp_method=tool_name,
                        request_id=request_id
                    )
                    raise mcp_error
        
        return wrapper
    return decorator


def mcp_resource_handler(resource_type: str):
    """
    Decorator for MCP resource functions to handle errors properly.
    
    Args:
        resource_type: Type of the MCP resource
        
    Returns:
        Decorated function with error handling
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                # Extract resource URI from args/kwargs if available
                resource_uri = kwargs.get('resource_uri') or (args[0] if args else 'unknown')
                
                # Handle the error and return proper MCP response
                error_response = MCPErrorHandler.handle_resource_error(
                    error=e,
                    resource_uri=str(resource_uri)
                )
                
                # For MCP resources, we typically want to raise the error
                if isinstance(e, TwStockAgentError):
                    raise e
                else:
                    # Convert to appropriate MCP error
                    mcp_error = MCPError(
                        message=str(e),
                        error_code=ErrorCode.MCP_RESOURCE_ERROR
                    )
                    raise mcp_error
        
        return wrapper
    return decorator


class MCPResponseFormatter:
    """Enhanced formatter for MCP protocol compliance with structured output consistency."""
    
    @staticmethod
    def format_stock_data_response(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format stock data for MCP response with enhanced metadata structure.
        
        Args:
            data: Raw stock data dictionary
            
        Returns:
            Formatted response with consistent metadata structure
        """
        # Ensure consistent metadata structure
        metadata = {
            "source": "tw-stock-agent",
            "version": "1.0",
            "data_type": "stock_data",
            "has_error": "error" in data and data["error"] is not None,
            "timestamp": data.get("updated_at", datetime.now().isoformat())
        }
        
        # Handle error responses
        if metadata["has_error"]:
            return {
                "stock_code": data.get("stock_code"),
                "error": data["error"],
                "updated_at": metadata["timestamp"],
                "_metadata": metadata
            }
        
        # Format successful response with enhanced metadata
        response = {**data}
        response["_metadata"] = metadata
        
        # Add performance metrics if available
        if "cache_info" in data:
            metadata["cache_info"] = data["cache_info"]
        
        return response
    
    @staticmethod
    def format_price_data_response(data: Union[Dict[str, Any], List[Any]]) -> Dict[str, Any]:
        """
        Format price data for MCP response with enhanced structure.
        
        Args:
            data: Price data (dict or list)
            
        Returns:
            Formatted response with consistent metadata
        """
        # Handle both dict (error) and list (success) formats
        if isinstance(data, dict):
            # Check if it's an error response
            if "error" in data and data["error"]:
                metadata = {
                    "source": "tw-stock-agent",
                    "version": "1.0",
                    "data_type": "price_history",
                    "has_error": True,
                    "record_count": 0,
                    "timestamp": data.get("updated_at", datetime.now().isoformat())
                }
                
                return {
                    "stock_code": data.get("stock_code"),
                    "period": data.get("period", "unknown"),
                    "data": [],
                    "error": data["error"],
                    "_metadata": metadata
                }
            else:
                # Success response in dict format (enhanced price history)
                price_data = data.get("data", [])
                metadata = {
                    "source": "tw-stock-agent",
                    "version": "1.0",
                    "data_type": "price_history",
                    "has_error": False,
                    "record_count": len(price_data),
                    "timestamp": data.get("updated_at", datetime.now().isoformat())
                }
                
                response = {**data}
                response["_metadata"] = metadata
                return response
        
        # Handle list format (legacy support)
        metadata = {
            "source": "tw-stock-agent",
            "version": "1.0",
            "data_type": "price_data",
            "has_error": False,
            "record_count": len(data) if isinstance(data, list) else 1,
            "timestamp": datetime.now().isoformat()
        }
        
        return {
            "data": data if isinstance(data, list) else [data],
            "_metadata": metadata
        }
    
    @staticmethod
    def format_realtime_data_response(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format realtime data for MCP response.
        
        Args:
            data: Realtime stock data
            
        Returns:
            Formatted response with enhanced metadata
        """
        metadata = {
            "source": "tw-stock-agent",
            "version": "1.0",
            "data_type": "realtime_data",
            "has_error": "error" in data and data["error"] is not None,
            "timestamp": data.get("updated_at", datetime.now().isoformat()),
            "market_status": data.get("market_status", "unknown")
        }
        
        if metadata["has_error"]:
            return {
                "stock_code": data.get("stock_code"),
                "error": data["error"],
                "updated_at": metadata["timestamp"],
                "_metadata": metadata
            }
        
        # Clean data - convert "-" strings to None for optional price fields
        cleaned_data = {}
        price_fields = ["current_price", "open", "high", "low", "opening_price", "highest_price", "lowest_price"]
        
        for key, value in data.items():
            if key in price_fields and value == "-":
                cleaned_data[key] = None  # Convert "-" to None for optional price fields
            else:
                cleaned_data[key] = value
        
        response = {**cleaned_data}
        response["_metadata"] = metadata
        return response
    
    @staticmethod
    def format_technical_analysis_response(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format technical analysis (Best Four Points) data for MCP response.
        
        Args:
            data: Technical analysis data
            
        Returns:
            Formatted response with analysis metadata
        """
        buy_signals = data.get("buy_signals", data.get("buy_points", []))
        sell_signals = data.get("sell_signals", data.get("sell_points", []))
        
        metadata = {
            "source": "tw-stock-agent",
            "version": "1.0",
            "data_type": "technical_analysis",
            "has_error": "error" in data and data["error"] is not None,
            "timestamp": data.get("updated_at", datetime.now().isoformat()),
            "signal_count": len(buy_signals) + len(sell_signals)
        }
        
        if metadata["has_error"]:
            return {
                "stock_code": data.get("stock_code"),
                "error": data["error"],
                "updated_at": metadata["timestamp"],
                "_metadata": metadata
            }
        
        response = {**data}
        response["_metadata"] = metadata
        return response
    
    @staticmethod
    def format_market_overview_response(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format market overview data for MCP response.
        
        Args:
            data: Market overview data
            
        Returns:
            Formatted response with market metadata
        """
        metadata = {
            "source": "tw-stock-agent",
            "version": "1.0",
            "data_type": "market_overview",
            "has_error": "error" in data and data["error"] is not None,
            "timestamp": data.get("updated_at", datetime.now().isoformat()),
            "market_date": data.get("trading_date", data.get("date"))
        }
        
        if metadata["has_error"]:
            return {
                "date": data.get("trading_date", data.get("date")),
                "error": data["error"],
                "updated_at": metadata["timestamp"],
                "_metadata": metadata
            }
        
        response = {**data}
        response["_metadata"] = metadata
        return response
    
    @staticmethod
    def format_generic_response(
        data: Dict[str, Any], 
        data_type: str = "generic",
        additional_metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Format generic response with consistent metadata structure.
        
        Args:
            data: Response data
            data_type: Type of data being formatted
            additional_metadata: Additional metadata to include
            
        Returns:
            Formatted response with consistent structure
        """
        metadata = {
            "source": "tw-stock-agent",
            "version": "1.0",
            "data_type": data_type,
            "has_error": "error" in data and data["error"] is not None,
            "timestamp": data.get("updated_at", datetime.now().isoformat())
        }
        
        if additional_metadata:
            metadata.update(additional_metadata)
        
        response = {**data}
        response["_metadata"] = metadata
        return response
    
    @staticmethod
    def format_error_response(
        error: Union[TwStockAgentError, Exception],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Format error response with enhanced structure.
        
        Args:
            error: Exception to format
            context: Additional context information
            
        Returns:
            Formatted error response
        """
        if isinstance(error, TwStockAgentError):
            error_response = error.to_mcp_error()
        else:
            error_response = create_error_response(error)
        
        # Enhance error response with consistent metadata
        metadata = {
            "source": "tw-stock-agent",
            "version": "1.0",
            "data_type": "error",
            "has_error": True,
            "timestamp": datetime.now().isoformat(),
            "error_type": type(error).__name__
        }
        
        if context:
            metadata.update(context)
        
        error_response["_metadata"] = metadata
        return error_response
    
    @staticmethod
    def extract_metadata_for_model(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract and remove metadata from response for Pydantic model creation.
        
        Args:
            data: Response data with metadata
            
        Returns:
            Data without metadata, suitable for model creation
        """
        clean_data = {k: v for k, v in data.items() if k != "_metadata"}
        return clean_data
    
    @staticmethod
    def validate_response_structure(data: Dict[str, Any]) -> bool:
        """
        Validate that response follows the expected structure.
        
        Args:
            data: Response data to validate
            
        Returns:
            True if structure is valid, False otherwise
        """
        required_metadata_fields = {"source", "version", "data_type", "has_error", "timestamp"}
        
        if "_metadata" not in data:
            return False
        
        metadata = data["_metadata"]
        if not isinstance(metadata, dict):
            return False
        
        # Check for required fields
        if not required_metadata_fields.issubset(set(metadata.keys())):
            return False
        
        # Validate field types
        if not isinstance(metadata.get("has_error"), bool):
            return False
        
        if not isinstance(metadata.get("source"), str):
            return False
        
        return True