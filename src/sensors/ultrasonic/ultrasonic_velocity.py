# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

# === MODULE META ===
# key: ultrasonic_velocity
# icon: v
# icon_file: icon_velocity.svg
# name: 超声波速度
# category: physics
# class: UltrasonicVelocityWidget
# kernel: _kernel_velocity:VelocityKernel
# ===================

# -*- coding: utf-8 -*-
"""超声波速度传感器模块 — 回声定位法测量物体速度。

多路连接：每路独立选择串口/模拟器、独立采样频率，多路距离/速度数据以
主机统一时间戳叠加画在同一张图上（架构与电压模块一致，
见 docs/multi-channel-design.md；超声波为单通道固件，多路 = 多个 ESP32）。
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
    TitleLabel,
    BodyLabel, CaptionLabel, SpinBox,
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

log = get_logger("ultrasonic_velocity")

# AI 分析实验：模块专属系统提示词（进入 AI 分析时随实验信息与数据发送给模型，
# 由 core.build_ai_system_prompt 组装进 system 消息）
AI_SYSTEM_PROMPT = (
    "你是一位资深物理实验指导教师与运动学分析专家，正在协助分析 HC-SR04 超声波"
    "差分回波计算速度的实验数据。"
    "测量原理：由相邻两次回波时间 t0、t1（µs）差分得到速度 "
    "v = (t0 − t1)/2 × v_s / [(t1 + t0)/2 + Δt]，其中 v_s ≈ 34000 cm/s（声速），"
    "Δt 为两次发射间隔（s，由相邻时间戳差得到）。距离量化误差会被时间差放大，"
    "速度噪声通常明显大于距离噪声。多路连接时各路时间轴以主机统一时间戳对齐"
    "（不同 ESP32 开机时刻不同，固件毫秒数不可跨路比较），可做多目标速度同步对比。"
    "数据特征：匀速运动的速度应围绕真值随机波动；加速/减速过程应呈单调变化；"
    "野值多来自丢波、多径反射或目标姿态突变，常表现为单点大跳变。"
    "常见误差来源：回波时间测量抖动、目标非匀速、反射面角度变化、温度对声速的"
    "影响、差分时间过小导致误差放大、采样周期与运动速度不匹配。"
    "分析要求：①评估直接差分的噪声水平，必要时建议对位移序列先做线性/二次拟合或"
    "分组平均再求导，并与差分速度对比；②区分真实加速度与测量噪声，给出速度不确定度"
    "估计（可用相邻速度差分的标准差/√2 近似）；③识别野值及其物理来源；④建议增大"
    "采样间隔、多周期平均或温度修正等改进措施。"
)

# 多路连接的默认曲线配色（按新建顺序轮换取未用色，界面上可单独改色）

# 颜色下拉中「自定义…」项的 userData 标记（选中后弹 Fluent 取色对话框）






class UltrasonicVelocityWidget(ChannelPanelMixin, QWidget):
    """超声波速度模块界面 - 回声定位法（多路连接）"""

    def __init__(self, kernel=None):
        super().__init__()
        # 内核由加载器注入；直接实例化时用同目录 _kernel_velocity.py 兜底
        self.kernel = kernel or self._create_default_kernel()
        self.channels = self.kernel.channels
        self._collecting = False
        self._rows = {}              # channel.id -> 行控件引用 dict
        self.sample_interval_ms = self.kernel.sample_interval_ms
        # 采样窗口（点数，全部通道共用）
        self.window_size = self.kernel.window_size

        self.init_ui()
        self._build_channels_from_kernel()

    @staticmethod
    def _create_default_kernel():
        """不经过 main.py 加载器时，直接加载同目录内核文件。"""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            '_kernel_velocity.py')
        spec = importlib.util.spec_from_file_location(
            '_sensor_kernel_ultrasonic_velocity', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.VelocityKernel()

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
        title = TitleLabel("速度")
        layout.addWidget(title)

        # ========== 卡片1：连接控制（可折叠，多路子卡布局） ==========
        self._build_conn_card(
            layout,
            "增加一路 HC-SR04 连接：\n"
            "每路可单独选择「有线串口 / 模拟器」，单独连接/断开，\n"
            "单独换曲线颜色；多路距离/速度数据叠加画在同一张图上\n"
            "（超声波为单通道固件，多路 = 多个 ESP32）")

        # 采样窗口（全部通道共用）：放连接控制卡下方一行说明 + 数字框
        window_row = QHBoxLayout()
        window_row.setSpacing(10)
        window_row.addWidget(BodyLabel("采样窗口:"))
        self.window_size_spin = SpinBox()
        self.window_size_spin.setRange(5, 100)
        self.window_size_spin.setValue(self.window_size)
        self.window_size_spin.setSuffix(" 点")
        self.window_size_spin.setToolTip("速度平滑/统计提示窗口大小（采样点数，全部通道共用）")
        self.window_size_spin.valueChanged.connect(self.on_window_size_changed)
        window_row.addWidget(self.window_size_spin)
        window_row.addStretch()
        self._conn_card_layout.addLayout(window_row)

        # ========== 卡片2：实时数据（可折叠，每路一行同屏） ==========
        self.velocity_stats_label = CaptionLabel("速度统计: 暂无数据")
        self._build_data_card([self.velocity_stats_label])
        layout.addWidget(self.card_data)

        # 隐藏摘要标签：**不加入可见布局**——多路时单一汇总位会被各路
        # 数据轮流抢占，可见区只保留每路一行的实时明细。
        # 它的唯一职责是全屏浮动面板折叠态摘要（FloatingDataPanel 依赖
        # .text() 读文本，不 reparent 不要求可见），内容 = 最新活动一路。
        self.current_data_label = BodyLabel("当前数据: 等待连接...")
        self.current_data_label.setFont(QFont("Cascadia Code", 14, QFont.Weight.Bold))
        self.current_data_label.setStyleSheet("color: #1a1a1a;")
        self.current_data_label.setParent(self)
        self.current_data_label.hide()

        # ========== 卡片3：速度-时间曲线（可全屏，双子图） ==========
        self._build_chart_card(layout, "速度-时间曲线", self.current_data_label, n_plots=2)

        # ========== 卡片4：操作按钮（可折叠） ==========
        self._build_action_card(layout)
        self._finish_page(layout, scroll, content, main_layout)

    def on_window_size_changed(self, value):
        """采样窗口（全部通道共用）交由内核保存。"""
        self.window_size = value
        self.kernel.set_window_size(value)

    def _sync_module_settings(self):
        """把内核模块级设置（采样窗口）同步回界面。"""
        self.window_size = self.kernel.window_size
        spin = getattr(self, 'window_size_spin', None)
        if spin is not None:
            spin.blockSignals(True)
            spin.setValue(self.window_size)
            spin.blockSignals(False)

    # ============================================================
    # 多路连接管理：通道的增删 / 行控件 / 单路连接控制
    # ============================================================








    def _refresh_summary_text(self):
        """隐藏摘要标签取「最近一路有数据的通道」最新值（供全屏折叠摘要）。"""
        for ch in reversed(self.channels):
            if ch.velocity_data:
                self.current_data_label.setText(
                    f"{ch.name}: {ch.velocity_data[-1]:.2f}cm/s")
                return
        for ch in reversed(self.channels):
            if ch.distance_data:
                self.current_data_label.setText(
                    f"{ch.name}: {ch.distance_data[-1]:.2f}cm")
                return
        self.current_data_label.setText("当前数据: 等待连接...")


























    def _apply_started_ui(self):
        """采集已开始：清空上一轮显示并切到采集状态。"""
        self._collecting = True
        self.data_text.clear()
        self._refresh_collect_btn()
        self.save_btn.setEnabled(False)
        log.info("开始采集（已连接 %d 路）",
                 sum(1 for ch in self.channels
                     if getattr(ch, 'connected', False)))
        self.current_data_label.setText("当前数据: 采集进行中...")
        for ch in self.channels:
            live = self._live_rows.get(ch.id)
            if live:
                live['echo_label'].setText(f"{ch.name} 回波: 采集中...")


    def _apply_stopped_ui(self):
        """采集已停止：刷新按钮与汇总标签。"""
        self._collecting = False
        self._refresh_collect_btn()
        total = sum(len(ch.distance_data) for ch in self.channels)
        self.save_btn.setEnabled(total > 0)
        log.info("停止采集，共 %d 个距离点 / %d 个速度点",
                 total, sum(len(ch.velocity_data) for ch in self.channels))
        self.current_data_label.setText("当前数据: 采集已停止")

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
                live['dist_label'].setText(f"{ch.name} 距离: {value:.2f}cm")
                live['echo_label'].setText(f"{ch.name} 回波: {int(raw)}µs")
            return

        if kind == EVENT_SAMPLE_RECORDED and ch is not None:
            value = data.get('value')
            raw = data.get('raw')
            velocity = data.get('velocity')
            if value is None:
                return
            live = self._live_rows.get(ch.id)
            if live:
                live['dist_label'].setText(f"{ch.name} 距离: {value:.2f}cm")
                live['echo_label'].setText(f"{ch.name} 回波: {int(raw)}µs")
                if velocity is not None:
                    live['vel_label'].setText(f"{velocity:.2f} cm/s")
            if velocity is not None:
                # 隐藏摘要标签记最新活动的一路（仅供全屏折叠态摘要读取）
                self.current_data_label.setText(
                    f"{ch.name}: {velocity:.2f}cm/s")
                time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                self.data_text.append(
                    f"{time_str} | {ch.name} | "
                    f"距离: {value:.2f}cm | 速度: {velocity:.2f}cm/s")
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
                    live['vel_label'].setText("--.-- cm/s")
                    live['echo_label'].setText(f"{ch.name}: {msg}")
                else:
                    live['vel_label'].setText("--.-- cm/s")
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
            self._sync_module_settings()
            return

        if kind == EVENT_ERROR and ch is not None:
            message = data.get('message', '')
            log.error("%s 设备错误: %s", ch.name, message)
            fluent_message_box(self, "串口错误", f"{ch.name}: {message}")
            return

    def update_stats(self):
        """更新速度统计信息：每路有数据的通道各显示一行统计。"""
        parts = []
        for ch in self.channels:
            if not ch.velocity_data:
                continue
            avg_velocity = np.mean(ch.velocity_data)
            max_velocity = np.max(ch.velocity_data)
            min_velocity = np.min(ch.velocity_data)
            parts.append(
                f"{ch.name}: 点数 {len(ch.velocity_data)} | "
                f"平均 {avg_velocity:.2f}cm/s | "
                f"最大 {max_velocity:.2f}cm/s | "
                f"最小 {min_velocity:.2f}cm/s")
        if parts:
            self.velocity_stats_label.setText(
                "速度统计: " + " ‖ ".join(parts))

    def update_chart(self):
        """更新速度图表（双子图：距离-时间 + 速度-时间，多路叠加）"""
        if not self.isVisible():
            return  # 页面隐藏时跳过重绘（定时器不停止，避免白耗 UI 线程）
        # 只画勾选显示的通道（图表卡顶部勾选行控制）；勾选不影响采集与统计
        active = [ch for ch in self.channels
                  if ch.distance_data and ch.visible]
        if not active:
            # 有数据但全部取消勾选 → 清空图表；本来就没数据 → 保持原样
            if any(ch.distance_data for ch in self.channels):
                self.chart.clear_chart()
            return
        c = self.chart
        c.begin()
        all_t = []
        # 子图0：距离-时间图（每路一条曲线，颜色 = 通道色）
        for ch in active:
            c.plot(ch.time_data, ch.distance_data,
                   color=ch.color, width=2, index=0, label=ch.name,
                   series_id=str(ch.id))
            all_t.extend(ch.time_data)
        c.set_labels('时间 (秒)', '距离 (厘米)', index=0)
        c.set_title('距离传感器的距离（多路对比）' if len(active) > 1
                    else '距离传感器的距离', index=0)
        c.legend(index=0)
        # 子图1：速度-时间图（速度序列由距离差分得到，起点对齐）
        for ch in active:
            if not ch.velocity_data:
                continue
            c.plot(ch.time_data[len(ch.time_data) - len(ch.velocity_data):],
                   ch.velocity_data, color=ch.color, width=2, index=1,
                   label=ch.name, series_id=str(ch.id))
        c.set_labels('时间 (秒)', '速度 (厘米/秒)', index=1)
        c.set_title('物体运动速度 - 回声定位法（多路对比）' if len(active) > 1
                    else '物体运动速度 - 回声定位法', index=1)
        c.legend(index=1)
        if len(all_t) > 1:
            c.set_xlim(min(all_t), max(all_t), index=0)
            c.set_xlim(min(all_t), max(all_t), index=1)
        c.end()




    def _apply_cleared_ui(self):
        """数据已清空：重置本模块的数据展示控件。"""
        # 内核 clear 不清采集状态；按钮跟随内核，避免显示与实际相反
        self._collecting = bool(getattr(self.kernel, 'collecting', False))
        self._refresh_collect_btn()
        self.data_text.clear()
        self.velocity_stats_label.setText("速度统计: 暂无数据")
        for ch in self.channels:
            live = self._live_rows.get(ch.id)
            if live:
                live['vel_label'].setText("--.-- cm/s")
                live['dist_label'].setText(f"{ch.name} 距离: ---- cm")
                live['echo_label'].setText(f"{ch.name} 回波: ---- µs")
        self.current_data_label.setText("当前数据: 等待数据...")
        self.chart.clear_chart()
        self.save_btn.setEnabled(False)









    def _live_row_spec(self, ch):
        return {'big_key': 'vel_label', 'big_text': '--.-- cm/s',
                'secondary': [
                    ('dist_label', f'{ch.name} 距离: ---- cm'),
                    ('echo_label', '回波: ---- µs'),
                ]}

    def _on_channel_connection_changed(self, ch, connected):
        live = self._live_rows.get(ch.id)
        if not live:
            return
        live['vel_label'].setText('--.-- cm/s')
        live['echo_label'].setText(
            f'{ch.name}: 连接中...' if connected else f'{ch.name} 回波: 已断开')
