# === MODULE META ===
# icon: A
# name: 电流传感器
# category: physics
# class: CurrentSensorBackend
# ===================

# -*- coding: utf-8 -*-
"""电流传感器 Backend — ACS712 霍尔电流传感器。

ACS712 工作原理：
  - 供电 VCC（典型 5V），零电流时输出 = VCC/2（约 2.5V）
  - 输出电压随电流线性变化：Vout = VCC/2 + I * 灵敏度
  - 三种量程灵敏度：5A→185mV/A，20A→100mV/A，30A→66mV/A
  - 可测交直流；交流时取滚动窗口 RMS

固件输出格式：`timestamp_ms,adc_raw`（CSV）。
本 Backend 负责解析、采样频率控制、电流换算、统计与持久化。
"""

from PySide6.QtCore import Slot, Property, Signal

from backends.backend_base import BackendBase


class CurrentSensorBackend(BackendBase):
    """电流传感器 Backend（ACS712）。"""

    # === QML 可监听信号 ===
    unitChanged = Signal()
    acsRangeChanged = Signal()

    # ESP32 ADC 参考电压
    VREF = 3.3

    # ACS712 量程 → 灵敏度（V/A）映射
    _RANGE_SENSITIVITY = {5: 0.185, 20: 0.100, 30: 0.066}

    # 显示单位换算因子（相对安培）
    _UNIT_FACTORS = {'A': 1.0, 'mA': 1000.0}

    def __init__(self, parent=None):
        # 内部状态默认值（_apply_loaded_config 会覆盖）
        self._acs_range = 5
        self._sensitivity = 0.185
        self._current_mode = 'DC'
        self._v_quiescent = 2.5
        self._divider_ratio = 1.0
        self._current_unit = 'A'
        self._adc_bits = 12
        self._vcc = 5.0
        self._ac_rms_window = 50

        # 运行时缓冲
        self._last_raw = 0
        self._start_timestamp_ms = 0
        self._ac_window_buffer: list[float] = []

        super().__init__('current_sensor', parent=parent)

    # ---------------- 子类覆写 ----------------
    def _apply_loaded_config(self):
        cfg = self._config or {}
        if 'acs_range' in cfg:
            try:
                self._acs_range = int(cfg['acs_range'])
            except (TypeError, ValueError):
                pass
        if 'sensitivity' in cfg:
            try:
                self._sensitivity = float(cfg['sensitivity'])
            except (TypeError, ValueError):
                self._sensitivity = self._sensitivity_for_range(self._acs_range)
        else:
            self._sensitivity = self._sensitivity_for_range(self._acs_range)
        if 'current_mode' in cfg and cfg['current_mode'] in ('DC', 'AC'):
            self._current_mode = cfg['current_mode']
        if 'v_quiescent' in cfg:
            try:
                self._v_quiescent = float(cfg['v_quiescent'])
            except (TypeError, ValueError):
                pass
        if 'divider_ratio' in cfg:
            try:
                self._divider_ratio = float(cfg['divider_ratio'])
            except (TypeError, ValueError):
                pass
        if 'current_unit' in cfg and cfg['current_unit'] in ('A', 'mA'):
            self._current_unit = cfg['current_unit']
        if 'adc_bits' in cfg:
            try:
                self._adc_bits = int(cfg['adc_bits'])
            except (TypeError, ValueError):
                pass
        if 'vcc' in cfg:
            try:
                self._vcc = float(cfg['vcc'])
            except (TypeError, ValueError):
                pass
        if 'ac_rms_window' in cfg:
            try:
                self._ac_rms_window = int(cfg['ac_rms_window'])
            except (TypeError, ValueError):
                pass
        if 'sample_interval_ms' in cfg:
            try:
                self._sample_interval_ms = int(cfg['sample_interval_ms'])
            except (TypeError, ValueError):
                pass

    def _collect_config_dict(self) -> dict:
        return {
            'acs_range': self._acs_range,
            'sensitivity': self._sensitivity,
            'current_mode': self._current_mode,
            'v_quiescent': self._v_quiescent,
            'divider_ratio': self._divider_ratio,
            'current_unit': self._current_unit,
            'adc_bits': self._adc_bits,
            'vcc': self._vcc,
            'ac_rms_window': self._ac_rms_window,
        }

    def parse_line(self, line: str):
        """解析 `timestamp_ms,adc_raw` 一行，返回 (timestamp_s, value_in_unit, display_text)。"""
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

        # 起始时间戳
        if self._start_timestamp_ms == 0:
            self._start_timestamp_ms = timestamp_ms
        self._last_raw = raw_value

        relative_time_s = (timestamp_ms - self._start_timestamp_ms) / 1000.0

        # ADC 原始值 → 传感器输出电压（扣除分压）→ 电流（A）
        v_adc = self._adc_to_vadc(raw_value)
        v_sensor = self._adc_to_vsensor(raw_value)
        current_a = (v_sensor - self._v_quiescent) / self._sensitivity if self._sensitivity else 0.0

        # AC 模式：维护滚动窗口并取 RMS
        if self._current_mode == 'AC':
            self._ac_window_buffer.append(current_a)
            if len(self._ac_window_buffer) > self._ac_rms_window:
                self._ac_window_buffer.pop(0)
            val_a = self._compute_rms() or current_a
        else:
            val_a = current_a

        val_in_unit = val_a * self._unit_factor()
        display = (
            f"ADC {raw_value} | ADC端 {v_adc:.4f}V | 传感器 {v_sensor:.4f}V | "
            f"电流 {self._format_value(val_a)} {self._current_unit}"
        )
        return (relative_time_s, val_in_unit, display)

    def build_csv_header(self) -> str:
        return (
            f"# PhysChem-DigitizerP 电流传感器数据导出\n"
            f"# ACS712 量程={self._acs_range}A 灵敏度={self._sensitivity}V/A "
            f"零点={self._v_quiescent:.4f}V 分压比={self._divider_ratio:.4f} "
            f"模式={self._current_mode} 单位={self._current_unit}\n"
            f"timestamp_s,current_{self._current_unit.lower()}\n"
        )

    # ---------------- 采集控制（重置内部缓冲） ----------------
    def startCollecting(self):
        self._start_timestamp_ms = 0
        self._ac_window_buffer.clear()
        self._last_raw = 0
        super().startCollecting()

    # ---------------- 内部计算 ----------------
    def _sensitivity_for_range(self, range_a: int) -> float:
        return self._RANGE_SENSITIVITY.get(range_a, 0.185)

    def _unit_factor(self) -> float:
        return self._UNIT_FACTORS.get(self._current_unit, 1.0)

    def _adc_to_vadc(self, adc_value: int) -> float:
        max_adc = (1 << self._adc_bits) - 1
        if max_adc <= 0:
            return 0.0
        return (adc_value / max_adc) * self.VREF

    def _adc_to_vsensor(self, adc_value: int) -> float:
        return self._adc_to_vadc(adc_value) * self._divider_ratio

    def _compute_rms(self):
        """计算 AC 模式下滚动窗口的电流 RMS（安培）。"""
        buf = self._ac_window_buffer
        if not buf:
            return None
        s = sum(x * x for x in buf)
        return (s / len(buf)) ** 0.5

    def _format_value(self, current_a: float) -> str:
        """按当前单位格式化数值（不带单位后缀）。"""
        c = current_a * self._unit_factor()
        if self._current_unit == 'mA':
            return f"{c:.2f}"
        abs_c = abs(c)
        if abs_c >= 1.0:
            return f"{c:.4f}"
        return f"{c:.6f}"

    # ---------------- QML 调用 Slot ----------------
    @Slot(int)
    def setAcsRange(self, range_val: int):
        """设置 ACS712 量程（5/20/30），自动更新灵敏度。"""
        if range_val not in (5, 20, 30):
            return
        if self._acs_range != range_val:
            self._acs_range = range_val
            self._sensitivity = self._sensitivity_for_range(range_val)
            self.acsRangeChanged.emit()
            self.saveConfig()
            self._append_log(
                f"量程切换为 {range_val}A，灵敏度 {self._sensitivity * 1000:.0f}mV/A"
            )

    @Slot(str)
    def setCurrentMode(self, mode: str):
        """设置测量模式（'DC' 或 'AC'）。"""
        if mode not in ('DC', 'AC'):
            return
        if self._current_mode != mode:
            self._current_mode = mode
            self._ac_window_buffer.clear()
            self.saveConfig()
            self._append_log(f"测量模式切换为 {mode}")

    @Slot(float)
    def setVQuiescent(self, v: float):
        """手动设置零点电压（V）。"""
        self._v_quiescent = float(v)
        self.saveConfig()
        self._append_log(f"零点电压已设置为 {self._v_quiescent:.4f}V")

    @Slot(float)
    def setDividerRatio(self, r: float):
        """设置分压比 (R1+R2)/R2。"""
        if r <= 0:
            return
        self._divider_ratio = float(r)
        self.saveConfig()
        self._append_log(f"分压比已设置为 {self._divider_ratio:.4f}")

    @Slot(str)
    def setCurrentUnit(self, unit: str):
        """设置显示单位（'A' 或 'mA'）。"""
        if unit not in ('A', 'mA'):
            return
        if self._current_unit != unit:
            self._current_unit = unit
            self.unitChanged.emit()
            self.saveConfig()
            self._append_log(f"显示单位切换为 {unit}")

    @Slot()
    def performZeroCalibration(self):
        """用当前 _last_raw 计算传感器输出电压并设为零点。"""
        if self._last_raw == 0 and not self._value_data:
            self.errorOccurred.emit("请先开始采集数据后再进行零点校准")
            return
        v_sensor = self._adc_to_vsensor(self._last_raw)
        self._v_quiescent = float(v_sensor)
        self.saveConfig()
        self._append_log(f"零点校准完成：V_quiescent = {self._v_quiescent:.4f}V")

    # ---------------- QML 只读 Property ----------------
    def _current_unit_getter(self):
        return self._current_unit

    currentUnit = Property(str, _current_unit_getter, notify=unitChanged)

    def _acs_range_getter(self):
        return self._acs_range

    acsRange = Property(int, _acs_range_getter, notify=acsRangeChanged)
