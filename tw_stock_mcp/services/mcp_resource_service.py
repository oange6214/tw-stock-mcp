"""
MCP Resource Service for Taiwan Stock Agent.

This module provides comprehensive resource management for MCP protocol,
including resource discovery, caching, subscriptions, and security.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

from cachetools import TTLCache
from tw_stock_mcp.exceptions import (
    TwStockAgentError,
    MCPResourceError,
    create_error_response
)
from tw_stock_mcp.utils.mcp_error_handler import MCPErrorHandler
from tw_stock_mcp.services.service_container import market_service, stock_service

logger = logging.getLogger("tw-stock-agent.mcp_resource_service")


class ResourceManager:
    """Manages MCP resources with caching, subscriptions, and security."""
    
    def __init__(self):
        """Initialize the resource manager."""
        # Resource caching with 5-minute TTL
        self.cache = TTLCache(maxsize=1000, ttl=300)  
        
        # Resource subscriptions
        self.subscriptions: Set[str] = set()
        
        # Rate limiting per resource type
        self.rate_limits = {
            "stock": {"requests": 100, "window": 3600},  # 100 requests/hour per stock
            "market": {"requests": 60, "window": 3600},   # 60 requests/hour for market
            "realtime": {"requests": 300, "window": 3600}  # 300 requests/hour for realtime
        }
        
        # Track resource access for rate limiting
        self.access_history: Dict[str, List[datetime]] = {}
        
        # Resource templates for discovery
        self.resource_templates = {
            "stock://info/{stock_code}": {
                "description": "Get detailed information about a specific Taiwan stock",
                "mimeType": "application/json",
                "parameters": ["stock_code"],
                "examples": ["stock://info/2330", "stock://info/1101"]
            },
            "stock://price/{stock_code}": {
                "description": "Get historical price data for a stock (default 1 month)",
                "mimeType": "application/json",
                "parameters": ["stock_code"],
                "examples": ["stock://price/2330", "stock://price/0050"]
            },
            "stock://price/{stock_code}/{period}": {
                "description": "Get historical price data for a specific period",
                "mimeType": "application/json",
                "parameters": ["stock_code", "period"],
                "examples": ["stock://price/2330/1y", "stock://price/1101/3mo"]
            },
            "stock://realtime/{stock_code}": {
                "description": "Get real-time trading data for a stock",
                "mimeType": "application/json",
                "parameters": ["stock_code"],
                "examples": ["stock://realtime/2330", "stock://realtime/0050"]
            },
            "stock://analysis/{stock_code}": {
                "description": "Get technical analysis and trading signals",
                "mimeType": "application/json",
                "parameters": ["stock_code"],
                "examples": ["stock://analysis/2330", "stock://analysis/1101"]
            },
            "market://overview": {
                "description": "Get Taiwan stock market overview and statistics",
                "mimeType": "application/json",
                "parameters": [],
                "examples": ["market://overview"]
            }
        }
    
    def list_resource_templates(self) -> List[Dict[str, Any]]:
        """List all available resource templates for discovery."""
        templates = []
        for uri_template, info in self.resource_templates.items():
            templates.append({
                "uriTemplate": uri_template,
                "name": uri_template.split("://")[1].replace("/", "_").replace("{", "").replace("}", ""),
                "description": info["description"],
                "mimeType": info["mimeType"],
                **info
            })
        return templates
    
    def _check_rate_limit(self, resource_uri: str) -> bool:
        """Check if resource request is within rate limits."""
        try:
            parsed = urlparse(resource_uri)
            resource_type = parsed.scheme  # stock, market, etc.
            
            if resource_type not in self.rate_limits:
                return True
            
            limit_config = self.rate_limits[resource_type]
            now = datetime.now()
            
            # Initialize access history for this resource
            if resource_uri not in self.access_history:
                self.access_history[resource_uri] = []
            
            # Clean old entries outside the window
            window_start = now - timedelta(seconds=limit_config["window"])
            self.access_history[resource_uri] = [
                access_time for access_time in self.access_history[resource_uri]
                if access_time >= window_start
            ]
            
            # Check if within limits
            if len(self.access_history[resource_uri]) >= limit_config["requests"]:
                return False
            
            # Record this access
            self.access_history[resource_uri].append(now)
            return True
            
        except Exception as e:
            logger.warning(f"Rate limit check failed for {resource_uri}: {e}")
            return True  # Allow on error
    
    def _get_cache_key(self, resource_uri: str) -> str:
        """Generate cache key for resource URI."""
        return f"resource:{resource_uri}"
    
    async def get_resource(self, resource_uri: str) -> str:
        """
        Get resource data with caching and rate limiting.
        
        Args:
            resource_uri: The resource URI to fetch
            
        Returns:
            JSON string containing resource data
            
        Raises:
            MCPResourceError: If resource access fails
        """
        # Rate limiting check
        if not self._check_rate_limit(resource_uri):
            raise MCPResourceError(
                resource_uri=resource_uri,
                message="Rate limit exceeded for resource access"
            )
        
        # Check cache first
        cache_key = self._get_cache_key(resource_uri)
        if cache_key in self.cache:
            logger.debug(f"Cache hit for resource: {resource_uri}")
            return self.cache[cache_key]
        
        try:
            # Parse resource URI - handle netloc as resource type for custom schemes
            parsed = urlparse(resource_uri)
            
            data = None
            
            if parsed.scheme == "stock":
                # For stock:// URIs, the format is stock://resource_type/stock_code[/period]
                resource_type = parsed.netloc  # The "hostname" is actually the resource type
                path_parts = parsed.path.strip('/').split('/') if parsed.path.strip('/') else []
                
                logger.debug(f"Parsing stock resource: type={resource_type}, path_parts={path_parts}")
                
                if not path_parts:
                    raise MCPResourceError(
                        resource_uri=resource_uri,
                        message=f"Missing stock code in resource URI"
                    )
                
                stock_code = path_parts[0]
                
                if resource_type == "info":
                    data = await stock_service.fetch_stock_data(stock_code)
                elif resource_type == "price":
                    period = path_parts[1] if len(path_parts) > 1 else "1mo"
                    days_map = {
                        "1d": 1,
                        "5d": 5,
                        "1mo": 30,
                        "3mo": 90,
                        "6mo": 180,
                        "1y": 365,
                        "ytd": max(
                            1,
                            (
                                datetime.now()
                                - datetime(datetime.now().year, 1, 1)
                            ).days,
                        ),
                        "max": 3650,
                    }
                    days = days_map.get(period, 30)
                    price_data = await stock_service.fetch_price_data(stock_code, days)
                    data = {
                        "stock_code": stock_code,
                        "period": period,
                        "data": price_data,
                        "requested_days": days,
                        "actual_records": len(price_data),
                    }
                elif resource_type == "realtime":
                    data = await stock_service.get_realtime_data(stock_code)
                elif resource_type == "analysis":
                    data = await stock_service.get_best_four_points(stock_code)
                else:
                    raise MCPResourceError(
                        resource_uri=resource_uri,
                        message=f"Unknown stock resource type: {resource_type}"
                    )
                        
            elif parsed.scheme == "market":
                # For market:// URIs, the format is market://resource_type
                resource_type = parsed.netloc
                
                if resource_type == "overview":
                    data = await market_service.get_market_overview()
                else:
                    raise MCPResourceError(
                        resource_uri=resource_uri,
                        message=f"Unknown market resource: {resource_type}"
                    )
            else:
                raise MCPResourceError(
                    resource_uri=resource_uri,
                    message=f"Unknown resource scheme: {parsed.scheme}"
                )
            
            if data is None:
                raise MCPResourceError(
                    resource_uri=resource_uri,
                    message="Resource not found or no data available"
                )
            
            # Add metadata for resource response
            resource_response = {
                "uri": resource_uri,
                "timestamp": datetime.now().isoformat(),
                "data": data,
                "_metadata": {
                    "source": "tw-stock-agent",
                    "cached": False,
                    "rate_limited": False
                }
            }
            
            # Convert to JSON with datetime handling
            json_response = json.dumps(resource_response, ensure_ascii=False, indent=2, default=str)
            
            # Cache the response
            self.cache[cache_key] = json_response
            logger.debug(f"Cached resource: {resource_uri}")
            
            return json_response
            
        except TwStockAgentError as e:
            # Handle known errors
            error_response = MCPErrorHandler.handle_resource_error(
                error=e,
                resource_uri=resource_uri
            )
            return json.dumps(error_response, ensure_ascii=False, indent=2, default=str)
            
        except Exception as e:
            # Handle unexpected errors
            logger.error(f"Unexpected error fetching resource {resource_uri}: {e}")
            error_response = create_error_response(e)
            error_response["resource_uri"] = resource_uri
            return json.dumps(error_response, ensure_ascii=False, indent=2, default=str)
    
    def subscribe_to_resource(self, resource_uri: str) -> bool:
        """
        Subscribe to resource updates.
        
        Args:
            resource_uri: The resource URI to subscribe to
            
        Returns:
            True if subscription successful
        """
        try:
            self.subscriptions.add(resource_uri)
            logger.info(f"Subscribed to resource: {resource_uri}")
            return True
        except Exception as e:
            logger.error(f"Failed to subscribe to resource {resource_uri}: {e}")
            return False
    
    def unsubscribe_from_resource(self, resource_uri: str) -> bool:
        """
        Unsubscribe from resource updates.
        
        Args:
            resource_uri: The resource URI to unsubscribe from
            
        Returns:
            True if unsubscription successful
        """
        try:
            self.subscriptions.discard(resource_uri)
            logger.info(f"Unsubscribed from resource: {resource_uri}")
            return True
        except Exception as e:
            logger.error(f"Failed to unsubscribe from resource {resource_uri}: {e}")
            return False
    
    def get_subscriptions(self) -> List[str]:
        """Get list of current resource subscriptions."""
        return list(self.subscriptions)
    
    def invalidate_cache(self, resource_pattern: Optional[str] = None) -> int:
        """
        Invalidate cached resources.
        
        Args:
            resource_pattern: Optional pattern to match specific resources
            
        Returns:
            Number of cache entries invalidated
        """
        if resource_pattern is None:
            # Clear entire cache
            count = len(self.cache)
            self.cache.clear()
            logger.info(f"Invalidated entire resource cache ({count} entries)")
            return count
        else:
            # Clear matching entries
            keys_to_remove = [
                key for key in self.cache.keys()
                if resource_pattern in key
            ]
            for key in keys_to_remove:
                del self.cache[key]
            logger.info(f"Invalidated {len(keys_to_remove)} cache entries matching '{resource_pattern}'")
            return len(keys_to_remove)
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "size": len(self.cache),
            "max_size": self.cache.maxsize,
            "ttl": self.cache.ttl,
            "hits": getattr(self.cache, 'hits', 0),
            "misses": getattr(self.cache, 'misses', 0),
            "subscriptions": len(self.subscriptions)
        }


# Global resource manager instance
resource_manager = ResourceManager()
