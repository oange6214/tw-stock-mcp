"""Shared service instances for MCP tools and resources."""

from tw_stock_mcp.services.market_service import MarketService
from tw_stock_mcp.services.stock_service import StockService

stock_service = StockService()
market_service = MarketService(stock_service=stock_service)
