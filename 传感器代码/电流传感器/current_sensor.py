# === MODULE META ===
# icon: A
# name: 电流传感器
# category: physics
# class: CurrentSensorWidget
# ===================

# -*- coding: utf-8 -*-
"""电流传感器模块 — ACS712 霍尔电流传感器，支持 5A/20A/30A 量程切换、AC/DC 测量与零点校准"""

import sys
import os
import threading
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QComboBox, QTextEdit, QGroupBox, QSpinBox, QDoubleSpinBox,
    QCheckBox, QInputDialog, QStyle, QScrollArea, QMessageBox,
)
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter
import serial
import serial.tools.list_ports
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np

# 从公共模块导入共享代码
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core import (
    SerialThread, BLESerialThread, scan_ble_devices,
    SampleRateDialog,
    load_sensor_config, save_sensor_config,
    card_style, primary_btn_style, accent_btn_style, modern_combo_style,
    BLE_AVAILABLE,
)


class CurrentSensorWidget(QWidget):
    """电流传感器模块界面 - ACS712 霍尔电流传感器

    ACS712 工作原理：
      - 供电 VCC（典型 5V），零电流时输出 = VCC/2（约 2.5V）
      - 输出电压随电流线性变化：Vout = VCC/2 + I * 灵敏度
      - 三种量程灵敏度：5A→185mV/A，20A→100mV/A，30A→66mV/A
      - 可测交直流；交流时取 RMS

    由于 ACS712 输出最高约 4.5V，超出 ESP32 ADC 的 3.3V 量程，
    通常在 ACS712 输出与 ESP32 ADC 之间加分压电路（分压比≈5/3.3≈1.515）。
    """

    # ADC 位数 → 满量程计数值
    ADC_BITS_OPTIONS = {8: 256, 10: 1024, 12: 4096, 14: 16384, 16: 65536}
    VREF = 3.3  # ESP32 ADC 参考电压

    # ACS712 量程参数：灵敏度（V/A）、标称量程（A）、说明
    ACS712_RANGES = {
        '5A':  {'sensitivity': 0.185, 'range_a': 5,  'desc': 'ACS712ELC-05B  ±5A  185mV/A'},
        '20A': {'sensitivity': 0.100, 'range_a': 20, 'desc': 'ACS712ELC-20A  ±20A  100mV/A'},
        '30A': {'sensitivity': 0.066, 'range_a': 30, 'desc': 'ACS712ELC-30A  ±30A  66mV/A'},
    }

    # 内部 current_data 始终存安培，显示时按当前单位换算
    UNIT_FACTORS = {'A': 1.0, 'mA': 1000.0}

    def __init__(self):
        super().__init__()
        self.serial_thread = None
        self.ble_thread = None
        self.current_data = []   # 电流值（安培，瞬时值）
        self.vsensor_data = []   # ACS712 输出电压（V，还原后），用于零点校准
        self.time_data = []
        self.raw_data = []
        self.start_timestamp_ms = 0

        # 采样频率设置（毫秒）
        self.sample_interval_ms = 100  # 默认 100ms (10Hz)
        self.last_sample_time_ms = 0

        # ACS712 参数
        self.acs_range = '5A'
        self.vcc = 5.0              # ACS712 供电电压
        self.v_quiescent = 2.5      # 零电流输出电压（= VCC/2，可校准）
        self.divider_ratio = 1.515  # 分压比 (R1+R2)/R2，还原 ACS712 原始输出
        self.adc_bits = 12
        self.current_mode = 'DC'    # DC / AC
        self.current_unit = 'A'     # A / mA
        self.zero_cal_active = False  # 是否已执行零点校准

        # AC 模式 RMS 滚动窗口大小（采样点数）
        self.ac_rms_window = 50

        self.config = self.load_config()
        self.init_ui()

    # ------------------------------------------------------------------
    # 配置读写
    # ------------------------------------------------------------------
    def load_config(self):
        config = load_sensor_config('current_sensor')
        if config:
            self.acs_range = config.get('acs_range', '5A')
            self.vcc = config.get('vcc', 5.0)
            self.v_quiescent = config.get('v_quiescent', self.vcc / 2.0)
            self.divider_ratio = config.get('divider_ratio', 1.515)
            self.adc_bits = config.get('adc_bits', 12)
            self.current_mode = config.get('current_mode', 'DC')
            self.current_unit = config.get('current_unit', 'A')
            self.zero_cal_active = config.get('zero_cal_active', False)
            self.sample_interval_ms = config.get('sample_interval_ms', 100)
            self.ac_rms_window = config.get('ac_rms_window', 50)
        return config

    def save_config(self):
        config = {
            'acs_range': self.acs_range,
            'vcc': self.vcc,
            'v_quiescent': self.v_quiescent,
            'divider_ratio': self.divider_ratio,
            'adc_bits': self.adc_bits,
            'current_mode': self.current_mode,
            'current_unit': self.current_unit,
            'zero_cal_active': self.zero_cal_active,
            'sample_interval_ms': self.sample_interval_ms,
            'ac_rms_window': self.ac_rms_window,
        }
        return save_sensor_config('current_sensor', config)

    # ------------------------------------------------------------------
    # 单位与换算
    # ------------------------------------------------------------------
    def to_current_unit(self, current_a):
        """安培 → 当前单位"""
        return current_a * self.UNIT_FACTORS.get(self.current_unit, 1.0)

    def format_current(self, current_a):
        """格式化显示：根据数量级自动选小数位"""
        c = self.to_current_unit(current_a)
        if self.current_unit == 'mA':
            return f"{c:.2f}"
        # 安培：按数量级
        abs_c = abs(c)
        if abs_c >= 1.0:
            return f"{c:.4f}"
        return f"{c:.6f}"

    @property
    def sensitivity(self):
        return self.ACS712_RANGES.get(self.acs_range, self.ACS712_RANGES['5A'])['sensitivity']

    def adc_to_vadc(self, adc_value):
        """ADC 输入端电压（ESP32 ADC 引脚处）"""
        max_adc = self.ADC_BITS_OPTIONS.get(self.adc_bits, 4096) - 1
        return (adc_value / max_adc) * self.VREF

    def adc_to_vsensor(self, adc_value):
        """还原 ACS712 输出电压（扣除分压电路影响）"""
        return self.adc_to_vadc(adc_value) * self.divider_ratio

    def adc_to_current(self, adc_value):
        """ADC 原始值 → 电流（安培，瞬时值）"""
        v_sensor = self.adc_to_vsensor(adc_value)
        return (v_sensor - self.v_quiescent) / self.sensitivity

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
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

        title = QLabel("电流")
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

        row1 = QHBoxLayout()
        row1.setSpacing(10)

        row1.addWidget(QLabel("连接方式:"))
        self.mode_combo = QComboBox()
        self.mode_combo.setStyleSheet(modern_combo_style())
        self.mode_combo.addItems(["有线串口", "BLE蓝牙"])
        if not BLE_AVAILABLE:
            self.mode_combo.setItemData(1, 0, Qt.ItemDataRole.UserRole - 1)
            self.mode_combo.setItemText(1, "BLE蓝牙（未安装bleak）")
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        row1.addWidget(self.mode_combo)

        self.serial_panel = QWidget()
        serial_layout = QHBoxLayout(self.serial_panel)
        serial_layout.setContentsMargins(0, 0, 0, 0)
        serial_layout.setSpacing(8)
        serial_layout.addWidget(QLabel("串口:"))
        self.port_combo = QComboBox()
        self.port_combo.setStyleSheet(modern_combo_style())
        self.refresh_ports()
        self.port_combo.setMinimumWidth(140)
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
        self.ble_device_combo = QComboBox()
        self.ble_device_combo.setStyleSheet(modern_combo_style())
        self.ble_device_combo.setMinimumWidth(180)
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

        # ========== 卡片2：ACS712 参数 ==========
        card_acs = QWidget()
        card_acs.setObjectName("card")
        card_acs.setStyleSheet(card_style())
        acs_card_layout = QVBoxLayout(card_acs)
        acs_card_layout.setContentsMargins(20, 16, 20, 16)
        acs_card_layout.setSpacing(12)

        acs_card_title = QLabel("ACS712 参数")
        acs_card_title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        acs_card_title.setStyleSheet("color: #1a1a1a;")
        acs_card_layout.addWidget(acs_card_title)

        # 量程选择 + 测量类型 + ADC 位数
        range_row = QHBoxLayout()
        range_row.setSpacing(10)
        range_row.addWidget(QLabel("量程:"))
        self.range_combo = QComboBox()
        self.range_combo.setStyleSheet(modern_combo_style())
        for key in ['5A', '20A', '30A']:
            self.range_combo.addItem(self.ACS712_RANGES[key]['desc'])
        range_idx = {'5A': 0, '20A': 1, '30A': 2}.get(self.acs_range, 0)
        self.range_combo.setCurrentIndex(range_idx)
        self.range_combo.currentIndexChanged.connect(self.on_range_changed)
        range_row.addWidget(self.range_combo)

        range_row.addWidget(QLabel("测量类型:"))
        self.mode_type_combo = QComboBox()
        self.mode_type_combo.setStyleSheet(modern_combo_style())
        self.mode_type_combo.addItems(["直流 DC", "交流 AC"])
        self.mode_type_combo.setCurrentIndex(0 if self.current_mode == 'DC' else 1)
        self.mode_type_combo.currentIndexChanged.connect(self.on_current_mode_changed)
        range_row.addWidget(self.mode_type_combo)

        range_row.addWidget(QLabel("ADC 位数:"))
        self.adc_bits_combo = QComboBox()
        self.adc_bits_combo.setStyleSheet(modern_combo_style())
        self.adc_bits_combo.addItems([
            "8 位 (0-255)",
            "10 位 (0-1023)",
            "12 位 (0-4095)  ESP32内置",
            "14 位 (0-16383)",
            "16 位 (0-65535)",
        ])
        bits_map = {0: 8, 1: 10, 2: 12, 3: 14, 4: 16}
        self.adc_bits_combo.setCurrentIndex({v: k for k, v in bits_map.items()}.get(self.adc_bits, 2))
        self.adc_bits_combo.currentIndexChanged.connect(self.on_adc_bits_changed)
        range_row.addWidget(self.adc_bits_combo)
        range_row.addStretch()
        acs_card_layout.addLayout(range_row)

        # 量程显示
        self.range_label = QLabel()
        self.range_label.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        self.range_label.setStyleSheet("color: #0078d4;")
        acs_card_layout.addWidget(self.range_label)

        # 供电电压 + 零点电压 + 分压比
        params_row = QHBoxLayout()
        params_row.setSpacing(10)

        params_row.addWidget(QLabel("供电 VCC:"))
        self.vcc_spin = QDoubleSpinBox()
        self.vcc_spin.setRange(4.5, 5.5)
        self.vcc_spin.setDecimals(2)
        self.vcc_spin.setSingleStep(0.1)
        self.vcc_spin.setValue(self.vcc)
        self.vcc_spin.setSuffix(" V")
        self.vcc_spin.setMinimumWidth(90)
        self.vcc_spin.valueChanged.connect(self.on_vcc_changed)
        params_row.addWidget(self.vcc_spin)

        params_row.addWidget(QLabel("零点电压:"))
        self.vquies_spin = QDoubleSpinBox()
        self.vquies_spin.setRange(0.0, 5.5)
        self.vquies_spin.setDecimals(3)
        self.vquies_spin.setSingleStep(0.01)
        self.vquies_spin.setValue(self.v_quiescent)
        self.vquies_spin.setSuffix(" V")
        self.vquies_spin.setToolTip("零电流时 ACS712 输出电压，理论值 = VCC/2\n"
                                    "实际传感器有偏差，建议用“零点校准”按钮自动获取")
        self.vquies_spin.setMinimumWidth(100)
        self.vquies_spin.valueChanged.connect(self.on_vquiescent_changed)
        params_row.addWidget(self.vquies_spin)

        params_row.addWidget(QLabel("分压比 (R1+R2)/R2:"))
        self.divider_spin = QDoubleSpinBox()
        self.divider_spin.setRange(1.0, 10.0)
        self.divider_spin.setDecimals(3)
        self.divider_spin.setSingleStep(0.01)
        self.divider_spin.setValue(self.divider_ratio)
        self.divider_spin.setSuffix(" x")
        self.divider_spin.setMinimumWidth(110)
        self.divider_spin.valueChanged.connect(self.on_divider_changed)
        params_row.addWidget(self.divider_spin)
        params_row.addStretch()
        acs_card_layout.addLayout(params_row)

        # 可测范围显示
        self.actual_range_label = QLabel()
        self.actual_range_label.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        self.actual_range_label.setStyleSheet("color: #28a745;")
        acs_card_layout.addWidget(self.actual_range_label)

        hint_label = QLabel(
            "ACS712 输出最高约 4.5V，超出 ESP32 ADC 的 3.3V 量程，需在输出与 ADC 之间加分压电路\n"
            "分压比 ≈ 5/3.3 ≈ 1.515（将 5V 映射到 3.3V）；电流 = (Vout − 零点电压) / 灵敏度"
        )
        hint_label.setStyleSheet("color: #888888; font-size: 11px;")
        hint_label.setWordWrap(True)
        acs_card_layout.addWidget(hint_label)

        # 显示单位 + 零点校准状态
        unit_row = QHBoxLayout()
        unit_row.setSpacing(10)
        unit_row.addWidget(QLabel("显示单位:"))
        self.unit_combo = QComboBox()
        self.unit_combo.setStyleSheet(modern_combo_style())
        self.unit_combo.addItems(["安培 (A)", "毫安 (mA)"])
        self.unit_combo.setCurrentIndex(0 if self.current_unit == 'A' else 1)
        self.unit_combo.currentIndexChanged.connect(self.on_unit_changed)
        unit_row.addWidget(self.unit_combo)

        unit_row.addWidget(QLabel("零点校准:"))
        self.zero_status_label = QLabel("未校准（零点=VCC/2）" if not self.zero_cal_active
                                        else f"已校准 (零点 {self.v_quiescent:.3f}V)")
        self.zero_status_label.setStyleSheet("color: #888; font-weight: bold;" if not self.zero_cal_active
                                             else "color: green; font-weight: bold;")
        unit_row.addWidget(self.zero_status_label)
        unit_row.addStretch()
        acs_card_layout.addLayout(unit_row)

        # AC 模式 RMS 窗口设置（仅 AC 模式可用）
        ac_row = QHBoxLayout()
        ac_row.setSpacing(10)
        ac_row.addWidget(QLabel("AC RMS 窗口:"))
        self.ac_window_spin = QSpinBox()
        self.ac_window_spin.setRange(5, 500)
        self.ac_window_spin.setValue(self.ac_rms_window)
        self.ac_window_spin.setSuffix(" 点")
        self.ac_window_spin.setToolTip("AC 模式下计算 RMS 的滚动窗口大小（采样点数）")
        self.ac_window_spin.valueChanged.connect(self.on_ac_window_changed)
        self.ac_window_spin.setEnabled(self.current_mode == 'AC')
        ac_row.addWidget(self.ac_window_spin)
        ac_row.addStretch()
        acs_card_layout.addLayout(ac_row)

        layout.addWidget(card_acs)

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

        self.current_value_label = QLabel("--.- A")
        self.current_value_label.setFont(QFont("Microsoft YaHei", 32, QFont.Weight.Bold))
        self.current_value_label.setStyleSheet("color: #0078d4;")
        data_card_layout.addWidget(self.current_value_label)

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

        self.current_vsensor_label = QLabel("传感器输出: --.- V")
        self.current_vsensor_label.setFont(QFont("Microsoft YaHei", 11))
        self.current_vsensor_label.setStyleSheet("color: #444444;")
        raw_row.addWidget(self.current_vsensor_label)
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

        chart_title = QLabel("电流-时间曲线")
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

        # 零点校准按钮：取最近若干个数据点平均的传感器输出作为零点电压
        self.zero_cal_btn = QPushButton("零点校准" if not self.zero_cal_active else "取消零点")
        self.zero_cal_btn.setFixedHeight(38)
        self.zero_cal_btn.clicked.connect(self.toggle_zero_cal)
        self.zero_cal_btn.setEnabled(False)
        self.zero_cal_btn.setStyleSheet(accent_btn_style("#fd7e14", "#e06b00", "#c75a00")
                                        if not self.zero_cal_active else
                                        accent_btn_style("#28a745", "#218838", "#1e7e34"))
        actions_layout.addWidget(self.zero_cal_btn)

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

        self.update_range_display()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_chart)
        self.timer.start(100)

    # ------------------------------------------------------------------
    # 参数变更槽函数
    # ------------------------------------------------------------------
    def on_mode_changed(self, index):
        if index == 0:
            self.serial_panel.show()
            self.ble_panel.hide()
        else:
            self.serial_panel.hide()
            self.ble_panel.show()

    def on_range_changed(self, index):
        key_map = {0: '5A', 1: '20A', 2: '30A'}
        self.acs_range = key_map.get(index, '5A')
        self.save_config()
        self.update_range_display()

    def on_current_mode_changed(self, index):
        self.current_mode = 'DC' if index == 0 else 'AC'
        self.ac_window_spin.setEnabled(self.current_mode == 'AC')
        self.save_config()
        self.update_stats()
        self.update_chart()
        self.update_current_display()

    def on_adc_bits_changed(self, index):
        bits_map = {0: 8, 1: 10, 2: 12, 3: 14, 4: 16}
        self.adc_bits = bits_map.get(index, 12)
        self.save_config()
        self.update_range_display()

    def on_vcc_changed(self, value):
        self.vcc = value
        # VCC 改变时，若未做零点校准则零点电压跟随 VCC/2
        if not self.zero_cal_active:
            self.v_quiescent = self.vcc / 2.0
            self.vquies_spin.blockSignals(True)
            self.vquies_spin.setValue(self.v_quiescent)
            self.vquies_spin.blockSignals(False)
            self.update_zero_status_label()
        self.save_config()
        self.update_range_display()

    def on_vquiescent_changed(self, value):
        self.v_quiescent = value
        # 手动改零点电压视为已校准
        self.zero_cal_active = True
        self.update_zero_status_label()
        self.update_zero_cal_btn()
        self.save_config()

    def on_divider_changed(self, value):
        self.divider_ratio = value
        self.save_config()
        self.update_range_display()

    def on_unit_changed(self, index):
        self.current_unit = 'A' if index == 0 else 'mA'
        self.save_config()
        self.update_stats()
        self.update_chart()
        self.update_current_display()

    def on_ac_window_changed(self, value):
        self.ac_rms_window = value
        self.save_config()
        self.update_stats()
        self.update_current_display()

    # ------------------------------------------------------------------
    # 零点校准
    # ------------------------------------------------------------------
    def update_zero_status_label(self):
        if self.zero_cal_active:
            self.zero_status_label.setText(f"已校准 (零点 {self.v_quiescent:.3f}V)")
            self.zero_status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.zero_status_label.setText(f"未校准（零点=VCC/2={self.vcc/2.0:.3f}V）")
            self.zero_status_label.setStyleSheet("color: #888; font-weight: bold;")

    def update_zero_cal_btn(self):
        if self.zero_cal_active:
            self.zero_cal_btn.setText("取消零点")
            self.zero_cal_btn.setStyleSheet(accent_btn_style("#28a745", "#218838", "#1e7e34"))
        else:
            self.zero_cal_btn.setText("零点校准")
            self.zero_cal_btn.setStyleSheet(accent_btn_style("#fd7e14", "#e06b00", "#c75a00"))

    def toggle_zero_cal(self):
        """零点校准/取消切换

        校准：取最近若干个数据点的 ACS712 输出电压平均值作为零点电压
        取消：零点电压恢复为 VCC/2
        """
        if self.zero_cal_active:
            # 取消零点校准
            self.zero_cal_active = False
            self.v_quiescent = self.vcc / 2.0
            self.vquies_spin.blockSignals(True)
            self.vquies_spin.setValue(self.v_quiescent)
            self.vquies_spin.blockSignals(False)
            self.update_zero_status_label()
            self.update_zero_cal_btn()
            self.save_config()
            self.recompute_current_data()
        else:
            # 执行零点校准：要求有数据
            if not self.vsensor_data:
                QMessageBox.warning(self, "提示", "请先开始采集数据（确保零电流状态）后再校准")
                return
            recent = self.vsensor_data[-10:] if len(self.vsensor_data) >= 10 else self.vsensor_data
            self.v_quiescent = float(np.mean(recent))
            self.zero_cal_active = True
            self.vquies_spin.blockSignals(True)
            self.vquies_spin.setValue(self.v_quiescent)
            self.vquies_spin.blockSignals(False)
            self.update_zero_status_label()
            self.update_zero_cal_btn()
            self.save_config()
            self.recompute_current_data()

    def recompute_current_data(self):
        """零点变化后，按已有 raw_data 重算 current_data"""
        if not self.raw_data:
            return
        self.vsensor_data = [self.adc_to_vsensor(r) for r in self.raw_data]
        self.current_data = [self.adc_to_current(r) for r in self.raw_data]
        self.update_stats()
        self.update_chart()
        self.update_current_display()

    def update_range_display(self):
        info = self.ACS712_RANGES.get(self.acs_range, self.ACS712_RANGES['5A'])
        self.range_label.setText(
            f"量程: ±{info['range_a']}A  灵敏度: {info['sensitivity']*1000:.0f}mV/A  "
            f"零点: {self.v_quiescent:.3f}V"
        )
        # 受分压与 ADC 限制的可测电流范围
        max_adc = self.ADC_BITS_OPTIONS.get(self.adc_bits, 4096) - 1
        v_sensor_max = self.VREF * self.divider_ratio  # ADC 满量程对应的传感器输出
        i_pos = (v_sensor_max - self.v_quiescent) / self.sensitivity
        i_neg = (0.0 - self.v_quiescent) / self.sensitivity
        lo, hi = min(i_pos, i_neg), max(i_pos, i_neg)
        self.actual_range_label.setText(
            f"可测范围: {lo:.2f}A ~ {hi:.2f}A "
            f"(ADC {max_adc}, 分压 {self.divider_ratio:.3f}x, 受 ADC 量程限制)"
        )

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------
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
            self.current_value_label.setText("--.- " + self.current_unit)
            self.current_raw_label.setText("原始ADC: 连接中...")
            self.current_vadc_label.setText("ADC端电压: --.- V")
            self.current_vsensor_label.setText("传感器输出: --.- V")
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
        except Exception:
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
            self.current_value_label.setText("电流: BLE连接中...")
            self.current_raw_label.setText("ADC: BLE连接中...")
        except Exception as e:
            QMessageBox.critical(self, "连接错误", f"BLE 连接失败: {e}")

    def on_ble_status(self, status):
        if status == "connected":
            self.current_value_label.setText("电流: BLE已连接，等待数据...")
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
        self.zero_cal_btn.setEnabled(False)
        self.current_value_label.setText(f"--.- {self.current_unit}")
        self.current_raw_label.setText("原始ADC: 已断开")
        self.current_vadc_label.setText("ADC端电压: --.- V")
        self.current_vsensor_label.setText("传感器输出: --.- V")

    # ------------------------------------------------------------------
    # 采集控制
    # ------------------------------------------------------------------
    def start_collection(self):
        self.current_data.clear()
        self.vsensor_data.clear()
        self.time_data.clear()
        self.raw_data.clear()
        self.data_text.clear()
        self.last_sample_time_ms = 0
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.zero_cal_btn.setEnabled(True)
        self.save_btn.setEnabled(False)
        self.current_value_label.setText("电流: 采集中...")
        self.current_raw_label.setText("原始ADC: 采集中...")

    def stop_collection(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.save_btn.setEnabled(len(self.current_data) > 0)

    # ------------------------------------------------------------------
    # 数据处理
    # ------------------------------------------------------------------
    def handle_data(self, data):
        if data.startswith("ERROR:"):
            QMessageBox.critical(self, "连接错误", data[6:])
            self.disconnect_all()
            return

        if data == "START":
            self.current_value_label.setText("电流: 设备就绪")
            self.current_raw_label.setText("原始ADC: 等待数据...")
            return

        # 未开始采集：仅刷新实时显示（不计入数据集）
        if not self.stop_btn.isEnabled():
            try:
                if "," in data:
                    parts = data.split(",")
                    if len(parts) == 2:
                        raw_value = int(parts[1])
                        self._update_realtime_display(raw_value)
            except ValueError:
                pass
            return

        try:
            if "," in data:
                parts = data.split(",")
                if len(parts) == 2:
                    timestamp_ms = int(parts[0])
                    raw_value = int(parts[1])

                    # 采样频率控制
                    if timestamp_ms - self.last_sample_time_ms < self.sample_interval_ms:
                        return
                    self.last_sample_time_ms = timestamp_ms

                    if len(self.time_data) == 0:
                        self.start_timestamp_ms = timestamp_ms

                    relative_time_s = (timestamp_ms - self.start_timestamp_ms) / 1000.0

                    v_adc = self.adc_to_vadc(raw_value)
                    v_sensor = self.adc_to_vsensor(raw_value)
                    current = self.adc_to_current(raw_value)

                    self.raw_data.append(raw_value)
                    self.vsensor_data.append(v_sensor)
                    self.current_data.append(current)
                    self.time_data.append(relative_time_s)

                    time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    display_text = (f"时间: {time_str} | ADC: {raw_value} | "
                                    f"ADC端: {v_adc:.4f}V | 传感器: {v_sensor:.4f}V | "
                                    f"电流: {self.format_current(current)} {self.current_unit}")
                    self.data_text.append(display_text)
                    self.data_text.verticalScrollBar().setValue(
                        self.data_text.verticalScrollBar().maximum()
                    )

                    self._update_realtime_display(raw_value)
                    self.update_stats()

        except ValueError:
            pass

    def _update_realtime_display(self, raw_value):
        """刷新实时数据显示（实时值 / 原始值 / 各级电压）"""
        v_adc = self.adc_to_vadc(raw_value)
        v_sensor = self.adc_to_vsensor(raw_value)
        current = self.adc_to_current(raw_value)

        self.current_raw_label.setText(f"原始ADC: {raw_value}")
        self.current_vadc_label.setText(f"ADC端电压: {v_adc:.4f} V")
        self.current_vsensor_label.setText(f"传感器输出: {v_sensor:.4f} V")

        if self.current_mode == 'AC':
            # AC 模式：显示滚动窗口 RMS
            rms = self._compute_ac_rms()
            if rms is not None:
                self.current_value_label.setText(f"{self.format_current(rms)} {self.current_unit}")
            else:
                self.current_value_label.setText(f"{self.format_current(current)} {self.current_unit}")
        else:
            self.current_value_label.setText(f"{self.format_current(current)} {self.current_unit}")

    def _compute_ac_rms(self):
        """计算 AC 模式下滚动窗口的电流 RMS（安培）"""
        if not self.current_data:
            return None
        window = self.current_data[-self.ac_rms_window:]
        arr = np.array(window, dtype=float)
        return float(np.sqrt(np.mean(arr ** 2)))

    def update_current_display(self):
        """单位/模式变化后刷新大字显示"""
        if not self.current_data:
            self.current_value_label.setText(f"--.- {self.current_unit}")
            return
        if self.current_mode == 'AC':
            rms = self._compute_ac_rms()
            val = rms if rms is not None else self.current_data[-1]
        else:
            val = self.current_data[-1]
        self.current_value_label.setText(f"{self.format_current(val)} {self.current_unit}")

    def update_stats(self):
        if not self.current_data:
            self.stats_label.setText("统计: 暂无数据")
            return
        arr = np.array(self.current_data, dtype=float)
        u = self.current_unit
        if self.current_mode == 'AC':
            rms = float(np.sqrt(np.mean(arr ** 2)))
            peak = float(np.max(np.abs(arr)))
            self.stats_label.setText(
                f"统计: 数据点 {len(arr)} | "
                f"RMS={self.format_current(rms)}{u} | "
                f"峰值={self.format_current(peak)}{u} | "
                f"窗口={self.ac_rms_window}点"
            )
        else:
            avg = float(np.mean(arr))
            mx = float(np.max(arr))
            mn = float(np.min(arr))
            std = float(np.std(arr))
            self.stats_label.setText(
                f"统计: 数据点 {len(arr)} | "
                f"平均={self.format_current(avg)}{u} | "
                f"最大={self.format_current(mx)}{u} | "
                f"最小={self.format_current(mn)}{u} | "
                f"标准差 σ={self.format_current(std)}{u}"
            )

    def update_chart(self):
        if not self.current_data:
            return
        self.figure.clear()
        ax = self.figure.add_subplot(111)

        display_data = [self.to_current_unit(c) for c in self.current_data]
        label = f'电流 ({self.current_unit})'
        ax.plot(self.time_data, display_data, '#0078d4', linewidth=2, label=label)

        # AC 模式叠加 RMS 参考线
        if self.current_mode == 'AC' and len(self.current_data) >= self.ac_rms_window:
            rms = self._compute_ac_rms()
            if rms is not None:
                rms_disp = self.to_current_unit(rms)
                ax.axhline(rms_disp, color='#fd7e14', linestyle='--', linewidth=1.5,
                           label=f'RMS {self.format_current(rms)}{self.current_unit}')
                ax.axhline(-rms_disp, color='#fd7e14', linestyle='--', linewidth=1.5)

        ax.axhline(0, color='#aaaaaa', linestyle=':', linewidth=1)
        ax.set_xlabel('时间 (秒)')
        ax.set_ylabel(label)
        ax.set_title('电流传感器实时数据', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper right')

        if len(self.time_data) > 1:
            ax.set_xlim(min(self.time_data), max(self.time_data))

        self.figure.tight_layout()
        self.canvas.draw()

    # ------------------------------------------------------------------
    # 采样频率 / 保存 / 清除
    # ------------------------------------------------------------------
    def edit_sample_rate(self):
        dialog = SampleRateDialog(self.sample_interval_ms, self)
        if dialog.exec() == 1:
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
        if not self.current_data:
            QMessageBox.warning(self, "警告", "没有数据可保存")
            return
        try:
            filename = f"current_sensor_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"# ACS712 量程={self.acs_range} 灵敏度={self.sensitivity}V/A "
                        f"零点={self.v_quiescent:.4f}V 分压比={self.divider_ratio} "
                        f"模式={self.current_mode} 单位={self.current_unit}\n")
                f.write(f"timestamp_s,raw_adc,v_adc,v_sensor,current_{self.current_unit.lower()}\n")
                for i, (t, current) in enumerate(zip(self.time_data, self.current_data)):
                    raw = self.raw_data[i] if i < len(self.raw_data) else 0
                    v_adc = self.adc_to_vadc(raw)
                    v_sensor = self.adc_to_vsensor(raw)
                    f.write(f"{t:.3f},{raw},{v_adc:.6f},{v_sensor:.6f},"
                            f"{self.to_current_unit(current):.6f}\n")
            QMessageBox.information(self, "成功", f"数据已保存到: {filename}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")

    def clear_data(self):
        self.current_data.clear()
        self.vsensor_data.clear()
        self.time_data.clear()
        self.raw_data.clear()
        self.data_text.clear()
        self.current_value_label.setText(f"--.- {self.current_unit}")
        self.current_raw_label.setText("原始ADC: ------")
        self.current_vadc_label.setText("ADC端电压: --.- V")
        self.current_vsensor_label.setText("传感器输出: --.- V")
        self.stats_label.setText("统计: 暂无数据")
        self.figure.clear()
        self.canvas.draw()
        self.save_btn.setEnabled(False)
