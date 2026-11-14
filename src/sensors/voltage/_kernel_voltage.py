# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

# -*- coding: utf-8 -*-
"""电压传感器内核 — 纯 Python，不依赖 Qt。

View（voltage_sensor.py）只负责控件；本文件负责：
- 通道配置与持久化（含每路 ADC / 分压 / 放大 / 去皮参数）
- 串口 / 模拟器传输（复用 core.SensorKernel 的传输与事件总线）
- 采样解析、有符号 ADC 换算、去皮、数据缓存
- 快照 / CSV / ai_data 导出与 tare 命令
"""

import numpy as np

from core import (
    MultiChannelKernel, ChannelBase, load_sensor_config, save_sensor_config,
    EVENT_CHANNELS_CHANGED, get_logger,
    ADC_BITS_OPTIONS, VREF,
    ADS1115_PGA_RANGES, ADS1115_CHANNELS,
)

log = get_logger('voltage_sensor_kernel')

CONFIG_KEY = 'voltage_sensor'

# 单位换算：内部 voltage_data 始终存伏特，按当前单位返回显示值
UNIT_FACTORS = {'kV': 0.001, 'V': 1.0, 'mV': 1000.0}


class VoltageChannel(ChannelBase):
    """一路电压采集连接的数据模型（不持有任何 Qt 控件）。"""

    def __init__(self, cid, name, color, mode='serial', port='',
                 sample_interval_ms=100, visible=True, adc_params=None):
        super().__init__(cid, name, color, mode=mode, port=port,
                         sample_interval_ms=sample_interval_ms,
                         visible=visible)

        # 本路 ADC 换算参数（每路独立；缺省继承模块级/全局默认）
        p = adc_params or {}
        self.adc_bits = p.get('adc_bits', 12)
        self.divider_ratio = p.get('divider_ratio', 1.0)
        self.amp_ratio = p.get('amp_ratio', 1.0)
        self.hx711_mode = p.get('hx711_mode', False)
        self.hx711_avdd = p.get('hx711_avdd', 5.0)
        self.hx711_channel = p.get('hx711_channel', 'B')
        self.ads1115_mode = p.get('ads1115_mode', False)
        self.ads1115_pga = p.get('ads1115_pga', '±2.048V')
        self.ads1115_channel = p.get('ads1115_channel', 'AIN0')

        # 采集数据（内部电压单位：伏特）
        self.voltage_data = []
        # 基类 channel_info / clear 使用的别名
        self.value_data = self.voltage_data
        # 去皮零点（每路独立）
        self.tare_offset_v = float(p.get('tare_offset_v', 0.0) or 0.0)
        self.tare_active = bool(p.get('tare_active', False))


class VoltageKernel(MultiChannelKernel):
    """电压传感器内核。"""

    CHANNEL_EXTRA_FIELDS = (
        'adc_bits', 'divider_ratio', 'amp_ratio',
        'hx711_mode', 'hx711_avdd', 'hx711_channel',
        'ads1115_mode', 'ads1115_pga', 'ads1115_channel',
        'tare_offset_v', 'tare_active',
    )

    def create_channel(self, cid, name, color, mode, port,
                       sample_interval_ms, visible, params):
        adc_params = dict(params.get('adc_params') or {})
        # HTTP add_channel 的 sensor_params 直接给每路字段，合并进来
        for f in self.CHANNEL_EXTRA_FIELDS:
            if f in params:
                adc_params[f] = params[f]
        if not adc_params:
            adc_params = self.adc_param_source(
                self.channels[0] if self.channels else None)
        return VoltageChannel(
            cid, name, color, mode=mode, port=port,
            sample_interval_ms=sample_interval_ms, visible=visible,
            adc_params=adc_params)

    def channel_restore_params(self, item):
        return {'adc_params': {**self.adc_param_source(), **item}}

    def after_restore_channels(self):
        self.mirror_first_channel(
            'adc_bits', 'divider_ratio', 'amp_ratio', 'hx711_mode',
            'hx711_avdd', 'hx711_channel', 'ads1115_mode',
            'ads1115_pga', 'ads1115_channel', 'sample_interval_ms')

    def csv_header(self):
        return ['channel', 'timestamp_s', 'raw_adc',
                f'voltage_{self.current_unit.lower()}']

    def csv_row_values(self, ch, i):
        voltage = ch.voltage_data[i] if i < len(ch.voltage_data) else 0.0
        t = ch.time_data[i] if i < len(ch.time_data) else 0.0
        raw = ch.raw_data[i] if i < len(ch.raw_data) else 0
        return [ch.name, f'{t:.3f}', raw,
                f'{self.to_current_unit(voltage):.6f}']

    key = CONFIG_KEY
    title = '电压传感器'
    x_label = '时间 (秒)'
    y_label = '电压 (V)'

    ADC_BITS_OPTIONS = ADC_BITS_OPTIONS
    ADS1115_PGA_RANGES = ADS1115_PGA_RANGES
    ADS1115_CHANNELS = ADS1115_CHANNELS
    UNIT_FACTORS = UNIT_FACTORS
    VREF = VREF

    def __init__(self):
        super().__init__()
        # 模块级镜像字段（旧配置兼容；第 1 路为准）
        self.sample_interval_ms = 100
        self.adc_bits = 12
        self.divider_ratio = 1.0
        self.amp_ratio = 1.0
        self.hx711_mode = False
        self.hx711_avdd = 5.0
        self.hx711_channel = 'B'
        self.ads1115_mode = False
        self.ads1115_pga = '±2.048V'
        self.ads1115_channel = 'AIN0'
        # 显示单位：内部 voltage_data 始终存伏特，仅在显示/保存时按当前单位换算
        self.current_unit = 'V'     # 可选：kV / V / mV

        self.config = self.load_config()
        self._restore_channels()

    # ---------------- 配置 ----------------
    def load_config(self):
        config = load_sensor_config(CONFIG_KEY)
        if config:
            self.adc_bits = config.get('adc_bits', 12)
            self.divider_ratio = config.get('divider_ratio', 1.0)
            self.amp_ratio = config.get('amp_ratio', 1.0)
            self.sample_interval_ms = config.get('sample_interval_ms', 100)
            self.hx711_mode = config.get('hx711_mode', False)
            self.hx711_avdd = config.get('hx711_avdd', 5.0)
            self.hx711_channel = config.get('hx711_channel', 'B')
            self.ads1115_mode = config.get('ads1115_mode', False)
            self.ads1115_pga = config.get('ads1115_pga', '±2.048V')
            self.ads1115_channel = config.get('ads1115_channel', 'AIN0')
            self.current_unit = config.get('current_unit', 'V')
        return config

    def save_config(self):
        first = self.channels[0] if self.channels else None
        config = {
            # 兼容旧版单通道上位机：顶层 ADC/采样/去皮字段取第 1 路的值
            'adc_bits': first.adc_bits if first else self.adc_bits,
            'divider_ratio': first.divider_ratio if first else self.divider_ratio,
            'amp_ratio': first.amp_ratio if first else self.amp_ratio,
            'hx711_mode': first.hx711_mode if first else self.hx711_mode,
            'hx711_avdd': first.hx711_avdd if first else self.hx711_avdd,
            'hx711_channel': first.hx711_channel if first else self.hx711_channel,
            'ads1115_mode': first.ads1115_mode if first else self.ads1115_mode,
            'ads1115_pga': first.ads1115_pga if first else self.ads1115_pga,
            'ads1115_channel': first.ads1115_channel if first else self.ads1115_channel,
            'current_unit': self.current_unit,
            'sample_interval_ms': first.sample_interval_ms if first else self.sample_interval_ms,
            'tare_offset_v': first.tare_offset_v if first else 0.0,
            'tare_active': first.tare_active if first else False,
        }
        return save_sensor_config(CONFIG_KEY, self.base_config(config))


    # ---------------- 通道 ----------------

    # ---------------- ADC 换算 ----------------
    def adc_param_source(self, channel=None):
        """取一路 ADC 参数字典：显式通道 > 第 1 路 > 模块级默认。"""
        ch = channel
        if ch is None and self.channels:
            ch = self.channels[0]
        if ch is not None:
            return {'adc_bits': ch.adc_bits, 'divider_ratio': ch.divider_ratio,
                    'amp_ratio': ch.amp_ratio, 'hx711_mode': ch.hx711_mode,
                    'hx711_avdd': ch.hx711_avdd, 'hx711_channel': ch.hx711_channel,
                    'ads1115_mode': ch.ads1115_mode, 'ads1115_pga': ch.ads1115_pga,
                    'ads1115_channel': ch.ads1115_channel}
        return {'adc_bits': self.adc_bits, 'divider_ratio': self.divider_ratio,
                'amp_ratio': self.amp_ratio, 'hx711_mode': self.hx711_mode,
                'hx711_avdd': self.hx711_avdd, 'hx711_channel': self.hx711_channel,
                'ads1115_mode': self.ads1115_mode, 'ads1115_pga': self.ads1115_pga,
                'ads1115_channel': self.ads1115_channel}

    def adc_to_vadc(self, adc_value, channel=None):
        """计算 ADC 输入端电压（未做分压/放大还原）。

        统一有符号换算：下位机输出有符号 ADC 值，0 对应 0V，量程 -VREF~+VREF。
        公式：(adc / max_adc) × VREF。
        """
        src = self.adc_param_source(channel)
        # HX711：24 位有符号补码（饱和码 ±2^23）
        # 满码对应电压 = AVDD / Gain / 2（A Gain128、B Gain32）
        if src['hx711_mode']:
            gain = 128 if src['hx711_channel'] == 'A' else 32
            return adc_value / 8388608.0 * (src['hx711_avdd'] / gain / 2)
        # ADS1115：16 位有符号补码，电压 = raw / 32768 × FSR
        if src['ads1115_mode']:
            fsr = ADS1115_PGA_RANGES.get(src['ads1115_pga'], 2.048)
            return adc_value / 32768.0 * fsr
        max_adc = ADC_BITS_OPTIONS.get(src['adc_bits'], 4095)
        return (adc_value / max_adc) * VREF

    def adc_to_voltage(self, adc_value, apply_tare=True, channel=None):
        """实际被测电压 = ADC端电压 × 分压比 / 放大倍数。

        apply_tare=False 时不扣去皮零点，用于在已有零点的基础上重新计算新零点。
        """
        v_adc = self.adc_to_vadc(adc_value, channel)
        src = self.adc_param_source(channel)
        actual_voltage = v_adc * src['divider_ratio'] / src['amp_ratio']
        if apply_tare and channel is not None and channel.tare_active:
            actual_voltage -= channel.tare_offset_v
        return actual_voltage

    # 单位换算：内部 voltage_data 始终存伏特，按当前单位返回显示值
    def to_current_unit(self, voltage_v):
        """伏特 → 当前单位"""
        return voltage_v * UNIT_FACTORS.get(self.current_unit, 1.0)

    def format_voltage(self, voltage_v):
        """格式化显示：根据数量级自动选小数位"""
        v = self.to_current_unit(voltage_v)
        if self.current_unit == 'kV':
            return f"{v:.6f}"
        elif self.current_unit == 'mV':
            return f"{v:.3f}"
        return f"{v:.4f}"

    # ---------------- 解析 / 采样 ----------------
    def simulator_spec(self, channel):
        # 模拟器产生有符号 ADC 范围的原始值，中点为 0V（按本路位数）
        max_adc = ADC_BITS_OPTIONS.get(channel.adc_bits, 4095)
        return {
            'value_min': -max_adc,
            'value_max': max_adc,
            'interval_ms': channel.sample_interval_ms,
        }

    def decode_line(self, line, channel):
        if ',' not in line:
            return None
        parts = line.split(',')
        if len(parts) != 2:
            return None
        try:
            return int(parts[1])
        except ValueError:
            return None

    def convert(self, channel, raw):
        # 每个有效样本都进实时滚动窗口（未采集时也供去皮使用）
        channel.live_window.append(raw)
        return self.adc_to_voltage(raw, channel=channel)

    def append_sample(self, channel, t, raw, value):
        channel.time_data.append(t)
        channel.raw_data.append(int(raw))
        channel.voltage_data.append(value)

    def clear_channel_data(self, channel):
        channel.time_data.clear()
        channel.raw_data.clear()
        channel.voltage_data.clear()
        channel.last_sample_s = None

    def channel_values(self, channel):
        return channel.voltage_data

    def channel_info(self, channel):
        info = super().channel_info(channel)
        info['tare_active'] = channel.tare_active
        info['tare_offset_v'] = channel.tare_offset_v
        return info

    # ---------------- 去皮 ----------------
    def tare_now(self, cid=None):
        """取最近 10 个采样点的平均值作为零点，并重算该路已有数据。

        不要求先开始采集；可反复点击重新归零；多路时各路零点独立。
        """
        with self._lock:
            if cid is not None:
                ch = self.get_channel(cid)
                targets = [ch] if ch is not None and ch.live_window else []
            else:
                targets = [ch for ch in self.channels if ch.live_window]
            if not targets:
                return {'ok': False,
                        'message': '还没有收到数据，等数据流入后再去皮'}
            parts = []
            for ch in targets:
                # 取最近 10 个采样点（去皮前的电压）平均值作为新零点
                pre_tare = [self.adc_to_voltage(r, apply_tare=False, channel=ch)
                            for r in ch.live_window]
                ch.tare_offset_v = float(np.mean(pre_tare))
                ch.tare_active = True
                parts.append(f"{ch.name} 零点={ch.tare_offset_v:.6g}V")
            self.recompute_voltage_data()
        log.info("去皮：%s", "; ".join(parts))
        self.save_config()
        self._publish(EVENT_CHANNELS_CHANGED)
        return {'ok': True, 'message': f'已去皮（{"; ".join(parts)}）'}

    def recompute_voltage_data(self):
        """按各通道已有 raw_data 重算 voltage_data（去皮后曲线同步归零）。"""
        with self._lock:
            for ch in self.channels:
                if not ch.raw_data:
                    continue
                ch.voltage_data[:] = [
                    self.adc_to_voltage(r, channel=ch) for r in ch.raw_data]

    # ---------------- 快照 / 导出 ----------------
    def ai_data(self):
        active = [ch for ch in self.channels if ch.voltage_data]
        if not active:
            return None
        main = max(active, key=lambda c: len(c.voltage_data))
        # 电路参数：ADC 端满量程、实际量程与理论分辨率（按主分析通道的参数）
        if main.ads1115_mode:
            fs = ADS1115_PGA_RANGES.get(main.ads1115_pga, 2.048)
            counts = 32768.0
        elif main.hx711_mode:
            gain = 128 if main.hx711_channel == 'A' else 32
            fs, counts = main.hx711_avdd / gain / 2, 8388608.0
        else:
            fs = VREF
            counts = float(ADC_BITS_OPTIONS.get(main.adc_bits, 4095))
        actual = fs * main.divider_ratio / main.amp_ratio
        res = actual / counts
        channels_desc = "、".join(
            f"{ch.name}[{len(ch.voltage_data)}点]"
            + (f"去皮{ch.tare_offset_v:.4g}V" if ch.tare_active else "未去皮")
            for ch in active)
        return {
            'title': self.title,
            'x_label': self.x_label,
            'y_label': f'电压 ({self.current_unit})',
            'points': list(zip(main.time_data,
                               [self.to_current_unit(v)
                                for v in main.voltage_data])),
            'params': (
                f"采样方式={'ADS1115 16位' if main.ads1115_mode else ('HX711 24位' if main.hx711_mode else f'ESP32 内置 ADC {main.adc_bits}位')}, "
                f"参考电压=3.3V, 分压比={main.divider_ratio}, 放大倍数={main.amp_ratio}, "
                f"ADC端满量程=±{fs:.6g}V, 实际量程=±{actual:.6g}V, "
                f"理论分辨率={res:.3g}V/计数, "
                f"ADS1115 PGA={main.ads1115_pga}/通道={main.ads1115_channel}, "
                f"HX711 AVDD={main.hx711_avdd}V/通道={main.hx711_channel}"
                f"(增益{128 if main.hx711_channel == 'A' else 32}), "
                f"多路连接: 共{len(active)}路（{channels_desc}），"
                f"主分析通道={main.name}, 各路ADC参数与零点独立, "
                f"显示单位={self.current_unit}, "
                f"采样间隔={main.sample_interval_ms}ms（各路独立）"),
        }

    def snapshot(self, points=0):
        snap = super().snapshot(points)
        main = max((ch for ch in self.channels if ch.voltage_data),
                   key=lambda c: len(c.voltage_data), default=None)
        if main is not None:
            snap['latest'] = {
                't': main.time_data[-1],
                'y': self.to_current_unit(main.voltage_data[-1]),
                'raw': main.raw_data[-1] if main.raw_data else None,
            }
        return snap


    # ---------------- 命令 ----------------
    def sensor_actions(self):
        return ['tare']

    def sensor_command(self, action, params):
        if action == 'tare':
            params = params or {}
            cid = params.get('channel_id', params.get('cid'))
            return self.tare_now(cid)
        return None
