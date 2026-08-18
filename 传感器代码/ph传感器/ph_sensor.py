# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

# === MODULE META ===
# icon: pH
# name: pH传感器
# category: chemistry
# class: PhSensorWidget
# ===================

# -*- coding: utf-8 -*-
"""pH 传感器模块 — 测量溶液酸碱度（SEN0161）"""

import sys
import os
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QGroupBox, QSpinBox, QDoubleSpinBox,
    QCheckBox, QInputDialog, QStyle, QScrollArea, 
    QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter
from qfluentwidgets import PushButton, PrimaryPushButton, ComboBox, TextEdit, TitleLabel
import serial
import serial.tools.list_ports
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np

# 从公共模块导入共享代码
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core import (
    fluent_message_box,
    SerialThread, SampleRateComboBox, CalibrationDialog, SimulatorThread,
    load_sensor_config, save_sensor_config, _get_config_file_path,
    card_style, primary_btn_style, accent_btn_style, modern_combo_style,
    CollapsibleCard, ExpandableTextEdit,
    scroll_area_style, page_bg_style, apply_module_theme,
)


class PhSensorWidget(QWidget):
    """pH传感器模块界面 - 支持单点/两点/三点校准"""

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
        self.ph_data = []          # pH 值数据
        self.time_data = []        # 时间数据
        self.adc_data = []         # 原始 ADC 数据
        self.start_timestamp_ms = 0

        # 采样频率设置（毫秒）
        self.sample_interval_ms = 100  # 默认 100ms (10Hz)
        self.last_sample_time_ms = 0   # 上次采样时间

        # 加载保存的配置
        self.config = self.load_config()

        # 校准参数 (pH, ADC) - 支持单点/两点/三点校准
        default_calibration = [
            (4.00, 2555),   # 酸性缓冲液
            (6.86, 2281),   # 中性缓冲液
            (9.18, 2030)    # 碱性缓冲液
        ]
        self.calibration_points = self.config.get('calibration_points', default_calibration)
        self.calibration_mode = self.config.get('calibration_mode', 3)

        # 计算校准系数（根据点数选择拟合方式）
        self.calculate_calibration_coefficients()

        self.init_ui()

    def get_config_path(self):
        """获取配置文件路径（已废弃，保留兼容）"""
        return _get_config_file_path()

    def load_config(self):
        """加载 pH 传感器配置"""
        config = load_sensor_config('ph_sensor')
        if config:
            self.sample_interval_ms = config.get('sample_interval_ms', 100)
            default_calibration = [
                (4.00, 2555), (6.86, 2281), (9.18, 2030)
            ]
            self.calibration_points = config.get('calibration_points', default_calibration)
            self.calibration_mode = config.get('calibration_mode', len(self.calibration_points))
        return config

    def save_config(self):
        """保存 pH 传感器配置"""
        config = {
            'calibration_points': self.calibration_points,
            'calibration_mode': self.calibration_mode,
            'sample_interval_ms': self.sample_interval_ms
        }
        return save_sensor_config('ph_sensor', config)

    def calculate_calibration_coefficients(self):
        """根据校准点数计算拟合系数
        - 单点校准: 使用理论斜率 (-0.5 pH/V) + 偏移量
        - 两点校准: 线性拟合 pH = k*ADC + b
        - 三点校准: 二次拟合 pH = a*ADC^2 + b*ADC + c
        """
        ph_values = [p[0] for p in self.calibration_points]
        adc_values = [p[1] for p in self.calibration_points]

        num_points = len(self.calibration_points)

        if num_points == 1:
            ph0, adc0 = self.calibration_points[0]
            theoretical_slope = -0.59  # 理论斜率 (pH/V), Nernst方程在25°C约为-59mV/pH
            intercept = ph0 - theoretical_slope * adc0
            self.cal_coeffs = (0, theoretical_slope, intercept)  # 二次项为0
            self.calibration_mode = 1

        elif num_points == 2:
            coefficients = np.polyfit(adc_values, ph_values, 1)
            self.cal_coeffs = (0, coefficients[0], coefficients[1])  # 扩展为3元组
            self.calibration_mode = 2

        else:  # 3点或更多
            coefficients = np.polyfit(adc_values, ph_values, min(2, num_points-1))
            if len(coefficients) == 2:
                self.cal_coeffs = (0, coefficients[0], coefficients[1])
            else:
                self.cal_coeffs = tuple(coefficients)
            self.calibration_mode = num_points

    def adc_to_ph(self, adc_value):
        """将ADC原始值转换为pH值（支持不同校准模式）"""
        if not hasattr(self, 'cal_coeffs'):
            return 7.0

        a, b, c = self.cal_coeffs
        ph_value = a * (adc_value ** 2) + b * adc_value + c

        return max(0.0, min(14.0, ph_value))

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
        title = TitleLabel("pH")
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
        self.connect_btn.clicked.connect(self.connect_device)
        row1.addWidget(self.connect_btn)

        self.disconnect_btn = PushButton("断开")
        self.disconnect_btn.setFixedHeight(36)
        self.disconnect_btn.setStyleSheet(self.CARD_BTN_STYLE)
        self.disconnect_btn.clicked.connect(self.disconnect_serial)
        self.disconnect_btn.setEnabled(False)
        row1.addWidget(self.disconnect_btn)

        row1.addSpacing(16)
        row1.addWidget(QLabel("采样频率:"))
        self.sample_rate_combo = SampleRateComboBox()
        self.sample_rate_combo.setSampleInterval(self.sample_interval_ms)
        self.sample_rate_combo.setMaximumWidth(120)
        self.sample_rate_combo.sampleIntervalChanged.connect(self.on_sample_interval_changed)
        row1.addWidget(self.sample_rate_combo)

        row1.addSpacing(16)
        row1.addWidget(QLabel("校准状态:"))
        mode_names = {1: "单点校准", 2: "两点校准", 3: "三点校准"}
        mode_name = mode_names.get(self.calibration_mode, f"{self.calibration_mode}点校准")
        self.calibration_label = QLabel(f"✓ {mode_name}")
        self.calibration_label.setStyleSheet("color: green; font-weight: bold;")
        row1.addWidget(self.calibration_label)

        row1.addStretch()
        card_layout.addLayout(row1)

        card_conn = CollapsibleCard("连接控制", card_conn_content, expanded=True)
        layout.addWidget(card_conn)

        # ========== 卡片2：校准参数（可折叠） ==========
        card_cal_content = QWidget()
        card_cal_content.setObjectName("card")
        card_cal_content.setStyleSheet(card_style() + " QWidget#card QLabel { color: #1a1a1a; }")
        cal_card_layout = QVBoxLayout(card_cal_content)
        cal_card_layout.setContentsMargins(20, 4, 20, 16)
        cal_card_layout.setSpacing(12)

        cal_lines = []
        for ph_val, adc_val in self.calibration_points:
            cal_lines.append(f"• pH {ph_val:.2f} → ADC {adc_val}")
        self.cal_text = QLabel("\n".join(cal_lines) if cal_lines else "未设置校准参数")
        self.cal_text.setStyleSheet("font-size: 12px; color: #666;")
        cal_card_layout.addWidget(self.cal_text)

        self.edit_cal_btn = PushButton("✏️ 编辑校准参数")
        self.edit_cal_btn.setFixedHeight(36)
        self.edit_cal_btn.setStyleSheet(self.CARD_BTN_STYLE)
        self.edit_cal_btn.clicked.connect(self.edit_calibration)
        cal_btn_row = QHBoxLayout()
        cal_btn_row.addWidget(self.edit_cal_btn)
        cal_btn_row.addStretch()
        cal_card_layout.addLayout(cal_btn_row)

        card_cal = CollapsibleCard("校准参数", card_cal_content, expanded=True)

        # ========== 卡片3：实时数据（可折叠） ==========
        card_data_content = QWidget()
        card_data_content.setObjectName("card")
        card_data_content.setStyleSheet(card_style())
        data_card_layout = QVBoxLayout(card_data_content)
        data_card_layout.setContentsMargins(20, 4, 20, 16)
        data_card_layout.setSpacing(12)

        self.current_ph_label = QLabel("pH: --.-")
        self.current_ph_label.setFont(QFont("Microsoft YaHei", 24, QFont.Weight.Bold))
        self.current_ph_label.setStyleSheet("color: #0078d4;")
        data_card_layout.addWidget(self.current_ph_label)

        raw_row = QHBoxLayout()
        raw_row.setSpacing(20)
        self.current_adc_label = QLabel("ADC: ----")
        self.current_adc_label.setFont(QFont("Microsoft YaHei", 11))
        self.current_adc_label.setStyleSheet("color: #444444;")
        raw_row.addWidget(self.current_adc_label)
        raw_row.addStretch()
        data_card_layout.addLayout(raw_row)

        self.stats_label = QLabel("统计信息：暂无数据")
        self.stats_label.setFont(QFont("Microsoft YaHei", 10))
        self.stats_label.setStyleSheet("color: #888888;")
        data_card_layout.addWidget(self.stats_label)

        card_data = CollapsibleCard("实时数据", card_data_content, expanded=True)

        # 校准参数 + 实时数据 并排同一行（顶部对齐，各自按内容高度，不强制等高）
        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)
        cards_row.addWidget(card_cal, stretch=1, alignment=Qt.AlignmentFlag.AlignTop)
        cards_row.addWidget(card_data, stretch=1, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(cards_row)

        # ========== 卡片4：pH-时间曲线（可全屏） ==========
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

        self.figure = Figure(figsize=(8, 5), dpi=100)
        self.figure.set_facecolor('#fafafa')
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setStyleSheet("border: 1px solid #e5e5e5; border-radius: 6px;")
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        content_row.addWidget(self.canvas, stretch=2)

        chart_card_layout.addLayout(content_row, 1)
        card_chart = CollapsibleCard("pH-时间曲线", card_chart_content, expanded=True, fullscreen=True)
        # 图表卡片加高为原来的 2 倍（内容区最小 400px），页面滚动查看
        card_chart.set_chart_min_height(400)
        # 全屏时：数据记录区作为可拖动折叠浮动面板浮于图表上方，折叠时显示实时 pH 值
        card_chart.set_fullscreen_overlay(self.data_text, self.current_ph_label)
        layout.addWidget(card_chart)

        # ========== 卡片5：操作按钮（可折叠） ==========
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

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_chart)
        self.timer.start(100)

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

    def connect_device(self):
        if self.mode_combo.currentIndex() == 0:
            self.connect_serial()
        else:
            self.connect_simulator()

    def connect_simulator(self):
        """连接模拟器：随机生成 pH ADC 值（0-4095，中性附近），无需硬件"""
        try:
            self.serial_thread = SimulatorThread(
                value_min=2000, value_max=2600,
                interval_ms=self.sample_interval_ms,
                start_value=2281)
            self.serial_thread.data_received.connect(self.handle_data)
            self.serial_thread.start()
            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(True)
            self.start_btn.setEnabled(True)
            self.current_ph_label.setText("pH: --.-")
            self.current_adc_label.setText("ADC: 模拟器连接中...")
        except Exception as e:
            fluent_message_box(self, "连接错误", f"模拟器启动失败: {e}")

    def connect_serial(self):
        """连接串口"""
        port = self.port_combo.currentText()
        if not port:
            fluent_message_box(self, "错误", "请选择串口")
            return

        try:
            self.serial_thread = SerialThread(port)
            self.serial_thread.data_received.connect(self.handle_data)
            self.serial_thread.start()

            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(True)
            self.start_btn.setEnabled(True)
            self.current_ph_label.setText("pH: --.-")
            self.current_adc_label.setText("ADC: 连接中...")

        except Exception as e:
            fluent_message_box(self, "连接错误", f"无法连接串口: {e}")

    def disconnect_serial(self):
        """断开串口连接"""
        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread.wait()
            self.serial_thread = None

        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.current_ph_label.setText("pH: --.-")
        self.current_adc_label.setText("ADC: 已断开")

    def start_collection(self):
        """开始数据采集"""
        self.ph_data.clear()
        self.time_data.clear()
        self.adc_data.clear()
        self.data_text.clear()
        self.last_sample_time_ms = 0  # 重置采样时间

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.save_btn.setEnabled(False)

        self.current_ph_label.setText("pH: 采集中...")
        self.current_adc_label.setText("ADC: 采集中...")

    def stop_collection(self):
        """停止数据采集"""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.save_btn.setEnabled(len(self.ph_data) > 0)

        if len(self.ph_data) > 0:
            avg_ph = np.mean(self.ph_data)
            self.current_ph_label.setText(f"pH: {avg_ph:.2f}")

    def handle_data(self, data):
        """处理接收到的数据"""
        if data.startswith("ERROR:"):
            fluent_message_box(self, "串口错误", data[6:])
            self.disconnect_serial()
            return

        if data == "START":
            self.current_ph_label.setText("pH: 等待数据...")
            self.current_adc_label.setText("ADC: 设备就绪")
            return

        # 未开始采集时：实时预览当前 pH/ADC，但不存储数据
        if not self.stop_btn.isEnabled():
            try:
                if "," in data:
                    parts = data.split(",")
                    if len(parts) == 2:
                        adc_value = int(parts[1])
                        if 0 <= adc_value <= 4095:
                            ph_value = self.adc_to_ph(adc_value)
                            self.current_ph_label.setText(f"pH: {ph_value:.2f}")
                            self.current_adc_label.setText(f"ADC: {adc_value}")
            except ValueError:
                pass
            return

        try:
            if "," in data:
                parts = data.split(",")
                if len(parts) == 2:
                    timestamp_ms = int(parts[0])  # 毫秒时间戳
                    adc_value = int(parts[1])

                    # 过滤无效 ADC 值（0-4095 范围）
                    if adc_value < 0 or adc_value > 4095:
                        return

                    # 采样频率控制：检查是否达到采样间隔
                    if timestamp_ms - self.last_sample_time_ms < self.sample_interval_ms:
                        return  # 未达到采样间隔，跳过此数据

                    # 更新上次采样时间
                    self.last_sample_time_ms = timestamp_ms

                    # 记录起始时间
                    if len(self.time_data) == 0:
                        self.start_timestamp_ms = timestamp_ms

                    # 计算相对时间（秒）
                    relative_time_s = (timestamp_ms - self.start_timestamp_ms) / 1000.0

                    # 使用校准转换pH值
                    ph_value = self.adc_to_ph(adc_value)

                    # 存储数据
                    self.ph_data.append(ph_value)
                    self.time_data.append(relative_time_s)
                    self.adc_data.append(adc_value)

                    # 更新显示
                    current_time = datetime.now()
                    time_str = current_time.strftime("%H:%M:%S.%f")[:-3]

                    display_text = f"时间: {time_str} | ADC: {adc_value} | pH: {ph_value:.2f}"
                    self.current_ph_label.setText(f"pH: {ph_value:.2f}")
                    self.current_adc_label.setText(f"ADC: {adc_value}")

                    # 添加到数据记录
                    self.data_text.append(display_text)
                    self.data_text.verticalScrollBar().setValue(
                        self.data_text.verticalScrollBar().maximum()
                    )

                    # 更新统计信息
                    self.update_stats()

        except ValueError:
            pass

    def update_stats(self):
        """更新统计信息"""
        if len(self.ph_data) > 0:
            avg_ph = np.mean(self.ph_data)
            max_ph = np.max(self.ph_data)
            min_ph = np.min(self.ph_data)
            std_ph = np.std(self.ph_data)

            stats_text = (f"统计: 数据点 {len(self.ph_data)} | "
                         f"平均 pH={avg_ph:.2f} | "
                         f"最大 pH={max_ph:.2f} | "
                         f"最小 pH={min_ph:.2f} | "
                         f"标准差 σ={std_ph:.3f}")
            self.stats_label.setText(stats_text)

    def update_chart(self):
        """更新pH值图表"""
        if len(self.ph_data) > 0:
            self.figure.clear()
            ax = self.figure.add_subplot(111)

            # 绘制pH值曲线
            ax.plot(self.time_data, self.ph_data, '#0078d4', linewidth=2, label='pH值')

            # 添加参考线（中性pH=7）
            ax.axhline(y=7.0, color='r', linestyle='--', alpha=0.5, label='中性(pH=7)')

            ax.set_xlabel('时间 (秒)')
            ax.set_ylabel('pH值')
            ax.set_title('pH传感器实时数据', fontsize=14, fontweight='bold')
            ax.set_ylim(0, 14)
            ax.grid(True, alpha=0.3)
            ax.legend(loc='upper right')

            # 自动调整坐标轴范围
            if len(self.time_data) > 1:
                ax.set_xlim(min(self.time_data), max(self.time_data))

            self.figure.tight_layout()
            self.canvas.draw()

    def save_data(self):
        """保存数据到文件"""
        if len(self.ph_data) == 0:
            fluent_message_box(self, "警告", "没有数据可保存")
            return

        try:
            filename = f"ph_sensor_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("time_s,adc_raw,ph_value\n")
                for i, (time_val, ph_val, adc_val) in enumerate(
                    zip(self.time_data, self.ph_data, self.adc_data)):
                    f.write(f"{time_val:.3f},{adc_val},{ph_val:.3f}\n")

            fluent_message_box(self, "成功",
                                   f"数据已保存到：{filename}\n"
                                   f"共 {len(self.ph_data)} 个数据点")
        except Exception as e:
            fluent_message_box(self, "错误", f"保存失败：{e}")

    def on_sample_interval_changed(self, interval_ms):
        """采样频率改变时更新间隔并保存配置（内联下拉框触发）"""
        self.sample_interval_ms = interval_ms
        self.save_config()

    def clear_data(self):
        """清除数据"""
        self.ph_data.clear()
        self.time_data.clear()
        self.adc_data.clear()
        self.data_text.clear()
        self.stats_label.setText("统计信息：暂无数据")
        self.current_ph_label.setText("pH: --.-")
        self.current_adc_label.setText("ADC: ----")
        self.figure.clear()
        self.canvas.draw()
        self.save_btn.setEnabled(False)

    def edit_calibration(self):
        """编辑校准参数对话框"""
        dialog = CalibrationDialog(self.calibration_points, self)
        if dialog.exec() == 1:  # QDialog.Accepted
            new_points = dialog.get_calibration_points()
            self.calibration_mode = dialog.get_calibration_mode()

            self.calibration_points = new_points
            self.calculate_calibration_coefficients()

            mode_names = {1: "单点校准", 2: "两点校准", 3: "三点校准"}
            mode_name = mode_names.get(self.calibration_mode, f"{self.calibration_mode}点校准")
            self.calibration_label.setText(f"✓ {mode_name}")

            cal_lines = []
            for ph_val, adc_val in new_points:
                cal_lines.append(f"• pH {ph_val:.2f} → ADC {adc_val}")
            self.cal_text.setText("\n".join(cal_lines))

            # 保存配置到文件
            self.save_config()

            fluent_message_box(self, "成功",
                                   "校准参数已更新并保存！\n新的校准曲线将立即生效。\n下次启动程序时会自动加载此配置。")

    def apply_theme(self, theme):
        """主题切换：刷新本模块内所有与主题相关的硬编码样式。"""
        apply_module_theme(self, theme)
        try:
            from qfluentwidgets import isDarkTheme
            self.figure.set_facecolor('#2d2d2d' if isDarkTheme() else '#fafafa')
            self.canvas.draw()
        except Exception:
            pass
