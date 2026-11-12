# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

# === MODULE META ===
# key: ph_sensor
# icon: pH
# name: pH传感器
# category: chemistry
# class: PhSensorWidget
# kernel: _kernel:PhKernel
# ===================

# -*- coding: utf-8 -*-
"""pH 传感器模块 — 测量溶液酸碱度（SEN0161）。

多路连接：每路独立选择串口/模拟器、独立校准参数（不同电极各自的
pH↔ADC 拟合）、独立采样频率，多路数据以主机统一时间戳叠加画在同一张
图上（架构与电压模块一致，见 docs/multi-channel-design.md）。
"""

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
    BodyLabel, CaptionLabel, FluentIcon as FIF,
    FlowLayout, LineEdit, ToolButton, CheckBox,
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
    CalibrationMessageBox,
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

log = get_logger("ph_sensor")

# AI 分析实验：模块专属系统提示词（进入 AI 分析时随实验信息与数据发送给模型，
# 由 core.build_ai_system_prompt 组装进 system 消息）
AI_SYSTEM_PROMPT = (
    "你是一位资深化学实验指导教师与水质分析专家，正在协助分析 SEN0161 pH 电极"
    "（ESP32-S3，12 位 ADC，0~4095）的实验数据。"
    "测量原理：pH 电极电位满足能斯特方程，电极本身 25℃ 斜率约 −59.16 mV/pH，"
    "SEN0161 放大板 PO 输出等效斜率约 −280 mV/pH（单点校准的理论斜率可在校准框中配置）；模块将电极"
    "模拟输出换算为 ADC 值后，用单点/两点/三点校准拟合"
    "pH 与 ADC 的关系（线性或二次多项式），再由 ADC 反算 pH。多路连接时各电极的"
    "校准参数互相独立（不同电极老化程度与偏移不同）。"
    "数据特征：电极稳定后读数应平稳（波动通常 <0.1 pH）；缓冲液中校准后偏差应很小；"
    "持续单向漂移多为电极老化、参比液干涸或温度变化；阶跃跳动多为搅拌、气泡或接触"
    "问题；温度变化会引起斜率与零点漂移。"
    "常见误差来源：电极老化与污染、参比液干涸、未做温度补偿、搅拌不均、缓冲液失效或"
    "交叉污染、读数未稳定即记录、ADC 噪声与接地干扰。"
    "分析要求：①先评估稳定性：漂移速率、噪声幅度、跳变点及发生时刻；②结合校准点数、"
    "校准液与拟合方式判断系统偏差来源；③估算稳定时间与不确定度；④给出电极保养"
    "（浸泡液、清洗）、重新校准、温度补偿与实验步骤改进的具体建议。"
)

# 多路连接的默认曲线配色（按新建顺序轮换取未用色，界面上可单独改色）
CHANNEL_COLORS = ('#0078d4', '#e74c3c', '#2ecc71', '#f39c12',
                  '#9b59b6', '#00bcd5', '#e67e22', '#16a085')

# 颜色下拉中「自定义…」项的 userData 标记（选中后弹 Fluent 取色对话框）
CUSTOM_COLOR_KEY = '__custom__'

# 单点/两点/三点校准的显示名
CAL_MODE_NAMES = {1: "单点校准", 2: "两点校准", 3: "三点校准"}


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


class PhSensorWidget(QWidget):
    """pH传感器模块界面 - 支持多路连接、逐路单点/两点/三点校准"""

    def __init__(self, kernel=None):
        super().__init__()
        # 内核由加载器注入；直接实例化时用同目录 _kernel.py 兜底
        self.kernel = kernel or self._create_default_kernel()
        self.channels = self.kernel.channels
        self._collecting = False
        self._rows = {}              # channel.id -> 行控件引用 dict
        self.sample_interval_ms = self.kernel.sample_interval_ms

        self.init_ui()
        self._build_channels_from_kernel()

    @staticmethod
    def _create_default_kernel():
        """不经过 main.py 加载器时，直接加载同目录内核文件。"""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            '_kernel.py')
        spec = importlib.util.spec_from_file_location(
            '_sensor_kernel_ph', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.PhKernel()

    # ------------------------------------------------------------------
    # 配置（委托内核）
    # ------------------------------------------------------------------
    def load_config(self):
        return self.kernel.config

    def save_config(self):
        return self.kernel.save_config()

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
        title = TitleLabel("pH")
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
            "增加一路 pH 电极连接：\n"
            "每路可单独选择「有线串口 / 模拟器」，单独连接/断开，\n"
            "单独换曲线颜色与校准参数；多路数据叠加画在同一张图上")
        self.add_channel_btn.clicked.connect(lambda: self.add_channel())
        self.card_conn.add_header_widget(self.add_channel_btn)
        # 主卡展开动画结束后按子卡实际高度收敛（子卡折叠后 sizeHint 不缩）
        self.card_conn.expandAni.finished.connect(self._sync_conn_card_height)
        layout.addWidget(self.card_conn)

        # ========== 卡片2：校准参数（可折叠，按连接独立） ==========
        card_cal_content = QWidget()
        card_cal_content.setObjectName("card")
        card_cal_content.setStyleSheet(card_style())
        cal_card_layout = QVBoxLayout(card_cal_content)
        cal_card_layout.setContentsMargins(20, 4, 20, 16)
        cal_card_layout.setSpacing(12)

        # 校准点明细：显示「当前连接」下拉所选路的校准点
        self.cal_text = CaptionLabel("未设置校准参数")
        cal_card_layout.addWidget(self.cal_text)

        self.edit_cal_btn = PushButton("✏️ 编辑校准参数")
        self.edit_cal_btn.setFixedHeight(36)
        self.edit_cal_btn.setToolTip("编辑「当前连接」下拉所选路的校准点\n"
                                     "（不同电极各自一套 pH↔ADC 拟合）")
        self.edit_cal_btn.clicked.connect(self.edit_calibration)
        cal_btn_row = QHBoxLayout()
        cal_btn_row.addWidget(self.edit_cal_btn)
        cal_btn_row.addStretch()
        cal_card_layout.addLayout(cal_btn_row)

        card_cal = FluentCard("校准参数", card_cal_content, expanded=True, icon=FIF.EDIT)
        self.card_cal = card_cal
        # header 右侧：「当前连接」下拉——校准参数按路独立，切换后显示所选路
        self._active_channel_combo = ComboBox()
        self._active_channel_combo.setMinimumWidth(110)
        self._active_channel_combo.setToolTip(
            "校准参数按连接独立设置：\n切换后显示所选路的校准点，编辑也作用于所选路")
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
        self.current_ph_label = BodyLabel("pH: --.-")
        self.current_ph_label.setFont(QFont("Cascadia Code", 14, QFont.Weight.Bold))
        self.current_ph_label.setStyleSheet("color: #0078d4;")
        self.current_ph_label.setParent(self)
        self.current_ph_label.hide()

        # 每路一行实时明细（通道增删时动态重建，见 _build_live_row）
        self._live_rows = {}          # channel.id -> {row, name_label, ph_label, adc_label}
        self._live_container = QWidget()
        self._live_layout = QVBoxLayout(self._live_container)
        self._live_layout.setContentsMargins(0, 0, 0, 0)
        self._live_layout.setSpacing(4)
        data_card_layout.addWidget(self._live_container)

        self.stats_label = CaptionLabel("统计信息：暂无数据")
        data_card_layout.addWidget(self.stats_label)

        card_data = FluentCard("实时数据", card_data_content, expanded=True, icon=FIF.HISTORY)
        self.card_data = card_data

        # 校准参数 + 实时数据 并排同一行（顶部对齐，各自按内容高度，不强制等高）
        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)
        cards_row.addWidget(card_cal, stretch=1, alignment=Qt.AlignmentFlag.AlignTop)
        cards_row.addWidget(card_data, stretch=1, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(cards_row)

        # ========== 卡片4：pH-时间曲线（可全屏） ==========
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
        card_chart = CollapsibleCard("pH-时间曲线", card_chart_content, expanded=True, fullscreen=True)
        # 图表卡片加高为原来的 2 倍（内容区最小 400px），页面滚动查看
        card_chart.set_chart_min_height(400)
        # 全屏时：数据记录区作为可拖动折叠浮动面板浮于图表上方，折叠时显示实时 pH 值
        # 全屏浮动栏：合并的开始/停止按钮（与操作按钮卡的 collect_btn 同步状态）
        self.float_collect_btn = PrimaryPushButton("开始采集")
        self.float_collect_btn.setFixedHeight(34)
        update_collect_btn(self.float_collect_btn, False)
        self.float_collect_btn.clicked.connect(self.toggle_collection)
        self.float_collect_btn.setEnabled(False)
        # 全屏时：数据记录 + 拟合分析面板浮于图表上方，浮动栏底部可控制开始/停止
        card_chart.set_fullscreen_overlay(
            self.data_text, self.current_ph_label,
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

        # 内核事件队列：后台采集线程只入队，GUI 线程由 QTimer 消费
        self._events = self.kernel.subscribe()
        self._event_timer = QTimer(self)
        self._event_timer.timeout.connect(self._drain_kernel_events)
        self._event_timer.start(50)

    # ============================================================
    # 多路连接管理：通道的增删 / 行控件 / 单路连接控制
    # ============================================================
    def _build_channels_from_kernel(self):
        """按内核已有通道重建 UI 行（内核负责配置恢复与拟合系数）。"""
        for ch in self.channels:
            self._build_channel_card(ch)
            self._build_live_row(ch)
        self._refresh_active_channel_combo()
        self._refresh_chart_visibility_row()
        self._update_delete_btns()
        self._sync_compat_aliases()
        self._refresh_cal_text()
        self._refresh_summary_text()

    def _make_channel(self, color=None, mode='serial', port='', name=None,
                      sample_interval_ms=None, cal_params=None):
        """创建内核通道，并为它建立对应的 UI 子卡/实时行。"""
        ch = self.kernel.add_channel(
            color=color, mode=mode, port=port, name=name,
            sample_interval_ms=sample_interval_ms,
            cal_params=cal_params)
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
        """为通道创建一行实时明细：名称+大字pH（通道色） | ADC。

        多路同屏各占一行，不再互相覆盖；顶部不再有共享汇总位。
        """
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(16)

        name_label = CaptionLabel(ch.name)
        h.addWidget(name_label)

        ph_label = BodyLabel("pH: --.-")
        ph_label.setFont(QFont("Cascadia Code", 20, QFont.Weight.Bold))
        ph_label.setStyleSheet(f"color: {ch.color};")
        h.addWidget(ph_label)

        h.addStretch()

        adc_label = CaptionLabel(f"{ch.name} ADC: ----")
        adc_label.setFont(QFont("Cascadia Code", 11))
        h.addWidget(adc_label)

        self._live_layout.addWidget(row)
        self._live_rows[ch.id] = {
            'row': row, 'name_label': name_label,
            'ph_label': ph_label, 'adc_label': adc_label,
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

    def _refresh_summary_text(self):
        """隐藏摘要标签取「最近一路有数据的通道」最新值（供全屏折叠摘要）。"""
        for ch in reversed(self.channels):
            if ch.ph_data:
                self.current_ph_label.setText(f"{ch.name}: {ch.ph_data[-1]:.2f}")
                return
        self.current_ph_label.setText("pH: --.-")

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
        self.kernel.notify_change(ch.id)
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

    def _apply_channel_color(self, ch):
        """把通道曲线颜色同步到该路实时行的大字标签。"""
        live = self._live_rows.get(ch.id)
        if live:
            live['ph_label'].setStyleSheet(f"color: {ch.color};")

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
        self.kernel.notify_change(ch.id)
        self.update_chart()
        # 实时行大字颜色同步为新通道色
        live = self._live_rows.get(ch.id)
        if live:
            live['ph_label'].setStyleSheet(f"color: {ch.color};")

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
            live['adc_label'].setText(f"{ch.name} ADC: ----")
        self._refresh_active_channel_combo()
        self._refresh_chart_visibility_row()
        self.kernel.notify_change(ch.id)
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
        self.kernel.notify_change(ch.id)

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
        live = self._live_rows.get(ch.id)
        if live:
            live['ph_label'].setText("pH: --.-")
            live['adc_label'].setText(f"{ch.name}: 连接中...")

    def _disconnect_channel(self, ch):
        """断开单路（其余通道不受影响）。"""
        self.kernel.disconnect(ch.id)
        refs = self._rows.get(ch.id)
        if refs:
            refs['connect_btn'].setText("连接")
        log.info("%s 已断开", ch.name)
        live = self._live_rows.get(ch.id)
        if live:
            live['ph_label'].setText("pH: --.-")
            live['adc_label'].setText(f"{ch.name} ADC: 已断开")
        self._refresh_summary_text()
        if not self.kernel.connected_any():
            self._set_collect_enabled(False)

    def connect_device(self):
        """连接全部未连接的通道（网页端 set_connection connect=true 走这里）。"""
        self.kernel.connect_all()
        for ch in self.channels:
            refs = self._rows.get(ch.id)
            if refs:
                refs['connect_btn'].setText(
                    "断开" if getattr(ch, 'connected', False) else "连接")
        self._set_collect_enabled(self.kernel.connected_any())

    def disconnect_all(self):
        """断开全部通道（退出清理 / 网页端命令也走这里）。"""
        self.kernel.disconnect_all()
        for ch in self.channels:
            refs = self._rows.get(ch.id)
            if refs:
                refs['connect_btn'].setText("连接")
        self._set_collect_enabled(False)

    # ------------------------------------------------------------------
    # 当前连接（校准参数卡）
    # ------------------------------------------------------------------
    def _active_channel_obj(self):
        """校准参数卡当前选中的通道对象（无通道/未初始化返回 None）。"""
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
        # 选中项可能变了（删除了原选中通道）：同步一次校准点明细显示
        self._refresh_cal_text()

    def _on_active_channel_changed(self, index):
        """「当前连接」切换：校准点明细切换为所选路。"""
        self._refresh_cal_text()

    def _refresh_cal_text(self):
        """校准点明细标签：显示「当前连接」所选路的校准点。"""
        ch = self._active_channel_obj()
        if ch is None:
            self.cal_text.setText("未设置校准参数")
            return
        cal_lines = []
        for ph_val, adc_val in ch.calibration_points:
            cal_lines.append(f"• pH {ph_val:.2f} → ADC {adc_val}")
        if ch.calibration_mode == 1 and cal_lines:
            cal_lines.append(f"• 理论斜率 {ch.theoretical_slope_mv:g} mV/pH")
        cal_lines.append(f"• {CAL_MODE_NAMES.get(ch.calibration_mode, f'{ch.calibration_mode}点校准')}"
                         f"（{ch.name}）")
        self.cal_text.setText("\n".join(cal_lines) if cal_lines else "未设置校准参数")

    # ------------------------------------------------------------------
    # 连接管理 / 采集控制
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
        """开始数据采集（数据清空与时间基准由内核负责）。"""
        self.kernel.start_collection()
        self._apply_started_ui()

    def _apply_started_ui(self):
        """采集已开始：清空上一轮显示并切到采集状态。"""
        self._collecting = True
        self.data_text.clear()
        self._refresh_collect_btn()
        self.save_btn.setEnabled(False)
        log.info("开始采集（已连接 %d 路）",
                 sum(1 for ch in self.channels
                     if getattr(ch, 'connected', False)))
        self.current_ph_label.setText("pH: 采集中...")
        for ch in self.channels:
            live = self._live_rows.get(ch.id)
            if live:
                live['adc_label'].setText(f"{ch.name} ADC: 采集中...")

    def stop_collection(self):
        """停止数据采集。"""
        self.kernel.stop_collection()
        self._apply_stopped_ui()

    def _apply_stopped_ui(self):
        """采集已停止：刷新按钮与汇总标签。"""
        self._collecting = False
        self._refresh_collect_btn()
        total = sum(len(ch.ph_data) for ch in self.channels)
        self.save_btn.setEnabled(total > 0)
        log.info("停止采集，共 %d 个数据点", total)
        if total > 0:
            main = max((ch for ch in self.channels if ch.ph_data),
                       key=lambda c: len(c.ph_data))
            avg_ph = np.mean(main.ph_data)
            self.current_ph_label.setText(f"{main.name} 均值: {avg_ph:.2f}")

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

        if kind == EVENT_SAMPLE_PREVIEW and ch is not None:
            value = data.get('value')
            raw = data.get('raw')
            live = self._live_rows.get(ch.id)
            if live and value is not None:
                live['ph_label'].setText(f"pH: {value:.2f}")
                live['adc_label'].setText(f"{ch.name} ADC: {int(raw)}")
            if value is not None:
                self.current_ph_label.setText(f"{ch.name}: {value:.2f}")
            return

        if kind == EVENT_SAMPLE_RECORDED and ch is not None:
            value = data.get('value')
            raw = data.get('raw')
            if value is None:
                return
            time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            self.data_text.append(
                f"{time_str} | {ch.name} | ADC: {int(raw)} | pH: {value:.2f}")
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
                    live['ph_label'].setText("pH: --.-")
                    live['adc_label'].setText(f"{ch.name}: {msg}")
                else:
                    live['ph_label'].setText("pH: --.-")
                    live['adc_label'].setText(f"{ch.name} ADC: 已断开")
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
            self._refresh_cal_text()
            return

        if kind == EVENT_ERROR and ch is not None:
            message = data.get('message', '')
            log.error("%s 设备错误: %s", ch.name, message)
            fluent_message_box(self, "串口错误", f"{ch.name}: {message}")
            return

    def update_stats(self):
        """统计栏：每路有数据的通道各显示一行统计。"""
        parts = []
        for ch in self.channels:
            if not ch.ph_data:
                continue
            avg_ph = np.mean(ch.ph_data)
            max_ph = np.max(ch.ph_data)
            min_ph = np.min(ch.ph_data)
            std_ph = np.std(ch.ph_data)
            parts.append(
                f"{ch.name}: 点数 {len(ch.ph_data)} | "
                f"平均 pH={avg_ph:.2f} | "
                f"最大 pH={max_ph:.2f} | "
                f"最小 pH={min_ph:.2f} | "
                f"σ={std_ph:.3f}")
        if parts:
            self.stats_label.setText("统计: " + " ‖ ".join(parts))

    def update_chart(self):
        """更新pH值图表（双引擎统一 API，多路叠加）"""
        if not self.isVisible():
            return  # 页面隐藏时跳过重绘（定时器不停止，避免白耗 UI 线程）
        # 只画勾选显示的通道（图表卡顶部勾选行控制）；勾选不影响采集与统计
        active = [ch for ch in self.channels
                  if ch.ph_data and ch.visible]
        if not active:
            # 有数据但全部取消勾选 → 清空图表；本来就没数据 → 保持原样
            if any(ch.ph_data for ch in self.channels):
                self.chart.clear_chart()
            return
        c = self.chart
        c.begin()
        all_t = []
        # 每路一条曲线：颜色 = 各通道行色块上选的颜色，图例 = 通道名
        for ch in active:
            c.plot(ch.time_data, ch.ph_data, color=ch.color, width=2,
                   label=ch.name)
            all_t.extend(ch.time_data)
        # 参考线（中性pH=7）
        c.hline(7.0, color='r', style='dash', alpha=0.5, label='中性(pH=7)')
        c.set_labels('时间 (秒)', 'pH值')
        c.set_title('pH传感器实时数据（多路对比）' if len(active) > 1
                    else 'pH传感器实时数据')
        c.set_ylim(0, 14)
        c.legend()
        # 自动调整坐标轴范围
        if len(all_t) > 1:
            c.set_xlim(min(all_t), max(all_t))
        c.end()

    def save_data(self):
        """保存数据到文件（由内核生成 CSV）。"""
        total = sum(len(ch.ph_data) for ch in self.channels)
        if total == 0:
            fluent_message_box(self, "警告", "没有数据可保存")
            return
        try:
            filename = self.kernel.export_csv()
            log.info("数据已保存到：%s（%d 点）", filename, total)
            fluent_message_box(self, "成功",
                               f"数据已保存到：{filename}\n"
                               f"共 {total} 个数据点")
        except Exception as e:
            log.error("保存失败：%s", e)
            fluent_message_box(self, "错误", f"保存失败：{e}")

    def _on_channel_sample_interval_changed(self, ch, interval_ms):
        """本路采样频率改变：更新该路间隔并保存配置。"""
        ch.sample_interval_ms = interval_ms
        if self.channels and ch is self.channels[0]:
            self.sample_interval_ms = interval_ms
            self.kernel.sample_interval_ms = interval_ms
        self.kernel.notify_change(ch.id)

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
        self.stats_label.setText("统计信息: 暂无数据")
        for ch in self.channels:
            live = self._live_rows.get(ch.id)
            if live:
                live['ph_label'].setText("pH: --.-")
                live['adc_label'].setText(f"{ch.name} ADC: ----")
        self.current_ph_label.setText("pH: --.-")
        self.chart.clear_chart()
        self.save_btn.setEnabled(False)

    def edit_calibration(self):
        """编辑校准参数对话框（作用于「当前连接」下拉所选的一路）。"""
        ch = self._active_channel_obj() or (self.channels[0] if self.channels else None)
        if ch is None:
            return
        dialog = CalibrationMessageBox(
            ch.calibration_points, self,
            theoretical_slope=ch.theoretical_slope_mv)
        if dialog.exec() == 1:  # QDialog.Accepted
            new_points = dialog.get_calibration_points()
            res = self.kernel.set_calibration(
                ch.id, new_points,
                mode=dialog.get_calibration_mode(),
                theoretical_slope_mv=dialog.get_theoretical_slope())
            if not res.get('ok'):
                fluent_message_box(self, "错误",
                                   res.get('message', '校准参数无效'))
                return
            self._refresh_cal_text()
            log.info("校准参数已更新（%s）：%s 点 %s",
                     ch.name, ch.calibration_mode, new_points)
            fluent_message_box(self, "成功",
                               f"{ch.name} 校准参数已更新并保存！\n"
                               f"新的校准曲线将立即生效。\n"
                               f"下次启动程序时会自动加载此配置。")

    def _ai_data(self):
        """AI 分析实验数据回调（数据由内核生成，View 只补系统提示词）。"""
        data = self.kernel.ai_data()
        if not data:
            return None
        data = dict(data)
        data['system_prompt'] = AI_SYSTEM_PROMPT
        return data

    def api_actions(self):
        """本模块支持的控制动作（供 KernelRegistry / HTTP 层展示）。"""
        return self.kernel.actions()

    def api_command(self, action, params=None):
        """执行控制动作（由 KernelRegistry 直接调用内核）。"""
        return self.kernel.command(action, params)

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
