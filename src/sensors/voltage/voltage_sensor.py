# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

# === MODULE META ===
# key: voltage_sensor
# icon: V
# name: 电压传感器
# category: physics
# class: VoltageSensorWidget
# kernel: _kernel_voltage:VoltageKernel
# ===================

# -*- coding: utf-8 -*-
"""电压传感器模块 — ADC 电压采集与分压电路换算，支持 ESP32 ADC 与 HX711 24位模式"""

import sys
import os
import importlib.util
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter, QColor
from qfluentwidgets import (
    PushButton, PrimaryPushButton, ComboBox, TextEdit, TitleLabel,
    BodyLabel, CaptionLabel, DoubleSpinBox, SwitchButton, FluentIcon as FIF,
    AdaptiveFlowLayout, FlowLayout, LineEdit, ToolButton, CheckBox,
)
from qfluentwidgets.components.dialog_box import ColorDialog
import numpy as np

# 从公共模块导入共享代码
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core import (
    get_logger,
    SERIAL_AVAILABLE,
    list_serial_ports,
    serial_unavailable_hint,
    EVENT_SAMPLE_PREVIEW,
    EVENT_SAMPLE_RECORDED,
    EVENT_CHANNEL_STATE,
    EVENT_COLLECTION_CHANGED,
    EVENT_CHANNELS_CHANGED,
    EVENT_ERROR,
)
from core_ui import (
    sync_kernel_channel_row,
    sync_kernel_channels,
    fluent_message_box,
    ChartPanel,
    SampleRateComboBox,
    card_style,
    primary_btn_style,
    accent_btn_style,
    modern_combo_style,
    CollapsibleCard,
    FluentCard,
    ExpandableTextEdit,
    scroll_area_style,
    page_bg_style,
    apply_module_theme,
    update_collect_btn,
    set_action_button_width,
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

# 颜色下拉中「自定义…」项的 userData 标记（选中后弹 Fluent 取色对话框）
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


class _FlowFixedWidth(QWidget):
    """FlowLayout 按控件 sizeHint() 排版，setFixedWidth 不会改变排版宽度。

    该容器把内部控件宽度锁定为 width，并让 sizeHint 返回这个宽度，
    使 FlowLayout 按紧凑宽度排列（参数行数字框用）。
    """

    def __init__(self, inner, width, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(inner)
        self._width = int(width)

    def sizeHint(self):
        return QSize(self._width, super().sizeHint().height())


class _FlowWrapBox(QWidget):
    """承载 FlowLayout 的容器：按可用宽度返回换行后的真实高度。

    FlowLayout.sizeHint() 只返回「单项最大尺寸」，不含换行后的总高度；
    QWidget 默认的 heightForWidth 也不会委托给布局。因此首次显示时父布局
    按过小的高度分配，勾选行被压扁（折叠再展开才恢复）。这里显式实现
    heightForWidth，让父布局按实际宽度算高度。
    """

    def __init__(self, flow, parent=None):
        super().__init__(parent)
        self._flow = flow
        self.setLayout(flow)
        sp = self.sizePolicy()
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        if width <= 0:
            width = 600
        return self._flow.heightForWidth(width)

    def sizeHint(self):
        width = self.width() if self.width() > 0 else 600
        return QSize(self._flow.sizeHint().width(), self.heightForWidth(width))

    def minimumSizeHint(self):
        m = self._flow.minimumSize()
        return QSize(m.width(), m.height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # 宽度变化会改变换行行数，需让父布局重新按 heightForWidth 分配
        self.updateGeometry()


class VoltageSensorWidget(QWidget):
    """电压传感器模块界面 - 支持ADC位数选择和电压分压放大比"""

    def __init__(self, kernel=None):
        super().__init__()
        # 内核由加载器注入；直接实例化时用同目录 _kernel_voltage.py 兜底
        self.kernel = kernel or self._create_default_kernel()
        self.channels = self.kernel.channels
        self._collecting = False  # 当前是否在采集（合并开始/停止按钮状态）
        self._rows = {}           # channel.id -> 行控件引用 dict

        # 模块级镜像（用于 UI 初值；实际以各路参数为准）
        self.sample_interval_ms = self.kernel.sample_interval_ms
        self.adc_bits = self.kernel.adc_bits
        self.divider_ratio = self.kernel.divider_ratio
        self.amp_ratio = self.kernel.amp_ratio
        self.hx711_mode = self.kernel.hx711_mode
        self.hx711_avdd = self.kernel.hx711_avdd
        self.hx711_channel = self.kernel.hx711_channel
        self.ads1115_mode = self.kernel.ads1115_mode
        self.ads1115_pga = self.kernel.ads1115_pga
        self.ads1115_channel = self.kernel.ads1115_channel

        # 换算常量由内核统一维护（View 只用于量程/下拉展示）
        self.ADC_BITS_OPTIONS = self.kernel.ADC_BITS_OPTIONS
        self.ADS1115_PGA_RANGES = self.kernel.ADS1115_PGA_RANGES
        self.ADS1115_CHANNELS = self.kernel.ADS1115_CHANNELS
        self.VREF = self.kernel.VREF

        self.init_ui()
        # 按内核已有通道重建 UI 行（内核负责配置恢复）
        self._build_channels_from_kernel()

    @staticmethod
    def _create_default_kernel():
        """不经过 main.py 加载器时，直接加载同目录内核文件。"""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            '_kernel_voltage.py')
        spec = importlib.util.spec_from_file_location(
            '_sensor_kernel_voltage', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.VoltageKernel()

    @property
    def current_unit(self):
        """电压显示单位（kV / V / mV），由内核持有，配置字段名保持不变。"""
        return self.kernel.current_unit

    @current_unit.setter
    def current_unit(self, unit):
        self.kernel.current_unit = unit

    # ------------------------------------------------------------------
    # 配置 / 换算（委托内核）
    # ------------------------------------------------------------------
    def load_config(self):
        return self.kernel.config

    def save_config(self):
        return self.kernel.save_config()

    def _adc_param_source(self, channel=None):
        """取一路 ADC 参数字典（委托内核，View 只用于控件回显）。"""
        return self.kernel.adc_param_source(channel)

    def adc_to_vadc(self, adc_value, channel=None):
        return self.kernel.adc_to_vadc(adc_value, channel)

    def adc_to_voltage(self, adc_value, apply_tare=True, channel=None):
        return self.kernel.adc_to_voltage(
            adc_value, apply_tare=apply_tare, channel=channel)

    def to_current_unit(self, voltage_v):
        """伏特 → 当前单位（委托内核）"""
        return self.kernel.to_current_unit(voltage_v)

    def format_voltage(self, voltage_v):
        """格式化显示（委托内核）"""
        return self.kernel.format_voltage(voltage_v)

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

        # 通道子卡容器：每路连接一张子卡（独立模式/串口/颜色/采样频率/连接按钮）
        self.channels_container = QWidget()
        self.channels_layout = QVBoxLayout(self.channels_container)
        self.channels_layout.setContentsMargins(0, 0, 0, 0)
        self.channels_layout.setSpacing(8)
        card_layout.addWidget(self.channels_container)

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
        # 固定窄宽度：分压比最长 1000.00，无需默认的宽输入框，否则两个
        # 数字框占掉整行，把后面的「显示单位/去皮」挤换行。FlowLayout 按
        # sizeHint 排版，故用 _FlowFixedWidth 容器锁定排版宽度
        self.divider_spin.setFixedWidth(136)
        self.divider_spin.setFixedHeight(36)
        self.divider_spin.setToolTip(params_hint_text)
        self.divider_spin.valueChanged.connect(self.on_divider_changed)
        params_row.addWidget(_FlowFixedWidth(self.divider_spin, 136))

        amp_label = BodyLabel("放大倍数:")
        amp_label.setToolTip(params_hint_text)
        params_row.addWidget(amp_label)
        self.amp_spin = DoubleSpinBox()
        self.amp_spin.setRange(0.01, 1000.0)
        self.amp_spin.setDecimals(2)
        self.amp_spin.setSingleStep(0.1)
        self.amp_spin.setValue(self.amp_ratio)
        self.amp_spin.setSuffix(" x")
        # 同上：固定窄宽度，避免与分压比一起把参数行撑爆导致换行
        self.amp_spin.setFixedWidth(136)
        self.amp_spin.setFixedHeight(36)
        self.amp_spin.setToolTip(params_hint_text)
        self.amp_spin.valueChanged.connect(self.on_amp_changed)
        params_row.addWidget(_FlowFixedWidth(self.amp_spin, 136))

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
        # 供 _reflow_adc_params 在文案变化后立即重排（FlowLayout 不会
        # 因子控件 sizeHint 变化自动重排）
        self.params_flow = params_row

        card_adc = FluentCard("ADC 与电路参数", card_adc_content, expanded=True, icon=FIF.SETTING)
        self.card_adc = card_adc
        # header 右侧：「当前连接」下拉——ADC 参数按路独立，切换后编辑所选路
        self._active_channel_combo = ComboBox()
        self._active_channel_combo.setMinimumWidth(110)
        self._active_channel_combo.setToolTip(
            "ADC 与电路参数按连接独立设置：\n切换后下方控件显示并编辑所选连接的参数")
        self._active_channel_combo.currentIndexChanged.connect(
            self._on_active_channel_changed)
        card_adc.add_header_widget(self._active_channel_combo)
        layout.addWidget(card_adc)

        # ========== 卡片3：实时数据（可折叠，每路一行同屏显示） ==========
        card_data_content = QWidget()
        card_data_content.setObjectName("card")
        card_data_content.setStyleSheet(card_style())
        data_card_layout = QVBoxLayout(card_data_content)
        data_card_layout.setContentsMargins(20, 4, 20, 16)
        data_card_layout.setSpacing(8)

        # 隐藏摘要标签：**不加入可见布局**——多路时单一汇总位会被各路
        # 数据轮流抢占（用户实测反馈），可见区只保留每路一行的实时明细。
        # 它的唯一职责是全屏浮动面板折叠态摘要（FloatingDataPanel 依赖
        # .text() 读文本，不 reparent 不要求可见），内容 = 最新活动一路。
        self.current_voltage_label = BodyLabel("--.- V")
        self.current_voltage_label.setFont(QFont("Cascadia Code", 14, QFont.Weight.Bold))
        self.current_voltage_label.setStyleSheet("color: #0078d4;")
        self.current_voltage_label.setParent(self)
        self.current_voltage_label.hide()

        # 每路一行实时明细（通道增删时动态重建，见 _build_live_row）
        self._live_rows = {}          # channel.id -> {row, voltage_label, raw_label, vadc_label}
        self._live_container = QWidget()
        self._live_layout = QVBoxLayout(self._live_container)
        self._live_layout.setContentsMargins(0, 0, 0, 0)
        self._live_layout.setSpacing(4)
        data_card_layout.addWidget(self._live_container)

        self.stats_label = CaptionLabel("暂无数据")
        data_card_layout.addWidget(self.stats_label)

        card_data = FluentCard("实时数据", card_data_content, expanded=True, icon=FIF.HISTORY)
        self.card_data = card_data
        layout.addWidget(card_data)

        # ========== 卡片4：图表 + 数据记录（可折叠） ==========
        card_chart_content = QWidget()
        card_chart_content.setObjectName("card")
        card_chart_content.setStyleSheet(card_style())
        chart_card_layout = QVBoxLayout(card_chart_content)
        chart_card_layout.setContentsMargins(20, 4, 20, 16)
        chart_card_layout.setSpacing(12)

        # 通道显示勾选行：勾选的通道画进图表，不勾选的隐藏
        # （只影响图表显示，采集/统计/保存不受影响；通道增删/改名时重建）
        self._visibility_flow = FlowLayout(isTight=True)
        self._visibility_flow.setHorizontalSpacing(14)
        self._visibility_flow.setVerticalSpacing(4)
        # 用按宽度算高度的容器，避免首次显示时被压扁（折叠展开后才正常）
        self._visibility_container = _FlowWrapBox(self._visibility_flow)
        chart_card_layout.addWidget(self._visibility_container)

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

        # 内核事件队列：后台采集线程只入队，GUI 线程由 QTimer 消费
        self._events = self.kernel.subscribe()
        self._event_timer = QTimer(self)
        self._event_timer.timeout.connect(self._drain_kernel_events)
        self._event_timer.start(50)

    # ---- ADC 参数按路独立：当前选中路辅助 ----
    ADC_BITS_INDEX = {8: 0, 10: 1, 12: 2, 14: 3, 16: 4, 18: 5, 20: 6, 22: 7, 24: 8}

    def _active_channel_obj(self):
        """ADC 参数卡当前选中的通道对象（无通道/未初始化返回 None）。"""
        combo = getattr(self, '_active_channel_combo', None)
        if combo is None:
            return None
        cid = combo.currentData()
        return next((ch for ch in self.channels if ch.id == cid), None)

    def _write_adc_param(self, attr, value):
        """把改动写入当前选中路；若为第 1 路同步内核模块级镜像字段。"""
        ch = self._active_channel_obj()
        if ch is None and self.channels:
            ch = self.channels[0]
        if ch is not None:
            setattr(ch, attr, value)
            if self.channels and ch is self.channels[0]:
                setattr(self.kernel, attr, value)
        else:
            setattr(self.kernel, attr, value)  # 无路时（初始化期）写全局默认

    def _refresh_active_channel_combo(self, keep_id=None):
        """通道增删/改名后重建「当前连接」下拉，尽量保住原选中。"""
        combo = getattr(self, '_active_channel_combo', None)
        if combo is None:
            return
        if keep_id is None and combo.count():
            keep_id = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for ch in self.channels:
            combo.addItem(ch.name, userData=ch.id)
        idx = next((i for i in range(combo.count())
                    if combo.itemData(i) == keep_id), 0)
        if combo.count():
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)
        # 选中项可能变了（删除了原选中通道）：同步一次控件显示
        self._sync_adc_controls(self._active_channel_obj())

    def _on_active_channel_changed(self, index):
        """「当前连接」切换：把控件值同步为所选路的参数。"""
        self._sync_adc_controls(self._active_channel_obj())

    def _sync_adc_controls(self, ch):
        """把 ADC 参数卡控件同步为通道 ch 的值（blockSignals 防递归）。"""
        if ch is None:
            return
        src = self._adc_param_source(ch)
        combo = self._active_channel_combo
        combo.blockSignals(True)
        idx = next((i for i in range(combo.count())
                    if combo.itemData(i) == ch.id), None)
        if idx is not None:
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)

        self.adc_bits_combo.blockSignals(True)
        self.adc_bits_combo.setCurrentIndex(
            self.ADC_BITS_INDEX.get(src['adc_bits'], 2))
        self.adc_bits_combo.blockSignals(False)

        self.hx711_check.blockSignals(True)
        self.hx711_check.setChecked(src['hx711_mode'])
        self.hx711_check.blockSignals(False)
        self.hx711_avdd_spin.blockSignals(True)
        self.hx711_avdd_spin.setValue(src['hx711_avdd'])
        self.hx711_avdd_spin.blockSignals(False)
        self.hx711_channel_combo.blockSignals(True)
        self.hx711_channel_combo.setCurrentIndex(
            0 if src['hx711_channel'] == 'B' else 1)
        self.hx711_channel_combo.blockSignals(False)

        self.ads1115_check.blockSignals(True)
        self.ads1115_check.setChecked(src['ads1115_mode'])
        self.ads1115_check.blockSignals(False)
        self.ads1115_pga_combo.blockSignals(True)
        self.ads1115_pga_combo.setCurrentText(src['ads1115_pga'])
        self.ads1115_pga_combo.blockSignals(False)
        self.ads1115_channel_combo.blockSignals(True)
        self.ads1115_channel_combo.setCurrentText(src['ads1115_channel'])
        self.ads1115_channel_combo.blockSignals(False)

        self.divider_spin.blockSignals(True)
        self.divider_spin.setValue(src['divider_ratio'])
        self.divider_spin.blockSignals(False)
        self.amp_spin.blockSignals(True)
        self.amp_spin.setValue(src['amp_ratio'])
        self.amp_spin.blockSignals(False)

        self._sync_adc_mode_panels(src)
        self.update_range_display()

    def _sync_adc_mode_panels(self, src):
        """按所选路的 ADC 位数同步 HX711 / ADS1115 面板可见与可用态。"""
        is_24 = src['adc_bits'] == 24
        is_16 = src['adc_bits'] == 16
        self.hx711_panel.setVisible(is_24)
        self.hx711_avdd_spin.setEnabled(src['hx711_mode'])
        self.hx711_channel_combo.setEnabled(src['hx711_mode'])
        self.ads1115_panel.setVisible(is_16)
        self.ads1115_pga_combo.setEnabled(src['ads1115_mode'])
        self.ads1115_channel_combo.setEnabled(src['ads1115_mode'])

    def on_adc_bits_changed(self, index):
        bits_map = {0: 8, 1: 10, 2: 12, 3: 14, 4: 16, 5: 18, 6: 20, 7: 22, 8: 24}
        ch = self._active_channel_obj()
        self._write_adc_param('adc_bits', bits_map.get(index, 12))
        # HX711 选项仅 24 位时显示；切到非 24 位时自动取消 HX711 模式
        src = self._adc_param_source(ch)
        if src['adc_bits'] != 24 and src['hx711_mode']:
            self.hx711_check.setChecked(False)   # 触发 on_hx711_mode_changed 写回
        # ADS1115 选项仅 16 位时显示；切到非 16 位时自动取消 ADS1115 模式
        if src['adc_bits'] != 16 and src['ads1115_mode']:
            self.ads1115_check.setChecked(False)
        self._sync_adc_mode_panels(self._adc_param_source(ch))
        self.save_config()
        self.update_range_display()

    def on_divider_changed(self, value):
        self._write_adc_param('divider_ratio', value)
        self.save_config()
        self.update_range_display()

    def on_amp_changed(self, value):
        self._write_adc_param('amp_ratio', value)
        self.save_config()
        self.update_range_display()

    def on_hx711_mode_changed(self, checked):
        """HX711 模式开关：启用后强制 ADC 位数=24，并切换至有符号换算"""
        ch = self._active_channel_obj()
        self._write_adc_param('hx711_mode', checked)
        self.hx711_avdd_spin.setEnabled(checked)
        self.hx711_channel_combo.setEnabled(checked)
        if checked:
            # 强制切到 24 位选项（触发 on_adc_bits_changed 写回当前路）
            self.adc_bits_combo.setCurrentIndex(8)
            self._write_adc_param('adc_bits', 24)
        self._sync_adc_mode_panels(self._adc_param_source(ch))
        self.save_config()
        self.update_range_display()

    def on_hx711_avdd_changed(self, value):
        self._write_adc_param('hx711_avdd', value)
        self.save_config()
        self.update_range_display()

    def on_hx711_channel_changed(self, index):
        self._write_adc_param('hx711_channel', 'B' if index == 0 else 'A')
        self.save_config()
        self.update_range_display()

    def on_ads1115_mode_changed(self, checked):
        """ADS1115 模式开关：启用后强制 ADC 位数=16"""
        ch = self._active_channel_obj()
        self._write_adc_param('ads1115_mode', checked)
        self.ads1115_pga_combo.setEnabled(checked)
        self.ads1115_channel_combo.setEnabled(checked)
        if checked:
            self.adc_bits_combo.setCurrentIndex(4)  # 16 位（触发 on_adc_bits_changed 写回）
        self._sync_adc_mode_panels(self._adc_param_source(ch))
        self.save_config()
        self.update_range_display()

    def on_ads1115_pga_changed(self, index):
        """切换 ADS1115 PGA 量程"""
        self._write_adc_param('ads1115_pga', self.ads1115_pga_combo.itemText(index))
        self.save_config()
        self.update_range_display()

    def on_ads1115_channel_changed(self, index):
        """切换 ADS1115 输入通道（MUX）"""
        self._write_adc_param('ads1115_channel', self.ads1115_channel_combo.itemText(index))
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
        # 单位切换后逐路刷新实时行（内部电压值不变，只换显示单位）
        for ch in self.channels:
            live = self._live_rows.get(ch.id)
            if not live:
                continue
            if ch.voltage_data:
                live['voltage_label'].setText(
                    f"{self.format_voltage(ch.voltage_data[-1])} {self.current_unit}")
            else:
                live['voltage_label'].setText(f"--.- {self.current_unit}")
        self._refresh_summary_text()

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
        self._reflow_adc_params()

    def tare_now(self):
        """去皮（零点计算、历史数据重算由内核完成，这里只刷新界面）。"""
        res = self.kernel.tare_now()
        if not res.get('ok'):
            fluent_message_box(self, "提示",
                               res.get('message', '还没有收到数据'))
            return
        self.update_tare_status_label()
        self._refresh_after_recompute()

    def _refresh_after_recompute(self):
        """去皮重算后刷新统计 / 图表 / 实时行 / 汇总标签。"""
        self.update_stats()
        self.update_chart()
        for ch in self.channels:
            live = self._live_rows.get(ch.id)
            if live and ch.voltage_data:
                live['voltage_label'].setText(
                    f"{self.format_voltage(ch.voltage_data[-1])} {self.current_unit}")
        self._refresh_summary_text()

    def api_actions(self):
        """本模块支持的控制动作（供 KernelRegistry / HTTP 层展示）。"""
        return self.kernel.actions()

    def api_command(self, action, params=None):
        """执行控制动作（由 KernelRegistry 直接调用内核）。"""
        res = self.kernel.command(action, params)
        if action == 'tare' and isinstance(res, dict) and res.get('ok'):
            self.update_tare_status_label()
            self._refresh_after_recompute()
        return res

    def update_range_display(self):
        """量程标签按「当前连接」下拉所选路的参数刷新。"""
        src = self._adc_param_source(self._active_channel_obj())
        if src['hx711_mode']:
            gain = 128 if src['hx711_channel'] == 'A' else 32
            fs = src['hx711_avdd'] / gain / 2  # 满量程差分电压 = ±0.5×(AVDD/Gain)
            self.range_label.setText(f"量程: ±{fs*1000:.1f}mV (HX711 通道{src['hx711_channel']}, Gain{gain})")
            actual_max = fs * src['divider_ratio'] / src['amp_ratio']
            self.actual_range_label.setText(f"实际量程: ±{actual_max*1000:.2f}mV")
        elif src['ads1115_mode']:
            fsr = self.ADS1115_PGA_RANGES.get(src['ads1115_pga'], 2.048)
            self.range_label.setText(f"量程: ±{fsr:.3f}V (ADS1115 PGA={src['ads1115_pga']}, 通道{src['ads1115_channel']})")
            actual_max = fsr * src['divider_ratio'] / src['amp_ratio']
            self.actual_range_label.setText(f"实际量程: ±{actual_max:.3f}V")
        else:
            max_adc = self.ADC_BITS_OPTIONS.get(src['adc_bits'], 4095)
            full = self.VREF
            self.range_label.setText(f"量程: -{full:.2f}V~+{full:.2f}V (ADC -{max_adc}~+{max_adc})")
            actual_full = full * src['divider_ratio'] / src['amp_ratio']
            self.actual_range_label.setText(f"实际量程: -{actual_full:.2f}V~+{actual_full:.2f}V")
        self._reflow_adc_params()

    def _reflow_adc_params(self):
        """ADC 参数行文案/面板显隐变化后立即重排，并重算卡片高度。

        - FlowLayout 不会因子标签文字变化（sizeHint 变化）自动重排，
          量程文案变长后会叠在一起；
        - FluentCard 高度是构造时按 body.sizeHint 固定的，ADS1115 /
          HX711 面板显隐后不重算就会被裁切，表现为要折叠再展开才正常。
        """
        flow = getattr(self, 'params_flow', None)
        if flow is not None:
            flow.invalidate()
            # 同 _refresh_chart_visibility_row：FlowLayout.activate() 不会
            # 重排子项，必须显式按当前几何 setGeometry
            geo = flow.geometry()
            if geo.width() > 0 and geo.height() > 0:
                flow.setGeometry(geo)
        card = getattr(self, 'card_adc', None)
        if card is not None:
            card.refresh_height()
            # 面板显示/隐藏引起的布局失效要到事件循环才结算：
            # 立即量到的高度可能仍是上一个状态（切回 12 位时会停在
            # 16 位的高度）。下一拍再量一次，保证能增也能缩。
            QTimer.singleShot(0, self._refresh_adc_card_height)

    def _refresh_adc_card_height(self):
        """事件循环结算布局后，再按真实内容高度收敛 ADC 卡高度。"""
        card = getattr(self, 'card_adc', None)
        if card is not None:
            card.refresh_height()

    # ============================================================
    # 多路连接管理：通道的增删 / 行控件 / 单路连接控制
    # ============================================================
    def _build_channels_from_kernel(self):
        """按内核已有通道重建 UI 行（内核负责配置恢复）。"""
        for ch in self.channels:
            self._build_channel_card(ch)
            self._build_live_row(ch)
        self._refresh_active_channel_combo()
        self._sync_adc_controls(self.channels[0] if self.channels else None)
        self._refresh_chart_visibility_row()
        self._update_delete_btns()
        self._sync_compat_aliases()
        self.update_tare_status_label()
        self._refresh_summary_text()

    def _make_channel(self, color=None, mode='serial', port='', name=None,
                      sample_interval_ms=None, adc_params=None):
        """创建内核通道，并为它建立对应的 UI 子卡/实时行。"""
        if adc_params is None:
            adc_params = self.kernel.adc_param_source(
                self._active_channel_obj())
        ch = self.kernel.add_channel(
            color=color, mode=mode, port=port, name=name,
            sample_interval_ms=sample_interval_ms, adc_params=adc_params)
        self._build_channel_card(ch)
        self._build_live_row(ch)
        self._refresh_chart_visibility_row()
        self._update_delete_btns()
        self._sync_conn_card_height()
        return ch

    def add_channel(self):
        """「新建连接」按钮：增加一路连接（默认有线串口，缺 pyserial 时为模拟器）。"""
        self._make_channel(mode='serial' if SERIAL_AVAILABLE else 'simulator')
        self._sync_compat_aliases()
        self._refresh_active_channel_combo()

    def _delete_channel(self, ch):
        """删除一路连接（正在连接的通道须先断开；至少保留一路）。"""
        if getattr(ch, 'connected', False):
            fluent_message_box(self, "提示", f"{ch.name} 正在连接，请先断开再删除")
            return
        refs = self._rows.pop(ch.id, None)
        if refs:
            self.channels_layout.removeWidget(refs['card'])
            refs['card'].deleteLater()
        self.kernel.remove_channel(ch.id)
        self._remove_live_row(ch)
        self._refresh_chart_visibility_row()
        self._update_delete_btns()
        self._sync_compat_aliases()
        self._refresh_active_channel_combo()
        self._sync_conn_card_height()

    def _build_live_row(self, ch):
        """为通道创建一行实时明细：名称+大字电压（通道色） | 原始ADC | ADC端电压。

        多路同屏各占一行，不再互相覆盖；顶部不再有共享汇总位。
        """
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(16)

        name_label = CaptionLabel(ch.name)
        h.addWidget(name_label)

        voltage_label = BodyLabel(f"--.- {self.current_unit}")
        voltage_label.setFont(QFont("Cascadia Code", 20, QFont.Weight.Bold))
        voltage_label.setStyleSheet(f"color: {ch.color};")
        h.addWidget(voltage_label)

        h.addStretch()

        raw_label = CaptionLabel(f"{ch.name} ADC: ------")
        raw_label.setFont(QFont("Cascadia Code", 11))
        h.addWidget(raw_label)

        vadc_label = CaptionLabel("ADC端电压: --.- V")
        vadc_label.setFont(QFont("Cascadia Code", 11))
        h.addWidget(vadc_label)

        self._live_layout.addWidget(row)
        self._live_rows[ch.id] = {
            'row': row, 'name_label': name_label, 'voltage_label': voltage_label,
            'raw_label': raw_label, 'vadc_label': vadc_label,
        }
        self._refresh_data_card_height()

    def _remove_live_row(self, ch):
        """删除通道的实时明细行（断开/删除通道时调用）。"""
        refs = self._live_rows.pop(ch.id, None)
        if refs:
            self._live_layout.removeWidget(refs['row'])
            refs['row'].deleteLater()
        # 该路被删后摘要标签可能指着它的旧值，刷成还有数据的最后一口
        self._refresh_summary_text()
        self._refresh_data_card_height()

    def _refresh_data_card_height(self):
        """实时数据卡行数变化后重算高度。

        FluentCard 高度只在构造时按 body.sizeHint 固定，新建连接增加
        实时明细行后不重算，后面的通道行会被裁掉（表现为只显示前两路）。
        """
        card = getattr(self, 'card_data', None)
        if card is not None:
            # 先激活实时行内层布局，否则外层 body 量到的仍是旧行数
            live = getattr(self, '_live_layout', None)
            if live is not None:
                live.invalidate()
                live.activate()
            card.refresh_height()
            # 新行加入布局要到下一拍才结算，再量一次才能包含全部行
            QTimer.singleShot(0, self._refresh_data_card_height_deferred)

    def _refresh_data_card_height_deferred(self):
        card = getattr(self, 'card_data', None)
        if card is not None:
            card.refresh_height()

    def _refresh_summary_text(self):
        """隐藏摘要标签取「最近一路有数据的通道」最新值（供全屏折叠摘要）。"""
        for ch in reversed(self.channels):
            if ch.voltage_data:
                self.current_voltage_label.setText(
                    f"{ch.name}: {self.format_voltage(ch.voltage_data[-1])} {self.current_unit}")
                return
        self.current_voltage_label.setText(f"--.- {self.current_unit}")

    def _refresh_chart_visibility_row(self):
        """重建图表卡顶部的通道显示勾选行（通道增删/改名后调用）。"""
        # 清旧行：qfluentwidgets FlowLayout.takeAt 返回控件本身
        # （非标准 QLayoutItem——源码 return self._items.pop(index).widget()），
        # 不能再对其调 .widget()；用 isinstance 兼容旧版本可能返回的 QLayoutItem
        while self._visibility_flow.count():
            item = self._visibility_flow.takeAt(0)
            w = item if isinstance(item, QWidget) else (item.widget() if item else None)
            if w is not None:
                w.hide()   # 先隐藏，避免 deleteLater 延迟销毁期间与新建勾选框重叠
                w.deleteLater()
        for ch in self.channels:
            cb = CheckBox(ch.name)
            cb.setChecked(ch.visible)
            cb.setToolTip(f"勾选后「{ch.name}」的曲线显示在图表上，取消则隐藏\n"
                          f"（仅影响图表显示，采集/统计/保存不受影响）")
            cb.toggled.connect(
                lambda on, c=ch: self._on_channel_visible_toggled(c, on))
            self._visibility_flow.addWidget(cb)
            # 新建控件默认不可见，而 FlowLayout(isTight) 的 _doLayout 会
            # 跳过不可见子项——不先 show() 就会漏排，停在 640x480 默认尺寸
            cb.show()
        self._visibility_container.setVisible(bool(self.channels))
        # FlowLayout 在子项增删后不会自行重排（尺寸未变时父布局也不会
        # 重新调用 setGeometry），新建的勾选框会停在 (0,0) 且保持
        # 640x480 默认尺寸，表现为「要折叠再展开才刷新」。
        # FlowLayout.activate() 实测无效（其 addItem 不触发 invalidate），
        # 必须显式 setGeometry，才会对所有子项重跑 _doLayout。
        self._visibility_flow.invalidate()
        self._visibility_flow.setGeometry(self._visibility_container.contentsRect())
        self._visibility_container.updateGeometry()

    def _on_channel_visible_toggled(self, ch, checked):
        """勾选/取消勾选：切换该路曲线显示并即时重绘。"""
        ch.visible = bool(checked)
        self.save_config()
        self.update_chart()

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
        """KernelRegistry / 网页端兼容：对外仍暴露单一 mode_combo/port_combo。

        core.KernelRegistry.connection_info / _apply_connection 依赖这两个属性
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
        body：连接方式 + 串口 + 刷新 + 连接按钮同一行（紧凑），
        采样频率独立一行；模拟器模式下串口部分隐藏。
        每路独立：模式选择、串口刷新、采样频率、连接/断开。
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
        delete_btn = ToolButton(FIF.DELETE, card)
        delete_btn.setFixedSize(28, 28)
        delete_btn.setToolTip("删除这一路连接（需先断开）")
        delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_btn.clicked.connect(lambda _=False, c=ch: self._delete_channel(c))
        card.add_header_widget(delete_btn)

        # ---- body 单行：连接方式 + 串口 + 刷新 + 采样频率 + 连接（紧凑） ----
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.addWidget(BodyLabel("连接方式"))
        mode_combo = ComboBox()
        mode_combo.addItems(["有线串口", "模拟器"])
        mode_combo.setCurrentIndex(1 if ch.mode == 'simulator' else 0)
        mode_combo.currentIndexChanged.connect(
            lambda i, c=ch: self._on_channel_mode_changed(c, i))
        row1.addWidget(mode_combo)

        port_combo = ComboBox()
        port_combo.setMinimumWidth(80)
        self._fill_channel_ports(ch, port_combo)
        port_combo.currentTextChanged.connect(lambda t, c=ch: setattr(c, 'port', t))
        port_label = BodyLabel("串口")
        row1.addWidget(port_label)
        row1.addWidget(port_combo)

        refresh_btn = PushButton("刷新")
        refresh_btn.setFixedHeight(30)
        refresh_btn.setToolTip("重新枚举本路的串口列表")
        refresh_btn.clicked.connect(
            lambda _=False, c=ch: self._refresh_channel_ports(c))
        row1.addWidget(refresh_btn)

        row1.addWidget(BodyLabel("采样频率"))
        sample_rate_combo = SampleRateComboBox()
        sample_rate_combo.setSampleInterval(ch.sample_interval_ms)
        sample_rate_combo.setMaximumWidth(110)
        sample_rate_combo.sampleIntervalChanged.connect(
            lambda ms, c=ch: self._on_channel_sample_interval_changed(c, ms))
        row1.addWidget(sample_rate_combo)

        row1.addStretch()

        connect_btn = PrimaryPushButton("连接")
        connect_btn.setFixedHeight(30)
        connect_btn.clicked.connect(
            lambda _=False, c=ch: self._toggle_channel_connection(c))
        row1.addWidget(connect_btn)
        w1 = QWidget()
        w1.setLayout(row1)
        card.add_widget(w1)

        # 子卡折叠动画期间逐帧同步主卡高度（子卡折叠后 sizeHint 不缩）
        card.expandAni.valueChanged.connect(self._sync_conn_card_height)
        card.expandAni.finished.connect(self._sync_conn_card_height)

        self.channels_layout.addWidget(card)
        self._rows[ch.id] = {
            'card': card, 'name_edit': name_edit, 'color_combo': color_combo,
            'delete_btn': delete_btn, 'mode_combo': mode_combo,
            'port_combo': port_combo, 'port_label': port_label,
            'refresh_btn': refresh_btn,
            'connect_btn': connect_btn, 'sample_rate_combo': sample_rate_combo,
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
        """颜色下拉选中：预设色直接生效；「自定义…」弹 Fluent 取色对话框。"""
        refs = self._rows.get(ch.id)
        if not refs:
            return
        combo = refs['color_combo']
        data = combo.itemData(index)
        if data == CUSTOM_COLOR_KEY:
            state = {'ok': False, 'color': None}
            dialog = ColorDialog(QColor(ch.color),
                                 f"选择 {ch.name} 的曲线颜色", self)
            dialog.colorChanged.connect(
                lambda c: state.__setitem__('color', c))
            dialog.yesButton.clicked.connect(
                lambda: state.__setitem__('ok', True))
            dialog.exec()
            color = state['color'] or getattr(dialog, 'color', None)
            if not (state['ok'] and color is not None and color.isValid()):
                self._init_channel_color_combo(ch)   # 取消：下拉回显当前色
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
                refs['card'].card.setTitle(ch.name)
            except Exception:
                pass
        live = self._live_rows.get(ch.id)
        if live:
            live['name_label'].setText(ch.name)
            live['raw_label'].setText(f"{ch.name} ADC: ------")
        self._refresh_active_channel_combo()
        self._refresh_chart_visibility_row()
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
        """模拟器模式下隐藏本路的串口标签/下拉与刷新按钮。"""
        refs = self._rows.get(ch.id)
        if refs:
            is_sim = ch.mode == 'simulator'
            refs['port_label'].setVisible(not is_sim)
            refs['port_combo'].setVisible(not is_sim)
            refs['refresh_btn'].setVisible(not is_sim)
            try:
                refs['card']._adjustViewSize()
            except Exception:
                pass
            self._sync_conn_card_height()

    def _toggle_channel_connection(self, ch):
        """单路的连接/断开按钮：按本路连接状态切换。"""
        if getattr(ch, 'connected', False):
            self._disconnect_channel(ch)
        else:
            self._connect_channel(ch)

    def _connect_channel(self, ch):
        """连接单路：串口或模拟器（其余通道不受影响）。"""
        refs = self._rows.get(ch.id)
        if ch.mode == 'serial':
            if not SERIAL_AVAILABLE:
                fluent_message_box(self, "提示", serial_unavailable_hint())
                return
            port = refs['port_combo'].currentText() if refs else ch.port
            if not port or "未安装" in port or "无可用" in port:
                fluent_message_box(self, "错误", f"{ch.name}: 请选择串口")
                return
            ch.port = port
        res = self.kernel.connect(ch.id)
        if not res.get('ok'):
            fluent_message_box(self, "连接错误",
                               res.get('message', f'{ch.name} 连接失败'))
            return
        if refs:
            refs['connect_btn'].setText("断开")
        log.info("%s 已连接（%s）", ch.name,
                 '模拟器' if ch.mode == 'simulator' else ch.port)
        self._set_collect_enabled(True)
        self.tare_btn.setEnabled(True)   # 连接后即可去皮，不必先开始采集
        live = self._live_rows.get(ch.id)
        if live:
            live['voltage_label'].setText(f"--.- {self.current_unit}")
            live['raw_label'].setText(f"{ch.name}: 连接中...")
            live['vadc_label'].setText(f"ADC端电压: --.- {self.current_unit}")

    def _disconnect_channel(self, ch):
        """断开单路（其余通道不受影响）。"""
        self.kernel.disconnect(ch.id)
        refs = self._rows.get(ch.id)
        if refs:
            refs['connect_btn'].setText("连接")
        log.info("%s 已断开", ch.name)
        # 本路实时行复位，其余路的显示保留
        live = self._live_rows.get(ch.id)
        if live:
            live['voltage_label'].setText(f"--.- {self.current_unit}")
            live['raw_label'].setText(f"{ch.name} ADC: 已断开")
            live['vadc_label'].setText(f"ADC端电压: --.- {self.current_unit}")
        self._refresh_summary_text()
        if not self.kernel.connected_any():
            self._set_collect_enabled(False)
            self.tare_btn.setEnabled(False)

    def connect_device(self):
        """连接全部未连接的通道（网页端 set_connection connect=true 走这里）。"""
        self.kernel.connect_all()
        for ch in self.channels:
            refs = self._rows.get(ch.id)
            if refs:
                refs['connect_btn'].setText(
                    "断开" if getattr(ch, 'connected', False) else "连接")
        self._set_collect_enabled(self.kernel.connected_any())
        self.tare_btn.setEnabled(self.kernel.connected_any())

    def disconnect_all(self):
        """断开全部通道（退出清理 / 网页端命令也走这里）。"""
        self.kernel.disconnect_all()
        for ch in self.channels:
            refs = self._rows.get(ch.id)
            if refs:
                refs['connect_btn'].setText("连接")
        self._set_collect_enabled(False)
        self.tare_btn.setEnabled(False)

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
        """开始数据采集（数据清空与主机时间基准由内核负责）。"""
        self.kernel.start_collection()
        self._apply_started_ui()

    def _apply_started_ui(self):
        """采集已开始：清空上一轮显示并切到采集状态。"""
        self._collecting = True
        self.data_text.clear()
        log.info("开始采集（已连接 %d 路）",
                 sum(1 for ch in self.channels
                     if getattr(ch, 'connected', False)))
        self._refresh_collect_btn()
        self.save_btn.setEnabled(False)
        self.current_voltage_label.setText("电压: 采集中...")
        for ch in self.channels:
            live = self._live_rows.get(ch.id)
            if live:
                live['raw_label'].setText(f"{ch.name} ADC: 采集中...")

    def stop_collection(self):
        """停止数据采集。"""
        self.kernel.stop_collection()
        self._apply_stopped_ui()

    def _apply_stopped_ui(self):
        """采集已停止：刷新按钮与汇总标签。"""
        self._collecting = False
        self._refresh_collect_btn()
        total = sum(len(ch.voltage_data) for ch in self.channels)
        self.save_btn.setEnabled(total > 0)
        log.info("停止采集，共 %d 个数据点", total)
        if total > 0:
            # 汇总标签显示数据最多通道的均值
            main = max(self.channels, key=lambda c: len(c.voltage_data))
            if main.voltage_data:
                avg_v = np.mean(main.voltage_data)
                self.current_voltage_label.setText(
                    f"{main.name} 均值: {self.format_voltage(avg_v)} {self.current_unit}")

    # ------------------------------------------------------------------
    # 内核事件 → UI（QTimer 在 GUI 线程消费，避免后台线程直接碰 QWidget）
    # ------------------------------------------------------------------
    def _drain_kernel_events(self):
        for event in self._events.drain(200):
            if event is None:
                return
            self._handle_kernel_event(event)

    def _handle_kernel_event(self, event):
        kind = event.kind
        cid = event.channel_id
        data = event.data or {}
        ch = self.kernel.get_channel(cid) if cid is not None else None
        unit = self.current_unit

        if kind == EVENT_SAMPLE_PREVIEW and ch is not None:
            value = data.get('value')
            raw = data.get('raw')
            if value is None or raw is None:
                return
            v_adc = self.adc_to_vadc(raw, ch)
            live = self._live_rows.get(ch.id)
            if live:
                live['raw_label'].setText(f"{ch.name} ADC: {int(raw)}")
                live['voltage_label'].setText(
                    f"{self.format_voltage(value)} {unit}")
                live['vadc_label'].setText(
                    f"ADC端电压: {self.format_voltage(v_adc)} {unit}")
            # 隐藏摘要标签记最新活动的一路（仅供全屏浮动面板折叠态摘要读取）
            self.current_voltage_label.setText(
                f"{ch.name}: {self.format_voltage(value)} {unit}")
            return

        if kind == EVENT_SAMPLE_RECORDED and ch is not None:
            value = data.get('value')
            raw = data.get('raw')
            if value is None or raw is None:
                return
            v_adc = self.adc_to_vadc(raw, ch)
            time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            display_text = (
                f"{time_str} | {ch.name} | ADC: {int(raw)} | "
                f"ADC端: {self.format_voltage(v_adc)} {unit} | "
                f"实际电压: {self.format_voltage(value)} {unit}")
            self.data_text.append(display_text)
            self.data_text.verticalScrollBar().setValue(
                self.data_text.verticalScrollBar().maximum())
            self.update_stats()
            return

        if kind == EVENT_CHANNEL_STATE and ch is not None:
            connected = bool(data.get('connected'))
            refs = self._rows.get(ch.id)
            if refs:
                refs['connect_btn'].setText("断开" if connected else "连接")
            live = self._live_rows.get(ch.id)
            if live:
                if connected:
                    msg = data.get('message') or '连接中...'
                    live['voltage_label'].setText(f"--.- {unit}")
                    live['raw_label'].setText(f"{ch.name}: {msg}")
                    live['vadc_label'].setText(f"ADC端电压: --.- {unit}")
                else:
                    live['voltage_label'].setText(f"--.- {unit}")
                    live['raw_label'].setText(f"{ch.name} ADC: 已断开")
                    live['vadc_label'].setText(f"ADC端电压: --.- {unit}")
            self._refresh_summary_text()
            self._set_collect_enabled(self.kernel.connected_any())
            self.tare_btn.setEnabled(self.kernel.connected_any())
            return

        if kind == EVENT_COLLECTION_CHANGED:
            collecting = bool(data.get('collecting'))
            if collecting and not self._collecting:
                self._apply_started_ui()
            elif not collecting and self._collecting:
                self._apply_stopped_ui()
            return

        if kind == EVENT_CHANNELS_CHANGED:
            sync_kernel_channels(self)
            if data.get('cleared'):
                self._apply_cleared_ui()
            self.update_tare_status_label()
            self.update_stats()
            self.update_chart()
            return

        if kind == EVENT_ERROR and ch is not None:
            message = data.get('message', '')
            log.error("%s 设备错误: %s", ch.name, message)
            fluent_message_box(self, "串口错误", f"{ch.name}: {message}")
            return

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
        # 只画勾选显示的通道（图表卡顶部勾选行控制）；勾选不影响采集与统计
        active = [ch for ch in self.channels
                  if ch.voltage_data and ch.visible]
        if not active:
            # 有数据但全部取消勾选 → 清空图表；本来就没数据 → 保持原样
            if any(ch.voltage_data for ch in self.channels):
                self.chart.clear_chart()
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

    def _on_channel_sample_interval_changed(self, ch, interval_ms):
        """本路采样频率改变：更新该路间隔并保存配置（对该路过滤即时生效；
        模拟器线程按创建时间隔发数，重连后按新频率运行）。"""
        ch.sample_interval_ms = interval_ms
        if self.channels and ch is self.channels[0]:
            self.sample_interval_ms = interval_ms  # 顶层字段跟第 1 路（旧配置兼容）
        self.save_config()

    def save_data(self):
        """保存数据到文件（由内核生成 CSV）。"""
        total = sum(len(ch.voltage_data) for ch in self.channels)
        if total == 0:
            fluent_message_box(self, "警告", "没有数据可保存")
            return
        try:
            filename = self.kernel.export_csv()
            log.info("数据已保存到: %s（%d 点）", filename, total)
            fluent_message_box(self, "成功", f"数据已保存到: {filename}")
        except Exception as e:
            log.error("保存失败: %s", e)
            fluent_message_box(self, "错误", f"保存失败: {e}")

    def clear_data(self):
        """清除数据。"""
        self.kernel.clear_data()
        self._apply_cleared_ui()
        log.info("已清除数据")

    def _apply_cleared_ui(self):
        """数据已清空：重置本模块的数据展示控件。"""
        # 内核 clear 不清采集状态；按钮跟随内核，避免显示与实际相反
        self._collecting = bool(getattr(self.kernel, 'collecting', False))
        self._refresh_collect_btn()
        self.data_text.clear()
        for ch in self.channels:
            live = self._live_rows.get(ch.id)
            if live:
                live['voltage_label'].setText(f"--.- {self.current_unit}")
                live['raw_label'].setText(f"{ch.name} ADC: ------")
                live['vadc_label'].setText(f"ADC端电压: --.- {self.current_unit}")
        self.current_voltage_label.setText(f"--.- {self.current_unit}")
        self.stats_label.setText("统计信息: 暂无数据")
        self.chart.clear_chart()
        self.save_btn.setEnabled(False)

    def _ai_data(self):
        """AI 分析实验数据回调（数据由内核生成，View 只补系统提示词）。"""
        data = self.kernel.ai_data()
        if not data:
            return None
        data = dict(data)
        data['system_prompt'] = AI_SYSTEM_PROMPT
        return data

    def api_snapshot(self):
        """当前实验数据快照（由内核生成，任意线程可读）。"""
        return self.kernel.snapshot()

    def api_csv(self):
        """HTTP 导出用 CSV（避免 KernelRegistry 回退到单通道快照拼接）。"""
        return self.kernel.csv_text()

    def shutdown(self):
        """退出清理：停止事件消费、关闭传输并关闭事件总线。"""
        try:
            self._event_timer.stop()
        except Exception:
            pass
        try:
            self._events.close()
        except Exception:
            pass
        self.kernel.shutdown()

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
