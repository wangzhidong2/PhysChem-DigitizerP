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

import os
import importlib.util
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from qfluentwidgets import (
    PushButton, ComboBox, TitleLabel,
    BodyLabel, DoubleSpinBox, SwitchButton, FluentIcon as FIF,
    FlowLayout,
)
import numpy as np

# 从公共模块导入共享代码
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core import (
    get_logger,
    EVENT_SAMPLE_PREVIEW,
    EVENT_SAMPLE_RECORDED,
    EVENT_CHANNEL_STATE,
    EVENT_COLLECTION_CHANGED,
    EVENT_CHANNELS_CHANGED,
    EVENT_ERROR,
)
from core_ui import (
    sync_kernel_channels,
    fluent_message_box,
    ChannelPanelMixin,
    FlowFixedWidth,
    card_style,
    FluentCard,
    scroll_area_style,
    page_bg_style,
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

# 颜色下拉中「自定义…」项的 userData 标记（选中后弹 Fluent 取色对话框）








class VoltageSensorWidget(ChannelPanelMixin, QWidget):
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
        self._build_conn_card(
            layout,
            "增加一路 ESP32 连接：\n"
            "每路可单独选择「有线串口 / 模拟器」，单独连接/断开，\n"
            "单独换曲线颜色；多路数据叠加画在同一张图上")

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
        params_row.addWidget(FlowFixedWidth(self.divider_spin, 136))

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
        params_row.addWidget(FlowFixedWidth(self.amp_spin, 136))

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
        # 原生 Fluent 按钮外观，不设 QSS（随主题白底黑字 / 深底白字）
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
        self._build_data_card()
        layout.addWidget(self.card_data)

        # 隐藏摘要标签：**不加入可见布局**——多路时单一汇总位会被各路
        # 数据轮流抢占（用户实测反馈），可见区只保留每路一行的实时明细。
        # 它的唯一职责是全屏浮动面板折叠态摘要（FloatingDataPanel 依赖
        # .text() 读文本，不 reparent 不要求可见），内容 = 最新活动一路。
        self.current_voltage_label = BodyLabel("--.- V")
        self.current_voltage_label.setFont(QFont("Cascadia Code", 14, QFont.Weight.Bold))
        self.current_voltage_label.setStyleSheet("color: #0078d4;")
        self.current_voltage_label.setParent(self)
        self.current_voltage_label.hide()

        # ========== 卡片4：图表 + 数据记录（可折叠） ==========
        self._build_chart_card(layout, "电压-时间曲线", self.current_voltage_label)

        # ========== 卡片5：操作按钮（可折叠） ==========
        self._build_action_card(layout)
        self._finish_page(layout, scroll, content, main_layout)

    # ---- ADC 参数按路独立：当前选中路辅助 ----
    ADC_BITS_INDEX = {8: 0, 10: 1, 12: 2, 14: 3, 16: 4, 18: 5, 20: 6, 22: 7, 24: 8}


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
        self.kernel.notify_change()
        self.update_range_display()

    def on_divider_changed(self, value):
        self._write_adc_param('divider_ratio', value)
        self.kernel.notify_change()
        self.update_range_display()

    def on_amp_changed(self, value):
        self._write_adc_param('amp_ratio', value)
        self.kernel.notify_change()
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
        self.kernel.notify_change()
        self.update_range_display()

    def on_hx711_avdd_changed(self, value):
        self._write_adc_param('hx711_avdd', value)
        self.kernel.notify_change()
        self.update_range_display()

    def on_hx711_channel_changed(self, index):
        self._write_adc_param('hx711_channel', 'B' if index == 0 else 'A')
        self.kernel.notify_change()
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
        self.kernel.notify_change()
        self.update_range_display()

    def on_ads1115_pga_changed(self, index):
        """切换 ADS1115 PGA 量程"""
        self._write_adc_param('ads1115_pga', self.ads1115_pga_combo.itemText(index))
        self.kernel.notify_change()
        self.update_range_display()

    def on_ads1115_channel_changed(self, index):
        """切换 ADS1115 输入通道（MUX）"""
        self._write_adc_param('ads1115_channel', self.ads1115_channel_combo.itemText(index))
        self.kernel.notify_change()
        self.update_range_display()

    def on_unit_changed(self, index):
        """切换显示单位：kV / V / mV。内部数据不变，仅刷新显示"""
        unit_map = {0: 'kV', 1: 'V', 2: 'mV'}
        self.current_unit = unit_map.get(index, 'V')
        self.kernel.notify_change()
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








    def _refresh_summary_text(self):
        """隐藏摘要标签取「最近一路有数据的通道」最新值（供全屏折叠摘要）。"""
        for ch in reversed(self.channels):
            if ch.voltage_data:
                self.current_voltage_label.setText(
                    f"{ch.name}: {self.format_voltage(ch.voltage_data[-1])} {self.current_unit}")
                return
        self.current_voltage_label.setText(f"--.- {self.current_unit}")


























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
                   label=f'{ch.name} ({self.current_unit})',
                   series_id=str(ch.id))
            all_t.extend(ch.time_data)
        c.set_labels('时间 (秒)', f'电压 ({self.current_unit})')
        c.set_title('电压传感器实时数据（多路对比）' if len(active) > 1
                    else '电压传感器实时数据')
        c.legend()
        if len(all_t) > 1:
            c.set_xlim(min(all_t), max(all_t))
        c.end()




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







    # ---------------- 公共多通道层的模块差异钩子 ----------------
    def _channel_extra_params(self):
        return {'adc_params': self.kernel.adc_param_source(
            self._active_channel_obj())}

    def _live_row_spec(self, ch):
        unit = self.current_unit
        return {
            'big_key': 'voltage_label',
            'big_text': f"--.- {unit}",
            'secondary': [
                ('raw_label', f"{ch.name} ADC: ------"),
                ('vadc_label', "ADC端电压: --.- V"),
            ],
        }

    def _sync_active_channel_controls(self, ch):
        self._sync_adc_controls(ch)

    def _after_channels_built(self):
        self.update_tare_status_label()

    def _on_channel_connection_changed(self, ch, connected):
        self.tare_btn.setEnabled(self.kernel.connected_any())
        live = self._live_rows.get(ch.id)
        if not live:
            return
        unit = self.current_unit
        live['voltage_label'].setText(f"--.- {unit}")
        live['vadc_label'].setText(f"ADC端电压: --.- {unit}")
        if connected:
            live['raw_label'].setText(f"{ch.name}: 连接中...")
        else:
            live['raw_label'].setText(f"{ch.name} ADC: 已断开")

    def _on_connection_state_changed(self):
        self.tare_btn.setEnabled(self.kernel.connected_any())
