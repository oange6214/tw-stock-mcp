"""Performance monitoring and metrics collection for connection pools."""
import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable

from tw_stock_mcp.utils.config import get_settings
from tw_stock_mcp.utils.connection_pool import ConnectionMetrics
from tw_stock_mcp.utils.database_pool import DatabaseMetrics

logger = logging.getLogger("tw-stock-agent.performance_monitor")


@dataclass
class SystemMetrics:
    """System-wide performance metrics"""
    timestamp: float
    http_pool_metrics: Optional[ConnectionMetrics] = None
    db_pool_metrics: Optional[DatabaseMetrics] = None
    memory_usage_mb: float = 0.0
    cpu_usage_percent: float = 0.0
    active_tasks: int = 0
    total_requests_per_minute: int = 0
    error_rate_percent: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary for serialization"""
        data = asdict(self)
        # Convert dataclass instances to dicts
        if self.http_pool_metrics:
            data['http_pool_metrics'] = asdict(self.http_pool_metrics)
        if self.db_pool_metrics:
            data['db_pool_metrics'] = asdict(self.db_pool_metrics)
        return data


class PerformanceCollector:
    """Collects performance metrics from various components"""
    
    def __init__(self):
        self._http_pool_provider: Optional[Callable[[], ConnectionMetrics]] = None
        self._db_pool_provider: Optional[Callable[[], DatabaseMetrics]] = None
        self._request_history: List[float] = []  # Track request timestamps
        self._error_history: List[float] = []    # Track error timestamps
        self._history_window = 300  # 5 minutes
    
    def register_http_pool_provider(self, provider: Callable[[], ConnectionMetrics]) -> None:
        """Register HTTP pool metrics provider"""
        self._http_pool_provider = provider
        logger.debug("HTTP pool metrics provider registered")
    
    def register_db_pool_provider(self, provider: Callable[[], DatabaseMetrics]) -> None:
        """Register database pool metrics provider"""
        self._db_pool_provider = provider
        logger.debug("Database pool metrics provider registered")
    
    def record_request(self) -> None:
        """Record a request for rate tracking"""
        current_time = time.time()
        self._request_history.append(current_time)
        # Clean old entries
        cutoff = current_time - self._history_window
        self._request_history = [t for t in self._request_history if t > cutoff]
    
    def record_error(self) -> None:
        """Record an error for error rate tracking"""
        current_time = time.time()
        self._error_history.append(current_time)
        # Clean old entries
        cutoff = current_time - self._history_window
        self._error_history = [t for t in self._error_history if t > cutoff]
    
    def _get_system_stats(self) -> Dict[str, float]:
        """Get basic system statistics"""
        try:
            import psutil
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            cpu_percent = process.cpu_percent()
            return {
                'memory_usage_mb': memory_mb,
                'cpu_usage_percent': cpu_percent
            }
        except ImportError:
            # psutil not available, return zeros
            return {
                'memory_usage_mb': 0.0,
                'cpu_usage_percent': 0.0
            }
        except Exception as e:
            logger.warning(f"Failed to get system stats: {e}")
            return {
                'memory_usage_mb': 0.0,
                'cpu_usage_percent': 0.0
            }
    
    def collect_metrics(self) -> SystemMetrics:
        """Collect current system metrics"""
        current_time = time.time()
        system_stats = self._get_system_stats()
        
        # Calculate requests per minute
        one_minute_ago = current_time - 60
        recent_requests = len([t for t in self._request_history if t > one_minute_ago])
        
        # Calculate error rate
        recent_errors = len([t for t in self._error_history if t > one_minute_ago])
        error_rate = (recent_errors / recent_requests * 100) if recent_requests > 0 else 0.0
        
        # Get active tasks count
        try:
            active_tasks = len([task for task in asyncio.all_tasks() if not task.done()])
        except Exception:
            active_tasks = 0
        
        return SystemMetrics(
            timestamp=current_time,
            http_pool_metrics=self._http_pool_provider() if self._http_pool_provider else None,
            db_pool_metrics=self._db_pool_provider() if self._db_pool_provider else None,
            memory_usage_mb=system_stats['memory_usage_mb'],
            cpu_usage_percent=system_stats['cpu_usage_percent'],
            active_tasks=active_tasks,
            total_requests_per_minute=recent_requests,
            error_rate_percent=error_rate,
        )


class PerformanceMonitor:
    """Performance monitoring service with metrics collection and export"""
    
    def __init__(self, export_path: Optional[str] = None):
        """Initialize performance monitor
        
        Args:
            export_path: Path to export metrics files (optional)
        """
        self.settings = get_settings()
        self.collector = PerformanceCollector()
        self._metrics_history: List[SystemMetrics] = []
        self._max_history = 1440  # 24 hours of minute-by-minute data
        
        # Export configuration
        self.export_path = Path(export_path) if export_path else Path.home() / ".tw_stock_mcp" / "metrics"
        self.export_path.mkdir(parents=True, exist_ok=True)
        
        # Monitoring state
        self._monitoring_task: Optional[asyncio.Task] = None
        self._stop_monitoring = asyncio.Event()
        self._enabled = self.settings.ENABLE_METRICS
        
        logger.info(f"Performance monitor initialized (enabled: {self._enabled})")
    
    def register_http_pool(self, metrics_provider: Callable[[], ConnectionMetrics]) -> None:
        """Register HTTP connection pool for monitoring"""
        self.collector.register_http_pool_provider(metrics_provider)
    
    def register_db_pool(self, metrics_provider: Callable[[], DatabaseMetrics]) -> None:
        """Register database pool for monitoring"""
        self.collector.register_db_pool_provider(metrics_provider)
    
    def record_request(self) -> None:
        """Record a request for monitoring"""
        if self._enabled:
            self.collector.record_request()
    
    def record_error(self) -> None:
        """Record an error for monitoring"""
        if self._enabled:
            self.collector.record_error()
    
    async def start_monitoring(self) -> None:
        """Start background monitoring task"""
        if not self._enabled or self._monitoring_task:
            return
        
        self._stop_monitoring.clear()
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())
        logger.info("Performance monitoring started")
    
    async def stop_monitoring(self) -> None:
        """Stop background monitoring task"""
        if not self._monitoring_task:
            return
        
        self._stop_monitoring.set()
        try:
            await asyncio.wait_for(self._monitoring_task, timeout=5.0)
        except asyncio.TimeoutError:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
        
        self._monitoring_task = None
        logger.info("Performance monitoring stopped")
    
    async def _monitoring_loop(self) -> None:
        """Background monitoring loop"""
        export_interval = self.settings.METRICS_EXPORT_INTERVAL
        
        while not self._stop_monitoring.is_set():
            try:
                # Collect metrics
                metrics = self.collector.collect_metrics()
                self._metrics_history.append(metrics)
                
                # Trim history if too long
                if len(self._metrics_history) > self._max_history:
                    self._metrics_history = self._metrics_history[-self._max_history:]
                
                # Log summary metrics
                self._log_metrics_summary(metrics)
                
                # Export metrics if interval reached
                if len(self._metrics_history) % export_interval == 0:
                    await self._export_metrics()
                
                # Wait for next collection
                await asyncio.wait_for(
                    self._stop_monitoring.wait(), 
                    timeout=60.0  # Collect every minute
                )
                
            except asyncio.TimeoutError:
                # Normal timeout, continue monitoring
                continue
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(60)  # Wait before retrying
    
    def _log_metrics_summary(self, metrics: SystemMetrics) -> None:
        """Log a summary of current metrics"""
        if not logger.isEnabledFor(logging.INFO):
            return
        
        summary_parts = [
            f"memory={metrics.memory_usage_mb:.1f}MB",
            f"cpu={metrics.cpu_usage_percent:.1f}%",
            f"tasks={metrics.active_tasks}",
            f"req/min={metrics.total_requests_per_minute}",
            f"errors={metrics.error_rate_percent:.1f}%"
        ]
        
        if metrics.http_pool_metrics:
            http_metrics = metrics.http_pool_metrics
            summary_parts.append(
                f"http_pool(active={http_metrics.active_connections}, "
                f"success={http_metrics.success_rate:.1f}%, "
                f"avg_time={http_metrics.average_response_time:.3f}s)"
            )
        
        if metrics.db_pool_metrics:
            db_metrics = metrics.db_pool_metrics
            summary_parts.append(
                f"db_pool(active={db_metrics.active_connections}/{db_metrics.total_connections}, "
                f"success={db_metrics.query_success_rate:.1f}%, "
                f"avg_time={db_metrics.average_query_time:.3f}s)"
            )
        
        logger.info(f"Performance: {', '.join(summary_parts)}")
    
    async def _export_metrics(self) -> None:
        """Export metrics to files"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Export current metrics
            current_file = self.export_path / f"metrics_current.json"
            if self._metrics_history:
                latest_metrics = self._metrics_history[-1]
                with open(current_file, 'w') as f:
                    json.dump(latest_metrics.to_dict(), f, indent=2)
            
            # Export historical data
            history_file = self.export_path / f"metrics_history_{timestamp}.json"
            history_data = [metrics.to_dict() for metrics in self._metrics_history[-60:]]  # Last hour
            with open(history_file, 'w') as f:
                json.dump(history_data, f, indent=2)
            
            # Clean old history files (keep last 24 hours)
            self._cleanup_old_exports()
            
            logger.debug(f"Metrics exported to {history_file}")
            
        except Exception as e:
            logger.error(f"Failed to export metrics: {e}")
    
    def _cleanup_old_exports(self) -> None:
        """Clean up old exported metrics files"""
        try:
            cutoff_time = time.time() - (24 * 3600)  # 24 hours ago
            
            for file_path in self.export_path.glob("metrics_history_*.json"):
                if file_path.stat().st_mtime < cutoff_time:
                    file_path.unlink()
            
        except Exception as e:
            logger.warning(f"Failed to cleanup old exports: {e}")
    
    def get_current_metrics(self) -> Optional[SystemMetrics]:
        """Get the most recent metrics"""
        return self._metrics_history[-1] if self._metrics_history else None
    
    def get_metrics_history(self, hours: int = 1) -> List[SystemMetrics]:
        """Get metrics history for the specified number of hours"""
        if not self._metrics_history:
            return []
        
        # Calculate how many samples to return (1 per minute)
        samples = min(hours * 60, len(self._metrics_history))
        return self._metrics_history[-samples:]
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get a summary of performance metrics"""
        if not self._metrics_history:
            return {"status": "no_data"}
        
        recent_metrics = self._metrics_history[-10:]  # Last 10 minutes
        
        # Calculate averages
        avg_memory = sum(m.memory_usage_mb for m in recent_metrics) / len(recent_metrics)
        avg_cpu = sum(m.cpu_usage_percent for m in recent_metrics) / len(recent_metrics)
        avg_requests = sum(m.total_requests_per_minute for m in recent_metrics) / len(recent_metrics)
        avg_error_rate = sum(m.error_rate_percent for m in recent_metrics) / len(recent_metrics)
        
        summary = {
            "status": "healthy",
            "collection_period_minutes": len(recent_metrics),
            "average_memory_mb": round(avg_memory, 1),
            "average_cpu_percent": round(avg_cpu, 1),
            "average_requests_per_minute": round(avg_requests, 1),
            "average_error_rate_percent": round(avg_error_rate, 2),
        }
        
        # Add pool-specific summaries
        latest = recent_metrics[-1]
        if latest.http_pool_metrics:
            summary["http_pool"] = {
                "active_connections": latest.http_pool_metrics.active_connections,
                "success_rate": round(latest.http_pool_metrics.success_rate * 100, 1),
                "average_response_time_ms": round(latest.http_pool_metrics.average_response_time * 1000, 1),
            }
        
        if latest.db_pool_metrics:
            summary["database_pool"] = {
                "active_connections": latest.db_pool_metrics.active_connections,
                "total_connections": latest.db_pool_metrics.total_connections,
                "success_rate": round(latest.db_pool_metrics.query_success_rate * 100, 1),
                "average_query_time_ms": round(latest.db_pool_metrics.average_query_time * 1000, 1),
            }
        
        # Determine overall health status
        if avg_error_rate > 10:
            summary["status"] = "unhealthy"
        elif avg_error_rate > 5 or avg_cpu > 80:
            summary["status"] = "degraded"
        
        return summary
    
    async def generate_report(self, hours: int = 24) -> str:
        """Generate a performance report"""
        metrics_history = self.get_metrics_history(hours)
        if not metrics_history:
            return "No performance data available"
        
        # Calculate statistics
        start_time = datetime.fromtimestamp(metrics_history[0].timestamp)
        end_time = datetime.fromtimestamp(metrics_history[-1].timestamp)
        
        total_requests = sum(m.total_requests_per_minute for m in metrics_history)
        total_errors = sum(m.total_requests_per_minute * m.error_rate_percent / 100 for m in metrics_history)
        
        avg_memory = sum(m.memory_usage_mb for m in metrics_history) / len(metrics_history)
        avg_cpu = sum(m.cpu_usage_percent for m in metrics_history) / len(metrics_history)
        
        peak_memory = max(m.memory_usage_mb for m in metrics_history)
        peak_cpu = max(m.cpu_usage_percent for m in metrics_history)
        
        report = f"""
Performance Report ({start_time.strftime('%Y-%m-%d %H:%M')} - {end_time.strftime('%Y-%m-%d %H:%M')})
==============================================================================

System Metrics:
- Average Memory Usage: {avg_memory:.1f} MB (Peak: {peak_memory:.1f} MB)
- Average CPU Usage: {avg_cpu:.1f}% (Peak: {peak_cpu:.1f}%)
- Total Requests: {total_requests:.0f}
- Total Errors: {total_errors:.0f}
- Overall Error Rate: {(total_errors/total_requests*100) if total_requests > 0 else 0:.2f}%

Connection Pool Status:
"""
        
        # Add HTTP pool statistics
        latest = metrics_history[-1]
        if latest.http_pool_metrics:
            http_metrics = latest.http_pool_metrics
            report += f"""
HTTP Connection Pool:
- Active Connections: {http_metrics.active_connections}
- Total Requests: {http_metrics.total_requests}
- Success Rate: {http_metrics.success_rate*100:.1f}%
- Average Response Time: {http_metrics.average_response_time*1000:.1f}ms
- Timeout Rate: {http_metrics.timeout_requests/http_metrics.total_requests*100 if http_metrics.total_requests > 0 else 0:.1f}%
"""
        
        # Add database pool statistics
        if latest.db_pool_metrics:
            db_metrics = latest.db_pool_metrics
            report += f"""
Database Connection Pool:
- Total Connections: {db_metrics.total_connections}
- Active Connections: {db_metrics.active_connections}
- Idle Connections: {db_metrics.idle_connections}
- Total Queries: {db_metrics.total_queries}
- Success Rate: {db_metrics.query_success_rate*100:.1f}%
- Average Query Time: {db_metrics.average_query_time*1000:.1f}ms
- Average Checkout Time: {db_metrics.average_checkout_time*1000:.1f}ms
"""
        
        return report.strip()
    
    def __del__(self):
        """Cleanup on deletion"""
        if self._monitoring_task and not self._monitoring_task.done():
            logger.warning("PerformanceMonitor deleted without proper cleanup")


# Global performance monitor instance
_global_monitor: Optional[PerformanceMonitor] = None


def get_global_monitor() -> PerformanceMonitor:
    """Get or create the global performance monitor"""
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = PerformanceMonitor()
    return _global_monitor


async def start_global_monitoring() -> None:
    """Start global performance monitoring"""
    monitor = get_global_monitor()
    await monitor.start_monitoring()


async def stop_global_monitoring() -> None:
    """Stop global performance monitoring"""
    global _global_monitor
    if _global_monitor:
        await _global_monitor.stop_monitoring()
        _global_monitor = None