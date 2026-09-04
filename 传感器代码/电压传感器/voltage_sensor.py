# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

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
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter
from qfluentwidgets import (
    PushButton, PrimaryPushButton, ComboBox, TextEdit, TitleLabel,
    BodyLabel, CaptionLabel, DoubleSpinBox, SwitchButton,
)
import numpy as np

# 从公共模块导入共享代码
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core import (
    fluent_message_box, ChartPanel,
    SerialThread, BLESerialThread, scan_ble_devices, SimulatorThread,
    SampleRateComboBox,
    load_sensor_config, save_sensor_config,
    SERIAL_AVAILABLE, list_serial_ports, serial_unavailable_hint,
    card_style, primary_btn_style, accent_btn_style, modern_combo_style,
    BLE_AVAILABLE, CollapsibleCard, FluentCard, ExpandableTextEdit,
    scroll_area_style, page_bg_style, apply_module_theme,
    update_collect_btn, set_action_button_width,
)


class VoltageSensorWidget(QWidget):
    """电压传感器模块界面 - 支持ADC位数选择和电压分压放大比"""

    # 有符号 ADC 满量程：±(2^N - 1)，例如 12 位 → ±4095
    ADC_BITS_OPTIONS = {8: 255, 10: 1023, 12: 4095, 14: 16383, 16: 65535, 18: 262143, 20: 1048575, 22: 4194303, 24: 16777215}
    VREF = 3.3

    # ADS1115 PGA 量程（TI ADS1115 数据手册 SBAS444E，9.3.3 节）
    # 16 位有符号二进制补码（-32768~+32767），电压 = raw / 32768 × FSR
    ADS1115_PGA_RANGES = {
        '±6.144V': 6.144,
        '±4.096V': 4.096,
        '±2.048V': 2.048,  # 默认（PGA=010）
        '±1.024V': 1.024,
        '±0.512V': 0.512,
        '±0.256V': 0.256,
    }
    # ADS1115 输入通道（MUX）：4 单端 + 2 差分
    ADS1115_CHANNELS = ['AIN0', 'AIN1', 'AIN2', 'AIN3', 'AIN0-AIN1', 'AIN2-AIN3']

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
        self._collecting = False  # 当前是否在采集（合并开始/停止按钮状态）
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
        # ADS1115 专用参数：16 位有符号补码 + 6 档 PGA + 4 单端/2 差分 MUX
        self.ads1115_mode = False
        self.ads1115_pga = '±2.048V'   # 默认 PGA=010（数据手册默认值）
        self.ads1115_channel = 'AIN0'  # 默认单端 AIN0
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
        self.ads1115_mode = self.config.get('ads1115_mode', False)
        self.ads1115_pga = self.config.get('ads1115_pga', '±2.048V')
        self.ads1115_channel = self.config.get('ads1115_channel', 'AIN0')
        self.current_unit = self.config.get('current_unit', 'V')
        self.tare_offset_v = self.config.get('tare_offset_v', 0.0)
        self.tare_active = self.config.get('tare_active', False)

        self.init_ui()
        # pyserial 未安装：自动切换到模拟器模式（串口连接优雅降级）
        if not SERIAL_AVAILABLE:
            self.mode_combo.setCurrentIndex(self.mode_combo.findText("模拟器"))

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
            self.ads1115_mode = config.get('ads1115_mode', False)
            self.ads1115_pga = config.get('ads1115_pga', '±2.048V')
            self.ads1115_channel = config.get('ads1115_channel', 'AIN0')
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
            'ads1115_mode': self.ads1115_mode,
            'ads1115_pga': self.ads1115_pga,
            'ads1115_channel': self.ads1115_channel,
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
        """计算 ADC 输入端电压（未做分压/放大还原）。

        统一有符号换算：下位机输出有符号 ADC 值，0 对应 0V，量程 -VREF~+VREF。
        例如 12 位 ADC，原始值 -4095~+4095，0 对应 0V，
        -4095 对应 -VREF，+4095 对应 +VREF。
        公式：(adc / max_adc) × VREF
        """
        # HX711 模式：24位有符号，参考电压 = AVDD / Gain
        if self.hx711_mode:
            gain = 128 if self.hx711_channel == 'A' else 32
            return adc_value / 8388608.0 * (self.hx711_avdd / gain)
        # ADS1115 模式：16位有符号补码，电压 = raw / 32768 × FSR
        # 数据手册 SBAS444E 9.3.3 节：FSR 由 PGA 设置（±6.144V ~ ±0.256V）
        if self.ads1115_mode:
            fsr = self.ADS1115_PGA_RANGES.get(self.ads1115_pga, 2.048)
            return adc_value / 32768.0 * fsr
        max_adc = self.ADC_BITS_OPTIONS.get(self.adc_bits, 4095)
        return (adc_value / max_adc) * self.VREF

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
        title = TitleLabel("电压")
        layout.addWidget(title)

        # ========== 卡片1：连接控制（可折叠） ==========
        card_conn_content = QWidget()
        card_conn_content.setObjectName("card")
        card_conn_content.setStyleSheet(card_style())
        card_layout = QVBoxLayout(card_conn_content)
        card_layout.setContentsMargins(20, 4, 20, 16)
        card_layout.setSpacing(12)

        # 第一行：连接方式 + 设备选择 + 按钮
        row1 = QHBoxLayout()
        row1.setSpacing(10)

        row1.addWidget(BodyLabel("连接方式:"))
        self.mode_combo = ComboBox()
        self.mode_combo.addItems(["有线串口", "BLE蓝牙", "模拟器"])
        if not BLE_AVAILABLE:
            self.mode_combo.setItemEnabled(1, False)
            self.mode_combo.setItemText(1, "BLE蓝牙（未安装bleak）")
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        row1.addWidget(self.mode_combo)

        self.serial_panel = QWidget()
        serial_layout = QHBoxLayout(self.serial_panel)
        serial_layout.setContentsMargins(0, 0, 0, 0)
        serial_layout.setSpacing(8)
        serial_layout.addWidget(BodyLabel("串口:"))
        self.port_combo = ComboBox()
        self.refresh_ports()
        self.port_combo.setMinimumWidth(140)
        serial_layout.addWidget(self.port_combo)
        self.refresh_btn = PushButton("刷新")
        self.refresh_btn.setFixedHeight(36)
        self.refresh_btn.setStyleSheet(self.CARD_BTN_STYLE)
        self.refresh_btn.clicked.connect(self.refresh_ports)
        serial_layout.addWidget(self.refresh_btn)

        self.ble_panel = QWidget()
        ble_layout = QHBoxLayout(self.ble_panel)
        ble_layout.setContentsMargins(0, 0, 0, 0)
        ble_layout.setSpacing(8)
        self.ble_device_combo = ComboBox()
        self.ble_device_combo.setMinimumWidth(180)
        ble_layout.addWidget(self.ble_device_combo)
        self.ble_scan_btn = PushButton("扫描BLE")
        self.ble_scan_btn.setFixedHeight(36)
        self.ble_scan_btn.setStyleSheet(self.CARD_BTN_STYLE)
        self.ble_scan_btn.clicked.connect(self.scan_ble)
        if not BLE_AVAILABLE:
            self.ble_scan_btn.setEnabled(False)
        ble_layout.addWidget(self.ble_scan_btn)

        # 模拟器面板：无需选择端口
        self.sim_panel = QWidget()
        sim_layout = QHBoxLayout(self.sim_panel)
        sim_layout.setContentsMargins(0, 0, 0, 0)
        sim_layout.setSpacing(8)
        sim_hint = CaptionLabel("无需硬件，生成随机数据用于调试")
        sim_layout.addWidget(sim_hint)
        sim_layout.addStretch()

        row1.addWidget(self.serial_panel)
        row1.addWidget(self.ble_panel)
        row1.addWidget(self.sim_panel)
        self.ble_panel.hide()
        self.sim_panel.hide()

        row1.addSpacing(16)
        self.connect_btn = PushButton("连接")
        self.connect_btn.setFixedHeight(36)
        self.connect_btn.setStyleSheet(self.CARD_BTN_STYLE)
        self.connect_btn.clicked.connect(self.toggle_connection)
        row1.addWidget(self.connect_btn)

        row1.addSpacing(16)
        row1.addWidget(BodyLabel("采样频率:"))
        self.sample_rate_combo = SampleRateComboBox()
        self.sample_rate_combo.setSampleInterval(self.sample_interval_ms)
        self.sample_rate_combo.setMaximumWidth(120)
        self.sample_rate_combo.sampleIntervalChanged.connect(self.on_sample_interval_changed)
        row1.addWidget(self.sample_rate_combo)

        row1.addStretch()
        card_layout.addLayout(row1)

        card_conn = FluentCard("连接控制", card_conn_content, expanded=True)
        layout.addWidget(card_conn)

        # ========== 卡片2：ADC 与电路参数（可折叠） ==========
        card_adc_content = QWidget()
        card_adc_content.setObjectName("card")
        card_adc_content.setStyleSheet(card_style())
        adc_card_layout = QVBoxLayout(card_adc_content)
        adc_card_layout.setContentsMargins(20, 4, 20, 16)
        adc_card_layout.setSpacing(12)

        bits_row = QHBoxLayout()
        bits_row.setSpacing(10)
        bits_row.addWidget(BodyLabel("ADC 位数:"))
        self.adc_bits_combo = ComboBox()
        self.adc_bits_combo.addItems([
            "8 位 (-255~+255)",
            "10 位 (-1023~+1023)",
            "12 位 (-4095~+4095)  ESP32内置",
            "14 位 (-16383~+16383)",
            "16 位 (-65535~+65535)  ADS1115等",
            "18 位 (-262143~+262143)",
            "20 位 (-1048575~+1048575)",
            "22 位 (-4194303~+4194303)",
            "24 位 (-16777215~+16777215)  HX711等"
        ])
        bits_map = {0: 8, 1: 10, 2: 12, 3: 14, 4: 16, 5: 18, 6: 20, 7: 22, 8: 24}
        self.adc_bits_combo.setCurrentIndex(bits_map.get(self.adc_bits, 2))
        self.adc_bits_combo.currentIndexChanged.connect(self.on_adc_bits_changed)
        bits_row.addWidget(self.adc_bits_combo)

        bits_row.addWidget(BodyLabel("参考电压: 3.3V"))
        self.range_label = BodyLabel(f"量程: -{self.VREF:.2f}V~+{self.VREF:.2f}V")
        self.range_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        bits_row.addWidget(self.range_label)
        bits_row.addStretch()
        adc_card_layout.addLayout(bits_row)

        # HX711 模式行：仅在 ADC 位数=24 时显示（用容器包裹便于整体显隐）
        self.hx711_panel = QWidget()
        hx711_row = QHBoxLayout(self.hx711_panel)
        hx711_row.setContentsMargins(0, 0, 0, 0)
        hx711_row.setSpacing(10)
        self.hx711_check = SwitchButton("HX711 模式（24位有符号）")
        self.hx711_check.setChecked(self.hx711_mode)
        self.hx711_check.setToolTip("启用后按 HX711 有符号 24 位 + AVDD/Gain 换算电压\n通道A=增益128，通道B=增益32")
        self.hx711_check.checkedChanged.connect(self.on_hx711_mode_changed)
        hx711_row.addWidget(self.hx711_check)

        hx711_row.addWidget(BodyLabel("AVDD:"))
        self.hx711_avdd_spin = DoubleSpinBox()
        self.hx711_avdd_spin.setRange(2.7, 5.5)
        self.hx711_avdd_spin.setDecimals(2)
        self.hx711_avdd_spin.setSingleStep(0.1)
        self.hx711_avdd_spin.setValue(self.hx711_avdd)
        self.hx711_avdd_spin.setSuffix(" V")
        self.hx711_avdd_spin.setMinimumWidth(90)
        self.hx711_avdd_spin.valueChanged.connect(self.on_hx711_avdd_changed)
        self.hx711_avdd_spin.setEnabled(self.hx711_mode)
        hx711_row.addWidget(self.hx711_avdd_spin)

        hx711_row.addWidget(BodyLabel("通道:"))
        self.hx711_channel_combo = ComboBox()
        self.hx711_channel_combo.addItems(["B (增益 32, ±156mV)", "A (增益 128, ±39mV)"])
        self.hx711_channel_combo.setCurrentIndex(0 if self.hx711_channel == 'B' else 1)
        self.hx711_channel_combo.currentIndexChanged.connect(self.on_hx711_channel_changed)
        self.hx711_channel_combo.setEnabled(self.hx711_mode)
        hx711_row.addWidget(self.hx711_channel_combo)

        hx711_row.addStretch()
        adc_card_layout.addWidget(self.hx711_panel)
        # 仅 24 位时显示 HX711 选项；非 24 位时自动取消勾选
        self.hx711_panel.setVisible(self.adc_bits == 24)
        if self.adc_bits != 24 and self.hx711_mode:
            self.hx711_check.setChecked(False)

        # ADS1115 模式行：仅在 ADC 位数=16 时显示
        # TI ADS1115：16位有符号补码 + 6档PGA + 4单端/2差分 MUX，I2C 接口
        # 数据手册 SBAS444E
        self.ads1115_panel = QWidget()
        ads1115_row = QHBoxLayout(self.ads1115_panel)
        ads1115_row.setContentsMargins(0, 0, 0, 0)
        ads1115_row.setSpacing(10)
        self.ads1115_check = SwitchButton("ADS1115 模式（16位有符号补码）")
        self.ads1115_check.setChecked(self.ads1115_mode)
        self.ads1115_check.setToolTip(
            "TI ADS1115 16位 I2C ADC\n"
            "有符号二进制补码（-32768~+32767）\n"
            "电压 = raw / 32768 × FSR\n"
            "6档PGA量程：±6.144V ~ ±0.256V\n"
            "4路单端或2路差分输入（MUX）"
        )
        self.ads1115_check.checkedChanged.connect(self.on_ads1115_mode_changed)
        ads1115_row.addWidget(self.ads1115_check)

        ads1115_row.addWidget(BodyLabel("PGA:"))
        self.ads1115_pga_combo = ComboBox()
        self.ads1115_pga_combo.addItems(list(self.ADS1115_PGA_RANGES.keys()))
        self.ads1115_pga_combo.setCurrentText(self.ads1115_pga)
        self.ads1115_pga_combo.currentIndexChanged.connect(self.on_ads1115_pga_changed)
        self.ads1115_pga_combo.setEnabled(self.ads1115_mode)
        ads1115_row.addWidget(self.ads1115_pga_combo)

        ads1115_row.addWidget(BodyLabel("通道:"))
        self.ads1115_channel_combo = ComboBox()
        self.ads1115_channel_combo.addItems(self.ADS1115_CHANNELS)
        self.ads1115_channel_combo.setCurrentText(self.ads1115_channel)
        self.ads1115_channel_combo.currentIndexChanged.connect(self.on_ads1115_channel_changed)
        self.ads1115_channel_combo.setEnabled(self.ads1115_mode)
        ads1115_row.addWidget(self.ads1115_channel_combo)

        ads1115_row.addStretch()
        adc_card_layout.addWidget(self.ads1115_panel)
        # 仅 16 位时显示 ADS1115 选项；非 16 位时自动取消勾选
        self.ads1115_panel.setVisible(self.adc_bits == 16)
        if self.adc_bits != 16 and self.ads1115_mode:
            self.ads1115_check.setChecked(False)

        params_row = QHBoxLayout()
        params_row.setSpacing(10)

        # 分压比/放大倍数解释文字（原为常显灰色小字，现改为悬停 tooltip 显示）
        params_hint_text = ("分压比 = (R1+R2)/R2，用于还原分压前的原始电压；\n"
                            "放大倍数 = 运放增益，用于还原放大前的信号电压")

        divider_label = BodyLabel("分压比 (R1+R2)/R2:")
        divider_label.setToolTip(params_hint_text)
        params_row.addWidget(divider_label)
        self.divider_spin = DoubleSpinBox()
        self.divider_spin.setRange(1.0, 1000.0)
        self.divider_spin.setDecimals(2)
        self.divider_spin.setSingleStep(0.1)
        self.divider_spin.setValue(self.divider_ratio)
        self.divider_spin.setSuffix(" x")
        self.divider_spin.setMinimumWidth(120)
        self.divider_spin.setFixedHeight(32)
        self.divider_spin.setToolTip(params_hint_text)
        self.divider_spin.valueChanged.connect(self.on_divider_changed)
        params_row.addWidget(self.divider_spin)

        amp_label = BodyLabel("放大倍数:")
        amp_label.setToolTip(params_hint_text)
        params_row.addWidget(amp_label)
        self.amp_spin = DoubleSpinBox()
        self.amp_spin.setRange(0.01, 1000.0)
        self.amp_spin.setDecimals(2)
        self.amp_spin.setSingleStep(0.1)
        self.amp_spin.setValue(self.amp_ratio)
        self.amp_spin.setSuffix(" x")
        self.amp_spin.setMinimumWidth(120)
        self.amp_spin.setFixedHeight(32)
        self.amp_spin.setToolTip(params_hint_text)
        self.amp_spin.valueChanged.connect(self.on_amp_changed)
        params_row.addWidget(self.amp_spin)

        self.actual_range_label = BodyLabel(f"实际量程: -{self.VREF * self.divider_ratio / self.amp_ratio:.2f}V~+{self.VREF * self.divider_ratio / self.amp_ratio:.2f}V")
        self.actual_range_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        params_row.addWidget(self.actual_range_label)
        params_row.addStretch()
        adc_card_layout.addLayout(params_row)

        # 显示单位选择
        unit_row = QHBoxLayout()
        unit_row.setSpacing(10)
        unit_row.addWidget(BodyLabel("显示单位:"))
        self.unit_combo = ComboBox()
        self.unit_combo.addItems(["千伏 (kV)", "伏 (V)", "毫伏 (mV)"])
        unit_map = {'kV': 0, 'V': 1, 'mV': 2}
        self.unit_combo.setCurrentIndex(unit_map.get(self.current_unit, 1))
        self.unit_combo.currentIndexChanged.connect(self.on_unit_changed)
        unit_row.addWidget(self.unit_combo)
        unit_row.addStretch()
        adc_card_layout.addLayout(unit_row)

        # 去皮状态显示行
        tare_row = QHBoxLayout()
        tare_row.setSpacing(10)
        tare_row.addWidget(BodyLabel("去皮:"))
        self.tare_status_label = BodyLabel("未启用" if not self.tare_active else
                                        f"已启用 (偏移 {self.format_voltage(self.tare_offset_v)} {self.current_unit})")
        self.tare_status_label.setStyleSheet("color: green; font-weight: bold;" if self.tare_active
                                             else "color: #888; font-weight: bold;")
        tare_row.addWidget(self.tare_status_label)
        tare_row.addStretch()
        adc_card_layout.addLayout(tare_row)

        card_adc = FluentCard("ADC 与电路参数", card_adc_content, expanded=True)
        layout.addWidget(card_adc)

        # ========== 卡片3：实时数据（可折叠） ==========
        card_data_content = QWidget()
        card_data_content.setObjectName("card")
        card_data_content.setStyleSheet(card_style())
        data_card_layout = QVBoxLayout(card_data_content)
        data_card_layout.setContentsMargins(20, 4, 20, 16)
        data_card_layout.setSpacing(12)

        self.current_voltage_label = BodyLabel("--.- V")
        self.current_voltage_label.setFont(QFont("Cascadia Code", 24, QFont.Weight.Bold))
        self.current_voltage_label.setStyleSheet("color: #0078d4;")
        data_card_layout.addWidget(self.current_voltage_label)

        raw_row = QHBoxLayout()
        raw_row.setSpacing(20)
        self.current_raw_label = BodyLabel("原始ADC: ------")
        self.current_raw_label.setFont(QFont("Cascadia Code", 11))
        self.current_raw_label.setStyleSheet("color: #444444;")
        raw_row.addWidget(self.current_raw_label)

        self.current_vadc_label = BodyLabel("ADC端电压: --.- V")
        self.current_vadc_label.setFont(QFont("Cascadia Code", 11))
        self.current_vadc_label.setStyleSheet("color: #444444;")
        raw_row.addWidget(self.current_vadc_label)
        raw_row.addStretch()
        data_card_layout.addLayout(raw_row)

        self.stats_label = CaptionLabel("暂无数据")
        data_card_layout.addWidget(self.stats_label)

        card_data = FluentCard("实时数据", card_data_content, expanded=True)
        layout.addWidget(card_data)

        # ========== 卡片4：图表 + 数据记录（可折叠） ==========
        card_chart_content = QWidget()
        card_chart_content.setObjectName("card")
        card_chart_content.setStyleSheet(card_style())
        chart_card_layout = QVBoxLayout(card_chart_content)
        chart_card_layout.setContentsMargins(20, 4, 20, 16)
        chart_card_layout.setSpacing(12)

        content_row = QHBoxLayout()
        content_row.setSpacing(16)

        # 左侧栏：数据记录 + 图表分析（视图窗口/拟合/离群点，紧凑纵向排布）
        left_col = QVBoxLayout()
        left_col.setSpacing(10)
        self.data_text = ExpandableTextEdit()
        left_col.addWidget(self.data_text)

        # 双引擎图表面板（matplotlib / pyqtgraph，设置页可切换）
        self.chart = ChartPanel()
        # 图表分析面板（仅 pyqtgraph 显示，其余引擎自动隐藏）
        left_col.addWidget(self.chart.get_analysis_panel())
        content_row.addLayout(left_col, stretch=0)

        content_row.addWidget(self.chart, stretch=2)
        chart_card_layout.addLayout(content_row, 1)
        card_chart = CollapsibleCard("电压-时间曲线", card_chart_content, expanded=True, fullscreen=True)
        # 图表卡片加高为原来的 2 倍（内容区最小 400px），页面滚动查看
        card_chart.set_chart_min_height(400)
        # 全屏时：数据记录区作为可拖动折叠浮动面板浮于图表上方，折叠时显示实时电压值
        # 全屏浮动栏：合并的开始/停止按钮（与操作按钮卡的 collect_btn 同步状态）
        self.float_collect_btn = PrimaryPushButton("开始采集")
        self.float_collect_btn.setFixedHeight(34)
        update_collect_btn(self.float_collect_btn, False)
        self.float_collect_btn.clicked.connect(self.toggle_collection)
        self.float_collect_btn.setEnabled(False)
        # 全屏时：数据记录 + 拟合分析面板浮于图表上方，浮动栏底部可控制开始/停止
        card_chart.set_fullscreen_overlay(
            self.data_text, self.current_voltage_label,
            extra_widgets=[self.chart.get_analysis_panel()],
            footer_widget=self.float_collect_btn)
        layout.addWidget(card_chart)

        # ========== 卡片5：操作按钮（可折叠） ==========
        card_actions_content = QWidget()
        card_actions_content.setObjectName("card")
        card_actions_content.setStyleSheet(card_style())
        actions_layout = QHBoxLayout(card_actions_content)
        actions_layout.setContentsMargins(20, 4, 20, 12)
        actions_layout.setSpacing(10)

        # 开始/停止合并为单按钮：文案随采集状态切换（停止采集/开始采集）
        self.collect_btn = PrimaryPushButton("开始采集")
        self.collect_btn.setFixedHeight(38)
        update_collect_btn(self.collect_btn, False)
        self.collect_btn.clicked.connect(self.toggle_collection)
        self.collect_btn.setEnabled(False)
        actions_layout.addWidget(self.collect_btn)

        # 去皮按钮：取最近若干个数据点平均值作为空载偏移
        self.tare_btn = PushButton("去皮" if not self.tare_active else "取消去皮")
        self.tare_btn.setFixedHeight(38)
        set_action_button_width(self.tare_btn)
        self.tare_btn.clicked.connect(self.toggle_tare)
        self.tare_btn.setEnabled(False)
        self.tare_btn.setStyleSheet("background-color: #fd7e14; color: white;"
                                    if not self.tare_active else
                                    "background-color: #28a745; color: white;")
        actions_layout.addWidget(self.tare_btn)

        

        self.save_btn = PushButton("保存数据")
        self.save_btn.setFixedHeight(38)
        set_action_button_width(self.save_btn)
        self.save_btn.clicked.connect(self.save_data)
        self.save_btn.setEnabled(False)
        actions_layout.addWidget(self.save_btn)

        self.clear_btn = PushButton("清除数据")
        self.clear_btn.setFixedHeight(38)
        set_action_button_width(self.clear_btn)
        self.clear_btn.clicked.connect(self.clear_data)
        actions_layout.addWidget(self.clear_btn)

        actions_layout.addStretch()
        card_actions = FluentCard("操作按钮", card_actions_content, expanded=True)
        layout.addWidget(card_actions)

        layout.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_chart)
        self.timer.start(100)

    def on_mode_changed(self, index):
        if index == 0:
            self.serial_panel.show()
            self.ble_panel.hide()
            self.sim_panel.hide()
        elif index == 1:
            self.serial_panel.hide()
            self.ble_panel.show()
            self.sim_panel.hide()
        else:
            self.serial_panel.hide()
            self.ble_panel.hide()
            self.sim_panel.show()

    def on_adc_bits_changed(self, index):
        bits_map = {0: 8, 1: 10, 2: 12, 3: 14, 4: 16, 5: 18, 6: 20, 7: 22, 8: 24}
        self.adc_bits = bits_map.get(index, 12)
        # HX711 选项仅 24 位时显示；切到非 24 位时自动取消 HX711 模式
        is_24bit = (self.adc_bits == 24)
        self.hx711_panel.setVisible(is_24bit)
        if not is_24bit and self.hx711_mode:
            self.hx711_check.setChecked(False)
        # ADS1115 选项仅 16 位时显示；切到非 16 位时自动取消 ADS1115 模式
        is_16bit = (self.adc_bits == 16)
        self.ads1115_panel.setVisible(is_16bit)
        if not is_16bit and self.ads1115_mode:
            self.ads1115_check.setChecked(False)
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

    def on_ads1115_mode_changed(self, checked):
        """ADS1115 模式开关：启用后强制 ADC 位数=16"""
        self.ads1115_mode = checked
        self.ads1115_pga_combo.setEnabled(checked)
        self.ads1115_channel_combo.setEnabled(checked)
        if checked:
            self.adc_bits_combo.setCurrentIndex(4)  # 16 位
            self.adc_bits = 16
        self.save_config()
        self.update_range_display()

    def on_ads1115_pga_changed(self, index):
        """切换 ADS1115 PGA 量程"""
        self.ads1115_pga = self.ads1115_pga_combo.itemText(index)
        self.save_config()
        self.update_range_display()

    def on_ads1115_channel_changed(self, index):
        """切换 ADS1115 输入通道（MUX）"""
        self.ads1115_channel = self.ads1115_channel_combo.itemText(index)
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
            self.tare_btn.setStyleSheet("background-color: #28a745; color: white;")
        else:
            self.tare_status_label.setText("未启用")
            self.tare_status_label.setStyleSheet("color: #888; font-weight: bold;")
            self.tare_btn.setText("去皮")
            self.tare_btn.setStyleSheet("background-color: #fd7e14; color: white;")

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
                fluent_message_box(self, "提示", "请先开始采集数据后再去皮")
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
        elif self.ads1115_mode:
            fsr = self.ADS1115_PGA_RANGES.get(self.ads1115_pga, 2.048)
            self.range_label.setText(f"量程: ±{fsr:.3f}V (ADS1115 PGA={self.ads1115_pga}, 通道{self.ads1115_channel})")
            actual_max = fsr * self.divider_ratio / self.amp_ratio
            self.actual_range_label.setText(f"实际量程: ±{actual_max:.3f}V")
        else:
            max_adc = self.ADC_BITS_OPTIONS.get(self.adc_bits, 4095)
            full = self.VREF
            self.range_label.setText(f"量程: -{full:.2f}V~+{full:.2f}V (ADC -{max_adc}~+{max_adc})")
            actual_full = full * self.divider_ratio / self.amp_ratio
            self.actual_range_label.setText(f"实际量程: -{actual_full:.2f}V~+{actual_full:.2f}V")

    def refresh_ports(self):
        """刷新可用串口列表（pyserial 未安装时显示占位提示）"""
        self.port_combo.clear()
        ports = list_serial_ports()
        for device, _desc in ports:
            self.port_combo.addItem(device)
        if not ports:
            self.port_combo.addItem("未安装 pyserial" if not SERIAL_AVAILABLE else "无可用串口")

    def scan_ble(self):
        if not BLE_AVAILABLE:
            fluent_message_box(self, "提示", "请先安装 bleak 库：pip install bleak")
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

    def toggle_connection(self):
        """切换连接状态：已连接则断开，否则按当前模式连接"""
        if (self.serial_thread and self.serial_thread.isRunning()) or \
           (self.ble_thread and self.ble_thread.isRunning()):
            self.disconnect_all()
        else:
            self.connect_device()

    def connect_device(self):
        mode = self.mode_combo.currentText()
        if "BLE" in mode:
            self.connect_ble()
        elif "模拟器" in mode:
            self.connect_simulator()
        else:
            self.connect_serial()

    def connect_simulator(self):
        """连接模拟器：随机生成 ADC 原始值，无需硬件"""
        try:
            # 模拟器产生有符号 ADC 范围的原始值，中点为 0V
            max_adc = self.ADC_BITS_OPTIONS.get(self.adc_bits, 4095)
            self.serial_thread = SimulatorThread(
                value_min=-max_adc, value_max=max_adc,
                interval_ms=self.sample_interval_ms)
            self.serial_thread.data_received.connect(self.handle_data)
            self.serial_thread.start()
            self.connect_btn.setText("断开")
            self._set_collect_enabled(True)
            self.current_voltage_label.setText("--.- V")
            self.current_raw_label.setText("原始ADC: 模拟器连接中...")
            self.current_vadc_label.setText("ADC端电压: --.- V")
        except Exception as e:
            fluent_message_box(self, "连接错误", f"模拟器启动失败: {e}")

    def connect_serial(self):
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
            self._set_collect_enabled(True)
            self.current_voltage_label.setText("--.- V")
            self.current_raw_label.setText("原始ADC: 连接中...")
            self.current_vadc_label.setText("ADC端电压: --.- V")
        except Exception as e:
            fluent_message_box(self, "连接错误", f"无法连接串口: {e}")

    def connect_ble(self):
        if not BLE_AVAILABLE:
            fluent_message_box(self, "提示", "请先安装 bleak 库：pip install bleak")
            return
        device_text = self.ble_device_combo.currentText()
        if not device_text or "未找到" in device_text:
            fluent_message_box(self, "提示", "请先扫描并选择 BLE 设备")
            return
        try:
            address = device_text.split("(")[-1].rstrip(")")
        except:
            fluent_message_box(self, "提示", "无法解析设备地址")
            return
        try:
            self.ble_thread = BLESerialThread(address)
            self.ble_thread.data_received.connect(self.handle_data)
            self.ble_thread.connection_status.connect(self.on_ble_status)
            self.ble_thread.start()
            self.connect_btn.setText("断开")
            self._set_collect_enabled(True)
            self.current_voltage_label.setText("BLE连接中...")
            self.current_raw_label.setText("ADC: BLE连接中...")
        except Exception as e:
            fluent_message_box(self, "连接错误", f"BLE 连接失败: {e}")

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
        self.connect_btn.setText("连接")
        self._set_collect_enabled(False)
        self.tare_btn.setEnabled(False)
        self.current_voltage_label.setText(f"--.- {self.current_unit}")
        self.current_raw_label.setText("原始ADC: 已断开")
        self.current_vadc_label.setText("ADC端电压: --.- V")

    def toggle_collection(self):
        """合并的开始/停止按钮：按当前采集状态切换。"""
        if self._collecting:
            self.stop_collection()
        else:
            self.start_collection()

    def _set_collect_enabled(self, enabled):
        """连接/断开时同步合并按钮与浮动栏按钮的可用性。"""
        self.collect_btn.setEnabled(enabled)
        self.float_collect_btn.setEnabled(enabled)

    def _refresh_collect_btn(self):
        """合并按钮与浮动栏按钮：文案随采集状态切换（停止采集/开始采集）。"""
        update_collect_btn(self.collect_btn, self._collecting)
        update_collect_btn(self.float_collect_btn, self._collecting)

    def start_collection(self):
        self.voltage_data.clear()
        self.time_data.clear()
        self.raw_data.clear()
        self.data_text.clear()
        self.last_sample_time_ms = 0  # 重置采样时间
        self._collecting = True
        self._refresh_collect_btn()
        self.tare_btn.setEnabled(True)
        self.save_btn.setEnabled(False)
        self.current_voltage_label.setText("电压: 采集中...")
        self.current_raw_label.setText("原始ADC: 采集中...")

    def stop_collection(self):
        self._collecting = False
        self._refresh_collect_btn()
        self.save_btn.setEnabled(len(self.voltage_data) > 0)
        if len(self.voltage_data) > 0:
            avg_v = np.mean(self.voltage_data)
            self.current_voltage_label.setText(f"{self.format_voltage(avg_v)} {self.current_unit}")

    def handle_data(self, data):
        if data.startswith("ERROR:"):
            fluent_message_box(self, "连接错误", data[6:])
            self.disconnect_all()
            return

        if data == "START":
            self.current_voltage_label.setText("电压: 设备就绪")
            self.current_raw_label.setText("原始ADC: 等待数据...")
            return

        if not self._collecting:
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
        if not self.isVisible():
            return  # 页面隐藏时跳过重绘（定时器不停止，避免白耗 UI 线程）
        if len(self.voltage_data) > 0:
            # 图表数据按当前单位换算
            display_data = [self.to_current_unit(v) for v in self.voltage_data]
            c = self.chart
            c.begin()
            c.plot(self.time_data, display_data, color='#0078d4', width=2,
                   label=f'电压 ({self.current_unit})')
            c.set_labels('时间 (秒)', f'电压 ({self.current_unit})')
            c.set_title('电压传感器实时数据')
            c.legend()
            if len(self.time_data) > 1:
                c.set_xlim(min(self.time_data), max(self.time_data))
            c.end()

    def on_sample_interval_changed(self, interval_ms):
        """采样频率改变时更新间隔并保存配置（内联下拉框触发）"""
        self.sample_interval_ms = interval_ms
        self.save_config()

    def save_data(self):
        if len(self.voltage_data) == 0:
            fluent_message_box(self, "警告", "没有数据可保存")
            return
        try:
            filename = f"voltage_sensor_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', encoding='utf-8') as f:
                # CSV 表头按当前单位命名，方便后续分析
                f.write(f"timestamp_s,raw_adc,voltage_{self.current_unit.lower()}\n")
                for i, (timestamp, voltage) in enumerate(zip(self.time_data, self.voltage_data)):
                    raw = self.raw_data[i] if i < len(self.raw_data) else 0
                    f.write(f"{timestamp:.3f},{raw},{self.to_current_unit(voltage):.6f}\n")
            fluent_message_box(self, "成功", f"数据已保存到: {filename}")
        except Exception as e:
            fluent_message_box(self, "错误", f"保存失败: {e}")

    def clear_data(self):
        self.voltage_data.clear()
        self.time_data.clear()
        self.raw_data.clear()
        self.data_text.clear()
        self.current_voltage_label.setText(f"--.- {self.current_unit}")
        self.current_raw_label.setText("原始ADC: ------")
        self.current_vadc_label.setText(f"ADC端电压: --.- {self.current_unit}")
        self.stats_label.setText("统计信息: 暂无数据")
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
