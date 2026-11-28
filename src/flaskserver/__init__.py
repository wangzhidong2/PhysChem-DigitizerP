# -*- coding: utf-8 -*-
"""
flaskserver — 实验数据 HTTP 接口插件（传输层）

把 core.KernelRegistry 的能力翻译成 HTTP 端点，供 AI Agent / 浏览器仪表盘使用。
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
        self._service = None        # core.KernelRegistry
        self._app_cfg = None        # core_ui.app_cfg
        self._started_at = None
        self._httpd = None
        self._thread = None
        self._app = None
        self._lock = threading.Lock()
        # 局域网开关变化回调（主程序注入）：服务重启后通知 GUI 刷新数据接口卡片。
        # 回调会在 Flask 请求线程里触发，实现方须自行切回 GUI 线程（如 Signal.emit）。
        self.on_state_change = None
        # 局域网切换串行锁：**不能复用 self._lock**——set_lan_access 内部要调
        # stop()/start()，两者都会去拿 self._lock，复用会立刻自死锁。
        self._lan_lock = threading.Lock()
        # 重绑网卡期间置位：此时 _httpd 为 None，外部线程若插进来调 start()
        # 会抢先按**旧配置**绑端口，导致「配置说局域网开、实际只绑回环」。
        # 置位后 start() 直接拒绝，把窗口留给 set_lan_access 自己完成重绑。
        self._rebinding = False

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
        """主程序注入依赖：{'service': KernelRegistry, 'app_cfg': AppConfig, 'log': logger}"""
        global log
        self._service = context.get('service')
        self._app_cfg = context.get('app_cfg')
        log = context.get('log')

    def start(self, host='127.0.0.1', port=8765, token=None, allow_lan=None,
              enable_cors=None, enable_auth=None, _rebind=False):
        """启动 HTTP 服务（werkzeug make_server，daemon 线程）。

        鉴权模型：**本机回环免令牌，局域网才按需令牌**。
        `token` 只用于非回环来源；`allow_lan=False` 时服务绑定 127.0.0.1，
        局域网根本连不上，故不需要令牌。

        Args:
            _rebind: 内部参数。set_lan_access 换绑网卡时置 True，用于放行
                重绑窗口；外部调用方一律不传，重绑期间会被拒绝，避免
                抢先按旧配置绑端口。
        Returns:
            (bool, str): (是否成功, 失败原因/成功后的地址)
        """
        with self._lock:
            if self._httpd is not None:
                return True, self.url
            if self._rebinding and not _rebind:
                # 另一个线程正在换绑网卡，等它绑好即可，别抢
                return False, '数据接口正在切换局域网访问，请稍候重试'
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
            if enable_auth is None:
                enable_auth = bool(self._app_cfg.serverAuth.value) if self._app_cfg else True
            if allow_lan and host == '127.0.0.1':
                host = '0.0.0.0'
            if not allow_lan:
                # 只监听回环：局域网连不上，令牌没有意义，置空避免误报鉴权
                token = ''
            elif not enable_auth:
                # 局域网开着但用户显式关掉鉴权：token 置空，非回环来源也免校验
                token = ''
            elif not token and self._app_cfg is not None:
                token = self._app_cfg.serverToken.value or self.regenerate_token()

            try:
                self._app = server_mod.build_app(
                    self._service, token=token,
                    allow_lan=allow_lan, enable_cors=enable_cors,
                    app_cfg=self._app_cfg)
                # /api/token/regenerate 回调：重生密钥并持久化
                self._app._token_regen = self.regenerate_token
                # /api/settings/web 回调：网页端在线切换「局域网访问」
                self._app._lan_control = self.set_lan_access
                self._app._port = int(port)
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
                # 局域网开着时令牌才生效：直接打到控制台，省得用户去卡片里翻。
                # 本机回环免密钥，令牌为空时不打印（没有可打印的东西）。
                if token:
                    lan_ip = server_mod.lan_ip()
                    log.info('局域网访问密钥: %s', token)
                    log.info('局域网设备访问: http://%s:%s  (请求头 X-Auth-Token 或地址 ?token=)',
                             lan_ip or '<本机局域网IP>', port)
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

    def set_lan_access(self, enabled):
        """在线切换「局域网访问」：写配置并重启服务以重新绑定网卡。

        监听地址在绑定时就定死了，运行时改不了，只能 stop() → start()。
        本方法由网页设置（Flask 请求线程）调用：werkzeug 的 threaded server
        把每个请求跑在 daemon 线程里，server_close() 不会等待当前请求线程，
        因此在这里重启不会自锁（已实测：stop+start 约 0.5s，端口可复用）。

        失败时回滚：若新绑定失败，退回旧绑定，配置也回退到旧值，避免
        「配置写着局域网开、实际服务没起来」的不一致。

        Args:
            enabled: True=监听 0.0.0.0（局域网可达），False=退回 127.0.0.1
        Returns:
            (bool, str): (是否成功, 提示文案)
        """
        enabled = bool(enabled)
        if self._app_cfg is None:
            return False, '当前运行方式不支持切换局域网访问'
        # 整个「停→起」流程必须串行：两个请求线程同时切换会互相踩，
        # 一个刚 start 完另一个又 stop，最后一次绑定可能和配置对不上。
        with self._lan_lock:
            if self._httpd is None:
                return False, '数据接口未运行，请先在桌面端开启'
            old_enabled = bool(self._app_cfg.serverLanAccess.value)
            old_host = self._httpd.server_address[0]
            # 期望绑定地址与实际监听不一致时才重启（例如配置被外部改过）
            want_host = '0.0.0.0' if enabled else '127.0.0.1'
            if enabled == old_enabled and str(old_host) == want_host:
                return True, ('局域网访问已开启' if enabled else '局域网访问已关闭')
            port = int(self._httpd.server_address[1])
            old_port = port
            old_allow_lan = old_enabled
            self._app_cfg.serverLanAccess.value = enabled
            try:
                self._app_cfg.save()
            except Exception as e:
                if log:
                    log.warning('保存局域网访问设置失败: %s', e)
            # 从这里到 start 结束是「重绑窗口」：_httpd 为 None，必须挡住
            # 外部线程的 start()，否则它会按旧配置抢先绑端口
            self._rebinding = True
            try:
                self.stop()
                ok, msg = self.start(port=port, allow_lan=enabled,
                                     enable_cors=bool(self._app_cfg.serverCors.value),
                                     _rebind=True)
            finally:
                self._rebinding = False
            if not ok:
                # 回滚：退到旧绑定，配置回退
                if log:
                    log.error('切换局域网访问失败，回滚: %s', msg)
                self._app_cfg.serverLanAccess.value = old_allow_lan
                try:
                    self._app_cfg.save()
                except Exception:
                    pass
                self._rebinding = True
                try:
                    rollback_ok, rollback_msg = self.start(
                        host=old_host, port=old_port, allow_lan=old_allow_lan,
                        enable_cors=bool(self._app_cfg.serverCors.value),
                        _rebind=True)
                finally:
                    self._rebinding = False
                # 无论回滚成败都要通知 GUI：服务可能已经停在中间态，
                # 卡片必须跟着刷新，否则界面还显示「运行中」而实际没起来
                self._notify_state_change()
                if not rollback_ok:
                    if log:
                        log.error('回滚也失败: %s', rollback_msg)
                    return False, '切换失败且回滚失败：%s（原错误：%s）' % (rollback_msg, msg)
                return False, '切换失败已回滚：%s' % msg
            if log:
                if enabled:
                    # 开局域网时打印真实 IP，别用会退回 127.0.0.1 的 self.url
                    log.info('局域网访问已开启，局域网设备请访问: %s',
                             self.lan_url or '（未检测到局域网网卡）')
                else:
                    log.info('局域网访问已关闭（%s）', self.url)
            self._notify_state_change()
            return True, ('局域网访问已开启，同一网络的设备现在可以访问'
                          if enabled else '局域网访问已关闭，服务已退回本机监听')

    def _notify_state_change(self):
        """通知主程序数据接口卡片状态变化（跨线程安全由实现方保证）。"""
        notify = self.on_state_change
        if callable(notify):
            try:
                notify()
            except Exception as e:
                if log:
                    log.warning('局域网切换回调异常: %s', e)

    @property
    def url(self):
        """服务地址；绑 0.0.0.0 时仍返回本机回环地址（本机访问用这个）。"""
        if self._httpd is None:
            return ''
        host, port = self._httpd.server_address[:2]
        if host in ('0.0.0.0', '::'):
            host = '127.0.0.1'
        return 'http://%s:%s' % (host, port)

    @property
    def lan_url(self):
        """局域网设备该用的地址；只在「局域网开着且有网卡」时返回，否则空串。

        与 url 的区别：url 永远给本机回环（0.0.0.0 会被换成 127.0.0.1），
        lan_url 给同一网络里其他设备该访问的真实 IP。
        """
        if self._httpd is None:
            return ''
        if self._app_cfg is None or not bool(self._app_cfg.serverLanAccess.value):
            return ''
        host, port = self._httpd.server_address[:2]
        if host not in ('0.0.0.0', '::'):
            return ''          # 只在回环上监听，局域网访问不到
        try:
            from . import server as server_mod
            ip = server_mod.lan_ip()
        except Exception:
            ip = ''
        if not ip:
            return ''
        return 'http://%s:%s' % (ip, port)

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
