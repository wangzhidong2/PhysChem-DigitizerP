# === MODULE META ===
# icon: V
# name: 电压传感器
# category: physics
# class: VoltageSensorWidget
# ===================

# -*- coding: utf-8 -*-
"""电压传感器模块 — ADC 电压采集与分压电路换算，支持 ESP32 ADC 与 HX711 24位模式"""

import sys
import os
import threading
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTextEdit, QGroupBox, QSpinBox, QDoubleSpinBox,
    QCheckBox, QInputDialog, QStyle, QScrollArea, QMessageBox,
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
    SerialThread, BLESerialThread, scan_ble_devices,
    SampleRateDialog,
    load_sensor_config, save_sensor_config,
    card_style, primary_btn_style, accent_btn_style, ModernComboBox,
    BLE_AVAILABLE,
)


class VoltageSensorWidget(QWidget):
    """电压传感器模块界面 - 支持ADC位数选择和电压分压放大比"""

    ADC_BITS_OPTIONS = {8: 256, 10: 1024, 12: 4095, 14: 16383, 16: 65535, 18: 262143, 20: 1048575, 22: 4194303, 24: 16777215}
    VREF = 3.3

    def __init__(self):
        super().__init__()
        self.serial_thread = None
        self.ble_thread = None
        self.voltage_data = []
        self.time_data = []
        self.raw_data = []
        self.start_timestamp_ms = 0

        # 采样频率设置（毫秒）
        self.sample_interval_ms = 100  # 默认 100ms (10Hz)
        self.last_sample_time_ms = 0   # 上次采样时间

        self.adc_bits = 12
        self.divider_ratio = 1.0
        self.amp_ratio = 1.0
        # HX711 专用参数：有符号 24 位 + AVDD/Gain 参考电压
        self.hx711_mode = False
        self.hx711_avdd = 5.0       # HX711 模块 AVDD 电压（V），常见为 5.0
        self.hx711_channel = 'B'    # 通道：A=增益128，B=增益32
        # 显示单位：内部 voltage_data 始终存伏特，仅在显示/保存时按当前单位换算
        self.current_unit = 'V'     # 可选：kV / V / mV
        # 去皮偏移：空载时传感器输出的非零电压，从测量值中扣除
        self.tare_offset_v = 0.0    # 单位：伏特（与 voltage_data 一致）
        self.tare_active = False    # 是否启用去皮

        self.config = self.load_config()
        self.adc_bits = self.config.get('adc_bits', 12)
        self.divider_ratio = self.config.get('divider_ratio', 1.0)
        self.amp_ratio = self.config.get('amp_ratio', 1.0)
        self.hx711_mode = self.config.get('hx711_mode', False)
        self.hx711_avdd = self.config.get('hx711_avdd', 5.0)
        self.hx711_channel = self.config.get('hx711_channel', 'B')
        self.current_unit = self.config.get('current_unit', 'V')
        self.tare_offset_v = self.config.get('tare_offset_v', 0.0)
        self.tare_active = self.config.get('tare_active', False)

        self.init_ui()

    def load_config(self):
        config = load_sensor_config('voltage_sensor')
        if config:
            self.adc_bits = config.get('adc_bits', 12)
            self.divider_ratio = config.get('divider_ratio', 1.0)
            self.amp_ratio = config.get('amp_ratio', 1.0)
            self.sample_interval_ms = config.get('sample_interval_ms', 100)
            self.hx711_mode = config.get('hx711_mode', False)
            self.hx711_avdd = config.get('hx711_avdd', 5.0)
            self.hx711_channel = config.get('hx711_channel', 'B')
            self.current_unit = config.get('current_unit', 'V')
            self.tare_offset_v = config.get('tare_offset_v', 0.0)
            self.tare_active = config.get('tare_active', False)
        return config

    def save_config(self):
        config = {
            'adc_bits': self.adc_bits,
            'divider_ratio': self.divider_ratio,
            'amp_ratio': self.amp_ratio,
            'sample_interval_ms': self.sample_interval_ms,
            'hx711_mode': self.hx711_mode,
            'hx711_avdd': self.hx711_avdd,
            'hx711_channel': self.hx711_channel,
            'current_unit': self.current_unit,
            'tare_offset_v': self.tare_offset_v,
            'tare_active': self.tare_active
        }
        return save_sensor_config('voltage_sensor', config)

    # 单位换算：内部 voltage_data 始终存伏特，按当前单位返回显示值
    UNIT_FACTORS = {'kV': 0.001, 'V': 1.0, 'mV': 1000.0}

    def to_current_unit(self, voltage_v):
        """伏特 → 当前单位"""
        return voltage_v * self.UNIT_FACTORS.get(self.current_unit, 1.0)

    def format_voltage(self, voltage_v):
        """格式化显示：根据数量级自动选小数位"""
        v = self.to_current_unit(voltage_v)
        if self.current_unit == 'kV':
            return f"{v:.6f}"
        elif self.current_unit == 'mV':
            return f"{v:.3f}"
        return f"{v:.4f}"

    def adc_to_voltage(self, adc_value):
        # 实际被测电压 = ADC端电压 × 分压比 / 放大倍数
        v_adc = self.adc_to_vadc(adc_value)
        actual_voltage = v_adc * self.divider_ratio / self.amp_ratio
        # 启用去皮时扣除空载偏移
        if self.tare_active:
            actual_voltage -= self.tare_offset_v
        return actual_voltage

    def adc_to_vadc(self, adc_value):
        """计算 ADC 输入端电压（未做分压/放大还原）"""
        # HX711 模式：24位有符号，参考电压 = AVDD / Gain
        # 通道A 增益128，通道B 增益32（固定）
        if self.hx711_mode:
            gain = 128 if self.hx711_channel == 'A' else 32
            return adc_value / 8388608.0 * (self.hx711_avdd / gain)
        max_adc = self.ADC_BITS_OPTIONS.get(self.adc_bits, 4096) - 1
        return (adc_value / max_adc) * self.VREF

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

        title = QLabel("电压")
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

        # 第一行：连接方式 + 设备选择 + 按钮
        row1 = QHBoxLayout()
        row1.setSpacing(10)

        row1.addWidget(QLabel("连接方式:"))
        self.mode_combo = ModernComboBox(
            items=["有线串口", "BLE蓝牙"],
            on_change=self.on_mode_changed,
        )
        if not BLE_AVAILABLE:
            self.mode_combo.setItemData(1, 0, Qt.ItemDataRole.UserRole - 1)
            self.mode_combo.setItemText(1, "BLE蓝牙（未安装bleak）")
        row1.addWidget(self.mode_combo)

        self.serial_panel = QWidget()
        serial_layout = QHBoxLayout(self.serial_panel)
        serial_layout.setContentsMargins(0, 0, 0, 0)
        serial_layout.setSpacing(8)
        serial_layout.addWidget(QLabel("串口:"))
        self.port_combo = ModernComboBox(min_width=140)
        self.refresh_ports()
        serial_layout.addWidget(self.port_combo)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setFixedHeight(36)
        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.refresh_btn.setStyleSheet(accent_btn_style("#f0f0f0", "#e0e0e0", "#d0d0d0"))
        serial_layout.addWidget(self.refresh_btn)

        self.ble_panel = QWidget()
        ble_layout = QHBoxLayout(self.ble_panel)
        ble_layout.setContentsMargins(0, 0, 0, 0)
        ble_layout.setSpacing(8)
        self.ble_device_combo = ModernComboBox(min_width=180)
        ble_layout.addWidget(self.ble_device_combo)
        self.ble_scan_btn = QPushButton("扫描BLE")
        self.ble_scan_btn.setFixedHeight(36)
        self.ble_scan_btn.clicked.connect(self.scan_ble)
        if not BLE_AVAILABLE:
            self.ble_scan_btn.setEnabled(False)
        ble_layout.addWidget(self.ble_scan_btn)

        row1.addWidget(self.serial_panel)
        row1.addWidget(self.ble_panel)
        self.ble_panel.hide()

        row1.addSpacing(16)
        self.connect_btn = QPushButton("连接")
        self.connect_btn.setFixedHeight(36)
        self.connect_btn.clicked.connect(self.connect_device)
        self.connect_btn.setStyleSheet(primary_btn_style())
        row1.addWidget(self.connect_btn)

        self.disconnect_btn = QPushButton("断开")
        self.disconnect_btn.setFixedHeight(36)
        self.disconnect_btn.clicked.connect(self.disconnect_all)
        self.disconnect_btn.setEnabled(False)
        self.disconnect_btn.setStyleSheet(accent_btn_style("#f0f0f0", "#e0e0e0", "#d0d0d0"))
        row1.addWidget(self.disconnect_btn)

        row1.addStretch()
        card_layout.addLayout(row1)

        # 第二行：采样频率
        row2 = QHBoxLayout()
        row2.setSpacing(10)
        row2.addWidget(QLabel("采样频率:"))
        self.sample_rate_label = QLabel(f"{1000 // self.sample_interval_ms}Hz")
        self.sample_rate_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        self.sample_rate_label.setStyleSheet("color: #0078d4;")
        row2.addWidget(self.sample_rate_label)

        sample_settings_btn = QPushButton("⚙")
        sample_settings_btn.setFixedSize(36, 36)
        sample_settings_btn.setToolTip("设置采样频率")
        sample_settings_btn.clicked.connect(self.edit_sample_rate)
        sample_settings_btn.setStyleSheet(accent_btn_style("#f0f0f0", "#e0e0e0", "#d0d0d0"))
        row2.addWidget(sample_settings_btn)
        row2.addStretch()
        card_layout.addLayout(row2)

        layout.addWidget(card_conn)

        # ========== 卡片2：ADC 与电路参数 ==========
        card_adc = QWidget()
        card_adc.setObjectName("card")
        card_adc.setStyleSheet(card_style())
        adc_card_layout = QVBoxLayout(card_adc)
        adc_card_layout.setContentsMargins(20, 16, 20, 16)
        adc_card_layout.setSpacing(12)

        adc_card_title = QLabel("ADC 与电路参数")
        adc_card_title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        adc_card_title.setStyleSheet("color: #1a1a1a;")
        adc_card_layout.addWidget(adc_card_title)

        bits_row = QHBoxLayout()
        bits_row.setSpacing(10)
        bits_row.addWidget(QLabel("ADC 位数:"))
        bits_map = {0: 8, 1: 10, 2: 12, 3: 14, 4: 16, 5: 18, 6: 20, 7: 22, 8: 24}
        self.adc_bits_combo = ModernComboBox(
            items=[
                "8 位 (0-255)",
                "10 位 (0-1023)",
                "12 位 (0-4095)  ESP32内置",
                "14 位 (0-16383)",
                "16 位 (0-65535)  ADS1115等",
                "18 位 (0-262143)",
                "20 位 (0-1048575)",
                "22 位 (0-4194303)",
                "24 位 (0-16777215)  HX711等"
            ],
            on_change=self.on_adc_bits_changed,
            default=bits_map.get(self.adc_bits, 2),
        )
        bits_row.addWidget(self.adc_bits_combo)

        bits_row.addWidget(QLabel("参考电压: 3.3V"))
        self.range_label = QLabel(f"量程: 0 ~ {self.VREF:.1f}V")
        self.range_label.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        self.range_label.setStyleSheet("color: #0078d4;")
        bits_row.addWidget(self.range_label)
        bits_row.addStretch()
        adc_card_layout.addLayout(bits_row)

        # HX711 模式行：复选框 + AVDD + 通道选择
        hx711_row = QHBoxLayout()
        hx711_row.setSpacing(10)
        self.hx711_check = QCheckBox("HX711 模式（24位有符号）")
        self.hx711_check.setChecked(self.hx711_mode)
        self.hx711_check.setToolTip("启用后按 HX711 有符号 24 位 + AVDD/Gain 换算电压\n通道A=增益128，通道B=增益32")
        self.hx711_check.toggled.connect(self.on_hx711_mode_changed)
        hx711_row.addWidget(self.hx711_check)

        hx711_row.addWidget(QLabel("AVDD:"))
        self.hx711_avdd_spin = QDoubleSpinBox()
        self.hx711_avdd_spin.setRange(2.7, 5.5)
        self.hx711_avdd_spin.setDecimals(2)
        self.hx711_avdd_spin.setSingleStep(0.1)
        self.hx711_avdd_spin.setValue(self.hx711_avdd)
        self.hx711_avdd_spin.setSuffix(" V")
        self.hx711_avdd_spin.setMinimumWidth(90)
        self.hx711_avdd_spin.valueChanged.connect(self.on_hx711_avdd_changed)
        self.hx711_avdd_spin.setEnabled(self.hx711_mode)
        hx711_row.addWidget(self.hx711_avdd_spin)

        hx711_row.addWidget(QLabel("通道:"))
        self.hx711_channel_combo = ModernComboBox(
            items=["B (增益 32, ±156mV)", "A (增益 128, ±39mV)"],
            on_change=self.on_hx711_channel_changed,
            default=0 if self.hx711_channel == 'B' else 1,
        )
        self.hx711_channel_combo.setEnabled(self.hx711_mode)
        hx711_row.addWidget(self.hx711_channel_combo)

        hx711_row.addStretch()
        adc_card_layout.addLayout(hx711_row)

        params_row = QHBoxLayout()
        params_row.setSpacing(10)
        params_row.addWidget(QLabel("分压比 (R1+R2)/R2:"))
        self.divider_spin = QDoubleSpinBox()
        self.divider_spin.setRange(1.0, 1000.0)
        self.divider_spin.setDecimals(2)
        self.divider_spin.setSingleStep(0.1)
        self.divider_spin.setValue(self.divider_ratio)
        self.divider_spin.setSuffix(" x")
        self.divider_spin.setMinimumWidth(120)
        self.divider_spin.valueChanged.connect(self.on_divider_changed)
        params_row.addWidget(self.divider_spin)

        params_row.addWidget(QLabel("放大倍数:"))
        self.amp_spin = QDoubleSpinBox()
        self.amp_spin.setRange(0.01, 1000.0)
        self.amp_spin.setDecimals(2)
        self.amp_spin.setSingleStep(0.1)
        self.amp_spin.setValue(self.amp_ratio)
        self.amp_spin.setSuffix(" x")
        self.amp_spin.setMinimumWidth(120)
        self.amp_spin.valueChanged.connect(self.on_amp_changed)
        params_row.addWidget(self.amp_spin)

        self.actual_range_label = QLabel(f"实际量程: 0 ~ {self.VREF * self.divider_ratio / self.amp_ratio:.2f}V")
        self.actual_range_label.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        self.actual_range_label.setStyleSheet("color: #28a745;")
        params_row.addWidget(self.actual_range_label)
        params_row.addStretch()
        adc_card_layout.addLayout(params_row)

        hint_label = QLabel("分压比 = (R1+R2)/R2，用于还原分压前的原始电压；放大倍数 = 运放增益，用于还原放大前的信号电压")
        hint_label.setStyleSheet("color: #888888; font-size: 11px;")
        hint_label.setWordWrap(True)
        adc_card_layout.addWidget(hint_label)

        # 显示单位选择
        unit_row = QHBoxLayout()
        unit_row.setSpacing(10)
        unit_row.addWidget(QLabel("显示单位:"))
        unit_map = {'kV': 0, 'V': 1, 'mV': 2}
        self.unit_combo = ModernComboBox(
            items=["千伏 (kV)", "伏 (V)", "毫伏 (mV)"],
            on_change=self.on_unit_changed,
            default=unit_map.get(self.current_unit, 1),
        )
        unit_row.addWidget(self.unit_combo)
        unit_row.addStretch()
        adc_card_layout.addLayout(unit_row)

        # 去皮状态显示行
        tare_row = QHBoxLayout()
        tare_row.setSpacing(10)
        tare_row.addWidget(QLabel("去皮:"))
        self.tare_status_label = QLabel("未启用" if not self.tare_active else
                                        f"已启用 (偏移 {self.format_voltage(self.tare_offset_v)} {self.current_unit})")
        self.tare_status_label.setStyleSheet("color: green; font-weight: bold;" if self.tare_active
                                             else "color: #888; font-weight: bold;")
        tare_row.addWidget(self.tare_status_label)
        tare_row.addStretch()
        adc_card_layout.addLayout(tare_row)

        layout.addWidget(card_adc)

        # ========== 卡片3：实时数据 ==========
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

        self.current_voltage_label = QLabel("--.- V")
        self.current_voltage_label.setFont(QFont("Microsoft YaHei", 32, QFont.Weight.Bold))
        self.current_voltage_label.setStyleSheet("color: #0078d4;")
        data_card_layout.addWidget(self.current_voltage_label)

        raw_row = QHBoxLayout()
        raw_row.setSpacing(20)
        self.current_raw_label = QLabel("原始ADC: ------")
        self.current_raw_label.setFont(QFont("Microsoft YaHei", 11))
        self.current_raw_label.setStyleSheet("color: #444444;")
        raw_row.addWidget(self.current_raw_label)

        self.current_vadc_label = QLabel("ADC端电压: --.- V")
        self.current_vadc_label.setFont(QFont("Microsoft YaHei", 11))
        self.current_vadc_label.setStyleSheet("color: #444444;")
        raw_row.addWidget(self.current_vadc_label)
        raw_row.addStretch()
        data_card_layout.addLayout(raw_row)

        self.stats_label = QLabel("暂无数据")
        self.stats_label.setFont(QFont("Microsoft YaHei", 10))
        self.stats_label.setStyleSheet("color: #888888;")
        data_card_layout.addWidget(self.stats_label)

        layout.addWidget(card_data)

        # ========== 卡片4：图表 + 数据记录 ==========
        card_chart = QWidget()
        card_chart.setObjectName("card")
        card_chart.setStyleSheet(card_style())
        chart_card_layout = QVBoxLayout(card_chart)
        chart_card_layout.setContentsMargins(20, 16, 20, 16)
        chart_card_layout.setSpacing(12)

        chart_title = QLabel("电压-时间曲线")
        chart_title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        chart_title.setStyleSheet("color: #1a1a1a;")
        chart_card_layout.addWidget(chart_title)

        content_row = QHBoxLayout()
        content_row.setSpacing(16)

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

        self.figure = Figure(figsize=(8, 5), dpi=100)
        self.figure.set_facecolor('#fafafa')
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setStyleSheet("border: 1px solid #e5e5e5; border-radius: 6px;")
        content_row.addWidget(self.canvas, stretch=2)

        chart_card_layout.addLayout(content_row)
        layout.addWidget(card_chart)

        # ========== 卡片5：操作按钮 ==========
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

        # 去皮按钮：取最近若干个数据点平均值作为空载偏移
        self.tare_btn = QPushButton("去皮" if not self.tare_active else "取消去皮")
        self.tare_btn.setFixedHeight(38)
        self.tare_btn.clicked.connect(self.toggle_tare)
        self.tare_btn.setEnabled(False)
        self.tare_btn.setStyleSheet(accent_btn_style("#fd7e14", "#e06b00", "#c75a00")
                                    if not self.tare_active else
                                    accent_btn_style("#28a745", "#218838", "#1e7e34"))
        actions_layout.addWidget(self.tare_btn)

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

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_chart)
        self.timer.start(100)

    def on_mode_changed(self, index):
        if index == 0:
            self.serial_panel.show()
            self.ble_panel.hide()
        else:
            self.serial_panel.hide()
            self.ble_panel.show()

    def on_adc_bits_changed(self, index):
        bits_map = {0: 8, 1: 10, 2: 12, 3: 14, 4: 16, 5: 18, 6: 20, 7: 22, 8: 24}
        self.adc_bits = bits_map.get(index, 12)
        self.save_config()
        self.update_range_display()

    def on_divider_changed(self, value):
        self.divider_ratio = value
        self.save_config()
        self.update_range_display()

    def on_amp_changed(self, value):
        self.amp_ratio = value
        self.save_config()
        self.update_range_display()

    def on_hx711_mode_changed(self, checked):
        """HX711 模式开关：启用后强制 ADC 位数=24，并切换至有符号换算"""
        self.hx711_mode = checked
        self.hx711_avdd_spin.setEnabled(checked)
        self.hx711_channel_combo.setEnabled(checked)
        if checked:
            # 强制切到 24 位选项
            self.adc_bits_combo.setCurrentIndex(8)
            self.adc_bits = 24
        self.save_config()
        self.update_range_display()

    def on_hx711_avdd_changed(self, value):
        self.hx711_avdd = value
        self.save_config()
        self.update_range_display()

    def on_hx711_channel_changed(self, index):
        self.hx711_channel = 'B' if index == 0 else 'A'
        self.save_config()
        self.update_range_display()

    def on_unit_changed(self, index):
        """切换显示单位：kV / V / mV。内部数据不变，仅刷新显示"""
        unit_map = {0: 'kV', 1: 'V', 2: 'mV'}
        self.current_unit = unit_map.get(index, 'V')
        self.save_config()
        # 刷新实时数据/统计/图表的显示
        self.update_stats()
        self.update_chart()
        # 刷新去皮状态标签（单位变了显示值要跟着变）
        self.update_tare_status_label()
        # 刷新当前电压大字显示（如果有最后一个数据点）
        if self.voltage_data:
            self.current_voltage_label.setText(f"{self.format_voltage(self.voltage_data[-1])} {self.current_unit}")

    def update_tare_status_label(self):
        """根据当前去皮状态刷新状态标签和按钮文字"""
        if self.tare_active:
            self.tare_status_label.setText(
                f"已启用 (偏移 {self.format_voltage(self.tare_offset_v)} {self.current_unit})")
            self.tare_status_label.setStyleSheet("color: green; font-weight: bold;")
            self.tare_btn.setText("取消去皮")
            self.tare_btn.setStyleSheet(accent_btn_style("#28a745", "#218838", "#1e7e34"))
        else:
            self.tare_status_label.setText("未启用")
            self.tare_status_label.setStyleSheet("color: #888; font-weight: bold;")
            self.tare_btn.setText("去皮")
            self.tare_btn.setStyleSheet(accent_btn_style("#fd7e14", "#e06b00", "#c75a00"))

    def toggle_tare(self):
        """去皮/取消去皮切换
        去皮：取最近若干个数据点的平均值作为空载偏移，从测量值中扣除
        取消：清空偏移，恢复原始测量值
        """
        if self.tare_active:
            # 取消去皮
            self.tare_active = False
            self.tare_offset_v = 0.0
            self.save_config()
            self.update_tare_status_label()
            # 重新计算已有数据（按新偏移重算 voltage_data）
            self.recompute_voltage_data()
        else:
            # 执行去皮：要求有数据
            if not self.voltage_data:
                QMessageBox.warning(self, "提示", "请先开始采集数据后再去皮")
                return
            # 取最近 10 个数据点平均值作为空载偏移
            recent = self.voltage_data[-10:] if len(self.voltage_data) >= 10 else self.voltage_data
            self.tare_offset_v = float(np.mean(recent))
            self.tare_active = True
            self.save_config()
            self.update_tare_status_label()
            self.recompute_voltage_data()

    def recompute_voltage_data(self):
        """去皮状态变化后，按已有 raw_data 重算 voltage_data"""
        if not self.raw_data:
            return
        self.voltage_data = [self.adc_to_voltage(r) for r in self.raw_data]
        self.update_stats()
        self.update_chart()
        if self.voltage_data:
            self.current_voltage_label.setText(
                f"{self.format_voltage(self.voltage_data[-1])} {self.current_unit}")

    def update_range_display(self):
        if self.hx711_mode:
            gain = 128 if self.hx711_channel == 'A' else 32
            fs = self.hx711_avdd / gain  # 满量程差分电压（单边）
            self.range_label.setText(f"量程: ±{fs*1000:.1f}mV (HX711 通道{self.hx711_channel}, Gain{gain})")
            actual_max = fs * self.divider_ratio / self.amp_ratio
            self.actual_range_label.setText(f"实际量程: ±{actual_max*1000:.2f}mV")
        else:
            max_adc = self.ADC_BITS_OPTIONS.get(self.adc_bits, 4096) - 1
            self.range_label.setText(f"量程: 0 ~ {self.VREF:.1f}V (ADC {max_adc})")
            actual_max = self.VREF * self.divider_ratio / self.amp_ratio
            self.actual_range_label.setText(f"实际量程: 0 ~ {actual_max:.2f}V")

    def refresh_ports(self):
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.port_combo.addItem(port.device)

    def scan_ble(self):
        if not BLE_AVAILABLE:
            QMessageBox.warning(self, "提示", "请先安装 bleak 库：pip install bleak")
            return
        self.ble_scan_btn.setEnabled(False)
        self.ble_scan_btn.setText("扫描中...")
        self._ble_scan_thread = threading.Thread(target=self._do_scan_ble, daemon=True)
        self._ble_scan_thread.start()

    def _do_scan_ble(self):
        try:
            devices = scan_ble_devices()
            self.ble_device_combo.clear()
            for name, addr in devices:
                self.ble_device_combo.addItem(f"{name} ({addr})")
            if not devices:
                self.ble_device_combo.addItem("未找到设备")
        except Exception as e:
            print(f"BLE 扫描错误: {e}")
        finally:
            self.ble_scan_btn.setEnabled(BLE_AVAILABLE)
            self.ble_scan_btn.setText("扫描BLE")

    def connect_device(self):
        mode = self.mode_combo.currentText()
        if "BLE" in mode:
            self.connect_ble()
        else:
            self.connect_serial()

    def connect_serial(self):
        port = self.port_combo.currentText()
        if not port:
            QMessageBox.warning(self, "错误", "请选择串口")
            return
        try:
            self.serial_thread = SerialThread(port)
            self.serial_thread.data_received.connect(self.handle_data)
            self.serial_thread.start()
            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(True)
            self.start_btn.setEnabled(True)
            self.current_voltage_label.setText("--.- V")
            self.current_raw_label.setText("原始ADC: 连接中...")
            self.current_vadc_label.setText("ADC端电压: --.- V")
        except Exception as e:
            QMessageBox.critical(self, "连接错误", f"无法连接串口: {e}")

    def connect_ble(self):
        if not BLE_AVAILABLE:
            QMessageBox.warning(self, "提示", "请先安装 bleak 库：pip install bleak")
            return
        device_text = self.ble_device_combo.currentText()
        if not device_text or "未找到" in device_text:
            QMessageBox.warning(self, "提示", "请先扫描并选择 BLE 设备")
            return
        try:
            address = device_text.split("(")[-1].rstrip(")")
        except:
            QMessageBox.warning(self, "提示", "无法解析设备地址")
            return
        try:
            self.ble_thread = BLESerialThread(address)
            self.ble_thread.data_received.connect(self.handle_data)
            self.ble_thread.connection_status.connect(self.on_ble_status)
            self.ble_thread.start()
            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(True)
            self.start_btn.setEnabled(True)
            self.current_voltage_label.setText("BLE连接中...")
            self.current_raw_label.setText("ADC: BLE连接中...")
        except Exception as e:
            QMessageBox.critical(self, "连接错误", f"BLE 连接失败: {e}")

    def on_ble_status(self, status):
        if status == "connected":
            self.current_voltage_label.setText("电压: BLE已连接，等待数据...")
            self.current_raw_label.setText("原始ADC: 等待数据...")

    def disconnect_all(self):
        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread.wait()
            self.serial_thread = None
        if self.ble_thread:
            self.ble_thread.stop()
            self.ble_thread.wait()
            self.ble_thread = None
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.tare_btn.setEnabled(False)
        self.current_voltage_label.setText(f"--.- {self.current_unit}")
        self.current_raw_label.setText("原始ADC: 已断开")
        self.current_vadc_label.setText("ADC端电压: --.- V")

    def start_collection(self):
        self.voltage_data.clear()
        self.time_data.clear()
        self.raw_data.clear()
        self.data_text.clear()
        self.last_sample_time_ms = 0  # 重置采样时间
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.tare_btn.setEnabled(True)
        self.save_btn.setEnabled(False)
        self.current_voltage_label.setText("电压: 采集中...")
        self.current_raw_label.setText("原始ADC: 采集中...")

    def stop_collection(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.save_btn.setEnabled(len(self.voltage_data) > 0)
        if len(self.voltage_data) > 0:
            avg_v = np.mean(self.voltage_data)
            self.current_voltage_label.setText(f"{self.format_voltage(avg_v)} {self.current_unit}")

    def handle_data(self, data):
        if data.startswith("ERROR:"):
            QMessageBox.critical(self, "连接错误", data[6:])
            self.disconnect_all()
            return

        if data == "START":
            self.current_voltage_label.setText("电压: 设备就绪")
            self.current_raw_label.setText("原始ADC: 等待数据...")
            return

        if not self.stop_btn.isEnabled():
            try:
                if "," in data:
                    parts = data.split(",")
                    if len(parts) == 2:
                        raw_value = int(parts[1])
                        voltage = self.adc_to_voltage(raw_value)
                        v_adc = self.adc_to_vadc(raw_value)
                        self.current_raw_label.setText(f"原始ADC: {raw_value}")
                        self.current_voltage_label.setText(f"{self.format_voltage(voltage)} {self.current_unit}")
                        self.current_vadc_label.setText(f"ADC端电压: {self.format_voltage(v_adc)} {self.current_unit}")
            except ValueError:
                pass
            return

        try:
            if "," in data:
                parts = data.split(",")
                if len(parts) == 2:
                    timestamp_ms = int(parts[0])
                    raw_value = int(parts[1])

                    # 采样频率控制：检查是否达到采样间隔
                    if timestamp_ms - self.last_sample_time_ms < self.sample_interval_ms:
                        return  # 未达到采样间隔，跳过此数据

                    # 更新上次采样时间
                    self.last_sample_time_ms = timestamp_ms

                    if len(self.time_data) == 0:
                        self.start_timestamp_ms = timestamp_ms

                    relative_time_s = (timestamp_ms - self.start_timestamp_ms) / 1000.0

                    self.raw_data.append(raw_value)

                    voltage = self.adc_to_voltage(raw_value)
                    v_adc = self.adc_to_vadc(raw_value)

                    self.voltage_data.append(voltage)
                    self.time_data.append(relative_time_s)

                    current_time = datetime.now()
                    time_str = current_time.strftime("%H:%M:%S.%f")[:-3]

                    display_text = (f"时间: {time_str} | ADC: {raw_value} | "
                                    f"ADC端: {self.format_voltage(v_adc)} {self.current_unit} | "
                                    f"实际电压: {self.format_voltage(voltage)} {self.current_unit}")
                    self.current_raw_label.setText(f"原始ADC: {raw_value}")
                    self.current_voltage_label.setText(f"{self.format_voltage(voltage)} {self.current_unit}")
                    self.current_vadc_label.setText(f"ADC端电压: {self.format_voltage(v_adc)} {self.current_unit}")

                    self.data_text.append(display_text)
                    self.data_text.verticalScrollBar().setValue(
                        self.data_text.verticalScrollBar().maximum()
                    )

                    self.update_stats()

        except ValueError:
            pass

    def update_stats(self):
        if len(self.voltage_data) > 0:
            avg_v = np.mean(self.voltage_data)
            max_v = np.max(self.voltage_data)
            min_v = np.min(self.voltage_data)
            std_v = np.std(self.voltage_data)
            u = self.current_unit

            stats_text = (f"统计: 数据点 {len(self.voltage_data)} | "
                         f"平均={self.format_voltage(avg_v)}{u} | "
                         f"最大={self.format_voltage(max_v)}{u} | "
                         f"最小={self.format_voltage(min_v)}{u} | "
                         f"标准差 σ={self.format_voltage(std_v)}{u}")
            self.stats_label.setText(stats_text)

    def update_chart(self):
        if len(self.voltage_data) > 0:
            self.figure.clear()
            ax = self.figure.add_subplot(111)

            # 图表数据按当前单位换算
            display_data = [self.to_current_unit(v) for v in self.voltage_data]
            ax.plot(self.time_data, display_data, '#0078d4', linewidth=2, label=f'电压 ({self.current_unit})')
            ax.set_xlabel('时间 (秒)')
            ax.set_ylabel(f'电压 ({self.current_unit})')
            ax.set_title('电压传感器实时数据', fontsize=14, fontweight='bold')
            ax.grid(True, alpha=0.3)
            ax.legend(loc='upper right')

            if len(self.time_data) > 1:
                ax.set_xlim(min(self.time_data), max(self.time_data))

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
            self.save_config()
            QMessageBox.information(self, "成功",
                                   f"采样频率已更新为 {freq} Hz！\n"
                                   f"采样间隔：{new_interval_ms} ms\n"
                                   f"配置已自动保存。")

    def save_data(self):
        if len(self.voltage_data) == 0:
            QMessageBox.warning(self, "警告", "没有数据可保存")
            return
        try:
            filename = f"voltage_sensor_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', encoding='utf-8') as f:
                # CSV 表头按当前单位命名，方便后续分析
                f.write(f"timestamp_s,raw_adc,voltage_{self.current_unit.lower()}\n")
                for i, (timestamp, voltage) in enumerate(zip(self.time_data, self.voltage_data)):
                    raw = self.raw_data[i] if i < len(self.raw_data) else 0
                    f.write(f"{timestamp:.3f},{raw},{self.to_current_unit(voltage):.6f}\n")
            QMessageBox.information(self, "成功", f"数据已保存到: {filename}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")

    def clear_data(self):
        self.voltage_data.clear()
        self.time_data.clear()
        self.raw_data.clear()
        self.data_text.clear()
        self.current_voltage_label.setText(f"--.- {self.current_unit}")
        self.current_raw_label.setText("原始ADC: ------")
        self.current_vadc_label.setText(f"ADC端电压: --.- {self.current_unit}")
        self.stats_label.setText("统计信息: 暂无数据")
        self.figure.clear()
        self.canvas.draw()
        self.save_btn.setEnabled(False)
