# -*- coding: utf-8 -*-
"""backends/backend_base.py — 传感器 Backend 基类

BackendBase 封装各传感器共享的通用逻辑，供 QML 通过 contextProperty 调用：
- 串口枚举 / 连接 / 断开
- 数据采集（开始/停止）
- 时间序列缓冲与统计
- CSV 保存
- 日志输出

子类需实现：
    - parse_line(line: str) -> tuple[float|None, float|None, str|None]
        解析一行串口数据，返回 (timestamp, value, display_text)。
        任一为 None 表示该字段不更新。
    - build_csv_header() -> str
        返回保存文件时的头部注释行（含校准参数等）。
    - build_csv_row() -> str
        返回最新一条数据的 CSV 行。

通用属性（QML 只读 Property）：
    - portNames: list[str]
    - connected: bool
    - collecting: bool
    - currentValue: str
    - statsText: str
    - logText: str
    - sampleRateHz: int

通用 Slot（QML 调用）：
    - refreshPorts()
    - connectPort(port: str)
    - disconnectPort()
    - startCollecting()
    - stopCollecting()
    - saveData(filePath: str)
    - clearData()
    - setSampleIntervalMs(ms: int)
"""

import os
from datetime import datetime

from PySide6.QtCore import QObject, Signal, Slot, Property, QTimer

from core import (
    SerialThread,
    list_serial_ports,
    load_sensor_config,
    save_sensor_config,
)


class BackendBase(QObject):
    """传感器 Backend 抽象基类。"""

    # === QML 可监听的信号 ===
    portsChanged = Signal()
    connectedChanged = Signal()
    collectingChanged = Signal()
    currentValueUpdated = Signal(str)
    statsUpdated = Signal(str)
    logAppended = Signal(str)
    chartUpdated = Signal()
    errorOccurred = Signal(str)

    def __init__(self, module_name: str, parent=None):
        super().__init__(parent)
        self._module_name = module_name

        # 串口
        self._ports: list[str] = []
        self._serial_thread: SerialThread | None = None

        # 状态
        self._connected = False
        self._collecting = False
        self._current_value = "等待连接..."
        self._stats_text = "暂无数据"
        self._log_text = ""

        # 数据缓冲
        self._time_data: list[float] = []
        self._value_data: list[float] = []
        self._sample_interval_ms = 100  # 默认 10Hz
        self._last_sample_ms = 0

        # 配置
        self._config = load_sensor_config(module_name)
        self._apply_loaded_config()

        # 图表刷新定时器
        self._chart_timer = QTimer(self)
        self._chart_timer.timeout.connect(self._on_chart_tick)
        self._chart_timer.start(100)

    # ---------------- 子类应覆写 ----------------
    def parse_line(self, line: str):
        """子类覆写：解析一行数据，返回 (timestamp, value, display_text)。

        返回 (None, None, None) 表示忽略该行。
        """
        raise NotImplementedError

    def build_csv_header(self) -> str:
        """子类覆写：CSV 文件头部注释。"""
        return f"# PhysChem-DigitizerP {self._module_name} 导出\n"

    def build_csv_row(self) -> str:
        """子类覆写：最新一条数据的 CSV 行。默认 timestamp,value。"""
        if not self._time_data:
            return ""
        return f"{self._time_data[-1]},{self._value_data[-1]}\n"

    def _apply_loaded_config(self):
        """子类覆写：从 self._config 应用配置到内部状态。"""
        pass

    def _collect_config_dict(self) -> dict:
        """子类覆写：收集当前配置，返回 dict 用于持久化。"""
        return {}

    # ---------------- 串口枚举/连接 ----------------
    @Slot()
    def refreshPorts(self):
        ports = [p[0] for p in list_serial_ports()]
        if ports != self._ports:
            self._ports = ports
            self.portsChanged.emit()

    def _set_connected(self, value: bool):
        if self._connected != value:
            self._connected = value
            self.connectedChanged.emit()

    def _set_collecting(self, value: bool):
        if self._collecting != value:
            self._collecting = value
            self.collectingChanged.emit()

    @Slot(str)
    def connectPort(self, port: str):
        if not port:
            self.errorOccurred.emit("请选择串口")
            return
        if self._serial_thread and self._serial_thread.isRunning():
            return
        self._serial_thread = SerialThread(port)
        self._serial_thread.data_received.connect(self._on_data_received)
        self._serial_thread.start()
        self._set_connected(True)
        self._append_log(f"已连接 {port}")

    @Slot()
    def disconnectPort(self):
        if self._serial_thread:
            self._serial_thread.data_received.disconnect(self._on_data_received)
            self._serial_thread.stop()
            self._serial_thread.wait()
            self._serial_thread = None
        self._set_connected(False)
        self._set_collecting(False)
        self._append_log("已断开")

    # ---------------- 采集控制 ----------------
    @Slot()
    def startCollecting(self):
        if not self._connected:
            self.errorOccurred.emit("请先连接串口")
            return
        self._time_data.clear()
        self._value_data.clear()
        self._last_sample_ms = 0
        self._set_collecting(True)
        self._set_current_value("采集进行中...")
        self._append_log("开始采集")

    @Slot()
    def stopCollecting(self):
        self._set_collecting(False)
        self._set_current_value("采集已停止")
        self._append_log("停止采集")

    @Slot(str)
    def saveData(self, file_path: str):
        if not file_path:
            return
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(self.build_csv_header())
                for t, v in zip(self._time_data, self._value_data):
                    f.write(f"{t},{v}\n")
            self._append_log(f"已保存 {len(self._time_data)} 条数据到 {file_path}")
        except Exception as e:
            self.errorOccurred.emit(f"保存失败: {e}")

    @Slot()
    def clearData(self):
        self._time_data.clear()
        self._value_data.clear()
        self._set_current_value("已清空")
        self._stats_text = "暂无数据"
        self.statsUpdated.emit(self._stats_text)
        self.chartUpdated.emit()
        self._append_log("数据已清空")

    @Slot(int)
    def setSampleIntervalMs(self, ms: int):
        self._sample_interval_ms = max(50, int(ms))

    # ---------------- 配置持久化 ----------------
    @Slot()
    def saveConfig(self):
        cfg = self._collect_config_dict()
        cfg['sample_interval_ms'] = self._sample_interval_ms
        save_sensor_config(self._module_name, cfg)

    # ---------------- 数据接收 ----------------
    def _on_data_received(self, line: str):
        if line.startswith("ERROR:"):
            self.errorOccurred.emit(line[6:])
            self.disconnectPort()
            return
        if line == "START":
            self._append_log("设备已启动")
            return

        ts, val, display = self.parse_line(line)
        if display is not None:
            self._set_current_value(display)
        if ts is not None and val is not None and self._collecting:
            # 采样频率控制：按时间戳过滤
            if self._last_sample_ms == 0 or (ts - self._last_sample_ms) >= self._sample_interval_ms:
                self._time_data.append(ts)
                self._value_data.append(val)
                self._last_sample_ms = ts
                self._update_stats()

    def _set_current_value(self, text: str):
        self._current_value = text
        self.currentValueUpdated.emit(text)

    def _update_stats(self):
        if not self._value_data:
            return
        vals = self._value_data
        self._stats_text = (
            f"点数 {len(vals)}  |  "
            f"最新 {vals[-1]:.4g}  |  "
            f"最大 {max(vals):.4g}  |  "
            f"最小 {min(vals):.4g}  |  "
            f"平均 {sum(vals)/len(vals):.4g}"
        )
        self.statsUpdated.emit(self._stats_text)

    def _append_log(self, text: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {text}"
        self._log_text = line + "\n" + self._log_text
        if len(self._log_text) > 8000:
            self._log_text = self._log_text[:8000]
        self.logAppended.emit(line)

    def _on_chart_tick(self):
        if self._collecting or self._value_data:
            self.chartUpdated.emit()

    # ---------------- QML 只读 Property ----------------
    def _ports_getter(self):
        return self._ports

    ports = Property(list, _ports_getter, notify=portsChanged)

    def _connected_getter(self):
        return self._connected

    connected = Property(bool, _connected_getter, notify=connectedChanged)

    def _collecting_getter(self):
        return self._collecting

    collecting = Property(bool, _collecting_getter, notify=collectingChanged)

    def _current_value_getter(self):
        return self._current_value

    currentValue = Property(str, _current_value_getter, notify=currentValueUpdated)

    def _stats_getter(self):
        return self._stats_text

    statsText = Property(str, _stats_getter, notify=statsUpdated)

    def _log_getter(self):
        return self._log_text

    logText = Property(str, _log_getter, notify=logAppended)

    def _sample_rate_getter(self):
        return 1000 // self._sample_interval_ms if self._sample_interval_ms else 0

    sampleRateHz = Property(int, _sample_rate_getter, constant=True)

    # ---------------- 给 QML 用的数据快照 ----------------
    @Slot(result=list)
    def timeData(self):
        return self._time_data

    @Slot(result=list)
    def valueData(self):
        return self._value_data

    # ---------------- 资源清理 ----------------
    def cleanup(self):
        if self._serial_thread:
            try:
                self._serial_thread.stop()
                self._serial_thread.wait()
            except Exception:
                pass
            self._serial_thread = None
        self._chart_timer.stop()
