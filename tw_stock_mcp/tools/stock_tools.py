import os
from datetime import datetime
from typing import Any

from tw_stock_mcp.services.service_container import market_service, stock_service
from tw_stock_mcp.utils.validation import (
    StockCodeValidator,
    validate_stock_request
)
from tw_stock_mcp.utils.mcp_error_handler import (
    mcp_error_handler,
    MCPResponseFormatter
)
from tw_stock_mcp.exceptions import (
    ParameterValidationError,
    TwStockAgentError
)

TWSE_EQUITIES_URL = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
TPEX_EQUITIES_URL = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"


def update_stock_codes():
    """Update stock codes from TWSE and TPEx websites."""
    def get_directory():
        return os.path.dirname(os.path.abspath(__file__))

    try:
        # Note: to_csv function is not defined in this file
        # This function would need to be implemented or imported
        # to_csv(TWSE_EQUITIES_URL, os.path.join(get_directory(), "twse_equities.csv"))
        # to_csv(TPEX_EQUITIES_URL, os.path.join(get_directory(), "tpex_equities.csv"))
        pass
    except Exception as e:
        import logging
        logger = logging.getLogger("tw-stock-agent.stock_tools")
        logger.error(f"Failed to update stock codes: {e}")

# Helper function to validate multiple stock codes
async def validate_and_fetch_multiple_stocks(stock_codes: list[str]) -> dict[str, Any]:
    """
    Helper function to validate and fetch multiple stock data.
    
    Args:
        stock_codes: List of stock codes to validate and fetch
        
    Returns:
        Dictionary of stock data with validation results
        
    Raises:
        ParameterValidationError: If stock codes list is invalid
    """
    if not stock_codes or not isinstance(stock_codes, list):
        raise ParameterValidationError(
            parameter_name="stock_codes",
            parameter_value=stock_codes,
            expected_format="Non-empty list of stock codes"
        )
    
    # Validate all stock codes first
    try:
        validated_codes = StockCodeValidator.validate_multiple_codes(stock_codes)
    except Exception as e:
        raise ParameterValidationError(
            parameter_name="stock_codes",
            parameter_value=stock_codes,
            message=f"Stock code validation failed: {str(e)}"
        )
    
    # Fetch data for all validated codes
    results = await stock_service.fetch_multiple_stocks_data(validated_codes)
    
    return {
        "requested_codes": stock_codes,
        "validated_codes": validated_codes,
        "results": results,
        "success_count": sum(1 for r in results.values() if "error" not in r),
        "error_count": sum(1 for r in results.values() if "error" in r)
    }

@mcp_error_handler("get_stock_data")
async def get_stock_data(stock_code: str) -> dict[str, Any]:
    """
    取得股票基本資料
    
    Args:
        stock_code: 股票代號，例如：2330
        
    Returns:
        股票資料，包含公司概況、產業別、市值等資訊
        
    Raises:
        InvalidStockCodeError: 股票代號格式錯誤
        StockNotFoundError: 找不到股票
        StockDataUnavailableError: 股票資料無法取得
    """
    # Validate request parameters
    validated_params = validate_stock_request(stock_code=stock_code)
    
    # Fetch stock data using the validated stock code
    result = await stock_service.fetch_stock_data(validated_params["stock_code"])
    
    # Format response for MCP
    return MCPResponseFormatter.format_stock_data_response(result)

@mcp_error_handler("get_price_history")
async def get_price_history(stock_code: str, period: str = "1mo") -> dict[str, Any]:
    """
    取得股票的歷史價格資料
    
    Args:
        stock_code: 股票代號，例如：2330
        period: 時間區間，可選值：'1d', '5d', '1mo', '3mo', '6mo', '1y', 'ytd', 'max'
        
    Returns:
        歷史價格資料
        
    Raises:
        InvalidStockCodeError: 股票代號格式錯誤
        ParameterValidationError: period參數錯誤
        StockDataUnavailableError: 價格資料無法取得
    """
    # Validate request parameters
    validated_params = validate_stock_request(
        stock_code=stock_code,
        period=period
    )
    
    # 處理period參數，轉換為天數
    days_map = {
        "1d": 1,
        "5d": 5,
        "1mo": 30,
        "3mo": 90,
        "6mo": 180,
        "1y": 365,
        "ytd": max(1, (datetime.now() - datetime(datetime.now().year, 1, 1)).days),
        "max": 3650  # 約10年
    }
    
    validated_period = validated_params["period"]
    days = days_map.get(validated_period, 30)
    
    if days <= 0:
        raise ParameterValidationError(
            parameter_name="period",
            parameter_value=period,
            message="Invalid period resulting in zero or negative days"
        )
    
    # Fetch price data
    price_data = await stock_service.fetch_price_data(
        validated_params["stock_code"], 
        days
    )
    
    result = {
        "stock_code": validated_params["stock_code"],
        "period": validated_period,
        "data": price_data,
        "requested_days": days,
        "actual_records": len(price_data) if isinstance(price_data, list) else 0
    }
    
    # Format response for MCP with enhanced structure  
    return MCPResponseFormatter.format_price_data_response(result)

@mcp_error_handler("get_best_four_points")
async def get_best_four_points(stock_code: str) -> dict[str, Any]:
    """
    取得四大買賣點分析
    
    Args:
        stock_code: 股票代號，例如：2330
        
    Returns:
        四大買賣點分析結果
        
    Raises:
        InvalidStockCodeError: 股票代號格式錯誤
        StockNotFoundError: 找不到股票
        StockDataUnavailableError: 分析資料無法取得
    """
    # Validate request parameters
    validated_params = validate_stock_request(stock_code=stock_code)
    
    # Fetch analysis data
    result = await stock_service.get_best_four_points(validated_params["stock_code"])
    
    # Format response for MCP with enhanced technical analysis structure
    return MCPResponseFormatter.format_technical_analysis_response(result)

@mcp_error_handler("get_realtime_data")
async def get_realtime_data(stock_code: str) -> dict[str, Any]:
    """
    取得即時股票資訊
    
    Args:
        stock_code: 股票代號，例如：2330
        
    Returns:
        即時股票資訊
        
    Raises:
        InvalidStockCodeError: 股票代號格式錯誤
        StockNotFoundError: 找不到股票
        StockDataUnavailableError: 即時資料無法取得
        StockMarketClosedError: 股市休市
    """
    # Validate request parameters
    validated_params = validate_stock_request(stock_code=stock_code)
    
    # Fetch real-time data
    result = await stock_service.get_realtime_data(validated_params["stock_code"])
    
    # Format response for MCP with enhanced realtime structure
    return MCPResponseFormatter.format_realtime_data_response(result)

@mcp_error_handler("get_deviation_scan")
async def get_deviation_scan(stock_codes: str = "") -> dict[str, Any]:
    """
    批量掃描台股負乖離翻正標的（20MA 基準）

    Args:
        stock_codes: 逗號分隔的股票代號，例如 "2330,2454,2382"。
                     留空則自動從 TWSE STOCK_DAY_ALL 抓取當日清單（TradeValue > 1億）。

    Returns:
        篩選結果，包含 matched 清單（今日乖離 0~5%，近30日負乖離 ≥24天）。
        每支股票回傳: code, name, close, ma20, today_deviation,
                      negative_days_30, negative_ratio_30, matched

    Notes:
        - 自動抓取近 4 個月 TWSE STOCK_DAY 資料（繞過 SSL 憑證問題）
        - 需要至少 51 筆收盤價（20 MA + 30 評估日 + 1 今日）
        - 並發上限 3，每股間隔 0.35s，符合 TWSE 速率限制
    """
    from tw_stock_mcp.services.deviation_service import (
        run_deviation_scan,
        fetch_twse_stock_list,
    )

    if stock_codes.strip():
        codes = [c.strip() for c in stock_codes.split(",") if c.strip()]
        stocks = [(c, c) for c in codes]  # name unknown when user provides codes
    else:
        stocks = await fetch_twse_stock_list()

    from tw_stock_mcp.services.deviation_service import _last_n_months
    result = await run_deviation_scan(stocks, months=_last_n_months(6))
    return result


@mcp_error_handler("get_fundamental_data")
async def get_fundamental_data(stock_code: str) -> dict[str, Any]:
    """
    取得個股三年基本面資料：每日本益比（PER/PBR/殖利率）與每季 EPS

    Args:
        stock_code: 股票代號，例如：2330

    Returns:
        per_history: 近三年每日 PER、PBR、殖利率
        eps_history: 近三年每季 EPS
        per_quarterly: 每季平均 PER（以季末日聚合）
        eps_ttm: 近四季累計 EPS

    Notes:
        - 資料來源：FinMind TaiwanStockPER 與 TaiwanStockFinancialStatements
        - 需要 FINMIND_API_TOKEN 環境變數（免費 tier 限 30 req/day）
    """
    import os
    from tw_stock_mcp.providers.finmind_provider import FinMindProvider

    validated_params = validate_stock_request(stock_code=stock_code)
    code = validated_params["stock_code"]

    token = os.environ.get("FINMIND_API_TOKEN")
    async with FinMindProvider(api_token=token) as provider:
        per_rows = await provider.get_per_history(code, years=3)
        eps_rows = await provider.get_eps_history(code, years=3)

    # Aggregate PER to quarterly averages
    from collections import defaultdict
    quarterly_per: dict[str, list[float]] = defaultdict(list)
    for row in per_rows:
        date = row.get("date", "")
        per_val = row.get("PER")
        if date and per_val is not None:
            try:
                q_key = f"{date[:4]}Q{(int(date[5:7]) - 1) // 3 + 1}"
                quarterly_per[q_key].append(float(per_val))
            except (ValueError, IndexError):
                pass

    per_quarterly = {
        q: round(sum(vals) / len(vals), 2)
        for q, vals in sorted(quarterly_per.items())
        if vals
    }

    # Compute trailing twelve months EPS
    eps_values = []
    for row in eps_rows:
        try:
            eps_values.append((row.get("date", ""), float(row.get("value", 0))))
        except (ValueError, TypeError):
            pass
    eps_values.sort(key=lambda x: x[0])
    eps_ttm = round(sum(v for _, v in eps_values[-4:]), 2) if len(eps_values) >= 4 else None

    return {
        "stock_code": code,
        "per_history": per_rows,
        "eps_history": eps_rows,
        "per_quarterly": per_quarterly,
        "eps_ttm": eps_ttm,
    }


@mcp_error_handler("get_market_overview")
async def get_market_overview() -> dict[str, Any]:
    """
    取得市場概況
    
    Returns:
        大盤指數、成交量、漲跌家數等資訊
        
    Raises:
        StockDataUnavailableError: 市場資料無法取得
    """
    try:
        result = await market_service.get_market_overview()

        # Format response for MCP with enhanced market overview structure
        return MCPResponseFormatter.format_market_overview_response(result)

    except TwStockAgentError:
        # Re-raise our custom errors
        raise
    except Exception as e:
        from tw_stock_mcp.exceptions import StockDataUnavailableError
        raise StockDataUnavailableError(
            stock_code="market",
            data_type="market overview",
            message=f"Failed to fetch market overview: {str(e)}"
        )
