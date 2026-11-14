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
from collections import deque
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

# ============================================================
# 多通道公共常量（各传感器内核共用，避免每模块各复制一份）
# ============================================================
#: 多路连接默认曲线配色（按新建顺序轮换取未用色，界面上可单独改色）
CHANNEL_COLORS = ('#0078d4', '#e74c3c', '#2ecc71', '#f39c12',
                  '#9b59b6', '#00bcd5', '#e67e22', '#16a085')

#: 有符号 ADC 满量程：±(2^N - 1)，例如 12 位 → ±4095
ADC_BITS_OPTIONS = {8: 255, 10: 1023, 12: 4095, 14: 16383, 16: 65535,
                    18: 262143, 20: 1048575, 22: 4194303, 24: 16777215}

#: ADC 参考电压（ESP32 analogRead 满量程）
VREF = 3.3

#: ADS1115 PGA 量程（TI ADS1115 数据手册 SBAS444E，9.3.3 节）
ADS1115_PGA_RANGES = {
    '±6.144V': 6.144,
    '±4.096V': 4.096,
    '±2.048V': 2.048,  # 默认（PGA=010）
    '±1.024V': 1.024,
    '±0.512V': 0.512,
    '±0.256V': 0.256,
}
#: ADS1115 输入通道（MUX）：4 单端 + 2 差分
ADS1115_CHANNELS = ['AIN0', 'AIN1', 'AIN2', 'AIN3', 'AIN0-AIN1', 'AIN2-AIN3']

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


#: 进程内配置读写锁：UI / Flask / 各模块内核共用同一个 sensor_config.json
_config_lock = threading.RLock()


def _atomic_write_json(path, data):
    """原子写入 JSON：同目录临时文件 → fsync → os.replace。

    读方只会看到完整的旧文件或完整的新文件，不会读到写了一半的 JSON。
    Windows 上目标文件正被读取时 os.replace 可能短暂失败，做几次短重试。
    """
    import tempfile
    directory = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(5):
            try:
                os.replace(tmp_path, path)
                return
            except PermissionError:
                if attempt >= 4:
                    raise
                time.sleep(0.02)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


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
        with _config_lock:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    all_config = json.load(f)
            else:
                all_config = {}

            all_config[module_name] = config_dict
            _atomic_write_json(config_path, all_config)

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
        with _config_lock:
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
        with _config_lock:
            _atomic_write_json(config_path, data)
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
        with _config_lock:
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
        opened = False
        try:
            self.serial = serial.Serial(self.port, self.baudrate, timeout=1)
            if not self.running:
                try:
                    self.serial.close()
                except Exception:
                    pass
                return
            self.serial.reset_input_buffer()
            opened = True
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
            opened = False     # 已报错，finally 不再重复通知
        finally:
            try:
                if self.serial and self.serial.is_open:
                    self.serial.close()
            except Exception:
                pass
            # 非主动 stop() 却退出循环（设备拔出 / 虚拟串口对端销毁）：
            # 必须通知内核断开，否则界面会一直显示「已连接」但不再有数据
            if opened and self.running:
                self.running = False
                log.warning("串口连接已断开: %s", self.port)
                self._emit("ERROR:串口连接已断开")

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

#: 进程内串口占用表：port -> (owner, 展示名)
#: 同一串口只能被一路打开（跨模块也生效），否则两路会平分同一数据流
_port_claims = {}
_port_claims_lock = threading.Lock()


def claim_serial_port(port, owner, label=''):
    """尝试占用串口。返回 None 成功；否则返回当前占用者的展示名。"""
    if not port:
        return None
    with _port_claims_lock:
        cur = _port_claims.get(port)
        if cur is not None and cur[0] != owner:
            return cur[1] or cur[0]
        _port_claims[port] = (owner, label or owner)
        return None


def release_serial_port(port, owner):
    """释放串口占用（只有占用者本人能释放）。"""
    if not port:
        return
    with _port_claims_lock:
        cur = _port_claims.get(port)
        if cur is not None and cur[0] == owner:
            _port_claims.pop(port, None)


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

    def notify_change(self, cid=None):
        """本地 UI 直接改了内核状态后调用：保存配置并广播刷新事件。

        View 的本地修改（改名、改色、换模式、改采样间隔、校准、显隐等）
        与 HTTP / CLI 的修改走同一条事件链路，保证各端（桌面其余窗口、
        网页、将来的 TUI）都能立即收到刷新通知。
        """
        self.save_config()
        self._publish(EVENT_CHANNELS_CHANGED, cid)

    def remove_channel(self, cid):
        ch = self.get_channel(cid)
        if ch is None:
            return False
        if len(self.channels) <= 1:
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
        owner = '%s#%s' % (self.key, cid)
        claimed = ''
        # 同一串口不允许被两路同时打开（含跨模块）：Linux 下可重复 open，
        # 两路会平分数据流；Windows 则直接报占用
        if ch.mode == 'serial':
            port = (ch.port or '').strip()
            if port and '未安装' not in port and '无可用' not in port:
                holder = claim_serial_port(
                    port, owner, '%s %s' % (self.title, ch.name))
                if holder is not None:
                    return {'ok': False, 'error': 'port_in_use',
                            'message': f'串口 {port} 已被「{holder}」占用'}
                claimed = port
        try:
            transport = self._make_transport(ch)
        except Exception as e:
            release_serial_port(claimed, owner)
            return {'ok': False, 'error': 'connect_failed', 'message': str(e)}
        transport.on_line = lambda line, cid=cid: self._handle_line(cid, line)
        ch.thread = transport
        ch.connected = True
        if claimed:
            ch._claimed_port = claimed
            ch._claim_owner = owner
        try:
            transport.start()
        except Exception as e:
            ch.thread = None
            ch.connected = False
            release_serial_port(claimed, owner)
            for attr in ('_claimed_port', '_claim_owner'):
                try:
                    delattr(ch, attr)
                except AttributeError:
                    pass
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
        claimed = getattr(ch, '_claimed_port', '')
        if claimed:
            release_serial_port(claimed, getattr(ch, '_claim_owner', ''))
            for attr in ('_claimed_port', '_claim_owner'):
                try:
                    delattr(ch, attr)
                except AttributeError:
                    pass
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
        # cleared=True 供 View 区分「清空数据」与普通通道变更，重置数据展示控件
        self._publish(EVENT_CHANNELS_CHANGED, None, {'cleared': True})
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
            if action == 'add_channel':
                mode = str(params.get('mode', 'serial')).strip()
                if mode in ('模拟器', 'simulator'):
                    mode = 'simulator'
                elif mode in ('串口', 'serial', '有线串口'):
                    mode = 'serial'
                extra = params.get('sensor_params') or {}
                if not isinstance(extra, dict):
                    extra = {}
                try:
                    ch = self.add_channel(
                        color=params.get('color'),
                        mode=mode,
                        port=str(params.get('port') or ''),
                        name=params.get('name'),
                        sample_interval_ms=params.get('sample_interval_ms'),
                        visible=bool(params.get('visible', True)),
                        **extra)
                except Exception as e:
                    return {'ok': False, 'error': 'add_channel_failed',
                            'message': f'新增通道失败: {e}'}
                result = {'ok': True, 'message': f'{ch.name} 已新增',
                          'channel': self.channel_info(ch)}
                if params.get('connect'):
                    result.update(self.connect(ch.id))
                return result
            if action == 'remove_channel':
                cid = params.get('channel_id', params.get('cid'))
                if cid is None:
                    return {'ok': False, 'message': '缺少 channel_id'}
                ch = self.get_channel(cid)
                if ch is None:
                    return {'ok': False, 'message': '通道不存在'}
                name = ch.name
                if not self.remove_channel(cid):
                    return {'ok': False,
                            'message': '至少保留一个通道，无法删除'}
                return {'ok': True, 'message': f'{name} 已删除'}
            if action == 'update_channel':
                cid = params.get('channel_id', params.get('cid'))
                if cid is None:
                    return {'ok': False, 'message': '缺少 channel_id'}
                ch = self.get_channel(cid)
                if ch is None:
                    return {'ok': False, 'message': '通道不存在'}
                fields = params.get('fields') or {
                    k: v for k, v in params.items()
                    if k not in ('channel_id', 'cid', 'connect', 'fields')}
                if not isinstance(fields, dict):
                    return {'ok': False, 'message': 'fields 必须是对象'}
                if 'mode' in fields:
                    mode = str(fields['mode']).strip()
                    if mode in ('模拟器', 'simulator'):
                        fields['mode'] = 'simulator'
                    elif mode in ('串口', 'serial', '有线串口'):
                        fields['mode'] = 'serial'
                self.update_channel(cid, **fields)
                result = {'ok': True, 'message': f'{ch.name} 已更新',
                          'channel': self.channel_info(ch)}
                if 'connect' in params:
                    result.update(self.connect(cid) if params.get('connect')
                                  else self.disconnect(cid))
                return result
            if action == 'connect':
                cid = params.get('channel_id', params.get('cid'))
                if cid is None:
                    self.connect_all()
                    return {'ok': True, 'message': '已连接全部通道'}
                return self.connect(cid)
            if action == 'disconnect':
                cid = params.get('channel_id', params.get('cid'))
                if cid is None:
                    self.disconnect_all()
                    return {'ok': True, 'message': '已断开全部通道'}
                return self.disconnect(cid)
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


class ChannelBase:
    """多通道内核中一路连接的公共数据模型（纯 Python，不持有 Qt 控件）。

    子类只初始化自己的物理参数与数据序列；id/名称/颜色/连接状态/采样间隔/
    图表显隐/时间戳等公共字段由本类统一维护，避免每个模块重复一份。
    """

    def __init__(self, cid, name, color, mode='serial', port='',
                 sample_interval_ms=100, visible=True):
        self.id = int(cid)
        self.name = name
        self.default_name = name
        self.color = color
        self.mode = mode or 'serial'
        self.port = port or ''
        self.thread = None
        self.connected = False
        self.sample_interval_ms = int(sample_interval_ms or 100)
        self.visible = bool(visible)
        # 数据序列：子类通常会把自己的数据列表别名到 value_data/raw_data，
        # 以便复用 SensorKernel 的快照、统计与 CSV 逻辑。
        self.time_data = []
        self.raw_data = []
        self.value_data = []
        # 实时显示 / 去皮用的滚动窗口（未开始采集时也持续记录）
        self.live_window = deque(maxlen=10)
        # 上次记录样本的主机相对秒（采样间隔过滤，每路独立）
        self.last_sample_s = None


class MultiChannelKernel(SensorKernel):
    """多通道传感器内核公共层。

    统一处理六类重复逻辑：通道 id/配色/默认名分配、配置恢复、每路字段
    序列化、顶层镜像字段、CSV 拼接。子类只需实现物理差异：
    ``create_channel`` / ``channel_restore_params`` / 换算与采样钩子。
    """

    #: 新建通道的默认配色（可在子类覆盖）
    CHANNEL_COLORS = CHANNEL_COLORS
    #: 每路公共持久化字段
    CHANNEL_COMMON_FIELDS = ('name', 'mode', 'port', 'color',
                             'sample_interval_ms', 'visible')
    #: 子类追加的每路持久化字段名
    CHANNEL_EXTRA_FIELDS = ()

    # ---------------- 通道创建 ----------------
    def create_channel(self, cid, name, color, mode, port,
                       sample_interval_ms, visible, params):
        """构造一路通道对象；params 为 add_channel/make_channel 的额外关键字。"""
        raise NotImplementedError

    def make_channel(self, color=None, mode='serial', port='', name=None,
                     sample_interval_ms=None, visible=True, **params):
        """分配稳定 id、默认名与未占用配色后交给 create_channel。"""
        cid = self._next_channel_id
        self._next_channel_id += 1
        seq = self._next_channel_seq
        self._next_channel_seq += 1
        if not color:
            used = {ch.color for ch in self.channels}
            colors = self.CHANNEL_COLORS
            color = next((c for c in colors if c not in used),
                         colors[(seq - 1) % len(colors)])
        return self.create_channel(
            cid, name or f'通道{seq}', color, mode, port,
            sample_interval_ms or self.sample_interval_ms, visible, params)

    # ---------------- 配置恢复 / 保存 ----------------
    def channel_restore_params(self, item):
        """把配置里的一路 dict 转成 make_channel 的额外关键字。"""
        return {}

    def after_restore_channels(self):
        """通道恢复完成后的模块级收尾（镜像顶层字段、重算系数等）。"""
        pass

    def _restore_channels(self):
        """按配置重建通道；旧版单通道配置自动迁移为一路通道。"""
        saved = (self.config or {}).get('channels') or []
        if saved:
            for item in saved:
                mode = item.get('mode', 'serial')
                if mode != 'simulator' and not SERIAL_AVAILABLE:
                    mode = 'simulator'   # pyserial 缺失时优雅降级
                self.channels.append(self.make_channel(
                    name=item.get('name') or None,
                    color=item.get('color') or None,
                    mode=mode, port=item.get('port', ''),
                    sample_interval_ms=item.get('sample_interval_ms'),
                    visible=item.get('visible', True),
                    **self.channel_restore_params(item)))
        else:
            mode = 'serial' if SERIAL_AVAILABLE else 'simulator'
            self.channels.append(self.make_channel(mode=mode))
        self.after_restore_channels()

    def channel_to_dict(self, ch):
        """一路通道 → 配置 dict（公共字段 + 子类扩展字段）。"""
        out = {f: getattr(ch, f, None) for f in self.CHANNEL_COMMON_FIELDS}
        for f in self.CHANNEL_EXTRA_FIELDS:
            if hasattr(ch, f):
                out[f] = getattr(ch, f)
        return self.serialize_channel(out, ch)

    def serialize_channel(self, out, ch):
        """子类可在写盘前转换字段格式（如 tuple → list）。"""
        return out

    def base_config(self, extra=None):
        """在模块顶层配置上补上统一的 sample_interval_ms 与 channels 列表。"""
        first = self.channels[0] if self.channels else None
        config = dict(extra or {})
        config.setdefault(
            'sample_interval_ms',
            first.sample_interval_ms if first else self.sample_interval_ms)
        config['channels'] = [self.channel_to_dict(ch) for ch in self.channels]
        return config

    def mirror_first_channel(self, *fields):
        """把第 1 路的字段镜像到模块级属性（旧版单通道配置兼容）。"""
        if not self.channels:
            return
        first = self.channels[0]
        for f in fields:
            if hasattr(first, f):
                value = getattr(first, f)
                if isinstance(value, list):
                    value = list(value)   # 避免顶层与通道共用同一个列表
                setattr(self, f, value)

    # ---------------- CSV ----------------
    def csv_comments(self):
        """CSV 头部注释行（子类按需覆盖）。"""
        return []

    def csv_header(self):
        """CSV 列名（可直接覆盖）。"""
        return ['channel', 'timestamp_s', 'raw_adc', 'value']

    def csv_row_values(self, channel, index):
        """一路一个样本的列值（子类按需覆盖）。"""
        values = self.channel_values(channel)
        t = channel.time_data[index] if index < len(channel.time_data) else 0.0
        raw = channel.raw_data[index] if index < len(channel.raw_data) else 0
        value = values[index] if index < len(values) else ''
        return [channel.name, f'{t:.3f}', raw, value]

    def csv_text(self):
        """长表 CSV：一行一个样本 + channel 列。"""
        total = sum(len(self.channel_values(ch)) for ch in self.channels)
        if total == 0:
            return ''
        lines = list(self.csv_comments())
        lines.append(','.join(self.csv_header()))
        for ch in self.channels:
            for i in range(len(self.channel_values(ch))):
                lines.append(','.join(str(v)
                                      for v in self.csv_row_values(ch, i)))
        return '\n'.join(lines) + '\n'


class KernelRegistry:
    """传感器内核注册表（纯 Python，供 Flask / MCP / CLI 直接调用）。

    UI 只负责创建内核并把同一个内核实例注册进来；HTTP 等外部接口直接操作
    内核，不再通过 QWidget、mode_combo、port_combo 等控件反射。

    同时承担进程内的事件汇聚：register() 时订阅该内核的事件总线，把事件
    追加到带单调序号的环形日志，供 SSE / 长轮询按 Last-Event-ID 续传。
    这样桌面 GUI、网页、CLI 任一处改内核，其他端都能立即收到刷新通知。
    """

    #: 事件环形缓冲长度；客户端落后超过此长度时下发 reset 让它整页刷新
    EVENT_LOG_MAX = 512
    #: 采样事件（每路 10Hz）合并为 data 通知的最小间隔（秒）
    DATA_EVENT_INTERVAL = 0.5

    def __init__(self):
        self._kernels = {}
        self._names = {}
        self._icons = {}
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._seq = 0
        self._events = deque(maxlen=self.EVENT_LOG_MAX)
        self._consumers = {}
        self._data_ts = {}

    # ---- 注册 ----
    def register(self, key, name, kernel, icon_path=None):
        with self._cond:
            self._kernels[key] = kernel
            self._names[key] = name
            if icon_path:
                self._icons[key] = icon_path
        self._start_consumer(key, kernel)
        log.info("KernelRegistry 注册模块: %s (%s)", name, key)

    def unregister(self, key):
        with self._cond:
            self._kernels.pop(key, None)
            self._names.pop(key, None)
            self._icons.pop(key, None)
            consumer = self._consumers.pop(key, None)
        if consumer:
            consumer['stop'].set()

    def get(self, key):
        with self._lock:
            return self._kernels.get(key)

    def keys(self):
        with self._lock:
            return list(self._kernels.keys())

    def icon_path(self, key):
        return self._icons.get(key)

    # ---- 事件汇聚（SSE / 长轮询数据源） ----
    def _start_consumer(self, key, kernel):
        """订阅内核事件总线，把事件并入 registry 事件日志。"""
        try:
            sub = kernel.subscribe(maxsize=2048)
        except Exception as e:
            log.warning("订阅内核事件失败 %s: %s", key, e)
            return
        stop = threading.Event()

        def _run():
            while not stop.is_set():
                try:
                    event = sub.get(timeout=0.5)
                except queue.Empty:
                    continue
                except Exception:
                    break
                try:
                    self._ingest(key, event)
                except Exception as e:
                    log.error("内核事件入队失败 %s: %s", key, e)

        thread = threading.Thread(target=_run, daemon=True,
                                  name='kernel-events-%s' % key)
        thread.start()
        with self._cond:
            old = self._consumers.get(key)
            self._consumers[key] = {'thread': thread, 'stop': stop, 'sub': sub}
        if old:
            old['stop'].set()

    def _ingest(self, key, event):
        """把一条内核事件写入环形日志；高频采样事件合并为 data 通知。"""
        kind = getattr(event, 'kind', '') or ''
        now = time.time()
        if kind in (EVENT_SAMPLE_PREVIEW, EVENT_SAMPLE_RECORDED):
            with self._cond:
                if now - self._data_ts.get(key, 0.0) < self.DATA_EVENT_INTERVAL:
                    return
                self._data_ts[key] = now
            entry = {'key': key, 'kind': 'data', 'channel_id': None, 'data': {}}
        else:
            entry = {'key': key, 'kind': kind,
                     'channel_id': getattr(event, 'channel_id', None),
                     'data': dict(getattr(event, 'data', None) or {})}
        entry['ts'] = round(now, 3)
        with self._cond:
            self._seq += 1
            entry['seq'] = self._seq
            self._events.append(entry)
            self._cond.notify_all()

    def current_seq(self):
        with self._cond:
            return self._seq

    def wait_events(self, since=0, timeout=20.0, limit=200):
        """等待序号大于 since 的事件（阻塞至多 timeout 秒）。

        Returns:
            (events, seq, gap)：events 为事件列表（最多 limit 条）；
            seq 为当前最新序号；gap=True 表示 since 已落后于环形缓冲，
            客户端应先整页刷新，再从 seq 续传。
        """
        try:
            since = int(since)
        except (TypeError, ValueError):
            since = 0
        try:
            limit = max(1, int(limit))
        except (TypeError, ValueError):
            limit = 200
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._cond:
            while True:
                if since > self._seq:
                    # 服务重启后客户端仍带旧序号：直接让它从头同步
                    return [], self._seq, True
                if self._events:
                    oldest = self._events[0].get('seq', 0)
                    gap = since + 1 < oldest
                    events = [e for e in self._events
                              if e.get('seq', 0) > since][:limit]
                    if events or gap:
                        return events, self._seq, gap
                remain = deadline - time.monotonic()
                if remain <= 0:
                    return [], self._seq, False
                self._cond.wait(remain)

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

    def channels(self, key):
        """返回模块全部通道的元数据（不包含曲线点）。"""
        kernel = self.get(key)
        if kernel is None:
            return []
        try:
            return [kernel.channel_info(ch) for ch in kernel.channels]
        except Exception as e:
            log.error("KernelRegistry.channels(%s) 失败: %s", key, e)
            return []

    def series_channels(self, key, limit=2000):
        """按通道返回曲线点，供网页端多通道绘图。"""
        kernel = self.get(key)
        if kernel is None:
            return []
        out = []
        for ch in list(kernel.channels):
            try:
                points = kernel.series(ch.id, limit=limit)
            except Exception as e:
                log.warning("读取通道 %s/%s 序列失败: %s", key, ch.id, e)
                points = []
            out.append({
                'id': ch.id,
                'name': ch.name,
                'color': ch.color,
                'visible': bool(getattr(ch, 'visible', True)),
                'points': points,
            })
        return out

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