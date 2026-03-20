"""Enhanced SQLite database connection pool with performance optimizations."""
import asyncio
import logging
import sqlite3
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue, Empty, Full
from typing import AsyncIterator, Iterator, Optional, Dict, Any, List

from tw_stock_mcp.utils.config import DatabasePoolConfig, get_database_pool_config

logger = logging.getLogger("tw-stock-agent.database_pool")


@dataclass
class DatabaseMetrics:
    """Database connection pool metrics"""
    total_connections: int = 0
    active_connections: int = 0
    idle_connections: int = 0
    total_queries: int = 0
    successful_queries: int = 0
    failed_queries: int = 0
    average_query_time: float = 0.0
    total_checkout_time: float = 0.0
    checkout_count: int = 0
    pool_overflows: int = 0
    connection_errors: int = 0
    last_updated: float = field(default_factory=time.time)
    
    @property
    def query_success_rate(self) -> float:
        """Calculate query success rate"""
        if self.total_queries == 0:
            return 0.0
        return self.successful_queries / self.total_queries
    
    @property
    def average_checkout_time(self) -> float:
        """Calculate average connection checkout time"""
        if self.checkout_count == 0:
            return 0.0
        return self.total_checkout_time / self.checkout_count
    
    def update_query_time(self, query_time: float) -> None:
        """Update average query time"""
        if self.total_queries == 0:
            self.average_query_time = query_time
        else:
            # Simple moving average
            self.average_query_time = (
                (self.average_query_time * (self.total_queries - 1) + query_time) / 
                self.total_queries
            )
        self.last_updated = time.time()


class PooledConnection:
    """Wrapper for pooled database connections with lifecycle tracking"""
    
    def __init__(self, connection: sqlite3.Connection, pool: 'DatabasePool'):
        self.connection = connection
        self.pool = pool
        self.created_at = time.time()
        self.last_used = time.time()
        self.use_count = 0
        self.in_use = False
        self.is_valid = True
    
    def execute(self, sql: str, parameters=None) -> sqlite3.Cursor:
        """Execute SQL with metrics tracking"""
        start_time = time.time()
        try:
            cursor = self.connection.cursor()
            if parameters:
                cursor.execute(sql, parameters)
            else:
                cursor.execute(sql)
            
            query_time = time.time() - start_time
            self.pool._metrics.successful_queries += 1
            self.pool._metrics.update_query_time(query_time)
            self.last_used = time.time()
            self.use_count += 1
            
            return cursor
            
        except Exception as e:
            query_time = time.time() - start_time
            self.pool._metrics.failed_queries += 1
            self.pool._metrics.update_query_time(query_time)
            logger.error(f"Query failed: {e}")
            raise
        finally:
            self.pool._metrics.total_queries += 1
    
    def executemany(self, sql: str, parameters_list) -> sqlite3.Cursor:
        """Execute many SQL statements with metrics tracking"""
        start_time = time.time()
        try:
            cursor = self.connection.cursor()
            cursor.executemany(sql, parameters_list)
            
            query_time = time.time() - start_time
            self.pool._metrics.successful_queries += 1
            self.pool._metrics.update_query_time(query_time)
            self.last_used = time.time()
            self.use_count += 1
            
            return cursor
            
        except Exception as e:
            query_time = time.time() - start_time
            self.pool._metrics.failed_queries += 1
            self.pool._metrics.update_query_time(query_time)
            logger.error(f"Batch query failed: {e}")
            raise
        finally:
            self.pool._metrics.total_queries += 1
    
    def commit(self) -> None:
        """Commit transaction"""
        self.connection.commit()
    
    def rollback(self) -> None:
        """Rollback transaction"""
        self.connection.rollback()
    
    def is_expired(self, max_lifetime: float) -> bool:
        """Check if connection has exceeded maximum lifetime"""
        return (time.time() - self.created_at) > max_lifetime
    
    def is_idle_expired(self, idle_timeout: float) -> bool:
        """Check if connection has been idle too long"""
        return (time.time() - self.last_used) > idle_timeout
    
    def ping(self) -> bool:
        """Test if connection is still valid"""
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            return True
        except Exception as e:
            logger.warning(f"Connection ping failed: {e}")
            self.is_valid = False
            return False
    
    def close(self) -> None:
        """Close the underlying connection"""
        try:
            self.connection.close()
        except Exception as e:
            logger.warning(f"Error closing connection: {e}")
        finally:
            self.is_valid = False


class DatabasePool:
    """Enhanced SQLite connection pool with performance optimizations"""
    
    def __init__(self, db_path: str, config: Optional[DatabasePoolConfig] = None):
        """Initialize the database connection pool
        
        Args:
            db_path: Path to the SQLite database file
            config: Database pool configuration
        """
        self.db_path = Path(db_path)
        self.config = config or get_database_pool_config()
        self._pool: Queue[PooledConnection] = Queue(maxsize=self.config.max_connections)
        self._metrics = DatabaseMetrics()
        self._lock = threading.RLock()
        self._closed = False
        
        # Ensure database directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Maintenance thread
        self._maintenance_thread: Optional[threading.Thread] = None
        self._stop_maintenance = threading.Event()
        
        # Initialize pool with minimum connections
        self._initialize_pool()
        self._start_maintenance()
    
    def _initialize_pool(self) -> None:
        """Initialize the connection pool with minimum connections"""
        with self._lock:
            # Create initial connections
            for _ in range(self.config.min_connections):
                try:
                    conn = self._create_connection()
                    self._pool.put_nowait(conn)
                    self._metrics.total_connections += 1
                    self._metrics.idle_connections += 1
                except Exception as e:
                    logger.error(f"Failed to create initial connection: {e}")
                    self._metrics.connection_errors += 1
        
        logger.info(
            f"Database pool initialized with {self._metrics.total_connections} connections "
            f"(min: {self.config.min_connections}, max: {self.config.max_connections})"
        )
    
    def _create_connection(self) -> PooledConnection:
        """Create a new optimized database connection"""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=self.config.connection_timeout,
            check_same_thread=False,
            isolation_level=None,  # Autocommit mode for better performance
        )
        
        # Set SQLite performance optimizations
        pragmas = [
            "PRAGMA journal_mode = WAL",
            "PRAGMA synchronous = NORMAL",
            "PRAGMA cache_size = -64000",  # 64MB cache
            "PRAGMA temp_store = MEMORY",
            "PRAGMA mmap_size = 268435456",  # 256MB mmap
            "PRAGMA optimize",
        ]
        
        if self.config.enable_foreign_keys:
            pragmas.append("PRAGMA foreign_keys = ON")
        
        cursor = conn.cursor()
        for pragma in pragmas:
            try:
                cursor.execute(pragma)
            except Exception as e:
                logger.warning(f"Failed to execute pragma '{pragma}': {e}")
        
        conn.row_factory = sqlite3.Row  # Enable column access by name
        return PooledConnection(conn, self)
    
    @contextmanager
    def get_connection(self) -> Iterator[PooledConnection]:
        """Get a connection from the pool with automatic return"""
        if self._closed:
            raise RuntimeError("Connection pool is closed")
        
        start_time = time.time()
        conn = None
        
        try:
            # Try to get connection from pool
            try:
                conn = self._pool.get(timeout=self.config.checkout_timeout)
                self._metrics.idle_connections -= 1
                self._metrics.active_connections += 1
            except Empty:
                # Pool is empty, try to create new connection if under limit
                with self._lock:
                    if self._metrics.total_connections < self.config.max_connections:
                        conn = self._create_connection()
                        self._metrics.total_connections += 1
                        self._metrics.active_connections += 1
                    else:
                        self._metrics.pool_overflows += 1
                        raise RuntimeError(
                            f"Connection pool exhausted. "
                            f"Max connections: {self.config.max_connections}"
                        )
            
            # Validate connection
            if self.config.pool_pre_ping and not conn.ping():
                logger.warning("Connection failed ping test, creating new connection")
                conn.close()
                conn = self._create_connection()
            
            conn.in_use = True
            checkout_time = time.time() - start_time
            self._metrics.checkout_count += 1
            self._metrics.total_checkout_time += checkout_time
            
            yield conn
            
        except Exception as e:
            self._metrics.connection_errors += 1
            logger.error(f"Error getting database connection: {e}")
            raise
        finally:
            if conn:
                conn.in_use = False
                self._return_connection(conn)
    
    def _return_connection(self, conn: PooledConnection) -> None:
        """Return a connection to the pool"""
        if conn.is_valid and not self._closed:
            # Check if connection should be recycled
            if (conn.is_expired(self.config.max_lifetime) or 
                conn.use_count > 1000):  # Recycle after 1000 uses
                logger.debug("Recycling connection due to age or usage")
                conn.close()
                with self._lock:
                    self._metrics.total_connections -= 1
                    self._metrics.active_connections -= 1
                # Create replacement if needed
                if self._metrics.total_connections < self.config.min_connections:
                    try:
                        new_conn = self._create_connection()
                        self._pool.put_nowait(new_conn)
                        self._metrics.total_connections += 1
                        self._metrics.idle_connections += 1
                    except Exception as e:
                        logger.error(f"Failed to create replacement connection: {e}")
            else:
                try:
                    self._pool.put_nowait(conn)
                    with self._lock:
                        self._metrics.active_connections -= 1
                        self._metrics.idle_connections += 1
                except Full:
                    # Pool is full, close excess connection
                    conn.close()
                    with self._lock:
                        self._metrics.total_connections -= 1
                        self._metrics.active_connections -= 1
        else:
            # Connection is invalid, close it
            conn.close()
            with self._lock:
                self._metrics.total_connections -= 1
                self._metrics.active_connections -= 1
    
    def _start_maintenance(self) -> None:
        """Start the maintenance thread"""
        if self._maintenance_thread is None or not self._maintenance_thread.is_alive():
            self._maintenance_thread = threading.Thread(
                target=self._maintenance_worker,
                daemon=True,
                name="DatabasePoolMaintenance"
            )
            self._maintenance_thread.start()
            logger.info("Database pool maintenance thread started")
    
    def _maintenance_worker(self) -> None:
        """Background maintenance worker"""
        while not self._stop_maintenance.wait(30):  # Run every 30 seconds
            try:
                self._cleanup_expired_connections()
                self._maintain_minimum_connections()
            except Exception as e:
                logger.error(f"Database pool maintenance error: {e}")
    
    def _cleanup_expired_connections(self) -> None:
        """Clean up expired and idle connections"""
        expired_connections = []
        
        # Collect expired connections
        while True:
            try:
                conn = self._pool.get_nowait()
                if (conn.is_idle_expired(self.config.idle_timeout) or 
                    conn.is_expired(self.config.max_lifetime) or
                    not conn.is_valid):
                    expired_connections.append(conn)
                else:
                    # Put valid connection back
                    self._pool.put_nowait(conn)
                    break
            except Empty:
                break
        
        # Close expired connections
        for conn in expired_connections:
            conn.close()
            with self._lock:
                self._metrics.total_connections -= 1
                self._metrics.idle_connections -= 1
        
        if expired_connections:
            logger.debug(f"Cleaned up {len(expired_connections)} expired connections")
    
    def _maintain_minimum_connections(self) -> None:
        """Ensure minimum number of connections in pool"""
        with self._lock:
            current_idle = self._metrics.idle_connections
            needed = max(0, self.config.min_connections - current_idle)
            
            for _ in range(needed):
                try:
                    conn = self._create_connection()
                    self._pool.put_nowait(conn)
                    self._metrics.total_connections += 1
                    self._metrics.idle_connections += 1
                except Exception as e:
                    logger.error(f"Failed to maintain minimum connections: {e}")
                    break
    
    def execute_query(self, sql: str, parameters=None) -> List[sqlite3.Row]:
        """Execute a query and return all results"""
        with self.get_connection() as conn:
            cursor = conn.execute(sql, parameters)
            return cursor.fetchall()
    
    def execute_one(self, sql: str, parameters=None) -> Optional[sqlite3.Row]:
        """Execute a query and return one result"""
        with self.get_connection() as conn:
            cursor = conn.execute(sql, parameters)
            return cursor.fetchone()
    
    def execute_scalar(self, sql: str, parameters=None) -> Any:
        """Execute a query and return scalar value"""
        with self.get_connection() as conn:
            cursor = conn.execute(sql, parameters)
            row = cursor.fetchone()
            return row[0] if row else None
    
    def execute_modify(self, sql: str, parameters=None) -> int:
        """Execute a modification query and return affected rows"""
        with self.get_connection() as conn:
            cursor = conn.execute(sql, parameters)
            conn.commit()
            return cursor.rowcount
    
    def execute_batch(self, sql: str, parameters_list) -> int:
        """Execute a batch of queries and return total affected rows"""
        with self.get_connection() as conn:
            cursor = conn.executemany(sql, parameters_list)
            conn.commit()
            return cursor.rowcount
    
    def get_metrics(self) -> DatabaseMetrics:
        """Get current database pool metrics"""
        with self._lock:
            self._metrics.last_updated = time.time()
            return self._metrics
    
    def reset_metrics(self) -> None:
        """Reset database pool metrics"""
        with self._lock:
            # Preserve connection counts
            total_conns = self._metrics.total_connections
            active_conns = self._metrics.active_connections
            idle_conns = self._metrics.idle_connections
            
            self._metrics = DatabaseMetrics()
            self._metrics.total_connections = total_conns
            self._metrics.active_connections = active_conns
            self._metrics.idle_connections = idle_conns
    
    def health_check(self) -> bool:
        """Perform a health check on the database pool"""
        try:
            result = self.execute_scalar("SELECT 1")
            return result == 1
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False
    
    def close(self) -> None:
        """Close the database pool and all connections"""
        if self._closed:
            return
        
        self._closed = True
        
        # Stop maintenance thread
        self._stop_maintenance.set()
        if self._maintenance_thread and self._maintenance_thread.is_alive():
            self._maintenance_thread.join(timeout=5)
        
        # Close all connections
        with self._lock:
            while True:
                try:
                    conn = self._pool.get_nowait()
                    conn.close()
                    self._metrics.total_connections -= 1
                except Empty:
                    break
        
        logger.info("Database pool closed")
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()


# Async wrapper for database pool
class AsyncDatabasePool:
    """Async wrapper for the database pool"""
    
    def __init__(self, db_path: str, config: Optional[DatabasePoolConfig] = None):
        self._pool = DatabasePool(db_path, config)
        self._executor = asyncio.get_event_loop().run_in_executor
    
    @asynccontextmanager
    async def get_connection(self) -> AsyncIterator[PooledConnection]:
        """Async context manager for database connections"""
        def _get_connection():
            return self._pool.get_connection()
        
        context_manager = await asyncio.get_event_loop().run_in_executor(
            None, _get_connection
        )
        
        async with asyncio.Lock():
            with context_manager as conn:
                yield conn
    
    async def execute_query(self, sql: str, parameters=None) -> List[sqlite3.Row]:
        """Async execute query"""
        return await asyncio.get_event_loop().run_in_executor(
            None, self._pool.execute_query, sql, parameters
        )
    
    async def execute_one(self, sql: str, parameters=None) -> Optional[sqlite3.Row]:
        """Async execute one"""
        return await asyncio.get_event_loop().run_in_executor(
            None, self._pool.execute_one, sql, parameters
        )
    
    async def execute_scalar(self, sql: str, parameters=None) -> Any:
        """Async execute scalar"""
        return await asyncio.get_event_loop().run_in_executor(
            None, self._pool.execute_scalar, sql, parameters
        )
    
    async def execute_modify(self, sql: str, parameters=None) -> int:
        """Async execute modify"""
        return await asyncio.get_event_loop().run_in_executor(
            None, self._pool.execute_modify, sql, parameters
        )
    
    async def execute_batch(self, sql: str, parameters_list) -> int:
        """Async execute batch"""
        return await asyncio.get_event_loop().run_in_executor(
            None, self._pool.execute_batch, sql, parameters_list
        )
    
    def get_metrics(self) -> DatabaseMetrics:
        """Get database pool metrics"""
        return self._pool.get_metrics()
    
    async def health_check(self) -> bool:
        """Async health check"""
        return await asyncio.get_event_loop().run_in_executor(
            None, self._pool.health_check
        )
    
    async def close(self) -> None:
        """Close the async database pool"""
        await asyncio.get_event_loop().run_in_executor(None, self._pool.close)
    
    async def __aenter__(self):
        """Async context manager entry"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()