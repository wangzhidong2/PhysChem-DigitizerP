# === MODULE META ===
# icon: x
# name: 超声波位移
# category: physics
# class: UltrasonicBackend
# ===================

# -*- coding: utf-8 -*-
"""超声波位移传感器 Backend — HC-SR04 测量物体距离/位移。

固件输出格式：`timestamp_us,echo_time_us`（CSV）。
本 Backend 负责解析、采样频率控制、距离换算（cm）、统计与持久化。
"""

from backends.backend_base import BackendBase


class UltrasonicBackend(BackendBase):
    """超声波位移传感器 Backend。"""

    def __init__(self, parent=None):
        super().__init__('ultrasonic_displacement', parent=parent)
        self._start_timestamp_us = 0
        self._last_echo_us = 0

    # ---------------- 子类覆写 ----------------
    def parse_line(self, line: str):
        """解析 `timestamp,echo_time` 一行。"""
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
        display = (
            f"回波 {echo_time}µs | 距离 {distance_cm:.2f}cm | "
            f"相对时间 {relative_time_s:.3f}s"
        )
        return (relative_time_s, distance_cm, display)

    def build_csv_header(self) -> str:
        return (
            f"# PhysChem-DigitizerP 超声波位移数据导出\n"
            f"# 采样间隔 {self._sample_interval_ms}ms | 距离公式 echo_us/58\n"
            f"timestamp_s,distance_cm\n"
        )

    # ---------------- 重置起始时间戳 ----------------
    def startCollecting(self):
        # 复用父类的开始采集逻辑，但要重置起始时间戳
        self._start_timestamp_us = 0
        self._last_echo_us = 0
        super().startCollecting()
