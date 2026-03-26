#!/usr/bin/env python3
"""
PyQt5 Dashboard for MAVLink Server with PyMAVLink Packet Parsing and Analytics Charts
WITH INTEGRATED NETWORK ANALYTICS ENGINE AND LINE CHARTS
Fixed: Uses sysid as unique identifier to prevent duplicate drone cards
"""

import sys
import socket
import threading
import time
from datetime import datetime
from typing import Dict
from dataclasses import dataclass, field
from collections import deque

from pymavlink.dialects.v20 import ardupilotmega as mavlink

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QGridLayout, QScrollArea, QSplitter, QTreeWidget, QTreeWidgetItem, 
    QLineEdit, QTabWidget, QPushButton, QTableWidget, QTableWidgetItem
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QPainter
from PyQt5.QtChart import QChart, QChartView, QLineSeries, QValueAxis

# Import the AttitudeIndicator widget
from widgets import AttitudeIndicator

# ===== NEW IMPORTS FOR ANALYTICS =====
from analytics.engine import NetworkAnalyticsEngine
from capture.message import CapturedMessage
# =====================================


@dataclass
class DroneStatus:
    """Data class to hold drone status information"""
    sysid: int
    addr: tuple = None  # (ip, port) - can change, so not primary key
    compid: int = 0
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
    vertical_speed: float = 0.0  # Climb rate in m/s (positive = climbing)
    
    # Message type tracking
    last_message_type: str = ""
    message_types: Dict[str, int] = field(default_factory=dict)


class DroneStatusSignal(QObject):
    """Signal emitter for drone status updates"""
    drone_connected = pyqtSignal(int, int, int)  # sysid, compid, port
    drone_disconnected = pyqtSignal(int)         # sysid
    drone_message_received = pyqtSignal(int, DroneStatus)  # sysid, status
    status_updated = pyqtSignal(int, DroneStatus)
    
    # ===== NEW SIGNAL FOR ANALYTICS =====
    analytics_updated = pyqtSignal(dict)  # Emits {report_dict}
    # ====================================


class MAVLinkServerThread(threading.Thread):
    """MAVLink Server using PyMAVLink for packet parsing"""
    
    def __init__(self, host='0.0.0.0', port=5566, timeout=10):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.timeout = timeout
        self.socket = None
        self.running = False
        self.drones = {}  # {sysid: DroneStatus} - keyed by system ID
        self.parsers = {}  # {(ip, port): MAVLink parser}
        self.signal_emitter = DroneStatusSignal()
        
        # ===== NEW: ANALYTICS ENGINE INITIALIZATION =====
        self.analytics_engine = NetworkAnalyticsEngine(windows=[1, 10, 60])
        self.analytics_lock = threading.Lock()
        # ================================================
        
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
            
            # ===== NEW: START ANALYTICS THREAD =====
            self.analytics_thread = threading.Thread(
                target=self._analytics_loop,
                daemon=True
            )
            self.analytics_thread.start()
            # ========================================
            
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
            # Initialize parser for this address if needed
            if addr not in self.parsers:
                self.parsers[addr] = mavlink.MAVLink(None, False)
            
            parser = self.parsers[addr]
            
            # Parse the packet byte by byte using pymavlink
            for byte in data:
                msg = parser.parse_char(bytes([byte]))
                
                if msg:
                    # ===== NEW: GET HIGH-RESOLUTION TIMESTAMPS =====
                    capture_time_ns = int(time.time_ns())
                    capture_time_us = int(time.time() * 1e6)
                    
                    # Extract message metadata
                    sysid = msg.get_srcSystem()
                    compid = msg.get_srcComponent()
                    msg_type = msg.get_type()
                    msg_id = msg.get_msgId()
                    
                    # Extract sequence number (if available)
                    msg_seq = 0
                    if hasattr(msg, 'seq'):
                        msg_seq = msg.seq
                    
                    # CREATE CapturedMessage FOR ANALYTICS
                    captured = CapturedMessage(
                        timestamp_ns=capture_time_ns,
                        timestamp_us=capture_time_us,
                        src_addr=addr,
                        src_sysid=sysid,
                        src_compid=compid,
                        msg_id=msg_id,
                        msg_name=msg_type,
                        msg_seq=msg_seq,
                        payload_len=len(data),
                        raw_bytes=data,
                    )
                    
                    # FEED TO ANALYTICS ENGINE (THREAD-SAFE)
                    with self.analytics_lock:
                        self.analytics_engine.process_message(captured)
                    # ==========================================
                    
                    # Check if this is a new drone (by sysid, not addr)
                    if sysid not in self.drones:
                        self._drone_connected(sysid, compid, addr, msg_type)
                    else:
                        # Update existing drone
                        self._update_drone_status(sysid, addr, msg, msg_type)
                    
        except Exception:
            # Silently ignore parsing errors
            pass
    
    def _drone_connected(self, sysid, compid, addr, first_msg_type):
        """Handle new drone connection"""
        status = DroneStatus(
            sysid=sysid,
            addr=addr,
            compid=compid,
            connected=True,
            first_message_time=time.time(),
            last_heartbeat=time.time(),
            last_update=datetime.now().strftime("%H:%M:%S"),
            connection_event="CONNECTED",
            last_message_type=first_msg_type
        )
        
        self.drones[sysid] = status
        self.signal_emitter.drone_connected.emit(sysid, compid, addr[1])
        self.signal_emitter.drone_message_received.emit(sysid, status)
        print(f"✓ DRONE CONNECTED: {addr[0]}:{addr[1]} (SysID: {sysid}, First Msg: {first_msg_type})")
    
    def _update_drone_status(self, sysid, addr, msg, msg_type):
        """Update drone status from MAVLink message"""
        status = self.drones[sysid]
        status.addr = addr  # Update address in case it changed (new port)
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
        except Exception:
            pass
        
        self.signal_emitter.drone_message_received.emit(sysid, status)
    
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
            status.altitude = msg.alt / 1000.0
            status.gps_fix = msg.fix_type
            status.gps_satellites = msg.satellites_visible
        except Exception as e:
            print(f"Error parsing GPS: {e}")
    
    def _parse_global_position(self, status, msg):
        """Parse GLOBAL_POSITION_INT message"""
        try:
            status.latitude = msg.lat / 1e7
            status.longitude = msg.lon / 1e7
            status.altitude = msg.alt / 1000.0
            status.groundspeed = (msg.vx**2 + msg.vy**2)**0.5 / 100.0
            status.heading = msg.hdg / 100.0
        except Exception as e:
            print(f"Error parsing GLOBAL_POSITION: {e}")
    
    def _parse_vfr_hud(self, status, msg):
        """Parse VFR_HUD message"""
        try:
            status.groundspeed = msg.groundspeed
            status.altitude = msg.alt
            status.heading = msg.heading
            status.vertical_speed = msg.climb
        except Exception as e:
            print(f"Error parsing VFR_HUD: {e}")
    
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
        
        for sysid, status in list(self.drones.items()):
            if current_time - status.last_heartbeat > self.timeout:
                disconnected.append(sysid)
        
        for sysid in disconnected:
            status = self.drones.pop(sysid)
            status.connected = False
            status.connection_event = "DISCONNECTED"
            status.last_update = datetime.now().strftime("%H:%M:%S")
            
            # Clean up parsers for this drone's address
            if status.addr in self.parsers:
                del self.parsers[status.addr]
            
            self.signal_emitter.drone_disconnected.emit(sysid)
            print(f"✗ DRONE DISCONNECTED: SysID {sysid} ({status.addr[0]}:{status.addr[1]})")
    
    # ===== NEW: ANALYTICS LOOP METHOD =====
    def _analytics_loop(self):
        """Periodic analytics reporter (every 500ms)"""
        print("✓ Analytics thread started")
        while self.running:
            try:
                # Get metrics with thread-safe lock
                with self.analytics_lock:
                    report = self.analytics_engine.get_report_summary(window_s=1)
                
                # Emit signal to UI
                self.signal_emitter.analytics_updated.emit(report)
                
                # Update every 500ms
                time.sleep(0.5)
            except Exception as e:
                print(f"Analytics update error: {e}")
    # ======================================
    
    def stop(self):
        """Stop the server"""
        self.running = False
        if self.socket:
            self.socket.close()


class DroneCard(QFrame):
    """Widget displaying drone status as a card with attitude indicator"""
    
    clicked = pyqtSignal(int)  # sysid
    
    def __init__(self, sysid: int, status: DroneStatus, parent=None):
        super().__init__(parent)
        self.sysid = sysid
        self.status = status
        self.selected = False
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Plain)
        self.setLineWidth(2)
        self.setCursor(Qt.PointingHandCursor)
        self.init_ui()
        self.update_style()
    
    def init_ui(self):
        """Initialize UI"""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(4)
        
        # Top section - Info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)
        
        # Drone ID
        drone_label = QLabel(f"Drone #{self.status.sysid}")
        drone_font = QFont("Consolas", 9, QFont.Bold)
        drone_label.setFont(drone_font)
        drone_label.setStyleSheet("color: #888888; background: transparent; border: none;")
        info_layout.addWidget(drone_label)
        
        # Connection status
        self.status_label = QLabel("● Connecting...")
        status_font = QFont("Consolas", 7)
        self.status_label.setFont(status_font)
        self.status_label.setStyleSheet("background: transparent; border: none;")
        info_layout.addWidget(self.status_label)
        
        # Address
        addr_text = f"{self.status.addr[0]}:{self.status.addr[1]}" if self.status.addr else "N/A"
        self.addr_label = QLabel(addr_text)
        addr_font = QFont("Consolas", 7)
        addr_font.setItalic(True)
        self.addr_label.setFont(addr_font)
        self.addr_label.setStyleSheet("color: #888888; background: transparent; border: none;")
        info_layout.addWidget(self.addr_label)
        
        # Messages and Uptime in horizontal layout
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(10)
        
        self.messages_label = QLabel("Messages: 0")
        msg_font = QFont("Consolas", 7)
        self.messages_label.setFont(msg_font)
        self.messages_label.setStyleSheet("background: transparent; border: none;")
        stats_layout.addWidget(self.messages_label)
        
        self.uptime_label = QLabel("Uptime: 0s")
        uptime_font = QFont("Consolas", 7)
        self.uptime_label.setFont(uptime_font)
        self.uptime_label.setStyleSheet("background: transparent; border: none;")
        stats_layout.addWidget(self.uptime_label)
        stats_layout.addStretch()
        
        info_layout.addLayout(stats_layout)
        main_layout.addLayout(info_layout)
        
        # Middle section - Attitude Indicator only
        self.attitude_indicator = AttitudeIndicator(parent=self)
        main_layout.addWidget(self.attitude_indicator)
        
        # Bottom section - Attitude values
        attitude_layout = QVBoxLayout()
        attitude_layout.setSpacing(2)
        
        self.roll_label = QLabel(f"Roll: {self.status.roll:.1f}°")
        roll_font = QFont("Consolas", 6)
        self.roll_label.setFont(roll_font)
        self.roll_label.setStyleSheet("background: transparent; border: none;")
        attitude_layout.addWidget(self.roll_label)
        
        self.pitch_label = QLabel(f"Pitch: {self.status.pitch:.1f}°")
        pitch_font = QFont("Consolas", 6)
        self.pitch_label.setFont(pitch_font)
        self.pitch_label.setStyleSheet("background: transparent; border: none;")
        attitude_layout.addWidget(self.pitch_label)
        
        self.yaw_label = QLabel(f"Yaw: {self.status.yaw:.1f}°")
        yaw_font = QFont("Consolas", 6)
        self.yaw_label.setFont(yaw_font)
        self.yaw_label.setStyleSheet("background: transparent; border: none;")
        attitude_layout.addWidget(self.yaw_label)
        
        main_layout.addLayout(attitude_layout)
        
        self.setLayout(main_layout)
        self.setMinimumHeight(280)
        self.setMinimumWidth(350)
    
    def update_status(self, status: DroneStatus):
        """Update drone status display"""
        self.status = status
        
        if status.connected:
            self.status_label.setText("● Connected")
            self.status_label.setStyleSheet("color: #00CC00; background: transparent; border: none;")
        else:
            self.status_label.setText("● Disconnected")
            self.status_label.setStyleSheet("color: #FF6666; background: transparent; border: none;")
        
        # Update address if it changed (drone reconnected on different port)
        if status.addr:
            addr_text = f"{status.addr[0]}:{status.addr[1]}"
            self.addr_label.setText(addr_text)
        
        self.messages_label.setText(f"Messages: {status.message_count}")
        
        if status.first_message_time > 0:
            uptime = time.time() - status.first_message_time
            self.uptime_label.setText(f"Uptime: {uptime:.1f}s")
        
        # Update attitude indicator with telemetry data
        self.roll_label.setText(f"Roll: {status.roll:.1f}°")
        self.pitch_label.setText(f"Pitch: {status.pitch:.1f}°")
        self.yaw_label.setText(f"Yaw: {status.yaw:.1f}°")
        self.attitude_indicator.set_attitude(status.pitch, status.roll, status.altitude, status.groundspeed)
    
    def set_selected(self, selected: bool):
        """Set selection state"""
        self.selected = selected
        self.update_style()
    
    def update_style(self):
        """Update card style based on selection"""
        if self.selected:
            self.setStyleSheet(
                "QFrame { border: 3px solid #4499FF; background-color: #ded5d6; border-radius: 5px; }"
            )
        else:
            self.setStyleSheet(
                "QFrame { border: 2px solid #444444; background-color: #ded5d6; border-radius: 5px; }"
            )
    
    def mousePressEvent(self, event):
        """Handle mouse click"""
        self.clicked.emit(self.sysid)


class OverviewTab(QWidget):
    """Overview tab showing all connected drones"""
    
    drone_selected = pyqtSignal(int)  # sysid
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.drone_cards = {}  # {sysid: DroneCard} - keyed by sysid
        self.init_ui()
    
    def init_ui(self):
        """Initialize UI"""
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # Title and Reference Altitude (Horizontal Layout)
        title_layout = QHBoxLayout()
        title_layout.setSpacing(15)
        
        # Title
        title_label = QLabel("Connected Drones Overview")
        title_font = QFont("Consolas", 12, QFont.Bold)
        title_label.setFont(title_font)
        title_layout.addWidget(title_label)
        
        # Reference Altitude Label
        ref_alt_label = QLabel("Reference Altitude (m):")
        ref_alt_font = QFont("Consolas", 9)
        ref_alt_label.setFont(ref_alt_font)
        title_layout.addWidget(ref_alt_label)
        
        # Reference Altitude Input
        self.reference_altitude = QLineEdit()
        self.reference_altitude.setText("0.0")
        self.reference_altitude.setMaximumWidth(100)
        self.reference_altitude.setFont(QFont("Consolas", 9))
        self.reference_altitude.setStyleSheet(
            "QLineEdit { background-color: #2A2A3E; color: #00CC00; border: 1px solid #444444; padding: 5px; }"
        )
        title_layout.addWidget(self.reference_altitude)
        title_layout.addStretch()
        
        layout.addLayout(title_layout)
        
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
    
    def add_drone(self, sysid: int, status: DroneStatus):
        """Add a new drone card"""
        card = DroneCard(sysid, status)
        card.clicked.connect(self.on_drone_card_clicked)
        self.drone_cards[sysid] = card
        
        # Calculate grid position (2 columns)
        row = len(self.drone_cards) - 1
        grid_row = row // 2
        grid_col = row % 2
        
        self.grid_layout.addWidget(card, grid_row, grid_col)
    
    def remove_drone(self, sysid: int):
        """Remove a drone card from the overview"""
        if sysid in self.drone_cards:
            card = self.drone_cards.pop(sysid)
            card.setParent(None)
            card.deleteLater()
    
    def update_drone_status(self, sysid: int, status: DroneStatus):
        """Update drone card status"""
        if sysid in self.drone_cards:
            self.drone_cards[sysid].update_status(status)
    
    def on_drone_card_clicked(self, sysid: int):
        """Handle drone card click"""
        for card in self.drone_cards.values():
            card.set_selected(False)
        
        self.drone_cards[sysid].set_selected(True)
        self.drone_selected.emit(sysid)


class DetailTab(QWidget):
    """Detail tab showing comprehensive drone information"""
    
    def __init__(self, overview_tab=None, parent=None):
        super().__init__(parent)
        self.current_drone = None
        self.overview_tab = overview_tab
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
    
    def set_selected_drone(self, sysid: int, status: DroneStatus):
        """Set the selected drone and display its details"""
        self.current_drone = sysid
        self.display_drone_details(sysid, status)
    
    def display_drone_details(self, sysid: int, status: DroneStatus):
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
        
        if status.addr:
            QTreeWidgetItem(network_item, ["IP Address", status.addr[0]])
            QTreeWidgetItem(network_item, ["Port", str(status.addr[1])])
        else:
            QTreeWidgetItem(network_item, ["IP Address", "N/A"])
            QTreeWidgetItem(network_item, ["Port", "N/A"])
        
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
        
        # Altitude Information
        altitude_item = QTreeWidgetItem(self.tree, ["Altitude Information", ""])
        altitude_font = QFont("Consolas", 10, QFont.Bold)
        altitude_item.setFont(0, altitude_font)
        altitude_item.setFont(1, altitude_font)
        
        QTreeWidgetItem(altitude_item, ["Absolute Altitude", f"{status.altitude:.2f}m"])
        
        # Relative altitude
        ref_alt = 0.0
        if self.overview_tab:
            try:
                ref_alt = float(self.overview_tab.reference_altitude.text())
                ref_alt = status.altitude - ref_alt
            except (ValueError, AttributeError):
                ref_alt = 0.0
        
        relative_altitude = status.altitude - ref_alt
        QTreeWidgetItem(altitude_item, ["Reference Altitude", f"{ref_alt:.2f}m"])
        QTreeWidgetItem(altitude_item, ["Relative Altitude", f"{relative_altitude:.2f}m"])
        
        # Altitude status indicator
        altitude_status = "Valid" if status.altitude > 0 else "No Data"
        QTreeWidgetItem(altitude_item, ["Altitude Status", altitude_status])
        
        # Altitude in feet
        altitude_feet = status.altitude * 3.28084
        QTreeWidgetItem(altitude_item, ["Altitude (Feet)", f"{altitude_feet:.2f}ft"])
        
        # Vertical Speed
        climb_direction = "↑ Climbing" if status.vertical_speed > 0.1 else "↓ Descending" if status.vertical_speed < -0.1 else "→ Level"
        QTreeWidgetItem(altitude_item, ["Climb Rate", f"{status.vertical_speed:.2f}m/s {climb_direction}"])
        
        # Altitude source
        QTreeWidgetItem(altitude_item, ["Altitude Source", "Barometer"])
        
        # Speed Information
        speed_item = QTreeWidgetItem(self.tree, ["Speed Information", ""])
        speed_font = QFont("Consolas", 10, QFont.Bold)
        speed_item.setFont(0, speed_font)
        speed_item.setFont(1, speed_font)
        
        QTreeWidgetItem(speed_item, ["Ground Speed (m/s)", f"{status.groundspeed:.2f}"])
        speed_kmh = status.groundspeed * 3.6
        speed_knots = status.groundspeed * 1.94384
        QTreeWidgetItem(speed_item, ["Ground Speed (km/h)", f"{speed_kmh:.2f}"])
        QTreeWidgetItem(speed_item, ["Ground Speed (knots)", f"{speed_knots:.2f}"])
        QTreeWidgetItem(speed_item, ["Heading", f"{status.heading:.1f}°"])
        
        # Speed status indicator
        speed_status = "Moving" if status.groundspeed > 0.5 else "Stationary"
        QTreeWidgetItem(speed_item, ["Speed Status", speed_status])

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


# ===== NEW: ANALYTICS TAB WIDGET WITH CHARTS =====
class AnalyticsTab(QWidget):
    """Real-time network analytics dashboard with line charts"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_window_s = 1
        
        # History storage for charts (keep last 60 seconds)
        self.traffic_history = deque(maxlen=60)
        self.loss_history = deque(maxlen=60)
        self.latency_history = deque(maxlen=60)
        
        self.init_ui()
    
    def init_ui(self):
        """Initialize UI with metrics display and charts"""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # Title
        title = QLabel("Network Analytics Dashboard")
        title_font = QFont("Consolas", 12, QFont.Bold)
        title.setFont(title_font)
        main_layout.addWidget(title)
        
        # Window selector buttons
        window_layout = QHBoxLayout()
        self.window_buttons = {}
        for window_s in [1, 10, 60]:
            btn = QPushButton(f"{window_s}s Window")
            btn.clicked.connect(lambda checked, w=window_s: self.set_window(w))
            btn.setMaximumWidth(120)
            self.window_buttons[window_s] = btn
            window_layout.addWidget(btn)
        window_layout.addStretch()
        main_layout.addLayout(window_layout)
        
        # ===== METRICS SECTION =====
        # Analytics grid (3 columns)
        grid_layout = QGridLayout()
        grid_layout.setSpacing(10)
        
        # Row 0: TRAFFIC TITLE
        traffic_title = QLabel("Traffic Metrics")
        traffic_font = QFont("Consolas", 10, QFont.Bold)
        traffic_title.setFont(traffic_font)
        grid_layout.addWidget(traffic_title, 0, 0, 1, 3)
        
        # Row 1: TRAFFIC METRICS
        self.msg_rate_label = QLabel("Message Rate: -- msg/s")
        self.bytes_rate_label = QLabel("Bytes Rate: -- bytes/s")
        self.msg_type_label = QLabel("Message Types: --")
        
        metric_font = QFont("Consolas", 9)
        for label in [self.msg_rate_label, self.bytes_rate_label, self.msg_type_label]:
            label.setFont(metric_font)
        
        grid_layout.addWidget(self.msg_rate_label, 1, 0)
        grid_layout.addWidget(self.bytes_rate_label, 1, 1)
        grid_layout.addWidget(self.msg_type_label, 1, 2)
        
        # Row 2: LATENCY TITLE
        latency_title = QLabel("Latency Metrics (Inter-Message Time)")
        latency_font = QFont("Consolas", 10, QFont.Bold)
        latency_title.setFont(latency_font)
        grid_layout.addWidget(latency_title, 2, 0, 1, 3)
        
        # Row 3: LATENCY METRICS
        self.imt_mean_label = QLabel("Mean IMT: -- ms")
        self.imt_stdev_label = QLabel("StDev IMT: -- ms")
        self.imt_p95_label = QLabel("P95 IMT: -- ms")
        
        for label in [self.imt_mean_label, self.imt_stdev_label, self.imt_p95_label]:
            label.setFont(metric_font)
        
        grid_layout.addWidget(self.imt_mean_label, 3, 0)
        grid_layout.addWidget(self.imt_stdev_label, 3, 1)
        grid_layout.addWidget(self.imt_p95_label, 3, 2)
        
        # Row 4: LOSS TITLE
        loss_title = QLabel("Message Loss Detection")
        loss_font = QFont("Consolas", 10, QFont.Bold)
        loss_title.setFont(loss_font)
        grid_layout.addWidget(loss_title, 4, 0, 1, 3)
        
        # Row 5: LOSS METRICS
        self.loss_rate_label = QLabel("Loss Rate: -- %")
        self.loss_count_label = QLabel("Lost Messages: --")
        self.loss_events_label = QLabel("Loss Events: --")
        
        for label in [self.loss_rate_label, self.loss_count_label, self.loss_events_label]:
            label.setFont(metric_font)
        
        grid_layout.addWidget(self.loss_rate_label, 5, 0)
        grid_layout.addWidget(self.loss_count_label, 5, 1)
        grid_layout.addWidget(self.loss_events_label, 5, 2)
        
        main_layout.addLayout(grid_layout)
        
        # ===== CHARTS SECTION =====
        charts_title = QLabel("Historical Trends (Last 60 Seconds)")
        charts_title_font = QFont("Consolas", 10, QFont.Bold)
        charts_title.setFont(charts_title_font)
        main_layout.addWidget(charts_title)
        
        # Create charts
        charts_grid = QGridLayout()
        charts_grid.setSpacing(10)
        
        # Traffic chart
        self.traffic_chart_view = self.create_line_chart("Message Rate (msg/s)", "Time (s)")
        charts_grid.addWidget(self.traffic_chart_view, 0, 0)
        
        # Loss chart
        self.loss_chart_view = self.create_line_chart("Loss Rate (%)", "Time (s)")
        charts_grid.addWidget(self.loss_chart_view, 0, 1)
        
        # Latency chart
        self.latency_chart_view = self.create_line_chart("Latency (ms)", "Time (s)")
        charts_grid.addWidget(self.latency_chart_view, 1, 0, 1, 2)
        
        main_layout.addLayout(charts_grid)
        
        self.setLayout(main_layout)
    
    def create_line_chart(self, title: str, x_axis: str) -> QChartView:
        """Create a line chart view"""
        chart = QChart()
        chart.setTitle(title)
        chart.setAnimationOptions(QChart.SeriesAnimations)
        
        # Create series
        series = QLineSeries()
        series.setName("Metric")
        chart.addSeries(series)
        
        # X axis
        x_axis_obj = QValueAxis()
        x_axis_obj.setTitleText(x_axis)
        x_axis_obj.setRange(0, 60)
        chart.addAxis(x_axis_obj, Qt.AlignBottom)
        series.attachAxis(x_axis_obj)
        
        # Y axis
        y_axis_obj = QValueAxis()
        y_axis_obj.setTitleText(title)
        chart.addAxis(y_axis_obj, Qt.AlignLeft)
        series.attachAxis(y_axis_obj)
        
        chart_view = QChartView(chart)
        chart_view.setRenderHint(QPainter.Antialiasing)
        
        # Store references
        if "Message Rate" in title:
            self.traffic_series = series
            self.traffic_y_axis = y_axis_obj
        elif "Loss Rate" in title:
            self.loss_series = series
            self.loss_y_axis = y_axis_obj
        elif "Latency" in title:
            self.latency_series = series
            self.latency_y_axis = y_axis_obj
        
        return chart_view
    
    def set_window(self, window_s: int):
        """Change active window"""
        self.current_window_s = window_s
        # Highlight active button
        for w, btn in self.window_buttons.items():
            btn.setStyleSheet(
                "background-color: #4499FF; color: white; font-weight: bold;"
                if w == window_s else ""
            )
    
    def update_analytics(self, report: dict):
        """Update display with new analytics report"""
        try:
            # Extract sections
            traffic = report.get('traffic', {})
            latency = report.get('latency', {})
            loss = report.get('loss', {})
            
            # Update traffic metrics
            msg_rate = traffic.get('msg_rate', 0)
            bytes_rate = traffic.get('bytes_rate', 0)
            msg_types = traffic.get('unique_msg_types', 0)
            
            self.msg_rate_label.setText(f"Message Rate: {msg_rate:.1f} msg/s")
            self.bytes_rate_label.setText(f"Bytes Rate: {bytes_rate:.0f} bytes/s")
            self.msg_type_label.setText(f"Message Types: {msg_types}")
            
            # Update latency metrics
            imt = latency.get('inter_message_time_ms', {})
            mean_imt = imt.get('mean', 0)
            stdev_imt = imt.get('stdev', 0)
            p95_imt = imt.get('p95', 0)
            
            self.imt_mean_label.setText(f"Mean IMT: {mean_imt:.2f} ms")
            self.imt_stdev_label.setText(f"StDev IMT: {stdev_imt:.2f} ms")
            self.imt_p95_label.setText(f"P95 IMT: {p95_imt:.2f} ms")
            
            # Update loss metrics
            loss_rate = loss.get('loss_rate_pct', 0)
            lost_count = loss.get('total_lost', 0)
            loss_events = loss.get('loss_events_count', 0)
            
            self.loss_rate_label.setText(f"Loss Rate: {loss_rate:.2f} %")
            self.loss_count_label.setText(f"Lost Messages: {lost_count}")
            self.loss_events_label.setText(f"Loss Events: {loss_events}")
            
            # Apply color coding for alerts
            if loss_rate > 1.0:
                self.loss_rate_label.setStyleSheet("color: #FF6666;")
            else:
                self.loss_rate_label.setStyleSheet("")
            
            if stdev_imt > 50:
                self.imt_stdev_label.setStyleSheet("color: #FFB366;")
            else:
                self.imt_stdev_label.setStyleSheet("")
            
            # ===== UPDATE CHARTS DATA =====
            self.update_charts_data(report)
                
        except Exception as e:
            print(f"Error updating analytics: {e}")
    
    def update_charts_data(self, report: dict):
        """Update chart data with new metrics"""
        try:
            traffic = report.get('traffic', {})
            loss = report.get('loss', {})
            latency = report.get('latency', {})
            
            msg_rate = traffic.get('msg_rate', 0.0)
            loss_rate = loss.get('loss_rate_pct', 0.0)
            
            imt = latency.get('inter_message_time_ms', {})
            latency_mean = imt.get('mean', 0.0)
            
            # Store in history
            self.traffic_history.append(msg_rate)
            self.loss_history.append(loss_rate)
            self.latency_history.append(latency_mean)
            
            # Update traffic series
            self.traffic_series.clear()
            for i, value in enumerate(self.traffic_history):
                self.traffic_series.append(i, value)
            
            # Update loss series
            self.loss_series.clear()
            for i, value in enumerate(self.loss_history):
                self.loss_series.append(i, value)
            
            # Update latency series
            self.latency_series.clear()
            for i, value in enumerate(self.latency_history):
                self.latency_series.append(i, value)
            
            # Auto-scale Y axes
            if self.traffic_history:
                max_traffic = max(self.traffic_history) if self.traffic_history else 100
                self.traffic_y_axis.setRange(0, max(100, max_traffic * 1.2))
            
            if self.loss_history and any(self.loss_history):
                max_loss = max(self.loss_history)
                self.loss_y_axis.setRange(0, max(1, max_loss * 1.2))
            
            if self.latency_history:
                max_latency = max(self.latency_history) if self.latency_history else 100
                self.latency_y_axis.setRange(0, max(100, max_latency * 1.2))
        
        except Exception as e:
            print(f"Error updating charts: {e}")
# ====================================


class MAVLinkDashboard(QMainWindow):
    """Main dashboard window"""
    
    def __init__(self, server_host='0.0.0.0', server_port=5566):
        super().__init__()
        self.server_host = server_host
        self.server_port = server_port
        self.drone_statuses = {}  # {sysid: DroneStatus} - keyed by sysid
        self.server = None
        self.init_ui()
        self.start_server()
    
    def init_ui(self):
        """Initialize main UI with tabs"""
        self.setWindowTitle("MAVLink Server Dashboard (PyMAVLink)")
        self.setGeometry(100, 100, 1600, 1000)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout()
        
        # Create main splitter (LEFT / RIGHT)
        splitter = QSplitter(Qt.Horizontal)

        # LEFT: Overview
        self.overview_tab = OverviewTab()
        splitter.addWidget(self.overview_tab)

        # RIGHT: Tabs (Detail + Analytics)
        right_tabs = QTabWidget()

        self.detail_tab = DetailTab(overview_tab=self.overview_tab)
        self.analytics_tab = AnalyticsTab()

        right_tabs.addTab(self.detail_tab, "Details")
        right_tabs.addTab(self.analytics_tab, "Analytics")

        splitter.addWidget(right_tabs)

        # Optional: set initial size ratio
        splitter.setStretchFactor(0, 2)  # Overview wider
        splitter.setStretchFactor(1, 3)

        main_layout.addWidget(splitter)
        
        central_widget.setLayout(main_layout)

        self.overview_tab.drone_selected.connect(self.on_drone_selected)
    
    def start_server(self):
        """Start MAVLink server"""
        self.server = MAVLinkServerThread(
            host=self.server_host,
            port=self.server_port,
            timeout=10
        )
        
        # ===== CONNECT SIGNALS =====
        self.server.signal_emitter.drone_connected.connect(self.on_drone_connected)
        self.server.signal_emitter.drone_disconnected.connect(self.on_drone_disconnected)
        self.server.signal_emitter.drone_message_received.connect(self.on_message_received)
        self.server.signal_emitter.analytics_updated.connect(self.on_analytics_updated)  # NEW
        # ===========================
        
        self.server.start()
    
    def on_drone_connected(self, sysid: int, compid: int, port: int):
        """Handle drone connection"""
        # Check if drone already exists (reconnection)
        if sysid in self.drone_statuses:
            status = self.drone_statuses[sysid]
            status.connected = True
            status.connection_event = "RECONNECTED"
            self.overview_tab.update_drone_status(sysid, status)
            print(f"✓ DRONE RECONNECTED: SysID {sysid} on new port {port}")
        else:
            # New drone
            status = DroneStatus(
                sysid=sysid,
                compid=compid,
                connected=True,
                first_message_time=time.time(),
                last_heartbeat=time.time(),
                last_update=datetime.now().strftime("%H:%M:%S"),
                connection_event="CONNECTED"
            )
            self.drone_statuses[sysid] = status
            self.overview_tab.add_drone(sysid, status)
            print(f"✓ NEW DRONE CONNECTED: SysID {sysid}")
    
    def on_drone_disconnected(self, sysid: int):
        """Handle drone disconnection"""
        if sysid in self.drone_statuses:
            status = self.drone_statuses[sysid]
            status.connected = False
            status.connection_event = "DISCONNECTED"
            status.last_update = datetime.now().strftime("%H:%M:%S")
            
            self.overview_tab.update_drone_status(sysid, status)
            
            if self.detail_tab.current_drone == sysid:
                self.detail_tab.display_drone_details(sysid, status)
            
            print(f"✗ DRONE DISCONNECTED: SysID {sysid}")
    
    def on_message_received(self, sysid: int, status: DroneStatus):
        """Handle message received"""
        if sysid in self.drone_statuses:
            self.drone_statuses[sysid] = status
            self.overview_tab.update_drone_status(sysid, status)
            
            if self.detail_tab.current_drone == sysid:
                self.detail_tab.display_drone_details(sysid, status)
    
    def on_drone_selected(self, sysid: int):
        """Handle drone selection"""
        if sysid in self.drone_statuses:
            status = self.drone_statuses[sysid]
            self.detail_tab.set_selected_drone(sysid, status)
    
    # ===== NEW: ANALYTICS SIGNAL HANDLER =====
    def on_analytics_updated(self, report: dict):
        """Handle analytics update signal from server"""
        self.analytics_tab.update_analytics(report)
    # ========================================
    
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