# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

# === MODULE META ===
# icon: P
# name: 电功率
# category: physics
# class: PowerSensorWidget
# ===================

# -*- coding: utf-8 -*-
"""电功率模块 — P = U × I

支持多传感器（多连接）并行采集：点「＋ 添加连接」可添加多路测量装置，
每路独立配置（连接方式 / 采样方式 / 电压串口 / 一体固件 / 电流串口 /
图线颜色），各路由独立串口或模拟线程并行采集互不干扰；图表多路叠加，
实时数据、统计、保存均按路独立呈现。

- 连接方式：单板一体（VI_*.ino 双通道同时输出）/ 双板分测 / 模拟器
- 电压采样方式三选一：ESP32 内置 ADC / ADS1115 (16位) / HX711 (24位)
- 电流：ACS712 5A/20A/30A 量程、DC/AC(有效值)、零点校准
- 图表：功率-时间曲线 + 电压/电流-时间曲线
- 统计：平均功率、累计电能 W（焦耳，梯形积分）
"""

import numpy as np
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QFileDialog,
)

from qfluentwidgets import (
    PushButton, PrimaryPushButton, ComboBox, DoubleSpinBox,
    BodyLabel, CaptionLabel, TitleLabel, isDarkTheme,
)

from core import (
    SERIAL_AVAILABLE,
    load_sensor_config, save_sensor_config,
    ChartPanel, card_style, scroll_area_style, page_bg_style,
    apply_module_theme, fluent_message_box,
    FluentCard, CollapsibleCard, ExpandableTextEdit,
    update_collect_btn, set_action_button_width,
    VIConnectionPanel, VIConnectionUnit, TimestampPairer,
)


class PowerSensorWidget(QWidget):
    """电功率模块 — 多路并行采集 电压×电流，实时计算功率并累计电能。"""

    # 电压/电流换算常量与单路解析逻辑统一封装在 core.VIConnectionUnit
    # 模块负责：数据缓冲、功率/电能计算、实时呈现、统计、图表、保存。

    def __init__(self):
        super().__init__()
        self._collecting = False
        self._bufs = {}          # VIConnectionUnit -> 数据缓冲 dict
        self._live_labels = {}   # unit -> BodyLabel（实时值行）
        self._stats_labels = {}  # unit -> CaptionLabel（统计行）
        self._active_index = 0      # 电压参数卡当前作用的单元序号
        self._cur_active_index = 0  # 电流参数卡当前作用的单元序号（独立于电压侧）
        self._pairer = None         # 双板分测配对器（时间戳就近匹配）
        self._voltage_unit = None   # 当前电压源连接
        self._current_unit = None   # 当前电流源连接
        self.config = self.load_config()
        self.init_ui()
        # pyserial 未安装：各单元自动切模拟器（模拟器模式可体验全部功能）
        if not SERIAL_AVAILABLE:
            for u in self.panel.units:
                u.volt_mode = u.cur_mode = 'simulator'
                u.volt_merged = True
            self.panel.sync_all_cards()

    # --------------------------------------------------------------
    # 配置读写（多连接：units 列表；兼容旧版单连接顶层字段）
    # --------------------------------------------------------------
    def load_config(self):
        config = load_sensor_config('power_sensor')
        self.units_configs = []
        self.dual_pairing = bool(config.get('dual_pairing', False)) if config else False
        if config:
            units = config.get('units')
            if units:
                self.units_configs = units
            else:
                # 旧版（单连接、顶层字段）迁移到 units[0]
                legacy = {}
                for k in ('volt_mode', 'cur_mode', 'volt_merged', 'volt_method',
                          'divider_ratio', 'amp_ratio', 'ads1115_pga',
                          'ads1115_channel', 'hx711_avdd', 'hx711_channel',
                          'acs_range', 'vcc', 'v_quiescent', 'i_divider_ratio',
                          'current_mode', 'current_unit', 'zero_cal_active',
                          'adc_bits', 'ac_rms_window'):
                    if k in config:
                        legacy[k] = config[k]
                self.units_configs = [legacy] if legacy else []
        return config

    def save_config(self):
        return save_sensor_config('power_sensor', {
            'sample_interval_ms': self.panel.sample_rate_combo.getSampleInterval(),
            'dual_pairing': self.panel.dual_pairing,
            'units': self.panel.get_configs(),
        })

    # --------------------------------------------------------------
    # UI 构建
    # --------------------------------------------------------------
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
        layout.setContentsMargins(20, 12, 20, 16)
        layout.setSpacing(8)

        # 页面标题
        layout.addWidget(TitleLabel("电功率"))

        # ========== 卡片1：连接控制（多连接，可增删，每路独立图线颜色） ==========
        self.panel = VIConnectionPanel(
            on_sample=self._on_unit_sample,
            sample_interval_ms=self.config.get('sample_interval_ms', 100),
            dual_pairing=self.dual_pairing,
        )
        self.panel.units_changed.connect(self._on_units_changed)
        self.panel.connection_changed.connect(self._on_connection_changed)
        self.panel.dual_pairing_changed.connect(self._on_dual_pairing_changed)
        layout.addWidget(self.panel)

        # ========== 卡片2：电压参数（作用于「当前连接」所选的单元） ==========
        card_volt = FluentCard("电压参数")
        self._active_unit_combo = ComboBox()
        self._active_unit_combo.currentIndexChanged.connect(self._on_active_changed)
        card_volt.add_row("当前连接", self._active_unit_combo)

        self.divider_spin = DoubleSpinBox()
        self.divider_spin.setRange(0.001, 10000.0)
        self.divider_spin.setDecimals(3)
        self.divider_spin.valueChanged.connect(self._on_divider_changed)
        card_volt.add_row("分压比 (R1+R2)/R2", self.divider_spin)

        self.amp_spin = DoubleSpinBox()
        self.amp_spin.setRange(0.001, 1000.0)
        self.amp_spin.setDecimals(3)
        self.amp_spin.valueChanged.connect(self._on_amp_changed)
        card_volt.add_row("放大倍数", self.amp_spin)

        self.pga_combo = ComboBox()
        self.pga_combo.addItems(list(VIConnectionUnit.ADS1115_PGA_RANGES.keys()))
        self.pga_combo.currentIndexChanged.connect(self._on_pga_changed)
        card_volt.add_row("ADS1115 PGA 量程", self.pga_combo)

        self.hx711_avdd_spin = DoubleSpinBox()
        self.hx711_avdd_spin.setRange(0.1, 15.0)
        self.hx711_avdd_spin.setDecimals(2)
        self.hx711_avdd_spin.valueChanged.connect(self._on_hx711_avdd_changed)
        card_volt.add_row("HX711 AVDD (V)", self.hx711_avdd_spin)

        self.hx711_ch_combo = ComboBox()
        self.hx711_ch_combo.addItems(["A (增益128)", "B (增益32)"])
        self.hx711_ch_combo.currentIndexChanged.connect(self._on_hx711_channel_changed)
        card_volt.add_row("HX711 通道", self.hx711_ch_combo)
        layout.addWidget(card_volt)

        # ========== 卡片3：电流参数（作用于「当前连接」选中的单元，独立于电压卡） ==========
        card_cur = FluentCard("电流参数（ACS712）")
        self._cur_active_combo = ComboBox()
        self._cur_active_combo.currentIndexChanged.connect(self._on_cur_active_changed)
        card_cur.add_row("当前连接", self._cur_active_combo)

        self.range_combo = ComboBox()
        self.range_combo.addItems(list(VIConnectionUnit.ACS712_RANGES.keys()))
        self.range_combo.currentIndexChanged.connect(self._on_range_changed)
        card_cur.add_row("量程", self.range_combo)
        self.range_desc_label = CaptionLabel(
            VIConnectionUnit.ACS712_RANGES['5A']['desc'])
        card_cur.add_widget(self.range_desc_label)

        self.vcc_spin = DoubleSpinBox()
        self.vcc_spin.setRange(2.0, 10.0)
        self.vcc_spin.setDecimals(2)
        self.vcc_spin.valueChanged.connect(self._on_vcc_changed)
        card_cur.add_row("供电电压 VCC (V)", self.vcc_spin)

        self.vq_spin = DoubleSpinBox()
        self.vq_spin.setRange(0.0, 5.0)
        self.vq_spin.setDecimals(4)
        self.vq_spin.valueChanged.connect(self._on_vq_changed)
        card_cur.add_row("零电流输出电压 (V)", self.vq_spin)

        self.i_divider_spin = DoubleSpinBox()
        self.i_divider_spin.setRange(1.0, 10.0)
        self.i_divider_spin.setDecimals(4)
        self.i_divider_spin.valueChanged.connect(self._on_i_divider_changed)
        card_cur.add_row("电流分压比", self.i_divider_spin)

        self.current_mode_combo = ComboBox()
        self.current_mode_combo.addItems(["DC 直流", "AC 交流（有效值）"])
        self.current_mode_combo.currentIndexChanged.connect(self._on_current_mode_changed)
        card_cur.add_row("测量模式", self.current_mode_combo)

        self.unit_combo = ComboBox()
        self.unit_combo.addItems(["A", "mA"])
        self.unit_combo.currentIndexChanged.connect(self._on_unit_changed)
        card_cur.add_row("电流单位", self.unit_combo)
        layout.addWidget(card_cur)

        # ========== 卡片4：实时数据（每连接独立一行） ==========
        card_data = FluentCard("实时数据")
        self._live_container = QWidget()
        self._live_box = QVBoxLayout(self._live_container)
        self._live_box.setSpacing(4)
        card_data.add_widget(self._live_container)
        self._stats_box = QVBoxLayout()
        self._stats_box.setSpacing(2)
        card_data.add_layout(self._stats_box)
        layout.addWidget(card_data)

        # ========== 卡片5：图表 + 数据记录（可折叠） ==========
        card_chart_content = QWidget()
        card_chart_content.setObjectName("card")
        card_chart_content.setStyleSheet(card_style())
        chart_card_layout = QVBoxLayout(card_chart_content)
        chart_card_layout.setContentsMargins(20, 4, 20, 16)
        chart_card_layout.setSpacing(12)

        content_row = QHBoxLayout()
        content_row.setSpacing(16)

        left_col = QVBoxLayout()
        left_col.setSpacing(10)
        self.data_text = ExpandableTextEdit()
        left_col.addWidget(self.data_text)

        # 双引擎图表面板（matplotlib / pyqtgraph，设置页可切换）
        self.chart = ChartPanel(n_plots=2)
        left_col.addWidget(self.chart.get_analysis_panel())
        content_row.addLayout(left_col, stretch=0)

        content_row.addWidget(self.chart, stretch=2)
        chart_card_layout.addLayout(content_row, 1)
        card_chart = CollapsibleCard(
            "电功率图表（功率-时间 + 电压/电流-时间，多路叠加）", card_chart_content,
            expanded=True, fullscreen=True)
        card_chart.set_chart_min_height(420)
        # 全屏浮动：数据记录 + 分析面板浮于图表上方，底部常驻开始/停止
        self.float_collect_btn = PrimaryPushButton("开始采集")
        self.float_collect_btn.setFixedHeight(34)
        update_collect_btn(self.float_collect_btn, False)
        self.float_collect_btn.clicked.connect(self.toggle_collection)
        self.float_collect_btn.setEnabled(False)
        card_chart.set_fullscreen_overlay(
            self.data_text, self._live_container,
            extra_widgets=[self.chart.get_analysis_panel()],
            footer_widget=self.float_collect_btn)
        layout.addWidget(card_chart)

        # ========== 卡片6：操作按钮 ==========
        card_actions = FluentCard("操作按钮")
        self.collect_btn = PrimaryPushButton("开始采集")
        self.collect_btn.setFixedHeight(38)
        update_collect_btn(self.collect_btn, False)
        self.collect_btn.clicked.connect(self.toggle_collection)
        self.collect_btn.setEnabled(False)
        act_row = QHBoxLayout()
        act_row.setSpacing(10)
        act_row.addWidget(self.collect_btn)

        self.zero_cal_btn = PushButton("零点校准")
        self.zero_cal_btn.setFixedHeight(38)
        set_action_button_width(self.zero_cal_btn)
        self.zero_cal_btn.clicked.connect(self.toggle_zero_cal)
        self.zero_cal_btn.setEnabled(False)
        act_row.addWidget(self.zero_cal_btn)

        self.save_btn = PushButton("保存数据")
        self.save_btn.setFixedHeight(38)
        set_action_button_width(self.save_btn)
        self.save_btn.clicked.connect(self.save_data)
        self.save_btn.setEnabled(False)
        act_row.addWidget(self.save_btn)

        self.clear_btn = PushButton("清除数据")
        self.clear_btn.setFixedHeight(38)
        set_action_button_width(self.clear_btn)
        self.clear_btn.clicked.connect(self.clear_data)
        act_row.addWidget(self.clear_btn)
        act_row.addStretch(1)
        card_actions.add_layout(act_row)
        layout.addWidget(card_actions)

        layout.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        # 按配置重建连接单元（触发 units_changed → 重建实时/统计行与参数控件）
        self.panel.set_configs(self.units_configs)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_chart)
        self.timer.start(100)

    # --------------------------------------------------------------
    # 「当前连接」目标单元
    # --------------------------------------------------------------
    def _active_unit(self):
        """电压参数卡当前作用的目标单元（无单元时返回 None）。"""
        units = self.panel.units
        if 0 <= self._active_index < len(units):
            return units[self._active_index]
        return None

    def _cur_active_unit(self):
        """电流参数卡当前作用的目标单元（无单元时返回 None）。"""
        units = self.panel.units
        if 0 <= self._cur_active_index < len(units):
            return units[self._cur_active_index]
        return None

    def _on_units_changed(self):
        """增删连接后：重建电压/电流「当前连接」下拉、实时/统计行、清理缓冲。"""
        units = self.panel.units
        # 同步电压「当前连接」下拉
        self._active_unit_combo.blockSignals(True)
        self._active_unit_combo.clear()
        for i, u in enumerate(units):
            self._active_unit_combo.addItem(f"连接 #{i + 1}")
        if self._active_index >= len(units):
            self._active_index = max(0, len(units) - 1)
        self._active_unit_combo.setCurrentIndex(
            self._active_index if units else -1)
        self._active_unit_combo.setEnabled(bool(units))
        self._active_unit_combo.blockSignals(False)

        # 同步电流「当前连接」下拉（与电压侧完全独立）
        self._cur_active_combo.blockSignals(True)
        self._cur_active_combo.clear()
        for i, u in enumerate(units):
            self._cur_active_combo.addItem(f"连接 #{i + 1}")
        if self._cur_active_index >= len(units):
            self._cur_active_index = max(0, len(units) - 1)
        self._cur_active_combo.setCurrentIndex(
            self._cur_active_index if units else -1)
        self._cur_active_combo.setEnabled(bool(units))
        self._cur_active_combo.blockSignals(False)

        # 重建实时/统计行（按角色；配对时电流源并入电压源行显示）
        self._apply_roles()
        self._rebuild_rows()

        # 清理已删除单元的缓冲
        self._bufs = {u: b for u, b in self._bufs.items() if u in units}

        # 参数控件同步到当前单元（电压卡 + 电流卡各自的「当前连接」）
        if units:
            self._load_active_params()
            self._load_cur_params()

    def _rebuild_rows(self):
        """按当前角色重建实时/统计行：both/voltage 一整行；独立电流一行；none/配对电流不显示。"""
        units = self.panel.units
        paired = self._pairer is not None
        for lbl in self._live_labels.values():
            self._live_box.removeWidget(lbl)
            lbl.deleteLater()
        for st in self._stats_labels.values():
            self._stats_box.removeWidget(st)
            st.deleteLater()
        self._live_labels = {}
        self._stats_labels = {}
        for unit in units:
            if unit.role == 'none':
                continue
            if paired and unit.role == 'current':
                continue  # 配对模式下电流源数据并入电压源行（见 _on_paired_raw）
            dot = f"<span style='color:{unit.color};'>●</span> "
            if unit.role == 'current':
                lbl = BodyLabel(dot + f"{unit.label}: 电流 -- {unit.current_unit}")
            else:
                lbl = BodyLabel(dot + f"{unit.label}: 电压 -- | 电流 -- | 功率 -- | 电能 0.000 J")
            lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            self._live_labels[unit] = lbl
            self._live_box.addWidget(lbl)
            st = CaptionLabel(f"{unit.label}: 数据点 0")
            self._stats_labels[unit] = st
            self._stats_box.addWidget(st)

    def _on_active_changed(self, index):
        self._active_index = index
        self._load_active_params()
        self._apply_roles()
        self._rebuild_rows()

    def _on_cur_active_changed(self, index):
        self._cur_active_index = index
        self._load_cur_params()
        self._apply_roles()
        self._rebuild_rows()

    # --------------------------------------------------------------
    # 角色绑定与双板分测配对（连接 → 电压/电流源）
    # --------------------------------------------------------------
    def _bound_units(self):
        """按两个参数卡的「当前连接」返回 (电压源单元, 电流源单元)。"""
        units = self.panel.units
        u_v = units[self._active_index] if 0 <= self._active_index < len(units) else None
        u_i = units[self._cur_active_index] if 0 <= self._cur_active_index < len(units) else None
        return u_v, u_i

    def _apply_roles(self):
        """按参数卡选择分配角色：同连接→both（一体/模拟器）；不同→电压/电流单通道；未绑定→none。

        双板分测勾选时，把电压源/电流源两路原始 ADC 流接入 TimestampPairer（时间戳就近匹配）。
        """
        units = self.panel.units
        self._unwire_raw()
        self._pairer = None
        self._voltage_unit = self._current_unit = None
        if not units:
            return
        u_v, u_i = self._bound_units()
        for u in units:
            if u is u_v and u is u_i:
                u.role = 'both'
            elif u is u_v:
                u.role = 'voltage'
            elif u is u_i:
                u.role = 'current'
            else:
                u.role = 'none'
        if u_v is not None and u_i is not None and u_v is not u_i:
            self._voltage_unit, self._current_unit = u_v, u_i
            if self.panel.dual_pairing:
                self._pairer = TimestampPairer(tolerance_ms=50,
                                               on_pair=self._on_paired_raw)
        for u in units:
            if u.role in ('voltage', 'current'):
                u.on_raw = self._on_raw_sample

    def _unwire_raw(self):
        for u in self.panel.units:
            u.on_raw = None

    def _on_dual_pairing_changed(self, checked):
        """双板分测开关：重分配角色/配对，重绘实时行（连接方式变更需手动重连）。"""
        self._apply_roles()
        self._rebuild_rows()
        self.save_config()

    def _on_raw_sample(self, unit, t_ms, adc):
        """单通道原始 ADC：双板分测→配对器；未勾选→独立单通道显示。"""
        if not self._collecting:
            return
        if self._pairer is not None:
            self._pairer.feed('v' if unit.role == 'voltage' else 'i', t_ms, adc)
            return
        buf = self._bufs.get(unit)
        if buf is None:
            return
        if buf['t0'] is None:
            buf['t0'] = t_ms
        t = (t_ms - buf['t0']) / 1000.0
        buf['t'].append(t)
        lbl = self._live_labels.get(unit)
        if unit.role == 'voltage':
            v = unit.adc_to_voltage(adc)
            buf['v'].append(v)
            if lbl is not None:
                lbl.setText(
                    f"<span style='color:{unit.color};'>●</span> "
                    f"{unit.label}: 电压 {v:.4f} V")
        else:
            i = unit.adc_to_current(adc)
            buf['i'].append(i)
            if lbl is not None:
                lbl.setText(
                    f"<span style='color:{unit.color};'>●</span> "
                    f"{unit.label}: 电流 {unit.format_current(i)} {unit.current_unit}")
        self.update_stats()

    def _on_paired_raw(self, t_ms, adc_v, adc_i):
        """双板分测配对成功：电压源/电流源各自换算成 U、I，走统一采样通路。"""
        if not self._collecting:
            return
        if self._voltage_unit is None or self._current_unit is None:
            return
        v = self._voltage_unit.adc_to_voltage(adc_v)
        i = self._current_unit.adc_to_current(adc_i)
        self._on_unit_sample(self._voltage_unit, t_ms, v, i)

    def _load_active_params(self):
        """把当前单元（电压卡选择器）的电压参数同步到电压参数卡控件。"""
        unit = self._active_unit()
        if unit is None:
            return
        for w in (self.divider_spin, self.amp_spin, self.hx711_avdd_spin,
                  self.pga_combo, self.hx711_ch_combo):
            w.blockSignals(True)
        self.divider_spin.setValue(unit.divider_ratio)
        self.amp_spin.setValue(unit.amp_ratio)
        self.pga_combo.setCurrentText(unit.ads1115_pga)
        self.hx711_avdd_spin.setValue(unit.hx711_avdd)
        self.hx711_ch_combo.setCurrentIndex(
            0 if unit.hx711_channel == 'A' else 1)
        for w in (self.divider_spin, self.amp_spin, self.hx711_avdd_spin,
                  self.pga_combo, self.hx711_ch_combo):
            w.blockSignals(False)
        self._sync_active_method_controls()

    def _load_cur_params(self):
        """把当前单元（电流卡选择器）的电流参数同步到电流参数卡控件。"""
        unit = self._cur_active_unit()
        if unit is None:
            return
        for w in (self.vcc_spin, self.vq_spin, self.i_divider_spin,
                  self.range_combo, self.current_mode_combo, self.unit_combo):
            w.blockSignals(True)
        self.range_combo.setCurrentText(unit.acs_range)
        self.range_desc_label.setText(
            unit.ACS712_RANGES.get(unit.acs_range,
                                   unit.ACS712_RANGES['5A'])['desc'])
        self.vcc_spin.setValue(unit.vcc)
        self.vq_spin.setValue(unit.v_quiescent)
        self.i_divider_spin.setValue(unit.i_divider_ratio)
        self.current_mode_combo.setCurrentIndex(
            0 if unit.current_mode == 'DC' else 1)
        self.unit_combo.setCurrentText(unit.current_unit)
        for w in (self.vcc_spin, self.vq_spin, self.i_divider_spin,
                  self.range_combo, self.current_mode_combo, self.unit_combo):
            w.blockSignals(False)

    def _sync_active_method_controls(self):
        """按当前单元电压采样方式启用对应的参数控件。"""
        unit = self._active_unit()
        if unit is None:
            return
        ads = unit.volt_method == 'ads1115'
        hx = unit.volt_method == 'hx711'
        self.divider_spin.setEnabled(True)
        self.amp_spin.setEnabled(True)
        self.pga_combo.setEnabled(ads)
        self.hx711_avdd_spin.setEnabled(hx)
        self.hx711_ch_combo.setEnabled(hx)

    # --------------------------------------------------------------
    # 参数变更槽函数（写回「当前连接」单元）
    # --------------------------------------------------------------
    def _save_active(self, mutator):
        unit = self._active_unit()
        if unit is None:
            return
        mutator(unit)
        self.save_config()

    def _save_cur(self, mutator):
        """电流参数写回「当前连接」（电流卡独立选择器）选中的单元。"""
        unit = self._cur_active_unit()
        if unit is None:
            return
        mutator(unit)
        self.save_config()

    def _on_divider_changed(self, value):
        self._save_active(lambda u: setattr(u, 'divider_ratio', value))

    def _on_amp_changed(self, value):
        self._save_active(lambda u: setattr(u, 'amp_ratio', value))

    def _on_pga_changed(self, index):
        if self._active_unit() is not None:
            self._active_unit().ads1115_pga = self.pga_combo.currentText()
            self.save_config()

    def _on_hx711_avdd_changed(self, value):
        self._save_active(lambda u: setattr(u, 'hx711_avdd', value))

    def _on_hx711_channel_changed(self, index):
        self._save_active(
            lambda u: setattr(u, 'hx711_channel', 'A' if index == 0 else 'B'))

    def _on_range_changed(self, index):
        unit = self._cur_active_unit()
        if unit is None:
            return
        unit.acs_range = self.range_combo.currentText()
        self.range_desc_label.setText(
            unit.ACS712_RANGES.get(unit.acs_range,
                                   unit.ACS712_RANGES['5A'])['desc'])
        self.save_config()

    def _on_vcc_changed(self, value):
        def _apply(u):
            u.vcc = value
            # 未校准时零点电压跟随 VCC/2
            if not u.zero_cal_active:
                u.v_quiescent = value / 2.0
                self.vq_spin.blockSignals(True)
                self.vq_spin.setValue(u.v_quiescent)
                self.vq_spin.blockSignals(False)
        self._save_cur(_apply)

    def _on_vq_changed(self, value):
        self._save_cur(lambda u: setattr(u, 'v_quiescent', value))

    def _on_i_divider_changed(self, value):
        self._save_cur(lambda u: setattr(u, 'i_divider_ratio', value))

    def _on_current_mode_changed(self, index):
        self._save_cur(
            lambda u: setattr(u, 'current_mode', 'DC' if index == 0 else 'AC'))

    def _on_unit_changed(self, index):
        self._save_cur(lambda u: setattr(u, 'current_unit',
                                         self.unit_combo.currentText()))

    # --------------------------------------------------------------
    # 面板回调：连接状态 / 数据样本
    # --------------------------------------------------------------
    def _on_connection_changed(self, connected):
        self._enable_controls(connected)

    def _on_unit_sample(self, unit, t_ms, v, i):
        """每路换算后的实时样本：记录 + 计算功率/电能 + 更新标签。"""
        if not self._collecting:
            return
        buf = self._bufs.get(unit)
        if buf is None:
            return
        if buf['t0'] is None:
            buf['t0'] = t_ms
        t = (t_ms - buf['t0']) / 1000.0
        buf['t'].append(t)
        buf['v'].append(v)
        buf['i'].append(i)
        p = v * i
        buf['p'].append(p)
        # 累计电能：梯形积分
        if buf['last_p'] is not None:
            dt = (t_ms - buf['last_t_ms']) / 1000.0
            buf['w'] += (p + buf['last_p']) / 2.0 * dt
        buf['last_p'] = p
        buf['last_t_ms'] = t_ms

        lbl = self._live_labels.get(unit)
        if lbl is not None:
            lbl.setText(
                f"<span style='color:{unit.color};'>●</span> "
                f"{unit.label}: 电压 {v:.4f} V | "
                f"电流 {unit.format_current(i)} {unit.current_unit} | "
                f"功率 {p:.4f} W | 电能 {buf['w']:.4f} J")

        time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.data_text.append(
            f"[{unit.label}] 时间: {time_str} | U: {v:.4f} V | "
            f"I: {unit.format_current(i)} {unit.current_unit} | "
            f"P: {p:.4f} W | W: {buf['w']:.4f} J")
        self.data_text.verticalScrollBar().setValue(
            self.data_text.verticalScrollBar().maximum())
        self.update_stats()

    def update_stats(self):
        """每连接一行统计（数据点 + 按角色可用的电压/电流/功率/电能）。"""
        for unit in self.panel.units:
            st = self._stats_labels.get(unit)
            if st is None:
                continue
            buf = self._bufs.get(unit)
            if not buf or not buf['t']:
                st.setText(f"{unit.label}: 数据点 0")
                continue
            n = len(buf['t'])
            parts = [f"{unit.label}: 数据点 {n}"]
            v_arr = np.array(buf['v']) if buf['v'] else None
            i_arr = np.array(buf['i']) if buf['i'] else None
            p_arr = np.array(buf['p']) if buf['p'] else None
            unit_label = unit.current_unit
            if v_arr is not None:
                parts.append(f"平均电压 {v_arr.mean():.4f} V")
            if i_arr is not None:
                parts.append(
                    f"平均电流 {unit.format_current(float(i_arr.mean()))}{unit_label}")
            if p_arr is not None and n:
                parts.append(f"平均功率 {float(p_arr.mean()):.4f} W")
                parts.append(f"累计电能 {buf['w']:.4f} J（{buf['w'] / 3600.0:.6f} Wh）")
            st.setText(" | ".join(parts))

    # --------------------------------------------------------------
    # 采样控制
    # --------------------------------------------------------------
    def toggle_collection(self):
        if self._collecting:
            self.stop_collection()
        else:
            self.start_collection()

    def _refresh_collect_btn(self):
        update_collect_btn(self.collect_btn, self._collecting)
        update_collect_btn(self.float_collect_btn, self._collecting)

    def start_collection(self):
        if not any(u.connected for u in self.panel.units):
            return
        self._bufs = {
            u: dict(t=[], v=[], i=[], p=[], t0=None, last_p=None,
                    last_t_ms=0, w=0.0)
            for u in self.panel.units
        }
        self._collecting = True
        self._refresh_collect_btn()

    def stop_collection(self):
        self._collecting = False
        self._refresh_collect_btn()

    def _enable_controls(self, enabled):
        self.collect_btn.setEnabled(enabled)
        self.float_collect_btn.setEnabled(enabled)
        self.save_btn.setEnabled(enabled or bool(
            self._bufs and any(b['t'] for b in self._bufs.values())))
        self.zero_cal_btn.setEnabled(enabled)
        if enabled:
            for u in self.panel.units:
                if u.zero_cal_active:
                    self.zero_cal_btn.setText("取消零点")
                    self.zero_cal_btn.setStyleSheet(
                        "background-color: #28a745; color: white;")
                    return
            self.zero_cal_btn.setText("零点校准")
            self.zero_cal_btn.setStyleSheet(
                "background-color: #fd7e14; color: white;")

    # --------------------------------------------------------------
    # 零点校准（作用于所有已连接单元，各自缓存独立）
    # --------------------------------------------------------------
    def toggle_zero_cal(self):
        if not self._collecting:
            return
        units = [u for u in self.panel.units if u.connected and u.zero_cal_active]
        if units:
            for u in units:
                u.cancel_zero_cal()
            self.zero_cal_btn.setText("零点校准")
            self.zero_cal_btn.setStyleSheet(
                "background-color: #fd7e14; color: white;")
        else:
            done = [u for u in self.panel.units
                    if u.connected and u.zero_calibrate()]
            if not done:
                fluent_message_box(self, "零点校准", "数据不足，请先采集几秒数据")
                return
            self.zero_cal_btn.setText("取消零点")
            self.zero_cal_btn.setStyleSheet(
                "background-color: #28a745; color: white;")
        self._load_active_params()
        self._load_cur_params()
        self.save_config()

    # --------------------------------------------------------------
    # 图表（多路叠加，每路用其图线颜色）
    # --------------------------------------------------------------
    def update_chart(self):
        c = self.chart
        c.begin()
        for unit in self.panel.units:
            buf = self._bufs.get(unit)
            if not buf or not buf['t']:
                continue
            col = unit.color
            # 子图0：功率-时间（仅双通道：一体/模拟器/配对）
            if buf['p']:
                c.plot(buf['t'], buf['p'], color=col, width=2,
                       label=f"{unit.label} 功率", index=0)
            # 子图1：电压 + 电流（按角色可用的通道绘制，电压粗、电流细）
            if buf['v']:
                c.plot(buf['t'], buf['v'], color=col, width=2,
                       label=f"{unit.label} 电压", index=1)
            if buf['i']:
                c.plot(buf['t'], buf['i'], color=col, width=1,
                       label=f"{unit.label} 电流", index=1)
        c.set_labels('时间 (s)', '功率 (W)', index=0)
        c.set_title('功率-时间曲线', index=0)
        c.set_labels('时间 (s)', '电压 (V) / 电流 (A)', index=1)
        c.set_title('电压-电流-时间曲线', index=1)
        c.legend(index=0)
        c.legend(index=1)
        c.end()

    # --------------------------------------------------------------
    # 保存 / 清除
    # --------------------------------------------------------------
    def save_data(self):
        units = self.panel.units
        if not any(self._bufs.get(u) and self._bufs[u]['t'] for u in units):
            fluent_message_box(self, "保存数据", "暂无数据")
            return
        default = f"power_sensor_data_{datetime.now():%Y%m%d_%H%M%S}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "保存数据", default,
                                              "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            # 各路独立累计电能（逐行梯形积分，避免每行都是最终总值）
            cums = {}
            for u in units:
                buf = self._bufs[u]
                cum, last_p, last_t = 0.0, None, None
                cums[u] = []
                for t, p in zip(buf['t'], buf['p']):
                    if last_p is not None:
                        cum += (p + last_p) / 2.0 * (t - last_t)
                    last_p, last_t = p, t
                    cums[u].append(cum)
            # 每路只导出实际采集到的通道（角色感知，列对齐）
            specs = []
            for i, u in enumerate(units, 1):
                buf = self._bufs[u]
                if not buf['t']:
                    continue
                cols = []
                if buf['v']:
                    cols.append(f"U{i}(V)")
                if buf['i']:
                    cols.append(f"I{i}(A)")
                if buf['p']:
                    cols.append(f"P{i}(W)")
                    cols.append(f"W{i}(J)")
                if cols:
                    specs.append((u, cols))
            if not specs:
                fluent_message_box(self, "保存数据", "暂无数据")
                return
            n = max(len(self._bufs[u]['t']) for u, _ in specs)
            with open(path, 'w', encoding='utf-8-sig') as f:
                header = ["时间(s)"]
                for u, cols in specs:
                    header.extend(cols)
                f.write(",".join(header) + "\n")
                for k in range(n):
                    t_cell = ""
                    for u, cols in specs:
                        if k < len(self._bufs[u]['t']):
                            t_cell = f"{self._bufs[u]['t'][k]:.3f}"
                            break
                    cells = [t_cell]
                    for u, cols in specs:
                        buf = self._bufs[u]
                        if k < len(buf['t']):
                            if buf['v']:
                                cells.append(f"{buf['v'][k]:.6f}")
                            if buf['i']:
                                cells.append(f"{buf['i'][k]:.6f}")
                            if buf['p']:
                                cells.append(f"{buf['p'][k]:.6f}")
                                cells.append(f"{cums[u][k]:.6f}")
                        else:
                            cells.extend([""] * len(cols))
                    f.write(",".join(cells) + "\n")
            fluent_message_box(self, "保存成功",
                               f"已保存 {n} 条数据到\n{path}")
        except Exception as e:
            fluent_message_box(self, "保存失败", str(e))

    def clear_data(self):
        self._bufs = {}
        for unit in self.panel.units:
            self._bufs[unit] = dict(t=[], v=[], i=[], p=[], t0=None,
                                    last_p=None, last_t_ms=0, w=0.0)
            lbl = self._live_labels.get(unit)
            if lbl is not None:
                dot = f"<span style='color:{unit.color};'>●</span> "
                if unit.role == 'current':
                    lbl.setText(dot + f"{unit.label}: 电流 -- {unit.current_unit}")
                else:
                    lbl.setText(
                        dot + f"{unit.label}: 电压 -- | 电流 -- | 功率 -- | 电能 0.000 J")
        self.update_stats()
        self.data_text.clear()
        self.chart.clear_chart()

    def closeEvent(self, event):
        """关闭页面时确保通信线程全部停止（防止退出时 QThread 崩溃）。"""
        self.panel.disconnect_all()
        super().closeEvent(event)

    # --------------------------------------------------------------
    # 主题
    # --------------------------------------------------------------
    def apply_theme(self, theme):
        # 采集按钮配色由 apply_module_theme 统一重刷（core.update_collect_btn）
        apply_module_theme(self, theme)
        self.chart.apply_chart_theme(isDarkTheme())