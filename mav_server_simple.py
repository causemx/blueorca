import time
import socket
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, Optional, Tuple
from loguru import logger

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


class MAVLinkServerThread(threading.Thread):
    """UDP server thread for receiving MAVLink messages"""
    
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 5566,
        timeout: int = 5,
        on_connected: Optional[Callable[[int, int, Tuple[str, int]], None]] = None,
        on_disconnected: Optional[Callable[[int], None]] = None,
    ):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.timeout = timeout
        self.socket: Optional[socket.socket] = None
        self.running = False
        self.drones: Dict[int, DroneStatus] = {}
        
        # Callbacks instead of Qt signals
        self.on_connected = on_connected or self._default_callback
        self.on_disconnected = on_disconnected or self._default_callback

    @staticmethod
    def _default_callback(*args, **kwargs):
        """Default no-op callback"""
        pass

    def run(self):
        """Main server loop"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
            self.socket.settimeout(1)

            self.socket.bind((self.host, self.port))
            self.running = True
            logger.info(f"MAVLink server started on {self.host}:{self.port}")

            while self.running:
                try:
                    data, addr = self.socket.recvfrom(4096)
                    self._handle_message(data, addr)
                except socket.timeout:
                    continue
                except Exception as e:
                    logger.error(f"Exception in receive loop: {e}")

        except OSError as e:
            logger.error(f"Cannot bind to {self.host}:{self.port} - {e}")
        finally:
            self.cleanup()

    def _handle_message(self, data: bytes, addr: Tuple[str, int]):
        """Process incoming MAVLink message"""
        # This is a simplified handler - extend based on actual MAVLink parsing
        sysid = self._extract_sysid(data)
        compid = self._extract_compid(data)
        
        if sysid is None:
            return

        if sysid not in self.drones:
            # New drone connected
            drone_status = DroneStatus(
                sysid=sysid,
                compid=compid or 0,
                addr=addr,
                connected=True,
                message_count=1,
                first_message_time=time.time(),
                last_heartbeat=time.time(),
            )
            self.drones[sysid] = drone_status
            self.on_connected(sysid, compid or 0, addr)
        else:
            # Update existing drone
            drone = self.drones[sysid]
            drone.addr = addr
            drone.message_count += 1
            drone.last_heartbeat = time.time()
            drone.last_update = datetime.now().strftime("%H:%M:%S")
            if not drone.connected:
                drone.connected = True
                drone.connection_event = "RECONNECTED"
                self.on_connected(sysid, compid or 0, addr)

    @staticmethod
    def _extract_sysid(data: bytes) -> Optional[int]:
        """Extract system ID from MAVLink message
        
        MAVLink v1: byte 3
        MAVLink v2: bytes 3-4 (after header)
        """
        if len(data) < 4:
            return None
        
        # Try MAVLink v1 format (byte 0xFE = 254, byte 3 = sysid)
        if data[0] == 0xFE and len(data) > 3:
            return data[3]
        
        # Try MAVLink v2 format (byte 0xFD, sysid at position 3)
        if data[0] == 0xFD and len(data) > 3:
            return data[3]
        
        return None

    @staticmethod
    def _extract_compid(data: bytes) -> Optional[int]:
        """Extract component ID from MAVLink message"""
        if len(data) < 5:
            return None
        
        if data[0] in (0xFE, 0xFD):
            return data[4]
        
        return None

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
    """Simple MAVLink listener without GUI dependencies"""
    
    def __init__(self, server_host: str = "0.0.0.0", server_port: int = 5566):
        self.server_host = server_host
        self.server_port = server_port
        self.drone_statuses: Dict[int, DroneStatus] = {}
        self.server: Optional[MAVLinkServerThread] = None

    def start_server(self):
        """Start the MAVLink server"""
        self.server = MAVLinkServerThread(
            host=self.server_host,
            port=self.server_port,
            timeout=5,
            on_connected=self.on_connected,
            on_disconnected=self.on_disconnected,
        )
        self.server.start()

    def on_connected(self, sysid: int, compid: int, addr: Tuple[str, int]):
        """Handle drone connection"""
        if sysid in self.drone_statuses:
            status = self.drone_statuses[sysid]
            status.connected = True
            status.connection_event = "RECONNECTED"
            logger.warning(f"RECONNECTED | SYSID:{sysid} CompID:{compid} from {addr[0]}:{addr[1]}")
        else:
            status = DroneStatus(
                sysid=sysid,
                compid=compid,
                addr=addr,
                connected=True,
                first_message_time=time.time(),
                last_heartbeat=time.time(),
                last_update=datetime.now().strftime("%H:%M:%S"),
                connection_event="CONNECTED",
            )
            self.drone_statuses[sysid] = status
            logger.success(f"CONNECTED | New drone - SYSID:{sysid} CompID:{compid} from {addr[0]}:{addr[1]}")

    def on_disconnected(self, sysid: int):
        """Handle drone disconnection"""
        if sysid in self.drone_statuses:
            status = self.drone_statuses[sysid]
            status.connected = False
            status.connection_event = "DISCONNECTED"
            status.last_update = datetime.now().strftime("%H:%M:%S")
            logger.warning(f"DISCONNECTED | SYSID:{sysid}")

    def print_status(self):
        """Print current drone status"""
        if not self.drone_statuses:
            logger.info("No drones connected")
            return
        
        connected_count = len([s for s in self.drone_statuses.values() if s.connected])
        logger.info(f"Connected Drones: {connected_count}")
        
        for sysid, status in self.drone_statuses.items():
            connection_str = "✓ CONNECTED" if status.connected else "✗ DISCONNECTED"
            logger.info(f"SYSID:{sysid:3d} | CompID:{status.compid:3d} | {connection_str}")
            logger.debug(f"Address: {status.addr}")
        

    def stop_server(self):
        """Stop the server"""
        if self.server:
            self.server.stop()


def main():
    """Main function - runs the MAVLink server in terminal"""
    # Configure loguru logger
    logger.remove()  # Remove default handler
    logger.add(
        lambda msg: print(msg, end=""),  # Console output
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        colorize=True,
        level="DEBUG"
    )
    logger.add(
        "mav_server_{time:YYYY-MM-DD}.log",  # File output with rotation
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}",
        rotation="00:00",  # Rotate at midnight
        retention="7 days",  # Keep logs for 7 days
        level="INFO"
    )
    
    listener = MAVListener(
        server_host="0.0.0.0",
        server_port=5566,
    )
    listener.start_server()

    # Keep the server running and print status periodically
    try:
        while True:
            time.sleep(10)
            listener.print_status()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        listener.stop_server()


if __name__ == "__main__":
    main()