# -*- coding: utf-8 -*-
"""
flaskserver — 实验数据 HTTP 接口插件（传输层）

把 core.DataService 的能力翻译成 HTTP 端点，供 AI Agent / 浏览器仪表盘使用。
本插件不含业务逻辑、不持有数据：删掉整个目录，主程序行为完全不变。

# === PLUGIN META ===
# name: flaskserver
# desc: 实验数据 HTTP 接口（AI Agent / 浏览器仪表盘）
# class: FlaskServerPlugin
# requires: flask
# ===================
"""

import os
import sys
import secrets
import threading

# 顶层绝不 import flask —— flask 未装时插件仍须可加载（缺失无影响）。
# 可用性探测用 find_spec 延迟完成，真正导入在 start() 里。

_plugin_dir = os.path.dirname(os.path.abspath(__file__))
if _plugin_dir not in sys.path:
    # server.py 以「from . import」相对导入使用；这里只保证 web 静态目录等
    # 资源路径解析方便。不把目录插到 sys.path 前面，避免通用名冲突。
    sys.path.append(_plugin_dir)

log = None  # attach() 时由主程序注入 core.get_logger


class FlaskServerPlugin:
    """flaskserver 插件：生命周期 + HTTP 服务托管。"""

    def __init__(self):
        self._service = None        # core.DataService
        self._app_cfg = None        # core.app_cfg
        self._started_at = None
        self._httpd = None
        self._thread = None
        self._app = None
        self._lock = threading.Lock()

    # ---- 元信息 ----
    @property
    def name(self):
        return 'flaskserver'

    def available(self):
        """探测 flask 是否可用。

        Returns:
            (bool, str): (是否可用, 不可用时的提示文案)
        """
        import importlib.util
        try:
            spec = importlib.util.find_spec('flask')
            # 命名空间包片段（目录同名冲突）不算真正可用
            if spec is None or getattr(spec, 'origin', None) in (None, 'namespace'):
                return False, '未安装 flask：pip install flask'
            import importlib
            mod = importlib.import_module('flask')
            getattr(mod, 'Flask')
            return True, ''
        except Exception as e:
            return False, 'flask 不可用：%s（pip install flask）' % e

    # ---- 生命周期 ----
    def attach(self, context):
        """主程序注入依赖：{'service': DataService, 'app_cfg': AppConfig, 'log': logger}"""
        global log
        self._service = context.get('service')
        self._app_cfg = context.get('app_cfg')
        log = context.get('log')

    def start(self, host='127.0.0.1', port=8765, token=None, allow_lan=None,
              enable_cors=None):
        """启动 HTTP 服务（werkzeug make_server，daemon 线程）。

        Returns:
            (bool, str): (是否成功, 失败原因/成功后的地址)
        """
        with self._lock:
            if self._httpd is not None:
                return True, self.url
            ok, hint = self.available()
            if not ok:
                return False, hint
            try:
                from . import server as server_mod
            except Exception as e:
                return False, '插件加载失败：%s' % e

            if allow_lan is None:
                allow_lan = bool(self._app_cfg.serverLanAccess.value) if self._app_cfg else False
            if enable_cors is None:
                enable_cors = bool(self._app_cfg.serverCors.value) if self._app_cfg else False
            if allow_lan and host == '127.0.0.1':
                host = '0.0.0.0'
            if not token and self._app_cfg is not None:
                token = self._app_cfg.serverToken.value or self.regenerate_token()

            try:
                self._app = server_mod.build_app(
                    self._service, token=token,
                    allow_lan=allow_lan, enable_cors=enable_cors)
                # /api/token/regenerate 回调：重生密钥并持久化
                self._app._token_regen = self.regenerate_token
                from werkzeug.serving import make_server
                self._httpd = make_server(host, int(port), self._app, threaded=True)
            except Exception as e:
                self._httpd = None
                self._app = None
                return False, '服务启动失败：%s' % e

            self._started_at = server_mod.time.time()
            import threading as _th
            self._thread = _th.Thread(target=self._httpd.serve_forever,
                                      kwargs={'poll_interval': 0.5},
                                      daemon=True, name='flaskserver')
            self._thread.start()
            if log:
                log.info('数据接口已启动: http://%s:%s', host, port)
            return True, self.url

    def stop(self):
        """停止 HTTP 服务并释放端口。"""
        with self._lock:
            if self._httpd is None:
                return
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception as e:
                if log:
                    log.warning('数据接口停止异常: %s', e)
            self._httpd = None
            self._thread = None
            self._app = None
            if log:
                log.info('数据接口已停止')

    def is_running(self):
        return self._httpd is not None

    @property
    def url(self):
        if self._httpd is None:
            return ''
        host, port = self._httpd.server_address[:2]
        if host in ('0.0.0.0', '::'):
            host = '127.0.0.1'
        return 'http://%s:%s' % (host, port)

    # ---- token ----
    def regenerate_token(self):
        """重生成访问密钥并持久化。旧 token 立即失效需重启服务生效。"""
        token = secrets.token_urlsafe(24)
        if self._app_cfg is not None:
            self._app_cfg.serverToken.value = token
        if log:
            log.info('数据接口密钥已重新生成')
        return token

    @property
    def token(self):
        if self._app_cfg is not None and self._app_cfg.serverToken.value:
            return self._app_cfg.serverToken.value
        return self.regenerate_token()
