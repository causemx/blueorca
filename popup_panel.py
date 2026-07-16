#!/usr/bin/env python3
"""
Reusable PopupPanel class for PyQt5.
Auto-dismisses with fade-out effect.

Usage:
    from popup_panel import PopupPanel
    
    popup = PopupPanel(
        title="Information",
        text="Your message here",
        auto_dismiss_ms=2000,
        width=320
    )
    popup.show_relative_to(button)
"""

from PyQt5.QtWidgets import (
    QFrame, QVBoxLayout, QLabel, QTextEdit, QPushButton
)
from PyQt5.QtCore import Qt, QPoint, QTimer, QPropertyAnimation, pyqtSignal, QObject


class PopupPanel(QFrame):
    """
    Customizable popup panel with auto-dismiss and fade-out effect.
    
    Signals:
        dismissed: Emitted when popup is closed
        shown: Emitted when popup is displayed
    """
    
    dismissed = pyqtSignal()
    shown = pyqtSignal()
    
    def __init__(self, 
                 title: str = "Information",
                 text: str = "Panel content",
                 auto_dismiss_ms: int = 2000,
                 width: int = 320,
                 fade_duration_ms: int = 500,
                 parent=None):
        """
        Initialize PopupPanel.
        
        Args:
            title: Header text in the panel
            text: Main content text
            auto_dismiss_ms: Auto-close delay in milliseconds (0 = no auto-close)
            width: Panel width in pixels
            fade_duration_ms: Fade-out animation duration in milliseconds
            parent: Parent widget (optional)
        """
        super().__init__(parent)
        
        self.auto_dismiss_ms = auto_dismiss_ms
        self.fade_duration_ms = fade_duration_ms
        self.width = width
        
        # Timer for auto-dismiss
        self.dismiss_timer = QTimer()
        self.dismiss_timer.timeout.connect(self.fade_out)
        
        # Animation for fade-out
        self.fade_animation = None
        
        # Setup UI
        self._setup_ui(title, text)
        
        # Setup window properties
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setStyleSheet("""
            QFrame {
                background-color: #f9f9f9;
                border: 2px solid #0078d4;
                border-radius: 6px;
            }
        """)
    
    def _setup_ui(self, title: str, text: str):
        """Setup the panel UI with title and text content."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # Title
        title_label = QLabel(title)
        title_label.setStyleSheet("color: black; font-weight: bold; font-size: 12px;")
        layout.addWidget(title_label)
        
        # Text content
        text_edit = QTextEdit()
        text_edit.setStyleSheet("""
            QTextEdit {
                color: black;
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 3px;
                font-size: 11px;
            }
        """)
        text_edit.setPlainText(text)
        text_edit.setReadOnly(True)
        text_edit.setFixedHeight(130)
        layout.addWidget(text_edit)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet("color: black; padding: 5px;")
        close_btn.clicked.connect(self.fade_out)
        layout.addWidget(close_btn)
        
        # Set panel width
        self.setFixedWidth(self.width)
    
    def show_relative_to(self, widget):
        """
        Show popup positioned below a widget.
        
        Args:
            widget: QWidget to position relative to (typically a button)
        """
        # Get global position below the widget
        widget_rect = widget.geometry()
        parent = widget.parent()
        
        if parent:
            global_pos = parent.mapToGlobal(QPoint(widget_rect.left(), widget_rect.bottom() + 5))
        else:
            global_pos = widget.mapToGlobal(QPoint(widget_rect.left(), widget_rect.bottom() + 5))
        
        self.move(global_pos)
        self.setWindowOpacity(1.0)  # Ensure fully opaque
        self.show()
        self.raise_()
        self.activateWindow()
        
        self.shown.emit()
        
        # Start auto-dismiss timer if configured
        if self.auto_dismiss_ms > 0:
            self.dismiss_timer.start(self.auto_dismiss_ms)
    
    def fade_out(self):
        """Start fade-out animation and close the popup."""
        if self.fade_animation is not None and self.fade_animation.state() != QPropertyAnimation.Stopped:
            # Animation already running, don't start another
            return
        
        self.dismiss_timer.stop()
        
        # Create fade-out animation
        self.fade_animation = QPropertyAnimation(self, b"windowOpacity")
        self.fade_animation.setDuration(self.fade_duration_ms)
        self.fade_animation.setStartValue(1.0)
        self.fade_animation.setEndValue(0.0)
        self.fade_animation.finished.connect(self._on_fade_finished)
        self.fade_animation.start()
    
    def _on_fade_finished(self):
        """Callback when fade animation completes."""
        self.hide()
        self.setWindowOpacity(1.0)  # Reset for next show
        self.dismissed.emit()
    
    def set_text(self, text: str):
        """Update the panel text content."""
        text_edit = self.findChild(QTextEdit)
        if text_edit:
            text_edit.setPlainText(text)
    
    def set_title(self, title: str):
        """Update the panel title."""
        for label in self.findChildren(QLabel):
            if label.styleSheet() and "font-weight: bold" in label.styleSheet():
                label.setText(title)
                return