import time
from typing import List, Dict
from loguru import logger

from capture.message import CapturedMessage
from .analyzers import TrafficAnalyzer, LatencyAnalyzer, MessageLossDetector

class NetworkAnalyticsEngine:
    def __init__(self, windows: List[int] = None):
        self.windows = windows
        self.traffic_analyzer = TrafficAnalyzer(windows)
        self.latency_analyzer = LatencyAnalyzer(windows)
        self.message_loss_detector = MessageLossDetector()

        self._message_count = 0
        self._start_time_us = time.time_ns() // 1000

    def process_message(self, msg: CapturedMessage) -> None:
        try:
            self.traffic_analyzer.track_message(msg)
            self.latency_analyzer.track_message(msg)
            self.message_loss_detector.track_message(msg)
            self._message_count += 1
        except Exception as e:
            logger.error(f"Error processing message in analytics: {e}")
    

    def process_batch(self, msgs: List[CapturedMessage]) -> None:
        for message in msgs:
            self.process_message(message)
    
    def get_report_summary(self, window_s=1) -> Dict:
        """Get total network analytic summary

        Args:
            window_s (int, optional): _description_. Defaults to 1.

        Returns:
            Dict: _description_
        """
        current_time_us = time.time_ns() // 1000
        elapsed_s = (current_time_us - self._start_time_us) / 1_000_000
        
        traffic_summary = self.traffic_analyzer.get_global_summary(window_s=window_s)
        latency_summary = self.latency_analyzer.get_global_summary(window_s=window_s)
        loss_summary = self.message_loss_detector.get_global_summary()
        
        return {
            'timestamp_us': current_time_us,
            'elapsed_seconds': elapsed_s,
            'total_messages_processed': self._message_count,
            'window_s': window_s,
            'traffic': traffic_summary,
            'latency': latency_summary,
            'loss': loss_summary,
        }

    def get_per_drone_report(self, sysid:int, window_s:int = 1) -> Dict:
        """Get report of per drone

        Args:
            sysid (int): drone's sysid
            window_s (int, optional): default window size. Defaults to 1.

        Returns:
            Dict: _description_
        """
        # Get per-drone traffic
        per_drone_traffic = self.traffic_analyzer.get_per_drone_summary()
        drone_traffic = per_drone_traffic.get(sysid, {})
        
        # Get per-drone loss
        per_drone_loss = self.message_loss_detector.get_per_drone_loss()
        drone_loss = per_drone_loss.get(sysid, {})
        
        # Calculate per-drone latency (need to track per drone separately)
        per_drone_latency = self._get_per_drone_latency(sysid)
        
        return {
            'timestamp_us': time.time_ns() // 1000,
            'sysid': sysid,
            'window_s': window_s,
            
            'traffic': {
                'message_count': drone_traffic.get('message_count', 0),
                'bytes_received': drone_traffic.get('bytes_received', 0),
                'last_seen_us': drone_traffic.get('last_seen_us', 0),
            },
            
            'latency': per_drone_latency,
            
            'loss': {
                'received': drone_loss.get('received', 0),
                'lost': drone_loss.get('lost', 0),
                'loss_rate_pct': drone_loss.get('loss_rate_pct', 0.0),
                'loss_events': drone_loss.get('loss_events', 0),
            },
        }

    def _get_per_drone_latency(self, sysid: int) -> Dict:
        latency_summary = self.latency_analyzer.get_global_summary(window_s=1)
        return latency_summary.get('inter_message_time_ms', {})

    def get_all_drones_report(self, window_s: int = 1) -> Dict[int, Dict]:
        """Get collapse network analytic report

        Returns:
            Dict[int, Dict]: _description_
        """
        result = {}
        per_drone_traffic = self.traffic_analyzer.get_per_drone_summary()

        for sysid in per_drone_traffic.keys():
            result[sysid] = self.get_per_drone_report(sysid)
        return result

    def reset(self) -> None:
        self.traffic_analyzer = TrafficAnalyzer(self.windows)
        self.latency_analyzer = LatencyAnalyzer(self.windows)
        self.message_loss_detector.reset()
        self._message_count = 0
        self._start_time_us = time.time_ns() // 1000
        logger.info("Analytics engine reset")

""" Example usage """
if __name__ == "__main__":
    from capture.message import CapturedMessage
    
    logger.remove()
    logger.add(lambda msg: print(msg, end=""), colorize=True)
    
    print("=== NetworkAnalyticsEngine Example ===\n")
    
    # Create engine
    engine = NetworkAnalyticsEngine(windows=[1, 10, 60])
    
    # Simulate messages
    print("Simulating 500 messages...\n")
    
    base_time_us = int(time.time() * 1_000_000)
    
    for i in range(500):
        msg = CapturedMessage(
            timestamp_ns=base_time_us * 1000 + i * 10_000,
            timestamp_us=base_time_us + i * 10,
            src_addr=("127.0.0.1", 14550),
            src_sysid=1,
            src_compid=1,
            msg_id=30,
            msg_name="ATTITUDE",
            msg_seq=i,
            payload_len=28,
            raw_bytes=b'\x00' * 28,
        )
        engine.process_message(msg)

    report = engine.get_detail_report()
    print(f"Total Messages: {report['total_messages_processed']}")
    print(f"\nTraffic ({report['window_s']}s window):")
    print(f"  Message Rate: {report['traffic']['msg_rate']:.1f} msg/s")
    print(f"  Bytes Rate: {report['traffic']['bytes_rate']:.0f} bytes/s")
    print(f"  Message Types: {report['traffic']['unique_msg_types']}")