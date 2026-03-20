"""
Error handling utilities for Taiwan Stock Agent.

This module provides utilities for error enrichment, logging, monitoring,
and production error handling patterns including retry mechanisms and circuit breakers.
"""

import asyncio
import functools
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional, Type, TypeVar, Union

from ..exceptions import (
    APIError,
    ErrorCode,
    ErrorContext,
    ErrorSeverity,
    ExternalAPIError,
    RateLimitError,
    TimeoutError,
    TwStockAgentError,
    create_error_response,
)

# Type variables for generic functions
F = TypeVar('F', bound=Callable[..., Any])
AsyncF = TypeVar('AsyncF', bound=Callable[..., Awaitable[Any]])

logger = logging.getLogger("tw-stock-agent.error_handler")


class ErrorEnricher:
    """Enriches errors with additional context and metadata."""
    
    @staticmethod
    def enrich_error(
        error: Exception,
        operation: Optional[str] = None,
        stock_code: Optional[str] = None,
        user_id: Optional[str] = None,
        request_id: Optional[str] = None,
        **additional_context: Any
    ) -> TwStockAgentError:
        """
        Enrich an exception with additional context.
        
        Args:
            error: Original exception
            operation: Operation being performed
            stock_code: Stock code if applicable
            user_id: User identifier
            request_id: Request identifier
            **additional_context: Additional context data
            
        Returns:
            Enriched TwStockAgentError
        """
        if isinstance(error, TwStockAgentError):
            # Update existing context
            if operation:
                error.context.operation = operation
            if stock_code:
                error.context.stock_code = stock_code
            if user_id:
                error.context.user_id = user_id
            if request_id:
                error.context.request_id = request_id
            
            # Add additional context
            error.context.additional_data.update(additional_context)
            return error
        
        # Create new TwStockAgentError from generic exception
        context = ErrorContext(
            operation=operation,
            stock_code=stock_code,
            user_id=user_id,
            request_id=request_id,
            additional_data=additional_context
        )
        
        # Map common exception types to appropriate error codes
        error_code = ErrorEnricher._map_exception_to_error_code(error)
        severity = ErrorEnricher._determine_severity(error)
        
        return TwStockAgentError(
            message=str(error),
            error_code=error_code,
            severity=severity,
            context=context,
            cause=error
        )
    
    @staticmethod
    def _map_exception_to_error_code(error: Exception) -> ErrorCode:
        """Map exception types to error codes."""
        error_mapping = {
            ValueError: ErrorCode.VALIDATION_ERROR,
            TypeError: ErrorCode.TYPE_ERROR,
            KeyError: ErrorCode.PARAMETER_MISSING,
            ConnectionError: ErrorCode.API_ERROR,
            TimeoutError: ErrorCode.API_TIMEOUT,
            PermissionError: ErrorCode.API_AUTHENTICATION_ERROR,
        }
        
        return error_mapping.get(type(error), ErrorCode.INTERNAL_ERROR)
    
    @staticmethod
    def _determine_severity(error: Exception) -> ErrorSeverity:
        """Determine error severity based on exception type."""
        high_severity_types = (ConnectionError, PermissionError, SystemError)
        low_severity_types = (ValueError, TypeError, KeyError)
        
        if isinstance(error, high_severity_types):
            return ErrorSeverity.HIGH
        elif isinstance(error, low_severity_types):
            return ErrorSeverity.MEDIUM
        else:
            return ErrorSeverity.MEDIUM


class ErrorLogger:
    """Handles structured error logging with correlation tracking."""
    
    def __init__(self, logger_name: str = "tw-stock-agent"):
        self.logger = logging.getLogger(logger_name)
    
    def log_error(
        self,
        error: Union[TwStockAgentError, Exception],
        include_traceback: bool = True,
        extra_fields: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log error with structured information.
        
        Args:
            error: Error to log
            include_traceback: Whether to include traceback
            extra_fields: Additional fields to include in log
        """
        log_data = {
            "error_type": type(error).__name__,
            "error_message": str(error),
        }
        
        if isinstance(error, TwStockAgentError):
            log_data.update({
                "error_code": error.error_code.value,
                "severity": error.severity.value,
                "correlation_id": error.context.correlation_id,
                "operation": error.context.operation,
                "stock_code": error.context.stock_code,
                "user_id": error.context.user_id,
                "request_id": error.context.request_id,
                "additional_data": error.context.additional_data,
            })
        
        if extra_fields:
            log_data.update(extra_fields)
        
        # Choose log level based on severity
        if isinstance(error, TwStockAgentError):
            log_level = self._get_log_level(error.severity)
        else:
            log_level = logging.ERROR
        
        self.logger.log(
            log_level,
            f"Error occurred: {str(error)}",
            extra=log_data,
            exc_info=include_traceback
        )
    
    def _get_log_level(self, severity: ErrorSeverity) -> int:
        """Map error severity to log level."""
        mapping = {
            ErrorSeverity.LOW: logging.INFO,
            ErrorSeverity.MEDIUM: logging.WARNING,
            ErrorSeverity.HIGH: logging.ERROR,
            ErrorSeverity.CRITICAL: logging.CRITICAL,
        }
        return mapping.get(severity, logging.ERROR)


class RetryManager:
    """Manages retry logic with exponential backoff."""
    
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
    
    def should_retry(self, error: Exception, attempt: int) -> bool:
        """
        Determine if operation should be retried.
        
        Args:
            error: Exception that occurred
            attempt: Current attempt number (0-based)
            
        Returns:
            True if should retry, False otherwise
        """
        if attempt >= self.max_retries:
            return False
        
        # Don't retry certain error types
        non_retryable_errors = (
            ValueError,
            TypeError,
            KeyError,
        )
        
        if isinstance(error, non_retryable_errors):
            return False
        
        # Check if it's a TwStockAgentError with specific codes
        if isinstance(error, TwStockAgentError):
            non_retryable_codes = {
                ErrorCode.VALIDATION_ERROR,
                ErrorCode.PARAMETER_MISSING,
                ErrorCode.PARAMETER_INVALID,
                ErrorCode.INVALID_STOCK_CODE,
                ErrorCode.STOCK_NOT_FOUND,
            }
            if error.error_code in non_retryable_codes:
                return False
        
        return True
    
    def calculate_delay(self, attempt: int) -> float:
        """
        Calculate delay for retry attempt.
        
        Args:
            attempt: Current attempt number (0-based)
            
        Returns:
            Delay in seconds
        """
        delay = self.base_delay * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay)
        
        if self.jitter:
            import random
            delay *= (0.5 + random.random() * 0.5)  # Add 0-50% jitter
        
        return delay


class CircuitBreaker:
    """Circuit breaker pattern implementation for external service calls."""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        timeout_seconds: float = 60.0,
        expected_exception: Type[Exception] = Exception
    ):
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    
    def call(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection.
        
        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
            
        Raises:
            Exception: If circuit is open or function fails
        """
        if self.state == "OPEN":
            if self._should_attempt_reset():
                self.state = "HALF_OPEN"
            else:
                raise TwStockAgentError(
                    message="Circuit breaker is OPEN - service unavailable",
                    error_code=ErrorCode.DATA_SOURCE_UNAVAILABLE,
                    severity=ErrorSeverity.HIGH,
                    suggestions=[
                        f"Service will be retried after {self.timeout_seconds} seconds",
                        "Check service health and availability",
                        "Use cached data if available"
                    ]
                )
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise
    
    async def acall(self, func: Callable[..., Awaitable[Any]], *args, **kwargs) -> Any:
        """Async version of call method."""
        if self.state == "OPEN":
            if self._should_attempt_reset():
                self.state = "HALF_OPEN"
            else:
                raise TwStockAgentError(
                    message="Circuit breaker is OPEN - service unavailable",
                    error_code=ErrorCode.DATA_SOURCE_UNAVAILABLE,
                    severity=ErrorSeverity.HIGH
                )
        
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise
    
    def _should_attempt_reset(self) -> bool:
        """Check if circuit should attempt to reset."""
        if self.last_failure_time is None:
            return True
        return time.time() - self.last_failure_time >= self.timeout_seconds
    
    def _on_success(self) -> None:
        """Handle successful operation."""
        self.failure_count = 0
        self.state = "CLOSED"
    
    def _on_failure(self) -> None:
        """Handle failed operation."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"


def with_error_handling(
    operation: str,
    stock_code: Optional[str] = None,
    include_traceback: bool = False,
    log_errors: bool = True
):
    """
    Decorator for adding comprehensive error handling to functions.
    
    Args:
        operation: Name of the operation for context
        stock_code: Stock code if applicable
        include_traceback: Whether to include traceback in response
        log_errors: Whether to log errors
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # Enrich error with context
                enriched_error = ErrorEnricher.enrich_error(
                    error=e,
                    operation=operation,
                    stock_code=stock_code
                )
                
                # Log error if requested
                if log_errors:
                    error_logger = ErrorLogger()
                    error_logger.log_error(enriched_error, include_traceback)
                
                # Re-raise enriched error
                raise enriched_error
        
        return wrapper
    return decorator


def with_async_error_handling(
    operation: str,
    stock_code: Optional[str] = None,
    include_traceback: bool = False,
    log_errors: bool = True
):
    """Async version of error handling decorator."""
    def decorator(func: AsyncF) -> AsyncF:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                # Enrich error with context
                enriched_error = ErrorEnricher.enrich_error(
                    error=e,
                    operation=operation,
                    stock_code=stock_code
                )
                
                # Log error if requested
                if log_errors:
                    error_logger = ErrorLogger()
                    error_logger.log_error(enriched_error, include_traceback)
                
                # Re-raise enriched error
                raise enriched_error
        
        return wrapper
    return decorator


def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True
):
    """
    Decorator for adding retry logic to functions.
    
    Args:
        max_retries: Maximum number of retries
        base_delay: Base delay between retries
        max_delay: Maximum delay between retries
        exponential_base: Base for exponential backoff
        jitter: Whether to add jitter to delays
    """
    def decorator(func: AsyncF) -> AsyncF:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            retry_manager = RetryManager(
                max_retries=max_retries,
                base_delay=base_delay,
                max_delay=max_delay,
                exponential_base=exponential_base,
                jitter=jitter
            )
            
            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    
                    if not retry_manager.should_retry(e, attempt):
                        break
                    
                    if attempt < max_retries:
                        delay = retry_manager.calculate_delay(attempt)
                        logger.warning(
                            f"Attempt {attempt + 1} failed, retrying in {delay:.2f}s: {str(e)}"
                        )
                        await asyncio.sleep(delay)
            
            # All retries exhausted, raise last error
            if last_error:
                raise last_error
        
        return wrapper
    return decorator