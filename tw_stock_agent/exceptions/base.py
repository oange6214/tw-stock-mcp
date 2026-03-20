"""
Base exception classes and utilities for the Taiwan Stock Agent.

This module provides the foundation for all custom exceptions in the system,
including error codes, severity levels, and context management.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, Field


class ErrorSeverity(str, Enum):
    """Error severity levels."""
    
    LOW = "low"          # Minor issues, informational
    MEDIUM = "medium"    # Warnings, degraded functionality
    HIGH = "high"        # Errors, failed operations
    CRITICAL = "critical" # Critical system failures


class ErrorCode(str, Enum):
    """Standardized error codes for programmatic handling."""
    
    # Generic errors
    UNKNOWN_ERROR = "UNKNOWN_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    
    # Validation errors
    VALIDATION_ERROR = "VALIDATION_ERROR"
    PARAMETER_MISSING = "PARAMETER_MISSING"
    PARAMETER_INVALID = "PARAMETER_INVALID"
    DATA_FORMAT_ERROR = "DATA_FORMAT_ERROR"
    TYPE_ERROR = "TYPE_ERROR"
    
    # Stock specific errors
    STOCK_NOT_FOUND = "STOCK_NOT_FOUND"
    INVALID_STOCK_CODE = "INVALID_STOCK_CODE"
    STOCK_DATA_UNAVAILABLE = "STOCK_DATA_UNAVAILABLE"
    STOCK_MARKET_CLOSED = "STOCK_MARKET_CLOSED"
    STOCK_DELISTED = "STOCK_DELISTED"
    
    # API errors
    API_ERROR = "API_ERROR"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    DATA_SOURCE_UNAVAILABLE = "DATA_SOURCE_UNAVAILABLE"
    EXTERNAL_API_ERROR = "EXTERNAL_API_ERROR"
    API_TIMEOUT = "API_TIMEOUT"
    API_AUTHENTICATION_ERROR = "API_AUTHENTICATION_ERROR"
    
    # Cache errors
    CACHE_ERROR = "CACHE_ERROR"
    CACHE_CONNECTION_ERROR = "CACHE_CONNECTION_ERROR"
    CACHE_KEY_ERROR = "CACHE_KEY_ERROR"
    CACHE_SERIALIZATION_ERROR = "CACHE_SERIALIZATION_ERROR"
    CACHE_EXPIRED = "CACHE_EXPIRED"
    
    # MCP protocol errors
    MCP_ERROR = "MCP_ERROR"
    MCP_VALIDATION_ERROR = "MCP_VALIDATION_ERROR"
    MCP_RESOURCE_ERROR = "MCP_RESOURCE_ERROR"
    MCP_TOOL_ERROR = "MCP_TOOL_ERROR"
    MCP_PROTOCOL_ERROR = "MCP_PROTOCOL_ERROR"


class ErrorContext(BaseModel):
    """Context information for errors."""
    
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.now)
    stock_code: Optional[str] = None
    operation: Optional[str] = None
    user_id: Optional[str] = None
    request_id: Optional[str] = None
    additional_data: Dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class TwStockAgentError(Exception):
    """
    Base exception class for Taiwan Stock Agent.
    
    All custom exceptions in the system should inherit from this class.
    Provides structured error information including error codes, severity,
    context, and user-friendly messages.
    """
    
    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.UNKNOWN_ERROR,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        context: Optional[ErrorContext] = None,
        cause: Optional[Exception] = None,
        suggestions: Optional[list[str]] = None,
        **kwargs: Any
    ) -> None:
        """
        Initialize the base exception.
        
        Args:
            message: Human-readable error message
            error_code: Standardized error code for programmatic handling
            severity: Error severity level
            context: Additional context information
            cause: Original exception that caused this error
            suggestions: List of suggestions to resolve the error
            **kwargs: Additional context data
        """
        super().__init__(message)
        
        self.message = message
        self.error_code = error_code
        self.severity = severity
        self.cause = cause
        self.suggestions = suggestions or []
        
        # Create context if not provided
        if context is None:
            context = ErrorContext()
        
        # Add any additional kwargs to context
        for key, value in kwargs.items():
            if hasattr(context, key):
                setattr(context, key, value)
            else:
                context.additional_data[key] = value
        
        self.context = context
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert exception to dictionary format.
        
        Returns:
            Dictionary representation of the error
        """
        result = {
            "error": True,
            "error_code": self.error_code.value,
            "message": self.message,
            "severity": self.severity.value,
            "timestamp": self.context.timestamp.isoformat(),
            "correlation_id": self.context.correlation_id,
        }
        
        # Add context fields if present
        if self.context.stock_code:
            result["stock_code"] = self.context.stock_code
        if self.context.operation:
            result["operation"] = self.context.operation
        if self.context.user_id:
            result["user_id"] = self.context.user_id
        if self.context.request_id:
            result["request_id"] = self.context.request_id
        
        # Add additional context data
        if self.context.additional_data:
            result["additional_data"] = self.context.additional_data
        
        # Add suggestions if present
        if self.suggestions:
            result["suggestions"] = self.suggestions
        
        # Add cause information if present
        if self.cause:
            result["cause"] = {
                "type": type(self.cause).__name__,
                "message": str(self.cause)
            }
        
        return result
    
    def to_mcp_error(self) -> Dict[str, Any]:
        """
        Convert exception to MCP-compatible error format.
        
        Returns:
            MCP-compatible error dictionary
        """
        return {
            "error": {
                "code": self.error_code.value,
                "message": self.message,
                "data": {
                    "severity": self.severity.value,
                    "correlation_id": self.context.correlation_id,
                    "timestamp": self.context.timestamp.isoformat(),
                    "suggestions": self.suggestions,
                    "context": self.context.dict(exclude_none=True)
                }
            }
        }
    
    def __str__(self) -> str:
        """String representation of the error."""
        return f"{self.error_code.value}: {self.message}"
    
    def __repr__(self) -> str:
        """Detailed string representation of the error."""
        return (
            f"{self.__class__.__name__}("
            f"message='{self.message}', "
            f"error_code={self.error_code.value}, "
            f"severity={self.severity.value}, "
            f"correlation_id='{self.context.correlation_id}'"
            f")"
        )


def create_error_response(
    error: Union[TwStockAgentError, Exception],
    include_traceback: bool = False
) -> Dict[str, Any]:
    """
    Create a standardized error response from any exception.
    
    Args:
        error: Exception to convert
        include_traceback: Whether to include traceback information
        
    Returns:
        Standardized error response dictionary
    """
    if isinstance(error, TwStockAgentError):
        response = error.to_dict()
    else:
        # Handle non-TwStockAgentError exceptions
        response = {
            "error": True,
            "error_code": ErrorCode.INTERNAL_ERROR.value,
            "message": str(error),
            "severity": ErrorSeverity.HIGH.value,
            "timestamp": datetime.now().isoformat(),
            "correlation_id": str(uuid.uuid4()),
            "cause": {
                "type": type(error).__name__,
                "message": str(error)
            }
        }
    
    if include_traceback:
        import traceback
        response["traceback"] = traceback.format_exc()
    
    return response