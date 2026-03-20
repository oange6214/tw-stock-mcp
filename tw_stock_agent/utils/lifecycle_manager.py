"""Application lifecycle management for graceful startup and shutdown."""
import asyncio
import atexit
import logging
import signal
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from tw_stock_agent.utils.connection_pool import HTTPConnectionPool, close_global_pool
from tw_stock_agent.utils.database_pool import AsyncDatabasePool
from tw_stock_agent.utils.performance_monitor import PerformanceMonitor, stop_global_monitoring

logger = logging.getLogger("tw-stock-agent.lifecycle_manager")


class LifecycleManager:
    """Manages application lifecycle, resource initialization, and graceful shutdown"""
    
    def __init__(self):
        self._startup_hooks: List[Callable[[], Any]] = []
        self._shutdown_hooks: List[Callable[[], Any]] = []
        self._async_startup_hooks: List[Callable[[], Any]] = []
        self._async_shutdown_hooks: List[Callable[[], Any]] = []
        self._resources: List[Any] = []
        self._shutdown_initiated = False
        self._shutdown_timeout = 30.0  # seconds
        
        # Register signal handlers for graceful shutdown
        self._register_signal_handlers()
        
        # Register atexit handler as fallback
        atexit.register(self._emergency_shutdown)
    
    def _register_signal_handlers(self) -> None:
        """Register signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating graceful shutdown...")
            if not self._shutdown_initiated:
                asyncio.create_task(self.shutdown())
        
        if sys.platform != "win32":
            signal.signal(signal.SIGTERM, signal_handler)
            signal.signal(signal.SIGINT, signal_handler)
    
    def add_startup_hook(self, hook: Callable[[], Any]) -> None:
        """Add a synchronous startup hook"""
        self._startup_hooks.append(hook)
    
    def add_shutdown_hook(self, hook: Callable[[], Any]) -> None:
        """Add a synchronous shutdown hook"""
        self._shutdown_hooks.append(hook)
    
    def add_async_startup_hook(self, hook: Callable[[], Any]) -> None:
        """Add an asynchronous startup hook"""
        self._async_startup_hooks.append(hook)
    
    def add_async_shutdown_hook(self, hook: Callable[[], Any]) -> None:
        """Add an asynchronous shutdown hook"""
        self._async_shutdown_hooks.append(hook)
    
    def register_resource(self, resource: Any) -> None:
        """Register a resource that needs cleanup on shutdown"""
        self._resources.append(resource)
    
    async def startup(self) -> None:
        """Execute all startup hooks"""
        logger.info("Starting application lifecycle...")
        
        # Execute synchronous startup hooks
        for hook in self._startup_hooks:
            try:
                logger.debug(f"Executing startup hook: {hook.__name__}")
                hook()
            except Exception as e:
                logger.error(f"Startup hook {hook.__name__} failed: {e}")
                raise
        
        # Execute asynchronous startup hooks
        for hook in self._async_startup_hooks:
            try:
                logger.debug(f"Executing async startup hook: {hook.__name__}")
                if asyncio.iscoroutinefunction(hook):
                    await hook()
                else:
                    hook()
            except Exception as e:
                logger.error(f"Async startup hook {hook.__name__} failed: {e}")
                raise
        
        logger.info("Application startup completed")
    
    async def shutdown(self) -> None:
        """Execute all shutdown hooks with timeout"""
        if self._shutdown_initiated:
            logger.warning("Shutdown already initiated")
            return
        
        self._shutdown_initiated = True
        logger.info("Starting graceful shutdown...")
        
        try:
            # Execute shutdown with timeout
            await asyncio.wait_for(self._execute_shutdown(), timeout=self._shutdown_timeout)
            logger.info("Graceful shutdown completed")
        except asyncio.TimeoutError:
            logger.error(f"Shutdown timeout after {self._shutdown_timeout}s, forcing exit")
            self._force_shutdown()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
            self._force_shutdown()
    
    async def _execute_shutdown(self) -> None:
        """Execute shutdown hooks"""
        # Execute asynchronous shutdown hooks first
        for hook in self._async_shutdown_hooks:
            try:
                logger.debug(f"Executing async shutdown hook: {hook.__name__}")
                if asyncio.iscoroutinefunction(hook):
                    await hook()
                else:
                    hook()
            except Exception as e:
                logger.error(f"Async shutdown hook {hook.__name__} failed: {e}")
        
        # Clean up registered resources
        for resource in self._resources:
            try:
                logger.debug(f"Cleaning up resource: {type(resource).__name__}")
                if hasattr(resource, 'close'):
                    if asyncio.iscoroutinefunction(resource.close):
                        await resource.close()
                    else:
                        resource.close()
                elif hasattr(resource, '__aenter__') and hasattr(resource, '__aexit__'):
                    # It's an async context manager, try to exit
                    await resource.__aexit__(None, None, None)
            except Exception as e:
                logger.error(f"Failed to cleanup resource {type(resource).__name__}: {e}")
        
        # Execute synchronous shutdown hooks
        for hook in self._shutdown_hooks:
            try:
                logger.debug(f"Executing shutdown hook: {hook.__name__}")
                hook()
            except Exception as e:
                logger.error(f"Shutdown hook {hook.__name__} failed: {e}")
    
    def _emergency_shutdown(self) -> None:
        """Emergency shutdown called by atexit"""
        if not self._shutdown_initiated:
            logger.warning("Emergency shutdown initiated via atexit")
            self._force_shutdown()
    
    def _force_shutdown(self) -> None:
        """Force immediate shutdown"""
        logger.warning("Forcing immediate shutdown")
        
        # Try to clean up resources quickly
        for resource in self._resources:
            try:
                if hasattr(resource, 'close'):
                    resource.close()
            except:
                pass  # Ignore errors during force shutdown
        
        # Cancel all running tasks
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                tasks = [task for task in asyncio.all_tasks(loop) if not task.done()]
                for task in tasks:
                    task.cancel()
        except:
            pass
    
    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        """Async context manager for complete application lifecycle"""
        try:
            await self.startup()
            yield
        finally:
            await self.shutdown()


class ConnectionPoolManager:
    """Manages connection pools for the application"""
    
    def __init__(self):
        self.http_pool: Optional[HTTPConnectionPool] = None
        self.db_pool: Optional[AsyncDatabasePool] = None
        self.performance_monitor: Optional[PerformanceMonitor] = None
        self._initialized = False
    
    async def initialize(self, db_path: str) -> None:
        """Initialize all connection pools"""
        if self._initialized:
            return
        
        logger.info("Initializing connection pools...")
        
        # Initialize HTTP connection pool
        self.http_pool = HTTPConnectionPool()
        logger.info("HTTP connection pool initialized")
        
        # Initialize database connection pool
        self.db_pool = AsyncDatabasePool(db_path)
        logger.info(f"Database connection pool initialized for {db_path}")
        
        # Initialize performance monitoring
        from tw_stock_agent.utils.performance_monitor import get_global_monitor
        self.performance_monitor = get_global_monitor()
        
        # Register pools with performance monitor
        if self.http_pool and self.performance_monitor:
            self.performance_monitor.register_http_pool(self.http_pool.get_metrics)
        
        if self.db_pool and self.performance_monitor:
            self.performance_monitor.register_db_pool(self.db_pool.get_metrics)
        
        # Start performance monitoring
        await self.performance_monitor.start_monitoring()
        logger.info("Performance monitoring started")
        
        # Warm up HTTP connections to common endpoints
        if self.http_pool:
            warmup_urls = [
                "https://www.twse.com.tw",
                "https://isin.twse.com.tw",
                "https://www.tpex.org.tw",
            ]
            await self.http_pool.warm_up(warmup_urls)
        
        self._initialized = True
        logger.info("Connection pools initialization completed")
    
    async def health_check(self) -> Dict[str, bool]:
        """Perform health check on all connection pools"""
        results = {}
        
        if self.http_pool:
            results['http_pool'] = await self.http_pool.health_check()
        
        if self.db_pool:
            results['db_pool'] = await self.db_pool.health_check()
        
        return results
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get performance summary from all pools"""
        if self.performance_monitor:
            return self.performance_monitor.get_performance_summary()
        return {"status": "monitoring_disabled"}
    
    async def close(self) -> None:
        """Close all connection pools"""
        if not self._initialized:
            return
        
        logger.info("Closing connection pools...")
        
        # Stop performance monitoring
        if self.performance_monitor:
            await self.performance_monitor.stop_monitoring()
        
        # Close HTTP pool
        if self.http_pool:
            await self.http_pool.close()
            logger.info("HTTP connection pool closed")
        
        # Close database pool
        if self.db_pool:
            await self.db_pool.close()
            logger.info("Database connection pool closed")
        
        # Close global pools
        await close_global_pool()
        await stop_global_monitoring()
        
        self._initialized = False
        logger.info("All connection pools closed")


# Global instances
_lifecycle_manager: Optional[LifecycleManager] = None
_pool_manager: Optional[ConnectionPoolManager] = None


def get_lifecycle_manager() -> LifecycleManager:
    """Get or create the global lifecycle manager"""
    global _lifecycle_manager
    if _lifecycle_manager is None:
        _lifecycle_manager = LifecycleManager()
    return _lifecycle_manager


def get_pool_manager() -> ConnectionPoolManager:
    """Get or create the global connection pool manager"""
    global _pool_manager
    if _pool_manager is None:
        _pool_manager = ConnectionPoolManager()
    return _pool_manager


@asynccontextmanager
async def application_lifespan(db_path: str) -> AsyncIterator[ConnectionPoolManager]:
    """Complete application lifespan context manager"""
    lifecycle = get_lifecycle_manager()
    pool_manager = get_pool_manager()
    
    # Register pool manager cleanup with lifecycle manager
    lifecycle.add_async_shutdown_hook(pool_manager.close)
    
    async with lifecycle.lifespan():
        # Initialize connection pools
        await pool_manager.initialize(db_path)
        yield pool_manager


# Convenience functions for common lifecycle operations
async def initialize_application(db_path: str) -> ConnectionPoolManager:
    """Initialize the application with all connection pools"""
    pool_manager = get_pool_manager()
    await pool_manager.initialize(db_path)
    return pool_manager


async def shutdown_application() -> None:
    """Gracefully shutdown the application"""
    lifecycle = get_lifecycle_manager()
    await lifecycle.shutdown()


def setup_signal_handlers() -> None:
    """Setup signal handlers for graceful shutdown"""
    get_lifecycle_manager()  # This will register signal handlers