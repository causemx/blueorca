import math
from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtGui import QPainter, QPen, QColor, QFont, QPainterPath


class AttitudeIndicator(QWidget):
    """Custom Attitude Indicator Widget"""
    
    def __init__(self, parent=None, min_width=300, min_height=300):
        super().__init__(parent)
        self.pitch = 0.0  # degrees (-90 to +90)
        self.roll = 0.0   # degrees (-180 to +180)
        
        self.setMinimumSize(min_width, min_height)
        self.setStyleSheet("background-color: #f0f0f0;")
    
    def set_attitude(self, pitch, roll):
        """Update pitch and roll values"""
        self.pitch = pitch
        self.roll = roll
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
        painter.setFont(QFont("Arial", 8))
        
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
        painter.setFont(QFont("Arial", 9))
        
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