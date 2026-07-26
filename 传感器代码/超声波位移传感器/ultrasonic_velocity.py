# === MODULE META ===
# icon: v
# name: 超声波速度
# category: physics
# class: UltrasonicVelocityBackend
# ===================

# -*- coding: utf-8 -*-
"""超声波速度传感器 Backend — 基于回声定位法累积窗口计算物体速度。

固件输出格式：`timestamp_us,echo_time_us`（CSV）。
本 Backend 在采样窗口内累积最近 N 个距离点，按窗口两端计算平均速度：
    v = (d_last - d_first) / (t_last - t_first)
窗口未满时仅显示距离，不输出速度值。
"""

from PySide6.QtCore import Slot

from backends.backend_base import BackendBase


class UltrasonicVelocityBackend(BackendBase):
    """超声波速度传感器 Backend。"""

    def __init__(self, parent=None):
        super().__init__('ultrasonic_velocity', parent=parent)
        self._start_timestamp_us = 0
        self._last_echo_us = 0
        self._window_size = 10
        # 滑动窗口：[(relative_time_s, distance_cm), ...]
        self._window: list = []

    # ---------------- 子类覆写 ----------------
    def parse_line(self, line: str):
        """解析 `timestamp,echo_time` 一行，累积窗口后输出速度。"""
        if ',' not in line:
            return (None, None, None)
        parts = line.split(',')
        if len(parts) != 2:
            return (None, None, None)
        try:
            timestamp_us = int(parts[0])
            echo_time = int(parts[1])
        except ValueError:
            return (None, None, None)

        # 过滤无效回波（100µs ~ 60ms）
        if echo_time < 100 or echo_time > 60000:
            return (None, None, None)

        # 距离换算：cm = echo_us / 58
        distance_cm = echo_time / 58.0

        # 第一个点记录起始时间戳
        if self._start_timestamp_us == 0:
            self._start_timestamp_us = timestamp_us
        self._last_echo_us = echo_time

        relative_time_s = (timestamp_us - self._start_timestamp_us) / 1_000_000.0

        # 累积到滑动窗口
        self._window.append((relative_time_s, distance_cm))
        if len(self._window) > self._window_size:
            self._window.pop(0)

        # 窗口未满：仅显示距离，不输出速度
        if len(self._window) < self._window_size:
            display = (
                f"回波 {echo_time}µs | 距离 {distance_cm:.2f}cm | "
                f"窗口 {len(self._window)}/{self._window_size} | "
                f"相对时间 {relative_time_s:.3f}s"
            )
            return (relative_time_s, None, display)

        # 窗口已满：速度 = (d_last - d_first) / (t_last - t_first)
        t_first, d_first = self._window[0]
        t_last, d_last = self._window[-1]
        dt = t_last - t_first
        velocity_cm_s = (d_last - d_first) / dt if dt > 0 else None

        if velocity_cm_s is None:
            display = (
                f"回波 {echo_time}µs | 距离 {distance_cm:.2f}cm | "
                f"速度 N/A | 相对时间 {relative_time_s:.3f}s"
            )
        else:
            display = (
                f"回波 {echo_time}µs | 距离 {distance_cm:.2f}cm | "
                f"速度 {velocity_cm_s:+.2f}cm/s | "
                f"窗口 {self._window_size} | "
                f"相对时间 {relative_time_s:.3f}s"
            )
        return (relative_time_s, velocity_cm_s, display)

    def build_csv_header(self) -> str:
        return (
            f"# PhysChem-DigitizerP 超声波速度数据导出\n"
            f"# 采样间隔 {self._sample_interval_ms}ms | 采样窗口 {self._window_size} 点\n"
            f"# 速度公式 (d_last - d_first) / (t_last - t_first) 单位 cm/s\n"
            f"timestamp_s,velocity_cm_s\n"
        )

    # ---------------- 配置持久化 ----------------
    def _apply_loaded_config(self):
        ws = self._config.get('window_size')
        if isinstance(ws, int) and 5 <= ws <= 100:
            self._window_size = ws

    def _collect_config_dict(self) -> dict:
        return {'window_size': self._window_size}

    # ---------------- QML 调用 ----------------
    @Slot(int)
    def setWindowSize(self, size: int):
        size = max(5, min(100, int(size)))
        if size != self._window_size:
            self._window_size = size
            # 窗口缩小后裁剪
            while len(self._window) > self._window_size:
                self._window.pop(0)

    # ---------------- 重置起始时间戳与窗口 ----------------
    def startCollecting(self):
        self._start_timestamp_us = 0
        self._last_echo_us = 0
        self._window.clear()
        super().startCollecting()
