# -*- coding: utf-8 -*-
"""
core.py — PhysChem-DigitizerP 公共模块

集中存放各传感器模块共享的代码：
- 配置管理（load/save_sensor_config）
- 串口通信线程（SerialThread）
- BLE 通信线程（BLESerialThread）+ 设备扫描
- 通用对话框（CalibrationDialog / SampleRateDialog）
- 共享样式（卡片 / 按钮 / Win11 风格 ComboBox）
- 主题工具函数

各传感器模块应通过 `from core import ...` 调用本模块的内容，
避免模块间互相依赖。
"""

import os
import json
import asyncio
import threading

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox,
    QLineEdit, QSpinBox, QRadioButton,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QFont

import serial
import serial.tools.list_ports

# ============================================================
# matplotlib 全局字体设置
# ============================================================
import matplotlib.pyplot as plt
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False

# ============================================================
# 统一配置管理 — 所有传感器校准配置保存在同一个 JSON 文件
# ============================================================
CONFIG_FILENAME = 'sensor_config.json'


def _get_config_file_path():
    """获取统一配置文件的绝对路径。

    配置文件始终位于主程序所在目录（即仓库根目录），与具体模块文件位置无关。
    """
    # 取 main.py 所在目录：模块文件位于 传感器代码/xxx/ 下，
    # 上溯两级即为仓库根目录。
    here = os.path.dirname(os.path.abspath(__file__))
    # core.py 在根目录，直接用 here
    return os.path.join(here, CONFIG_FILENAME)


def load_sensor_config(module_name):
    """从统一配置文件中读取指定模块的配置。

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
    """将指定模块的配置写入统一配置文件。

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


# ============================================================
# 串口通信线程
# ============================================================
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


# ============================================================
# BLE 通信（可选依赖 bleak）
# ============================================================
BLE_NUS_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
BLE_NUS_TX_UUID      = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
BLE_NUS_RX_UUID      = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"

try:
    from bleak import BleakClient, BleakScanner
    BLE_AVAILABLE = True
except ImportError:
    BLE_AVAILABLE = False


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


# ============================================================
# 共享样式 — Win11 风格
# ============================================================
def card_style():
    """卡片容器样式（浅色主题）"""
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


def primary_btn_style():
    """主操作按钮样式（蓝色填充）"""
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


def accent_btn_style(normal, hover, pressed):
    """次操作按钮样式（自定义颜色，带边框）"""
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


def win11_combo_style():
    """Win11 WinUI3 风格 QComboBox 样式（浅色主题）。

    特征：
    - 圆角 6px，浅灰背景
    - 悬停时边框加深
    - 聚焦时蓝色边框
    - 下拉箭头使用 Segoe Fluent Icons 字符
    - 下拉列表圆角，选中项蓝色高亮
    """
    return """
        QComboBox {
            background-color: #ffffff;
            border: 1px solid #d0d0d0;
            border-radius: 6px;
            padding: 6px 32px 6px 12px;
            min-height: 20px;
            font-size: 13px;
            color: #1a1a1a;
        }
        QComboBox:hover {
            border: 1px solid #b0b0b0;
            background-color: #fafafa;
        }
        QComboBox:focus {
            border: 1px solid #0078d4;
        }
        QComboBox:on {
            border: 1px solid #0078d4;
            border-bottom-left-radius: 0px;
            border-bottom-right-radius: 0px;
        }
        QComboBox::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 28px;
            border: none;
            background: transparent;
        }
        QComboBox::drop-down:hover {
            background-color: #f0f0f0;
            border-top-right-radius: 6px;
            border-bottom-right-radius: 6px;
        }
        QComboBox::down-arrow {
            image: none;
            border: none;
            width: 14px;
            height: 14px;
        }
        QComboBox QAbstractItemView {
            background-color: #ffffff;
            border: 1px solid #d0d0d0;
            border-radius: 6px;
            padding: 4px;
            outline: none;
            selection-background-color: #f0f6ff;
            selection-color: #0078d4;
            color: #1a1a1a;
        }
        QComboBox QAbstractItemView::item {
            min-height: 32px;
            padding: 4px 12px;
            border-radius: 4px;
            color: #1a1a1a;
        }
        QComboBox QAbstractItemView::item:hover {
            background-color: #f5f5f5;
        }
        QComboBox QAbstractItemView::item:selected {
            background-color: #f0f6ff;
            color: #0078d4;
        }
    """


def win11_combo_style_dark():
    """Win11 WinUI3 风格 QComboBox 样式（深色主题）"""
    return """
        QComboBox {
            background-color: #2d2d2d;
            border: 1px solid #3d3d3d;
            border-radius: 6px;
            padding: 6px 32px 6px 12px;
            min-height: 20px;
            font-size: 13px;
            color: #ffffff;
        }
        QComboBox:hover {
            border: 1px solid #5d5d5d;
            background-color: #323232;
        }
        QComboBox:focus, QComboBox:on {
            border: 1px solid #60cdff;
        }
        QComboBox::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 28px;
            border: none;
            background: transparent;
        }
        QComboBox::drop-down:hover {
            background-color: #3d3d3d;
            border-top-right-radius: 6px;
            border-bottom-right-radius: 6px;
        }
        QComboBox::down-arrow {
            image: none;
            border: none;
            width: 14px;
            height: 14px;
        }
        QComboBox QAbstractItemView {
            background-color: #2d2d2d;
            border: 1px solid #3d3d3d;
            border-radius: 6px;
            padding: 4px;
            outline: none;
            selection-background-color: #1f3a5f;
            selection-color: #60cdff;
            color: #ffffff;
        }
        QComboBox QAbstractItemView::item {
            min-height: 32px;
            padding: 4px 12px;
            border-radius: 4px;
            color: #ffffff;
        }
        QComboBox QAbstractItemView::item:hover {
            background-color: #3d3d3d;
        }
        QComboBox QAbstractItemView::item:selected {
            background-color: #1f3a5f;
            color: #60cdff;
        }
    """


# ============================================================
# 通用对话框
# ============================================================
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
            QPushButton:hover { background-color: #e0e0e0; }
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
            QPushButton:hover { background-color: #106ebe; }
            QPushButton:pressed { background-color: #005a9e; }
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

        info_label = QLabel(
            "请选择数据采集的采样频率：\n"
            "下位机最大输出频率为 10Hz，设定高于此值将接收全部数据。\n"
            "频率越低，数据点越稀疏，适合长时间监测。"
        )
        info_label.setStyleSheet("color: #666; padding: 10px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

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

            if interval_ms == self.current_interval_ms:
                rb.setChecked(True)

            rb_layout.addWidget(rb)
            rb_layout.addWidget(QLabel(f"({desc})"))
            rb_layout.addStretch()
            preset_layout.addLayout(rb_layout)

            self.preset_buttons.append(rb)

        preset_group.setLayout(preset_layout)
        layout.addWidget(preset_group)

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

        for rb in self.preset_buttons:
            rb.toggled.connect(self.on_preset_changed)

        self.custom_input.valueChanged.connect(self.on_custom_changed)

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
            QPushButton:hover { background-color: #e0e0e0; }
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
            QPushButton:hover { background-color: #106ebe; }
            QPushButton:pressed { background-color: #005a9e; }
        """)
        button_layout.addWidget(ok_btn)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def on_preset_changed(self, checked):
        if checked:
            rb = self.sender()
            interval = rb.property("interval")
            self.custom_input.setValue(interval)

    def on_custom_changed(self, value):
        freq = 1000 // value
        self.custom_freq_label.setText(f"{freq} Hz")

    def get_sample_interval(self):
        return self.custom_input.value()
