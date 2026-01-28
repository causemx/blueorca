#!/usr/bin/env python3
"""
PyQt5 Dashboard for MAVLink Server with PyMAVLink Packet Parsing
Fixed grid layout - one drone card = one grid block
"""

import sys
import socket
import threading
import time
from datetime import datetime
from typing import Dict
from dataclasses import dataclass, field

from pymavlink.dialects.v20 import ardupilotmega as mavlink

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QGridLayout, QScrollArea, QSplitter, QTreeWidget, QTreeWidgetItem
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtGui import QFont


@dataclass
class DroneStatus:
    """Data class to hold drone status information"""
    addr: tuple  # (ip, port)
    sysid: int
    compid: int
    connected: bool = True
    message_count: int = 0
    first_message_time: float = 0.0
    last_heartbeat: float = 0.0
    last_update: str = ""
    connection_event: str = ""  # "CONNECTED" or "DISCONNECTED"
    
    # Telemetry data from MAVLink messages
    armed: bool = False
    mode: str = "UNKNOWN"
    battery_percent: int = 0
    battery_voltage: float = 0.0
    battery_current: float = 0.0
    gps_fix: int = 0
    gps_satellites: int = 0
    altitude: float = 0.0
    latitude: float = 0.0
    longitude: float = 0.0
    groundspeed: float = 0.0
    heading: float = 0.0
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    system_status: str = "UNKNOWN"
    
    # Message type tracking
    last_message_type: str = ""
    message_types: Dict[str, int] = field(default_factory=dict)


class DroneStatusSignal(QObject):
    """Signal emitter for drone status updates"""
    drone_connected = pyqtSignal(tuple, int, int)  # addr, sysid, compid
    drone_disconnected = pyqtSignal(tuple, int)    # addr, sysid
    drone_message_received = pyqtSignal(tuple, DroneStatus)  # addr, status
    status_updated = pyqtSignal(tuple, DroneStatus)


class MAVLinkServerThread(threading.Thread):
    """MAVLink Server using PyMAVLink for packet parsing"""
    
    def __init__(self, host='0.0.0.0', port=5566, timeout=10):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.timeout = timeout
        self.socket = None
        self.running = False
        self.drones = {}  # {(ip, port): DroneStatus}
        self.parsers = {}  # {(ip, port): MAVLink parser}
        self.signal_emitter = DroneStatusSignal()
        
    def run(self):
        """Start the server"""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
        self.socket.settimeout(1)
        
        try:
            self.socket.bind((self.host, self.port))
            self.running = True
            print(f"✓ MAVLink Server started on {self.host}:{self.port}")
        except OSError as e:
            print(f"✗ Error: Cannot bind to {self.host}:{self.port}: {e}")
            return
        
        try:
            while self.running:
                self._check_disconnections()
                
                try:
                    data, addr = self.socket.recvfrom(1024)
                    if data:
                        self._handle_packet(data, addr)
                except socket.timeout:
                    continue
                    
        finally:
            self.stop()
    
    def _handle_packet(self, data, addr):
        """Handle incoming MAVLink packet using pymavlink"""
        try:
            # Initialize parser for this drone if needed
            if addr not in self.parsers:
                self.parsers[addr] = mavlink.MAVLink(None, False)
            
            parser = self.parsers[addr]
            
            # Parse the packet byte by byte using pymavlink
            for byte in data:
                msg = parser.parse_char(bytes([byte]))
                
                if msg:
                    # Got a complete MAVLink message
                    sysid = msg.get_srcSystem()
                    compid = msg.get_srcComponent()
                    msg_type = msg.get_type()
                    
                    # Check if this is a new drone
                    if addr not in self.drones:
                        self._drone_connected(addr, sysid, compid, msg_type)
                    else:
                        # Update drone status with new message
                        self._update_drone_status(addr, msg, msg_type)
                    
        except Exception as e:
            # Silently ignore parsing errors
            pass
    
    def _drone_connected(self, addr, sysid, compid, first_msg_type):
        """Handle new drone connection"""
        status = DroneStatus(
            addr=addr,
            sysid=sysid,
            compid=compid,
            connected=True,
            first_message_time=time.time(),
            last_heartbeat=time.time(),
            last_update=datetime.now().strftime("%H:%M:%S"),
            connection_event="CONNECTED",
            last_message_type=first_msg_type
        )
        
        self.drones[addr] = status
        self.signal_emitter.drone_connected.emit(addr, sysid, compid)
        self.signal_emitter.drone_message_received.emit(addr, status)
        print(f"✓ DRONE CONNECTED: {addr[0]}:{addr[1]} (SysID: {sysid}, First Msg: {first_msg_type})")
    
    def _update_drone_status(self, addr, msg, msg_type):
        """Update drone status from MAVLink message"""
        status = self.drones[addr]
        status.message_count += 1
        status.last_heartbeat = time.time()
        status.last_update = datetime.now().strftime("%H:%M:%S")
        status.last_message_type = msg_type
        
        # Track message type counts
        if msg_type not in status.message_types:
            status.message_types[msg_type] = 0
        status.message_types[msg_type] += 1
        
        # Parse specific message types to extract telemetry
        try:
            if msg_type == 'HEARTBEAT':
                self._parse_heartbeat(status, msg)
            elif msg_type == 'SYS_STATUS':
                self._parse_sys_status(status, msg)
            elif msg_type == 'BATTERY_STATUS':
                self._parse_battery_status(status, msg)
            elif msg_type == 'ATTITUDE':
                self._parse_attitude(status, msg)
            elif msg_type == 'GPS_RAW_INT':
                self._parse_gps(status, msg)
            elif msg_type == 'GLOBAL_POSITION_INT':
                self._parse_global_position(status, msg)
            elif msg_type == 'VFR_HUD':
                self._parse_vfr_hud(status, msg)
        except Exception as e:
            pass
        
        self.signal_emitter.drone_message_received.emit(addr, status)
    
    def _parse_heartbeat(self, status, msg):
        """Parse HEARTBEAT message"""
        try:
            status.armed = bool(msg.base_mode & 0x80)
            status.system_status = self._get_system_status_name(msg.system_status)
            mode_map = {0: 'STABILIZE', 2: 'ALT_HOLD', 3: 'AUTO', 4: 'GUIDED', 6: 'RTL', 9: 'LAND'}
            status.mode = mode_map.get(msg.custom_mode, f'MODE_{msg.custom_mode}')
        except Exception:
            pass
    
    def _parse_sys_status(self, status, msg):
        """Parse SYS_STATUS message"""
        try:
            status.battery_percent = msg.battery_remaining
            status.battery_voltage = msg.voltage_battery / 1000.0
            status.battery_current = msg.current_battery / 100.0 if msg.current_battery != -1 else 0.0
        except Exception:
            pass
    
    def _parse_battery_status(self, status, msg):
        """Parse BATTERY_STATUS message"""
        try:
            if msg.voltages[0] != 0xffff:
                status.battery_voltage = msg.voltages[0] / 1000.0
            status.battery_current = msg.current_battery / 100.0 if msg.current_battery != -1 else 0.0
            status.battery_percent = msg.battery_remaining
        except Exception:
            pass
    
    def _parse_attitude(self, status, msg):
        """Parse ATTITUDE message"""
        try:
            status.roll = msg.roll
            status.pitch = msg.pitch
            status.yaw = msg.yaw
        except Exception:
            pass
    
    def _parse_gps(self, status, msg):
        """Parse GPS_RAW_INT message"""
        try:
            status.latitude = msg.lat / 1e7
            status.longitude = msg.lon / 1e7
            status.altitude = msg.alt / 1e3
            status.gps_fix = msg.fix_type
            status.gps_satellites = msg.satellites_visible
        except Exception:
            pass
    
    def _parse_global_position(self, status, msg):
        """Parse GLOBAL_POSITION_INT message"""
        try:
            status.latitude = msg.lat / 1e7
            status.longitude = msg.lon / 1e7
            status.altitude = msg.alt / 1e3
            status.groundspeed = (msg.vx**2 + msg.vy**2)**0.5 / 100.0
            status.heading = msg.hdg / 100.0
        except Exception:
            pass
    
    def _parse_vfr_hud(self, status, msg):
        """Parse VFR_HUD message"""
        try:
            status.groundspeed = msg.groundspeed
            status.altitude = msg.alt
            status.heading = msg.heading
        except Exception:
            pass
    
    @staticmethod
    def _get_system_status_name(status_code):
        """Convert system status code to name"""
        status_names = {
            0: 'UNINIT', 1: 'BOOT', 2: 'CALIBRATING', 3: 'STANDBY',
            4: 'ACTIVE', 5: 'CRITICAL', 6: 'EMERGENCY', 7: 'POWEROFF', 8: 'SHUTDOWN',
        }
        return status_names.get(status_code, f'UNKNOWN({status_code})')
    
    def _check_disconnections(self):
        """Check for inactive drones"""
        current_time = time.time()
        disconnected = []
        
        for addr, status in list(self.drones.items()):
            if current_time - status.last_heartbeat > self.timeout:
                disconnected.append(addr)
        
        for addr in disconnected:
            status = self.drones.pop(addr)
            status.connected = False
            status.connection_event = "DISCONNECTED"
            status.last_update = datetime.now().strftime("%H:%M:%S")
            
            if addr in self.parsers:
                del self.parsers[addr]
            
            self.signal_emitter.drone_disconnected.emit(addr, status.sysid)
            print(f"✗ DRONE DISCONNECTED: {addr[0]}:{addr[1]} (SysID: {status.sysid}, Messages: {status.message_count})")
    
    def stop(self):
        """Stop the server"""
        self.running = False
        if self.socket:
            self.socket.close()


class DroneCard(QFrame):
    """Widget displaying drone status as a card"""
    
    clicked = pyqtSignal(tuple)
    
    def __init__(self, addr: tuple, status: DroneStatus, parent=None):
        super().__init__(parent)
        self.addr = addr
        self.status = status
        self.selected = False
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Plain)
        self.setLineWidth(2)
        self.setCursor(Qt.PointingHandCursor)
        self.init_ui()
        self.update_style()
    
    def init_ui(self):
        """Initialize UI"""
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        
        # Drone ID
        drone_label = QLabel(f"SYSID: {self.status.sysid}")
        drone_font = QFont("Consolas", 11, QFont.Bold)
        drone_label.setFont(drone_font)
        drone_label.setStyleSheet("color: #888888; background: transparent; border: none;")
        layout.addWidget(drone_label)
        
        # Connection status
        self.status_label = QLabel("● Connecting...")
        status_font = QFont("Consolas", 9)
        self.status_label.setFont(status_font)
        self.status_label.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self.status_label)
        
        # Address
        addr_label = QLabel(f"{self.addr[0]}:{self.addr[1]}")
        addr_font = QFont("Consolas", 8)
        addr_font.setItalic(True)
        addr_label.setFont(addr_font)
        addr_label.setStyleSheet("color: #888888; background: transparent; border: none;")
        layout.addWidget(addr_label)
        
        # Messages
        self.messages_label = QLabel("Messages: 0")
        msg_font = QFont("Consolas", 8)
        self.messages_label.setFont(msg_font)
        self.messages_label.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self.messages_label)
        
        # Uptime
        self.uptime_label = QLabel("Uptime: 0s")
        uptime_font = QFont("Consolas", 8)
        self.uptime_label.setFont(uptime_font)
        self.uptime_label.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self.uptime_label)
        
        layout.addStretch()
        self.setLayout(layout)
        self.setMaximumHeight(150)
        self.setMinimumWidth(200)
    
    def update_status(self, status: DroneStatus):
        """Update drone status display"""
        self.status = status
        
        if status.connected:
            self.status_label.setText("● Connected")
            self.status_label.setStyleSheet("color: #00CC00; background: transparent; border: none;")
        else:
            self.status_label.setText("● Disconnected")
            self.status_label.setStyleSheet("color: #FF6666; background: transparent; border: none;")
        
        self.messages_label.setText(f"Messages: {status.message_count}")
        
        if status.first_message_time > 0:
            uptime = time.time() - status.first_message_time
            self.uptime_label.setText(f"Uptime: {uptime:.1f}s")
    
    def set_selected(self, selected: bool):
        """Set selection state"""
        self.selected = selected
        self.update_style()
    
    def update_style(self):
        """Update card style based on selection"""
        if self.selected:
            self.setStyleSheet(
                "QFrame { border: 3px solid #4499FF; background-color: #1A1A2E; border-radius: 5px; }"
            )
        else:
            self.setStyleSheet(
                "QFrame { border: 2px solid #444444; background-color: #0F0F1E; border-radius: 5px; }"
            )
    
    def mousePressEvent(self, event):
        """Handle mouse click"""
        self.clicked.emit(self.addr)


class OverviewTab(QWidget):
    """Overview tab showing all connected drones"""
    
    drone_selected = pyqtSignal(tuple)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.drone_cards = {}
        self.init_ui()
    
    def init_ui(self):
        """Initialize UI"""
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # Title
        title_label = QLabel("Connected Drones Overview")
        title_font = QFont("Consolas", 12, QFont.Bold)
        title_label.setFont(title_font)
        layout.addWidget(title_label)
        
        # Create scrollable area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("QScrollArea { border: none; }")
        
        # Container for drone cards
        container = QWidget()
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(10)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        container.setLayout(self.grid_layout)
        
        scroll_area.setWidget(container)
        layout.addWidget(scroll_area)
        
        self.setLayout(layout)
    
    def add_drone(self, addr: tuple, status: DroneStatus):
        """Add a new drone card"""
        card = DroneCard(addr, status)
        card.clicked.connect(self.on_drone_card_clicked)
        self.drone_cards[addr] = card
        
        # Calculate grid position (2 columns)
        row = len(self.drone_cards) - 1
        grid_row = row // 2
        grid_col = row % 2
        
        self.grid_layout.addWidget(card, grid_row, grid_col)
    
    def update_drone_status(self, addr: tuple, status: DroneStatus):
        """Update drone card status"""
        if addr in self.drone_cards:
            self.drone_cards[addr].update_status(status)
    
    def on_drone_card_clicked(self, addr: tuple):
        """Handle drone card click"""
        for card in self.drone_cards.values():
            card.set_selected(False)
        
        self.drone_cards[addr].set_selected(True)
        self.drone_selected.emit(addr)


class DetailTab(QWidget):
    """Detail tab showing comprehensive drone information"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_drone = None
        self.init_ui()
    
    def init_ui(self):
        """Initialize UI"""
        layout = QVBoxLayout()
        
        # Title
        self.title_label = QLabel("Drone Details")
        title_font = QFont("Consolas", 12, QFont.Bold)
        self.title_label.setFont(title_font)
        layout.addWidget(self.title_label)
        
        # Subtitle
        self.subtitle_label = QLabel("Select a drone from the overview to view details")
        subtitle_font = QFont("Consolas", 9)
        self.subtitle_label.setFont(subtitle_font)
        layout.addWidget(self.subtitle_label)
        
        # Tree widget
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Parameter", "Value"])
        self.tree.setFont(QFont("Consolas", 9))
        self.tree.setColumnWidth(0, 200)
        self.tree.setColumnWidth(1, 300)
        
        layout.addWidget(self.tree)
        self.setLayout(layout)
    
    def set_selected_drone(self, addr: tuple, status: DroneStatus):
        """Set the selected drone and display its details"""
        self.current_drone = addr
        self.display_drone_details(addr, status)
    
    def display_drone_details(self, addr: tuple, status: DroneStatus):
        """Display detailed information for a drone"""
        self.title_label.setText(f"Drone #{status.sysid} - Detailed Telemetry")
        self.subtitle_label.setText(f"Status: {'Connected' if status.connected else 'Disconnected'}")
        
        self.tree.clear()
        
        # System Information
        system_item = QTreeWidgetItem(self.tree, ["System Information", ""])
        system_font = QFont("Consolas", 10, QFont.Bold)
        system_item.setFont(0, system_font)
        system_item.setFont(1, system_font)
        
        QTreeWidgetItem(system_item, ["System ID", str(status.sysid)])
        QTreeWidgetItem(system_item, ["Component ID", str(status.compid)])
        QTreeWidgetItem(system_item, ["Connected", "Yes" if status.connected else "No"])
        QTreeWidgetItem(system_item, ["Connection Event", status.connection_event or "N/A"])
        QTreeWidgetItem(system_item, ["Armed Status", "Armed" if status.armed else "Disarmed"])
        QTreeWidgetItem(system_item, ["Flight Mode", status.mode])
        QTreeWidgetItem(system_item, ["System Status", status.system_status])
        
        # Network Information
        network_item = QTreeWidgetItem(self.tree, ["Network Information", ""])
        network_font = QFont("Consolas", 10, QFont.Bold)
        network_item.setFont(0, network_font)
        network_item.setFont(1, network_font)
        
        QTreeWidgetItem(network_item, ["IP Address", addr[0]])
        QTreeWidgetItem(network_item, ["Port", str(addr[1])])
        
        # Battery
        battery_item = QTreeWidgetItem(self.tree, ["Battery", ""])
        battery_font = QFont("Consolas", 10, QFont.Bold)
        battery_item.setFont(0, battery_font)
        battery_item.setFont(1, battery_font)
        
        QTreeWidgetItem(battery_item, ["Voltage", f"{status.battery_voltage:.2f}V"])
        QTreeWidgetItem(battery_item, ["Current", f"{status.battery_current:.2f}A"])
        QTreeWidgetItem(battery_item, ["Percentage", f"{status.battery_percent}%"])
        
        # GPS
        gps_item = QTreeWidgetItem(self.tree, ["GPS", ""])
        gps_font = QFont("Consolas", 10, QFont.Bold)
        gps_item.setFont(0, gps_font)
        gps_item.setFont(1, gps_font)
        
        QTreeWidgetItem(gps_item, ["Fix Type", self._get_gps_fix_name(status.gps_fix)])
        QTreeWidgetItem(gps_item, ["Satellites", str(status.gps_satellites)])
        QTreeWidgetItem(gps_item, ["Latitude", f"{status.latitude:.6f}"])
        QTreeWidgetItem(gps_item, ["Longitude", f"{status.longitude:.6f}"])
        
        # Position & Motion
        motion_item = QTreeWidgetItem(self.tree, ["Position & Motion", ""])
        motion_font = QFont("Consolas", 10, QFont.Bold)
        motion_item.setFont(0, motion_font)
        motion_item.setFont(1, motion_font)
        
        QTreeWidgetItem(motion_item, ["Altitude", f"{status.altitude:.2f}m"])
        QTreeWidgetItem(motion_item, ["Ground Speed", f"{status.groundspeed:.2f}m/s"])
        QTreeWidgetItem(motion_item, ["Heading", f"{status.heading:.1f}°"])
        
        # Attitude
        attitude_item = QTreeWidgetItem(self.tree, ["Attitude", ""])
        attitude_font = QFont("Consolas", 10, QFont.Bold)
        attitude_item.setFont(0, attitude_font)
        attitude_item.setFont(1, attitude_font)
        
        QTreeWidgetItem(attitude_item, ["Roll", f"{status.roll:.2f}°"])
        QTreeWidgetItem(attitude_item, ["Pitch", f"{status.pitch:.2f}°"])
        QTreeWidgetItem(attitude_item, ["Yaw", f"{status.yaw:.2f}°"])
        
        # Message Statistics
        stats_item = QTreeWidgetItem(self.tree, ["Message Statistics", ""])
        stats_font = QFont("Consolas", 10, QFont.Bold)
        stats_item.setFont(0, stats_font)
        stats_item.setFont(1, stats_font)
        
        QTreeWidgetItem(stats_item, ["Total Messages", str(status.message_count)])
        QTreeWidgetItem(stats_item, ["Last Message Type", status.last_message_type])
        
        if status.message_types:
            msg_types_str = ", ".join([f"{k}:{v}" for k, v in sorted(status.message_types.items())])
            QTreeWidgetItem(stats_item, ["Message Types", msg_types_str])
        
        if status.first_message_time > 0:
            uptime = time.time() - status.first_message_time
            QTreeWidgetItem(stats_item, ["Uptime", f"{uptime:.1f}s"])
        
        # Update Time
        time_item = QTreeWidgetItem(self.tree, ["Update Time", ""])
        time_font = QFont("Consolas", 10, QFont.Bold)
        time_item.setFont(0, time_font)
        time_item.setFont(1, time_font)
        
        QTreeWidgetItem(time_item, ["Last Update", status.last_update or "Never"])
        
        self.tree.expandAll()
    
    @staticmethod
    def _get_gps_fix_name(fix_type: int) -> str:
        """Convert GPS fix type to readable name"""
        gps_fix_names = {0: "No GPS", 1: "No Fix", 2: "2D Fix", 3: "3D Fix", 4: "DGPS Fix", 5: "RTK Fixed"}
        return gps_fix_names.get(fix_type, f"Unknown ({fix_type})")


class MAVLinkDashboard(QMainWindow):
    """Main dashboard window"""
    
    def __init__(self, server_host='0.0.0.0', server_port=5566):
        super().__init__()
        self.server_host = server_host
        self.server_port = server_port
        self.drone_statuses = {}
        self.server = None
        self.init_ui()
        self.start_server()
    
    def init_ui(self):
        """Initialize main UI"""
        self.setWindowTitle("MAVLink Server Dashboard (PyMAVLink)")
        self.setGeometry(100, 100, 1600, 800)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout()
        
        # Create splitter
        splitter = QSplitter(Qt.Horizontal)
        
        # Overview and Detail tabs
        self.overview_tab = OverviewTab()
        self.overview_tab.drone_selected.connect(self.on_drone_selected)
        
        self.detail_tab = DetailTab()
        
        # Add to splitter
        splitter.addWidget(self.overview_tab)
        splitter.addWidget(self.detail_tab)
        splitter.setSizes([640, 960])
        
        main_layout.addWidget(splitter)
        central_widget.setLayout(main_layout)
    
    def start_server(self):
        """Start MAVLink server"""
        self.server = MAVLinkServerThread(
            host=self.server_host,
            port=self.server_port,
            timeout=10
        )
        
        self.server.signal_emitter.drone_connected.connect(self.on_drone_connected)
        self.server.signal_emitter.drone_disconnected.connect(self.on_drone_disconnected)
        self.server.signal_emitter.drone_message_received.connect(self.on_message_received)
        
        self.server.start()
    
    def on_drone_connected(self, addr: tuple, sysid: int, compid: int):
        """Handle drone connection"""
        status = DroneStatus(
            addr=addr,
            sysid=sysid,
            compid=compid,
            connected=True,
            first_message_time=time.time(),
            last_heartbeat=time.time(),
            last_update=datetime.now().strftime("%H:%M:%S"),
            connection_event="CONNECTED"
        )
        
        self.drone_statuses[addr] = status
        self.overview_tab.add_drone(addr, status)
    
    def on_drone_disconnected(self, addr: tuple, sysid: int):
        """Handle drone disconnection"""
        if addr in self.drone_statuses:
            status = self.drone_statuses[addr]
            status.connected = False
            status.connection_event = "DISCONNECTED"
            status.last_update = datetime.now().strftime("%H:%M:%S")
            
            self.overview_tab.update_drone_status(addr, status)
            
            if self.detail_tab.current_drone == addr:
                self.detail_tab.display_drone_details(addr, status)
    
    def on_message_received(self, addr: tuple, status: DroneStatus):
        """Handle message received"""
        if addr in self.drone_statuses:
            self.drone_statuses[addr] = status
            self.overview_tab.update_drone_status(addr, status)
            
            if self.detail_tab.current_drone == addr:
                self.detail_tab.display_drone_details(addr, status)
    
    def on_drone_selected(self, addr: tuple):
        """Handle drone selection"""
        if addr in self.drone_statuses:
            status = self.drone_statuses[addr]
            self.detail_tab.set_selected_drone(addr, status)
    
    def closeEvent(self, event):
        """Handle window close"""
        if self.server:
            self.server.stop()
        event.accept()


def main():
    """Main application entry point"""
    app = QApplication(sys.argv)
    
    dashboard = MAVLinkDashboard(
        server_host='0.0.0.0',
        server_port=5566
    )
    dashboard.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()