# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

# -*- coding: utf-8 -*-
"""超声波位移内核 — 纯 Python，不依赖 Qt。

View（ultrasonic_displacement.py）只负责控件；本文件负责：
- 通道配置与持久化
- 串口 / 模拟器传输
- 回波解析、量程过滤、距离换算
- 采样节流、数据缓存、快照、CSV 导出
"""

from core import (
    MultiChannelKernel, ChannelBase, load_sensor_config, save_sensor_config,
    get_logger, CHANNEL_COLORS,
)

log = get_logger('ultrasonic_displacement_kernel')

CONFIG_KEY = 'ultrasonic_displacement'

# 多路连接的默认曲线配色（按新建顺序轮换取未用色，界面上可单独改色）
CHANNEL_COLORS = CHANNEL_COLORS

# 固件有效回波窗口（µs）
ECHO_MIN_US = 100
ECHO_MAX_US = 60000
# 回波时间 → 厘米的换算常数（声速约 340 m/s 的往返换算）
US_PER_CM = 58.0


class DisplacementChannel(ChannelBase):
    """一路超声波位移连接的数据模型（不持有任何 Qt 控件）。"""

    def __init__(self, cid, name, color, mode='serial', port='',
                 sample_interval_ms=100, visible=True):
        super().__init__(cid, name, color, mode=mode, port=port,
                         sample_interval_ms=sample_interval_ms,
                         visible=visible)

        self.data_points = []
        self.echo_data = []
        # 基类 channel_info / clear 使用这两个名字；保持别名，避免 View 改字段
        self.raw_data = self.echo_data
        self.value_data = self.data_points


class DisplacementKernel(MultiChannelKernel):
    """超声波位移内核。"""

    def create_channel(self, cid, name, color, mode, port,
                       sample_interval_ms, visible, params):
        return DisplacementChannel(
            cid, name, color, mode=mode, port=port,
            sample_interval_ms=sample_interval_ms, visible=visible)

    def after_restore_channels(self):
        self.mirror_first_channel('sample_interval_ms')

    def csv_header(self):
        return ['channel', 'timestamp_s', 'echo_us', 'distance_cm']

    def csv_row_values(self, ch, i):
        t = ch.time_data[i] if i < len(ch.time_data) else 0.0
        echo = ch.echo_data[i] if i < len(ch.echo_data) else 0
        dist = ch.data_points[i] if i < len(ch.data_points) else 0.0
        return [ch.name, f'{t:.3f}', echo, f'{dist:.3f}']

    key = CONFIG_KEY
    title = '超声波位移'
    x_label = '时间 (秒)'
    y_label = '距离 (厘米)'

    def __init__(self):
        super().__init__()
        self.config = self.load_config()
        self._restore_channels()

    # ---------------- 配置 ----------------
    def load_config(self):
        config = load_sensor_config(CONFIG_KEY)
        if config:
            self.sample_interval_ms = config.get('sample_interval_ms', 100)
        return config

    def save_config(self):
        return save_sensor_config(CONFIG_KEY, self.base_config())


    # ---------------- 通道 ----------------

    # ---------------- 物理 ----------------
    def simulator_spec(self, channel):
        return {
            'value_min': ECHO_MIN_US,
            'value_max': ECHO_MAX_US,
            'interval_ms': channel.sample_interval_ms,
            'start_value': 11600,
            'timestamp_scale': 1000,
        }

    def decode_line(self, line, channel):
        if ',' not in line:
            return None
        parts = line.split(',')
        if len(parts) != 2:
            return None
        try:
            echo_time = int(parts[1])
        except ValueError:
            return None
        if echo_time < ECHO_MIN_US or echo_time > ECHO_MAX_US:
            return None
        return float(echo_time)

    def convert(self, channel, raw):
        return raw / US_PER_CM

    # ---------------- 数据 ----------------
    def append_sample(self, channel, t, raw, value):
        channel.time_data.append(t)
        channel.data_points.append(value)
        channel.echo_data.append(int(raw))

    def clear_channel_data(self, channel):
        channel.time_data.clear()
        channel.data_points.clear()
        channel.echo_data.clear()
        channel.last_sample_s = None

    def channel_values(self, channel):
        return channel.data_points

    def channel_info(self, channel):
        info = super().channel_info(channel)
        info['latest_raw'] = channel.echo_data[-1] if channel.echo_data else None
        return info

    # ---------------- 快照 / 导出 ----------------
    def ai_data(self):
        active = [ch for ch in self.channels if ch.data_points]
        if not active:
            return None
        main = max(active, key=lambda c: len(c.data_points))
        channels_desc = '、'.join(
            f'{ch.name}[{len(ch.data_points)}点]' for ch in active)
        return {
            'title': self.title,
            'x_label': self.x_label,
            'y_label': self.y_label,
            'points': list(zip(main.time_data, main.data_points)),
            'params': (
                f'传感器=HC-SR04 超声波, 距离换算=回波时间(µs)/58, '
                f'声速假设=340m/s（温度每变化 1℃ 约 ±0.17%）, '
                f'固件有效回波窗口=100~60000µs（约 2~100cm）, '
                f'最小触发间隔=20ms, '
                f'多路连接: 共{len(active)}路（{channels_desc}），'
                f'主分析通道={main.name}, '
                f'时间轴=主机统一时间戳（各路对齐）, '
                f'采样间隔={main.sample_interval_ms}ms（各路独立）'),
        }


    def sensor_actions(self):
        return []
