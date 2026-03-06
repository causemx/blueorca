
import time
import statistics
from collections import deque
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from loguru import logger


@dataclass
class WindowStats:
    """Statistics for a single time window"""
    window_size_s: int
    count: int = 0
    sum: float = 0.0
    mean: float = 0.0
    stdev: float = 0.0
    min: float = 0.0
    max: float = 0.0
    p50: float = 0.0  # median
    p95: float = 0.0
    p99: float = 0.0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for easy access"""
        return {
            'window_size_s': self.window_size_s,
            'count': self.count,
            'sum': self.sum,
            'mean': self.mean,
            'stdev': self.stdev,
            'min': self.min,
            'max': self.max,
            'p50': self.p50,
            'p95': self.p95,
            'p99': self.p99,
        }


class WindowManager:
    
    def __init__(self, windows: List[int] = None):

        if windows is None:
            windows = [1, 10, 60]
        
        self.windows = sorted(windows)  # Sort for consistent ordering
        
        # Data storage: (value, timestamp_us) tuples
        # Using deque for efficient removal from both ends
        self._datapoints: deque = deque()
        
        # Cached stats (updated on query)
        self._stats_cache: Dict[int, WindowStats] = {}
        
        # Track statistics for quick access
        self._last_update_time_us = 0
        
        logger.debug(f"WindowManager initialized with windows: {self.windows}s")
    
    def add_value(self, value: float, timestamp_us: Optional[int] = None) -> None:
        """
        Add a datapoint to tracking.
        
        Args:
            value: Numeric value to add
            timestamp_us: Timestamp in microseconds (default: current time)
        """
        if timestamp_us is None:
            timestamp_us = time.time_ns() // 1000
        
        # Purge expired datapoints before adding new one
        self._purge_expired(timestamp_us)
        
        # Add new datapoint
        self._datapoints.append((value, timestamp_us))
        self._last_update_time_us = timestamp_us
    
    def _purge_expired(self, current_time_us: int) -> None:
        """
        Remove datapoints older than the largest window.
        
        Args:
            current_time_us: Current timestamp in microseconds
        """
        if not self.windows:
            return
        
        # Calculate oldest acceptable timestamp
        max_window_s = max(self.windows)
        cutoff_time_us = current_time_us - (max_window_s * 1_000_000)
        
        # Remove old datapoints from front of deque
        while self._datapoints and self._datapoints[0][1] < cutoff_time_us:
            self._datapoints.popleft()
    
    def get_stats(self, window_s: int) -> WindowStats:
        """
        Get statistics for a specific window.
        
        Args:
            window_s: Window size in seconds
            
        Returns:
            WindowStats object with count, mean, stdev, percentiles
            
        Raises:
            ValueError: If window_s not in configured windows
        """
        if window_s not in self.windows:
            raise ValueError(f"Window {window_s}s not configured. Available: {self.windows}")
        
        # Get current time
        current_time_us = time.time_ns() // 1000
        
        # Filter datapoints in this window
        cutoff_time_us = current_time_us - (window_s * 1_000_000)
        values = [v for v, ts in self._datapoints if ts >= cutoff_time_us]
        
        # Calculate statistics
        stats = WindowStats(window_size_s=window_s)
        
        if not values:
            return stats  # Empty stats
        
        stats.count = len(values)
        stats.sum = sum(values)
        stats.mean = stats.sum / stats.count
        stats.min = min(values)
        stats.max = max(values)
        
        # Standard deviation
        if stats.count > 1:
            stats.stdev = statistics.stdev(values)
        else:
            stats.stdev = 0.0
        
        # Percentiles
        stats.p50 = self._percentile(values, 50)
        stats.p95 = self._percentile(values, 95)
        stats.p99 = self._percentile(values, 99)
        
        return stats
    
    def get_all_stats(self) -> Dict[int, WindowStats]:
        """
        Get statistics for all configured windows.
        
        Returns:
            Dictionary mapping window_size_s -> WindowStats
        """
        return {w: self.get_stats(w) for w in self.windows}
    
    def _percentile(self, values: List[float], percentile: int) -> float:
         
        """
        Calculate percentile of values.
        
        Args:
            values: List of numeric values
            percentile: Percentile to calculate (0-100)
            
        Returns:
            Percentile value
        """
        if not values:
            return 0.0
        
        if len(values) == 1:
            return values[0]
        
        # Simple percentile calculation
        sorted_values = sorted(values)
        index = (percentile / 100.0) * (len(sorted_values) - 1)
        
        # Linear interpolation
        lower_index = int(index)
        upper_index = min(lower_index + 1, len(sorted_values) - 1)
        
        if lower_index == upper_index:
            return sorted_values[lower_index]
        
        weight = index - lower_index
        return (sorted_values[lower_index] * (1 - weight) + 
                sorted_values[upper_index] * weight)
    
    def get_count(self, window_s: int) -> int:
        """Get number of datapoints in window"""
        return self.get_stats(window_s).count
    
    def get_mean(self, window_s: int) -> float:
        """Get mean value in window"""
        return self.get_stats(window_s).mean
    
    def get_stdev(self, window_s: int) -> float:
        """Get standard deviation in window"""
        return self.get_stats(window_s).stdev
    
    def reset(self) -> None:
        """Clear all datapoints"""
        self._datapoints.clear()
        self._stats_cache.clear()
        logger.debug("WindowManager reset")
    
    def get_datapoint_count(self) -> int:
        """Get total number of datapoints currently tracked"""
        return len(self._datapoints)
    
"""
if __name__ == "__main__":
    wm = WindowManager(windows=[1, 5, 10])
    
    # Simulate adding values over time
    start_time_us = time.time_ns() // 100
    
    for i in range(100):
        # Add value with small delay
        current_time_us = start_time_us + (i * 10_000)  # 10ms apart
        wm.add_value(float(i), timestamp_us=current_time_us)
    
    for window_s in [1, 5, 10]:
        print(f"count: {wm.get_count(window_s)}")
        print(f"stats: {wm.get_stats(window_s)}")
        print(f"mean: {wm.get_mean(window_s)}")
"""        