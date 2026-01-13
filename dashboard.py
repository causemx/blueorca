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
    QTableWidgetItem, QHeaderView, QSplitter
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


class DroneStatusSignal(QObject):
    """Signal emitter for drone status updates"""
    status_updated = pyqtSignal(int, DroneStatus)


class DroneMonitor:
    """Manages drone connections and status updates"""
    
    def __init__(self, connection_strings: Dict[int, str]):
        self.drones: Dict[int, DroneNode] = {}
        self.statuses: Dict[int, DroneStatus] = {}
        self.signal_emitter = DroneStatusSignal()
        self.monitoring = False
        self.monitor_thread = None
        
        # Initialize drones
        for system_id, conn_str in connection_strings.items():
            self.drones[system_id] = DroneNode(conn_str)
            self.statuses[system_id] = DroneStatus(system_id=system_id)
    
    def start_monitoring(self):
        """Start monitoring all drone connections"""
        if not self.monitoring:
            self.monitoring = True
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()
    
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
            
            time.sleep(0.5)
    
    def _parse_drone_status(self, system_id: int, status_dict: dict) -> DroneStatus:
        """Parse drone status dictionary into DroneStatus object"""
        status = DroneStatus(system_id=system_id)
        status.connected = status_dict.get('connected', False)
        status.armed = status_dict.get('armed', False)
        status.mode = status_dict.get('mode', 'UNKNOWN')
        status.altitude = status_dict.get('altitude', 0.0)
        status.groundspeed = status_dict.get('groundspeed', 0.0)
        status.heading = status_dict.get('heading', 0.0)
        status.system_status = status_dict.get('system_status', 'UNKNOWN')
        status.last_update = datetime.now().strftime("%H:%M:%S")
        
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
        
        # Connection status
        status_text = "Connected" if self.status.connected else "Disconnected"
        status_label = QLabel(f"Status: {status_text}")
        status_font = QFont("Consolas")
        status_font.setPointSize(7)
        status_label.setFont(status_font)
        layout.addWidget(status_label)
        
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
            self.setStyleSheet(
                "DroneCard { border: 2px solid #0078d4; background-color: #e7f3ff; border-radius: 5px; }"
            )
        else:
            self.setStyleSheet(
                "DroneCard { border: 1px solid #ccc; background-color: #f5f5f5; border-radius: 5px; }"
            )
    
    def mousePressEvent(self, event):
        """Handle click event"""
        self.clicked.emit(self.status.system_id)
        super().mousePressEvent(event)


class OverviewTab(QWidget):
    """Overview tab showing all drones as cards"""
    
    drone_selected = pyqtSignal(int)
    
    def __init__(self, monitor: DroneMonitor, parent=None):
        super().__init__(parent)
        self.monitor = monitor
        self.drone_cards: Dict[int, DroneCard] = {}
        self.selected_drone = None
        self.init_ui()
        
        # Connect status update signal
        self.monitor.signal_emitter.status_updated.connect(self.on_status_updated)
    
    def init_ui(self):
        """Initialize UI"""
        layout = QVBoxLayout()
        
        # Title
        title = QLabel("Drone Swarm Overview")
        title_font = QFont("Consolas")
        title_font.setBold(True)
        title_font.setPointSize(12)
        title.setFont(title_font)
        layout.addWidget(title)
        
        # Info label
        info = QLabel("Click a drone card to view details")
        info_font = QFont("Consolas")
        info_font.setPointSize(9)
        info.setFont(info_font)
        layout.addWidget(info)
        
        # Scrollable area for drone cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        
        grid_widget = QWidget()
        grid_layout = QGridLayout(grid_widget)
        grid_layout.setSpacing(12)
        
        # Create cards for each drone
        for system_id in sorted(self.monitor.drones.keys()):
            status = self.monitor.get_status(system_id)
            card = DroneCard(status)
            card.clicked.connect(self.on_drone_selected)
            self.drone_cards[system_id] = card
            
            # Add to grid (3 columns)
            row = (system_id - 1) // 3
            col = (system_id - 1) % 3
            grid_layout.addWidget(card, row, col)
        
        # Add stretch to fill remaining space
        grid_layout.setRowStretch(grid_layout.rowCount(), 1)
        grid_layout.setColumnStretch(3, 1)
        scroll.setWidget(grid_widget)
        layout.addWidget(scroll)
        
        self.setLayout(layout)
    
    def on_status_updated(self, system_id: int, status: DroneStatus):
        """Handle status update from monitor"""
        if system_id in self.drone_cards:
            self.drone_cards[system_id].update_status(status)
    
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
        
        # Table for detailed telemetry
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Parameter", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        
        # Set table font to Consolas
        table_font = QFont("Consolas")
        table_font.setPointSize(9)
        self.table.setFont(table_font)
        
        layout.addWidget(self.table)
        
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
        
        # Clear and populate table
        self.table.setRowCount(0)
        
        details = [
            ("System ID", str(status.system_id)),
            ("Connected", "Yes" if status.connected else "No"),
            ("Armed Status", "Armed" if status.armed else "Disarmed"),
            ("Flight Mode", status.mode),
            ("System Status", status.system_status),
            ("", ""),
            ("Battery", ""),
            ("  Percentage", f"{status.battery_percentage}%"),
            ("  Voltage", f"{status.battery_voltage} mV"),
            ("", ""),
            ("GPS", ""),
            ("  Fix Type", self._get_gps_fix_name(status.gps_fix)),
            ("  Satellites", str(status.gps_satellites)),
            ("  Latitude", f"{status.lat:.6f}"),
            ("  Longitude", f"{status.lon:.6f}"),
            ("", ""),
            ("Position & Motion", ""),
            ("  Altitude", f"{status.altitude:.2f} m"),
            ("  Ground Speed", f"{status.groundspeed:.2f} m/s"),
            ("  Heading", f"{status.heading:.1f}"),
            ("", ""),
            ("Last Update", status.last_update),
        ]
        
        for param, value in details:
            row = self.table.rowCount()
            self.table.insertRow(row)
            
            param_item = QTableWidgetItem(param)
            value_item = QTableWidgetItem(value)
            
            item_font = QFont("Consolas")
            item_font.setPointSize(8)
            param_item.setFont(item_font)
            value_item.setFont(item_font)
            
            if param == "":
                # Section divider
                param_item.setBackground(QBrush(QColor("#e0e0e0")))
                value_item.setBackground(QBrush(QColor("#e0e0e0")))
            elif param.startswith("  "):
                # Indented items - same font
                pass
            else:
                # Headers - bold
                item_font.setBold(True)
                param_item.setFont(item_font)
            
            self.table.setItem(row, 0, param_item)
            self.table.setItem(row, 1, value_item)
    
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
        2: "udp:172.21.128.1:14560",
        3: "udp:172.21.128.1:14570",
        4: "udp:172.21.128.1:14580",
        5: "udp:172.21.128.1:14590",
        6: "udp:172.21.128.1:14600",
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