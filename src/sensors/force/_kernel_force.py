# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

# -*- coding: utf-8 -*-
"""力传感器内核 — 纯 Python，不依赖 Qt。

View（force_sensor.py）只负责控件；本文件负责：
- 通道模型与配置持久化
- 串口 / 模拟器传输与固件命令（TARE）
- 数据解析、去皮、两点校准、单位换算
- 采样节流、数据缓存、快照、CSV 导出
"""


import numpy as np

from core import (
    MultiChannelKernel, ChannelBase, load_sensor_config, save_sensor_config,
    EVENT_CHANNEL_STATE, EVENT_CHANNELS_CHANGED,
    get_logger, CHANNEL_COLORS,
)

log = get_logger('force_sensor_kernel')

CONFIG_KEY = 'force_sensor'

# 多路连接的默认曲线配色（按新建顺序轮换取未用色，界面上可单独改色）
CHANNEL_COLORS = CHANNEL_COLORS

# 固件去皮完成 / 校准就绪的通知事件（模块自定义，View 用 QTimer 消费）
EVENT_TARE_DONE = 'tare_done'
EVENT_CALIBRATION_READY = 'calibration_ready'

GRAVITY = 9.8


class ForceChannel(ChannelBase):
    """一路 HX711 力/质量连接的数据模型（不持有任何 Qt 控件）。"""

    def __init__(self, cid, name, color, mode='serial', port='',
                 sample_interval_ms=100, visible=True, cal_params=None):
        super().__init__(cid, name, color, mode=mode, port=port,
                         sample_interval_ms=sample_interval_ms,
                         visible=visible)

        p = cal_params or {}
        self.offset = p.get('offset', 0)
        self.scale = p.get('scale', 1.0)
        self.calibrated = p.get('calibrated', False)

        # 采集数据：raw_data 存原始 ADC，force_data 存克值
        # （未校准时为原始 ADC 值）
        self.force_data = []
        # 基类 channel_values 使用 value_data；保持别名
        self.value_data = self.force_data


class ForceKernel(MultiChannelKernel):
    """力传感器内核。"""

    CHANNEL_EXTRA_FIELDS = ('offset', 'scale', 'calibrated')

    def create_channel(self, cid, name, color, mode, port,
                       sample_interval_ms, visible, params):
        cal_params = dict(params.get('cal_params') or {})
        for f in self.CHANNEL_EXTRA_FIELDS:
            if f in params:
                cal_params[f] = params[f]
        return ForceChannel(cid, name, color, mode=mode, port=port,
                            sample_interval_ms=sample_interval_ms,
                            visible=visible, cal_params=cal_params or None)

    def channel_restore_params(self, item):
        return {'cal_params': {
            'offset': self.offset, 'scale': self.scale,
            'calibrated': self.calibrated, **item}}

    def legacy_channel_params(self):
        return {'cal_params': {
            'offset': self.offset, 'scale': self.scale,
            'calibrated': self.calibrated}}

    def after_restore_channels(self):
        self._sync_first_channel()

    def csv_comments(self):
        lines = []
        for ch in self.channels:
            cal_desc = (f'校准 scale={ch.scale:.6f} offset={ch.offset}'
                        if ch.calibrated else '未校准（值为原始ADC）')
            lines.append(f'# {ch.name}: {cal_desc}')
        return lines

    def csv_header(self):
        return ['channel', 'time_s', 'raw_adc', 'value', 'unit']

    def csv_row_values(self, ch, i):
        t = ch.time_data[i] if i < len(ch.time_data) else 0.0
        raw = ch.raw_data[i] if i < len(ch.raw_data) else 0
        force = ch.force_data[i] if i < len(ch.force_data) else 0.0
        converted = self.convert_unit(force) if ch.calibrated else force
        return [ch.name, f'{t:.3f}', raw, f'{converted:.6f}',
                self.unit_str(ch)]

    key = CONFIG_KEY
    title = '力传感器'
    x_label = '时间 (秒)'
    y_label = '质量 (克)'

    def __init__(self):
        super().__init__()
        # 模块级镜像字段（旧配置兼容；第 1 路为准）
        self.offset = 0
        self.scale = 1.0
        self.calibrated = False
        self.cal_known_weight = 100.0
        self.current_unit = 'g'
        # 调校流程状态（同一时刻只标定一路）
        self._calib_cid = None
        self._calib_step = 0
        self._calib_raw_before = None
        self._calib_raw_after = None

        self.config = self.load_config()
        self._restore_channels()

    # ---------------- 配置 ----------------
    def load_config(self):
        config = load_sensor_config(CONFIG_KEY)
        if config:
            self.offset = config.get('offset', 0)
            self.scale = config.get('scale', 1.0)
            self.calibrated = config.get('calibrated', False)
            self.cal_known_weight = config.get('cal_known_weight', 100.0)
            self.current_unit = config.get('unit', 'g')
            self.sample_interval_ms = config.get('sample_interval_ms', 100)
        return config

    def save_config(self):
        first = self.channels[0] if self.channels else None
        config = {
            'offset': first.offset if first else self.offset,
            'scale': first.scale if first else self.scale,
            'calibrated': first.calibrated if first else self.calibrated,
            'cal_known_weight': self.cal_known_weight,
            'unit': self.current_unit,
            'sample_interval_ms': (
                first.sample_interval_ms if first else self.sample_interval_ms),
        }
        return save_sensor_config(CONFIG_KEY, self.base_config(config))


    def _sync_first_channel(self):
        first = self.channels[0] if self.channels else None
        if first is not None:
            self.offset = first.offset
            self.scale = first.scale
            self.calibrated = first.calibrated
            self.sample_interval_ms = first.sample_interval_ms

    # ---------------- 通道 ----------------

    def main_channel(self):
        """主通道：数据最多的一路（无数据时取第 1 路）。"""
        with_data = [ch for ch in self.channels if ch.force_data]
        if with_data:
            return max(with_data, key=lambda c: len(c.force_data))
        return self.channels[0] if self.channels else None

    # ---------------- 单位 ----------------
    def convert_unit(self, value_grams):
        """将克值转换为当前单位值（未校准数据不经过这里）。"""
        if self.current_unit == 'kg':
            return value_grams / 1000.0
        if self.current_unit == 'N':
            return value_grams / 1000.0 * GRAVITY
        return value_grams

    def unit_str(self, channel=None):
        """当前单位字符串（未校准通道显示 raw）。"""
        ch = channel or self.main_channel()
        calibrated = ch.calibrated if ch is not None else self.calibrated
        return self.current_unit if calibrated else 'raw'

    def chart_ylabel(self):
        """图表 Y 轴标签（按主通道校准状态）。"""
        main = self.main_channel()
        calibrated = main.calibrated if main is not None else self.calibrated
        if not calibrated:
            return '原始ADC值'
        labels = {'g': '质量 (g)', 'kg': '质量 (kg)', 'N': '力 (N)'}
        return labels.get(self.current_unit, '质量 (g)')

    def display_value(self, channel, value=None, raw=None):
        """把克值/原始 ADC 换算为界面显示值（校准数学留在内核）。"""
        if channel.calibrated:
            grams = (value if value is not None
                     else (raw - channel.offset) * channel.scale)
            return self.convert_unit(grams)
        return float(raw if value is None else value)

    def set_unit(self, unit):
        if unit not in ('g', 'kg', 'N'):
            return {'ok': False, 'message': f'不支持的单位: {unit}'}
        self.current_unit = unit
        self.save_config()
        self._publish(EVENT_CHANNELS_CHANGED)
        return {'ok': True, 'unit': unit,
                'message': f'显示单位已设为 {unit}'}

    def set_sample_interval(self, cid, interval_ms):
        ch = self.get_channel(cid)
        if ch is None:
            return {'ok': False, 'message': '通道不存在'}
        ch.sample_interval_ms = max(10, int(interval_ms))
        if self.channels and ch is self.channels[0]:
            self.sample_interval_ms = ch.sample_interval_ms
        self.save_config()
        self._publish(EVENT_CHANNELS_CHANGED, ch.id)
        return {'ok': True, 'sample_interval_ms': ch.sample_interval_ms}

    # ---------------- 物理 ----------------
    def simulator_spec(self, channel):
        # HX711 24 位原始读数，围绕一个基准值缓慢漂移
        return {
            'value_min': 7500000,
            'value_max': 9000000,
            'interval_ms': channel.sample_interval_ms,
            'start_value': 8200000,
        }

    def decode_line(self, line, channel):
        if ',' not in line:
            return None
        parts = line.split(',')
        if len(parts) != 2:
            return None
        try:
            raw_value = int(parts[1])
        except ValueError:
            return None
        return raw_value

    def convert(self, channel, raw):
        # 本次原始读数进入实时/去皮窗口（未开始采集也持续刷新）
        channel.live_window.append(int(raw))
        if channel.calibrated:
            return (raw - channel.offset) * channel.scale
        return float(raw)

    def append_sample(self, channel, t, raw, value):
        channel.time_data.append(t)
        channel.raw_data.append(int(raw))
        # value 为克值（未校准时为原始 ADC 值）
        channel.force_data.append(value)

    def clear_channel_data(self, channel):
        channel.time_data.clear()
        channel.raw_data.clear()
        channel.force_data.clear()
        channel.last_sample_s = None

    def channel_values(self, channel):
        return channel.force_data

    def channel_info(self, channel):
        info = super().channel_info(channel)
        info['calibrated'] = channel.calibrated
        info['offset'] = channel.offset
        info['scale'] = channel.scale
        info['unit'] = self.unit_str(channel)
        info['latest_raw'] = (channel.raw_data[-1]
                              if channel.raw_data else None)
        return info

    # ---------------- 去皮 / 校准 ----------------
    def tare(self):
        """对所有有数据流入的通道分别去皮（各自零点独立）。"""
        targets = [ch for ch in self.channels if ch.live_window]
        if not targets:
            return {'ok': False, 'message': '还没有收到数据，等数据流入后再去皮'}

        details = []
        notified = []
        for ch in targets:
            # 上位机侧零点：最近 10 个采样的平均值（比取单点更抗噪声）
            ch.offset = int(round(float(np.mean(ch.live_window))))
            details.append({'channel_id': ch.id, 'name': ch.name,
                            'offset': ch.offset})
            # 真串口才通知固件；模拟器没有这个命令
            if self._write_firmware_tare(ch):
                notified.append(ch.name)
        self._sync_first_channel()
        self.save_config()
        self.recompute_force_data()
        self._publish(EVENT_CHANNELS_CHANGED)
        log.info('去皮：%s', '; '.join(
            f"{d['name']} offset={d['offset']}" for d in details))
        return {'ok': True, 'message': '去皮完成', 'channels': details,
                'firmware': notified}

    def _write_firmware_tare(self, channel):
        """向真实串口固件发送 TARE 命令；模拟器不发送。"""
        if channel.mode == 'simulator':
            return False
        thread = getattr(channel, 'thread', None)
        if thread is None or not channel.connected:
            return False
        try:
            return bool(thread.send(b'TARE\n'))
        except Exception as e:
            log.warning('固件去皮命令发送失败（%s）：%s', channel.name, e)
            return False

    def _calib_channel(self, cid=None):
        if cid is None:
            cid = self._calib_cid
        if cid is not None:
            return self.get_channel(cid)
        return self.channels[0] if self.channels else None

    def calib_begin(self, cid=None):
        """开始两点标定流程（空载零点 → 已知砝码）。"""
        ch = self._calib_channel(cid)
        if ch is None:
            return {'ok': False, 'message': '通道不存在'}
        if not ch.connected:
            return {'ok': False, 'message': '设备未连接，无法校准'}
        self._calib_cid = ch.id
        self._calib_step = 1
        self._calib_raw_before = None
        self._calib_raw_after = None
        return {'ok': True, 'step': 1, 'channel_id': ch.id,
                'name': ch.name, 'message': f'{ch.name} 请空载并记录零点'}

    def calib_record_zero(self, cid=None):
        """记录空载零点（取该路最新实时读数）。"""
        ch = self._calib_channel(cid)
        if ch is None:
            return {'ok': False, 'message': '通道不存在'}
        if self._calib_step < 1 or self._calib_cid != ch.id:
            return {'ok': False, 'message': '请先开始校准'}
        if not ch.live_window:
            return {'ok': False, 'message': '还没有收到数据，等数据流入后再记录零点'}
        self._calib_raw_before = int(ch.live_window[-1])
        self._calib_step = 2
        return {'ok': True, 'step': 2, 'channel_id': ch.id,
                'name': ch.name, 'raw_before': self._calib_raw_before}

    def calib_record_known(self, cid=None, known_grams=None):
        """记录已知砝码读数并完成标定（scale = 砝码克数 / ADC 差值）。"""
        ch = self._calib_channel(cid)
        if ch is None:
            return {'ok': False, 'message': '通道不存在'}
        if self._calib_step != 2 or self._calib_cid != ch.id:
            return {'ok': False, 'message': '请先记录空载零点'}
        if not ch.live_window:
            return {'ok': False, 'message': '还没有收到数据，等数据流入后再记录'}
        try:
            known = float(known_grams)
        except (TypeError, ValueError):
            return {'ok': False, 'message': '砝码质量无效'}
        if known <= 0:
            return {'ok': False, 'message': '砝码质量必须大于 0'}

        raw_before = self._calib_raw_before
        raw_after = int(ch.live_window[-1])
        diff = raw_after - raw_before
        self._calib_step = 0
        self._calib_raw_after = raw_after
        if diff == 0:
            return {'ok': False, 'message': 'ADC差值为0，请检查传感器是否正常工作',
                    'raw_before': raw_before, 'raw_after': raw_after}

        ch.scale = known / diff
        ch.offset = raw_before
        ch.calibrated = True
        self.cal_known_weight = known
        self._sync_first_channel()
        self.save_config()
        self.recompute_force_data()
        self._publish(EVENT_CHANNELS_CHANGED)
        log.info('校准完成（%s）：offset=%s, scale=%.6f, 砝码=%.4g g',
                 ch.name, ch.offset, ch.scale, known)
        return {'ok': True, 'channel_id': ch.id, 'name': ch.name,
                'raw_before': raw_before, 'raw_after': raw_after,
                'diff': diff, 'scale': ch.scale, 'offset': ch.offset,
                'known': known}

    def calib_cancel(self, cid=None):
        """取消未完成的标定流程。"""
        self._calib_cid = None
        self._calib_step = 0
        self._calib_raw_before = None
        self._calib_raw_after = None
        return {'ok': True, 'message': '已取消校准'}

    def recompute_force_data(self):
        """零点/标定系数变化后，按各通道已有 raw_data 重算 force_data。"""
        if not any(ch.raw_data for ch in self.channels):
            return
        for ch in self.channels:
            if ch.calibrated:
                ch.force_data[:] = [(r - ch.offset) * ch.scale
                                    for r in ch.raw_data]
            else:
                ch.force_data[:] = [float(r) for r in ch.raw_data]

    # ---------------- 行解析（固件控制消息） ----------------
    def _handle_line(self, cid, line):
        ch = self.get_channel(cid)
        if ch is None:
            return

        if line.startswith('TARE_DONE'):
            parts = line.split(',')
            if len(parts) == 2:
                try:
                    # 固件用 10 次平均得到零点，比上位机单点更稳，以它为准
                    ch.offset = int(parts[1])
                    self._sync_first_channel()
                    self.save_config()
                    log.info('固件去皮完成（%s）：零点 offset=%d',
                             ch.name, ch.offset)
                    self._publish(EVENT_TARE_DONE, cid,
                                  {'offset': ch.offset, 'name': ch.name})
                except (ValueError, TypeError):
                    pass
            return

        if line.startswith('CALIBRATE_READY'):
            self._publish(EVENT_CALIBRATION_READY, cid,
                          {'name': ch.name})
            return

        if line == 'START':
            self._publish(EVENT_CHANNEL_STATE, cid,
                          {'connected': True, 'message': '设备就绪'})
            return

        super()._handle_line(cid, line)

    # ---------------- 快照 / 导出 ----------------
    def ai_data(self):
        active = [ch for ch in self.channels if ch.force_data]
        if not active:
            return None
        main = max(active, key=lambda c: len(c.force_data))
        display = ([self.convert_unit(v) for v in main.force_data]
                   if main.calibrated else list(main.force_data))
        channels_desc = '、'.join(
            f"{ch.name}[{len(ch.force_data)}点"
            + (f'/去皮{ch.offset}/标定{ch.scale:.4g}g/计数' if ch.calibrated
               else f'/未校准(零点{ch.offset})') + ']'
            for ch in active)
        return {
            'title': self.title,
            'x_label': self.x_label,
            'y_label': self.chart_ylabel(),
            'points': list(zip(main.time_data, display)),
            'params': (
                f'传感器=HX711（24 位 ADC）+ 应变片, '
                f'主分析通道={main.name}, '
                f'去皮 offset={main.offset}, '
                f'标定 scale={main.scale:.6f} 克/计数, '
                f'砝码质量={self.cal_known_weight}g, '
                f'已校准={main.calibrated}'
                + ('' if main.calibrated else '（未校准时数据为原始 ADC 值）')
                + f', 显示单位={self.current_unit}, 重力加速度 g=9.8m/s², '
                f'原始 ADC 范围=±8388607（24 位有符号）, '
                f'多路连接: 共{len(active)}路（{channels_desc}），'
                f'各路去皮零点与标定系数独立, '
                f'采样间隔={main.sample_interval_ms}ms（各路独立）'),
        }


    def snapshot(self, points=0):
        data = super().snapshot(points)
        main = self.main_channel()
        latest = data.get('latest')
        if latest is not None and main is not None and main.raw_data:
            latest['raw'] = main.raw_data[-1]
        return data

    # ---------------- 命令 ----------------
    def sensor_actions(self):
        return ['tare', 'calibrate',
                'calib_begin', 'calib_record_zero', 'calib_record_known',
                'calib_cancel', 'set_unit']

    def _channel_from_params(self, params):
        cid = params.get('channel_id', params.get('cid'))
        if cid is not None:
            return self.get_channel(cid)
        return self._calib_channel()

    def sensor_command(self, action, params):
        params = params or {}
        if action == 'tare':
            return self.tare()
        if action == 'set_unit':
            return self.set_unit(params.get('unit', params.get('value')))
        if action in ('calibrate', 'calib_begin'):
            ch = self._channel_from_params(params)
            return self.calib_begin(ch.id if ch is not None else None)
        if action == 'calib_record_zero':
            ch = self._channel_from_params(params)
            return self.calib_record_zero(ch.id if ch is not None else None)
        if action == 'calib_record_known':
            ch = self._channel_from_params(params)
            grams = (params.get('grams', params.get('known_grams',
                       params.get('weight'))))
            return self.calib_record_known(
                ch.id if ch is not None else None, grams)
        if action == 'calib_cancel':
            ch = self._channel_from_params(params)
            return self.calib_cancel(ch.id if ch is not None else None)
        return None
