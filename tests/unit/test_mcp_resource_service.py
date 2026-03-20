"""Unit tests for MCP Resource Service."""

import pytest
from unittest.mock import AsyncMock, patch
import json
from datetime import datetime

from tw_stock_mcp.services.mcp_resource_service import ResourceManager
from tw_stock_mcp.exceptions import MCPResourceError


class TestResourceManager:
    """Test the ResourceManager class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.resource_manager = ResourceManager()
    
    def test_resource_templates_listing(self):
        """Test listing of resource templates."""
        templates = self.resource_manager.list_resource_templates()
        
        assert len(templates) == 6  # We have 6 resource templates
        
        # Check that all expected templates are present
        template_uris = [t["uriTemplate"] for t in templates]
        expected_uris = [
            "stock://info/{stock_code}",
            "stock://price/{stock_code}",
            "stock://price/{stock_code}/{period}",
            "stock://realtime/{stock_code}",
            "stock://analysis/{stock_code}",
            "market://overview"
        ]
        
        for expected_uri in expected_uris:
            assert expected_uri in template_uris
    
    def test_cache_key_generation(self):
        """Test cache key generation."""
        uri = "stock://info/2330"
        key = self.resource_manager._get_cache_key(uri)
        assert key == "resource:stock://info/2330"
    
    def test_rate_limit_check(self):
        """Test rate limiting functionality."""
        uri = "stock://info/2330"
        
        # First request should be allowed
        assert self.resource_manager._check_rate_limit(uri) is True
        
        # Should still be allowed for reasonable number of requests
        for _ in range(10):
            assert self.resource_manager._check_rate_limit(uri) is True
    
    def test_subscription_management(self):
        """Test resource subscription functionality."""
        uri = "stock://realtime/2330"
        
        # Initially no subscriptions
        assert len(self.resource_manager.get_subscriptions()) == 0
        
        # Subscribe to resource
        result = self.resource_manager.subscribe_to_resource(uri)
        assert result is True
        assert uri in self.resource_manager.get_subscriptions()
        
        # Unsubscribe from resource
        result = self.resource_manager.unsubscribe_from_resource(uri)
        assert result is True
        assert uri not in self.resource_manager.get_subscriptions()
    
    def test_cache_invalidation(self):
        """Test cache invalidation functionality."""
        # Add some mock data to cache
        self.resource_manager.cache["resource:stock://info/2330"] = "mock_data_1"
        self.resource_manager.cache["resource:stock://price/2330"] = "mock_data_2"
        self.resource_manager.cache["resource:market://overview"] = "mock_data_3"
        
        # Test pattern-based invalidation
        count = self.resource_manager.invalidate_cache("stock://info")
        assert count == 1
        assert "resource:stock://info/2330" not in self.resource_manager.cache
        assert "resource:stock://price/2330" in self.resource_manager.cache
        
        # Test full cache invalidation
        count = self.resource_manager.invalidate_cache()
        assert count == 2  # Remaining 2 entries
        assert len(self.resource_manager.cache) == 0
    
    def test_cache_stats(self):
        """Test cache statistics."""
        stats = self.resource_manager.get_cache_stats()
        
        assert "size" in stats
        assert "max_size" in stats
        assert "ttl" in stats
        assert "subscriptions" in stats
        
        assert stats["max_size"] == 1000
        assert stats["ttl"] == 300
    
    @pytest.mark.asyncio
    async def test_get_stock_info_resource(self):
        """Test getting stock info resource."""
        with patch('tw_stock_mcp.services.mcp_resource_service.get_stock_data') as mock_get:
            mock_get.return_value = {
                "stock_code": "2330",
                "name": "台積電",
                "market_type": "上市"
            }
            
            result = await self.resource_manager.get_resource("stock://info/2330")
            
            # Should be valid JSON
            data = json.loads(result)
            assert data["uri"] == "stock://info/2330"
            assert "data" in data
            assert data["data"]["stock_code"] == "2330"
            assert "_metadata" in data
    
    @pytest.mark.asyncio
    async def test_get_price_resource_with_period(self):
        """Test getting price resource with period."""
        with patch('tw_stock_mcp.services.mcp_resource_service.get_price_history') as mock_get:
            mock_get.return_value = {
                "stock_code": "2330",
                "period": "1y",
                "data": [{"date": "2024-01-01", "close": 600.0}]
            }
            
            result = await self.resource_manager.get_resource("stock://price/2330/1y")
            
            # Should be valid JSON
            data = json.loads(result)
            assert data["uri"] == "stock://price/2330/1y"
            assert "data" in data
            assert data["data"]["period"] == "1y"
    
    @pytest.mark.asyncio
    async def test_get_market_overview_resource(self):
        """Test getting market overview resource."""
        with patch('tw_stock_mcp.services.mcp_resource_service.get_market_overview') as mock_get:
            mock_get.return_value = {
                "trading_date": "2024-01-01",
                "taiex_index": {"current_value": 17000.0}
            }
            
            result = await self.resource_manager.get_resource("market://overview")
            
            # Should be valid JSON
            data = json.loads(result)
            assert data["uri"] == "market://overview"
            assert "data" in data
    
    @pytest.mark.asyncio
    async def test_invalid_resource_scheme(self):
        """Test handling of invalid resource scheme."""
        result = await self.resource_manager.get_resource("invalid://test")
        
        # Should return error response
        data = json.loads(result)
        assert "error" in data or ("data" in data and "error" in data["data"])
    
    @pytest.mark.asyncio
    async def test_invalid_resource_type(self):
        """Test handling of invalid resource type."""
        result = await self.resource_manager.get_resource("stock://invalid/2330")
        
        # Should return error response
        data = json.loads(result)
        assert "error" in data or ("data" in data and "error" in data["data"])
    
    @pytest.mark.asyncio
    async def test_resource_caching(self):
        """Test that resources are properly cached."""
        with patch('tw_stock_mcp.services.mcp_resource_service.get_stock_data') as mock_get:
            mock_get.return_value = {"stock_code": "2330", "name": "台積電"}
            
            # First call should hit the service
            result1 = await self.resource_manager.get_resource("stock://info/2330")
            assert mock_get.call_count == 1
            
            # Second call should use cache
            result2 = await self.resource_manager.get_resource("stock://info/2330")
            assert mock_get.call_count == 1  # Still only 1 call
            
            # Results should be identical
            assert result1 == result2
    
    @pytest.mark.asyncio 
    async def test_error_handling_in_resource_fetch(self):
        """Test error handling when resource fetch fails."""
        with patch('tw_stock_mcp.services.mcp_resource_service.get_stock_data') as mock_get:
            from tw_stock_mcp.exceptions import StockNotFoundError
            mock_get.side_effect = StockNotFoundError("2330")
            
            result = await self.resource_manager.get_resource("stock://info/2330")
            
            # Should return error response as JSON
            data = json.loads(result)
            assert "error" in data
    
    def test_resource_template_structure(self):
        """Test that resource templates have proper structure."""
        templates = self.resource_manager.list_resource_templates()
        
        for template in templates:
            # Each template should have required fields
            assert "uriTemplate" in template
            assert "name" in template
            assert "description" in template
            assert "mimeType" in template
            assert "parameters" in template
            assert "examples" in template
            
            # MIME type should be JSON
            assert template["mimeType"] == "application/json"
            
            # Should have examples
            assert len(template["examples"]) > 0