"""Rate limiter utility for API calls."""
import time
from threading import Lock


class RateLimiter:
    """Rate limiter for API calls."""
    
    def __init__(self, calls: int, period: float):
        """
        Initialize the rate limiter.
        
        Args:
            calls: Number of calls allowed in the period
            period: Time period in seconds
        """
        self.calls = calls
        self.period = period
        self.timestamps: dict[str, list] = {}
        self.lock = Lock()
    
    def _cleanup_old_timestamps(self, key: str) -> None:
        """Remove timestamps older than the period."""
        current_time = time.time()
        self.timestamps[key] = [
            ts for ts in self.timestamps[key]
            if current_time - ts < self.period
        ]
    
    def acquire(self, key: str) -> float | None:
        """
        Try to acquire a rate limit slot.
        
        Args:
            key: The key to rate limit
            
        Returns:
            The time to wait if rate limited, None if not rate limited
        """
        with self.lock:
            if key not in self.timestamps:
                self.timestamps[key] = []
            
            self._cleanup_old_timestamps(key)
            
            if len(self.timestamps[key]) >= self.calls:
                oldest_timestamp = self.timestamps[key][0]
                wait_time = self.period - (time.time() - oldest_timestamp)
                return max(0, wait_time)
            
            self.timestamps[key].append(time.time())
            return None
    
    def wait(self, key: str) -> None:
        """
        Wait until a rate limit slot is available.
        
        Args:
            key: The key to rate limit
        """
        while True:
            wait_time = self.acquire(key)
            if wait_time is None:
                return
            time.sleep(wait_time)

# TWSE API rate limiter (3 requests per 5 seconds)
twse_rate_limiter = RateLimiter(calls=3, period=5.0) 