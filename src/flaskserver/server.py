# -*- coding: utf-8 -*-
"""
flaskserver.server — Flask app、路由、token 校验、静态托管

只做一件事：把 core.KernelRegistry 的方法翻译成 HTTP 端点。
不持有数据、不认识任何具体传感器、不操作任何 Qt 控件。

鉴权模型（按请求来源判定，而不是按端点判定）：

- **本机回环**（127.0.0.1 / ::1）：读写一律免令牌。浏览器仪表盘默认就
  跑在回环上，本地自己用不该再输一次密钥。
- **局域网来源**（非回环）：只在「局域网访问」开启后可能到达；此时若
  鉴权开启则读写都要令牌，鉴权关闭则同样免令牌（用户显式选择的风险）。

响应里的 ``scope`` 字段（loopback / auth / off）描述本次请求实际落在
哪一档，前端据此决定要不要显示登录页。
"""

import json
import os
import socket
import time
from pathlib import Path

from flask import (Flask, jsonify, request, Response, send_file,
                   stream_with_context)

_WEB_DIR = Path(__file__).parent / 'web'
#: 内嵌字体目录：与主程序共用 src/assets/fonts/（本文件在 src/flaskserver/ 下，上溯两级为 src/）
_FONT_DIR = Path(__file__).resolve().parent.parent / 'assets' / 'fonts'
_READ_TIMEOUT_S = 8.0

#: 浏览器仪表盘内嵌字体：字体族名 → 文件基准名（不含扩展名）。
#: 文件基准名带 _Regular 后缀，不能由族名推导，故显式映射。
WEB_FONT_FACE = 'HarmonyOS Sans SC'
WEB_FONT_BASE = 'HarmonyOS_Sans_SC_Regular'

#: 网页字体可选范围（host 端字体族名 → 下拉显示名）。
#: 只有访客浏览器能靠名字找到的通用字体才放进来；内嵌字体始终第一项。
WEB_FONT_CHOICES = (
    ('', '系统默认'),
    ('Microsoft YaHei', '微软雅黑'),
    ('SimSun', '宋体'),
    ('SimHei', '黑体'),
    ('KaiTi', '楷体'),
    ('FangSong', '仿宋'),
    ('Segoe UI', 'Segoe UI'),
    ('Arial', 'Arial'),
    ('Georgia', 'Georgia'),
    ('Consolas', 'Consolas'),
)


def _font_file_for(base_name):
    """返回可用的字体文件路径：优先 woff2（体积约为 TTF 一半），退回 ttf。

    返回 (path, mime) 或 (None, None)。
    """
    for suffix, mime in (('.woff2', 'font/woff2'), ('.ttf', 'font/ttf')):
        p = _FONT_DIR / (base_name + suffix)
        if p.is_file():
            return p, mime
    return None, None


def lan_ip():
    """本机在局域网中的出口 IP；离线/无网卡时返回空串。

    UDP connect 不发包，只让系统选出出口网卡；标准库实现，不引入依赖。
    插件层启动时打印密钥也要用这个地址，故为公开名。
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        return s.getsockname()[0]
    except OSError:
        return ''
    finally:
        s.close()


#: 兼容旧名（模块内原有调用点仍用 _lan_ip）
_lan_ip = lan_ip


# ============================================================
# 错误响应与 token 校验
# ============================================================

def _error(code, error, message):
    resp = jsonify({'ok': False, 'error': error, 'message': message})
    resp.status_code = code
    return resp


def _json_body():
    """读取请求体 JSON 对象；非法/非对象一律返回空 dict（调用方按缺字段处理）。"""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


#: 回环来源地址：只有这些不需要令牌（IPv6 可能是 ::1 或 IPv4 映射形式）
_LOOPBACK_ADDRS = frozenset((
    '127.0.0.1', '::1', 'localhost', '::ffff:127.0.0.1',
))


def _peer_addr():
    """本次请求的对端地址（去掉端口），无法判断时返回空串。"""
    addr = ''
    try:
        addr = request.remote_addr or ''
    except Exception:
        return ''
    addr = str(addr).strip()
    if addr.startswith('['):                 # [::1]:1234 → ::1
        addr = addr[1:].split(']', 1)[0]
    elif addr.count(':') == 1:               # 127.0.0.1:1234 → 127.0.0.1
        addr = addr.split(':', 1)[0]
    return addr


def is_loopback_request():
    """本请求是否来自本机回环（本地访问免令牌的唯一依据）。"""
    addr = _peer_addr()
    if not addr:
        return False
    if addr in _LOOPBACK_ADDRS:
        return True
    # 127.0.0.0/8 全部视为回环；::ffff:127.x.x.x 同理
    if addr.startswith('127.'):
        return True
    if addr.startswith('::ffff:127.'):
        return True
    return False


def build_app(service, token='', allow_lan=False, enable_cors=False,
              app_cfg=None):
    """构建 Flask app。

    Args:
        service: core.KernelRegistry 实例（直接持有内核，不经过 QWidget）
        token: 局域网访问令牌；本机回环永远免校验，此值为空则局域网也免校验
        allow_lan: 局域网模式 —— 服务绑定在 0.0.0.0，非回环来源才需要 token
        enable_cors: 是否允许跨域
        app_cfg: core_ui.app_cfg（网页字体等外观设置读写用）；None 时只读回退默认
    """
    app = Flask(__name__, static_folder=str(_WEB_DIR), static_url_path='')

    # werkzeug 每请求打一行日志会污染控制台，压到 ERROR
    import logging
    logging.getLogger('werkzeug').setLevel(logging.ERROR)

    app.config['JSON_AS_ASCII'] = False
    app._start_time = time.time()
    app._token = token or ''
    app._allow_lan = allow_lan

    if enable_cors:
        @app.after_request
        def _cors(resp):
            resp.headers['Access-Control-Allow-Origin'] = '*'
            resp.headers['Access-Control-Allow-Headers'] = 'X-Auth-Token, Content-Type'
            resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            return resp

    def _auth_scope():
        """本次请求的鉴权档位：loopback / auth / off。

        - loopback：来自本机回环，读写一律免令牌
        - auth：来自局域网且令牌已配置，读写都要令牌
        - off：来自局域网但令牌为空（用户在设置里关掉了鉴权）
        """
        if is_loopback_request():
            return 'loopback'
        return 'auth' if app._token else 'off'

    def _check_token(write=False):
        """令牌校验：只对**局域网来源**生效，本机回环始终放行。

        Args:
            write: 保留参数，用于区分读写；当前两档都按同一来源规则判定，
                   保留是为了将来「本机免读、写需令牌」之类的收紧
        Returns:
            None 通过；否则返回 401 响应
        """
        scope = _auth_scope()
        if scope != 'auth':
            return None
        supplied = (request.headers.get('X-Auth-Token')
                    or request.args.get('token') or '')
        if supplied == app._token:
            return None
        return _error(401, 'unauthorized', '缺少或错误的访问密钥')

    # --------------------------------------------------------
    # 读取端点（本机回环免令牌）
    # --------------------------------------------------------
    @app.route('/api/health')
    def health():
        r = _check_token(write=False)
        if r is not None:
            return r
        scope = _auth_scope()
        return jsonify({
            'ok': True,
            'plugin': 'flaskserver',
            'version': 2,
            'uptime_s': round(time.time() - app._start_time, 1),
            'flask': True,
            'modules_n': len(service.keys()),
            'lan_access': allow_lan,
            # scope=loopback/off 时免令牌；scope=auth 时读写都要令牌
            'scope': scope,
            'auth_enabled': bool(app._token),
            'auth_required': scope == 'auth',
            'loopback': scope == 'loopback',
            # 谁占着哪个串口：让 MCP/脚本能判断「连不上是因为被桌面端占用」
            'serial_owners': (service.serial_owners()
                              if hasattr(service, 'serial_owners') else {}),
        })

    @app.route('/api/auth/check')
    def auth_check():
        """登录探测：无副作用，报告本次来源需要什么级别的鉴权。

        - scope=loopback → 200，免令牌直接进桌面
        - scope=off      → 200，局域网也免令牌
        - scope=auth     → 令牌正确 200，缺失/错误 401（前端据此显示登录页）
        """
        r = _check_token(write=True)
        if r is not None:
            return r
        scope = _auth_scope()
        return jsonify({'ok': True, 'scope': scope,
                        'auth_enabled': bool(app._token),
                        'auth_required': scope == 'auth'})

    @app.route('/api/modules')
    def modules():
        r = _check_token(write=False)
        if r is not None:
            return r
        return jsonify({'ok': True, 'modules': service.modules()})

    @app.route('/api/modules/<key>')
    def module_snapshot(key):
        r = _check_token(write=False)
        if r is not None:
            return r
        try:
            points = int(request.args.get('points', 0))
        except ValueError:
            return _error(400, 'bad_request', 'points 必须是整数')
        snap = service.snapshot(key, points=max(0, points))
        if snap is None:
            return _error(404, 'module_not_found', '模块不存在: %s' % key)
        snap['ok'] = True
        return jsonify(snap)

    # --------------------------------------------------------
    # 事件推送（SSE）：桌面 GUI / 网页 / CLI 任一处改内核都会广播
    #
    # 事件统一为 {seq, key, kind, channel_id, data, ts}：
    # - channels_changed / collection_changed / channel_state / error 为状态事件
    # - data 为高频采样合并后的「有新数据」通知（每路最多 2 次/秒）
    # 客户端按 Last-Event-ID 断线续传；落后超过环形缓冲时收到 reset 事件。
    # --------------------------------------------------------
    @app.route('/api/events')
    def events():
        r = _check_token(write=False)
        if r is not None:
            return r
        wait_events = getattr(service, 'wait_events', None)
        if not callable(wait_events):
            return _error(503, 'not_supported', '当前服务不支持事件推送')
        current_seq = getattr(service, 'current_seq', None)
        start = current_seq() if callable(current_seq) else 0
        raw = request.args.get('since')
        if raw is None or raw == '':
            raw = request.headers.get('Last-Event-ID')
        try:
            since = int(raw) if raw not in (None, '') else start
        except (TypeError, ValueError):
            since = start

        def _stream():
            cursor = since
            yield 'retry: 3000\n\n'
            while True:
                batch, seq, gap = wait_events(cursor, timeout=15.0)
                if gap:
                    cursor = seq
                    yield 'event: reset\ndata: {}\n\n'
                    continue
                if not batch:
                    # 心跳：保持连接不被代理/浏览器掐断
                    yield ': ping %d\n\n' % int(time.time())
                    continue
                for event in batch:
                    cursor = event.get('seq', cursor)
                    yield 'id: %d\nevent: kernel\ndata: %s\n\n' % (
                        cursor, json.dumps(event, ensure_ascii=False))

        resp = Response(stream_with_context(_stream()),
                        mimetype='text/event-stream')
        resp.headers['Cache-Control'] = 'no-cache'
        resp.headers['X-Accel-Buffering'] = 'no'
        return resp

    @app.route('/api/modules/<key>/channels')
    def module_channels(key):
        r = _check_token(write=False)
        if r is not None:
            return r
        if key not in service.keys():
            return _error(404, 'module_not_found', '模块不存在: %s' % key)
        return jsonify({'ok': True, 'key': key,
                        'channels': service.channels(key)})

    @app.route('/api/modules/<key>/channels', methods=['POST'])
    def module_channel_add(key):
        r = _check_token(write=True)
        if r is not None:
            return r
        if key not in service.keys():
            return _error(404, 'module_not_found', '模块不存在: %s' % key)
        body = _json_body()
        res = service.submit_command(key, 'add_channel', body,
                                     timeout=_READ_TIMEOUT_S)
        status = 200 if res.get('ok') else 400
        return jsonify(dict(res, ok=res.get('ok', False))), status

    @app.route('/api/modules/<key>/channels/<int:cid>', methods=['PATCH'])
    def module_channel_update(key, cid):
        r = _check_token(write=True)
        if r is not None:
            return r
        if key not in service.keys():
            return _error(404, 'module_not_found', '模块不存在: %s' % key)
        body = _json_body()
        body['channel_id'] = cid
        res = service.submit_command(key, 'update_channel', body,
                                     timeout=_READ_TIMEOUT_S)
        status = 200 if res.get('ok') else 400
        return jsonify(dict(res, ok=res.get('ok', False))), status

    @app.route('/api/modules/<key>/channels/<int:cid>', methods=['DELETE'])
    def module_channel_remove(key, cid):
        r = _check_token(write=True)
        if r is not None:
            return r
        if key not in service.keys():
            return _error(404, 'module_not_found', '模块不存在: %s' % key)
        res = service.submit_command(
            key, 'remove_channel', {'channel_id': cid},
            timeout=_READ_TIMEOUT_S)
        status = 200 if res.get('ok') else 400
        return jsonify(dict(res, ok=res.get('ok', False))), status

    @app.route('/api/modules/<key>/channels/<int:cid>/connect', methods=['POST'])
    def module_channel_connect(key, cid):
        r = _check_token(write=True)
        if r is not None:
            return r
        if key not in service.keys():
            return _error(404, 'module_not_found', '模块不存在: %s' % key)
        res = service.submit_command(
            key, 'connect', {'channel_id': cid}, timeout=_READ_TIMEOUT_S)
        status = 200 if res.get('ok') else 400
        return jsonify(dict(res, ok=res.get('ok', False))), status

    @app.route('/api/modules/<key>/channels/<int:cid>/disconnect', methods=['POST'])
    def module_channel_disconnect(key, cid):
        r = _check_token(write=True)
        if r is not None:
            return r
        if key not in service.keys():
            return _error(404, 'module_not_found', '模块不存在: %s' % key)
        res = service.submit_command(
            key, 'disconnect', {'channel_id': cid}, timeout=_READ_TIMEOUT_S)
        status = 200 if res.get('ok') else 400
        return jsonify(dict(res, ok=res.get('ok', False))), status

    @app.route('/api/modules/<key>/series')
    def module_series(key):
        r = _check_token(write=False)
        if r is not None:
            return r
        if key not in service.keys():
            return _error(404, 'module_not_found', '模块不存在: %s' % key)
        try:
            limit = int(request.args.get('limit', 2000))
        except ValueError:
            return _error(400, 'bad_request', 'limit 必须是整数')
        limit = max(1, limit)
        return jsonify({'ok': True, 'key': key,
                        'points': service.series(key, limit=limit),
                        'channels': service.series_channels(key, limit=limit)})

    @app.route('/api/modules/<key>/export.csv')
    def module_csv(key):
        r = _check_token(write=False)
        if r is not None:
            return r
        text = service.csv(key)
        if text is None:
            return _error(404, 'module_not_found', '模块不存在: %s' % key)
        return Response(text, mimetype='text/csv',
                        headers={'Content-Disposition':
                                 'attachment; filename="%s.csv"' % key})

    # --------------------------------------------------------
    # 控制端点（局域网来源需要 token，本机回环免令牌）
    # --------------------------------------------------------
    @app.route('/api/modules/<key>/icon.svg')
    def module_icon(key):
        """模块 SVG 图标（模块目录 assets/ 下）；无图标返回 404，前端回退文字。

        支持 ?theme=dark：优先返回同名 *_dark.svg（白字）变体，
        不存在时回退浅色文件；默认（或 ?theme=light）返回注册时的浅色文件。
        """
        r = _check_token(write=False)
        if r is not None:
            return r
        if key not in service.keys():
            return _error(404, 'module_not_found', '模块不存在: %s' % key)
        path = service.icon_path(key)
        if not path or not os.path.isfile(path):
            return _error(404, 'no_icon', '模块无 SVG 图标: %s' % key)
        if request.args.get('theme') == 'dark':
            dark_path = path[:-4] + '_dark.svg'
            if os.path.isfile(dark_path):
                path = dark_path
        resp = send_file(path, mimetype='image/svg+xml', conditional=True)
        resp.headers['Cache-Control'] = 'no-cache'
        return resp

    @app.route('/api/modules/<key>/collect', methods=['POST'])
    def collect(key):
        r = _check_token(write=True)
        if r is not None:
            return r
        if key not in service.keys():
            return _error(404, 'module_not_found', '模块不存在: %s' % key)
        action = _json_body().get('action', '')
        if action not in ('start', 'stop', 'toggle'):
            return _error(400, 'bad_request',
                          'action 必须是 start / stop / toggle')
        res = service.submit_command(key, action, timeout=_READ_TIMEOUT_S)
        if res.get('error') == 'timeout':
            return _error(504, 'timeout', res.get('message', 'GUI 未响应'))
        status = 200 if res.get('ok') else 409
        return jsonify(dict(res, ok=res.get('ok', False))), status

    @app.route('/api/modules/<key>/command', methods=['POST'])
    def command(key):
        r = _check_token(write=True)
        if r is not None:
            return r
        if key not in service.keys():
            return _error(404, 'module_not_found', '模块不存在: %s' % key)
        body = _json_body()
        action = body.get('action', '')
        if not action:
            return _error(400, 'bad_request', '缺少 action')
        res = service.submit_command(key, action, body.get('params') or {},
                                     timeout=_READ_TIMEOUT_S)
        if res.get('error') == 'timeout':
            return _error(504, 'timeout', res.get('message', 'GUI 未响应'))
        if res.get('error') == 'unsupported_action':
            return _error(400, 'unsupported_action',
                          res.get('message', '动作不支持'))
        status = 200 if res.get('ok') else 400
        return jsonify(dict(res, ok=res.get('ok', False))), status

    @app.route('/api/modules/<key>/params', methods=['POST'])
    def params(key):
        r = _check_token(write=True)
        if r is not None:
            return r
        if key not in service.keys():
            return _error(404, 'module_not_found', '模块不存在: %s' % key)
        body = _json_body()
        new_params = body.get('params')
        if not isinstance(new_params, dict) or not new_params:
            return _error(400, 'bad_request', 'params 必须是非空对象')
        # 第一版只开放安全项：采样间隔（ms）与显示单位；校准系数不开放
        allowed = {}
        for k, v in new_params.items():
            if k in ('sample_interval_ms', 'unit'):
                allowed[k] = v
        if not allowed:
            return _error(400, 'forbidden_param',
                          '仅允许修改 sample_interval_ms / unit')
        results = []
        ok_all = True
        for k, v in allowed.items():
            if k == 'sample_interval_ms':
                res = service.submit_command(
                    key, 'set_sample_interval', {'ms': v},
                    timeout=_READ_TIMEOUT_S)
            else:  # unit
                res = service.submit_command(key, 'set_unit', {'unit': v},
                                             timeout=_READ_TIMEOUT_S)
            results.append(res)
            if not res.get('ok'):
                ok_all = False
        return jsonify({'ok': ok_all, 'results': results})

    @app.route('/api/token/regenerate', methods=['POST'])
    def regenerate():
        r = _check_token(write=True)
        if r is not None:
            return r
        regen = getattr(app, '_token_regen', None)
        if not callable(regen):
            return _error(503, 'not_supported', '当前运行方式不支持在线重生密钥')
        new_token = regen()
        app._token = new_token
        return jsonify({'ok': True, 'token': new_token,
                        'message': '旧密钥立即失效（本机访问不受影响）'})

    # --------------------------------------------------------
    # 网页字体与外观设置
    #
    # 字体选择存服务端（app_cfg.webFontFamily）而非 localStorage：
    # 局域网下手机/别的电脑打开仪表盘即自动用上同一字体，换浏览器也一致，
    # 且与桌面端「应用字体」互不干扰。
    # --------------------------------------------------------
    def _web_font_family():
        """当前仪表盘字体名；'' 表示系统默认。配置缺失时回退内嵌字体。"""
        if app_cfg is None:
            return WEB_FONT_FACE
        try:
            return str(app_cfg.webFontFamily.value or '')
        except Exception:
            return WEB_FONT_FACE

    @app.route('/font.css')
    def font_css():
        """内嵌字体 @font-face：浏览器只认 woff2/ttf，TTF 压成 woff2 省一半流量。

        返回 CSS 而不是字体本身，是为了让 index.html 只写一行 <link>：
        具体文件名与格式由服务端决定，缺文件时自动降级。
        """
        face = WEB_FONT_FACE
        path, mime = _font_file_for(WEB_FONT_BASE)
        if path is None:
            # 缺字体文件：返回空 CSS，浏览器用系统字体，页面照常工作
            return Response('/* 内嵌字体缺失，回退系统字体 */\n',
                            mimetype='text/css')
        fmt = 'woff2' if path.suffix == '.woff2' else 'truetype'
        css = (
            "@font-face{\n"
            "  font-family:'%s';\n"
            "  src:url('/font-file?v=%s') format('%s');\n"
            "  font-weight:400;\n"
            "  font-display:swap;\n"
            "}\n" % (face, path.stat().st_mtime_ns, fmt)
        )
        resp = Response(css, mimetype='text/css')
        resp.headers['Cache-Control'] = 'no-cache'
        return resp

    @app.route('/font-file')
    def font_file():
        """内嵌字体文件本体（带长缓存：文件名带 mtime 版本号，可放心缓存）。"""
        path, mime = _font_file_for(WEB_FONT_BASE)
        if path is None:
            return _error(404, 'no_font', '未找到内嵌字体文件')
        resp = send_file(path, mimetype=mime, conditional=True)
        resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        return resp

    @app.route('/api/settings/web')
    def web_settings():
        r = _check_token(write=False)
        if r is not None:
            return r
        installed = []
        if app_cfg is not None:
            try:
                from core_ui import available_font_families
                installed = available_font_families()
            except Exception:
                installed = []
        font_ok = _font_file_for(WEB_FONT_BASE)[0] is not None
        # 选项：内嵌字体恒在前；其余仅列出本机确实装了的，避免选了没效果
        choices = []
        if font_ok:
            choices.append({'value': WEB_FONT_FACE,
                            'label': WEB_FONT_FACE + '（内嵌）'})
        for value, label in WEB_FONT_CHOICES:
            if value == '':
                choices.append({'value': '', 'label': label})
            elif not installed or value in installed:
                choices.append({'value': value, 'label': label})
        ip = _lan_ip()
        port = getattr(app, '_port', 0)
        lan_on = bool(app._allow_lan)
        return jsonify({'ok': True, 'font': _web_font_family(),
                        'font_embedded': font_ok, 'font_name': WEB_FONT_FACE,
                        'choices': choices,
                        # 局域网访问：以当前实际监听的 app 为准（重启后由插件回填）
                        'lan_access': lan_on,
                        'lan_available': bool(ip),
                        # 只有真开了局域网才给地址：否则前端会显示一个连不上的地址
                        'lan_url': ('http://%s:%s' % (ip, port))
                        if lan_on and ip and port else '',
                        'auth_enabled': bool(app._token)})

    @app.route('/api/settings/web', methods=['POST'])
    def web_settings_set():
        r = _check_token(write=True)
        if r is not None:
            return r
        body = _json_body()
        if 'lan_access' in body:
            return _set_lan_access(body.get('lan_access'))
        if app_cfg is None:
            return _error(503, 'not_supported', '当前运行方式不支持修改网页设置')
        font = body.get('font')
        if not isinstance(font, str):
            return _error(400, 'bad_request', 'font 必须是字符串')
        font = font.strip()
        allowed = {c[0] for c in WEB_FONT_CHOICES} | {WEB_FONT_FACE}
        if font not in allowed:
            return _error(400, 'bad_value',
                          '不支持的字体：%s' % (font or '(空)'))
        try:
            app_cfg.webFontFamily.value = font
            app_cfg.save()
        except Exception as e:
            return _error(500, 'save_failed', '保存失败：%s' % e)
        return jsonify({'ok': True, 'font': font, 'message': '字体已切换'})

    def _set_lan_access(enabled):
        """网页端切换「局域网访问」：写配置并由插件重启服务重新绑定网卡。"""
        ctl = getattr(app, '_lan_control', None)
        if not callable(ctl):
            return _error(503, 'not_supported', '当前运行方式不支持切换局域网访问')
        if not isinstance(enabled, bool):
            return _error(400, 'bad_request', 'lan_access 必须是布尔值')
        ok, msg = ctl(enabled)
        if not ok:
            return _error(500, 'restart_failed', msg)
        # 注意：这里读的是**旧 app** 的属性（服务已重启，旧 app 即将被回收），
        # 但端口在重启前后不变（同端口重绑），lan_url 仍正确
        ip = _lan_ip()
        port = getattr(app, '_port', 0)
        return jsonify({'ok': True, 'lan_access': enabled, 'message': msg,
                        'lan_url': ('http://%s:%s' % (ip, port))
                        if enabled and ip and port else ''})

    # --------------------------------------------------------
    # 仪表盘静态页（/ 返回 index.html）
    # --------------------------------------------------------
    @app.route('/')
    def index():
        resp = app.make_response(app.send_static_file('index.html'))
        # 页面本身不缓存：改文案/换版本后刷新即生效
        resp.headers['Cache-Control'] = 'no-cache'
        return resp

    @app.errorhandler(404)
    def not_found(_e):
        return _error(404, 'not_found', '资源不存在')

    @app.errorhandler(500)
    def server_error(_e):
        return _error(500, 'internal_error', '服务器内部错误')

    return app
