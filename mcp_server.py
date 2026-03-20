import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP

from tw_stock_agent.models import (
    BestFourPointsResponse,
    MarketOverviewResponse,
    PriceHistoryResponse,
    RealtimeDataResponse,
    StockDataResponse,
)
from tw_stock_agent.tools.stock_tools import (
    get_best_four_points,
    get_deviation_scan,
    get_market_overview,
    get_price_history,
    get_realtime_data,
    get_stock_data,
)
from tw_stock_agent.utils.config import get_settings
from tw_stock_agent.utils.mcp_error_handler import (
    MCPErrorHandler,
    MCPResponseFormatter
)
from tw_stock_agent.exceptions import (
    TwStockAgentError,
    create_error_response
)
from tw_stock_agent.services.mcp_resource_service import resource_manager

# Get settings from config
settings = get_settings()

# Configure logging
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format=settings.LOG_FORMAT
)
logger = logging.getLogger("tw-stock-agent")


@dataclass
class AppContext:
    """Application context with shared resources."""
    logger: logging.Logger
    settings: dict


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage application lifecycle with proper startup/shutdown."""
    logger.info("Starting tw-stock-agent MCP server")
    
    # Initialize shared resources
    app_context = AppContext(
        logger=logger,
        settings=settings
    )
    
    try:
        yield app_context
    finally:
        logger.info("Shutting down tw-stock-agent MCP server")


# Initialize FastMCP with enhanced configuration and lifespan
mcp = FastMCP(
    name="tw-stock-agent",
    description="台灣股市資料MCP服務 - Taiwan Stock Market Data MCP Server",
    lifespan=app_lifespan
)

@mcp.tool(name="get_stock_data",
          description="Get detailed information about a specific stock.",
)
async def get_stock_data_tool(stock_code: str) -> StockDataResponse:
    """Get detailed information about a specific stock."""
    try:
        raw_data = await get_stock_data(stock_code)
        # Extract clean data without _metadata for Pydantic model
        from tw_stock_agent.utils.mcp_error_handler import MCPResponseFormatter
        clean_data = MCPResponseFormatter.extract_metadata_for_model(raw_data)
        return StockDataResponse(**clean_data)
    except TwStockAgentError as e:
        # For MCP tools, we need to return a valid response with error information
        return StockDataResponse(
            stock_code=stock_code,
            updated_at=e.context.timestamp.isoformat(),
            error=e.message
        )
    except Exception as e:
        # Handle unexpected errors
        return StockDataResponse(
            stock_code=stock_code,
            updated_at=datetime.now().isoformat(),
            error=f"Unexpected error: {str(e)}"
        )


@mcp.tool(name="get_price_history",
          description="Get historical price data for a specific stock.",
)
async def get_price_history_tool(
    stock_code: str, period: str = "1mo"
) -> PriceHistoryResponse:
    """Get historical price data for a specific stock.""" 
    try:
        raw_data = await get_price_history(stock_code, period)
        # Extract clean data without _metadata for Pydantic model
        from tw_stock_agent.utils.mcp_error_handler import MCPResponseFormatter
        clean_data = MCPResponseFormatter.extract_metadata_for_model(raw_data)
        return PriceHistoryResponse(**clean_data)
    except TwStockAgentError as e:
        # Return error response in proper format
        return PriceHistoryResponse(
            stock_code=stock_code,
            period=period,
            data=[],
            error=e.message
        )
    except Exception as e:
        return PriceHistoryResponse(
            stock_code=stock_code,
            period=period,
            data=[],
            error=f"Unexpected error: {str(e)}"
        )

@mcp.tool(name="get_best_four_points",
          description="Get Best Four Points analysis for a specific stock.",
)
async def get_best_four_points_tool(stock_code: str) -> BestFourPointsResponse:
    """Get Best Four Points analysis for a specific stock."""
    try:
        raw_data = await get_best_four_points(stock_code)
        # Extract clean data without _metadata for Pydantic model
        from tw_stock_agent.utils.mcp_error_handler import MCPResponseFormatter
        clean_data = MCPResponseFormatter.extract_metadata_for_model(raw_data)
        return BestFourPointsResponse(**clean_data)
    except TwStockAgentError as e:
        return BestFourPointsResponse(
            stock_code=stock_code,
            updated_at=e.context.timestamp.isoformat(),
            error=e.message
        )
    except Exception as e:
        return BestFourPointsResponse(
            stock_code=stock_code,
            updated_at=datetime.now().isoformat(),
            error=f"Unexpected error: {str(e)}"
        )

@mcp.tool(name="get_realtime_data",
          description="Get real-time data for a specific stock.",
)
async def get_realtime_data_tool(stock_code: str) -> RealtimeDataResponse:
    """Get real-time data for a specific stock."""
    try:
        raw_data = await get_realtime_data(stock_code)
        # Extract clean data without _metadata for Pydantic model
        from tw_stock_agent.utils.mcp_error_handler import MCPResponseFormatter
        clean_data = MCPResponseFormatter.extract_metadata_for_model(raw_data)
        return RealtimeDataResponse(**clean_data)
    except TwStockAgentError as e:
        return RealtimeDataResponse(
            stock_code=stock_code,
            updated_at=e.context.timestamp.isoformat(),
            error=e.message
        )
    except Exception as e:
        return RealtimeDataResponse(
            stock_code=stock_code,
            updated_at=datetime.now().isoformat(),
            error=f"Unexpected error: {str(e)}"
        )

@mcp.tool(name="get_market_overview",
          description="Get market overview information.",
)
async def get_market_overview_tool() -> MarketOverviewResponse:
    """Get market overview information."""
    try:
        raw_data = await get_market_overview()
        # Extract clean data without _metadata for Pydantic model
        from tw_stock_agent.utils.mcp_error_handler import MCPResponseFormatter
        clean_data = MCPResponseFormatter.extract_metadata_for_model(raw_data)
        return MarketOverviewResponse(**clean_data)
    except TwStockAgentError as e:
        return MarketOverviewResponse(
            date=e.context.timestamp.isoformat(),
            error=e.message
        )
    except Exception as e:
        from datetime import datetime
        return MarketOverviewResponse(
            date=datetime.now().isoformat(),
            error=f"Unexpected error: {str(e)}"
        )


@mcp.tool(
    name="get_deviation_scan",
    description=(
        "批量掃描所有台股的 20MA 負乖離翻正標的。"
        "篩選條件：今日乖離率 0~5%（剛站上 MA20），且近 30 日有 ≥24 天為負乖離。"
        "傳入逗號分隔的 stock_codes 可只掃描指定股票；留空則自動從 TWSE 抓取當日清單。"
        "注意：全市場掃描約需 10–20 分鐘，建議盤後執行。"
    ),
)
async def get_deviation_scan_tool(stock_codes: str = "") -> Dict[str, Any]:
    """Bulk TWSE deviation scan — returns matched stocks with 20MA deviation criteria."""
    try:
        return await get_deviation_scan(stock_codes)
    except TwStockAgentError as e:
        return {"error": e.message, "matched": [], "matched_count": 0}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}", "matched": [], "matched_count": 0}


# Resource management endpoints using centralized resource manager
@mcp.resource("stock://info/{stock_code}")
async def get_stock_info_resource(stock_code: str) -> str:
    """Get detailed information about a specific stock."""
    return await resource_manager.get_resource(f"stock://info/{stock_code}")


@mcp.resource("stock://price/{stock_code}")
async def get_stock_price_resource(stock_code: str) -> str:
    """Get historical price data for a specific stock."""
    return await resource_manager.get_resource(f"stock://price/{stock_code}")


@mcp.resource("stock://price/{stock_code}/{period}")
async def get_stock_price_period_resource(stock_code: str, period: str) -> str:
    """Get historical price data for a specific stock and period."""
    return await resource_manager.get_resource(f"stock://price/{stock_code}/{period}")


@mcp.resource("stock://realtime/{stock_code}")
async def get_stock_realtime_resource(stock_code: str) -> str:
    """Get real-time data for a specific stock."""
    return await resource_manager.get_resource(f"stock://realtime/{stock_code}")


@mcp.resource("stock://analysis/{stock_code}")
async def get_stock_analysis_resource(stock_code: str) -> str:
    """Get technical analysis for a specific stock."""
    return await resource_manager.get_resource(f"stock://analysis/{stock_code}")


@mcp.resource("market://overview")
async def get_market_overview_resource() -> str:
    """Get Taiwan stock market overview."""
    return await resource_manager.get_resource("market://overview")


# Resource discovery and management tools
@mcp.tool(name="list_resources",
          description="List all available MCP resources with templates and examples")
async def list_resources_tool() -> Dict[str, Any]:
    """List all available MCP resources."""
    try:
        templates = resource_manager.list_resource_templates()
        cache_stats = resource_manager.get_cache_stats()
        subscriptions = resource_manager.get_subscriptions()
        
        return {
            "resource_templates": templates,
            "cache_statistics": cache_stats,
            "active_subscriptions": subscriptions,
            "total_resources": len(templates),
            "_metadata": {
                "source": "tw-stock-agent",
                "timestamp": datetime.now().isoformat(),
                "data_type": "resource_discovery"
            }
        }
    except Exception as e:
        logger.error(f"Failed to list resources: {e}")
        return {
            "error": f"Failed to list resources: {str(e)}",
            "_metadata": {
                "source": "tw-stock-agent",
                "timestamp": datetime.now().isoformat(),
                "data_type": "resource_discovery",
                "has_error": True
            }
        }


@mcp.tool(name="subscribe_resource",
          description="Subscribe to resource updates for caching and notifications")
async def subscribe_resource_tool(resource_uri: str) -> Dict[str, Any]:
    """Subscribe to resource updates."""
    try:
        success = resource_manager.subscribe_to_resource(resource_uri)
        return {
            "resource_uri": resource_uri,
            "subscribed": success,
            "active_subscriptions": resource_manager.get_subscriptions(),
            "_metadata": {
                "source": "tw-stock-agent",
                "timestamp": datetime.now().isoformat(),
                "data_type": "resource_subscription"
            }
        }
    except Exception as e:
        logger.error(f"Failed to subscribe to resource {resource_uri}: {e}")
        return {
            "resource_uri": resource_uri,
            "subscribed": False,
            "error": str(e),
            "_metadata": {
                "source": "tw-stock-agent",
                "timestamp": datetime.now().isoformat(),
                "data_type": "resource_subscription",
                "has_error": True
            }
        }


@mcp.tool(name="invalidate_cache",
          description="Invalidate resource cache for fresh data")
async def invalidate_cache_tool(resource_pattern: Optional[str] = None) -> Dict[str, Any]:
    """Invalidate resource cache."""
    try:
        invalidated_count = resource_manager.invalidate_cache(resource_pattern)
        cache_stats = resource_manager.get_cache_stats()
        
        return {
            "pattern": resource_pattern or "all",
            "invalidated_entries": invalidated_count,
            "cache_statistics": cache_stats,
            "_metadata": {
                "source": "tw-stock-agent",
                "timestamp": datetime.now().isoformat(),
                "data_type": "cache_management"
            }
        }
    except Exception as e:
        logger.error(f"Failed to invalidate cache: {e}")
        return {
            "pattern": resource_pattern or "all",
            "invalidated_entries": 0,
            "error": str(e),
            "_metadata": {
                "source": "tw-stock-agent",
                "timestamp": datetime.now().isoformat(),
                "data_type": "cache_management",
                "has_error": True
            }
        }


if __name__ == "__main__":
    mcp.run()