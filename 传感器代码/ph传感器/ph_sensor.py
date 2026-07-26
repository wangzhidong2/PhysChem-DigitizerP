# === MODULE META ===
# icon: pH
# name: pH传感器
# category: chemistry
# class: PhSensorBackend
# ===================

# -*- coding: utf-8 -*-
"""pH 传感器 Backend — SEN0161 测量溶液酸碱度。

固件输出格式：`timestamp_ms,adc_raw`（CSV）。
本 Backend 负责解析、采样频率控制、ADC→pH 换算（单点/两点/三点校准）、统计与持久化。
"""

import numpy as np
from PySide6.QtCore import Signal, Slot, Property

from backends.backend_base import BackendBase


class PhSensorBackend(BackendBase):
    """pH 传感器 Backend，支持单点/两点/三点校准。"""

    # QML 监听此信号以刷新校准相关 UI
    calibrationChanged = Signal()

    # 各模式的默认校准点（标准缓冲液 pH → ADC）
    _DEFAULT_POINTS_BY_MODE = {
        1: [(7.00, 2281)],
        2: [(4.00, 2555), (9.18, 2030)],
        3: [(4.00, 2555), (6.86, 2281), (9.18, 2030)],
    }

    def __init__(self, parent=None):
        # _apply_loaded_config 在 super().__init__ 内被调用，
        # 负责初始化 _calibration_mode / _calibration_points / _cal_coeffs
        super().__init__('ph_sensor', parent=parent)
        # 非配置状态
        self._last_ph = 7.0
        self._last_adc = 0
        self._start_timestamp_ms = 0

    # ---------------- 子类覆写 ----------------
    def _apply_loaded_config(self):
        """从 self._config 应用校准配置到内部状态。"""
        default_points = self._DEFAULT_POINTS_BY_MODE[3]
        pts = self._config.get('calibration_points', default_points)
        # 归一化为 [[ph, adc], ...]；保留 3 项以便 QML 按 index 读取任意点
        self._calibration_points = [[float(p[0]), float(p[1])] for p in pts]
        while len(self._calibration_points) < 3:
            self._calibration_points.append([4.0, 2555])
        mode = self._config.get('calibration_mode', 3)
        self._calibration_mode = max(1, min(3, int(mode)))
        self._recalc_coefficients()

    def _collect_config_dict(self):
        """收集当前配置，返回 dict 用于持久化。"""
        return {
            'calibration_points': self._calibration_points,
            'calibration_mode': self._calibration_mode,
        }

    def parse_line(self, line: str):
        """解析 `timestamp_ms,adc_raw` 一行。

        返回 (relative_time_s, ph_value, display_text)，
        任一不需要更新时为 None。
        """
        if ',' not in line:
            return (None, None, None)
        parts = line.split(',')
        if len(parts) != 2:
            return (None, None, None)
        try:
            timestamp_ms = int(parts[0])
            adc_value = int(parts[1])
        except ValueError:
            return (None, None, None)

        # ESP32 12 位 ADC 范围 0-4095
        if adc_value < 0 or adc_value > 4095:
            return (None, None, None)

        # 第一个点记录起始时间戳
        if self._start_timestamp_ms == 0:
            self._start_timestamp_ms = timestamp_ms

        relative_time_s = (timestamp_ms - self._start_timestamp_ms) / 1000.0
        ph_value = self._adc_to_ph(adc_value)
        self._last_adc = adc_value
        self._last_ph = ph_value

        display = (
            f"ADC {adc_value} | pH {ph_value:.2f} | "
            f"t {relative_time_s:.3f}s"
        )
        return (relative_time_s, ph_value, display)

    def build_csv_header(self) -> str:
        """返回包含校准信息的 CSV 头。"""
        mode_names = {1: "单点", 2: "两点", 3: "三点"}
        mode_name = mode_names.get(self._calibration_mode, f"{self._calibration_mode}点")
        lines = [
            "# PhysChem-DigitizerP pH 传感器数据导出",
            f"# 采样间隔 {self._sample_interval_ms}ms | 校准模式: {mode_name}",
            "# 校准点 (pH -> ADC):",
        ]
        for i, p in enumerate(self._calibration_points[:self._calibration_mode]):
            lines.append(f"#   [{i+1}] pH {p[0]:.2f} -> ADC {int(p[1])}")
        lines.append("timestamp_s,ph_value")
        return "\n".join(lines) + "\n"

    # ---------------- 校准计算 ----------------
    def _recalc_coefficients(self):
        """根据当前 mode 与 points 重新计算拟合系数。

        - 1 点：使用 Nernst 理论斜率 -0.59 pH/V + 偏移
        - 2 点：线性拟合 pH = k*ADC + b
        - 3 点：二次拟合 pH = a*ADC^2 + b*ADC + c
        """
        pts = self._calibration_points[:self._calibration_mode]
        ph_values = [float(p[0]) for p in pts]
        adc_values = [float(p[1]) for p in pts]
        n = len(pts)
        if n == 1:
            ph0, adc0 = pts[0]
            slope = -0.59
            intercept = ph0 - slope * adc0
            self._cal_coeffs = (0.0, slope, intercept)
        elif n == 2:
            coeffs = np.polyfit(adc_values, ph_values, 1)
            self._cal_coeffs = (0.0, float(coeffs[0]), float(coeffs[1]))
        else:  # n >= 3
            coeffs = np.polyfit(adc_values, ph_values, 2)
            self._cal_coeffs = (float(coeffs[0]), float(coeffs[1]), float(coeffs[2]))

    def _adc_to_ph(self, adc_value: float) -> float:
        a, b, c = self._cal_coeffs
        ph = a * adc_value * adc_value + b * adc_value + c
        return max(0.0, min(14.0, ph))

    # ---------------- 采集开始时重置起始时间戳 ----------------
    def startCollecting(self):
        self._start_timestamp_ms = 0
        self._last_adc = 0
        self._last_ph = 7.0
        super().startCollecting()

    # ---------------- QML Slot ----------------
    @Slot(int)
    def setCalibrationMode(self, mode: int):
        """设置校准模式（1/2/3），并重置校准点为该模式默认值。"""
        if mode not in (1, 2, 3):
            return
        self._calibration_mode = mode
        defaults = self._DEFAULT_POINTS_BY_MODE[mode]
        self._calibration_points = [[float(p[0]), float(p[1])] for p in defaults]
        # 保持 3 项长度以便 QML 按 index 读取任意点
        while len(self._calibration_points) < 3:
            self._calibration_points.append([4.0, 2555])
        self._recalc_coefficients()
        self.calibrationChanged.emit()

    @Slot(int, float, float)
    def setCalibrationPoint(self, index: int, ph: float, adc: float):
        """更新指定索引（0-indexed）的校准点。"""
        if not (0 <= index < len(self._calibration_points)):
            return
        self._calibration_points[index] = [float(ph), float(adc)]
        self._recalc_coefficients()
        self.calibrationChanged.emit()

    @Slot(result=int)
    def getCalibrationMode(self):
        return self._calibration_mode

    @Slot(int, result=list)
    def getCalibrationPoint(self, index: int):
        """返回 [ph, adc]，index 越界时返回空列表。"""
        if not (0 <= index < len(self._calibration_points)):
            return []
        p = self._calibration_points[index]
        return [float(p[0]), float(p[1])]

    @Slot()
    def saveCalibration(self):
        """保存校准配置到磁盘。"""
        self.saveConfig()

    # ---------------- QML Property ----------------
    def _calibration_mode_getter(self):
        return self._calibration_mode

    calibrationMode = Property(int, _calibration_mode_getter, notify=calibrationChanged)
