# === MODULE META ===
# icon: V
# name: 电压传感器
# category: physics
# class: VoltageSensorBackend
# ===================

# -*- coding: utf-8 -*-
"""电压传感器 Backend — ADC 电压采集与分压电路换算。

支持两种模式：
  - ESP32 内置 ADC（12bit，0-4095，VREF=3.3V）
  - HX711 24bit 有符号 ADC（通道 A 增益 128 / 通道 B 增益 32，AVDD=5.0V）

固件输出格式：`timestamp_ms,adc_raw`（CSV）。
本 Backend 负责解析、采样频率控制、电压换算（按分压比/放大倍数/去皮/单位）、统计与持久化。
"""

from PySide6.QtCore import Slot, Property, Signal

from backends.backend_base import BackendBase


class VoltageSensorBackend(BackendBase):
    """电压传感器 Backend。"""

    # ESP32 内置 ADC 参数
    VREF = 3.3              # ESP32 ADC 参考电压（V）
    ADC_MAX_ESP32 = 4095    # 12bit 满量程

    # HX711 参数
    HX711_AVDD = 5.0                # HX711 模块 AVDD 电压（V）
    HX711_HALFSCALE = 8388608.0     # 2^23，24bit 有符号半量程

    # 显示单位换算因子（内部 voltage_data 始终以 V 计算，按单位转换为显示值）
    UNIT_FACTORS = {'kV': 0.001, 'V': 1.0, 'mV': 1000.0}

    # === QML 可监听的信号 ===
    unitChanged = Signal()
    adcModeChanged = Signal()
    hx711ChannelChanged = Signal()
    hx711GainChanged = Signal()
    dividerRatioChanged = Signal()
    amplifierGainChanged = Signal()
    tareOffsetChanged = Signal()

    def __init__(self, parent=None):
        # 先初始化内部状态（super().__init__ 会触发 _apply_loaded_config 覆写）
        self._adc_mode = 'esp32'
        self._hx711_channel = 'A'
        self._hx711_gain = 128
        self._divider_ratio = 1.0
        self._amplifier_gain = 1.0
        self._unit = 'V'
        self._tare_offset = 0.0
        self._last_raw = None
        self._start_timestamp_ms = 0

        super().__init__('voltage_sensor', parent=parent)

    # ---------------- 子类覆写：配置持久化 ----------------
    def _apply_loaded_config(self):
        cfg = self._config or {}
        mode = cfg.get('adc_mode', 'esp32')
        self._adc_mode = mode if mode in ('esp32', 'hx711') else 'esp32'
        ch = cfg.get('hx711_channel', 'A')
        self._hx711_channel = ch if ch in ('A', 'B') else 'A'
        gain = int(cfg.get('hx711_gain', 128))
        self._hx711_gain = gain if gain in (128, 32) else 128
        self._divider_ratio = float(cfg.get('divider_ratio', 1.0)) or 1.0
        self._amplifier_gain = float(cfg.get('amplifier_gain', 1.0)) or 1.0
        unit = cfg.get('unit', 'V')
        self._unit = unit if unit in ('kV', 'V', 'mV') else 'V'
        self._tare_offset = float(cfg.get('tare_offset', 0.0))

    def _collect_config_dict(self) -> dict:
        return {
            'adc_mode': self._adc_mode,
            'hx711_channel': self._hx711_channel,
            'hx711_gain': self._hx711_gain,
            'divider_ratio': self._divider_ratio,
            'amplifier_gain': self._amplifier_gain,
            'unit': self._unit,
            'tare_offset': self._tare_offset,
        }

    # ---------------- 子类覆写：解析与 CSV ----------------
    def parse_line(self, line: str):
        """解析 `timestamp_ms,adc_raw` 一行。

        返回 (relative_time_s, value_in_current_unit, display_text)。
        """
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

        # 第一个点记录起始时间戳，后续转为相对秒
        if self._start_timestamp_ms == 0:
            self._start_timestamp_ms = timestamp_ms
        relative_time_s = (timestamp_ms - self._start_timestamp_ms) / 1000.0

        # 电压换算：ADC 端电压 → 实际电压（分压比/放大倍数还原）→ 去皮
        v_adc = self._adc_to_vadc(raw_value)
        voltage_v = v_adc * self._divider_ratio / self._amplifier_gain
        voltage_v -= self._tare_offset

        # 按当前单位换算
        factor = self.UNIT_FACTORS.get(self._unit, 1.0)
        value_in_unit = voltage_v * factor

        display = (
            f"ADC: {raw_value} | ADC端: {v_adc:.4f}V | "
            f"电压: {value_in_unit:.4g} {self._unit}"
        )
        return (relative_time_s, value_in_unit, display)

    def _adc_to_vadc(self, raw_value: int) -> float:
        """计算 ADC 输入端电压（未做分压/放大还原）。"""
        if self._adc_mode == 'hx711':
            gain = self._hx711_gain if self._hx711_gain in (128, 32) else 128
            return raw_value / self.HX711_HALFSCALE * (self.HX711_AVDD / gain)
        # ESP32 12bit ADC
        return (raw_value / self.ADC_MAX_ESP32) * self.VREF

    def build_csv_header(self) -> str:
        return (
            f"# PhysChem-DigitizerP 电压传感器数据导出\n"
            f"# ADC 模式: {self._adc_mode}\n"
            f"# HX711 通道: {self._hx711_channel} | 增益: {self._hx711_gain}\n"
            f"# 分压比: {self._divider_ratio} | 放大倍数: {self._amplifier_gain}\n"
            f"# 单位: {self._unit} | 去皮偏移: {self._tare_offset} V\n"
            f"# 采样间隔: {self._sample_interval_ms}ms\n"
            f"timestamp_s,voltage_{self._unit.lower()}\n"
        )

    # ---------------- 采集起始时间戳重置 ----------------
    def startCollecting(self):
        self._start_timestamp_ms = 0
        super().startCollecting()

    # ---------------- QML 调用 Slot ----------------
    @Slot(str)
    def setAdcMode(self, mode: str):
        if mode not in ('esp32', 'hx711'):
            return
        if self._adc_mode != mode:
            self._adc_mode = mode
            self.adcModeChanged.emit()
            self.saveConfig()

    @Slot(str)
    def setHx711Channel(self, ch: str):
        if ch not in ('A', 'B'):
            return
        if self._hx711_channel != ch:
            self._hx711_channel = ch
            # 通道与增益联动：A=128，B=32
            new_gain = 128 if ch == 'A' else 32
            if self._hx711_gain != new_gain:
                self._hx711_gain = new_gain
                self.hx711GainChanged.emit()
            self.hx711ChannelChanged.emit()
            self.saveConfig()

    @Slot(int)
    def setHx711Gain(self, gain: int):
        if gain not in (128, 32):
            return
        if self._hx711_gain != gain:
            self._hx711_gain = gain
            # 通道与增益联动：128→A，32→B
            new_ch = 'A' if gain == 128 else 'B'
            if self._hx711_channel != new_ch:
                self._hx711_channel = new_ch
                self.hx711ChannelChanged.emit()
            self.hx711GainChanged.emit()
            self.saveConfig()

    @Slot(float)
    def setDividerRatio(self, r: float):
        if r <= 0:
            return
        if self._divider_ratio != r:
            self._divider_ratio = r
            self.dividerRatioChanged.emit()
            self.saveConfig()

    @Slot(float)
    def setAmplifierGain(self, g: float):
        if g <= 0:
            return
        if self._amplifier_gain != g:
            self._amplifier_gain = g
            self.amplifierGainChanged.emit()
            self.saveConfig()

    @Slot(str)
    def setUnit(self, unit: str):
        if unit not in ('kV', 'V', 'mV'):
            return
        if self._unit != unit:
            self._unit = unit
            self.unitChanged.emit()
            self.saveConfig()

    @Slot()
    def performTare(self):
        """用当前 _last_raw 设为零点偏移。"""
        if self._last_raw is None:
            self.errorOccurred.emit("暂无数据，无法去皮")
            return
        v_adc = self._adc_to_vadc(self._last_raw)
        offset = v_adc * self._divider_ratio / self._amplifier_gain
        self._tare_offset = offset
        self.tareOffsetChanged.emit()
        self.saveConfig()
        shown = offset * self.UNIT_FACTORS.get(self._unit, 1.0)
        self._append_log(
            f"去皮: 偏移 {offset:.6f} V ({shown:.4g} {self._unit})"
        )

    # ---------------- QML 只读 Property ----------------
    def _unit_getter(self):
        return self._unit
    currentUnit = Property(str, _unit_getter, notify=unitChanged)

    def _adc_mode_getter(self):
        return self._adc_mode
    adcMode = Property(str, _adc_mode_getter, notify=adcModeChanged)

    def _hx711_channel_getter(self):
        return self._hx711_channel
    hx711Channel = Property(str, _hx711_channel_getter, notify=hx711ChannelChanged)

    def _hx711_gain_getter(self):
        return self._hx711_gain
    hx711Gain = Property(int, _hx711_gain_getter, notify=hx711GainChanged)

    def _divider_ratio_getter(self):
        return self._divider_ratio
    dividerRatio = Property(float, _divider_ratio_getter, notify=dividerRatioChanged)

    def _amplifier_gain_getter(self):
        return self._amplifier_gain
    amplifierGain = Property(float, _amplifier_gain_getter, notify=amplifierGainChanged)

    def _tare_offset_getter(self):
        return self._tare_offset
    tareOffset = Property(float, _tare_offset_getter, notify=tareOffsetChanged)
