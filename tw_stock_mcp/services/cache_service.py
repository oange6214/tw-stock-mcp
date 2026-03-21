import asyncio
import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from queue import Queue
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

from tw_stock_mcp.utils.database_pool import DatabasePool, DatabasePoolConfig

logger = logging.getLogger("tw-stock-agent.cache_service")

@dataclass
class CacheStats:
    """快取統計資料"""
    hits: int = 0
    misses: int = 0
    sets: int = 0
    deletes: int = 0
    cleanups: int = 0
    total_size: int = 0
    
    @property
    def hit_rate(self) -> float:
        """計算命中率"""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0


@dataclass
class CacheConfig:
    """快取配置"""
    max_connections: int = 10
    timeout: float = 30.0
    journal_mode: str = "WAL"
    synchronous: str = "NORMAL"
    cache_size: int = -64000  # 64MB
    temp_store: str = "MEMORY"
    mmap_size: int = 268435456  # 256MB
    auto_vacuum: str = "INCREMENTAL"
    cleanup_interval: int = 3600  # 1 hour
    max_cache_size: int = 1000000  # 1M entries
    backup_interval: int = 86400  # 24 hours
    
    # Enhanced connection pool settings
    min_connections: int = 2
    connection_timeout: float = 30.0
    idle_timeout: float = 300.0
    max_lifetime: float = 3600.0
    checkout_timeout: float = 30.0
    pool_recycle: int = 3600
    pool_pre_ping: bool = True
    use_optimized_pool: bool = True  # Enable optimized connection pool


class CacheService:
    """生產級快取服務，提供高性能、thread-safe的資料快取功能"""
    
    def __init__(self, config: Optional[CacheConfig] = None):
        """初始化快取服務
        
        Args:
            config: 快取配置，None時使用預設配置
        """
        self.config = config or CacheConfig()
        self.stats = CacheStats()
        self._stats_lock = threading.RLock()
        
        # 確保快取目錄存在
        self.cache_dir = os.path.join(os.path.expanduser("~"), ".tw_stock_mcp", "cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # 初始化SQLite資料庫
        self.db_path = os.path.join(self.cache_dir, "cache.db")
        
        # 無論使用哪種連線池，都先執行 schema 初始化與 migration
        self._init_db()

        # Choose connection pool implementation
        self._optimized_pool: Optional[DatabasePool] = None
        if self.config.use_optimized_pool:
            # Use optimized database pool
            pool_config = DatabasePoolConfig(
                max_connections=self.config.max_connections,
                min_connections=self.config.min_connections,
                connection_timeout=self.config.connection_timeout,
                idle_timeout=self.config.idle_timeout,
                max_lifetime=self.config.max_lifetime,
                checkout_timeout=self.config.checkout_timeout,
                pool_recycle=self.config.pool_recycle,
                pool_pre_ping=self.config.pool_pre_ping,
            )
            self._optimized_pool = DatabasePool(self.db_path, pool_config)
            logger.info("Using optimized database connection pool")
        else:
            # Use legacy connection pool
            self._connection_pool: Queue[sqlite3.Connection] = Queue(maxsize=self.config.max_connections)
            self._pool_lock = threading.Lock()
            self._pool_initialized = False
            self._init_connection_pool()
        
        # 清理和維護
        self._cleanup_thread: Optional[threading.Thread] = None
        self._stop_cleanup = threading.Event()
        
        # Start cleanup scheduler
        self._start_cleanup_scheduler()
    
    def _init_db(self) -> None:
        """初始化快取資料庫和索引"""
        # Use a direct connection for initialization to avoid circular dependency
        conn = sqlite3.connect(self.db_path, timeout=self.config.timeout)
        try:
            cursor = conn.cursor()
            
            # 檢查是否需要遷移現有表
            cursor.execute("PRAGMA table_info(cache)")
            existing_columns = {row[1] for row in cursor.fetchall()}
            
            if not existing_columns:
                # 新建表
                cursor.execute('''
                    CREATE TABLE cache (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        expire_at INTEGER,
                        created_at INTEGER NOT NULL,
                        access_count INTEGER DEFAULT 0,
                        last_accessed INTEGER,
                        data_type TEXT DEFAULT 'json',
                        compressed INTEGER DEFAULT 0,
                        size_bytes INTEGER DEFAULT 0,
                        tags TEXT  -- JSON array for cache tagging
                    )
                ''')
            else:
                # 遷移現有表（添加新列）
                new_columns = {
                    'access_count': 'INTEGER DEFAULT 0',
                    'last_accessed': 'INTEGER',
                    'data_type': 'TEXT DEFAULT "json"',
                    'compressed': 'INTEGER DEFAULT 0',
                    'size_bytes': 'INTEGER DEFAULT 0',
                    'tags': 'TEXT'
                }
                
                for col_name, col_type in new_columns.items():
                    if col_name not in existing_columns:
                        try:
                            cursor.execute(f"ALTER TABLE cache ADD COLUMN {col_name} {col_type}")
                            logger.info(f"添加新列: {col_name}")
                        except sqlite3.OperationalError as e:
                            logger.warning(f"添加列 {col_name} 失敗: {e}")
                
                # 確保created_at列存在且不為NULL
                if 'created_at' not in existing_columns:
                    try:
                        cursor.execute("ALTER TABLE cache ADD COLUMN created_at INTEGER NOT NULL DEFAULT 0")
                        # 更新現有記錄的created_at
                        cursor.execute("UPDATE cache SET created_at = ? WHERE created_at = 0", (int(time.time()),))
                    except sqlite3.OperationalError as e:
                        logger.warning(f"處理created_at列失敗: {e}")
            
            # 建立索引以提升性能（檢查列是否存在）
            cursor.execute("PRAGMA table_info(cache)")
            final_columns = {row[1] for row in cursor.fetchall()}
            
            index_definitions = [
                ("idx_cache_expire_at", "expire_at"),
                ("idx_cache_created_at", "created_at"),
                ("idx_cache_last_accessed", "last_accessed"),
                ("idx_cache_data_type", "data_type"),
                ("idx_cache_tags", "tags"),
            ]
            
            for index_name, column_name in index_definitions:
                if column_name in final_columns:
                    try:
                        cursor.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON cache({column_name})")
                    except sqlite3.OperationalError as e:
                        logger.warning(f"建立索引 {index_name} 失敗: {e}")
            
            # 建立統計表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS cache_stats (
                    id INTEGER PRIMARY KEY,
                    timestamp INTEGER NOT NULL,
                    operation TEXT NOT NULL,
                    key_pattern TEXT,
                    execution_time_ms REAL,
                    cache_size INTEGER,
                    memory_usage INTEGER
                )
            ''')
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_stats_timestamp ON cache_stats(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_stats_operation ON cache_stats(operation)")
            
            # 配置SQLite性能參數
            pragma_settings = [
                f"PRAGMA journal_mode = {self.config.journal_mode}",
                f"PRAGMA synchronous = {self.config.synchronous}",
                f"PRAGMA cache_size = {self.config.cache_size}",
                f"PRAGMA temp_store = {self.config.temp_store}",
                f"PRAGMA mmap_size = {self.config.mmap_size}",
                f"PRAGMA auto_vacuum = {self.config.auto_vacuum}",
                "PRAGMA foreign_keys = ON",
                "PRAGMA optimize",
            ]
            
            for pragma in pragma_settings:
                cursor.execute(pragma)
            
            conn.commit()
            logger.info("快取資料庫初始化完成")
        finally:
            conn.close()
    
    def _init_connection_pool(self) -> None:
        """初始化連線池"""
        with self._pool_lock:
            if self._pool_initialized:
                return
                
            for _ in range(self.config.max_connections):
                conn = sqlite3.connect(
                    self.db_path,
                    timeout=self.config.timeout,
                    check_same_thread=False
                )
                conn.row_factory = sqlite3.Row
                self._connection_pool.put(conn)
            
            self._pool_initialized = True
            logger.info(f"連線池初始化完成，大小: {self.config.max_connections}")
    
    @contextmanager
    def _get_connection(self) -> Iterator[sqlite3.Connection]:
        """從連線池獲取連線，使用context manager管理"""
        if self._optimized_pool:
            # Use optimized database pool
            with self._optimized_pool.get_connection() as pooled_conn:
                yield pooled_conn.connection
        else:
            # Use legacy connection pool
            if not self._pool_initialized:
                self._init_connection_pool()
                
            conn = None
            try:
                conn = self._connection_pool.get(timeout=self.config.timeout)
                yield conn
            except Exception as e:
                logger.error(f"資料庫連線出錯: {e}")
                raise
            finally:
                if conn is not None:
                    try:
                        self._connection_pool.put(conn, timeout=1.0)
                    except:
                        # If pool is full or having issues, close the connection
                        try:
                            conn.close()
                        except:
                            pass
    
    def _start_cleanup_scheduler(self) -> None:
        """啟動清理調度器"""
        if self._cleanup_thread is None or not self._cleanup_thread.is_alive():
            self._cleanup_thread = threading.Thread(
                target=self._cleanup_worker,
                daemon=True,
                name="CacheCleanupWorker"
            )
            self._cleanup_thread.start()
            logger.info("快取清理調度器已啟動")
    
    def _cleanup_worker(self) -> None:
        """清理工作執行緒"""
        while not self._stop_cleanup.wait(self.config.cleanup_interval):
            try:
                self.cleanup_expired()
                self._vacuum_database()
                self._cleanup_stats()
                self._update_cache_stats()
            except Exception as e:
                logger.error(f"快取清理工作出錯: {e}")
    
    def _record_stat(self, operation: str, key_pattern: str = None, 
                    execution_time_ms: float = None) -> None:
        """記錄統計資料"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO cache_stats (timestamp, operation, key_pattern, execution_time_ms) VALUES (?, ?, ?, ?)",
                    (int(time.time()), operation, key_pattern, execution_time_ms)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"記錄統計出錯: {e}")
    
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """
        從快取取得資料
        
        Args:
            key: 快取鍵
            
        Returns:
            快取的資料，若不存在或已過期則返回None
        """
        start_time = time.time()
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 查詢快取資料
                cursor.execute(
                    "SELECT value, expire_at, data_type FROM cache WHERE key = ?", 
                    (key,)
                )
                result = cursor.fetchone()
                
                if result:
                    value, expire_at, data_type = result
                    current_time = int(time.time())
                    
                    # 檢查是否過期
                    if expire_at is None or expire_at > current_time:
                        # 更新存取記錄
                        cursor.execute(
                            "UPDATE cache SET access_count = access_count + 1, last_accessed = ? WHERE key = ?",
                            (current_time, key)
                        )
                        conn.commit()
                        
                        # 更新統計
                        with self._stats_lock:
                            self.stats.hits += 1
                        
                        try:
                            return json.loads(value)
                        except json.JSONDecodeError:
                            logger.error(f"快取資料 {key} 解析失敗")
                    else:
                        # 移除過期資料
                        self.delete(key)
                        logger.debug(f"快取資料 {key} 已過期")
                
                # 更新統計
                with self._stats_lock:
                    self.stats.misses += 1
                
                return None
        
        except Exception as e:
            logger.error(f"取得快取資料 {key} 時出錯: {e!s}")
            with self._stats_lock:
                self.stats.misses += 1
            return None
        finally:
            execution_time = (time.time() - start_time) * 1000
            self._record_stat("get", key, execution_time)
    
    def set(self, key: str, value: Dict[str, Any], expire: Optional[int] = None, 
           tags: Optional[List[str]] = None) -> bool:
        """
        設定快取資料
        
        Args:
            key: 快取鍵
            value: 要快取的資料
            expire: 過期秒數，None表示永不過期
            tags: 快取標籤，用於分組管理
            
        Returns:
            是否成功設定
        """
        start_time = time.time()
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 將資料轉換為JSON字串
                value_str = json.dumps(value, ensure_ascii=False)
                current_time = int(time.time())
                expire_at = current_time + expire if expire is not None else None
                tags_str = json.dumps(tags) if tags else None
                size_bytes = len(value_str.encode('utf-8'))
                
                # 檢查快取大小限制
                if self._should_evict():
                    self._evict_lru_entries()
                
                # 新增或更新快取資料
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO cache 
                    (key, value, expire_at, created_at, last_accessed, data_type, size_bytes, tags)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (key, value_str, expire_at, current_time, current_time, 'json', size_bytes, tags_str)
                )
                
                conn.commit()
                
                # 更新統計
                with self._stats_lock:
                    self.stats.sets += 1
                    
                logger.debug(f"成功設定快取資料 {key}")
                return True
                
        except Exception as e:
            logger.error(f"設定快取資料 {key} 時出錯: {e!s}")
            return False
        finally:
            execution_time = (time.time() - start_time) * 1000
            self._record_stat("set", key, execution_time)
    
    def delete(self, key: str) -> bool:
        """
        刪除快取資料
        
        Args:
            key: 快取鍵
            
        Returns:
            是否成功刪除
        """
        start_time = time.time()
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("DELETE FROM cache WHERE key = ?", (key,))
                conn.commit()
                
                success = cursor.rowcount > 0
                if success:
                    with self._stats_lock:
                        self.stats.deletes += 1
                
                return success
        
        except Exception as e:
            logger.error(f"刪除快取資料 {key} 時出錯: {e!s}")
            return False
        finally:
            execution_time = (time.time() - start_time) * 1000
            self._record_stat("delete", key, execution_time)
    
    def cleanup_expired(self) -> int:
        """
        清理過期的快取資料
        
        Returns:
            清理的資料數量
        """
        start_time = time.time()
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                current_time = int(time.time())
                cursor.execute(
                    "DELETE FROM cache WHERE expire_at IS NOT NULL AND expire_at < ?", 
                    (current_time,)
                )
                
                conn.commit()
                cleaned = cursor.rowcount
                
                with self._stats_lock:
                    self.stats.cleanups += cleaned
                
                if cleaned > 0:
                    logger.info(f"清理了 {cleaned} 條過期快取資料")
                
                return cleaned
        
        except Exception as e:
            logger.error(f"清理過期快取資料時出錯: {e!s}")
            return 0
        finally:
            execution_time = (time.time() - start_time) * 1000
            self._record_stat("cleanup_expired", None, execution_time)
    
    # Backward compatibility alias
    def clear_expired(self) -> int:
        """向後相容的方法名稱"""
        return self.cleanup_expired()
    
    def _should_evict(self) -> bool:
        """檢查是否需要清理快取"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM cache")
                count = cursor.fetchone()[0]
                return count >= self.config.max_cache_size
        except Exception:
            return False
    
    def _evict_lru_entries(self, count: int = 100) -> int:
        """清理最少使用的快取項目"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    DELETE FROM cache WHERE key IN (
                        SELECT key FROM cache 
                        ORDER BY last_accessed ASC, access_count ASC 
                        LIMIT ?
                    )
                    """,
                    (count,)
                )
                conn.commit()
                evicted = cursor.rowcount
                logger.info(f"清理了 {evicted} 條LRU快取項目")
                return evicted
        except Exception as e:
            logger.error(f"LRU清理出錯: {e}")
            return 0
    
    def _vacuum_database(self) -> None:
        """壓縮資料庫"""
        try:
            with self._get_connection() as conn:
                conn.execute("PRAGMA incremental_vacuum")
                conn.commit()
        except Exception as e:
            logger.error(f"資料庫壓縮出錯: {e}")
    
    def _cleanup_stats(self, days: int = 7) -> None:
        """清理舊的統計資料"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cutoff_time = int(time.time()) - (days * 86400)
                cursor.execute(
                    "DELETE FROM cache_stats WHERE timestamp < ?",
                    (cutoff_time,)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"清理統計資料出錯: {e}")
    
    def _update_cache_stats(self) -> None:
        """更新快取統計"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*), SUM(size_bytes) FROM cache")
                count, total_size = cursor.fetchone()
                
                with self._stats_lock:
                    self.stats.total_size = total_size or 0
        except Exception as e:
            logger.error(f"更新統計出錯: {e}")
    
    def get_stats(self) -> CacheStats:
        """獲取快取統計資料"""
        with self._stats_lock:
            # 更新即時統計
            self._update_cache_stats()
            return CacheStats(
                hits=self.stats.hits,
                misses=self.stats.misses,
                sets=self.stats.sets,
                deletes=self.stats.deletes,
                cleanups=self.stats.cleanups,
                total_size=self.stats.total_size
            )
    
    def get_pool_metrics(self) -> Optional[Dict[str, Any]]:
        """獲取連線池指標"""
        if self._optimized_pool:
            db_metrics = self._optimized_pool.get_metrics()
            return {
                "pool_type": "optimized",
                "total_connections": db_metrics.total_connections,
                "active_connections": db_metrics.active_connections,
                "idle_connections": db_metrics.idle_connections,
                "total_queries": db_metrics.total_queries,
                "successful_queries": db_metrics.successful_queries,
                "failed_queries": db_metrics.failed_queries,
                "query_success_rate": db_metrics.query_success_rate,
                "average_query_time": db_metrics.average_query_time,
                "average_checkout_time": db_metrics.average_checkout_time,
                "pool_overflows": db_metrics.pool_overflows,
                "connection_errors": db_metrics.connection_errors,
            }
        else:
            return {
                "pool_type": "legacy",
                "max_connections": self.config.max_connections,
                "pool_size": self._connection_pool.qsize() if hasattr(self, '_connection_pool') else 0,
            }
    
    def get_keys_by_pattern(self, pattern: str) -> List[str]:
        """根據模式獲取快取鍵"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT key FROM cache WHERE key LIKE ?",
                    (pattern,)
                )
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"獲取快取鍵出錯: {e}")
            return []
    
    def get_keys_by_tags(self, tags: List[str]) -> List[str]:
        """根據標籤獲取快取鍵"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # 構建查詢條件
                conditions = []
                params = []
                for tag in tags:
                    conditions.append("tags LIKE ?")
                    params.append(f'%"{tag}"%')
                
                query = f"SELECT key FROM cache WHERE {' OR '.join(conditions)}"
                cursor.execute(query, params)
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"根據標籤獲取快取鍵出錯: {e}")
            return []
    
    def delete_by_pattern(self, pattern: str) -> int:
        """根據模式刪除快取項目"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM cache WHERE key LIKE ?",
                    (pattern,)
                )
                conn.commit()
                deleted = cursor.rowcount
                
                with self._stats_lock:
                    self.stats.deletes += deleted
                
                logger.info(f"根據模式 {pattern} 刪除了 {deleted} 條快取項目")
                return deleted
        except Exception as e:
            logger.error(f"根據模式刪除快取出錯: {e}")
            return 0
    
    def delete_by_tags(self, tags: List[str]) -> int:
        """根據標籤刪除快取項目"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                conditions = []
                params = []
                for tag in tags:
                    conditions.append("tags LIKE ?")
                    params.append(f'%"{tag}"%')
                
                query = f"DELETE FROM cache WHERE {' OR '.join(conditions)}"
                cursor.execute(query, params)
                conn.commit()
                deleted = cursor.rowcount
                
                with self._stats_lock:
                    self.stats.deletes += deleted
                
                logger.info(f"根據標籤刪除了 {deleted} 條快取項目")
                return deleted
        except Exception as e:
            logger.error(f"根據標籤刪除快取出錯: {e}")
            return 0
    
    def set_bulk(self, items: List[Tuple[str, Dict[str, Any], Optional[int], Optional[List[str]]]]) -> int:
        """批量設置快取項目
        
        Args:
            items: 項目列表，每個項目包含 (key, value, expire, tags)
            
        Returns:
            成功設置的項目數量
        """
        if not items:
            return 0
            
        start_time = time.time()
        success_count = 0
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                current_time = int(time.time())
                
                # 檢查快取大小限制
                if self._should_evict():
                    self._evict_lru_entries(len(items))
                
                for key, value, expire, tags in items:
                    try:
                        value_str = json.dumps(value, ensure_ascii=False)
                        expire_at = current_time + expire if expire is not None else None
                        tags_str = json.dumps(tags) if tags else None
                        size_bytes = len(value_str.encode('utf-8'))
                        
                        cursor.execute(
                            """
                            INSERT OR REPLACE INTO cache 
                            (key, value, expire_at, created_at, last_accessed, data_type, size_bytes, tags)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (key, value_str, expire_at, current_time, current_time, 'json', size_bytes, tags_str)
                        )
                        success_count += 1
                    except Exception as e:
                        logger.error(f"批量設置快取項目 {key} 出錯: {e}")
                
                conn.commit()
                
                with self._stats_lock:
                    self.stats.sets += success_count
                
                logger.info(f"批量設置 {success_count}/{len(items)} 個快取項目")
                return success_count
                
        except Exception as e:
            logger.error(f"批量設置快取出錯: {e}")
            return success_count
        finally:
            execution_time = (time.time() - start_time) * 1000
            self._record_stat("set_bulk", f"count:{len(items)}", execution_time)
    
    def get_bulk(self, keys: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        """批量獲取快取項目"""
        if not keys:
            return {}
            
        start_time = time.time()
        result = {}
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 使用 IN 查詢批量獲取
                placeholders = ','.join('?' for _ in keys)
                cursor.execute(
                    f"SELECT key, value, expire_at, data_type FROM cache WHERE key IN ({placeholders})",
                    keys
                )
                
                current_time = int(time.time())
                found_keys = set()
                expired_keys = []
                
                for row in cursor.fetchall():
                    key, value, expire_at, data_type = row
                    found_keys.add(key)
                    
                    if expire_at is None or expire_at > current_time:
                        try:
                            result[key] = json.loads(value)
                            # 更新存取記錄
                            cursor.execute(
                                "UPDATE cache SET access_count = access_count + 1, last_accessed = ? WHERE key = ?",
                                (current_time, key)
                            )
                        except json.JSONDecodeError:
                            logger.error(f"快取資料 {key} 解析失敗")
                            result[key] = None
                    else:
                        expired_keys.append(key)
                        result[key] = None
                
                # 刪除過期項目
                if expired_keys:
                    placeholders = ','.join('?' for _ in expired_keys)
                    cursor.execute(f"DELETE FROM cache WHERE key IN ({placeholders})", expired_keys)
                
                conn.commit()
                
                # 補充未找到的鍵
                for key in keys:
                    if key not in found_keys:
                        result[key] = None
                
                # 更新統計
                hits = len([k for k, v in result.items() if v is not None])
                misses = len(keys) - hits
                
                with self._stats_lock:
                    self.stats.hits += hits
                    self.stats.misses += misses
                
                return result
                
        except Exception as e:
            logger.error(f"批量獲取快取出錯: {e}")
            return {key: None for key in keys}
        finally:
            execution_time = (time.time() - start_time) * 1000
            self._record_stat("get_bulk", f"count:{len(keys)}", execution_time)
    
    def warm_cache(self, key_value_pairs: Dict[str, Dict[str, Any]], 
                   default_expire: Optional[int] = None) -> int:
        """快取預熱"""
        items = [
            (key, value, default_expire, None) 
            for key, value in key_value_pairs.items()
        ]
        return self.set_bulk(items)
    
    def backup_cache(self, backup_path: str) -> bool:
        """備份快取資料庫"""
        try:
            # 確保備份目錄存在
            os.makedirs(os.path.dirname(backup_path), exist_ok=True)
            
            with self._get_connection() as conn:
                backup_conn = sqlite3.connect(backup_path)
                conn.backup(backup_conn)
                backup_conn.close()
            
            logger.info(f"快取資料庫備份至: {backup_path}")
            return True
        except Exception as e:
            logger.error(f"快取備份出錯: {e}")
            return False
    
    def restore_cache(self, backup_path: str) -> bool:
        """還原快取資料庫"""
        try:
            if not os.path.exists(backup_path):
                logger.error(f"備份檔案不存在: {backup_path}")
                return False
            
            # 停止清理工作
            self._stop_cleanup.set()
            if self._cleanup_thread:
                self._cleanup_thread.join()
            
            # 關閉所有連線
            while not self._connection_pool.empty():
                conn = self._connection_pool.get()
                conn.close()
            
            # 複製備份檔案
            import shutil
            shutil.copy2(backup_path, self.db_path)
            
            # 重新初始化
            self._pool_initialized = False
            self._stop_cleanup.clear()
            self._init_connection_pool()
            self._start_cleanup_scheduler()
            
            logger.info(f"從備份還原快取資料庫: {backup_path}")
            return True
        except Exception as e:
            logger.error(f"快取還原出錯: {e}")
            return False
    
    def close(self) -> None:
        """關閉快取服務"""
        logger.info("正在關閉快取服務...")
        
        # 停止清理工作
        self._stop_cleanup.set()
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5)
        
        # 關閉連線池
        if self._optimized_pool:
            # Close optimized pool
            self._optimized_pool.close()
        else:
            # Close legacy connection pool
            while not self._connection_pool.empty():
                try:
                    conn = self._connection_pool.get_nowait()
                    conn.close()
                except:
                    break
        
        logger.info("快取服務已關閉")
    
    def __enter__(self):
        """Context manager 支援"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager 支援"""
        self.close()