"""Shared service instances for MCP tools and resources."""

from tw_stock_agent.services.market_service import MarketService
from tw_stock_agent.services.stock_service import StockService

stock_service = StockService()
market_service = MarketService(stock_service=stock_service)
