import time
import socket
import threading
import argparse
import csv

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, Optional, Tuple
from loguru import logger

from capture.capturer import MessageCapturer
from capture.processor import MessageProcessor
from analytics.engine import NetworkAnalyticsEngine
from pymavlink.dialects.v20 import ardupilotmega as mavlink


@dataclass
class DroneStatus:
    """Data class to hold drone status information"""
    sysid: int
    addr: Optional[Tuple[str, int]] = None  # (ip, port)
    compid: int = 0
    connected: bool = True
    message_count: int = 0
    first_message_time: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    last_update: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))
    connection_event: str = ""  # "CONNECTED" or "DISCONNECTED"

    def __str__(self):
        return (f"DroneStatus(sysid={self.sysid}, compid={self.compid}, "
                f"connected={self.connected}, addr={self.addr}, "
                f"messages={self.message_count}, last_update={self.last_update})")


class MAVLinkServer(threading.Thread):
    
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 5566,
        auto_find_port: bool = False,
        connection_timeout: float = 5.0,
        on_connected: Optional[Callable[[int, int, Tuple[str, int]], None]] = None,
        on_disconnected: Optional[Callable[[int], None]] = None,
        on_message_received: Optional[Callable[[int, DroneStatus], None]] = None,
        enable_analytics: bool = True,
    ):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.auto_find_port = auto_find_port
        self.actual_port = port
        self.connection_timeout = connection_timeout
        
        self.socket: Optional[socket.socket] = None
        self.running = False
        self.last_disconnect_check = time.time()
        
        # Single source of truth for drone states
        self.drones: Dict[int, DroneStatus] = {}
        self.parsers: Dict[Tuple[str, int], mavlink.MAVLink] = {}
        
        # Message capture & analytics
        self.capturer = MessageCapturer()
        self.enable_analytics = enable_analytics
        self.analytics: Optional[NetworkAnalyticsEngine] = None
        self.processor: Optional[MessageProcessor] = None
        
        if enable_analytics:
            self.analytics = NetworkAnalyticsEngine(windows=[1, 10, 60])

        # Event callbacks
        self.on_connected = on_connected or self._default_callback
        self.on_disconnected = on_disconnected or self._default_callback
        self.on_message_received = on_message_received or self._default_callback

    @staticmethod
    def _default_callback(*args, **kwargs):
        """Default no-op callback"""
        pass

    def _find_available_port(self, start_port: int = 5566) -> int:
        """Find next available port starting from start_port"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            for port in range(start_port, start_port + 100):
                try:
                    sock.bind((self.host, port))
                    sock.close()
                    logger.debug(f"Found available port: {port}")
                    return port
                except OSError:
                    continue
            raise OSError("No available ports in range")
        finally:
            sock.close()

    def run(self):
        """Main server loop"""
        try:
            # Determine actual port
            if self.auto_find_port:
                self.actual_port = self._find_available_port(self.port)
            else:
                self.actual_port = self.port

            # Setup socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
            self.socket.settimeout(1)
            self.socket.bind((self.host, self.actual_port))
            
            self.running = True
            logger.info(f"* MAVLink server started on {self.host}:{self.actual_port}")
            
            # Start analytics processor if enabled
            if self.enable_analytics:
                self._start_analytics()

            # Main receive loop
            while self.running:
                try:
                    data, addr = self.socket.recvfrom(4096)
                    self._handle_message(data, addr)
                except socket.timeout:
                    pass
                except Exception as e:
                    logger.error(f"Exception in receive loop: {e}")
                
                # Periodically check for disconnected drones
                current_time = time.time()
                if current_time - self.last_disconnect_check > 1.0:  # Check every 1 second
                    self._check_disconnections()
                    self.last_disconnect_check = current_time

        except OSError as e:
            logger.error(f"Cannot bind to {self.host}:{self.actual_port} - {e}")
            raise
        finally:
            self.cleanup()

    def _start_analytics(self):
        """Start the analytics message processor"""
        logger.info("Starting analytics processor...")
        
        self.processor = MessageProcessor(
            queue=self.capturer.queue,
            batch_size=100,
            batch_timeout=0.5,
        )
        
        # Register analytics handler
        self.processor.register_handler(self._analytics_handler)
        self.processor.start()
        
        logger.info("Analytics processor started")
    
    def _analytics_handler(self, batch):
        """Handler for processing batch of messages through analytics"""
        if self.analytics:
            self.analytics.process_batch(batch)

    def _handle_message(self, data: bytes, addr: Tuple[str, int]):
        """Process incoming MAVLink message"""
        try:
            # Get or create parser for this address
            if addr not in self.parsers:
                self.parsers[addr] = mavlink.MAVLink(None, False)
            
            parser = self.parsers[addr]
            
            # Parse byte-by-byte with proper framing validation
            for byte in data:
                msg = parser.parse_char(bytes([byte]))

                if msg:
                    sysid = msg.get_srcSystem()
                    compid = msg.get_srcComponent()

                    self.capturer.capture_message(msg, data, addr)
                    
                    if sysid not in self.drones:
                        # New drone connected
                        self._handle_new_drone(sysid, compid, addr)
                    else:
                        # Update existing drone
                        self._update_drone(sysid, addr)
                    
                    # Notify about message
                    self.on_message_received(sysid, self.drones[sysid])
                    
        except Exception:
            # Silently ignore parsing errors
            pass

    def _handle_new_drone(self, sysid: int, compid: int, addr: Tuple[str, int]):
        """Handle new drone connection"""
        drone = DroneStatus(
            sysid=sysid,
            compid=compid,
            addr=addr,
            connected=True,
            first_message_time=time.time(),
            last_heartbeat=time.time(),
            connection_event="CONNECTED",
        )
        self.drones[sysid] = drone
        self.on_connected(sysid, compid, addr)

    def _update_drone(self, sysid: int, addr: Tuple[str, int]):
        """Update existing drone status"""
        drone = self.drones[sysid]
        drone.addr = addr
        drone.message_count += 1
        drone.last_heartbeat = time.time()
        drone.last_update = datetime.now().strftime("%H:%M:%S")
        
        # Re-connect if was previously disconnected
        if not drone.connected:
            drone.connected = True
            drone.connection_event = "RECONNECTED"
            self.on_connected(drone.sysid, drone.compid, addr)

    def _check_disconnections(self) -> None:
        """
        Check for drones that haven't sent messages within timeout period.
        Mark them as disconnected and trigger callback.
        """
        current_time = time.time()
        disconnected_sysids = []
        
        for sysid, drone in self.drones.items():
            # Check if drone is currently connected AND has exceeded timeout
            if drone.connected:
                time_since_last_message = current_time - drone.last_heartbeat
                
                if time_since_last_message > self.connection_timeout:
                    # Mark as disconnected
                    drone.connected = False
                    drone.connection_event = "DISCONNECTED"
                    drone.last_update = datetime.now().strftime("%H:%M:%S")
                    disconnected_sysids.append(sysid)
        
        # Trigger callbacks for disconnected drones
        for sysid in disconnected_sysids:
            self.on_disconnected(sysid)

    def get_drone_status(self, sysid: int) -> Optional[DroneStatus]:
        """Get status of a specific drone"""
        return self.drones.get(sysid)

    def get_all_drones(self) -> Dict[int, DroneStatus]:
        """Get all connected drones"""
        return self.drones.copy()
    
    def get_analytics_report(self, window_s: int = 1) -> Optional[Dict]:
        """Get global analytics report (all drones combined)"""
        if self.analytics:
            return self.analytics.get_report_summary(window_s=window_s)
        return None

    def get_per_drone_analytics(self, sysid: int, window_s: int = 1) -> Optional[Dict]:
        """Get analytics report for specific drone"""
        if self.analytics:
            return self.analytics.get_per_drone_report(sysid, window_s=window_s)
        return None
    
    def get_all_drones_analytics(self, window_s: int = 1) -> Optional[Dict]:
        """Get analytics reports for all drones"""
        if self.analytics:
            return self.analytics.get_all_drones_report(window_s)
        return None

    def stop(self):
        """Stop the server"""
        self.running = False
        # Stop processor if running
        if self.processor:
            self.processor.join_wait()

    def cleanup(self):
        """Clean up resources"""
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
        logger.info("MAVLink server stopped")


class MAVListener:
    """
    High-level interface for MAVLink server.
    
    Provides simplified API for starting/stopping server and handling events.
    Delegates all drone state management to MAVLinkServer (no duplication).
    """
    
    def __init__(
        self,
        server_host: str = "0.0.0.0",
        server_port: int = 5566,
        auto_find_port: bool = False,
        connection_timeout: float = 5.0,
        enable_analytics: bool = True,
    ):
        self.server_host = server_host
        self.server_port = server_port
        self.auto_find_port = auto_find_port
        self.connection_timeout = connection_timeout
        self.enable_analytics = enable_analytics
        self.server: Optional[MAVLinkServer] = None

    def start_server(self):
        """Start the MAVLink server"""
        self.server = MAVLinkServer(
            host=self.server_host,
            port=self.server_port,
            auto_find_port=self.auto_find_port,
            connection_timeout=self.connection_timeout,
            on_connected=self._on_drone_connected,
            on_disconnected=self._on_drone_disconnected,
            on_message_received=self._on_message_received,
            enable_analytics=self.enable_analytics,
        )
        self.server.start()

    def _on_drone_connected(self, sysid: int, compid: int, addr: Tuple[str, int]):
        """Handle drone connection event"""
        drone = self.server.get_drone_status(sysid)
        
        if drone and drone.connection_event == "RECONNECTED":
            logger.warning(f"RECONNECTED | SYSID:{sysid} CompID:{compid} from {addr[0]}:{addr[1]}")
        else:
            logger.success(f"CONNECTED | New drone - SYSID:{sysid} CompID:{compid} from {addr[0]}:{addr[1]}")

    def _on_drone_disconnected(self, sysid: int):
        """Handle drone disconnection event"""
        drone = self.server.get_drone_status(sysid)
        if drone:
            logger.warning(f"DISCONNECTED | SYSID:{sysid} (idle for {self.connection_timeout}s)")

    def _on_message_received(self, sysid: int, drone_status: DroneStatus):
        """Handle message received event"""
        # Can be used for additional processing if needed
        # Currently just receives notifications
        pass

    def print_status(self):
        """Print current drone status"""
        if not self.server:
            logger.info("Server not started")
            return
        
        drones = self.server.get_all_drones()
        if not drones:
            logger.info("No drones connected")
            return
        
        connected_count = len([s for s in drones.values() if s.connected])
        logger.info(f"Connected Drones: {connected_count}/{len(drones)}")
        
        for sysid, status in sorted(drones.items()):
            connection_str = "+ CONNECTED" if status.connected else "- DISCONNECTED"
            time_since_msg = time.time() - status.last_heartbeat
            logger.info(f"SYSID:{sysid:3d} | CompID:{status.compid:3d} | Messages:{status.message_count:5d} | {connection_str} (idle: {time_since_msg:.1f}s)")

    def print_global_analytics(self, window_s: int = 1):
        """Print global analytics (all drones combined)"""
        if not self.server:
            logger.info("Server not started")
            return
        
        report = self.server.get_analytics_report(window_s=window_s)
        if not report:
            logger.info("Analytics not available")
            return
        
        logger.info(f"GLOBAL ANALYTICS ({report['window_s']}s window) - Total: {report['total_messages_processed']} msgs")
        
        # Traffic
        traffic = report.get('traffic', {})
        logger.info(f"Traffic: {traffic.get('msg_rate', 0):.1f} msg/s | {traffic.get('bytes_rate', 0):.0f} bytes/s | {traffic.get('unique_drones', 0)} drones")
        
        # Latency
        latency = report.get('latency', {})
        imt = latency.get('inter_message_time_ms', {})
        logger.info(f"Latency: mean={imt.get('mean', 0):.2f}ms | stdev={imt.get('stdev', 0):.2f}ms")
        
        # Loss
        loss = report.get('loss', {})
        logger.info(f"Loss: {loss.get('total_lost', 0)} msgs | Rate: {loss.get('loss_rate_pct', 0):.4f}% | Events: {loss.get('loss_events_count', 0)}")
        

    def print_per_drone_analytics(self, window_s: int = 1):
        """Print detailed per-drone analytics"""
        if not self.server:
            logger.info("Server not started")
            return
        
        all_drones_report = self.server.get_all_drones_analytics(window_s=window_s)
        if not all_drones_report:
            logger.info("Per-drone analytics not available")
            return
        
        logger.info(f"PER-DRONE ANALYTICS ({window_s}s window)")
        
        # Print comparison table
        logger.info("Dumpping analytics:")
        logger.info(f"{'SYSID':<8} {'Messages':<12} {'Bytes':<12} {'Loss Rate':<12} {'Latency (ms)':<15}")
        
        for sysid, report in sorted(all_drones_report.items()):
            traffic = report.get('traffic', {})
            loss = report.get('loss', {})
            latency = report.get('latency', {})
            
            msg_count = traffic.get('message_count', 0)
            bytes_count = traffic.get('bytes_received', 0)
            loss_rate = loss.get('loss_rate_pct', 0.0)
            latency_mean = latency.get('mean_ms', 0) if latency else 0
            
            logger.info(f"{sysid:<8} {msg_count:<12} {bytes_count:<12} {loss_rate:<12.4f} {latency_mean:<15.2f}")
    

    def stop_server(self):
        """Stop the server"""
        if self.server:
            self.server.stop()


def main():
    """Main function - runs the MAVLink server"""
    parser = argparse.ArgumentParser(
        description='MAVLink Server - UDP listener for drone telemetry with analytics',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with analytics enabled (default)
  python mav_server_simple.py
  
  # Disable analytics
  python mav_server_simple.py --no-analytics
  
  # With custom port
  python mav_server_simple.py --port 5577
  
  # With custom timeout
  python mav_server_simple.py --timeout 10
  
  # Test with SITL:
  # Terminal 1: python mav_server_simple.py
  # Terminal 2: sim_vehicle.py -v ArduCopter -I 1 --sysid 1 --out 127.0.0.1:5566
        """
    )
    parser.add_argument(
        '--host',
        type=str,
        default='0.0.0.0',
        help='Server host to bind to (default: 0.0.0.0)'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=5566,
        help='Server port to bind to (default: 5566)'
    )
    parser.add_argument(
        '--timeout',
        type=float,
        default=5.0,
        help='Connection timeout in seconds (default: 5.0)'
    )
    parser.add_argument(
        '--auto-port',
        action='store_true',
        help='Automatically find available port'
    )
    parser.add_argument(
        '--no-analytics',
        action='store_true',
        help='Disable analytics engine'
    )
    parser.add_argument(
        '--instance-id',
        type=int,
        help='Instance ID for logging'
    )
    
    args = parser.parse_args()
    
    # Configure logger
    logger.remove()
    
    log_filename = "mav_server_{time:YYYY-MM-DD}.log"
    if args.instance_id is not None:
        log_filename = f"mav_server_inst{args.instance_id}_{{time:YYYY-MM-DD}}.log"
    
    logger.add(
        lambda msg: print(msg, end=""),
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        colorize=True,
        level="DEBUG"
    )
    logger.add(
        log_filename,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}",
        rotation="00:00",
        retention="7 days",
        level="INFO"
    )
    
    analytics_status = "ENABLED" if not args.no_analytics else "DISABLED"
    logger.info(f"Starting MAVLink Server - Instance ID: {args.instance_id or 'default'}")
    logger.info(f"Configuration: {args.host}:{args.port} (auto_port={args.auto_port}, timeout={args.timeout}s)")
    logger.info(f"Analytics: {analytics_status}")
    
    try:
        listener = MAVListener(
            server_host=args.host,
            server_port=args.port,
            auto_find_port=args.auto_port,
            connection_timeout=args.timeout,
            enable_analytics=not args.no_analytics,
        )
        listener.start_server()
        
        time.sleep(0.5)
        
        if listener.server and listener.server.running:
            actual_port = listener.server.actual_port
            logger.success(f"Server successfully started on port {actual_port}")
        else:
            logger.error("Server failed to start")
            return

        # Print status and analytics every 5 seconds
        print_interval = 3
        last_print = time.time()
        
        logger.info("Starting periodic reporting (every 3 seconds)...")
        
        while True:
            time.sleep(1)
            current_time = time.time()
            
            if current_time - last_print >= print_interval:
                logger.info("")  # Blank line
                listener.print_status()
                
                if not args.no_analytics:
                    listener.print_per_drone_analytics()
                    # listener.print_global_analytics()
                
                last_print = current_time

    except KeyboardInterrupt:
        logger.info("\nShutting down...")
        listener.stop_server()
        logger.success("Server stopped cleanly")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)


if __name__ == "__main__":
    main()