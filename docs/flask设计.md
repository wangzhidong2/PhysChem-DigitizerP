# flaskserver 插件 — 开发文档

> 状态：**设计稿**（尚未实现）
> 目标读者：本项目的开发者（含 AI Agent）
> 相关：`AGENTS.md`（项目总规约）、`README.md`（用户文档）

---

## 1. 目标与原则

给运行中的上位机加一个 **HTTP 数据接口**，让外部程序读取实验数据、并在授权下控制仪器：

1. **AI Agent / MCP 调用** —— 让 OpenCode、DSH 等 agent 直接读实验数据做分析（对应 `README.md` 第 265 行的设想）。
2. **浏览器仪表盘** —— 用手机或另一台电脑打开网页实时看曲线，不装任何客户端。

### 1.1 首要原则：核心在主程序，插件只是传输层

**Flask 程序只是辅助。** 一切有实质价值的逻辑都必须在主程序里实现：

| 能力 | 归属 | 理由 |
|---|---|---|
| 数据总线（模块注册、快照、序列、CSV） | **主程序 `core.py`** | 与传输方式无关，MCP / 脚本 / 未来的其他接口都要复用 |
| 控制命令队列 + GUI 线程执行 | **主程序 `core.py`** | 跨线程调度是程序内部事务，不该由插件负责 |
| 模块适配（`api_snapshot` / `api_command`） | **主程序各传感器模块** | 每个模块最清楚自己的数据长什么样 |
| 配置（端口 / token / 开关） | **主程序 `core.py`** | 与现有 `AppConfig` 同源，受"恢复默认设置"管辖 |
| UI（主页启动按钮、设置项） | **主程序 `main.py`** | 插件缺失时 UI 依然要正确降级 |
| **把上述能力通过 HTTP 暴露出去** | **插件 `flaskserver/`** | 这才是插件的唯一职责 |

**推论**：插件应当薄到"只翻译协议"。它不含业务逻辑、不持有数据、不认识任何具体传感器；删掉它，主程序的能力分毫不少（只是没有 HTTP 出口）。

### 1.2 三条硬约束

| 约束 | 含义 |
|---|---|
| **可插拔** | 整个 `flaskserver/` 目录删掉，主程序行为与体验**完全不变** |
| **依赖可选** | 未安装 `flask` 时程序照常启动，与 `pyserial` / `bleak` / 图表引擎的降级方式一致 |
| **前端分离** | HTML / JS / CSS 是独立文件，Python 代码里**不出现任何 HTML 字符串** |

---

## 2. 非目标（本期不做）

- ❌ 不做多用户 / 权限分级（只有"本机"与"带 token"两档）
- ❌ 不做 HTTPS（本机回环 + 局域网明文，文档中明确告知风险）
- ❌ 不做数据落库（历史数据只在内存 + CSV 导出，与主程序现状一致）
- ❌ 不做修改校准参数的图形化前端（参数写入只在 API 层提供，且限白名单）
- ❌ 不替换主程序现有的 CSV 保存逻辑（模块 `save_data` 保持原样，API 另提供导出）
- ❌ 插件不做任何数据加工（降采样、CSV 生成都在主程序的 `DataService` 里）

---

## 3. 命名与目录结构

### 3.1 为什么不能叫 `flask/`

`python main.py` 启动时仓库根目录位于 `sys.path[0]`；六个传感器模块里还各自有一句

```python
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
```

把仓库根**插到 `sys.path` 最前面**。因此根目录下名为 `flask` 的文件夹会参与 `import flask` 的解析：

| 情况 | 后果 |
|---|---|
| `flask/` 无 `__init__.py` | 按 PEP 420 只是"命名空间片段"，扫描继续、site-packages 的正规包胜出 → 暂不冲突 |
| `flask/` 有 `__init__.py` | 成为正规包，**顶掉真正的 Flask** → `from flask import Flask` 导入到插件目录，功能报废 |
| **Flask 未安装**且 `flask/` 存在 | `find_spec('flask')` 非空、`import_module('flask')` 成功（命名空间包）→ **可用性探测误报"已安装"**，直到真正 `from flask import Flask` 才崩 |

第三条恰好破坏"缺失没有影响"这一核心需求，所以**目录名必须避开 `flask` 这个精确名字**。

**决定：根目录 `flaskserver/`。** 要改名只需改加载器里的一处常量。

### 3.2 目录结构

```
PhysChem-DigitizerP/
├── main.py                       ← 插件扫描/加载/注入；主页「数据接口」按钮
├── core.py                       ← 新增 DataService（数据与控制总线）+ 配置项
├── 传感器代码/                     ← 六个模块各加 api_snapshot() / api_command()
└── flaskserver/                  ← 插件目录（整个删掉 → 程序毫无影响）
    ├── __init__.py               ← 识别区 + available() + Plugin 类（生命周期）
    ├── server.py                 ← Flask app、路由、token 校验、静态托管、后台线程
    ├── web/                      ← 前端（独立文件，不嵌 Python 字符串）
    │   ├── index.html
    │   ├── app.js
    │   └── style.css
    └── README.md                 ← 插件使用说明（装 flask / 端点清单 / 示例）
```

**对比早期草案**：原先计划的 `plugin.py`（生命周期）与 `bridge.py`（命令队列 + 快照）**已移入主程序**——前者并入 `__init__.py`，后者成为 `core.DataService`。插件只剩两个 Python 文件。

---

## 4. 主程序侧：`core.DataService`（核心）

传输无关的数据与控制总线。**任何**外部接口（Flask / MCP / 未来的 WebSocket）都只依赖它。

```python
class DataService(QObject):
    """实验数据与控制总线（与传输方式无关）。

    - 只读方法（modules / snapshot / series / csv）可由任意线程调用，
      内部只读模块的 Python 数据，不触碰 Qt 控件。
    - submit_command() 由任意线程调用，但命令实际在 GUI 线程执行。
    """

    # ---- 注册 ----
    def register(self, key, name, widget): ...      # main.py 在模块实例化后调用
    def unregister(self, key): ...

    # ---- 只读（任意线程安全）----
    def modules(self) -> list[dict]: ...            # 摘要列表
    def snapshot(self, key, points=0) -> dict: ...  # 单模块快照
    def series(self, key, limit=2000) -> list: ...  # 降采样序列
    def csv(self, key) -> str: ...                  # CSV 文本（含参数注释头）
    def actions(self, key) -> list[str]: ...        # 该模块支持的控制动作

    # ---- 控制（命令在 GUI 线程执行）----
    def submit_command(self, key, action, params=None, timeout=8.0) -> dict: ...
```

### 4.1 命令分发：两级回退

```python
def submit_command(self, key, action, params=None, timeout=8.0):
    # 1) 投进队列，GUI 线程的 QTimer 取出执行
    # 2) 执行时：先试模块自己的 api_command(action, params)
    #    3) 返回 None 或未实现 → 回退到通用动作表
```

通用动作表（在主程序里，按方法名探测，覆盖六个模块共有语义）：

| 动作 | 探测的方法名 |
|---|---|
| `start` | `start_collection` |
| `stop` | `stop_collection` |
| `clear` | `clear_data` |
| `toggle` | `toggle_collection` |

这样六个模块**只需实现自己特有的动作**（去皮、零点校准等），通用动作零重复代码。

### 4.2 为什么放在 `core.py`

`core.py` 的定位就是"集中存放各模块共享的代码"。`DataService` 服务于所有传输层，正是共享代码。若将来它继续膨胀（例如加入历史落库），再拆成独立顶层模块也不影响本设计——插件的接口面不变。

> `core.py` 需补充 `QObject` 到 `PySide6.QtCore` 的导入列表。

---

## 5. 插件侧：HTTP 传输层

`flaskserver/` 的职责，一句话：**把 `DataService` 的方法翻译成 HTTP 端点。**

```python
# flaskserver/__init__.py
class FlaskServerPlugin:
    def available(self) -> tuple[bool, str]:        # 探测 flask 是否可用 + 提示文案
    def attach(self, context) -> None:              # 拿到 DataService / app_cfg / window
    def start(self, host, port, token) -> tuple[bool, str]
    def stop(self) -> None
    def is_running(self) -> bool
    @property
    def url(self) -> str
```

`server.py` 内部：

```python
def build_app(service, token, allow_lan, enable_cors):
    app = Flask(__name__, static_folder=str(Path(__file__).parent / 'web'),
                static_url_path='')
    # ... 路由全部是对 service.xxx() 的薄包装 + token 校验 + 异常→状态码映射
    return app
```

**插件里不允许出现的东西**：数据缓冲、降采样、CSV 拼接、模块方法名、任何 `import` 具体传感器模块、任何 Qt 控件操作。

---

## 6. 加载机制

### 6.1 发现规则

`main.py` 扫描**仓库根目录下的一级子目录**，满足两条即视为插件：

1. 目录内有 `__init__.py`
2. `__init__.py` 前 50 行内含识别区

```python
# === PLUGIN META ===
# name: flaskserver
# desc: 实验数据 HTTP 接口（AI Agent / 浏览器仪表盘）
# class: FlaskServerPlugin
# requires: flask
# ===================
```

复用 `传感器代码/` 已有的"识别区 + 前 50 行"思路；`docs/`、`传感器代码/`、`.venv/` 因无识别区被自然跳过。

### 6.2 加载方式（关键）

**不能**把插件目录加进 `sys.path`（会引入 `server` 这类通用名，有冲突风险）。按显式路径加载成**正规包**：

```python
spec = importlib.util.spec_from_file_location(
    'physchem_plugin_flaskserver',                    # 合成模块名，带前缀杜绝重名
    plugin_dir / '__init__.py',
    submodule_search_locations=[str(plugin_dir)])      # 使 from . import server 可用
```

要点：
- 插件内部一律用**相对导入**（`from . import server`）
- 插件目录**不进 `sys.path`**，目录叫什么名字都不影响导入系统
- 加载失败（语法错误、缺文件）只记日志并跳过，**不影响主程序启动**

### 6.3 启动时序

```
main() 创建 QApplication
   ↓
MainWindow 构造完成（模块已实例化）
   ↓
service = core.DataService()
for name, widget in modules: service.register(...)     ← 核心能力就绪（与插件无关）
   ↓
plugins = load_plugins()          ← 扫描 + 加载，失败静默
   ↓
plugin.attach(context)            ← context 含 service / app_cfg / window
   ↓
主页「数据接口」卡片按 plugin.available() 决定显示与可用性
   ↓
用户点按钮 → plugin.start(host, port, token) → 端口监听
   ↓
再点 / 退出程序 → plugin.stop() → 端口释放
```

---

## 7. 依赖与降级矩阵

插件**顶层绝不 `import flask`**（否则插件加载即失败，违反"缺失无影响"）；改为延迟导入 + 探测。

| # | `flaskserver/` | 已装 flask | 主程序启动 | 主页按钮 | HTTP 端口 |
|---|---|---|---|---|---|
| 1 | 不存在 | — | ✅ 正常 | **不显示** | 不监听 |
| 2 | 存在 | ❌ | ✅ 正常 | 显示但**灰显**，提示 `pip install flask` | 不监听 |
| 3 | 存在 | ✅ | ✅ 正常 | 可用，默认「启动」 | 不监听 |
| 4 | 存在 | ✅，已启动 | ✅ 正常 | 显示「停止」+ 地址 | 监听 |

`requirements.txt` 中 flask 列为**可选**（单独注释区块）。`PhysChem-DigitizerP.spec` 需把 `flaskserver/` 按数据文件收集（与 `传感器代码/` 同理），并对 flask 做 `hiddenimports` 兜底。

---

## 8. 线程模型（本设计最关键的部分）

### 8.1 三条铁律

1. **Qt 控件只能在 GUI 线程碰。** 本项目已因违反这条在 BLE 扫描处（`force_sensor.py:524-536`、`voltage_sensor.py:854-866`、`current_sensor.py:790-802`）留下跨线程操作控件的隐患——新功能**不允许**再犯。
2. **HTTP 线程不碰任何 Qt 对象。**
3. **数据读取不必经过 GUI 线程；控制命令必须经过 GUI 线程。**

### 8.2 只读路径：直接拉快照

六个模块**本来就维护着完整时间序列**（`time_data` / `*_data`），主程序不再缓冲一份：

```
HTTP 线程 ──DataService.snapshot()──→ api_snapshot() ──→ 模块（只读 Python 列表）
```

*权衡*：快照读取正被 GUI 线程 append 的列表。CPython 的 GIL 保证 `list(x)` 不会读到损坏数据（最多稍旧）；契约要求**先复制再按最短长度对齐**，避免两条列表长度不一致导致坐标错配。采样率 10 Hz、HTTP 轮询通常 ≤2 Hz，误差可接受，换来零每点开销、无重复状态。

**契约硬性要求：`api_snapshot()` 内不得调用任何 Qt 方法**（不要读 `QLabel.text()`，要读模块自己的 Python 列表）。

### 8.3 控制路径：命令队列 + GUI 线程执行

```
HTTP 线程（或任意线程）              GUI 线程
   │
   ├─ 生成 req_id，放入 queue.Queue
   ├─ 等待 threading.Event ────────────────┐
   │                                        │
   │                        QTimer(50ms) 触发 _drain()
   │                        取出命令 → api_command() / 通用动作表
   │                        结果写入 result_box，Event.set()
   │                                        │
   └─ 超时 8s 或拿到结果 ←──────────────────┘
```

- 队列与闸门属于 `core.DataService`（`QObject`）
- `QTimer` 在 `DataService.__init__` 时创建 —— 要求 `DataService` 在 `QApplication` 之后构造（`main.py` 自然满足）
- 超时返回 `504`（HTTP 层）/ `{ok: false}`（服务层），提示"GUI 未响应"（如主线程被模态框阻塞）
- 命令执行异常一律捕获，不让异常穿到传输层

### 8.4 服务端线程

```python
from werkzeug.serving import make_server       # 随 flask 一起安装
self._httpd = make_server(host, port, app, threaded=True)
self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
self._thread.start()
# 停止：
self._httpd.shutdown()      # 可靠关闭，端口立即释放
```

**不使用 `app.run()`** —— 它没有干净的停机手段（无法释放端口、无法在同一进程内重启）。`make_server` 提供 `shutdown()`，这是"按钮可以反复启停"的前提。

另需把 `werkzeug` 日志级别压到 `ERROR`（默认每请求打一行，会污染控制台，违反项目"控制台整洁"的取向）。

---

## 9. 模块适配契约

### 9.1 约定

传感器模块**可选**实现两个方法（不实现时接口仍可用，只读降级到已有的 `_ai_data()`）：

```python
def api_snapshot(self):
    """返回当前实验数据快照。禁止调用任何 Qt 方法。"""
    return {
        'key': 'force_sensor',              # 稳定标识（URL 里用）
        'name': '力传感器',
        'connected': bool,                  # 是否已连接设备
        'collecting': bool,                 # 是否正在采集
        'x_label': '时间 (秒)',
        'y_label': '质量 (g)',
        'unit': 'g',
        'params': {...},                    # 校准/量程等参数（JSON 可序列化）
        'points': [(t, y), ...],            # 完整序列；降采样由 DataService 负责
        'latest': {'t': ..., 'y': ..., 'raw': ...},
    }

def api_command(self, action, params):
    """执行模块特有控制动作。只能在 GUI 线程调用（由 DataService 保证）。
    通用动作（start/stop/clear）返回 None 即交给通用动作表处理。"""
    return {'ok': True, 'message': '已开始采集'}
```

**复用点**：六个模块已有的 `_ai_data()` 返回 `{title, x_label, y_label, points, params}`，与 `api_snapshot()` 高度重合。实现时 `api_snapshot()` 内部调用 `_ai_data()` 再补齐 `connected`/`collecting`/`unit`/`latest`，避免维护两套取数逻辑。

### 9.2 各模块的特有动作

| 模块 | `key` | 特有动作 | 映射到 |
|---|---|---|---|
| 超声波位移 | `ultrasonic_displacement` | — | 仅通用动作 |
| 超声波速度 | `ultrasonic_velocity` | — | 仅通用动作 |
| pH 传感器 | `ph_sensor` | — | 仅通用动作 |
| 力传感器 | `force_sensor` | `tare` / `calibrate` | `send_tare` / `start_calibration` |
| 电压传感器 | `voltage_sensor` | `tare` | `toggle_tare` |
| 电流传感器 | `current_sensor` | `zero_cal` / `cancel_zero_cal` | `toggle_zero_cal` |

`start` / `stop` / `clear` / `toggle` 四个通用动作用 §4.1 的动作表统一兜底，各模块零重复代码。

### 9.3 未接入的模块

电学综合模块尚在构思。接口对其保持中立：只要实现 `api_snapshot()` / `api_command()` 并在 `main.py` 注册，即自动出现在 API 与仪表盘里，**无需改插件**。这正是"核心在主程序"带来的好处。

---

## 10. REST API 规格

统一前缀 `/api`。响应为 JSON（`Content-Type: application/json; charset=utf-8`），CSV 端点除外。

### 10.1 读取（默认无需 token）

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/health` | 存活探测：`{ok, plugin, version, uptime_s, flask, modules_n}` |
| `GET` | `/api/modules` | 模块列表与状态摘要 |
| `GET` | `/api/modules/<key>` | 单模块快照（含 `latest` / `params` / `actions`），`?points=N` 附带序列 |
| `GET` | `/api/modules/<key>/series?limit=N` | 仅序列，默认降采样到 2000 点 |
| `GET` | `/api/modules/<key>/export.csv` | 当前数据导出（含参数注释头，与模块 `save_data` 同格式） |

### 10.2 控制（需要 token）

token 通过 `X-Auth-Token` 请求头或 `?token=` 传递。

| 方法 | 路径 | 请求体 | 说明 |
|---|---|---|---|
| `POST` | `/api/modules/<key>/collect` | `{"action":"start"\|"stop"\|"toggle"}` | 开始/停止采集 |
| `POST` | `/api/modules/<key>/command` | `{"action":"tare","params":{}}` | 模块特有动作 |
| `POST` | `/api/modules/<key>/params` | `{"params":{...}}` | 写参数（**白名单校验**） |
| `POST` | `/api/token/regenerate` | — | 重生成 token |

### 10.3 状态码

| 码 | 含义 |
|---|---|
| `200` | 成功 |
| `400` | 参数非法 / 动作不支持 |
| `401` | token 缺失或错误 |
| `404` | 模块 `key` 不存在 |
| `409` | 状态冲突（如已采集时再 `start`） |
| `503` | 插件未启动 / flask 未安装 |
| `504` | GUI 线程未在超时内响应 |

错误体统一：`{"ok": false, "error": "module_not_found", "message": "..."}`

---

## 11. 安全模型

引入控制端点意味着**外部程序能启停正在进行的实验**，因此：

| 项 | 决定 | 理由 |
|---|---|---|
| 默认监听地址 | **`127.0.0.1`** | 默认不暴露到局域网，避免同网段任意人操作实验台 |
| 局域网开放 | 需**显式**打开开关 | 打开时读操作也强制 token，并在日志与 UI 给出警告 |
| token | `secrets.token_urlsafe(24)`，首次开启自动生成 | 持久化到 `app_config.json`，重启后书签仍可用 |
| token 存放 | 主页卡片可见、可复制、可重生 | 用户是设备所有者，无需隐藏 |
| 读操作 | 回环地址下免 token | 浏览器仪表盘开箱可用 |
| 写操作 | **始终**需要 token | 防止网页里被诱导发起的跨站请求 |
| CORS | 默认**不开启** | 需要时显式打开 |

> ⚠️ 文档与 UI 都需明示：**局域网模式下任何能访问该端口的人都能控制实验**，请仅在可信网络使用。

---

## 12. 前端仪表盘

- 位置：`flaskserver/web/`，由 Flask 以 `static_folder` 托管，`/` 返回 `index.html`
- **零构建、零 CDN**：手写原生 JS + Canvas，离线实验环境可用
- 第一版内容：
  - 模块卡片列表：名称、连接/采集状态、实时值
  - 选中模块的曲线图（Canvas 绘制，滚动窗口）
  - 控制条：按 `/api/modules/<key>` 返回的 `actions` **动态生成按钮**
  - token 输入框（写操作用，存 `localStorage`）
- 轮询而非 WebSocket：`GET /api/modules/<key>/series?limit=...`，间隔 1 s（可调）
  - 理由：实现简单、无长连接状态、局域网延迟足够；后续如需高频再评估 SSE
- *预留*：`app.js` 把数据源封装成一个函数，将来换 SSE 只改这一处

---

## 13. UI 集成

### 13.1 主页入口卡片

主页在**项目信息卡下方、项目地址卡上方**插入一张紧凑卡片，作为数据接口的**唯一入口**：

```
┌──────────────────────────────────────────────────────────┐
│  ⚡ 数据接口                                   [打开…]     │
│  把实验数据开放给 AI Agent 与浏览器仪表盘                   │
│  ● 未运行                                                 │
└──────────────────────────────────────────────────────────┘
```

| 状态 | 卡片表现 |
|---|---|
| 插件不存在 | **整张卡片不显示**（`HomePageWidget` 仅在拿到插件时构建） |
| 插件在、flask 未装 | 副标题改为 `未安装 flask，pip install flask`；按钮仍可点，对话框内给出指引 |
| 未运行 | 状态点灰 +「未运行」 |
| 已运行 | 状态点绿 +「运行中 · http://127.0.0.1:8765」 |

- 卡片上的按钮**只负责打开对话框**，不在卡片上直接启停（启停、局域网、打开浏览器统一收进对话框，见 §13.2）
- 实现位置：`main.py` 的 `HomePageWidget`，新增 `set_data_plugin(plugin)` / `_refresh_data_card()`
- 主题适配：卡片用 FluentWidgets 原生组件（`CardWidget` / `PushButton` / `BodyLabel`），随主题自动变色；主页已有的 `apply_theme()` 无需改动

### 13.2 「数据接口」对话框（核心交互）

点击主页按钮弹出。基于 **`MessageBoxBase`**（与 `CalibrationMessageBox` 同一套路：WinUI3 掩码弹窗 + 自定义表单区 `viewLayout`），隐藏 `yesButton`，`cancelButton` 文案改为「关闭」。

```
┌─ 数据接口 ────────────────────────────────────────────┐
│                                                       │
│  连接地址                                             │
│    本机     http://127.0.0.1:8765         [复制]       │
│    局域网   http://192.168.1.23:8765      [复制]       │  ← 仅局域网开关打开时出现
│                                                       │
│  访问密钥   aB3d…9Kf2                     [复制][重生] │  ← 仅服务运行时出现
│                                                       │
│  ─────────────────────────────────────────────        │
│  数据接口     [SwitchButton   开 / 关]                 │
│  局域网访问   [SwitchButton   关]                      │
│                                                       │
│  ─────────────────────────────────────────────        │
│  在浏览器打开                            [打开仪表盘]  │  ← 仅数据接口开关打开时出现
│                                                       │
│                                           [   关闭   ] │
└───────────────────────────────────────────────────────┘
```

**控件行为**

| 控件 | 行为 |
|---|---|
| **数据接口** 开关 | 开 → `plugin.start(host, port, token)`；关 → `plugin.stop()`。flask 未装时置灰，并在下方追加一行 `未安装 flask：pip install flask` |
| **局域网访问** 开关 | 开 → 先弹**风险确认框**（"同一网络内的任何人都能访问并控制本机实验"），确认后写配置并**重启服务**以重新绑定网卡；关 → 同样重启回 `127.0.0.1` |
| **在浏览器打开** | `QDesktopServices.openUrl(QUrl(url))`，用系统默认浏览器打开仪表盘 |
| **复制** | 写系统剪贴板 + `InfoBar` 轻提示（复用主页 `_copy_to_clipboard` 的做法） |
| **重生** | 重新生成 token（仅运行中可用），旧 token 立即失效 |

**动态显示规则**（统一由对话框的 `_refresh()` 驱动）

| 元素 | 显示条件 |
|---|---|
| 局域网地址行 | 局域网访问开关 = 开 |
| 访问密钥行 | 服务运行中 |
| 「在浏览器打开」整行 | **数据接口开关 = 开**（即服务运行中） |

**必须注意的实现细节**

1. **切换局域网开关要重启服务。** 监听地址在绑定时就定死了，运行时改不了：`plugin.stop()` → `plugin.start(新 host, ...)`。这正是 §8.4 选用 `werkzeug.serving.make_server`（有可靠 `shutdown()`）而不是 `app.run()` 的原因——没有它，开关一关就再也绑不回端口。
2. **重启期间两个开关都要短暂禁用**，避免连点造成两个服务实例争抢同一端口。
3. **局域网 IP 用标准库取，不引入依赖**：
   ```python
   import socket

   def lan_ip():
       """本机在局域网中的出口 IP；离线/无网卡时返回空串。"""
       s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
       try:
           s.connect(('8.8.8.8', 80))   # UDP connect 不发包，只为让系统选出出口网卡
           return s.getsockname()[0]
       except OSError:
           return ''
       finally:
           s.close()
   ```
   离线时该行为空，此时**不允许**打开局域网开关（否则会给出一个打不开的地址）。
4. **对话框不阻塞采集。** 它是模态的，但服务跑在 daemon 线程、数据在模块里，弹窗期间采集与曲线照常。
5. **关闭对话框只关窗口，不停服务。** 服务状态由开关决定，与对话框生命周期解耦——反复开关弹窗不影响已启动的接口。
6. 弹窗 `exec()` 返回后用 `deleteLater()` 释放；**不要**用 `WA_DeleteOnClose`（会立即销毁 C++ 对象，之后访问控件会报 `RuntimeError: Internal C++ object already deleted`）。

**端口在哪里改**

对话框里的地址是**只读展示**；端口仍在设置页（§13.3）修改。理由是对话框定位为"日常看状态 + 开关"，端口属一次性配置，混进来会让弹窗变重。运行中改端口同样触发重启。

### 13.3 设置页

端口、监听地址、局域网开关、CORS 开关这类**不常改**的项放设置页的「数据接口」分组（沿用 `SettingCardGroup` + `SettingCard`）：

| 设置项 | 控件 | 默认 |
|---|---|---|
| 监听端口 | `SpinBox` (1024–65535) | `8765` |
| 允许局域网访问 | `SwitchButton` | 关（开启时弹风险确认框） |
| 允许跨域 (CORS) | `SwitchButton` | 关 |
| 重新生成 token | `PushButton` | — |

**这两处 UI 都在主程序里**（符合 §1.1），插件不提供任何 Qt 代码。

---

## 14. MCP 代理方案

MCP 做成**独立的 stdio 代理脚本**，而不是把 `mcp` 依赖塞进主程序：

```
Agent (DSH/OpenCode) ──stdio JSON-RPC──→ mcp_server.py ──HTTP──→ 主程序 /api
```

- 位置：`flaskserver/mcp_server.py`（与插件同目录，便于分发）
- 依赖：`mcp` 包（可选，只在这个脚本里用）
- 工具（tools）建议：
  - `list_modules()` —— 有哪些模块、是否在采集
  - `get_snapshot(module, points?)` —— 最新数据与参数
  - `get_series(module, limit?)` —— 序列（供 agent 自己做拟合/统计）
  - `control_collect(module, action)` —— 开始/停止
  - `send_command(module, action, params?)` —— 去皮/零点校准等
- 好处：主程序依赖不变；MCP 侧升级不影响主程序；REST 接口本身也可被非 MCP 脚本直接复用

---

## 15. 分阶段实施计划

每阶段结束都应是**可启动、可验证**的状态。

| 阶段 | 内容 | 验收标准 |
|---|---|---|
| **P0** | 本文档 | 结构、职责边界、契约、端点、安全模型达成一致 |
| **P1** | `core.DataService` + 插件骨架 + 加载器 | ① 删掉 `flaskserver/` 程序照常启动且主页无卡片 ② 放回后日志出现"已加载插件" ③ 插件内故意写语法错误，主程序仍正常启动 |
| **P2** | 六模块 `api_snapshot()` | 通过临时脚本调用 `DataService.snapshot()`，六个模块数据与参数均正确 |
| **P3** | 控制路径（队列 + GUI 执行） | 临时脚本调 `submit_command('current_sensor','start')`，界面真的开始采集；主线程阻塞时 8 s 超时返回而不崩 |
| **P4** | `flaskserver` HTTP 层 | 未装 flask 时按钮灰显；装上后 `/api/health`、`/api/modules`、控制端点全部按规格响应 |
| **P5** | 主页入口卡片 + 「数据接口」对话框 + 设置页分组 | 对话框四项功能齐全、动态显示规则正确；开关反复切换端口能正确释放与重绑；删掉插件目录后主页恢复原样 |
| **P6** | `web/` 仪表盘 | 浏览器看到实时曲线并能控制；断网（无 CDN）环境正常 |
| **P7** | MCP 代理 | Agent 能通过 stdio 列出模块并取到数据 |
| **P8** | 文档 | `flaskserver/README.md`、根 `README.md`、`AGENTS.md`、`requirements.txt` 全部更新 |

> **顺序说明**：P1~P3 全部在主程序内完成，**此时还没有任何 Flask 代码**——如果这三步做完发现接口设计有问题，改动成本极低。这正是"核心在主程序"的另一个好处。

---

## 16. 验证矩阵

| # | 场景 | 期望 |
|---|---|---|
| 1 | `flaskserver/` 不存在 | 程序正常启动，主页无「数据接口」卡片 |
| 2 | 插件在、flask 未装 | 程序正常启动；对话框里「数据接口」开关置灰并提示安装命令 |
| 3 | 插件在、flask 已装、未启动 | 端口未监听（`netstat` 验证）；卡片状态为「未运行」 |
| 4 | 打开「数据接口」开关 | 卡片变绿；`/api/health` 200；`/api/modules` 列出六个模块 |
| 5 | 采集数据时轮询 `/series` | 点数增长、数值合理、无异常断点 |
| 6 | `POST /collect` 无 token | 401 |
| 7 | `POST /collect` 带正确 token | 实验真的开始/停止（界面同步变化） |
| 8 | 对不存在的模块发请求 | 404 |
| 9 | 主线程弹模态框时发控制命令 | 8 s 后 504，程序不崩 |
| 10 | 「数据接口」开关反复切换 10 次 | 端口每次正确释放与重新监听，无线程泄漏 |
| 11 | 接口开启时退出程序 | 正常退出，无 `QThread` 析构崩溃（exit code 0） |
| 12 | 局域网模式打开 | 读操作也要求 token；日志有明确警告 |
| 13 | 临时给插件 `__init__.py` 塞语法错误 | 主程序照常启动，日志提示插件加载失败 |
| 14 | 打开对话框（服务未运行） | 显示本机地址与端口；密钥行、「在浏览器打开」均隐藏 |
| 15 | 打开「数据接口」开关 | 密钥行与「在浏览器打开」出现；地址可复制；点「打开仪表盘」系统浏览器能打开 |
| 16 | 运行中打开「局域网访问」 | 先弹风险确认；确认后服务重启，局域网地址行出现；手机可访问 |
| 17 | 关闭「局域网访问」 | 服务重启回 `127.0.0.1`，局域网不再可达 |
| 18 | 关掉对话框但不关开关 | 服务仍在运行、端点仍可访问（弹窗与生命周期解耦） |
| 19 | 断网环境下打开对话框 | 局域网地址为空，「局域网访问」开关不可用 |

---

## 17. 待决问题

1. **默认端口** —— 暂定 `8765`，需确认不与用户本机其他服务冲突。
2. **`params` 写接口白名单** —— 第一版建议**只开放采样间隔、单位切换**这类安全项；校准系数暂不开放，避免 Agent 误改。
3. **降采样算法** —— 暂用等间隔抽取（与 `_format_ai_data` 一致）；若曲线要求保峰值，后续换 LTTB。
4. **是否需要 SSE** —— 仪表盘第一版用轮询；若实测延迟不可接受再评估。
5. **端口是否也放进对话框** —— 当前设计把端口留在设置页，对话框里只读展示。若觉得"看得见改不了"别扭，可把 `SpinBox` 一并放进对话框。
6. **是否记住上次的启停状态** —— 当前默认每次启动程序都是「关」。若希望"上次开着这次自动开"，需新增持久化项，并考虑开机即占端口的副作用。
7. **多网卡时显示哪个局域网地址** —— `lan_ip()` 取的是默认出口网卡。若机器同时接有线 / 无线 / 虚拟网卡，可能要列出多个候选让用户选。

---

## 18. 变更记录

| 日期 | 变更 |
|---|---|
| 初稿 | 建立设计：目录结构、加载机制、线程模型、模块契约、端点规格、安全模型、实施计划 |
| 修订 1 | **架构反转**：核心能力（数据总线 / 命令队列 / 模块适配 / 配置 / UI）全部归主程序，插件缩为纯 HTTP 传输层（`plugin.py`、`bridge.py` 移入主程序）；新增 §1.1 职责划分、§4 `core.DataService`、§13 UI 集成；调整阶段计划与验证矩阵 |
| 修订 2 | §13 重写：主页按钮改为**打开「数据接口」对话框**（不再在卡片上内联启停）；对话框含本机/局域网地址、访问密钥、**数据接口开关**、**局域网访问开关**，以及**开关打开后才出现**的「在浏览器打开」；补充"切局域网需重启服务""局域网 IP 用标准库获取""离线时禁用局域网开关""关弹窗不停服务"等实现约束 |