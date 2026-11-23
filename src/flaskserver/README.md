# flaskserver 插件 — 实验数据 HTTP 接口

把运行中的上位机数据开放给 **AI Agent**（REST / MCP）与**浏览器仪表盘**。
设计文档见 `../../docs/flask-server-design.md`。

## 安装

```bash
pip install flask        # 可选依赖；未装时主程序照常运行，入口按钮灰显
```

MCP 代理另需（仅 AI Agent 场景）：

```bash
pip install -U "mcp>=2.3"
```

## 使用

1. 主页 →「数据接口」卡片 →「打开…」
2. 打开「数据接口」开关（默认监听 `http://127.0.0.1:8765`）
3. 浏览器访问该地址即为实时仪表盘；首次开启自动生成访问密钥

「局域网访问」开关会把监听地址改为 `0.0.0.0`（手机/其他电脑可访问），
⚠️ **同一网络内的任何人都能查看并控制实验，请仅在可信网络开启。**
端口、CORS、密钥重生在设置页「数据接口」分组。

### 仪表盘登录（路由器式）

开启鉴权后，浏览器直接打开仪表盘地址会先显示**登录页**：输入正确密钥才进入桌面，
登录成功后地址栏自动带上 `?token=`（刷新或把链接发给可信同事可直接进入）。
从上位机内点「打开仪表盘」会自动带上密钥，无需再输一次。

### 连接管理（串口 / 模拟器）

仪表盘每个模块窗口内可选择连接方式（模拟器 / 串口）与串口设备，
点「应用」立即生效并自动连接——HTTP 层直接调用 `KernelRegistry` 里的内核，
与桌面端共用同一个内核实例与同一套连接逻辑，插件本身不含连接业务。

> 切换连接方式会**先断开旧传输再按新模式重连**：否则会出现「界面显示模拟器、
> 通道仍在读串口」的错位，串口占用表也不会释放（别的客户端会一直看到 `port_in_use`）。

## 实时同步

桌面 GUI、浏览器仪表盘、CLI/MCP 改的是**同一份内核状态**，通过
`GET /api/events`（SSE，`text/event-stream`）实时广播：

- 桌面改名/改色/换模式/改采样间隔/校准/显隐 → 网页立即刷新；
- 网页新增/删除通道、连接/断开、改参数 → 桌面立即刷新（≈10–20 ms）；
- 事件 `{seq, key, kind, channel_id, data, ts}` 带单调序号，断线用
  `Last-Event-ID` 续传；落后超过 512 条时收到 `event: reset`，前端整页重拉；
- 采样事件合并为 `data` 通知（每路最多 2 次/秒），网页在 SSE 正常时
  自动跳过 1 s 轮询，掉线后回落到轮询兜底。

```bash
curl -N "http://127.0.0.1:8765/api/events?since=0"
```

## REST API

统一前缀 `/api`；写操作需要 token（`X-Auth-Token` 头或 `?token=`）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 存活探测：`auth_enabled`、`lan_access`、`serial_owners`（谁占着哪个串口） |
| GET | `/api/auth/check` | 登录探测：按写级别校验、无副作用，正确返回 200，错误 401 |
| GET | `/api/events?since=N` | 实时事件流（SSE），断线可用 `Last-Event-ID` 续传 |
| GET | `/api/modules` | 模块列表与状态摘要 |
| GET | `/api/modules/<key>` | 单模块快照，`?points=N` 附带序列；含 `connection` 连接信息 |
| GET | `/api/modules/<key>/series?limit=N` | 降采样序列（默认 2000 点）；`channels` 字段含每路曲线 |
| GET | `/api/modules/<key>/channels` | 通道列表（模式 / 端口 / 采样间隔 / 连接状态） |
| POST | `/api/modules/<key>/channels` | 新增通道，如 `{"name":"通道2","mode":"模拟器","sample_interval_ms":100,"connect":true}` |
| PATCH | `/api/modules/<key>/channels/<cid>` | 修改单路参数，如 `{"sample_interval_ms":200}` 或 `{"mode":"串口","port":"COM3","connect":true}` |
| DELETE | `/api/modules/<key>/channels/<cid>` | 删除通道 |
| POST | `/api/modules/<key>/channels/<cid>/connect` | 连接指定通道 |
| POST | `/api/modules/<key>/channels/<cid>/disconnect` | 断开指定通道 |
| GET | `/api/modules/<key>/export.csv` | CSV 导出（含参数注释头） |
| POST | `/api/modules/<key>/collect` | `{"action":"start"\|"stop"\|"toggle"}` |
| POST | `/api/modules/<key>/command` | `{"action":"tare",...}`；连接管理：`{"action":"set_connection","params":{"mode":"模拟器"\|"串口","port":"COM3","connect":true}}`、`{"action":"refresh_ports"}` |
| POST | `/api/modules/<key>/params` | 写参数（白名单：采样间隔/单位） |
| POST | `/api/token/regenerate` | 重生密钥 |

模块 `key`：`ultrasonic_displacement` / `ultrasonic_velocity` / `ph_sensor` /
`force_sensor` / `voltage_sensor` / `current_sensor`。

### curl 示例

```bash
curl http://127.0.0.1:8765/api/modules
curl -X POST http://127.0.0.1:8765/api/modules/force_sensor/collect \
     -H "X-Auth-Token: <密钥>" -H "Content-Type: application/json" \
     -d '{"action":"start"}'
curl "http://127.0.0.1:8765/api/modules/force_sensor/series?limit=100"
```

## MCP（AI Agent 接入）

协议：**MCP 2026-07-28**。请求无状态（每个请求自带 `_meta`），服务端实现
`server/discover`、`resultType`、`structuredContent`、`outputSchema` 与工具
`annotations`；同时保留旧客户端的 `initialize` 握手回退。

```bash
pip install -U "mcp>=2.3"
```

> `mcp 1.x` 的 `FastMCP` 已废弃且没有 `server/discover`，装 1.x 会直接退出并提示升级。

### 三步接入（复制即可用）

1. **装依赖**：`pip install -U "mcp>=2.3"`（直连串口再加 `pip install pyserial`）。
2. **桌面端**：主页 →「数据接口」→ 打开开关 → 复制密钥。
3. **写配置**（Claude Desktop / Cursor 通用；Claude Code 用下一节的 `claude mcp add`）：

```json
{
  "mcpServers": {
    "physchem": {
      "command": "python",
      "args": ["/path/to/src/flaskserver/mcp_server.py"],
      "env": {
        "PCD_BACKEND": "http",
        "PCD_API_BASE": "http://127.0.0.1:8765",
        "PCD_TOKEN": "设置页里的密钥"
      }
    }
  }
}
```

重启客户端后问它「列一下有哪些传感器模块」，回 6 个即接通。报错对照：
`upstream_unreachable`（数据接口没开）、`unauthorized`（密钥错）、
`port_in_use`（串口被桌面端占着，属正常，改用 `http`）。

Windows 的路径写法、各客户端配置文件位置、以及更多错误处理见根
[README 的 6.11 节](../../README.md#611在-ai-agent-里接入-mcp三步)。

### 两种数据后端

| `PCD_BACKEND` | 链路 | 适用场景 |
|---|---|---|
| `http`（默认） | Agent → MCP → HTTP → 运行中的上位机内核 | 桌面端开着，Agent 与桌面/网页共享同一份状态 |
| `local` | Agent → MCP → 进程内 `KernelRegistry` | 无 GUI / 服务器 / CI；不需要 PySide6，也不需要 Flask |

`local` 只加载各模块的 `_kernel*.py` 与文件头 `MODULE META`，**不 import View 文件**，
因此在没有 PySide6 的机器上也能跑。它会独占串口，不要与桌面端同时连接同一台设备。

#### 串口是独占资源：桌面端占着时，MCP 走 HTTP 而不是再开一次串口

一个串口同一时间只应有一个"拥有者"。桌面端连着 `COM3` 时：

- MCP 用 `local` 后端再去 `connect_device(mode="串口", port="COM3")`：
  Windows 会直接拒绝，Linux/macOS 允许重复 `open`，但**两个进程会瓜分字节流**，
  桌面端的曲线会缺数据甚至掉线。占用表 `claim_serial_port` 只在**同一进程内**生效，
  拦不住跨进程抢口。
- MCP 用 `http` 后端：串口只由桌面端持有，MCP 通过 HTTP 调同一个 `KernelRegistry`。
  桌面端采到的点、MCP 读到的值、网页仪表盘画的曲线是**同一份数据**。

所以默认配置就是 `PCD_BACKEND=http`。`local` 只用于「没有桌面端在跑」的场景（服务器、CI、无头采集）。

MCP 在连接前会读一次占用表：`get_status().connection` 带 `owners` 与 `port_holder`，
`local` 后端还会顺带探一次桌面端的 `/api/health`。若目标端口已被桌面端持有，
直接返回 `port_in_use` 并指出持有者，**不会**硬开第二次串口把桌面端顶掉。

#### 局域网：把 MCP 指到桌面端的 IP

桌面端打开「局域网访问」后监听 `0.0.0.0:8765`，另一台机器上的 Agent 直接改地址即可：

```bash
PCD_BACKEND=http PCD_API_BASE=http://192.168.1.20:8765 PCD_TOKEN=<密钥> \
  python src/flaskserver/mcp_server.py
```

注意局域网模式下**读操作也强制 token**（`allow_lan`），不带密钥连 `list_modules` 都会返回
`unauthorized`。串口仍然只由桌面端那台机器持有，MCP 只是远程操作它。

#### `connect_device` 的连接语义

- `mode="串口"` 且不传 `port`：沿用该通道已保存的端口，返回 `reused_port=true` 并在
  `message` 里说明用的是哪个口，避免"以为是默认口、其实连了上次失败的口"；
- 串口打不开（不存在 / 被占用 / 无权限）：等待后台打开结果后返回
  `connect_failed` + `isError=true`，**把端口回滚到连接前的值**，并把 `state` 一并回传；
- 该模块没有可用端口时返回 `missing_parameter`，`data.ports` 给出候选列表。

### 启动与客户端配置

```bash
# 连桌面端（默认）
PCD_API_BASE=http://127.0.0.1:8765 PCD_TOKEN=<密钥> \
  python src/flaskserver/mcp_server.py

# 无头：MCP 进程自己驱动内核
PCD_BACKEND=local python src/flaskserver/mcp_server.py

# 可选：Streamable HTTP，供多个 Agent 共享
PCD_MCP_TRANSPORT=streamable-http PCD_MCP_PORT=8766 python src/flaskserver/mcp_server.py
```

通用 `mcpServers` 配置（Claude Desktop / Cursor / OpenCode 等）：

```json
{
  "mcpServers": {
    "physchem": {
      "command": "python",
      "args": ["/path/to/src/flaskserver/mcp_server.py"],
      "env": {
        "PCD_BACKEND": "http",
        "PCD_API_BASE": "http://127.0.0.1:8765",
        "PCD_TOKEN": "<设置页里的密钥>"
      }
    }
  }
}
```

三种场景只改 `env`：

| 场景 | `PCD_BACKEND` | `PCD_API_BASE` | `PCD_TOKEN` |
|---|---|---|---|
| 桌面端开着（推荐） | `http` | `http://127.0.0.1:8765` | 设置页密钥 |
| 另一台电脑 / 手机热点 | `http` | `http://<桌面端IP>:8765` | 设置页密钥（局域网模式读也要） |
| 没有桌面端（服务器/CI） | `local` | 不填 | 不填 |

Windows 示例（路径用双反斜杠，`python` 建议写绝对路径，避开 Microsoft Store 的假 python）：

```json
{
  "mcpServers": {
    "physchem": {
      "command": "C:\\Users\\me\\AppData\\Local\\Programs\\Python\\Python312\\python.exe",
      "args": ["D:\\PhysChem-DigitizerP\\src\\flaskserver\\mcp_server.py"],
      "env": {
        "PCD_BACKEND": "http",
        "PCD_API_BASE": "http://127.0.0.1:8765",
        "PCD_TOKEN": "a1b2c3d4e5f6"
      }
    }
  }
}
```

配置文件位置：Claude Desktop 为 `%APPDATA%\Claude\claude_desktop_config.json`
（macOS：`~/Library/Application Support/Claude/claude_desktop_config.json`）；
Cursor 为 `~/.cursor/mcp.json`；Claude Code 用 `claude mcp add`（见下）。

```bash
claude mcp add physchem \
  -e PCD_BACKEND=http -e PCD_API_BASE=http://127.0.0.1:8765 -e PCD_TOKEN=<密钥> \
  -- python /path/to/src/flaskserver/mcp_server.py
```

> MCP 代理是独立的 Python 进程，必须用**装了 `mcp>=2.3` 的 Python** 启动，
> 不能用打包好的桌面端 exe 代替。桌面端不开「数据接口」时，`http` 后端会返回
> `upstream_unreachable`，Agent 能据此提示用户先打开开关。

### 工具

| 工具 | 读写 | 用途 |
|---|---|---|
| `list_modules` | 读 | 所有模块的 key、连接、采集、点数 |
| `get_status` | 读 | 单模块完整状态 + 通道 + **带参数说明的 actions** |
| `get_reading` | 读 | 最新值、单位、最近窗口 σ/波动率 |
| `summarize` | 读 | 均值/σ/极值/漂移/数据质量提示 |
| `get_series` | 读 | 原始点（默认 200，避免塞满上下文） |
| `wait_for_data` | 读 | 阻塞等待点数达标或读数稳定；数据不再增长会提前返回 `stalled` |
| `control_collect` | 写 | start / stop / toggle，回传 before/after |
| `set_parameter` | 写 | 采样间隔、单位；**回读确认是否生效** |
| `connect_device` | 写 | 串口 / 模拟器连接 |
| `calibrate` | 写（破坏性） | 写校准点并回读 |
| `send_command` | 写（破坏性） | 兜底：去皮、清零、加删通道等 |
| `export_csv` | 写 | 导出到固定目录，返回路径与数据行数；无数据返回 `no_data` |
| `make_report` | 写 | 生成 Markdown + 自包含 HTML 报告 |

另提供资源 `pcd://modules/{key}/status`、`pcd://modules/{key}/csv`，
以及提示词 `run_experiment`、`analyze_measurement`。

### 返回结构（状态回传）

每个工具都返回同一结构，成功与失败都可判断：

```json
{
  "ok": true,
  "action": "control_collect",
  "module": "ph_sensor",
  "message": "已开始采集，当前 0 点",
  "error": null,
  "hint": "",
  "state": {"collecting": true, "connected": true, "points_n": 0, "channels": []},
  "data": {"before": {"collecting": false}, "after": {"collecting": true},
           "effective": true},
  "backend": "local",
  "ts": 1763700000.0
}
```

失败时 `ok=false` 且 MCP 层 `isError=true`，`error` 是稳定的机器码：

| 错误码 | 含义 | 下一步 |
|---|---|---|
| `module_not_found` | 模块 key 不存在 | 先 `list_modules` |
| `channel_not_found` | 通道 id 不存在 | 看 `get_status().state.channels[].id` |
| `not_connected` | 没有通道连接，采集不会产生数据 | 先 `connect_device` |
| `unsupported_action` | 该模块没有这个动作 | 看 `get_status().actions` |
| `missing_parameter` | 缺必填参数（如串口名） | 按 `data.ports` 里的候选补全 |
| `port_in_use` | 串口被桌面端/别的进程占着 | 改用 `PCD_BACKEND=http` 共享，不要直连 |
| `connect_failed` | 端口打不开（不存在/无权限） | 换端口或改用模拟器 |
| `no_data` | 还没有数据可导出 | 先 `connect_device` + `control_collect(start)` |
| `unauthorized` | 缺少/错误访问密钥 | 设置 `PCD_TOKEN` |
| `upstream_unreachable` | 连不上上位机 | 开「数据接口」或改用 `local` |
| `bad_response` | 端口上不是本程序的接口 | 核对 `PCD_API_BASE` 端口 |

`hint` 字段直接给出纠正建议；`state` 即使失败也会带上现场状态。

`wait_for_data` 的结果里还有两个字段，避免 Agent 误判：

| 字段 | 含义 |
|---|---|
| `reason` | `reached`（条件满足）/ `timeout`（等满 `timeout_s`）/ `stalled`（点数约 5 s 不再增长） |
| `stalled` | `true` 表示采集线程可能已中断（拔线、断电），不是"读数稳定" |

### 报告输出

`PCD_REPORT_DIR`（默认 `~/PhysChemReports`）：

- `*.md` — Markdown 报告
- `*.html` — 自包含 HTML（内联 CSS + SVG 曲线，可离线打开/打印）
- `data/<模块>_<时间戳>_<毫秒>.csv` — 原始数据附件

报告章节按「有内容才出」编号：只填结论时不会出现「三、结论」这种跳号。
CSV 的注释头行数随通道数变化，返回的 `rows` 统计的是**数据行**（不含注释与表头）。

### 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `PCD_BACKEND` | `http` | `http` 或 `local` |
| `PCD_API_BASE` | `http://127.0.0.1:8765` | http 后端的上位机地址 |
| `PCD_TOKEN` | 空 | 上位机开启鉴权时必填 |
| `PCD_SENSORS_DIR` | `../sensors` | local 后端的模块目录 |
| `PCD_REPORT_DIR` | `~/PhysChemReports` | 报告与 CSV 输出目录 |
| `PCD_MCP_TRANSPORT` | `stdio` | `stdio` 或 `streamable-http` |
| `PCD_MCP_HOST` / `PCD_MCP_PORT` | `127.0.0.1` / `8766` | HTTP 传输监听地址 |
| `PCD_LOG` | 空 | 设为 `1` 打开内核日志（仍写 stderr） |

### 安全

- http 后端的写操作全部要求 `X-Auth-Token`；
- `export_csv` / `make_report` 只写 `PCD_REPORT_DIR`，**不接受调用方指定路径**；
- `calibrate` / `send_command` 标注 `destructiveHint`，客户端可据此要求人工确认；
- `local` 模式绕过鉴权，因为它直接操作本机内核——只在自己可控的环境里使用。

## 可插拔保证

整个 `./src/flaskserver/` 目录删掉后主程序行为完全不变（主页卡片消失、无 HTTP 端口）。
本插件只做协议翻译：无业务逻辑、不持有数据、不认识具体传感器。
