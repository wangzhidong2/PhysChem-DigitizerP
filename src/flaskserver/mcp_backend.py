# -*- coding: utf-8 -*-
"""
mcp_backend.py — MCP 的数据后端（HTTP 中转 / 进程内直连内核）

MCP 工具层只依赖本文件的 Backend 接口，两种实现共用同一套语义：

- HttpBackend：连运行中的上位机（默认）。桌面、网页、Agent 操作的是
  同一个内核实例，状态天然一致。
- LocalBackend：在 MCP 进程内直接构建 core.KernelRegistry，无 GUI、
  无 Flask、无 HTTP。适合服务器 / CI / 无人值守实验。

两种后端对工具层暴露完全相同的方法与返回结构，切换只改环境变量
PCD_BACKEND=http|local。

统一约定：
- 成功返回 dict；业务失败抛 BackendError（带机器可读 code、可执行 hint）。
- 写命令执行后由工具层再读一次状态，回传"是否真的生效"，而不是回显入参。
"""

import glob
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_API_BASE = 'http://127.0.0.1:8765'

#: 串口占用表的缓存时长（秒）。
#: 每次 status() 都要带 owners，但跨进程探测要发一次 HTTP；桌面端地址不可达时
#: 单次探测会等到超时（1s），而 wait_for_data 每 0.2s 就要读一次状态，
#: 不缓存会把 30s 的等待拖成 150s。连接前的预检用 force=True 绕开缓存。
OWNERS_TTL_S = 3.0


def probe_remote_owners(base=None, token=None, timeout=1.0):
    """读一次运行中上位机的串口占用表，返回 ({port: 展示名}, 实际地址)。

    跨进程时本进程的占用表看不到别人，只能问对方。连不上就返回空表，
    不影响本进程内的判断。
    """
    base = (base or os.environ.get('PCD_API_BASE') or DEFAULT_API_BASE).rstrip('/')
    token = token if token is not None else os.environ.get('PCD_TOKEN', '')
    headers = {'X-Auth-Token': token} if token else {}
    try:
        req = urllib.request.Request(base + '/api/health', headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            d = json.loads(resp.read().decode('utf-8', 'replace'))
        return (d.get('serial_owners') or {}), base
    except Exception:
        return {}, ''

#: 各动作的参数说明。给模型看的"能力清单"，避免它靠猜 params 结构。
#: 与 core.SensorKernel.command() 及各内核 sensor_command() 一一对应。
ACTION_SPECS = {
    'start': {'desc': '开始采集', 'params': {}},
    'stop': {'desc': '停止采集', 'params': {}},
    'toggle': {'desc': '切换采集状态', 'params': {}},
    'clear': {'desc': '清空已采集的数据（不可恢复）', 'params': {}},
    'refresh_ports': {'desc': '重新扫描可用串口', 'params': {}},
    'set_sample_interval': {
        'desc': '设置采样间隔',
        'params': {'ms': '整数，10~10000，单位毫秒',
                   'channel_id': '可选，缺省作用于全部通道'}},
    'set_connection': {
        'desc': '设置连接方式（不传 connect 则只改配置不连接）',
        'params': {'mode': '"串口" 或 "模拟器"', 'port': '串口名，如 COM3',
                   'connect': '布尔，是否立即连接',
                   'channel_id': '可选，缺省为第 1 路'}},
    'connect': {'desc': '连接通道', 'params': {'channel_id': '可选，缺省连接全部'}},
    'disconnect': {'desc': '断开通道', 'params': {'channel_id': '可选，缺省断开全部'}},
    'add_channel': {'desc': '新增一路通道',
                    'params': {'name': 'str', 'mode': '"串口"|"模拟器"',
                               'port': 'str', 'sample_interval_ms': 'int',
                               'connect': 'bool'}},
    'remove_channel': {'desc': '删除通道', 'params': {'channel_id': 'int'}},
    'update_channel': {'desc': '修改通道参数',
                       'params': {'channel_id': 'int', 'sample_interval_ms': 'int',
                                  'name': 'str', 'visible': 'bool'}},
    'export_csv': {'desc': '导出 CSV 到指定路径（MCP 侧请改用 export_csv 工具）',
                   'params': {'path': 'str'}},
    'get_calibration': {'desc': '读取当前校准参数', 'params': {'channel_id': '可选'}},
    'set_calibration': {
        'desc': '写入校准点（会改变后续所有读数）',
        'params': {'points': '[[标准值, 原始ADC], ...]',
                   'mode': '整数，1/2/3 点校准',
                   'theoretical_slope_mv': '单点校准时的理论斜率，mV/pH',
                   'channel_id': '可选'}},
    'tare': {'desc': '去皮 / 置零（以当前读数为零点）', 'params': {'channel_id': '可选'}},
    'zero_cal': {'desc': '电流模块零校准', 'params': {}},
    'set_mode': {'desc': '切换测量模式', 'params': {'mode': 'str'}},
    'set_unit': {'desc': '切换显示单位', 'params': {'unit': 'str'}},
    'set_rms_window': {'desc': '设置有效值窗口', 'params': {'window': 'int'}},
    'set_window_size': {'desc': '设置速度计算窗口', 'params': {'window_size': 'int'}},
    'calib_begin': {'desc': '开始力传感器两点校准', 'params': {'channel_id': '可选'}},
    'calib_record_zero': {'desc': '记录零点', 'params': {'channel_id': '可选'}},
    'calib_record_known': {'desc': '记录已知砝码',
                           'params': {'grams': '砝码克数', 'channel_id': '可选'}},
    'calib_cancel': {'desc': '取消校准', 'params': {'channel_id': '可选'}},
}


class BackendError(Exception):
    """业务失败：带机器可读错误码与给模型的纠正建议。"""

    def __init__(self, code, message, hint='', status=None, data=None):
        super().__init__(message)
        self.code = code or 'failed'
        self.message = message or '操作失败'
        self.hint = hint or ''
        self.status = status
        self.data = data


def redirect_logs_to_stderr():
    """把日志从 stdout 改道 stderr。

    stdio 传输下 stdout 是 MCP 协议通道，任何一行非 JSON 输出都会让客户端
    解析失败；而 core 的默认控制台 handler 写的是 stdout，必须在启动前改道。
    """
    loggers = [logging.getLogger()]
    for name in list(logging.root.manager.loggerDict):
        loggers.append(logging.getLogger(name))
    for lg in loggers:
        for handler in list(getattr(lg, 'handlers', [])):
            if (isinstance(handler, logging.StreamHandler)
                    and getattr(handler, 'stream', None) is sys.stdout):
                try:
                    handler.setStream(sys.stderr)
                except Exception:
                    handler.stream = sys.stderr


def describe_actions(actions):
    """把内核的动作名列表翻译成带说明的能力清单。"""
    out = []
    for action in actions or []:
        spec = ACTION_SPECS.get(action)
        out.append({
            'action': action,
            'desc': (spec or {}).get('desc', '模块自定义动作'),
            'params': (spec or {}).get('params', {}),
        })
    return out


def state_of(snap):
    """从快照里抽取模型决策需要的状态（去掉曲线点等大字段）。"""
    if not snap:
        return None
    channels = []
    for ch in snap.get('channels') or []:
        channels.append({k: ch.get(k) for k in (
            'id', 'name', 'mode', 'port', 'connected', 'sample_interval_ms',
            'points_n', 'latest_raw', 'visible') if k in ch})
    latest = snap.get('latest')
    return {
        'collecting': bool(snap.get('collecting')),
        'connected': bool(snap.get('connected')),
        'points_n': int(snap.get('total_points') or 0),
        'latest': latest,
        'y_label': snap.get('y_label') or '',
        'channels': channels,
    }


class Backend:
    """后端接口：MCP 工具层只认这几个方法。"""

    kind = 'base'

    def health(self):
        return {'ok': True, 'backend': self.kind}

    def modules(self):
        raise NotImplementedError

    def status(self, key):
        raise NotImplementedError

    def series(self, key, limit=500, channel_id=None):
        raise NotImplementedError

    def command(self, key, action, params=None):
        raise NotImplementedError

    def csv_text(self, key):
        raise NotImplementedError

    def close(self):
        pass

    # ---- 共用 ----
    def _status_payload(self, key, snap):
        if snap is None:
            raise BackendError('module_not_found', '模块不存在: %s' % key,
                               hint='先调用 list_modules 查看可用模块 key')
        actions = snap.get('actions') or []
        conn = snap.get('connection') or {}
        owners = self.serial_owners()
        port = (conn.get('port') or '').strip()
        return {
            'module': key,
            'name': snap.get('name') or key,
            'backend': self.kind,
            'state': state_of(snap),
            'x_label': snap.get('x_label') or '',
            'y_label': snap.get('y_label') or '',
            'params_text': (snap.get('params') or '')[:800],
            'actions': describe_actions(actions),
            'connection': {
                'mode': conn.get('mode'),
                'port': conn.get('port'),
                # 内核用占位文案表示「没串口」，不要让它混进可选端口列表，
                # 否则模型可能把「无可用串口」当成端口名传回来
                'ports': [p for p in (conn.get('ports') or [])
                          if '未安装' not in p and '无可用' not in p],
                'ports_note': ('未安装 pyserial' if any(
                    '未安装' in p for p in (conn.get('ports') or []))
                    else '' if [p for p in (conn.get('ports') or [])
                                if '无可用' not in p] else '未检测到串口'),
                'modes': [m.get('text') for m in (conn.get('modes') or [])],
                # 谁占着串口：当前通道的端口若被别的模块/进程持有，直接告诉模型
                'owners': owners,
                'port_holder': owners.get(port) or '',
            },
        }

    def serial_owners(self, force=False):
        """本会话可见的串口占用者；local 后端额外探一次桌面端（跨进程）。

        结果带 TTL 缓存：状态读取很频繁（wait_for_data 每 0.2s 一次），
        每次探测远端会让等待时间成倍变长。连接前的预检传 force=True 拿最新值。
        """
        now = time.time()
        cached = getattr(self, '_owners_cache', None)
        if not force and cached and now - cached[0] < OWNERS_TTL_S:
            return dict(cached[1])
        try:
            owners = self._owners_uncached()
        except Exception:
            owners = {}
        self._owners_cache = (now, dict(owners))
        return owners

    def _owners_uncached(self):
        """子类实现真正的取值；基类只问一次自己的 health()。"""
        return (self.health() or {}).get('serial_owners') or {}


class HttpBackend(Backend):
    """连运行中的上位机：Agent ─HTTP→ Flask ─→ KernelRegistry。"""

    kind = 'http'

    def __init__(self, base=None, token=None, timeout=20.0):
        self.base = (base or os.environ.get('PCD_API_BASE') or DEFAULT_API_BASE).rstrip('/')
        self.token = token if token is not None else os.environ.get('PCD_TOKEN', '')
        self.timeout = timeout

    # ---- 传输 ----
    def _req(self, path, method='GET', body=None, timeout=None):
        data = json.dumps(body).encode('utf-8') if body is not None else None
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['X-Auth-Token'] = self.token
        req = urllib.request.Request(self.base + path, data=data,
                                     method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                raw = resp.read().decode('utf-8', errors='replace')
                if not raw.strip():
                    return {}
                try:
                    return json.loads(raw)
                except ValueError:
                    # 端口被别的服务占用时会返回 HTML，不能让它变成内部异常
                    raise BackendError(
                        'bad_response',
                        '接口返回的不是 JSON（%s 可能不是本程序的数据接口）' % self.base,
                        hint='确认 PCD_API_BASE 指向主程序「数据接口」的端口（默认 8765）')
        except urllib.error.HTTPError as e:
            raw = e.read().decode('utf-8', errors='replace')
            try:
                d = json.loads(raw)
            except Exception:
                d = {}
            code = d.get('error') or ('http_%d' % e.code)
            msg = d.get('message') or ('HTTP %d' % e.code)
            hint = ''
            if e.code == 401:
                hint = ('上位机开启了访问密钥：设置环境变量 PCD_TOKEN 为设置页里的密钥，'
                        '或在设置页关闭鉴权')
            elif e.code == 404:
                hint = '先调用 list_modules 查看可用模块 key'
            raise BackendError(code, msg, hint=hint, status=e.code)
        except urllib.error.URLError as e:
            raise BackendError(
                'upstream_unreachable',
                '连不上上位机数据接口（%s）' % (getattr(e, 'reason', e),),
                hint=('确认主程序已打开「数据接口」开关，且 PCD_API_BASE 与端口一致'
                      '（默认 %s）；或改用 PCD_BACKEND=local 让 MCP 直接驱动内核'
                      % DEFAULT_API_BASE))

    # ---- 接口 ----
    def health(self):
        d = self._req('/api/health', timeout=5)
        d['backend'] = self.kind
        if d.get('auth_enabled') and not self.token:
            d['warning'] = ('上位机已开启鉴权，但未设置 PCD_TOKEN：'
                            '读操作可用，所有写操作会返回 unauthorized')
        return d

    def modules(self):
        d = self._req('/api/modules')
        out = []
        for m in d.get('modules') or []:
            out.append({
                'key': m.get('key'),
                'name': m.get('name'),
                'connected': bool(m.get('connected')),
                'collecting': bool(m.get('collecting')),
                'points_n': int(m.get('total_points') or 0),
                'latest': m.get('latest'),
                'y_label': m.get('y_label') or '',
                'channels_n': len(m.get('channels') or []),
            })
        return out

    def status(self, key):
        snap = self._req('/api/modules/%s' % key)
        return self._status_payload(key, snap)

    def series(self, key, limit=500, channel_id=None):
        limit = max(1, min(int(limit), 20000))
        d = self._req('/api/modules/%s/series?limit=%d' % (key, limit))
        channels = d.get('channels') or []
        if channel_id is not None:
            channels = [c for c in channels if c.get('id') == channel_id]
            if not channels:
                raise BackendError('channel_not_found',
                                   '模块 %s 没有通道 %s' % (key, channel_id),
                                   hint='调用 get_status 查看 channels[].id')
        return {
            'module': key,
            'semantics': '等距降采样，最多 limit 点；不是"最近 limit 点"',
            'channels': channels,
        }

    def command(self, key, action, params=None):
        try:
            d = self._req('/api/modules/%s/command' % key, 'POST',
                          {'action': action, 'params': params or {}})
        except BackendError as e:
            if e.code == 'unsupported_action':
                e.hint = '调用 get_status 查看该模块 actions 列表；或用专用工具'
            raise
        if d.get('ok') is False:
            raise BackendError(d.get('error') or 'command_failed',
                               d.get('message') or '命令执行失败')
        return d

    def csv_text(self, key):
        headers = {'X-Auth-Token': self.token} if self.token else {}
        req = urllib.request.Request(self.base + '/api/modules/%s/export.csv' % key,
                                     headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read().decode('utf-8', errors='replace')
        except urllib.error.HTTPError as e:
            raise BackendError('export_failed', '导出失败（HTTP %d）' % e.code)
        except urllib.error.URLError as e:
            raise BackendError('upstream_unreachable', '连不上上位机：%s' % e.reason)


class LocalBackend(Backend):
    """进程内直连内核：不经过 Flask、不依赖 Qt/PySide6。

    只加载 `_kernel*.py` 与模块文件头的 MODULE META，**不 import View
    文件**（那些依赖 PySide6），因此可在服务器/CI 中运行。
    """

    kind = 'local'

    def __init__(self, sensors_dir=None, log_enabled=False):
        self._dir = sensors_dir or os.environ.get('PCD_SENSORS_DIR') or self._default_dir()
        self._registry = None
        self._log_enabled = log_enabled
        self._load()

    @staticmethod
    def _default_dir():
        # 本文件在 src/flaskserver/ 下，传感器目录是同级 src/sensors/
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'sensors')

    def _load(self):
        src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        import sys
        if src not in sys.path:
            sys.path.insert(0, src)
        import core
        if not self._log_enabled:
            core.setup_logging(enabled=False)
        redirect_logs_to_stderr()
        import module_loader
        self._core = core
        self._module_loader = module_loader
        self._registry = core.KernelRegistry()

        if not os.path.isdir(self._dir):
            raise BackendError('sensors_dir_missing',
                               '找不到传感器目录: %s' % self._dir,
                               hint='设置 PCD_SENSORS_DIR 指向 src/sensors')
        for sub in sorted(os.listdir(self._dir)):
            d = os.path.join(self._dir, sub)
            if not os.path.isdir(d):
                continue
            for py in sorted(glob.glob(os.path.join(d, '*.py'))):
                base = os.path.basename(py)
                if base.startswith('_') or base.startswith('test'):
                    continue
                meta = module_loader.parse_module_meta(py)
                if not meta or not meta.get('kernel'):
                    continue
                cls = module_loader.load_module_kernel(py, meta)
                if cls is None:
                    continue
                try:
                    kernel = cls()
                except Exception as e:
                    raise BackendError('kernel_init_failed',
                                       '内核 %s 初始化失败: %s' % (cls.__name__, e))
                key = meta.get('key') or getattr(kernel, 'key', '') or base[:-3]
                self._registry.register(key, meta['name'], kernel)

        if not self._registry.keys():
            raise BackendError('no_modules', '没有发现任何可用的传感器内核',
                               hint='确认 PCD_SENSORS_DIR 下有含 "# kernel:" 的模块文件')

    # ---- 接口 ----
    def _owners_uncached(self):
        """本进程占用表 + 桌面端（若在跑）的占用表，标注来源。"""
        owners = {}
        try:
            owners = dict(self._registry.serial_owners() or {})
        except Exception:
            pass
        remote, base = probe_remote_owners()
        for port, label in remote.items():
            owners.setdefault(port, '桌面端 %s · %s' % (base, label))
        return owners

    def health(self):
        owners = {}
        try:
            owners = self._registry.serial_owners()
        except Exception:
            pass
        return {'ok': True, 'backend': self.kind, 'modules_n': len(self._registry.keys()),
                'sensors_dir': self._dir,
                'serial_owners': owners,
                'note': '进程内直连内核；不要与桌面端同时操作同一串口'}

    def modules(self):
        out = []
        for key in self._registry.keys():
            snap = self._registry.snapshot(key)
            if snap is None:
                continue
            out.append({
                'key': key,
                'name': snap.get('name'),
                'connected': bool(snap.get('connected')),
                'collecting': bool(snap.get('collecting')),
                'points_n': int(snap.get('total_points') or 0),
                'latest': snap.get('latest'),
                'y_label': snap.get('y_label') or '',
                'channels_n': len(snap.get('channels') or []),
            })
        return out

    def status(self, key):
        return self._status_payload(key, self._registry.snapshot(key))

    def series(self, key, limit=500, channel_id=None):
        if key not in self._registry.keys():
            raise BackendError('module_not_found', '模块不存在: %s' % key,
                               hint='先调用 list_modules')
        limit = max(1, min(int(limit), 20000))
        channels = self._registry.series_channels(key, limit=limit)
        if channel_id is not None:
            channels = [c for c in channels if c.get('id') == channel_id]
            if not channels:
                raise BackendError('channel_not_found',
                                   '模块 %s 没有通道 %s' % (key, channel_id))
        return {
            'module': key,
            'semantics': '每路最近 limit 点（内核按尾部截取）',
            'channels': channels,
        }

    def command(self, key, action, params=None):
        if key not in self._registry.keys():
            raise BackendError('module_not_found', '模块不存在: %s' % key)
        res = self._registry.submit_command(key, action, params or {})
        if isinstance(res, dict) and res.get('ok') is False:
            code = res.get('error') or 'command_failed'
            hint = ''
            if code == 'unsupported_action':
                hint = '调用 get_status 查看该模块 actions 列表；或用专用工具'
            raise BackendError(code, res.get('message') or '命令执行失败', hint=hint)
        return res if isinstance(res, dict) else {'ok': True, 'message': str(res)}

    def csv_text(self, key):
        text = self._registry.csv(key)
        if text is None:
            raise BackendError('module_not_found', '模块不存在: %s' % key)
        return text

    def close(self):
        for key in list(self._registry.keys()):
            kernel = self._registry.get(key)
            try:
                kernel.shutdown()
            except Exception:
                pass


def build_backend():
    """按环境变量创建后端：PCD_BACKEND=local|http（默认 http）。"""
    kind = (os.environ.get('PCD_BACKEND') or 'http').strip().lower()
    if kind == 'local':
        return LocalBackend(log_enabled=os.environ.get('PCD_LOG') == '1')
    if kind != 'http':
        raise BackendError('bad_backend', '未知的 PCD_BACKEND: %s' % kind,
                           hint='只支持 http 或 local')
    return HttpBackend()
