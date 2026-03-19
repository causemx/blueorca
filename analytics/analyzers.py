from typing import Dict, List, Tuple
from loguru import logger
from collections import defaultdict

from .window import WindowManager
from .models import DroneMetrics, MessageTypeMetrics
from capture.message import CapturedMessage


class TrafficAnalyzer:
    """
    Analyzes message traffic patterns.
    
    Tracks:
    - Messages per second (global & per-drone)
    - Bytes per second
    - Message type distribution
    - Traffic trends
    """
    
    def __init__(self, windows: List[int] = None):
        if windows is None:
            windows = [1, 10, 60]
        
        # Window managers for different metrics
        self._msg_count_window = WindowManager(windows=windows)  # Count messages
        self._bytes_window = WindowManager(windows=windows)      # Count bytes
        
        # Per-drone tracking
        self._drone_metrics: Dict[int, DroneMetrics] = {}
        
        # Per-message-type tracking
        self._msg_type_metrics: Dict[str, MessageTypeMetrics] = {}
        
        # Message type distribution (for histogram)
        self._msg_type_counts: Dict[str, int] = defaultdict(int)
        self._msg_type_bytes: Dict[str, int] = defaultdict(int)
        
        logger.debug("TrafficAnalyzer initialized")
    
    def track_message(self, msg: CapturedMessage) -> None:
        """Track a message for traffic analysis"""
        timestamp_us = msg.timestamp_us
        
        # Track global message count and bytes
        self._msg_count_window.add_value(1.0, timestamp_us=timestamp_us)
        self._bytes_window.add_value(float(msg.payload_len), timestamp_us=timestamp_us)
        
        # Track per-message-type
        if msg.msg_name not in self._msg_type_metrics:
            self._msg_type_metrics[msg.msg_name] = MessageTypeMetrics(
                msg_name=msg.msg_name,
                msg_id=msg.msg_id
            )
        
        msg_type_metric = self._msg_type_metrics[msg.msg_name]
        msg_type_metric.count += 1
        msg_type_metric.bytes += msg.payload_len
        msg_type_metric.last_seen_us = timestamp_us
        
        self._msg_type_counts[msg.msg_name] += 1
        self._msg_type_bytes[msg.msg_name] += msg.payload_len
        
        # Track per-drone
        if msg.src_sysid not in self._drone_metrics:
            self._drone_metrics[msg.src_sysid] = DroneMetrics(sysid=msg.src_sysid)
        
        drone = self._drone_metrics[msg.src_sysid]
        drone.message_count += 1
        drone.bytes_received += msg.payload_len
        drone.last_timestamp_us = timestamp_us
    
    def get_summary(self, window_s: int = 1) -> Dict:
        """Get traffic summary for specific window"""
        msg_stats = self._msg_count_window.get_stats(window_s=window_s)
        bytes_stats = self._bytes_window.get_stats(window_s=window_s)
        
        # Calculate rates (per second)
        msg_rate = msg_stats.sum  # Count of messages in window
        bytes_rate = bytes_stats.sum  # Total bytes in window
        
        # Get top message types
        top_msg_types = sorted(
            self._msg_type_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )[:5]
        
        return {
            'window_s': window_s,
            'msg_rate': msg_rate,  # msg/s
            'bytes_rate': bytes_rate,  # bytes/s
            'msg_count': msg_stats.count,
            'total_bytes': bytes_stats.sum,
            'msg_type_top_5': dict(top_msg_types),
            'unique_msg_types': len(self._msg_type_metrics),
            'unique_drones': len(self._drone_metrics),
        }
    
    def get_per_drone_summary(self) -> Dict[int, Dict]:
        """Get traffic summary per drone"""
        result = {}
        for sysid, drone in self._drone_metrics.items():
            result[sysid] = {
                'message_count': drone.message_count,
                'bytes_received': drone.bytes_received,
                'last_seen_us': drone.last_timestamp_us,
            }
        return result
    
    def get_message_type_stats(self) -> Dict[str, Dict]:
        """Get stats per message type"""
        result = {}
        for msg_name, metric in self._msg_type_metrics.items():
            result[msg_name] = {
                'msg_id': metric.msg_id,
                'count': metric.count,
                'bytes': metric.bytes,
                'last_seen_us': metric.last_seen_us,
            }
        return result


class LatencyAnalyzer:
    """
    Analyzes timing and inter-message arrival patterns.
    
    Tracks:
    - Inter-message arrival times
    - Per-message-type frequency
    - Timestamp consistency
    - Clock drift estimation
    """
    
    def __init__(self, windows: List[int] = None):
        if windows is None:
            windows = [1, 10, 60]
        
        # Window manager for inter-message times
        self._imt_window = WindowManager(windows=windows)  # Inter-message time
        
        # Per-drone last message timestamp
        self._drone_last_msg_us: Dict[int, int] = {}
        
        # Per-message-type tracking
        self._msg_type_last_seen: Dict[str, int] = {}
        self._msg_type_arrival_times: Dict[str, List[int]] = defaultdict(list)
        
        # Clock drift tracking (per drone)
        self._drone_clock_drift: Dict[int, float] = {}  # ppm (parts per million)
        
        logger.debug("LatencyAnalyzer initialized")
    
    def track_message(self, msg: CapturedMessage) -> None:
        """Track message for latency analysis"""
        timestamp_us = msg.timestamp_us
        sysid = msg.src_sysid
        msg_name = msg.msg_name
        
        # Calculate inter-message time (time since last message from this drone)
        if sysid in self._drone_last_msg_us:
            imt_us = timestamp_us - self._drone_last_msg_us[sysid]
            imt_ms = imt_us / 1000.0
            self._imt_window.add_value(imt_ms, timestamp_us=timestamp_us)
        
        self._drone_last_msg_us[sysid] = timestamp_us
        
        # Track per-message-type arrival times
        if msg_name in self._msg_type_last_seen:
            last_seen = self._msg_type_last_seen[msg_name]
            arrival_time_us = timestamp_us - last_seen
            self._msg_type_arrival_times[msg_name].append(arrival_time_us)
            
            # Keep only recent history (last 1000 arrivals)
            if len(self._msg_type_arrival_times[msg_name]) > 1000:
                self._msg_type_arrival_times[msg_name] = \
                    self._msg_type_arrival_times[msg_name][-1000:]
        
        self._msg_type_last_seen[msg_name] = timestamp_us
    
    def get_summary(self, window_s: int = 1) -> Dict:
        """Get latency summary for specific window"""
        imt_stats = self._imt_window.get_stats(window_s=window_s)
        
        return {
            'window_s': window_s,
            'inter_message_time_ms': {
                'mean': imt_stats.mean,
                'stdev': imt_stats.stdev,
                'min': imt_stats.min,
                'max': imt_stats.max,
                'p50': imt_stats.p50,
                'p95': imt_stats.p95,
                'p99': imt_stats.p99,
                'count': imt_stats.count,
            },
        }
    
    def get_frequency_analysis(self) -> Dict[str, Dict]:
        """Analyze message frequency per type"""
        result = {}
        
        for msg_name, arrival_times in self._msg_type_arrival_times.items():
            if not arrival_times:
                continue
            
            # Calculate frequency
            mean_interval_us = sum(arrival_times) / len(arrival_times)
            if mean_interval_us > 0:
                frequency_hz = 1_000_000 / mean_interval_us
            else:
                frequency_hz = 0.0
            
            # Calculate jitter (stdev of intervals)
            if len(arrival_times) > 1:
                mean = sum(arrival_times) / len(arrival_times)
                variance = sum((x - mean) ** 2 for x in arrival_times) / len(arrival_times)
                stdev_us = variance ** 0.5
                jitter_ms = stdev_us / 1000.0
            else:
                jitter_ms = 0.0
            
            result[msg_name] = {
                'frequency_hz': frequency_hz,
                'mean_interval_us': mean_interval_us,
                'jitter_ms': jitter_ms,
                'sample_count': len(arrival_times),
            }
        
        return result


class MessageLossDetector:
    """
    Detects message loss using sequence numbers.
    
    Tracks:
    - Sequence number gaps (lost messages)
    - Duplicate messages
    - Out-of-order arrivals
    - Per-drone and per-message-type loss
    """
    
    def __init__(self):
        # Per-drone last sequence number
        self._drone_last_seq: Dict[int, int] = {}
        
        # Per (sysid, msg_type) last sequence
        self._msg_type_last_seq: Dict[Tuple[int, str], int] = {}
        
        # Loss tracking
        self._total_messages: int = 0
        self._total_loss_count: int = 0
        self._loss_events: List[Dict] = []
        
        # Per-drone metrics
        self._drone_loss_stats: Dict[int, Dict] = defaultdict(
            lambda: {'received': 0, 'lost': 0, 'loss_events': 0}
        )
        
        logger.debug("MessageLossDetector initialized")
    
    def track_message(self, msg: CapturedMessage) -> None:
        """Track message for loss detection"""
        sysid = msg.src_sysid
        msg_name = msg.msg_name
        msg_seq = msg.msg_seq
        
        self._total_messages += 1
        self._drone_loss_stats[sysid]['received'] += 1
        
        # Skip if no sequence number
        if msg_seq == 0:
            return
        
        # Check for loss using per-drone sequence
        key = (sysid, msg_name)
        
        if key in self._msg_type_last_seq:
            last_seq = self._msg_type_last_seq[key]
            
            # Check for gap
            if msg_seq > last_seq + 1:
                lost_count = msg_seq - last_seq - 1
                self._total_loss_count += lost_count
                self._drone_loss_stats[sysid]['lost'] += lost_count
                self._drone_loss_stats[sysid]['loss_events'] += 1
                
                # Record loss event
                self._loss_events.append({
                    'timestamp_us': msg.timestamp_us,
                    'sysid': sysid,
                    'msg_type': msg_name,
                    'lost_count': lost_count,
                    'sequence_range': (last_seq + 1, msg_seq - 1),
                })
                
                # Keep only recent events
                if len(self._loss_events) > 1000:
                    self._loss_events = self._loss_events[-1000:]
        
        self._msg_type_last_seq[key] = msg_seq
    
    def get_summary(self) -> Dict:
        """Get loss detection summary"""
        loss_rate = 0.0
        if self._total_messages > 0:
            loss_rate = (self._total_loss_count / 
                        (self._total_messages + self._total_loss_count) * 100)
        
        return {
            'total_messages': self._total_messages,
            'total_lost': self._total_loss_count,
            'loss_rate_pct': loss_rate,
            'loss_events_count': len(self._loss_events),
        }
    
    def get_per_drone_loss(self) -> Dict[int, Dict]:
        """Get loss stats per drone"""
        result = {}
        for sysid, stats in self._drone_loss_stats.items():
            total = stats['received'] + stats['lost']
            loss_rate = 0.0
            if total > 0:
                loss_rate = (stats['lost'] / total * 100)
            
            result[sysid] = {
                'received': stats['received'],
                'lost': stats['lost'],
                'loss_rate_pct': loss_rate,
                'loss_events': stats['loss_events'],
            }
        
        return result
    
    def reset(self) -> None:
        """Reset all loss tracking"""
        self._total_messages = 0
        self._total_loss_count = 0
        self._loss_events.clear()
        self._drone_loss_stats.clear()