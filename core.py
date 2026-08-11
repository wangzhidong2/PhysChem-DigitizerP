# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

# -*- coding: utf-8 -*-
"""
core.py — PhysChem-DigitizerP 公共模块

集中存放各传感器模块共享的代码：
- 配置管理（load/save_sensor_config）
- 串口通信线程（SerialThread）
- BLE 通信线程（BLESerialThread）+ 设备扫描
- 通用对话框（CalibrationDialog / SampleRateDialog）
- 共享样式（卡片 / 按钮 / 现代化风格 ComboBox）
- 主题工具函数

各传感器模块应通过 `from core import ...` 调用本模块的内容，
避免模块间互相依赖。
"""

import os
import json
import asyncio
import threading

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QRadioButton, QWidget, QPushButton, QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QThread, QPoint, QTimer
from PySide6.QtGui import QFont, QColor, QPainter, QPen, QBrush, QPainterPath

from qfluentwidgets import (
    PushButton, PrimaryPushButton, ComboBox, EditableComboBox,
    LineEdit, TextEdit, Dialog, MessageBox,
)

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
    data_received = Signal(str)

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
    data_received = Signal(str)
    connection_status = Signal(str)

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
# 可展开/收起的文本记录区
# ============================================================
class ExpandableTextEdit(QWidget):
    """可展开/收起的文本记录区。

    - 默认收起：只显示约 3 行高度（紧凑视图）
    - 点击"展开 ▼"按钮：向上扩展高度，显示更多内容
    - 点击"收起 ▲"按钮：恢复 3 行高度

    内部使用 qfluentwidgets.TextEdit 显示只读文本。
    用 setMaximumHeight 限制高度，避免抢占图表空间。
    """

    # 收起时高度（约 3 行 + 边距）
    COLLAPSED_HEIGHT = 64
    # 展开时高度（约 12 行）
    EXPANDED_HEIGHT = 280

    def __init__(self, parent=None):
        super().__init__(parent)
        self._expanded = False
        self._embedded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 顶部行：标题 + 展开/收起按钮（用容器包裹，便于嵌入浮动面板时整体隐藏）
        self._header_container = QWidget()
        top_row = QHBoxLayout(self._header_container)
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)
        self.title_label = QLabel("数据记录")
        self.title_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        self.title_label.setStyleSheet("color: #1a1a1a; background: transparent;")
        top_row.addWidget(self.title_label)
        top_row.addStretch()

        self.toggle_btn = QPushButton("展开 ▼")
        self.toggle_btn.setFixedHeight(24)
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #0078d4;
                font-size: 12px;
                padding: 0 4px;
            }
            QPushButton:hover { color: #005a9e; text-decoration: underline; }
        """)
        self.toggle_btn.clicked.connect(self._toggle)
        top_row.addWidget(self.toggle_btn)
        layout.addWidget(self._header_container)

        # 文本区
        from qfluentwidgets import TextEdit
        self.text_edit = TextEdit()
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit, 1)

        # 初始应用折叠状态
        self._apply_state()

    def _toggle(self):
        """切换展开/收起状态"""
        self._expanded = not self._expanded
        self._apply_state()

    def _apply_state(self):
        """根据当前状态应用高度约束和文字"""
        if self._embedded:
            # 嵌入模式：由父容器控制大小，自身不设高度约束
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            self.text_edit.setMaximumHeight(16777215)
            self.toggle_btn.setText("收起 ▲" if self._expanded else "展开 ▼")
        elif self._expanded:
            # 展开状态：文本区最大 EXPANDED_HEIGHT，外部 widget 自适应
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            self.text_edit.setMaximumHeight(self.EXPANDED_HEIGHT)
            self.toggle_btn.setText("收起 ▲")
        else:
            # 折叠状态：固定高度为 COLLAPSED_HEIGHT + 标题行
            header_h = self._header_container.sizeHint().height()
            total_h = header_h + 4 + self.COLLAPSED_HEIGHT
            self.setFixedHeight(total_h)
            self.text_edit.setMaximumHeight(self.COLLAPSED_HEIGHT)
            self.toggle_btn.setText("展开 ▼")

    # 代理 TextEdit 的常用方法，保持与原 data_text 调用兼容
    def append(self, text):
        self.text_edit.append(text)

    def clear(self):
        self.text_edit.clear()

    def toPlainText(self):
        return self.text_edit.toPlainText()

    def setPlainText(self, text):
        self.text_edit.setPlainText(text)

    def verticalScrollBar(self):
        return self.text_edit.verticalScrollBar()

    def set_embedded_mode(self, enabled=True):
        """嵌入模式：隐藏自身标题栏（用于浮动面板内，避免与面板标题重复）"""
        self._embedded = enabled
        self._header_container.setVisible(not enabled)
        self._apply_state()


# ============================================================
# 浮动数据面板（全屏图表模式）
# ============================================================
class FloatingDataPanel(QWidget):
    """可拖动、可折叠的浮动数据面板。

    全屏图表模式下，实时数据以浮动小窗形式显示在图表上方。
    - 展开态：标题 + 完整实时数据内容 + 折叠按钮
    - 折叠态：标题 + 主实时值摘要 + 展开按钮
    - 鼠标按住面板空白区域可拖动，自动限制在父控件范围内
    """

    MAX_SUMMARY_LEN = 50

    def __init__(self, content_widget, summary_widget=None, title="数据记录", parent=None):
        super().__init__(parent)
        self._content_widget = content_widget
        self._summary_widget = summary_widget
        self._collapsed = False
        self._dragging = False
        self._drag_offset = QPoint()

        self.setObjectName("floating_panel")
        self.setMaximumWidth(420)
        self.setMinimumWidth(280)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 8, 12, 10)
        main_layout.setSpacing(6)

        # 标题行
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        self.title_label = QLabel(title)
        self.title_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        self.title_label.setStyleSheet("color: #1a1a1a; background: transparent; border: none;")
        header_layout.addWidget(self.title_label)

        self.summary_label = QLabel("")
        self.summary_label.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        self.summary_label.setStyleSheet("color: #0078d4; background: transparent; border: none;")
        self.summary_label.hide()
        header_layout.addWidget(self.summary_label)
        header_layout.addStretch()

        self.toggle_btn = QPushButton("折叠")
        self.toggle_btn.setFixedHeight(26)
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                border: none;
                border-radius: 4px;
                color: white;
                font-size: 12px;
                padding: 2px 10px;
            }
            QPushButton:hover { background-color: #106ebe; }
        """)
        self.toggle_btn.clicked.connect(self._toggle)
        header_layout.addWidget(self.toggle_btn)

        main_layout.addLayout(header_layout)

        # 完整内容
        self._content_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        main_layout.addWidget(self._content_widget, 1)

        # 定时刷新折叠态摘要文本（实时值在持续更新）
        self._summary_timer = QTimer(self)
        self._summary_timer.timeout.connect(self._update_summary)
        self._summary_timer.start(100)

        self._update_summary()

        # 默认展开尺寸
        self.resize(380, 360)

    def _toggle(self):
        """切换折叠/展开状态"""
        self._collapsed = not self._collapsed
        self._content_widget.setVisible(not self._collapsed)
        self.summary_label.setVisible(self._collapsed)
        self.toggle_btn.setText("展开" if self._collapsed else "折叠")
        self._update_summary()
        self.adjustSize()

    def _update_summary(self):
        """从 summary_widget 读取当前实时值，更新折叠态摘要显示"""
        if self._summary_widget is not None:
            text = self._summary_widget.text()
            # 去掉常见前缀，保持摘要简洁
            for prefix in ("当前数据: ", "电压: ", "电流: "):
                if text.startswith(prefix):
                    text = text[len(prefix):]
                    break
            if len(text) > self.MAX_SUMMARY_LEN:
                text = text[:self.MAX_SUMMARY_LEN - 3] + "..."
            self.summary_label.setText(text)

    def release_content(self):
        """将内容控件从面板中移出（reparent 到 None），返回内容控件。

        在销毁浮动面板前调用，避免内容控件随面板一起被删除。
        """
        if self._content_widget is not None:
            self.layout().removeWidget(self._content_widget)
            self._content_widget.setParent(None)
            widget = self._content_widget
            self._content_widget = None
            return widget
        return None

    def paintEvent(self, e):
        """绘制半透明白色圆角背景"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(QColor(255, 255, 255, 245)))
        painter.setPen(QPen(QColor("#b0b0b0"), 1))
        path = QPainterPath()
        path.addRoundedRect(0.5, 0.5, self.width() - 1, self.height() - 1, 8, 8)
        painter.drawPath(path)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            # 点击按钮时不启动拖动
            child = self.childAt(e.position().toPoint())
            if child is not self.toggle_btn:
                self._dragging = True
                self._drag_offset = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._dragging:
            new_pos = self.pos() + e.position().toPoint() - self._drag_offset
            parent = self.parent()
            if parent is not None:
                new_pos.setX(max(0, min(new_pos.x(), parent.width() - self.width())))
                new_pos.setY(max(0, min(new_pos.y(), parent.height() - self.height())))
            self.move(new_pos)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._dragging = False
        super().mouseReleaseEvent(e)

    def clamp_position(self):
        """限制面板位置在父控件范围内（父控件 resize 时调用）"""
        parent = self.parent()
        if parent is None:
            return
        x = max(0, min(self.x(), parent.width() - self.width()))
        y = max(0, min(self.y(), parent.height() - self.height()))
        self.move(x, y)


# ============================================================
# 可折叠卡片
# ============================================================
class CollapsibleCard(QWidget):
    """可折叠卡片：点击标题区切换内容显示/隐藏。

    - 折叠时：只显示标题 + 向下箭头 ▼
    - 展开时：显示标题 + 全部内容 + 向上箭头 ▲

    外观为白底 + 圆角 + 浅灰边框，与主页卡片一致。
    用 paintEvent 直接绘制白色背景，避免父级样式表级联覆盖。

    使用方式：
        content = QWidget()
        content_layout = QVBoxLayout(content)
        ...  # 添加内容控件
        card = CollapsibleCard("卡片标题", content, expanded=True)
        parent_layout.addWidget(card)
    """

    CARD_STYLE = """
        QWidget#collapsible_card QWidget {
            background: transparent;
        }
        QWidget#collapsible_card QComboBox,
        QWidget#collapsible_card QTextEdit,
        QWidget#collapsible_card QPlainTextEdit,
        QWidget#collapsible_card QSpinBox,
        QWidget#collapsible_card QDoubleSpinBox,
        QWidget#collapsible_card QLineEdit,
        QWidget#collapsible_card QListView,
        QWidget#collapsible_card QTreeView,
        QWidget#collapsible_card QTableView,
        QWidget#collapsible_card QScrollArea,
        QWidget#collapsible_card QAbstractScrollArea {
            background: #ffffff;
        }
        QFrame#collapsible_header {
            background: transparent;
            border: none;
            border-radius: 8px;
        }
        QFrame#collapsible_header:hover {
            background: #fafafa;
        }
    """

    class _Header(QFrame):
        """可点击的标题栏（QFrame + mouseReleaseEvent）。"""

        clicked = Signal()

        def mouseReleaseEvent(self, e):
            if e.button() == Qt.MouseButton.LeftButton:
                self.clicked.emit()
            super().mouseReleaseEvent(e)

    def __init__(self, title, content_widget, parent=None, expanded=True, fullscreen=False):
        super().__init__(parent)
        self._expanded = expanded
        self._content_widget = content_widget
        self._fullscreen = False  # 当前是否处于全屏状态
        self._fullscreen_enabled = fullscreen  # 是否启用全屏按钮
        self._orig_parent = None  # 全屏前的父控件
        self._orig_layout = None  # 全屏前所在的布局
        self._orig_index = -1     # 全屏前在布局中的索引
        self._host = None         # 全屏时的宿主 viewport
        self._scroll = None       # 全屏时的 QScrollArea
        # 全屏浮动面板相关
        self._overlay_content_widget = None   # 全屏时浮于图表上方的控件（如数据记录区）
        self._overlay_summary_widget = None   # 折叠态显示的摘要标签（如实时值）
        self._overlay_orig_parent = None      # 浮动控件的原父控件
        self._overlay_orig_layout = None      # 浮动控件的原布局
        self._overlay_orig_index = -1         # 浮动控件在原布局中的索引
        self._overlay_orig_stretch = 0        # 浮动控件在原布局中的 stretch
        self._floating_panel = None           # 全屏时的 FloatingDataPanel 实例
        self._fullscreen_hidden_widgets = []  # 全屏时需隐藏的控件

        self.setObjectName("collapsible_card")
        self.setStyleSheet(self.CARD_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题栏（可点击 QFrame）
        self.header = self._Header()
        self.header.setObjectName("collapsible_header")
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(24, 14, 24, 14)
        header_layout.setSpacing(8)

        self.title_label = QLabel(title)
        self.title_label.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        self.title_label.setStyleSheet("color: #1a1a1a;")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        # 全屏按钮（可选）
        if self._fullscreen_enabled:
            self.fullscreen_btn = QPushButton("⛶")
            self.fullscreen_btn.setFixedSize(28, 28)
            self.fullscreen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.fullscreen_btn.setToolTip("全屏显示 / 退出全屏")
            self.fullscreen_btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    border: none;
                    border-radius: 4px;
                    font-size: 16px;
                    color: #666666;
                }
                QPushButton:hover { background: #f0f0f0; color: #0078d4; }
            """)
            self.fullscreen_btn.clicked.connect(self.toggle_fullscreen)
            header_layout.addWidget(self.fullscreen_btn)

        self.arrow_label = QLabel("▲" if expanded else "▼")
        self.arrow_label.setFont(QFont("Microsoft YaHei", 12))
        self.arrow_label.setStyleSheet("color: #666666;")
        header_layout.addWidget(self.arrow_label)

        self.header.clicked.connect(self._toggle)
        layout.addWidget(self.header)

        # 内容区（stretch=1 填满标题栏下方剩余空间）
        # 必须先 addWidget（设置父级）再 setVisible，
        # 否则无父级的 content_widget 会被当作顶级窗口闪现
        layout.addWidget(self._content_widget, 1)
        self._content_widget.setVisible(expanded)

    def paintEvent(self, e):
        """直接用 QPainter 绘制白色圆角背景，绕过样式表级联覆盖。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(QColor("#ffffff")))
        painter.setPen(QPen(QColor("#e5e5e5"), 1))
        path = QPainterPath()
        path.addRoundedRect(0.5, 0.5, self.width() - 1, self.height() - 1, 8, 8)
        painter.drawPath(path)

    def _toggle(self):
        """切换展开/折叠状态，并同步箭头方向"""
        self._expanded = not self._expanded
        self._content_widget.setVisible(self._expanded)
        self.arrow_label.setText("▲" if self._expanded else "▼")

    def toggle_fullscreen(self):
        """切换全屏/还原。

        全屏时：把卡片 reparent 到模块的滚动区 viewport 上，作为覆盖层填满整个内容区，
        不覆盖侧边栏和标题栏（因为 viewport 本身就在内容区内）。
        还原时：把卡片 reparent 回原父控件，插回原布局原位置。
        """
        if not self._fullscreen:
            self._enter_fullscreen()
        else:
            self._exit_fullscreen()

    # ---------- 全屏浮动面板接口 ----------
    def set_fullscreen_overlay(self, content_widget, summary_widget=None):
        """设置全屏时浮动面板的内容控件。

        Args:
            content_widget: 全屏时浮于图表上方的控件（如数据记录区文本框）。
                            全屏时该控件会被移入可拖动、可折叠的浮动面板；
                            退出全屏时自动恢复到原布局原位置。
            summary_widget: 折叠态显示的摘要标签（如实时值标签，可选）
        """
        self._overlay_content_widget = content_widget
        self._overlay_summary_widget = summary_widget

    def add_fullscreen_hidden_widget(self, widget):
        """注册全屏时需隐藏的控件"""
        self._fullscreen_hidden_widgets.append(widget)

    def _detach_overlay_widget(self):
        """从原布局中移除浮动内容控件，并记录原位置以便恢复。

        Returns: 被移除的控件（成功时）或 None
        """
        widget = self._overlay_content_widget
        if widget is None:
            return None
        self._overlay_orig_parent = widget.parentWidget()
        # 在父控件的布局树中递归查找包含该 widget 的布局及索引
        self._overlay_orig_layout = None
        self._overlay_orig_index = -1
        self._overlay_orig_stretch = 0
        if self._overlay_orig_parent is not None:
            result = self._find_widget_in_layout_tree(
                self._overlay_orig_parent.layout(), widget)
            if result is not None:
                self._overlay_orig_layout, self._overlay_orig_index = result
        if self._overlay_orig_layout is not None:
            # 记录 stretch factor
            item = self._overlay_orig_layout.itemAt(self._overlay_orig_index)
            if item is not None:
                # QBoxLayout / QGridLayout 等支持 stretch
                try:
                    self._overlay_orig_stretch = self._overlay_orig_layout.stretch(self._overlay_orig_index)
                except Exception:
                    self._overlay_orig_stretch = 0
            self._overlay_orig_layout.removeWidget(widget)
        widget.setParent(None)
        return widget

    @staticmethod
    def _find_widget_in_layout_tree(layout, target):
        """在布局树中递归查找 target widget，返回 (layout, index) 或 None"""
        if layout is None:
            return None
        for i in range(layout.count()):
            it = layout.itemAt(i)
            if it is None:
                continue
            if it.widget() is target:
                return (layout, i)
            sub = it.layout()
            if sub is not None:
                r = CollapsibleCard._find_widget_in_layout_tree(sub, target)
                if r is not None:
                    return r
        return None

    def _restore_overlay_widget(self):
        """将浮动内容控件恢复到原布局原位置"""
        widget = self._overlay_content_widget
        if widget is None or self._overlay_orig_layout is None:
            return
        widget.setParent(self._overlay_orig_parent)
        if self._overlay_orig_index >= 0:
            self._overlay_orig_layout.insertWidget(self._overlay_orig_index, widget, self._overlay_orig_stretch)
        else:
            self._overlay_orig_layout.addWidget(widget, self._overlay_orig_stretch)
        widget.show()

    def _find_content_host(self):
        """向上查找适合作为全屏宿主的滚动区 viewport。

        传感器模块结构：模块widget -> main_layout -> scroll(QScrollArea) -> content。
        全屏时覆盖到 scroll 的 viewport 上，这样能利用整个内容区，且不覆盖侧边栏/标题栏。
        """
        from PySide6.QtWidgets import QScrollArea
        p = self.parent()
        while p is not None:
            if isinstance(p, QScrollArea):
                return p.viewport()  # scroll 的 viewport
            p = p.parent()
        return None

    def _find_scroll_area(self):
        """向上查找 QScrollArea，用于监听尺寸变化"""
        from PySide6.QtWidgets import QScrollArea
        p = self.parent()
        while p is not None:
            if isinstance(p, QScrollArea):
                return p
            p = p.parent()
        return None

    def _enter_fullscreen(self):
        """进入全屏：reparent 到 viewport，绝对定位填满"""
        from PySide6.QtWidgets import QScrollArea
        host = self._find_content_host()
        if host is None:
            return
        scroll = self._find_scroll_area()
        if scroll is None:
            return

        # 记录原位置
        self._orig_parent = self.parent()
        pl = self._orig_parent.layout()
        self._orig_layout = None
        self._orig_index = -1
        if pl is not None:
            for i in range(pl.count()):
                it = pl.itemAt(i)
                if it and it.widget() is self:
                    self._orig_index = i
                    self._orig_layout = pl
                    break

        # 从原布局移除（不删除 widget）
        if self._orig_layout is not None:
            self._orig_layout.removeWidget(self)

        # reparent 到 viewport，绝对定位填满
        self.setParent(host)
        self._host = host
        self._scroll = scroll
        self._fullscreen = True

        # 隐藏滚动条（全屏时不滚动）
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # 安装事件过滤器监听 viewport 尺寸变化
        host.installEventFilter(self)

        # 隐藏注册的控件（如数据记录区），让图表 canvas 填满整个区域
        for w in self._fullscreen_hidden_widgets:
            w.setVisible(False)

        # reparent 后必须显式 show()，否则 Qt 可能将卡片及其内容（含图表）标记为不可见
        self.show()
        self.header.setVisible(True)
        self.title_label.setVisible(True)
        self.arrow_label.setVisible(True)
        if hasattr(self, 'fullscreen_btn'):
            self.fullscreen_btn.setVisible(True)
        # 内容区（含 FigureCanvas）必须可见
        self._content_widget.setVisible(True)

        # 立即设置一次几何，再用延迟回调修正（隐藏滚动条后 viewport 尺寸会变化）
        self.setGeometry(0, 0, host.width(), host.height())
        self.raise_()
        # 强制布局重算，确保图表 canvas 拿到正确尺寸
        if self.layout() is not None:
            self.layout().activate()

        # 创建浮动数据面板：将数据记录区控件浮于图表上方
        if self._overlay_content_widget is not None:
            overlay_content = self._detach_overlay_widget()
            if overlay_content is not None:
                # 嵌入模式：隐藏 data_text 自身标题栏，避免与浮动面板标题重复
                if hasattr(overlay_content, 'set_embedded_mode'):
                    overlay_content.set_embedded_mode(True)
                self._floating_panel = FloatingDataPanel(
                    overlay_content,
                    summary_widget=self._overlay_summary_widget,
                    parent=self,
                )
                self._floating_panel.move(16, 16)
                self._floating_panel.show()
                self._floating_panel.raise_()

        # 延迟修正几何：等滚动条隐藏、viewport 尺寸更新后再最终定位
        def _fix_geom():
            if self._fullscreen and self._host is not None:
                self.setGeometry(0, 0, self._host.width(), self._host.height())
                if self.layout() is not None:
                    self.layout().activate()
                # 触发内部 matplotlib canvas 重绘
                self._redraw_canvas()
                # 浮动面板可能需要调整位置
                if self._floating_panel is not None:
                    self._floating_panel.clamp_position()
        QTimer.singleShot(0, _fix_geom)

    def _redraw_canvas(self):
        """查找卡片内的 FigureCanvas 并触发重绘，避免全屏后图表空白"""
        try:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        except Exception:
            return
        # 在内容区递归查找 FigureCanvas
        def _find(w):
            if isinstance(w, FigureCanvasQTAgg):
                return w
            for child in w.children():
                r = _find(child)
                if r is not None:
                    return r
            return None
        canvas = _find(self._content_widget)
        if canvas is not None:
            try:
                canvas.draw()
            except Exception:
                pass

    def _exit_fullscreen(self):
        """退出全屏：reparent 回原父控件，插回原位置"""
        if self._host is None:
            return
        # 移除事件过滤器
        self._host.removeEventFilter(self)

        # 恢复滚动条
        if self._scroll is not None:
            self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # 销毁浮动数据面板，恢复内容控件到原布局
        if self._floating_panel is not None:
            released = self._floating_panel.release_content()
            self._floating_panel.deleteLater()
            self._floating_panel = None
            self._restore_overlay_widget()
            # 关闭嵌入模式，恢复 data_text 自身标题栏
            if released is not None and hasattr(released, 'set_embedded_mode'):
                released.set_embedded_mode(False)

        # 恢复全屏时隐藏的控件
        for w in self._fullscreen_hidden_widgets:
            w.setVisible(True)

        # reparent 回原父控件
        self.setParent(self._orig_parent)
        if self._orig_layout is not None and self._orig_index >= 0:
            self._orig_layout.insertWidget(self._orig_index, self)

        self._fullscreen = False
        self._host = None
        self._scroll = None

        # reparent 后显式 show，确保卡片及其内容可见
        self.show()
        self._content_widget.setVisible(self._expanded)
        if self.layout() is not None:
            self.layout().activate()
        # 延迟重绘 canvas，等布局稳定
        QTimer.singleShot(0, self._redraw_canvas)

    def eventFilter(self, obj, e):
        """监听 viewport 尺寸变化，全屏时跟随"""
        from PySide6.QtCore import QEvent
        if obj is self._host and e.type() == QEvent.Type.Resize:
            if self._fullscreen and self._host is not None:
                self.setGeometry(0, 0, self._host.width(), self._host.height())
                if self._floating_panel is not None:
                    self._floating_panel.clamp_position()
        return super().eventFilter(obj, e)


# ============================================================
# 共享样式 — 现代化风格
# ============================================================
def card_style():
    """卡片容器样式（浅色主题）。

    注意：页面容器常写 `content.setStyleSheet("background: #f3f3f3;")`，
    该无选择器的样式表会级联到所有子 widget，导致卡片内的中间容器
    （如 serial_panel、ble_panel 等未设 objectName 的 QWidget）继承
    灰色背景。这里用 `QWidget#card QWidget` 把卡片内所有子 widget
    背景置透明，使其透出卡片白色底；各控件（ComboBox/TextEdit/
    QPushButton 等）自身的样式表优先级更高，不受影响。
    """
    return """
        QWidget#card {
            background-color: #ffffff;
            border: 1px solid #e5e5e5;
            border-radius: 8px;
        }
        QWidget#card QWidget {
            background-color: transparent;
        }
        QWidget#card QComboBox,
        QWidget#card QTextEdit,
        QWidget#card QPlainTextEdit,
        QWidget#card QSpinBox,
        QWidget#card QDoubleSpinBox,
        QWidget#card QLineEdit,
        QWidget#card QListView,
        QWidget#card QTreeView,
        QWidget#card QTableView,
        QWidget#card QScrollArea,
        QWidget#card QAbstractScrollArea {
            background-color: #ffffff;
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


def modern_combo_style():
    """现代化风格 QComboBox 样式（浅色主题）。

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


def modern_combo_style_dark():
    """现代化风格 QComboBox 样式（深色主题）"""
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
# ComboBox 箭头翻转补丁
# ============================================================
def patch_combobox_arrow_flip():
    """让 FluentWidgets 的 ComboBox / EditableComboBox 展开下拉时箭头朝上。

    FluentWidgets 的 ComboBox 继承自 QPushButton（非 QComboBox），
    paintEvent 中硬编码绘制 FIF.ARROW_DOWN，无论是否展开都朝下。
    本函数 monkey-patch 其 paintEvent，当下拉菜单（dropMenu）存在时
    将箭头绕中心旋转 180°，实现「展开朝上 / 收起朝下」的交互。
    同时处理 EditableComboBox 的 LineEditButton 箭头按钮。
    """
    from qfluentwidgets.components.widgets.combo_box import (
        ComboBox as _CBox, EditableComboBox as _EBox, ComboBoxBase as _CBase,
    )
    from qfluentwidgets.components.widgets.line_edit import LineEditButton as _LEBtn
    from qfluentwidgets.common.icon import (
        FluentIcon as _FIF, isDarkTheme, drawIcon as _drawIcon,
    )
    from PySide6.QtWidgets import QPushButton as _QPB, QToolButton as _QTB
    from PySide6.QtGui import QPainter as _QPainter
    from PySide6.QtCore import QRectF as _QRectF

    if getattr(_CBox, '_arrow_flip_patched', False):
        return

    # --- ComboBox.paintEvent：展开时箭头旋转 180° ---
    def _combo_paint(self, e):
        _QPB.paintEvent(self, e)
        painter = _QPainter(self)
        painter.setRenderHints(_QPainter.Antialiasing)
        if self.isHover:
            painter.setOpacity(0.8)
        elif self.isPressed:
            painter.setOpacity(0.7)
        rect = _QRectF(self.width()-22, self.height()/2-5+self.arrowAni.y, 10, 10)
        flipped = self.dropMenu is not None
        if flipped:
            painter.save()
            c = rect.center()
            painter.translate(c.x(), c.y())
            painter.rotate(180)
            painter.translate(-c.x(), -c.y())
        if isDarkTheme():
            _FIF.ARROW_DOWN.render(painter, rect)
        else:
            _FIF.ARROW_DOWN.render(painter, rect, fill="#646464")
        if flipped:
            painter.restore()
    _CBox.paintEvent = _combo_paint

    # --- LineEditButton.paintEvent：EditableComboBox 的箭头按钮，展开时翻转 ---
    _orig_leb_paint = _LEBtn.paintEvent

    def _leb_paint(self, e):
        parent = self.parent()
        flip = (parent is not None
                and getattr(parent, 'dropMenu', None) is not None
                and getattr(self, '_icon', None) is _FIF.ARROW_DOWN)
        if not flip:
            _orig_leb_paint(self, e)
            return
        _QTB.paintEvent(self, e)
        painter = _QPainter(self)
        painter.setRenderHints(_QPainter.Antialiasing | _QPainter.SmoothPixmapTransform)
        iw, ih = self.iconSize().width(), self.iconSize().height()
        w, h = self.width(), self.height()
        rect = _QRectF((w - iw)/2, (h - ih)/2, iw, ih)
        if self.isPressed:
            painter.setOpacity(0.7)
        painter.save()
        c = rect.center()
        painter.translate(c.x(), c.y())
        painter.rotate(180)
        painter.translate(-c.x(), -c.y())
        if isDarkTheme():
            _drawIcon(self._icon, painter, rect)
        else:
            _drawIcon(self._icon, painter, rect, fill='#656565')
        painter.restore()
    _LEBtn.paintEvent = _leb_paint

    # --- 菜单打开/关闭后触发重绘，确保箭头方向同步 ---
    from PySide6.QtCore import QTimer as _QTimer

    def _refresh(self):
        self.update()
        db = getattr(self, 'dropButton', None)
        if db is not None:
            db.update()

    _orig_show = _CBase._showComboMenu

    def _show(self):
        # _orig_show 内部会同步执行 menu.exec()（进入新的事件循环阻塞），
        # 若直接在 _orig_show 返回后调用 _refresh，那时菜单已关闭、
        # dropMenu 已被置 None，箭头翻转永远无法触发。
        # 用 QTimer.singleShot(0) 把 _refresh 投递到下一个事件循环迭代：
        # 当 _orig_show 内部 dropMenu 设置完毕并调用 menu.exec() 进入
        # 嵌套事件循环时，QTimer 回调会被处理，此时 dropMenu 已存在，
        # 箭头会被正确翻转重绘。
        _QTimer.singleShot(0, lambda: _refresh(self))
        _orig_show(self)
    _CBase._showComboMenu = _show

    _orig_close = _CBase._closeComboMenu

    def _close(self):
        _orig_close(self)
        _refresh(self)
    _CBase._closeComboMenu = _close

    _orig_onclose = _CBase._onDropMenuClosed

    def _onclose(self):
        _orig_onclose(self)
        _refresh(self)
    _CBase._onDropMenuClosed = _onclose

    _orig_onclose_e = _EBox._onDropMenuClosed

    def _onclose_e(self):
        _orig_onclose_e(self)
        _refresh(self)
    _EBox._onDropMenuClosed = _onclose_e

    _CBox._arrow_flip_patched = True


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

        cancel_btn = PushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        ok_btn = PrimaryPushButton("确定")
        ok_btn.clicked.connect(self.accept)
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

            ph_input = LineEdit()
            ph_input.setText(str(default_points[i][0]) if i < len(default_points) else "7.00")
            ph_input.setFixedWidth(80)
            ph_input.setAlignment(Qt.AlignmentFlag.AlignRight)
            group_layout.addWidget(ph_input)

            group_layout.addWidget(QLabel("→"))

            adc_label = QLabel("ADC/电压:")
            group_layout.addWidget(adc_label)

            adc_input = LineEdit()
            adc_input.setText(str(default_points[i][1]) if i < len(default_points) else "2281")
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
    """采样频率设置对话框

    使用 EditableComboBox：既可从预设频率下拉选择，也可直接输入自定义频率值。
    输入格式：纯数字（视为 Hz）或带 "Hz"/"hz" 后缀，范围 0.1~10 Hz，
    对应采样间隔 100~10000 ms（下位机最大输出频率为 10 Hz）。
    """

    # 预设频率：(interval_ms, 显示文本, 说明)
    PRESETS = [
        (100,  "10 Hz",   "全速接收（下位机最大频率），适合大多数实验"),
        (200,  "5 Hz",    "中速采样，适合一般变化信号"),
        (500,  "2 Hz",    "低速采样，适合缓慢变化的信号"),
        (1000, "1 Hz",    "超低速采样，长时间监测"),
        (2000, "0.5 Hz",  "极低速采样，每2秒一个点"),
        (5000, "0.2 Hz",  "最低速采样，每5秒一个点"),
    ]

    # 允许的频率范围（Hz）：下位机最大 10 Hz，最低 0.1 Hz（10000ms）
    FREQ_MIN = 0.1
    FREQ_MAX = 10.0

    def __init__(self, current_interval_ms, parent=None):
        super().__init__(parent)
        self.current_interval_ms = current_interval_ms
        self._interval_ms = current_interval_ms  # 当前选中/输入对应的间隔
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("设置采样频率")
        self.setModal(True)
        self.setFixedSize(420, 280)

        layout = QVBoxLayout()
        layout.setSpacing(12)

        info_label = QLabel(
            "请选择或输入数据采集的采样频率：\n"
            "下位机最大输出频率为 10 Hz，设定高于此值将接收全部数据。\n"
            "频率越低，数据点越稀疏，适合长时间监测。"
        )
        info_label.setStyleSheet("color: #666; padding: 4px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # 可编辑下拉框：预设项 + 自由输入
        self.combo = EditableComboBox()
        self.combo.setPlaceholderText("选择预设频率，或直接输入 Hz 值（如 3 或 0.5Hz）")
        for interval_ms, label, _ in self.PRESETS:
            self.combo.addItem(label, userData=interval_ms)

        # 当前值回填：优先匹配预设，否则显示换算后的 Hz 文本
        current_text = self._interval_to_text(self.current_interval_ms)
        self.combo.setCurrentText(current_text)
        self.combo.currentTextChanged.connect(self._on_text_changed)
        self.combo.setFixedHeight(34)
        layout.addWidget(self.combo)

        # 实时反馈：显示当前频率 ↔ 采样间隔，以及合法性提示
        self.feedback_label = QLabel()
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setStyleSheet("padding: 4px;")
        layout.addWidget(self.feedback_label)

        layout.addStretch()

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = PushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        ok_btn = PrimaryPushButton("确定")
        ok_btn.clicked.connect(self._on_accept)
        button_layout.addWidget(ok_btn)

        layout.addLayout(button_layout)
        self.setLayout(layout)

        self._on_text_changed(self.combo.currentText())

    # ---------- 解析与反馈 ----------
    def _interval_to_text(self, interval_ms):
        """采样间隔 → 显示文本（优先匹配预设项，否则换算 Hz）"""
        for iv, label, _ in self.PRESETS:
            if iv == interval_ms:
                return label
        freq = 1000.0 / interval_ms
        return f"{freq:g} Hz"

    def _parse_freq(self, text):
        """解析输入文本为频率（Hz）。失败返回 None。

        接受格式：'10'、'10Hz'、'10 Hz'、'0.5hz' 等
        """
        s = text.strip().lower().replace("hz", "").strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None

    def _on_text_changed(self, text):
        freq = self._parse_freq(text)
        if freq is None or freq <= 0:
            self._interval_ms = None
            self.feedback_label.setText(
                '<span style="color:#c0392b;">⚠ 无法识别，请输入数字频率（Hz），如 10、2、0.5</span>'
            )
            return

        # 超出范围时仍换算显示，但标红提示
        interval_ms = round(1000.0 / freq)
        self._interval_ms = interval_ms

        in_range = self.FREQ_MIN <= freq <= self.FREQ_MAX
        color = "#0078d4" if in_range else "#c0392b"
        warn = "" if in_range else "  （超出 0.1~10 Hz 范围，将被限制）"
        self.feedback_label.setText(
            f'<span style="color:#444;">当前：'
            f'<b style="color:{color};">{freq:g} Hz</b> '
            f'（采样间隔 {interval_ms} ms）{warn}</span>'
        )

    def _on_accept(self):
        # 输入非法时不允许确定
        if self._interval_ms is None:
            return
        # 限制到允许范围
        interval = max(100, min(10000, self._interval_ms))
        self._interval_ms = interval
        self.accept()

    def get_sample_interval(self):
        """返回当前采样间隔（ms）。"""
        return self._interval_ms if self._interval_ms is not None else self.current_interval_ms


class SampleRateComboBox(EditableComboBox):
    """采样频率内联可编辑下拉框（直接嵌入主界面，无需弹对话框）。

    传感器模块用本组件替换原先的「频率 QLabel + ⚙设置按钮」：
    - 下拉选预设频率（10/5/2/1/0.5/0.2 Hz）
    - 或手动输入 Hz 值（如 3、0.5Hz），文本改变时即时生效
    - 范围 0.1~10 Hz，对应采样间隔 100~10000 ms（下位机最大 10 Hz）

    信号：
        sampleIntervalChanged(int): 采样间隔改变时发射，参数为新间隔（ms）
    """

    # 预设频率：(interval_ms, 显示文本, 说明)
    PRESETS = [
        (100,  "10 Hz",   "全速接收（下位机最大频率）"),
        (200,  "5 Hz",    "中速采样"),
        (500,  "2 Hz",    "低速采样"),
        (1000, "1 Hz",    "超低速采样"),
        (2000, "0.5 Hz",  "极低速采样"),
        (5000, "0.2 Hz",  "最低速采样"),
    ]

    FREQ_MIN = 0.1   # Hz
    FREQ_MAX = 10.0  # Hz

    sampleIntervalChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._interval_ms = 100
        self._block_signal = True  # 初始化期间抑制信号

        for interval_ms, label, _ in self.PRESETS:
            self.addItem(label, userData=interval_ms)

        self.setPlaceholderText("采样频率")
        self.setMaxVisibleItems(10)
        self.setFixedHeight(32)
        self.setMinimumWidth(110)
        self.currentTextChanged.connect(self._on_text_changed)

        self._block_signal = False

    # ---------- 公共接口 ----------
    def setSampleInterval(self, interval_ms):
        """设置当前采样间隔（ms），不会重复发射信号。"""
        prev = self._interval_ms
        self._block_signal = True
        self._interval_ms = interval_ms
        self.setCurrentText(self._interval_to_text(interval_ms))
        self._block_signal = False
        if prev != interval_ms:
            self.sampleIntervalChanged.emit(interval_ms)

    def getSampleInterval(self):
        """返回当前采样间隔（ms）。"""
        return self._interval_ms

    # ---------- 内部 ----------
    def _interval_to_text(self, interval_ms):
        for iv, label, _ in self.PRESETS:
            if iv == interval_ms:
                return label
        freq = 1000.0 / interval_ms
        return f"{freq:g} Hz"

    def _parse_freq(self, text):
        s = text.strip().lower().replace("hz", "").strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None

    def _on_text_changed(self, text):
        if self._block_signal:
            return
        freq = self._parse_freq(text)
        if freq is None or freq <= 0:
            return  # 解析失败（输入中间态），保持上一次有效值
        interval_ms = round(1000.0 / freq)
        interval_ms = max(100, min(10000, interval_ms))
        if interval_ms != self._interval_ms:
            self._interval_ms = interval_ms
            self.sampleIntervalChanged.emit(interval_ms)
