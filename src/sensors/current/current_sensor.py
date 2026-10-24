# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

# === MODULE META ===
# icon: A
# name: 电流传感器
# category: physics
# class: CurrentSensorWidget
# ===================

# -*- coding: utf-8 -*-
"""电流传感器模块 — ACS712 霍尔电流传感器，支持 5A/20A/30A 量程切换、AC/DC 测量与零点校准。

多路连接：每路独立选择串口/模拟器、独立 ACS712 换算参数与零点、独立采样频率，
多路数据以主机统一时间戳叠加画在同一张图上（架构与电压模块一致，
见 docs/multi-channel-design.md）。
"""

import sys
import os
import time
from collections import deque
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter, QColor
from qfluentwidgets import (
    PushButton, PrimaryPushButton, ComboBox, TextEdit, TitleLabel,
    BodyLabel, CaptionLabel, SpinBox, DoubleSpinBox, FluentIcon as FIF,
    FlowLayout, LineEdit, ToolButton, CheckBox,
)
from qfluentwidgets.components.dialog_box import ColorDialog
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


class _Channel:
    """一路连接的数据模型（纯 Python 对象，不持有任何 Qt 控件）。

    每路连接独立选择「有线串口 / 模拟器」、独立串口、独立曲线颜色、
    独立 ACS712 换算参数与零点校准；数据按主机统一时间戳记录（见 handle_data）。
    UI 行控件引用由模块统一保管在 _rows[channel.id] 里。
    """

    def __init__(self, cid, name, color, mode='serial', port='',
                 sample_interval_ms=100, acs_params=None):
        self.id = cid                      # 稳定 id（信号绑定用，删除后不复用）
        self.name = name                    # 显示名（可自定义，留空回退默认名）
        self.default_name = name            # 默认名（通道N，创建时定序）
        self.color = color                  # 曲线颜色
        self.mode = mode                    # 'serial' | 'simulator'
        self.port = port                    # 串口模式下选中的端口
        self.thread = None                  # SerialThread / SimulatorThread
        self.sample_interval_ms = sample_interval_ms  # 本路采样间隔（每路独立）
        # 本路 ACS712 换算参数（每路独立；缺省继承模块级/全局默认）
        p = acs_params or {}
        self.acs_range = p.get('acs_range', '5A')
        self.vcc = p.get('vcc', 5.0)
        self.v_quiescent = p.get('v_quiescent', 2.5)
        self.divider_ratio = p.get('divider_ratio', 1.515)
        self.adc_bits = p.get('adc_bits', 12)
        self.zero_cal_active = p.get('zero_cal_active', False)
        self.visible = p.get('visible', True)   # 图表显示开关（勾选框控制）
        # 采集数据（内部电流单位：安培）
        self.time_data = []
        self.raw_data = []
        self.vsensor_data = []
        self.current_data = []
        # 去皮 / 实时显示用的滚动窗口（含未采集时的实时数据）
        self.live_window = deque(maxlen=10)
        # 上次记录样本的主机相对秒（采样间隔过滤，每路独立）
        self.last_sample_s = None


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
        self._collecting = False  # 当前是否在采集（合并开始/停止按钮状态）
        # 多路连接：每路一个 _Channel（独立模式/串口/颜色/换算参数/零点/数据）
        self.channels = []
        self._rows = {}              # channel.id -> 行控件引用 dict
        self._next_channel_id = 1   # 稳定 id 分配器（删除后不复用）
        self._next_channel_seq = 1  # 显示名序号（通道N）
        self._t0_mono = None        # 采集期主机统一时间基准（首个样本时刻）

        # 采样频率设置（毫秒）—— 模块级镜像字段（始终与第 1 路一致）
        self.sample_interval_ms = 100  # 默认 100ms (10Hz)

        # ACS712 参数（模块级镜像字段，始终与第 1 路一致；各路独立值在 _Channel 上）
        self.acs_range = '5A'
        self.vcc = 5.0              # ACS712 供电电压
        self.v_quiescent = 2.5      # 零电流输出电压（= VCC/2，可校准）
        self.divider_ratio = 1.515  # 分压比 (R1+R2)/R2，还原 ACS712 原始输出
        self.adc_bits = 12
        self.zero_cal_active = False
        # 模块级共享设置（对全部通道生效）
        self.current_mode = 'DC'    # DC / AC
        self.current_unit = 'A'     # A / mA
        # AC 模式 RMS 滚动窗口大小（采样点数）
        self.ac_rms_window = 50

        self.config = self.load_config()
        self.init_ui()
        # 恢复上次的通道列表（含模式/串口/颜色/换算参数/零点）；无记录时建一路默认通道
        self._restore_channels()

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
            self.zero_cal_active = config.get('zero_cal_active', False)
            self.current_mode = config.get('current_mode', 'DC')
            self.current_unit = config.get('current_unit', 'A')
            self.sample_interval_ms = config.get('sample_interval_ms', 100)
            self.ac_rms_window = config.get('ac_rms_window', 50)
        return config

    def save_config(self):
        first = self.channels[0] if self.channels else None
        config = {
            # 兼容旧版单通道上位机：顶层换算/采样/校准字段取第 1 路的值
            'acs_range': first.acs_range if first else self.acs_range,
            'vcc': first.vcc if first else self.vcc,
            'v_quiescent': first.v_quiescent if first else self.v_quiescent,
            'divider_ratio': first.divider_ratio if first else self.divider_ratio,
            'adc_bits': first.adc_bits if first else self.adc_bits,
            'zero_cal_active': first.zero_cal_active if first else self.zero_cal_active,
            'current_mode': self.current_mode,
            'current_unit': self.current_unit,
            'sample_interval_ms': first.sample_interval_ms if first else self.sample_interval_ms,
            'ac_rms_window': self.ac_rms_window,
            # 多路连接：每路的模式/串口/颜色/采样间隔/换算参数/图表显示
            'channels': [
                {'name': ch.name, 'mode': ch.mode, 'port': ch.port,
                 'color': ch.color, 'sample_interval_ms': ch.sample_interval_ms,
                 'acs_range': ch.acs_range, 'vcc': ch.vcc,
                 'v_quiescent': ch.v_quiescent,
                 'divider_ratio': ch.divider_ratio, 'adc_bits': ch.adc_bits,
                 'zero_cal_active': ch.zero_cal_active,
                 'visible': ch.visible}
                for ch in self.channels
            ],
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

    def _sensitivity_of(self, src):
        return self.ACS712_RANGES.get(src['acs_range'], self.ACS712_RANGES['5A'])['sensitivity']

    def _adc_param_source(self, channel=None):
        """取一路 ACS712 换算参数字典：显式通道 > 参数卡当前选中路 > 第 1 路 > 模块级。

        模块级字段（self.acs_range 等）始终与第 1 路保持镜像，
        供旧版单通道调用方与配置顶层字段使用。
        """
        ch = channel
        if ch is None:
            ch = self._active_channel_obj()
        if ch is None and self.channels:
            ch = self.channels[0]
        if ch is not None:
            return {'acs_range': ch.acs_range, 'vcc': ch.vcc,
                    'v_quiescent': ch.v_quiescent,
                    'divider_ratio': ch.divider_ratio, 'adc_bits': ch.adc_bits,
                    'zero_cal_active': ch.zero_cal_active}
        return {'acs_range': self.acs_range, 'vcc': self.vcc,
                'v_quiescent': self.v_quiescent,
                'divider_ratio': self.divider_ratio, 'adc_bits': self.adc_bits,
                'zero_cal_active': self.zero_cal_active}

    def adc_to_vadc(self, adc_value, channel=None):
        """ADC 输入端电压（ESP32 ADC 引脚处）。

        多路连接时传 channel：按该路自己的 ADC 位数换算。
        """
        src = self._adc_param_source(channel)
        max_adc = self.ADC_BITS_OPTIONS.get(src['adc_bits'], 4096) - 1
        return (adc_value / max_adc) * self.VREF

    def adc_to_vsensor(self, adc_value, channel=None):
        """还原 ACS712 输出电压（扣除分压电路影响）。

        多路连接时传 channel：按该路自己的分压比还原。
        """
        src = self._adc_param_source(channel)
        return self.adc_to_vadc(adc_value, channel) * src['divider_ratio']

    def adc_to_current(self, adc_value, channel=None):
        """ADC 原始值 → 电流（安培，瞬时值）。

        多路连接时传 channel：按该路自己的量程灵敏度与零点换算。
        """
        src = self._adc_param_source(channel)
        v_sensor = self.adc_to_vsensor(adc_value, channel)
        return (v_sensor - src['v_quiescent']) / self._sensitivity_of(src)

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
            "增加一路 ACS712 连接：\n"
            "每路可单独选择「有线串口 / 模拟器」，单独连接/断开，\n"
            "单独换曲线颜色与量程/零点参数；多路数据叠加画在同一张图上")
        self.add_channel_btn.clicked.connect(lambda: self.add_channel())
        self.card_conn.add_header_widget(self.add_channel_btn)
        # 主卡展开动画结束后按子卡实际高度收敛（子卡折叠后 sizeHint 不缩）
        self.card_conn.expandAni.finished.connect(self._sync_conn_card_height)
        layout.addWidget(self.card_conn)

        # ========== 卡片2：ACS712 参数（可折叠，按连接独立） ==========
        card_acs_content = QWidget()
        card_acs_content.setObjectName("card")
        card_acs_content.setStyleSheet(card_style())
        acs_card_layout = QVBoxLayout(card_acs_content)
        acs_card_layout.setContentsMargins(20, 4, 20, 16)
        acs_card_layout.setSpacing(12)

        # 量程选择
        range_row = QHBoxLayout()
        range_row.setSpacing(10)
        range_row.addWidget(BodyLabel("量程:"))
        self.range_combo = ComboBox()
        for key in ['5A', '20A', '30A']:
            self.range_combo.addItem(self.ACS712_RANGES[key]['desc'])
        range_idx = {'5A': 0, '20A': 1, '30A': 2}.get(self.acs_range, 0)
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
        self.adc_bits_combo.setCurrentIndex({v: k for k, v in bits_map.items()}.get(self.adc_bits, 2))
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
        self.vcc_spin.setValue(self.vcc)
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
        self.vquies_spin.setValue(self.v_quiescent)
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
        self.divider_spin.setValue(self.divider_ratio)
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
        self.zero_cal_btn.setStyleSheet("background-color: #fd7e14; color: white;")
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
        card_data_content = QWidget()
        card_data_content.setObjectName("card")
        card_data_content.setStyleSheet(card_style())
        data_card_layout = QVBoxLayout(card_data_content)
        data_card_layout.setContentsMargins(20, 4, 20, 16)
        data_card_layout.setSpacing(8)

        # 隐藏摘要标签：**不加入可见布局**——多路时单一汇总位会被各路
        # 数据轮流抢占，可见区只保留每路一行的实时明细。
        # 它的唯一职责是全屏浮动面板折叠态摘要（FloatingDataPanel 依赖
        # .text() 读文本，不 reparent 不要求可见），内容 = 最新活动一路。
        self.current_value_label = BodyLabel("--.- A")
        self.current_value_label.setFont(QFont("Cascadia Code", 14, QFont.Weight.Bold))
        self.current_value_label.setStyleSheet("color: #0078d4;")
        self.current_value_label.setParent(self)
        self.current_value_label.hide()

        # 每路一行实时明细（通道增删时动态重建，见 _build_live_row）
        self._live_rows = {}          # channel.id -> {row, name_label, value_label, raw_label, vadc_label, vsensor_label}
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
        card_chart = CollapsibleCard("电流-时间曲线", card_chart_content, expanded=True, fullscreen=True)
        # 图表卡片加高为原来的 2 倍（内容区最小 400px），页面滚动查看
        card_chart.set_chart_min_height(400)
        # 全屏时：数据记录区作为可拖动折叠浮动面板浮于图表上方，折叠时显示实时电流值
        # 全屏浮动栏：合并的开始/停止按钮（与操作按钮卡的 collect_btn 同步状态）
        self.float_collect_btn = PrimaryPushButton("开始采集")
        self.float_collect_btn.setFixedHeight(34)
        update_collect_btn(self.float_collect_btn, False)
        self.float_collect_btn.clicked.connect(self.toggle_collection)
        self.float_collect_btn.setEnabled(False)
        # 全屏时：数据记录 + 拟合分析面板浮于图表上方，浮动栏底部可控制开始/停止
        card_chart.set_fullscreen_overlay(
            self.data_text, self.current_value_label,
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

        self.update_range_display()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_chart)
        self.timer.start(100)

    # ------------------------------------------------------------------
    # ACS712 参数按路独立：当前选中路辅助
    # ------------------------------------------------------------------
    ADC_BITS_INDEX = {8: 0, 10: 1, 12: 2, 14: 3, 16: 4}

    def _active_channel_obj(self):
        """ACS712 参数卡当前选中的通道对象（无通道/未初始化返回 None）。"""
        combo = getattr(self, '_active_channel_combo', None)
        if combo is None:
            return None
        cid = combo.currentData()
        return next((ch for ch in self.channels if ch.id == cid), None)

    def _write_acs_param(self, attr, value):
        """把改动写入当前选中路；若为第 1 路同步模块级镜像字段。"""
        ch = self._active_channel_obj()
        if ch is not None:
            setattr(ch, attr, value)
            if self.channels and ch is self.channels[0]:
                setattr(self, attr, value)
        else:
            setattr(self, attr, value)  # 无路时（初始化期）写全局默认

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
        self._sync_acs_controls(self._active_channel_obj())

    def _on_active_channel_changed(self, index):
        """「当前连接」切换：把控件值同步为所选路的参数。"""
        self._sync_acs_controls(self._active_channel_obj())

    def _sync_acs_controls(self, ch):
        """把 ACS712 参数卡控件同步为通道 ch 的值（blockSignals 防递归）。"""
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
        self.save_config()
        self.update_range_display()

    def on_current_mode_changed(self, index):
        self.current_mode = 'DC' if index == 0 else 'AC'
        self.ac_window_spin.setEnabled(self.current_mode == 'AC')
        self.save_config()
        self.update_stats()
        self.update_chart()
        # 模式切换后逐路刷新实时行
        for ch in self.channels:
            live = self._live_rows.get(ch.id)
            if live and ch.current_data:
                live['value_label'].setText(
                    f"{self.format_current(ch.current_data[-1])} {self.current_unit}")
        self._refresh_summary_text()

    def on_adc_bits_changed(self, index):
        bits_map = {0: 8, 1: 10, 2: 12, 3: 14, 4: 16}
        self._write_acs_param('adc_bits', bits_map.get(index, 12))
        self.save_config()
        self.update_range_display()

    def on_vcc_changed(self, value):
        ch = self._active_channel_obj()
        self._write_acs_param('vcc', value)
        # VCC 改变时，若该路未做零点校准则零点电压跟随 VCC/2
        if ch is not None and not ch.zero_cal_active:
            ch.v_quiescent = value / 2.0
            if self.channels and ch is self.channels[0]:
                self.v_quiescent = ch.v_quiescent
            self.vquies_spin.blockSignals(True)
            self.vquies_spin.setValue(ch.v_quiescent)
            self.vquies_spin.blockSignals(False)
            self.update_zero_status_label()
        self.save_config()
        self.update_range_display()

    def on_vquiescent_changed(self, value):
        # 手动改零点电压视为已校准（写入当前选中路）
        self._write_acs_param('v_quiescent', value)
        self._write_acs_param('zero_cal_active', True)
        self.update_zero_status_label()
        self.save_config()

    def on_divider_changed(self, value):
        self._write_acs_param('divider_ratio', value)
        self.save_config()
        self.update_range_display()

    def on_unit_changed(self, index):
        self.current_unit = 'A' if index == 0 else 'mA'
        self.save_config()
        self.update_stats()
        self.update_chart()
        # 单位切换后逐路刷新实时行（内部电流值不变，只换显示单位）
        for ch in self.channels:
            live = self._live_rows.get(ch.id)
            if not live:
                continue
            if ch.current_data:
                live['value_label'].setText(
                    f"{self.format_current(ch.current_data[-1])} {self.current_unit}")
            else:
                live['value_label'].setText(f"--.- {self.current_unit}")
        self._refresh_summary_text()

    def on_ac_window_changed(self, value):
        self.ac_rms_window = value
        self.save_config()
        self.update_stats()

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
            vcc = first.vcc if first else self.vcc
            self.zero_status_label.setText(f"未校准（零点=VCC/2={vcc/2.0:.3f}V）")
            self.zero_status_label.setStyleSheet("color: #888; font-weight: bold;")

    def tare_now(self):
        """去皮（零点校准）：取最近若干个实时采样点的 ACS712 输出电压均值作为零点。

        与旧实现的区别（对齐电压传感器的去皮行为）：
        1. 不要求先「开始采集」——设备连着、有数据流入即可去皮
           （用各路 live_window 实时窗口，采集前后都在持续更新）；
        2. 可反复点击，每点一次都以当前读数重新归零，没有「取消去皮」；
        3. 零点按去皮前的传感器输出计算，重复去皮不会互相叠加；
        4. 多路连接时对**所有有数据流入的通道**分别校准，各路零点独立
           （不同 ACS712 的空载偏移不同）。
        """
        targets = [ch for ch in self.channels if ch.live_window]
        if not targets:
            fluent_message_box(self, "提示", "还没有收到数据，等数据流入后再去皮")
            return
        parts = []
        for ch in targets:
            # 取最近 10 个采样点的传感器输出电压（未扣零点）平均值作为新零点
            recent = [self.adc_to_vsensor(r, channel=ch) for r in ch.live_window]
            ch.v_quiescent = float(np.mean(recent))
            ch.zero_cal_active = True
            parts.append(f"{ch.name} 零点={ch.v_quiescent:.4f}V")
        log.info("去皮：%s", "; ".join(parts))
        # 零点电压输入框同步为当前选中路的新零点
        cur = self._active_channel_obj() or (self.channels[0] if self.channels else None)
        if cur is not None and cur in targets:
            self.vquies_spin.blockSignals(True)
            self.vquies_spin.setValue(cur.v_quiescent)
            self.vquies_spin.blockSignals(False)
        self.save_config()
        self.update_zero_status_label()
        # 按新零点重算已采集的数据，曲线同步归零
        self.recompute_current_data()

    def api_actions(self):
        """本模块支持的控制动作（供 DataService / HTTP 层展示）。"""
        return ['zero_cal']

    def api_command(self, action, params=None):
        """执行模块特有控制动作（由 DataService 保证在 GUI 线程调用）。
        通用动作（start/stop/clear/toggle）返回 None 交给通用动作表。"""
        if action == 'zero_cal':
            if not any(ch.live_window for ch in self.channels):
                return {'ok': False, 'message': '还没有收到数据，等数据流入后再去皮'}
            self.tare_now()
            offsets = "; ".join(f"{ch.name}={ch.v_quiescent:.4f}V"
                                for ch in self.channels if ch.zero_cal_active)
            return {'ok': True,
                    'message': f'已去皮（{offsets}）'}
        return None

    def recompute_current_data(self):
        """零点变化后，按各通道已有 raw_data 重算 current_data"""
        if not any(ch.raw_data for ch in self.channels):
            return
        for ch in self.channels:
            ch.vsensor_data = [self.adc_to_vsensor(r, channel=ch) for r in ch.raw_data]
            ch.current_data = [self.adc_to_current(r, channel=ch) for r in ch.raw_data]
        self.update_stats()
        self.update_chart()
        # 逐路刷新实时行 + 汇总标签（去皮后显示值归零）
        for ch in self.channels:
            live = self._live_rows.get(ch.id)
            if live and ch.current_data:
                live['value_label'].setText(
                    f"{self.format_current(ch.current_data[-1])} {self.current_unit}")
        self._refresh_summary_text()

    def update_range_display(self):
        """可测范围标签按「当前连接」下拉所选路的参数刷新。"""
        src = self._adc_param_source()
        sensitivity = self._sensitivity_of(src)
        max_adc = self.ADC_BITS_OPTIONS.get(src['adc_bits'], 4096) - 1
        v_sensor_max = self.VREF * src['divider_ratio']  # ADC 满量程对应的传感器输出
        i_pos = (v_sensor_max - src['v_quiescent']) / sensitivity
        i_neg = (0.0 - src['v_quiescent']) / sensitivity
        lo, hi = min(i_pos, i_neg), max(i_pos, i_neg)
        self.actual_range_label.setText(
            f"可测范围: {lo:.2f}A ~ {hi:.2f}A "
            f"(ADC {max_adc}, 分压 {src['divider_ratio']:.3f}x, 受 ADC 量程限制)"
        )

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
                    mode=mode, port=item.get('port', ''),
                    sample_interval_ms=item.get('sample_interval_ms'),
                    # 缺字段用模块级顶层值补齐（旧版多通道配置迁移）
                    acs_params={**self._adc_param_source(), **item})
        else:
            # 旧版单通道配置迁移：顶层采样间隔/换算字段作为第 1 路初值
            self._make_channel(mode='serial' if SERIAL_AVAILABLE else 'simulator')
        self._refresh_active_channel_combo()
        self._sync_acs_controls(self.channels[0] if self.channels else None)
        # 顶层镜像字段刷新为第 1 路实际值（旧版顶层配置可能滞后于各路参数）
        if self.channels:
            first = self.channels[0]
            self.acs_range = first.acs_range
            self.vcc = first.vcc
            self.v_quiescent = first.v_quiescent
            self.divider_ratio = first.divider_ratio
            self.adc_bits = first.adc_bits
            self.zero_cal_active = first.zero_cal_active
            self.sample_interval_ms = first.sample_interval_ms
        self._sync_compat_aliases()
        self.update_zero_status_label()
        self._refresh_summary_text()

    def _make_channel(self, color=None, mode='serial', port='', name=None,
                      sample_interval_ms=None, acs_params=None):
        """创建通道对象 + 对应 UI 行（不重复使用已删除通道的 id/name）。

        新建通道的换算参数缺省继承「参数卡当前选中路 / 第 1 路 / 模块级」。
        """
        cid = self._next_channel_id
        self._next_channel_id += 1
        seq = self._next_channel_seq
        self._next_channel_seq += 1
        if not color:
            used = {ch.color for ch in self.channels}
            color = next((c for c in CHANNEL_COLORS if c not in used),
                         CHANNEL_COLORS[(seq - 1) % len(CHANNEL_COLORS)])
        if acs_params is None:
            acs_params = self._adc_param_source()
        ch = _Channel(cid, name or f"通道{seq}", color, mode=mode, port=port,
                      sample_interval_ms=sample_interval_ms or self.sample_interval_ms,
                      acs_params=acs_params)
        self.channels.append(ch)
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
        self._remove_live_row(ch)
        self._refresh_chart_visibility_row()
        self._update_delete_btns()
        self._sync_compat_aliases()
        self._refresh_active_channel_combo()
        self.save_config()
        self._sync_conn_card_height()

    def _build_live_row(self, ch):
        """为通道创建一行实时明细：名称+大字电流（通道色） | 原始ADC | ADC端电压 | 传感器输出。

        多路同屏各占一行，不再互相覆盖；顶部不再有共享汇总位。
        """
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(16)

        name_label = CaptionLabel(ch.name)
        h.addWidget(name_label)

        value_label = BodyLabel(f"--.- {self.current_unit}")
        value_label.setFont(QFont("Cascadia Code", 20, QFont.Weight.Bold))
        value_label.setStyleSheet(f"color: {ch.color};")
        h.addWidget(value_label)

        h.addStretch()

        raw_label = CaptionLabel(f"{ch.name} ADC: ------")
        raw_label.setFont(QFont("Cascadia Code", 11))
        h.addWidget(raw_label)

        vadc_label = CaptionLabel("ADC端电压: --.- V")
        vadc_label.setFont(QFont("Cascadia Code", 11))
        h.addWidget(vadc_label)

        vsensor_label = CaptionLabel("传感器输出: --.- V")
        vsensor_label.setFont(QFont("Cascadia Code", 11))
        h.addWidget(vsensor_label)

        self._live_layout.addWidget(row)
        self._live_rows[ch.id] = {
            'row': row, 'name_label': name_label, 'value_label': value_label,
            'raw_label': raw_label, 'vadc_label': vadc_label,
            'vsensor_label': vsensor_label,
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
            if ch.current_data:
                self.current_value_label.setText(
                    f"{ch.name}: {self.format_current(ch.current_data[-1])} {self.current_unit}")
                return
        self.current_value_label.setText(f"--.- {self.current_unit}")

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
        """DataService / 网页端兼容：对外仍暴露单一 mode_combo/port_combo。

        core.DataService.connection_info / _apply_connection 依赖这两个属性
        读写连接方式与端口；多路化后让它们指向第 1 路的行控件，
        set_connection('模拟器'/.../串口端口) 即作用于第 1 路，
        connect=true 连接全部、断开连接全部，网页端不破。
        """
        if self.channels:
            refs = self._rows[self.channels[0].id]
            self.mode_combo = refs['mode_combo']
            self.port_combo = refs['port_combo']

    def _build_channel_card(self, ch):
        """为通道创建一张连接子卡（参考电压模块多路连接的子卡样式）。

        header：名称编辑 / 图线颜色下拉 / 删除按钮；
        body：连接方式 + 串口 + 刷新 + 采样频率 + 连接按钮同一行（紧凑）。
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
        # 实时行大字颜色同步为新通道色
        live = self._live_rows.get(ch.id)
        if live:
            live['value_label'].setStyleSheet(f"color: {ch.color};")

    def _on_channel_name_edited(self, ch, text):
        """名称编辑完成：写回通道名（留空恢复默认「通道N」）。"""
        t = text.strip()
        ch.name = t or ch.default_name
        refs = self._rows.get(ch.id)
        if refs:
            try:
                refs['card'].titleLabel.setText(ch.name)
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
        """单路的连接/断开按钮：按本路线程状态切换。"""
        if ch.thread and ch.thread.isRunning():
            self._disconnect_channel(ch)
        else:
            self._connect_channel(ch)

    def _connect_channel(self, ch):
        """连接单路：串口或模拟器（其余通道不受影响）。"""
        try:
            if ch.mode == 'simulator':
                # 模拟器产生 0~满量程 的原始 ADC 值，中点≈零电流（按本路位数）
                max_adc = self.ADC_BITS_OPTIONS.get(ch.adc_bits, 4096) - 1
                th = SimulatorThread(value_min=0, value_max=max_adc,
                                     interval_ms=ch.sample_interval_ms,
                                     start_value=max_adc / 2.0)
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
        self.zero_cal_btn.setEnabled(True)   # 连接后即可去皮，不必先开始采集
        live = self._live_rows.get(ch.id)
        if live:
            live['value_label'].setText(f"--.- {self.current_unit}")
            live['raw_label'].setText(f"{ch.name}: 连接中...")
            live['vadc_label'].setText("ADC端电压: --.- V")
            live['vsensor_label'].setText("传感器输出: --.- V")

    def _disconnect_channel(self, ch):
        """断开单路（其余通道不受影响）。"""
        if ch.thread:
            stop_thread(ch.thread, name=f"电流{ch.name}线程")
            ch.thread = None
        refs = self._rows.get(ch.id)
        if refs:
            refs['connect_btn'].setText("连接")
        log.info("%s 已断开", ch.name)
        # 本路实时行复位 + 去皮窗口清空，其余路的显示保留
        ch.live_window.clear()
        live = self._live_rows.get(ch.id)
        if live:
            live['value_label'].setText(f"--.- {self.current_unit}")
            live['raw_label'].setText(f"{ch.name} ADC: 已断开")
            live['vadc_label'].setText("ADC端电压: --.- V")
            live['vsensor_label'].setText("传感器输出: --.- V")
        self._refresh_summary_text()
        if not any(c.thread for c in self.channels):
            self._set_collect_enabled(False)
            self.zero_cal_btn.setEnabled(False)

    def connect_device(self):
        """连接全部未连接的通道（网页端 set_connection connect=true 走这里）。"""
        for ch in self.channels:
            if not (ch.thread and ch.thread.isRunning()):
                self._connect_channel(ch)

    def disconnect_all(self):
        """断开全部通道（退出清理 / 网页端命令也走这里）。"""
        for ch in list(self.channels):
            self._disconnect_channel(ch)

    # ------------------------------------------------------------------
    # 采集控制
    # ------------------------------------------------------------------
    def toggle_collection(self):
        """合并的开始/停止按钮：按当前采集状态切换。"""
        if self._collecting:
            self.stop_collection()
        else:
            self.start_collection()

    def _set_collect_enabled(self, enabled):
        """连接/断开时同步合并按钮与浮动栏按钮的可用性。

        「去皮」依赖实时数据流：连接后即可用（无需先开始采集），断开则禁用
        —— 与采集按钮同步，避免连没连上都能点。
        """
        self.collect_btn.setEnabled(enabled)
        self.float_collect_btn.setEnabled(enabled)
        self.zero_cal_btn.setEnabled(
            enabled or any(ch.live_window for ch in self.channels))

    def _refresh_collect_btn(self):
        """合并按钮与浮动栏按钮：文案随采集状态切换（停止采集/开始采集）。"""
        update_collect_btn(self.collect_btn, self._collecting)
        update_collect_btn(self.float_collect_btn, self._collecting)

    def start_collection(self):
        for ch in self.channels:
            ch.current_data.clear()
            ch.vsensor_data.clear()
            ch.time_data.clear()
            ch.raw_data.clear()
            ch.last_sample_s = None
        self.data_text.clear()
        # 主机统一时间基准：以采集期收到的**首个样本**为 t=0（各路共享）
        self._t0_mono = None
        self._collecting = True
        log.info("开始采集（已连接 %d 路）",
                 sum(1 for ch in self.channels if ch.thread))
        self._refresh_collect_btn()
        self.save_btn.setEnabled(False)
        self.current_value_label.setText("电流: 采集中...")
        for ch in self.channels:
            live = self._live_rows.get(ch.id)
            if live:
                live['raw_label'].setText(f"{ch.name} ADC: 采集中...")

    def stop_collection(self):
        self._collecting = False
        self._refresh_collect_btn()
        total = sum(len(ch.current_data) for ch in self.channels)
        self.save_btn.setEnabled(total > 0)
        log.info("停止采集，共 %d 个数据点", total)
        if total > 0:
            # 汇总标签显示数据最多通道的均值
            main = max(self.channels, key=lambda c: len(c.current_data))
            if main.current_data:
                avg_c = np.mean(main.current_data)
                self.current_value_label.setText(
                    f"{main.name} 均值: {self.format_current(avg_c)} {self.current_unit}")

    # ------------------------------------------------------------------
    # 数据处理
    # ------------------------------------------------------------------
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
            live = self._live_rows.get(ch.id)
            if live:
                live['raw_label'].setText(f"{ch.name}: 设备就绪，等待数据...")
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

        # 实时显示 + 去皮滚动窗口（未采集时也持续刷新）——只更新本路行
        ch.live_window.append(raw_value)
        v_adc = self.adc_to_vadc(raw_value, channel=ch)
        v_sensor = self.adc_to_vsensor(raw_value, channel=ch)
        current = self.adc_to_current(raw_value, channel=ch)
        live = self._live_rows.get(ch.id)
        if live:
            live['raw_label'].setText(f"{ch.name} ADC: {raw_value}")
            live['vadc_label'].setText(f"ADC端电压: {v_adc:.4f} V")
            live['vsensor_label'].setText(f"传感器输出: {v_sensor:.4f} V")
            if self.current_mode == 'AC':
                # AC 模式：优先显示该路滚动窗口 RMS
                rms = self._compute_ac_rms(ch)
                if rms is not None:
                    live['value_label'].setText(
                        f"{self.format_current(rms)} {self.current_unit}")
                else:
                    live['value_label'].setText(
                        f"{self.format_current(current)} {self.current_unit}")
            else:
                live['value_label'].setText(
                    f"{self.format_current(current)} {self.current_unit}")
        # 隐藏摘要标签记最新活动的一路（仅供全屏浮动面板折叠态摘要读取）
        self.current_value_label.setText(
            f"{ch.name}: {self.format_current(current)} {self.current_unit}")

        if not self._collecting:
            return

        # 主机统一时间戳：采集期首个到达样本定为 t=0
        now = time.monotonic()
        if self._t0_mono is None:
            self._t0_mono = now
        t_rel = now - self._t0_mono

        # 采样频率控制（每路独立过滤，按本路设定的间隔）
        if ch.last_sample_s is not None and \
                (t_rel - ch.last_sample_s) * 1000 < ch.sample_interval_ms:
            return
        ch.last_sample_s = t_rel

        ch.raw_data.append(raw_value)
        ch.vsensor_data.append(v_sensor)
        ch.current_data.append(current)
        ch.time_data.append(t_rel)

        time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        display_text = (f"{time_str} | {ch.name} | ADC: {raw_value} | "
                        f"ADC端: {v_adc:.4f}V | 传感器: {v_sensor:.4f}V | "
                        f"电流: {self.format_current(current)} {self.current_unit}")
        self.data_text.append(display_text)
        self.data_text.verticalScrollBar().setValue(
            self.data_text.verticalScrollBar().maximum()
        )
        self.update_stats()

    def _compute_ac_rms(self, ch):
        """计算 AC 模式下该通道滚动窗口的电流 RMS（安培）。"""
        if not ch.current_data:
            return None
        window = ch.current_data[-self.ac_rms_window:]
        arr = np.array(window, dtype=float)
        return float(np.sqrt(np.mean(arr ** 2)))

    def update_stats(self):
        """统计栏：每路有数据的通道各显示一行统计（点数/均值/极值/σ 或 RMS）。"""
        parts = []
        u = self.current_unit
        for ch in self.channels:
            if not ch.current_data:
                continue
            arr = np.array(ch.current_data, dtype=float)
            if self.current_mode == 'AC':
                rms = float(np.sqrt(np.mean(arr ** 2)))
                peak = float(np.max(np.abs(arr)))
                parts.append(
                    f"{ch.name}: 点数 {len(arr)} | "
                    f"RMS={self.format_current(rms)}{u} | "
                    f"峰值={self.format_current(peak)}{u}")
            else:
                avg = float(np.mean(arr))
                mx = float(np.max(arr))
                mn = float(np.min(arr))
                std = float(np.std(arr))
                parts.append(
                    f"{ch.name}: 点数 {len(arr)} | "
                    f"均={self.format_current(avg)}{u} | "
                    f"最大={self.format_current(mx)}{u} | "
                    f"最小={self.format_current(mn)}{u} | "
                    f"σ={self.format_current(std)}{u}")
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
            display_data = [self.to_current_unit(v) for v in ch.current_data]
            c.plot(ch.time_data, display_data, color=ch.color, width=2,
                   label=f'{ch.name} ({self.current_unit})')
            all_t.extend(ch.time_data)
        # AC 模式：单路可见时叠加该路 RMS 参考线（多路时各路 RMS 不同，不画）
        if self.current_mode == 'AC' and len(active) == 1 and \
                len(active[0].current_data) >= self.ac_rms_window:
            rms = self._compute_ac_rms(active[0])
            if rms is not None:
                rms_disp = self.to_current_unit(rms)
                c.hline(rms_disp, color='#fd7e14', style='dash', width=1.5,
                        label=f'RMS {self.format_current(rms)}{self.current_unit}')
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
    def _on_channel_sample_interval_changed(self, ch, interval_ms):
        """本路采样频率改变：更新该路间隔并保存配置（对该路过滤即时生效；
        模拟器线程按创建时间隔发数，重连后按新频率运行）。"""
        ch.sample_interval_ms = interval_ms
        if self.channels and ch is self.channels[0]:
            self.sample_interval_ms = interval_ms  # 顶层字段跟第 1 路（旧配置兼容）
        self.save_config()

    def save_data(self):
        total = sum(len(ch.current_data) for ch in self.channels)
        if total == 0:
            fluent_message_box(self, "警告", "没有数据可保存")
            return
        try:
            filename = f"current_sensor_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', encoding='utf-8') as f:
                # 长表格式：一行一个样本 + 通道名列。多路的时间轴天然对齐
                # （主机统一时间戳），便于 Excel 透视/筛选按通道分组分析
                f.write(f"# ACS712 模式={self.current_mode} 单位={self.current_unit} "
                        f"AC RMS窗口={self.ac_rms_window}点\n")
                f.write(f"channel,timestamp_s,raw_adc,v_adc,v_sensor,current_{self.current_unit.lower()}\n")
                for ch in self.channels:
                    src = self._adc_param_source(ch)
                    f.write(f"# {ch.name}: 量程={ch.acs_range} "
                            f"灵敏度={self._sensitivity_of(src)}V/A "
                            f"零点={ch.v_quiescent:.4f}V 分压比={ch.divider_ratio}\n")
                    for i, (t, current) in enumerate(zip(ch.time_data, ch.current_data)):
                        raw = ch.raw_data[i] if i < len(ch.raw_data) else 0
                        v_adc = self.adc_to_vadc(raw, channel=ch)
                        v_sensor = self.adc_to_vsensor(raw, channel=ch)
                        f.write(f"{ch.name},{t:.3f},{raw},{v_adc:.6f},{v_sensor:.6f},"
                                f"{self.to_current_unit(current):.6f}\n")
            log.info("数据已保存到: %s（%d 点）", filename, total)
            fluent_message_box(self, "成功", f"数据已保存到: {filename}")
        except Exception as e:
            log.error("保存失败: %s", e)
            fluent_message_box(self, "错误", f"保存失败: {e}")

    def clear_data(self):
        for ch in self.channels:
            ch.current_data.clear()
            ch.vsensor_data.clear()
            ch.time_data.clear()
            ch.raw_data.clear()
            ch.last_sample_s = None
        self._t0_mono = None
        self.data_text.clear()
        log.info("已清除数据")
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

    def _ai_data(self):
        """AI 分析实验数据回调（图表卡「AI分析实验」按钮调用）。

        多路连接时取**数据最多的通道**作为主分析序列，各通道概况与
        每路零点写入 params，供模型理解多路对比背景。
        """
        active = [ch for ch in self.channels if ch.current_data]
        if not active:
            return None
        main = max(active, key=lambda c: len(c.current_data))
        # 电路参数：电流分辨率与可测范围（受 ADC 量程、分压比与零点限制，按主分析通道）
        src = self._adc_param_source(main)
        sensitivity = self._sensitivity_of(src)
        max_adc = self.ADC_BITS_OPTIONS.get(src['adc_bits'], 4096) - 1
        res_i = (self.VREF / max_adc) * src['divider_ratio'] / sensitivity
        v_sensor_max = self.VREF * src['divider_ratio']
        i_pos = (v_sensor_max - src['v_quiescent']) / sensitivity
        i_neg = (0.0 - src['v_quiescent']) / sensitivity
        lo, hi = min(i_pos, i_neg), max(i_pos, i_neg)
        channels_desc = "、".join(
            f"{ch.name}[{len(ch.current_data)}点/量程{ch.acs_range}"
            + ("/已校零" if ch.zero_cal_active else "/未校零")
            + f"]" for ch in active)
        return {
            'title': '电流传感器',
            'x_label': '时间 (秒)',
            'y_label': f'电流 ({self.current_unit})',
            'points': list(zip(main.time_data,
                               [self.to_current_unit(c) for c in main.current_data])),
            'params': (
                f"传感器=ACS712 {src['acs_range']} 量程（灵敏度 {sensitivity:.3f} V/A）, "
                f"VCC={src['vcc']}V, 零点电压={src['v_quiescent']:.4f}V"
                f"(理论 VCC/2={src['vcc'] / 2:.4f}V), "
                f"分压比={src['divider_ratio']}, ADC 位数={src['adc_bits']}, "
                f"电流分辨率≈{res_i * 1000:.3f}mA/计数, "
                f"可测范围≈{lo:.2f}~{hi:.2f}A（受 ADC 量程与分压限制）, "
                f"模式={self.current_mode}, AC RMS 窗口={self.ac_rms_window}点, "
                f"零点校准={'已校准' if src['zero_cal_active'] else '未校准'}, "
                f"多路连接: 共{len(active)}路（{channels_desc}），"
                f"主分析通道={main.name}, 各路量程/零点/分压独立, "
                f"显示单位={self.current_unit}, "
                f"采样间隔={main.sample_interval_ms}ms（各路独立）"),
            'system_prompt': AI_SYSTEM_PROMPT,
        }

    def api_snapshot(self):
        """当前实验数据快照（供 core.DataService 任意线程读取）。
        禁止调用任何 Qt 方法：只读模块自身的 Python 数据。"""
        d = self._ai_data() or {}
        points = list(d.get('points') or [])
        latest = None
        main = max((ch for ch in self.channels if ch.current_data),
                   key=lambda c: len(c.current_data), default=None)
        if main is not None:
            latest = {'t': main.time_data[-1],
                      'y': self.to_current_unit(main.current_data[-1]),
                      'raw': main.raw_data[-1] if main.raw_data else None}
        return {
            'key': 'current_sensor',
            'name': '电流传感器',
            'connected': any(ch.thread is not None for ch in self.channels),
            'collecting': self._collecting,
            'x_label': d.get('x_label', '时间 (秒)'),
            'y_label': d.get('y_label', '电流 (A)'),
            'params': d.get('params', {}),
            'points': points,
            'latest': latest,
            # 多路连接明细（points 仍为主通道序列，前端单曲线不破）
            'channels': [
                {'name': ch.name, 'color': ch.color,
                 'connected': ch.thread is not None,
                 'points_n': len(ch.current_data),
                 'zero_cal_active': ch.zero_cal_active,
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
        # 图表 figure 背景跟随主题
        try:
            from qfluentwidgets import isDarkTheme
            self.chart.apply_chart_theme(isDarkTheme())
        except Exception:
            pass
