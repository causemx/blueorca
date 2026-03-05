import time
import socket
import threading
import argparse
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, Optional, Tuple
from loguru import logger

from capture.capturer import MessageCapturer
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
        
        self.capturer = MessageCapturer()

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

    def _check_disconnections(self):
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

    def stop(self):
        """Stop the server"""
        self.running = False

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
    ):
        self.server_host = server_host
        self.server_port = server_port
        self.auto_find_port = auto_find_port
        self.connection_timeout = connection_timeout
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
            connection_str = "✓ CONNECTED" if status.connected else "✗ DISCONNECTED"
            time_since_msg = time.time() - status.last_heartbeat
            logger.info(f"SYSID:{sysid:3d} | CompID:{status.compid:3d} | Messages:{status.message_count:5d} | {connection_str} (idle: {time_since_msg:.1f}s)")

    def stop_server(self):
        """Stop the server"""
        if self.server:
            self.server.stop()


def main():
    """Main function - runs the MAVLink server"""
    parser = argparse.ArgumentParser(
        description='MAVLink Server - UDP listener for drone telemetry with disconnection detection',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single instance on default port 5566
  python mav_server_refactored_fixed.py
  
  # With custom timeout (default 5s)
  python mav_server_refactored_fixed.py --timeout 10
  
  # With custom port
  python mav_server_refactored_fixed.py --port 5577
  
  # With auto port detection
  python mav_server_refactored_fixed.py --auto-port
  
  # Custom host
  python mav_server_refactored_fixed.py --host 192.168.1.100 --port 5566
  
  # Test with multiple SITL instances:
  # Terminal 1: python mav_server_refactored_fixed.py --timeout 3
  # Terminal 2: sim_vehicle.py -v ArduCopter -I 1 --sysid 1 --out 127.0.0.1:5566
  # Terminal 3: sim_vehicle.py -v ArduCopter -I 2 --sysid 2 --out 127.0.0.1:5566
  # Stop a drone (Ctrl+C) to see disconnection detection
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
    
    logger.info(f"Starting MAVLink Server - Instance ID: {args.instance_id or 'default'}")
    logger.info(f"Configuration: {args.host}:{args.port} (auto_port={args.auto_port}, timeout={args.timeout}s)")
    
    try:
        listener = MAVListener(
            server_host=args.host,
            server_port=args.port,
            auto_find_port=args.auto_port,
            connection_timeout=args.timeout,
        )
        listener.start_server()
        
        time.sleep(0.5)
        
        if listener.server and listener.server.running:
            actual_port = listener.server.actual_port
            logger.success(f"Server successfully started on port {actual_port}")
        else:
            logger.error("Server failed to start")
            return

        # [Optional] Keep running and print status
        """
        while True:
            time.sleep(3)
            listener.print_status()
        """    

    except KeyboardInterrupt:
        logger.info("Shutting down...")
        listener.stop_server()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)


if __name__ == "__main__":
    main()