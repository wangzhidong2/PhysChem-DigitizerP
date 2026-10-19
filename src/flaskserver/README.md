# flaskserver 插件 — 实验数据 HTTP 接口

把运行中的上位机数据开放给 **AI Agent**（REST / MCP）与**浏览器仪表盘**。
设计文档见 `../../docs/flask-server-design.md`。

## 安装

```bash
pip install flask        # 可选依赖；未装时主程序照常运行，入口按钮灰显
```

MCP 代理另需（仅 AI Agent 场景）：

```bash
pip install mcp
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
点「应用」立即生效并自动连接——由 `DataService` 把命令投递到 GUI 线程，
复用与主程序完全相同的连接控件与重连逻辑，插件本身不含连接业务。

## REST API

统一前缀 `/api`；写操作需要 token（`X-Auth-Token` 头或 `?token=`）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 存活探测（含 `auth_enabled` 鉴权状态） |
| GET | `/api/auth/check` | 登录探测：按写级别校验、无副作用，正确返回 200，错误 401 |
| GET | `/api/modules` | 模块列表与状态摘要 |
| GET | `/api/modules/<key>` | 单模块快照，`?points=N` 附带序列；含 `connection` 连接信息 |
| GET | `/api/modules/<key>/series?limit=N` | 降采样序列（默认 2000 点） |
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

```bash
PCD_API_BASE=http://127.0.0.1:8765 PCD_TOKEN=<密钥> \
  python src/flaskserver/mcp_server.py
```

提供工具：`list_modules` / `get_snapshot` / `get_series` /
`control_collect` / `send_command`。

## 可插拔保证

整个 `src/flaskserver/` 目录删掉后主程序行为完全不变（主页卡片消失、无 HTTP 端口）。
本插件只做协议翻译：无业务逻辑、不持有数据、不认识具体传感器。
