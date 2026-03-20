"""HTTP Connection Pool Manager for optimized external API requests."""
import asyncio
import logging
import ssl
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Optional

import aiohttp
from aiohttp import ClientTimeout, TCPConnector, ClientSession

from tw_stock_agent.utils.config import ConnectionPoolConfig, get_connection_pool_config

logger = logging.getLogger("tw-stock-agent.connection_pool")


@dataclass
class ConnectionMetrics:
    """Connection pool metrics"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    timeout_requests: int = 0
    retry_requests: int = 0
    active_connections: int = 0
    pool_size: int = 0
    average_response_time: float = 0.0
    last_updated: float = field(default_factory=time.time)
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate"""
        if self.total_requests == 0:
            return 0.0
        return self.successful_requests / self.total_requests
    
    def update_response_time(self, response_time: float) -> None:
        """Update average response time"""
        if self.total_requests == 0:
            self.average_response_time = response_time
        else:
            # Simple moving average
            self.average_response_time = (
                (self.average_response_time * (self.total_requests - 1) + response_time) / 
                self.total_requests
            )
        self.last_updated = time.time()


class HTTPConnectionPool:
    """High-performance HTTP connection pool using aiohttp"""
    
    def __init__(self, config: Optional[ConnectionPoolConfig] = None):
        """Initialize the HTTP connection pool
        
        Args:
            config: Connection pool configuration
        """
        self.config = config or get_connection_pool_config()
        self._session: Optional[ClientSession] = None
        self._metrics = ConnectionMetrics()
        self._lock = asyncio.Lock()
        self._closed = False
        
        # Request headers for Taiwan stock APIs
        self._default_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/html, application/xhtml+xml, application/xml;q=0.9, */*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br" if self.config.enable_compression else "identity",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
        }
    
    @staticmethod
    def _build_ssl_context() -> ssl.SSLContext:
        """Return an SSL context that skips certificate verification.

        TWSE (openapi.twse.com.tw, www.twse.com.tw) certificates are missing
        the Subject Key Identifier extension, causing standard verification to
        fail.  Since this pool is used exclusively for public Taiwan stock market
        APIs, disabling verification is safe.
        """
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    async def _create_session(self) -> ClientSession:
        """Create a new aiohttp ClientSession with optimized settings"""
        ssl_ctx = self._build_ssl_context()

        # Configure TCP connector for connection pooling
        connector = TCPConnector(
            limit=self.config.max_connections,
            limit_per_host=self.config.max_connections_per_host,
            keepalive_timeout=self.config.keepalive_timeout,
            enable_cleanup_closed=True,
            force_close=False,
            use_dns_cache=True,
            ttl_dns_cache=300,  # 5 minutes DNS cache
            ssl=ssl_ctx,
        )
        
        # Configure timeouts
        timeout = ClientTimeout(
            total=self.config.total_timeout,
            connect=self.config.connection_timeout,
            sock_read=self.config.read_timeout,
        )
        
        # Create session with optimized settings
        session = ClientSession(
            connector=connector,
            timeout=timeout,
            headers=self._default_headers,
            trust_env=self.config.trust_env,
            cookie_jar=aiohttp.CookieJar() if self.config.enable_cookies else None,
            read_bufsize=64 * 1024,  # 64KB read buffer
            auto_decompress=self.config.enable_compression,
        )
        
        logger.info(
            f"Created HTTP session with max_connections={self.config.max_connections}, "
            f"max_per_host={self.config.max_connections_per_host}"
        )
        return session
    
    async def _get_session(self) -> ClientSession:
        """Get or create the HTTP session"""
        async with self._lock:
            if self._session is None or self._session.closed:
                self._session = await self._create_session()
            return self._session
    
    async def get(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """Perform GET request with connection pooling and retry logic"""
        return await self._request("GET", url, **kwargs)
    
    async def post(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """Perform POST request with connection pooling and retry logic"""
        return await self._request("POST", url, **kwargs)
    
    async def _request(
        self, 
        method: str, 
        url: str, 
        headers: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> aiohttp.ClientResponse:
        """Perform HTTP request with retry logic and metrics tracking"""
        if self._closed:
            raise RuntimeError("Connection pool is closed")
        
        start_time = time.time()
        last_exception = None
        
        # Merge custom headers with defaults
        request_headers = self._default_headers.copy()
        if headers:
            request_headers.update(headers)
        
        for attempt in range(self.config.retry_attempts + 1):
            try:
                session = await self._get_session()
                self._metrics.total_requests += 1

                if attempt > 0:
                    self._metrics.retry_requests += 1
                    delay = self.config.retry_delay * (2 ** (attempt - 1))
                    await asyncio.sleep(delay)
                    logger.debug(f"Retry attempt {attempt} for {method} {url} after {delay}s delay")

                # Do NOT use session.request() as a context manager here.
                # Exiting async-with calls response.release(), which closes the
                # underlying stream before callers have a chance to read the body.
                # The caller (request_context) is responsible for closing the response.
                response = await session.request(
                    method,
                    url,
                    headers=request_headers,
                    **kwargs,
                )

                # Update metrics
                response_time = time.time() - start_time
                self._metrics.successful_requests += 1
                self._metrics.update_response_time(response_time)

                if hasattr(session.connector, "_conns"):
                    self._metrics.active_connections = len(session.connector._conns)
                    self._metrics.pool_size = session.connector.limit

                logger.debug(
                    f"{method} {url} completed in {response_time:.3f}s "
                    f"(status: {response.status}, attempt: {attempt + 1})"
                )
                return response

            except asyncio.TimeoutError as e:
                last_exception = e
                self._metrics.timeout_requests += 1
                logger.warning(f"Timeout on attempt {attempt + 1} for {method} {url}: {e}")

            except (aiohttp.ClientError, OSError) as e:
                last_exception = e
                logger.warning(f"Request failed on attempt {attempt + 1} for {method} {url}: {e}")

            except Exception as e:
                last_exception = e
                logger.error(f"Unexpected error on attempt {attempt + 1} for {method} {url}: {e}")
        
        # All retries failed
        self._metrics.failed_requests += 1
        response_time = time.time() - start_time
        self._metrics.update_response_time(response_time)
        
        logger.error(
            f"All {self.config.retry_attempts + 1} attempts failed for {method} {url} "
            f"in {response_time:.3f}s. Last error: {last_exception}"
        )
        raise last_exception
    
    @asynccontextmanager
    async def request_context(
        self, 
        method: str, 
        url: str, 
        **kwargs
    ) -> AsyncIterator[aiohttp.ClientResponse]:
        """Context manager for HTTP requests with automatic response cleanup"""
        response = await self._request(method, url, **kwargs)
        try:
            yield response
        finally:
            response.close()
    
    async def get_json(self, url: str, **kwargs) -> Dict[str, Any]:
        """Perform GET request and return JSON response (always UTF-8)."""
        async with self.request_context("GET", url, **kwargs) as response:
            response.raise_for_status()
            # Explicitly decode as UTF-8 — TWSE APIs omit charset in Content-Type
            # which causes aiohttp to fall back to platform default on some systems.
            body = await response.read()
            import json as _json
            return _json.loads(body.decode("utf-8"))
    
    async def get_text(self, url: str, encoding: str = "utf-8", **kwargs) -> str:
        """Perform GET request and return text response"""
        async with self.request_context("GET", url, **kwargs) as response:
            response.raise_for_status()
            return await response.text(encoding=encoding)
    
    def get_metrics(self) -> ConnectionMetrics:
        """Get current connection pool metrics"""
        return self._metrics
    
    def reset_metrics(self) -> None:
        """Reset connection pool metrics"""
        self._metrics = ConnectionMetrics()
    
    async def health_check(self, url: str = "https://www.google.com") -> bool:
        """Perform a health check on the connection pool"""
        try:
            async with self.request_context("GET", url) as response:
                return response.status == 200
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False
    
    async def warm_up(self, urls: list[str]) -> Dict[str, bool]:
        """Warm up the connection pool by pre-connecting to URLs"""
        results = {}
        tasks = []
        
        for url in urls:
            task = asyncio.create_task(self._warm_up_url(url))
            tasks.append((url, task))
        
        for url, task in tasks:
            try:
                results[url] = await task
            except Exception as e:
                logger.warning(f"Warm-up failed for {url}: {e}")
                results[url] = False
        
        successful_warmups = sum(results.values())
        logger.info(f"Connection pool warm-up completed: {successful_warmups}/{len(urls)} successful")
        return results
    
    async def _warm_up_url(self, url: str) -> bool:
        """Warm up connection to a specific URL"""
        try:
            async with self.request_context("HEAD", url) as response:
                return True
        except Exception:
            return False
    
    async def close(self) -> None:
        """Close the connection pool and cleanup resources"""
        if self._closed:
            return
        
        self._closed = True
        async with self._lock:
            if self._session and not self._session.closed:
                await self._session.close()
                # Wait for session to fully close
                await asyncio.sleep(0.25)
        
        logger.info("HTTP connection pool closed")
    
    async def __aenter__(self):
        """Async context manager entry"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()


# Global connection pool instance
_global_pool: Optional[HTTPConnectionPool] = None
_pool_lock = asyncio.Lock()


async def get_global_pool() -> HTTPConnectionPool:
    """Get or create the global HTTP connection pool"""
    global _global_pool
    
    async with _pool_lock:
        if _global_pool is None or _global_pool._closed:
            _global_pool = HTTPConnectionPool()
        return _global_pool


async def close_global_pool() -> None:
    """Close the global HTTP connection pool"""
    global _global_pool
    
    async with _pool_lock:
        if _global_pool:
            await _global_pool.close()
            _global_pool = None