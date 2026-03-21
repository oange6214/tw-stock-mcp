import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP

from tw_stock_mcp.tools.stock_tools import (
    get_best_four_points,
    get_deviation_scan,
    get_fundamental_data,
    get_market_overview,
    get_price_history,
    get_realtime_data,
    get_stock_data,
)
from tw_stock_mcp.utils.config import get_settings
from tw_stock_mcp.exceptions import TwStockAgentError
from tw_stock_mcp.services.mcp_resource_service import resource_manager

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
    lifespan=app_lifespan
)

@mcp.tool(name="get_stock_data",
          description="取得股票基本資料（公司名稱、產業別、市場等）。",
)
async def get_stock_data_tool(stock_code: str) -> Dict[str, Any]:
    try:
        return await get_stock_data(stock_code)
    except TwStockAgentError as e:
        return {"stock_code": stock_code, "error": e.message}
    except Exception as e:
        return {"stock_code": stock_code, "error": str(e)}


@mcp.tool(name="get_price_history",
          description="取得股票歷史 K 線資料。",
)
async def get_price_history_tool(stock_code: str, period: str = "1mo") -> Dict[str, Any]:
    try:
        return await get_price_history(stock_code, period)
    except TwStockAgentError as e:
        return {"stock_code": stock_code, "period": period, "data": [], "error": e.message}
    except Exception as e:
        return {"stock_code": stock_code, "period": period, "data": [], "error": str(e)}


@mcp.tool(name="get_best_four_points",
          description="取得四大買賣點技術分析。",
)
async def get_best_four_points_tool(stock_code: str) -> Dict[str, Any]:
    try:
        return await get_best_four_points(stock_code)
    except TwStockAgentError as e:
        return {"stock_code": stock_code, "error": e.message}
    except Exception as e:
        return {"stock_code": stock_code, "error": str(e)}


@mcp.tool(name="get_realtime_data",
          description="取得即時報價。",
)
async def get_realtime_data_tool(stock_code: str) -> Dict[str, Any]:
    try:
        return await get_realtime_data(stock_code)
    except TwStockAgentError as e:
        return {"stock_code": stock_code, "error": e.message}
    except Exception as e:
        return {"stock_code": stock_code, "error": str(e)}


@mcp.tool(name="get_market_overview",
          description="取得大盤概況（加權指數等）。",
)
async def get_market_overview_tool() -> Dict[str, Any]:
    try:
        return await get_market_overview()
    except TwStockAgentError as e:
        return {"error": e.message}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(
    name="get_fundamental_data",
    description=(
        "取得個股三年基本面資料：每日本益比（PER）、股價淨值比（PBR）、殖利率，"
        "以及每季 EPS，並計算每季平均 PER 與近四季累計 EPS（TTM）。"
        "需要 FINMIND_API_TOKEN 環境變數。"
    ),
)
async def get_fundamental_data_tool(stock_code: str) -> Dict[str, Any]:
    try:
        return await get_fundamental_data(stock_code)
    except TwStockAgentError as e:
        return {"stock_code": stock_code, "error": e.message}
    except Exception as e:
        return {"stock_code": stock_code, "error": str(e)}


@mcp.tool(
    name="get_deviation_scan",
    description=(
        "批量掃描所有台股的 60MA 負乖離翻正標的。"
        "篩選條件：今日乖離率 0~5%（剛站上 MA60），且近 30 日有 ≥24 天為負乖離。"
        "傳入逗號分隔的 stock_codes 可只掃描指定股票；留空則自動從 TWSE 抓取當日清單。"
        "注意：全市場掃描約需 10–20 分鐘，建議盤後執行。"
    ),
)
async def get_deviation_scan_tool(stock_codes: str = "") -> Dict[str, Any]:
    """Bulk TWSE deviation scan — returns matched stocks with 60MA deviation criteria."""
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


def main():
    mcp.run()


if __name__ == "__main__":
    main()