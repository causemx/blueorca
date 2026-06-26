import sys
import time
from collections import deque
from typing import Any, Dict

from loguru import logger
from PyQt5.QtChart import QChart, QChartView, QLineSeries, QValueAxis
from PyQt5.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QPainter
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from mav_server import MAVListener


class AnalyticsSignals(QObject):
    """Signal emitter for analytics updates"""

    data_updated = pyqtSignal(dict)
    drone_list_updated = pyqtSignal(dict)


class MAVAnalyticsDashboard(QMainWindow):
    """
    PyQt5 Dashboard for MAVLink Network Analytics

    Features:
    - Real-time traffic monitoring (msg/s, bytes/s)
    - Per-drone metrics display
    - Message loss detection and visualization
    - Latency analysis with percentiles
    - Live updating line charts
    """

    def __init__(self, mav_listener: MAVListener):
        super().__init__()
        self.mav_listener = mav_listener
        self.setWindowTitle("MAVLink Analytics Dashboard")
        self.setGeometry(100, 100, 1600, 900)

        # Analytics data storage for charts
        self.traffic_history = deque(maxlen=60)  # Keep last 60 seconds
        self.loss_history = deque(maxlen=60)
        self.latency_history = deque(maxlen=60)
        self.timestamps = deque(maxlen=60)

        # UI Components
        self.setup_ui()

        # Timer for periodic updates
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_dashboard)
        self.update_timer.start(1000)  # Update every 1 second

        logger_info("Analytics Dashboard initialized")

    def setup_ui(self):
        """Build the UI"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)

        # Top control bar
        control_layout = self.create_control_bar()
        main_layout.addLayout(control_layout)

        # Tab widget for different views
        tabs = QTabWidget()
        tabs.addTab(self.create_overview_tab(), "Overview")
        tabs.addTab(self.create_per_drone_tab(), "Per-Drone Metrics")
        tabs.addTab(self.create_charts_tab(), "Analytics Charts")

        main_layout.addWidget(tabs)

    def create_control_bar(self) -> QHBoxLayout:
        """Create top control bar"""
        layout = QHBoxLayout()

        # Window size selector
        layout.addSpacing(20)
        layout.addWidget(QLabel("Analytics Window:"))

        self.window_combo = QComboBox()
        self.window_combo.addItems(["1s", "10s", "60s"])
        self.window_combo.setCurrentText("1s")
        self.window_combo.currentTextChanged.connect(self.on_window_changed)
        layout.addWidget(self.window_combo)

        layout.addStretch()

        # Refresh button
        refresh_btn = QPushButton("Refresh Now")
        refresh_btn.clicked.connect(self.update_dashboard)
        layout.addWidget(refresh_btn)

        # Auto-refresh toggle
        self.auto_refresh_btn = QPushButton("Auto-Refresh: ON")
        self.auto_refresh_btn.setCheckable(True)
        self.auto_refresh_btn.setChecked(True)
        self.auto_refresh_btn.clicked.connect(self.toggle_auto_refresh)
        layout.addWidget(self.auto_refresh_btn)

        return layout

    def create_overview_tab(self) -> QWidget:
        """Create overview dashboard tab"""
        widget = QWidget()
        layout = QGridLayout()
        widget.setLayout(layout)

        # Global metrics row 1
        layout.addWidget(self.create_metric_card("Total Messages", "0"), 0, 0)
        layout.addWidget(self.create_metric_card("Msg Rate (msg/s)", "0.0"), 0, 1)
        layout.addWidget(self.create_metric_card("Throughput (KB/s)", "0.0"), 0, 2)
        layout.addWidget(self.create_metric_card("Connected Drones", "0"), 0, 3)

        # Global metrics row 2
        layout.addWidget(self.create_metric_card("Loss Rate (%)", "0.00"), 1, 0)
        layout.addWidget(self.create_metric_card("Latency (ms)", "0.00"), 1, 1)
        layout.addWidget(self.create_metric_card("Jitter (ms)", "0.00"), 1, 2)
        layout.addWidget(self.create_metric_card("Message Types", "0"), 1, 3)

        # Store references to metric labels for updates
        self.metrics = {}
        for i, _widget in enumerate(
            [layout.itemAt(j).widget() for j in range(layout.count())]
        ):
            if isinstance(_widget, QFrame):
                for child in _widget.findChildren(QLabel):
                    if child.text() not in [
                        "Total Messages",
                        "Msg Rate (msg/s)",
                        "Throughput (KB/s)",
                        "Connected Drones",
                        "Loss Rate (%)",
                        "Latency (ms)",
                        "Jitter (ms)",
                        "Message Types",
                    ]:
                        self.metrics[_widget.findChild(QLabel, None).text()] = child

        # Store labels properly
        self.total_msgs_label = None
        self.msg_rate_label = None
        self.throughput_label = None
        self.drones_label = None
        self.loss_rate_label = None
        self.latency_label = None
        self.jitter_label = None
        self.msg_types_label = None

        layout.setRowStretch(2, 1)

        return widget

    def create_metric_card(self, title: str, value: str) -> QFrame:
        """Create a metric display card"""
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                border: 2px solid #cccccc;
                border-radius: 5px;
                padding: 10px;
                background-color: #f8f9fa;
            }
        """)

        layout = QVBoxLayout()
        frame.setLayout(layout)

        title_label = QLabel(title)
        title_label.setFont(QFont("Arial", 10, QFont.Bold))
        title_label.setStyleSheet("color: #666666;")
        layout.addWidget(title_label)

        value_label = QLabel(value)
        value_label.setFont(QFont("Arial", 18, QFont.Bold))
        value_label.setStyleSheet("color: #2196F3;")
        layout.addWidget(value_label)

        # Store reference using title as key
        setattr(
            self,
            f"metric_{title.replace(' ', '_').replace('(', '').replace(')', '').lower()}",
            value_label,
        )

        return frame

    def create_per_drone_tab(self) -> QWidget:
        """Create per-drone metrics tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        widget.setLayout(layout)

        # Per-drone table
        self.drone_table = QTableWidget()
        self.drone_table.setColumnCount(8)
        self.drone_table.setHorizontalHeaderLabels(
            [
                "SysID",
                "Status",
                "Messages",
                "Bytes",
                "Loss Rate (%)",
                "Latency (ms)",
                "Last Seen",
                "Address",
            ]
        )
        self.drone_table.setColumnWidth(0, 60)
        self.drone_table.setColumnWidth(1, 100)
        self.drone_table.setColumnWidth(2, 100)
        self.drone_table.setColumnWidth(3, 100)
        self.drone_table.setColumnWidth(4, 120)
        self.drone_table.setColumnWidth(5, 120)
        self.drone_table.setColumnWidth(6, 150)
        self.drone_table.setColumnWidth(7, 150)

        layout.addWidget(self.drone_table)

        return widget

    def create_charts_tab(self) -> QWidget:
        """Create charts tab with live updating graphs"""
        widget = QWidget()
        layout = QGridLayout()
        widget.setLayout(layout)

        # Traffic chart
        self.traffic_chart_view = self.create_line_chart(
            "Message Rate (msg/s)", "Time (s)"
        )
        layout.addWidget(self.traffic_chart_view, 0, 0)

        # Loss chart
        self.loss_chart_view = self.create_line_chart("Loss Rate (%)", "Time (s)")
        layout.addWidget(self.loss_chart_view, 0, 1)

        # Latency chart
        self.latency_chart_view = self.create_line_chart("Latency (ms)", "Time (s)")
        layout.addWidget(self.latency_chart_view, 1, 0)

        # Throughput chart
        self.throughput_chart_view = self.create_line_chart(
            "Throughput (KB/s)", "Time (s)"
        )
        layout.addWidget(self.throughput_chart_view, 1, 1)

        return widget

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
        elif "Throughput" in title:
            self.throughput_series = series
            self.throughput_y_axis = y_axis_obj

        return chart_view

    def on_window_changed(self, window_str: str):
        """Handle window size change"""
        self.update_dashboard()

    def toggle_auto_refresh(self):
        """Toggle auto-refresh"""
        if self.auto_refresh_btn.isChecked():
            self.auto_refresh_btn.setText("Auto-Refresh: ON")
            self.update_timer.start(1000)
        else:
            self.auto_refresh_btn.setText("Auto-Refresh: OFF")
            self.update_timer.stop()

    def update_dashboard(self):
        """Update all dashboard metrics"""
        if not self.mav_listener.server or not self.mav_listener.server.running:
            self.status_label.setText("Server: OFFLINE")
            self.status_label.setStyleSheet("color: red;")
            return

        # Get window size
        window_s = int(self.window_combo.currentText()[0])

        # Get reports
        global_report = self.mav_listener.server.get_analytics_report(window_s=window_s)
        all_drones_report = self.mav_listener.server.get_all_drones_analytics(
            window_s=window_s
        )

        if global_report:
            self.update_overview_metrics(global_report)
            self.update_charts_data(global_report)

        if all_drones_report:
            self.update_drone_table(all_drones_report)

    def update_overview_metrics(self, report: Dict[str, Any]):
        """Update overview tab metrics"""
        traffic = report.get("traffic", {})
        loss = report.get("loss", {})
        latency = report.get("latency", {})

        # Safe getattr with defaults
        total_msgs = report.get("total_messages_processed", 0)
        msg_rate = traffic.get("msg_rate", 0.0)
        bytes_rate = traffic.get("bytes_rate", 0.0)
        unique_drones = traffic.get("unique_drones", 0)
        loss_rate = loss.get("loss_rate_pct", 0.0)

        imt = latency.get("inter_message_time_ms", {})
        latency_mean = imt.get("mean", 0.0)
        latency_stdev = imt.get("stdev", 0.0)

        unique_msg_types = traffic.get("unique_msg_types", 0)

        # Update labels safely
        try:
            self.metric_total_messages.setText(f"{total_msgs:,}")
            self.metric_msg_ratemsg_s.setText(f"{msg_rate:.1f}")
            self.metric_throughputkbs.setText(f"{bytes_rate / 1024:.1f}")
            self.metric_connected_drones.setText(f"{unique_drones}")
            self.metric_loss_rate.setText(f"{loss_rate:.4f}")
            self.metric_latencyms.setText(f"{latency_mean:.2f}")
            self.metric_jitterms.setText(f"{latency_stdev:.2f}")
            self.metric_message_types.setText(f"{unique_msg_types}")
        except AttributeError:
            pass  # Labels not yet created

    def update_charts_data(self, report: Dict[str, Any]):
        """Update chart data with new metrics"""
        current_time = time.time()
        traffic = report.get("traffic", {})
        loss = report.get("loss", {})
        latency = report.get("latency", {})

        msg_rate = traffic.get("msg_rate", 0.0)
        bytes_rate = traffic.get("bytes_rate", 0.0)
        loss_rate = loss.get("loss_rate_pct", 0.0)

        imt = latency.get("inter_message_time_ms", {})
        latency_mean = imt.get("mean", 0.0)

        # Store in history
        self.timestamps.append(len(self.timestamps))
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

        # Update throughput series
        self.throughput_series.clear()
        for i, value in enumerate(self.traffic_history):
            self.throughput_series.append(
                i, value * 30 / 1024
            )  # Approximate KB/s (30 bytes avg per msg)

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

        if self.traffic_history:
            max_throughput = (
                max(self.traffic_history) * 30 / 1024 if self.traffic_history else 100
            )
            self.throughput_y_axis.setRange(0, max(100, max_throughput * 1.2))

    def update_drone_table(self, all_drones_report: Dict[int, Dict]):
        """Update per-drone metrics table"""
        self.drone_table.setRowCount(0)

        for sysid in sorted(all_drones_report.keys()):
            report = all_drones_report[sysid]

            traffic = report.get("traffic", {})
            loss = report.get("loss", {})
            latency = report.get("latency", {})

            msg_count = traffic.get("message_count", 0)
            bytes_count = traffic.get("bytes_received", 0)
            loss_rate = loss.get("loss_rate_pct", 0.0)
            latency_mean = latency.get("mean", 0.0) if latency else 0.0
            last_seen_us = traffic.get("last_seen_us", 0)

            # Get drone status
            drone = self.mav_listener.server.get_drone_status(sysid)
            status_str = "CONNECTED" if drone and drone.connected else "DISCONNECTED"
            addr_str = (
                f"{drone.addr[0]}:{drone.addr[1]}" if drone and drone.addr else "N/A"
            )

            # Insert row
            row = self.drone_table.rowCount()
            self.drone_table.insertRow(row)

            self.drone_table.setItem(row, 0, QTableWidgetItem(str(sysid)))
            self.drone_table.setItem(row, 1, QTableWidgetItem(status_str))
            self.drone_table.setItem(row, 2, QTableWidgetItem(f"{msg_count:,}"))
            self.drone_table.setItem(row, 3, QTableWidgetItem(f"{bytes_count:,}"))
            self.drone_table.setItem(row, 4, QTableWidgetItem(f"{loss_rate:.4f}"))
            self.drone_table.setItem(row, 5, QTableWidgetItem(f"{latency_mean:.2f}"))
            self.drone_table.setItem(row, 6, QTableWidgetItem(f"{last_seen_us}"))
            self.drone_table.setItem(row, 7, QTableWidgetItem(addr_str))


def logger_info(msg: str):
    """Simple logging wrapper"""
    logger.info(msg)


def main():
    """Run the analytics dashboard"""
    # Create MAVLink listener (server will be started separately or internally)
    listener = MAVListener(
        server_host="0.0.0.0",
        server_port=5566,
        auto_find_port=False,
        connection_timeout=5.0,
        enable_analytics=True,
    )

    # Start server
    listener.start_server()
    logger_info("MAVLink server started")

    # Create PyQt application
    app = QApplication(sys.argv)
    dashboard = MAVAnalyticsDashboard(listener)
    dashboard.show()

    logger_info("Analytics dashboard started")

    # Run application
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
