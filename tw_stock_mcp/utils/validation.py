"""
Input validation utilities for Taiwan Stock Agent.

This module provides comprehensive validation for Taiwan stock codes,
parameters, and data formats with specific rules for Taiwan stock market.
"""

import re
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Union

from ..exceptions import (
    DataFormatError,
    EnumValidationError,
    InvalidStockCodeError,
    ParameterValidationError,
    RangeValidationError,
    RequiredParameterMissingError,
    StockCodeValidationError,
    TypeValidationError,
)


class StockCodeValidator:
    """Validator for Taiwan stock codes with comprehensive rules."""
    
    # Taiwan stock code patterns
    STOCK_CODE_PATTERN = re.compile(r'^\d{4,6}$')
    
    # Known stock code ranges for different markets
    TWSE_RANGES = [
        (1000, 9999),  # Main board
    ]
    
    TPEX_RANGES = [
        (1000, 9999),  # OTC market
    ]
    
    # Special stock code prefixes and their meanings
    SPECIAL_PREFIXES = {
        '00': 'ETF',
        '01': 'Government bonds',
        '02': 'Corporate bonds',
        '03': 'Foreign stocks',
        '91': 'Warrants',
        '92': 'Call warrants',
        '93': 'Put warrants',
    }
    
    @classmethod
    def validate_stock_code(cls, stock_code: str, strict: bool = True) -> str:
        """
        Validate Taiwan stock code format and structure.
        
        Args:
            stock_code: Stock code to validate
            strict: Whether to apply strict validation rules
            
        Returns:
            Cleaned and validated stock code
            
        Raises:
            InvalidStockCodeError: If stock code is invalid
            StockCodeValidationError: If format is wrong
        """
        if not stock_code:
            raise RequiredParameterMissingError("stock_code")
        
        # Clean the stock code
        cleaned_code = cls._clean_stock_code(stock_code)
        
        # Basic format validation
        if not cls.STOCK_CODE_PATTERN.match(cleaned_code):
            raise StockCodeValidationError(
                stock_code=stock_code,
                message=f"Invalid stock code format: '{stock_code}'. Must be 4-6 digits."
            )
        
        # Length validation
        if len(cleaned_code) < 4 or len(cleaned_code) > 6:
            raise StockCodeValidationError(
                stock_code=stock_code,
                message=f"Stock code length must be 4-6 digits, got {len(cleaned_code)}"
            )
        
        if strict:
            cls._validate_stock_code_rules(cleaned_code)
        
        return cleaned_code
    
    @classmethod
    def _clean_stock_code(cls, stock_code: str) -> str:
        """Clean stock code by removing spaces and non-digit characters."""
        # Remove spaces and common separators
        cleaned = re.sub(r'[\s\-\.]', '', stock_code.strip())
        
        # Remove any non-digit characters
        cleaned = re.sub(r'[^\d]', '', cleaned)
        
        return cleaned
    
    @classmethod
    def _validate_stock_code_rules(cls, stock_code: str) -> None:
        """Apply strict validation rules for Taiwan stock codes."""
        code_num = int(stock_code)
        
        # Check for obviously invalid codes
        invalid_patterns = [
            '0000', '0001', '0002', '0003',  # Reserved codes
            '9999',  # Invalid range
        ]
        
        if stock_code in invalid_patterns:
            raise InvalidStockCodeError(
                stock_code=stock_code,
                message=f"Stock code '{stock_code}' is in reserved/invalid range"
            )
        
        # Validate common ranges (allow ETFs starting with 00)
        if len(stock_code) == 4:
            # Allow ETFs (00xx) and regular stocks (1000-9999)
            if not ((50 <= code_num <= 999) or (1000 <= code_num <= 9999)):
                raise InvalidStockCodeError(
                    stock_code=stock_code,
                    message=f"4-digit stock code must be 0050-0999 (ETFs) or 1000-9999 (stocks)"
                )
    
    @classmethod
    def get_stock_type(cls, stock_code: str) -> str:
        """
        Determine stock type based on code pattern.
        
        Args:
            stock_code: Validated stock code
            
        Returns:
            Stock type description
        """
        if len(stock_code) >= 2:
            prefix = stock_code[:2]
            if prefix in cls.SPECIAL_PREFIXES:
                return cls.SPECIAL_PREFIXES[prefix]
        
        # Determine market based on common ranges
        code_num = int(stock_code)
        
        if 1000 <= code_num <= 1999:
            return "Cement, Food, Plastics"
        elif 2000 <= code_num <= 2999:
            return "Textile, Electronics, Semiconductor"
        elif 3000 <= code_num <= 3999:
            return "Steel, Construction, Transportation"
        elif 4000 <= code_num <= 4999:
            return "Tourism, Department Stores"
        elif 5000 <= code_num <= 5999:
            return "Paper, Automobile, Trading"
        elif 6000 <= code_num <= 6999:
            return "Other industries"
        elif 8000 <= code_num <= 8999:
            return "Financial, Insurance"
        elif 9000 <= code_num <= 9999:
            return "Investment Trust, Other"
        else:
            return "Unknown"
    
    @classmethod
    def validate_multiple_codes(cls, stock_codes: List[str], strict: bool = True) -> List[str]:
        """
        Validate multiple stock codes.
        
        Args:
            stock_codes: List of stock codes to validate
            strict: Whether to apply strict validation
            
        Returns:
            List of validated stock codes
            
        Raises:
            ValidationError: If any code is invalid
        """
        if not stock_codes:
            raise ParameterValidationError(
                parameter_name="stock_codes",
                parameter_value=stock_codes,
                expected_format="Non-empty list of stock codes"
            )
        
        validated_codes = []
        errors = []
        
        for i, code in enumerate(stock_codes):
            try:
                validated_code = cls.validate_stock_code(code, strict=strict)
                validated_codes.append(validated_code)
            except Exception as e:
                errors.append(f"Code {i+1} ('{code}'): {str(e)}")
        
        if errors:
            raise ParameterValidationError(
                parameter_name="stock_codes",
                parameter_value=stock_codes,
                message=f"Invalid stock codes found: {'; '.join(errors)}"
            )
        
        return validated_codes


class ParameterValidator:
    """General parameter validation utilities."""
    
    @staticmethod
    def validate_required(value: Any, parameter_name: str) -> Any:
        """Validate that required parameter is present and not None/empty."""
        if value is None:
            raise RequiredParameterMissingError(parameter_name)
        
        if isinstance(value, (str, list, dict)) and len(value) == 0:
            raise RequiredParameterMissingError(parameter_name)
        
        return value
    
    @staticmethod
    def validate_type(
        value: Any,
        expected_type: type,
        parameter_name: str,
        allow_none: bool = False
    ) -> Any:
        """Validate parameter type."""
        if allow_none and value is None:
            return value
        
        if not isinstance(value, expected_type):
            raise TypeValidationError(
                field_name=parameter_name,
                expected_type=expected_type.__name__,
                received_type=type(value).__name__,
                received_value=value
            )
        
        return value
    
    @staticmethod
    def validate_range(
        value: Union[int, float],
        parameter_name: str,
        min_value: Optional[Union[int, float]] = None,
        max_value: Optional[Union[int, float]] = None,
        inclusive: bool = True
    ) -> Union[int, float]:
        """Validate numeric value is within range."""
        if min_value is not None:
            if inclusive and value < min_value:
                raise RangeValidationError(parameter_name, value, min_value, max_value)
            elif not inclusive and value <= min_value:
                raise RangeValidationError(parameter_name, value, min_value, max_value)
        
        if max_value is not None:
            if inclusive and value > max_value:
                raise RangeValidationError(parameter_name, value, min_value, max_value)
            elif not inclusive and value >= max_value:
                raise RangeValidationError(parameter_name, value, min_value, max_value)
        
        return value
    
    @staticmethod
    def validate_enum(
        value: Any,
        parameter_name: str,
        allowed_values: List[Any],
        case_sensitive: bool = True
    ) -> Any:
        """Validate value is in allowed enum values."""
        if not case_sensitive and isinstance(value, str):
            value_lower = value.lower()
            allowed_lower = [str(v).lower() for v in allowed_values]
            if value_lower not in allowed_lower:
                raise EnumValidationError(parameter_name, value, allowed_values)
            # Return the original cased version
            return allowed_values[allowed_lower.index(value_lower)]
        else:
            if value not in allowed_values:
                raise EnumValidationError(parameter_name, value, allowed_values)
        
        return value
    
    @staticmethod
    def validate_string_length(
        value: str,
        parameter_name: str,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None
    ) -> str:
        """Validate string length."""
        length = len(value)
        
        if min_length is not None and length < min_length:
            raise ParameterValidationError(
                parameter_name=parameter_name,
                parameter_value=value,
                message=f"String too short: {length} < {min_length}"
            )
        
        if max_length is not None and length > max_length:
            raise ParameterValidationError(
                parameter_name=parameter_name,
                parameter_value=value,
                message=f"String too long: {length} > {max_length}"
            )
        
        return value
    
    @staticmethod
    def validate_date_format(
        value: str,
        parameter_name: str,
        date_format: str = "%Y-%m-%d"
    ) -> str:
        """Validate date string format."""
        try:
            datetime.strptime(value, date_format)
            return value
        except ValueError as e:
            raise DataFormatError(
                data_type="date",
                expected_format=date_format,
                received_data=value,
                message=f"Invalid date format for {parameter_name}: {value}"
            )


class StockParameterValidator:
    """Specific validation for stock-related parameters."""
    
    @staticmethod
    def validate_period(period: str) -> str:
        """Validate time period parameter for stock data."""
        allowed_periods = [
            "1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"
        ]
        
        return ParameterValidator.validate_enum(
            value=period,
            parameter_name="period",
            allowed_values=allowed_periods,
            case_sensitive=False
        )
    
    @staticmethod
    def validate_days(days: int) -> int:
        """Validate days parameter for historical data."""
        ParameterValidator.validate_type(days, int, "days")
        return ParameterValidator.validate_range(
            value=days,
            parameter_name="days",
            min_value=1,
            max_value=3650  # Max 10 years
        )
    
    @staticmethod
    def validate_limit(limit: int) -> int:
        """Validate limit parameter for data pagination."""
        ParameterValidator.validate_type(limit, int, "limit")
        return ParameterValidator.validate_range(
            value=limit,
            parameter_name="limit",
            min_value=1,
            max_value=1000  # Reasonable limit
        )
    
    @staticmethod
    def validate_market(market: str) -> str:
        """Validate market parameter."""
        allowed_markets = ["TWSE", "TPEx", "ALL"]
        
        return ParameterValidator.validate_enum(
            value=market,
            parameter_name="market",
            allowed_values=allowed_markets,
            case_sensitive=False
        )


def validate_stock_request(
    stock_code: Optional[str] = None,
    period: Optional[str] = None,
    days: Optional[int] = None,
    limit: Optional[int] = None,
    market: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Validate a complete stock request with all parameters.
    
    Args:
        stock_code: Stock code to validate
        period: Time period for data
        days: Number of days for historical data
        limit: Limit for pagination
        market: Market filter
        **kwargs: Additional parameters
        
    Returns:
        Dictionary of validated parameters
        
    Raises:
        ValidationError: If any parameter is invalid
    """
    validated_params = {}
    
    # Validate stock code if provided
    if stock_code is not None:
        validated_params["stock_code"] = StockCodeValidator.validate_stock_code(
            stock_code, strict=True
        )
    
    # Validate period if provided
    if period is not None:
        validated_params["period"] = StockParameterValidator.validate_period(period)
    
    # Validate days if provided
    if days is not None:
        validated_params["days"] = StockParameterValidator.validate_days(days)
    
    # Validate limit if provided
    if limit is not None:
        validated_params["limit"] = StockParameterValidator.validate_limit(limit)
    
    # Validate market if provided
    if market is not None:
        validated_params["market"] = StockParameterValidator.validate_market(market)
    
    # Add any additional validated parameters
    for key, value in kwargs.items():
        if value is not None:
            validated_params[key] = value
    
    return validated_params