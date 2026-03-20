"""
Validation exception classes for Taiwan Stock Agent.

This module contains exceptions for input validation, parameter checking,
and data format validation.
"""

from typing import Any, List, Optional

from .base import ErrorCode, ErrorContext, ErrorSeverity, TwStockAgentError


class ValidationError(TwStockAgentError):
    """Base exception for validation errors."""
    
    def __init__(
        self,
        message: str,
        field_name: Optional[str] = None,
        field_value: Optional[Any] = None,
        error_code: ErrorCode = ErrorCode.VALIDATION_ERROR,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        context: Optional[ErrorContext] = None,
        **kwargs
    ) -> None:
        super().__init__(
            message=message,
            error_code=error_code,
            severity=severity,
            context=context,
            field_name=field_name,
            field_value=field_value,
            **kwargs
        )


class ParameterValidationError(ValidationError):
    """Exception raised when parameter validation fails."""
    
    def __init__(
        self,
        parameter_name: str,
        parameter_value: Optional[Any] = None,
        expected_format: Optional[str] = None,
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            msg = f"Invalid parameter '{parameter_name}'"
            if parameter_value is not None:
                msg += f" with value: {parameter_value}"
            if expected_format:
                msg += f". Expected format: {expected_format}"
            message = msg
        
        super().__init__(
            message=message,
            field_name=parameter_name,
            field_value=parameter_value,
            error_code=ErrorCode.PARAMETER_INVALID,
            severity=ErrorSeverity.MEDIUM,
            suggestions=[
                "Check parameter format and type",
                "Refer to API documentation",
                "Validate input before submission",
                "Use proper data types"
            ],
            expected_format=expected_format,
            **kwargs
        )


class RequiredParameterMissingError(ValidationError):
    """Exception raised when required parameter is missing."""
    
    def __init__(
        self,
        parameter_name: str,
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            message = f"Required parameter '{parameter_name}' is missing"
        
        super().__init__(
            message=message,
            field_name=parameter_name,
            error_code=ErrorCode.PARAMETER_MISSING,
            severity=ErrorSeverity.HIGH,
            suggestions=[
                f"Provide the required parameter: {parameter_name}",
                "Check API documentation for required fields",
                "Verify request format",
                "Use proper parameter names"
            ],
            **kwargs
        )


class DataFormatError(ValidationError):
    """Exception raised when data format is invalid."""
    
    def __init__(
        self,
        data_type: str,
        expected_format: str,
        received_data: Optional[Any] = None,
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            msg = f"Invalid {data_type} format. Expected: {expected_format}"
            if received_data is not None:
                msg += f", received: {received_data}"
            message = msg
        
        super().__init__(
            message=message,
            field_value=received_data,
            error_code=ErrorCode.DATA_FORMAT_ERROR,
            severity=ErrorSeverity.MEDIUM,
            suggestions=[
                f"Use proper {data_type} format: {expected_format}",
                "Check data conversion and parsing",
                "Validate data before processing",
                "Use appropriate data validation libraries"
            ],
            data_type=data_type,
            expected_format=expected_format,
            **kwargs
        )


class TypeValidationError(ValidationError):
    """Exception raised when type validation fails."""
    
    def __init__(
        self,
        field_name: str,
        expected_type: str,
        received_type: str,
        received_value: Optional[Any] = None,
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            msg = f"Type error for field '{field_name}': expected {expected_type}, got {received_type}"
            if received_value is not None:
                msg += f" (value: {received_value})"
            message = msg
        
        super().__init__(
            message=message,
            field_name=field_name,
            field_value=received_value,
            error_code=ErrorCode.TYPE_ERROR,
            severity=ErrorSeverity.MEDIUM,
            suggestions=[
                f"Convert value to {expected_type}",
                "Check data types before processing",
                "Use proper type casting",
                "Validate input types"
            ],
            expected_type=expected_type,
            received_type=received_type,
            **kwargs
        )


class RangeValidationError(ValidationError):
    """Exception raised when value is outside valid range."""
    
    def __init__(
        self,
        field_name: str,
        value: Any,
        min_value: Optional[Any] = None,
        max_value: Optional[Any] = None,
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            msg = f"Value '{value}' for field '{field_name}' is outside valid range"
            if min_value is not None and max_value is not None:
                msg += f" [{min_value}, {max_value}]"
            elif min_value is not None:
                msg += f" (minimum: {min_value})"
            elif max_value is not None:
                msg += f" (maximum: {max_value})"
            message = msg
        
        suggestions = [
            "Use value within valid range",
            "Check field constraints",
            "Validate input boundaries"
        ]
        
        if min_value is not None and max_value is not None:
            suggestions.insert(0, f"Use value between {min_value} and {max_value}")
        elif min_value is not None:
            suggestions.insert(0, f"Use value >= {min_value}")
        elif max_value is not None:
            suggestions.insert(0, f"Use value <= {max_value}")
        
        super().__init__(
            message=message,
            field_name=field_name,
            field_value=value,
            error_code=ErrorCode.PARAMETER_INVALID,
            severity=ErrorSeverity.MEDIUM,
            suggestions=suggestions,
            min_value=min_value,
            max_value=max_value,
            **kwargs
        )


class EnumValidationError(ValidationError):
    """Exception raised when value is not in allowed enum values."""
    
    def __init__(
        self,
        field_name: str,
        value: Any,
        allowed_values: List[Any],
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            message = f"Invalid value '{value}' for field '{field_name}'. Allowed values: {allowed_values}"
        
        super().__init__(
            message=message,
            field_name=field_name,
            field_value=value,
            error_code=ErrorCode.PARAMETER_INVALID,
            severity=ErrorSeverity.MEDIUM,
            suggestions=[
                f"Use one of the allowed values: {allowed_values}",
                "Check field documentation for valid options",
                "Verify spelling and case sensitivity",
                "Use exact match for enum values"
            ],
            allowed_values=allowed_values,
            **kwargs
        )


class StockCodeValidationError(ValidationError):
    """Exception raised when Taiwan stock code validation fails."""
    
    def __init__(
        self,
        stock_code: str,
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            message = f"Invalid Taiwan stock code format: '{stock_code}'"
        
        super().__init__(
            message=message,
            field_name="stock_code",
            field_value=stock_code,
            error_code=ErrorCode.INVALID_STOCK_CODE,
            severity=ErrorSeverity.HIGH,
            suggestions=[
                "Use 4-6 digit Taiwan stock codes (e.g., '2330' for TSMC)",
                "Remove any letters, spaces, or special characters",
                "Check Taiwan Stock Exchange for valid codes",
                "Common examples: 2330 (TSMC), 2317 (Hon Hai), 1301 (台塑)"
            ],
            **kwargs
        )