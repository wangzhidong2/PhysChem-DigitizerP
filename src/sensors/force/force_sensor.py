# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

# === MODULE META ===
# icon: F
# name: 力传感器
# category: physics
# class: ForceSensorWidget
# ===================

# -*- coding: utf-8 -*-
"""力传感器模块 — HX711 力/质量传感器测量。

多路连接：每路独立选择串口/模拟器、独立去皮零点与标定系数、独立采样频率，
多路数据以主机统一时间戳叠加画在同一张图上（架构与电压模块一致，
见 docs/multi-channel-design.md）。
"""

import sys
import os
import time
from collections import deque
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QScrollArea, QSizePolicy, QDialog,
)
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter, QColor
from qfluentwidgets import (
    PushButton, PrimaryPushButton, ComboBox, TextEdit, TitleLabel,
    BodyLabel, CaptionLabel, FluentIcon as FIF, MessageBoxBase,
    DoubleSpinBox, SubtitleLabel,
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
    SampleRateComboBox, CalibrationDialog, stop_thread,
    load_sensor_config, save_sensor_config,
    SERIAL_AVAILABLE, list_serial_ports, serial_unavailable_hint,
    card_style, primary_btn_style, accent_btn_style, modern_combo_style,
    CollapsibleCard, FluentCard, ExpandableTextEdit,
    _get_config_file_path,
    scroll_area_style, page_bg_style, apply_module_theme,
    update_collect_btn, set_action_button_width,
    get_logger,
)

log = get_logger("force_sensor")

# AI 分析实验：模块专属系统提示词（进入 AI 分析时随实验信息与数据发送给模型，
# 由 core.build_ai_system_prompt 组装进 system 消息）
AI_SYSTEM_PROMPT = (
    "你是一位资深物理实验指导教师与力学测量专家，正在协助分析 HX711（24 位 ADC）"
    "加应变片式力/质量传感器的实验数据。"
    "测量原理：质量(克) =（raw − 去皮 offset）× 标定系数 scale；offset 由空载去皮获得，"
    "scale 由已知砝码两点标定；显示单位 g/kg/N（N = 克 ÷ 1000 × 9.8）。未校准时显示"
    "原始 ADC 值。多路连接时各路传感器（不同 HX711 + 应变片）的 offset 与 scale 互相独立。"
    "数据特征：静态称重曲线应平稳，噪声通常在显示精度的 1~2 个单位内；加载与卸载对应"
    "台阶式变化；蠕变表现为读数缓慢下沉，温度漂移表现为零点或灵敏度随时间缓变；"
    "冲击、振动、自由落体等动态过程呈脉冲或振荡。"
    "常见误差来源：传感器蠕变与迟滞、温度漂移、平台振动、接线/接触电阻变化、超量程、"
    "标定砝码不准、未充分预热、去皮时未真正空载。"
    "分析要求：①评估零点漂移与噪声幅度，判断标定是否仍然有效；②识别加载/卸载台阶，"
    "给出幅值、稳定时间与超调；③动态过程给出峰值、变化速率与响应时间，并与 F=ma、"
    "重力模型对照；④区分随机误差与系统误差，建议多点标定、数字滤波（滑动平均/中值）、"
    "减振、预热与量程复核等改进措施。"
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


class KnownWeightMessageBox(MessageBoxBase):
    """校准-已知质量输入弹窗 — 基于 Fluent-Widgets 原生 MessageBoxBase。

    WinUI3 掩码弹窗：居中浮窗 + 阴影 + 确定/取消按钮，样式随 Fluent 主题，
    与主程序其他 MessageBox 视觉一致。替代旧的原生 QInputDialog。
    exec() 返回 QDialog.Accepted 表示确认，self.weight 为输入的砝码质量（克）。
    """

    def __init__(self, default_weight=100.0, parent=None):
        super().__init__(parent)
        self.weight = default_weight

        self.yesButton.setText("确定")
        self.cancelButton.setText("取消")
        # 只固定宽度：竖向高度交由表单内容自适应
        self.widget.setFixedWidth(420)

        view = self.viewLayout
        view.addWidget(SubtitleLabel("校准 - 已知质量"))

        info = CaptionLabel("请放上已知质量的砝码，并输入砝码质量：")
        info.setWordWrap(True)
        view.addWidget(info)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(BodyLabel("砝码质量"))
        self.weight_input = DoubleSpinBox()
        self.weight_input.setRange(0.01, 100000)
        self.weight_input.setDecimals(2)
        self.weight_input.setValue(float(default_weight))
        self.weight_input.setMinimumWidth(160)
        self.weight_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.weight_input.setToolTip(
            "已知砝码的质量，范围 0.01 ~ 100000 克，保留 2 位小数")
        row.addWidget(self.weight_input)
        row.addWidget(CaptionLabel("克 (g)"), 1)
        view.addLayout(row)

    def validate(self):
        # 点击确定时才把输入读回 self.weight，输入非法（超范围/为空）则不关窗
        self.weight = self.weight_input.value()
        return True


class _Channel:
    """一路连接的数据模型（纯 Python 对象，不持有任何 Qt 控件）。

    每路连接独立选择「有线串口 / 模拟器」、独立串口、独立曲线颜色、
    独立去皮零点与标定系数（不同 HX711 的 offset/scale 各不相同）；
    数据按主机统一时间戳记录（见 handle_data）。
    UI 行控件引用由模块统一保管在 _rows[channel.id] 里。
    """

    def __init__(self, cid, name, color, mode='serial', port='',
                 sample_interval_ms=100, cal_params=None):
        self.id = cid                      # 稳定 id（信号绑定用，删除后不复用）
        self.name = name                    # 显示名（可自定义，留空回退默认名）
        self.default_name = name            # 默认名（通道N，创建时定序）
        self.color = color                  # 曲线颜色
        self.mode = mode                    # 'serial' | 'simulator'
        self.port = port                    # 串口模式下选中的端口
        self.thread = None                  # SerialThread / SimulatorThread
        self.sample_interval_ms = sample_interval_ms  # 本路采样间隔（每路独立）
        # 本路换算参数（每路独立；缺省继承模块级/全局默认）
        p = cal_params or {}
        self.offset = p.get('offset', 0)
        self.scale = p.get('scale', 1.0)
        self.calibrated = p.get('calibrated', False)
        self.visible = p.get('visible', True)   # 图表显示开关（勾选框控制）
        # 采集数据（已校准存克值，未校准存原始 ADC 值）
        self.time_data = []
        self.raw_data = []
        self.force_data = []
        # 去皮 / 实时显示用的滚动窗口（含未采集时的实时数据）
        self.live_window = deque(maxlen=10)
        # 上次记录样本的主机相对秒（采样间隔过滤，每路独立）
        self.last_sample_s = None


class ForceSensorWidget(QWidget):
    """力传感器（HX711）模块界面 - 支持多路连接、逐路去皮与校准、单位切换"""

    GRAVITY = 9.8
    UNIT_LABELS = {"g": "克 (g)", "kg": "千克 (kg)", "N": "牛顿 (N)"}

    def __init__(self):
        super().__init__()
        self._collecting = False  # 当前是否在采集（合并开始/停止按钮状态）
        # 多路连接：每路一个 _Channel（独立模式/串口/颜色/去皮/校准/数据）
        self.channels = []
        self._rows = {}              # channel.id -> 行控件引用 dict
        self._next_channel_id = 1   # 稳定 id 分配器（删除后不复用）
        self._next_channel_seq = 1  # 显示名序号（通道N）
        self._t0_mono = None        # 采集期主机统一时间基准（首个样本时刻）

        # 采样频率设置（毫秒）—— 模块级镜像字段（始终与第 1 路一致）
        self.sample_interval_ms = 100  # 默认 100ms (10Hz)

        # 模块级换算镜像字段（始终与第 1 路一致；各路独立值在 _Channel 上）
        self.offset = 0
        self.scale = 1.0
        self.calibrated = False
        # 模块级共享设置（对全部通道生效）
        self.cal_known_weight = 100.0   # 校准砝码质量的默认提示值
        self.current_unit = "g"

        # 校准流程状态（针对「校准与去皮」卡当前选中路）
        self.cal_step = 0
        self.cal_raw_before = 0
        self.cal_raw_after = 0

        self.config = self.load_config()
        self.offset = self.config.get('offset', 0)
        self.scale = self.config.get('scale', 1.0)
        self.calibrated = self.config.get('calibrated', False)
        self.cal_known_weight = self.config.get('cal_known_weight', 100.0)
        self.current_unit = self.config.get('unit', 'g')

        self.init_ui()
        # 恢复上次的通道列表（含模式/串口/颜色/去皮/校准）；无记录时建一路默认通道
        self._restore_channels()

    def convert_unit(self, value_grams):
        """将克值转换为当前单位值

        转换关系：
          g  → 直接返回
          kg → value_grams / 1000
          N  → value_grams / 1000 * 9.8
        """
        if self.current_unit == "kg":
            return value_grams / 1000.0
        elif self.current_unit == "N":
            return value_grams / 1000.0 * self.GRAVITY
        return value_grams

    def get_unit_str(self, ch=None):
        """获取当前单位字符串（未校准通道显示 raw）"""
        ch = ch or self._main_channel()
        calibrated = ch.calibrated if ch is not None else self.calibrated
        return self.current_unit if calibrated else "raw"

    def get_chart_ylabel(self):
        """获取图表Y轴标签（按主通道的校准状态）"""
        main = self._main_channel()
        calibrated = main.calibrated if main is not None else self.calibrated
        if not calibrated:
            return "原始ADC值"
        labels = {"g": "质量 (g)", "kg": "质量 (kg)", "N": "力 (N)"}
        return labels.get(self.current_unit, "质量 (g)")

    def _main_channel(self):
        """主通道：数据最多的一路（无数据时取第 1 路）。"""
        with_data = [ch for ch in self.channels if ch.force_data]
        if with_data:
            return max(with_data, key=lambda c: len(c.force_data))
        return self.channels[0] if self.channels else None

    def get_config_path(self):
        """获取配置文件路径（已废弃，保留兼容）"""
        return _get_config_file_path()

    def load_config(self):
        """加载力传感器配置"""
        config = load_sensor_config('force_sensor')
        if config:
            self.offset = config.get('offset', 0)
            self.scale = config.get('scale', 1.0)
            self.calibrated = config.get('calibrated', False)
            self.cal_known_weight = config.get('cal_known_weight', 100.0)
            self.current_unit = config.get('unit', 'g')
            self.sample_interval_ms = config.get('sample_interval_ms', 100)
        return config

    def save_config(self):
        """保存力传感器配置（顶层字段取第 1 路，channels 记录各路独立参数）"""
        first = self.channels[0] if self.channels else None
        config = {
            'offset': first.offset if first else self.offset,
            'scale': first.scale if first else self.scale,
            'calibrated': first.calibrated if first else self.calibrated,
            'cal_known_weight': self.cal_known_weight,
            'unit': self.current_unit,
            'sample_interval_ms': first.sample_interval_ms if first else self.sample_interval_ms,
            # 多路连接：每路的模式/串口/颜色/采样间隔/去皮/校准/图表显示
            'channels': [
                {'name': ch.name, 'mode': ch.mode, 'port': ch.port,
                 'color': ch.color, 'sample_interval_ms': ch.sample_interval_ms,
                 'offset': ch.offset, 'scale': ch.scale,
                 'calibrated': ch.calibrated, 'visible': ch.visible}
                for ch in self.channels
            ],
        }
        return save_sensor_config('force_sensor', config)

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
        title = TitleLabel("力")
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
            "增加一路 HX711 连接：\n"
            "每路可单独选择「有线串口 / 模拟器」，单独连接/断开，\n"
            "单独换曲线颜色；去皮与校准按路独立（不同传感器零点/灵敏度不同）")
        self.add_channel_btn.clicked.connect(lambda: self.add_channel())
        self.card_conn.add_header_widget(self.add_channel_btn)
        # 主卡展开动画结束后按子卡实际高度收敛（子卡折叠后 sizeHint 不缩）
        self.card_conn.expandAni.finished.connect(self._sync_conn_card_height)
        layout.addWidget(self.card_conn)

        # ========== 卡片2：校准与去皮（可折叠，按连接独立） ==========
        card_cal_content = QWidget()
        card_cal_content.setObjectName("card")
        card_cal_content.setStyleSheet(card_style())
        cal_card_layout = QVBoxLayout(card_cal_content)
        cal_card_layout.setContentsMargins(20, 4, 20, 16)
        cal_card_layout.setSpacing(12)

        self.cal_status_label = BodyLabel("")
        self.update_cal_status_label()
        cal_card_layout.addWidget(self.cal_status_label)

        cal_btn_row = QHBoxLayout()
        cal_btn_row.setSpacing(10)

        self.tare_btn = PushButton("去皮（TARE）")
        self.tare_btn.setFixedHeight(36)
        self.tare_btn.setStyleSheet("background-color: #fd7e14; color: white;")
        self.tare_btn.setToolTip("取最近 10 个采样点的平均值作为零点（offset），从测量值中扣除。\n"
                                 "连接设备后即可点，不必先开始采集；可反复点击重新去皮，\n"
                                 "没有「取消去皮」按钮。多路连接时对有数据流入的通道分别去皮\n"
                                 "（各路零点独立；有线串口同时通知各路固件）。")
        self.tare_btn.clicked.connect(self.tare_now)
        self.tare_btn.setEnabled(False)
        cal_btn_row.addWidget(self.tare_btn)

        self.calibrate_btn = PushButton("校准（CALIBRATE）")
        self.calibrate_btn.setFixedHeight(36)
        self.calibrate_btn.setToolTip("两点标定：作用于「当前连接」下拉所选的一路\n"
                                      "（空载记录零点 → 放已知砝码记录 → 得出该路 scale）")
        self.calibrate_btn.clicked.connect(self.start_calibration)
        self.calibrate_btn.setEnabled(False)
        cal_btn_row.addWidget(self.calibrate_btn)

        cal_btn_row.addStretch()
        cal_card_layout.addLayout(cal_btn_row)

        unit_row = QHBoxLayout()
        unit_row.setSpacing(8)
        unit_row.addWidget(BodyLabel("显示单位:"))
        self.unit_combo = ComboBox()
        self.unit_combo.addItems(["克 (g)", "千克 (kg)", "牛顿 (N)"])
        unit_map = {"g": 0, "kg": 1, "N": 2}
        self.unit_combo.setCurrentIndex(unit_map.get(self.current_unit, 0))
        self.unit_combo.currentIndexChanged.connect(self.on_unit_changed)
        unit_row.addWidget(self.unit_combo)
        unit_hint = CaptionLabel("g = 9.8 m/s²")
        unit_row.addWidget(unit_hint)
        unit_row.addStretch()
        cal_card_layout.addLayout(unit_row)

        card_cal = FluentCard("校准与去皮", card_cal_content, expanded=True, icon=FIF.EDIT)
        self.card_cal = card_cal
        # header 右侧：「当前连接」下拉——去皮/校准状态与参数按路独立
        self._active_channel_combo = ComboBox()
        self._active_channel_combo.setMinimumWidth(110)
        self._active_channel_combo.setToolTip(
            "校准与去皮按连接独立：\n切换后显示所选路的校准状态；校准流程作用于所选路")
        self._active_channel_combo.currentIndexChanged.connect(
            self._on_active_channel_changed)
        card_cal.add_header_widget(self._active_channel_combo)

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
        self.current_force_label = BodyLabel("力/质量: --.-")
        self.current_force_label.setFont(QFont("Cascadia Code", 14, QFont.Weight.Bold))
        self.current_force_label.setStyleSheet("color: #1a1a1a;")
        self.current_force_label.setParent(self)
        self.current_force_label.hide()

        # 每路一行实时明细（通道增删时动态重建，见 _build_live_row）
        self._live_rows = {}          # channel.id -> {row, name_label, force_label, raw_label}
        self._live_container = QWidget()
        self._live_layout = QVBoxLayout(self._live_container)
        self._live_layout.setContentsMargins(0, 0, 0, 0)
        self._live_layout.setSpacing(4)
        data_card_layout.addWidget(self._live_container)

        self.current_unit_label = CaptionLabel(
            f"单位: {self.UNIT_LABELS.get(self.current_unit, 'g')}（未校准则显示原始值）"
        )
        data_card_layout.addWidget(self.current_unit_label)

        self.stats_label = CaptionLabel("统计信息：暂无数据")
        data_card_layout.addWidget(self.stats_label)

        card_data = FluentCard("实时数据", card_data_content, expanded=True, icon=FIF.HISTORY)
        self.card_data = card_data

        # 校准与去皮 + 实时数据 并排同一行
        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)
        cards_row.addWidget(card_cal, stretch=1, alignment=Qt.AlignmentFlag.AlignTop)
        cards_row.addWidget(card_data, stretch=1, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(cards_row)

        # ========== 卡片4：力-时间曲线（可全屏） ==========
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
        card_chart = CollapsibleCard("力-时间曲线", card_chart_content, expanded=True, fullscreen=True)
        # 图表卡片加高为原来的 2 倍（内容区最小 400px），页面滚动查看
        card_chart.set_chart_min_height(400)
        # 全屏浮动栏：合并的开始/停止按钮（与操作按钮卡的 collect_btn 同步状态）
        self.float_collect_btn = PrimaryPushButton("开始采集")
        self.float_collect_btn.setFixedHeight(34)
        update_collect_btn(self.float_collect_btn, False)
        self.float_collect_btn.clicked.connect(self.toggle_collection)
        self.float_collect_btn.setEnabled(False)
        # 全屏时：数据记录 + 拟合分析面板浮于图表上方，浮动栏底部可控制开始/停止
        card_chart.set_fullscreen_overlay(
            self.data_text, self.current_force_label,
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

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_chart)
        self.timer.start(100)

    def on_unit_changed(self, index):
        unit_list = ["g", "kg", "N"]
        self.current_unit = unit_list[index]
        self.save_config()
        main = self._main_channel()
        calibrated = main.calibrated if main is not None else self.calibrated
        self.current_unit_label.setText(
            f"单位: {self.UNIT_LABELS.get(self.current_unit, 'g')}"
            + ("（未校准则显示原始值）" if not calibrated else f"（校准比例={main.scale:.6f}）")
        )
        # 逐路刷新实时行（显示单位变了，换算后的显示值要跟着变）
        for ch in self.channels:
            live = self._live_rows.get(ch.id)
            if live and ch.force_data:
                live['force_label'].setText(self._format_force_value(ch))
        self.update_stats()
        self.update_chart()

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
                    cal_params={'offset': self.offset, 'scale': self.scale,
                                'calibrated': self.calibrated, **item})
        else:
            # 旧版单通道配置迁移：顶层去皮/校准字段作为第 1 路初值
            self._make_channel(mode='serial' if SERIAL_AVAILABLE else 'simulator')
        self._refresh_active_channel_combo()
        # 顶层镜像字段刷新为第 1 路实际值
        if self.channels:
            first = self.channels[0]
            self.offset = first.offset
            self.scale = first.scale
            self.calibrated = first.calibrated
            self.sample_interval_ms = first.sample_interval_ms
        self._sync_compat_aliases()
        self.update_cal_status_label()
        self._refresh_summary_text()

    def _make_channel(self, color=None, mode='serial', port='', name=None,
                      sample_interval_ms=None, cal_params=None):
        """创建通道对象 + 对应 UI 行（不重复使用已删除通道的 id/name）。

        新建通道的去皮/校准参数缺省继承第 1 路 / 模块级。
        """
        cid = self._next_channel_id
        self._next_channel_id += 1
        seq = self._next_channel_seq
        self._next_channel_seq += 1
        if not color:
            used = {ch.color for ch in self.channels}
            color = next((c for c in CHANNEL_COLORS if c not in used),
                         CHANNEL_COLORS[(seq - 1) % len(CHANNEL_COLORS)])
        if cal_params is None:
            first = self.channels[0] if self.channels else None
            cal_params = {'offset': first.offset if first else self.offset,
                          'scale': first.scale if first else self.scale,
                          'calibrated': first.calibrated if first else self.calibrated}
        ch = _Channel(cid, name or f"通道{seq}", color, mode=mode, port=port,
                      sample_interval_ms=sample_interval_ms or self.sample_interval_ms,
                      cal_params=cal_params)
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
        """为通道创建一行实时明细：名称+大字力/质量（通道色） | 原始ADC。

        多路同屏各占一行，不再互相覆盖；顶部不再有共享汇总位。
        """
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(16)

        name_label = CaptionLabel(ch.name)
        h.addWidget(name_label)

        force_label = BodyLabel("力/质量: --.-")
        force_label.setFont(QFont("Cascadia Code", 20, QFont.Weight.Bold))
        force_label.setStyleSheet(f"color: {ch.color};")
        h.addWidget(force_label)

        h.addStretch()

        raw_label = CaptionLabel(f"{ch.name} ADC: ------")
        raw_label.setFont(QFont("Cascadia Code", 11))
        h.addWidget(raw_label)

        self._live_layout.addWidget(row)
        self._live_rows[ch.id] = {
            'row': row, 'name_label': name_label,
            'force_label': force_label, 'raw_label': raw_label,
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
            live = getattr(self, '_live_layout', None)
            if live is not None:
                live.invalidate()
                live.activate()
            card.refresh_height()
            QTimer.singleShot(0, self._refresh_data_card_height_deferred)

    def _refresh_data_card_height_deferred(self):
        card = getattr(self, 'card_data', None)
        if card is not None:
            card.refresh_height()

    def _format_force_value(self, ch):
        """按该路校准状态与当前单位，格式化实时大字文本。"""
        if not ch.force_data and not ch.live_window:
            return "力/质量: --.-"
        if ch.calibrated:
            grams = ch.force_data[-1] if ch.force_data else (
                (ch.live_window[-1] - ch.offset) * ch.scale)
            converted = self.convert_unit(grams)
        else:
            converted = float(ch.force_data[-1] if ch.force_data
                              else ch.live_window[-1])
        return f"力/质量: {converted:.4f} {self.get_unit_str(ch)}"

    def _refresh_summary_text(self):
        """隐藏摘要标签取「最近一路有数据的通道」最新值（供全屏折叠摘要）。"""
        for ch in reversed(self.channels):
            if ch.force_data or ch.live_window:
                self.current_force_label.setText(self._format_force_value(ch))
                return
        self.current_force_label.setText("力/质量: --.-")

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
            live['force_label'].setStyleSheet(f"color: {ch.color};")

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
                # HX711 24 位原始读数，围绕一个基准值缓慢漂移
                th = SimulatorThread(
                    value_min=7500000, value_max=9000000,
                    interval_ms=ch.sample_interval_ms,
                    start_value=8200000)
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
        self.tare_btn.setEnabled(True)
        self.calibrate_btn.setEnabled(True)
        live = self._live_rows.get(ch.id)
        if live:
            live['force_label'].setText("力/质量: 等待数据...")
            live['raw_label'].setText(f"{ch.name}: 连接中...")

    def _disconnect_channel(self, ch):
        """断开单路（其余通道不受影响）。"""
        if ch.thread:
            stop_thread(ch.thread, name=f"力{ch.name}线程")
            ch.thread = None
        refs = self._rows.get(ch.id)
        if refs:
            refs['connect_btn'].setText("连接")
        log.info("%s 已断开", ch.name)
        # 本路实时行复位 + 去皮窗口清空，其余路的显示保留
        ch.live_window.clear()
        live = self._live_rows.get(ch.id)
        if live:
            live['force_label'].setText("力/质量: --.-")
            live['raw_label'].setText(f"{ch.name} ADC: 已断开")
        self._refresh_summary_text()
        if not any(c.thread for c in self.channels):
            self._set_collect_enabled(False)
            self.tare_btn.setEnabled(False)
            self.calibrate_btn.setEnabled(False)

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
    # 当前连接（校准与去皮卡）
    # ------------------------------------------------------------------
    def _active_channel_obj(self):
        """校准与去皮卡当前选中的通道对象（无通道/未初始化返回 None）。"""
        combo = getattr(self, '_active_channel_combo', None)
        if combo is None:
            return None
        cid = combo.currentData()
        return next((ch for ch in self.channels if ch.id == cid), None)

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
        # 选中项可能变了（删除了原选中通道）：同步一次状态显示，
        # 并复位校准流程（校准针对单路进行，换路后重来）
        self._reset_calibration_step()
        self.update_cal_status_label()

    def _on_active_channel_changed(self, index):
        """「当前连接」切换：刷新校准状态显示，复位未完成的校准流程。"""
        self._reset_calibration_step()
        self.update_cal_status_label()

    def _reset_calibration_step(self):
        """校准流程中途换路/增删路时复位按钮文案（避免把 A 路零点标到 B 路）。"""
        if self.cal_step != 0:
            self.cal_step = 0
            self.calibrate_btn.setText("校准（CALIBRATE）")

    # ------------------------------------------------------------------
    # 去皮与校准（每路独立）
    # ------------------------------------------------------------------
    def tare_now(self):
        """去皮：把最近若干个采样的平均值记为新的零点（offset），支持反复点击。

        多路连接时对**所有有数据流入的通道**分别去皮，各路零点独立
        （不同 HX711 的空载偏移不同）：
        1. 不要求先「开始采集」——设备连着、有数据流入即可去皮（用各路实时窗口）；
        2. 有线串口照旧向**各自固件**发 TARE 命令（固件内部状态保持同步）；
           模拟器没有这个命令，直接走上位机侧零点；
        3. 可反复点击，每点一次都以当前读数重新归零，没有「取消去皮」。
        """
        targets = [ch for ch in self.channels if ch.live_window]
        if not targets:
            fluent_message_box(self, "提示", "还没有收到数据，等数据流入后再去皮")
            return

        parts = []
        notified = []
        for ch in targets:
            # 上位机侧零点：最近 10 个采样的平均值（比取单点更抗噪声）
            ch.offset = int(round(float(np.mean(ch.live_window))))
            parts.append(f"{ch.name} offset={ch.offset}")
            # 真串口才通知固件（固件回 TARE_DONE 后会用它的 10 次平均值
            # 覆盖上面的零点，以固件为准）
            if self._write_firmware_tare(ch):
                notified.append(ch.name)
        log.info("去皮：%s", "; ".join(parts))
        self.save_config()
        self.update_cal_status_label()
        live_note = "（已通知固件: " + "、".join(notified) + "）" if notified else ""
        self.current_force_label.setText(f"力/质量: 去皮完成{live_note}")
        # 按新零点重算已采集的数据（去皮只改 offset，已存克值按原零点算，
        # 重算保持曲线与新零点一致）
        self.recompute_force_data()

    def _write_firmware_tare(self, ch):
        """向该路固件发送 TARE 命令；仅真串口可用（模拟器没有这个命令）。"""
        thread = ch.thread
        if not (thread and thread.isRunning()):
            return False
        port = getattr(thread, 'serial', None)
        if not (port and port.is_open):
            return False
        try:
            port.write(b"TARE\n")
            return True
        except Exception as e:
            log.warning("固件去皮命令发送失败（%s）：%s", ch.name, e)
            return False

    def update_cal_status_label(self):
        """刷新校准状态标签（多路时逐路显示零点与标定状态）"""
        parts = []
        for ch in self.channels:
            if ch.calibrated:
                parts.append(f"{ch.name}: ✓ 已校准(比例={ch.scale:.6f}, 偏移={ch.offset})")
            else:
                parts.append(f"{ch.name}: 未校准(偏移={ch.offset})")
        if not parts:
            self.cal_status_label.setText("校准状态: 暂无通道")
            self.cal_status_label.setStyleSheet("color: #555; font-weight: bold;")
            return
        calibrated_any = any(ch.calibrated for ch in self.channels)
        self.cal_status_label.setText("校准状态: " + "；".join(parts))
        self.cal_status_label.setStyleSheet(
            "color: #2e7d32; font-weight: bold;" if calibrated_any
            else "color: #555; font-weight: bold;")

    def recompute_force_data(self):
        """零点变化后，按各通道已有 raw_data 重算 force_data"""
        if not any(ch.raw_data for ch in self.channels):
            return
        for ch in self.channels:
            if ch.calibrated:
                ch.force_data = [(r - ch.offset) * ch.scale for r in ch.raw_data]
            else:
                ch.force_data = [float(r) for r in ch.raw_data]
        self.update_stats()
        self.update_chart()
        # 逐路刷新实时行 + 汇总标签（去皮后显示值归零）
        for ch in self.channels:
            live = self._live_rows.get(ch.id)
            if live and ch.force_data:
                live['force_label'].setText(self._format_force_value(ch))
        self._refresh_summary_text()

    def api_actions(self):
        """本模块支持的控制动作（供 DataService / HTTP 层展示）。"""
        return ['tare', 'calibrate']

    def api_command(self, action, params=None):
        """执行模块特有控制动作（由 DataService 保证在 GUI 线程调用）。
        通用动作（start/stop/clear/toggle）返回 None 交给通用动作表。"""
        if action == 'tare':
            if not any(ch.thread for ch in self.channels):
                return {'ok': False, 'message': '设备未连接，无法去皮'}
            if not any(ch.live_window for ch in self.channels):
                return {'ok': False, 'message': '还没有收到数据，无法去皮'}
            self.tare_now()
            offsets = "; ".join(f"{ch.name}={ch.offset}"
                                for ch in self.channels if ch.live_window)
            return {'ok': True, 'message': f'已去皮（{offsets}）'}
        if action == 'calibrate':
            if not any(ch.thread for ch in self.channels):
                return {'ok': False, 'message': '设备未连接，无法校准'}
            self.start_calibration()
            return {'ok': True, 'message': '校准流程已启动（请在界面上继续操作）'}
        return None

    def start_calibration(self):
        """两点标定流程：作用于「当前连接」下拉所选的一路。"""
        ch = self._active_channel_obj() or (self.channels[0] if self.channels else None)
        if ch is None:
            return
        if self.cal_step == 0:
            self.cal_step = 1
            self.calibrate_btn.setText(f"1. {ch.name} 空载，点击记录零点")
        elif self.cal_step == 1:
            # 用实时窗口最新值（未开始采集也能校准）
            if ch.live_window:
                self.cal_raw_before = ch.live_window[-1]
            self.cal_step = 2
            dlg = KnownWeightMessageBox(self.cal_known_weight, self)
            ok = dlg.exec() == QDialog.DialogCode.Accepted
            weight = dlg.weight
            if ok:
                self.cal_known_weight = weight
                self.calibrate_btn.setText(f"2. {ch.name} 已放{weight}g砝码，点击记录")
            else:
                self.cal_step = 0
                self.calibrate_btn.setText("校准（CALIBRATE）")
        elif self.cal_step == 2:
            if ch.live_window:
                self.cal_raw_after = ch.live_window[-1]
                diff = self.cal_raw_after - self.cal_raw_before
                if diff != 0:
                    ch.scale = self.cal_known_weight / diff
                    ch.offset = self.cal_raw_before
                    ch.calibrated = True
                    if self.channels and ch is self.channels[0]:
                        self.scale = ch.scale
                        self.offset = ch.offset
                        self.calibrated = True
                    self.save_config()
                    self.update_cal_status_label()
                    main = self._main_channel()
                    if main is not None and main.calibrated:
                        self.current_unit_label.setText(
                            f"单位: {self.UNIT_LABELS.get(self.current_unit, 'g')}"
                            f"（校准比例={main.scale:.6f}）")
                    log.info("校准完成（%s）：offset=%s, scale=%.6f, 砝码=%.4g g",
                             ch.name, ch.offset, ch.scale, self.cal_known_weight)
                    fluent_message_box(self, "校准成功",
                        f"{ch.name} 校准完成！\n"
                        f"空载ADC: {self.cal_raw_before}\n"
                        f"加载ADC: {self.cal_raw_after}\n"
                        f"ADC差值: {diff}\n"
                        f"校准比例: {ch.scale:.6f}\n"
                        f"砝码质量: {self.cal_known_weight}g")
                    # 按新标定系数重算该路已有数据
                    self.recompute_force_data()
                else:
                    fluent_message_box(self, "校准失败", "ADC差值为0，请检查传感器是否正常工作")

            self.cal_step = 0
            self.calibrate_btn.setText("校准（CALIBRATE）")

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
        """连接/断开时同步合并按钮与浮动栏按钮的可用性。"""
        self.collect_btn.setEnabled(enabled)
        self.float_collect_btn.setEnabled(enabled)

    def _refresh_collect_btn(self):
        """合并按钮与浮动栏按钮：文案随采集状态切换（停止采集/开始采集）。"""
        update_collect_btn(self.collect_btn, self._collecting)
        update_collect_btn(self.float_collect_btn, self._collecting)

    def start_collection(self):
        for ch in self.channels:
            ch.force_data.clear()
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

        self.current_force_label.setText("力/质量: 采集中...")
        for ch in self.channels:
            live = self._live_rows.get(ch.id)
            if live:
                live['raw_label'].setText(f"{ch.name} ADC: 采集中...")

    def stop_collection(self):
        self._collecting = False
        self._refresh_collect_btn()
        total = sum(len(ch.force_data) for ch in self.channels)
        self.save_btn.setEnabled(total > 0)
        log.info("停止采集，共 %d 个数据点", total)

        if total > 0:
            main = self._main_channel()
            if main is not None and main.force_data:
                converted = self.convert_unit(np.mean(main.force_data)) \
                    if main.calibrated else np.mean(main.force_data)
                self.current_force_label.setText(
                    f"{main.name} 均值: {converted:.4f} {self.get_unit_str(main)}")

    def handle_data(self, data, ch):
        """一路连接的数据回调（SerialThread / SimulatorThread → 本模块）。

        多路连接下的约定：
        - ERROR / START / TARE_DONE 按通道处理，出错只断开这一路；
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
                live['force_label'].setText("力/质量: 设备就绪")
                live['raw_label'].setText(f"{ch.name}: 等待数据...")
            return

        if data.startswith("TARE_DONE"):
            parts = data.split(",")
            if len(parts) == 2:
                try:
                    # 固件用 10 次平均得到零点，比上位机单点更稳，以它为准
                    # （只覆盖发出过 TARE 的这一路）
                    ch.offset = int(parts[1])
                    self.save_config()
                    self.update_cal_status_label()
                    live = self._live_rows.get(ch.id)
                    if live:
                        live['force_label'].setText(f"{ch.name}: 去皮完成")
                    log.info("固件去皮完成（%s）：零点 offset=%d", ch.name, ch.offset)
                except (ValueError, TypeError):
                    pass
            return

        if data.startswith("CALIBRATE_READY"):
            live = self._live_rows.get(ch.id)
            if live:
                live['force_label'].setText(f"{ch.name}: 请放置已知质量砝码")
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
        if ch.calibrated:
            force_value_grams = (raw_value - ch.offset) * ch.scale
            force_value = self.convert_unit(force_value_grams)
        else:
            force_value = float(raw_value)
        unit = self.get_unit_str(ch)
        live = self._live_rows.get(ch.id)
        if live:
            live['raw_label'].setText(f"{ch.name} ADC: {raw_value}")
            live['force_label'].setText(f"力/质量: {force_value:.4f} {unit}")
        # 隐藏摘要标签记最新活动的一路（仅供全屏浮动面板折叠态摘要读取）
        self.current_force_label.setText(
            f"{ch.name}: {force_value:.4f} {unit}")

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
        ch.force_data.append(force_value_grams if ch.calibrated else force_value)
        ch.time_data.append(t_rel)

        time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        display_text = (f"{time_str} | {ch.name} | ADC: {raw_value} | "
                        f"{unit}: {force_value:.4f}")
        self.data_text.append(display_text)
        self.data_text.verticalScrollBar().setValue(
            self.data_text.verticalScrollBar().maximum()
        )
        self.update_stats()

    def update_stats(self):
        """统计栏：每路有数据的通道各显示一行统计（按各自校准状态换算）。"""
        parts = []
        for ch in self.channels:
            if not ch.force_data:
                continue
            unit = self.get_unit_str(ch)
            converted_data = ([self.convert_unit(v) for v in ch.force_data]
                              if ch.calibrated else list(ch.force_data))
            avg_force = np.mean(converted_data)
            max_force = np.max(converted_data)
            min_force = np.min(converted_data)
            std_force = np.std(converted_data)
            parts.append(
                f"{ch.name}: 点数 {len(ch.force_data)} | "
                f"平均={avg_force:.4f}{unit} | "
                f"最大={max_force:.4f}{unit} | "
                f"最小={min_force:.4f}{unit} | "
                f"σ={std_force:.4f}")
        if parts:
            self.stats_label.setText("统计: " + " ‖ ".join(parts))

    def update_chart(self):
        if not self.isVisible():
            return  # 页面隐藏时跳过重绘（定时器不停止，避免白耗 UI 线程）
        # 只画勾选显示的通道（图表卡顶部勾选行控制）；勾选不影响采集与统计
        active = [ch for ch in self.channels
                  if ch.force_data and ch.visible]
        if not active:
            # 有数据但全部取消勾选 → 清空图表；本来就没数据 → 保持原样
            if any(ch.force_data for ch in self.channels):
                self.chart.clear_chart()
            return
        ylabel = self.get_chart_ylabel()
        c = self.chart
        c.begin()
        all_t = []
        # 每路一条曲线：颜色 = 各通道行色块上选的颜色，图例 = 通道名
        for ch in active:
            if ch.calibrated:
                converted_data = [self.convert_unit(v) for v in ch.force_data]
            else:
                converted_data = list(ch.force_data)
            c.plot(ch.time_data, converted_data, color=ch.color, width=2,
                   label=f'{ch.name} ({ylabel})')
            all_t.extend(ch.time_data)
        c.set_labels('时间 (秒)', ylabel)
        c.set_title('力传感器实时数据（多路对比）' if len(active) > 1
                    else '力传感器实时数据')
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
        total = sum(len(ch.force_data) for ch in self.channels)
        if total == 0:
            fluent_message_box(self, "警告", "没有数据可保存")
            return
        try:
            unit = self.get_unit_str()
            filename = f"force_sensor_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', encoding='utf-8') as f:
                # 长表格式：一行一个样本 + 通道名列。多路的时间轴天然对齐
                # （主机统一时间戳），便于 Excel 透视/筛选按通道分组分析
                for ch in self.channels:
                    cal_desc = (f"校准 scale={ch.scale:.6f} offset={ch.offset}"
                                if ch.calibrated else "未校准（值为原始ADC）")
                    f.write(f"# {ch.name}: {cal_desc}\n")
                f.write(f"channel,time_s,raw_adc,value,unit\n")
                for ch in self.channels:
                    ch_unit = self.get_unit_str(ch)
                    for i, (time_val, force_val) in enumerate(
                            zip(ch.time_data, ch.force_data)):
                        raw_val = ch.raw_data[i] if i < len(ch.raw_data) else 0
                        converted = (self.convert_unit(force_val)
                                     if ch.calibrated else force_val)
                        f.write(f"{ch.name},{time_val:.3f},{raw_val},"
                                f"{converted:.6f},{ch_unit}\n")

            log.info("数据已保存到：%s（%d 点）", filename, total)
            fluent_message_box(self, "成功",
                                    f"数据已保存到：{filename}\n"
                                    f"共 {total} 个数据点\n"
                                    f"单位：{self.UNIT_LABELS.get(self.current_unit, 'g')}")
        except Exception as e:
            log.error("保存失败：%s", e)
            fluent_message_box(self, "错误", f"保存失败：{e}")

    def clear_data(self):
        for ch in self.channels:
            ch.force_data.clear()
            ch.time_data.clear()
            ch.raw_data.clear()
            ch.last_sample_s = None
        self._t0_mono = None
        self.data_text.clear()
        log.info("已清除数据")
        self.stats_label.setText("统计信息: 暂无数据")
        for ch in self.channels:
            live = self._live_rows.get(ch.id)
            if live:
                live['force_label'].setText("力/质量: --.-")
                live['raw_label'].setText(f"{ch.name} ADC: ------")
        self.current_force_label.setText("力/质量: --.-")
        self.chart.clear_chart()
        self.save_btn.setEnabled(False)

    def _ai_data(self):
        """AI 分析实验数据回调（图表卡「AI分析实验」按钮调用）。

        多路连接时取**数据最多的通道**作为主分析序列，各通道概况与
        每路去皮/标定参数写入 params，供模型理解多路对比背景。
        """
        active = [ch for ch in self.channels if ch.force_data]
        if not active:
            return None
        main = max(active, key=lambda c: len(c.force_data))
        # 已校准时 force_data 存克值，按显示单位换算后与 y_label 保持一致；
        # 未校准时为原始 ADC 值
        display = ([self.convert_unit(v) for v in main.force_data]
                   if main.calibrated else list(main.force_data))
        channels_desc = "、".join(
            f"{ch.name}[{len(ch.force_data)}点"
            + (f"/去皮{ch.offset}/标定{ch.scale:.4g}g/计数" if ch.calibrated
               else f"/未校准(零点{ch.offset})") + "]"
            for ch in active)
        return {
            'title': '力传感器',
            'x_label': '时间 (秒)',
            'y_label': self.get_chart_ylabel(),
            'points': list(zip(main.time_data, display)),
            'params': (
                f"传感器=HX711（24 位 ADC）+ 应变片, "
                f"主分析通道={main.name}, "
                f"去皮 offset={main.offset}, "
                f"标定 scale={main.scale:.6f} 克/计数, 砝码质量={self.cal_known_weight}g, "
                f"已校准={main.calibrated}"
                + ("" if main.calibrated else "（未校准时数据为原始 ADC 值）")
                + f", 显示单位={self.current_unit}, 重力加速度 g=9.8m/s², "
                f"原始 ADC 范围=±8388607（24 位有符号）, "
                f"多路连接: 共{len(active)}路（{channels_desc}），"
                f"各路去皮零点与标定系数独立, "
                f"采样间隔={main.sample_interval_ms}ms（各路独立）"),
            'system_prompt': AI_SYSTEM_PROMPT,
        }

    def api_snapshot(self):
        """当前实验数据快照（供 core.DataService 任意线程读取）。
        禁止调用任何 Qt 方法：只读模块自身的 Python 数据。"""
        d = self._ai_data() or {}
        points = list(d.get('points') or [])
        latest = None
        main = self._main_channel()
        if points:
            t, y = points[-1]
            latest = {'t': t, 'y': y,
                      'raw': main.raw_data[-1] if (main and main.raw_data) else None}
        return {
            'key': 'force_sensor',
            'name': '力传感器',
            'connected': any(ch.thread is not None for ch in self.channels),
            'collecting': self._collecting,
            'x_label': d.get('x_label', '时间 (秒)'),
            'y_label': d.get('y_label', '力'),
            'params': d.get('params', {}),
            'points': points,
            'latest': latest,
            # 多路连接明细（points 仍为主通道序列，前端单曲线不破）
            'channels': [
                {'name': ch.name, 'color': ch.color,
                 'connected': ch.thread is not None,
                 'points_n': len(ch.force_data),
                 'calibrated': ch.calibrated,
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
