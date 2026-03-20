"""Configuration utility for managing application settings."""
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to this file's location (project root), not CWD
_ENV_FILE = str(Path(__file__).parent.parent.parent / ".env")


@dataclass
class ConnectionPoolConfig:
    """HTTP connection pool configuration"""
    max_connections: int = 100  # Maximum total connections
    max_connections_per_host: int = 30  # Maximum connections per host
    connection_timeout: float = 30.0  # Connection timeout in seconds
    read_timeout: float = 60.0  # Read timeout in seconds
    keepalive_timeout: float = 30.0  # Keep-alive timeout
    limit_per_host: int = 10  # Concurrent requests per host
    total_timeout: float = 300.0  # Total request timeout
    retry_attempts: int = 3  # Retry attempts for failed requests
    retry_delay: float = 1.0  # Initial retry delay
    enable_compression: bool = True  # Enable gzip compression
    enable_cookies: bool = False  # Enable cookie jar
    trust_env: bool = True  # Trust environment proxy settings


@dataclass
class DatabasePoolConfig:
    """Database connection pool configuration"""
    max_connections: int = 20  # Maximum database connections
    min_connections: int = 5  # Minimum database connections
    connection_timeout: float = 30.0  # Connection timeout
    idle_timeout: float = 300.0  # Idle connection timeout
    max_lifetime: float = 3600.0  # Maximum connection lifetime
    checkout_timeout: float = 30.0  # Connection checkout timeout
    pool_recycle: int = 3600  # Recycle connections after seconds
    pool_pre_ping: bool = True  # Ping connections before use
    enable_wal_mode: bool = True  # Enable WAL mode for SQLite
    enable_foreign_keys: bool = True  # Enable foreign key constraints


class Settings(BaseSettings):
    """應用程式設定"""
    
    # API 設定
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8000
    API_WORKERS: int = 1
    
    # 快取設定
    CACHE_TTL_STOCK_DATA: int = 86400  # 24小時
    CACHE_TTL_PRICE_DATA: int = 1800   # 30分鐘
    CACHE_TTL_REALTIME: int = 60       # 1分鐘
    CACHE_TTL_BEST_FOUR_POINTS: int = 3600  # 1小時
    
    # 速率限制設定
    RATE_LIMIT_REQUESTS: int = 3
    RATE_LIMIT_PERIOD: int = 5  # 秒
    
    # 日誌設定
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # HTTP Connection Pool 設定
    HTTP_MAX_CONNECTIONS: int = 100
    HTTP_MAX_CONNECTIONS_PER_HOST: int = 30
    HTTP_CONNECTION_TIMEOUT: float = 30.0
    HTTP_READ_TIMEOUT: float = 60.0
    HTTP_KEEPALIVE_TIMEOUT: float = 30.0
    HTTP_LIMIT_PER_HOST: int = 10
    HTTP_TOTAL_TIMEOUT: float = 300.0
    HTTP_RETRY_ATTEMPTS: int = 3
    HTTP_RETRY_DELAY: float = 1.0
    HTTP_ENABLE_COMPRESSION: bool = True
    
    # Database Connection Pool 設定
    DB_MAX_CONNECTIONS: int = 20
    DB_MIN_CONNECTIONS: int = 5
    DB_CONNECTION_TIMEOUT: float = 30.0
    DB_IDLE_TIMEOUT: float = 300.0
    DB_MAX_LIFETIME: float = 3600.0
    DB_CHECKOUT_TIMEOUT: float = 30.0
    DB_POOL_RECYCLE: int = 3600
    DB_POOL_PRE_PING: bool = True
    
    # Performance Monitoring 設定
    ENABLE_METRICS: bool = True
    METRICS_EXPORT_INTERVAL: int = 60  # seconds
    ENABLE_CONNECTION_MONITORING: bool = True

    # Provider 設定
    STOCK_DATA_PROVIDER: str = "twstock"  # "twstock" | "finmind"
    FINMIND_API_TOKEN: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=True
    )

@lru_cache
def get_settings() -> Settings:
    """獲取應用程式設定"""
    return Settings()

def get_cache_ttl(key: str) -> int:
    """獲取快取過期時間"""
    settings = get_settings()
    ttl_map: dict[str, int] = {
        "stock_data": settings.CACHE_TTL_STOCK_DATA,
        "price_data": settings.CACHE_TTL_PRICE_DATA,
        "realtime": settings.CACHE_TTL_REALTIME,
        "best_four_points": settings.CACHE_TTL_BEST_FOUR_POINTS
    }
    return ttl_map.get(key, 3600)  # 預設1小時

def get_connection_pool_config() -> ConnectionPoolConfig:
    """獲取 HTTP 連線池配置"""
    settings = get_settings()
    return ConnectionPoolConfig(
        max_connections=settings.HTTP_MAX_CONNECTIONS,
        max_connections_per_host=settings.HTTP_MAX_CONNECTIONS_PER_HOST,
        connection_timeout=settings.HTTP_CONNECTION_TIMEOUT,
        read_timeout=settings.HTTP_READ_TIMEOUT,
        keepalive_timeout=settings.HTTP_KEEPALIVE_TIMEOUT,
        limit_per_host=settings.HTTP_LIMIT_PER_HOST,
        total_timeout=settings.HTTP_TOTAL_TIMEOUT,
        retry_attempts=settings.HTTP_RETRY_ATTEMPTS,
        retry_delay=settings.HTTP_RETRY_DELAY,
        enable_compression=settings.HTTP_ENABLE_COMPRESSION,
    )

def get_database_pool_config() -> DatabasePoolConfig:
    """獲取資料庫連線池配置"""
    settings = get_settings()
    return DatabasePoolConfig(
        max_connections=settings.DB_MAX_CONNECTIONS,
        min_connections=settings.DB_MIN_CONNECTIONS,
        connection_timeout=settings.DB_CONNECTION_TIMEOUT,
        idle_timeout=settings.DB_IDLE_TIMEOUT,
        max_lifetime=settings.DB_MAX_LIFETIME,
        checkout_timeout=settings.DB_CHECKOUT_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_pre_ping=settings.DB_POOL_PRE_PING,
    ) 
