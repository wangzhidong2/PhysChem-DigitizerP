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
import time
from collections import deque
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QSizePolicy, QColorDialog,
)
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter, QColor
from qfluentwidgets import (
    PushButton, PrimaryPushButton, ComboBox, TextEdit, TitleLabel,
    BodyLabel, CaptionLabel, DoubleSpinBox, SwitchButton, FluentIcon as FIF,
    AdaptiveFlowLayout, FlowLayout, LineEdit, ToolButton,
)
import numpy as np

# 从公共模块导入共享代码
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core import (
    fluent_message_box, ChartPanel,
    SerialThread, SimulatorThread,
    SampleRateComboBox, stop_thread,
    load_sensor_config, save_sensor_config,
    SERIAL_AVAILABLE, list_serial_ports, serial_unavailable_hint,
    card_style, primary_btn_style, accent_btn_style, modern_combo_style,
    CollapsibleCard, FluentCard, ExpandableTextEdit,
    scroll_area_style, page_bg_style, apply_module_theme,
    update_collect_btn, set_action_button_width,
    get_logger,
)

log = get_logger("voltage_sensor")

# AI 分析实验：模块专属系统提示词（进入 AI 分析时随实验信息与数据发送给模型，
# 由 core.build_ai_system_prompt 组装进 system 消息）
AI_SYSTEM_PROMPT = (
    "你是一位资深物理实验指导教师与电子测量专家，正在协助分析电压采集实验数据"
    "（ESP32 内置 ADC / ADS1115 16 位 / HX711 24 位，信号可经分压与放大电路接入）。"
    "测量原理：ADC 端电压 V_adc = raw / 满量程 × 参考电压（内置 ADC 有符号模式量程 "
    "-VREF~+VREF，VREF=3.3V；ADS1115 为 raw/32768 × FSR(PGA)；HX711 为 "
    "raw/2^23 × AVDD/Gain/2，满量程差分输入 = ±0.5×(AVDD/Gain)）；被测电压 = V_adc × 分压比 ÷ 放大倍数，启用去皮时再减"
    "空载偏移。理论分辨率 = 参考电压/满量程 × 分压比 ÷ 放大倍数，有效分辨率受噪声限制。"
    "数据特征：稳压源应呈平直曲线；电池等电源呈缓慢下降趋势；ADC 量化台阶、随机噪声"
    "与工频干扰叠加在真实信号上。"
    "常见误差来源：分压电阻精度与温漂、ADC 非线性与噪声、参考电压漂移、未共地或"
    "接地环路、输入超量程、PGA/通道/增益配置与固件不一致、去皮基准选取不当。"
    "分析要求：①结合分压比与放大倍数评估量程与分辨率是否匹配被测信号；"
    "②用均值、标准差、峰峰值与漂移速率量化噪声与趋势，区分真实变化与量化/噪声；"
    "③数据呈台阶状时指出量化或参考跳变来源；④给出多点校准、软件滤波/多次平均、"
    "调整 PGA/增益、更换更高精度 ADC、改善接地与屏蔽等具体建议。"
)


# 多路连接的默认曲线配色（按新建顺序轮换取未用色，界面上可单独改色）
CHANNEL_COLORS = ('#0078d4', '#e74c3c', '#2ecc71', '#f39c12',
                  '#9b59b6', '#00bcd5', '#e67e22', '#16a085')

# 颜色下拉中「自定义…」项的 userData 标记（选中后弹 QColorDialog）
CUSTOM_COLOR_KEY = '__custom__'


def _make_color_icon(hex_color, size=24):
    """生成实心圆色块 QIcon（颜色下拉项的预览图标）。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(hex_color))
    p.drawEllipse(2, 2, size - 4, size - 4)
    p.end()
    return QIcon(pm)


class _Channel:
    """一路连接的数据模型（纯 Python 对象，不持有任何 Qt 控件）。

    每路连接独立选择「有线串口 / 模拟器」、独立串口、独立曲线颜色、
    独立去皮零点；数据按主机统一时间戳记录（见 handle_data）。
    UI 行控件引用由模块统一保管在 _rows[channel.id] 里。
    """

    def __init__(self, cid, name, color, mode='serial', port=''):
        self.id = cid                      # 稳定 id（信号绑定用，删除后不复用）
        self.name = name                    # 显示名（可自定义，留空回退默认名）
        self.default_name = name            # 默认名（通道N，创建时定序）
        self.color = color                  # 曲线颜色
        self.mode = mode                    # 'serial' | 'simulator'
        self.port = port                    # 串口模式下选中的端口
        self.thread = None                  # SerialThread / SimulatorThread
        # 采集数据（内部电压单位：伏特）
        self.time_data = []
        self.raw_data = []
        self.voltage_data = []
        # 去皮 / 实时显示用的滚动窗口（含未采集时的实时数据）
        self.live_window = deque(maxlen=10)
        # 上次记录样本的主机相对秒（采样间隔过滤，每路独立）
        self.last_sample_s = None
        # 去皮零点（每路独立）
        self.tare_offset_v = 0.0
        self.tare_active = False


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

    def __init__(self):
        super().__init__()
        self._collecting = False  # 当前是否在采集（合并开始/停止按钮状态）
        # 多路连接：每路一个 _Channel（独立模式/串口/颜色/去皮/数据）
        self.channels = []
        self._rows = {}              # channel.id -> 行控件引用 dict
        self._next_channel_id = 1   # 稳定 id 分配器（删除后不复用）
        self._next_channel_seq = 1  # 显示名序号（通道N）
        self._t0_mono = None        # 采集期主机统一时间基准（首个样本时刻）

        # 采样频率设置（毫秒）—— 全部通道共用
        self.sample_interval_ms = 100  # 默认 100ms (10Hz)

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

        self.init_ui()
        # 恢复上次的通道列表（含模式/串口/颜色/去皮）；无记录时建一路默认通道
        self._restore_channels()

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
        return config

    def save_config(self):
        first = self.channels[0] if self.channels else None
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
            # 兼容旧版单通道上位机：顶层去皮字段取第 1 路的值
            'tare_offset_v': first.tare_offset_v if first else 0.0,
            'tare_active': first.tare_active if first else False,
            # 多路连接：每路的模式/串口/颜色/去皮
            'channels': [
                {'name': ch.name, 'mode': ch.mode, 'port': ch.port,
                 'color': ch.color, 'tare_offset_v': ch.tare_offset_v,
                 'tare_active': ch.tare_active}
                for ch in self.channels
            ],
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

    def adc_to_voltage(self, adc_value, apply_tare=True, channel=None):
        """实际被测电压 = ADC端电压 × 分压比 / 放大倍数。

        apply_tare=False 时不扣去皮零点，用于在已有零点的基础上重新计算新零点。
        多路连接时传 channel：按该通道自己的零点去皮（各路零点独立）。
        """
        v_adc = self.adc_to_vadc(adc_value)
        actual_voltage = v_adc * self.divider_ratio / self.amp_ratio
        # 启用去皮时扣除该通道自己的零点偏移
        if apply_tare and channel is not None and channel.tare_active:
            actual_voltage -= channel.tare_offset_v
        return actual_voltage

    def adc_to_vadc(self, adc_value):
        """计算 ADC 输入端电压（未做分压/放大还原）。

        统一有符号换算：下位机输出有符号 ADC 值，0 对应 0V，量程 -VREF~+VREF。
        例如 12 位 ADC，原始值 -4095~+4095，0 对应 0V，
        -4095 对应 -VREF，+4095 对应 +VREF。
        公式：(adc / max_adc) × VREF
        """
        # HX711 模式：24位有符号补码（饱和码 ±2^23）
        # 数据手册：满量程差分输入范围 = ±0.5 × (AVDD / Gain)，
        # 即满码对应电压 = AVDD / Gain / 2（通道A Gain128@5V → ±20mV，B Gain32@5V → ±80mV）
        if self.hx711_mode:
            gain = 128 if self.hx711_channel == 'A' else 32
            return adc_value / 8388608.0 * (self.hx711_avdd / gain / 2)
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

        # ========== 卡片1：连接控制（可折叠，参考电学综合多连接面板样式） ==========
        card_conn_content = QWidget()
        card_layout = QVBoxLayout(card_conn_content)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(10)

        card_layout.addWidget(CaptionLabel(
            "每路连接可单独选择串口/模拟器与曲线颜色，多路数据同图叠加对比"))

        # 通道子卡容器：每路连接一张子卡（独立模式/串口/颜色/连接按钮）
        self.channels_container = QWidget()
        self.channels_layout = QVBoxLayout(self.channels_container)
        self.channels_layout.setContentsMargins(0, 0, 0, 0)
        self.channels_layout.setSpacing(8)
        card_layout.addWidget(self.channels_container)

        # 采样频率行（全部通道共用同一采样间隔）
        row1 = QHBoxLayout()
        row1.setSpacing(10)
        row1.addWidget(BodyLabel("采样频率:"))
        self.sample_rate_combo = SampleRateComboBox()
        self.sample_rate_combo.setSampleInterval(self.sample_interval_ms)
        self.sample_rate_combo.setMaximumWidth(120)
        self.sample_rate_combo.sampleIntervalChanged.connect(self.on_sample_interval_changed)
        row1.addWidget(self.sample_rate_combo)
        row1.addStretch()
        card_layout.addLayout(row1)

        self.card_conn = FluentCard("连接控制", card_conn_content, expanded=True, icon=FIF.CONNECT)
        # header 右侧：＋ 新建连接（原生按钮，随主题自适应）
        self.add_channel_btn = PushButton("＋ 新建连接")
        self.add_channel_btn.setFixedHeight(30)
        self.add_channel_btn.setToolTip(
            "增加一路 ESP32 连接：\n"
            "每路可单独选择「有线串口 / 模拟器」，单独连接/断开，\n"
            "单独换曲线颜色；多路数据叠加画在同一张图上")
        self.add_channel_btn.clicked.connect(lambda: self.add_channel())
        self.card_conn.add_header_widget(self.add_channel_btn)
        # 主卡展开动画结束后按子卡实际高度收敛（子卡折叠后 sizeHint 不缩）
        self.card_conn.expandAni.finished.connect(self._sync_conn_card_height)
        layout.addWidget(self.card_conn)

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
        # 该版本 SwitchButton 无描述文字（setText 只改 On/Off 标签），
        # 描述用独立标签放在开关旁
        self.hx711_check = SwitchButton()
        hx711_row.addWidget(self.hx711_check)
        hx711_row.addWidget(BodyLabel("HX711 模式（24位有符号）"))
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
        # AVDD 是 HX711 的模拟电源引脚电压，同时充当 ADC 参考电压，直接决定换算结果
        self.hx711_avdd_spin.setToolTip(
            "AVDD：HX711 模拟电源引脚上的电压（2.6–5.5V）。它同时是 ADC 的参考电压，"
            "本模块的电压换算 V = raw/2²³ × (AVDD / Gain) 依赖此值。"
            "模块上该脚通常与 VCC 相连（片内稳压器旁路），请填模块供电的实测电压"
            "（万用表量 AVDD–GND）；它一般还给传感器提供桥路激励 E+，故称重测量是比例式的。"
        )
        self.hx711_avdd_spin.valueChanged.connect(self.on_hx711_avdd_changed)
        self.hx711_avdd_spin.setEnabled(self.hx711_mode)
        hx711_row.addWidget(self.hx711_avdd_spin)

        hx711_row.addWidget(BodyLabel("通道:"))
        self.hx711_channel_combo = ComboBox()
        self.hx711_channel_combo.addItems(["B (增益 32, ±80mV)", "A (增益 128, ±20mV)"])
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
        self.ads1115_check = SwitchButton()
        ads1115_row.addWidget(self.ads1115_check)
        ads1115_row.addWidget(BodyLabel("ADS1115 模式（16位有符号补码）"))
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

        # 紧凑流式布局：按控件自然宽度排列，宽度不够时自动换行。
        # 不用 AdaptiveFlowLayout——那是等宽卡片网格布局，会把每个控件
        # 拉成同一列宽，标签与输入框之间出现大片空白
        params_row = FlowLayout(isTight=True)
        params_row.setHorizontalSpacing(10)
        params_row.setVerticalSpacing(8)

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
        self.divider_spin.setFixedHeight(36)
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
        self.amp_spin.setFixedHeight(36)
        self.amp_spin.setToolTip(params_hint_text)
        self.amp_spin.valueChanged.connect(self.on_amp_changed)
        params_row.addWidget(self.amp_spin)

        self.actual_range_label = BodyLabel(f"实际量程: -{self.VREF * self.divider_ratio / self.amp_ratio:.2f}V~+{self.VREF * self.divider_ratio / self.amp_ratio:.2f}V")
        self.actual_range_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        params_row.addWidget(self.actual_range_label)

        # 显示单位与去皮并入本行（原各占一行，现合并减少总行数）
        params_row.addWidget(BodyLabel("显示单位:"))
        self.unit_combo = ComboBox()
        self.unit_combo.addItems(["千伏 (kV)", "伏 (V)", "毫伏 (mV)"])
        unit_map = {'kV': 0, 'V': 1, 'mV': 2}
        self.unit_combo.setCurrentIndex(unit_map.get(self.current_unit, 1))
        self.unit_combo.currentIndexChanged.connect(self.on_unit_changed)
        params_row.addWidget(self.unit_combo)

        params_row.addWidget(BodyLabel("去皮:"))
        self.tare_status_label = BodyLabel("未启用")
        self.tare_status_label.setStyleSheet("color: #888; font-weight: bold;")
        params_row.addWidget(self.tare_status_label)

        self.tare_btn = PushButton("去皮")
        self.tare_btn.setFixedHeight(36)
        set_action_button_width(self.tare_btn)
        self.tare_btn.setStyleSheet("background-color: #fd7e14; color: white;")
        self.tare_btn.setToolTip("取最近 10 个采样点的平均值作为零点，从测量值中扣除。\n"
                                 "随时可点（不必先开始采集，连上设备有数据即可）。\n"
                                 "可反复点击重新归零；多路连接时对有数据流入的通道分别去皮（各路零点独立）。")
        self.tare_btn.clicked.connect(self.tare_now)
        self.tare_btn.setEnabled(False)
        params_row.addWidget(self.tare_btn)
        adc_card_layout.addLayout(params_row)

        card_adc = FluentCard("ADC 与电路参数", card_adc_content, expanded=True, icon=FIF.SETTING)
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

        card_data = FluentCard("实时数据", card_data_content, expanded=True, icon=FIF.HISTORY)
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
        self.chart.set_ai_data_provider(self._ai_data)
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

        # 去皮按钮已移到「ADC 与电路参数」卡：连接后即可用，支持反复点击重新去皮

        

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
        card_actions = FluentCard("操作按钮", card_actions_content, expanded=True, icon=FIF.PLAY)
        layout.addWidget(card_actions)

        layout.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_chart)
        self.timer.start(100)

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
        # 刷新当前电压大字显示（取最近一路有数据的通道）
        for ch in reversed(self.channels):
            if ch.voltage_data:
                self.current_voltage_label.setText(
                    f"{self.format_voltage(ch.voltage_data[-1])} {self.current_unit}")
                break

    def update_tare_status_label(self):
        """刷新去皮状态标签：多路时逐路显示零点（各路独立）。"""
        actives = [ch for ch in self.channels if ch.tare_active]
        if actives:
            text = "已启用 (" + "; ".join(
                f"{ch.name} {self.format_voltage(ch.tare_offset_v)}{self.current_unit}"
                for ch in actives) + ")"
            self.tare_status_label.setText(text)
            self.tare_status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.tare_status_label.setText("未启用")
            self.tare_status_label.setStyleSheet("color: #888; font-weight: bold;")

    def tare_now(self):
        """去皮：取最近若干个采样点的平均值作为零点，从测量值中扣除。

        1. 不要求先「开始采集」——设备连着、有数据流入即可去皮（用实时采样窗口）；
        2. 可反复点击，每点一次都以当前读数重新归零，没有「取消去皮」；
        3. 零点按去皮前的读数计算，重复去皮不会互相叠加、也不会把已有零点清掉；
        4. 多路连接时对**所有有数据流入的通道**分别去皮，各路零点独立。
        """
        targets = [ch for ch in self.channels if ch.live_window]
        if not targets:
            fluent_message_box(self, "提示", "还没有收到数据，等数据流入后再去皮")
            return
        parts = []
        for ch in targets:
            # 取最近 10 个采样点（去皮前的电压）平均值作为新零点
            pre_tare = [self.adc_to_voltage(r, apply_tare=False) for r in ch.live_window]
            ch.tare_offset_v = float(np.mean(pre_tare))
            ch.tare_active = True
            parts.append(f"{ch.name} 零点={ch.tare_offset_v:.6g}V")
        log.info("去皮：%s", "; ".join(parts))
        self.save_config()
        self.update_tare_status_label()
        # 按新零点重算已采集的数据，曲线同步归零
        self.recompute_voltage_data()

    def api_actions(self):
        """本模块支持的控制动作（供 DataService / HTTP 层展示）。"""
        return ['tare']

    def api_command(self, action, params=None):
        """执行模块特有控制动作（由 DataService 保证在 GUI 线程调用）。
        通用动作（start/stop/clear/toggle）返回 None 交给通用动作表。"""
        if action == 'tare':
            if not any(ch.live_window for ch in self.channels):
                return {'ok': False, 'message': '还没有收到数据，无法去皮'}
            self.tare_now()
            offsets = "; ".join(f"{ch.name}={ch.tare_offset_v:.6g}V"
                                for ch in self.channels if ch.tare_active)
            return {'ok': True, 'message': f'已去皮（{offsets}）'}
        return None

    def recompute_voltage_data(self):
        """去皮状态变化后，按各通道已有 raw_data 重算 voltage_data"""
        if not any(ch.raw_data for ch in self.channels):
            return
        for ch in self.channels:
            ch.voltage_data = [self.adc_to_voltage(r, channel=ch) for r in ch.raw_data]
        self.update_stats()
        self.update_chart()
        # 大字显示最近一路有数据的最新值
        for ch in reversed(self.channels):
            if ch.voltage_data:
                self.current_voltage_label.setText(
                    f"{self.format_voltage(ch.voltage_data[-1])} {self.current_unit}")
                break

    def update_range_display(self):
        if self.hx711_mode:
            gain = 128 if self.hx711_channel == 'A' else 32
            fs = self.hx711_avdd / gain / 2  # 满量程差分电压 = ±0.5×(AVDD/Gain)
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

    # ============================================================
    # 多路连接管理：通道的增删 / 行控件 / 单路连接控制
    # ============================================================
    def _restore_channels(self):
        """按配置重建通道行；旧版单通道配置自动迁移为一路通道。"""
        saved = (self.config or {}).get('channels') or []
        if saved:
            for item in saved:
                mode = item.get('mode', 'serial')
                if mode != 'simulator' and not SERIAL_AVAILABLE:
                    mode = 'simulator'   # pyserial 缺失时优雅降级
                ch = self._make_channel(
                    name=item.get('name') or None,
                    color=item.get('color') or None,
                    mode=mode, port=item.get('port', ''))
                ch.tare_offset_v = float(item.get('tare_offset_v', 0.0) or 0.0)
                ch.tare_active = bool(item.get('tare_active', False))
        else:
            # 旧版单通道配置迁移：保留顶层去皮字段作为第 1 路零点
            ch = self._make_channel(
                mode='serial' if SERIAL_AVAILABLE else 'simulator')
            ch.tare_offset_v = float((self.config or {}).get('tare_offset_v', 0.0) or 0.0)
            ch.tare_active = bool((self.config or {}).get('tare_active', False))
        self._sync_compat_aliases()
        self.update_tare_status_label()

    def _make_channel(self, color=None, mode='serial', port='', name=None):
        """创建通道对象 + 对应 UI 行（不重复使用已删除通道的 id/name）。"""
        cid = self._next_channel_id
        self._next_channel_id += 1
        seq = self._next_channel_seq
        self._next_channel_seq += 1
        if not color:
            used = {ch.color for ch in self.channels}
            color = next((c for c in CHANNEL_COLORS if c not in used),
                         CHANNEL_COLORS[(seq - 1) % len(CHANNEL_COLORS)])
        ch = _Channel(cid, name or f"通道{seq}", color, mode=mode, port=port)
        self.channels.append(ch)
        self._build_channel_card(ch)
        self._update_delete_btns()
        self._sync_conn_card_height()
        return ch

    def add_channel(self):
        """「新建连接」按钮：增加一路连接（默认有线串口，缺 pyserial 时为模拟器）。"""
        self._make_channel(mode='serial' if SERIAL_AVAILABLE else 'simulator')
        self._sync_compat_aliases()
        self.save_config()

    def _delete_channel(self, ch):
        """删除一路连接（正在连接的通道须先断开；至少保留一路）。"""
        if ch.thread and ch.thread.isRunning():
            fluent_message_box(self, "提示", f"{ch.name} 正在连接，请先断开再删除")
            return
        refs = self._rows.pop(ch.id, None)
        if refs:
            self.channels_layout.removeWidget(refs['card'])
            refs['card'].deleteLater()
        self.channels.remove(ch)
        self._update_delete_btns()
        self._sync_compat_aliases()
        self.save_config()
        self._sync_conn_card_height()

    def _sync_conn_card_height(self):
        """连接控制卡高度随子卡实际高度自适应。

        子卡折叠后其 sizeHint() 仍返回全展开高度，主卡 body 的
        sizeHint() 因此高估（折叠后残留空白）；这里把 channels_container
        的贡献替换为各子卡实际 height() 之和 + 间距后重算。
        """
        try:
            card = self.card_conn
            h = card.body.sizeHint().height()
            cont = self.channels_container
            cards = [self._rows[ch.id]['card']
                     for ch in self.channels if ch.id in self._rows]
            if cont is not None and cards:
                actual = sum(c.height() for c in cards) + 8 * (len(cards) - 1)
                h = h - cont.sizeHint().height() + actual
            h = max(int(h), 1)
            card.spaceWidget.setFixedHeight(h)
            if card.isExpand:
                card.setFixedHeight(card.card.height() + h)
        except Exception:
            pass

    def _update_delete_btns(self):
        """仅剩一路时禁用其删除按钮（至少保留一路连接行）。"""
        single = len(self.channels) <= 1
        for ch in self.channels:
            refs = self._rows.get(ch.id)
            if refs:
                refs['delete_btn'].setEnabled(not single)

    def _sync_compat_aliases(self):
        """DataService / 网页端兼容：对外仍暴露单一 mode_combo/port_combo。

        core.DataService.connection_info / _apply_connection 依赖这两个属性
        读写连接方式与端口；多路化后让它们指向第 1 路的行控件，
        set_connection('模拟器'/.../串口端口) 即作用于第 1 路，网页端不破。
        """
        if self.channels:
            refs = self._rows[self.channels[0].id]
            self.mode_combo = refs['mode_combo']
            self.port_combo = refs['port_combo']

    def _build_channel_card(self, ch):
        """为通道创建一张连接子卡（参考电学综合单元卡样式）。

        header：名称编辑 / 图线颜色下拉 / 删除按钮；
        body：连接方式 + 连接按钮；串口行（串口 + 刷新，模拟器下整行隐藏）。
        每路独立：模式选择、串口刷新、连接/断开。
        """
        card = FluentCard(ch.default_name, None, True, self)

        # ---- header：自定义名称 ----
        name_edit = LineEdit(card)
        name_edit.setText(ch.name)
        name_edit.setPlaceholderText("自定义名称")
        name_edit.setFixedWidth(112)
        name_edit.setToolTip("图表图例/实时数据中显示的名称（留空恢复默认「通道N」）")
        name_edit.editingFinished.connect(
            lambda c=ch, e=name_edit: self._on_channel_name_edited(c, e.text()))
        card.add_header_widget(name_edit)

        # ---- header：图线颜色下拉（预设色 + 自定义…） ----
        color_combo = ComboBox(card)
        color_combo.setMinimumWidth(96)
        color_combo.setToolTip("该连接的图线颜色")
        color_combo.currentIndexChanged.connect(
            lambda i, c=ch: self._on_channel_color_changed(c, i))
        card.add_header_widget(color_combo)

        # ---- header：删除按钮 ----
        delete_btn = ToolButton(FluentIcon.DELETE, card)
        delete_btn.setFixedSize(28, 28)
        delete_btn.setToolTip("删除这一路连接（需先断开）")
        delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_btn.clicked.connect(lambda _=False, c=ch: self._delete_channel(c))
        card.add_header_widget(delete_btn)

        # ---- body 第 1 行：连接方式 + 连接/断开（每路独立） ----
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.addWidget(BodyLabel("连接方式"))
        mode_combo = ComboBox()
        mode_combo.addItems(["有线串口", "模拟器"])
        mode_combo.setCurrentIndex(1 if ch.mode == 'simulator' else 0)
        mode_combo.currentIndexChanged.connect(
            lambda i, c=ch: self._on_channel_mode_changed(c, i))
        row1.addWidget(mode_combo)
        row1.addStretch()
        connect_btn = PrimaryPushButton("连接")
        connect_btn.setFixedHeight(30)
        connect_btn.clicked.connect(
            lambda _=False, c=ch: self._toggle_channel_connection(c))
        row1.addWidget(connect_btn)
        w1 = QWidget()
        w1.setLayout(row1)
        card.add_widget(w1)

        # ---- body 第 2 行：串口 + 刷新（模拟器模式整行隐藏） ----
        port_row = QHBoxLayout()
        port_row.setSpacing(8)
        port_row.addWidget(BodyLabel("串口"))
        port_combo = ComboBox()
        port_combo.setMinimumWidth(130)
        self._fill_channel_ports(ch, port_combo)
        port_combo.currentTextChanged.connect(lambda t, c=ch: setattr(c, 'port', t))
        port_row.addWidget(port_combo, 1)
        refresh_btn = PushButton("刷新")
        refresh_btn.setFixedHeight(30)
        refresh_btn.setToolTip("重新枚举本路的串口列表")
        refresh_btn.clicked.connect(
            lambda _=False, c=ch: self._refresh_channel_ports(c))
        port_row.addWidget(refresh_btn)
        port_row_w = QWidget()
        port_row_w.setLayout(port_row)
        card.add_widget(port_row_w)

        # 子卡折叠动画期间逐帧同步主卡高度（子卡折叠后 sizeHint 不缩）
        card.expandAni.valueChanged.connect(self._sync_conn_card_height)
        card.expandAni.finished.connect(self._sync_conn_card_height)

        self.channels_layout.addWidget(card)
        self._rows[ch.id] = {
            'card': card, 'name_edit': name_edit, 'color_combo': color_combo,
            'delete_btn': delete_btn, 'mode_combo': mode_combo,
            'port_combo': port_combo, 'port_row': port_row_w,
            'refresh_btn': refresh_btn, 'connect_btn': connect_btn,
        }
        self._init_channel_color_combo(ch)
        self._apply_channel_mode_visibility(ch)

    def _init_channel_color_combo(self, ch):
        """（重建）填充颜色下拉：预设色 + 已存自定义色 + 「自定义…」项。"""
        refs = self._rows.get(ch.id)
        if not refs:
            return
        combo = refs['color_combo']
        combo.blockSignals(True)
        combo.clear()
        for c in CHANNEL_COLORS:
            combo.addItem(c, _make_color_icon(c), userData=c)
        if ch.color and combo.findData(ch.color) < 0:
            combo.addItem(ch.color, _make_color_icon(ch.color), userData=ch.color)
        combo.addItem("自定义…", QIcon(), userData=CUSTOM_COLOR_KEY)
        idx = combo.findData(ch.color)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    def _on_channel_color_changed(self, ch, index):
        """颜色下拉选中：预设色直接生效；「自定义…」弹 QColorDialog。"""
        refs = self._rows.get(ch.id)
        if not refs:
            return
        combo = refs['color_combo']
        data = combo.itemData(index)
        if data == CUSTOM_COLOR_KEY:
            color = QColorDialog.getColor(
                QColor(ch.color), self, f"选择 {ch.name} 的曲线颜色")
            if not color.isValid():
                self._init_channel_color_combo(ch)
                return
            ch.color = color.name()
            # 该项定格为选定的颜色，尾部再补一个「自定义…」常驻入口
            combo.blockSignals(True)
            combo.setItemText(index, ch.color)
            combo.setItemIcon(index, _make_color_icon(ch.color))
            combo.setItemData(index, ch.color)
            combo.addItem("自定义…", QIcon(), userData=CUSTOM_COLOR_KEY)
            combo.blockSignals(False)
        else:
            ch.color = data
        self.save_config()
        self.update_chart()

    def _on_channel_name_edited(self, ch, text):
        """名称编辑完成：写回通道名（留空恢复默认「通道N」）。"""
        t = text.strip()
        ch.name = t or ch.default_name
        refs = self._rows.get(ch.id)
        if refs:
            try:
                refs['card'].setTitle(ch.name)
            except Exception:
                pass
        self.save_config()
        self.update_chart()

    def _fill_channel_ports(self, ch, combo):
        """重填串口列表，尽量保住该通道上次选中的端口。"""
        want = ch.port
        combo.clear()
        ports = list_serial_ports()
        for device, _desc in ports:
            combo.addItem(device)
        if not ports:
            combo.addItem("未安装 pyserial" if not SERIAL_AVAILABLE else "无可用串口")
        if want and combo.findText(want) >= 0:
            combo.setCurrentText(want)
        ch.port = combo.currentText()

    def refresh_ports(self):
        """刷新所有通道的串口列表（网页端 refresh_ports 命令也走这里）。"""
        for ch in self.channels:
            self._refresh_channel_ports(ch)

    def _refresh_channel_ports(self, ch):
        refs = self._rows.get(ch.id)
        if refs:
            self._fill_channel_ports(ch, refs['port_combo'])

    def _on_channel_mode_changed(self, ch, index):
        ch.mode = 'simulator' if index == 1 else 'serial'
        self._apply_channel_mode_visibility(ch)
        self.save_config()

    def _apply_channel_mode_visibility(self, ch):
        """模拟器模式下隐藏本路的串口行（标签 + 下拉 + 刷新按钮）。"""
        refs = self._rows.get(ch.id)
        if refs:
            is_sim = ch.mode == 'simulator'
            refs['port_row'].setVisible(not is_sim)
            try:
                refs['card']._adjustViewSize()
            except Exception:
                pass
            self._sync_conn_card_height()

    def _toggle_channel_connection(self, ch):
        """单路的连接/断开按钮：按本路线程状态切换。"""
        if ch.thread and ch.thread.isRunning():
            self._disconnect_channel(ch)
        else:
            self._connect_channel(ch)

    def _connect_channel(self, ch):
        """连接单路：串口或模拟器（其余通道不受影响）。"""
        try:
            if ch.mode == 'simulator':
                # 模拟器产生有符号 ADC 范围的原始值，中点为 0V
                max_adc = self.ADC_BITS_OPTIONS.get(self.adc_bits, 4095)
                th = SimulatorThread(value_min=-max_adc, value_max=max_adc,
                                     interval_ms=self.sample_interval_ms)
            else:
                if not SERIAL_AVAILABLE:
                    fluent_message_box(self, "提示", serial_unavailable_hint())
                    return
                port = self._rows[ch.id]['port_combo'].currentText()
                if not port or "未安装" in port or "无可用" in port:
                    fluent_message_box(self, "错误", f"{ch.name}: 请选择串口")
                    return
                ch.port = port
                th = SerialThread(port)
            th.data_received.connect(lambda d, c=ch: self.handle_data(d, c))
            ch.thread = th
            th.start()
        except Exception as e:
            ch.thread = None
            fluent_message_box(self, "连接错误", f"{ch.name} 连接失败: {e}")
            return
        refs = self._rows.get(ch.id)
        if refs:
            refs['connect_btn'].setText("断开")
        log.info("%s 已连接（%s）", ch.name,
                 '模拟器' if ch.mode == 'simulator' else ch.port)
        self._set_collect_enabled(True)
        self.tare_btn.setEnabled(True)   # 连接后即可去皮，不必先开始采集
        self.current_voltage_label.setText("--.- V")
        self.current_raw_label.setText(f"{ch.name}: 连接中...")
        self.current_vadc_label.setText("ADC端电压: --.- V")

    def _disconnect_channel(self, ch):
        """断开单路（其余通道不受影响）。"""
        if ch.thread:
            stop_thread(ch.thread, name=f"电压{ch.name}线程")
            ch.thread = None
        refs = self._rows.get(ch.id)
        if refs:
            refs['connect_btn'].setText("连接")
        log.info("%s 已断开", ch.name)
        if not any(c.thread for c in self.channels):
            self._set_collect_enabled(False)
            self.tare_btn.setEnabled(False)
            self.current_voltage_label.setText(f"--.- {self.current_unit}")
            self.current_raw_label.setText("原始ADC: 已断开")
            self.current_vadc_label.setText("ADC端电压: --.- V")

    def connect_device(self):
        """连接全部未连接的通道（网页端 set_connection connect=true 走这里）。"""
        for ch in self.channels:
            if not (ch.thread and ch.thread.isRunning()):
                self._connect_channel(ch)

    def disconnect_all(self):
        """断开全部通道（退出清理 / 网页端命令也走这里）。"""
        for ch in list(self.channels):
            self._disconnect_channel(ch)

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
        for ch in self.channels:
            ch.time_data.clear()
            ch.raw_data.clear()
            ch.voltage_data.clear()
            ch.last_sample_s = None
        self.data_text.clear()
        # 主机统一时间基准：以采集期收到的**首个样本**为 t=0（各路共享）
        self._t0_mono = None
        self._collecting = True
        log.info("开始采集（已连接 %d 路）",
                 sum(1 for ch in self.channels if ch.thread))
        self._refresh_collect_btn()
        self.save_btn.setEnabled(False)
        self.current_voltage_label.setText("电压: 采集中...")
        self.current_raw_label.setText("原始ADC: 采集中...")

    def stop_collection(self):
        self._collecting = False
        self._refresh_collect_btn()
        total = sum(len(ch.voltage_data) for ch in self.channels)
        self.save_btn.setEnabled(total > 0)
        log.info("停止采集，共 %d 个数据点", total)
        if total > 0:
            # 大字显示数据最多通道的均值
            main = max(self.channels, key=lambda c: len(c.voltage_data))
            if main.voltage_data:
                avg_v = np.mean(main.voltage_data)
                self.current_voltage_label.setText(
                    f"{self.format_voltage(avg_v)} {self.current_unit}")

    def handle_data(self, data, ch):
        """一路连接的数据回调（SerialThread / SimulatorThread → 本模块）。

        多路连接下的约定：
        - ERROR / START 按通道处理，出错只断开这一路；
        - 记录用**主机统一时间戳**（time.monotonic），各路天然对齐在同一
          时间轴（不同 ESP32 开机时刻不同，固件时间戳不可跨路比较）；
        - 固件的 timestamp 字段只做格式解析，不参与记录。
        """
        if data.startswith("ERROR:"):
            log.error("%s 设备错误: %s", ch.name, data[6:])
            fluent_message_box(self, "连接错误", f"{ch.name}: {data[6:]}")
            self._disconnect_channel(ch)
            return

        if data == "START":
            self.current_raw_label.setText(f"{ch.name}: 设备就绪，等待数据...")
            return

        try:
            if "," not in data:
                return
            parts = data.split(",")
            if len(parts) != 2:
                return
            raw_value = int(parts[1])
        except ValueError:
            return

        # 实时显示 + 去皮滚动窗口（未采集时也持续刷新）
        ch.live_window.append(raw_value)
        voltage = self.adc_to_voltage(raw_value, channel=ch)
        v_adc = self.adc_to_vadc(raw_value)
        self.current_raw_label.setText(f"{ch.name} ADC: {raw_value}")
        self.current_voltage_label.setText(
            f"{self.format_voltage(voltage)} {self.current_unit}（{ch.name}）")
        self.current_vadc_label.setText(
            f"ADC端电压: {self.format_voltage(v_adc)} {self.current_unit}")

        if not self._collecting:
            return

        # 主机统一时间戳：采集期首个到达样本定为 t=0
        now = time.monotonic()
        if self._t0_mono is None:
            self._t0_mono = now
        t_rel = now - self._t0_mono

        # 采样频率控制（每路独立过滤）
        if ch.last_sample_s is not None and \
                (t_rel - ch.last_sample_s) * 1000 < self.sample_interval_ms:
            return
        ch.last_sample_s = t_rel

        ch.raw_data.append(raw_value)
        ch.voltage_data.append(voltage)
        ch.time_data.append(t_rel)

        time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        display_text = (f"{time_str} | {ch.name} | ADC: {raw_value} | "
                        f"ADC端: {self.format_voltage(v_adc)} {self.current_unit} | "
                        f"实际电压: {self.format_voltage(voltage)} {self.current_unit}")
        self.data_text.append(display_text)
        self.data_text.verticalScrollBar().setValue(
            self.data_text.verticalScrollBar().maximum()
        )
        self.update_stats()

    def update_stats(self):
        """统计栏：每路有数据的通道各显示一行统计（点数/均值/极值/σ）。"""
        parts = []
        for ch in self.channels:
            if not ch.voltage_data:
                continue
            avg_v = np.mean(ch.voltage_data)
            max_v = np.max(ch.voltage_data)
            min_v = np.min(ch.voltage_data)
            std_v = np.std(ch.voltage_data)
            u = self.current_unit
            parts.append(
                f"{ch.name}: 点数 {len(ch.voltage_data)} | "
                f"均={self.format_voltage(avg_v)}{u} | "
                f"最大={self.format_voltage(max_v)}{u} | "
                f"最小={self.format_voltage(min_v)}{u} | "
                f"σ={self.format_voltage(std_v)}{u}")
        if parts:
            self.stats_label.setText("统计: " + " ‖ ".join(parts))

    def update_chart(self):
        if not self.isVisible():
            return  # 页面隐藏时跳过重绘（定时器不停止，避免白耗 UI 线程）
        active = [ch for ch in self.channels if ch.voltage_data]
        if not active:
            return
        c = self.chart
        c.begin()
        all_t = []
        # 每路一条曲线：颜色 = 各通道行色块上选的颜色，图例 = 通道名
        for ch in active:
            display_data = [self.to_current_unit(v) for v in ch.voltage_data]
            c.plot(ch.time_data, display_data, color=ch.color, width=2,
                   label=f'{ch.name} ({self.current_unit})')
            all_t.extend(ch.time_data)
        c.set_labels('时间 (秒)', f'电压 ({self.current_unit})')
        c.set_title('电压传感器实时数据（多路对比）' if len(active) > 1
                    else '电压传感器实时数据')
        c.legend()
        if len(all_t) > 1:
            c.set_xlim(min(all_t), max(all_t))
        c.end()

    def on_sample_interval_changed(self, interval_ms):
        """采样频率改变时更新间隔并保存配置（内联下拉框触发）"""
        self.sample_interval_ms = interval_ms
        self.save_config()

    def save_data(self):
        total = sum(len(ch.voltage_data) for ch in self.channels)
        if total == 0:
            fluent_message_box(self, "警告", "没有数据可保存")
            return
        try:
            filename = f"voltage_sensor_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', encoding='utf-8') as f:
                # 长表格式：一行一个样本 + 通道名列。多路的时间轴天然对齐
                # （主机统一时间戳），便于 Excel 透视/筛选按通道分组分析
                f.write(f"channel,timestamp_s,raw_adc,voltage_{self.current_unit.lower()}\n")
                for ch in self.channels:
                    for i, voltage in enumerate(ch.voltage_data):
                        t = ch.time_data[i] if i < len(ch.time_data) else 0.0
                        raw = ch.raw_data[i] if i < len(ch.raw_data) else 0
                        f.write(f"{ch.name},{t:.3f},{raw},"
                                f"{self.to_current_unit(voltage):.6f}\n")
            log.info("数据已保存到: %s（%d 点）", filename, total)
            fluent_message_box(self, "成功", f"数据已保存到: {filename}")
        except Exception as e:
            log.error("保存失败: %s", e)
            fluent_message_box(self, "错误", f"保存失败: {e}")

    def clear_data(self):
        for ch in self.channels:
            ch.time_data.clear()
            ch.raw_data.clear()
            ch.voltage_data.clear()
            ch.last_sample_s = None
        self._t0_mono = None
        self.data_text.clear()
        log.info("已清除数据")
        self.current_voltage_label.setText(f"--.- {self.current_unit}")
        self.current_raw_label.setText("原始ADC: ------")
        self.current_vadc_label.setText(f"ADC端电压: --.- {self.current_unit}")
        self.stats_label.setText("统计信息: 暂无数据")
        self.chart.clear_chart()
        self.save_btn.setEnabled(False)

    def _ai_data(self):
        """AI 分析实验数据回调（图表卡「AI分析实验」按钮调用）。

        多路连接时取**数据最多的通道**作为主分析序列，各通道概况与
        每路去皮零点写入 params，供模型理解多路对比背景。
        """
        active = [ch for ch in self.channels if ch.voltage_data]
        if not active:
            return None
        main = max(active, key=lambda c: len(c.voltage_data))
        # 电路参数：ADC 端满量程、实际量程与理论分辨率（随模式变化）
        if self.ads1115_mode:
            fs = self.ADS1115_PGA_RANGES.get(self.ads1115_pga, 2.048)
            counts = 32768.0
        elif self.hx711_mode:
            gain = 128 if self.hx711_channel == 'A' else 32
            fs, counts = self.hx711_avdd / gain / 2, 8388608.0  # 满量程 = ±0.5×(AVDD/Gain)
        else:
            fs = self.VREF
            counts = float(self.ADC_BITS_OPTIONS.get(self.adc_bits, 4095))
        actual = fs * self.divider_ratio / self.amp_ratio
        res = actual / counts
        channels_desc = "、".join(
            f"{ch.name}[{len(ch.voltage_data)}点]"
            + (f"去皮{ch.tare_offset_v:.4g}V" if ch.tare_active else "未去皮")
            for ch in active)
        return {
            'title': '电压传感器',
            'x_label': '时间 (秒)',
            'y_label': f'电压 ({self.current_unit})',
            'points': list(zip(main.time_data,
                               [self.to_current_unit(v) for v in main.voltage_data])),
            'params': (
                f"采样方式={'ADS1115 16位' if self.ads1115_mode else ('HX711 24位' if self.hx711_mode else f'ESP32 内置 ADC {self.adc_bits}位')}, "
                f"参考电压=3.3V, 分压比={self.divider_ratio}, 放大倍数={self.amp_ratio}, "
                f"ADC端满量程=±{fs:.6g}V, 实际量程=±{actual:.6g}V, "
                f"理论分辨率={res:.3g}V/计数, "
                f"ADS1115 PGA={self.ads1115_pga}/通道={self.ads1115_channel}, "
                f"HX711 AVDD={self.hx711_avdd}V/通道={self.hx711_channel}"
                f"(增益{128 if self.hx711_channel == 'A' else 32}), "
                f"多路连接: 共{len(active)}路（{channels_desc}），"
                f"主分析通道={main.name}, 各路零点独立, "
                f"显示单位={self.current_unit}, 采样间隔={self.sample_interval_ms}ms"),
            'system_prompt': AI_SYSTEM_PROMPT,
        }

    def api_snapshot(self):
        """当前实验数据快照（供 core.DataService 任意线程读取）。
        禁止调用任何 Qt 方法：只读模块自身的 Python 数据。"""
        d = self._ai_data() or {}
        points = list(d.get('points') or [])
        latest = None
        main = max((ch for ch in self.channels if ch.voltage_data),
                   key=lambda c: len(c.voltage_data), default=None)
        if main is not None:
            latest = {'t': main.time_data[-1],
                      'y': self.to_current_unit(main.voltage_data[-1]),
                      'raw': main.raw_data[-1] if main.raw_data else None}
        return {
            'key': 'voltage_sensor',
            'name': '电压传感器',
            'connected': any(ch.thread is not None for ch in self.channels),
            'collecting': self._collecting,
            'x_label': d.get('x_label', '时间 (秒)'),
            'y_label': d.get('y_label', '电压 (V)'),
            'params': d.get('params', {}),
            'points': points,
            'latest': latest,
            # 多路连接明细（points 仍为主通道序列，前端单曲线不破）
            'channels': [
                {'name': ch.name, 'color': ch.color,
                 'connected': ch.thread is not None,
                 'points_n': len(ch.voltage_data),
                 'tare_active': ch.tare_active,
                 'latest_raw': ch.raw_data[-1] if ch.raw_data else None}
                for ch in self.channels
            ],
        }

    def showEvent(self, e):
        """首次显示后按子卡真实高度收敛连接控制卡（构建期 height() 不可靠）。"""
        super().showEvent(e)
        self._sync_conn_card_height()

    def apply_theme(self, theme):
        """主题切换：刷新本模块内所有与主题相关的硬编码样式。"""
        apply_module_theme(self, theme)
        try:
            from qfluentwidgets import isDarkTheme
            self.chart.apply_chart_theme(isDarkTheme())
        except Exception:
            pass
