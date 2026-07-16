import sys
import math
from PyQt5.QtWidgets import QApplication, QFrame, QTextEdit, QPushButton, QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PyQt5.QtCore import Qt, QTimer, QPoint, QPropertyAnimation, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor, QFont, QPainterPath
from PyQt5.QtCore import pyqtSignal, QObject
from popup_panel import PopupPanel
from enum import Enum


class FlightStatus(Enum):
    """Drone flight readiness status"""
    READY = "ready"           # Green - Ready to fly
    WARNING = "warning"       # Yellow - Warning (ready but with caution)
    NOT_READY = "not_ready"   # Red - Not ready


class StatusButton(QWidget):
    """Status button showing flight readiness"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.status = FlightStatus.NOT_READY
        self.setMinimumSize(180, 50)
        self.setMaximumSize(200, 60)
        self.setCursor(Qt.PointingHandCursor)
        
        # Initialize PopupPanel for status information
        self.popup_panel = PopupPanel(
            title="Status Information",
            text="hello",
            auto_dismiss_ms=2000,
            width=300,
            fade_duration_ms=500
        )
    
    def set_status(self, status):
        """Update flight status"""
        if isinstance(status, FlightStatus):
            self.status = status
        self.update()
    
    def mousePressEvent(self, event):
        """Handle mouse click to show PopupPanel"""
        if event.button() == Qt.LeftButton:
            self.popup_panel.show_relative_to(self)
    
    def paintEvent(self, event):
        """Draw the status button"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        width = self.width()
        height = self.height()
        
        # Determine colors based on status
        if self.status == FlightStatus.READY:
            bg_color = QColor(34, 139, 34)      # Green
            text = "Ready To Fly"
        elif self.status == FlightStatus.WARNING:
            bg_color = QColor(184, 134, 11)     # Gold/Yellow
            text = "Ready To Fly"
        else:  # NOT_READY
            bg_color = QColor(220, 20, 60)      # Red
            text = "Not Ready"
        
        # Draw status indicator dot inside icon
        icon_radius = 12
        icon_x = 15
        icon_y = height / 2
        
        painter.setBrush(bg_color)
        painter.drawEllipse(
            int(icon_x - icon_radius + 4), int(icon_y - icon_radius + 4),
            icon_radius * 2 - 8, icon_radius * 2 - 8
        )
        
        # Draw text
        painter.setPen(QPen(bg_color, 1))
        painter.setFont(QFont("Arial", 10, QFont.Bold))
        painter.drawText(
            int(icon_x), 0,
            int(width - icon_x - 25), height,
            Qt.AlignCenter | Qt.AlignVCenter,
            text
        )


class MockData(QObject):
    """Mock data generator for attitude and altitude values"""
    data_updated = pyqtSignal(float, float, float)  # pitch, roll, altitude
    status_updated = pyqtSignal(FlightStatus)  # flight status
    
    def __init__(self):
        super().__init__()
        self.pitch = 0.0
        self.roll = 0.0
        self.altitude = 0.0  # meters
        self.pitch_direction = 1
        self.roll_direction = 1
        self.altitude_direction = 1
        self.flight_status = FlightStatus.NOT_READY
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_data)
        self.timer.start(100)  # Update every 100ms
        self.time_count = 0
    
    def update_data(self):
        """Simulate attitude and altitude data changes"""
        self.time_count += 1
        
        # Oscillate pitch between -30 and +30 degrees
        self.pitch += self.pitch_direction * 2
        if self.pitch >= 30 or self.pitch <= -30:
            self.pitch_direction *= -1
        
        # Oscillate roll between -45 and +45 degrees
        self.roll += self.roll_direction * 1.5
        if self.roll >= 45 or self.roll <= -45:
            self.roll_direction *= -1
        
        # Simulate takeoff and landing
        # Climb for 10 seconds, descent for 10 seconds, repeat
        if self.time_count < 100:  # Takeoff phase
            self.altitude += self.altitude_direction * 0.5  # 0.5m per 100ms
        elif self.time_count < 200:  # Descent phase
            self.altitude += self.altitude_direction * 0.5
        else:  # Reset
            self.time_count = 0
            self.altitude_direction *= -1
        
        # Clamp altitude to reasonable values
        self.altitude = max(0.0, min(self.altitude, 100.0))
        
        # Update flight status based on altitude (simulation)
        # Not ready on ground (altitude < 1m)
        # Warning when climbing/descending (1m <= altitude < 10m)
        # Ready when in stable flight (altitude >= 10m)
        if self.altitude < 1.0:
            new_status = FlightStatus.NOT_READY
        elif self.altitude < 10.0:
            new_status = FlightStatus.WARNING
        else:
            new_status = FlightStatus.READY
        
        if new_status != self.flight_status:
            self.flight_status = new_status
            self.status_updated.emit(self.flight_status)
        
        self.data_updated.emit(self.pitch, self.roll, self.altitude)


class AltitudeBar(QWidget):
    """Separate altitude bar widget"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.altitude = 0.0
        self.setMinimumSize(60, 200)
        self.setStyleSheet("background-color: #f0f0f0;")
    
    def set_altitude(self, altitude):
        """Update altitude value"""
        self.altitude = max(0.0, min(altitude, 100.0))
        self.update()
    
    def paintEvent(self, event):
        """Draw the altitude bar"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        width = self.width()
        height = self.height()
        
        # Altitude bar dimensions
        bar_x = width / 2 - 20
        bar_y = 20
        bar_width = 40
        bar_height = height - 60
        max_altitude = 100.0
        
        # Draw background box
        painter.setPen(QPen(Qt.black, 2))
        painter.setBrush(QColor(50, 50, 50))
        painter.drawRect(int(bar_x), int(bar_y), int(bar_width), int(bar_height))
        
        # Draw altitude scale (0 at bottom, 100 at top)
        painter.setPen(QPen(Qt.white, 1))
        painter.setFont(QFont("Arial", 6))
        
        # Draw major and minor tick marks
        for alt in range(0, int(max_altitude) + 1, 5):
            y_pos = bar_y + bar_height - (alt / max_altitude) * bar_height
            
            if alt % 10 == 0:
                # Major tick mark (every 10m)
                painter.drawLine(
                    int(bar_x), int(y_pos),
                    int(bar_x + 12), int(y_pos)
                )
                # Altitude number on the right
                painter.drawText(
                    int(bar_x + 15), int(y_pos - 6),
                    30, 12,
                    Qt.AlignLeft | Qt.AlignVCenter,
                    str(int(alt))
                )
            else:
                # Minor tick mark (every 5m)
                painter.drawLine(
                    int(bar_x + 4), int(y_pos),
                    int(bar_x + 10), int(y_pos)
                )
        
        # Draw cyan highlight line at current altitude
        current_alt_y = bar_y + bar_height - (self.altitude / max_altitude) * bar_height
        painter.setPen(QPen(QColor(0, 255, 255), 3))
        painter.drawLine(
            int(bar_x - 8), int(current_alt_y),
            int(bar_x + bar_width + 8), int(current_alt_y)
        )
        
        # Draw current altitude display box (below the scale)
        box_y = bar_y + bar_height + 10
        box_height = 25
        
        painter.setPen(QPen(Qt.white, 2))
        painter.setBrush(QColor(0, 0, 0))
        painter.drawRect(
            int(bar_x - 10), int(box_y),
            int(bar_width + 20), int(box_height)
        )
        
        # Draw altitude value in box (green text)
        painter.setPen(QPen(QColor(0, 255, 0), 1))
        painter.setFont(QFont("Courier", 9, QFont.Bold))
        altitude_text = f"{int(self.altitude)}m"
        painter.drawText(
            int(bar_x - 10), int(box_y),
            int(bar_width + 20), int(box_height),
            Qt.AlignCenter,
            altitude_text
        )


class AttitudeIndicator(QWidget):
    """Custom Attitude Indicator Widget"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pitch = 0.0  # degrees (-90 to +90)
        self.roll = 0.0   # degrees (-180 to +180)
        self.altitude = 0.0  # meters
        self.ground_speed = 0.0  # m/s
        
        self.setMinimumSize(200, 200)
        self.setStyleSheet("background-color: #f0f0f0;")
    
    def set_attitude(self, pitch, roll, altitude=0.0, ground_speed=0.0):
        """Update pitch, roll, altitude, and ground_speed values"""
        self.pitch = pitch
        self.roll = roll
        self.altitude = altitude
        self.ground_speed = ground_speed
        self.update()  # Trigger repaint
    
    def paintEvent(self, event):
        """Draw the attitude indicator"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Get widget dimensions
        width = self.width()
        height = self.height()
        center_x = width / 2
        center_y = height / 2
        radius = min(width, height) / 2 - 20
        
        # Draw outer circle (frame)
        painter.setPen(QPen(Qt.black, 3))
        painter.drawEllipse(
            int(center_x - radius),
            int(center_y - radius),
            int(radius * 2),
            int(radius * 2)
        )
        
        # Save painter state
        painter.save()
        
        # Translate to center and apply rotation
        painter.translate(center_x, center_y)
        painter.rotate(self.roll)
        
        # Create circular clipping path
        clip_path = QPainterPath()
        clip_path.addEllipse(-radius, -radius, radius * 2, radius * 2)
        painter.setClipPath(clip_path)
        
        # Draw sky (blue) and ground (brown) background
        sky_color = QColor(100, 150, 255)  # Light blue
        ground_color = QColor(139, 100, 50)  # Brown
        
        # Calculate pitch offset (vertical movement)
        pitch_offset = (self.pitch / 90.0) * radius
        
        # Draw sky half - fill from top to pitch_offset line
        painter.fillRect(
            int(-radius * 2), int(-radius * 2),
            int(radius * 4), int(radius * 2 + pitch_offset),
            sky_color
        )
        
        # Draw ground half - fill from pitch_offset line to bottom
        # The rectangles overlap at pitch_offset, preventing gaps
        painter.fillRect(
            int(-radius * 2), int(pitch_offset),
            int(radius * 4), int(radius * 2),
            ground_color
        )
        
        # Draw horizon line
        painter.setPen(QPen(Qt.white, 2))
        painter.drawLine(int(-radius), 0, int(radius), 0)
        
        # Draw pitch lines and numbers
        painter.setPen(QPen(Qt.white, 1))
        painter.setFont(QFont("Arial", 6))
        
        for pitch_val in range(-90, 91, 10):
            if pitch_val % 10 == 0 and pitch_val != 0:
                line_length = 30 if pitch_val % 20 == 0 else 15
                y_pos = -(pitch_val / 90.0) * radius
                
                painter.drawLine(
                    int(-line_length), int(y_pos),
                    int(line_length), int(y_pos)
                )
                
                # Draw numbers
                if pitch_val % 20 == 0:
                    painter.drawText(
                        int(-50), int(y_pos - 5),
                        30, 15,
                        Qt.AlignRight | Qt.AlignVCenter,
                        str(pitch_val)
                    )
                    painter.drawText(
                        int(20), int(y_pos - 5),
                        30, 15,
                        Qt.AlignLeft | Qt.AlignVCenter,
                        str(pitch_val)
                    )
        
        # Restore painter state
        painter.restore()
        
        # Draw center marker (aircraft symbol)
        painter.setPen(QPen(Qt.white, 2))
        painter.setBrush(Qt.NoBrush)
        
        # Draw crosshair/aircraft symbol
        marker_size = 20
        painter.drawEllipse(
            int(center_x - marker_size),
            int(center_y - marker_size),
            int(marker_size * 2),
            int(marker_size * 2)
        )
        
        # Draw horizontal line (wings)
        painter.drawLine(
            int(center_x - 40), int(center_y),
            int(center_x - 25), int(center_y)
        )
        painter.drawLine(
            int(center_x + 25), int(center_y),
            int(center_x + 40), int(center_y)
        )
        
        # Draw vertical line (nose)
        painter.drawLine(
            int(center_x), int(center_y - 25),
            int(center_x), int(center_y - 35)
        )
        
        # Draw roll scale (outer ring)
        painter.setPen(QPen(Qt.black, 1))
        painter.setFont(QFont("Arial", 7))
        
        for roll_val in range(0, 360, 30):
            angle_rad = math.radians(roll_val)
            x1 = center_x + (radius + 10) * math.sin(angle_rad)
            y1 = center_y - (radius + 10) * math.cos(angle_rad)
            x2 = center_x + (radius + 25) * math.sin(angle_rad)
            y2 = center_y - (radius + 25) * math.cos(angle_rad)
            
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))
            
            # Draw roll degree labels
            if roll_val % 90 == 0:
                label = str(roll_val)
                x_text = center_x + (radius + 40) * math.sin(angle_rad)
                y_text = center_y - (radius + 40) * math.cos(angle_rad)
                painter.drawText(
                    int(x_text - 10), int(y_text - 10),
                    20, 20,
                    Qt.AlignCenter,
                    label
                )
        
        # Draw roll pointer (triangle at top)
        pointer_x = center_x
        pointer_y = center_y - radius - 30
        painter.setPen(QPen(Qt.white, 2))
        painter.setBrush(QColor(255, 255, 0))
        painter.drawPolygon(
            [QPoint(int(pointer_x - 8), int(pointer_y - 5)),
             QPoint(int(pointer_x + 8), int(pointer_y - 5)),
             QPoint(int(pointer_x), int(pointer_y + 5))]
        )
        
        # Draw black background circle in center for altitude display
        painter.setPen(QPen(Qt.white, 1))
        painter.setBrush(QColor(0, 0, 0))
        painter.drawEllipse(
            int(center_x - 30), int(center_y - 30),
            60, 60
        )
        
        # Draw altitude value in center
        painter.setPen(QPen(Qt.green, 2))
        painter.setFont(QFont("Arial", 8))
        altitude_text = f"{int(self.altitude)}m"
        painter.drawText(
            int(center_x - 28), int(center_y - 20),
            56, 20,
            Qt.AlignCenter,
            altitude_text
        )
        
        # Draw ground speed value below altitude
        painter.setPen(QPen(Qt.green, 2))
        painter.setFont(QFont("Arial", 8))
        speed_text = f"{self.ground_speed:.1f}m/s"
        painter.drawText(
            int(center_x - 28), int(center_y),
            56, 20,
            Qt.AlignCenter,
            speed_text
        )


class MainWindow(QWidget):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.initUI()
    
    def initUI(self):
        """Initialize UI components"""
        layout = QVBoxLayout()
        
        # Title bar with title on left and status button on right
        title_layout = QHBoxLayout()
        
        # Title
        title = QLabel("Drone Attitude & Altitude Indicator")
        title.setFont(QFont("Arial", 14, QFont.Bold))
        title_layout.addWidget(title)
        
        # Status button (right side)
        self.status_button = StatusButton()
        title_layout.addStretch()  # Add space to push button to the right
        title_layout.addWidget(self.status_button)
        
        layout.addLayout(title_layout)
        
        # Horizontal layout for attitude indicator and altitude bar
        instruments_layout = QHBoxLayout()
        
        # Attitude indicator widget
        self.attitude = AttitudeIndicator()
        instruments_layout.addWidget(self.attitude)
        
        # Altitude bar widget
        # self.altitude_bar = AltitudeBar()
        # instruments_layout.addWidget(self.altitude_bar)
        
        layout.addLayout(instruments_layout)
        
        # Status label
        self.status_label = QLabel("Pitch: 0.0°  Roll: 0.0°  Alt: 0.0m")
        self.status_label.setFont(QFont("Arial", 11))
        layout.addWidget(self.status_label)
        
        self.setLayout(layout)
        self.setWindowTitle("Drone Attitude & Altitude Indicator")
        self.setGeometry(100, 100, 650, 500)
        
        # Connect mock data
        self.mock_data = MockData()
        self.mock_data.data_updated.connect(self.on_data_updated)
        self.mock_data.status_updated.connect(self.on_status_updated)
    
    def on_data_updated(self, pitch, roll, altitude):
        """Handle mock data updates"""
        self.attitude.set_attitude(pitch, roll, altitude)
        # self.altitude_bar.set_altitude(altitude)
        self.status_label.setText(
            f"Pitch: {pitch:.1f}°  Roll: {roll:.1f}°  Alt: {altitude:.1f}m"
        )
    
    def on_status_updated(self, status):
        """Handle flight status updates"""
        self.status_button.set_status(status)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())