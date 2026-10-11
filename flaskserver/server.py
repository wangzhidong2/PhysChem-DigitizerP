# -*- coding: utf-8 -*-
"""
flaskserver.server — Flask app、路由、token 校验、静态托管

只做一件事：把 core.DataService 的方法翻译成 HTTP 端点。
不持有数据、不认识任何具体传感器、不操作任何 Qt 控件。
"""

import time
from pathlib import Path

from flask import Flask, jsonify, request, Response, send_file

_WEB_DIR = Path(__file__).parent / 'web'
#: 内嵌字体目录：与主程序共用 assets/fonts/（本文件在 flaskserver/ 下，上溯两级为仓库根）
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


def build_app(service, token='', allow_lan=False, enable_cors=False,
              app_cfg=None):
    """构建 Flask app。

    Args:
        service: core.DataService 实例（数据与控制总线）
        token: 访问密钥；空字符串表示写操作也免校验（不推荐）
        allow_lan: 局域网模式 —— 读操作也强制 token
        enable_cors: 是否允许跨域
        app_cfg: core.app_cfg（网页字体等外观设置读写用）；None 时只读回退默认
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

    def _check_token(write=False):
        """token 校验：写操作始终需要；读操作仅局域网模式需要。

        Returns:
            None 通过；否则返回 401 响应
        """
        if not app._token:
            return None
        if not (write or allow_lan):
            return None
        supplied = (request.headers.get('X-Auth-Token')
                    or request.args.get('token') or '')
        if supplied == app._token:
            return None
        return _error(401, 'unauthorized', '缺少或错误的访问密钥')

    # --------------------------------------------------------
    # 读取端点（回环地址下默认免 token）
    # --------------------------------------------------------
    @app.route('/api/health')
    def health():
        r = _check_token(write=False)
        if r is not None:
            return r
        return jsonify({
            'ok': True,
            'plugin': 'flaskserver',
            'version': 1,
            'uptime_s': round(time.time() - app._start_time, 1),
            'flask': True,
            'modules_n': len(service.keys()),
            'lan_access': allow_lan,
            'auth_enabled': bool(app._token),
        })

    @app.route('/api/auth/check')
    def auth_check():
        """登录探测：始终按写级别校验（token 非空时必须带对），无副作用。

        - 鉴权关闭 → 200 且 auth_enabled=false（前端免登录直接进）
        - 密钥正确 → 200 且 auth_enabled=true
        - 密钥缺失/错误 → 401（前端据此显示登录页）
        """
        r = _check_token(write=True)
        if r is not None:
            return r
        return jsonify({'ok': True, 'auth_enabled': bool(app._token)})

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
        return jsonify({'ok': True, 'key': key,
                        'points': service.series(key, limit=max(1, limit))})

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
    # 控制端点（始终需要 token）
    # --------------------------------------------------------
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
                        'message': '旧密钥立即失效'})

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
                from core import available_font_families
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
        return jsonify({'ok': True, 'font': _web_font_family(),
                        'font_embedded': font_ok, 'font_name': WEB_FONT_FACE,
                        'choices': choices})

    @app.route('/api/settings/web', methods=['POST'])
    def web_settings_set():
        r = _check_token(write=True)
        if r is not None:
            return r
        if app_cfg is None:
            return _error(503, 'not_supported', '当前运行方式不支持修改网页设置')
        body = _json_body()
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

    # --------------------------------------------------------
    # 仪表盘静态页（/ 返回 index.html）
    # --------------------------------------------------------
    @app.route('/')
    def index():
        return app.send_static_file('index.html')

    @app.errorhandler(404)
    def not_found(_e):
        return _error(404, 'not_found', '资源不存在')

    @app.errorhandler(500)
    def server_error(_e):
        return _error(500, 'internal_error', '服务器内部错误')

    return app
