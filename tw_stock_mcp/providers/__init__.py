"""Provider abstraction layer for stock data sources.

Usage:
    from tw_stock_mcp.providers import StockDataProvider, create_provider

    # Default provider from STOCK_DATA_PROVIDER env var (default: "twstock")
    provider = create_provider()

    # Explicit provider
    from tw_stock_mcp.providers.finmind_provider import FinMindProvider
    provider = FinMindProvider(api_token="...")
"""

from tw_stock_mcp.providers.base import StockDataProvider
from tw_stock_mcp.providers.factory import create_provider

__all__ = ["StockDataProvider", "create_provider"]
