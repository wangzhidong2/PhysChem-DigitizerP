# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

# -*- coding: utf-8 -*-
"""pH 传感器内核 — 纯 Python，不依赖 Qt。

负责通道配置、串口/模拟器传输、ADC 解析、单点/两点/三点校准、
pH 换算、缓存、快照与 CSV。View（ph_sensor.py）只负责控件。
"""

import numpy as np

from core import (
    MultiChannelKernel, ChannelBase, load_sensor_config, save_sensor_config,
    get_logger, CHANNEL_COLORS,
)

log = get_logger('ph_sensor_kernel')

CONFIG_KEY = 'ph_sensor'

# 单点校准默认理论斜率（mV/pH）：SEN0161 放大板 PO 端口等效斜率（含板上增益），
# 官方示例约 3.5 pH/V ≈ -286 mV/pH，取 -280 为默认；电极裸 Nernst 斜率为
# -59.16 mV/pH（25℃），未含放大幅度。斜率可在校准对话框按实测/两点缓冲液修改。
DEFAULT_THEORETICAL_SLOPE_MV = -280.0
# ADC 换算常量（与固件一致：analogReadResolution(12) + 11dB 衰减 ≈ 0~3.3V）
PH_ADC_MAX = 4095
PH_ADC_VREF = 3.3

DEFAULT_CALIBRATION_POINTS = [
    (4.00, 2555),   # 酸性缓冲液
    (6.86, 2281),   # 中性缓冲液
    (9.18, 2030),   # 碱性缓冲液
]

CHANNEL_COLORS = CHANNEL_COLORS

CAL_MODE_NAMES = {1: '单点校准', 2: '两点校准', 3: '三点校准'}


class PhChannel(ChannelBase):
    """一路 pH 电极连接的数据模型（不持有任何 Qt 控件）。"""

    def __init__(self, cid, name, color, mode='serial', port='',
                 sample_interval_ms=100, visible=True, cal_params=None):
        super().__init__(cid, name, color, mode=mode, port=port,
                         sample_interval_ms=sample_interval_ms,
                         visible=visible)

        p = cal_params or {}
        self.calibration_points = [
            tuple(pt) for pt in
            (p.get('calibration_points') or DEFAULT_CALIBRATION_POINTS)]
        self.calibration_mode = p.get(
            'calibration_mode', len(self.calibration_points))
        self.theoretical_slope_mv = p.get(
            'theoretical_slope_mv', DEFAULT_THEORETICAL_SLOPE_MV)
        self.cal_coeffs = (0.0, 0.0, 7.0)

        self.adc_data = []
        self.ph_data = []
        # 基类 channel_info / clear 使用这两个名字；保持别名
        self.raw_data = self.adc_data
        self.value_data = self.ph_data


class PhKernel(MultiChannelKernel):
    """pH 传感器内核。"""

    CHANNEL_EXTRA_FIELDS = (
        'calibration_points', 'calibration_mode', 'theoretical_slope_mv',
    )

    def create_channel(self, cid, name, color, mode, port,
                       sample_interval_ms, visible, params):
        cal_params = dict(params.get('cal_params') or {})
        for f in self.CHANNEL_EXTRA_FIELDS:
            if f in params:
                cal_params[f] = params[f]
        return PhChannel(cid, name, color, mode=mode, port=port,
                         sample_interval_ms=sample_interval_ms,
                         visible=visible, cal_params=cal_params or None)

    def channel_restore_params(self, item):
        points = item.get('calibration_points')
        if points:
            points = [tuple(p) for p in points]
        return {'cal_params': {
            'calibration_points': points,
            'calibration_mode': item.get('calibration_mode'),
            'theoretical_slope_mv': item.get(
                'theoretical_slope_mv', self.theoretical_slope_mv),
        }}

    def legacy_channel_params(self):
        return {'cal_params': {
            'calibration_points': self.calibration_points,
            'calibration_mode': self.calibration_mode,
            'theoretical_slope_mv': self.theoretical_slope_mv,
        }}

    def after_restore_channels(self):
        self.calculate_calibration_coefficients()
        self.mirror_first_channel(
            'calibration_points', 'calibration_mode',
            'theoretical_slope_mv', 'cal_coeffs', 'sample_interval_ms')

    def csv_comments(self):
        lines = []
        for ch in self.channels:
            mode_name = CAL_MODE_NAMES.get(
                ch.calibration_mode, f'{ch.calibration_mode}点校准')
            lines.append(f'# {ch.name}: {mode_name} '
                         f'{[tuple(p) for p in ch.calibration_points]}')
        return lines

    def csv_header(self):
        return ['channel', 'time_s', 'adc_raw', 'ph_value']

    def csv_row_values(self, ch, i):
        t = ch.time_data[i] if i < len(ch.time_data) else 0.0
        adc = ch.adc_data[i] if i < len(ch.adc_data) else 0
        ph = ch.ph_data[i] if i < len(ch.ph_data) else 0.0
        return [ch.name, f'{t:.3f}', adc, f'{ph:.3f}']

    key = CONFIG_KEY
    title = 'pH传感器'
    x_label = '时间 (秒)'
    y_label = 'pH值'

    def __init__(self):
        super().__init__()
        # 模块级镜像字段（旧配置兼容；第 1 路为准）
        self.calibration_points = list(DEFAULT_CALIBRATION_POINTS)
        self.calibration_mode = len(DEFAULT_CALIBRATION_POINTS)
        self.theoretical_slope_mv = DEFAULT_THEORETICAL_SLOPE_MV
        self.cal_coeffs = (0.0, 0.0, 7.0)
        self.config = self.load_config()
        self._restore_channels()

    # ---------------- 配置 ----------------
    def load_config(self):
        config = load_sensor_config(CONFIG_KEY)
        if config:
            self.sample_interval_ms = config.get('sample_interval_ms', 100)
            self.calibration_points = [
                tuple(p) for p in config.get(
                    'calibration_points', DEFAULT_CALIBRATION_POINTS)]
            self.calibration_mode = config.get(
                'calibration_mode', len(self.calibration_points))
            self.theoretical_slope_mv = config.get(
                'theoretical_slope_mv', DEFAULT_THEORETICAL_SLOPE_MV)
        return config

    def save_config(self):
        first = self.channels[0] if self.channels else None
        config = {
            'calibration_points': (
                [tuple(p) for p in first.calibration_points]
                if first else self.calibration_points),
            'calibration_mode': (
                first.calibration_mode if first else self.calibration_mode),
            'theoretical_slope_mv': (
                first.theoretical_slope_mv if first
                else self.theoretical_slope_mv),
            'sample_interval_ms': (
                first.sample_interval_ms if first else self.sample_interval_ms),
        }
        return save_sensor_config(CONFIG_KEY, self.base_config(config))


    # ---------------- 通道 ----------------

    # ---------------- 校准 / 物理 ----------------
    def _calc_coeffs_for(self, channel):
        points = [tuple(p) for p in channel.calibration_points]
        ph_values = [p[0] for p in points]
        adc_values = [p[1] for p in points]
        num_points = len(points)

        if num_points == 1:
            ph0, adc0 = points[0]
            slope_mv = float(channel.theoretical_slope_mv)
            if slope_mv == 0:
                log.error('配置中的理论斜率为 0（非法），本次计算临时改用默认 '
                          '%.2f mV/pH', DEFAULT_THEORETICAL_SLOPE_MV)
                slope_mv = DEFAULT_THEORETICAL_SLOPE_MV
            d_adc_per_ph = slope_mv / 1000.0 * PH_ADC_MAX / PH_ADC_VREF
            slope_ph_per_adc = 1.0 / d_adc_per_ph
            intercept = ph0 - slope_ph_per_adc * adc0
            channel.cal_coeffs = (0, slope_ph_per_adc, intercept)
            channel.calibration_mode = 1
        elif num_points == 2:
            coefficients = np.polyfit(adc_values, ph_values, 1)
            channel.cal_coeffs = (0, coefficients[0], coefficients[1])
            channel.calibration_mode = 2
        else:
            coefficients = np.polyfit(
                adc_values, ph_values, min(2, num_points - 1))
            if len(coefficients) == 2:
                channel.cal_coeffs = (0, coefficients[0], coefficients[1])
            else:
                channel.cal_coeffs = tuple(coefficients)
            channel.calibration_mode = num_points

    def calculate_calibration_coefficients(self, channel=None):
        targets = [channel] if channel is not None else list(self.channels)
        for ch in targets:
            self._calc_coeffs_for(ch)

    def adc_to_ph(self, channel, raw):
        a, b, c = channel.cal_coeffs
        value = a * (raw ** 2) + b * raw + c
        return max(0.0, min(14.0, value))

    def set_calibration(self, cid, points, mode=None,
                        theoretical_slope_mv=None):
        ch = self.get_channel(cid)
        if ch is None:
            return {'ok': False, 'error': 'channel_not_found',
                    'message': '通道不存在'}
        try:
            ch.calibration_points = [tuple(p) for p in points]
            if theoretical_slope_mv is not None:
                ch.theoretical_slope_mv = float(theoretical_slope_mv)
            if mode is not None:
                ch.calibration_mode = int(mode)
            self._calc_coeffs_for(ch)
            if self.channels and ch is self.channels[0]:
                self.calibration_points = [tuple(p) for p in ch.calibration_points]
                self.calibration_mode = ch.calibration_mode
                self.theoretical_slope_mv = ch.theoretical_slope_mv
                self.cal_coeffs = ch.cal_coeffs
            self.save_config()
            self._publish('channels_changed', cid)
            return {'ok': True, 'message': f'{ch.name} 校准参数已更新',
                    'calibration': self.get_calibration(cid)['calibration']}
        except Exception as e:
            return {'ok': False, 'error': 'bad_calibration',
                    'message': f'校准参数无效: {e}'}

    def get_calibration(self, cid):
        ch = self.get_channel(cid)
        if ch is None:
            return {'ok': False, 'error': 'channel_not_found',
                    'message': '通道不存在'}
        return {'ok': True, 'calibration': {
            'channel_id': ch.id,
            'name': ch.name,
            'points': [tuple(p) for p in ch.calibration_points],
            'mode': ch.calibration_mode,
            'theoretical_slope_mv': ch.theoretical_slope_mv,
            'coeffs': [float(x) for x in ch.cal_coeffs],
        }}

    # ---------------- 解析 / 采样 ----------------
    def simulator_spec(self, channel):
        return {
            'value_min': 2000,
            'value_max': 2600,
            'interval_ms': channel.sample_interval_ms,
            'start_value': 2281,
        }

    def decode_line(self, line, channel):
        if ',' not in line:
            return None
        parts = line.split(',')
        if len(parts) != 2:
            return None
        try:
            adc = int(parts[1])
        except ValueError:
            return None
        if adc < 0 or adc > PH_ADC_MAX:
            return None
        return float(adc)

    def convert(self, channel, raw):
        return self.adc_to_ph(channel, raw)

    def append_sample(self, channel, t, raw, value):
        channel.time_data.append(t)
        channel.adc_data.append(int(raw))
        channel.ph_data.append(value)

    def clear_channel_data(self, channel):
        channel.time_data.clear()
        channel.adc_data.clear()
        channel.ph_data.clear()
        channel.last_sample_s = None

    def channel_values(self, channel):
        return channel.ph_data

    def channel_info(self, channel):
        info = super().channel_info(channel)
        info['calibration_mode'] = channel.calibration_mode
        info['calibration_points'] = [tuple(p)
                                      for p in channel.calibration_points]
        info['theoretical_slope_mv'] = channel.theoretical_slope_mv
        info['latest_raw'] = channel.adc_data[-1] if channel.adc_data else None
        return info

    # ---------------- 快照 / 导出 ----------------
    def ai_data(self):
        active = [ch for ch in self.channels if ch.ph_data]
        if not active:
            return None
        main = max(active, key=lambda c: len(c.ph_data))
        mode_name = CAL_MODE_NAMES.get(
            main.calibration_mode, f'{main.calibration_mode}点校准')
        channels_desc = '、'.join(
            f"{ch.name}[{len(ch.ph_data)}点/"
            + CAL_MODE_NAMES.get(ch.calibration_mode,
                                 f'{ch.calibration_mode}点') + ']'
            for ch in active)
        return {
            'title': self.title,
            'x_label': self.x_label,
            'y_label': self.y_label,
            'points': list(zip(main.time_data, main.ph_data)),
            'params': (
                f'传感器=SEN0161 pH 电极 + ESP32-S3（12 位 ADC，0~4095）, '
                f'主分析通道={main.name}, '
                f'校准方式={mode_name}, '
                f'校准 {len(main.calibration_points)} 点 {main.calibration_points}, '
                f'拟合系数 a={main.cal_coeffs[0]:.6g}, '
                f'b={main.cal_coeffs[1]:.6g}, c={main.cal_coeffs[2]:.6g}'
                f'（pH = a·ADC² + b·ADC + c）, '
                f'理论斜率（单点用）={main.theoretical_slope_mv:g}mV/pH, '
                f'多路连接: 共{len(active)}路（{channels_desc}），'
                f'各路校准参数独立, '
                f'采样间隔={main.sample_interval_ms}ms（各路独立）'),
        }


    # ---------------- 命令 ----------------
    def sensor_actions(self):
        return ['get_calibration', 'set_calibration']

    def sensor_command(self, action, params):
        if action == 'get_calibration':
            cid = params.get('channel_id', params.get('cid'))
            ch = (self.get_channel(cid) if cid is not None
                  else (self.channels[0] if self.channels else None))
            if ch is None:
                return {'ok': False, 'message': '通道不存在'}
            return self.get_calibration(ch.id)
        if action == 'set_calibration':
            cid = params.get('channel_id', params.get('cid'))
            ch = (self.get_channel(cid) if cid is not None
                  else (self.channels[0] if self.channels else None))
            if ch is None:
                return {'ok': False, 'message': '通道不存在'}
            points = params.get('points')
            if not points:
                return {'ok': False, 'message': '缺少校准点 points'}
            return self.set_calibration(
                ch.id, points,
                mode=params.get('mode'),
                theoretical_slope_mv=params.get('theoretical_slope_mv'))
        return None
