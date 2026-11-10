# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

# -*- coding: utf-8 -*-
"""
core.py — PhysChem-DigitizerP 公共内核

只依赖 Python 标准库（pyserial 为可选依赖），不 import PySide6 / qfluentwidgets。
包含：
- 运行日志（由 core_ui 从 app_config.json 注入开关与级别）
- sensor_config.json 读写
- 串口枚举与串口/模拟器传输
- 事件总线、ChannelSpec / Sample / KernelEvent
- SensorKernel 内核基类
- KernelRegistry 内核注册表（供 Flask / MCP / CLI 直接调用）

公共 UI（主题、字体、ChartPanel、通用控件/对话框）在 core_ui.py。
"""

import os
import sys
import json
import time
import random
import logging
import queue
import threading
from dataclasses import dataclass, field

# pyserial 为可选依赖：未安装时程序仍可运行（模拟器模式不受影响），
# 串口连接相关功能优雅降级（列表为空 + 连接时弹提示装库）
try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    serial = None
    SERIAL_AVAILABLE = False

# ============================================================
# 统一配置管理 — 所有传感器校准配置保存在同一个 JSON 文件
# ============================================================
CONFIG_FILENAME = 'sensor_config.json'

LOG_FILENAME = 'logs.json'
_LOG_LEVELS = {
    'warning': logging.WARNING,
    'info': logging.INFO,
    'debug': logging.DEBUG,
}

#: 应用根 logger：所有代码统一使用 get_logger('模块名') 获取子 logger，
#: 根 logger 默认只挂 NullHandler（避免无 handler 时触发 logging.lastResort
#: 把 WARNING+ 打到 stderr，从而保证「关闭时完全静默」）
_root_log = logging.getLogger('physchem')
_root_log.addHandler(logging.NullHandler())
_root_log.propagate = False

_json_log_handler = None
_console_log_handler = None
_logging_active = False   # 已挂 handler 状态：避免 core/main 两次 setup 重复记录


class _SourceFormatter(logging.Formatter):
    """把 physchem.xxx 命名空间前缀裁掉，只显示模块名。"""

    def format(self, record):
        record.source = record.name.split('.', 1)[-1]
        return super().format(record)


class JsonLinesLogHandler(logging.Handler):
    """把日志逐条追加到 logs.json（JSON Lines，UTF-8，立即 flush）。

    跨会话追加；总行数超出上限（含 10% 余量）时重写文件、只保留最新
    max_entries 条，避免每次写入都裁剪。文件写入加锁，串口等
    后台线程记录同样安全。
    """

    def __init__(self, path, max_entries=5000):
        super().__init__()
        self.path = path
        self.max_entries = self._normalize_max_entries(max_entries)
        self._lock = threading.Lock()
        with self._lock:
            self._count = self._count_lines() if os.path.exists(path) else 0

    @staticmethod
    def _normalize_max_entries(max_entries):
        """配置文件被手工改坏时回退默认值，避免启动即异常。"""
        try:
            return max(100, int(max_entries))
        except (TypeError, ValueError):
            return 5000

    def _count_lines(self):
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                return sum(1 for _ in f)
        except Exception:
            return 0

    def set_max_entries(self, max_entries):
        self.max_entries = self._normalize_max_entries(max_entries)
        with self._lock:
            self._trim(force=True)

    def emit(self, record):
        try:
            entry = {
                'time': time.strftime('%Y-%m-%d %H:%M:%S',
                                      time.localtime(record.created))
                        + f'.{int(record.msecs):03d}',
                'level': record.levelname,
                'source': record.name.split('.', 1)[-1],
                'message': record.getMessage(),
            }
            line = json.dumps(entry, ensure_ascii=False)
            with self._lock:
                with open(self.path, 'a', encoding='utf-8') as f:
                    f.write(line + '\n')
                self._count += 1
                self._trim()
        except Exception:
            self.handleError(record)

    def _trim(self, force=False):
        """裁剪最旧记录（调用方须持有 self._lock）。"""
        margin = max(10, self.max_entries // 10)   # 10% 余量，避免每次写入都重写
        if not force and self._count <= self.max_entries + margin:
            return
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            if len(lines) <= self.max_entries:
                self._count = len(lines)
                return
            lines = lines[-self.max_entries:]
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            os.replace(tmp, self.path)
            self._count = len(lines)
        except Exception:
            pass

#: 日志开关与参数由 core_ui 从 app_config.json 注入；内核本身不依赖 Qt。
_log_enabled = False
_log_level = 'info'
_log_max_entries = 5000
_config_persistence_enabled = True


def set_config_persistence(enabled):
    """由 UI 层注入「保存配置」开关；内核不直接依赖 AppConfig。"""
    global _config_persistence_enabled
    _config_persistence_enabled = bool(enabled)


def _current_log_level():
    # 文件记录未开启时，控制台固定「标准」；开启后才采用用户选择的详细度。
    if not _logging_active:
        return logging.INFO
    return _LOG_LEVELS.get(str(_log_level).lower(), logging.INFO)


def _ensure_log_handlers():
    """创建（懒初始化）控制台与 JSON Lines 两个 handler。"""
    global _console_log_handler, _json_log_handler
    if _console_log_handler is None:
        # stdout 被重定向（管道/文件）时按系统 ANSI 代码页编码（中文系统为
        # GBK），含 '✓' 等非 GBK 字符的记录会抛 UnicodeEncodeError 被整条
        # 丢弃，并向 stderr 刷「--- Logging error ---」回溯。这里把编码错误
        # 策略改为 replace：无法编码的字符替换显示，记录不再丢失；交互式
        # 控制台走 UTF-16 直写（PEP 528），行为完全不受影响。
        try:
            sys.stdout.reconfigure(errors='replace')
        except Exception:
            pass
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(_SourceFormatter(
            '[%(asctime)s.%(msecs)03d] [%(levelname)s] %(source)s: %(message)s',
            '%H:%M:%S'))
        _console_log_handler = h
    if _json_log_handler is None:
        _json_log_handler = JsonLinesLogHandler(
            get_log_file_path(), int(_log_max_entries or 5000))
    return _console_log_handler, _json_log_handler


def set_log_enabled(enabled):
    """切换「写入 logs.json」：控制台始终输出，开关只决定是否落盘。"""
    global _logging_active, _log_enabled
    _log_enabled = bool(enabled)
    console, json_handler = _ensure_log_handlers()
    _root_log.setLevel(logging.DEBUG)
    if console not in _root_log.handlers:
        _root_log.addHandler(console)
    if _log_enabled:
        if json_handler not in _root_log.handlers:
            _root_log.addHandler(json_handler)
        if not _logging_active:
            log.info('运行日志已开始写入 logs.json（级别=%s，最多 %d 条）',
                     _log_level, json_handler.max_entries)
        _logging_active = True
    else:
        if json_handler in _root_log.handlers:
            _root_log.removeHandler(json_handler)
        _logging_active = False
    _apply_log_level()


def set_log_level(level):
    """运行时切换详细度；持久化由 core_ui 负责写 app_config.json。"""
    global _log_level
    level = str(level).lower()
    if level not in _LOG_LEVELS:
        return
    _log_level = level
    _apply_log_level()


def set_log_max_entries(max_entries):
    """运行时调整 logs.json 最大保留条数（立即裁剪超出的旧记录）。"""
    global _log_max_entries
    try:
        _log_max_entries = max(100, int(max_entries))
    except (TypeError, ValueError):
        _log_max_entries = 5000
    if _json_log_handler is not None:
        _json_log_handler.set_max_entries(_log_max_entries)


def setup_logging(enabled=None, level=None, max_entries=None):
    """按 UI 注入的 app_config 值初始化日志。

    无参数调用时保持当前内核默认（控制台输出、不落盘），便于内核独立测试。
    """
    global _log_level, _log_max_entries
    if level is not None:
        _log_level = str(level).lower() if str(level).lower() in _LOG_LEVELS else 'info'
    if max_entries is not None:
        try:
            _log_max_entries = max(100, int(max_entries))
        except (TypeError, ValueError):
            _log_max_entries = 5000
    set_log_enabled(bool(_log_enabled if enabled is None else enabled))

def get_logger(name='core'):
    """获取应用子 logger（如 get_logger('voltage_sensor')）。"""
    return logging.getLogger('physchem.%s' % name) if name else _root_log


#: core.py 自身日志（来源显示为 core；子 logger 通过根 logger 的 handler 输出）
log = get_logger('core')
def get_log_file_path():
    """logs.json 的绝对路径（src/ 源码目录，与 sensor_config.json 同目录）。

    可用环境变量 PHYSCHEM_LOG_FILE 覆盖（自动化测试/多实例隔离用）。
    """
    override = os.environ.get('PHYSCHEM_LOG_FILE')
    if override:
        return override
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), LOG_FILENAME)
def _apply_log_level():
    level = _current_log_level()
    for h in (_console_log_handler, _json_log_handler):
        if h is not None:
            h.setLevel(level)
def _get_config_file_path():
    """获取统一配置文件的绝对路径。

    配置文件始终位于源码目录（即 src/，与 main.py 同级），与具体模块文件位置无关。
    """
    # core.py 与 main.py 同在 src/ 目录，直接用其所在目录。
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, CONFIG_FILENAME)


def load_sensor_config(module_name):
    """从统一配置文件中读取指定模块的配置。

    Args:
        module_name: 模块名称，如 'ph_sensor'、'force_sensor'

    Returns:
        dict: 该模块的配置字典，不存在则返回空字典
    """
    # 持久化开关关闭：不读取旧配置，各模块使用默认值
    if not _config_persistence_enabled:
        log.info("配置保存已关闭，[%s] 跳过读取，使用默认值", module_name)
        return {}

    config_path = _get_config_file_path()
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                all_config = json.load(f)
            module_config = all_config.get(module_name, {})
            if module_config:
                log.info("✓ 已加载 [%s] 配置", module_name)
            else:
                log.info("[%s] 无已保存配置，使用默认值", module_name)
            return module_config
        else:
            log.info("配置文件不存在：%s，所有模块使用默认值", config_path)
            return {}
    except Exception as e:
        log.warning("读取配置文件失败：%s", e)
        return {}


def save_sensor_config(module_name, config_dict):
    """将指定模块的配置写入统一配置文件。

    Args:
        module_name: 模块名称，如 'ph_sensor'、'force_sensor'
        config_dict: 该模块的配置字典

    Returns:
        bool: 是否保存成功
    """
    # 持久化开关关闭：静默丢弃写入（视为成功，避免 UI 报保存失败），
    # 更改仅保留在各模块内存中，退出程序后销毁
    if not _config_persistence_enabled:
        return True

    config_path = _get_config_file_path()
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                all_config = json.load(f)
        else:
            all_config = {}

        all_config[module_name] = config_dict

        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(all_config, f, ensure_ascii=False, indent=2)

        log.info("[%s] 配置已保存到 %s", module_name, config_path)
        return True
    except Exception as e:
        log.warning("保存 [%s] 配置失败: %s", module_name, e)
        return False


def export_sensor_config(target_dir):
    """将 sensor_config.json 导出到指定目录。

    由设置页「导出配置」调用（系统文件夹选择对话框）。

    Args:
        target_dir: 目标目录路径（用户通过 QFileDialog 选择）

    Returns:
        tuple[bool, str]: (是否成功, 消息文件路径或错误描述)
    """
    import shutil
    config_path = _get_config_file_path()
    if not os.path.exists(config_path):
        return False, "配置文件不存在，无需导出"
    try:
        dest = os.path.join(target_dir, CONFIG_FILENAME)
        shutil.copy2(config_path, dest)
        log.info("配置已导出到 %s", dest)
        return True, dest
    except Exception as e:
        log.warning("导出配置失败: %s", e)
        return False, str(e)


def import_sensor_config(source_file):
    """从指定文件导入 sensor_config.json，覆盖当前配置。

    由设置页「导入配置」调用（系统文件选择对话框）。

    Args:
        source_file: 源文件路径（用户通过 QFileDialog 选择的 .json 文件）

    Returns:
        tuple[bool, str]: (是否成功, 消息描述)
    """
    try:
        with open(source_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError:
        return False, "文件格式错误，不是有效的 JSON 文件"
    except Exception as e:
        return False, f"读取文件失败: {e}"

    if not isinstance(data, dict):
        return False, "文件内容格式错误，期望 JSON 对象"

    config_path = _get_config_file_path()
    try:
        # 先写临时文件再重命名，避免 Windows 文件锁导致 PermissionError
        import tempfile
        dir_name = os.path.dirname(config_path)
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, config_path)
        except Exception:
            # 清理临时文件
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        log.info("配置已从 %s 导入到 %s", source_file, config_path)
        return True, f"已导入 {len(data)} 个模块的配置"
    except Exception as e:
        log.warning("导入配置失败: %s", e)
        return False, f"写入配置文件失败: {e}"


def clear_sensor_config():
    """删除统一配置文件 sensor_config.json，所有校准配置恢复默认值。

    由设置页「清除用户设置」调用（确认框后）。
    已加载模块内存中的配置不受影响，重启程序后全部使用默认值。

    Returns:
        bool: 是否成功（文件本就不存在也视为成功）
    """
    config_path = _get_config_file_path()
    try:
        if os.path.exists(config_path):
            os.remove(config_path)
            log.info("已清除用户配置文件：%s", config_path)
        else:
            log.info("配置文件不存在，无需清除")
        return True
    except Exception as e:
        log.warning("清除配置文件失败: %s", e)
        return False




def list_serial_ports():
    """枚举可用串口，返回 [(device, description), ...]。

    pyserial 未安装时返回空列表（调用方据此提示安装），
    其余情况任何异常都吞掉返回空列表，避免刷新按钮崩溃。
    """
    if not SERIAL_AVAILABLE:
        return []
    try:
        return [(p.device, p.description or "") for p in serial.tools.list_ports.comports()]
    except Exception as e:
        log.error("枚举串口失败: %s", e)
        return []


def serial_unavailable_hint():
    """pyserial 未安装时的用户提示文案（供各模块弹窗使用）。"""
    return "未安装 pyserial，串口连接不可用。\n\n请安装后重启程序：\npip install pyserial\n\n提示：当前仍可使用「模拟器」模式体验全部功能。"


# ============================================================
# 内核公共层（纯 Python）
#
# 这一层的职责是把“设备通信 / 采样 / 缓存 / 事件”从 QWidget 中拿出来。
# 传感器 _kernel.py 只依赖这里的纯 API；View 只依赖上面的 UI 公共区。
# core.py 本身不依赖 Qt；View / ChartPanel / 通用控件等 UI 侧代码见 core_ui.py。
# ============================================================

#: 内核事件类型
EVENT_SAMPLE_PREVIEW = 'sample_preview'
EVENT_SAMPLE_RECORDED = 'sample_recorded'
EVENT_CHANNEL_STATE = 'channel_state'
EVENT_COLLECTION_CHANGED = 'collection_changed'
EVENT_CHANNELS_CHANGED = 'channels_changed'
EVENT_ERROR = 'error'


@dataclass
class ChannelSpec:
    """一路连接的最小配置（可持久化部分）。"""
    id: int
    name: str
    color: str
    mode: str = 'serial'          # serial | simulator
    port: str = ''
    sample_interval_ms: int = 100
    visible: bool = True
    sensor_params: dict = field(default_factory=dict)


@dataclass
class Sample:
    """内核里的一个样本。"""
    channel_id: int
    seq: int
    t: float
    raw: float
    value: float


@dataclass
class KernelEvent:
    """内核向前端推送的事件。"""
    kind: str
    channel_id: int | None = None
    data: dict = field(default_factory=dict)


class EventSubscription:
    """一个订阅者的有界事件队列。

    - 后台线程只 put，不碰 Qt；
    - View/TUI/CLI 在自己的线程里 get/drain；
    - 队列满时优先丢弃 sample_preview，保留状态/错误事件。
    """

    def __init__(self, maxsize=1024):
        self._queue = queue.Queue(maxsize=max(1, int(maxsize)))
        self._closed = False

    def put(self, event):
        if self._closed:
            return
        try:
            self._queue.put_nowait(event)
            return
        except queue.Full:
            pass
        if event.kind == EVENT_SAMPLE_PREVIEW:
            return
        # 状态/错误事件优先：丢掉最旧的一条，再尝试放入
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            pass

    def get(self, timeout=None):
        return self._queue.get(timeout=timeout)

    def get_nowait(self):
        return self._queue.get_nowait()

    def drain(self, limit=200):
        """一次取出最多 limit 条事件（GUI 线程用）。"""
        out = []
        for _ in range(max(0, int(limit))):
            try:
                out.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return out

    def close(self):
        self._closed = True
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

    def __iter__(self):
        while True:
            event = self.get()
            if event is None:
                return
            yield event


class EventBus:
    """内核事件总线：多个前端可以同时订阅。"""

    def __init__(self):
        self._subs = []
        self._lock = threading.Lock()

    def subscribe(self, maxsize=1024):
        sub = EventSubscription(maxsize)
        with self._lock:
            self._subs.append(sub)
        return sub

    def publish(self, event):
        with self._lock:
            subs = list(self._subs)
        for sub in subs:
            sub.put(event)

    def close(self):
        with self._lock:
            subs = list(self._subs)
            self._subs = []
        for sub in subs:
            sub.close()


class _CallbackTransport:
    """普通 threading.Thread 传输基类（不依赖 QThread）。"""

    def __init__(self):
        self._thread = None
        # 初始即为运行态：stop() 先于 run() 执行时不会被覆盖（沿用旧版约定）
        self.running = True

    def start(self):
        # 不重置 running：若 stop() 先于 start() 执行，run() 首行会立即退出
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False
        self._join()

    def _join(self, timeout=2.0):
        t = self._thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout)

    def is_running(self):
        t = self._thread
        return bool(self.running and t is not None and t.is_alive())

    # 兼容旧 View 的 QThread 风格调用
    def isRunning(self):
        return self.is_running()

    def send(self, data):
        """向设备写数据；只有真实串口实现。"""
        return False

    def _run(self):
        raise NotImplementedError


class SerialTransport(_CallbackTransport):
    """真实串口传输：普通后台线程，回调字符串行。"""

    def __init__(self, port, baudrate=115200, on_line=None):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.on_line = on_line
        self.serial = None

    def _emit(self, line):
        if self.on_line is not None:
            try:
                self.on_line(line)
            except Exception as e:
                log.error("SerialTransport 回调失败: %s", e)

    def _run(self):
        if not SERIAL_AVAILABLE:
            self._emit("ERROR:pyserial 未安装")
            return
        if not self.running:
            return
        try:
            self.serial = serial.Serial(self.port, self.baudrate, timeout=1)
            if not self.running:
                try:
                    self.serial.close()
                except Exception:
                    pass
                return
            self.serial.reset_input_buffer()
            log.info("串口已打开: %s", self.port)
            while self.running:
                try:
                    if self.serial.in_waiting > 0:
                        line = self.serial.readline().decode(
                            'utf-8', errors='ignore').strip()
                        if line:
                            self._emit(line)
                    else:
                        time.sleep(0.01)
                except Exception as e:
                    log.error("读取串口数据错误: %s", e)
                    break
        except Exception as e:
            log.error("串口错误: %s", e)
            self._emit(f"ERROR:{e}")
        finally:
            try:
                if self.serial and self.serial.is_open:
                    self.serial.close()
            except Exception:
                pass

    def stop(self):
        self.running = False
        try:
            if self.serial:
                self.serial.close()
        except Exception:
            pass
        self._join()

    def send(self, data):
        try:
            ser = self.serial
            if ser and ser.is_open:
                ser.write(data)
                return True
        except Exception as e:
            log.warning("串口写入失败: %s", e)
        return False


class SimulatorTransport(_CallbackTransport):
    """模拟器传输：输出格式与固件一致，先发 START，再发 timestamp,raw。"""

    def __init__(self, value_min=0, value_max=4095, interval_ms=100,
                 start_value=None, timestamp_scale=1, on_line=None):
        super().__init__()
        self.value_min = int(value_min)
        self.value_max = int(value_max)
        self.interval_ms = max(10, int(interval_ms))
        self.timestamp_scale = max(1, int(timestamp_scale))
        self.on_line = on_line
        span = self.value_max - self.value_min
        self._value = (float(start_value) if start_value is not None
                       else self.value_min + span / 2.0)
        self._drift_step = max(1.0, span * 0.005)
        self._noise_amp = max(1.0, span * 0.01)

    def _emit(self, line):
        if self.on_line is not None:
            try:
                self.on_line(line)
            except Exception as e:
                log.error("SimulatorTransport 回调失败: %s", e)

    def _run(self):
        if not self.running:
            return
        self._emit("START")
        start_s = time.time()
        while self.running:
            self._value += random.uniform(-self._drift_step, self._drift_step)
            if self._value < self.value_min:
                self._value = self.value_min + abs(self._value - self.value_min) * 0.5
            elif self._value > self.value_max:
                self._value = self.value_max - abs(self._value - self.value_max) * 0.5
            raw = self._value + random.uniform(-self._noise_amp, self._noise_amp)
            raw = int(round(max(self.value_min, min(self.value_max, raw))))
            elapsed = int((time.time() - start_s) * 1000 * self.timestamp_scale)
            self._emit(f"{elapsed},{raw}")
            slept = 0.0
            while self.running and slept < self.interval_ms / 1000.0:
                time.sleep(0.02)
                slept += 0.02

    def stop(self):
        self.running = False
        self._join()


#: 退出清理时未在限时内结束的普通线程（保活引用，避免被 Python 回收）
_retired_transports = []


def stop_transport(transport, timeout=2000, name="通信线程"):
    """停止普通线程传输并限时等待；超时的保留引用。"""
    if transport is None:
        return
    try:
        transport.stop()
    except Exception as e:
        log.warning("停止%s失败: %s", name, e)
    t = getattr(transport, '_thread', None)
    if t is not None and t.is_alive() and t is not threading.current_thread():
        try:
            t.join(timeout / 1000.0)
        except Exception as e:
            log.warning("等待%s退出失败: %s", name, e)
        if t.is_alive():
            log.warning("%s未在 %dms 内退出，保留引用", name, timeout)
            _retired_transports.append(transport)


class SensorKernel:
    """多路传感器内核基类。

    子类只需要实现物理差异：
    - load_config / save_config
    - make_channel
    - decode_line / convert
    - simulator_spec
    - append_sample / channel_values
    - ai_data / channel_info / csv_text
    - sensor_actions / sensor_command
    """

    key = ''
    title = ''
    x_label = '时间 (秒)'
    y_label = ''

    def __init__(self):
        self.channels = []
        self.collecting = False
        self.sample_interval_ms = 100
        self._t0_mono = None
        self._seq = 0
        self._next_channel_id = 1
        self._next_channel_seq = 1
        self._lock = threading.RLock()
        self._bus = EventBus()

    # ---------------- 子类钩子 ----------------
    def load_config(self):
        return {}

    def save_config(self):
        return True

    def make_channel(self, color=None, mode='serial', port='', name=None,
                     sample_interval_ms=None, visible=True, **params):
        raise NotImplementedError

    def decode_line(self, line, channel):
        raise NotImplementedError

    def convert(self, channel, raw):
        raise NotImplementedError

    def simulator_spec(self, channel):
        """返回 SimulatorTransport 参数 dict；None 表示不支持模拟器。"""
        return None

    def append_sample(self, channel, t, raw, value):
        channel.time_data.append(t)
        channel.raw_data.append(raw)
        channel.value_data.append(value)

    def clear_channel_data(self, channel):
        channel.time_data.clear()
        channel.raw_data.clear()
        channel.value_data.clear()
        channel.last_sample_s = None

    def channel_values(self, channel):
        return channel.value_data

    def channel_info(self, channel):
        values = self.channel_values(channel)
        return {
            'id': channel.id,
            'name': channel.name,
            'color': channel.color,
            'mode': channel.mode,
            'port': channel.port,
            'sample_interval_ms': channel.sample_interval_ms,
            'visible': channel.visible,
            'connected': bool(getattr(channel, 'connected', False)),
            'points_n': len(values),
            'latest_raw': (channel.raw_data[-1]
                           if getattr(channel, 'raw_data', None) else None),
        }

    def ai_data(self):
        return None

    def csv_text(self):
        return ''

    def sensor_actions(self):
        return []

    def sensor_command(self, action, params):
        return None

    # ---------------- 事件 ----------------
    def subscribe(self, callback=None, maxsize=1024):
        sub = self._bus.subscribe(maxsize)
        if callback is not None:
            def _consume():
                for event in sub:
                    try:
                        callback(event)
                    except Exception as e:
                        log.error("内核事件回调失败: %s", e)
            threading.Thread(target=_consume, daemon=True).start()
        return sub

    def _publish(self, kind, channel_id=None, data=None):
        self._bus.publish(KernelEvent(kind, channel_id, data or {}))

    # ---------------- 通道 ----------------
    def get_channel(self, cid):
        for ch in self.channels:
            if ch.id == cid:
                return ch
        return None

    def add_channel(self, color=None, mode='serial', port='', name=None,
                    sample_interval_ms=None, visible=True, **params):
        ch = self.make_channel(
            color=color, mode=mode, port=port, name=name,
            sample_interval_ms=sample_interval_ms, visible=visible, **params)
        self.channels.append(ch)
        self.save_config()
        self._publish(EVENT_CHANNELS_CHANGED)
        return ch

    def update_channel(self, cid, **fields):
        ch = self.get_channel(cid)
        if ch is None:
            return False
        for k, v in fields.items():
            if hasattr(ch, k):
                setattr(ch, k, v)
        self.save_config()
        self._publish(EVENT_CHANNELS_CHANGED, cid)
        return True

    def remove_channel(self, cid):
        ch = self.get_channel(cid)
        if ch is None:
            return False
        if getattr(ch, 'connected', False):
            self.disconnect(cid)
        self.channels.remove(ch)
        self.save_config()
        self._publish(EVENT_CHANNELS_CHANGED)
        return True

    def is_connected(self, cid):
        ch = self.get_channel(cid)
        return bool(ch and getattr(ch, 'connected', False))

    def connected_any(self):
        return any(getattr(ch, 'connected', False) for ch in self.channels)

    # ---------------- 连接 ----------------
    def _make_transport(self, channel):
        if channel.mode == 'simulator':
            spec = self.simulator_spec(channel) or {}
            return SimulatorTransport(on_line=None, **spec)
        if not SERIAL_AVAILABLE:
            raise RuntimeError(serial_unavailable_hint())
        port = (channel.port or '').strip()
        if not port or '未安装' in port or '无可用' in port:
            raise RuntimeError('请先选择串口')
        return SerialTransport(port)

    def connect(self, cid):
        ch = self.get_channel(cid)
        if ch is None:
            return {'ok': False, 'error': 'channel_not_found',
                    'message': '通道不存在'}
        if getattr(ch, 'connected', False):
            return {'ok': True, 'message': f'{ch.name} 已连接'}
        try:
            transport = self._make_transport(ch)
        except Exception as e:
            return {'ok': False, 'error': 'connect_failed', 'message': str(e)}
        transport.on_line = lambda line, cid=cid: self._handle_line(cid, line)
        ch.thread = transport
        ch.connected = True
        try:
            transport.start()
        except Exception as e:
            ch.thread = None
            ch.connected = False
            return {'ok': False, 'error': 'connect_failed',
                    'message': f'{ch.name} 连接失败: {e}'}
        self._publish(EVENT_CHANNEL_STATE, cid,
                      {'connected': True, 'message': '已连接'})
        return {'ok': True, 'message': f'{ch.name} 已连接'}

    def disconnect(self, cid):
        ch = self.get_channel(cid)
        if ch is None:
            return {'ok': False, 'error': 'channel_not_found',
                    'message': '通道不存在'}
        transport = getattr(ch, 'thread', None)
        if transport is not None:
            stop_transport(transport, name=f'{self.title}{ch.name}线程')
        ch.thread = None
        ch.connected = False
        self._publish(EVENT_CHANNEL_STATE, cid,
                      {'connected': False, 'message': '已断开'})
        return {'ok': True, 'message': f'{ch.name} 已断开'}

    def connect_all(self):
        for ch in list(self.channels):
            if not getattr(ch, 'connected', False):
                self.connect(ch.id)

    def disconnect_all(self):
        for ch in list(self.channels):
            if getattr(ch, 'connected', False) or getattr(ch, 'thread', None):
                self.disconnect(ch.id)

    # ---------------- 采集 ----------------
    def start_collection(self):
        with self._lock:
            for ch in self.channels:
                self.clear_channel_data(ch)
            self._t0_mono = None
            self._seq = 0
            self.collecting = True
        self._publish(EVENT_COLLECTION_CHANGED, None, {'collecting': True})
        return {'ok': True, 'message': '已开始采集'}

    def stop_collection(self):
        with self._lock:
            self.collecting = False
        self._publish(EVENT_COLLECTION_CHANGED, None, {'collecting': False})
        return {'ok': True, 'message': '已停止采集'}

    def toggle_collection(self):
        return (self.stop_collection() if self.collecting
                else self.start_collection())

    def clear_data(self):
        with self._lock:
            for ch in self.channels:
                self.clear_channel_data(ch)
            self._t0_mono = None
            self._seq = 0
        self._publish(EVENT_CHANNELS_CHANGED)
        return {'ok': True, 'message': '已清除数据'}

    def _handle_line(self, cid, line):
        ch = self.get_channel(cid)
        if ch is None:
            return
        if line.startswith('ERROR:'):
            message = line[6:]
            log.error('%s 设备错误: %s', ch.name, message)
            self._publish(EVENT_ERROR, cid, {'message': message})
            self.disconnect(cid)
            return
        if line == 'START':
            self._publish(EVENT_CHANNEL_STATE, cid,
                          {'connected': True, 'message': '设备已启动，等待数据...'})
            return
        try:
            raw = self.decode_line(line, ch)
        except Exception as e:
            log.warning('%s 数据解析失败: %s', ch.name, e)
            return
        if raw is None:
            return
        try:
            value = self.convert(ch, raw)
        except Exception as e:
            log.warning('%s 换算失败: %s', ch.name, e)
            return

        with self._lock:
            now = time.monotonic()
            if self._t0_mono is None:
                self._t0_mono = now
            t_rel = now - self._t0_mono
            self._publish(EVENT_SAMPLE_PREVIEW, cid, {
                't': t_rel, 'raw': raw, 'value': value,
            })
            if not self.collecting:
                return
            if (ch.last_sample_s is not None and
                    (t_rel - ch.last_sample_s) * 1000 < ch.sample_interval_ms):
                return
            ch.last_sample_s = t_rel
            self._seq += 1
            seq = self._seq
            self.append_sample(ch, t_rel, raw, value)
        self._publish(EVENT_SAMPLE_RECORDED, cid, {
            'seq': seq, 't': t_rel, 'raw': raw, 'value': value,
        })

    # ---------------- 读取 / 导出 ----------------
    def snapshot(self, points=0):
        ai = self.ai_data() or {}
        pts = list(ai.get('points') or [])
        total_points = len(pts)
        if points and len(pts) > points:
            step = len(pts) / float(points)
            pts = [pts[int(i * step)] for i in range(points)]
        latest = None
        if pts:
            t, y = pts[-1]
            latest = {'t': t, 'y': y}
        return {
            'key': self.key,
            'name': self.title,
            'connected': self.connected_any(),
            'collecting': self.collecting,
            'x_label': ai.get('x_label', self.x_label),
            'y_label': ai.get('y_label', self.y_label),
            'params': ai.get('params', ''),
            'points': pts,
            'total_points': total_points,
            'latest': latest,
            'channels': [self.channel_info(ch) for ch in self.channels],
        }

    def series(self, cid=None, limit=2000):
        if cid is None:
            ch = next((c for c in self.channels if self.channel_values(c)), None)
        else:
            ch = self.get_channel(cid)
        if ch is None:
            return []
        pairs = list(zip(ch.time_data, self.channel_values(ch)))
        if limit and len(pairs) > limit:
            pairs = pairs[-int(limit):]
        return pairs

    def stats(self):
        out = {}
        for ch in self.channels:
            values = list(self.channel_values(ch))
            if not values:
                out[ch.id] = {'count': 0}
                continue
            out[ch.id] = {
                'count': len(values),
                'mean': sum(values) / len(values),
                'min': min(values),
                'max': max(values),
            }
        return out

    def export_csv(self, path=None):
        text = self.csv_text()
        if not text:
            raise ValueError('没有数据可保存')
        if not path:
            stamp = time.strftime('%Y%m%d_%H%M%S')
            path = f'{self.key}_data_{stamp}.csv'
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return os.path.abspath(path)

    # ---------------- 命令 ----------------
    def actions(self):
        return [
            'start', 'stop', 'toggle', 'clear',
            'refresh_ports', 'set_sample_interval',
            'set_connection', 'export_csv',
        ] + list(self.sensor_actions())

    def command(self, action, params=None):
        params = params or {}
        try:
            if action == 'start':
                return self.start_collection()
            if action == 'stop':
                return self.stop_collection()
            if action == 'toggle':
                return self.toggle_collection()
            if action == 'clear':
                return self.clear_data()
            if action == 'refresh_ports':
                return {'ok': True, 'ports': [
                    {'device': d, 'description': desc}
                    for d, desc in list_serial_ports()]}
            if action == 'set_sample_interval':
                ms = params.get('ms', params.get('sample_interval_ms'))
                if ms is None:
                    return {'ok': False, 'message': '缺少采样间隔'}
                cid = params.get('channel_id', params.get('cid'))
                targets = ([self.get_channel(cid)] if cid is not None
                           else list(self.channels))
                for ch in targets:
                    if ch is not None:
                        ch.sample_interval_ms = max(10, int(ms))
                self.save_config()
                self._publish(EVENT_CHANNELS_CHANGED, cid)
                return {'ok': True, 'message': f'采样间隔已设为 {int(ms)}ms'}
            if action == 'set_connection':
                cid = params.get('channel_id', params.get('cid'))
                ch = (self.get_channel(cid) if cid is not None
                      else (self.channels[0] if self.channels else None))
                if ch is None:
                    return {'ok': False, 'message': '通道不存在'}
                mode = str(params.get('mode', '')).strip()
                if mode in ('串口', 'serial', '有线串口'):
                    ch.mode = 'serial'
                elif mode in ('模拟器', 'simulator'):
                    ch.mode = 'simulator'
                if params.get('port'):
                    ch.port = str(params['port'])
                self.save_config()
                self._publish(EVENT_CHANNELS_CHANGED, ch.id)
                if params.get('connect'):
                    self.disconnect(ch.id)
                    return self.connect(ch.id)
                return {'ok': True, 'message': f'{ch.name} 连接方式已更新'}
            if action == 'export_csv':
                path = self.export_csv(params.get('path'))
                return {'ok': True, 'message': path, 'path': path}
            res = self.sensor_command(action, params)
            if res is not None:
                return res
            return {'ok': False, 'error': 'unsupported_action',
                    'message': f'不支持的命令: {action}'}
        except Exception as e:
            log.error('内核命令失败 %s/%s: %s', self.key, action, e)
            return {'ok': False, 'error': 'execution_failed', 'message': str(e)}

    def shutdown(self):
        self.disconnect_all()
        self._bus.close()


class KernelRegistry:
    """传感器内核注册表（纯 Python，供 Flask / MCP / CLI 直接调用）。

    UI 只负责创建内核并把同一个内核实例注册进来；HTTP 等外部接口直接操作
    内核，不再通过 QWidget、mode_combo、port_combo 等控件反射。
    """

    def __init__(self):
        self._kernels = {}
        self._names = {}
        self._icons = {}
        self._lock = threading.RLock()

    # ---- 注册 ----
    def register(self, key, name, kernel, icon_path=None):
        with self._lock:
            self._kernels[key] = kernel
            self._names[key] = name
            if icon_path:
                self._icons[key] = icon_path
        log.info("KernelRegistry 注册模块: %s (%s)", name, key)

    def unregister(self, key):
        with self._lock:
            self._kernels.pop(key, None)
            self._names.pop(key, None)
            self._icons.pop(key, None)

    def get(self, key):
        with self._lock:
            return self._kernels.get(key)

    def keys(self):
        with self._lock:
            return list(self._kernels.keys())

    def icon_path(self, key):
        return self._icons.get(key)

    # ---- 只读 ----
    def modules(self):
        out = []
        for key in self.keys():
            snap = self.snapshot(key)
            if snap is not None:
                snap.pop('points', None)
                out.append(snap)
        return out

    def snapshot(self, key, points=0):
        kernel = self.get(key)
        if kernel is None:
            return None
        try:
            snap = dict(kernel.snapshot(points=points) or {})
        except Exception as e:
            log.error("KernelRegistry.snapshot(%s) 失败: %s", key, e)
            return None
        snap.setdefault('key', key)
        snap.setdefault('name', self._names.get(key, key))
        snap['actions'] = self.actions(key)
        snap['connection'] = self.connection_info(key)
        return snap

    def series(self, key, limit=2000):
        snap = self.snapshot(key, points=limit)
        return snap.get('points', []) if snap else []

    def csv(self, key):
        kernel = self.get(key)
        if kernel is None:
            return None
        try:
            return kernel.csv_text()
        except Exception as e:
            log.error("KernelRegistry.csv(%s) 失败: %s", key, e)
            return None

    def actions(self, key):
        kernel = self.get(key)
        if kernel is None:
            return []
        try:
            return sorted(set(kernel.actions()))
        except Exception as e:
            log.error("KernelRegistry.actions(%s) 失败: %s", key, e)
            return []

    # ---- 连接信息（直接读内核通道，不碰控件） ----
    def connection_info(self, key):
        kernel = self.get(key)
        if kernel is None:
            return None
        channels = getattr(kernel, 'channels', None) or []
        if not channels:
            return None
        first = channels[0]
        ports = [device for device, _desc in list_serial_ports()]
        if not ports:
            ports = (['未安装 pyserial'] if not SERIAL_AVAILABLE
                     else ['无可用串口'])
        return {
            'modes': [
                {'text': '有线串口', 'enabled': bool(SERIAL_AVAILABLE)},
                {'text': '模拟器', 'enabled': True},
            ],
            'mode': '模拟器' if first.mode == 'simulator' else '有线串口',
            'ports': ports,
            'port': first.port or '',
        }

    # ---- 控制（直接调用内核线程安全方法） ----
    def submit_command(self, key, action, params=None, timeout=None):
        kernel = self.get(key)
        if kernel is None:
            return {'ok': False, 'error': 'module_not_found',
                    'message': '模块不存在: %s' % key}
        try:
            return kernel.command(action, params or {})
        except Exception as e:
            log.error("KernelRegistry 执行命令失败 %s/%s: %s", key, action, e)
            return {'ok': False, 'error': 'execution_failed', 'message': str(e)}