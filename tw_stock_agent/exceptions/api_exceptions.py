"""
API-related exception classes for Taiwan Stock Agent.

This module contains exceptions for external API interactions,
rate limiting, timeouts, and data source issues.
"""

from typing import Optional

from .base import ErrorCode, ErrorContext, ErrorSeverity, TwStockAgentError


class APIError(TwStockAgentError):
    """Base exception for API-related errors."""
    
    def __init__(
        self,
        message: str,
        api_name: Optional[str] = None,
        status_code: Optional[int] = None,
        error_code: ErrorCode = ErrorCode.API_ERROR,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        context: Optional[ErrorContext] = None,
        **kwargs
    ) -> None:
        if context is None:
            context = ErrorContext()
        
        super().__init__(
            message=message,
            error_code=error_code,
            severity=severity,
            context=context,
            api_name=api_name,
            status_code=status_code,
            **kwargs
        )


class RateLimitError(APIError):
    """Exception raised when API rate limit is exceeded."""
    
    def __init__(
        self,
        api_name: str,
        retry_after: Optional[int] = None,
        current_limit: Optional[int] = None,
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            msg = f"Rate limit exceeded for {api_name} API"
            if retry_after:
                msg += f". Retry after {retry_after} seconds"
            message = msg
        
        suggestions = [
            "Wait before making another request",
            "Implement exponential backoff",
            "Use caching to reduce API calls",
            "Consider upgrading API plan if available"
        ]
        
        if retry_after:
            suggestions.insert(0, f"Wait {retry_after} seconds before retrying")
        
        super().__init__(
            message=message,
            api_name=api_name,
            error_code=ErrorCode.RATE_LIMIT_EXCEEDED,
            severity=ErrorSeverity.MEDIUM,
            suggestions=suggestions,
            retry_after=retry_after,
            current_limit=current_limit,
            **kwargs
        )


class DataSourceUnavailableError(APIError):
    """Exception raised when data source is unavailable."""
    
    def __init__(
        self,
        data_source: str,
        message: Optional[str] = None,
        estimated_recovery: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            message = f"Data source '{data_source}' is currently unavailable"
        
        suggestions = [
            "Try again later",
            "Check data source status page",
            "Use cached data if available",
            "Switch to alternative data source"
        ]
        
        if estimated_recovery:
            suggestions.insert(0, f"Service expected to recover: {estimated_recovery}")
        
        super().__init__(
            message=message,
            api_name=data_source,
            error_code=ErrorCode.DATA_SOURCE_UNAVAILABLE,
            severity=ErrorSeverity.HIGH,
            suggestions=suggestions,
            data_source=data_source,
            estimated_recovery=estimated_recovery,
            **kwargs
        )


class ExternalAPIError(APIError):
    """Exception raised when external API returns an error."""
    
    def __init__(
        self,
        api_name: str,
        status_code: int,
        response_body: Optional[str] = None,
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            message = f"External API error from {api_name}: HTTP {status_code}"
        
        severity = ErrorSeverity.HIGH
        suggestions = [
            "Check API documentation for error details",
            "Verify API endpoint and parameters",
            "Try again with different parameters"
        ]
        
        # Adjust severity and suggestions based on status code
        if 400 <= status_code < 500:
            severity = ErrorSeverity.MEDIUM
            suggestions.extend([
                "Check request format and parameters",
                "Verify authentication credentials",
                "Review API usage guidelines"
            ])
        elif 500 <= status_code < 600:
            suggestions.extend([
                "Wait and retry - server error",
                "Check API status page",
                "Contact API provider if issue persists"
            ])
        
        super().__init__(
            message=message,
            api_name=api_name,
            status_code=status_code,
            error_code=ErrorCode.EXTERNAL_API_ERROR,
            severity=severity,
            suggestions=suggestions,
            response_body=response_body,
            **kwargs
        )


class TimeoutError(APIError):
    """Exception raised when API request times out."""
    
    def __init__(
        self,
        api_name: str,
        timeout_seconds: float,
        operation: Optional[str] = None,
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            msg = f"Request to {api_name} timed out after {timeout_seconds} seconds"
            if operation:
                msg = f"{operation} request to {api_name} timed out after {timeout_seconds} seconds"
            message = msg
        
        super().__init__(
            message=message,
            api_name=api_name,
            error_code=ErrorCode.API_TIMEOUT,
            severity=ErrorSeverity.MEDIUM,
            suggestions=[
                "Increase timeout duration",
                "Check network connectivity",
                "Try again with smaller data sets",
                "Contact API provider about performance issues"
            ],
            timeout_seconds=timeout_seconds,
            operation=operation,
            **kwargs
        )


class AuthenticationError(APIError):
    """Exception raised when API authentication fails."""
    
    def __init__(
        self,
        api_name: str,
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            message = f"Authentication failed for {api_name} API"
        
        super().__init__(
            message=message,
            api_name=api_name,
            error_code=ErrorCode.API_AUTHENTICATION_ERROR,
            severity=ErrorSeverity.HIGH,
            suggestions=[
                "Check API credentials",
                "Verify API key is valid and not expired",
                "Ensure proper authentication headers",
                "Contact API provider for access issues"
            ],
            **kwargs
        )


class QuotaExceededError(APIError):
    """Exception raised when API quota is exceeded."""
    
    def __init__(
        self,
        api_name: str,
        quota_type: str = "requests",
        reset_time: Optional[str] = None,
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            msg = f"{quota_type.title()} quota exceeded for {api_name} API"
            if reset_time:
                msg += f". Quota resets at {reset_time}"
            message = msg
        
        suggestions = [
            "Wait for quota reset",
            "Optimize request frequency",
            "Use caching to reduce API calls",
            "Consider upgrading API plan"
        ]
        
        if reset_time:
            suggestions.insert(0, f"Quota resets at {reset_time}")
        
        super().__init__(
            message=message,
            api_name=api_name,
            error_code=ErrorCode.RATE_LIMIT_EXCEEDED,
            severity=ErrorSeverity.MEDIUM,
            suggestions=suggestions,
            quota_type=quota_type,
            reset_time=reset_time,
            **kwargs
        )