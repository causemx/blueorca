import sys
import json
import threading
import time
from datetime import datetime
from typing import Dict, List
from dataclasses import dataclass, asdict

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QGridLayout, QLabel, QScrollArea, QFrame, QTableWidget,
    QTableWidgetItem, QHeaderView, QSplitter, QTreeWidget, QTreeWidgetItem
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QTimer, QSize
from PyQt5.QtGui import QColor, QFont, QBrush

from control import DroneNode, FlightMode


@dataclass
class DroneStatus:
    """Data class to hold drone status information"""
    system_id: int
    connected: bool = False
    armed: bool = False
    mode: str = "UNKNOWN"
    battery_percentage: int = 0
    battery_voltage: int = 0
    gps_fix: int = 0
    gps_satellites: int = 0
    altitude: float = 0.0
    groundspeed: float = 0.0
    heading: float = 0.0
    lat: float = 0.0
    lon: float = 0.0
    system_status: str = "UNKNOWN"
    last_update: str = ""
    connection_changed: bool = False  # Flag to indicate connection status changed
    connection_event: str = ""  # "CONNECTED" or "DISCONNECTED"
    activate: bool = True  # True = heartbeat received, False = no heartbeat for 5 seconds
    
    # Drone Parameters (Configuration)
    params: Dict[str, any] = None  # Will hold all drone parameters


class DroneStatusSignal(QObject):
    """Signal emitter for drone status updates"""
    status_updated = pyqtSignal(int, DroneStatus)


class DroneMonitor:
    """Manages drone connections and status updates"""
    
    def __init__(self, connection_strings: Dict[int, str]):
        self.drones: Dict[int, DroneNode] = {}
        self.statuses: Dict[int, DroneStatus] = {}
        self.previous_connected: Dict[int, bool] = {}  # Track previous connection state
        self.signal_emitter = DroneStatusSignal()
        self.monitoring = False
        self.monitor_thread = None
        
        # Update rate configuration (in seconds)
        self.update_interval = 0.5  # Default: 0.5 seconds (2 Hz)
        # Common values:
        # 0.2 (5 Hz) - Very fast, high CPU usage
        # 0.33 (3 Hz) - Fast updates
        # 0.5 (2 Hz) - Balanced (default)
        # 1.0 (1 Hz) - Slow, lower CPU usage
        # 2.0 (0.5 Hz) - Very slow
        
        # Initialize drones
        for system_id, conn_str in connection_strings.items():
            self.drones[system_id] = DroneNode(conn_str)
            self.statuses[system_id] = DroneStatus(system_id=system_id)
            self.previous_connected[system_id] = False  # Initially disconnected
    
    def start_monitoring(self):
        """Start monitoring all drone connections"""
        if not self.monitoring:
            self.monitoring = True
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()
    
    def set_update_interval(self, interval: float):
        """
        Set the monitoring update interval (in seconds)
        
        Args:
            interval (float): Time in seconds between updates
            
        Common values:
            0.2 (5 Hz) - Very fast, high CPU usage
            0.33 (3 Hz) - Fast updates
            0.5 (2 Hz) - Balanced (default)
            1.0 (1 Hz) - Slow, lower CPU usage
            2.0 (0.5 Hz) - Very slow
            
        Example:
            monitor.set_update_interval(1.0)  # Update once per second
        """
        if interval < 0.1:
            print("Warning: Update interval < 0.1s may cause high CPU usage")
        if interval > 10:
            print("Warning: Update interval > 10s may miss time-sensitive updates")
        
        self.update_interval = interval
        print(f"Update interval set to {interval}s ({1/interval:.2f} Hz)")
    
    def get_update_interval(self) -> float:
        """Get the current monitoring update interval in seconds"""
        return self.update_interval
    
    def stop_monitoring(self):
        """Stop monitoring and disconnect all drones"""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join()
        
        for drone in self.drones.values():
            drone.cleanup()
    
    def _monitor_loop(self):
        """Background thread to monitor drone status"""
        while self.monitoring:
            for system_id, drone in self.drones.items():
                try:
                    if not drone.drone:
                        # Try to connect
                        if drone.connect():
                            pass
                    else:
                        # Update status from drone
                        status_dict = drone.get_drone_status()
                        status = self._parse_drone_status(system_id, status_dict)
                        self.statuses[system_id] = status
                        self.signal_emitter.status_updated.emit(system_id, status)
                
                except Exception as e:
                    print(f"Error monitoring drone {system_id}: {e}")
            
            time.sleep(self.update_interval)  # Use configurable interval
    
    def _parse_drone_status(self, system_id: int, status_dict: dict) -> DroneStatus:
        """Parse drone status dictionary into DroneStatus object"""
        status = DroneStatus(system_id=system_id)
        status.connected = status_dict.get('connected', False)
        status.activate = status_dict.get('activate', True)  # Get activate status
        status.armed = status_dict.get('armed', False)
        status.mode = status_dict.get('mode', 'UNKNOWN')
        status.altitude = status_dict.get('altitude', 0.0)
        status.groundspeed = status_dict.get('groundspeed', 0.0)
        status.heading = status_dict.get('heading', 0.0)
        status.system_status = status_dict.get('system_status', 'UNKNOWN')
        status.last_update = datetime.now().strftime("%H:%M:%S")
        
        # Detect connection status change
        previous_connected = self.previous_connected.get(system_id, False)
        if status.connected and not previous_connected:
            # Drone just connected
            status.connection_changed = True
            status.connection_event = "CONNECTED"
            self.previous_connected[system_id] = True
        elif not status.connected and previous_connected:
            # Drone just disconnected
            status.connection_changed = True
            status.connection_event = "DISCONNECTED"
            self.previous_connected[system_id] = False
        
        # Parse position
        position = status_dict.get('position', (0.0, 0.0))
        if position:
            status.lat, status.lon = position
        
        # Parse battery
        battery = status_dict.get('battery', {})
        if battery:
            status.battery_percentage = battery.get('percentage', 0)
            status.battery_voltage = battery.get('voltage', 0)
        
        # Parse GPS
        gps = status_dict.get('gps', {})
        if gps:
            status.gps_fix = gps.get('fix_type', 0)
            status.gps_satellites = gps.get('satellites_visible', 0)
        
        # Parse drone parameters (configuration)
        status.params = status_dict.get('params', {})
        
        return status
    
    def get_status(self, system_id: int) -> DroneStatus:
        """Get current status of a drone"""
        return self.statuses.get(system_id, DroneStatus(system_id=system_id))
    
    def get_all_statuses(self) -> Dict[int, DroneStatus]:
        """Get all drone statuses"""
        return self.statuses.copy()


class DroneCard(QFrame):
    """Widget displaying drone status as a card"""
    
    clicked = pyqtSignal(int)
    
    def __init__(self, status: DroneStatus, parent=None):
        super().__init__(parent)
        self.status = status
        self.selected = False
        self.init_ui()
    
    def init_ui(self):
        """Initialize UI"""
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(QSize(160, 160))
        self.setMaximumSize(QSize(180, 190))
        
        layout = QVBoxLayout()
        layout.setSpacing(4)
        layout.setContentsMargins(8, 8, 8, 8)
        self.setLayout(layout)
        
        # Populate with widgets
        self.populate_layout()
    
    def populate_layout(self):
        """Populate the layout with drone status widgets"""
        layout = self.layout()
        
        # System ID
        id_label = QLabel(f"Drone #{self.status.system_id}")
        id_font = QFont("Consolas")
        id_font.setBold(True)
        id_font.setPointSize(9)
        id_label.setFont(id_font)
        layout.addWidget(id_label)
        
        # Connection notification banner
        if self.status.connection_changed:
            notification_label = QLabel(f"[{self.status.connection_event}]")
            notification_font = QFont("Consolas")
            notification_font.setBold(True)
            notification_font.setPointSize(8)
            notification_label.setFont(notification_font)
            
            if self.status.connection_event == "CONNECTED":
                # Green for connected
                notification_label.setStyleSheet("color: green; font-weight: bold;")
            elif self.status.connection_event == "DISCONNECTED":
                # Red for disconnected
                notification_label.setStyleSheet("color: red; font-weight: bold;")
            
            layout.addWidget(notification_label)
        
        # Connection status
        status_text = "Connected" if self.status.connected else "Disconnected"
        status_color = "green" if self.status.connected else "gray"
        status_label = QLabel(f"Status: {status_text}")
        status_font = QFont("Consolas")
        status_font.setPointSize(7)
        status_label.setFont(status_font)
        status_label.setStyleSheet(f"color: {status_color};")
        layout.addWidget(status_label)
        
        # Activate status
        activate_text = "Active" if self.status.activate else "Idle"
        activate_color = "green" if self.status.activate else "orange"
        activate_label = QLabel(f"Active: {activate_text}")
        activate_label.setFont(status_font)
        activate_label.setStyleSheet(f"color: {activate_color};")
        layout.addWidget(activate_label)
        
        # Armed status
        armed_text = "Armed" if self.status.armed else "Disarmed"
        armed_label = QLabel(f"Armed: {armed_text}")
        armed_label.setFont(status_font)
        layout.addWidget(armed_label)
        
        # Flight mode
        mode_label = QLabel(f"Mode: {self.status.mode}")
        mode_label.setFont(status_font)
        layout.addWidget(mode_label)
        
        # Battery
        battery_label = QLabel(f"Battery: {self.status.battery_percentage}%")
        battery_label.setFont(status_font)
        layout.addWidget(battery_label)
        
        # GPS Status
        gps_status = "Fixed" if self.status.gps_fix >= 2 else "No Fix"
        gps_label = QLabel(f"GPS: {gps_status} ({self.status.gps_satellites})")
        gps_label.setFont(status_font)
        layout.addWidget(gps_label)
        
        # Altitude
        alt_label = QLabel(f"Alt: {self.status.altitude:.1f}m")
        alt_label.setFont(status_font)
        layout.addWidget(alt_label)
        
        # Last update
        time_label = QLabel(f"Updated: {self.status.last_update}")
        time_font = QFont("Consolas")
        time_font.setPointSize(6)
        time_label.setFont(time_font)
        layout.addWidget(time_label)
        
        layout.addStretch()
    
    def update_status(self, status: DroneStatus):
        """Update displayed status"""
        self.status = status
        self.update_ui()
    
    def update_ui(self):
        """Refresh UI with current status"""
        # Clear existing layout items without recreating layout
        layout = self.layout()
        if layout is not None:
            # Remove all widgets from layout
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        
        # Recreate UI in the existing layout
        self.populate_layout()
    
    def set_selected(self, selected: bool):
        """Set selection state"""
        self.selected = selected
        self.update_style()
    
    def update_style(self):
        """Update card styling based on state"""
        if self.selected:
            # Selected state - blue border
            self.setStyleSheet(
                "DroneCard { border: 2px solid #0078d4; background-color: #e7f3ff; border-radius: 5px; }"
            )
        else:
            # Unselected state - vary color based on connection
            if self.status.connected:
                # Connected - green border
                self.setStyleSheet(
                    "DroneCard { border: 2px solid #107c10; background-color: #f0f9f6; border-radius: 5px; }"
                )
            else:
                # Disconnected - gray border
                self.setStyleSheet(
                    "DroneCard { border: 2px solid #c5c5c5; background-color: #f5f5f5; border-radius: 5px; }"
                )
    
    def mousePressEvent(self, event):
        """Handle click event"""
        self.clicked.emit(self.status.system_id)
        super().mousePressEvent(event)


class SwarmHealthChecker(QWidget):
    """Widget to display swarm health status"""
    
    def __init__(self, monitor: DroneMonitor, parent=None):
        super().__init__(parent)
        self.monitor = monitor
        self.init_ui()
        
        # Connect status update signal
        self.monitor.signal_emitter.status_updated.connect(self.update_health_status)
    
    def init_ui(self):
        """Initialize UI"""
        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        
        # Title
        title = QLabel("Swarm Health Checker")
        title_font = QFont("Consolas")
        title_font.setBold(True)
        title_font.setPointSize(11)
        title.setFont(title_font)
        layout.addWidget(title)
        
        # Health status area (scrollable)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(180)
        
        self.health_widget = QWidget()
        self.health_layout = QVBoxLayout(self.health_widget)
        self.health_layout.setSpacing(4)
        self.health_layout.setContentsMargins(4, 4, 4, 4)
        
        scroll.setWidget(self.health_widget)
        layout.addWidget(scroll)
        
        # Summary stats
        self.summary_label = QLabel("Initializing...")
        summary_font = QFont("Consolas")
        summary_font.setPointSize(8)
        self.summary_label.setFont(summary_font)
        layout.addWidget(self.summary_label)
        
        self.setLayout(layout)
    
    def update_health_status(self, system_id: int, status: DroneStatus):
        """Update health status display"""
        # Clear current health items
        while self.health_layout.count():
            item = self.health_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Get all drones and their status
        health_items = []
        total_drones = 0
        connected_drones = 0
        active_drones = 0
        
        for drone_id in sorted(self.monitor.drones.keys()):
            drone_status = self.monitor.get_status(drone_id)
            total_drones += 1
            
            if drone_status.connected:
                connected_drones += 1
            
            if drone_status.activate:
                active_drones += 1
            
            # Create health item for this drone
            health_line = self.create_health_item(drone_id, drone_status)
            health_items.append(health_line)
        
        # Add all health items to layout
        for item in health_items:
            self.health_layout.addWidget(item)
        
        self.health_layout.addStretch()
        
        # Update summary
        self.update_summary(total_drones, connected_drones, active_drones)
    
    def create_health_item(self, system_id: int, status: DroneStatus) -> QWidget:
        """Create a health item widget for a drone"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Drone ID
        id_label = QLabel(f"Drone #{system_id}")
        id_font = QFont("Consolas")
        id_font.setBold(True)
        id_font.setPointSize(8)
        id_label.setFont(id_font)
        id_label.setMinimumWidth(80)
        layout.addWidget(id_label)
        
        # Status indicators
        # Connected indicator
        connected_status = "✓ Connected" if status.connected else "✗ Disconnected"
        connected_color = "green" if status.connected else "red"
        connected_label = QLabel(connected_status)
        connected_label.setFont(QFont("Consolas", 8))
        connected_label.setStyleSheet(f"color: {connected_color};")
        connected_label.setMinimumWidth(120)
        layout.addWidget(connected_label)
        
        # Activate/Alive indicator
        activate_status = "✓ Active" if status.activate else "✗ Idle"
        activate_color = "green" if status.activate else "orange"
        activate_label = QLabel(activate_status)
        activate_label.setFont(QFont("Consolas", 8))
        activate_label.setStyleSheet(f"color: {activate_color};")
        activate_label.setMinimumWidth(100)
        layout.addWidget(activate_label)
        
        # Armed status
        armed_status = "Armed" if status.armed else "Disarmed"
        armed_label = QLabel(f"[{armed_status}]")
        armed_label.setFont(QFont("Consolas", 8))
        armed_label.setMinimumWidth(90)
        layout.addWidget(armed_label)
        
        # Battery status
        battery_color = "green" if status.battery_percentage > 50 else ("orange" if status.battery_percentage > 20 else "red")
        battery_label = QLabel(f"Batt: {status.battery_percentage}%")
        battery_label.setFont(QFont("Consolas", 8))
        battery_label.setStyleSheet(f"color: {battery_color};")
        battery_label.setMinimumWidth(80)
        layout.addWidget(battery_label)
        
        # Last update time
        time_label = QLabel(f"[{status.last_update}]")
        time_label.setFont(QFont("Consolas", 7))
        layout.addWidget(time_label)
        
        layout.addStretch()
        
        return widget
    
    def update_summary(self, total: int, connected: int, active: int):
        """Update summary statistics"""
        disconnected = total - connected
        idle = connected - active
        
        summary_text = f"Total: {total} | Connected: {connected} | Disconnected: {disconnected} | Active: {active} | Idle: {idle}"
        
        # Color code the summary
        self.summary_label.setText(summary_text)
        
        # Change color based on health
        if connected == total and active == total:
            color = "green"  # All healthy
        elif disconnected > 0:
            color = "red"  # Some disconnected
        elif idle > 0:
            color = "orange"  # Some idle but connected
        else:
            color = "black"
        
        self.summary_label.setStyleSheet(f"color: {color}; font-weight: bold;")


class OverviewTab(QWidget):
    """Overview tab showing all drones as cards"""
    
    drone_selected = pyqtSignal(int)
    
    def __init__(self, monitor: DroneMonitor, parent=None):
        super().__init__(parent)
        self.monitor = monitor
        self.drone_cards: Dict[int, DroneCard] = {}
        self.selected_drone = None
        self.grid_layout = None
        self.grid_widget = None
        self.scroll_area = None
        self.health_checker = None
        self.init_ui()
        
        # Connect status update signal
        self.monitor.signal_emitter.status_updated.connect(self.on_status_updated)
    
    def init_ui(self):
        """Initialize UI"""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)
        
        # Title
        title = QLabel("Drone Swarm Overview")
        title_font = QFont("Consolas")
        title_font.setBold(True)
        title_font.setPointSize(12)
        title.setFont(title_font)
        main_layout.addWidget(title)
        
        # Info label
        info = QLabel("Click a drone card to view details")
        info_font = QFont("Consolas")
        info_font.setPointSize(9)
        info.setFont(info_font)
        main_layout.addWidget(info)
        
        # Scrollable area for drone cards
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setMinimumHeight(300)
        
        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(12)
        
        # Create cards for each drone
        for system_id in sorted(self.monitor.drones.keys()):
            status = self.monitor.get_status(system_id)
            card = DroneCard(status)
            card.clicked.connect(self.on_drone_selected)
            self.drone_cards[system_id] = card
            
            # Add to grid (3 columns)
            row = (system_id - 1) // 3
            col = (system_id - 1) % 3
            self.grid_layout.addWidget(card, row, col)
        
        # Add stretch to fill remaining space
        self.grid_layout.setRowStretch(self.grid_layout.rowCount(), 1)
        self.grid_layout.setColumnStretch(3, 1)
        self.scroll_area.setWidget(self.grid_widget)
        main_layout.addWidget(self.scroll_area)
        
        # Swarm Health Checker
        self.health_checker = SwarmHealthChecker(self.monitor)
        main_layout.addWidget(self.health_checker)
        
        # Add stretch at the end
        main_layout.addStretch()
        
        self.setLayout(main_layout)
    
    def on_status_updated(self, system_id: int, status: DroneStatus):
        """Handle status update from monitor - add/remove cards based on connection"""
        # If drone connects and card doesn't exist, create it
        if status.connected and system_id not in self.drone_cards:
            self.add_drone_card(system_id, status)
        
        # If drone disconnects and card exists, remove it
        elif not status.connected and system_id in self.drone_cards:
            self.remove_drone_card(system_id)
        
        # Update card if it exists
        elif system_id in self.drone_cards:
            self.drone_cards[system_id].update_status(status)
    
    def add_drone_card(self, system_id: int, status: DroneStatus):
        """Add a drone card to the grid"""
        card = DroneCard(status)
        card.clicked.connect(self.on_drone_selected)
        self.drone_cards[system_id] = card
        
        # Find position in grid (3 columns)
        row = (system_id - 1) // 3
        col = (system_id - 1) % 3
        self.grid_layout.addWidget(card, row, col)
    
    def remove_drone_card(self, system_id: int):
        """Remove a drone card from the grid"""
        if system_id in self.drone_cards:
            card = self.drone_cards[system_id]
            
            # If this card was selected, deselect it
            if self.selected_drone == system_id:
                self.selected_drone = None
            
            # Remove from layout and delete
            self.grid_layout.removeWidget(card)
            card.deleteLater()
            del self.drone_cards[system_id]
    
    def on_drone_selected(self, system_id: int):
        """Handle drone selection"""
        # Update selection state
        if self.selected_drone is not None and self.selected_drone in self.drone_cards:
            self.drone_cards[self.selected_drone].set_selected(False)
        
        self.selected_drone = system_id
        self.drone_cards[system_id].set_selected(True)
        self.drone_selected.emit(system_id)


class DetailTab(QWidget):
    """Detail tab showing comprehensive drone information"""
    
    def __init__(self, monitor: DroneMonitor, parent=None):
        super().__init__(parent)
        self.monitor = monitor
        self.current_drone = None
        self.init_ui()
        
        # Connect status update signal
        self.monitor.signal_emitter.status_updated.connect(self.on_status_updated)
    
    def init_ui(self):
        """Initialize UI"""
        layout = QVBoxLayout()
        
        # Title
        self.title_label = QLabel("Drone Detailed Status")
        title_font = QFont("Consolas")
        title_font.setBold(True)
        title_font.setPointSize(12)
        self.title_label.setFont(title_font)
        layout.addWidget(self.title_label)
        
        # Subtitle
        self.subtitle_label = QLabel("Select a drone from the overview to view details")
        subtitle_font = QFont("Consolas")
        subtitle_font.setPointSize(9)
        self.subtitle_label.setFont(subtitle_font)
        layout.addWidget(self.subtitle_label)
        
        # Tree widget for detailed telemetry
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Parameter", "Value"])
        self.tree.setFont(QFont("Consolas", 9))
        self.tree.setColumnWidth(0, 200)
        self.tree.setColumnWidth(1, 300)
        
        layout.addWidget(self.tree)
        
        self.setLayout(layout)
    
    def set_selected_drone(self, system_id: int):
        """Set the selected drone and display its details"""
        self.current_drone = system_id
        self.display_drone_details(system_id)
    
    def display_drone_details(self, system_id: int):
        """Display detailed information for a drone"""
        status = self.monitor.get_status(system_id)
        
        # Update titles
        self.title_label.setText(f"Drone #{system_id} - Detailed Telemetry")
        self.subtitle_label.setText(f"Status: {'Connected' if status.connected else 'Disconnected'}")
        
        # Clear tree
        self.tree.clear()
        
        # System Information Category
        system_item = QTreeWidgetItem(self.tree, ["System", ""])
        system_font = QFont("Consolas", 10, QFont.Bold)
        system_item.setFont(0, system_font)
        system_item.setFont(1, system_font)
        
        QTreeWidgetItem(system_item, ["System ID", str(status.system_id)])
        QTreeWidgetItem(system_item, ["Connected", "Yes" if status.connected else "No"])
        QTreeWidgetItem(system_item, ["Activate", "Yes" if status.activate else "No (No heartbeat)"])
        QTreeWidgetItem(system_item, ["Armed Status", "Armed" if status.armed else "Disarmed"])
        QTreeWidgetItem(system_item, ["Flight Mode", status.mode])
        QTreeWidgetItem(system_item, ["System Status", status.system_status])
        
        # Battery Category
        battery_item = QTreeWidgetItem(self.tree, ["Battery", ""])
        battery_font = QFont("Consolas", 10, QFont.Bold)
        battery_item.setFont(0, battery_font)
        battery_item.setFont(1, battery_font)
        
        QTreeWidgetItem(battery_item, ["Percentage", f"{status.battery_percentage}%"])
        QTreeWidgetItem(battery_item, ["Voltage", f"{status.battery_voltage} mV"])
        
        # GPS Category
        gps_item = QTreeWidgetItem(self.tree, ["GPS", ""])
        gps_font = QFont("Consolas", 10, QFont.Bold)
        gps_item.setFont(0, gps_font)
        gps_item.setFont(1, gps_font)
        
        QTreeWidgetItem(gps_item, ["Fix Type", self._get_gps_fix_name(status.gps_fix)])
        QTreeWidgetItem(gps_item, ["Satellites", str(status.gps_satellites)])
        QTreeWidgetItem(gps_item, ["Latitude", f"{status.lat:.6f}"])
        QTreeWidgetItem(gps_item, ["Longitude", f"{status.lon:.6f}"])
        
        # Position & Motion Category
        motion_item = QTreeWidgetItem(self.tree, ["Position & Motion", ""])
        motion_font = QFont("Consolas", 10, QFont.Bold)
        motion_item.setFont(0, motion_font)
        motion_item.setFont(1, motion_font)
        
        QTreeWidgetItem(motion_item, ["Altitude", f"{status.altitude:.2f} m"])
        QTreeWidgetItem(motion_item, ["Ground Speed", f"{status.groundspeed:.2f} m/s"])
        QTreeWidgetItem(motion_item, ["Heading", f"{status.heading:.1f}°"])
        
        # Update Time Category
        time_item = QTreeWidgetItem(self.tree, ["Update Time", ""])
        time_font = QFont("Consolas", 10, QFont.Bold)
        time_item.setFont(0, time_font)
        time_item.setFont(1, time_font)
        
        QTreeWidgetItem(time_item, ["Last Update", status.last_update])
        
        # Expand all categories
        self.tree.collapseAll()
    
    
    def on_status_updated(self, system_id: int, status: DroneStatus):
        """Handle status update from monitor"""
        if self.current_drone == system_id:
            self.display_drone_details(system_id)
    
    @staticmethod
    def _get_gps_fix_name(fix_type: int) -> str:
        """Convert GPS fix type to readable name"""
        gps_fix_names = {
            0: "No GPS",
            1: "No Fix",
            2: "2D Fix",
            3: "3D Fix",
            4: "DGPS Fix",
            5: "RTK Fixed",
        }
        return gps_fix_names.get(fix_type, f"Unknown ({fix_type})")


class DroneDashboard(QMainWindow):
    """Main dashboard window"""
    
    def __init__(self, monitor: DroneMonitor):
        super().__init__()
        self.monitor = monitor
        self.init_ui()
    
    def init_ui(self):
        """Initialize main UI"""
        self.setWindowTitle("Drone Swarm Monitoring Dashboard")
        self.setGeometry(100, 100, 1600, 800)
        
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout()
        
        # Create splitter for left/right layout
        splitter = QSplitter(Qt.Horizontal)
        
        # Left side - Overview
        self.overview_tab = OverviewTab(self.monitor)
        self.overview_tab.drone_selected.connect(self.on_drone_selected_from_overview)
        
        # Right side - Detail
        self.detail_tab = DetailTab(self.monitor)
        
        # Add to splitter
        splitter.addWidget(self.overview_tab)
        splitter.addWidget(self.detail_tab)
        
        # Set initial sizes (40% overview, 60% detail)
        splitter.setSizes([640, 960])
        
        main_layout.addWidget(splitter)
        central_widget.setLayout(main_layout)
        
        # Start monitoring
        self.monitor.start_monitoring()
    
    def on_drone_selected_from_overview(self, system_id: int):
        """Handle drone selection from overview"""
        # Display selected drone in detail view on the right
        self.detail_tab.set_selected_drone(system_id)
    
    def closeEvent(self, event):
        """Handle window close"""
        self.monitor.stop_monitoring()
        event.accept()


def main():
    """Main application entry point"""
    # Define drone connections (system_id: connection_string)
    drone_connections = {
        1: "udp:172.21.128.1:14550",
    }
    
    # Create monitor
    monitor = DroneMonitor(drone_connections)
    
    # Create and show application
    app = QApplication(sys.argv)
    dashboard = DroneDashboard(monitor)
    dashboard.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()