#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
物理实验数据采集软件
支持多种传感器模块的数据采集和管理
"""

import sys
import os
import json
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLabel, QPushButton, QFrame, QStackedWidget,
                            QListWidget, QListWidgetItem, QMessageBox, QComboBox,
                            QTextEdit, QGroupBox, QSpinBox, QDoubleSpinBox, QCheckBox,
                            QStyle, QDialog, QLineEdit, QRadioButton, QScrollArea,
                            QInputDialog, QGridLayout)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QSize
from PyQt6.QtGui import QFont, QIcon, QPalette, QColor, QPixmap, QPainter
import serial
import serial.tools.list_ports
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np

try:
    import asyncio
    from bleak import BleakClient, BleakScanner
    BLE_AVAILABLE = True
except ImportError:
    BLE_AVAILABLE = False

import threading

# ============================================================
# 统一配置管理 — 所有传感器校准配置保存在同一个 JSON 文件
# ============================================================
CONFIG_FILENAME = 'sensor_config.json'


def _get_config_file_path():
    """获取统一配置文件的绝对路径"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_FILENAME)


def load_sensor_config(module_name):
    """从统一配置文件中读取指定模块的配置
    
    Args:
        module_name: 模块名称，如 'ph_sensor'、'force_sensor'
    
    Returns:
        dict: 该模块的配置字典，不存在则返回空字典
    """
    config_path = _get_config_file_path()
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                all_config = json.load(f)
            module_config = all_config.get(module_name, {})
            if module_config:
                print(f"✓ 已加载 [{module_name}] 配置")
            else:
                print(f"ℹ️ [{module_name}] 无已保存配置，使用默认值")
            return module_config
        else:
            print(f"ℹ️ 配置文件不存在：{config_path}，所有模块使用默认值")
            return {}
    except Exception as e:
        print(f"⚠️ 读取配置文件失败：{e}")
        return {}


def save_sensor_config(module_name, config_dict):
    """将指定模块的配置写入统一配置文件
    
    Args:
        module_name: 模块名称，如 'ph_sensor'、'force_sensor'
        config_dict: 该模块的配置字典
    
    Returns:
        bool: 是否保存成功
    """
    config_path = _get_config_file_path()
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                all_config = json.load(f)
        else:
            all_config = {}
        
        all_config[module_name] = config_dict
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(all_config, f, ensure_ascii=False, indent=2)
        
        print(f"✓ [{module_name}] 配置已保存到 {config_path}")
        return True
    except Exception as e:
        print(f"⚠️ 保存 [{module_name}] 配置失败：{e}")
        return False


# 设置 matplotlib 全局字体为微软雅黑
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题


class SerialThread(QThread):
    """串口通信线程"""
    data_received = pyqtSignal(str)
    
    def __init__(self, port, baudrate=115200):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.serial = None
        self.running = False
    
    def run(self):
        try:
            self.serial = serial.Serial(self.port, self.baudrate, timeout=1)
            self.running = True
            
            # 清空串口缓冲区
            self.serial.reset_input_buffer()
            
            while self.running:
                try:
                    if self.serial.in_waiting > 0:
                        line = self.serial.readline().decode('utf-8', errors='ignore').strip()
                        if line:
                            self.data_received.emit(line)
                except Exception as e:
                    print(f"读取串口数据错误: {e}")
                    break
        except Exception as e:
            print(f"串口错误: {e}")
            self.data_received.emit(f"ERROR:{e}")
    
    def stop(self):
        self.running = False
        if self.serial:
            self.serial.close()


BLE_NUS_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
BLE_NUS_TX_UUID      = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
BLE_NUS_RX_UUID      = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"


class BLESerialThread(QThread):
    """BLE 串口通信线程 — 基于 bleak 库连接 ESP32-S3 的 NUS 服务"""
    data_received = pyqtSignal(str)
    connection_status = pyqtSignal(str)

    def __init__(self, device_address, device_name=""):
        super().__init__()
        self.device_address = device_address
        self.device_name = device_name
        self.running = False
        self._buffer = ""
        self._client = None

    def run(self):
        if not BLE_AVAILABLE:
            self.data_received.emit("ERROR:bleak 库未安装，请运行 pip install bleak")
            return

        self.running = True

        try:
            asyncio.run(self._ble_loop())
        except asyncio.CancelledError:
            pass
        except Exception as e:
            error_msg = str(e)
            if "not found" in error_msg.lower() or "could not find" in error_msg.lower():
                self.data_received.emit("ERROR:设备未找到，请确保 ESP32-S3 已上电并配对")
            elif "timeout" in error_msg.lower():
                self.data_received.emit("ERROR:连接超时，请检查设备是否在范围内")
            else:
                self.data_received.emit(f"ERROR:BLE 连接失败: {error_msg}")

    async def _ble_loop(self):
        try:
            self._client = BleakClient(
                self.device_address,
                timeout=10.0,
                disconnected_callback=self._on_disconnected
            )

            await self._client.connect()

            if self._client.is_connected:
                self.connection_status.emit("connected")
                self.data_received.emit("START")
            else:
                self.data_received.emit("ERROR:连接建立失败")
                return

            try:
                await self._client.start_notify(BLE_NUS_TX_UUID, self._notification_handler)
            except Exception as e:
                self.data_received.emit(f"ERROR:无法订阅数据通知: {e}")
                return

            while self.running and self._client.is_connected:
                await asyncio.sleep(0.05)

            if self._client.is_connected:
                try:
                    await self._client.stop_notify(BLE_NUS_TX_UUID)
                except:
                    pass
                try:
                    await self._client.disconnect()
                except:
                    pass

        except Exception as e:
            raise e

    def _notification_handler(self, sender, data):
        try:
            text = data.decode('utf-8', errors='ignore')
            self._buffer += text
            while '\n' in self._buffer:
                line, self._buffer = self._buffer.split('\n', 1)
                line = line.strip()
                if line:
                    self.data_received.emit(line)
        except Exception as e:
            print(f"BLE 数据处理错误: {e}")

    def _on_disconnected(self, client):
        if self.running:
            self.data_received.emit("ERROR:设备意外断开连接")
            self.running = False

    def stop(self):
        self.running = False
        if self._client and self._client.is_connected:
            try:
                asyncio.run(self._client.disconnect())
            except:
                pass


def scan_ble_devices():
    """扫描附近的 BLE 设备，返回 [(名称, 地址), ...]"""
    if not BLE_AVAILABLE:
        return []

    try:
        devices = asyncio.run(BleakScanner.discover(timeout=5.0))
        result = []
        for d in devices:
            name = d.name or "未知设备"
            result.append((name, d.address))
        return sorted(result, key=lambda x: x[0])
    except Exception as e:
        print(f"BLE 扫描错误: {e}")
        return []


class UltrasonicWidget(QWidget):
    """超声波位移模块界面"""

    def __init__(self):
        super().__init__()
        self.serial_thread = None
        self.data_points = []
        self.timestamps = []
        self.start_time = None
        self.start_timestamp_us = 0  # 记录第一个数据点的时间戳

        # 采样频率设置（毫秒）
        self.sample_interval_ms = 100  # 默认 100ms (10Hz)
        self.last_sample_time_ms = 0   # 上次采样时间

        self.init_ui()
    
    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: #f3f3f3; }")

        content = QWidget()
        content.setStyleSheet("background: #f3f3f3;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)

        # 页面标题
        title = QLabel("超声波位移")
        title.setFont(QFont("Microsoft YaHei", 28, QFont.Weight.Bold))
        title.setStyleSheet("color: #1a1a1a; margin-bottom: 4px;")
        layout.addWidget(title)

        # ========== 卡片1：连接控制 ==========
        card_conn = QWidget()
        card_conn.setObjectName("card")
        card_conn.setStyleSheet(self._card_style())
        card_layout = QVBoxLayout(card_conn)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.setSpacing(12)

        card_title = QLabel("连接控制")
        card_title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        card_title.setStyleSheet("color: #1a1a1a;")
        card_layout.addWidget(card_title)

        conn_row = QHBoxLayout()
        conn_row.setSpacing(10)

        conn_row.addWidget(QLabel("串口:"))
        self.port_combo = QComboBox()
        self.refresh_ports()
        self.port_combo.setMinimumWidth(160)
        conn_row.addWidget(self.port_combo)

        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setFixedHeight(36)
        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.refresh_btn.setStyleSheet(self._accent_btn_style("#f0f0f0", "#e0e0e0", "#d0d0d0"))
        conn_row.addWidget(self.refresh_btn)

        self.connect_btn = QPushButton("连接")
        self.connect_btn.setFixedHeight(36)
        self.connect_btn.clicked.connect(self.toggle_connection)
        self.connect_btn.setStyleSheet(self._primary_btn_style())
        conn_row.addWidget(self.connect_btn)

        conn_row.addSpacing(20)

        conn_row.addWidget(QLabel("采样:"))
        self.sample_rate_label = QLabel(f"{1000 // self.sample_interval_ms}Hz")
        self.sample_rate_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        self.sample_rate_label.setStyleSheet("color: #0078d4;")
        conn_row.addWidget(self.sample_rate_label)

        sample_settings_btn = QPushButton("⚙")
        sample_settings_btn.setFixedSize(36, 36)
        sample_settings_btn.setToolTip("设置采样频率")
        sample_settings_btn.clicked.connect(self.edit_sample_rate)
        sample_settings_btn.setStyleSheet(self._accent_btn_style("#f0f0f0", "#e0e0e0", "#d0d0d0"))
        conn_row.addWidget(sample_settings_btn)

        conn_row.addStretch()
        card_layout.addLayout(conn_row)
        layout.addWidget(card_conn)

        # ========== 卡片2：实时数据 ==========
        card_data = QWidget()
        card_data.setObjectName("card")
        card_data.setStyleSheet(self._card_style())
        data_card_layout = QVBoxLayout(card_data)
        data_card_layout.setContentsMargins(20, 16, 20, 16)
        data_card_layout.setSpacing(12)

        data_card_title = QLabel("实时数据")
        data_card_title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        data_card_title.setStyleSheet("color: #1a1a1a;")
        data_card_layout.addWidget(data_card_title)

        self.current_data_label = QLabel("等待连接...")
        self.current_data_label.setFont(QFont("Microsoft YaHei", 11))
        self.current_data_label.setStyleSheet("color: #444444;")
        data_card_layout.addWidget(self.current_data_label)

        self.stats_label = QLabel("暂无数据")
        self.stats_label.setFont(QFont("Microsoft YaHei", 10))
        self.stats_label.setStyleSheet("color: #888888;")
        data_card_layout.addWidget(self.stats_label)

        layout.addWidget(card_data)

        # ========== 卡片3：图表 + 数据记录 ==========
        card_chart = QWidget()
        card_chart.setObjectName("card")
        card_chart.setStyleSheet(self._card_style())
        chart_card_layout = QVBoxLayout(card_chart)
        chart_card_layout.setContentsMargins(20, 16, 20, 16)
        chart_card_layout.setSpacing(12)

        chart_header = QHBoxLayout()
        chart_title = QLabel("距离-时间曲线")
        chart_title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        chart_title.setStyleSheet("color: #1a1a1a;")
        chart_header.addWidget(chart_title)
        chart_header.addStretch()
        chart_card_layout.addLayout(chart_header)

        content_row = QHBoxLayout()
        content_row.setSpacing(16)

        # 左侧：数据记录
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        record_label = QLabel("数据记录")
        record_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        record_label.setStyleSheet("color: #1a1a1a;")
        left_layout.addWidget(record_label)

        self.data_text = QTextEdit()
        self.data_text.setReadOnly(True)
        self.data_text.setStyleSheet("""
            QTextEdit {
                background-color: #fafafa;
                border: 1px solid #e5e5e5;
                border-radius: 6px;
                padding: 8px;
                font-size: 11px;
                color: #333333;
            }
        """)
        left_layout.addWidget(self.data_text)
        content_row.addWidget(left_panel, stretch=1)

        # 右侧：图表
        self.figure = Figure(figsize=(8, 6), dpi=100)
        self.figure.set_facecolor('#fafafa')
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setStyleSheet("border: 1px solid #e5e5e5; border-radius: 6px;")
        content_row.addWidget(self.canvas, stretch=2)

        chart_card_layout.addLayout(content_row)
        layout.addWidget(card_chart)

        # ========== 卡片4：操作按钮 ==========
        card_actions = QWidget()
        card_actions.setObjectName("card")
        card_actions.setStyleSheet(self._card_style())
        actions_layout = QHBoxLayout(card_actions)
        actions_layout.setContentsMargins(20, 12, 20, 12)
        actions_layout.setSpacing(10)

        self.start_btn = QPushButton("开始采集")
        self.start_btn.setFixedHeight(38)
        self.start_btn.clicked.connect(self.start_collection)
        self.start_btn.setEnabled(False)
        self.start_btn.setStyleSheet(self._primary_btn_style())
        actions_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("停止采集")
        self.stop_btn.setFixedHeight(38)
        self.stop_btn.clicked.connect(self.stop_collection)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(self._accent_btn_style("#f0f0f0", "#e0e0e0", "#d0d0d0"))
        actions_layout.addWidget(self.stop_btn)

        self.save_btn = QPushButton("保存数据")
        self.save_btn.setFixedHeight(38)
        self.save_btn.clicked.connect(self.save_data)
        self.save_btn.setEnabled(False)
        self.save_btn.setStyleSheet(self._accent_btn_style("#f0f0f0", "#e0e0e0", "#d0d0d0"))
        actions_layout.addWidget(self.save_btn)

        self.clear_btn = QPushButton("清除数据")
        self.clear_btn.setFixedHeight(38)
        self.clear_btn.clicked.connect(self.clear_data)
        self.clear_btn.setStyleSheet(self._accent_btn_style("#f0f0f0", "#e0e0e0", "#d0d0d0"))
        actions_layout.addWidget(self.clear_btn)

        actions_layout.addStretch()
        layout.addWidget(card_actions)

        layout.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll)
        self.setLayout(main_layout)

        # 定时器用于更新图表
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_chart)
        self.timer.start(100)
    
    def _card_style(self):
        return """
            QWidget#card {
                background-color: #ffffff;
                border: 1px solid #e5e5e5;
                border-radius: 8px;
            }
            QWidget#card QLabel,
            QWidget#card QFrame {
                background-color: transparent;
            }
        """

    def _primary_btn_style(self):
        return """
            QPushButton {
                background-color: #0078d4;
                border: none;
                color: white;
                border-radius: 6px;
                font-size: 13px;
                padding: 0 16px;
            }
            QPushButton:hover { background-color: #106ebe; }
            QPushButton:pressed { background-color: #005a9e; }
            QPushButton:disabled { background-color: #cccccc; color: #888888; }
        """

    def _accent_btn_style(self, normal, hover, pressed):
        return f"""
            QPushButton {{
                background-color: {normal};
                border: 1px solid #d0d0d0;
                color: #1a1a1a;
                border-radius: 6px;
                font-size: 13px;
                padding: 0 16px;
            }}
            QPushButton:hover {{ background-color: {hover}; }}
            QPushButton:pressed {{ background-color: {pressed}; }}
            QPushButton:disabled {{ background-color: #f5f5f5; color: #aaaaaa; }}
        """
    
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
            self.current_data_label.setText("已连接，等待数据...")
            
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
        self.current_data_label.setText("已断开")
    
    def start_collection(self):
        """开始数据采集"""
        self.data_points.clear()
        self.timestamps.clear()
        self.start_time = datetime.now()
        self.data_text.clear()
        self.last_sample_time_ms = 0  # 重置采样时间
        
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.save_btn.setEnabled(False)
        
        self.current_data_label.setText("采集进行中...")
    
    def stop_collection(self):
        """停止数据采集"""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.save_btn.setEnabled(len(self.data_points) > 0)
        
        self.current_data_label.setText("采集已停止")
    
    def handle_data(self, data):
        """处理接收到的数据"""
        # 检查是否是错误信息
        if data.startswith("ERROR:"):
            QMessageBox.critical(self, "串口错误", data[6:])
            self.disconnect_serial()
            return
        
        # 检查是否是启动信号
        if data == "START":
            self.current_data_label.setText("设备已启动，等待数据...")
            return
        
        if not self.stop_btn.isEnabled():  # 如果没有在采集状态，忽略数据
            return
        
        try:
            # 解析数据格式: timestamp,echo_time
            if "," in data:
                parts = data.split(",")
                if len(parts) == 2:
                    timestamp_us = int(parts[0])  # 微秒时间戳
                    echo_time = int(parts[1])
                    
                    # 过滤无效数据（回波时间过小或过大）
                    if echo_time < 100 or echo_time > 60000:  # 100µs - 60ms
                        return

                    # 采样频率控制：检查是否达到采样间隔
                    timestamp_ms = timestamp_us // 1000  # 转换为毫秒
                    if timestamp_ms - self.last_sample_time_ms < self.sample_interval_ms:
                        return  # 未达到采样间隔，跳过此数据

                    # 更新上次采样时间
                    self.last_sample_time_ms = timestamp_ms
                    
                    # 计算距离（厘米）
                    distance_cm = echo_time / 58.0
                    
                    # 记录数据
                    current_time = datetime.now()
                    time_str = current_time.strftime("%H:%M:%S.%f")[:-3]
                    
                    # 如果是第一个数据点，记录起始时间
                    if len(self.timestamps) == 0:
                        self.start_timestamp_us = timestamp_us
                    
                    # 计算相对于起始时间的秒数
                    relative_time_s = (timestamp_us - self.start_timestamp_us) / 1000000.0
                    
                    self.data_points.append(distance_cm)
                    self.timestamps.append(relative_time_s)  # 相对时间（秒）
                    
                    # 更新显示
                    display_text = f"时间: {time_str} | 回波: {echo_time}µs | 距离: {distance_cm:.2f}cm | 相对时间: {relative_time_s:.3f}s"
                    self.current_data_label.setText(f"当前数据: {display_text}")
                    
                    # 添加到数据记录
                    self.data_text.append(display_text)
                    
                    # 自动滚动到底部
                    self.data_text.verticalScrollBar().setValue(
                        self.data_text.verticalScrollBar().maximum()
                    )
                    
                    # 更新统计信息
                    self.update_stats()
                    
        except ValueError:
            pass  # 忽略无法解析的数据
    
    def update_stats(self):
        """更新统计信息"""
        if len(self.data_points) > 0:
            avg_distance = np.mean(self.data_points)
            max_distance = np.max(self.data_points)
            min_distance = np.min(self.data_points)
            
            stats_text = f"数据点 {len(self.data_points)} | 平均 {avg_distance:.2f}cm | 最大 {max_distance:.2f}cm | 最小 {min_distance:.2f}cm"
            self.stats_label.setText(stats_text)
    
    def update_chart(self):
        """更新图表"""
        if len(self.data_points) > 0:
            self.figure.clear()
            ax = self.figure.add_subplot(111)
            
            ax.plot(self.timestamps, self.data_points, 'b-', linewidth=2)
            ax.set_xlabel('时间 (秒)')
            ax.set_ylabel('距离 (厘米)')
            ax.set_title('距离传感器的距离 - 实时数据')
            ax.grid(True, alpha=0.3)
            
            # 自动调整坐标轴范围
            if len(self.timestamps) > 1:
                time_range = max(self.timestamps) - min(self.timestamps)
                distance_range = max(self.data_points) - min(self.data_points)
                
                if time_range > 0:
                    ax.set_xlim(min(self.timestamps), max(self.timestamps))
                if distance_range > 0:
                    ax.set_ylim(min(self.data_points) - 0.1 * distance_range,
                               max(self.data_points) + 0.1 * distance_range)
            
            self.canvas.draw()

    def edit_sample_rate(self):
        """编辑采样频率对话框"""
        dialog = SampleRateDialog(self.sample_interval_ms, self)
        if dialog.exec() == 1:  # QDialog.Accepted
            new_interval_ms = dialog.get_sample_interval()
            self.sample_interval_ms = new_interval_ms
            freq = 1000 // new_interval_ms
            self.sample_rate_label.setText(f"{freq}Hz")
            QMessageBox.information(self, "成功",
                                   f"采样频率已更新为 {freq} Hz！\n"
                                   f"采样间隔：{new_interval_ms} ms")

    def save_data(self):
        """保存数据到文件"""
        if len(self.data_points) == 0:
            QMessageBox.warning(self, "警告", "没有数据可保存")
            return
        
        try:
            filename = f"ultrasonic_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("timestamp_ms,distance_cm\n")
                for i, (timestamp, distance) in enumerate(zip(self.timestamps, self.data_points)):
                    f.write(f"{timestamp*1000:.0f},{distance:.3f}\n")
            
            QMessageBox.information(self, "成功", f"数据已保存到: {filename}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")
    
    def clear_data(self):
        """清除数据"""
        self.data_points.clear()
        self.timestamps.clear()
        self.data_text.clear()
        self.stats_label.setText("暂无数据")
        self.current_data_label.setText("等待数据...")
        self.figure.clear()
        self.canvas.draw()
        self.save_btn.setEnabled(False)


class UltrasonicVelocityWidget(QWidget):
    """超声波速度模块界面 - 回声定位法"""

    def __init__(self):
        super().__init__()
        self.serial_thread = None
        self.distance_data = []    # 距离数据
        self.time_data = []        # 时间数据
        self.velocity_data = []    # 速度数据
        self.echo_time_data = []   # 原始回波时间数据 (µs)
        self.start_timestamp_us = 0

        # 采样频率设置（毫秒）
        self.sample_interval_ms = 100  # 默认 100ms (10Hz)
        self.last_sample_time_ms = 0   # 上次采样时间

        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # 控制面板
        control_group = QGroupBox("控制面板")
        control_layout = QHBoxLayout()
        
        # 串口选择
        control_layout.addWidget(QLabel("串口:"))
        self.port_combo = QComboBox()
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

        # 速度计算参数
        control_layout.addWidget(QLabel("采样窗口:"))
        self.window_size_spin = QSpinBox()
        self.window_size_spin.setRange(5, 100)
        self.window_size_spin.setValue(10)
        self.window_size_spin.setSuffix(" 点")
        control_layout.addWidget(self.window_size_spin)
        
        control_group.setLayout(control_layout)
        layout.addWidget(control_group)
        
        # 数据显示区域
        data_group = QGroupBox("实时数据")
        data_layout = QHBoxLayout()
        
        # 左侧：文本数据显示
        text_widget = QWidget()
        text_layout = QVBoxLayout()
        
        # 当前数据
        self.current_data_label = QLabel("当前数据: 等待连接...")
        self.current_data_label.setFont(QFont("Arial", 12))
        text_layout.addWidget(self.current_data_label)
        
        # 速度统计
        self.velocity_stats_label = QLabel("速度统计: 暂无数据")
        text_layout.addWidget(self.velocity_stats_label)
        
        # 数据记录
        self.data_text = QTextEdit()
        self.data_text.setMaximumHeight(150)
        text_layout.addWidget(QLabel("速度记录:"))
        text_layout.addWidget(self.data_text)
        
        text_widget.setLayout(text_layout)
        data_layout.addWidget(text_widget)
        
        # 右侧：图表显示
        self.figure = Figure(figsize=(8, 6))
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
        self.timer.start(100)  # 每100ms更新一次图表
    
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
            self.current_data_label.setText("当前数据: 已连接，等待数据...")
            
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
        self.current_data_label.setText("当前数据: 已断开")
    
    def start_collection(self):
        """开始数据采集"""
        self.distance_data.clear()
        self.time_data.clear()
        self.velocity_data.clear()
        self.echo_time_data.clear()  # 清除回波时间数据
        self.data_text.clear()
        self.last_sample_time_ms = 0  # 重置采样时间
        
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.save_btn.setEnabled(False)
        
        self.current_data_label.setText("当前数据: 采集进行中...")
    
    def stop_collection(self):
        """停止数据采集"""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.save_btn.setEnabled(len(self.distance_data) > 0)
        
        self.current_data_label.setText("当前数据: 采集已停止")
    
    def handle_data(self, data):
        """处理接收到的数据 - 回声定位法计算速度"""
        # 检查是否是错误信息
        if data.startswith("ERROR:"):
            QMessageBox.critical(self, "串口错误", data[6:])
            self.disconnect_serial()
            return
        
        # 检查是否是启动信号
        if data == "START":
            self.current_data_label.setText("当前数据: 设备已启动，等待数据...")
            return
        
        if not self.stop_btn.isEnabled():  # 如果没有在采集状态，忽略数据
            return
        
        try:
            # 解析数据格式: timestamp,echo_time
            if "," in data:
                parts = data.split(",")
                if len(parts) == 2:
                    timestamp_us = int(parts[0])  # 微秒时间戳
                    echo_time = int(parts[1])
                    
                    # 过滤无效数据
                    if echo_time < 100 or echo_time > 60000:
                        return

                    # 采样频率控制：检查是否达到采样间隔
                    timestamp_ms = timestamp_us // 1000  # 转换为毫秒
                    if timestamp_ms - self.last_sample_time_ms < self.sample_interval_ms:
                        return  # 未达到采样间隔，跳过此数据

                    # 更新上次采样时间
                    self.last_sample_time_ms = timestamp_ms
                    
                    # 计算距离（厘米）
                    distance_cm = echo_time / 58.0
                    
                    # 如果是第一个数据点，记录起始时间
                    if len(self.time_data) == 0:
                        self.start_timestamp_us = timestamp_us
                    
                    # 计算相对于起始时间的秒数
                    relative_time_s = (timestamp_us - self.start_timestamp_us) / 1000000.0
                    
                    # 记录距离、时间和原始回波时间数据
                    self.distance_data.append(distance_cm)
                    self.time_data.append(relative_time_s)
                    self.echo_time_data.append(echo_time)  # 保存原始回波时间
                    
                    # 回声定位法计算速度
                    velocity = self.calculate_velocity()
                    if velocity is not None:
                        self.velocity_data.append(velocity)
                    
                    # 更新显示
                    current_time = datetime.now()
                    time_str = current_time.strftime("%H:%M:%S.%f")[:-3]
                    
                    if velocity is not None:
                        display_text = f"时间: {time_str} | 距离: {distance_cm:.2f}cm | 速度: {velocity:.2f}cm/s"
                        self.current_data_label.setText(display_text)
                        
                        # 添加到数据记录
                        self.data_text.append(display_text)
                        
                        # 自动滚动到底部
                        self.data_text.verticalScrollBar().setValue(
                            self.data_text.verticalScrollBar().maximum()
                        )
                    
                    # 更新统计信息
                    self.update_stats()
                    
        except ValueError:
            pass  # 忽略无法解析的数据
    
    def calculate_velocity(self):
        """回声定位法计算速度 - 基于两次测量的时间差
        
        算法原理：
        v = (t₀ - t₁)/2 × vₛ / [(t₁ + t₀)/2 + Δt]
        
        其中：
        - t₀: 第一次回波时间 (µs)
        - t₁: 第二次回波时间 (µs)
        - Δt: 两次发射的时间间隔 (s)
        - vₛ: 声速 = 34000 cm/s
        """
        if len(self.distance_data) < 2:
            return None
        
        try:
            # 获取最近两次测量的数据
            t0 = self.echo_time_data[-2]  # 第一次回波时间 (µs)
            t1 = self.echo_time_data[-1]  # 第二次回波时间 (µs)
            
            # 计算两次发射的时间间隔 Δt (秒)
            # 使用 Arduino 的测量间隔 (MIN_INTERVAL = 20000 µs = 0.02s)
            delta_t = 0.02  # 默认 20ms
            if len(self.time_data) >= 2:
                delta_t = self.time_data[-1] - self.time_data[-2]
            
            # 声速 (cm/s)
            v_sound = 34000  # 340 m/s = 34000 cm/s
            
            # 计算速度 (cm/s)
            # v = (t₀ - t₁)/2 × vₛ / [(t₁ + t₀)/2 + Δt]
            numerator = (t0 - t1) / 2.0 * v_sound
            denominator = (t1 + t0) / 2.0 + delta_t * 1000000  # 将 Δt 转换为 µs
            
            if denominator == 0:
                return None
            
            velocity_cm_s = numerator / denominator
            
            return velocity_cm_s
            
        except Exception as e:
            print(f"速度计算错误: {e}")
            return None
    
    def update_stats(self):
        """更新速度统计信息"""
        if len(self.velocity_data) > 0:
            avg_velocity = np.mean(self.velocity_data)
            max_velocity = np.max(self.velocity_data)
            min_velocity = np.min(self.velocity_data)
            
            stats_text = f"速度统计: 数据点 {len(self.velocity_data)} | " \
                        f"平均 {avg_velocity:.2f}cm/s | " \
                        f"最大 {max_velocity:.2f}cm/s | " \
                        f"最小 {min_velocity:.2f}cm/s"
            self.velocity_stats_label.setText(stats_text)
    
    def update_chart(self):
        """更新速度图表"""
        if len(self.velocity_data) > 0:
            self.figure.clear()
            
            # 创建子图
            ax1 = self.figure.add_subplot(211)  # 距离-时间图
            ax2 = self.figure.add_subplot(212)  # 速度-时间图
            
            # 绘制距离-时间图
            ax1.plot(self.time_data, self.distance_data, 'b-', linewidth=2)
            ax1.set_xlabel('时间 (秒)')
            ax1.set_ylabel('距离 (厘米)')
            ax1.set_title('距离传感器的距离')
            ax1.grid(True, alpha=0.3)
            
            # 绘制速度-时间图
            ax2.plot(self.time_data[len(self.time_data)-len(self.velocity_data):], 
                    self.velocity_data, 'r-', linewidth=2)
            ax2.set_xlabel('时间 (秒)')
            ax2.set_ylabel('速度 (厘米/秒)')
            ax2.set_title('物体运动速度 - 回声定位法')
            ax2.grid(True, alpha=0.3)
            
            # 自动调整布局
            self.figure.tight_layout()
            self.canvas.draw()

    def edit_sample_rate(self):
        """编辑采样频率对话框"""
        dialog = SampleRateDialog(self.sample_interval_ms, self)
        if dialog.exec() == 1:  # QDialog.Accepted
            new_interval_ms = dialog.get_sample_interval()
            self.sample_interval_ms = new_interval_ms
            freq = 1000 // new_interval_ms
            self.sample_rate_label.setText(f"{freq}Hz")
            QMessageBox.information(self, "成功",
                                   f"采样频率已更新为 {freq} Hz！\n"
                                   f"采样间隔：{new_interval_ms} ms")

    def save_data(self):
        """保存数据到文件 - 超声波速度"""
        if len(self.distance_data) == 0:
            QMessageBox.warning(self, "警告", "没有数据可保存")
            return
        
        try:
            filename = f"ultrasonic_velocity_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("time_s,distance_cm,velocity_cm_s\n")
                for i, (time_val, distance, velocity) in enumerate(
                    zip(self.time_data, self.distance_data, 
                        self.velocity_data + [None] * (len(self.distance_data) - len(self.velocity_data)))):
                    
                    velocity_str = f"{velocity:.3f}" if velocity is not None else ""
                    f.write(f"{time_val:.3f},{distance:.3f},{velocity_str}\n")
            
            QMessageBox.information(self, "成功", f"数据已保存到: {filename}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")
    
    def clear_data(self):
        """清除数据"""
        self.distance_data.clear()
        self.time_data.clear()
        self.velocity_data.clear()
        self.echo_time_data.clear()  # 清除回波时间数据
        self.data_text.clear()
        self.velocity_stats_label.setText("速度统计: 暂无数据")
        self.current_data_label.setText("当前数据: 等待数据...")
        self.figure.clear()
        self.canvas.draw()
        self.save_btn.setEnabled(False)


class HomePageWidget(QWidget):
    """主页面 - Win11 风格卡片布局"""
    
    module_clicked = pyqtSignal(str)
    
    CARD_STYLE = """
        QWidget#card {
            background-color: #ffffff;
            border: 1px solid #e5e5e5;
            border-radius: 8px;
        }
        QWidget#card QLabel,
        QWidget#card QFrame {
            background-color: transparent;
        }
    """
    
    CARD_HOVER_STYLE = """
        QPushButton#module_item {
            background-color: transparent;
            border: none;
            border-radius: 6px;
            text-align: left;
            padding: 12px 16px;
        }
        QPushButton#module_item:hover {
            background-color: #f0f0f0;
        }
        QPushButton#module_item:pressed {
            background-color: #e5e5e5;
        }
    """
    
    def __init__(self):
        super().__init__()
        self.init_ui()
    
    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: #f3f3f3; }")
        
        content = QWidget()
        content.setStyleSheet("background: #f3f3f3;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 24)
        content_layout.setSpacing(16)
        
        # 页面标题
        title = QLabel("主页")
        title.setFont(QFont("Microsoft YaHei", 28, QFont.Weight.Bold))
        title.setStyleSheet("color: #1a1a1a; margin-bottom: 4px;")
        content_layout.addWidget(title)
        
        # ========== 卡片1：版本信息 + 项目简介 ==========
        card1 = QWidget()
        card1.setObjectName("card")
        card1.setStyleSheet(self.CARD_STYLE)
        card1_layout = QVBoxLayout(card1)
        card1_layout.setContentsMargins(20, 20, 20, 20)
        card1_layout.setSpacing(12)
        
        # 顶部：应用图标 + 名称 + 版本 + GitHub按钮
        top_row = QWidget()
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(16)
        
        # 应用图标
        icon_label = QLabel("🔬")
        icon_label.setFont(QFont("Segoe MDL2 Assets", 36))
        icon_label.setFixedSize(64, 64)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("""
            background-color: #e8f0fe;
            border-radius: 12px;
            color: #0067c0;
        """)
        top_layout.addWidget(icon_label)
        
        # 应用名称和版本
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        
        app_name = QLabel("PhysChem-DigitizerP")
        app_name.setFont(QFont("Microsoft YaHei", 18, QFont.Weight.Bold))
        app_name.setStyleSheet("color: #1a1a1a;")
        info_layout.addWidget(app_name)
        
        version_label = QLabel("版本 1.2.4 | MIT 开源协议")
        version_label.setFont(QFont("Microsoft YaHei", 10))
        version_label.setStyleSheet("color: #666666;")
        info_layout.addWidget(version_label)
        
        top_layout.addLayout(info_layout)
        top_layout.addStretch()
        
        # GitHub 按钮
        github_btn = QPushButton("  GitHub")
        github_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        github_btn.setFixedHeight(36)
        github_btn.setStyleSheet("""
            QPushButton {
                background-color: #0067c0;
                border: none;
                border-radius: 6px;
                color: white;
                font-size: 13px;
                padding: 0 16px;
            }
            QPushButton:hover {
                background-color: #005a9e;
            }
            QPushButton:pressed {
                background-color: #004578;
            }
        """)
        github_btn.clicked.connect(lambda: self.open_github())
        top_layout.addWidget(github_btn)
        
        card1_layout.addWidget(top_row)
        
        # 分隔线
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("color: #e0e0e0;")
        card1_layout.addWidget(separator)
        
        # 项目简介
        desc_label = QLabel(
            "基于 Arduino/ESP32 的低成本理化实验数字化采集系统，"
            "为中学和大学物理/化学实验室提供低成本、高精度的传感器解决方案。"
        )
        desc_label.setWordWrap(True)
        desc_label.setFont(QFont("Microsoft YaHei", 11))
        desc_label.setStyleSheet("color: #444444; line-height: 1.5;")
        card1_layout.addWidget(desc_label)
        
        # 特性标签
        tags_layout = QHBoxLayout()
        tags_layout.setSpacing(8)
        
        tags = [
            ("MIT 开源", "#e8f5e9", "#2e7d32"),
            ("教学实验", "#f3e5f5", "#7b1fa2"),
        ]
        
        for text, bg, fg in tags:
            tag = QLabel(text)
            tag.setFont(QFont("Microsoft YaHei", 9))
            tag.setStyleSheet(f"""
                background-color: {bg};
                color: {fg};
                border-radius: 4px;
                padding: 4px 10px;
            """)
            tags_layout.addWidget(tag)
        
        tags_layout.addStretch()
        card1_layout.addLayout(tags_layout)
        
        content_layout.addWidget(card1)
        
        # ========== 物理实验模块 + 化学实验模块 并排 ==========
        modules_row = QHBoxLayout()
        modules_row.setSpacing(16)

        # 物理实验模块（2×2 网格）
        card2 = self.create_grid_module_card(
            "物理实验模块",
            "4 个模块",
            [
                ("x", "超声波位移"),
                ("v", "超声波速度"),
                ("F", "力传感器"),
                ("V", "电压"),
            ]
        )
        modules_row.addWidget(card2, stretch=2)

        # 化学实验模块
        card3 = self.create_grid_module_card(
            "化学实验模块",
            "1 个模块",
            [
                ("pH", "pH传感器"),
            ]
        )
        modules_row.addWidget(card3, stretch=2)

        content_layout.addLayout(modules_row)
        content_layout.addStretch()
        
        scroll.setWidget(content)
        main_layout.addWidget(scroll)
        self.setLayout(main_layout)
    
    def create_module_card(self, title, subtitle, modules):
        """创建 Win11 风格模块卡片"""
        card = QWidget()
        card.setObjectName("card")
        card.setStyleSheet(self.CARD_STYLE)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 16, 20, 8)
        card_layout.setSpacing(0)
        
        # 卡片标题
        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        
        icon = QLabel("⚛️" if "物理" in title else "🧪")
        icon.setFont(QFont("Segoe MDL2 Assets", 18))
        icon.setFixedSize(32, 32)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("color: #0067c0;")
        title_row.addWidget(icon)
        
        title_text = QVBoxLayout()
        title_text.setSpacing(0)
        
        title_label = QLabel(title)
        title_label.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #1a1a1a;")
        title_text.addWidget(title_label)
        
        subtitle_label = QLabel(subtitle)
        subtitle_label.setFont(QFont("Microsoft YaHei", 10))
        subtitle_label.setStyleSheet("color: #888888;")
        title_text.addWidget(subtitle_label)
        
        title_row.addLayout(title_text)
        title_row.addStretch()
        
        card_layout.addLayout(title_row)
        card_layout.addSpacing(12)
        
        # 模块列表
        for i, (icon_text, name, desc) in enumerate(modules):
            item = self.create_module_item(icon_text, name, desc)
            card_layout.addWidget(item)
            
            # 分隔线（除了最后一个）
            if i < len(modules) - 1:
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.HLine)
                sep.setStyleSheet("color: #e8e8e8;")
                card_layout.addWidget(sep)
        
        card_layout.addSpacing(8)
        
        return card
    
    def create_module_item(self, icon_text, name, desc):
        """创建单个模块列表项"""
        btn = QPushButton()
        btn.setObjectName("module_item")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(56)
        btn.setStyleSheet(self.CARD_HOVER_STYLE)
        
        btn_layout = QHBoxLayout(btn)
        btn_layout.setContentsMargins(12, 8, 12, 8)
        btn_layout.setSpacing(14)
        
        # 图标
        icon_label = QLabel(icon_text)
        icon_label.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        icon_label.setFixedSize(36, 36)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("""
            background-color: #e8f0fe;
            border-radius: 8px;
            color: #0067c0;
        """)
        btn_layout.addWidget(icon_label)
        
        # 名称和描述
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        
        name_label = QLabel(name)
        name_label.setFont(QFont("Microsoft YaHei", 12))
        name_label.setStyleSheet("color: #1a1a1a;")
        text_layout.addWidget(name_label)
        
        desc_label = QLabel(desc)
        desc_label.setFont(QFont("Microsoft YaHei", 9))
        desc_label.setStyleSheet("color: #888888;")
        text_layout.addWidget(desc_label)
        
        btn_layout.addLayout(text_layout, stretch=1)
        
        # 箭头
        arrow = QLabel(">")
        arrow.setFont(QFont("Arial", 12))
        arrow.setStyleSheet("color: #999999;")
        btn_layout.addWidget(arrow)
        
        btn.clicked.connect(lambda: self.on_module_clicked(name))
        
        return btn
    
    def create_grid_module_card(self, title, subtitle, modules):
        """创建 Win11 设置风格的网格卡片"""
        card = QWidget()
        card.setObjectName("card")
        card.setStyleSheet(self.CARD_STYLE)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 16)
        card_layout.setSpacing(0)

        title_label = QLabel(title)
        title_label.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #1a1a1a;")
        card_layout.addWidget(title_label)

        subtitle_label = QLabel(subtitle)
        subtitle_label.setFont(QFont("Microsoft YaHei", 10))
        subtitle_label.setStyleSheet("color: #666666; margin-bottom: 12px;")
        card_layout.addWidget(subtitle_label)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 0)

        for i, (icon_text, name) in enumerate(modules):
            row, col = divmod(i, 2)
            item = self.create_grid_module_item(icon_text, name)
            grid.addWidget(item, row, col)

        card_layout.addLayout(grid)
        card_layout.addSpacing(4)
        return card
    
    def create_grid_module_item(self, icon_text, name):
        """创建网格内的单个模块项：图标 + 名称"""
        btn = QPushButton()
        btn.setObjectName("module_item")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(48)
        btn.setMaximumWidth(200)
        btn.setStyleSheet(self.CARD_HOVER_STYLE)

        btn_layout = QHBoxLayout(btn)
        btn_layout.setContentsMargins(12, 6, 12, 6)
        btn_layout.setSpacing(10)

        icon_label = QLabel(icon_text)
        icon_label.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        icon_label.setFixedSize(32, 32)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("""
            background-color: #e8f0fe;
            border-radius: 6px;
            color: #0067c0;
        """)
        btn_layout.addWidget(icon_label)

        name_label = QLabel(name)
        name_label.setFont(QFont("Microsoft YaHei", 12))
        name_label.setStyleSheet("color: #1a1a1a;")
        btn_layout.addWidget(name_label)

        arrow = QLabel(">")
        arrow.setFont(QFont("Arial", 12))
        arrow.setStyleSheet("color: #999999;")
        btn_layout.addWidget(arrow)

        btn.clicked.connect(lambda: self.on_module_clicked(name))
        return btn
    
    def open_github(self):
        import webbrowser
        webbrowser.open("https://github.com/wangzhidong2/PhysChem-DigitizerP")
    
    def on_module_clicked(self, module_name):
        self.module_clicked.emit(module_name)
    
    def apply_theme(self, theme):
        if theme == "dark":
            self.CARD_STYLE = """
                QWidget#card {
                    background-color: #2d2d2d;
                    border: 1px solid #404040;
                    border-radius: 8px;
                }
                QWidget#card QLabel,
                QWidget#card QFrame {
                    background-color: transparent;
                }
            """
            self.CARD_HOVER_STYLE = """
                QPushButton#module_item {
                    background-color: transparent;
                    border: none;
                    border-radius: 6px;
                    text-align: left;
                    padding: 12px 16px;
                }
                QPushButton#module_item:hover {
                    background-color: #404040;
                }
                QPushButton#module_item:pressed {
                    background-color: #505050;
                }
            """
        else:
            self.CARD_STYLE = """
                QWidget#card {
                    background-color: #ffffff;
                    border: 1px solid #e5e5e5;
                    border-radius: 8px;
                }
                QWidget#card QLabel,
                QWidget#card QFrame {
                    background-color: transparent;
                }
            """
            self.CARD_HOVER_STYLE = """
                QPushButton#module_item {
                    background-color: transparent;
                    border: none;
                    border-radius: 6px;
                    text-align: left;
                    padding: 12px 16px;
                }
                QPushButton#module_item:hover {
                    background-color: #f0f0f0;
                }
                QPushButton#module_item:pressed {
                    background-color: #e5e5e5;
                }
            """


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
        self.port_combo = QComboBox()
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


class VoltageSensorWidget(QWidget):
    """电压传感器模块界面 - 支持ADC位数选择和电压分压放大比"""

    ADC_BITS_OPTIONS = {8: 256, 10: 1024, 12: 4095, 14: 16383, 16: 65535, 18: 262143, 20: 1048575, 22: 4194303, 24: 16777215}
    VREF = 3.3

    def __init__(self):
        super().__init__()
        self.serial_thread = None
        self.ble_thread = None
        self.voltage_data = []
        self.time_data = []
        self.raw_data = []
        self.start_timestamp_ms = 0

        # 采样频率设置（毫秒）
        self.sample_interval_ms = 100  # 默认 100ms (10Hz)
        self.last_sample_time_ms = 0   # 上次采样时间

        self.adc_bits = 12
        self.divider_ratio = 1.0
        self.amp_ratio = 1.0
        # HX711 专用参数：有符号 24 位 + AVDD/Gain 参考电压
        self.hx711_mode = False
        self.hx711_avdd = 5.0       # HX711 模块 AVDD 电压（V），常见为 5.0
        self.hx711_channel = 'B'    # 通道：A=增益128，B=增益32
        # 显示单位：内部 voltage_data 始终存伏特，仅在显示/保存时按当前单位换算
        self.current_unit = 'V'     # 可选：kV / V / mV

        self.config = self.load_config()
        self.adc_bits = self.config.get('adc_bits', 12)
        self.divider_ratio = self.config.get('divider_ratio', 1.0)
        self.amp_ratio = self.config.get('amp_ratio', 1.0)
        self.hx711_mode = self.config.get('hx711_mode', False)
        self.hx711_avdd = self.config.get('hx711_avdd', 5.0)
        self.hx711_channel = self.config.get('hx711_channel', 'B')
        self.current_unit = self.config.get('current_unit', 'V')

        self.init_ui()

    def load_config(self):
        config = load_sensor_config('voltage_sensor')
        if config:
            self.adc_bits = config.get('adc_bits', 12)
            self.divider_ratio = config.get('divider_ratio', 1.0)
            self.amp_ratio = config.get('amp_ratio', 1.0)
            self.sample_interval_ms = config.get('sample_interval_ms', 100)
            self.hx711_mode = config.get('hx711_mode', False)
            self.hx711_avdd = config.get('hx711_avdd', 5.0)
            self.hx711_channel = config.get('hx711_channel', 'B')
            self.current_unit = config.get('current_unit', 'V')
        return config

    def save_config(self):
        config = {
            'adc_bits': self.adc_bits,
            'divider_ratio': self.divider_ratio,
            'amp_ratio': self.amp_ratio,
            'sample_interval_ms': self.sample_interval_ms,
            'hx711_mode': self.hx711_mode,
            'hx711_avdd': self.hx711_avdd,
            'hx711_channel': self.hx711_channel,
            'current_unit': self.current_unit
        }
        return save_sensor_config('voltage_sensor', config)

    # 单位换算：内部 voltage_data 始终存伏特，按当前单位返回显示值
    UNIT_FACTORS = {'kV': 0.001, 'V': 1.0, 'mV': 1000.0}

    def to_current_unit(self, voltage_v):
        """伏特 → 当前单位"""
        return voltage_v * self.UNIT_FACTORS.get(self.current_unit, 1.0)

    def format_voltage(self, voltage_v):
        """格式化显示：根据数量级自动选小数位"""
        v = self.to_current_unit(voltage_v)
        if self.current_unit == 'kV':
            return f"{v:.6f}"
        elif self.current_unit == 'mV':
            return f"{v:.3f}"
        return f"{v:.4f}"

    def adc_to_voltage(self, adc_value):
        # 实际被测电压 = ADC端电压 × 分压比 / 放大倍数
        v_adc = self.adc_to_vadc(adc_value)
        actual_voltage = v_adc * self.divider_ratio / self.amp_ratio
        return actual_voltage

    def adc_to_vadc(self, adc_value):
        """计算 ADC 输入端电压（未做分压/放大还原）"""
        # HX711 模式：24位有符号，参考电压 = AVDD / Gain
        # 通道A 增益128，通道B 增益32（固定）
        if self.hx711_mode:
            gain = 128 if self.hx711_channel == 'A' else 32
            return adc_value / 8388608.0 * (self.hx711_avdd / gain)
        max_adc = self.ADC_BITS_OPTIONS.get(self.adc_bits, 4096) - 1
        return (adc_value / max_adc) * self.VREF

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: #f3f3f3; }")

        content = QWidget()
        content.setStyleSheet("background: #f3f3f3;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)

        title = QLabel("电压")
        title.setFont(QFont("Microsoft YaHei", 28, QFont.Weight.Bold))
        title.setStyleSheet("color: #1a1a1a; margin-bottom: 4px;")
        layout.addWidget(title)

        # ========== 卡片1：连接控制 ==========
        card_conn = QWidget()
        card_conn.setObjectName("card")
        card_conn.setStyleSheet(self._card_style())
        card_layout = QVBoxLayout(card_conn)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.setSpacing(12)

        card_title = QLabel("连接控制")
        card_title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        card_title.setStyleSheet("color: #1a1a1a;")
        card_layout.addWidget(card_title)

        # 第一行：连接方式 + 设备选择 + 按钮
        row1 = QHBoxLayout()
        row1.setSpacing(10)

        row1.addWidget(QLabel("连接方式:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["有线串口", "BLE蓝牙"])
        if not BLE_AVAILABLE:
            self.mode_combo.setItemData(1, 0, Qt.ItemDataRole.UserRole - 1)
            self.mode_combo.setItemText(1, "BLE蓝牙（未安装bleak）")
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        row1.addWidget(self.mode_combo)

        self.serial_panel = QWidget()
        serial_layout = QHBoxLayout(self.serial_panel)
        serial_layout.setContentsMargins(0, 0, 0, 0)
        serial_layout.setSpacing(8)
        serial_layout.addWidget(QLabel("串口:"))
        self.port_combo = QComboBox()
        self.refresh_ports()
        self.port_combo.setMinimumWidth(140)
        serial_layout.addWidget(self.port_combo)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setFixedHeight(36)
        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.refresh_btn.setStyleSheet(self._accent_btn_style("#f0f0f0", "#e0e0e0", "#d0d0d0"))
        serial_layout.addWidget(self.refresh_btn)

        self.ble_panel = QWidget()
        ble_layout = QHBoxLayout(self.ble_panel)
        ble_layout.setContentsMargins(0, 0, 0, 0)
        ble_layout.setSpacing(8)
        self.ble_device_combo = QComboBox()
        self.ble_device_combo.setMinimumWidth(180)
        ble_layout.addWidget(self.ble_device_combo)
        self.ble_scan_btn = QPushButton("扫描BLE")
        self.ble_scan_btn.setFixedHeight(36)
        self.ble_scan_btn.clicked.connect(self.scan_ble)
        if not BLE_AVAILABLE:
            self.ble_scan_btn.setEnabled(False)
        ble_layout.addWidget(self.ble_scan_btn)

        row1.addWidget(self.serial_panel)
        row1.addWidget(self.ble_panel)
        self.ble_panel.hide()

        row1.addSpacing(16)
        self.connect_btn = QPushButton("连接")
        self.connect_btn.setFixedHeight(36)
        self.connect_btn.clicked.connect(self.connect_device)
        self.connect_btn.setStyleSheet(self._primary_btn_style())
        row1.addWidget(self.connect_btn)

        self.disconnect_btn = QPushButton("断开")
        self.disconnect_btn.setFixedHeight(36)
        self.disconnect_btn.clicked.connect(self.disconnect_all)
        self.disconnect_btn.setEnabled(False)
        self.disconnect_btn.setStyleSheet(self._accent_btn_style("#f0f0f0", "#e0e0e0", "#d0d0d0"))
        row1.addWidget(self.disconnect_btn)

        row1.addStretch()
        card_layout.addLayout(row1)

        # 第二行：采样频率
        row2 = QHBoxLayout()
        row2.setSpacing(10)
        row2.addWidget(QLabel("采样频率:"))
        self.sample_rate_label = QLabel(f"{1000 // self.sample_interval_ms}Hz")
        self.sample_rate_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        self.sample_rate_label.setStyleSheet("color: #0078d4;")
        row2.addWidget(self.sample_rate_label)

        sample_settings_btn = QPushButton("⚙")
        sample_settings_btn.setFixedSize(36, 36)
        sample_settings_btn.setToolTip("设置采样频率")
        sample_settings_btn.clicked.connect(self.edit_sample_rate)
        sample_settings_btn.setStyleSheet(self._accent_btn_style("#f0f0f0", "#e0e0e0", "#d0d0d0"))
        row2.addWidget(sample_settings_btn)
        row2.addStretch()
        card_layout.addLayout(row2)

        layout.addWidget(card_conn)

        # ========== 卡片2：ADC 与电路参数 ==========
        card_adc = QWidget()
        card_adc.setObjectName("card")
        card_adc.setStyleSheet(self._card_style())
        adc_card_layout = QVBoxLayout(card_adc)
        adc_card_layout.setContentsMargins(20, 16, 20, 16)
        adc_card_layout.setSpacing(12)

        adc_card_title = QLabel("ADC 与电路参数")
        adc_card_title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        adc_card_title.setStyleSheet("color: #1a1a1a;")
        adc_card_layout.addWidget(adc_card_title)

        bits_row = QHBoxLayout()
        bits_row.setSpacing(10)
        bits_row.addWidget(QLabel("ADC 位数:"))
        self.adc_bits_combo = QComboBox()
        self.adc_bits_combo.addItems([
            "8 位 (0-255)",
            "10 位 (0-1023)",
            "12 位 (0-4095)  ESP32内置",
            "14 位 (0-16383)",
            "16 位 (0-65535)  ADS1115等",
            "18 位 (0-262143)",
            "20 位 (0-1048575)",
            "22 位 (0-4194303)",
            "24 位 (0-16777215)  HX711等"
        ])
        bits_map = {0: 8, 1: 10, 2: 12, 3: 14, 4: 16, 5: 18, 6: 20, 7: 22, 8: 24}
        self.adc_bits_combo.setCurrentIndex(bits_map.get(self.adc_bits, 2))
        self.adc_bits_combo.currentIndexChanged.connect(self.on_adc_bits_changed)
        bits_row.addWidget(self.adc_bits_combo)

        bits_row.addWidget(QLabel("参考电压: 3.3V"))
        self.range_label = QLabel(f"量程: 0 ~ {self.VREF:.1f}V")
        self.range_label.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        self.range_label.setStyleSheet("color: #0078d4;")
        bits_row.addWidget(self.range_label)
        bits_row.addStretch()
        adc_card_layout.addLayout(bits_row)

        # HX711 模式行：复选框 + AVDD + 通道选择
        hx711_row = QHBoxLayout()
        hx711_row.setSpacing(10)
        self.hx711_check = QCheckBox("HX711 模式（24位有符号）")
        self.hx711_check.setChecked(self.hx711_mode)
        self.hx711_check.setToolTip("启用后按 HX711 有符号 24 位 + AVDD/Gain 换算电压\n通道A=增益128，通道B=增益32")
        self.hx711_check.toggled.connect(self.on_hx711_mode_changed)
        hx711_row.addWidget(self.hx711_check)

        hx711_row.addWidget(QLabel("AVDD:"))
        self.hx711_avdd_spin = QDoubleSpinBox()
        self.hx711_avdd_spin.setRange(2.7, 5.5)
        self.hx711_avdd_spin.setDecimals(2)
        self.hx711_avdd_spin.setSingleStep(0.1)
        self.hx711_avdd_spin.setValue(self.hx711_avdd)
        self.hx711_avdd_spin.setSuffix(" V")
        self.hx711_avdd_spin.setMinimumWidth(90)
        self.hx711_avdd_spin.valueChanged.connect(self.on_hx711_avdd_changed)
        self.hx711_avdd_spin.setEnabled(self.hx711_mode)
        hx711_row.addWidget(self.hx711_avdd_spin)

        hx711_row.addWidget(QLabel("通道:"))
        self.hx711_channel_combo = QComboBox()
        self.hx711_channel_combo.addItems(["B (增益 32, ±156mV)", "A (增益 128, ±39mV)"])
        self.hx711_channel_combo.setCurrentIndex(0 if self.hx711_channel == 'B' else 1)
        self.hx711_channel_combo.currentIndexChanged.connect(self.on_hx711_channel_changed)
        self.hx711_channel_combo.setEnabled(self.hx711_mode)
        hx711_row.addWidget(self.hx711_channel_combo)

        hx711_row.addStretch()
        adc_card_layout.addLayout(hx711_row)

        params_row = QHBoxLayout()
        params_row.setSpacing(10)
        params_row.addWidget(QLabel("分压比 (R1+R2)/R2:"))
        self.divider_spin = QDoubleSpinBox()
        self.divider_spin.setRange(1.0, 1000.0)
        self.divider_spin.setDecimals(2)
        self.divider_spin.setSingleStep(0.1)
        self.divider_spin.setValue(self.divider_ratio)
        self.divider_spin.setSuffix(" x")
        self.divider_spin.setMinimumWidth(120)
        self.divider_spin.valueChanged.connect(self.on_divider_changed)
        params_row.addWidget(self.divider_spin)

        params_row.addWidget(QLabel("放大倍数:"))
        self.amp_spin = QDoubleSpinBox()
        self.amp_spin.setRange(0.01, 1000.0)
        self.amp_spin.setDecimals(2)
        self.amp_spin.setSingleStep(0.1)
        self.amp_spin.setValue(self.amp_ratio)
        self.amp_spin.setSuffix(" x")
        self.amp_spin.setMinimumWidth(120)
        self.amp_spin.valueChanged.connect(self.on_amp_changed)
        params_row.addWidget(self.amp_spin)

        self.actual_range_label = QLabel(f"实际量程: 0 ~ {self.VREF * self.divider_ratio / self.amp_ratio:.2f}V")
        self.actual_range_label.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        self.actual_range_label.setStyleSheet("color: #28a745;")
        params_row.addWidget(self.actual_range_label)
        params_row.addStretch()
        adc_card_layout.addLayout(params_row)

        hint_label = QLabel("分压比 = (R1+R2)/R2，用于还原分压前的原始电压；放大倍数 = 运放增益，用于还原放大前的信号电压")
        hint_label.setStyleSheet("color: #888888; font-size: 11px;")
        hint_label.setWordWrap(True)
        adc_card_layout.addWidget(hint_label)

        # 显示单位选择
        unit_row = QHBoxLayout()
        unit_row.setSpacing(10)
        unit_row.addWidget(QLabel("显示单位:"))
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["千伏 (kV)", "伏 (V)", "毫伏 (mV)"])
        unit_map = {'kV': 0, 'V': 1, 'mV': 2}
        self.unit_combo.setCurrentIndex(unit_map.get(self.current_unit, 1))
        self.unit_combo.currentIndexChanged.connect(self.on_unit_changed)
        unit_row.addWidget(self.unit_combo)
        unit_row.addStretch()
        adc_card_layout.addLayout(unit_row)

        layout.addWidget(card_adc)

        # ========== 卡片3：实时数据 ==========
        card_data = QWidget()
        card_data.setObjectName("card")
        card_data.setStyleSheet(self._card_style())
        data_card_layout = QVBoxLayout(card_data)
        data_card_layout.setContentsMargins(20, 16, 20, 16)
        data_card_layout.setSpacing(12)

        data_card_title = QLabel("实时数据")
        data_card_title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        data_card_title.setStyleSheet("color: #1a1a1a;")
        data_card_layout.addWidget(data_card_title)

        self.current_voltage_label = QLabel("--.- V")
        self.current_voltage_label.setFont(QFont("Microsoft YaHei", 32, QFont.Weight.Bold))
        self.current_voltage_label.setStyleSheet("color: #0078d4;")
        data_card_layout.addWidget(self.current_voltage_label)

        raw_row = QHBoxLayout()
        raw_row.setSpacing(20)
        self.current_raw_label = QLabel("原始ADC: ------")
        self.current_raw_label.setFont(QFont("Microsoft YaHei", 11))
        self.current_raw_label.setStyleSheet("color: #444444;")
        raw_row.addWidget(self.current_raw_label)

        self.current_vadc_label = QLabel("ADC端电压: --.- V")
        self.current_vadc_label.setFont(QFont("Microsoft YaHei", 11))
        self.current_vadc_label.setStyleSheet("color: #444444;")
        raw_row.addWidget(self.current_vadc_label)
        raw_row.addStretch()
        data_card_layout.addLayout(raw_row)

        self.stats_label = QLabel("暂无数据")
        self.stats_label.setFont(QFont("Microsoft YaHei", 10))
        self.stats_label.setStyleSheet("color: #888888;")
        data_card_layout.addWidget(self.stats_label)

        layout.addWidget(card_data)

        # ========== 卡片4：图表 + 数据记录 ==========
        card_chart = QWidget()
        card_chart.setObjectName("card")
        card_chart.setStyleSheet(self._card_style())
        chart_card_layout = QVBoxLayout(card_chart)
        chart_card_layout.setContentsMargins(20, 16, 20, 16)
        chart_card_layout.setSpacing(12)

        chart_title = QLabel("电压-时间曲线")
        chart_title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        chart_title.setStyleSheet("color: #1a1a1a;")
        chart_card_layout.addWidget(chart_title)

        content_row = QHBoxLayout()
        content_row.setSpacing(16)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        record_label = QLabel("数据记录")
        record_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        record_label.setStyleSheet("color: #1a1a1a;")
        left_layout.addWidget(record_label)

        self.data_text = QTextEdit()
        self.data_text.setReadOnly(True)
        self.data_text.setStyleSheet("""
            QTextEdit {
                background-color: #fafafa;
                border: 1px solid #e5e5e5;
                border-radius: 6px;
                padding: 8px;
                font-size: 11px;
                color: #333333;
            }
        """)
        left_layout.addWidget(self.data_text)
        content_row.addWidget(left_panel, stretch=1)

        self.figure = Figure(figsize=(8, 5), dpi=100)
        self.figure.set_facecolor('#fafafa')
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setStyleSheet("border: 1px solid #e5e5e5; border-radius: 6px;")
        content_row.addWidget(self.canvas, stretch=2)

        chart_card_layout.addLayout(content_row)
        layout.addWidget(card_chart)

        # ========== 卡片5：操作按钮 ==========
        card_actions = QWidget()
        card_actions.setObjectName("card")
        card_actions.setStyleSheet(self._card_style())
        actions_layout = QHBoxLayout(card_actions)
        actions_layout.setContentsMargins(20, 12, 20, 12)
        actions_layout.setSpacing(10)

        self.start_btn = QPushButton("开始采集")
        self.start_btn.setFixedHeight(38)
        self.start_btn.clicked.connect(self.start_collection)
        self.start_btn.setEnabled(False)
        self.start_btn.setStyleSheet(self._primary_btn_style())
        actions_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("停止采集")
        self.stop_btn.setFixedHeight(38)
        self.stop_btn.clicked.connect(self.stop_collection)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(self._accent_btn_style("#f0f0f0", "#e0e0e0", "#d0d0d0"))
        actions_layout.addWidget(self.stop_btn)

        self.save_btn = QPushButton("保存数据")
        self.save_btn.setFixedHeight(38)
        self.save_btn.clicked.connect(self.save_data)
        self.save_btn.setEnabled(False)
        self.save_btn.setStyleSheet(self._accent_btn_style("#f0f0f0", "#e0e0e0", "#d0d0d0"))
        actions_layout.addWidget(self.save_btn)

        self.clear_btn = QPushButton("清除数据")
        self.clear_btn.setFixedHeight(38)
        self.clear_btn.clicked.connect(self.clear_data)
        self.clear_btn.setStyleSheet(self._accent_btn_style("#f0f0f0", "#e0e0e0", "#d0d0d0"))
        actions_layout.addWidget(self.clear_btn)

        actions_layout.addStretch()
        layout.addWidget(card_actions)

        layout.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll)
        self.setLayout(main_layout)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_chart)
        self.timer.start(100)

    def _card_style(self):
        return """
            QWidget#card {
                background-color: #ffffff;
                border: 1px solid #e5e5e5;
                border-radius: 8px;
            }
            QWidget#card QLabel,
            QWidget#card QFrame {
                background-color: transparent;
            }
        """

    def _primary_btn_style(self):
        return """
            QPushButton {
                background-color: #0078d4;
                border: none;
                color: white;
                border-radius: 6px;
                font-size: 13px;
                padding: 0 16px;
            }
            QPushButton:hover { background-color: #106ebe; }
            QPushButton:pressed { background-color: #005a9e; }
            QPushButton:disabled { background-color: #cccccc; color: #888888; }
        """

    def _accent_btn_style(self, normal, hover, pressed):
        return f"""
            QPushButton {{
                background-color: {normal};
                border: 1px solid #d0d0d0;
                color: #1a1a1a;
                border-radius: 6px;
                font-size: 13px;
                padding: 0 16px;
            }}
            QPushButton:hover {{ background-color: {hover}; }}
            QPushButton:pressed {{ background-color: {pressed}; }}
            QPushButton:disabled {{ background-color: #f5f5f5; color: #aaaaaa; }}
        """

    def on_mode_changed(self, index):
        if index == 0:
            self.serial_panel.show()
            self.ble_panel.hide()
        else:
            self.serial_panel.hide()
            self.ble_panel.show()

    def on_adc_bits_changed(self, index):
        bits_map = {0: 8, 1: 10, 2: 12, 3: 14, 4: 16, 5: 18, 6: 20, 7: 22, 8: 24}
        self.adc_bits = bits_map.get(index, 12)
        self.save_config()
        self.update_range_display()

    def on_divider_changed(self, value):
        self.divider_ratio = value
        self.save_config()
        self.update_range_display()

    def on_amp_changed(self, value):
        self.amp_ratio = value
        self.save_config()
        self.update_range_display()

    def on_hx711_mode_changed(self, checked):
        """HX711 模式开关：启用后强制 ADC 位数=24，并切换至有符号换算"""
        self.hx711_mode = checked
        self.hx711_avdd_spin.setEnabled(checked)
        self.hx711_channel_combo.setEnabled(checked)
        if checked:
            # 强制切到 24 位选项
            self.adc_bits_combo.setCurrentIndex(8)
            self.adc_bits = 24
        self.save_config()
        self.update_range_display()

    def on_hx711_avdd_changed(self, value):
        self.hx711_avdd = value
        self.save_config()
        self.update_range_display()

    def on_hx711_channel_changed(self, index):
        self.hx711_channel = 'B' if index == 0 else 'A'
        self.save_config()
        self.update_range_display()

    def on_unit_changed(self, index):
        """切换显示单位：kV / V / mV。内部数据不变，仅刷新显示"""
        unit_map = {0: 'kV', 1: 'V', 2: 'mV'}
        self.current_unit = unit_map.get(index, 'V')
        self.save_config()
        # 刷新实时数据/统计/图表的显示
        self.update_stats()
        self.update_chart()
        # 刷新当前电压大字显示（如果有最后一个数据点）
        if self.voltage_data:
            self.current_voltage_label.setText(f"{self.format_voltage(self.voltage_data[-1])} {self.current_unit}")

    def update_range_display(self):
        if self.hx711_mode:
            gain = 128 if self.hx711_channel == 'A' else 32
            fs = self.hx711_avdd / gain  # 满量程差分电压（单边）
            self.range_label.setText(f"量程: ±{fs*1000:.1f}mV (HX711 通道{self.hx711_channel}, Gain{gain})")
            actual_max = fs * self.divider_ratio / self.amp_ratio
            self.actual_range_label.setText(f"实际量程: ±{actual_max*1000:.2f}mV")
        else:
            max_adc = self.ADC_BITS_OPTIONS.get(self.adc_bits, 4096) - 1
            self.range_label.setText(f"量程: 0 ~ {self.VREF:.1f}V (ADC {max_adc})")
            actual_max = self.VREF * self.divider_ratio / self.amp_ratio
            self.actual_range_label.setText(f"实际量程: 0 ~ {actual_max:.2f}V")

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
        else:
            self.connect_serial()

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
            self.current_voltage_label.setText("--.- V")
            self.current_raw_label.setText("原始ADC: 连接中...")
            self.current_vadc_label.setText("ADC端电压: --.- V")
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
            self.current_voltage_label.setText("BLE连接中...")
            self.current_raw_label.setText("ADC: BLE连接中...")
        except Exception as e:
            QMessageBox.critical(self, "连接错误", f"BLE 连接失败: {e}")

    def on_ble_status(self, status):
        if status == "connected":
            self.current_voltage_label.setText("电压: BLE已连接，等待数据...")
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
        self.current_voltage_label.setText(f"--.- {self.current_unit}")
        self.current_raw_label.setText("原始ADC: 已断开")
        self.current_vadc_label.setText("ADC端电压: --.- V")

    def start_collection(self):
        self.voltage_data.clear()
        self.time_data.clear()
        self.raw_data.clear()
        self.data_text.clear()
        self.last_sample_time_ms = 0  # 重置采样时间
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.save_btn.setEnabled(False)
        self.current_voltage_label.setText("电压: 采集中...")
        self.current_raw_label.setText("原始ADC: 采集中...")

    def stop_collection(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.save_btn.setEnabled(len(self.voltage_data) > 0)
        if len(self.voltage_data) > 0:
            avg_v = np.mean(self.voltage_data)
            self.current_voltage_label.setText(f"{self.format_voltage(avg_v)} {self.current_unit}")

    def handle_data(self, data):
        if data.startswith("ERROR:"):
            QMessageBox.critical(self, "连接错误", data[6:])
            self.disconnect_all()
            return

        if data == "START":
            self.current_voltage_label.setText("电压: 设备就绪")
            self.current_raw_label.setText("原始ADC: 等待数据...")
            return

        if not self.stop_btn.isEnabled():
            try:
                if "," in data:
                    parts = data.split(",")
                    if len(parts) == 2:
                        raw_value = int(parts[1])
                        voltage = self.adc_to_voltage(raw_value)
                        v_adc = self.adc_to_vadc(raw_value)
                        self.current_raw_label.setText(f"原始ADC: {raw_value}")
                        self.current_voltage_label.setText(f"{self.format_voltage(voltage)} {self.current_unit}")
                        self.current_vadc_label.setText(f"ADC端电压: {self.format_voltage(v_adc)} {self.current_unit}")
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

                    voltage = self.adc_to_voltage(raw_value)
                    v_adc = self.adc_to_vadc(raw_value)

                    self.voltage_data.append(voltage)
                    self.time_data.append(relative_time_s)

                    current_time = datetime.now()
                    time_str = current_time.strftime("%H:%M:%S.%f")[:-3]

                    display_text = (f"时间: {time_str} | ADC: {raw_value} | "
                                    f"ADC端: {self.format_voltage(v_adc)} {self.current_unit} | "
                                    f"实际电压: {self.format_voltage(voltage)} {self.current_unit}")
                    self.current_raw_label.setText(f"原始ADC: {raw_value}")
                    self.current_voltage_label.setText(f"{self.format_voltage(voltage)} {self.current_unit}")
                    self.current_vadc_label.setText(f"ADC端电压: {self.format_voltage(v_adc)} {self.current_unit}")

                    self.data_text.append(display_text)
                    self.data_text.verticalScrollBar().setValue(
                        self.data_text.verticalScrollBar().maximum()
                    )

                    self.update_stats()

        except ValueError:
            pass

    def update_stats(self):
        if len(self.voltage_data) > 0:
            avg_v = np.mean(self.voltage_data)
            max_v = np.max(self.voltage_data)
            min_v = np.min(self.voltage_data)
            std_v = np.std(self.voltage_data)
            u = self.current_unit

            stats_text = (f"统计: 数据点 {len(self.voltage_data)} | "
                         f"平均={self.format_voltage(avg_v)}{u} | "
                         f"最大={self.format_voltage(max_v)}{u} | "
                         f"最小={self.format_voltage(min_v)}{u} | "
                         f"标准差 σ={self.format_voltage(std_v)}{u}")
            self.stats_label.setText(stats_text)

    def update_chart(self):
        if len(self.voltage_data) > 0:
            self.figure.clear()
            ax = self.figure.add_subplot(111)

            # 图表数据按当前单位换算
            display_data = [self.to_current_unit(v) for v in self.voltage_data]
            ax.plot(self.time_data, display_data, '#0078d4', linewidth=2, label=f'电压 ({self.current_unit})')
            ax.set_xlabel('时间 (秒)')
            ax.set_ylabel(f'电压 ({self.current_unit})')
            ax.set_title('电压传感器实时数据', fontsize=14, fontweight='bold')
            ax.grid(True, alpha=0.3)
            ax.legend(loc='upper right')

            if len(self.time_data) > 1:
                ax.set_xlim(min(self.time_data), max(self.time_data))

            self.figure.tight_layout()
            self.canvas.draw()

    def edit_sample_rate(self):
        """编辑采样频率对话框"""
        dialog = SampleRateDialog(self.sample_interval_ms, self)
        if dialog.exec() == 1:  # QDialog.Accepted
            new_interval_ms = dialog.get_sample_interval()
            self.sample_interval_ms = new_interval_ms
            freq = 1000 // new_interval_ms
            self.sample_rate_label.setText(f"{freq}Hz")
            self.save_config()
            QMessageBox.information(self, "成功",
                                   f"采样频率已更新为 {freq} Hz！\n"
                                   f"采样间隔：{new_interval_ms} ms\n"
                                   f"配置已自动保存。")

    def save_data(self):
        if len(self.voltage_data) == 0:
            QMessageBox.warning(self, "警告", "没有数据可保存")
            return
        try:
            filename = f"voltage_sensor_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', encoding='utf-8') as f:
                # CSV 表头按当前单位命名，方便后续分析
                f.write(f"timestamp_s,raw_adc,voltage_{self.current_unit.lower()}\n")
                for i, (timestamp, voltage) in enumerate(zip(self.time_data, self.voltage_data)):
                    raw = self.raw_data[i] if i < len(self.raw_data) else 0
                    f.write(f"{timestamp:.3f},{raw},{self.to_current_unit(voltage):.6f}\n")
            QMessageBox.information(self, "成功", f"数据已保存到: {filename}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")

    def clear_data(self):
        self.voltage_data.clear()
        self.time_data.clear()
        self.raw_data.clear()
        self.data_text.clear()
        self.current_voltage_label.setText(f"--.- {self.current_unit}")
        self.current_raw_label.setText("原始ADC: ------")
        self.current_vadc_label.setText(f"ADC端电压: --.- {self.current_unit}")
        self.stats_label.setText("统计信息: 暂无数据")
        self.figure.clear()
        self.canvas.draw()
        self.save_btn.setEnabled(False)


class ForceSensorWidget(QWidget):
    """力传感器（HX711）模块界面 - 支持去皮、校准和单位切换"""
    
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
        layout = QVBoxLayout()
        
        # 连接方式选择
        conn_group = QGroupBox("连接方式")
        conn_layout = QHBoxLayout()
        
        conn_layout.addWidget(QLabel("连接方式:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["有线串口", "BLE蓝牙"])
        if not BLE_AVAILABLE:
            self.mode_combo.setItemData(1, 0, Qt.ItemDataRole.UserRole - 1)
            self.mode_combo.setItemText(1, "BLE蓝牙（未安装bleak）")
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        conn_layout.addWidget(self.mode_combo)
        
        # 串口面板
        self.serial_panel = QWidget()
        serial_layout = QHBoxLayout(self.serial_panel)
        serial_layout.setContentsMargins(0, 0, 0, 0)
        
        serial_layout.addWidget(QLabel("串口:"))
        self.port_combo = QComboBox()
        self.refresh_ports()
        serial_layout.addWidget(self.port_combo)
        
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        serial_layout.addWidget(self.refresh_btn)
        
        # BLE 面板
        self.ble_panel = QWidget()
        ble_layout = QHBoxLayout(self.ble_panel)
        ble_layout.setContentsMargins(0, 0, 0, 0)
        
        self.ble_device_combo = QComboBox()
        ble_layout.addWidget(self.ble_device_combo)
        
        self.ble_scan_btn = QPushButton("扫描BLE")
        self.ble_scan_btn.clicked.connect(self.scan_ble)
        if not BLE_AVAILABLE:
            self.ble_scan_btn.setEnabled(False)
        ble_layout.addWidget(self.ble_scan_btn)
        
        conn_layout.addWidget(self.serial_panel)
        conn_layout.addWidget(self.ble_panel)
        self.ble_panel.hide()
        
        conn_layout.addStretch()
        
        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(self.connect_device)
        conn_layout.addWidget(self.connect_btn)
        
        self.disconnect_btn = QPushButton("断开")
        self.disconnect_btn.clicked.connect(self.disconnect_all)
        self.disconnect_btn.setEnabled(False)
        conn_layout.addWidget(self.disconnect_btn)

        conn_layout.addStretch()

        # 采样频率显示
        conn_layout.addWidget(QLabel("采样:"))
        self.sample_rate_label = QLabel(f"{1000//self.sample_interval_ms}Hz")
        self.sample_rate_label.setStyleSheet("color: #0078d4; font-weight: bold;")
        conn_layout.addWidget(self.sample_rate_label)

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
        conn_layout.addWidget(sample_settings_btn)

        conn_group.setLayout(conn_layout)
        layout.addWidget(conn_group)
        
        # 校准面板
        cal_group = QGroupBox("校准与去皮")
        cal_layout = QVBoxLayout()
        
        cal_info_layout = QHBoxLayout()
        self.cal_status_label = QLabel("校准状态: 未校准" if not self.calibrated else f"校准状态: ✓ 已校准 (比例={self.scale:.6f}, 偏移={self.offset})")
        self.cal_status_label.setStyleSheet("color: green; font-weight: bold;" if self.calibrated else "color: red; font-weight: bold;")
        cal_info_layout.addWidget(self.cal_status_label)
        cal_layout.addLayout(cal_info_layout)
        
        cal_btn_layout = QHBoxLayout()
        
        self.tare_btn = QPushButton("去皮（TARE）")
        self.tare_btn.clicked.connect(self.send_tare)
        self.tare_btn.setEnabled(False)
        self.tare_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078d4; color: white;
                border: none; padding: 8px 16px; border-radius: 4px;
            }
            QPushButton:hover { background-color: #106ebe; }
            QPushButton:pressed { background-color: #005a9e; }
        """)
        cal_btn_layout.addWidget(self.tare_btn)
        
        self.calibrate_btn = QPushButton("校准（CALIBRATE）")
        self.calibrate_btn.clicked.connect(self.start_calibration)
        self.calibrate_btn.setEnabled(False)
        self.calibrate_btn.setStyleSheet("""
            QPushButton {
                background-color: #fd7e14; color: white;
                border: none; padding: 8px 16px; border-radius: 4px;
            }
            QPushButton:hover { background-color: #e06b00; }
            QPushButton:pressed { background-color: #c55a00; }
        """)
        cal_btn_layout.addWidget(self.calibrate_btn)
        
        cal_btn_layout.addStretch()
        cal_layout.addLayout(cal_btn_layout)
        
        unit_layout = QHBoxLayout()
        unit_layout.addWidget(QLabel("显示单位:"))
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["克 (g)", "千克 (kg)", "牛顿 (N)"])
        unit_map = {"g": 0, "kg": 1, "N": 2}
        self.unit_combo.setCurrentIndex(unit_map.get(self.current_unit, 0))
        self.unit_combo.currentIndexChanged.connect(self.on_unit_changed)
        self.unit_combo.setStyleSheet("""
            QComboBox {
                padding: 6px 12px; border: 1px solid #ccc; border-radius: 4px;
                min-width: 120px;
            }
        """)
        unit_layout.addWidget(self.unit_combo)
        
        unit_layout.addWidget(QLabel("  g = 9.8 m/s²"))
        unit_layout.addStretch()
        cal_layout.addLayout(unit_layout)
        
        cal_group.setLayout(cal_layout)
        layout.addWidget(cal_group)
        
        # 数据显示区域
        data_group = QGroupBox("实时数据")
        data_layout = QHBoxLayout()
        
        text_widget = QWidget()
        text_layout = QVBoxLayout()
        
        self.current_force_label = QLabel("力/质量: --.-")
        self.current_force_label.setFont(QFont("Arial", 28, QFont.Weight.Bold))
        self.current_force_label.setStyleSheet("color: #0078d4; padding: 10px;")
        text_layout.addWidget(self.current_force_label)
        
        self.current_raw_label = QLabel("原始ADC: ------")
        self.current_raw_label.setFont(QFont("Arial", 14))
        text_layout.addWidget(self.current_raw_label)
        
        self.current_unit_label = QLabel(f"单位: {self.UNIT_LABELS.get(self.current_unit, 'g')}（未校准则显示原始值）")
        self.current_unit_label.setStyleSheet("color: #666; font-size: 12px;")
        text_layout.addWidget(self.current_unit_label)
        
        self.stats_label = QLabel("统计信息: 暂无数据")
        text_layout.addWidget(self.stats_label)
        
        self.data_text = QTextEdit()
        self.data_text.setMaximumHeight(120)
        text_layout.addWidget(QLabel("数据记录:"))
        text_layout.addWidget(self.data_text)
        
        text_widget.setLayout(text_layout)
        data_layout.addWidget(text_widget)
        
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
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_chart)
        self.timer.start(100)
    
    def on_mode_changed(self, index):
        if index == 0:
            self.serial_panel.show()
            self.ble_panel.hide()
        else:
            self.serial_panel.hide()
            self.ble_panel.show()
    
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
        else:
            self.connect_serial()
    
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
            self.calibrate_btn.setStyleSheet("""
                QPushButton {
                    background-color: #dc3545; color: white;
                    border: none; padding: 8px 16px; border-radius: 4px;
                }
                QPushButton:hover { background-color: #c82333; }
            """)
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
                self.calibrate_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #fd7e14; color: white;
                        border: none; padding: 8px 16px; border-radius: 4px;
                    }
                    QPushButton:hover { background-color: #e06b00; }
                """)
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
            self.calibrate_btn.setStyleSheet("""
                QPushButton {
                    background-color: #fd7e14; color: white;
                    border: none; padding: 8px 16px; border-radius: 4px;
                }
                QPushButton:hover { background-color: #e06b00; }
            """)
    
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

    def edit_sample_rate(self):
        """编辑采样频率对话框"""
        dialog = SampleRateDialog(self.sample_interval_ms, self)
        if dialog.exec() == 1:  # QDialog.Accepted
            new_interval_ms = dialog.get_sample_interval()
            self.sample_interval_ms = new_interval_ms
            freq = 1000 // new_interval_ms
            self.sample_rate_label.setText(f"{freq}Hz")
            self.save_config()
            QMessageBox.information(self, "成功",
                                   f"采样频率已更新为 {freq} Hz！\n"
                                   f"采样间隔：{new_interval_ms} ms\n"
                                   f"配置已自动保存。")

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


class CalibrationDialog(QDialog):
    """校准参数编辑对话框 - 支持单点/两点/三点校准"""
    
    def __init__(self, calibration_points, parent=None):
        super().__init__(parent)
        self.calibration_points = calibration_points
        self.calibration_mode = len(calibration_points) if calibration_points else 2
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("编辑校准参数")
        self.setModal(True)
        self.setFixedSize(500, 500)
        
        layout = QVBoxLayout()
        
        info_label = QLabel(
            "请选择校准模式并输入标准缓冲液 pH 值及其对应的 ADC 原始值："
        )
        info_label.setStyleSheet("color: #666; padding: 10px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        mode_group = QGroupBox("校准模式")
        mode_layout = QVBoxLayout()
        
        self.mode_buttons = []
        modes = [
            (1, "单点校准", "仅使用一个参考点，需要已知理论斜率（约 -0.5 pH/V）"),
            (2, "两点校准", "线性拟合，适合大多数常规测量"),
            (3, "三点校准", "二次拟合，精度最高，推荐用于精确实验")
        ]
        
        for count, label, desc in modes:
            rb_layout = QHBoxLayout()
            rb = QRadioButton(f"{label}")
            rb.setProperty("mode", count)
            rb.setToolTip(desc)
            
            if count == self.calibration_mode:
                rb.setChecked(True)
            
            rb.toggled.connect(self.on_mode_changed)
            rb_layout.addWidget(rb)
            rb_layout.addWidget(QLabel(f"({desc})"))
            rb_layout.addStretch()
            mode_layout.addLayout(rb_layout)
            
            self.mode_buttons.append(rb)
        
        mode_group.setLayout(mode_layout)
        layout.addWidget(mode_group)
        
        points_group = QGroupBox("校准点设置")
        self.points_layout = QVBoxLayout()
        self.point_widgets = []
        self._create_point_inputs()
        points_group.setLayout(self.points_layout)
        layout.addWidget(points_group)
        
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #f0f0f0;
                color: #333;
                border: 1px solid #ccc;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
        """)
        button_layout.addWidget(cancel_btn)
        
        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(self.accept)
        ok_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
            QPushButton:pressed {
                background-color: #005a9e;
            }
        """)
        button_layout.addWidget(ok_btn)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def _create_point_inputs(self):
        for widget in self.point_widgets:
            widget['group'].deleteLater()
        self.point_widgets.clear()
        
        point_names_1 = ["参考缓冲液 (点 1)"]
        point_names_2 = ["低 pH 缓冲液 (点 1)", "高 pH 缓冲液 (点 2)"]
        point_names_3 = ["酸性缓冲液 (点 1)", "中性缓冲液 (点 2)", "碱性缓冲液 (点 3)"]
        
        names_map = {1: point_names_1, 2: point_names_2, 3: point_names_3}
        point_names = names_map.get(self.calibration_mode, point_names_2)
        
        defaults = {
            1: [(7.00, 2281)],
            2: [(4.00, 2555), (9.18, 2030)],
            3: [(4.00, 2555), (6.86, 2281), (9.18, 2030)]
        }
        default_points = defaults.get(self.calibration_mode, defaults[2])
        
        for i, name in enumerate(point_names):
            group = QGroupBox(name)
            group_layout = QHBoxLayout()
            
            ph_label = QLabel("pH 值:")
            group_layout.addWidget(ph_label)
            
            ph_input = QLineEdit(str(default_points[i][0]) if i < len(default_points) else "7.00")
            ph_input.setFixedWidth(80)
            ph_input.setAlignment(Qt.AlignmentFlag.AlignRight)
            group_layout.addWidget(ph_input)
            
            group_layout.addWidget(QLabel("→"))
            
            adc_label = QLabel("ADC/电压:")
            group_layout.addWidget(adc_label)
            
            adc_input = QLineEdit(str(default_points[i][1]) if i < len(default_points) else "2281")
            adc_input.setFixedWidth(80)
            adc_input.setAlignment(Qt.AlignmentFlag.AlignRight)
            group_layout.addWidget(adc_input)
            
            group_layout.addStretch()
            group.setLayout(group_layout)
            self.points_layout.addWidget(group)
            
            self.point_widgets.append({
                'group': group,
                'ph': ph_input,
                'adc': adc_input
            })
    
    def on_mode_changed(self):
        sender = self.sender()
        if sender.isChecked():
            self.calibration_mode = sender.property("mode")
            self._create_point_inputs()
    
    def get_calibration_mode(self):
        return self.calibration_mode
    
    def get_calibration_points(self):
        """获取校准参数"""
        points = []
        for widget in self.point_widgets:
            ph_val = float(widget['ph'].text())
            adc_val = float(widget['adc'].text())
            points.append((ph_val, adc_val))
        return points


class SampleRateDialog(QDialog):
    """采样频率设置对话框"""
    
    def __init__(self, current_interval_ms, parent=None):
        super().__init__(parent)
        self.current_interval_ms = current_interval_ms
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("设置采样频率")
        self.setModal(True)
        self.setFixedSize(400, 260)
        
        layout = QVBoxLayout()
        
        # 说明文字
        info_label = QLabel(
            "请选择数据采集的采样频率：\n"
            "下位机最大输出频率为 10Hz，设定高于此值将接收全部数据。\n"
            "频率越低，数据点越稀疏，适合长时间监测。"
        )
        info_label.setStyleSheet("color: #666; padding: 10px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # 预设频率选项
        preset_group = QGroupBox("预设频率")
        preset_layout = QVBoxLayout()
        
        self.preset_buttons = []
        presets = [
            (100, "10 Hz", "全速接收（下位机最大频率），适合大多数实验"),
            (200, "5 Hz", "中速采样，适合一般变化信号"),
            (500, "2 Hz", "低速采样，适合缓慢变化的信号"),
            (1000, "1 Hz", "超低速采样，长时间监测"),
            (2000, "0.5 Hz", "极低速采样，每2秒一个点"),
            (5000, "0.2 Hz", "最低速采样，每5秒一个点")
        ]
        
        for interval_ms, label, desc in presets:
            rb_layout = QHBoxLayout()
            rb = QRadioButton(f"{label}")
            rb.setProperty("interval", interval_ms)
            rb.setToolTip(desc)
            
            # 如果当前值匹配，则选中
            if interval_ms == self.current_interval_ms:
                rb.setChecked(True)
            
            rb_layout.addWidget(rb)
            rb_layout.addWidget(QLabel(f"({desc})"))
            rb_layout.addStretch()
            preset_layout.addLayout(rb_layout)
            
            self.preset_buttons.append(rb)
        
        preset_group.setLayout(preset_layout)
        layout.addWidget(preset_group)
        
        # 自定义频率
        custom_group = QGroupBox("自定义频率")
        custom_layout = QHBoxLayout()
        
        custom_layout.addWidget(QLabel("采样间隔:"))
        self.custom_input = QSpinBox()
        self.custom_input.setRange(100, 10000)
        self.custom_input.setValue(self.current_interval_ms)
        self.custom_input.setSuffix(" ms")
        self.custom_input.setFixedWidth(120)
        custom_layout.addWidget(self.custom_input)
        
        custom_layout.addWidget(QLabel("(对应 "))
        self.custom_freq_label = QLabel(f"{1000//self.current_interval_ms} Hz")
        self.custom_freq_label.setStyleSheet("font-weight: bold; color: #0078d4;")
        custom_layout.addWidget(self.custom_freq_label)
        custom_layout.addWidget(QLabel(")"))
        
        custom_layout.addStretch()
        custom_group.setLayout(custom_layout)
        layout.addWidget(custom_group)
        
        # 连接信号
        for rb in self.preset_buttons:
            rb.toggled.connect(self.on_preset_changed)
        
        self.custom_input.valueChanged.connect(self.on_custom_changed)
        
        # 按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #f0f0f0;
                color: #333;
                border: 1px solid #ccc;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
        """)
        button_layout.addWidget(cancel_btn)
        
        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(self.accept)
        ok_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
            QPushButton:pressed {
                background-color: #005a9e;
            }
        """)
        button_layout.addWidget(ok_btn)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def on_preset_changed(self, checked):
        """预设选项改变"""
        if checked:
            rb = self.sender()
            interval = rb.property("interval")
            self.custom_input.setValue(interval)
    
    def on_custom_changed(self, value):
        """自定义输入改变"""
        freq = 1000 // value
        self.custom_freq_label.setText(f"{freq} Hz")
    
    def get_sample_interval(self):
        """获取采样间隔"""
        return self.custom_input.value()


class NavButton(QPushButton):
    """Win11 风格侧边栏导航按钮"""
    
    def __init__(self, icon_text, label, tooltip="", parent=None):
        super().__init__(parent)
        self.icon_text = icon_text
        self.label = label
        self.tooltip = tooltip
        self._is_selected = False
        self._is_collapsed = False
        self._theme = "light"
        
        self.setCheckable(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip)
        self.setFixedHeight(40)
        self.setMinimumWidth(40)
        
        self._update_style()
    
    def set_selected(self, selected):
        self._is_selected = selected
        self._update_style()
    
    def set_collapsed(self, collapsed):
        self._is_collapsed = collapsed
        self._update_style()
    
    def set_theme(self, theme):
        self._theme = theme
        self._update_style()
    
    def _update_style(self):
        if self._theme == "dark":
            bg = "#2d2d2d"
            bg_hover = "#3d3d3d"
            bg_selected = "#3d3d3d"
            text_color = "#ffffff"
            icon_color = "#ffffff"
            indicator_color = "#60cdff"
        else:
            bg = "transparent"
            bg_hover = "#e9e9e9"
            bg_selected = "#e9e9e9"
            text_color = "#1a1a1a"
            icon_color = "#1a1a1a"
            indicator_color = "#0067c0"
        
        border_radius = "8px"
        
        if self._is_selected:
            if self._is_collapsed:
                self.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {bg_selected};
                        border: none;
                        border-radius: {border_radius};
                        color: {text_color};
                        font-size: 14px;
                        font-weight: 500;
                    }}
                """)
            else:
                self.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {bg_selected};
                        border: none;
                        border-radius: {border_radius};
                        color: {text_color};
                        font-size: 14px;
                        font-weight: 500;
                        text-align: left;
                        padding-left: 14px;
                    }}
                """)
        else:
            if self._is_collapsed:
                self.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {bg};
                        border: none;
                        border-radius: {border_radius};
                        color: {text_color};
                        font-size: 14px;
                    }}
                    QPushButton:hover {{
                        background-color: {bg_hover};
                    }}
                """)
            else:
                self.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {bg};
                        border: none;
                        border-radius: {border_radius};
                        color: {text_color};
                        font-size: 14px;
                        text-align: left;
                        padding-left: 14px;
                    }}
                    QPushButton:hover {{
                        background-color: {bg_hover};
                    }}
                """)
    
    def paintEvent(self, event):
        super().paintEvent(event)
        from PyQt6.QtGui import QFontMetrics
        from PyQt6.QtCore import QRect
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        if self._theme == "dark":
            icon_color = QColor("#ffffff") if not self._is_selected else QColor("#60cdff")
            text_color = QColor("#ffffff")
            indicator_color = QColor("#60cdff")
        else:
            icon_color = QColor("#1a1a1a") if not self._is_selected else QColor("#0067c0")
            text_color = QColor("#1a1a1a")
            indicator_color = QColor("#0067c0")
        
        rect = self.rect()
        
        # Draw blue indicator bar on the left when selected
        if self._is_selected:
            indicator_width = 3
            indicator_height = 16
            indicator_x = 0
            indicator_y = (rect.height() - indicator_height) // 2
            painter.setBrush(indicator_color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(indicator_x, indicator_y, indicator_width, indicator_height, 2, 2)
        
        # Draw icon
        icon_size = 20
        icon_x = 12 if not self._is_collapsed else (rect.width() - icon_size) // 2
        icon_y = (rect.height() - icon_size) // 2
        
        font = QFont("Segoe MDL2 Assets", 14)
        painter.setFont(font)
        painter.setPen(icon_color)
        painter.drawText(QRect(icon_x, icon_y, icon_size, icon_size), Qt.AlignmentFlag.AlignCenter, self.icon_text)
        
        # Draw text label when expanded
        if not self._is_collapsed:
            painter.setPen(text_color)
            label_font = QFont("Microsoft YaHei", 10)
            painter.setFont(label_font)
            fm = QFontMetrics(label_font)
            text_x = 42
            text_rect = QRect(text_x, 0, rect.width() - text_x - 8, rect.height())
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.label)
        
        painter.end()


class SidebarWidget(QWidget):
    """Win11 风格可折叠侧边栏组件"""
    
    module_changed = pyqtSignal(int)
    
    def __init__(self):
        super().__init__()
        self.is_collapsed = False
        self.expanded_width = 220
        self.collapsed_width = 60
        self.current_index = 0
        self.theme = "light"
        self.init_ui()
    
    def init_ui(self):
        self.setFixedWidth(self.expanded_width)
        self.setStyleSheet("background-color: #f0f0f0; border: none;")
        
        # 主布局
        self.main_layout = QVBoxLayout()
        self.main_layout.setContentsMargins(8, 8, 8, 8)
        self.main_layout.setSpacing(2)
        
        # 顶部汉堡菜单按钮
        self.hamburger_btn = QPushButton()
        self.hamburger_btn.setFixedSize(44, 44)
        self.hamburger_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hamburger_btn.setToolTip("折叠/展开侧边栏")
        self.hamburger_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #e9e9e9;
            }
        """)
        self.hamburger_btn.clicked.connect(self.toggle_collapse)
        self.main_layout.addWidget(self.hamburger_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        
        # 导航按钮列表
        self.nav_buttons = []
        self.nav_container = QWidget()
        self.nav_layout = QVBoxLayout()
        self.nav_layout.setContentsMargins(0, 4, 0, 0)
        self.nav_layout.setSpacing(2)
        
        self.modules = [
            ("🏠", "主页", "项目介绍与功能导航"),
            ("x", "超声波位移", "测量物体位移和运动轨迹"),
            ("v", "超声波速度", "回声定位法测量物体速度"),
            ("F", "力传感器", "HX711力/质量传感器测量"),
            ("V", "电压", "ADC电压采集与分压电路换算"),
            ("pH", "pH传感器", "测量溶液酸碱度"),
        ]
        
        for icon, name, desc in self.modules:
            btn = NavButton(icon, name, desc)
            btn.clicked.connect(lambda checked, idx=len(self.nav_buttons): self.on_nav_clicked(idx))
            self.nav_buttons.append(btn)
            self.nav_layout.addWidget(btn)
        
        self.nav_layout.addStretch()
        self.nav_container.setLayout(self.nav_layout)
        self.main_layout.addWidget(self.nav_container)
        
        # 底部设置按钮（固定在底部）
        self.settings_btn = NavButton("⚙", "设置", "应用设置与偏好")
        self.settings_btn.clicked.connect(lambda: self.on_nav_clicked(len(self.modules)))
        self.nav_buttons.append(self.settings_btn)
        self.main_layout.addWidget(self.settings_btn)
        
        self.setLayout(self.main_layout)
        
        # 设置默认选中
        self.set_current_row(0)
        
        # 初始化汉堡图标
        self._update_hamburger_icon()
    
    def toggle_collapse(self):
        self.is_collapsed = not self.is_collapsed
        
        if self.is_collapsed:
            self.setFixedWidth(self.collapsed_width)
        else:
            self.setFixedWidth(self.expanded_width)
        
        for btn in self.nav_buttons:
            btn.set_collapsed(self.is_collapsed)
        
        self._update_hamburger_icon()
    
    def _update_hamburger_icon(self):
        from PyQt6.QtCore import QRect
        
        pixmap = QPixmap(20, 20)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        if self.theme == "dark":
            color = QColor("#ffffff")
        else:
            color = QColor("#1a1a1a")
        
        painter.setPen(color)
        font = QFont("Segoe MDL2 Assets", 14)
        painter.setFont(font)
        painter.drawText(QRect(0, 0, 20, 20), Qt.AlignmentFlag.AlignCenter, "\uE700")
        painter.end()
        
        self.hamburger_btn.setIcon(QIcon(pixmap))
        self.hamburger_btn.setIconSize(QSize(20, 20))
    
    def set_current_row(self, row):
        if 0 <= row < len(self.nav_buttons):
            self.current_index = row
            for i, btn in enumerate(self.nav_buttons):
                btn.set_selected(i == row)
    
    def get_current_row(self):
        return self.current_index
    
    def on_nav_clicked(self, index):
        self.set_current_row(index)
        self.module_changed.emit(index)
    
    def apply_theme(self, theme):
        self.theme = theme
        if theme == "dark":
            self.setStyleSheet("background-color: #202020; border: none;")
            self.hamburger_btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: none;
                    border-radius: 8px;
                }
                QPushButton:hover {
                    background-color: #3d3d3d;
                }
            """)
        else:
            self.setStyleSheet("background-color: #f0f0f0; border: none;")
            self.hamburger_btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: none;
                    border-radius: 8px;
                }
                QPushButton:hover {
                    background-color: #e9e9e9;
                }
            """)
        
        for btn in self.nav_buttons:
            btn.set_theme(theme)
        
        self._update_hamburger_icon()


class SettingsWidget(QWidget):
    """设置界面组件"""
    
    theme_changed = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.current_theme = "light"
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # 标题
        title = QLabel("设置")
        title.setFont(QFont("Arial", 24, QFont.Weight.Bold))
        layout.addWidget(title)
        
        # 外观设置卡片
        appearance_group = QGroupBox("外观")
        appearance_layout = QVBoxLayout()
        appearance_layout.setSpacing(15)
        
        # 应用主题选项
        theme_label = QLabel("应用主题")
        theme_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        appearance_layout.addWidget(theme_label)
        
        theme_desc = QLabel("选择要显示的应用主题")
        theme_desc.setStyleSheet("color: #666; font-size: 11px;")
        appearance_layout.addWidget(theme_desc)
        
        # Win11风格的主题选择按钮组
        self.theme_button_group = QVBoxLayout()
        self.theme_button_group.setSpacing(8)
        
        self.theme_buttons = {}
        themes = [
            ("system", "使用系统设置"),
            ("light", "浅色"),
            ("dark", "深色")
        ]
        
        for theme_id, theme_name in themes:
            btn = QPushButton(f"  {theme_name}")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(40)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: white;
                    border: 1px solid #e0e0e0;
                    border-radius: 4px;
                    text-align: left;
                    padding-left: 15px;
                    font-size: 13px;
                    color: #333;
                }
                QPushButton:hover {
                    background-color: #f5f5f5;
                    border-color: #0078d4;
                }
                QPushButton:checked {
                    background-color: #e6f2ff;
                    border-left: 3px solid #0078d4;
                    color: #0078d4;
                    font-weight: bold;
                }
            """)
            btn.clicked.connect(lambda checked, tid=theme_id: self.change_theme(tid))
            self.theme_buttons[theme_id] = btn
            self.theme_button_group.addWidget(btn)
        
        appearance_layout.addLayout(self.theme_button_group)
        appearance_group.setLayout(appearance_layout)
        layout.addWidget(appearance_group)
        
        layout.addStretch()
        self.setLayout(layout)
        
        # 默认选中浅色模式
        self.theme_buttons["light"].setChecked(True)
    
    def change_theme(self, theme_id):
        """切换主题"""
        for btn in self.theme_buttons.values():
            btn.setChecked(False)
        self.theme_buttons[theme_id].setChecked(True)
        self.current_theme = theme_id
        self.theme_changed.emit(theme_id)
    
    def apply_theme(self, theme):
        """应用主题到设置界面本身"""
        if theme == "dark":
            dark_style = """
                QWidget {
                    background-color: #202020;
                    color: #ffffff;
                }
                QGroupBox {
                    font-weight: bold;
                    border: 2px solid #3d3d3d;
                    border-radius: 8px;
                    margin-top: 10px;
                    padding-top: 10px;
                    color: #ffffff;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px 0 5px;
                    color: #ffffff;
                }
                QLabel {
                    color: #ffffff;
                }
                QPushButton {
                    background-color: #333333;
                    border: 1px solid #444444;
                    color: #ffffff;
                    border-radius: 4px;
                    padding: 8px 16px;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #404040;
                    border-color: #0078d4;
                }
                QPushButton:checked {
                    background-color: #003366;
                    border-left: 3px solid #0078d4;
                    color: #0078d4;
                    font-weight: bold;
                }
            """
            self.setStyleSheet(dark_style)
        else:
            light_style = """
                QWidget {
                    background-color: #fafafa;
                    color: #000000;
                }
                QGroupBox {
                    font-weight: bold;
                    border: 2px solid #e0e0e0;
                    border-radius: 8px;
                    margin-top: 10px;
                    padding-top: 10px;
                    color: #000000;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px 0 5px;
                    color: #000000;
                }
                QLabel {
                    color: #000000;
                }
                QPushButton {
                    background-color: white;
                    border: 1px solid #e0e0e0;
                    color: #333333;
                    border-radius: 4px;
                    padding: 8px 16px;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #f5f5f5;
                    border-color: #0078d4;
                }
                QPushButton:checked {
                    background-color: #e6f2ff;
                    border-left: 3px solid #0078d4;
                    color: #0078d4;
                    font-weight: bold;
                }
            """
            self.setStyleSheet(light_style)


class MainWindow(QMainWindow):
    """主窗口"""
    
    def __init__(self):
        super().__init__()
        
        # 设置全局字体为微软雅黑
        font = QFont("Microsoft YaHei", 9)
        self.setFont(font)
        
        self.init_ui()
        self.apply_win11_style()
    
    def init_ui(self):
        self.setWindowTitle("PhysChem-DigitizerP")
        self.setGeometry(100, 100, 1200, 800)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QHBoxLayout()
        
        # 侧边栏
        self.sidebar = SidebarWidget()
        self.sidebar.module_changed.connect(self.switch_module)
        main_layout.addWidget(self.sidebar)
        
        # 内容区域
        self.content_stack = QStackedWidget()
        main_layout.addWidget(self.content_stack)
        
        # 创建各个模块的界面
        self.modules = {}
        
        # 主页
        home_page_widget = HomePageWidget()
        home_page_widget.module_clicked.connect(self.on_home_module_clicked)
        self.content_stack.addWidget(home_page_widget)
        self.modules["主页"] = home_page_widget
        
        # 超声波位移模块
        ultrasonic_widget = UltrasonicWidget()
        self.content_stack.addWidget(ultrasonic_widget)
        self.modules["超声波位移"] = ultrasonic_widget
        
        # 超声波速度模块
        ultrasonic_velocity_widget = UltrasonicVelocityWidget()
        self.content_stack.addWidget(ultrasonic_velocity_widget)
        self.modules["超声波速度"] = ultrasonic_velocity_widget
        
        # 力传感器模块
        force_sensor_widget = ForceSensorWidget()
        if hasattr(self, 'flask_server') and self.flask_server:
            force_sensor_widget.set_flask_server(self.flask_server)
        self.content_stack.addWidget(force_sensor_widget)
        self.modules["力传感器"] = force_sensor_widget
        
        # 电压传感器模块
        voltage_sensor_widget = VoltageSensorWidget()
        self.content_stack.addWidget(voltage_sensor_widget)
        self.modules["电压"] = voltage_sensor_widget
        
        # pH传感器模块
        ph_sensor_widget = PhSensorWidget()
        self.content_stack.addWidget(ph_sensor_widget)
        self.modules["pH传感器"] = ph_sensor_widget
        
        # 设置模块
        self.settings_widget = SettingsWidget()
        self.settings_widget.theme_changed.connect(self.change_app_theme)
        self.content_stack.addWidget(self.settings_widget)
        self.modules["设置"] = self.settings_widget
        
        central_widget.setLayout(main_layout)
        
        # 默认选择第一个模块
        self.sidebar.set_current_row(0)
    
    def switch_module(self, index):
        """切换模块"""
        if index >= 0:
            self.content_stack.setCurrentIndex(index)
    
    def on_home_module_clicked(self, module_name):
        """处理主页模块卡片点击事件"""
        # 根据模块名称找到对应的索引
        module_index = None
        for i, (icon, name, desc) in enumerate(self.sidebar.modules):
            if name == module_name:
                module_index = i
                break
        
        if module_index is not None:
            self.sidebar.set_current_row(module_index)
            self.switch_module(module_index)
    
    def change_app_theme(self, theme):
        """切换应用主题"""
        self.current_theme = theme
        self.apply_theme(theme)
        
        # 更新设置界面的主题
        if hasattr(self, 'settings_widget'):
            self.settings_widget.apply_theme(theme)
        
        # 更新侧边栏的主题
        if hasattr(self, 'sidebar'):
            self.sidebar.apply_theme(theme)
        
        # 更新主页的主题
        if hasattr(self, 'modules') and "主页" in self.modules:
            home_widget = self.modules["主页"]
            if hasattr(home_widget, 'apply_theme'):
                home_widget.apply_theme(theme)
    
    def apply_theme(self, theme):
        """应用指定主题"""
        if theme == "dark":
            dark_style = """
                QMainWindow {
                    background-color: #202020;
                    color: white;
                }
                QGroupBox {
                    font-weight: bold;
                    border: 2px solid #3d3d3d;
                    border-radius: 8px;
                    margin-top: 10px;
                    padding-top: 10px;
                    color: white;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px 0 5px;
                    color: white;
                }
                QPushButton {
                    background-color: #0078d4;
                    border: none;
                    color: white;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #106ebe;
                }
                QPushButton:disabled {
                    background-color: #444444;
                    color: #888888;
                }
                QLabel {
                    font-size: 14px;
                    color: white;
                }
                QTextEdit, QComboBox, QSpinBox {
                    border: 1px solid #444444;
                    border-radius: 4px;
                    padding: 4px;
                    font-size: 14px;
                    color: white;
                    background-color: #333333;
                }
                QListWidget {
                    background-color: #2d2d2d;
                    border: none;
                    font-size: 14px;
                    color: white;
                }
                QListWidget::item {
                    padding: 15px;
                    border-bottom: 1px solid #3d3d3d;
                    color: white;
                }
                QListWidget::item:selected {
                    background-color: #0078d4;
                    color: white;
                }
                QListWidget::item:hover {
                    background-color: #3d3d3d;
                }
            """
            self.setStyleSheet(dark_style)
        else:
            light_style = """
                QMainWindow {
                    background-color: #f3f3f3;
                    color: black;
                }
                QGroupBox {
                    font-weight: bold;
                    border: 2px solid #e0e0e0;
                    border-radius: 8px;
                    margin-top: 10px;
                    padding-top: 10px;
                    color: black;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px 0 5px;
                    color: black;
                }
                QPushButton {
                    background-color: #0078d4;
                    border: none;
                    color: white;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #106ebe;
                }
                QPushButton:disabled {
                    background-color: #cccccc;
                    color: #666666;
                }
                QLabel {
                    font-size: 14px;
                    color: black;
                }
                QTextEdit, QComboBox, QSpinBox {
                    border: 1px solid #cccccc;
                    border-radius: 4px;
                    padding: 4px;
                    font-size: 14px;
                    color: black;
                    background-color: white;
                }
                QListWidget {
                    background-color: #f3f3f3;
                    border: none;
                    font-size: 14px;
                    color: black;
                }
                QListWidget::item {
                    padding: 15px;
                    border-bottom: 1px solid #e0e0e0;
                    color: black;
                }
                QListWidget::item:selected {
                    background-color: #0078d4;
                    color: white;
                }
                QListWidget::item:hover {
                    background-color: #f0f0f0;
                }
            """
            self.setStyleSheet(light_style)
    
    def apply_win11_style(self):
        """应用 Win11 风格样式（默认浅色模式）"""
        self.current_theme = "light"
        self.apply_theme("light")


def main():
    app = QApplication(sys.argv)
    
    # 设置应用程序样式
    app.setStyle('Fusion')
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
