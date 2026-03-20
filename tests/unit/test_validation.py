"""
Tests for input validation utilities.

This module tests stock code validation, parameter validation,
and request validation functions.
"""

import pytest
from datetime import datetime

from tw_stock_agent.utils.validation import (
    StockCodeValidator,
    ParameterValidator,
    StockParameterValidator,
    validate_stock_request,
)
from tw_stock_agent.exceptions import (
    InvalidStockCodeError,
    StockCodeValidationError,
    ParameterValidationError,
    RequiredParameterMissingError,
    TypeValidationError,
    RangeValidationError,
    EnumValidationError,
    DataFormatError,
)


class TestStockCodeValidator:
    """Test StockCodeValidator functionality."""
    
    def test_valid_stock_codes(self):
        """Test validation of valid stock codes."""
        valid_codes = ["2330", "1234", "999999", "0050"]
        
        for code in valid_codes:
            validated = StockCodeValidator.validate_stock_code(code)
            assert validated == code
    
    def test_valid_stock_codes_with_cleaning(self):
        """Test validation with code cleaning."""
        test_cases = [
            ("2330 ", "2330"),  # Trailing space
            (" 2330", "2330"),  # Leading space
            ("2-3-3-0", "2330"),  # With dashes
            ("2.3.3.0", "2330"),  # With dots
            ("TW2330", "2330"),  # With letters (removed)
        ]
        
        for input_code, expected in test_cases:
            validated = StockCodeValidator.validate_stock_code(input_code, strict=False)
            assert validated == expected
    
    def test_invalid_stock_code_format(self):
        """Test invalid stock code formats."""
        invalid_codes = [
            "123",      # Too short
            "1234567",  # Too long
            "ABC",      # Letters only
            "",         # Empty
            "   ",      # Whitespace only
        ]
        
        for code in invalid_codes:
            with pytest.raises((StockCodeValidationError, InvalidStockCodeError, RequiredParameterMissingError)):
                StockCodeValidator.validate_stock_code(code)
    
    def test_strict_validation(self):
        """Test strict validation rules."""
        # Test reserved codes
        with pytest.raises(InvalidStockCodeError):
            StockCodeValidator.validate_stock_code("0000", strict=True)
        
        with pytest.raises(InvalidStockCodeError):
            StockCodeValidator.validate_stock_code("9999", strict=True)
    
    def test_stock_type_detection(self):
        """Test stock type detection."""
        test_cases = [
            ("2330", "Textile, Electronics, Semiconductor"),
            ("1301", "Cement, Food, Plastics"),
            ("3008", "Steel, Construction, Transportation"),
            ("0050", "ETF"),
            ("8888", "Financial, Insurance"),
        ]
        
        for code, expected_type in test_cases:
            stock_type = StockCodeValidator.get_stock_type(code)
            assert expected_type in stock_type or stock_type == expected_type
    
    def test_validate_multiple_codes(self):
        """Test validation of multiple stock codes."""
        valid_codes = ["2330", "1234", "0050"]
        validated = StockCodeValidator.validate_multiple_codes(valid_codes)
        assert validated == valid_codes
    
    def test_validate_multiple_codes_with_errors(self):
        """Test validation of multiple codes with some invalid."""
        mixed_codes = ["2330", "INVALID", "1234"]
        
        with pytest.raises(ParameterValidationError) as exc_info:
            StockCodeValidator.validate_multiple_codes(mixed_codes)
        
        assert "INVALID" in str(exc_info.value)
    
    def test_empty_stock_codes_list(self):
        """Test validation with empty list."""
        with pytest.raises(ParameterValidationError):
            StockCodeValidator.validate_multiple_codes([])


class TestParameterValidator:
    """Test ParameterValidator functionality."""
    
    def test_validate_required(self):
        """Test required parameter validation."""
        # Valid cases
        assert ParameterValidator.validate_required("value", "param") == "value"
        assert ParameterValidator.validate_required(123, "param") == 123
        assert ParameterValidator.validate_required([1, 2], "param") == [1, 2]
        
        # Invalid cases
        with pytest.raises(RequiredParameterMissingError):
            ParameterValidator.validate_required(None, "param")
        
        with pytest.raises(RequiredParameterMissingError):
            ParameterValidator.validate_required("", "param")
        
        with pytest.raises(RequiredParameterMissingError):
            ParameterValidator.validate_required([], "param")
    
    def test_validate_type(self):
        """Test type validation."""
        # Valid cases
        assert ParameterValidator.validate_type("test", str, "param") == "test"
        assert ParameterValidator.validate_type(123, int, "param") == 123
        assert ParameterValidator.validate_type(None, str, "param", allow_none=True) is None
        
        # Invalid cases
        with pytest.raises(TypeValidationError):
            ParameterValidator.validate_type("123", int, "param")
        
        with pytest.raises(TypeValidationError):
            ParameterValidator.validate_type(None, str, "param", allow_none=False)
    
    def test_validate_range(self):
        """Test range validation."""
        # Valid cases
        assert ParameterValidator.validate_range(5, "param", 1, 10) == 5
        assert ParameterValidator.validate_range(1, "param", min_value=1) == 1
        assert ParameterValidator.validate_range(10, "param", max_value=10) == 10
        
        # Invalid cases
        with pytest.raises(RangeValidationError):
            ParameterValidator.validate_range(0, "param", 1, 10)
        
        with pytest.raises(RangeValidationError):
            ParameterValidator.validate_range(11, "param", 1, 10)
    
    def test_validate_enum(self):
        """Test enum validation."""
        allowed_values = ["apple", "banana", "cherry"]
        
        # Valid cases
        assert ParameterValidator.validate_enum("apple", "param", allowed_values) == "apple"
        
        # Case insensitive
        result = ParameterValidator.validate_enum(
            "APPLE", "param", allowed_values, case_sensitive=False
        )
        assert result == "apple"
        
        # Invalid cases
        with pytest.raises(EnumValidationError):
            ParameterValidator.validate_enum("grape", "param", allowed_values)
    
    def test_validate_string_length(self):
        """Test string length validation."""
        # Valid cases
        assert ParameterValidator.validate_string_length("test", "param", 1, 10) == "test"
        
        # Invalid cases
        with pytest.raises(ParameterValidationError):
            ParameterValidator.validate_string_length("", "param", min_length=1)
        
        with pytest.raises(ParameterValidationError):
            ParameterValidator.validate_string_length("toolong", "param", max_length=5)
    
    def test_validate_date_format(self):
        """Test date format validation."""
        # Valid cases
        valid_date = "2023-12-01"
        assert ParameterValidator.validate_date_format(valid_date, "param") == valid_date
        
        # Custom format
        custom_date = "01/12/2023"
        result = ParameterValidator.validate_date_format(
            custom_date, "param", "%d/%m/%Y"
        )
        assert result == custom_date
        
        # Invalid cases
        with pytest.raises(DataFormatError):
            ParameterValidator.validate_date_format("invalid-date", "param")


class TestStockParameterValidator:
    """Test StockParameterValidator functionality."""
    
    def test_validate_period(self):
        """Test period validation."""
        valid_periods = ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"]
        
        for period in valid_periods:
            validated = StockParameterValidator.validate_period(period)
            assert validated.lower() == period.lower()
        
        # Case insensitive
        assert StockParameterValidator.validate_period("1MO") == "1mo"
        
        # Invalid period
        with pytest.raises(EnumValidationError):
            StockParameterValidator.validate_period("invalid")
    
    def test_validate_days(self):
        """Test days validation."""
        # Valid cases
        assert StockParameterValidator.validate_days(30) == 30
        assert StockParameterValidator.validate_days(1) == 1
        assert StockParameterValidator.validate_days(3650) == 3650
        
        # Invalid cases
        with pytest.raises(RangeValidationError):
            StockParameterValidator.validate_days(0)
        
        with pytest.raises(RangeValidationError):
            StockParameterValidator.validate_days(3651)
        
        with pytest.raises(TypeValidationError):
            StockParameterValidator.validate_days("30")
    
    def test_validate_limit(self):
        """Test limit validation."""
        # Valid cases
        assert StockParameterValidator.validate_limit(100) == 100
        assert StockParameterValidator.validate_limit(1) == 1
        assert StockParameterValidator.validate_limit(1000) == 1000
        
        # Invalid cases
        with pytest.raises(RangeValidationError):
            StockParameterValidator.validate_limit(0)
        
        with pytest.raises(RangeValidationError):
            StockParameterValidator.validate_limit(1001)
    
    def test_validate_market(self):
        """Test market validation."""
        valid_markets = ["TWSE", "TPEx", "ALL"]
        
        for market in valid_markets:
            validated = StockParameterValidator.validate_market(market)
            assert validated.upper() == market.upper()
        
        # Case insensitive
        assert StockParameterValidator.validate_market("twse") == "TWSE"
        
        # Invalid market
        with pytest.raises(EnumValidationError):
            StockParameterValidator.validate_market("INVALID")


class TestValidateStockRequest:
    """Test complete stock request validation."""
    
    def test_validate_complete_request(self):
        """Test validation of complete stock request."""
        params = validate_stock_request(
            stock_code="2330",
            period="1mo",
            days=30,
            limit=100,
            market="TWSE"
        )
        
        assert params["stock_code"] == "2330"
        assert params["period"] == "1mo"
        assert params["days"] == 30
        assert params["limit"] == 100
        assert params["market"] == "TWSE"
    
    def test_validate_partial_request(self):
        """Test validation with only some parameters."""
        params = validate_stock_request(stock_code="2330", period="1y")
        
        assert params["stock_code"] == "2330"
        assert params["period"] == "1y"
        assert "days" not in params
        assert "limit" not in params
        assert "market" not in params
    
    def test_validate_request_with_none_values(self):
        """Test validation with None values."""
        params = validate_stock_request(
            stock_code="2330",
            period=None,
            days=None
        )
        
        assert params["stock_code"] == "2330"
        assert "period" not in params
        assert "days" not in params
    
    def test_validate_request_with_invalid_stock_code(self):
        """Test validation with invalid stock code."""
        with pytest.raises((InvalidStockCodeError, StockCodeValidationError)):
            validate_stock_request(stock_code="INVALID")
    
    def test_validate_request_with_invalid_period(self):
        """Test validation with invalid period."""
        with pytest.raises(EnumValidationError):
            validate_stock_request(stock_code="2330", period="invalid")
    
    def test_validate_request_with_additional_params(self):
        """Test validation with additional parameters."""
        params = validate_stock_request(
            stock_code="2330",
            custom_param="value",
            another_param=123
        )
        
        assert params["stock_code"] == "2330"
        assert params["custom_param"] == "value"
        assert params["another_param"] == 123


@pytest.mark.parametrize("stock_code,expected", [
    ("2330", "2330"),      # TSMC
    ("1101", "1101"),      # Taiwan Cement
    ("0050", "0050"),      # Taiwan 50 ETF
    ("2317", "2317"),      # Hon Hai
    ("1301", "1301"),      # Taiwan Plastics
])
def test_common_taiwan_stock_codes(stock_code, expected):
    """Test validation of common Taiwan stock codes."""
    validated = StockCodeValidator.validate_stock_code(stock_code)
    assert validated == expected


@pytest.mark.parametrize("invalid_code", [
    "999",        # Too short
    "1234567",    # Too long
    "AAAA",       # Letters
    "12A4",       # Mixed
    "",           # Empty
    "   ",        # Whitespace
])
def test_invalid_stock_codes_parametrized(invalid_code):
    """Parametrized test for invalid stock codes."""
    with pytest.raises((InvalidStockCodeError, StockCodeValidationError, RequiredParameterMissingError)):
        StockCodeValidator.validate_stock_code(invalid_code)


class TestValidationErrorMessages:
    """Test that validation errors have helpful messages."""
    
    def test_stock_code_error_message(self):
        """Test stock code validation error message."""
        with pytest.raises(StockCodeValidationError) as exc_info:
            StockCodeValidator.validate_stock_code("ABC")
        
        error = exc_info.value
        assert "4-6 digits" in error.message
        assert "ABC" in error.message
        assert len(error.suggestions) > 0
        assert any("2330" in suggestion for suggestion in error.suggestions)
    
    def test_parameter_validation_error_message(self):
        """Test parameter validation error message."""
        with pytest.raises(TypeValidationError) as exc_info:
            ParameterValidator.validate_type("string", int, "test_param")
        
        error = exc_info.value
        assert "test_param" in str(error)
        assert "int" in str(error)
        assert "str" in str(error)
    
    def test_range_validation_error_message(self):
        """Test range validation error message."""
        with pytest.raises(RangeValidationError) as exc_info:
            ParameterValidator.validate_range(15, "days", 1, 10)
        
        error = exc_info.value
        assert "days" in str(error)
        assert "15" in str(error)
        assert "[1, 10]" in str(error)


class TestValidationPerformance:
    """Test validation performance for common scenarios."""
    
    def test_bulk_stock_code_validation(self):
        """Test performance of bulk stock code validation."""
        import time
        
        # Generate test stock codes
        stock_codes = [f"{i:04d}" for i in range(1000, 2000)]  # 1000 codes
        
        start_time = time.time()
        validated = StockCodeValidator.validate_multiple_codes(stock_codes, strict=False)
        end_time = time.time()
        
        assert len(validated) == len(stock_codes)
        assert (end_time - start_time) < 1.0  # Should complete in under 1 second
    
    def test_request_validation_performance(self):
        """Test performance of complete request validation."""
        import time
        
        start_time = time.time()
        
        # Validate 100 requests
        for i in range(100):
            validate_stock_request(
                stock_code=f"{1000 + i:04d}",
                period="1mo",
                days=30,
                limit=100
            )
        
        end_time = time.time()
        assert (end_time - start_time) < 0.5  # Should complete in under 0.5 seconds