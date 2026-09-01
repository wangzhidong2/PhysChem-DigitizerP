# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

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
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter
from qfluentwidgets import (
    PushButton, PrimaryPushButton, ComboBox, TextEdit, TitleLabel,
    BodyLabel, CaptionLabel,
)
import numpy as np

# 从公共模块导入共享代码
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core import (
    fluent_message_box, ChartPanel,
    SerialThread, SampleRateComboBox, SimulatorThread,
    load_sensor_config, save_sensor_config,
    SERIAL_AVAILABLE, list_serial_ports, serial_unavailable_hint,
    card_style, primary_btn_style, accent_btn_style,
    modern_combo_style, CollapsibleCard, FluentCard, ExpandableTextEdit,
    scroll_area_style, page_bg_style, apply_module_theme,
)


class UltrasonicWidget(QWidget):
    """超声波位移模块界面"""

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
        self.data_points = []
        self.timestamps = []
        self.start_time = None
        self.start_timestamp_us = 0  # 记录第一个数据点的时间戳

        # 采样频率设置（毫秒）
        self.sample_interval_ms = 100  # 默认 100ms (10Hz)
        self.last_sample_time_ms = 0   # 上次采样时间

        self.init_ui()
        # pyserial 未安装：自动切换到模拟器模式（串口连接优雅降级）
        if not SERIAL_AVAILABLE:
            self.mode_combo.setCurrentIndex(self.mode_combo.findText("模拟器"))

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(scroll_area_style())

        content = QWidget()
        content.setStyleSheet(page_bg_style())
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)

        # 页面标题：用 TitleLabel 自动适配主题
        title = TitleLabel("超声波位移")
        layout.addWidget(title)

        # ========== 卡片1：连接控制（可折叠） ==========
        card_conn_content = QWidget()
        card_conn_content.setObjectName("card")
        card_conn_content.setStyleSheet(card_style())
        card_layout = QVBoxLayout(card_conn_content)
        card_layout.setContentsMargins(20, 4, 20, 16)
        card_layout.setSpacing(12)

        conn_row = QHBoxLayout()
        conn_row.setSpacing(10)

        conn_row.addWidget(BodyLabel("连接方式:"))
        self.mode_combo = ComboBox()
        self.mode_combo.addItems(["有线串口", "模拟器"])
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        conn_row.addWidget(self.mode_combo)

        self.serial_panel = QWidget()
        serial_row = QHBoxLayout(self.serial_panel)
        serial_row.setContentsMargins(0, 0, 0, 0)
        serial_row.setSpacing(8)
        serial_row.addWidget(BodyLabel("串口:"))
        self.port_combo = ComboBox()
        self.refresh_ports()
        self.port_combo.setMinimumWidth(160)
        serial_row.addWidget(self.port_combo)

        self.refresh_btn = PushButton("刷新")
        self.refresh_btn.setFixedHeight(36)
        self.refresh_btn.setStyleSheet(self.CARD_BTN_STYLE)
        self.refresh_btn.clicked.connect(self.refresh_ports)
        serial_row.addWidget(self.refresh_btn)
        conn_row.addWidget(self.serial_panel)

        # 模拟器面板：无需选择端口
        self.sim_panel = QWidget()
        sim_row = QHBoxLayout(self.sim_panel)
        sim_row.setContentsMargins(0, 0, 0, 0)
        sim_hint = CaptionLabel("无需硬件，生成随机数据用于调试")
        sim_row.addWidget(sim_hint)
        sim_row.addStretch()
        conn_row.addWidget(self.sim_panel)
        self.sim_panel.hide()

        self.connect_btn = PushButton("连接")
        self.connect_btn.setFixedHeight(36)
        self.connect_btn.setStyleSheet(self.CARD_BTN_STYLE)
        self.connect_btn.clicked.connect(self.toggle_connection)
        conn_row.addWidget(self.connect_btn)

        conn_row.addSpacing(20)

        conn_row.addWidget(BodyLabel("采样:"))
        self.sample_rate_combo = SampleRateComboBox()
        self.sample_rate_combo.setSampleInterval(self.sample_interval_ms)
        self.sample_rate_combo.sampleIntervalChanged.connect(self.on_sample_interval_changed)
        conn_row.addWidget(self.sample_rate_combo)

        conn_row.addStretch()
        card_layout.addLayout(conn_row)
        card_conn = FluentCard("连接控制", card_conn_content, expanded=True)
        layout.addWidget(card_conn)

        # ========== 卡片2：实时数据（可折叠） ==========
        card_data_content = QWidget()
        card_data_content.setObjectName("card")
        card_data_content.setStyleSheet(card_style())
        data_card_layout = QVBoxLayout(card_data_content)
        data_card_layout.setContentsMargins(20, 4, 20, 16)
        data_card_layout.setSpacing(12)

        self.current_data_label = BodyLabel("等待连接...")
        self.current_data_label.setFont(QFont("Cascadia Code", 11))
        self.current_data_label.setStyleSheet("color: #444444;")
        data_card_layout.addWidget(self.current_data_label)

        self.stats_label = CaptionLabel("暂无数据")
        data_card_layout.addWidget(self.stats_label)

        card_data = FluentCard("实时数据", card_data_content, expanded=True)
        layout.addWidget(card_data)

        # ========== 卡片3：图表 + 数据记录（可折叠） ==========
        card_chart_content = QWidget()
        card_chart_content.setObjectName("card")
        card_chart_content.setStyleSheet(card_style())
        chart_card_layout = QVBoxLayout(card_chart_content)
        chart_card_layout.setContentsMargins(20, 4, 20, 16)
        chart_card_layout.setSpacing(12)

        content_row = QHBoxLayout()
        content_row.setSpacing(16)

        # 左侧：数据记录（可展开/收起，默认3行高度）
        self.data_text = ExpandableTextEdit()
        content_row.addWidget(self.data_text, stretch=0)

        # 右侧：图表
        # 双引擎图表面板（matplotlib / pyqtgraph，设置页可切换）
        self.chart = ChartPanel()
        content_row.addWidget(self.chart, stretch=2)

        # 视图窗口控制：显示整个范围 / 最近 N 秒（仅 pyqtgraph，其他引擎自动隐藏）
        chart_card_layout.addWidget(self.chart.get_view_window_widget())
        chart_card_layout.addLayout(content_row, 1)
        card_chart = CollapsibleCard("距离-时间曲线", card_chart_content, expanded=True, fullscreen=True)
        # 图表卡片加高为原来的 2 倍（内容区最小 400px），页面滚动查看
        card_chart.set_chart_min_height(400)
        # 全屏时：数据记录区作为可拖动折叠浮动面板浮于图表上方，折叠时显示实时位移值
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
        card_actions = FluentCard("操作按钮", card_actions_content, expanded=True)
        layout.addWidget(card_actions)

        layout.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        # 定时器用于更新图表
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_chart)
        self.timer.start(100)

    def refresh_ports(self):
        """刷新可用串口列表（pyserial 未安装时显示占位提示）"""
        self.port_combo.clear()
        ports = list_serial_ports()
        for device, _desc in ports:
            self.port_combo.addItem(device)
        if not ports:
            self.port_combo.addItem("未安装 pyserial" if not SERIAL_AVAILABLE else "无可用串口")

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
            # echo_time 100~60000µs（约 1.7cm~1m），在 11600µs(约20cm)附近漂移
            self.serial_thread = SimulatorThread(
                value_min=100, value_max=60000,
                interval_ms=self.sample_interval_ms,
                start_value=11600, timestamp_scale=1000)
            self.serial_thread.data_received.connect(self.handle_data)
            self.serial_thread.start()

            self.connect_btn.setText("断开")
            self.start_btn.setEnabled(True)
            self.current_data_label.setText("模拟器已连接，等待数据...")

        except Exception as e:
            fluent_message_box(self, "连接错误", f"模拟器启动失败: {e}")

    def connect_serial(self):
        """连接串口"""
        if not SERIAL_AVAILABLE:
            fluent_message_box(self, "提示", serial_unavailable_hint())
            return
        port = self.port_combo.currentText()
        if not port:
            fluent_message_box(self, "错误", "请选择串口")
            return

        try:
            self.serial_thread = SerialThread(port)
            self.serial_thread.data_received.connect(self.handle_data)
            self.serial_thread.start()

            self.connect_btn.setText("断开")
            self.start_btn.setEnabled(True)
            self.current_data_label.setText("已连接，等待数据...")

        except Exception as e:
            fluent_message_box(self, "连接错误", f"无法连接串口: {e}")

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
            fluent_message_box(self, "串口错误", data[6:])
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
            c = self.chart
            c.begin()
            c.plot(self.timestamps, self.data_points, color='b', width=2)
            c.set_labels('时间 (秒)', '距离 (厘米)')
            c.set_title('距离传感器的距离 - 实时数据')

            # 自动调整坐标轴范围
            if len(self.timestamps) > 1:
                time_range = max(self.timestamps) - min(self.timestamps)
                distance_range = max(self.data_points) - min(self.data_points)

                if time_range > 0:
                    c.set_xlim(min(self.timestamps), max(self.timestamps))
                if distance_range > 0:
                    c.set_ylim(min(self.data_points) - 0.1 * distance_range,
                               max(self.data_points) + 0.1 * distance_range)
            c.end()

    def on_sample_interval_changed(self, interval_ms):
        """采样频率改变时更新间隔（内联下拉框触发）"""
        self.sample_interval_ms = interval_ms

    def save_data(self):
        """保存数据到文件"""
        if len(self.data_points) == 0:
            fluent_message_box(self, "警告", "没有数据可保存")
            return

        try:
            filename = f"ultrasonic_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("timestamp_ms,distance_cm\n")
                for i, (timestamp, distance) in enumerate(zip(self.timestamps, self.data_points)):
                    f.write(f"{timestamp*1000:.0f},{distance:.3f}\n")

            fluent_message_box(self, "成功", f"数据已保存到: {filename}")
        except Exception as e:
            fluent_message_box(self, "错误", f"保存失败: {e}")

    def clear_data(self):
        """清除数据"""
        self.data_points.clear()
        self.timestamps.clear()
        self.data_text.clear()
        self.stats_label.setText("暂无数据")
        self.current_data_label.setText("等待数据...")
        self.chart.clear_chart()
        self.save_btn.setEnabled(False)

    def apply_theme(self, theme):
        """主题切换：刷新本模块内所有与主题相关的硬编码样式。"""
        apply_module_theme(self, theme)
        try:
            from qfluentwidgets import isDarkTheme
            self.chart.apply_chart_theme(isDarkTheme())
        except Exception:
            pass
