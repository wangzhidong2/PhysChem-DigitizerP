# === MODULE META ===
# icon: F
# name: 力传感器
# category: physics
# class: ForceSensorBackend
# ===================

# -*- coding: utf-8 -*-
"""力传感器 Backend — HX711 24bit ADC 测量质量/力。

固件输出格式：`timestamp_ms,raw_adc`（CSV）。
本 Backend 负责解析、采样频率控制、按校准系数与去皮偏移换算质量/力、
单位切换（g/kg/N）与持久化。

固件特殊消息：
- "START"                 设备启动（基类已处理）
- "TARE_DONE,offset"      去皮完成，固件返回新的零点偏移
- "CALIBRATE_READY,..."   校准准备就绪提示
"""

from PySide6.QtCore import Slot, Signal, Property

from backends.backend_base import BackendBase


class ForceSensorBackend(BackendBase):
    """力传感器（HX711）Backend。"""

    GRAVITY = 9.8
    UNIT_LABELS = {"g": "质量 (g)", "kg": "质量 (kg)", "N": "力 (N)"}

    # === 自定义信号 ===
    unitChanged = Signal()
    calibrationFactorChanged = Signal()
    tareOffsetChanged = Signal()

    def __init__(self, parent=None):
        # 内部状态需在 super().__init__ 之前初始化，
        # 因为父类构造函数会调用 _apply_loaded_config 覆写这些值。
        self._calibration_factor = 1.0
        self._tare_offset = 0
        self._unit = 'g'
        self._last_raw = 0
        self._start_timestamp_ms = 0

        super().__init__('force_sensor', parent=parent)

    # ---------------- 子类覆写 ----------------
    def _apply_loaded_config(self):
        """从 self._config 应用配置到内部状态。"""
        if not self._config:
            return
        self._calibration_factor = float(self._config.get('calibration_factor', 1.0))
        self._tare_offset = int(self._config.get('tare_offset', 0))
        unit = self._config.get('unit', 'g')
        if unit in ('g', 'kg', 'N'):
            self._unit = unit

    def _collect_config_dict(self) -> dict:
        """收集当前配置，返回 dict 用于持久化。"""
        return {
            'calibration_factor': self._calibration_factor,
            'tare_offset': self._tare_offset,
            'unit': self._unit,
        }

    def parse_line(self, line: str):
        """解析一行数据，返回 (timestamp_s, value_in_unit, display_text)。

        - "TARE_DONE,offset"        → 更新 _tare_offset，仅刷新显示
        - "CALIBRATE_READY,..."     → 仅刷新显示
        - "timestamp_ms,raw_adc"    → 主数据行
        """
        # 去皮完成消息：固件返回新的零点偏移
        if line.startswith("TARE_DONE"):
            parts = line.split(',')
            if len(parts) == 2:
                try:
                    self._tare_offset = int(parts[1])
                    self.tareOffsetChanged.emit()
                except ValueError:
                    pass
            return (None, None, f"去皮完成 | 偏移 {self._tare_offset}")

        # 校准准备就绪消息
        if line.startswith("CALIBRATE_READY"):
            return (None, None, "请放置已知质量砝码")

        # 主数据行：timestamp_ms,raw_adc
        if ',' not in line:
            return (None, None, None)
        parts = line.split(',')
        if len(parts) != 2:
            return (None, None, None)
        try:
            timestamp_ms = int(parts[0])
            raw_value = int(parts[1])
        except ValueError:
            return (None, None, None)

        self._last_raw = raw_value

        # 第一个点记录起始时间戳
        if self._start_timestamp_ms == 0:
            self._start_timestamp_ms = timestamp_ms
        relative_time_s = (timestamp_ms - self._start_timestamp_ms) / 1000.0

        # 质量(克) = (原始ADC - 去皮偏移) * 校准系数
        grams = (raw_value - self._tare_offset) * self._calibration_factor
        value_in_unit = self._convert_unit(grams)

        unit_label = self.UNIT_LABELS.get(self._unit, self._unit)
        display = (
            f"原始ADC {raw_value} | {unit_label}: {value_in_unit:.4f} | "
            f"相对时间 {relative_time_s:.3f}s"
        )
        return (relative_time_s, value_in_unit, display)

    def build_csv_header(self) -> str:
        return (
            f"# PhysChem-DigitizerP 力传感器数据导出\n"
            f"# HX711 24bit ADC | 校准系数 {self._calibration_factor} | "
            f"去皮偏移 {self._tare_offset} | 单位 {self._unit}\n"
            f"# 公式 value = (raw_adc - tare_offset) * calibration_factor\n"
            f"timestamp_s,value_{self._unit}\n"
        )

    # ---------------- 单位换算 ----------------
    def _convert_unit(self, grams: float) -> float:
        """将克值转换为当前单位值。"""
        if self._unit == "kg":
            return grams / 1000.0
        elif self._unit == "N":
            return grams / 1000.0 * self.GRAVITY
        return grams

    # ---------------- QML 调用的 Slot ----------------
    @Slot(float)
    def setCalibrationFactor(self, factor: float):
        if factor != self._calibration_factor:
            self._calibration_factor = float(factor)
            self.calibrationFactorChanged.emit()
            self._append_log(f"校准系数已设置为 {self._calibration_factor}")

    @Slot()
    def performTare(self):
        """以当前最新原始读数作为零点偏移。"""
        self._tare_offset = self._last_raw
        self.tareOffsetChanged.emit()
        self._append_log(f"去皮完成 | 偏移 {self._tare_offset}")

    @Slot(str)
    def setUnit(self, unit: str):
        if unit in ('g', 'kg', 'N') and unit != self._unit:
            self._unit = unit
            self.unitChanged.emit()
            self._append_log(f"单位已切换为 {unit}")

    # ---------------- QML 只读 Property ----------------
    def _unit_getter(self):
        return self._unit

    currentUnit = Property(str, _unit_getter, notify=unitChanged)

    def _calib_getter(self):
        return self._calibration_factor

    calibrationFactor = Property(float, _calib_getter, notify=calibrationFactorChanged)

    def _tare_getter(self):
        return self._tare_offset

    tareOffset = Property(int, _tare_getter, notify=tareOffsetChanged)

    # ---------------- 重置起始时间戳 ----------------
    def startCollecting(self):
        # 复用父类的开始采集逻辑，但要重置起始时间戳
        self._start_timestamp_ms = 0
        super().startCollecting()
