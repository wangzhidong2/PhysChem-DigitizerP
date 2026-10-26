# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

# === MODULE META ===
# icon: x
# icon_file: icon.svg
# name: 超声波位移
# category: physics
# class: UltrasonicWidget
# ===================

# -*- coding: utf-8 -*-
"""超声波位移传感器模块 — 测量物体位移和运动轨迹。

多路连接：每路独立选择串口/模拟器、独立采样频率，多路距离数据以主机
统一时间戳叠加画在同一张图上（架构与电压模块一致，
见 docs/multi-channel-design.md；超声波为单通道固件，多路 = 多个 ESP32）。
"""

import sys
import os
import time
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
    fluent_message_box, ChartPanel,
    SerialThread, SampleRateComboBox, SimulatorThread,
    stop_thread,
    load_sensor_config, save_sensor_config,
    SERIAL_AVAILABLE, list_serial_ports, serial_unavailable_hint,
    card_style, primary_btn_style, accent_btn_style,
    modern_combo_style, CollapsibleCard, FluentCard, ExpandableTextEdit,
    scroll_area_style, page_bg_style, apply_module_theme,
    update_collect_btn, set_action_button_width,
    get_logger,
)

log = get_logger("ultrasonic_displacement")

# AI 分析实验：模块专属系统提示词（进入 AI 分析时随实验信息与数据发送给模型，
# 由 core.build_ai_system_prompt 组装进 system 消息）
AI_SYSTEM_PROMPT = (
    "你是一位资深物理实验指导教师与运动学分析专家，正在协助分析 HC-SR04 超声波"
    "测距/位移实验数据。"
    "测量原理：距离 = 回波时间(µs) ÷ 58（cm），对应声速约 340 m/s 的往返换算；"
    "声速随温度变化约 +0.6 m/s 每 ℃（≈ +0.17%/℃）。固件有效回波窗口约 "
    "100~60000 µs（约 2~100 cm），最小触发间隔约 20 ms，无回波时不输出数据。"
    "多路连接时各路时间轴以主机统一时间戳对齐（不同 ESP32 开机时刻不同，"
    "固件毫秒数不可跨路比较），可做多点位位移同步对比。"
    "数据特征：静止目标读数在真实距离附近抖动（±0.3 cm 级）；测量面倾斜或柔软、"
    "过近/过远会输出野值或丢数；快速运动时可能丢波产生离群点。"
    "常见误差来源：回波时间量化与抖动、测量面倾斜或多径反射、遮挡、温度影响、"
    "量程边界、采样周期与运动速度不匹配（混叠）。"
    "分析要求：①先用物理量程与相邻点一致性判据标注/剔除野值，并说明判据；"
    "②分析位移趋势与稳定性，计算平均速度及其波动；③结合实验场景（自由落体、匀速"
    "运动、振动等）对照理想模型（如 s=½gt²、匀速直线）做拟合与残差分析；"
    "④给出采样率、温度修正、多次平均、测量面与安装角度等改进建议。"
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

    每路连接独立选择「有线串口 / 模拟器」、独立串口、独立曲线颜色；
    数据按主机统一时间戳记录（见 handle_data）。
    超声波为单通道固件，多路 = 多个 ESP32。
    UI 行控件引用由模块统一保管在 _rows[channel.id] 里。
    """

    def __init__(self, cid, name, color, mode='serial', port='',
                 sample_interval_ms=100):
        self.id = cid                      # 稳定 id（信号绑定用，删除后不复用）
        self.name = name                    # 显示名（可自定义，留空回退默认名）
        self.default_name = name            # 默认名（通道N，创建时定序）
        self.color = color                  # 曲线颜色
        self.mode = mode                    # 'serial' | 'simulator'
        self.port = port                    # 串口模式下选中的端口
        self.thread = None                  # SerialThread / SimulatorThread
        self.sample_interval_ms = sample_interval_ms  # 本路采样间隔（每路独立）
        self.visible = True                 # 图表显示开关（勾选框控制）
        # 采集数据
        self.time_data = []                 # 相对时间（秒，主机统一时间戳）
        self.data_points = []               # 距离（厘米）
        self.echo_data = []                 # 原始回波时间（µs）
        # 上次记录样本的主机相对秒（采样间隔过滤，每路独立）
        self.last_sample_s = None


class UltrasonicWidget(QWidget):
    """超声波位移模块界面（多路连接）"""

    def __init__(self):
        super().__init__()
        self._collecting = False  # 当前是否在采集（合并开始/停止按钮状态）
        # 多路连接：每路一个 _Channel（独立模式/串口/颜色/数据）
        self.channels = []
        self._rows = {}              # channel.id -> 行控件引用 dict
        self._next_channel_id = 1   # 稳定 id 分配器（删除后不复用）
        self._next_channel_seq = 1  # 显示名序号（通道N）
        self._t0_mono = None        # 采集期主机统一时间基准（首个样本时刻）

        # 采样频率设置（毫秒）—— 模块级镜像字段（始终与第 1 路一致）
        self.sample_interval_ms = 100  # 默认 100ms (10Hz)

        self.config = self.load_config()
        self.init_ui()
        # 恢复上次的通道列表（含模式/串口/颜色）；无记录时建一路默认通道
        self._restore_channels()

    # ------------------------------------------------------------------
    # 配置读写
    # ------------------------------------------------------------------
    def load_config(self):
        config = load_sensor_config('ultrasonic_displacement')
        if config:
            self.sample_interval_ms = config.get('sample_interval_ms', 100)
        return config

    def save_config(self):
        first = self.channels[0] if self.channels else None
        config = {
            'sample_interval_ms': first.sample_interval_ms if first else self.sample_interval_ms,
            # 多路连接：每路的模式/串口/颜色/采样间隔/图表显示
            'channels': [
                {'name': ch.name, 'mode': ch.mode, 'port': ch.port,
                 'color': ch.color, 'sample_interval_ms': ch.sample_interval_ms,
                 'visible': ch.visible}
                for ch in self.channels
            ],
        }
        return save_sensor_config('ultrasonic_displacement', config)

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
        title = TitleLabel("超声波位移")
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
            "增加一路 HC-SR04 连接：\n"
            "每路可单独选择「有线串口 / 模拟器」，单独连接/断开，\n"
            "单独换曲线颜色；多路距离数据叠加画在同一张图上\n"
            "（超声波为单通道固件，多路 = 多个 ESP32）")
        self.add_channel_btn.clicked.connect(lambda: self.add_channel())
        self.card_conn.add_header_widget(self.add_channel_btn)
        # 主卡展开动画结束后按子卡实际高度收敛（子卡折叠后 sizeHint 不缩）
        self.card_conn.expandAni.finished.connect(self._sync_conn_card_height)
        layout.addWidget(self.card_conn)

        # ========== 卡片2：实时数据（可折叠，每路一行同屏） ==========
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
        self.current_data_label = BodyLabel("等待连接...")
        self.current_data_label.setFont(QFont("Cascadia Code", 14, QFont.Weight.Bold))
        self.current_data_label.setStyleSheet("color: #444444;")
        self.current_data_label.setParent(self)
        self.current_data_label.hide()

        # 每路一行实时明细（通道增删时动态重建，见 _build_live_row）
        self._live_rows = {}          # channel.id -> {row, name_label, dist_label, echo_label}
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

        # ========== 卡片3：图表 + 数据记录（可折叠） ==========
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
        card_chart = CollapsibleCard("距离-时间曲线", card_chart_content, expanded=True, fullscreen=True)
        # 图表卡片加高为原来的 2 倍（内容区最小 400px），页面滚动查看
        card_chart.set_chart_min_height(400)
        # 全屏时：数据记录区作为可拖动折叠浮动面板浮于图表上方，折叠时显示实时位移值
        # 全屏浮动栏：合并的开始/停止按钮（与操作按钮卡的 collect_btn 同步状态）
        self.float_collect_btn = PrimaryPushButton("开始采集")
        self.float_collect_btn.setFixedHeight(34)
        update_collect_btn(self.float_collect_btn, False)
        self.float_collect_btn.clicked.connect(self.toggle_collection)
        self.float_collect_btn.setEnabled(False)
        # 全屏时：数据记录 + 拟合分析面板浮于图表上方，浮动栏底部可控制开始/停止
        card_chart.set_fullscreen_overlay(
            self.data_text, self.current_data_label,
            extra_widgets=[self.chart.get_analysis_panel()],
            footer_widget=self.float_collect_btn)
        layout.addWidget(card_chart)

        # ========== 卡片4：操作按钮（可折叠） ==========
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

        # 定时器用于更新图表
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_chart)
        self.timer.start(100)

    # ============================================================
    # 多路连接管理：通道的增删 / 行控件 / 单路连接控制
    # ============================================================
    def _restore_channels(self):
        """按配置重建通道行；无记录时建一路默认通道。"""
        saved = (self.config or {}).get('channels') or []
        if saved:
            for item in saved:
                mode = item.get('mode', 'serial')
                if mode != 'simulator' and not SERIAL_AVAILABLE:
                    mode = 'simulator'   # pyserial 缺失时优雅降级
                self._make_channel(
                    name=item.get('name') or None,
                    color=item.get('color') or None,
                    mode=mode, port=item.get('port', ''),
                    sample_interval_ms=item.get('sample_interval_ms'),
                    visible=item.get('visible', True))
        else:
            self._make_channel(mode='serial' if SERIAL_AVAILABLE else 'simulator')
        if self.channels:
            self.sample_interval_ms = self.channels[0].sample_interval_ms
        self._sync_compat_aliases()
        self._refresh_summary_text()

    def _make_channel(self, color=None, mode='serial', port='', name=None,
                      sample_interval_ms=None, visible=True):
        """创建通道对象 + 对应 UI 行（不重复使用已删除通道的 id/name）。"""
        cid = self._next_channel_id
        self._next_channel_id += 1
        seq = self._next_channel_seq
        self._next_channel_seq += 1
        if not color:
            used = {ch.color for ch in self.channels}
            color = next((c for c in CHANNEL_COLORS if c not in used),
                         CHANNEL_COLORS[(seq - 1) % len(CHANNEL_COLORS)])
        ch = _Channel(cid, name or f"通道{seq}", color, mode=mode, port=port,
                      sample_interval_ms=sample_interval_ms or self.sample_interval_ms)
        ch.visible = bool(visible)
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
        self.save_config()
        self._sync_conn_card_height()

    def _build_live_row(self, ch):
        """为通道创建一行实时明细：名称+大字距离（通道色） | 回波时间。

        多路同屏各占一行，不再互相覆盖；顶部不再有共享汇总位。
        """
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(16)

        name_label = CaptionLabel(ch.name)
        h.addWidget(name_label)

        dist_label = BodyLabel("--.-- cm")
        dist_label.setFont(QFont("Cascadia Code", 20, QFont.Weight.Bold))
        dist_label.setStyleSheet(f"color: {ch.color};")
        h.addWidget(dist_label)

        h.addStretch()

        echo_label = CaptionLabel(f"{ch.name} 回波: ---- µs")
        echo_label.setFont(QFont("Cascadia Code", 11))
        h.addWidget(echo_label)

        self._live_layout.addWidget(row)
        self._live_rows[ch.id] = {
            'row': row, 'name_label': name_label,
            'dist_label': dist_label, 'echo_label': echo_label,
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
            if ch.data_points:
                self.current_data_label.setText(
                    f"{ch.name}: {ch.data_points[-1]:.2f}cm")
                return
        self.current_data_label.setText("等待连接...")

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
            live['dist_label'].setStyleSheet(f"color: {ch.color};")

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
            live['echo_label'].setText(f"{ch.name} 回波: ---- µs")
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
                # echo_time 100~60000µs（约 1.7cm~1m），在 11600µs(约20cm)附近漂移
                th = SimulatorThread(
                    value_min=100, value_max=60000,
                    interval_ms=ch.sample_interval_ms,
                    start_value=11600, timestamp_scale=1000)
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
        live = self._live_rows.get(ch.id)
        if live:
            live['dist_label'].setText("--.-- cm")
            live['echo_label'].setText(f"{ch.name}: 连接中...")

    def _disconnect_channel(self, ch):
        """断开单路（其余通道不受影响）。"""
        if ch.thread:
            stop_thread(ch.thread, name=f"超声波位移{ch.name}线程")
            ch.thread = None
        refs = self._rows.get(ch.id)
        if refs:
            refs['connect_btn'].setText("连接")
        log.info("%s 已断开", ch.name)
        # 本路实时行复位，其余路的显示保留
        live = self._live_rows.get(ch.id)
        if live:
            live['dist_label'].setText("--.-- cm")
            live['echo_label'].setText(f"{ch.name} 回波: 已断开")
        self._refresh_summary_text()
        if not any(c.thread for c in self.channels):
            self._set_collect_enabled(False)

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
        """开始数据采集"""
        for ch in self.channels:
            ch.data_points.clear()
            ch.time_data.clear()
            ch.echo_data.clear()
            ch.last_sample_s = None
        self.data_text.clear()
        # 主机统一时间基准：以采集期收到的**首个样本**为 t=0（各路共享）
        self._t0_mono = None

        self._collecting = True
        log.info("开始采集（已连接 %d 路）",
                 sum(1 for ch in self.channels if ch.thread))
        self._refresh_collect_btn()
        self.save_btn.setEnabled(False)

        self.current_data_label.setText("采集进行中...")
        for ch in self.channels:
            live = self._live_rows.get(ch.id)
            if live:
                live['echo_label'].setText(f"{ch.name} 回波: 采集中...")

    def stop_collection(self):
        """停止数据采集"""
        self._collecting = False
        self._refresh_collect_btn()
        total = sum(len(ch.data_points) for ch in self.channels)
        self.save_btn.setEnabled(total > 0)
        log.info("停止采集，共 %d 个数据点", total)

        self.current_data_label.setText("采集已停止")

    def handle_data(self, data, ch):
        """一路连接的数据回调（SerialThread / SimulatorThread → 本模块）。

        多路连接下的约定：
        - ERROR / START 按通道处理，出错只断开这一路；
        - 记录用**主机统一时间戳**（time.monotonic），各路天然对齐在同一
          时间轴（不同 ESP32 开机时刻不同，固件时间戳不可跨路比较）；
        - 固件的 timestamp 字段只做格式解析，不参与记录。
        """
        # 检查是否是错误信息
        if data.startswith("ERROR:"):
            log.error("%s 设备错误: %s", ch.name, data[6:])
            fluent_message_box(self, "串口错误", f"{ch.name}: {data[6:]}")
            self._disconnect_channel(ch)
            return

        # 检查是否是启动信号
        if data == "START":
            live = self._live_rows.get(ch.id)
            if live:
                live['echo_label'].setText(f"{ch.name}: 设备已启动，等待数据...")
            return

        try:
            # 解析数据格式: timestamp,echo_time
            if "," not in data:
                return
            parts = data.split(",")
            if len(parts) != 2:
                return
            echo_time = int(parts[1])
        except ValueError:
            return  # 忽略无法解析的数据

        # 过滤无效数据（回波时间过小或过大）
        if echo_time < 100 or echo_time > 60000:  # 100µs - 60ms
            return

        # 计算距离（厘米）
        distance_cm = echo_time / 58.0

        # 实时显示（未采集时也持续刷新）——只更新本路行
        live = self._live_rows.get(ch.id)
        if live:
            live['dist_label'].setText(f"{distance_cm:.2f} cm")
            live['echo_label'].setText(f"{ch.name} 回波: {echo_time}µs")
        # 隐藏摘要标签记最新活动的一路（仅供全屏浮动面板折叠态摘要读取）
        self.current_data_label.setText(f"{ch.name}: {distance_cm:.2f}cm")

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

        # 记录数据
        ch.data_points.append(distance_cm)
        ch.time_data.append(t_rel)
        ch.echo_data.append(echo_time)

        time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        display_text = (f"{time_str} | {ch.name} | 回波: {echo_time}µs | "
                        f"距离: {distance_cm:.2f}cm")
        self.data_text.append(display_text)

        # 自动滚动到底部
        self.data_text.verticalScrollBar().setValue(
            self.data_text.verticalScrollBar().maximum()
        )

        # 更新统计信息
        self.update_stats()

    def update_stats(self):
        """更新统计信息：每路有数据的通道各显示一行统计。"""
        parts = []
        for ch in self.channels:
            if not ch.data_points:
                continue
            avg_distance = np.mean(ch.data_points)
            max_distance = np.max(ch.data_points)
            min_distance = np.min(ch.data_points)
            parts.append(
                f"{ch.name}: 点数 {len(ch.data_points)} | "
                f"平均 {avg_distance:.2f}cm | "
                f"最大 {max_distance:.2f}cm | "
                f"最小 {min_distance:.2f}cm")
        if parts:
            self.stats_label.setText("统计: " + " ‖ ".join(parts))

    def update_chart(self):
        """更新图表（多路叠加，勾选行控制显示）"""
        if not self.isVisible():
            return  # 页面隐藏时跳过重绘（定时器不停止，避免白耗 UI 线程）
        # 只画勾选显示的通道（图表卡顶部勾选行控制）；勾选不影响采集与统计
        active = [ch for ch in self.channels
                  if ch.data_points and ch.visible]
        if not active:
            # 有数据但全部取消勾选 → 清空图表；本来就没数据 → 保持原样
            if any(ch.data_points for ch in self.channels):
                self.chart.clear_chart()
            return
        c = self.chart
        c.begin()
        all_t = []
        all_d = []
        # 每路一条曲线：颜色 = 各通道行色块上选的颜色，图例 = 通道名
        for ch in active:
            c.plot(ch.time_data, ch.data_points, color=ch.color, width=2,
                   label=ch.name)
            all_t.extend(ch.time_data)
            all_d.extend(ch.data_points)
        c.set_labels('时间 (秒)', '距离 (厘米)')
        c.set_title('距离传感器的距离 - 实时数据（多路对比）' if len(active) > 1
                    else '距离传感器的距离 - 实时数据')
        c.legend()

        # 自动调整坐标轴范围
        if len(all_t) > 1:
            time_range = max(all_t) - min(all_t)
            distance_range = max(all_d) - min(all_d)

            if time_range > 0:
                c.set_xlim(min(all_t), max(all_t))
            if distance_range > 0:
                c.set_ylim(min(all_d) - 0.1 * distance_range,
                           max(all_d) + 0.1 * distance_range)
        c.end()

    def _on_channel_sample_interval_changed(self, ch, interval_ms):
        """本路采样频率改变：更新该路间隔并保存配置（对该路过滤即时生效；
        模拟器线程按创建时间隔发数，重连后按新频率运行）。"""
        ch.sample_interval_ms = interval_ms
        if self.channels and ch is self.channels[0]:
            self.sample_interval_ms = interval_ms  # 顶层字段跟第 1 路（旧配置兼容）
        self.save_config()

    def save_data(self):
        """保存数据到文件（长表：一行一个样本 + 通道名列）"""
        total = sum(len(ch.data_points) for ch in self.channels)
        if total == 0:
            fluent_message_box(self, "警告", "没有数据可保存")
            return
        try:
            filename = f"ultrasonic_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', encoding='utf-8') as f:
                # 长表格式：一行一个样本 + 通道名列。多路的时间轴天然对齐
                # （主机统一时间戳），便于 Excel 透视/筛选按通道分组分析
                f.write("channel,timestamp_s,echo_us,distance_cm\n")
                for ch in self.channels:
                    for i, (timestamp, distance) in enumerate(
                            zip(ch.time_data, ch.data_points)):
                        echo = ch.echo_data[i] if i < len(ch.echo_data) else 0
                        f.write(f"{ch.name},{timestamp:.3f},{echo},{distance:.3f}\n")

            log.info("数据已保存到: %s（%d 点）", filename, total)
            fluent_message_box(self, "成功", f"数据已保存到: {filename}")
        except Exception as e:
            log.error("保存失败: %s", e)
            fluent_message_box(self, "错误", f"保存失败: {e}")

    def clear_data(self):
        """清除数据"""
        for ch in self.channels:
            ch.data_points.clear()
            ch.time_data.clear()
            ch.echo_data.clear()
            ch.last_sample_s = None
        self._t0_mono = None
        self.data_text.clear()
        self.stats_label.setText("暂无数据")
        for ch in self.channels:
            live = self._live_rows.get(ch.id)
            if live:
                live['dist_label'].setText("--.-- cm")
                live['echo_label'].setText(f"{ch.name} 回波: ---- µs")
        self.current_data_label.setText("等待数据...")
        log.info("已清除数据")
        self.chart.clear_chart()
        self.save_btn.setEnabled(False)

    def _ai_data(self):
        """AI 分析实验数据回调（图表卡「AI分析实验」按钮调用）。

        多路连接时取**数据最多的通道**作为主分析序列，各通道概况
        写入 params，供模型理解多路对比背景。
        """
        active = [ch for ch in self.channels if ch.data_points]
        if not active:
            return None
        main = max(active, key=lambda c: len(c.data_points))
        channels_desc = "、".join(
            f"{ch.name}[{len(ch.data_points)}点]" for ch in active)
        return {
            'title': '超声波位移',
            'x_label': '时间 (秒)',
            'y_label': '距离 (厘米)',
            'points': list(zip(main.time_data, main.data_points)),
            'params': (
                f"传感器=HC-SR04 超声波, 距离换算=回波时间(µs)/58, "
                f"声速假设=340m/s（温度每变化 1℃ 约 ±0.17%）, "
                f"固件有效回波窗口=100~60000µs（约 2~100cm）, "
                f"最小触发间隔=20ms, "
                f"多路连接: 共{len(active)}路（{channels_desc}），"
                f"主分析通道={main.name}, "
                f"时间轴=主机统一时间戳（各路对齐）, "
                f"采样间隔={main.sample_interval_ms}ms（各路独立）"),
            'system_prompt': AI_SYSTEM_PROMPT,
        }

    def api_snapshot(self):
        """当前实验数据快照（供 core.DataService 任意线程读取）。
        禁止调用任何 Qt 方法：只读模块自身的 Python 数据。"""
        d = self._ai_data() or {}
        points = list(d.get('points') or [])
        latest = None
        if points:
            t, y = points[-1]
            latest = {'t': t, 'y': y}
        return {
            'key': 'ultrasonic_displacement',
            'name': '超声波位移',
            'connected': any(ch.thread is not None for ch in self.channels),
            'collecting': self._collecting,
            'x_label': d.get('x_label', '时间 (秒)'),
            'y_label': d.get('y_label', '距离 (厘米)'),
            'params': d.get('params', {}),
            'points': points,
            'latest': latest,
            # 多路连接明细（points 仍为主通道序列，前端单曲线不破）
            'channels': [
                {'name': ch.name, 'color': ch.color,
                 'connected': ch.thread is not None,
                 'points_n': len(ch.data_points),
                 'latest_raw': ch.echo_data[-1] if ch.echo_data else None}
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
