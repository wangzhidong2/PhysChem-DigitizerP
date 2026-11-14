# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

# === MODULE META ===
# key: current_sensor
# icon: A
# name: 电流传感器
# category: physics
# class: CurrentSensorWidget
# kernel: _kernel_current:CurrentKernel
# ===================

# -*- coding: utf-8 -*-
"""电流传感器模块 — ACS712 霍尔电流传感器，支持 5A/20A/30A 量程切换、AC/DC 测量与零点校准。

多路连接：每路独立选择串口/模拟器、独立 ACS712 换算参数与零点、独立采样频率，
多路数据以主机统一时间戳叠加画在同一张图上（架构与电压模块一致，
见 docs/multi-channel-design.md）。
"""

import os
import importlib.util
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from qfluentwidgets import (
    PushButton, ComboBox, TitleLabel,
    BodyLabel, SpinBox, DoubleSpinBox, FluentIcon as FIF,
)

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
    ChannelPanelMixin,
    sync_kernel_channels,
    fluent_message_box,
    card_style,
    FluentCard,
    scroll_area_style,
    page_bg_style,
)

log = get_logger("current_sensor")

# AI 分析实验：模块专属系统提示词（进入 AI 分析时随实验信息与数据发送给模型，
# 由 core.build_ai_system_prompt 组装进 system 消息）
AI_SYSTEM_PROMPT = (
    "你是一位资深物理实验指导教师与电学测量专家，正在协助分析 ACS712 霍尔电流"
    "传感器（5A/20A/30A 量程，DC/AC 模式）的实验数据。"
    "测量原理：ACS712 零电流输出约 VCC/2，灵敏度约 185/100/66 mV/A（对应 5A/20A/30A）；"
    "传感器输出经分压电路接入 ADC，电流 I =（V_sensor − 零点电压）÷ 灵敏度，其中 "
    "V_sensor = ADC 端电压 × 分压比；AC 模式取滚动窗口的电流 RMS。"
    "数据特征：直流回路电流应平稳，负载切换呈台阶；交流电流呈周期波动，RMS 应与"
    "有效值一致；电机、开关电源类负载会出现尖峰与纹波；ADC 位数与分压比共同决定"
    "可分辨的最小电流变化。多路连接时各路传感器参数（量程/零点/分压比）互相独立。"
    "常见误差来源：零点漂移与温漂、电源纹波、分压电阻误差、导线磁场干扰、量程选择"
    "不当（小电流用大量程会明显降低分辨率）、未做零点校准、AC 窗口过短导致 RMS 波动。"
    "分析要求：①结合量程、灵敏度与分压比估算电流分辨率，判断读数可信度与量程是否合适；"
    "②DC 数据：分析均值、漂移、噪声与功率变化趋势，识别负载台阶；③AC 数据：估算周期、"
    "峰值、RMS 与波形因数（峰值/RMS），判断是否接近正弦或含明显谐波；④给出零点/量程"
    "校准、滤波、抗干扰或更换量程的具体建议。"
)

# 多路连接的默认曲线配色（按新建顺序轮换取未用色，界面上可单独改色）

# 颜色下拉中「自定义…」项的 userData 标记（选中后弹 Fluent 取色对话框）






class CurrentSensorWidget(ChannelPanelMixin, QWidget):
    """电流传感器模块界面 - ACS712 霍尔电流传感器

    ACS712 工作原理：
      - 供电 VCC（典型 5V），零电流时输出 = VCC/2（约 2.5V）
      - 输出电压随电流线性变化：Vout = VCC/2 + I * 灵敏度
      - 三种量程灵敏度：5A→185mV/A，20A→100mV/A，30A→66mV/A
      - 可测交直流；交流时取 RMS

    由于 ACS712 输出最高约 4.5V，超出 ESP32 ADC 的 3.3V 量程，
    通常在 ACS712 输出与 ESP32 ADC 之间加分压电路（分压比≈5/3.3≈1.515）。
    """

    def __init__(self, kernel=None):
        super().__init__()
        # 内核由加载器注入；直接实例化时用同目录 _kernel_current.py 兜底
        self.kernel = kernel or self._create_default_kernel()
        self.channels = self.kernel.channels
        self._collecting = False  # 当前是否在采集（合并开始/停止按钮状态）
        self._rows = {}              # channel.id -> 行控件引用 dict
        self.sample_interval_ms = self.kernel.sample_interval_ms

        # 模块级共享设置镜像（真正读写在内核）
        self.current_mode = self.kernel.current_mode
        self.current_unit = self.kernel.current_unit
        self.ac_rms_window = self.kernel.ac_rms_window

        self.init_ui()
        # 内核已恢复通道列表（含模式/串口/颜色/换算参数/零点）
        self._build_channels_from_kernel()

    @staticmethod
    def _create_default_kernel():
        """不经过 main.py 加载器时，直接加载同目录内核文件。"""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            '_kernel_current.py')
        spec = importlib.util.spec_from_file_location(
            '_sensor_kernel_current', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.CurrentKernel()

    # ------------------------------------------------------------------
    # 配置（委托内核）
    # ------------------------------------------------------------------


    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
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
        title = TitleLabel("电流")
        layout.addWidget(title)

        # ========== 卡片1：连接控制（可折叠，多路子卡布局） ==========
        self._build_conn_card(
            layout,
            "增加一路 ACS712 连接：\n"
            "每路可单独选择「有线串口 / 模拟器」，单独连接/断开，\n"
            "单独换曲线颜色与量程/零点参数；多路数据叠加画在同一张图上")

        # ========== 卡片2：ACS712 参数（可折叠，按连接独立） ==========
        card_acs_content = QWidget()
        card_acs_content.setObjectName("card")
        card_acs_content.setStyleSheet(card_style())
        acs_card_layout = QVBoxLayout(card_acs_content)
        acs_card_layout.setContentsMargins(20, 4, 20, 16)
        acs_card_layout.setSpacing(12)

        # 参数卡初始值取第 1 路（通道由内核恢复）
        src = self.kernel.adc_param_source(
            self.channels[0] if self.channels else None)

        # 量程选择
        range_row = QHBoxLayout()
        range_row.setSpacing(10)
        range_row.addWidget(BodyLabel("量程:"))
        self.range_combo = ComboBox()
        for key in ['5A', '20A', '30A']:
            self.range_combo.addItem(self.kernel.ACS712_RANGES[key]['desc'])
        range_idx = {'5A': 0, '20A': 1, '30A': 2}.get(src['acs_range'], 0)
        self.range_combo.setCurrentIndex(range_idx)
        self.range_combo.currentIndexChanged.connect(self.on_range_changed)
        range_row.addWidget(self.range_combo)

        range_row.addWidget(BodyLabel("测量类型:"))
        self.mode_type_combo = ComboBox()
        self.mode_type_combo.addItems(["直流 DC", "交流 AC"])
        self.mode_type_combo.setCurrentIndex(0 if self.current_mode == 'DC' else 1)
        self.mode_type_combo.currentIndexChanged.connect(self.on_current_mode_changed)
        range_row.addWidget(self.mode_type_combo)

        range_row.addWidget(BodyLabel("ADC 位数:"))
        self.adc_bits_combo = ComboBox()
        self.adc_bits_combo.addItems([
            "8 位 (0-255)",
            "10 位 (0-1023)",
            "12 位 (0-4095)  ESP32内置",
            "14 位 (0-16383)",
            "16 位 (0-65535)",
        ])
        bits_map = {0: 8, 1: 10, 2: 12, 3: 14, 4: 16}
        self.adc_bits_combo.setCurrentIndex({v: k for k, v in bits_map.items()}.get(src['adc_bits'], 2))
        self.adc_bits_combo.currentIndexChanged.connect(self.on_adc_bits_changed)
        range_row.addWidget(self.adc_bits_combo)
        range_row.addStretch()
        acs_card_layout.addLayout(range_row)

        # 供电电压 + 零点电压 + 分压比
        params_row = QHBoxLayout()
        params_row.setSpacing(10)

        # 供电/分压解释文字（原为常显灰色小字，现改为悬停 tooltip 显示）
        params_hint_text = ("ACS712 输出最高约 4.5V，超出 ESP32 ADC 的 3.3V 量程，需在输出与 ADC 之间加分压电路\n"
                            "分压比 ≈ 5/3.3 ≈ 1.515（将 5V 映射到 3.3V）；电流 = (Vout − 零点电压) / 灵敏度\n"
                            "以上参数按连接独立：用右上角「当前连接」下拉切换后编辑所选路")

        vcc_label = BodyLabel("供电 VCC:")
        vcc_label.setToolTip(params_hint_text)
        params_row.addWidget(vcc_label)
        self.vcc_spin = DoubleSpinBox()
        self.vcc_spin.setRange(4.5, 5.5)
        self.vcc_spin.setDecimals(2)
        self.vcc_spin.setSingleStep(0.1)
        self.vcc_spin.setValue(src['vcc'])
        self.vcc_spin.setSuffix(" V")
        self.vcc_spin.setMinimumWidth(90)
        self.vcc_spin.setFixedHeight(32)
        self.vcc_spin.setToolTip(params_hint_text)
        self.vcc_spin.valueChanged.connect(self.on_vcc_changed)
        params_row.addWidget(self.vcc_spin)

        vquies_label = BodyLabel("零点电压:")
        vquies_label.setToolTip(params_hint_text)
        params_row.addWidget(vquies_label)
        self.vquies_spin = DoubleSpinBox()
        self.vquies_spin.setRange(0.0, 5.5)
        self.vquies_spin.setDecimals(3)
        self.vquies_spin.setSingleStep(0.01)
        self.vquies_spin.setValue(src['v_quiescent'])
        self.vquies_spin.setSuffix(" V")
        self.vquies_spin.setToolTip("零电流时 ACS712 输出电压，理论值 = VCC/2\n"
                                    "实际传感器有偏差，建议用“零点校准”按钮自动获取\n"
                                    "（多路连接时显示当前所选路的零点，编辑写入该路）\n\n"
                                    + params_hint_text)
        self.vquies_spin.setMinimumWidth(100)
        self.vquies_spin.setFixedHeight(32)
        self.vquies_spin.valueChanged.connect(self.on_vquiescent_changed)
        params_row.addWidget(self.vquies_spin)

        params_row.addWidget(BodyLabel("分压比 (R1+R2)/R2:"))
        self.divider_spin = DoubleSpinBox()
        self.divider_spin.setRange(1.0, 10.0)
        self.divider_spin.setDecimals(3)
        self.divider_spin.setSingleStep(0.01)
        self.divider_spin.setValue(src['divider_ratio'])
        self.divider_spin.setSuffix(" x")
        self.divider_spin.setMinimumWidth(110)
        self.divider_spin.valueChanged.connect(self.on_divider_changed)
        params_row.addWidget(self.divider_spin)
        params_row.addStretch()
        acs_card_layout.addLayout(params_row)

        # 可测范围显示
        self.actual_range_label = BodyLabel()
        self.actual_range_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.actual_range_label.setStyleSheet("color: #1a1a1a;")
        acs_card_layout.addWidget(self.actual_range_label)

        # 显示单位 + 零点校准状态
        unit_row = QHBoxLayout()
        unit_row.setSpacing(10)
        unit_row.addWidget(BodyLabel("显示单位:"))
        self.unit_combo = ComboBox()
        self.unit_combo.addItems(["安培 (A)", "毫安 (mA)"])
        self.unit_combo.setCurrentIndex(0 if self.current_unit == 'A' else 1)
        self.unit_combo.currentIndexChanged.connect(self.on_unit_changed)
        unit_row.addWidget(self.unit_combo)

        unit_row.addWidget(BodyLabel("零点校准:"))
        self.zero_status_label = BodyLabel("未校准（零点=VCC/2）")
        self.zero_status_label.setStyleSheet("color: #888; font-weight: bold;")
        unit_row.addWidget(self.zero_status_label)

        # 去皮按钮放在设置区内（与零点状态同一行）：
        # 采集前即可反复点击归零，不依赖「开始采集」后的数据；
        # 多路连接时对有数据流入的通道分别校准（各路零点独立）
        self.zero_cal_btn = PushButton("去皮")
        self.zero_cal_btn.setFixedHeight(32)
        self.zero_cal_btn.setMinimumWidth(80)
        self.zero_cal_btn.setToolTip("以当前零电流读数作为零点（可反复点击重新归零）\n"
                                     "设备连接后即有实时数据，无需先开始采集\n"
                                     "多路连接时对有数据流入的通道分别校准（各路零点独立）")
        self.zero_cal_btn.setEnabled(False)   # 连接后由 _set_collect_enabled 打开
        self.zero_cal_btn.clicked.connect(self.tare_now)
        unit_row.addWidget(self.zero_cal_btn)

        unit_row.addStretch()
        acs_card_layout.addLayout(unit_row)

        # AC 模式 RMS 窗口设置（仅 AC 模式可用；对全部通道共用）
        ac_row = QHBoxLayout()
        ac_row.setSpacing(10)
        ac_row.addWidget(BodyLabel("AC RMS 窗口:"))
        self.ac_window_spin = SpinBox()
        self.ac_window_spin.setRange(5, 500)
        self.ac_window_spin.setValue(self.ac_rms_window)
        self.ac_window_spin.setSuffix(" 点")
        self.ac_window_spin.setToolTip("AC 模式下计算 RMS 的滚动窗口大小（采样点数，全部通道共用）")
        self.ac_window_spin.valueChanged.connect(self.on_ac_window_changed)
        self.ac_window_spin.setEnabled(self.current_mode == 'AC')
        ac_row.addWidget(self.ac_window_spin)
        ac_row.addStretch()
        acs_card_layout.addLayout(ac_row)

        card_acs = FluentCard("ACS712 参数", card_acs_content, expanded=True, icon=FIF.SETTING)
        self.card_acs = card_acs
        # header 右侧：「当前连接」下拉——ACS712 参数按路独立，切换后编辑所选路
        self._active_channel_combo = ComboBox()
        self._active_channel_combo.setMinimumWidth(110)
        self._active_channel_combo.setToolTip(
            "ACS712 参数按连接独立设置：\n切换后下方控件显示并编辑所选连接的参数")
        self._active_channel_combo.currentIndexChanged.connect(
            self._on_active_channel_changed)
        card_acs.add_header_widget(self._active_channel_combo)
        layout.addWidget(card_acs)

        # ========== 卡片3：实时数据（可折叠，每路一行同屏） ==========
        self._build_data_card()
        layout.addWidget(self.card_data)

        # 隐藏摘要标签：**不加入可见布局**——多路时单一汇总位会被各路
        # 数据轮流抢占，可见区只保留每路一行的实时明细。
        # 它的唯一职责是全屏浮动面板折叠态摘要（FloatingDataPanel 依赖
        # .text() 读文本，不 reparent 不要求可见），内容 = 最新活动一路。
        self.current_value_label = BodyLabel("--.- A")
        self.current_value_label.setFont(QFont("Cascadia Code", 14, QFont.Weight.Bold))
        self.current_value_label.setStyleSheet("color: #0078d4;")
        self.current_value_label.setParent(self)
        self.current_value_label.hide()

        # ========== 卡片4：图表 + 数据记录（可折叠） ==========
        self._build_chart_card(layout, "电流-时间曲线", self.current_value_label)

        # ========== 卡片5：操作按钮（可折叠） ==========
        self._build_action_card(layout)
        self.update_range_display()
        self._finish_page(layout, scroll, content, main_layout)

    # ------------------------------------------------------------------
    # 多路连接管理：通道的增删 / 行控件 / 单路连接控制
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # ACS712 参数按路独立：当前选中路辅助
    # ------------------------------------------------------------------
    ADC_BITS_INDEX = {8: 0, 10: 1, 12: 2, 14: 3, 16: 4}


    def _write_acs_param(self, attr, value):
        """把参数改动写入当前选中路（保存由内核负责）。"""
        ch = self._active_channel_obj()
        if ch is not None:
            setattr(ch, attr, value)


    def _on_active_channel_changed(self, index):
        """「当前连接」切换：把控件值同步为所选路的参数。"""
        self._sync_acs_controls(self._active_channel_obj())

    def _sync_acs_controls(self, ch):
        """把 ACS712 参数卡控件同步为通道 ch 的值（blockSignals 防递归）。"""
        if ch is None:
            return
        src = self.kernel.adc_param_source(ch)
        combo = self._active_channel_combo
        combo.blockSignals(True)
        idx = next((i for i in range(combo.count())
                    if combo.itemData(i) == ch.id), None)
        if idx is not None:
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)

        self.range_combo.blockSignals(True)
        self.range_combo.setCurrentIndex(
            {'5A': 0, '20A': 1, '30A': 2}.get(src['acs_range'], 0))
        self.range_combo.blockSignals(False)

        self.adc_bits_combo.blockSignals(True)
        self.adc_bits_combo.setCurrentIndex(
            self.ADC_BITS_INDEX.get(src['adc_bits'], 2))
        self.adc_bits_combo.blockSignals(False)

        self.vcc_spin.blockSignals(True)
        self.vcc_spin.setValue(src['vcc'])
        self.vcc_spin.blockSignals(False)
        self.vquies_spin.blockSignals(True)
        self.vquies_spin.setValue(src['v_quiescent'])
        self.vquies_spin.blockSignals(False)
        self.divider_spin.blockSignals(True)
        self.divider_spin.setValue(src['divider_ratio'])
        self.divider_spin.blockSignals(False)

        self.update_range_display()

    # ------------------------------------------------------------------
    # 参数变更槽函数
    # ------------------------------------------------------------------
    def on_range_changed(self, index):
        key_map = {0: '5A', 1: '20A', 2: '30A'}
        self._write_acs_param('acs_range', key_map.get(index, '5A'))
        self.kernel.notify_change()
        self.update_range_display()

    def on_current_mode_changed(self, index):
        self.kernel.set_mode('DC' if index == 0 else 'AC')
        self._sync_module_settings()
        self.update_stats()
        self.update_chart()
        self._refresh_live_values()
        self._refresh_summary_text()

    def on_adc_bits_changed(self, index):
        bits_map = {0: 8, 1: 10, 2: 12, 3: 14, 4: 16}
        self._write_acs_param('adc_bits', bits_map.get(index, 12))
        self.kernel.notify_change()
        self.update_range_display()

    def on_vcc_changed(self, value):
        ch = self._active_channel_obj()
        self._write_acs_param('vcc', value)
        # VCC 改变时，若该路未做零点校准则零点电压跟随 VCC/2
        if ch is not None and not ch.zero_cal_active:
            ch.v_quiescent = value / 2.0
            self.vquies_spin.blockSignals(True)
            self.vquies_spin.setValue(ch.v_quiescent)
            self.vquies_spin.blockSignals(False)
            self.update_zero_status_label()
        self.kernel.notify_change()
        self.update_range_display()

    def on_vquiescent_changed(self, value):
        # 手动改零点电压视为已校准（写入当前选中路）
        self._write_acs_param('v_quiescent', value)
        self._write_acs_param('zero_cal_active', True)
        self.update_zero_status_label()
        self.kernel.notify_change()

    def on_divider_changed(self, value):
        self._write_acs_param('divider_ratio', value)
        self.kernel.notify_change()
        self.update_range_display()

    def on_unit_changed(self, index):
        self.kernel.set_unit('A' if index == 0 else 'mA')
        self._sync_module_settings()
        self.update_stats()
        self.update_chart()
        self._refresh_live_values()
        self._refresh_summary_text()

    def on_ac_window_changed(self, value):
        self.kernel.set_rms_window(value)
        self._sync_module_settings()
        self.update_stats()
        self.update_chart()

    # ------------------------------------------------------------------
    # 零点校准（每路独立零点）
    # ------------------------------------------------------------------
    def update_zero_status_label(self):
        """零点校准状态标签：多路时逐路显示零点（各路独立）。"""
        actives = [ch for ch in self.channels if ch.zero_cal_active]
        if actives:
            text = "已校准 (" + "; ".join(
                f"{ch.name} {ch.v_quiescent:.3f}V" for ch in actives) + ")"
            self.zero_status_label.setText(text)
            self.zero_status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            first = self.channels[0] if self.channels else None
            vcc = first.vcc if first else 5.0
            self.zero_status_label.setText(f"未校准（零点=VCC/2={vcc/2.0:.3f}V）")
            self.zero_status_label.setStyleSheet("color: #888; font-weight: bold;")

    def tare_now(self):
        """去皮（零点校准）：委托内核按各路实时窗口计算零点并重算已采数据。"""
        res = self.kernel.tare_now()
        if not res.get('ok'):
            fluent_message_box(self, "提示", res.get('message', '去皮失败'))
            return
        # 零点电压输入框同步为当前选中路的新零点
        cur = self._active_channel_obj() or (self.channels[0] if self.channels else None)
        if cur is not None:
            self.vquies_spin.blockSignals(True)
            self.vquies_spin.setValue(cur.v_quiescent)
            self.vquies_spin.blockSignals(False)
        self.update_zero_status_label()
        self.update_stats()
        self.update_chart()
        self._refresh_live_values()
        self._refresh_summary_text()

    def _sync_module_settings(self):
        """把内核模块级设置（模式/单位/RMS 窗口）同步回界面控件。"""
        self.current_mode = self.kernel.current_mode
        self.current_unit = self.kernel.current_unit
        self.ac_rms_window = self.kernel.ac_rms_window
        combo = getattr(self, 'mode_type_combo', None)
        if combo is not None:
            combo.blockSignals(True)
            combo.setCurrentIndex(0 if self.current_mode == 'DC' else 1)
            combo.blockSignals(False)
        combo = getattr(self, 'unit_combo', None)
        if combo is not None:
            combo.blockSignals(True)
            combo.setCurrentIndex(0 if self.current_unit == 'A' else 1)
            combo.blockSignals(False)
        spin = getattr(self, 'ac_window_spin', None)
        if spin is not None:
            spin.blockSignals(True)
            spin.setValue(self.ac_rms_window)
            spin.blockSignals(False)
            spin.setEnabled(self.current_mode == 'AC')

    def _refresh_live_values(self):
        """按当前模式/单位刷新每路实时行的大字电流值。"""
        for ch in self.channels:
            live = self._live_rows.get(ch.id)
            if not live:
                continue
            if not ch.current_data:
                live['value_label'].setText(f"--.- {self.current_unit}")
                continue
            value = ch.current_data[-1]
            if self.current_mode == 'AC':
                rms = self.kernel.compute_ac_rms(ch)
                if rms is not None:
                    value = rms
            live['value_label'].setText(
                f"{self.kernel.format_current(value)} {self.current_unit}")

    def update_range_display(self):
        """可测范围标签按「当前连接」下拉所选路的参数刷新。"""
        lo, hi, max_adc, src = self.kernel.measurable_range(
            self._active_channel_obj())
        self.actual_range_label.setText(
            f"可测范围: {lo:.2f}A ~ {hi:.2f}A "
            f"(ADC {max_adc}, 分压 {src['divider_ratio']:.3f}x, 受 ADC 量程限制)"
        )

    # ============================================================
    # 多路连接管理：通道的增删 / 行控件 / 单路连接控制
    # ============================================================







    def _refresh_summary_text(self):
        """隐藏摘要标签取「最近一路有数据的通道」最新值（供全屏折叠摘要）。"""
        for ch in reversed(self.channels):
            if ch.current_data:
                self.current_value_label.setText(
                    f"{ch.name}: "
                    f"{self.kernel.format_current(ch.current_data[-1])} "
                    f"{self.current_unit}")
                return
        self.current_value_label.setText(f"--.- {self.current_unit}")






















    # ------------------------------------------------------------------
    # 采集控制
    # ------------------------------------------------------------------




    def _apply_started_ui(self):
        """采集已开始：清空上一轮显示并切到采集状态。"""
        self._collecting = True
        self.data_text.clear()
        log.info("开始采集（已连接 %d 路）",
                 sum(1 for ch in self.channels
                     if getattr(ch, 'connected', False)))
        self._refresh_collect_btn()
        self.save_btn.setEnabled(False)
        self.current_value_label.setText("电流: 采集中...")
        for ch in self.channels:
            live = self._live_rows.get(ch.id)
            if live:
                live['raw_label'].setText(f"{ch.name} ADC: 采集中...")


    def _apply_stopped_ui(self):
        """采集已停止：刷新按钮与汇总标签。"""
        self._collecting = False
        self._refresh_collect_btn()
        total = sum(len(ch.current_data) for ch in self.channels)
        self.save_btn.setEnabled(total > 0)
        log.info("停止采集，共 %d 个数据点", total)
        if total > 0:
            # 汇总标签显示数据最多通道的均值
            main = max(self.channels, key=lambda c: len(c.current_data))
            stats = self.kernel.channel_stats(main)
            if stats.get('count'):
                self.current_value_label.setText(
                    f"{main.name} 均值: "
                    f"{self.kernel.format_current(stats['mean'])} "
                    f"{self.current_unit}")

    # ------------------------------------------------------------------
    # 内核事件 → UI（QTimer 在 GUI 线程消费，避免后台线程直接碰 QWidget）
    # ------------------------------------------------------------------

    def _handle_kernel_event(self, event):
        kind = event.kind
        cid = event.channel_id
        data = event.data or {}
        ch = self.kernel.get_channel(cid) if cid is not None else None

        if kind == EVENT_SAMPLE_PREVIEW and ch is not None:
            raw = data.get('raw')
            value = data.get('value')
            if raw is None or value is None:
                return
            v_adc = self.kernel.adc_to_vadc(raw, channel=ch)
            v_sensor = self.kernel.adc_to_vsensor(raw, channel=ch)
            display = value
            if self.current_mode == 'AC':
                rms = self.kernel.compute_ac_rms(ch)
                if rms is not None:
                    display = rms
            live = self._live_rows.get(ch.id)
            if live:
                live['raw_label'].setText(f"{ch.name} ADC: {int(raw)}")
                live['vadc_label'].setText(f"ADC端电压: {v_adc:.4f} V")
                live['vsensor_label'].setText(f"传感器输出: {v_sensor:.4f} V")
                live['value_label'].setText(
                    f"{self.kernel.format_current(display)} "
                    f"{self.current_unit}")
            self.current_value_label.setText(
                f"{ch.name}: {self.kernel.format_current(value)} "
                f"{self.current_unit}")
            return

        if kind == EVENT_SAMPLE_RECORDED and ch is not None:
            raw = data.get('raw')
            value = data.get('value')
            if raw is None or value is None:
                return
            v_adc = self.kernel.adc_to_vadc(raw, channel=ch)
            v_sensor = self.kernel.adc_to_vsensor(raw, channel=ch)
            time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            self.data_text.append(
                f"{time_str} | {ch.name} | ADC: {int(raw)} | "
                f"ADC端: {v_adc:.4f}V | 传感器: {v_sensor:.4f}V | "
                f"电流: {self.kernel.format_current(value)} "
                f"{self.current_unit}")
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
                    live['value_label'].setText(f"--.- {self.current_unit}")
                    live['raw_label'].setText(f"{ch.name}: {msg}")
                    live['vadc_label'].setText("ADC端电压: --.- V")
                    live['vsensor_label'].setText("传感器输出: --.- V")
                else:
                    live['value_label'].setText(f"--.- {self.current_unit}")
                    live['raw_label'].setText(f"{ch.name} ADC: 已断开")
                    live['vadc_label'].setText("ADC端电压: --.- V")
                    live['vsensor_label'].setText("传感器输出: --.- V")
            self._refresh_summary_text()
            self._set_collect_enabled(self.kernel.connected_any())
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
            self._sync_module_settings()
            self.update_zero_status_label()
            self._refresh_live_values()
            self._refresh_summary_text()
            return

        if kind == EVENT_ERROR and ch is not None:
            message = data.get('message', '')
            log.error("%s 设备错误: %s", ch.name, message)
            fluent_message_box(self, "串口错误", f"{ch.name}: {message}")
            return

    def update_stats(self):
        """统计栏：每路有数据的通道各显示一行统计（点数/均值/极值/σ 或 RMS）。"""
        parts = []
        u = self.current_unit
        for ch in self.channels:
            stats = self.kernel.channel_stats(ch)
            if not stats.get('count'):
                continue
            if self.current_mode == 'AC':
                parts.append(
                    f"{ch.name}: 点数 {stats['count']} | "
                    f"RMS={self.kernel.format_current(stats['rms'])}{u} | "
                    f"峰值={self.kernel.format_current(stats['peak'])}{u}")
            else:
                parts.append(
                    f"{ch.name}: 点数 {stats['count']} | "
                    f"均={self.kernel.format_current(stats['mean'])}{u} | "
                    f"最大={self.kernel.format_current(stats['max'])}{u} | "
                    f"最小={self.kernel.format_current(stats['min'])}{u} | "
                    f"σ={self.kernel.format_current(stats['std'])}{u}")
        if parts:
            self.stats_label.setText("统计: " + " ‖ ".join(parts))

    def update_chart(self):
        if not self.isVisible():
            return  # 页面隐藏时跳过重绘（定时器不停止，避免白耗 UI 线程）
        # 只画勾选显示的通道（图表卡顶部勾选行控制）；勾选不影响采集与统计
        active = [ch for ch in self.channels
                  if ch.current_data and ch.visible]
        if not active:
            # 有数据但全部取消勾选 → 清空图表；本来就没数据 → 保持原样
            if any(ch.current_data for ch in self.channels):
                self.chart.clear_chart()
            return
        c = self.chart
        c.begin()
        all_t = []
        label = f'电流 ({self.current_unit})'
        # 每路一条曲线：颜色 = 各通道行色块上选的颜色，图例 = 通道名
        for ch in active:
            display_data = [self.kernel.to_current_unit(v) for v in ch.current_data]
            c.plot(ch.time_data, display_data, color=ch.color, width=2,
                   label=f'{ch.name} ({self.current_unit})',
                   series_id=str(ch.id))
            all_t.extend(ch.time_data)
        # AC 模式：单路可见时叠加该路 RMS 参考线（多路时各路 RMS 不同，不画）
        if self.current_mode == 'AC' and len(active) == 1 and \
                len(active[0].current_data) >= self.ac_rms_window:
            rms = self.kernel.compute_ac_rms(active[0])
            if rms is not None:
                rms_disp = self.kernel.to_current_unit(rms)
                c.hline(rms_disp, color='#fd7e14', style='dash', width=1.5,
                        label=f'RMS {self.kernel.format_current(rms)}'
                              f'{self.current_unit}')
                c.hline(-rms_disp, color='#fd7e14', style='dash', width=1.5)
        c.hline(0, color='#aaaaaa', style='dot', width=1)
        c.set_labels('时间 (秒)', label)
        c.set_title('电流传感器实时数据（多路对比）' if len(active) > 1
                    else '电流传感器实时数据')
        c.legend()
        if len(all_t) > 1:
            c.set_xlim(min(all_t), max(all_t))
        c.end()

    # ------------------------------------------------------------------
    # 采样频率 / 保存 / 清除
    # ------------------------------------------------------------------



    def _apply_cleared_ui(self):
        """数据已清空：重置本模块的数据展示控件。"""
        # 内核 clear 不清采集状态；按钮跟随内核，避免显示与实际相反
        self._collecting = bool(getattr(self.kernel, 'collecting', False))
        self._refresh_collect_btn()
        self.data_text.clear()
        for ch in self.channels:
            live = self._live_rows.get(ch.id)
            if live:
                live['value_label'].setText(f"--.- {self.current_unit}")
                live['raw_label'].setText(f"{ch.name} ADC: ------")
                live['vadc_label'].setText("ADC端电压: --.- V")
                live['vsensor_label'].setText("传感器输出: --.- V")
        self.current_value_label.setText(f"--.- {self.current_unit}")
        self.stats_label.setText("统计: 暂无数据")
        self.chart.clear_chart()
        self.save_btn.setEnabled(False)









    def _channel_extra_params(self):
        return {'acs_params': self.kernel.adc_param_source(
            self._active_channel_obj())}

    def _live_row_spec(self, ch):
        unit = self.current_unit
        return {'big_key': 'value_label', 'big_text': f'--.- {unit}',
                'secondary': [
                    ('raw_label', f'{ch.name} ADC: ------'),
                    ('vadc_label', 'ADC端电压: --.- V'),
                    ('vsensor_label', '传感器输出: --.- V'),
                ]}

    def _sync_active_channel_controls(self, ch):
        self._sync_acs_controls(ch)

    def _on_channel_connection_changed(self, ch, connected):
        self.zero_cal_btn.setEnabled(self.kernel.connected_any())
        live = self._live_rows.get(ch.id)
        if not live:
            return
        live['value_label'].setText(f'--.- {self.current_unit}')
        live['vadc_label'].setText('ADC端电压: --.- V')
        live['vsensor_label'].setText('传感器输出: --.- V')
        live['raw_label'].setText(
            f'{ch.name}: 连接中...' if connected else f'{ch.name} ADC: 已断开')

    def _on_connection_state_changed(self):
        self.zero_cal_btn.setEnabled(self.kernel.connected_any())
