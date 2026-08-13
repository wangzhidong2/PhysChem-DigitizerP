# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

# === MODULE META ===
# icon: F
# name: 力传感器
# category: physics
# class: ForceSensorWidget
# ===================

# -*- coding: utf-8 -*-
"""力传感器模块 — HX711 力/质量传感器测量"""

import sys
import os
import threading
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QSpinBox, QDoubleSpinBox,
    QCheckBox, QInputDialog, QStyle, QScrollArea, QMessageBox,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter
from qfluentwidgets import PushButton, PrimaryPushButton, ComboBox, TextEdit
import serial
import serial.tools.list_ports
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np

# 从公共模块导入共享代码
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core import (
    SerialThread, BLESerialThread, scan_ble_devices, SimulatorThread,
    SampleRateComboBox, CalibrationDialog,
    load_sensor_config, save_sensor_config,
    card_style, primary_btn_style, accent_btn_style, modern_combo_style,
    CollapsibleCard, ExpandableTextEdit,
    BLE_AVAILABLE, _get_config_file_path,
)


class ForceSensorWidget(QWidget):
    """力传感器（HX711）模块界面 - 支持去皮、校准和单位切换"""

    # 连接控制卡片内按钮统一样式：白底黑字
    CARD_BTN_STYLE = """
        QPushButton {
            background-color: #ffffff;
            border: 1px solid #d0d0d0;
            color: #1a1a1a;
            border-radius: 6px;
            padding: 0 16px;
            font-size: 13px;
        }
        QPushButton:hover {
            background-color: #f5f5f5;
            border: 1px solid #0078d4;
            color: #0078d4;
        }
        QPushButton:pressed { background-color: #e5e5e5; }
        QPushButton:disabled {
            background-color: #f5f5f5;
            color: #aaaaaa;
            border: 1px solid #e5e5e5;
        }
    """

    GRAVITY = 9.8
    UNIT_LABELS = {"g": "克 (g)", "kg": "千克 (kg)", "N": "牛顿 (N)"}

    def __init__(self):
        super().__init__()
        self.serial_thread = None
        self.ble_thread = None
        self.flask_server = None
        self.force_data = []
        self.time_data = []
        self.raw_data = []
        self.start_timestamp_ms = 0

        # 采样频率设置（毫秒）
        self.sample_interval_ms = 100  # 默认 100ms (10Hz)
        self.last_sample_time_ms = 0   # 上次采样时间

        self.offset = 0
        self.scale = 1.0
        self.calibrated = False
        self.cal_known_weight = 100.0
        self.cal_raw_before = 0
        self.cal_raw_after = 0
        self.cal_step = 0
        self.current_unit = "g"

        self.config = self.load_config()
        self.offset = self.config.get('offset', 0)
        self.scale = self.config.get('scale', 1.0)
        self.calibrated = self.config.get('calibrated', False)
        self.cal_known_weight = self.config.get('cal_known_weight', 100.0)
        self.current_unit = self.config.get('unit', 'g')

        self.init_ui()

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

    def get_unit_str(self):
        """获取当前单位字符串"""
        return self.current_unit if self.calibrated else "raw"

    def get_chart_ylabel(self):
        """获取图表Y轴标签"""
        if not self.calibrated:
            return "原始ADC值"
        labels = {"g": "质量 (g)", "kg": "质量 (kg)", "N": "力 (N)"}
        return labels.get(self.current_unit, "质量 (g)")

    def set_flask_server(self, server):
        self.flask_server = server

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
        """保存力传感器配置"""
        config = {
            'offset': self.offset,
            'scale': self.scale,
            'calibrated': self.calibrated,
            'cal_known_weight': self.cal_known_weight,
            'unit': self.current_unit,
            'sample_interval_ms': self.sample_interval_ms
        }
        return save_sensor_config('force_sensor', config)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: #f3f3f3; }")

        content = QWidget()
        content.setStyleSheet("background: #f3f3f3;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)

        title = QLabel("力")
        title.setFont(QFont("Microsoft YaHei", 28, QFont.Weight.Bold))
        title.setStyleSheet("color: #1a1a1a; margin-bottom: 4px;")
        layout.addWidget(title)

        # ========== 卡片1：连接控制（可折叠） ==========
        card_conn_content = QWidget()
        card_conn_content.setObjectName("card")
        card_conn_content.setStyleSheet(card_style())
        card_layout = QVBoxLayout(card_conn_content)
        card_layout.setContentsMargins(20, 4, 20, 16)
        card_layout.setSpacing(12)

        row1 = QHBoxLayout()
        row1.setSpacing(10)

        row1.addWidget(QLabel("连接方式:"))
        self.mode_combo = ComboBox()
        self.mode_combo.addItems(["有线串口", "BLE蓝牙", "模拟器"])
        if not BLE_AVAILABLE:
            self.mode_combo.setItemEnabled(1, False)
            self.mode_combo.setItemText(1, "BLE蓝牙（未安装bleak）")
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        row1.addWidget(self.mode_combo)

        # 串口面板
        self.serial_panel = QWidget()
        serial_layout = QHBoxLayout(self.serial_panel)
        serial_layout.setContentsMargins(0, 0, 0, 0)
        serial_layout.setSpacing(8)
        serial_layout.addWidget(QLabel("串口:"))
        self.port_combo = ComboBox()
        self.refresh_ports()
        self.port_combo.setMinimumWidth(140)
        serial_layout.addWidget(self.port_combo)
        self.refresh_btn = PushButton("刷新")
        self.refresh_btn.setFixedHeight(36)
        self.refresh_btn.setStyleSheet(self.CARD_BTN_STYLE)
        self.refresh_btn.clicked.connect(self.refresh_ports)
        serial_layout.addWidget(self.refresh_btn)
        row1.addWidget(self.serial_panel)

        # BLE 面板
        self.ble_panel = QWidget()
        ble_layout = QHBoxLayout(self.ble_panel)
        ble_layout.setContentsMargins(0, 0, 0, 0)
        ble_layout.setSpacing(8)
        self.ble_device_combo = ComboBox()
        self.ble_device_combo.setMinimumWidth(180)
        ble_layout.addWidget(self.ble_device_combo)
        self.ble_scan_btn = PushButton("扫描BLE")
        self.ble_scan_btn.setFixedHeight(36)
        self.ble_scan_btn.setStyleSheet(self.CARD_BTN_STYLE)
        self.ble_scan_btn.clicked.connect(self.scan_ble)
        if not BLE_AVAILABLE:
            self.ble_scan_btn.setEnabled(False)
        ble_layout.addWidget(self.ble_scan_btn)
        row1.addWidget(self.ble_panel)
        self.ble_panel.hide()

        # 模拟器面板：无需选择端口
        self.sim_panel = QWidget()
        sim_layout = QHBoxLayout(self.sim_panel)
        sim_layout.setContentsMargins(0, 0, 0, 0)
        sim_layout.setSpacing(8)
        sim_hint = QLabel("无需硬件，生成随机数据用于调试")
        sim_hint.setStyleSheet("color: #888;")
        sim_layout.addWidget(sim_hint)
        sim_layout.addStretch()
        row1.addWidget(self.sim_panel)
        self.sim_panel.hide()

        row1.addSpacing(16)
        self.connect_btn = PushButton("连接")
        self.connect_btn.setFixedHeight(36)
        self.connect_btn.setStyleSheet(self.CARD_BTN_STYLE)
        self.connect_btn.clicked.connect(self.connect_device)
        row1.addWidget(self.connect_btn)

        self.disconnect_btn = PushButton("断开")
        self.disconnect_btn.setFixedHeight(36)
        self.disconnect_btn.setStyleSheet(self.CARD_BTN_STYLE)
        self.disconnect_btn.clicked.connect(self.disconnect_all)
        self.disconnect_btn.setEnabled(False)
        row1.addWidget(self.disconnect_btn)

        row1.addSpacing(16)
        row1.addWidget(QLabel("采样频率:"))
        self.sample_rate_combo = SampleRateComboBox()
        self.sample_rate_combo.setSampleInterval(self.sample_interval_ms)
        self.sample_rate_combo.setMaximumWidth(120)
        self.sample_rate_combo.sampleIntervalChanged.connect(self.on_sample_interval_changed)
        row1.addWidget(self.sample_rate_combo)

        row1.addStretch()
        card_layout.addLayout(row1)

        card_conn = CollapsibleCard("连接控制", card_conn_content, expanded=True)
        layout.addWidget(card_conn)

        # ========== 卡片2：校准与去皮（可折叠） ==========
        card_cal_content = QWidget()
        card_cal_content.setObjectName("card")
        card_cal_content.setStyleSheet(card_style() + " QWidget#card QLabel { color: #1a1a1a; }")
        cal_card_layout = QVBoxLayout(card_cal_content)
        cal_card_layout.setContentsMargins(20, 4, 20, 16)
        cal_card_layout.setSpacing(12)

        self.cal_status_label = QLabel(
            "校准状态: 未校准" if not self.calibrated
            else f"校准状态: ✓ 已校准 (比例={self.scale:.6f}, 偏移={self.offset})"
        )
        self.cal_status_label.setStyleSheet(
            "color: #2e7d32; font-weight: bold;" if self.calibrated
            else "color: #555; font-weight: bold;"
        )
        cal_card_layout.addWidget(self.cal_status_label)

        cal_btn_row = QHBoxLayout()
        cal_btn_row.setSpacing(10)

        self.tare_btn = PushButton("去皮（TARE）")
        self.tare_btn.setFixedHeight(36)
        self.tare_btn.setStyleSheet(self.CARD_BTN_STYLE)
        self.tare_btn.clicked.connect(self.send_tare)
        self.tare_btn.setEnabled(False)
        cal_btn_row.addWidget(self.tare_btn)

        self.calibrate_btn = PushButton("校准（CALIBRATE）")
        self.calibrate_btn.setFixedHeight(36)
        self.calibrate_btn.setStyleSheet(self.CARD_BTN_STYLE)
        self.calibrate_btn.clicked.connect(self.start_calibration)
        self.calibrate_btn.setEnabled(False)
        cal_btn_row.addWidget(self.calibrate_btn)

        cal_btn_row.addStretch()
        cal_card_layout.addLayout(cal_btn_row)

        unit_row = QHBoxLayout()
        unit_row.setSpacing(8)
        unit_row.addWidget(QLabel("显示单位:"))
        self.unit_combo = ComboBox()
        self.unit_combo.addItems(["克 (g)", "千克 (kg)", "牛顿 (N)"])
        unit_map = {"g": 0, "kg": 1, "N": 2}
        self.unit_combo.setCurrentIndex(unit_map.get(self.current_unit, 0))
        self.unit_combo.currentIndexChanged.connect(self.on_unit_changed)
        unit_row.addWidget(self.unit_combo)
        unit_hint = QLabel("g = 9.8 m/s²")
        unit_hint.setStyleSheet("color: #888; font-size: 12px;")
        unit_row.addWidget(unit_hint)
        unit_row.addStretch()
        cal_card_layout.addLayout(unit_row)

        card_cal = CollapsibleCard("校准与去皮", card_cal_content, expanded=True)

        # ========== 卡片3：实时数据（可折叠） ==========
        card_data_content = QWidget()
        card_data_content.setObjectName("card")
        card_data_content.setStyleSheet(card_style())
        data_card_layout = QVBoxLayout(card_data_content)
        data_card_layout.setContentsMargins(20, 4, 20, 16)
        data_card_layout.setSpacing(12)

        self.current_force_label = QLabel("力/质量: --.-")
        self.current_force_label.setFont(QFont("Microsoft YaHei", 24, QFont.Weight.Bold))
        self.current_force_label.setStyleSheet("color: #1a1a1a;")
        data_card_layout.addWidget(self.current_force_label)

        raw_row = QHBoxLayout()
        raw_row.setSpacing(20)
        self.current_raw_label = QLabel("原始ADC: ------")
        self.current_raw_label.setFont(QFont("Microsoft YaHei", 11))
        self.current_raw_label.setStyleSheet("color: #444444;")
        raw_row.addWidget(self.current_raw_label)
        raw_row.addStretch()
        data_card_layout.addLayout(raw_row)

        self.current_unit_label = QLabel(
            f"单位: {self.UNIT_LABELS.get(self.current_unit, 'g')}（未校准则显示原始值）"
        )
        self.current_unit_label.setStyleSheet("color: #666; font-size: 12px;")
        data_card_layout.addWidget(self.current_unit_label)

        self.stats_label = QLabel("统计信息：暂无数据")
        self.stats_label.setFont(QFont("Microsoft YaHei", 10))
        self.stats_label.setStyleSheet("color: #888888;")
        data_card_layout.addWidget(self.stats_label)

        card_data = CollapsibleCard("实时数据", card_data_content, expanded=True)

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

        content_row = QHBoxLayout()
        content_row.setSpacing(16)

        # 左侧：数据记录（可展开/收起）
        self.data_text = ExpandableTextEdit()
        content_row.addWidget(self.data_text, stretch=0)

        self.figure = Figure(figsize=(8, 5), dpi=100)
        self.figure.set_facecolor('#fafafa')
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setStyleSheet("border: 1px solid #e5e5e5; border-radius: 6px;")
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        content_row.addWidget(self.canvas, stretch=2)

        chart_card_layout.addLayout(content_row, 1)
        card_chart = CollapsibleCard("力-时间曲线", card_chart_content, expanded=True, fullscreen=True)
        # 图表卡片加高为原来的 2 倍（内容区最小 400px），页面滚动查看
        card_chart.set_chart_min_height(400)
        card_chart.set_fullscreen_overlay(self.data_text, self.current_force_label)
        layout.addWidget(card_chart)

        # ========== 卡片5：操作按钮（可折叠） ==========
        card_actions_content = QWidget()
        card_actions_content.setObjectName("card")
        card_actions_content.setStyleSheet(card_style())
        actions_layout = QHBoxLayout(card_actions_content)
        actions_layout.setContentsMargins(20, 4, 20, 12)
        actions_layout.setSpacing(10)

        self.start_btn = PrimaryPushButton("开始采集")
        self.start_btn.setFixedHeight(38)
        self.start_btn.clicked.connect(self.start_collection)
        self.start_btn.setEnabled(False)
        actions_layout.addWidget(self.start_btn)

        self.stop_btn = PushButton("停止采集")
        self.stop_btn.setFixedHeight(38)
        self.stop_btn.clicked.connect(self.stop_collection)
        self.stop_btn.setEnabled(False)
        actions_layout.addWidget(self.stop_btn)

        self.save_btn = PushButton("保存数据")
        self.save_btn.setFixedHeight(38)
        self.save_btn.clicked.connect(self.save_data)
        self.save_btn.setEnabled(False)
        actions_layout.addWidget(self.save_btn)

        self.clear_btn = PushButton("清除数据")
        self.clear_btn.setFixedHeight(38)
        self.clear_btn.clicked.connect(self.clear_data)
        actions_layout.addWidget(self.clear_btn)

        actions_layout.addStretch()
        card_actions = CollapsibleCard("操作按钮", card_actions_content, expanded=True)
        layout.addWidget(card_actions)

        layout.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_chart)
        self.timer.start(100)

    def on_mode_changed(self, index):
        if index == 0:
            self.serial_panel.show()
            self.ble_panel.hide()
            self.sim_panel.hide()
        elif index == 1:
            self.serial_panel.hide()
            self.ble_panel.show()
            self.sim_panel.hide()
        else:
            self.serial_panel.hide()
            self.ble_panel.hide()
            self.sim_panel.show()

    def on_unit_changed(self, index):
        unit_list = ["g", "kg", "N"]
        self.current_unit = unit_list[index]
        self.save_config()
        self.current_unit_label.setText(
            f"单位: {self.UNIT_LABELS.get(self.current_unit, 'g')}"
            + ("（未校准则显示原始值）" if not self.calibrated else f"（校准比例={self.scale:.6f}）")
        )
        if len(self.force_data) > 0:
            self.update_stats()
            self.update_chart()
            converted = self.convert_unit(self.force_data[-1])
            unit = self.get_unit_str()
            self.current_force_label.setText(f"力/质量: {converted:.4f} {unit}")

    def refresh_ports(self):
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.port_combo.addItem(port.device)

    def scan_ble(self):
        if not BLE_AVAILABLE:
            QMessageBox.warning(self, "提示", "请先安装 bleak 库：pip install bleak")
            return

        self.ble_scan_btn.setEnabled(False)
        self.ble_scan_btn.setText("扫描中...")

        self._ble_scan_thread = threading.Thread(target=self._do_scan_ble, daemon=True)
        self._ble_scan_thread.start()

    def _do_scan_ble(self):
        try:
            devices = scan_ble_devices()
            self.ble_device_combo.clear()
            for name, addr in devices:
                self.ble_device_combo.addItem(f"{name} ({addr})")
            if not devices:
                self.ble_device_combo.addItem("未找到设备")
        except Exception as e:
            print(f"BLE 扫描错误: {e}")
        finally:
            self.ble_scan_btn.setEnabled(BLE_AVAILABLE)
            self.ble_scan_btn.setText("扫描BLE")

    def connect_device(self):
        mode = self.mode_combo.currentText()
        if "BLE" in mode:
            self.connect_ble()
        elif "模拟器" in mode:
            self.connect_simulator()
        else:
            self.connect_serial()

    def connect_simulator(self):
        """连接模拟器：随机生成 HX711 原始值，无需硬件"""
        try:
            # HX711 24 位原始读数，围绕一个基准值缓慢漂移
            self.serial_thread = SimulatorThread(
                value_min=7500000, value_max=9000000,
                interval_ms=self.sample_interval_ms,
                start_value=8200000)
            self.serial_thread.data_received.connect(self.handle_data)
            self.serial_thread.start()
            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(True)
            self.start_btn.setEnabled(True)
            self.tare_btn.setEnabled(True)
            self.calibrate_btn.setEnabled(True)
            self.current_force_label.setText("力/质量: 模拟器等待数据...")
            self.current_raw_label.setText("原始ADC: 模拟器连接中...")
        except Exception as e:
            QMessageBox.critical(self, "连接错误", f"模拟器启动失败: {e}")

    def connect_serial(self):
        port = self.port_combo.currentText()
        if not port:
            QMessageBox.warning(self, "错误", "请选择串口")
            return
        try:
            self.serial_thread = SerialThread(port)
            self.serial_thread.data_received.connect(self.handle_data)
            self.serial_thread.start()
            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(True)
            self.start_btn.setEnabled(True)
            self.tare_btn.setEnabled(True)
            self.calibrate_btn.setEnabled(True)
            self.current_force_label.setText("力/质量: 等待数据...")
            self.current_raw_label.setText("原始ADC: 连接中...")
        except Exception as e:
            QMessageBox.critical(self, "连接错误", f"无法连接串口: {e}")

    def connect_ble(self):
        if not BLE_AVAILABLE:
            QMessageBox.warning(self, "提示", "请先安装 bleak 库：pip install bleak")
            return

        device_text = self.ble_device_combo.currentText()
        if not device_text or "未找到" in device_text:
            QMessageBox.warning(self, "提示", "请先扫描并选择 BLE 设备")
            return

        try:
            address = device_text.split("(")[-1].rstrip(")")
        except:
            QMessageBox.warning(self, "提示", "无法解析设备地址")
            return

        try:
            self.ble_thread = BLESerialThread(address)
            self.ble_thread.data_received.connect(self.handle_data)
            self.ble_thread.connection_status.connect(self.on_ble_status)
            self.ble_thread.start()
            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(True)
            self.start_btn.setEnabled(True)
            self.tare_btn.setEnabled(True)
            self.calibrate_btn.setEnabled(True)
            self.current_force_label.setText("力/质量: BLE连接中...")
            self.current_raw_label.setText("原始ADC: BLE连接中...")
        except Exception as e:
            QMessageBox.critical(self, "连接错误", f"BLE 连接失败: {e}")

    def on_ble_status(self, status):
        if status == "connected":
            self.current_force_label.setText("力/质量: BLE已连接，等待数据...")
            self.current_raw_label.setText("原始ADC: 等待数据...")

    def disconnect_all(self):
        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread.wait()
            self.serial_thread = None
        if self.ble_thread:
            self.ble_thread.stop()
            self.ble_thread.wait()
            self.ble_thread = None

        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.tare_btn.setEnabled(False)
        self.calibrate_btn.setEnabled(False)
        self.current_force_label.setText("力/质量: --.-")
        self.current_raw_label.setText("原始ADC: 已断开")

    def send_tare(self):
        """发送去皮命令"""
        if not self.serial_thread and not self.ble_thread:
            QMessageBox.warning(self, "警告", "请先连接设备")
            return

        try:
            if self.serial_thread and self.serial_thread.isRunning():
                if hasattr(self.serial_thread, 'serial') and self.serial_thread.serial and self.serial_thread.serial.is_open:
                    self.serial_thread.serial.write(b"TARE\n")
                    self.current_force_label.setText("力/质量: 去皮中...")

                    if len(self.raw_data) > 0:
                        self.offset = self.raw_data[-1]
                        self.save_config()
                        self.cal_status_label.setText(f"校准状态: ✓ 已校准 (比例={self.scale:.6f}, 偏移={self.offset})")

                        QTimer.singleShot(500, lambda: self.current_force_label.setText("力/质量: 去皮完成"))
                    else:
                        QTimer.singleShot(500, lambda: self.current_force_label.setText("力/质量: 等待数据..."))
                else:
                    QMessageBox.warning(self, "错误", "串口未打开，无法发送去皮命令")

            elif self.ble_thread and self.ble_thread.isRunning():
                if hasattr(self.ble_thread, 'send_command'):
                    self.ble_thread.send_command("TARE")
                    self.current_force_label.setText("力/质量: 去皮中（BLE）...")

                    if len(self.raw_data) > 0:
                        self.offset = self.raw_data[-1]
                        self.save_config()
                        self.cal_status_label.setText(f"校准状态: ✓ 已校准 (比例={self.scale:.6f}, 偏移={self.offset})")

                        QTimer.singleShot(500, lambda: self.current_force_label.setText("力/质量: 去皮完成"))
                    else:
                        QTimer.singleShot(500, lambda: self.current_force_label.setText("力/质量: 等待数据..."))
                else:
                    QMessageBox.information(self, "提示", "BLE连接不支持去皮命令，请使用空载校准功能")

        except Exception as e:
            QMessageBox.critical(self, "去皮失败", f"发送去皮命令时出错：{e}")
            self.current_force_label.setText("力/质量: 去皮失败")

    def start_calibration(self):
        if self.cal_step == 0:
            self.cal_step = 1
            self.calibrate_btn.setText("1. 请空载，点击记录零点")
            self.calibrate_btn.setStyleSheet(self.CARD_BTN_STYLE)
        elif self.cal_step == 1:
            if len(self.raw_data) > 0:
                self.cal_raw_before = self.raw_data[-1]
            self.cal_step = 2
            weight, ok = QInputDialog.getDouble(
                self, "校准 - 已知质量",
                "请放上已知质量的砝码，\n输入砝码质量（克）：",
                self.cal_known_weight, 0.01, 100000, 2
            )
            if ok:
                self.cal_known_weight = weight
                self.calibrate_btn.setText(f"2. 已放{weight}g砝码，点击记录")
            else:
                self.cal_step = 0
                self.calibrate_btn.setText("校准（CALIBRATE）")
                self.calibrate_btn.setStyleSheet(self.CARD_BTN_STYLE)
        elif self.cal_step == 2:
            if len(self.raw_data) > 0:
                self.cal_raw_after = self.raw_data[-1]
                diff = self.cal_raw_after - self.cal_raw_before
                if diff != 0:
                    self.scale = self.cal_known_weight / diff
                    self.offset = self.cal_raw_before
                    self.calibrated = True
                    self.save_config()
                    self.cal_status_label.setText(f"校准状态: ✓ 已校准 (比例={self.scale:.6f}, 偏移={self.offset})")
                    self.cal_status_label.setStyleSheet("color: green; font-weight: bold;")
                    self.current_unit_label.setText(f"单位: {self.UNIT_LABELS.get(self.current_unit, 'g')}（校准比例={self.scale:.6f}）")
                    QMessageBox.information(self, "校准成功",
                        f"校准完成！\n"
                        f"空载ADC: {self.cal_raw_before}\n"
                        f"加载ADC: {self.cal_raw_after}\n"
                        f"ADC差值: {diff}\n"
                        f"校准比例: {self.scale:.6f}\n"
                        f"砝码质量: {self.cal_known_weight}g")
                else:
                    QMessageBox.warning(self, "校准失败", "ADC差值为0，请检查传感器是否正常工作")

            self.cal_step = 0
            self.calibrate_btn.setText("校准（CALIBRATE）")
            self.calibrate_btn.setStyleSheet(self.CARD_BTN_STYLE)

    def start_collection(self):
        self.force_data.clear()
        self.time_data.clear()
        self.raw_data.clear()
        self.data_text.clear()
        self.last_sample_time_ms = 0  # 重置采样时间

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.save_btn.setEnabled(False)

        self.current_force_label.setText("力/质量: 采集中...")
        self.current_raw_label.setText("原始ADC: 采集中...")

    def stop_collection(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.save_btn.setEnabled(len(self.force_data) > 0)

        if len(self.force_data) > 0:
            converted = self.convert_unit(np.mean(self.force_data))
            unit = self.get_unit_str()
            self.current_force_label.setText(f"力/质量: {converted:.4f} {unit}")

    def handle_data(self, data):
        if data.startswith("ERROR:"):
            QMessageBox.critical(self, "连接错误", data[6:])
            self.disconnect_all()
            return

        if data == "START":
            self.current_force_label.setText("力/质量: 设备就绪")
            self.current_raw_label.setText("原始ADC: 等待数据...")
            return

        if data.startswith("TARE_DONE"):
            parts = data.split(",")
            if len(parts) == 2:
                try:
                    self.offset = int(parts[1])
                    self.current_force_label.setText("力/质量: 去皮完成")
                except:
                    pass
            return

        if data.startswith("CALIBRATE_READY"):
            self.current_force_label.setText("力/质量: 请放置已知质量砝码")
            return

        if not self.stop_btn.isEnabled():
            try:
                if "," in data:
                    parts = data.split(",")
                    if len(parts) == 2:
                        timestamp_ms = int(parts[0])
                        raw_value = int(parts[1])
                        self.raw_data.append(raw_value)

                        if self.calibrated:
                            force_value_grams = (raw_value - self.offset) * self.scale
                            force_value = self.convert_unit(force_value_grams)
                        else:
                            force_value = float(raw_value)

                        unit = self.get_unit_str()
                        self.current_raw_label.setText(f"原始ADC: {raw_value}")
                        self.current_force_label.setText(f"力/质量: {force_value:.4f} {unit}")
            except ValueError:
                pass
            return

        try:
            if "," in data:
                parts = data.split(",")
                if len(parts) == 2:
                    timestamp_ms = int(parts[0])
                    raw_value = int(parts[1])

                    # 采样频率控制：检查是否达到采样间隔
                    if timestamp_ms - self.last_sample_time_ms < self.sample_interval_ms:
                        return  # 未达到采样间隔，跳过此数据

                    # 更新上次采样时间
                    self.last_sample_time_ms = timestamp_ms

                    if len(self.time_data) == 0:
                        self.start_timestamp_ms = timestamp_ms

                    relative_time_s = (timestamp_ms - self.start_timestamp_ms) / 1000.0

                    self.raw_data.append(raw_value)

                    if self.calibrated:
                        force_value_grams = (raw_value - self.offset) * self.scale
                        force_value = self.convert_unit(force_value_grams)
                    else:
                        force_value = float(raw_value)

                    self.force_data.append(force_value_grams if self.calibrated else force_value)
                    self.time_data.append(relative_time_s)

                    current_time = datetime.now()
                    time_str = current_time.strftime("%H:%M:%S.%f")[:-3]

                    unit = self.get_unit_str()
                    display_text = f"时间: {time_str} | ADC: {raw_value} | {unit}: {force_value:.4f}"
                    self.current_raw_label.setText(f"原始ADC: {raw_value}")
                    self.current_force_label.setText(f"力/质量: {force_value:.4f} {unit}")

                    self.data_text.append(display_text)
                    self.data_text.verticalScrollBar().setValue(
                        self.data_text.verticalScrollBar().maximum()
                    )

                    self.update_stats()

                    if self.flask_server:
                        self.flask_server.update_data('force', {
                            'force': force_value,
                            'raw_adc': raw_value,
                            'timestamp': time_str,
                            'connected': True,
                            'collecting': True,
                            'history': [(time_str, force_value)]
                        })

        except ValueError:
            pass

    def update_stats(self):
        if len(self.force_data) > 0:
            unit = self.get_unit_str()
            converted_data = [self.convert_unit(v) for v in self.force_data] if self.calibrated else self.force_data
            avg_force = np.mean(converted_data)
            max_force = np.max(converted_data)
            min_force = np.min(converted_data)
            std_force = np.std(converted_data)

            stats_text = (f"统计: 数据点 {len(self.force_data)} | "
                         f"平均={avg_force:.4f}{unit} | "
                         f"最大={max_force:.4f}{unit} | "
                         f"最小={min_force:.4f}{unit} | "
                         f"标准差 σ={std_force:.4f}")
            self.stats_label.setText(stats_text)

    def update_chart(self):
        if len(self.force_data) > 0:
            self.figure.clear()
            ax = self.figure.add_subplot(111)

            ylabel = self.get_chart_ylabel()
            if self.calibrated:
                converted_data = [self.convert_unit(v) for v in self.force_data]
            else:
                converted_data = self.force_data
            ax.plot(self.time_data, converted_data, '#0078d4', linewidth=2, label=ylabel)

            ax.set_xlabel('时间 (秒)')
            ax.set_ylabel(ylabel)
            ax.set_title('力传感器实时数据', fontsize=14, fontweight='bold')
            ax.grid(True, alpha=0.3)
            ax.legend(loc='upper right')

            if len(self.time_data) > 1:
                ax.set_xlim(min(self.time_data), max(self.time_data))

            self.figure.tight_layout()
            self.canvas.draw()

    def on_sample_interval_changed(self, interval_ms):
        """采样频率改变时更新间隔并保存配置（内联下拉框触发）"""
        self.sample_interval_ms = interval_ms
        self.save_config()

    def save_data(self):
        if len(self.force_data) == 0:
            QMessageBox.warning(self, "警告", "没有数据可保存")
            return

        try:
            unit = self.get_unit_str()
            filename = f"force_sensor_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', encoding='utf-8') as f:
                if self.calibrated:
                    f.write("time_s,raw_adc,force_g,force_{}\n".format(unit))
                    for i, (time_val, force_grams, raw_val) in enumerate(
                        zip(self.time_data, self.force_data, self.raw_data[-len(self.time_data):])):
                        converted = self.convert_unit(force_grams)
                        f.write(f"{time_val:.3f},{raw_val},{force_grams:.4f},{converted:.6f}\n")
                else:
                    f.write("time_s,raw_adc,raw_value\n")
                    for i, (time_val, force_val, raw_val) in enumerate(
                        zip(self.time_data, self.force_data, self.raw_data[-len(self.time_data):])):
                        f.write(f"{time_val:.3f},{raw_val},{force_val:.4f}\n")

            QMessageBox.information(self, "成功",
                                   f"数据已保存到：{filename}\n"
                                   f"共 {len(self.force_data)} 个数据点\n"
                                   f"单位：{self.UNIT_LABELS.get(self.current_unit, 'g')}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败：{e}")

    def clear_data(self):
        self.force_data.clear()
        self.time_data.clear()
        self.raw_data.clear()
        self.data_text.clear()
        self.stats_label.setText("统计信息: 暂无数据")
        self.current_force_label.setText("力/质量: --.-")
        self.current_raw_label.setText("原始ADC: ------")
        self.figure.clear()
        self.canvas.draw()
        self.save_btn.setEnabled(False)
