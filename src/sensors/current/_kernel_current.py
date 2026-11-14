# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

# -*- coding: utf-8 -*-
"""ACS712 电流传感器内核 — 纯 Python，不依赖 Qt。

View（current_sensor.py）只负责控件；本文件负责：
- 通道配置与持久化
- 串口 / 模拟器传输
- ADC 解析、分压还原、电流换算、AC RMS
- 零点校准（去皮）与已采数据重算
- 采样节流、数据缓存、快照、CSV 导出
"""


import numpy as np

from core import (
    MultiChannelKernel, ChannelBase, load_sensor_config, save_sensor_config,
    EVENT_CHANNELS_CHANGED, get_logger, CHANNEL_COLORS,
)

log = get_logger('current_sensor_kernel')

CONFIG_KEY = 'current_sensor'

# 多路连接的默认曲线配色（按新建顺序轮换取未用色，界面上可单独改色）
CHANNEL_COLORS = CHANNEL_COLORS

# ADC 位数 → 满量程计数值
ADC_BITS_OPTIONS = {8: 256, 10: 1024, 12: 4096, 14: 16384, 16: 65536}
# ESP32 ADC 参考电压
VREF = 3.3

# ACS712 量程参数：灵敏度（V/A）、标称量程（A）、说明
ACS712_RANGES = {
    '5A':  {'sensitivity': 0.185, 'range_a': 5,  'desc': 'ACS712ELC-05B  ±5A  185mV/A'},
    '20A': {'sensitivity': 0.100, 'range_a': 20, 'desc': 'ACS712ELC-20A  ±20A  100mV/A'},
    '30A': {'sensitivity': 0.066, 'range_a': 30, 'desc': 'ACS712ELC-30A  ±30A  66mV/A'},
}

# 内部 current_data 始终存安培，显示时按当前单位换算
UNIT_FACTORS = {'A': 1.0, 'mA': 1000.0}


class CurrentChannel(ChannelBase):
    """一路 ACS712 连接的数据模型（不持有任何 Qt 控件）。"""

    def __init__(self, cid, name, color, mode='serial', port='',
                 sample_interval_ms=100, visible=True, acs_params=None):
        super().__init__(cid, name, color, mode=mode, port=port,
                         sample_interval_ms=sample_interval_ms,
                         visible=visible)

        # 本路 ACS712 换算参数（每路独立；缺省继承模块级/全局默认）
        p = acs_params or {}
        self.acs_range = p.get('acs_range', '5A')
        self.vcc = p.get('vcc', 5.0)
        self.v_quiescent = p.get('v_quiescent', 2.5)
        self.divider_ratio = p.get('divider_ratio', 1.515)
        self.adc_bits = p.get('adc_bits', 12)
        self.zero_cal_active = p.get('zero_cal_active', False)

        # 采集数据（内部电流单位：安培）
        self.vsensor_data = []
        self.current_data = []


class CurrentKernel(MultiChannelKernel):
    """ACS712 电流传感器内核。"""

    CHANNEL_EXTRA_FIELDS = (
        'acs_range', 'vcc', 'v_quiescent', 'divider_ratio',
        'adc_bits', 'zero_cal_active',
    )

    def create_channel(self, cid, name, color, mode, port,
                       sample_interval_ms, visible, params):
        acs_params = dict(params.get('acs_params') or {})
        for f in self.CHANNEL_EXTRA_FIELDS:
            if f in params:
                acs_params[f] = params[f]
        if not acs_params:
            acs_params = self.adc_param_source(
                self.channels[0] if self.channels else None)
        return CurrentChannel(cid, name, color, mode=mode, port=port,
                              sample_interval_ms=sample_interval_ms,
                              visible=visible, acs_params=acs_params)

    def channel_restore_params(self, item):
        return {'acs_params': {**self.adc_param_source(), **item}}

    def after_restore_channels(self):
        self.mirror_first_channel(
            'acs_range', 'vcc', 'v_quiescent', 'divider_ratio',
            'adc_bits', 'zero_cal_active', 'sample_interval_ms')

    def csv_comments(self):
        lines = [
            f"# ACS712 模式={self.current_mode} 单位={self.current_unit} "
            f"AC RMS窗口={self.ac_rms_window}点",
        ]
        for ch in self.channels:
            src = self.adc_param_source(ch)
            lines.append(
                f"# {ch.name}: 量程={ch.acs_range} "
                f"灵敏度={self.sensitivity_of(src)}V/A "
                f"零点={ch.v_quiescent:.4f}V 分压比={ch.divider_ratio}")
        return lines

    def csv_header(self):
        return ['channel', 'timestamp_s', 'raw_adc', 'v_adc', 'v_sensor',
                f'current_{self.current_unit.lower()}']

    def csv_row_values(self, ch, i):
        t = ch.time_data[i] if i < len(ch.time_data) else 0.0
        raw = ch.raw_data[i] if i < len(ch.raw_data) else 0
        current = ch.current_data[i] if i < len(ch.current_data) else 0.0
        return [ch.name, f'{t:.3f}', raw,
                f'{self.adc_to_vadc(raw, channel=ch):.6f}',
                f'{self.adc_to_vsensor(raw, channel=ch):.6f}',
                f'{self.to_current_unit(current):.6f}']

    key = CONFIG_KEY
    title = '电流传感器'
    x_label = '时间 (秒)'
    y_label = '电流 (A)'

    ADC_BITS_OPTIONS = ADC_BITS_OPTIONS
    VREF = VREF
    ACS712_RANGES = ACS712_RANGES
    UNIT_FACTORS = UNIT_FACTORS

    def __init__(self):
        super().__init__()
        # 模块级共享设置（对全部通道生效）
        self.current_mode = 'DC'
        self.current_unit = 'A'
        self.ac_rms_window = 50
        # 模块级 ACS 默认值（旧版单通道顶层配置兼容）
        self.acs_range = '5A'
        self.vcc = 5.0
        self.v_quiescent = 2.5
        self.divider_ratio = 1.515
        self.adc_bits = 12
        self.zero_cal_active = False

        self.config = self.load_config()
        self._restore_channels()

    # ---------------- 配置 ----------------
    def load_config(self):
        config = load_sensor_config(CONFIG_KEY)
        if config:
            self.acs_range = config.get('acs_range', '5A')
            self.vcc = config.get('vcc', 5.0)
            self.v_quiescent = config.get('v_quiescent', self.vcc / 2.0)
            self.divider_ratio = config.get('divider_ratio', 1.515)
            self.adc_bits = config.get('adc_bits', 12)
            self.zero_cal_active = config.get('zero_cal_active', False)
            self.current_mode = config.get('current_mode', 'DC')
            self.current_unit = config.get('current_unit', 'A')
            self.sample_interval_ms = config.get('sample_interval_ms', 100)
            self.ac_rms_window = config.get('ac_rms_window', 50)
        return config

    def save_config(self):
        first = self.channels[0] if self.channels else None
        config = {
            # 兼容旧版单通道上位机：顶层换算/采样/校准字段取第 1 路的值
            'acs_range': first.acs_range if first else self.acs_range,
            'vcc': first.vcc if first else self.vcc,
            'v_quiescent': first.v_quiescent if first else self.v_quiescent,
            'divider_ratio': first.divider_ratio if first else self.divider_ratio,
            'adc_bits': first.adc_bits if first else self.adc_bits,
            'zero_cal_active': first.zero_cal_active if first else self.zero_cal_active,
            'current_mode': self.current_mode,
            'current_unit': self.current_unit,
            'sample_interval_ms': first.sample_interval_ms if first else self.sample_interval_ms,
            'ac_rms_window': self.ac_rms_window,
        }
        return save_sensor_config(CONFIG_KEY, self.base_config(config))


    # ---------------- 通道 ----------------

    # ---------------- 参数来源 / 换算 ----------------
    def adc_param_source(self, channel=None):
        """取一路 ACS712 换算参数字典：显式通道 > 第 1 路 > 模块级默认。"""
        ch = channel
        if ch is None and self.channels:
            ch = self.channels[0]
        if ch is not None:
            return {'acs_range': ch.acs_range, 'vcc': ch.vcc,
                    'v_quiescent': ch.v_quiescent,
                    'divider_ratio': ch.divider_ratio,
                    'adc_bits': ch.adc_bits,
                    'zero_cal_active': ch.zero_cal_active}
        return {'acs_range': self.acs_range, 'vcc': self.vcc,
                'v_quiescent': self.v_quiescent,
                'divider_ratio': self.divider_ratio,
                'adc_bits': self.adc_bits,
                'zero_cal_active': self.zero_cal_active}

    def sensitivity_of(self, src):
        return self.ACS712_RANGES.get(
            src['acs_range'], self.ACS712_RANGES['5A'])['sensitivity']

    def adc_to_vadc(self, adc_value, channel=None):
        """ADC 输入端电压（ESP32 ADC 引脚处）。"""
        src = self.adc_param_source(channel)
        max_adc = self.ADC_BITS_OPTIONS.get(src['adc_bits'], 4096) - 1
        return (adc_value / max_adc) * self.VREF

    def adc_to_vsensor(self, adc_value, channel=None):
        """还原 ACS712 输出电压（扣除分压电路影响）。"""
        src = self.adc_param_source(channel)
        return self.adc_to_vadc(adc_value, channel) * src['divider_ratio']

    def adc_to_current(self, adc_value, channel=None):
        """ADC 原始值 → 电流（安培，瞬时值）。"""
        src = self.adc_param_source(channel)
        v_sensor = self.adc_to_vsensor(adc_value, channel)
        return (v_sensor - src['v_quiescent']) / self.sensitivity_of(src)

    def measurable_range(self, channel=None):
        """按通道参数计算可测电流范围（安培）与 ADC 满量程计数值。"""
        src = self.adc_param_source(channel)
        sensitivity = self.sensitivity_of(src)
        max_adc = self.ADC_BITS_OPTIONS.get(src['adc_bits'], 4096) - 1
        v_sensor_max = self.VREF * src['divider_ratio']
        i_pos = (v_sensor_max - src['v_quiescent']) / sensitivity
        i_neg = (0.0 - src['v_quiescent']) / sensitivity
        return min(i_pos, i_neg), max(i_pos, i_neg), max_adc, src

    def to_current_unit(self, current_a):
        """安培 → 当前单位。"""
        return current_a * self.UNIT_FACTORS.get(self.current_unit, 1.0)

    def format_current(self, current_a):
        """格式化显示：根据数量级自动选小数位。"""
        c = self.to_current_unit(current_a)
        if self.current_unit == 'mA':
            return f"{c:.2f}"
        abs_c = abs(c)
        if abs_c >= 1.0:
            return f"{c:.4f}"
        return f"{c:.6f}"

    # ---------------- 解析 / 采样 ----------------
    def simulator_spec(self, channel):
        # 模拟器产生 0~满量程 的原始 ADC 值，中点≈零电流（按本路位数）
        max_adc = self.ADC_BITS_OPTIONS.get(channel.adc_bits, 4096) - 1
        return {
            'value_min': 0,
            'value_max': max_adc,
            'interval_ms': channel.sample_interval_ms,
            'start_value': max_adc / 2.0,
        }

    def decode_line(self, line, channel):
        if ',' not in line:
            return None
        parts = line.split(',')
        if len(parts) != 2:
            return None
        try:
            raw = int(parts[1])
        except ValueError:
            return None
        max_adc = self.ADC_BITS_OPTIONS.get(channel.adc_bits, 4096) - 1
        if raw < 0 or raw > max_adc:
            return None
        return float(raw)

    def convert(self, channel, raw):
        return self.adc_to_current(raw, channel=channel)

    def append_sample(self, channel, t, raw, value):
        channel.time_data.append(t)
        channel.raw_data.append(int(raw))
        channel.vsensor_data.append(self.adc_to_vsensor(raw, channel=channel))
        channel.current_data.append(value)

    def clear_channel_data(self, channel):
        channel.time_data.clear()
        channel.raw_data.clear()
        channel.vsensor_data.clear()
        channel.current_data.clear()
        channel.last_sample_s = None

    def channel_values(self, channel):
        return channel.current_data

    def channel_info(self, channel):
        info = super().channel_info(channel)
        info['acs_range'] = channel.acs_range
        info['zero_cal_active'] = channel.zero_cal_active
        info['v_quiescent'] = channel.v_quiescent
        info['latest_raw'] = channel.raw_data[-1] if channel.raw_data else None
        return info

    # ---------------- 连接 ----------------
    def _handle_line(self, cid, line):
        # 实时窗口用于去皮：即使未开始采集，也持续记录最近原始值
        ch = self.get_channel(cid)
        if ch is not None and not line.startswith('ERROR:') and line != 'START':
            try:
                raw = self.decode_line(line, ch)
            except Exception:
                raw = None
            if raw is not None:
                ch.live_window.append(int(raw))
        super()._handle_line(cid, line)

    def disconnect(self, cid):
        ch = self.get_channel(cid)
        res = super().disconnect(cid)
        if ch is not None:
            ch.live_window.clear()
        return res

    # ---------------- 零点校准 / 重算 ----------------
    def tare_now(self):
        """去皮（零点校准）：取各路最近实时采样点的传感器输出电压均值作为零点。"""
        targets = [ch for ch in self.channels if ch.live_window]
        if not targets:
            return {'ok': False, 'error': 'no_data',
                    'message': '还没有收到数据，等数据流入后再去皮'}
        parts = []
        calibrated = []
        for ch in targets:
            recent = [self.adc_to_vsensor(r, channel=ch)
                      for r in ch.live_window]
            ch.v_quiescent = float(np.mean(recent))
            ch.zero_cal_active = True
            parts.append(f"{ch.name} 零点={ch.v_quiescent:.4f}V")
            calibrated.append(ch.id)
        log.info("去皮：%s", "; ".join(parts))
        self.save_config()
        self.recompute_current_data()
        self._publish(EVENT_CHANNELS_CHANGED)
        return {'ok': True, 'message': f"已去皮（{'; '.join(parts)}）",
                'calibrated': calibrated}

    def recompute_current_data(self):
        """零点变化后，按各通道已有 raw_data 重算电流。"""
        if not any(ch.raw_data for ch in self.channels):
            return
        for ch in self.channels:
            ch.vsensor_data = [self.adc_to_vsensor(r, channel=ch)
                               for r in ch.raw_data]
            ch.current_data = [self.adc_to_current(r, channel=ch)
                               for r in ch.raw_data]

    def _compute_ac_rms(self, channel):
        """计算 AC 模式下该通道已采电流序列的 RMS（安培）。"""
        if not channel.current_data:
            return None
        window = channel.current_data[-self.ac_rms_window:]
        arr = np.array(window, dtype=float)
        return float(np.sqrt(np.mean(arr ** 2)))

    def compute_ac_rms(self, channel):
        return self._compute_ac_rms(channel)

    def channel_stats(self, channel):
        """一路已采电流序列的统计量（内部单位安培）。"""
        if not channel.current_data:
            return {'count': 0}
        arr = np.array(channel.current_data, dtype=float)
        return {
            'count': int(arr.size),
            'mean': float(np.mean(arr)),
            'min': float(np.min(arr)),
            'max': float(np.max(arr)),
            'std': float(np.std(arr)),
            'rms': float(np.sqrt(np.mean(arr ** 2))),
            'peak': float(np.max(np.abs(arr))),
        }

    # ---------------- 快照 / 导出 ----------------
    def ai_data(self):
        active = [ch for ch in self.channels if ch.current_data]
        if not active:
            return None
        main = max(active, key=lambda c: len(c.current_data))
        src = self.adc_param_source(main)
        sensitivity = self.sensitivity_of(src)
        max_adc = self.ADC_BITS_OPTIONS.get(src['adc_bits'], 4096) - 1
        res_i = (self.VREF / max_adc) * src['divider_ratio'] / sensitivity
        lo, hi, _max_adc, _src = self.measurable_range(main)
        channels_desc = '、'.join(
            f"{ch.name}[{len(ch.current_data)}点/量程{ch.acs_range}"
            + ('/已校零' if ch.zero_cal_active else '/未校零')
            + ']' for ch in active)
        return {
            'title': self.title,
            'x_label': self.x_label,
            'y_label': f'电流 ({self.current_unit})',
            'points': list(zip(main.time_data,
                               [self.to_current_unit(c)
                                for c in main.current_data])),
            'params': (
                f"传感器=ACS712 {src['acs_range']} 量程"
                f"（灵敏度 {sensitivity:.3f} V/A）, "
                f"VCC={src['vcc']}V, 零点电压={src['v_quiescent']:.4f}V"
                f"(理论 VCC/2={src['vcc'] / 2:.4f}V), "
                f"分压比={src['divider_ratio']}, ADC 位数={src['adc_bits']}, "
                f"电流分辨率≈{res_i * 1000:.3f}mA/计数, "
                f"可测范围≈{lo:.2f}~{hi:.2f}A（受 ADC 量程与分压限制）, "
                f"模式={self.current_mode}, AC RMS 窗口={self.ac_rms_window}点, "
                f"零点校准={'已校准' if src['zero_cal_active'] else '未校准'}, "
                f"多路连接: 共{len(active)}路（{channels_desc}），"
                f"主分析通道={main.name}, 各路量程/零点/分压独立, "
                f"显示单位={self.current_unit}, "
                f"采样间隔={main.sample_interval_ms}ms（各路独立）"),
        }


    def snapshot(self, points=0):
        """当前实验数据快照（供 KernelRegistry 任意线程读取）。"""
        d = self.ai_data() or {}
        pts = list(d.get('points') or [])
        total_points = len(pts)
        if points and len(pts) > points:
            step = len(pts) / float(points)
            pts = [pts[int(i * step)] for i in range(points)]
        latest = None
        main = max((ch for ch in self.channels if ch.current_data),
                   key=lambda c: len(c.current_data), default=None)
        if main is not None:
            latest = {'t': main.time_data[-1],
                      'y': self.to_current_unit(main.current_data[-1]),
                      'raw': main.raw_data[-1] if main.raw_data else None}
        return {
            'key': self.key,
            'name': self.title,
            'connected': self.connected_any(),
            'collecting': self.collecting,
            'x_label': d.get('x_label', self.x_label),
            'y_label': d.get('y_label', self.y_label),
            'params': d.get('params', ''),
            'points': pts,
            'total_points': total_points,
            'latest': latest,
            # 多路连接明细（points 仍为主通道序列，前端单曲线不破）
            'channels': [
                {'name': ch.name, 'color': ch.color,
                 'connected': bool(ch.connected),
                 'points_n': len(ch.current_data),
                 'zero_cal_active': ch.zero_cal_active,
                 'latest_raw': ch.raw_data[-1] if ch.raw_data else None}
                for ch in self.channels
            ],
        }

    # ---------------- 命令 ----------------
    def set_mode(self, mode):
        mode = str(mode).strip().upper()
        if mode not in ('DC', 'AC'):
            return {'ok': False, 'error': 'bad_mode',
                    'message': '测量类型只能是 DC 或 AC'}
        self.current_mode = mode
        self.save_config()
        self._publish(EVENT_CHANNELS_CHANGED, None, {'current_mode': mode})
        return {'ok': True, 'message': f'测量类型已切换为 {mode}', 'mode': mode}

    def set_unit(self, unit):
        if isinstance(unit, int):
            unit = 'A' if unit == 0 else 'mA'
        unit = str(unit).strip()
        if unit.lower() == 'ma':
            unit = 'mA'
        elif unit.lower() == 'a':
            unit = 'A'
        if unit not in self.UNIT_FACTORS:
            return {'ok': False, 'error': 'bad_unit',
                    'message': '显示单位只能是 A 或 mA'}
        self.current_unit = unit
        self.save_config()
        self._publish(EVENT_CHANNELS_CHANGED, None, {'current_unit': unit})
        return {'ok': True, 'message': f'显示单位已切换为 {unit}', 'unit': unit}

    def set_rms_window(self, window):
        try:
            window = int(window)
        except (TypeError, ValueError):
            return {'ok': False, 'error': 'bad_window',
                    'message': 'AC RMS 窗口必须是整数'}
        self.ac_rms_window = max(5, min(500, window))
        self.save_config()
        self._publish(EVENT_CHANNELS_CHANGED, None,
                      {'ac_rms_window': self.ac_rms_window})
        return {'ok': True,
                'message': f'AC RMS 窗口已设为 {self.ac_rms_window} 点',
                'window': self.ac_rms_window}

    def sensor_actions(self):
        return ['zero_cal', 'set_mode', 'set_unit', 'set_rms_window']

    def sensor_command(self, action, params):
        if action == 'zero_cal':
            return self.tare_now()
        if action == 'set_mode':
            return self.set_mode(params.get('mode', params.get('value')))
        if action == 'set_unit':
            return self.set_unit(params.get('unit', params.get('value')))
        if action == 'set_rms_window':
            value = params.get('window', params.get('value'))
            if value is None:
                return {'ok': False, 'message': '缺少 RMS 窗口大小'}
            return self.set_rms_window(value)
        return None
