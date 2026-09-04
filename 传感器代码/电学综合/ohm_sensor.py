# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

# === MODULE META ===
# icon: R
# name: 欧姆定律
# category: physics
# class: OhmSensorWidget
# ===================

# -*- coding: utf-8 -*-
"""欧姆定律模块 — R = U / I

同时采集 电压 + 电流，实时计算电阻并验证欧姆定律：
- 连接方式三种：单板一体（一台 ESP32 烧录 电学综合/VI_*.ino，
  双通道同时输出 `时间戳,电压ADC,电流ADC`）/ 双板分测（复用
  电压传感器 + 电流传感器两块板，双串口）/ 模拟器
- 电压采样方式三选一：ESP32 内置 ADC / ADS1115 (16位) / HX711 (24位)，
  换算公式与 电压传感器 模块一致
- 电流：ACS712 5A/20A/30A 量程、DC/AC(有效值)、零点校准
- 图表：I-U 曲线（线性拟合斜率倒数 = 电阻 R，配合分析面板）+ R-t 曲线
"""

import numpy as np
from collections import deque
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QFileDialog,
)

from qfluentwidgets import (
    PushButton, PrimaryPushButton, ComboBox, DoubleSpinBox,
    BodyLabel, CaptionLabel, TitleLabel, isDarkTheme,
)

from core import (
    SERIAL_AVAILABLE, list_serial_ports, serial_unavailable_hint,
    SerialThread, SimulatorThread,
    load_sensor_config, save_sensor_config,
    ChartPanel, card_style, scroll_area_style, page_bg_style,
    apply_module_theme, fluent_message_box,
    FluentCard, CollapsibleCard, ExpandableTextEdit, SampleRateComboBox,
    update_collect_btn, set_action_button_width,
)


class OhmSensorWidget(QWidget):
    """欧姆定律模块 — 同时测电压 U 与电流 I，实时计算电阻 R = U/I。"""

    # ---- 电压换算常量（与电压传感器模块一致）----
    ADC_BITS_OPTIONS = {8: 255, 10: 1023, 12: 4095, 14: 16383,
                        16: 65535, 18: 262143, 20: 1048575,
                        22: 4194303, 24: 16777215}
    VREF = 3.3  # ESP32 ADC 参考电压

    # ADS1115 PGA 量程（TI ADS1115 数据手册 SBAS444E，9.3.3 节）
    ADS1115_PGA_RANGES = {
        '±6.144V': 6.144,
        '±4.096V': 4.096,
        '±2.048V': 2.048,   # 默认（PGA=010）
        '±1.024V': 1.024,
        '±0.512V': 0.512,
        '±0.256V': 0.256,
    }

    # ---- 电流换算常量（与电流传感器模块一致）----
    ACS712_RANGES = {
        '5A':  {'sensitivity': 0.185, 'range_a': 5,  'desc': 'ACS712ELC-05B  ±5A  185mV/A'},
        '20A': {'sensitivity': 0.100, 'range_a': 20, 'desc': 'ACS712ELC-20A  ±20A  100mV/A'},
        '30A': {'sensitivity': 0.066, 'range_a': 30, 'desc': 'ACS712ELC-30A  ±30A  66mV/A'},
    }
    UNIT_FACTORS = {'A': 1.0, 'mA': 1000.0}

    # 连接方式：单板一体 / 双板分测 / 模拟器
    MODE_VALUES = ['single', 'dual', 'simulator']
    # 电压采样方式（三套固件）
    VOLT_METHOD_VALUES = ['esp32', 'ads1115', 'hx711']

    # 无效电流判断阈值（A）：|I| 小于该值视为开路，电阻显示 "---"
    I_EPS = 1e-7

    def __init__(self):
        super().__init__()
        self.serial_vi = None     # 单板一体：唯一串口线程
        self.serial_v = None      # 双板分测：电压板串口
        self.serial_i = None      # 双板分测：电流板串口
        self.sim_v = None         # 模拟器：电压线程
        self.sim_i = None         # 模拟器：电流线程
        self._collecting = False
        self._connected = False

        # 数据
        self.time_data = []       # 相对时间 (s)
        self.v_data = []          # 电压 (V)
        self.i_data = []          # 电流 (A，AC 模式为有效值)
        self.r_data = []          # 电阻 (Ω)，无效 (开路) 时为 None
        self.raw_v = []           # 电压 ADC 原始值
        self.raw_i = []           # 电流 ADC 原始值
        self.start_timestamp_ms = 0
        self.last_sample_time_ms = 0

        # 采样频率（毫秒）
        self.sample_interval_ms = 100
        self.zero_cal_active = False
        self._recent_vs = deque(maxlen=10)  # 最近 N 个 ACS712 输出电压，用于零点校准
        # 双板/模拟器模式下电压-电流配对缓存（连接后、开始采集前也可能收数）
        self._pending_v = None
        self._pending_i = None
        # 退出慢的旧线程保留引用（切模式/断开时防止 QThread 销毁崩溃）
        self._retired_threads = []

        # 连接/测量配置
        self.connect_mode = 'single'     # single / dual / simulator
        self.volt_method = 'esp32'       # esp32 / ads1115 / hx711
        # 电压参数
        self.divider_ratio = 1.0         # 分压比 (R1+R2)/R2
        self.amp_ratio = 1.0             # 放大倍数
        self.ads1115_pga = '±6.144V'     # 与 VI_ADS1115.ino 默认 PGA 一致
        self.ads1115_channel = 'AIN0'
        self.hx711_avdd = 5.0
        self.hx711_channel = 'B'         # B=增益32（VI_HX711.ino 默认）
        # 电流参数
        self.acs_range = '5A'
        self.vcc = 5.0
        self.v_quiescent = 2.5           # 零电流输出电压（零点校准后更新）
        self.i_divider_ratio = 1.515     # ACS712 输出分压比
        self.current_mode = 'DC'         # DC / AC
        self.current_unit = 'A'
        self.adc_bits = 12
        self.ac_rms_window = 50          # AC 模式 RMS 滚动窗口

        self.config = self.load_config()
        self.init_ui()
        # pyserial 未安装：自动切模拟器
        if not SERIAL_AVAILABLE:
            self.mode_combo.setCurrentIndex(self.MODE_VALUES.index('simulator'))
            self.on_mode_changed(self.MODE_VALUES.index('simulator'))

    # --------------------------------------------------------------
    # 配置读写
    # --------------------------------------------------------------
    def load_config(self):
        config = load_sensor_config('ohm_sensor')
        if config:
            self.connect_mode = config.get('connect_mode', self.connect_mode)
            self.volt_method = config.get('volt_method', self.volt_method)
            self.divider_ratio = config.get('divider_ratio', self.divider_ratio)
            self.amp_ratio = config.get('amp_ratio', self.amp_ratio)
            self.ads1115_pga = config.get('ads1115_pga', self.ads1115_pga)
            self.ads1115_channel = config.get('ads1115_channel', self.ads1115_channel)
            self.hx711_avdd = config.get('hx711_avdd', self.hx711_avdd)
            self.hx711_channel = config.get('hx711_channel', self.hx711_channel)
            self.acs_range = config.get('acs_range', self.acs_range)
            self.vcc = config.get('vcc', self.vcc)
            self.v_quiescent = config.get('v_quiescent', self.v_quiescent)
            self.i_divider_ratio = config.get('i_divider_ratio', self.i_divider_ratio)
            self.current_mode = config.get('current_mode', self.current_mode)
            self.current_unit = config.get('current_unit', self.current_unit)
            self.zero_cal_active = config.get('zero_cal_active', False)
            self.sample_interval_ms = config.get('sample_interval_ms', 100)
            self.ac_rms_window = config.get('ac_rms_window', 50)
            self.adc_bits = config.get('adc_bits', 12)
        return config

    def save_config(self):
        config = {
            'connect_mode': self.connect_mode,
            'volt_method': self.volt_method,
            'divider_ratio': self.divider_ratio,
            'amp_ratio': self.amp_ratio,
            'ads1115_pga': self.ads1115_pga,
            'ads1115_channel': self.ads1115_channel,
            'hx711_avdd': self.hx711_avdd,
            'hx711_channel': self.hx711_channel,
            'acs_range': self.acs_range,
            'vcc': self.vcc,
            'v_quiescent': self.v_quiescent,
            'i_divider_ratio': self.i_divider_ratio,
            'current_mode': self.current_mode,
            'current_unit': self.current_unit,
            'zero_cal_active': self.zero_cal_active,
            'sample_interval_ms': self.sample_interval_ms,
            'ac_rms_window': self.ac_rms_window,
            'adc_bits': self.adc_bits,
        }
        return save_sensor_config('ohm_sensor', config)

    # --------------------------------------------------------------
    # 单位与换算
    # --------------------------------------------------------------
    def to_current_unit(self, current_a):
        return current_a * self.UNIT_FACTORS.get(self.current_unit, 1.0)

    def format_current(self, current_a):
        c = self.to_current_unit(current_a)
        if self.current_unit == 'mA':
            return f"{c:.2f}"
        abs_c = abs(c)
        if abs_c >= 1.0:
            return f"{c:.4f}"
        return f"{c:.6f}"

    @property
    def sensitivity(self):
        return self.ACS712_RANGES.get(self.acs_range,
                                      self.ACS712_RANGES['5A'])['sensitivity']

    def adc_to_voltage(self, adc_value):
        """电压 ADC 原始值 → 被测电压 (V)。

        换算公式与电压传感器模块一致：
        - esp32：adc / 4095 × 3.3V
        - ads1115：有符号 16 位补码，adc / 32768 × PGA 量程
        - hx711：有符号 24 位，adc / 8388608 × (AVDD / 增益)
        再按 分压比 / 放大倍数 还原实际电压。
        """
        if self.volt_method == 'ads1115':
            fsr = self.ADS1115_PGA_RANGES.get(self.ads1115_pga, 6.144)
            v_adc = adc_value / 32768.0 * fsr
        elif self.volt_method == 'hx711':
            gain = 128 if self.hx711_channel == 'A' else 32
            v_adc = adc_value / 8388608.0 * (self.hx711_avdd / gain)
        else:
            max_adc = self.ADC_BITS_OPTIONS.get(self.adc_bits, 4095)
            v_adc = (adc_value / max_adc) * self.VREF
        return v_adc * self.divider_ratio / self.amp_ratio

    def adc_to_vsensor(self, adc_value):
        """电流 ADC 原始值 → ACS712 输出电压 (V，扣除分压电路影响)。"""
        max_adc = self.ADC_BITS_OPTIONS.get(self.adc_bits, 4095)
        v_adc = (adc_value / max_adc) * self.VREF
        return v_adc * self.i_divider_ratio

    def adc_to_current(self, adc_value):
        """电流 ADC 原始值 → 瞬时电流 (A)。"""
        return (self.adc_to_vsensor(adc_value) - self.v_quiescent) / self.sensitivity

    # --------------------------------------------------------------
    # UI 构建
    # --------------------------------------------------------------
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
        layout.setContentsMargins(20, 12, 20, 16)
        layout.setSpacing(8)

        # 页面标题
        layout.addWidget(TitleLabel("欧姆定律"))

        # ========== 卡片1：连接控制 ==========
        card_conn = FluentCard("连接控制")
        self.mode_combo = ComboBox()
        self.mode_combo.addItems([
            "单板一体（一台 ESP32 同时测电压+电流）",
            "双板分测（电压板 + 电流板，双串口）",
            "模拟器",
        ])
        self.mode_combo.setCurrentIndex(self.MODE_VALUES.index(self.connect_mode))
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        card_conn.add_row("测量模式", self.mode_combo)

        self.volt_combo = ComboBox()
        self.volt_combo.addItems([
            "ESP32 内置 ADC", "ADS1115 (16位)", "HX711 (24位)",
        ])
        self.volt_combo.setCurrentIndex(self.VOLT_METHOD_VALUES.index(self.volt_method))
        self.volt_combo.currentIndexChanged.connect(self.on_volt_method_changed)
        card_conn.add_row("电压采样方式", self.volt_combo)

        # 串口（电压/一体）
        port_row = QHBoxLayout()
        port_row.setSpacing(8)
        self.port_combo = ComboBox()
        self.port_combo.setMinimumWidth(180)
        self.refresh_btn = PushButton("刷新")
        self.refresh_btn.setFixedHeight(30)
        self.refresh_btn.clicked.connect(self.refresh_ports)
        port_row.addWidget(self.port_combo, 1)
        port_row.addWidget(self.refresh_btn)
        port_widget = QWidget()
        port_widget.setLayout(port_row)
        card_conn.add_row("串口(电压/一体)", port_widget)
        card_conn.add_widget(CaptionLabel("单板：烧录 电学综合/VI_*.ino；双板：电压板接此口"))

        # 串口（电流，双板模式显示）
        self.port2_row_container = QWidget()
        r2 = QHBoxLayout(self.port2_row_container)
        r2.setContentsMargins(0, 0, 0, 0)
        r2.setSpacing(8)
        self.port2_combo = ComboBox()
        self.port2_combo.setMinimumWidth(180)
        r2.addWidget(self.port2_combo, 1)
        self.port2_row_container.setVisible(self.connect_mode == 'dual')
        card_conn.add_row("电流串口", self.port2_row_container)

        # 采样频率（内联下拉）
        self.sample_rate_combo = SampleRateComboBox()
        self.sample_rate_combo.setSampleInterval(self.sample_interval_ms)
        self.sample_rate_combo.sampleIntervalChanged.connect(self.on_sample_interval_changed)
        card_conn.add_row("采样频率", self.sample_rate_combo)

        # 连接按钮 + 状态
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.connect_btn = PrimaryPushButton("连接")
        self.connect_btn.setFixedHeight(34)
        self.connect_btn.clicked.connect(self.toggle_connection)
        btn_row.addWidget(self.connect_btn)
        self.status_label = BodyLabel("未连接")
        btn_row.addWidget(self.status_label)
        btn_row.addStretch(1)
        card_conn.add_layout(btn_row)
        layout.addWidget(card_conn)

        # ========== 卡片2：电压参数 ==========
        card_volt = FluentCard("电压参数")
        self.divider_spin = DoubleSpinBox()
        self.divider_spin.setRange(0.001, 10000.0)
        self.divider_spin.setDecimals(3)
        self.divider_spin.setValue(self.divider_ratio)
        self.divider_spin.valueChanged.connect(self.on_divider_changed)
        card_volt.add_row("分压比 (R1+R2)/R2", self.divider_spin)

        self.amp_spin = DoubleSpinBox()
        self.amp_spin.setRange(0.001, 1000.0)
        self.amp_spin.setDecimals(3)
        self.amp_spin.setValue(self.amp_ratio)
        self.amp_spin.valueChanged.connect(self.on_amp_changed)
        card_volt.add_row("放大倍数", self.amp_spin)

        self.pga_combo = ComboBox()
        self.pga_combo.addItems(list(self.ADS1115_PGA_RANGES.keys()))
        self.pga_combo.setCurrentText(self.ads1115_pga)
        self.pga_combo.currentIndexChanged.connect(self.on_pga_changed)
        card_volt.add_row("ADS1115 PGA 量程", self.pga_combo)

        self.hx711_avdd_spin = DoubleSpinBox()
        self.hx711_avdd_spin.setRange(0.1, 15.0)
        self.hx711_avdd_spin.setDecimals(2)
        self.hx711_avdd_spin.setValue(self.hx711_avdd)
        self.hx711_avdd_spin.valueChanged.connect(self.on_hx711_avdd_changed)
        card_volt.add_row("HX711 AVDD (V)", self.hx711_avdd_spin)

        self.hx711_ch_combo = ComboBox()
        self.hx711_ch_combo.addItems(["A (增益128)", "B (增益32)"])
        self.hx711_ch_combo.setCurrentIndex(0 if self.hx711_channel == 'A' else 1)
        self.hx711_ch_combo.currentIndexChanged.connect(self.on_hx711_channel_changed)
        card_volt.add_row("HX711 通道", self.hx711_ch_combo)
        layout.addWidget(card_volt)

        # ========== 卡片3：电流参数 ==========
        card_cur = FluentCard("电流参数（ACS712）")
        self.range_combo = ComboBox()
        self.range_combo.addItems(list(self.ACS712_RANGES.keys()))
        self.range_combo.setCurrentText(self.acs_range)
        self.range_combo.currentIndexChanged.connect(self.on_range_changed)
        card_cur.add_row("量程", self.range_combo)
        self.range_desc_label = CaptionLabel(
            self.ACS712_RANGES.get(self.acs_range, self.ACS712_RANGES['5A'])['desc'])
        card_cur.add_widget(self.range_desc_label)

        self.vcc_spin = DoubleSpinBox()
        self.vcc_spin.setRange(2.0, 10.0)
        self.vcc_spin.setDecimals(2)
        self.vcc_spin.setValue(self.vcc)
        self.vcc_spin.valueChanged.connect(self.on_vcc_changed)
        card_cur.add_row("供电电压 VCC (V)", self.vcc_spin)

        self.vq_spin = DoubleSpinBox()
        self.vq_spin.setRange(0.0, 5.0)
        self.vq_spin.setDecimals(4)
        self.vq_spin.setValue(self.v_quiescent)
        self.vq_spin.valueChanged.connect(self.on_vq_changed)
        card_cur.add_row("零电流输出电压 (V)", self.vq_spin)

        self.i_divider_spin = DoubleSpinBox()
        self.i_divider_spin.setRange(1.0, 10.0)
        self.i_divider_spin.setDecimals(4)
        self.i_divider_spin.setValue(self.i_divider_ratio)
        self.i_divider_spin.valueChanged.connect(self.on_i_divider_changed)
        card_cur.add_row("电流分压比", self.i_divider_spin)

        self.current_mode_combo = ComboBox()
        self.current_mode_combo.addItems(["DC 直流", "AC 交流（有效值）"])
        self.current_mode_combo.setCurrentIndex(
            0 if self.current_mode == 'DC' else 1)
        self.current_mode_combo.currentIndexChanged.connect(self.on_current_mode_changed)
        card_cur.add_row("测量模式", self.current_mode_combo)

        self.unit_combo = ComboBox()
        self.unit_combo.addItems(["A", "mA"])
        self.unit_combo.setCurrentText(self.current_unit)
        self.unit_combo.currentIndexChanged.connect(self.on_unit_changed)
        card_cur.add_row("电流单位", self.unit_combo)
        layout.addWidget(card_cur)

        # ========== 卡片4：实时数据 ==========
        card_data = FluentCard("实时数据")
        data_grid = QHBoxLayout()
        data_grid.setSpacing(16)
        self.voltage_value_label = BodyLabel("电压: ---")
        self.voltage_value_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.voltage_value_label.setStyleSheet("color: #0078d4;")
        self.current_value_label = BodyLabel("电流: ---")
        self.current_value_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.current_value_label.setStyleSheet("color: #0f8f8f;")
        self.resistance_value_label = BodyLabel("电阻: ---")
        self.resistance_value_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self.resistance_value_label.setStyleSheet("color: #d13438;")
        data_grid.addWidget(self.voltage_value_label)
        data_grid.addWidget(self.current_value_label)
        data_grid.addWidget(self.resistance_value_label)
        data_grid.addStretch(1)
        card_data.add_layout(data_grid)
        self.stats_label = CaptionLabel("统计: 数据点 0 | 电压 平均/最大/最小 | 电流 平均/最大/最小 | 电阻 平均/最大/最小")
        card_data.add_widget(self.stats_label)
        layout.addWidget(card_data)

        # ========== 卡片5：图表 + 数据记录（可折叠） ==========
        card_chart_content = QWidget()
        card_chart_content.setObjectName("card")
        card_chart_content.setStyleSheet(card_style())
        chart_card_layout = QVBoxLayout(card_chart_content)
        chart_card_layout.setContentsMargins(20, 4, 20, 16)
        chart_card_layout.setSpacing(12)

        content_row = QHBoxLayout()
        content_row.setSpacing(16)

        left_col = QVBoxLayout()
        left_col.setSpacing(10)
        self.data_text = ExpandableTextEdit()
        left_col.addWidget(self.data_text)

        # 双引擎图表面板（matplotlib / pyqtgraph，设置页可切换）
        self.chart = ChartPanel(n_plots=2)
        # 图表分析面板（仅 pyqtgraph 显示）：对 I-U 曲线做线性拟合 → 斜率倒数 = R
        left_col.addWidget(self.chart.get_analysis_panel())
        content_row.addLayout(left_col, stretch=0)

        content_row.addWidget(self.chart, stretch=2)
        chart_card_layout.addLayout(content_row, 1)
        card_chart = CollapsibleCard(
            "欧姆定律图表（I-U 曲线 + 电阻-时间曲线）", card_chart_content,
            expanded=True, fullscreen=True)
        card_chart.set_chart_min_height(420)
        # 全屏浮动：数据记录 + 拟合分析面板浮于图表上方，底部常驻开始/停止
        self.float_collect_btn = PrimaryPushButton("开始采集")
        self.float_collect_btn.setFixedHeight(34)
        update_collect_btn(self.float_collect_btn, False)
        self.float_collect_btn.clicked.connect(self.toggle_collection)
        self.float_collect_btn.setEnabled(False)
        card_chart.set_fullscreen_overlay(
            self.data_text, self.resistance_value_label,
            extra_widgets=[self.chart.get_analysis_panel()],
            footer_widget=self.float_collect_btn)
        layout.addWidget(card_chart)

        # ========== 卡片6：操作按钮 ==========
        card_actions = FluentCard("操作按钮")
        self.collect_btn = PrimaryPushButton("开始采集")
        self.collect_btn.setFixedHeight(38)
        update_collect_btn(self.collect_btn, False)
        self.collect_btn.clicked.connect(self.toggle_collection)
        self.collect_btn.setEnabled(False)
        act_row = QHBoxLayout()
        act_row.setSpacing(10)
        act_row.addWidget(self.collect_btn)

        self.zero_cal_btn = PushButton("零点校准")
        self.zero_cal_btn.setFixedHeight(38)
        set_action_button_width(self.zero_cal_btn)
        self.zero_cal_btn.clicked.connect(self.toggle_zero_cal)
        self.zero_cal_btn.setEnabled(False)
        self.zero_cal_btn.setStyleSheet(
            "background-color: #fd7e14; color: white;"
            if not self.zero_cal_active else
            "background-color: #28a745; color: white;")
        if self.zero_cal_active:
            self.zero_cal_btn.setText("取消零点")
        act_row.addWidget(self.zero_cal_btn)

        self.save_btn = PushButton("保存数据")
        self.save_btn.setFixedHeight(38)
        set_action_button_width(self.save_btn)
        self.save_btn.clicked.connect(self.save_data)
        self.save_btn.setEnabled(False)
        act_row.addWidget(self.save_btn)

        self.clear_btn = PushButton("清除数据")
        self.clear_btn.setFixedHeight(38)
        set_action_button_width(self.clear_btn)
        self.clear_btn.clicked.connect(self.clear_data)
        act_row.addWidget(self.clear_btn)
        act_row.addStretch(1)
        card_actions.add_layout(act_row)
        layout.addWidget(card_actions)

        layout.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        # 按当前配置同步控件可用状态
        self._sync_volt_method_controls()
        self.refresh_ports()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_chart)
        self.timer.start(100)

    # --------------------------------------------------------------
    # 参数变更槽函数
    # --------------------------------------------------------------
    def on_mode_changed(self, index):
        mode = self.MODE_VALUES[index] if 0 <= index < len(self.MODE_VALUES) else 'single'
        self.connect_mode = mode
        # 双板分测才需要第二个串口
        self.port2_row_container.setVisible(mode == 'dual')
        self.save_config()
        if self._connected:
            self.disconnect_all()

    def on_volt_method_changed(self, index):
        self.volt_method = self.VOLT_METHOD_VALUES[index] if 0 <= index < len(self.VOLT_METHOD_VALUES) else 'esp32'
        self._sync_volt_method_controls()
        self.save_config()

    def _sync_volt_method_controls(self):
        """按电压采样方式启用对应的参数控件。"""
        esp = self.volt_method == 'esp32'
        ads = self.volt_method == 'ads1115'
        hx = self.volt_method == 'hx711'
        self.divider_spin.setEnabled(True)
        self.amp_spin.setEnabled(True)
        self.pga_combo.setEnabled(ads)
        self.hx711_avdd_spin.setEnabled(hx)
        self.hx711_ch_combo.setEnabled(hx)

    def on_divider_changed(self, value):
        self.divider_ratio = value
        self.save_config()

    def on_amp_changed(self, value):
        self.amp_ratio = value
        self.save_config()

    def on_pga_changed(self, index):
        self.ads1115_pga = self.pga_combo.currentText()
        self.save_config()

    def on_hx711_avdd_changed(self, value):
        self.hx711_avdd = value
        self.save_config()

    def on_hx711_channel_changed(self, index):
        self.hx711_channel = 'A' if index == 0 else 'B'
        self.save_config()

    def on_range_changed(self, index):
        self.acs_range = self.range_combo.currentText()
        self.range_desc_label.setText(
            self.ACS712_RANGES.get(self.acs_range, self.ACS712_RANGES['5A'])['desc'])
        self.save_config()

    def on_vcc_changed(self, value):
        self.vcc = value
        # 未校准时零点电压跟随 VCC/2
        if not self.zero_cal_active:
            self.v_quiescent = value / 2.0
            self.vq_spin.blockSignals(True)
            self.vq_spin.setValue(self.v_quiescent)
            self.vq_spin.blockSignals(False)
        self.save_config()

    def on_vq_changed(self, value):
        self.v_quiescent = value
        self.save_config()

    def on_i_divider_changed(self, value):
        self.i_divider_ratio = value
        self.save_config()

    def on_current_mode_changed(self, index):
        self.current_mode = 'DC' if index == 0 else 'AC'
        self.save_config()

    def on_unit_changed(self, index):
        self.current_unit = self.unit_combo.currentText()
        self.save_config()

    def on_sample_interval_changed(self, interval_ms):
        self.sample_interval_ms = interval_ms
        self.save_config()

    def refresh_ports(self):
        ports = list_serial_ports()
        for combo in (self.port_combo, self.port2_combo):
            combo.blockSignals(True)
            combo.clear()
            if ports:
                for device, desc in ports:
                    combo.addItem(f"{device} {desc}" if desc else device, userData=device)
                combo.setCurrentIndex(0)
            else:
                if SERIAL_AVAILABLE:
                    combo.addItem("未检测到串口设备", userData="")
                else:
                    combo.addItem("未安装 pyserial", userData="")
            combo.blockSignals(False)

    # --------------------------------------------------------------
    # 连接
    # --------------------------------------------------------------
    def on_serial_unavailable(self):
        fluent_message_box(self, "串口不可用", serial_unavailable_hint())

    def toggle_connection(self):
        if self._connected:
            self.disconnect_all()
        else:
            self.connect_device()

    def connect_device(self):
        if self.connect_mode == 'simulator':
            self._connect_simulator()
            return
        if not SERIAL_AVAILABLE:
            self.on_serial_unavailable()
            return
        port = self.port_combo.currentData() or ""
        if not port:
            fluent_message_box(self, "连接失败", "请先选择串口")
            return
        self._connected = True
        self.status_label.setText("连接中...")
        self.connect_btn.setEnabled(False)
        if self.connect_mode == 'single':
            self.serial_vi = SerialThread(port)
            self.serial_vi.data_received.connect(self.handle_vi_line)
            self.serial_vi.start()
        else:
            port2 = self.port2_combo.currentData() or ""
            if not port2:
                self._connected = False
                self.connect_btn.setEnabled(True)
                fluent_message_box(self, "连接失败", "双板分测需要选择电流串口")
                return
            self.serial_v = SerialThread(port)
            self.serial_v.data_received.connect(self.handle_v_line)
            self.serial_v.start()
            self.serial_i = SerialThread(port2)
            self.serial_i.data_received.connect(self.handle_i_line)
            self.serial_i.start()

    def _connect_simulator(self):
        self._connected = True
        self.status_label.setText("已连接（模拟器）")
        self.connect_btn.setEnabled(True)
        self.connect_btn.setText("断开")
        self._enable_controls(True)
        # 电压模拟：ADC 0~4095 围绕 ~2500 漂移（约 2V）
        self.sim_v = SimulatorThread(0, 4095, 100, start_value=2500)
        # 电流模拟：ADC 围绕中点 2048 附近 ±200（≈零点附近的小电流）
        self.sim_i = SimulatorThread(1800, 2300, 100, start_value=2048)
        self.sim_v.data_received.connect(self.handle_v_line)
        self.sim_i.data_received.connect(self.handle_i_line)
        self.sim_v.start()
        self.sim_i.start()

    def disconnect_all(self):
        self._connected = False
        self._collecting = False
        self.connect_btn.setText("连接")
        self.connect_btn.setEnabled(True)
        self.status_label.setText("未连接")
        self._enable_controls(False)
        threads = (self.serial_vi, self.serial_v, self.serial_i,
                   self.sim_v, self.sim_i)
        for t in threads:
            if t is not None:
                try:
                    t.stop()
                except Exception:
                    pass
        # 等线程真正退出再释放引用：QThread 仍在运行时被销毁会触发
        # Qt fail-fast 崩溃（0xC0000409）。个别线程退出慢（如串口打开中）
        # 超时后把引用收进 _retired_threads 保留，等其自然退出后再释放，
        # 杜绝「切模式闪退」。
        for t in threads:
            if t is None:
                continue
            try:
                if not t.wait(2000):
                    self._retired_threads.append(t)
            except Exception:
                self._retired_threads.append(t)
        # 清理已退出线程的残留引用（线程对象本身在 finished 后由 Qt 释放）
        self._retired_threads = [t for t in self._retired_threads
                                 if t.isRunning()]
        self.serial_vi = self.serial_v = self.serial_i = None
        self.sim_v = self.sim_i = None

    def closeEvent(self, event):
        """关闭页面时确保通信线程全部停止（防止退出时 QThread 崩溃）。"""
        self.disconnect_all()
        super().closeEvent(event)

    def _enable_controls(self, enabled):
        self.collect_btn.setEnabled(enabled)
        self.float_collect_btn.setEnabled(enabled)
        self.save_btn.setEnabled(enabled)
        self.zero_cal_btn.setEnabled(enabled)

    # --------------------------------------------------------------
    # 数据解析（单板三字段 / 双板与模拟器两字段 + 配对）
    # --------------------------------------------------------------
    @staticmethod
    def _parse(line):
        parts = line.strip().split(',')
        try:
            t = int(float(parts[0]))
            vals = [int(float(v)) for v in parts[1:]]
            return t, vals
        except (ValueError, IndexError):
            return None

    def handle_vi_line(self, data):
        """单板一体：一行 时间戳,电压ADC,电流ADC。"""
        if data == "START":
            self._on_started()
            return
        if data.startswith("ERROR"):
            self._on_error(data)
            return
        parsed = self._parse(data)
        if parsed is None:
            return
        t, vals = parsed
        if len(vals) != 2:
            return
        self._consume_pair(t, vals[0], vals[1])

    def handle_v_line(self, data):
        """电压通道数据（双板电压板 / 模拟器）。"""
        if data == "START":
            self._on_started()
            return
        if data.startswith("ERROR"):
            self._on_error(data)
            return
        parsed = self._parse(data)
        if parsed is None:
            return
        t, vals = parsed
        if len(vals) != 1:
            return
        # 电压到达时用最近一次电流配对
        if self._pending_i is not None:
            ti, adc_i = self._pending_i
            self._pending_i = None
            self._consume_pair(t, vals[0], adc_i)
        else:
            self._pending_v = (t, vals[0])

    def handle_i_line(self, data):
        """电流通道数据（双板电流板 / 模拟器）。"""
        if data.startswith("ERROR"):
            self._on_error(data)
            return
        parsed = self._parse(data)
        if parsed is None:
            return
        t, vals = parsed
        if len(vals) != 1:
            return
        self._pending_i = (t, vals[0])
        if self._pending_v is not None:
            tv, adc_v = self._pending_v
            self._pending_v = None
            self._consume_pair(tv, adc_v, vals[0])

    def _on_started(self):
        if self.connect_mode != 'simulator':
            self._connected = True
            self.status_label.setText("已连接")
        self.connect_btn.setText("断开")
        self.connect_btn.setEnabled(True)
        self._enable_controls(True)

    def _on_error(self, data):
        self._connected = False
        self.status_label.setText("连接失败")
        self.connect_btn.setText("连接")
        self.connect_btn.setEnabled(True)
        self._enable_controls(False)
        msg = data[len("ERROR:"):] if data.startswith("ERROR:") else data
        fluent_message_box(self, "连接错误", msg)

    # --------------------------------------------------------------
    # 采样控制
    # --------------------------------------------------------------
    def toggle_collection(self):
        if self._collecting:
            self.stop_collection()
        else:
            self.start_collection()

    def _set_collect_enabled(self, enabled):
        self.collect_btn.setEnabled(enabled)
        self.float_collect_btn.setEnabled(enabled)

    def _refresh_collect_btn(self):
        update_collect_btn(self.collect_btn, self._collecting)
        update_collect_btn(self.float_collect_btn, self._collecting)

    def start_collection(self):
        if not self._connected:
            return
        self.time_data.clear()
        self.v_data.clear()
        self.i_data.clear()
        self.r_data.clear()
        self.raw_v.clear()
        self.raw_i.clear()
        self._collecting = True
        self._pending_v = None
        self._pending_i = None
        self.start_timestamp_ms = 0
        self.last_sample_time_ms = 0
        self._refresh_collect_btn()

    def stop_collection(self):
        self._collecting = False
        self._refresh_collect_btn()

    # --------------------------------------------------------------
    # 数据处理
    # --------------------------------------------------------------
    def _consume_pair(self, t_ms, adc_v, adc_i):
        # 采样频率控制：按电压时间戳
        if t_ms - self.last_sample_time_ms < self.sample_interval_ms:
            return
        self.last_sample_time_ms = t_ms

        if self.start_timestamp_ms == 0:
            self.start_timestamp_ms = t_ms
        relative_s = (t_ms - self.start_timestamp_ms) / 1000.0

        v = self.adc_to_voltage(adc_v)
        v_sensor = self.adc_to_vsensor(adc_i)
        i_inst = (v_sensor - self.v_quiescent) / self.sensitivity

        if self.current_mode == 'AC':
            # 有效值：滚动窗口 RMS
            self._i_win = getattr(self, '_i_win', deque(maxlen=self.ac_rms_window))
            self._i_win.append(i_inst)
            if len(self._i_win) >= 2:
                arr = np.array(self._i_win)
                i = float(np.sqrt(np.mean(arr ** 2)))
            else:
                i = 0.0
        else:
            i = i_inst

        # 零点校准缓存（取最近 ACS712 输出电压）
        self._recent_vs.append(v_sensor)

        t = relative_s
        if self._collecting:
            self.time_data.append(t)
            self.v_data.append(v)
            self.i_data.append(i)
            self.raw_v.append(adc_v)
            self.raw_i.append(adc_i)
            r = None if abs(i) < self.I_EPS else v / i
            self.r_data.append(r)

            time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            unit = self.current_unit
            if r is not None:
                r_text = f"{r:.4f}" if abs(r) >= 1 else f"{r:.6f}"
                self.resistance_value_label.setText(f"电阻: {r_text} Ω")
                r_line = f"{r_text} Ω"
            else:
                self.resistance_value_label.setText("电阻: ---")
                r_line = "---"
            self.voltage_value_label.setText(f"电压: {v:.4f} V")
            self.current_value_label.setText(f"电流: {self.format_current(i)} {unit}")
            self.data_text.append(
                f"时间: {time_str} | U: {v:.4f} V | I: {self.format_current(i)} A | R: {r_line}")
            self.data_text.verticalScrollBar().setValue(
                self.data_text.verticalScrollBar().maximum())
            self.update_stats()

    def update_stats(self):
        if not self.time_data:
            return
        n = len(self.time_data)
        v_arr = np.array(self.v_data)
        i_arr = np.array(self.i_data)
        r_vals = [r for r in self.r_data if r is not None]
        unit = self.current_unit
        parts = [f"数据点 {n}",
                 f"电压 平均={v_arr.mean():.4f}V 最大={v_arr.max():.4f}V 最小={v_arr.min():.4f}V",
                 f"电流 平均={self.format_current(float(i_arr.mean()))}{unit} "
                 f"最大={self.format_current(float(i_arr.max()))}{unit}",
                 ]
        if r_vals:
            r_arr = np.array(r_vals)
            parts.append(f"电阻 平均={r_arr.mean():.4f}Ω 最大={r_arr.max():.4f}Ω 最小={r_arr.min():.4f}Ω")
        else:
            parts.append("电阻 无有效数据（电流过小）")
        self.stats_label.setText("统计: " + " | ".join(parts))

    # --------------------------------------------------------------
    # 零点校准
    # --------------------------------------------------------------
    def toggle_zero_cal(self):
        if not self._collecting:
            return
        if not self.zero_cal_active:
            vals = list(self._recent_vs)
            if len(vals) < 3:
                fluent_message_box(self, "零点校准", "数据不足，请先采集几秒数据")
                return
            self.v_quiescent = sum(vals) / len(vals)
            self.zero_cal_active = True
            self.zero_cal_btn.setText("取消零点")
            self.zero_cal_btn.setStyleSheet("background-color: #28a745; color: white;")
        else:
            self.v_quiescent = self.vcc / 2.0
            self.zero_cal_active = False
            self.zero_cal_btn.setText("零点校准")
            self.zero_cal_btn.setStyleSheet("background-color: #fd7e14; color: white;")
        self.vq_spin.blockSignals(True)
        self.vq_spin.setValue(self.v_quiescent)
        self.vq_spin.blockSignals(False)
        self.save_config()

    # --------------------------------------------------------------
    # 图表
    # --------------------------------------------------------------
    def update_chart(self):
        c = self.chart
        c.begin()
        # 子图1：I-U 曲线（电压横轴、电流纵轴，线性拟合斜率倒数 = R）
        c.plot(self.v_data, self.i_data, color='#0078d4', width=2,
               label='电流-电压', index=0)
        c.set_labels('电压 (V)', '电流 (A)', index=0)
        c.set_title('I-U 曲线（可在线性拟合并读取 R²，斜率倒数即电阻）', index=0)
        c.legend(index=0)
        # 子图2：R-t（无效点跳过）
        rt, vt = [], []
        for t, r in zip(self.time_data, self.r_data):
            if r is not None:
                vt.append(t)
                rt.append(r)
        c.plot(vt, rt, color='#d13438', width=2, label='电阻', index=1)
        c.set_labels('时间 (s)', '电阻 (Ω)', index=1)
        c.set_title('电阻-时间曲线', index=1)
        c.legend(index=1)
        c.end()

    # --------------------------------------------------------------
    # 保存 / 清除
    # --------------------------------------------------------------
    def save_data(self):
        if not self.time_data:
            fluent_message_box(self, "保存数据", "暂无数据")
            return
        default = f"ohm_sensor_data_{datetime.now():%Y%m%d_%H%M%S}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "保存数据", default, "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8-sig') as f:
                f.write("时间(s),电压(V),电流(A),电阻(Ω)\n")
                for t, v, i, r in zip(self.time_data, self.v_data,
                                      self.i_data, self.r_data):
                    r_text = '-' if r is None else f"{r:.6f}"
                    f.write(f"{t:.3f},{v:.6f},{i:.6f},{r_text}\n")
            fluent_message_box(self, "保存成功",
                               f"已保存 {len(self.time_data)} 条数据到\n{path}")
        except Exception as e:
            fluent_message_box(self, "保存失败", str(e))

    def clear_data(self):
        self.time_data.clear()
        self.v_data.clear()
        self.i_data.clear()
        self.r_data.clear()
        self.raw_v.clear()
        self.raw_i.clear()
        self.start_timestamp_ms = 0
        self.last_sample_time_ms = 0
        self._pending_v = None
        self._pending_i = None
        self.voltage_value_label.setText("电压: ---")
        self.current_value_label.setText("电流: ---")
        self.resistance_value_label.setText("电阻: ---")
        self.stats_label.setText("统计: 数据点 0")
        self.data_text.clear()
        self.chart.clear_chart()

    # --------------------------------------------------------------
    # 主题
    # --------------------------------------------------------------
    def apply_theme(self, theme):
        apply_module_theme(self, theme)
        self.chart.apply_chart_theme(isDarkTheme())
        update_collect_btn(self.collect_btn, self._collecting)
        update_collect_btn(self.float_collect_btn, self._collecting)