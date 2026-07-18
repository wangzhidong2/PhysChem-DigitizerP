# === MODULE META ===
# icon: pH
# name: pH传感器
# category: chemistry
# class: PhSensorWidget
# ===================

# -*- coding: utf-8 -*-
"""pH 传感器模块 — 测量溶液酸碱度（SEN0161）"""

import sys
import os
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTextEdit, QGroupBox, QSpinBox, QDoubleSpinBox,
    QCheckBox, QInputDialog, QStyle, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QFont, QIcon, QPixmap, QPainter
import serial
import serial.tools.list_ports
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np

# 从公共模块导入共享代码
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core import (
    SerialThread, SampleRateDialog, CalibrationDialog,
    load_sensor_config, save_sensor_config, _get_config_file_path,
    card_style, primary_btn_style, accent_btn_style, ModernComboBox,
)


class PhSensorWidget(QWidget):
    """pH传感器模块界面 - 支持单点/两点/三点校准"""

    def __init__(self):
        super().__init__()
        self.serial_thread = None
        self.ph_data = []          # pH 值数据
        self.time_data = []        # 时间数据
        self.adc_data = []         # 原始 ADC 数据
        self.start_timestamp_ms = 0

        # 采样频率设置（毫秒）
        self.sample_interval_ms = 100  # 默认 100ms (10Hz)
        self.last_sample_time_ms = 0   # 上次采样时间

        # 加载保存的配置
        self.config = self.load_config()

        # 校准参数 (pH, ADC) - 支持单点/两点/三点校准
        default_calibration = [
            (4.00, 2555),   # 酸性缓冲液
            (6.86, 2281),   # 中性缓冲液
            (9.18, 2030)    # 碱性缓冲液
        ]
        self.calibration_points = self.config.get('calibration_points', default_calibration)
        self.calibration_mode = self.config.get('calibration_mode', 3)

        # 计算校准系数（根据点数选择拟合方式）
        self.calculate_calibration_coefficients()

        self.init_ui()

    def get_config_path(self):
        """获取配置文件路径（已废弃，保留兼容）"""
        return _get_config_file_path()

    def load_config(self):
        """加载 pH 传感器配置"""
        config = load_sensor_config('ph_sensor')
        if config:
            self.sample_interval_ms = config.get('sample_interval_ms', 100)
            default_calibration = [
                (4.00, 2555), (6.86, 2281), (9.18, 2030)
            ]
            self.calibration_points = config.get('calibration_points', default_calibration)
            self.calibration_mode = config.get('calibration_mode', len(self.calibration_points))
        return config

    def save_config(self):
        """保存 pH 传感器配置"""
        config = {
            'calibration_points': self.calibration_points,
            'calibration_mode': self.calibration_mode,
            'sample_interval_ms': self.sample_interval_ms
        }
        return save_sensor_config('ph_sensor', config)

    def calculate_calibration_coefficients(self):
        """根据校准点数计算拟合系数
        - 单点校准: 使用理论斜率 (-0.5 pH/V) + 偏移量
        - 两点校准: 线性拟合 pH = k*ADC + b
        - 三点校准: 二次拟合 pH = a*ADC^2 + b*ADC + c
        """
        ph_values = [p[0] for p in self.calibration_points]
        adc_values = [p[1] for p in self.calibration_points]

        num_points = len(self.calibration_points)

        if num_points == 1:
            ph0, adc0 = self.calibration_points[0]
            theoretical_slope = -0.59  # 理论斜率 (pH/V), Nernst方程在25°C约为-59mV/pH
            intercept = ph0 - theoretical_slope * adc0
            self.cal_coeffs = (0, theoretical_slope, intercept)  # 二次项为0
            self.calibration_mode = 1

        elif num_points == 2:
            coefficients = np.polyfit(adc_values, ph_values, 1)
            self.cal_coeffs = (0, coefficients[0], coefficients[1])  # 扩展为3元组
            self.calibration_mode = 2

        else:  # 3点或更多
            coefficients = np.polyfit(adc_values, ph_values, min(2, num_points-1))
            if len(coefficients) == 2:
                self.cal_coeffs = (0, coefficients[0], coefficients[1])
            else:
                self.cal_coeffs = tuple(coefficients)
            self.calibration_mode = num_points

    def adc_to_ph(self, adc_value):
        """将ADC原始值转换为pH值（支持不同校准模式）"""
        if not hasattr(self, 'cal_coeffs'):
            return 7.0

        a, b, c = self.cal_coeffs
        ph_value = a * (adc_value ** 2) + b * adc_value + c

        return max(0.0, min(14.0, ph_value))

    def init_ui(self):
        layout = QVBoxLayout()

        # 控制面板
        control_group = QGroupBox("控制面板")
        control_layout = QHBoxLayout()

        # 串口选择
        control_layout.addWidget(QLabel("串口:"))
        self.port_combo = ModernComboBox()
        self.refresh_ports()
        control_layout.addWidget(self.port_combo)

        # 刷新按钮
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        control_layout.addWidget(self.refresh_btn)

        # 连接按钮
        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(self.toggle_connection)
        control_layout.addWidget(self.connect_btn)

        control_layout.addStretch()

        # 采样频率显示
        control_layout.addWidget(QLabel("采样:"))
        self.sample_rate_label = QLabel(f"{1000//self.sample_interval_ms}Hz")
        self.sample_rate_label.setStyleSheet("color: #0078d4; font-weight: bold;")
        control_layout.addWidget(self.sample_rate_label)

        # 采样频率设置按钮
        sample_settings_btn = QPushButton("⚙️")
        sample_settings_btn.setFixedWidth(40)
        sample_settings_btn.setToolTip("设置采样频率")
        sample_settings_btn.clicked.connect(self.edit_sample_rate)
        sample_settings_btn.setStyleSheet("""
            QPushButton {
                background-color: #f0f0f0;
                border: 1px solid #ccc;
                border-radius: 4px;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
            QPushButton:pressed {
                background-color: #d0d0d0;
            }
        """)
        control_layout.addWidget(sample_settings_btn)

        control_layout.addStretch()

        # 校准信息显示
        control_layout.addWidget(QLabel("校准状态:"))
        mode_names = {1: "单点校准", 2: "两点校准", 3: "三点校准"}
        mode_name = mode_names.get(self.calibration_mode, f"{self.calibration_mode}点校准")
        self.calibration_label = QLabel(f"✓ {mode_name}")
        self.calibration_label.setStyleSheet("color: green; font-weight: bold;")
        control_layout.addWidget(self.calibration_label)

        control_group.setLayout(control_layout)
        layout.addWidget(control_group)

        # 校准参数显示卡片
        cal_info_group = QGroupBox("校准参数")
        cal_info_layout = QVBoxLayout()

        # 校准参数显示
        cal_lines = []
        for i, (ph_val, adc_val) in enumerate(self.calibration_points):
            cal_lines.append(f"• pH {ph_val:.2f} → ADC {adc_val}")
        self.cal_text = QLabel("\n".join(cal_lines) if cal_lines else "未设置校准参数")
        self.cal_text.setStyleSheet("font-size: 12px; color: #666;")
        cal_info_layout.addWidget(self.cal_text)

        # 编辑按钮
        edit_btn = QPushButton("✏️ 编辑校准参数")
        edit_btn.clicked.connect(self.edit_calibration)
        edit_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
            QPushButton:pressed {
                background-color: #005a9e;
            }
        """)
        cal_info_layout.addWidget(edit_btn)

        cal_info_group.setLayout(cal_info_layout)
        layout.addWidget(cal_info_group)

        # 数据显示区域
        data_group = QGroupBox("实时数据")
        data_layout = QHBoxLayout()

        # 左侧：文本数据显示
        text_widget = QWidget()
        text_layout = QVBoxLayout()

        # 当前pH值（大字显示）
        self.current_ph_label = QLabel("pH: --.-")
        self.current_ph_label.setFont(QFont("Arial", 28, QFont.Weight.Bold))
        self.current_ph_label.setStyleSheet("color: #0078d4; padding: 10px;")
        text_layout.addWidget(self.current_ph_label)

        # 当前ADC值
        self.current_adc_label = QLabel("ADC: ----")
        self.current_adc_label.setFont(QFont("Arial", 14))
        text_layout.addWidget(self.current_adc_label)

        # 统计信息
        self.stats_label = QLabel("统计信息: 暂无数据")
        text_layout.addWidget(self.stats_label)

        # 数据记录
        self.data_text = QTextEdit()
        self.data_text.setMaximumHeight(120)
        text_layout.addWidget(QLabel("数据记录:"))
        text_layout.addWidget(self.data_text)

        text_widget.setLayout(text_layout)
        data_layout.addWidget(text_widget)

        # 右侧：图表显示
        self.figure = Figure(figsize=(8, 5))
        self.canvas = FigureCanvas(self.figure)
        data_layout.addWidget(self.canvas)

        data_group.setLayout(data_layout)
        layout.addWidget(data_group)

        # 控制按钮
        button_layout = QHBoxLayout()

        self.start_btn = QPushButton("开始采集")
        self.start_btn.clicked.connect(self.start_collection)
        self.start_btn.setEnabled(False)
        button_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("停止采集")
        self.stop_btn.clicked.connect(self.stop_collection)
        self.stop_btn.setEnabled(False)
        button_layout.addWidget(self.stop_btn)

        self.save_btn = QPushButton("保存数据")
        self.save_btn.clicked.connect(self.save_data)
        self.save_btn.setEnabled(False)
        button_layout.addWidget(self.save_btn)

        self.clear_btn = QPushButton("清除数据")
        self.clear_btn.clicked.connect(self.clear_data)
        button_layout.addWidget(self.clear_btn)

        button_layout.addStretch()
        layout.addLayout(button_layout)

        self.setLayout(layout)

        # 定时器用于更新图表
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_chart)
        self.timer.start(100)

    def refresh_ports(self):
        """刷新可用串口列表"""
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.port_combo.addItem(port.device)

    def toggle_connection(self):
        """切换串口连接状态"""
        if self.serial_thread and self.serial_thread.isRunning():
            self.disconnect_serial()
        else:
            self.connect_serial()

    def connect_serial(self):
        """连接串口"""
        port = self.port_combo.currentText()
        if not port:
            QMessageBox.warning(self, "错误", "请选择串口")
            return

        try:
            self.serial_thread = SerialThread(port)
            self.serial_thread.data_received.connect(self.handle_data)
            self.serial_thread.start()

            self.connect_btn.setText("断开")
            self.start_btn.setEnabled(True)
            self.current_ph_label.setText("pH: --.-")
            self.current_adc_label.setText("ADC: ----")

        except Exception as e:
            QMessageBox.critical(self, "连接错误", f"无法连接串口: {e}")

    def disconnect_serial(self):
        """断开串口连接"""
        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread.wait()
            self.serial_thread = None

        self.connect_btn.setText("连接")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.current_ph_label.setText("pH: --.-")
        self.current_adc_label.setText("ADC: 已断开")

    def start_collection(self):
        """开始数据采集"""
        self.ph_data.clear()
        self.time_data.clear()
        self.adc_data.clear()
        self.data_text.clear()
        self.last_sample_time_ms = 0  # 重置采样时间

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.save_btn.setEnabled(False)

        self.current_ph_label.setText("pH: 采集中...")
        self.current_adc_label.setText("ADC: 采集中...")

    def stop_collection(self):
        """停止数据采集"""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.save_btn.setEnabled(len(self.ph_data) > 0)

        if len(self.ph_data) > 0:
            avg_ph = np.mean(self.ph_data)
            self.current_ph_label.setText(f"pH: {avg_ph:.2f}")

    def handle_data(self, data):
        """处理接收到的数据"""
        if data.startswith("ERROR:"):
            QMessageBox.critical(self, "串口错误", data[6:])
            self.disconnect_serial()
            return

        if data == "START":
            self.current_ph_label.setText("pH: 等待数据...")
            self.current_adc_label.setText("ADC: 设备就绪")
            return

        if not self.stop_btn.isEnabled():
            return

        try:
            if "," in data:
                parts = data.split(",")
                if len(parts) == 2:
                    timestamp_ms = int(parts[0])  # 毫秒时间戳
                    adc_value = int(parts[1])

                    # 过滤无效 ADC 值（0-4095 范围）
                    if adc_value < 0 or adc_value > 4095:
                        return

                    # 采样频率控制：检查是否达到采样间隔
                    if timestamp_ms - self.last_sample_time_ms < self.sample_interval_ms:
                        return  # 未达到采样间隔，跳过此数据

                    # 更新上次采样时间
                    self.last_sample_time_ms = timestamp_ms

                    # 记录起始时间
                    if len(self.time_data) == 0:
                        self.start_timestamp_ms = timestamp_ms

                    # 计算相对时间（秒）
                    relative_time_s = (timestamp_ms - self.start_timestamp_ms) / 1000.0

                    # 使用校准转换pH值
                    ph_value = self.adc_to_ph(adc_value)

                    # 存储数据
                    self.ph_data.append(ph_value)
                    self.time_data.append(relative_time_s)
                    self.adc_data.append(adc_value)

                    # 更新显示
                    current_time = datetime.now()
                    time_str = current_time.strftime("%H:%M:%S.%f")[:-3]

                    display_text = f"时间: {time_str} | ADC: {adc_value} | pH: {ph_value:.2f}"
                    self.current_ph_label.setText(f"pH: {ph_value:.2f}")
                    self.current_adc_label.setText(f"ADC: {adc_value}")

                    # 添加到数据记录
                    self.data_text.append(display_text)
                    self.data_text.verticalScrollBar().setValue(
                        self.data_text.verticalScrollBar().maximum()
                    )

                    # 更新统计信息
                    self.update_stats()

        except ValueError:
            pass

    def update_stats(self):
        """更新统计信息"""
        if len(self.ph_data) > 0:
            avg_ph = np.mean(self.ph_data)
            max_ph = np.max(self.ph_data)
            min_ph = np.min(self.ph_data)
            std_ph = np.std(self.ph_data)

            stats_text = (f"统计: 数据点 {len(self.ph_data)} | "
                         f"平均 pH={avg_ph:.2f} | "
                         f"最大 pH={max_ph:.2f} | "
                         f"最小 pH={min_ph:.2f} | "
                         f"标准差 σ={std_ph:.3f}")
            self.stats_label.setText(stats_text)

    def update_chart(self):
        """更新pH值图表"""
        if len(self.ph_data) > 0:
            self.figure.clear()
            ax = self.figure.add_subplot(111)

            # 绘制pH值曲线
            ax.plot(self.time_data, self.ph_data, 'b-', linewidth=2, label='pH值')

            # 添加参考线（中性pH=7）
            ax.axhline(y=7.0, color='r', linestyle='--', alpha=0.5, label='中性(pH=7)')

            ax.set_xlabel('时间 (秒)')
            ax.set_ylabel('pH值')
            ax.set_title('pH传感器实时数据', fontsize=14, fontweight='bold')
            ax.set_ylim(0, 14)
            ax.grid(True, alpha=0.3)
            ax.legend(loc='upper right')

            # 自动调整坐标轴范围
            if len(self.time_data) > 1:
                ax.set_xlim(min(self.time_data), max(self.time_data))

            self.figure.tight_layout()
            self.canvas.draw()

    def save_data(self):
        """保存数据到文件"""
        if len(self.ph_data) == 0:
            QMessageBox.warning(self, "警告", "没有数据可保存")
            return

        try:
            filename = f"ph_sensor_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("time_s,adc_raw,ph_value\n")
                for i, (time_val, ph_val, adc_val) in enumerate(
                    zip(self.time_data, self.ph_data, self.adc_data)):
                    f.write(f"{time_val:.3f},{adc_val},{ph_val:.3f}\n")

            QMessageBox.information(self, "成功",
                                   f"数据已保存到：{filename}\n"
                                   f"共 {len(self.ph_data)} 个数据点")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败：{e}")

    def edit_sample_rate(self):
        """编辑采样频率对话框"""
        dialog = SampleRateDialog(self.sample_interval_ms, self)
        if dialog.exec() == 1:  # QDialog.Accepted
            # 获取新的采样间隔
            new_interval_ms = dialog.get_sample_interval()

            # 更新采样间隔
            self.sample_interval_ms = new_interval_ms

            # 更新显示
            freq = 1000 // new_interval_ms
            self.sample_rate_label.setText(f"{freq}Hz")

            # 保存配置到文件
            self.save_config()

            QMessageBox.information(self, "成功",
                                   f"采样频率已更新为 {freq} Hz！\n"
                                   f"采样间隔：{new_interval_ms} ms\n"
                                   f"配置已自动保存，下次启动时生效。")

    def clear_data(self):
        """清除数据"""
        self.ph_data.clear()
        self.time_data.clear()
        self.adc_data.clear()
        self.data_text.clear()
        self.stats_label.setText("统计信息：暂无数据")
        self.current_ph_label.setText("pH: --.-")
        self.current_adc_label.setText("ADC: ----")
        self.figure.clear()
        self.canvas.draw()
        self.save_btn.setEnabled(False)

    def edit_calibration(self):
        """编辑校准参数对话框"""
        dialog = CalibrationDialog(self.calibration_points, self)
        if dialog.exec() == 1:  # QDialog.Accepted
            new_points = dialog.get_calibration_points()
            self.calibration_mode = dialog.get_calibration_mode()

            self.calibration_points = new_points
            self.calculate_calibration_coefficients()

            mode_names = {1: "单点校准", 2: "两点校准", 3: "三点校准"}
            mode_name = mode_names.get(self.calibration_mode, f"{self.calibration_mode}点校准")
            self.calibration_label.setText(f"✓ {mode_name}")

            cal_lines = []
            for ph_val, adc_val in new_points:
                cal_lines.append(f"• pH {ph_val:.2f} → ADC {adc_val}")
            self.cal_text.setText("\n".join(cal_lines))

            # 保存配置到文件
            self.save_config()

            QMessageBox.information(self, "成功",
                                   "校准参数已更新并保存！\n新的校准曲线将立即生效。\n下次启动程序时会自动加载此配置。")
