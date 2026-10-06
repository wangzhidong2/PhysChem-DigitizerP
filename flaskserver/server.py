# -*- coding: utf-8 -*-
"""
flaskserver.server — Flask app、路由、token 校验、静态托管

只做一件事：把 core.DataService 的方法翻译成 HTTP 端点。
不持有数据、不认识任何具体传感器、不操作任何 Qt 控件。
"""

import time
from pathlib import Path

from flask import Flask, jsonify, request, Response

_WEB_DIR = Path(__file__).parent / 'web'
_READ_TIMEOUT_S = 8.0


# ============================================================
# 错误响应与 token 校验
# ============================================================

def _error(code, error, message):
    resp = jsonify({'ok': False, 'error': error, 'message': message})
    resp.status_code = code
    return resp


def build_app(service, token='', allow_lan=False, enable_cors=False):
    """构建 Flask app。

    Args:
        service: core.DataService 实例（数据与控制总线）
        token: 访问密钥；空字符串表示写操作也免校验（不推荐）
        allow_lan: 局域网模式 —— 读操作也强制 token
        enable_cors: 是否允许跨域
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
        })

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
    def _json_body():
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}

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
