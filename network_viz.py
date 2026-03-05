import sys
import time
import threading
import math
from datetime import datetime
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QGraphicsView, QGraphicsScene, QGraphicsEllipseItem, QGraphicsLineItem,
    QGraphicsTextItem, QHeaderView
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QColor, QPen, QBrush, QFont, QPainter

from loguru import logger
import socket


# ============================================================================
# MAVLink Server Components (from original mav_server_simple.py)
# ============================================================================

@dataclass
class DroneStatus:
    """Data class to hold drone status information"""
    sysid: int
    addr: Optional[Tuple[str, int]] = None
    compid: int = 0
    connected: bool = True
    message_count: int = 0
    first_message_time: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    last_update: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))
    connection_event: str = ""

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
        on_connected=None,
        on_disconnected=None,
    ):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.timeout = timeout
        self.socket: Optional[socket.socket] = None
        self.running = False
        self.drones: Dict[int, DroneStatus] = {}
        
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
        sysid = self._extract_sysid(data)
        compid = self._extract_compid(data)
        
        if sysid is None:
            return

        if sysid not in self.drones:
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
        """Extract system ID from MAVLink message"""
        if len(data) < 4:
            return None
        
        if data[0] == 0xFE and len(data) > 3:
            return data[3]
        
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


# ============================================================================
# PyQt5 Signal Emitters and Visualization Components
# ============================================================================

class ServerSignalEmitter(QObject):
    """Emits signals for server events (thread-safe)"""
    drone_connected = pyqtSignal(int, int, str, int)  # sysid, compid, addr, msg_count
    drone_updated = pyqtSignal(int, int, int)  # sysid, msg_count, last_heartbeat
    drone_disconnected = pyqtSignal(int)  # sysid


class DroneGraphicsItem:
    """Visual representation of a drone on the network diagram"""
    
    def __init__(self, scene, sysid: int, x: float, y: float):
        self.sysid = sysid
        self.x = x
        self.y = y
        
        # Circle for drone
        self.circle = QGraphicsEllipseItem(x - 15, y - 15, 30, 30)
        self.circle.setPen(QPen(QColor("#2196F3"), 2))
        self.circle.setBrush(QBrush(QColor("#64B5F6")))
        scene.addItem(self.circle)
        
        # Label
        self.label = QGraphicsTextItem(f"SYSID:{sysid}")
        self.label.setFont(QFont("Arial", 9, QFont.Bold))
        self.label.setPos(x - 20, y + 20)
        scene.addItem(self.label)
        
        # Status indicator (small circle)
        self.status_indicator = QGraphicsEllipseItem(x + 12, y - 12, 10, 10)
        self.status_indicator.setPen(QPen(QColor("#4CAF50"), 1))
        self.status_indicator.setBrush(QBrush(QColor("#4CAF50")))
        scene.addItem(self.status_indicator)
        
        self.connected = True
        self.message_count = 0

    def set_connected(self, connected: bool):
        """Update connection status visually"""
        self.connected = connected
        if connected:
            self.circle.setBrush(QBrush(QColor("#64B5F6")))
            self.status_indicator.setBrush(QBrush(QColor("#4CAF50")))
        else:
            self.circle.setBrush(QBrush(QColor("#BDBDBD")))
            self.status_indicator.setBrush(QBrush(QColor("#F44336")))

    def update_message_count(self, count: int):
        """Update message count display"""
        self.message_count = count
        self.label.setPlainText(f"SYSID:{self.sysid}\nMsg:{count}")


class NetworkVisualizationWidget(QGraphicsView):
    """Widget for network topology visualization"""
    
    def __init__(self):
        self.scene = QGraphicsScene()
        super().__init__(self.scene)
        
        self.setRenderHint(QPainter.Antialiasing)
        self.setStyleSheet("border: 1px solid #ddd; background-color: #f5f5f5;")
        
        # Server node in center
        server_x, server_y = 400, 300
        self.server_circle = QGraphicsEllipseItem(server_x - 20, server_y - 20, 40, 40)
        self.server_circle.setPen(QPen(QColor("#FF6F00"), 3))
        self.server_circle.setBrush(QBrush(QColor("#FFB74D")))
        self.scene.addItem(self.server_circle)
        
        server_label = QGraphicsTextItem("MAVLink\nServer")
        server_label.setFont(QFont("Arial", 10, QFont.Bold))
        server_label.setPos(server_x - 30, server_y - 10)
        self.scene.addItem(server_label)
        
        self.server_pos = (server_x, server_y)
        self.drones = {}  # sysid -> DroneGraphicsItem
        self.connections = {}  # sysid -> QGraphicsLineItem

    def add_drone(self, sysid: int):
        """Add a drone to the visualization"""
        if sysid in self.drones:
            return
        
        # Position drones in a circle around server
        angle = (len(self.drones) * 360) / max(1, 10)
        radius = 150
        x = self.server_pos[0] + radius * math.cos(math.radians(angle))
        y = self.server_pos[1] + radius * math.sin(math.radians(angle))
        
        # Create drone visual
        drone = DroneGraphicsItem(self.scene, sysid, x, y)
        self.drones[sysid] = drone
        
        # Draw connection line
        line = QGraphicsLineItem(
            self.server_pos[0], self.server_pos[1],
            x, y
        )
        line.setPen(QPen(QColor("#2196F3"), 2))
        self.scene.addItem(line)
        self.connections[sysid] = line

    def remove_drone(self, sysid: int):
        """Remove a drone from the visualization"""
        if sysid not in self.drones:
            return
        
        drone = self.drones[sysid]
        self.scene.removeItem(drone.circle)
        self.scene.removeItem(drone.label)
        self.scene.removeItem(drone.status_indicator)
        
        if sysid in self.connections:
            self.scene.removeItem(self.connections[sysid])
            del self.connections[sysid]
        
        del self.drones[sysid]

    def update_drone_status(self, sysid: int, connected: bool, msg_count: int):
        """Update drone status display"""
        if sysid in self.drones:
            drone = self.drones[sysid]
            drone.set_connected(connected)
            drone.update_message_count(msg_count)


class StatusTableWidget(QTableWidget):
    """Table showing detailed drone information"""
    
    def __init__(self):
        super().__init__()
        self.setColumnCount(6)
        self.setHorizontalHeaderLabels([
            "SYSID", "CompID", "Address", "Messages", "Status", "Last Update"
        ])
        
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setStyleSheet("background-color: #f0f0f0;")
        
        self.setStyleSheet("""
            QTableWidget {
                border: 1px solid #ddd;
                gridline-color: #ddd;
            }
            QTableWidget::item {
                padding: 5px;
            }
        """)
        
        self.drones_info = {}  # sysid -> row info

    def add_drone_entry(self, sysid: int, compid: int, addr: str):
        """Add a new drone to the table"""
        row = self.rowCount()
        self.insertRow(row)
        
        # SYSID
        sysid_item = QTableWidgetItem(str(sysid))
        sysid_item.setFont(QFont("Arial", 10, QFont.Bold))
        self.setItem(row, 0, sysid_item)
        
        # CompID
        self.setItem(row, 1, QTableWidgetItem(str(compid)))
        
        # Address
        self.setItem(row, 2, QTableWidgetItem(addr))
        
        # Messages (will be updated)
        msg_item = QTableWidgetItem("0")
        self.setItem(row, 3, msg_item)
        
        # Status
        status_item = QTableWidgetItem("Connected")
        status_item.setForeground(QColor("#4CAF50"))
        status_item.setFont(QFont("Arial", 9, QFont.Bold))
        self.setItem(row, 4, status_item)
        
        # Last Update
        time_item = QTableWidgetItem(datetime.now().strftime("%H:%M:%S"))
        self.setItem(row, 5, time_item)
        
        self.drones_info[sysid] = {
            'row': row,
            'msg_item': msg_item,
            'status_item': status_item,
            'time_item': time_item
        }

    def update_drone_entry(self, sysid: int, msg_count: int, connected: bool):
        """Update drone information in table"""
        if sysid not in self.drones_info:
            return
        
        info = self.drones_info[sysid]
        info['msg_item'].setText(str(msg_count))
        
        status_text = "Connected" if connected else "Disconnected"
        status_color = QColor("#4CAF50") if connected else QColor("#F44336")
        
        info['status_item'].setText(status_text)
        info['status_item'].setForeground(status_color)
        info['time_item'].setText(datetime.now().strftime("%H:%M:%S"))

    def remove_drone_entry(self, sysid: int):
        """Remove drone from table"""
        if sysid in self.drones_info:
            row = self.drones_info[sysid]['row']
            self.removeRow(row)
            del self.drones_info[sysid]
            
            # Update row indices
            for sid, info in self.drones_info.items():
                if info['row'] > row:
                    info['row'] -= 1


class MainWindow(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MAVLink Network Visualization")
        self.setGeometry(100, 100, 1400, 800)
        
        # Setup logger
        logger.remove()
        logger.add(
            lambda msg: print(msg, end=""),
            format="<green>{time:HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <level>{message}</level>",
            colorize=True,
            level="DEBUG"
        )
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QHBoxLayout(central_widget)
        
        # Left side - Visualization and controls
        left_layout = QVBoxLayout()
        
        # Network visualization
        self.network_widget = NetworkVisualizationWidget()
        left_layout.addWidget(self.network_widget)
        
        # Control buttons
        button_layout = QHBoxLayout()
        
        self.start_button = QPushButton("Start Server")
        self.start_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """)
        self.start_button.clicked.connect(self.start_server)
        button_layout.addWidget(self.start_button)
        
        self.stop_button = QPushButton("Stop Server")
        self.stop_button.setEnabled(False)
        self.stop_button.setStyleSheet("""
            QPushButton {
                background-color: #F44336;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
            QPushButton:disabled {
                background-color: #ccc;
            }
        """)
        self.stop_button.clicked.connect(self.stop_server)
        button_layout.addWidget(self.stop_button)
        
        self.status_label = QLabel("Status: Idle")
        self.status_label.setStyleSheet("font-weight: bold; color: #666;")
        button_layout.addWidget(self.status_label)
        button_layout.addStretch()
        
        left_layout.addLayout(button_layout)
        
        # Right side - Status table
        right_layout = QVBoxLayout()
        right_label = QLabel("Connected Drones")
        right_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        right_layout.addWidget(right_label)
        
        self.status_table = StatusTableWidget()
        right_layout.addWidget(self.status_table)
        
        # Drone count label
        self.count_label = QLabel("Total: 0 drones")
        self.count_label.setStyleSheet("font-size: 10px; color: #666;")
        right_layout.addWidget(self.count_label)
        
        # Add layouts to main
        main_layout.addLayout(left_layout, 2)
        main_layout.addLayout(right_layout, 1)
        
        # Server thread and signal emitter
        self.server_thread: Optional[MAVLinkServerThread] = None
        self.signal_emitter = ServerSignalEmitter()
        
        # Connect signals
        self.signal_emitter.drone_connected.connect(self.on_drone_connected)
        self.signal_emitter.drone_updated.connect(self.on_drone_updated)
        self.signal_emitter.drone_disconnected.connect(self.on_drone_disconnected)
        
        # Timer to periodically update status
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_drone_statuses)
        
        # Tracking
        self.connected_drones = {}  # sysid -> DroneStatus
        
        self.setStyleSheet("""
            QMainWindow {
                background-color: #fafafa;
            }
            QLabel {
                color: #333;
            }
        """)

    def start_server(self):
        """Start the MAVLink server"""
        self.server_thread = MAVLinkServerThread(
            host="0.0.0.0",
            port=5566,
            on_connected=self.on_server_drone_connected,
            on_disconnected=self.on_server_drone_disconnected,
        )
        self.server_thread.start()
        
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_label.setText("Status: Server running on 0.0.0.0:5566")
        self.status_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
        
        self.update_timer.start(1000)  # Update every second
        logger.success("Server started")

    def on_server_drone_connected(self, sysid: int, compid: int, addr: Tuple[str, int]):
        """Callback from server thread when drone connects"""
        ip, port = addr
        self.signal_emitter.drone_connected.emit(sysid, compid, f"{ip}:{port}", 0)

    def on_server_drone_disconnected(self, sysid: int):
        """Callback from server thread when drone disconnects"""
        self.signal_emitter.drone_disconnected.emit(sysid)

    def on_drone_connected(self, sysid: int, compid: int, addr: str, msg_count: int):
        """Handle drone connection signal"""
        self.connected_drones[sysid] = {
            'compid': compid,
            'addr': addr,
            'connected': True,
            'msg_count': msg_count
        }
        
        self.network_widget.add_drone(sysid)
        self.status_table.add_drone_entry(sysid, compid, addr)
        self.update_count_label()
        
        logger.success(f"✓ CONNECTED | SYSID:{sysid} CompID:{compid} from {addr}")

    def on_drone_updated(self, sysid: int, msg_count: int, heartbeat: int):
        """Handle drone status update"""
        if sysid in self.connected_drones:
            self.connected_drones[sysid]['msg_count'] = msg_count
            self.network_widget.update_drone_status(sysid, True, msg_count)
            self.status_table.update_drone_entry(sysid, msg_count, True)

    def on_drone_disconnected(self, sysid: int):
        """Handle drone disconnection"""
        if sysid in self.connected_drones:
            self.connected_drones[sysid]['connected'] = False
            self.network_widget.update_drone_status(sysid, False, 
                                                   self.connected_drones[sysid]['msg_count'])
            self.status_table.update_drone_entry(sysid, 
                                               self.connected_drones[sysid]['msg_count'], 
                                               False)
        
        logger.warning(f"✗ DISCONNECTED | SYSID:{sysid}")

    def update_drone_statuses(self):
        """Periodically update drone statuses from server"""
        if not self.server_thread:
            return
        
        current_time = time.time()
        timeout_threshold = 5  # seconds
        
        for sysid, drone_status in self.server_thread.get_all_drones().items():
            if sysid in self.connected_drones:
                # Check for timeout
                time_since_heartbeat = current_time - drone_status.last_heartbeat
                
                if time_since_heartbeat > timeout_threshold and self.connected_drones[sysid]['connected']:
                    self.on_drone_disconnected(sysid)
                elif time_since_heartbeat <= timeout_threshold and not self.connected_drones[sysid]['connected']:
                    self.on_drone_connected(
                        sysid, 
                        drone_status.compid, 
                        f"{drone_status.addr[0]}:{drone_status.addr[1]}" if drone_status.addr else "Unknown",
                        drone_status.message_count
                    )
                elif self.connected_drones[sysid]['connected']:
                    self.signal_emitter.drone_updated.emit(
                        sysid, 
                        drone_status.message_count,
                        int(drone_status.last_heartbeat)
                    )

    def update_count_label(self):
        """Update the drone count label"""
        connected = sum(1 for d in self.connected_drones.values() if d['connected'])
        total = len(self.connected_drones)
        self.count_label.setText(f"Total: {total} drones ({connected} connected)")

    def stop_server(self):
        """Stop the MAVLink server"""
        if self.server_thread:
            self.server_thread.stop()
            self.update_timer.stop()
        
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText("Status: Idle")
        self.status_label.setStyleSheet("font-weight: bold; color: #F44336;")
        
        logger.info("Server stopped")

    def closeEvent(self, event):
        """Handle window close"""
        self.stop_server()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()