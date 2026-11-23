# -*- coding: utf-8 -*-
"""
flaskserver/mcp_server.py — MCP 服务（2026-07-28 规范）

把上位机的传感器内核暴露给 AI Agent，让 Agent 能自己读参数、改参数、
做实验、取数据、写报告：

    Agent ──stdio / Streamable HTTP──→ 本文件 ──→ Backend ──→ KernelRegistry

两种数据后端（环境变量 PCD_BACKEND）：
    http  （默认）连运行中的上位机，与桌面/网页共享同一内核
    local 进程内直接构建内核，不需要 GUI / Flask / 串口以外的任何东西

协议：MCP 2026-07-28（无状态：请求自带 _meta，支持 server/discover）。
需要 mcp >= 2.3；旧版 SDK 没有 server/discover，会给出明确升级提示。

环境变量：
    PCD_BACKEND=http|local        后端类型
    PCD_API_BASE=http://127.0.0.1:8765   http 后端的上位机地址
    PCD_TOKEN=<密钥>              上位机开启了鉴权时必须设置
    PCD_SENSORS_DIR=<路径>        local 后端的传感器目录（默认 ../sensors）
    PCD_REPORT_DIR=<路径>         报告输出目录（默认 ~/PhysChemReports）
    PCD_MCP_TRANSPORT=stdio|streamable-http
    PCD_MCP_HOST / PCD_MCP_PORT   streamable-http 监听地址（默认 127.0.0.1:8766）

运行：
    pip install -U "mcp>=2.3"
    python src/flaskserver/mcp_server.py
"""

import json
import os
import sys
import time
from typing import Annotated, Literal

try:
    from mcp.server.mcpserver import MCPServer
    from mcp.types import (CallToolResult, LATEST_PROTOCOL_VERSION,
                           TextContent, ToolAnnotations)
except ImportError as _e:  # pragma: no cover - 只影响独立运行
    raise SystemExit(
        '需要 mcp>=2.3（提供 MCP 2026-07-28 规范支持）。\n'
        '当前环境缺少或版本过低：%s\n'
        '  pip install -U "mcp>=2.3"\n'
        '说明：mcp 1.x 的 FastMCP 已废弃，且没有 server/discover。' % _e
    ) from _e

try:
    from pydantic import BaseModel, Field
except ImportError as _e:  # pragma: no cover - mcp 会自带 pydantic
    raise SystemExit('缺少 pydantic（安装 mcp 时会自动带上）: %s' % _e) from _e

try:  # 作为脚本运行（python mcp_server.py）
    from mcp_backend import (BackendError, build_backend, redirect_logs_to_stderr)
    from mcp_report import compute_stats, quality_notes, report_root, write_report
except ImportError:  # 作为包模块导入（flaskserver.mcp_server）
    from .mcp_backend import (BackendError, build_backend, redirect_logs_to_stderr)
    from .mcp_report import compute_stats, quality_notes, report_root, write_report

# stdio 传输下 stdout 属于协议，先把日志改道到 stderr（core 默认写 stdout）
redirect_logs_to_stderr()


SERVER_NAME = 'physchem-digitizer'
SERVER_VERSION = '2.0.0'

if LATEST_PROTOCOL_VERSION < '2026-07-28':  # 字符串比较对 ISO 日期有效
    print('[mcp] 警告：当前 mcp SDK 最高支持 %s，低于 2026-07-28；'
          '请升级：pip install -U "mcp>=2.3"' % LATEST_PROTOCOL_VERSION,
          file=sys.stderr)


# ============================================================
# 返回结构：所有工具统一回传 ok / error / state
#
# 成功与失败都走 CallToolResult：
# - structuredContent 给机器读（稳定字段，客户端可校验）
# - content.text 给人/模型读（一句话结论）
# - isError 让 Agent 框架能区分"工具失败"和"业务失败"
# ============================================================

class OpResult(BaseModel):
    """所有工具的统一返回。"""

    ok: bool = Field(description='操作是否成功')
    action: str = Field(default='', description='执行的动作名')
    module: str | None = Field(default=None, description='模块 key')
    message: str = Field(default='', description='一句话结果说明')
    error: str | None = Field(default=None,
                              description='机器可读错误码，如 unsupported_action / unauthorized')
    hint: str = Field(default='', description='出错时的纠正建议')
    state: dict | None = Field(default=None, description='操作后的实时状态')
    data: dict | None = Field(default=None, description='本次操作的具体数据')
    backend: str = Field(default='', description='http 或 local')
    ts: float = Field(default=0.0, description='Unix 时间戳')


def _payload(ok, action, module=None, message='', error=None, hint='',
             state=None, data=None):
    return {
        'ok': bool(ok), 'action': action, 'module': module,
        'message': message, 'error': error, 'hint': hint,
        'state': state, 'data': data, 'backend': _backend_kind(), 'ts': time.time(),
    }


def _ok(action, module=None, message='', data=None, state=None):
    payload = _payload(True, action, module, message, None, '', state, data)
    return CallToolResult(
        content=[TextContent(type='text', text=message or '成功')],
        structuredContent=payload, isError=False)


def _fail(action, module, err, state=None, data=None):
    if not isinstance(err, BackendError):
        err = BackendError('internal_error', str(err))
    if data is None:
        data = getattr(err, 'data', None)
    text = err.message
    if err.hint:
        text += '\n建议：' + err.hint
    payload = _payload(False, action, module, err.message, err.code, err.hint,
                       state, data)
    return CallToolResult(
        content=[TextContent(type='text', text=text)],
        structuredContent=payload, isError=True)


def _guard(action, module, fn, with_state=True):
    """执行 fn() -> (data, message)，统一补状态与异常转换。"""
    def snapshot():
        if not (with_state and module):
            return None
        try:
            return get_backend().status(module)['state']
        except Exception:
            return None

    try:
        data, message = fn()
        return _ok(action, module, message, data, snapshot())
    except BackendError as e:
        return _fail(action, module, e, state=snapshot(),
                     data=getattr(e, 'data', None))
    except Exception as e:  # 兜底：不让异常穿到协议层变成"工具崩溃"
        return _fail(action, module,
                     BackendError('internal_error', '%s: %s' % (type(e).__name__, e)),
                     state=snapshot())


_BACKEND = None


def get_backend():
    global _BACKEND
    if _BACKEND is None:
        _BACKEND = build_backend()
    return _BACKEND


def _backend_kind():
    try:
        return get_backend().kind
    except Exception:
        return 'unknown'


# ============================================================
# MCP 服务
# ============================================================

mcp = MCPServer(
    SERVER_NAME,
    title='PhysChem Digitizer',
    version=SERVER_VERSION,
    instructions=(
        '理化实验数字化采集系统。可用流程：先用 list_modules 看有哪些模块，'
        'get_status 看连接与可用动作，connect_device 选模拟器或串口，'
        'control_collect 开始采集，wait_for_data 等数据稳定，'
        'summarize 看统计，最后 make_report 生成报告。'
        '所有写操作都会回传执行后的真实状态，请以 state 为准，不要假设命令一定生效。'
    ),
)

READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, idempotent_hint=False,
                        destructive_hint=False, open_world_hint=False)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, idempotent_hint=False,
                              destructive_hint=True, open_world_hint=False)


# ------------------------------------------------------------
# 读：模块 / 状态 / 读数 / 序列 / 统计
# ------------------------------------------------------------

@mcp.tool(annotations=READ, structured_output=True)
def list_modules() -> OpResult:
    """列出所有传感器模块及其实时状态（连接、采集、点数、最新值）。

    不确定模块 key 时先调用本工具。返回的 modules[].key 是后续所有工具的 module 参数。
    """
    def run():
        mods = get_backend().modules()
        collecting = sum(1 for m in mods if m['collecting'])
        return ({'modules': mods, 'count': len(mods)},
                '共 %d 个模块，%d 个正在采集' % (len(mods), collecting))
    return _guard('list_modules', None, run, with_state=False)


@mcp.tool(annotations=READ, structured_output=True)
def get_status(module: Annotated[str, Field(description='模块 key，如 ph_sensor')]) -> OpResult:
    """读取模块的完整状态：连接方式、每路通道、参数、以及可执行的动作清单。

    actions 里每一项都带 params 说明，是调用 send_command 的依据。
    """
    def run():
        st = get_backend().status(module)
        state = st['state']
        msg = '%s：%s，%d 点' % (
            st['name'], '采集中' if state['collecting'] else '未采集',
            state['points_n'])
        if not state['connected']:
            msg += '（未连接，先调用 connect_device）'
        return st, msg
    return _guard('get_status', module, run, with_state=False)


@mcp.tool(annotations=READ, structured_output=True)
def get_reading(
    module: Annotated[str, Field(description='模块 key')],
    channel_id: Annotated[int | None, Field(description='通道 id，缺省用主通道')] = None,
    window: Annotated[int, Field(description='用于判断稳定性的最近点数', ge=5, le=200)] = 30,
) -> OpResult:
    """读取当前读数：最新值、单位、最近 window 点的标准差与波动率。

    适合"看一眼现在是多少"。要看趋势用 summarize，要原始点用 get_series。
    """
    def run():
        st = get_backend().status(module)
        ser = get_backend().series(module, limit=window, channel_id=channel_id)
        ch = (ser.get('channels') or [None])[0]
        ys = [p[1] for p in (ch or {}).get('points', [])]
        std = None
        if len(ys) >= 3:
            mean = sum(ys) / len(ys)
            std = (sum((y - mean) ** 2 for y in ys) / (len(ys) - 1)) ** 0.5
        latest = st['state'].get('latest') or {}
        value = latest.get('y') if isinstance(latest, dict) else None
        if value is None and ys:
            value = ys[-1]
        rel = (std / abs(value)) if (std is not None and value) else None
        data = {
            'value': value, 'unit': st.get('y_label') or '',
            't': latest.get('t') if isinstance(latest, dict) else None,
            'n_recent': len(ys), 'std_recent': std,
            'rel_std': rel,
            'stable': bool(std is not None and rel is not None and rel < 0.02),
            'channel': {'id': ch.get('id'), 'name': ch.get('name')} if ch else None,
        }
        msg = '当前 %s%s' % (
            ('%.4g' % value) if isinstance(value, (int, float)) else '—',
            (' ' + data['unit']) if data['unit'] else '')
        if std is not None:
            msg += '，最近 %d 点 σ=%.4g' % (len(ys), std)
            msg += '，读数稳定' if data['stable'] else '，读数仍在波动'
        return data, msg
    return _guard('get_reading', module, run)


@mcp.tool(annotations=READ, structured_output=True)
def get_series(
    module: Annotated[str, Field(description='模块 key')],
    limit: Annotated[int, Field(description='返回点数上限（按时间尾部或等距降采样）',
                                ge=1, le=20000)] = 200,
    channel_id: Annotated[int | None, Field(description='只取某一路通道')] = None,
) -> OpResult:
    """获取时间序列原始点，用于自己拟合或画图。

    默认只给 200 点，避免把上下文塞满；需要全量请用 export_csv。
    注意 semantics 字段：不同后端的降采样方式不同。
    """
    def run():
        ser = get_backend().series(module, limit=limit, channel_id=channel_id)
        n = sum(len(c.get('points') or []) for c in ser['channels'])
        return ser, '返回 %d 路共 %d 点（%s）' % (
            len(ser['channels']), n, ser.get('semantics', ''))
    return _guard('get_series', module, run)


@mcp.tool(annotations=READ, structured_output=True)
def summarize(
    module: Annotated[str, Field(description='模块 key')],
    limit: Annotated[int, Field(description='参与统计的点数上限', ge=10, le=20000)] = 2000,
    channel_id: Annotated[int | None, Field(description='只统计某一路')] = None,
) -> OpResult:
    """对最近数据做统计：点数、均值、标准差、极值、前后半段漂移、数据质量提示。

    做"是否达到平衡/是否异常"的判断时优先用本工具，不要自己拉原始点算。
    """
    def run():
        ser = get_backend().series(module, limit=limit, channel_id=channel_id)
        stats = compute_stats(ser.get('channels'))
        notes = quality_notes(stats)
        data = {'module': module, 'stats': stats, 'quality_notes': notes,
                'window': limit}
        if stats:
            s = stats[0]
            msg = '%d 点，均值 %s，σ %s，前后漂移 %s' % (
                s.get('n', 0),
                ('%.4g' % s['mean']) if s.get('n') else '—',
                ('%.4g' % s['std']) if s.get('n') else '—',
                ('%.4g' % s['drift']) if s.get('n') else '—')
        else:
            msg = '没有可用数据'
        if notes:
            msg += '；' + '；'.join(notes[:2])
        return data, msg
    return _guard('summarize', module, run)


@mcp.tool(annotations=READ, structured_output=True)
def wait_for_data(
    module: Annotated[str, Field(description='模块 key')],
    min_points: Annotated[int, Field(description='至少累计多少点才返回', ge=1, le=100000)] = 10,
    timeout_s: Annotated[float, Field(description='最长等待秒数', ge=0.5, le=120)] = 30.0,
    stable_std: Annotated[float | None, Field(
        description='可选：最近窗口标准差低于该值视为稳定（如 pH 用 0.02）')] = None,
    window: Annotated[int, Field(description='稳定性判定的窗口点数', ge=5, le=200)] = 30,
    channel_id: Annotated[int | None, Field(description='只盯某一路通道')] = None,
) -> OpResult:
    """阻塞等待，直到采集到足够点数或读数稳定；超时也会正常返回。

    返回 data.reached 表示条件是否满足，data.state 是等待结束时的真实状态。
    这是"等实验做完再读"的正确方式，不要用多次 get_reading 轮询。
    """
    def run():
        backend = get_backend()
        t0 = time.time()
        need_stable = stable_std is not None
        ok_streak = 0
        last_std = None
        prev_n = -1
        stalled = 0
        while True:
            st = backend.status(module)
            state = st['state']
            n = int(state.get('points_n') or 0)
            grew = n > prev_n
            if not grew:
                stalled += 1
            prev_n = n
            if need_stable and grew:
                # 只拿新到的点算稳定性：数据不再增长时窗口是不变的，
                # 反复读同一批点会把"设备停了"误判成"读数稳定了"
                ser = backend.series(module, limit=window, channel_id=channel_id)
                ch = (ser.get('channels') or [None])[0]
                ys = [p[1] for p in (ch or {}).get('points', [])]
                if len(ys) >= max(5, window // 2):
                    mean = sum(ys) / len(ys)
                    last_std = (sum((y - mean) ** 2 for y in ys) / (len(ys) - 1)) ** 0.5
                    if last_std <= stable_std:
                        ok_streak += 1
                    else:
                        ok_streak = 0
            reached = (n >= min_points) and (not need_stable or ok_streak >= 3)
            elapsed = time.time() - t0
            # 连续约 5s 点数不变（拔线/断电/设备停了）：提前返回，别让 Agent 干等到超时
            stalled_out = (not reached) and stalled >= 25
            if reached or stalled_out or elapsed >= timeout_s:
                reason = 'reached' if reached else ('stalled' if stalled_out else 'timeout')
                data = {
                    'reached': reached,
                    'reason': reason,
                    'timeout': reason == 'timeout',
                    'elapsed_s': round(elapsed, 2),
                    'points_n': n,
                    'std': last_std,
                    'stalled': reason == 'stalled',
                    'criteria': {'min_points': min_points,
                                 'stable_std': stable_std, 'window': window},
                }
                if reached:
                    msg = '已达条件：%d 点，用时 %.1fs' % (n, elapsed)
                    if need_stable:
                        msg += '，σ=%.4g' % (last_std or 0)
                elif stalled_out:
                    msg = ('等待 %.1fs 后点数停止增长（停在 %d 点）：'
                           '采集线程可能已中断，检查设备供电与串口连接'
                           % (elapsed, n))
                else:
                    msg = '等待 %.1fs 超时：当前 %d 点' % (elapsed, n)
                    if need_stable and last_std is not None:
                        msg += '，σ=%.4g（阈值 %.4g）' % (last_std, stable_std)
                    if not state.get('collecting'):
                        msg += '；采集未开启，先调用 control_collect(start)'
                    elif not state.get('connected'):
                        msg += '；设备未连接，先调用 connect_device'
                    elif n == 0:
                        msg += '；采集已开启但没有数据，检查串口或设备供电'
                return data, msg
            time.sleep(0.2)
    return _guard('wait_for_data', module, run)


# ------------------------------------------------------------
# 写：采集 / 参数 / 连接 / 校准
# ------------------------------------------------------------

@mcp.tool(annotations=WRITE, structured_output=True)
def control_collect(
    module: Annotated[str, Field(description='模块 key')],
    action: Annotated[Literal['start', 'stop', 'toggle'],
                      Field(description='start 开始 / stop 停止 / toggle 切换')],
) -> OpResult:
    """开始或停止采集，并回传执行后的真实状态（collecting、points_n）。

    如果命令返回成功但 state.collecting 没变，说明没有连接设备，先 connect_device。
    """
    def run():
        backend = get_backend()
        before = backend.status(module)['state']
        if action in ('start', 'toggle') and not before['collecting'] and not before['connected']:
            raise BackendError(
                'not_connected',
                '没有通道连接，开始采集不会产生任何数据',
                hint='先调用 connect_device（无硬件用 mode="模拟器"）',
                data={'before': {'collecting': before['collecting'],
                                 'points_n': before['points_n']}})
        backend.command(module, action)
        after = backend.status(module)['state']
        effective = before['collecting'] != after['collecting']
        data = {'before': {'collecting': before['collecting'],
                           'points_n': before['points_n']},
                'after': {'collecting': after['collecting'],
                          'points_n': after['points_n']},
                'effective': effective}
        if not effective:
            msg = '命令已下发，但采集状态未改变（当前 %s）' % (
                '采集中' if after['collecting'] else '未采集')
            if not after['connected']:
                msg += '；设备未连接，请先 connect_device'
        else:
            msg = '已开始采集' if after['collecting'] else '已停止采集'
            msg += '，当前 %d 点' % after['points_n']
        return data, msg
    return _guard('control_collect', module, run)


@mcp.tool(annotations=WRITE, structured_output=True)
def set_parameter(
    module: Annotated[str, Field(description='模块 key')],
    sample_interval_ms: Annotated[int | None, Field(
        description='采样间隔，毫秒（10~10000）', ge=10, le=10000)] = None,
    unit: Annotated[str | None, Field(description='显示单位，如 pH / N / V / A / mm')] = None,
    channel_id: Annotated[int | None, Field(description='只改某一路通道')] = None,
) -> OpResult:
    """修改采样间隔或显示单位，并回读确认是否真的生效。

    返回 data.applied 是执行后从内核读回的值，data.mismatch 列出没生效的项。
    """
    if sample_interval_ms is None and unit is None:
        return _fail('set_parameter', module,
                     BackendError('missing_parameter', '至少要指定 sample_interval_ms 或 unit'))

    def run():
        backend = get_backend()
        params = {}
        if channel_id is not None:
            params['channel_id'] = channel_id
        applied, mismatch, errors = {}, [], []
        unit_reply = None
        if sample_interval_ms is not None:
            try:
                backend.command(module, 'set_sample_interval',
                                dict(params, ms=sample_interval_ms))
            except BackendError as e:
                errors.append({'param': 'sample_interval_ms', 'error': e.code,
                               'message': e.message})
        if unit is not None:
            try:
                # set_unit 在内核里返回 {'unit': 实际值}，优先用它做回读
                res = backend.command(module, 'set_unit', dict(params, unit=unit))
                if isinstance(res, dict):
                    unit_reply = res.get('unit')
            except BackendError as e:
                errors.append({'param': 'unit', 'error': e.code, 'message': e.message})
        st = backend.status(module)
        chans = st['state'].get('channels') or []
        target = [c for c in chans if channel_id is None or c.get('id') == channel_id]
        if sample_interval_ms is not None:
            actual = [c.get('sample_interval_ms') for c in target if c]
            applied['sample_interval_ms'] = actual
            if actual and all(v != sample_interval_ms for v in actual):
                mismatch.append('sample_interval_ms')
        if unit is not None and not errors:
            # 回读：内核返回值 > 状态里的轴标签；都没有才退回入参
            actual_unit = unit_reply if unit_reply is not None else (st.get('y_label') or unit)
            applied['unit'] = actual_unit
            if str(actual_unit) != str(unit) and str(unit) not in str(actual_unit):
                mismatch.append('unit')
        data = {'requested': {'sample_interval_ms': sample_interval_ms, 'unit': unit},
                'applied': applied, 'mismatch': mismatch, 'errors': errors}
        if errors:
            e = errors[0]
            raise BackendError(e['error'], e['message'],
                               hint='调用 get_status 查看该模块支持的参数',
                               data=data)
        msg = '参数已生效：' + '，'.join(
            '%s=%s' % (k, v) for k, v in applied.items() if v is not None)
        if mismatch:
            msg = '参数未完全生效：' + '，'.join(mismatch)
        return data, msg
    return _guard('set_parameter', module, run)


@mcp.tool(annotations=WRITE, structured_output=True)
def connect_device(
    module: Annotated[str, Field(description='模块 key')],
    mode: Annotated[Literal['模拟器', '串口'], Field(description='连接方式')],
    port: Annotated[str | None, Field(description='串口名，如 COM3；模拟器可省略')] = None,
    channel_id: Annotated[int | None, Field(description='只连某一路通道')] = None,
) -> OpResult:
    """连接设备（模拟器或串口），并回读 connected 状态。

    没有硬件时用 mode="模拟器" 即可跑通完整实验流程。串口名可从 get_status 的
    connection.ports 里选。
    """
    def run():
        backend = get_backend()
        before = backend.status(module)
        bconn = before.get('connection') or {}
        prev_port = (bconn.get('port') or '').strip()
        prev_mode = bconn.get('mode') or ''
        target = (port or prev_port or '').strip()
        if mode == '串口' and not target:
            raise BackendError(
                'missing_parameter', '串口模式需要 port，当前也没有已保存的端口',
                hint='先调用 get_status，从 connection.ports 里选一个端口名',
                data={'ports': bconn.get('ports') or []})

        # 跨进程预检：local 后端看不到桌面端的占用表，这里主动问一次。
        # 串口同一时间只能有一个进程持有，硬连会瓜分字节流、把桌面端顶掉。
        # 注意：换到另一个端口时同样要查（"已连着 A 现在要连 B" 也要防抢）。
        held_by_self = any((c.get('port') or '').strip() == target and c.get('connected')
                           for c in (before.get('state', {}).get('channels') or []))
        if mode == '串口' and target and backend.kind == 'local' and not held_by_self:
            owners = backend.serial_owners(force=True)
            holder = owners.get(target)
            if holder:
                raise BackendError(
                    'port_in_use',
                    '串口 %s 已被「%s」占用，不能在另一个进程里再打开一次'
                    % (target, holder),
                    hint=('串口是独占资源：改用 PCD_BACKEND=http 连上正在运行的上位机，'
                          '共享同一个内核；或先在桌面端断开该通道'),
                    data={'port': target, 'holder': holder, 'owners': owners})

        params = {'mode': mode, 'connect': True}
        if port:
            params['port'] = port
        if channel_id is not None:
            params['channel_id'] = channel_id
        backend.command(module, 'set_connection', params)

        def probe():
            st = backend.status(module)
            return st, st['state']

        # 串口在后台线程打开，失败时 connected 会先置真再回滚：
        # 必须等一小段再判，否则会把「打不开的 COM9」报成「已连接」。
        time.sleep(0.15)
        st, state = probe()
        if state['connected'] and mode == '串口':
            time.sleep(0.3)
            st, state = probe()

        if not state['connected']:
            # 回滚端口，避免坏端口写进配置后，后续不带 port 的调用继续踩坑
            rollback = {'mode': prev_mode or '模拟器'}
            if prev_port:
                rollback['port'] = prev_port
            try:
                backend.command(module, 'set_connection', rollback)
            except Exception:
                pass
            holder = (backend.serial_owners(force=True) or {}).get(target)
            if holder:
                raise BackendError(
                    'port_in_use',
                    '串口 %s 已被「%s」占用，无法打开' % (target, holder),
                    hint=('串口同一时间只能被一个进程持有：改用 PCD_BACKEND=http '
                          '共享正在运行的上位机；或先在桌面端断开该通道'),
                    data={'port': target, 'holder': holder,
                          'attempted': {'mode': mode, 'port': target},
                          'previous': {'mode': prev_mode, 'port': prev_port}})
            raise BackendError(
                'connect_failed',
                '%s %s 打开失败（端口不存在、被其它程序占用或无权限）'
                % (mode, target or ''),
                hint=('桌面端已占用该串口时，MCP 不要直连串口，'
                      '改用 PCD_BACKEND=http 共享桌面端的同一个内核；'
                      '无硬件可用 mode="模拟器"'),
                data={'attempted': {'mode': mode, 'port': target},
                      'previous': {'mode': prev_mode, 'port': prev_port},
                      'ports': bconn.get('ports') or []})

        data = {'connected': True,
                'mode': st.get('connection', {}).get('mode'),
                'port': st.get('connection', {}).get('port'),
                'reused_port': bool(not port and target),
                'channels': state.get('channels')}
        if mode == '串口':
            msg = '已连接（串口 %s）' % data['port'] if data['port'] else '已连接（串口）'
            if not port and target:
                msg += '，沿用已保存端口 %s' % target
        else:
            msg = '已连接（模拟器）'
        return data, msg
    return _guard('connect_device', module, run)


@mcp.tool(annotations=DESTRUCTIVE, structured_output=True)
def calibrate(
    module: Annotated[str, Field(description='模块 key')],
    points: Annotated[list[list[float]], Field(
        description='校准点 [[标准值, 原始ADC], ...]，如 [[4.0,2555],[6.86,2281]]')],
    mode: Annotated[int | None, Field(description='校准点数模式，缺省按点数自动')] = None,
    theoretical_slope_mv: Annotated[float | None, Field(
        description='单点校准时的理论斜率（pH 常用 -280 mV/pH）')] = None,
    channel_id: Annotated[int | None, Field(description='只校准某一路')] = None,
) -> OpResult:
    """写入校准点。会改变该通道之后所有读数，执行前请确认标准液数值。

    写入后会回读内核里的校准参数，确认实际生效值。
    """
    if not points:
        return _fail('calibrate', module,
                     BackendError('missing_parameter', 'points 不能为空'))
    for p in points:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            return _fail('calibrate', module,
                         BackendError('bad_parameter',
                                      'points 每项必须是 [标准值, 原始ADC]'))

    def run():
        backend = get_backend()
        params = {'points': [[float(p[0]), float(p[1])] for p in points]}
        if mode is not None:
            params['mode'] = mode
        if theoretical_slope_mv is not None:
            params['theoretical_slope_mv'] = theoretical_slope_mv
        if channel_id is not None:
            params['channel_id'] = channel_id
        backend.command(module, 'set_calibration', params)
        readback = backend.command(module, 'get_calibration',
                                   {'channel_id': channel_id} if channel_id else {})
        return ({'written': params, 'readback': readback},
                '校准已写入并回读确认（%d 点）' % len(points))
    return _guard('calibrate', module, run)


@mcp.tool(annotations=DESTRUCTIVE, structured_output=True)
def send_command(
    module: Annotated[str, Field(description='模块 key')],
    action: Annotated[str, Field(description='动作名，见 get_status 的 actions')],
    params: Annotated[dict | None, Field(description='动作参数，结构见 actions[].params')] = None,
) -> OpResult:
    """兜底命令入口：去皮、清零、切模式、加删通道等专用工具未覆盖的动作。

    优先用专用工具；本工具不做参数校验，动作名写错会返回 unsupported_action。
    """
    def run():
        res = get_backend().command(module, action, params or {})
        msg = (res.get('message') if isinstance(res, dict) else '') or '已执行 %s' % action
        return {'result': res}, msg
    return _guard('send_command', module, run)


# ------------------------------------------------------------
# 产出：CSV / 实验报告
# ------------------------------------------------------------

def _export_csv(module, text=None):
    """导出 CSV 到固定目录（不接受调用方指定路径，避免任意写盘）。"""
    if text is None:
        text = get_backend().csv_text(module)
    if not text.strip():
        raise BackendError('no_data', '模块 %s 当前没有可导出的数据' % module,
                           hint='先 connect_device → control_collect(start) 采集一段时间')
    root = report_root() / 'data'
    root.mkdir(parents=True, exist_ok=True)
    # 同一秒内可能连续导出（make_report 也会调本函数），加毫秒避免互相覆盖
    stamp = time.strftime('%Y%m%d_%H%M%S') + '_%03d' % (int(time.time() * 1000) % 1000)
    path = root / ('%s_%s.csv' % (module, stamp))
    path.write_text(text, encoding='utf-8')
    # 注释头行数随通道数变化（多通道时不止 1 行），不能写死 -2
    body = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith('#')]
    rows = max(0, len(body) - 1)  # 去掉表头
    return str(path), rows, len(text.encode('utf-8'))


@mcp.tool(annotations=WRITE, structured_output=True)
def export_csv(module: Annotated[str, Field(description='模块 key')]) -> OpResult:
    """把模块全部数据导出为 CSV（含参数注释头），返回文件路径。

    文件固定写到 PCD_REPORT_DIR/data/，不能指定任意路径。
    数据量大时用它，不要用 get_series 拉全量。
    """
    def run():
        path, rows, size = _export_csv(module)
        return ({'path': path, 'rows': rows, 'bytes': size},
                '已导出 %d 行到 %s' % (rows, path))
    return _guard('export_csv', module, run)


@mcp.tool(annotations=WRITE, structured_output=True)
def make_report(
    module: Annotated[str, Field(description='模块 key')],
    title: Annotated[str, Field(description='报告标题')] = '',
    objective: Annotated[str, Field(description='实验目的（由你撰写）')] = '',
    procedure: Annotated[str, Field(description='实验步骤（由你撰写）')] = '',
    conclusion: Annotated[str, Field(description='结论（由你根据数据撰写）')] = '',
    notes: Annotated[str, Field(description='备注/异常说明')] = '',
    limit: Annotated[int, Field(description='参与统计与画图的最大点数',
                                ge=50, le=20000)] = 5000,
    include_csv: Annotated[bool, Field(description='是否同时导出 CSV 附件')] = True,
) -> OpResult:
    """生成实验报告（Markdown + 自包含 HTML），返回文件路径。

    数据、统计、曲线由本工具生成；目的/步骤/结论由调用方（AI）撰写后传入。
    报告写到 PCD_REPORT_DIR，HTML 可直接打开或打印。
    """
    def run():
        backend = get_backend()
        st = backend.status(module)
        ser = backend.series(module, limit=limit)
        stats = compute_stats(ser.get('channels'))
        csv_path = None
        if include_csv:
            try:
                csv_path, _, _ = _export_csv(module)
            except BackendError:
                csv_path = None
        ctx = {
            'module': module,
            'title': title or ('%s 实验报告' % st.get('name', module)),
            'objective': objective, 'procedure': procedure,
            'conclusion': conclusion, 'notes': notes,
            'status': st, 'series': ser, 'stats': stats,
            'csv_path': csv_path,
            'backend': backend.kind,
            'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        files = write_report(ctx)
        data = {'files': files, 'stats': stats,
                'quality_notes': quality_notes(stats),
                'points_n': st['state']['points_n'],
                'csv_path': csv_path}
        return data, '报告已生成：%s' % files['html']
    return _guard('make_report', module, run)


# ------------------------------------------------------------
# 资源：让支持 Resources 的客户端直接读取，不必调工具
# ------------------------------------------------------------

@mcp.resource('pcd://modules/{key}/status', mime_type='application/json')
def resource_status(key: str) -> str:
    """模块实时状态（JSON）。"""
    try:
        return json.dumps(get_backend().status(key), ensure_ascii=False, indent=2)
    except BackendError as e:
        # 资源读取失败也给出结构化内容，否则客户端只看到一条协议级错误
        return json.dumps({'ok': False, 'error': e.code, 'message': e.message,
                           'hint': e.hint}, ensure_ascii=False, indent=2)


@mcp.resource('pcd://modules/{key}/csv', mime_type='text/csv')
def resource_csv(key: str) -> str:
    """模块全量数据 CSV（含参数注释头）。数据很大时优先用 export_csv 工具。"""
    try:
        return get_backend().csv_text(key)
    except BackendError as e:
        return '# 读取失败(%s): %s\n' % (e.code, e.message)


# ------------------------------------------------------------
# 提示词：把"怎么做一次实验"固化下来，用户可一键调用
# ------------------------------------------------------------

@mcp.prompt(title='执行一次完整测量')
def run_experiment(module: str, goal: str = '获得稳定读数') -> str:
    """生成一段闭环实验的操作提示词。"""
    return (
        '你要在 PhysChem-Digitizer 上完成一次测量，目标是：%s。\n'
        '严格按下面顺序做，每步都检查返回的 ok 与 state：\n'
        '1) list_modules 确认 %s 存在；\n'
        '2) get_status 看 connected、actions 与 connection.ports；\n'
        '3) 未连接则 connect_device（无硬件用 mode="模拟器"）；\n'
        '4) 需要时 set_parameter 调整采样间隔；\n'
        '5) control_collect("start")，确认 state.collecting 为 true；\n'
        '6) wait_for_data 等到 min_points 或 stable_std 满足；\n'
        '7) summarize 判断是否稳定、有无漂移；\n'
        '8) control_collect("stop")；\n'
        '9) make_report 生成报告，结论必须基于 summarize 的数字，不要编造。\n'
        '任何时候 ok=false，先读 error 与 hint 再决定重试还是换方案，不要盲目重复同一调用。'
        % (goal, module)
    )


@mcp.prompt(title='分析一次测量')
def analyze_measurement(module: str) -> str:
    """生成数据分析提示词。"""
    return (
        '分析模块 %s 的最近数据：先 summarize 看均值/σ/漂移与质量提示，'
        '必要时 get_series 取原始点做拟合。结论要区分三种可能：'
        '仪器问题（未连接、量程溢出）、环境干扰（波动大但无趋势）、'
        '真实物理变化（单调漂移或阶跃）。最后给出下一步建议（继续等待/重新校准/更换量程）。'
        % module
    )


# ------------------------------------------------------------
# 启动
# ------------------------------------------------------------

def main():
    transport = os.environ.get('PCD_MCP_TRANSPORT', 'stdio').strip() or 'stdio'
    try:
        h = get_backend().health()
        print('[mcp] 后端 %s 就绪：%s' % (h.get('backend'), json.dumps(h, ensure_ascii=False)[:200]),
              file=sys.stderr)
        if h.get('warning'):
            print('[mcp] 警告：%s' % h['warning'], file=sys.stderr)
    except BackendError as e:
        # 不退出：Agent 可能稍后才打开上位机；但必须让它看到原因
        print('[mcp] 后端暂不可用：%s\n[mcp] 建议：%s' % (e.message, e.hint), file=sys.stderr)
    except Exception as e:
        print('[mcp] 后端初始化失败：%s' % e, file=sys.stderr)

    if transport == 'stdio':
        mcp.run(transport='stdio')
    elif transport in ('http', 'streamable-http'):
        mcp.run(transport='streamable-http',
                host=os.environ.get('PCD_MCP_HOST', '127.0.0.1'),
                port=int(os.environ.get('PCD_MCP_PORT', '8766')))
    else:
        raise SystemExit('PCD_MCP_TRANSPORT 只支持 stdio 或 streamable-http，收到：%s'
                         % transport)


if __name__ == '__main__':
    main()
