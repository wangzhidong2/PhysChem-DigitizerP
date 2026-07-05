# === MODULE META ===
# icon: v
# name: 超声波速度
# category: physics
# class: UltrasonicVelocityWidget
# ===================

# -*- coding: utf-8 -*-
"""超声波速度传感器模块 — 回声定位法测量物体速度"""

import sys
import os
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QComboBox, QTextEdit, QGroupBox, QSpinBox, QDoubleSpinBox,
    QCheckBox, QInputDialog, QStyle, QMessageBox,
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
    card_style, primary_btn_style, accent_btn_style, win11_combo_style,
)


class UltrasonicVelocityWidget(QWidget):
    """超声波速度模块界面 - 回声定位法"""

    def __init__(self):
        super().__init__()
        self.serial_thread = None
        self.distance_data = []    # 距离数据
        self.time_data = []        # 时间数据
        self.velocity_data = []    # 速度数据
        self.echo_time_data = []   # 原始回波时间数据 (µs)
        self.start_timestamp_us = 0

        # 采样频率设置（毫秒）
        self.sample_interval_ms = 100  # 默认 100ms (10Hz)
        self.last_sample_time_ms = 0   # 上次采样时间

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # 控制面板
        control_group = QGroupBox("控制面板")
        control_layout = QHBoxLayout()

        # 串口选择
        control_layout.addWidget(QLabel("串口:"))
        self.port_combo = QComboBox()
        self.port_combo.setStyleSheet(win11_combo_style())
        self.refresh_ports()
        control_layout.addWidget(self.port_combo)

        # 刷新按钮
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        control_layout.addWidget(self.refresh_btn)

        # 连接按钮
        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(self.toggle_connection)
        control_layout.addWidget(self.connect_btn)

        control_layout.addStretch()

        # 采样频率显示
        control_layout.addWidget(QLabel("采样:"))
        self.sample_rate_label = QLabel(f"{1000//self.sample_interval_ms}Hz")
        self.sample_rate_label.setStyleSheet("color: #0078d4; font-weight: bold;")
        control_layout.addWidget(self.sample_rate_label)

        # 采样频率设置按钮
        sample_settings_btn = QPushButton("⚙️")
        sample_settings_btn.setFixedWidth(40)
        sample_settings_btn.setToolTip("设置采样频率")
        sample_settings_btn.clicked.connect(self.edit_sample_rate)
        sample_settings_btn.setStyleSheet("""
            QPushButton {
                background-color: #f0f0f0;
                border: 1px solid #ccc;
                border-radius: 4px;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
            QPushButton:pressed {
                background-color: #d0d0d0;
            }
        """)
        control_layout.addWidget(sample_settings_btn)

        control_layout.addStretch()

        # 速度计算参数
        control_layout.addWidget(QLabel("采样窗口:"))
        self.window_size_spin = QSpinBox()
        self.window_size_spin.setRange(5, 100)
        self.window_size_spin.setValue(10)
        self.window_size_spin.setSuffix(" 点")
        control_layout.addWidget(self.window_size_spin)

        control_group.setLayout(control_layout)
        layout.addWidget(control_group)

        # 数据显示区域
        data_group = QGroupBox("实时数据")
        data_layout = QHBoxLayout()

        # 左侧：文本数据显示
        text_widget = QWidget()
        text_layout = QVBoxLayout()

        # 当前数据
        self.current_data_label = QLabel("当前数据: 等待连接...")
        self.current_data_label.setFont(QFont("Arial", 12))
        text_layout.addWidget(self.current_data_label)

        # 速度统计
        self.velocity_stats_label = QLabel("速度统计: 暂无数据")
        text_layout.addWidget(self.velocity_stats_label)

        # 数据记录
        self.data_text = QTextEdit()
        self.data_text.setMaximumHeight(150)
        text_layout.addWidget(QLabel("速度记录:"))
        text_layout.addWidget(self.data_text)

        text_widget.setLayout(text_layout)
        data_layout.addWidget(text_widget)

        # 右侧：图表显示
        self.figure = Figure(figsize=(8, 6))
        self.canvas = FigureCanvas(self.figure)
        data_layout.addWidget(self.canvas)

        data_group.setLayout(data_layout)
        layout.addWidget(data_group)

        # 控制按钮
        button_layout = QHBoxLayout()

        self.start_btn = QPushButton("开始采集")
        self.start_btn.clicked.connect(self.start_collection)
        self.start_btn.setEnabled(False)
        button_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("停止采集")
        self.stop_btn.clicked.connect(self.stop_collection)
        self.stop_btn.setEnabled(False)
        button_layout.addWidget(self.stop_btn)

        self.save_btn = QPushButton("保存数据")
        self.save_btn.clicked.connect(self.save_data)
        self.save_btn.setEnabled(False)
        button_layout.addWidget(self.save_btn)

        self.clear_btn = QPushButton("清除数据")
        self.clear_btn.clicked.connect(self.clear_data)
        button_layout.addWidget(self.clear_btn)

        button_layout.addStretch()
        layout.addLayout(button_layout)

        self.setLayout(layout)

        # 定时器用于更新图表
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_chart)
        self.timer.start(100)  # 每100ms更新一次图表

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
            self.current_data_label.setText("当前数据: 已连接，等待数据...")

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
        self.current_data_label.setText("当前数据: 已断开")

    def start_collection(self):
        """开始数据采集"""
        self.distance_data.clear()
        self.time_data.clear()
        self.velocity_data.clear()
        self.echo_time_data.clear()  # 清除回波时间数据
        self.data_text.clear()
        self.last_sample_time_ms = 0  # 重置采样时间

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.save_btn.setEnabled(False)

        self.current_data_label.setText("当前数据: 采集进行中...")

    def stop_collection(self):
        """停止数据采集"""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.save_btn.setEnabled(len(self.distance_data) > 0)

        self.current_data_label.setText("当前数据: 采集已停止")

    def handle_data(self, data):
        """处理接收到的数据 - 回声定位法计算速度"""
        # 检查是否是错误信息
        if data.startswith("ERROR:"):
            QMessageBox.critical(self, "串口错误", data[6:])
            self.disconnect_serial()
            return

        # 检查是否是启动信号
        if data == "START":
            self.current_data_label.setText("当前数据: 设备已启动，等待数据...")
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

                    # 过滤无效数据
                    if echo_time < 100 or echo_time > 60000:
                        return

                    # 采样频率控制：检查是否达到采样间隔
                    timestamp_ms = timestamp_us // 1000  # 转换为毫秒
                    if timestamp_ms - self.last_sample_time_ms < self.sample_interval_ms:
                        return  # 未达到采样间隔，跳过此数据

                    # 更新上次采样时间
                    self.last_sample_time_ms = timestamp_ms

                    # 计算距离（厘米）
                    distance_cm = echo_time / 58.0

                    # 如果是第一个数据点，记录起始时间
                    if len(self.time_data) == 0:
                        self.start_timestamp_us = timestamp_us

                    # 计算相对于起始时间的秒数
                    relative_time_s = (timestamp_us - self.start_timestamp_us) / 1000000.0

                    # 记录距离、时间和原始回波时间数据
                    self.distance_data.append(distance_cm)
                    self.time_data.append(relative_time_s)
                    self.echo_time_data.append(echo_time)  # 保存原始回波时间

                    # 回声定位法计算速度
                    velocity = self.calculate_velocity()
                    if velocity is not None:
                        self.velocity_data.append(velocity)

                    # 更新显示
                    current_time = datetime.now()
                    time_str = current_time.strftime("%H:%M:%S.%f")[:-3]

                    if velocity is not None:
                        display_text = f"时间: {time_str} | 距离: {distance_cm:.2f}cm | 速度: {velocity:.2f}cm/s"
                        self.current_data_label.setText(display_text)

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

    def calculate_velocity(self):
        """回声定位法计算速度 - 基于两次测量的时间差

        算法原理：
        v = (t₀ - t₁)/2 × vₛ / [(t₁ + t₀)/2 + Δt]

        其中：
        - t₀: 第一次回波时间 (µs)
        - t₁: 第二次回波时间 (µs)
        - Δt: 两次发射的时间间隔 (s)
        - vₛ: 声速 = 34000 cm/s
        """
        if len(self.distance_data) < 2:
            return None

        try:
            # 获取最近两次测量的数据
            t0 = self.echo_time_data[-2]  # 第一次回波时间 (µs)
            t1 = self.echo_time_data[-1]  # 第二次回波时间 (µs)

            # 计算两次发射的时间间隔 Δt (秒)
            # 使用 Arduino 的测量间隔 (MIN_INTERVAL = 20000 µs = 0.02s)
            delta_t = 0.02  # 默认 20ms
            if len(self.time_data) >= 2:
                delta_t = self.time_data[-1] - self.time_data[-2]

            # 声速 (cm/s)
            v_sound = 34000  # 340 m/s = 34000 cm/s

            # 计算速度 (cm/s)
            # v = (t₀ - t₁)/2 × vₛ / [(t₁ + t₀)/2 + Δt]
            numerator = (t0 - t1) / 2.0 * v_sound
            denominator = (t1 + t0) / 2.0 + delta_t * 1000000  # 将 Δt 转换为 µs

            if denominator == 0:
                return None

            velocity_cm_s = numerator / denominator

            return velocity_cm_s

        except Exception as e:
            print(f"速度计算错误: {e}")
            return None

    def update_stats(self):
        """更新速度统计信息"""
        if len(self.velocity_data) > 0:
            avg_velocity = np.mean(self.velocity_data)
            max_velocity = np.max(self.velocity_data)
            min_velocity = np.min(self.velocity_data)

            stats_text = f"速度统计: 数据点 {len(self.velocity_data)} | " \
                        f"平均 {avg_velocity:.2f}cm/s | " \
                        f"最大 {max_velocity:.2f}cm/s | " \
                        f"最小 {min_velocity:.2f}cm/s"
            self.velocity_stats_label.setText(stats_text)

    def update_chart(self):
        """更新速度图表"""
        if len(self.velocity_data) > 0:
            self.figure.clear()

            # 创建子图
            ax1 = self.figure.add_subplot(211)  # 距离-时间图
            ax2 = self.figure.add_subplot(212)  # 速度-时间图

            # 绘制距离-时间图
            ax1.plot(self.time_data, self.distance_data, 'b-', linewidth=2)
            ax1.set_xlabel('时间 (秒)')
            ax1.set_ylabel('距离 (厘米)')
            ax1.set_title('距离传感器的距离')
            ax1.grid(True, alpha=0.3)

            # 绘制速度-时间图
            ax2.plot(self.time_data[len(self.time_data)-len(self.velocity_data):],
                    self.velocity_data, 'r-', linewidth=2)
            ax2.set_xlabel('时间 (秒)')
            ax2.set_ylabel('速度 (厘米/秒)')
            ax2.set_title('物体运动速度 - 回声定位法')
            ax2.grid(True, alpha=0.3)

            # 自动调整布局
            self.figure.tight_layout()
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
        """保存数据到文件 - 超声波速度"""
        if len(self.distance_data) == 0:
            QMessageBox.warning(self, "警告", "没有数据可保存")
            return

        try:
            filename = f"ultrasonic_velocity_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("time_s,distance_cm,velocity_cm_s\n")
                for i, (time_val, distance, velocity) in enumerate(
                    zip(self.time_data, self.distance_data,
                        self.velocity_data + [None] * (len(self.distance_data) - len(self.velocity_data)))):

                    velocity_str = f"{velocity:.3f}" if velocity is not None else ""
                    f.write(f"{time_val:.3f},{distance:.3f},{velocity_str}\n")

            QMessageBox.information(self, "成功", f"数据已保存到: {filename}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")

    def clear_data(self):
        """清除数据"""
        self.distance_data.clear()
        self.time_data.clear()
        self.velocity_data.clear()
        self.echo_time_data.clear()  # 清除回波时间数据
        self.data_text.clear()
        self.velocity_stats_label.setText("速度统计: 暂无数据")
        self.current_data_label.setText("当前数据: 等待数据...")
        self.figure.clear()
        self.canvas.draw()
        self.save_btn.setEnabled(False)
