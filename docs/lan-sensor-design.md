# 局域网传感器接入 — 开发文档

> 状态：**设计稿**（尚未实现）
> 目标读者：本项目的开发者（含 AI Agent）
> 相关：`AGENTS.md`（项目总规约）、`docs/flask-server-design.md`（数据接口插件，方向相反的另一半）
> 复用基础：PDsmartUPS 项目的配网 + HTTP 上报模式（`gitcode.com/wangzhidong2/PDsmartUPS`）

---

## 1. 目标与原则

给「传感器固件 → Python 上位机」这一段增加**局域网无线连接方式**：ESP32 与电脑在同一局域网内，固件主动把采样数据批量上报给上位机，替代 USB 串口线。

```
现状：  固件 ──USB 串口线──▶ SerialThread ──▶ data_received("t,v") ──▶ 模块解析
新增：  固件 ──WiFi / HTTP──▶ LANSensorThread ──▶ data_received("t,v") ──▶ 模块解析（零改动）
```

三个目标：

1. **免线**：实验台上不再被 USB 线束缚（力学实验的运动台、化学实验的搅拌台尤其受益）。
2. **免烧录配置**：WiFi 与服务器地址都在**配网页**里改、存 EEPROM，换路由器 / 换电脑不用重烧固件。
3. **模块零改动**：对上位机六个传感器模块而言，局域网只是第四种连接方式，数据解析、校准、保存逻辑一行不改。

### 1.1 首要原则：连接能力在 core，不依赖 flaskserver

`flaskserver/` 是**可选插件**（可整体删除、默认开关关闭），而传感器连接是核心功能——**数据接收端不得依赖 flask**。因此接收端用 Python 标准库 `http.server.ThreadingHTTPServer` 内嵌在 `core.LANSensorThread` 里，零新依赖，pyserial 之外什么都不用装。

对固件而言毫无区别：它只是一个普通的 HTTP POST 客户端，不关心对面是 Flask 还是 stdlib。

### 1.2 三条硬约束

| 约束 | 含义 |
|---|---|
| **与串口同构** | `LANSensorThread` 对外接口与 `SerialThread` 完全一致（`data_received` 信号 + `START` / `t,v` / `ERROR:` 文本协议），模块解析代码零改动 |
| **依赖可选的只是 WiFi** | 未连接 WiFi 时固件退回串口输出（`feed()` 同步 `Serial.print`），有线调试能力保留 |
| **配置全部在设备端** | WiFi 凭据、服务器地址、端口都存设备 EEPROM，由配网页管理；上位机不做任何设备配置 UI |

---

## 2. 非目标（本期不做）

- ❌ 不做 HTTPS / token 鉴权（与现有局域网仪表盘同一信任模型，见 §10）
- ❌ 不做 ESP8266 WiFi 固件（ESP8266 内存紧张，且其用户可继续用串口版；架构上不排除）
- ❌ 不做固件 OTA 升级
- ❌ 不做多传感器单端口路由（每模块独立端口，与现有"每模块独立连接"的模型一致）
- ❌ 不做采样率协商（固件定速输出，上位机沿用现有采样频率过滤）
- ❌ 不替换串口连接（四种连接方式并存：模拟器 / 串口 / BLE / 局域网）

---

## 3. 总体架构

```
                ┌─────────── ESP32 固件（每传感器一份 WiFi 变体）───────────┐
                │                                                          │
   采样 loop ──▶ net.feed(t, v) ──▶ 环形缓冲(≤200条) ──▶ 每500ms 批量 POST   │
                │       │                              {"device","seq",     │
                │       └─ Serial.print（保留有线调试）   "reset","samples"}  │
                │                                                          │
   AP 热点常开 ◀─ WIFI_AP_STA ──▶ STA 连路由器（EEPROM 凭据，断线自动重连）    │
   192.168.4.1      配网 Web 页（改 WiFi / 改服务器地址 / 自动发现 / 重启）    │
                └───────────────┬──────────────────────────┬───────────────┘
                                │ HTTP POST (2 req/s)       │ UDP 广播 (仅发现时)
                                ▼                           ▼
        ┌─── Python 上位机 ──────────────────────────────────────────────┐
        │  LANSensorThread (core.py, 每模块一个 :8800-8805)               │
        │    ThreadingHTTPServer ◀─ POST /api/data                       │
        │    解析 JSON → emit("START"/"t,v") ──▶ 模块 data_received（同串口）│
        │    响应体捎带下行命令 {"cmds":["TARE"]}                          │
        │                                                                │
        │  LanDiscoveryService (core.py, UDP :8899 全局一个)              │
        │    应答设备的发现广播 → 回 {host, port}                          │
        └────────────────────────────────────────────────────────────────┘
```

要点：

- **上行**：500ms 批量（10Hz 时 5 条/请求、2 请求/秒），兼顾实时性与连接开销。
- **下行**：不单独开端口。上位机把待发命令排队，**随下一次 POST 的响应体**捎带回固件（≤500ms 延迟，零额外请求）。
- **发现**：UDP 广播只用于「设备找不到服务器」时的自动发现；日常上报纯 HTTP。

---

## 4. 用户体验流程

### 4.1 首次配网（一次）

1. 上电 → 固件起 AP 热点（**无论 STA 是否连接，热点常开**，SSID 形如 `PhysChem-force_sensor`，密码 `12345678`）。
2. 手机连热点 → 浏览器打开 `192.168.4.1` → 配网页：
   - 扫描并选择家里 / 实验室的路由器，输入密码；
   - 填服务器地址（见 §4.2 的免填方案）；
   - 保存 → 写 EEPROM → 自动连接 STA。
3. 热点**保持开启**：之后随时可以再连进来改配置。

### 4.2 服务器地址：自动发现优先，手动兜底

- **上位机侧**：在软件里把模块连接方式切到「局域网」→ 模块内起接收服务，状态栏显示 `等待设备连接（192.168.x.x:8802）`。
- **设备侧（免填）**：EEPROM 里没有服务器地址时，固件上电自动 UDP 广播 3 次（每 2 秒一次）；上位机 `LanDiscoveryService` 应答本机 IP 与该模块端口 → 固件拿到地址直接开始上报（**只存内存，不写 EEPROM**，配网页显示"自动发现的地址"，用户点保存才固化）。
- **手动**：配网页「服务器设置」里任何时候都可以手填 IP + 端口（支持域名），保存即生效。换电脑、IP 变了、想固定下来，都走这里。

### 4.3 日常使用

1. 设备上电 → 自动连 WiFi（上次的服务器地址在 EEPROM）→ 自动开始上报。
2. 上位机模块选「局域网」→ 点「连接」→ 接收服务监听 → 设备 POST 到达 → `START` → 实时曲线。
3. 实验中途想改配置？手机连热点（或同局域网访问设备的 STA IP）进配网页，改完保存，立即生效。

### 4.4 修改服务器地址（换电脑 / 换端口）

手机连设备热点 → 配网页改「服务器地址」→ 保存 → 固件下一批数据发往新地址。**无需重烧固件、无需重启设备。**

---

## 5. 固件侧设计

### 5.1 `PhysChemNet` 共享库

单个头文件库（`sensors/PhysChemNet/PhysChemNet.h`，使用者复制进 Arduino `libraries/` 目录），约 300 行，内含 AP+STA 双模、配网 Web、EEPROM、批量上报、下行命令、UDP 发现。各传感器固件只写传感器逻辑 + 几行调用：

```cpp
#include <PhysChemNet.h>

PhysChemNet net("force_sensor");   // 设备 ID（= 上位机模块的 device key）

void onCommand(String cmd) {       // 下行命令回调（响应体捎带到达）
  if (cmd == "TARE") { tare(10); net.reply("TARE_DONE," + String(offset)); }
}

void setup() {
  Serial.begin(115200);
  net.begin();                     // 读 EEPROM → 起 AP（常开）→ 连 STA
  net.onCommand(onCommand);
  // ... 原 setup 逻辑（引脚、初始去皮等）不动
}

void loop() {
  net.loop();                      // 处理配网页请求 / 500ms 批量 POST / 重连
  // ... 原采样逻辑不动，把输出改为：
  net.feed(currentTime, rawValue); // 入缓冲 + 同步 Serial.print（保留有线调试）
}
```

库内部三个来源（均出自 PDsmartUPS，已验证）：

| 模块 | PDsmartUPS 对应 | 调整 |
|---|---|---|
| AP 配网 + EEPROM | `scanWiFiList` / `saveWiFiToEEPROM` / `readWiFiFromEEPROM` | EEPROM 布局扩展（§5.3）；页面加服务器地址与发现区块 |
| HTTP 上报 | `sendLogs()`（手搓 `WiFiClient`） | 改用 `HTTPClient` 库（省一半代码）；改批量数据格式 |
| 断线重连 | loop 末尾的重连块 | 保持；AP 常开期间重连不影响热点入口 |

### 5.2 AP+STA 双模常开（本设计的核心差异点）

PDsmartUPS 只在 **STA 未连接**时起 AP；本项目要求 **STA 连接成功后热点仍然保持开启**：

```cpp
void setup() {
  WiFi.mode(WIFI_AP_STA);                 // 双模
  WiFi.softAP(AP_SSID, AP_PASS);          // 无条件起热点（先起，保证入口永远在）
  readConfigFromEEPROM();                 // WiFi + 服务器地址
  if (有WiFi凭据) connectSTA();            // 异步连接，失败不阻塞 AP
}
```

理由与代价：

| 项 | 说明 |
|---|---|
| 为什么常开 | 实验中途随时可能要改服务器地址 / 换路由器；如果像 PDsmartUPS 那样连上就关热点，改配置必须先断 WiFi 或重烧 |
| 配网页双入口 | 热点 `192.168.4.1` 永远可达；STA 连接后同一路由器内也可用 `设备STA_IP` 访问（`WebServer` 在双模下两个接口都响应） |
| 信道跟随 | ESP32 单射频：STA 连接 / 重连路由器时，AP 信道会跟随 STA，**热点上的手机可能短暂掉线重连**（几秒）。教学场景可接受，列入已知限制（§11） |
| 吞吐影响 | AP 常开会略降 STA 吞吐；本项目 2 req/s 的上报量完全无感 |
| 热点命名 | `PhysChem-<device_id>`（如 `PhysChem-force_sensor`），多传感器同场时手机可分辨 |

### 5.3 EEPROM 布局（512 字节）

沿用 PDsmartUPS 的定长字段风格，扩展服务器配置：

| 偏移 | 长度 | 内容 |
|---|---|---|
| 0–199 | 200 | WiFi SSID |
| 200 | 1 | SSID 长度 |
| 201–399 | 199 | WiFi 密码 |
| 400 | 1 | 密码长度 |
| 401–445 | 45 | 服务器地址（IP 或域名，文本） |
| 446 | 1 | 服务器地址长度 |
| 447–451 | 5 | 服务器端口（文本，如 `"8802"`） |
| 452 | 1 | 端口长度 |
| 453 | 1 | 配置有效标志 `0xA5`（区分"从未配置"与"配置为空"；全 `0xFF` 视为未配置） |
| 454–511 | 58 | 预留（未来：上报周期、设备别名等） |

存文本而非二进制：与 PDsmartUPS 一致、便于配网页直接回显、避免字节序问题。

### 5.4 配网 Web 页（单页，中文，PDsmartUPS 风格）

| 路由 | 方法 | 功能 |
|---|---|---|
| `/` | GET | 单页应用：状态区 + WLAN 设置 + 服务器设置（三个折叠卡片） |
| `/api/status` | GET | `{device, sta:{connected, ssid, ip}, ap:{ip}, server:{host, port, source: saved/auto/manual, last_post_ms_ago, last_post_ok}}` |
| `/api/scan` | GET | WiFi 扫描列表（SSID + 信号强度） |
| `/api/wifi` | POST | `{ssid, pwd}` → 存 EEPROM → 连接 STA（热点保持） |
| `/api/server` | POST | `{host, port}` → 校验（端口 1–65535）→ 存 EEPROM → **立即生效**（下一批发新地址） |
| `/api/discover` | POST | 触发一次 UDP 广播，等 2 秒，返回发现的地址或 `not_found`（用于「自动发现」按钮填充表单） |
| `/api/reboot` | POST | 重启设备（配网后让自动发现的新配置走一遍完整上电流程用） |

页面状态区常显：设备 ID、当前 WiFi 与 IP、服务器地址（及来源）、最近一次上报结果与时间——**排障时不用猜设备到底连没连上、发没发出去**。

### 5.5 上报与命令状态机（固件侧）

```
feed(t, v) ──▶ 环形缓冲(容量200) ──┐  缓冲满 → 丢最旧 + 置 pending_reset
                                    │
loop() 每 500ms:                    ▼
  服务器地址已配置? ──否──▶ 跳过（仅 Serial 输出）
  │是
  POST /api/data  {"device","seq":++n,"reset":pending_reset,
                   "samples":[[t,v],...],          ← 力传感器同款；VI 固件为 [t,v,i] 三元组
                   "replies":["TARE_DONE,offset"]} ← 上一轮命令的回执（有待发时）
  ├─ 200 {"ok":true,"cmds":["TARE"]} → 清缓冲；逐条执行 onCommand(cmd)
  ├─ 失败/超时(1.5s) → 缓冲保留，与下批合并重试；连续失败只记状态不清数据
  └─ 设备重启后首批 → reset=true（上位机据此重发 START）
```

- **`seq` 批次号**：上位机可检测跳号（丢批告警用，第一版仅记录不处理）。
- **POST 阻塞的影响**：正常局域网内一次 POST < 100ms；服务器不可达时最多阻塞 1.5s——期间 `loop()` 停转、采样暂停。缓冲保证数据不丢（200 条 ≈ 10Hz 下 20 秒容量），恢复后续传。取舍见 §11。
- **命令回执 `replies`**：`net.reply(text)` 把文本放进下一批请求体，上位机收到后按行 `emit`（如 `TARE_DONE,offset`），复用现有串口回执的解析路径。

### 5.6 WiFi 固件清单（6 个，目录名 = 文件名，避开 Arduino 的坑）

| 固件 | 基于的串口版 | 设备 ID | 端口 | 备注 |
|---|---|---|---|---|
| `sensors/ultrasonic/HC-SR04esp32_wifi/HC-SR04esp32_wifi.ino` | `HC-SR04esp32/HC-SR04esp32.ino` | `ultrasonic` | 8800 | 位移 + 速度两个模块共用；时间戳保持**微秒** |
| `sensors/ph/ph_esp32_wifi/ph_esp32_wifi.ino` | `ph_esp32/ph_esp32.ino` | `ph_sensor` | 8801 | |
| `sensors/force/force_wifi/force_wifi.ino` | `force/force.ino` | `force_sensor` | 8802 | **含 TARE/CALIBRATE 下行命令**（样板固件） |
| `sensors/voltage/ESP32_Voltage_WiFi/ESP32_Voltage_WiFi.ino` | `ESP32_Voltage_Sensor/ESP32_Voltage_Sensor.ino` | `voltage_sensor` | 8803 | 仅 ESP32 内置 ADC 版；ADS1115/HX711 变体后续按需 |
| `sensors/current/ESP32_ADC_Raw_WiFi/ESP32_ADC_Raw_WiFi.ino` | `ESP32_ADC_Raw_Data/ESP32_ADC_Raw_Data.ino` | `current_sensor` | 8804 | |
| `sensors/electronics/VI_ESP32_ADC_WiFi/VI_ESP32_ADC_WiFi.ino` | `VI_ESP32_ADC/VI_ESP32_ADC.ino` | `vi_esp32_adc` | 8805 | samples 为 `[t, v_adc, i_adc]` 三元组 |

> 超声波位移 / 速度是两个上位机模块、一份固件：二者共用端口 8800 与设备 ID `ultrasonic`，**同一时间只允许一个超声波模块处于「局域网已连接」状态**（与串口行为一致：同一设备同一时刻也只能被一个模块占用）。

---

## 6. Python 侧设计

### 6.1 `core.LANSensorThread`（对齐 `SerialThread`）

```python
class LANSensorThread(QThread):
    """局域网传感器接收线程：内嵌 stdlib HTTP 服务，对外接口与 SerialThread 同构。"""
    data_received = Signal(str)     # "START" / "t,v" / "TARE_DONE,..." / "ERROR:..."
    status_changed = Signal(str)    # 可选："等待设备 (192.168.x.x:8802)" / "已连接 <设备IP>" / "设备超时"

    def __init__(self, device_id, port, timeout_s=15.0): ...
    def send_command(self, cmd: str): ...   # 下行命令排队，随下次 POST 响应捎带（力传感器 TARE 用）
    def stop(self): ...                     # shutdown() + server_close()，与 SerialThread.stop 同语义
```

行为规格：

| 阶段 | 行为 |
|---|---|
| `start()` | `ThreadingHTTPServer` 绑定 `0.0.0.0:port` → `status_changed("等待设备 (IP:端口)")`。**端口绑定失败**（被占用 / 双超声波模块冲突）→ `data_received("ERROR:端口被占用…")`，线程结束 |
| 收到 POST | 校验 `device` 字段匹配 → 首批或 `reset=true` 时先 `emit("START")` → 逐样本 `emit("t,v")` → `emit` replies → 响应 `{"ok":true,"cmds":[排队命令]}`（并清队列） |
| 15 秒无 POST | `data_received("ERROR:设备超时，等待重新连接…")` + 状态回「等待设备」；**线程不退出**，设备恢复上报后自动续上（比串口版友好：拔线重插不用重点「连接」） |
| `stop()` | `shutdown()` 可靠释放端口（与 flaskserver 的 `make_server` 停机同理由，见 `flask-server-design.md` §8.4） |

**线程模型**：HTTP handler 跑在 `ThreadingHTTPServer` 的工作线程里，`emit` 跨线程信号由 Qt 自动队列到 GUI 线程——安全且无需额外封送；handler 内**只**做 JSON 解析与 `emit`，不碰任何 Qt 控件（遵守 `flask-server-design.md` §8.1 铁律）。超时监测由 `run()` 主循环轮询 `last_recv` 时间戳。

### 6.2 `core.LanDiscoveryService`（全局一个，main.py 启动）

- UDP `0.0.0.0:8899`，daemon 线程，随主程序启停。
- 维护注册表 `{device_id: port}`：`LANSensorThread.start` 时注册、`stop` 后注销。
- 收到 `{"proto":"physchem-discover","device":"force_sensor"}`：
  - 该 device 已注册 → 单播应答 `{"proto":"physchem-discover-reply","device":"force_sensor","host":"<lan_ip()>","port":8802}`
  - 未注册 → **不应答**（设备侧 2 秒超时即放弃，提示用户先在上位机开局域网模式）。
- 多网卡：应答的 `host` 取 `lan_ip()`（默认出口网卡），与仪表盘局域网地址的取法一致。

### 6.3 `core.lan_ip()` 挪家

`lan_ip()` 目前在 `main.py`；`LANSensorThread` 与发现服务都在 `core.py` 需要它。**移入 `core.py`**，`main.py` 改为 `from core import lan_ip`（函数体不变，就是 `flask-server-design.md` §13.3 里那段 UDP connect 探测）。

### 6.4 模块接入（六个模块各 ~30 行）

| 改动点 | 内容 |
|---|---|
| `mode_combo` | 加第四项「局域网」（现有：模拟器 / 串口 / BLE） |
| 模块常量 | `LAN_DEVICE_ID`、`LAN_PORT`（按 §5.6 端口表） |
| `connect_device()` | 新分支：`LANSensorThread(LAN_DEVICE_ID, LAN_PORT)`，信号接法与 `SerialThread` 完全相同 |
| 面板 UI | 局域网模式下显示 `本机 192.168.x.x:8802，等待设备连接…`（只读，让用户知道该往配网页里填什么） |
| 力传感器 | 去皮 / 校准按钮在局域网模式下改调 `lan_thread.send_command("TARE")`（串口模式保持 `serial.write("TARE\n")`）；`TARE_DONE` 回执走现有解析 |
| 模式持久化 | 连接方式选择已随 `sensor_config.json` 保存，无需新增字段 |
| `DataService._apply_connection` | 模式模糊匹配补 `'局域网' / 'lan'` 分支 → 网页仪表盘也能切到局域网模式 |

### 6.5 端口一览

| 端口 | 用途 | 归属 |
|---|---|---|
| 8765 | flaskserver 数据接口（现有） | 插件 |
| **8800–8805** | 六个模块的传感器接收服务 | `core.LANSensorThread`（按需启停） |
| **8899** | UDP 设备发现应答 | `core.LanDiscoveryService`（常驻） |

---

## 7. 协议规格

### 7.1 上行：`POST /api/data`

```http
POST /api/data HTTP/1.1
Content-Type: application/json

{
  "device": "force_sensor",
  "seq": 128,
  "reset": false,
  "samples": [[123456, 8388608], [123556, 8388609], ...],
  "replies": ["TARE_DONE,offset"]        // 可选，上一轮命令的回执
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `device` | str | 设备 ID（§5.6 表）；上位机不匹配则忽略整个请求（仍回 200，防设备反复重试刷日志） |
| `seq` | int | 批次号，每批 +1；跳号 = 丢批 |
| `reset` | bool | 设备重启 / 缓冲溢出丢数据后为 `true`，上位机据此重发 `START` |
| `samples` | list | 每项 `[t, v]`（普通模块）或 `[t, v, i]`（VI 固件）；`t` 单位与串口版一致（超声波微秒，其余毫秒）；**还原为 `"t,v"` 文本逐条 emit，模块解析零改动** |
| `replies` | list[str] | 可选；逐条 emit（如 `TARE_DONE,offset`） |

**响应**：

```json
{"ok": true, "cmds": ["TARE"]}
```

- `cmds`：上位机排队的下行命令（可能为空数组）；固件逐条回调 `onCommand`。
- 非 200 / 超时 → 固件保留缓冲重试（§5.5）。

### 7.2 UDP 发现

```json
// 设备 → 255.255.255.255:8899（广播，重复 3 次每次隔 2s）
{"proto": "physchem-discover", "device": "force_sensor", "v": 1}

// 上位机 → 设备（单播应答，仅当该 device 的局域网模式已开启）
{"proto": "physchem-discover-reply", "device": "force_sensor", "host": "192.168.5.10", "port": 8802, "v": 1}
```

### 7.3 与现有文本协议的映射（上位机内部）

| 收到 | emit 到 `data_received` | 模块侧行为 |
|---|---|---|
| 首批 / `reset=true` | `"START"` | 各模块现有的“设备就绪”路径 |
| 每个 sample | `"123456,8388608"` | 现有 CSV 解析（`split(',')`），零改动 |
| 每条 reply | `"TARE_DONE,offset"` | 力传感器现有回执解析 |
| 15s 无 POST | `"ERROR:设备超时…"` | 现有 `ERROR:` 处理路径（UI 提示、置未连接） |

---

## 8. 固件库的文件组织

```
sensors/PhysChemNet/
├── PhysChemNet.h        // 全部实现（单头文件库，#include 即用）
├── README.md            // 安装（复制进 libraries/）+ API + 配网页说明 + 协议
└── examples/
    └── force_wifi/force_wifi.ino   // 样例（与 §5.6 的力传感器固件同源）
```

- **单头文件**：Arduino 项目没有包管理器，单 `.h` 复制即用，门槛最低。
- 库内**不使用** `String` 拼接构造大 JSON（500ms 批量 5 条的量级可以接受，与 PDsmartUPS 相同手法：`String` 拼接 + `HTTPClient`）；若将来提高频率再换定长 `char` 缓冲。
- 依赖仅 Arduino-ESP32 自带库（`WiFi.h` / `WebServer.h` / `EEPROM.h` / `HTTPClient.h` / `WiFiUdp.h`）。

---

## 9. UI 集成（上位机）

不新增任何主页卡片 / 设置页——局域网是**模块内**的连接方式，与串口平级：

```
┌─ 连接控制卡 ────────────────────────────────┐
│ 连接方式  [模拟器 ▾]  ← 下拉新增「局域网」     │
│ 串口      [COM3 ▾] [刷新]   ← 非串口模式隐藏   │
│ ── 以下仅局域网模式显示 ──                    │
│ 本机地址   192.168.5.10:8802     [复制]       │
│ 状态      等待设备连接…（设备配网页填此地址）    │
└────────────────────────────────────────────┘
```

- 「本机地址」行给 `lan_ip()`，无网卡时显示「未检测到局域网」并禁用连接按钮（对齐仪表盘局域网开关的降级行为）。
- `status_changed` 信号驱动状态行文字，同时映射到模块现有连接状态标签。
- 主题 / 全屏 / 网页仪表盘等一切现有能力自动覆盖新模式（因为对模块来说它就是又一个 `data_received` 来源）。

---

## 10. 安全模型

| 项 | 决定 | 理由 |
|---|---|---|
| 接收端鉴权 | **无**（局域网内任何设备都可 POST） | 与现有仪表盘局域网模式同一信任模型：课堂教学网。加共享密钥的成本是配网页多一个框 + 双端校验，列为后续可选增强 |
| 接收端绑定 | `0.0.0.0:8800-8805`（局域网模式开启期间） | 必须，否则设备连不上；未开启模块不占端口 |
| 下行命令 | 同样无鉴权 | 同上；`cmds` 只影响该设备自身的去皮/校准 |
| 配网页 | 无密码（热点密码即门槛） | 热点密码 `12345678` 是公开默认值——修改入口在配网页里（改的是 WiFi，热点名/密码本期固定，见 §12） |
| 数据面 | 明文 HTTP | 同仪表盘；不做 HTTPS（§2） |

> ⚠️ 文档与各传感器 README 需明示：**开启局域网模式后，同一网络内的任何人都可能向你的实验灌数据或给设备发命令**，请仅在可信网络使用。

---

## 11. 边界情况与已知限制

| # | 场景 | 行为 / 代价 |
|---|---|---|
| 1 | STA 连接 / 重连期间 | AP 信道跟随 STA，热点上的手机短暂掉线重连（ESP32 单射频，无法避免） |
| 2 | 服务器关机 / 地址错 | POST 超时 1.5s 阻塞 loop → 采样暂停；缓冲保留（≤200 条 ≈ 20s），恢复后续传；超容量的旧数据丢弃并置 `reset` |
| 3 | 设备超时（>15s 无 POST） | 上位机 emit `ERROR:` 并回「等待设备」，线程存活；设备恢复后自动续传，**无需重新点连接** |
| 4 | 上位机先关后开（IP 没变） | 设备 POST 失败 → 重试 → 上位机起来后自动接上 |
| 5 | 上位机 IP 变了 | 设备一直失败 → 用户手机连热点改地址（§4.4）；或 EEPROM 为空时走自动发现 |
| 6 | 两个超声波模块同时开局域网 | 后者端口绑定失败 → `ERROR:端口被占用`，UI 提示（与串口被占用同体验） |
| 7 | 局域网延迟 | 批量窗口 500ms + 局域网 RTT → 曲线落后真实 ≤ ~0.6s；对力学/化学教学实验可接受 |
| 8 | 缓冲溢出（服务器长时间不可达） | 丢最旧 + `reset=true`；上位机重发 `START`，图表出现断点（与串口丢行同观感） |
| 9 | 多网卡上位机 | `lan_ip()` 取默认出口网卡；用户填错网段的 IP 属配置问题，配网页可见上报失败状态便于排查 |

---

## 12. 待决问题

1. **热点 SSID / 密码**：暂定 `PhysChem-<device_id>` / `12345678`（PDsmartUPS 同款）。是否允许在配网页修改热点自身凭据？（改错会失联，第一版建议只读展示）
2. **`replies` 回执机制**：力传感器的 `TARE_DONE` 需要它；其他模块首版用不到。是否保留在协议里（建议保留，成本一行）？
3. **超声波 device ID**：位移/速度共用 `ultrasonic` 还是烧录时选 `ultrasonic_displacement` / `ultrasonic_velocity`？建议前者（固件免配置，两模块都能收）。
4. **UDP 发现端口 8899**：需实测确认学校 / 家用路由器不拦截 UDP 广播；被拦时自动发现失效，手动配网页兜底（功能不残缺）。
5. **上报周期可配**：500ms 硬编码 vs EEPROM 预留字段里做成可配（1–5s）？建议第一版硬编码，字段已预留。
6. **VI 固件的 samples 三元组**是否需要独立 `device` 粒度的校验（8805 端口只收 `vi_esp32_adc`）——是，与单值模块同规则，无需特殊处理，仅确认。

---

## 13. 分阶段实施计划

| 阶段 | 内容 | 验收标准 |
|---|---|---|
| **P0** | 本文档 | 结构、协议、边界行为达成一致 |
| **P1** | `PhysChemNet.h` 库骨架 | 手机的热点能看到、配网页能连 WiFi 并保存（重新上电仍连）；服务器地址可改可存 |
| **P2** | `core.lan_ip()` 挪家 + `LANSensorThread` + `LanDiscoveryService` | 单元级：用 `curl` 模拟设备 POST，`data_received` 逐条收到 `START`/`t,v`；设备发现应答正确 |
| **P3** | 力传感器端到端（`force_wifi.ino` + 模块接入） | 无线采集曲线正常；去皮按钮经 `cmds` 下行、`TARE_DONE` 回执显示；拔设备网线 → 15s 后 UI 报超时 → 恢复后自动续传 |
| **P4** | 铺满其余 5 固件 + 5 模块 | 六个模块局域网模式全部可用；两超声波模块抢端口报错正确 |
| **P5** | `DataService._apply_connection` 补局域网 | 网页仪表盘可切换模块到局域网模式 |
| **P6** | 文档 | 根 `README.md`、六传感器 README、`AGENTS.md`、`PhysChemNet/README.md`、固件烧录说明 |

> **顺序说明**：P2 在纯 Python 侧即可验证（curl 当设备），不依赖任何固件进度；P1 与 P2 可并行。P3 选力传感器做样板，因为它是唯一有下行命令的模块——最难的用例先跑通，其余五个是纯上行复制。

---

## 14. 验证矩阵

| # | 场景 | 期望 |
|---|---|---|
| 1 | 新设备上电（EEPROM 空） | 热点 `PhysChem-xxx` 出现；连入可打开 `192.168.4.1` 配网页 |
| 2 | 配网页连 WiFi 并保存 | STA 连上路由器；**热点仍在线**；重启设备后自动连上（EEPROM 生效） |
| 3 | 上位机开局域网模式 + 设备 EEPROM 无服务器地址 | 设备广播发现 → 自动拿到地址开始上报（内存态，配网页显示"自动发现"） |
| 4 | 配网页手动改服务器地址并保存 | 下一批 POST 发往新地址；无需重启设备 |
| 5 | 正常采集 | 曲线实时（落后 ≤0.6s）；拔 USB 对比串口版数据一致 |
| 6 | 局域网模式下点「去皮」 | ≤500ms 内设备执行；`TARE_DONE` 回执显示；曲线归零 |
| 7 | 设备断电 20s 再上电 | 上位机先 `ERROR:超时` 回等待态，设备回来后自动续传并发 `START` |
| 8 | 上位机退出再启动（IP 未变） | 设备自动重连，无需任何操作 |
| 9 | 两个超声波模块同时开局域网 | 后开的收到 `ERROR:端口被占用` |
| 10 | 服务器地址填错 | 配网页 `last_post_ok=false` 可见；设备持续重试不崩；缓冲溢出后 `reset` 续传 |
| 11 | STA 断网 | 热点仍可访问（手机可进配网页排查）；网络恢复后自动重连上报 |
| 12 | 未连接 WiFi 的固件 | 串口输出照常（`feed` 同步 Serial），有线调试不受影响 |
| 13 | 退出程序（局域网模式开启中） | 端口释放、线程正常回收，无 `QThread` 析构崩溃 |
| 14 | 网页仪表盘切某模块到局域网模式 | 模块真的进入等待设备状态（`_apply_connection` 生效） |

---

## 15. 变更记录

| 日期 | 变更 |
|---|---|
| 初稿 | 建立设计：架构（固件主动 HTTP POST + stdlib 接收）、PhysChemNet 共享库、AP+STA 双模常开、配网页与 EEPROM 布局、500ms 批量协议、响应体捎带下行命令、UDP 自动发现、端口分配、实施计划 |
