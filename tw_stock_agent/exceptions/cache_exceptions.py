"""
Cache-related exception classes for Taiwan Stock Agent.

This module contains exceptions for cache operations,
including connection issues, serialization problems, and key management.
"""

from typing import Optional

from .base import ErrorCode, ErrorContext, ErrorSeverity, TwStockAgentError


class CacheError(TwStockAgentError):
    """Base exception for cache-related errors."""
    
    def __init__(
        self,
        message: str,
        cache_key: Optional[str] = None,
        operation: Optional[str] = None,
        error_code: ErrorCode = ErrorCode.CACHE_ERROR,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        context: Optional[ErrorContext] = None,
        **kwargs
    ) -> None:
        if context is None:
            context = ErrorContext()
        if operation:
            context.operation = operation
        
        super().__init__(
            message=message,
            error_code=error_code,
            severity=severity,
            context=context,
            cache_key=cache_key,
            **kwargs
        )


class CacheConnectionError(CacheError):
    """Exception raised when cache connection fails."""
    
    def __init__(
        self,
        cache_backend: str = "unknown",
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            message = f"Failed to connect to cache backend: {cache_backend}"
        
        super().__init__(
            message=message,
            error_code=ErrorCode.CACHE_CONNECTION_ERROR,
            severity=ErrorSeverity.HIGH,
            suggestions=[
                "Check cache service is running",
                "Verify network connectivity",
                "Check cache configuration",
                "Restart cache service if necessary",
                "Use fallback storage mechanism"
            ],
            cache_backend=cache_backend,
            **kwargs
        )


class CacheKeyError(CacheError):
    """Exception raised when cache key is invalid or not found."""
    
    def __init__(
        self,
        cache_key: str,
        operation: str = "access",
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            message = f"Cache key error during {operation}: '{cache_key}'"
        
        super().__init__(
            message=message,
            cache_key=cache_key,
            operation=operation,
            error_code=ErrorCode.CACHE_KEY_ERROR,
            severity=ErrorSeverity.MEDIUM,
            suggestions=[
                "Verify cache key format",
                "Check key exists in cache",
                "Use proper key naming conventions",
                "Handle cache misses gracefully"
            ],
            **kwargs
        )


class CacheSerializationError(CacheError):
    """Exception raised when cache serialization/deserialization fails."""
    
    def __init__(
        self,
        data_type: str,
        operation: str = "serialize",
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            message = f"Failed to {operation} {data_type} for cache storage"
        
        super().__init__(
            message=message,
            operation=operation,
            error_code=ErrorCode.CACHE_SERIALIZATION_ERROR,
            severity=ErrorSeverity.MEDIUM,
            suggestions=[
                "Check data format compatibility",
                "Verify serialization settings",
                "Handle complex data types properly",
                "Use alternative serialization method"
            ],
            data_type=data_type,
            **kwargs
        )


class CacheExpiredError(CacheError):
    """Exception raised when accessing expired cache data."""
    
    def __init__(
        self,
        cache_key: str,
        expired_at: Optional[str] = None,
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            msg = f"Cache entry expired: '{cache_key}'"
            if expired_at:
                msg += f" (expired at {expired_at})"
            message = msg
        
        super().__init__(
            message=message,
            cache_key=cache_key,
            error_code=ErrorCode.CACHE_EXPIRED,
            severity=ErrorSeverity.LOW,
            suggestions=[
                "Refresh data from original source",
                "Check cache TTL settings",
                "Implement cache warming strategies",
                "Handle cache misses gracefully"
            ],
            expired_at=expired_at,
            **kwargs
        )


class CacheFullError(CacheError):
    """Exception raised when cache storage is full."""
    
    def __init__(
        self,
        current_size: Optional[int] = None,
        max_size: Optional[int] = None,
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            msg = "Cache storage is full"
            if current_size and max_size:
                msg += f" ({current_size}/{max_size} entries)"
            message = msg
        
        super().__init__(
            message=message,
            error_code=ErrorCode.CACHE_ERROR,
            severity=ErrorSeverity.MEDIUM,
            suggestions=[
                "Clear old cache entries",
                "Increase cache size limit",
                "Implement LRU eviction policy",
                "Optimize cache usage patterns"
            ],
            current_size=current_size,
            max_size=max_size,
            **kwargs
        )


class CacheIntegrityError(CacheError):
    """Exception raised when cache data integrity is compromised."""
    
    def __init__(
        self,
        cache_key: str,
        expected_checksum: Optional[str] = None,
        actual_checksum: Optional[str] = None,
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            message = f"Cache data integrity check failed for key: '{cache_key}'"
        
        super().__init__(
            message=message,
            cache_key=cache_key,
            error_code=ErrorCode.CACHE_ERROR,
            severity=ErrorSeverity.HIGH,
            suggestions=[
                "Clear corrupted cache entry",
                "Refresh data from source",
                "Check cache storage health",
                "Verify cache configuration"
            ],
            expected_checksum=expected_checksum,
            actual_checksum=actual_checksum,
            **kwargs
        )