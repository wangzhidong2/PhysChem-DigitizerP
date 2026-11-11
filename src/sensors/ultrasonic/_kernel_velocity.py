# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

# -*- coding: utf-8 -*-
"""超声波速度内核 — 纯 Python，不依赖 Qt。

View（ultrasonic_velocity.py）只负责控件；本文件负责：
- 通道配置与持久化（含模块级共享的 window_size）
- 串口 / 模拟器传输
- 回波解析、距离换算、相邻两笔回波差分求速度
- 采样节流、数据缓存、快照、CSV 导出
"""

from core import (
    SensorKernel, load_sensor_config, save_sensor_config,
    SERIAL_AVAILABLE, EVENT_SAMPLE_RECORDED, EVENT_CHANNELS_CHANGED,
    get_logger,
)

log = get_logger('ultrasonic_velocity_kernel')

CONFIG_KEY = 'ultrasonic_velocity'

# 多路连接的默认曲线配色（按新建顺序轮换取未用色，界面上可单独改色）
CHANNEL_COLORS = ('#0078d4', '#e74c3c', '#2ecc71', '#f39c12',
                  '#9b59b6', '#00bcd5', '#e67e22', '#16a085')

# 固件有效回波窗口（µs）
ECHO_MIN_US = 100
ECHO_MAX_US = 60000
# 回波时间 → 厘米的换算常数（声速约 340 m/s 的往返换算）
US_PER_CM = 58.0
# 差分速度公式使用的声速（cm/s）
SOUND_SPEED_CM_S = 34000.0
# 缺少相邻时间戳时的默认发射间隔（s，固件 MIN_INTERVAL = 20ms）
DEFAULT_DELTA_T_S = 0.02


class VelocityChannel:
    """一路超声波速度连接的数据模型（不持有任何 Qt 控件）。"""

    def __init__(self, cid, name, color, mode='serial', port='',
                 sample_interval_ms=100, visible=True):
        self.id = cid
        self.name = name
        self.default_name = name
        self.color = color
        self.mode = mode
        self.port = port
        self.thread = None
        self.connected = False
        self.sample_interval_ms = sample_interval_ms
        self.visible = bool(visible)

        self.time_data = []
        self.distance_data = []
        self.echo_time_data = []
        # 速度（cm/s，差分得到，比距离少 1 点）
        self.velocity_data = []
        # 基类 channel_info / series 使用这两个名字；保持别名
        self.raw_data = self.echo_time_data
        self.value_data = self.velocity_data
        self.last_sample_s = None
        self.last_velocity = None


class VelocityKernel(SensorKernel):
    """超声波速度内核。"""

    key = CONFIG_KEY
    title = '超声波速度'
    x_label = '时间 (秒)'
    y_label = '速度 (cm/s)'

    def __init__(self):
        super().__init__()
        # 采样窗口（点数，全部通道共用）
        self.window_size = 10
        self.config = self.load_config()
        self._restore_channels()

    # ---------------- 配置 ----------------
    def load_config(self):
        config = load_sensor_config(CONFIG_KEY)
        if config:
            self.sample_interval_ms = config.get('sample_interval_ms', 100)
            self.window_size = config.get('window_size', 10)
        return config

    def save_config(self):
        first = self.channels[0] if self.channels else None
        config = {
            'sample_interval_ms': (
                first.sample_interval_ms if first else self.sample_interval_ms),
            'window_size': self.window_size,
            'channels': [
                {'name': ch.name, 'mode': ch.mode, 'port': ch.port,
                 'color': ch.color,
                 'sample_interval_ms': ch.sample_interval_ms,
                 'visible': ch.visible}
                for ch in self.channels
            ],
        }
        return save_sensor_config(CONFIG_KEY, config)

    def _restore_channels(self):
        saved = (self.config or {}).get('channels') or []
        if saved:
            for item in saved:
                mode = item.get('mode', 'serial')
                if mode != 'simulator' and not SERIAL_AVAILABLE:
                    mode = 'simulator'
                self.channels.append(self.make_channel(
                    name=item.get('name') or None,
                    color=item.get('color') or None,
                    mode=mode,
                    port=item.get('port', ''),
                    sample_interval_ms=item.get('sample_interval_ms'),
                    visible=item.get('visible', True)))
        else:
            mode = 'serial' if SERIAL_AVAILABLE else 'simulator'
            self.channels.append(self.make_channel(mode=mode))
        if self.channels:
            self.sample_interval_ms = self.channels[0].sample_interval_ms

    # ---------------- 通道 ----------------
    def make_channel(self, color=None, mode='serial', port='', name=None,
                     sample_interval_ms=None, visible=True, **params):
        cid = self._next_channel_id
        self._next_channel_id += 1
        seq = self._next_channel_seq
        self._next_channel_seq += 1
        if not color:
            used = {ch.color for ch in self.channels}
            color = next((c for c in CHANNEL_COLORS if c not in used),
                         CHANNEL_COLORS[(seq - 1) % len(CHANNEL_COLORS)])
        return VelocityChannel(
            cid, name or f'通道{seq}', color,
            mode=mode, port=port,
            sample_interval_ms=sample_interval_ms or self.sample_interval_ms,
            visible=visible)

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

    def calculate_velocity(self, channel):
        """回声定位法计算速度 — 基于该路两次测量的时间差。

        v = (t₀ - t₁)/2 × vₛ / [(t₁ + t₀)/2 + Δt]

        其中 t₀/t₁ 为相邻两次回波时间（µs），Δt 为两次发射间隔（s），
        vₛ = 34000 cm/s。返回 None 表示点数不足或无法计算。
        """
        if len(channel.distance_data) < 2:
            return None
        try:
            t0 = channel.echo_time_data[-2]
            t1 = channel.echo_time_data[-1]

            delta_t = DEFAULT_DELTA_T_S
            if len(channel.time_data) >= 2:
                delta_t = channel.time_data[-1] - channel.time_data[-2]

            numerator = (t0 - t1) / 2.0 * SOUND_SPEED_CM_S
            denominator = (t1 + t0) / 2.0 + delta_t * 1000000

            if denominator == 0:
                return None
            return numerator / denominator
        except Exception as e:
            log.warning("速度计算错误（%s）: %s", channel.name, e)
            return None

    # ---------------- 数据 ----------------
    def append_sample(self, channel, t, raw, value):
        channel.time_data.append(t)
        channel.distance_data.append(value)
        channel.echo_time_data.append(int(raw))
        velocity = self.calculate_velocity(channel)
        channel.last_velocity = velocity
        if velocity is not None:
            channel.velocity_data.append(velocity)

    def clear_channel_data(self, channel):
        channel.time_data.clear()
        channel.distance_data.clear()
        channel.echo_time_data.clear()
        channel.velocity_data.clear()
        channel.last_sample_s = None
        channel.last_velocity = None

    def channel_values(self, channel):
        return channel.velocity_data

    def _publish(self, kind, channel_id=None, data=None):
        """记录样本事件补上差分速度：基类在 append_sample 之后立即发布，
        同一通道单线程处理，故 last_velocity 必对应当前样本。"""
        if kind == EVENT_SAMPLE_RECORDED and channel_id is not None:
            ch = self.get_channel(channel_id)
            if ch is not None:
                data = dict(data or {})
                data['velocity'] = getattr(ch, 'last_velocity', None)
        super()._publish(kind, channel_id, data)

    # ---------------- 快照 / 导出 ----------------
    def ai_data(self):
        active = [ch for ch in self.channels if ch.velocity_data]
        if not active:
            return None
        main = max(active, key=lambda c: len(c.velocity_data))
        channels_desc = '、'.join(
            f'{ch.name}[{len(ch.velocity_data)}点]' for ch in active)
        return {
            'title': self.title,
            'x_label': self.x_label,
            'y_label': self.y_label,
            'points': list(zip(
                main.time_data[len(main.time_data) - len(main.velocity_data):],
                main.velocity_data)),
            'params': (
                f'传感器=HC-SR04 超声波, 速度=相邻两次回波差分'
                f'（v=(t0−t1)/2 × 34000 / [(t1+t0)/2 + Δt]，'
                f'Δt 为相邻时间戳差，单位 cm/s）, '
                f'声速假设=34000cm/s, '
                f'固件有效回波窗口=100~60000µs（约 2~100cm）, '
                f'最小触发间隔=20ms, '
                f'多路连接: 共{len(active)}路（{channels_desc}），'
                f'主分析通道={main.name}, '
                f'时间轴=主机统一时间戳（各路对齐）, '
                f'采样间隔={main.sample_interval_ms}ms（各路独立）'),
        }

    def csv_text(self):
        total = sum(len(ch.distance_data) for ch in self.channels)
        if total == 0:
            return ''
        lines = ['channel,time_s,distance_cm,velocity_cm_s']
        for ch in self.channels:
            for i, (time_val, distance) in enumerate(
                    zip(ch.time_data, ch.distance_data)):
                vi = i - (len(ch.time_data) - len(ch.velocity_data))
                velocity = (ch.velocity_data[vi]
                            if 0 <= vi < len(ch.velocity_data) else None)
                velocity_str = (f'{velocity:.3f}'
                                if velocity is not None else '')
                lines.append(
                    f'{ch.name},{time_val:.3f},{distance:.3f},{velocity_str}')
        return '\n'.join(lines) + '\n'

    # ---------------- 命令 ----------------
    def set_window_size(self, value):
        try:
            self.window_size = max(1, int(value))
        except (TypeError, ValueError):
            return {'ok': False, 'message': '采样窗口无效'}
        self.save_config()
        self._publish(EVENT_CHANNELS_CHANGED)
        return {'ok': True, 'window_size': self.window_size,
                'message': f'采样窗口已设为 {self.window_size} 点'}

    def sensor_actions(self):
        return ['set_window_size']

    def sensor_command(self, action, params):
        if action == 'set_window_size':
            value = params.get('window_size', params.get('value'))
            if value is None:
                return {'ok': False, 'message': '缺少采样窗口 window_size'}
            return self.set_window_size(value)
        return None
