# === MODULE META ===
# icon: x
# name: 超声波位移
# category: physics
# class: UltrasonicWidget
# ===================

# -*- coding: utf-8 -*-
"""超声波位移传感器模块 — 测量物体位移和运动轨迹"""

import sys
import os
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QComboBox, QTextEdit, QGroupBox, QSpinBox, QDoubleSpinBox,
    QCheckBox, QInputDialog, QGridLayout, QStyle, QScrollArea, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QFont, QIcon, QPixmap, QPainter
import serial
import serial.tools.list_ports
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np

# 从公共模块导入共享代码
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core import (
    SerialThread, SampleRateDialog,
    load_sensor_config, save_sensor_config,
    card_style, primary_btn_style, accent_btn_style,
    modern_combo_style,
)


class UltrasonicWidget(QWidget):
    """超声波位移模块界面"""

    def __init__(self):
        super().__init__()
        self.serial_thread = None
        self.data_points = []
        self.timestamps = []
        self.start_time = None
        self.start_timestamp_us = 0  # 记录第一个数据点的时间戳

        # 采样频率设置（毫秒）
        self.sample_interval_ms = 100  # 默认 100ms (10Hz)
        self.last_sample_time_ms = 0   # 上次采样时间

        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: #f3f3f3; }")

        content = QWidget()
        content.setStyleSheet("background: #f3f3f3;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)

        # 页面标题
        title = QLabel("超声波位移")
        title.setFont(QFont("Microsoft YaHei", 28, QFont.Weight.Bold))
        title.setStyleSheet("color: #1a1a1a; margin-bottom: 4px;")
        layout.addWidget(title)

        # ========== 卡片1：连接控制 ==========
        card_conn = QWidget()
        card_conn.setObjectName("card")
        card_conn.setStyleSheet(card_style())
        card_layout = QVBoxLayout(card_conn)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.setSpacing(12)

        card_title = QLabel("连接控制")
        card_title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        card_title.setStyleSheet("color: #1a1a1a;")
        card_layout.addWidget(card_title)

        conn_row = QHBoxLayout()
        conn_row.setSpacing(10)

        conn_row.addWidget(QLabel("串口:"))
        self.port_combo = QComboBox()
        self.port_combo.setStyleSheet(modern_combo_style())
        self.refresh_ports()
        self.port_combo.setMinimumWidth(160)
        conn_row.addWidget(self.port_combo)

        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setFixedHeight(36)
        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.refresh_btn.setStyleSheet(accent_btn_style("#f0f0f0", "#e0e0e0", "#d0d0d0"))
        conn_row.addWidget(self.refresh_btn)

        self.connect_btn = QPushButton("连接")
        self.connect_btn.setFixedHeight(36)
        self.connect_btn.clicked.connect(self.toggle_connection)
        self.connect_btn.setStyleSheet(primary_btn_style())
        conn_row.addWidget(self.connect_btn)

        conn_row.addSpacing(20)

        conn_row.addWidget(QLabel("采样:"))
        self.sample_rate_label = QLabel(f"{1000 // self.sample_interval_ms}Hz")
        self.sample_rate_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        self.sample_rate_label.setStyleSheet("color: #0078d4;")
        conn_row.addWidget(self.sample_rate_label)

        sample_settings_btn = QPushButton("⚙")
        sample_settings_btn.setFixedSize(36, 36)
        sample_settings_btn.setToolTip("设置采样频率")
        sample_settings_btn.clicked.connect(self.edit_sample_rate)
        sample_settings_btn.setStyleSheet(accent_btn_style("#f0f0f0", "#e0e0e0", "#d0d0d0"))
        conn_row.addWidget(sample_settings_btn)

        conn_row.addStretch()
        card_layout.addLayout(conn_row)
        layout.addWidget(card_conn)

        # ========== 卡片2：实时数据 ==========
        card_data = QWidget()
        card_data.setObjectName("card")
        card_data.setStyleSheet(card_style())
        data_card_layout = QVBoxLayout(card_data)
        data_card_layout.setContentsMargins(20, 16, 20, 16)
        data_card_layout.setSpacing(12)

        data_card_title = QLabel("实时数据")
        data_card_title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        data_card_title.setStyleSheet("color: #1a1a1a;")
        data_card_layout.addWidget(data_card_title)

        self.current_data_label = QLabel("等待连接...")
        self.current_data_label.setFont(QFont("Microsoft YaHei", 11))
        self.current_data_label.setStyleSheet("color: #444444;")
        data_card_layout.addWidget(self.current_data_label)

        self.stats_label = QLabel("暂无数据")
        self.stats_label.setFont(QFont("Microsoft YaHei", 10))
        self.stats_label.setStyleSheet("color: #888888;")
        data_card_layout.addWidget(self.stats_label)

        layout.addWidget(card_data)

        # ========== 卡片3：图表 + 数据记录 ==========
        card_chart = QWidget()
        card_chart.setObjectName("card")
        card_chart.setStyleSheet(card_style())
        chart_card_layout = QVBoxLayout(card_chart)
        chart_card_layout.setContentsMargins(20, 16, 20, 16)
        chart_card_layout.setSpacing(12)

        chart_header = QHBoxLayout()
        chart_title = QLabel("距离-时间曲线")
        chart_title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        chart_title.setStyleSheet("color: #1a1a1a;")
        chart_header.addWidget(chart_title)
        chart_header.addStretch()
        chart_card_layout.addLayout(chart_header)

        content_row = QHBoxLayout()
        content_row.setSpacing(16)

        # 左侧：数据记录
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        record_label = QLabel("数据记录")
        record_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        record_label.setStyleSheet("color: #1a1a1a;")
        left_layout.addWidget(record_label)

        self.data_text = QTextEdit()
        self.data_text.setReadOnly(True)
        self.data_text.setStyleSheet("""
            QTextEdit {
                background-color: #fafafa;
                border: 1px solid #e5e5e5;
                border-radius: 6px;
                padding: 8px;
                font-size: 11px;
                color: #333333;
            }
        """)
        left_layout.addWidget(self.data_text)
        content_row.addWidget(left_panel, stretch=1)

        # 右侧：图表
        self.figure = Figure(figsize=(8, 6), dpi=100)
        self.figure.set_facecolor('#fafafa')
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setStyleSheet("border: 1px solid #e5e5e5; border-radius: 6px;")
        content_row.addWidget(self.canvas, stretch=2)

        chart_card_layout.addLayout(content_row)
        layout.addWidget(card_chart)

        # ========== 卡片4：操作按钮 ==========
        card_actions = QWidget()
        card_actions.setObjectName("card")
        card_actions.setStyleSheet(card_style())
        actions_layout = QHBoxLayout(card_actions)
        actions_layout.setContentsMargins(20, 12, 20, 12)
        actions_layout.setSpacing(10)

        self.start_btn = QPushButton("开始采集")
        self.start_btn.setFixedHeight(38)
        self.start_btn.clicked.connect(self.start_collection)
        self.start_btn.setEnabled(False)
        self.start_btn.setStyleSheet(primary_btn_style())
        actions_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("停止采集")
        self.stop_btn.setFixedHeight(38)
        self.stop_btn.clicked.connect(self.stop_collection)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(accent_btn_style("#f0f0f0", "#e0e0e0", "#d0d0d0"))
        actions_layout.addWidget(self.stop_btn)

        self.save_btn = QPushButton("保存数据")
        self.save_btn.setFixedHeight(38)
        self.save_btn.clicked.connect(self.save_data)
        self.save_btn.setEnabled(False)
        self.save_btn.setStyleSheet(accent_btn_style("#f0f0f0", "#e0e0e0", "#d0d0d0"))
        actions_layout.addWidget(self.save_btn)

        self.clear_btn = QPushButton("清除数据")
        self.clear_btn.setFixedHeight(38)
        self.clear_btn.clicked.connect(self.clear_data)
        self.clear_btn.setStyleSheet(accent_btn_style("#f0f0f0", "#e0e0e0", "#d0d0d0"))
        actions_layout.addWidget(self.clear_btn)

        actions_layout.addStretch()
        layout.addWidget(card_actions)

        layout.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll)
        self.setLayout(main_layout)

        # 定时器用于更新图表
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_chart)
        self.timer.start(100)

    def refresh_ports(self):
        """刷新可用串口列表"""
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.port_combo.addItem(port.device)

    def toggle_connection(self):
        """切换串口连接状态"""
        if self.serial_thread and self.serial_thread.isRunning():
            self.disconnect_serial()
        else:
            self.connect_serial()

    def connect_serial(self):
        """连接串口"""
        port = self.port_combo.currentText()
        if not port:
            QMessageBox.warning(self, "错误", "请选择串口")
            return

        try:
            self.serial_thread = SerialThread(port)
            self.serial_thread.data_received.connect(self.handle_data)
            self.serial_thread.start()

            self.connect_btn.setText("断开")
            self.start_btn.setEnabled(True)
            self.current_data_label.setText("已连接，等待数据...")

        except Exception as e:
            QMessageBox.critical(self, "连接错误", f"无法连接串口: {e}")

    def disconnect_serial(self):
        """断开串口连接"""
        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread.wait()
            self.serial_thread = None

        self.connect_btn.setText("连接")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.current_data_label.setText("已断开")

    def start_collection(self):
        """开始数据采集"""
        self.data_points.clear()
        self.timestamps.clear()
        self.start_time = datetime.now()
        self.data_text.clear()
        self.last_sample_time_ms = 0  # 重置采样时间

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.save_btn.setEnabled(False)

        self.current_data_label.setText("采集进行中...")

    def stop_collection(self):
        """停止数据采集"""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.save_btn.setEnabled(len(self.data_points) > 0)

        self.current_data_label.setText("采集已停止")

    def handle_data(self, data):
        """处理接收到的数据"""
        # 检查是否是错误信息
        if data.startswith("ERROR:"):
            QMessageBox.critical(self, "串口错误", data[6:])
            self.disconnect_serial()
            return

        # 检查是否是启动信号
        if data == "START":
            self.current_data_label.setText("设备已启动，等待数据...")
            return

        if not self.stop_btn.isEnabled():  # 如果没有在采集状态，忽略数据
            return

        try:
            # 解析数据格式: timestamp,echo_time
            if "," in data:
                parts = data.split(",")
                if len(parts) == 2:
                    timestamp_us = int(parts[0])  # 微秒时间戳
                    echo_time = int(parts[1])

                    # 过滤无效数据（回波时间过小或过大）
                    if echo_time < 100 or echo_time > 60000:  # 100µs - 60ms
                        return

                    # 采样频率控制：检查是否达到采样间隔
                    timestamp_ms = timestamp_us // 1000  # 转换为毫秒
                    if timestamp_ms - self.last_sample_time_ms < self.sample_interval_ms:
                        return  # 未达到采样间隔，跳过此数据

                    # 更新上次采样时间
                    self.last_sample_time_ms = timestamp_ms

                    # 计算距离（厘米）
                    distance_cm = echo_time / 58.0

                    # 记录数据
                    current_time = datetime.now()
                    time_str = current_time.strftime("%H:%M:%S.%f")[:-3]

                    # 如果是第一个数据点，记录起始时间
                    if len(self.timestamps) == 0:
                        self.start_timestamp_us = timestamp_us

                    # 计算相对于起始时间的秒数
                    relative_time_s = (timestamp_us - self.start_timestamp_us) / 1000000.0

                    self.data_points.append(distance_cm)
                    self.timestamps.append(relative_time_s)  # 相对时间（秒）

                    # 更新显示
                    display_text = f"时间: {time_str} | 回波: {echo_time}µs | 距离: {distance_cm:.2f}cm | 相对时间: {relative_time_s:.3f}s"
                    self.current_data_label.setText(f"当前数据: {display_text}")

                    # 添加到数据记录
                    self.data_text.append(display_text)

                    # 自动滚动到底部
                    self.data_text.verticalScrollBar().setValue(
                        self.data_text.verticalScrollBar().maximum()
                    )

                    # 更新统计信息
                    self.update_stats()

        except ValueError:
            pass  # 忽略无法解析的数据

    def update_stats(self):
        """更新统计信息"""
        if len(self.data_points) > 0:
            avg_distance = np.mean(self.data_points)
            max_distance = np.max(self.data_points)
            min_distance = np.min(self.data_points)

            stats_text = f"数据点 {len(self.data_points)} | 平均 {avg_distance:.2f}cm | 最大 {max_distance:.2f}cm | 最小 {min_distance:.2f}cm"
            self.stats_label.setText(stats_text)

    def update_chart(self):
        """更新图表"""
        if len(self.data_points) > 0:
            self.figure.clear()
            ax = self.figure.add_subplot(111)

            ax.plot(self.timestamps, self.data_points, 'b-', linewidth=2)
            ax.set_xlabel('时间 (秒)')
            ax.set_ylabel('距离 (厘米)')
            ax.set_title('距离传感器的距离 - 实时数据')
            ax.grid(True, alpha=0.3)

            # 自动调整坐标轴范围
            if len(self.timestamps) > 1:
                time_range = max(self.timestamps) - min(self.timestamps)
                distance_range = max(self.data_points) - min(self.data_points)

                if time_range > 0:
                    ax.set_xlim(min(self.timestamps), max(self.timestamps))
                if distance_range > 0:
                    ax.set_ylim(min(self.data_points) - 0.1 * distance_range,
                               max(self.data_points) + 0.1 * distance_range)

            self.canvas.draw()

    def edit_sample_rate(self):
        """编辑采样频率对话框"""
        dialog = SampleRateDialog(self.sample_interval_ms, self)
        if dialog.exec() == 1:  # QDialog.Accepted
            new_interval_ms = dialog.get_sample_interval()
            self.sample_interval_ms = new_interval_ms
            freq = 1000 // new_interval_ms
            self.sample_rate_label.setText(f"{freq}Hz")
            QMessageBox.information(self, "成功",
                                   f"采样频率已更新为 {freq} Hz！\n"
                                   f"采样间隔：{new_interval_ms} ms")

    def save_data(self):
        """保存数据到文件"""
        if len(self.data_points) == 0:
            QMessageBox.warning(self, "警告", "没有数据可保存")
            return

        try:
            filename = f"ultrasonic_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("timestamp_ms,distance_cm\n")
                for i, (timestamp, distance) in enumerate(zip(self.timestamps, self.data_points)):
                    f.write(f"{timestamp*1000:.0f},{distance:.3f}\n")

            QMessageBox.information(self, "成功", f"数据已保存到: {filename}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")

    def clear_data(self):
        """清除数据"""
        self.data_points.clear()
        self.timestamps.clear()
        self.data_text.clear()
        self.stats_label.setText("暂无数据")
        self.current_data_label.setText("等待数据...")
        self.figure.clear()
        self.canvas.draw()
        self.save_btn.setEnabled(False)
