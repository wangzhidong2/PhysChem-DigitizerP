# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

# === MODULE META ===
# key: ultrasonic_displacement
# icon: x
# icon_file: icon.svg
# name: 超声波位移
# category: physics
# class: UltrasonicWidget
# kernel: _kernel_displacement:DisplacementKernel
# ===================

# -*- coding: utf-8 -*-
"""超声波位移传感器模块 — 测量物体位移和运动轨迹。

多路连接：每路独立选择串口/模拟器、独立采样频率，多路距离数据以主机
统一时间戳叠加画在同一张图上（架构与电压模块一致，
见 docs/multi-channel-design.md；超声波为单通道固件，多路 = 多个 ESP32）。
"""

import os
import importlib.util
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from qfluentwidgets import (
    TitleLabel,
    BodyLabel,
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
    ChannelPanelMixin,
    sync_kernel_channels,
    fluent_message_box,
    scroll_area_style,
    page_bg_style,
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

# 颜色下拉中「自定义…」项的 userData 标记（选中后弹 Fluent 取色对话框）






class UltrasonicWidget(ChannelPanelMixin, QWidget):
    """超声波位移模块界面（多路连接）"""

    def __init__(self, kernel=None):
        super().__init__()
        # 内核由加载器注入；直接实例化时用同目录 _kernel_displacement.py 兜底
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
                            '_kernel_displacement.py')
        spec = importlib.util.spec_from_file_location(
            '_sensor_kernel_ultrasonic_displacement', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.DisplacementKernel()

    # ------------------------------------------------------------------
    # 配置（委托内核）
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
        title = TitleLabel("超声波位移")
        layout.addWidget(title)

        # ========== 卡片1：连接控制（可折叠，多路子卡布局） ==========
        self._build_conn_card(
            layout,
            "增加一路 HC-SR04 连接：\n"
            "每路可单独选择「有线串口 / 模拟器」，单独连接/断开，\n"
            "单独换曲线颜色；多路距离数据叠加画在同一张图上\n"
            "（超声波为单通道固件，多路 = 多个 ESP32）")

        # ========== 卡片2：实时数据（可折叠，每路一行同屏） ==========
        self._build_data_card()
        layout.addWidget(self.card_data)

        # 隐藏摘要标签：**不加入可见布局**——多路时单一汇总位会被各路
        # 数据轮流抢占，可见区只保留每路一行的实时明细。
        # 它的唯一职责是全屏浮动面板折叠态摘要（FloatingDataPanel 依赖
        # .text() 读文本，不 reparent 不要求可见），内容 = 最新活动一路。
        self.current_data_label = BodyLabel("等待连接...")
        self.current_data_label.setFont(QFont("Cascadia Code", 14, QFont.Weight.Bold))
        self.current_data_label.setStyleSheet("color: #444444;")
        self.current_data_label.setParent(self)
        self.current_data_label.hide()

        # ========== 卡片3：图表 + 数据记录（可折叠） ==========
        self._build_chart_card(layout, "距离-时间曲线", self.current_data_label)

        # ========== 卡片4：操作按钮（可折叠） ==========
        self._build_action_card(layout)
        self._finish_page(layout, scroll, content, main_layout)

    # ============================================================
    # 多路连接管理：通道的增删 / 行控件 / 单路连接控制
    # ============================================================








    def _refresh_summary_text(self):
        """隐藏摘要标签取「最近一路有数据的通道」最新值（供全屏折叠摘要）。"""
        for ch in reversed(self.channels):
            if ch.data_points:
                self.current_data_label.setText(
                    f"{ch.name}: {ch.data_points[-1]:.2f}cm")
                return
        self.current_data_label.setText("等待连接...")


























    def _apply_started_ui(self):
        """采集已开始：清空上一轮显示并切到采集状态。"""
        self._collecting = True
        self.data_text.clear()
        self._refresh_collect_btn()
        self.save_btn.setEnabled(False)
        log.info("开始采集（已连接 %d 路）",
                 sum(1 for ch in self.channels
                     if getattr(ch, 'connected', False)))
        self.current_data_label.setText("采集进行中...")
        for ch in self.channels:
            live = self._live_rows.get(ch.id)
            if live:
                live['echo_label'].setText(f"{ch.name} 回波: 采集中...")


    def _apply_stopped_ui(self):
        """采集已停止：刷新按钮与汇总标签。"""
        self._collecting = False
        self._refresh_collect_btn()
        total = sum(len(ch.data_points) for ch in self.channels)
        self.save_btn.setEnabled(total > 0)
        log.info("停止采集，共 %d 个数据点", total)
        self.current_data_label.setText("采集已停止")

    # ------------------------------------------------------------------
    # 内核事件 → UI（QTimer 在 GUI 线程消费，避免后台线程直接碰 QWidget）
    # ------------------------------------------------------------------

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
                live['dist_label'].setText(f"{value:.2f} cm")
                live['echo_label'].setText(
                    f"{ch.name} 回波: {int(raw)}µs")
            if value is not None:
                self.current_data_label.setText(f"{ch.name}: {value:.2f}cm")
            return

        if kind == EVENT_SAMPLE_RECORDED and ch is not None:
            value = data.get('value')
            raw = data.get('raw')
            if value is None:
                return
            time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            self.data_text.append(
                f"{time_str} | {ch.name} | 回波: {int(raw)}µs | "
                f"距离: {value:.2f}cm")
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
                    live['dist_label'].setText("--.-- cm")
                    live['echo_label'].setText(f"{ch.name}: {msg}")
                else:
                    live['dist_label'].setText("--.-- cm")
                    live['echo_label'].setText(f"{ch.name} 回波: 已断开")
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
            return

        if kind == EVENT_ERROR and ch is not None:
            message = data.get('message', '')
            log.error("%s 设备错误: %s", ch.name, message)
            fluent_message_box(self, "串口错误", f"{ch.name}: {message}")
            return

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
                   label=ch.name, series_id=str(ch.id))
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




    def _apply_cleared_ui(self):
        """数据已清空：重置本模块的数据展示控件。"""
        # 内核 clear 不清采集状态；按钮跟随内核，避免显示与实际相反
        self._collecting = bool(getattr(self.kernel, 'collecting', False))
        self._refresh_collect_btn()
        self.data_text.clear()
        self.stats_label.setText("暂无数据")
        for ch in self.channels:
            live = self._live_rows.get(ch.id)
            if live:
                live['dist_label'].setText("--.-- cm")
                live['echo_label'].setText(f"{ch.name} 回波: ---- µs")
        self.current_data_label.setText("等待数据...")
        self.chart.clear_chart()
        self.save_btn.setEnabled(False)









    def _live_row_spec(self, ch):
        return {'big_key': 'dist_label', 'big_text': '--.-- cm',
                'secondary': [('echo_label', f'{ch.name} 回波: ---- µs')]}

    def _on_channel_connection_changed(self, ch, connected):
        live = self._live_rows.get(ch.id)
        if not live:
            return
        live['dist_label'].setText('--.-- cm')
        live['echo_label'].setText(
            f'{ch.name}: 连接中...' if connected else f'{ch.name} 回波: 已断开')
