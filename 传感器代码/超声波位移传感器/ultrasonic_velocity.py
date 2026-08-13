# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

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
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QSpinBox, QDoubleSpinBox,
    QCheckBox, QInputDialog, QStyle, QScrollArea, QMessageBox,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter
from qfluentwidgets import PushButton, PrimaryPushButton, ComboBox, TextEdit
import serial
import serial.tools.list_ports
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np

# 从公共模块导入共享代码
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core import (
    SerialThread, SampleRateComboBox, SimulatorThread,
    card_style, primary_btn_style, accent_btn_style, modern_combo_style,
    CollapsibleCard, ExpandableTextEdit,
)


class UltrasonicVelocityWidget(QWidget):
    """超声波速度模块界面 - 回声定位法"""

    # 连接控制卡片内按钮统一样式：白底黑字
    CARD_BTN_STYLE = """
        QPushButton {
            background-color: #ffffff;
            border: 1px solid #d0d0d0;
            color: #1a1a1a;
            border-radius: 6px;
            padding: 0 16px;
            font-size: 13px;
        }
        QPushButton:hover {
            background-color: #f5f5f5;
            border: 1px solid #0078d4;
            color: #0078d4;
        }
        QPushButton:pressed { background-color: #e5e5e5; }
        QPushButton:disabled {
            background-color: #f5f5f5;
            color: #aaaaaa;
            border: 1px solid #e5e5e5;
        }
    """

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
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: #f3f3f3; }")

        content = QWidget()
        content.setStyleSheet("background: #f3f3f3;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)

        title = QLabel("速度")
        title.setFont(QFont("Microsoft YaHei", 28, QFont.Weight.Bold))
        title.setStyleSheet("color: #1a1a1a; margin-bottom: 4px;")
        layout.addWidget(title)

        # ========== 卡片1：连接控制（可折叠） ==========
        card_conn_content = QWidget()
        card_conn_content.setObjectName("card")
        card_conn_content.setStyleSheet(card_style())
        card_layout = QVBoxLayout(card_conn_content)
        card_layout.setContentsMargins(20, 4, 20, 16)
        card_layout.setSpacing(12)

        row1 = QHBoxLayout()
        row1.setSpacing(10)

        row1.addWidget(QLabel("连接方式:"))
        self.mode_combo = ComboBox()
        self.mode_combo.addItems(["有线串口", "模拟器"])
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        row1.addWidget(self.mode_combo)

        # 串口面板
        self.serial_panel = QWidget()
        serial_layout = QHBoxLayout(self.serial_panel)
        serial_layout.setContentsMargins(0, 0, 0, 0)
        serial_layout.setSpacing(8)
        serial_layout.addWidget(QLabel("串口:"))
        self.port_combo = ComboBox()
        self.refresh_ports()
        self.port_combo.setMinimumWidth(140)
        serial_layout.addWidget(self.port_combo)
        self.refresh_btn = PushButton("刷新")
        self.refresh_btn.setFixedHeight(36)
        self.refresh_btn.setStyleSheet(self.CARD_BTN_STYLE)
        self.refresh_btn.clicked.connect(self.refresh_ports)
        serial_layout.addWidget(self.refresh_btn)
        row1.addWidget(self.serial_panel)

        # 模拟器面板：无需选择端口
        self.sim_panel = QWidget()
        sim_layout = QHBoxLayout(self.sim_panel)
        sim_layout.setContentsMargins(0, 0, 0, 0)
        sim_layout.setSpacing(8)
        sim_hint = QLabel("无需硬件，生成随机数据用于调试")
        sim_hint.setStyleSheet("color: #888;")
        sim_layout.addWidget(sim_hint)
        sim_layout.addStretch()
        row1.addWidget(self.sim_panel)
        self.sim_panel.hide()

        row1.addSpacing(16)
        self.connect_btn = PushButton("连接")
        self.connect_btn.setFixedHeight(36)
        self.connect_btn.setStyleSheet(self.CARD_BTN_STYLE)
        self.connect_btn.clicked.connect(self.toggle_connection)
        row1.addWidget(self.connect_btn)

        row1.addSpacing(16)
        row1.addWidget(QLabel("采样频率:"))
        self.sample_rate_combo = SampleRateComboBox()
        self.sample_rate_combo.setSampleInterval(self.sample_interval_ms)
        self.sample_rate_combo.setMaximumWidth(120)
        self.sample_rate_combo.sampleIntervalChanged.connect(self.on_sample_interval_changed)
        row1.addWidget(self.sample_rate_combo)

        row1.addSpacing(16)
        row1.addWidget(QLabel("采样窗口:"))
        self.window_size_spin = QSpinBox()
        self.window_size_spin.setRange(5, 100)
        self.window_size_spin.setValue(10)
        self.window_size_spin.setSuffix(" 点")
        row1.addWidget(self.window_size_spin)

        row1.addStretch()
        card_layout.addLayout(row1)

        card_conn = CollapsibleCard("连接控制", card_conn_content, expanded=True)
        layout.addWidget(card_conn)

        # ========== 卡片2：实时数据（可折叠） ==========
        card_data_content = QWidget()
        card_data_content.setObjectName("card")
        card_data_content.setStyleSheet(card_style())
        data_card_layout = QVBoxLayout(card_data_content)
        data_card_layout.setContentsMargins(20, 4, 20, 16)
        data_card_layout.setSpacing(12)

        self.current_data_label = QLabel("当前数据: 等待连接...")
        self.current_data_label.setFont(QFont("Microsoft YaHei", 24, QFont.Weight.Bold))
        self.current_data_label.setStyleSheet("color: #1a1a1a;")
        data_card_layout.addWidget(self.current_data_label)

        self.velocity_stats_label = QLabel("速度统计: 暂无数据")
        self.velocity_stats_label.setFont(QFont("Microsoft YaHei", 10))
        self.velocity_stats_label.setStyleSheet("color: #888888;")
        data_card_layout.addWidget(self.velocity_stats_label)

        card_data = CollapsibleCard("实时数据", card_data_content, expanded=True)
        layout.addWidget(card_data)

        # ========== 卡片3：速度-时间曲线（可全屏） ==========
        card_chart_content = QWidget()
        card_chart_content.setObjectName("card")
        card_chart_content.setStyleSheet(card_style())
        chart_card_layout = QVBoxLayout(card_chart_content)
        chart_card_layout.setContentsMargins(20, 4, 20, 16)
        chart_card_layout.setSpacing(12)

        content_row = QHBoxLayout()
        content_row.setSpacing(16)

        # 左侧：数据记录（可展开/收起）
        self.data_text = ExpandableTextEdit()
        content_row.addWidget(self.data_text, stretch=0)

        self.figure = Figure(figsize=(8, 6), dpi=100)
        self.figure.set_facecolor('#fafafa')
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setStyleSheet("border: 1px solid #e5e5e5; border-radius: 6px;")
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        content_row.addWidget(self.canvas, stretch=2)

        chart_card_layout.addLayout(content_row, 1)
        card_chart = CollapsibleCard("速度-时间曲线", card_chart_content, expanded=True, fullscreen=True)
        # 图表卡片加高为原来的 2 倍（内容区最小 400px），页面滚动查看
        card_chart.set_chart_min_height(400)
        card_chart.set_fullscreen_overlay(self.data_text, self.current_data_label)
        layout.addWidget(card_chart)

        # ========== 卡片4：操作按钮（可折叠） ==========
        card_actions_content = QWidget()
        card_actions_content.setObjectName("card")
        card_actions_content.setStyleSheet(card_style())
        actions_layout = QHBoxLayout(card_actions_content)
        actions_layout.setContentsMargins(20, 4, 20, 12)
        actions_layout.setSpacing(10)

        self.start_btn = PrimaryPushButton("开始采集")
        self.start_btn.setFixedHeight(38)
        self.start_btn.clicked.connect(self.start_collection)
        self.start_btn.setEnabled(False)
        actions_layout.addWidget(self.start_btn)

        self.stop_btn = PushButton("停止采集")
        self.stop_btn.setFixedHeight(38)
        self.stop_btn.clicked.connect(self.stop_collection)
        self.stop_btn.setEnabled(False)
        actions_layout.addWidget(self.stop_btn)

        self.save_btn = PushButton("保存数据")
        self.save_btn.setFixedHeight(38)
        self.save_btn.clicked.connect(self.save_data)
        self.save_btn.setEnabled(False)
        actions_layout.addWidget(self.save_btn)

        self.clear_btn = PushButton("清除数据")
        self.clear_btn.setFixedHeight(38)
        self.clear_btn.clicked.connect(self.clear_data)
        actions_layout.addWidget(self.clear_btn)

        actions_layout.addStretch()
        card_actions = CollapsibleCard("操作按钮", card_actions_content, expanded=True)
        layout.addWidget(card_actions)

        layout.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

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

    def on_mode_changed(self, index):
        if index == 0:
            self.serial_panel.show()
            self.sim_panel.hide()
        else:
            self.serial_panel.hide()
            self.sim_panel.show()

    def toggle_connection(self):
        """切换连接状态"""
        if self.serial_thread and self.serial_thread.isRunning():
            self.disconnect_serial()
        elif self.mode_combo.currentIndex() == 0:
            self.connect_serial()
        else:
            self.connect_simulator()

    def connect_simulator(self):
        """连接模拟器：随机生成回波时间（µs），无需硬件。时间戳以微秒计。"""
        try:
            self.serial_thread = SimulatorThread(
                value_min=100, value_max=60000,
                interval_ms=self.sample_interval_ms,
                start_value=11600, timestamp_scale=1000)
            self.serial_thread.data_received.connect(self.handle_data)
            self.serial_thread.start()

            self.connect_btn.setText("断开")
            self.start_btn.setEnabled(True)
            self.current_data_label.setText("当前数据: 模拟器已连接，等待数据...")

        except Exception as e:
            QMessageBox.critical(self, "连接错误", f"模拟器启动失败: {e}")

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
            ax1.plot(self.time_data, self.distance_data, color='#0078d4', linewidth=2)
            ax1.set_xlabel('时间 (秒)')
            ax1.set_ylabel('距离 (厘米)')
            ax1.set_title('距离传感器的距离')
            ax1.grid(True, alpha=0.3)

            # 绘制速度-时间图
            ax2.plot(self.time_data[len(self.time_data)-len(self.velocity_data):],
                    self.velocity_data, color='#1a1a1a', linewidth=2)
            ax2.set_xlabel('时间 (秒)')
            ax2.set_ylabel('速度 (厘米/秒)')
            ax2.set_title('物体运动速度 - 回声定位法')
            ax2.grid(True, alpha=0.3)

            # 自动调整布局
            self.figure.tight_layout()
            self.canvas.draw()

    def on_sample_interval_changed(self, interval_ms):
        """采样频率改变时更新间隔（内联下拉框触发）"""
        self.sample_interval_ms = interval_ms

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
