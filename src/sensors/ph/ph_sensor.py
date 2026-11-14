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
    BodyLabel, CaptionLabel, FluentIcon as FIF,
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
    CalibrationMessageBox,
    card_style,
    FluentCard,
    scroll_area_style,
    page_bg_style,
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

# 颜色下拉中「自定义…」项的 userData 标记（选中后弹 Fluent 取色对话框）

# 单点/两点/三点校准的显示名
CAL_MODE_NAMES = {1: "单点校准", 2: "两点校准", 3: "三点校准"}






class PhSensorWidget(ChannelPanelMixin, QWidget):
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
        self._build_conn_card(
            layout,
            "增加一路 pH 电极连接：\n"
            "每路可单独选择「有线串口 / 模拟器」，单独连接/断开，\n"
            "单独换曲线颜色与校准参数；多路数据叠加画在同一张图上")

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
        self._build_data_card(stats_text="统计信息：暂无数据")

        # 隐藏摘要标签：**不加入可见布局**——多路时单一汇总位会被各路
        # 数据轮流抢占，可见区只保留每路一行的实时明细。
        # 它的唯一职责是全屏浮动面板折叠态摘要（FloatingDataPanel 依赖
        # .text() 读文本，不 reparent 不要求可见），内容 = 最新活动一路。
        self.current_ph_label = BodyLabel("pH: --.-")
        self.current_ph_label.setFont(QFont("Cascadia Code", 14, QFont.Weight.Bold))
        self.current_ph_label.setStyleSheet("color: #0078d4;")
        self.current_ph_label.setParent(self)
        self.current_ph_label.hide()

        # 校准参数 + 实时数据 并排同一行（顶部对齐，各自按内容高度，不强制等高）
        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)
        cards_row.addWidget(card_cal, stretch=1, alignment=Qt.AlignmentFlag.AlignTop)
        cards_row.addWidget(self.card_data, stretch=1, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(cards_row)

        # ========== 卡片4：pH-时间曲线（可全屏） ==========
        self._build_chart_card(layout, "pH-时间曲线", self.current_ph_label)

        # ========== 卡片5：操作按钮（可折叠） ==========
        self._build_action_card(layout)
        self._finish_page(layout, scroll, content, main_layout)

    # ============================================================
    # 多路连接管理：通道的增删 / 行控件 / 单路连接控制
    # ============================================================








    def _refresh_summary_text(self):
        """隐藏摘要标签取「最近一路有数据的通道」最新值（供全屏折叠摘要）。"""
        for ch in reversed(self.channels):
            if ch.ph_data:
                self.current_ph_label.setText(f"{ch.name}: {ch.ph_data[-1]:.2f}")
                return
        self.current_ph_label.setText("pH: --.-")






















    # ------------------------------------------------------------------
    # 当前连接（校准参数卡）
    # ------------------------------------------------------------------


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
                   label=ch.name, series_id=str(ch.id))
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









    def _live_row_spec(self, ch):
        return {'big_key': 'ph_label', 'big_text': 'pH: --.-',
                'secondary': [('adc_label', f'{ch.name} ADC: ----')]}

    def _sync_active_channel_controls(self, ch):
        self._refresh_cal_text()

    def _on_channel_connection_changed(self, ch, connected):
        live = self._live_rows.get(ch.id)
        if not live:
            return
        live['ph_label'].setText('pH: --.-')
        live['adc_label'].setText(
            f'{ch.name}: 连接中...' if connected else f'{ch.name} ADC: 已断开')
