# UI 与内核分离 —— 设计方案

> 状态：已实现（2026-11-12，`feat/kernel-ui-split-rest`）；第 5 节的部分命名与提案不同，见「实现说明」
> 日期：2026-11-09
> 基线：`main` @ `09190c2`
> 相关文档：[多路连接设计](multi-channel-design.md)、[flaskserver 插件设计](flask-server-design.md)、[项目约束](../AGENTS.md)

## 1. 背景与结论

当前项目的功能是完整的，但代码结构把三类职责混在了一起：

- **界面职责**：Qt / FluentWidgets 控件、图表、主题、对话框；
- **设备职责**：串口/模拟器线程、数据解析、采样节流；
- **业务职责**：物理量换算、校准、统计、缓存、CSV、快照、AI 数据组装。

结果是每个传感器 `Widget` 同时承担以上全部职责，`core.py` 又集中了几乎全部共享能力。任何一处改动都容易牵连 UI、采集和接口层。

**结论：可以做 UI 与内核分离，但应采用“绞杀式迁移”，不重写。** 先把内核抽成无 Qt 依赖的 Python 包，`core.py` 保留兼容门面，逐个模块替换，最后删除门面。

## 2. 现状诊断

### 2.1 量化指标

以下指标以当前 `main` 分支为基线，使用 Python `ast` 统计类内方法体行数，仅用于判断结构耦合程度，不代表逐字重复率。

| 指标 | 数值 | 说明 |
|---|---:|---|
| `src/core.py` | 6983 行 | 配置、日志、串口、图表、主题、对话框、AI、DataService 全部集中 |
| 6 个传感器 Widget 方法体 | 约 7920 行 | pH / 电压 / 电流 / 力 / 超声波位移 / 超声波速度 |
| 6 个模块同名方法 | 47 个 | 通道管理、连接、采集、快照、CSV 等方法高度同构 |
| 同名方法覆盖各模块方法体 | 78%–100% | 同名不代表逐字相同，但职责结构高度一致 |
| 粗分后的采集/换算/缓存/快照逻辑 | 约 3779 行 | 这部分目前藏在 QWidget 内，无法脱离 GUI 测试 |

### 2.2 关键耦合点

| 耦合点 | 位置 | 问题 |
|---|---|---|
| `core.py` 顶部直接导入 PySide6 / qfluentwidgets | [`src/core.py`](../src/core.py) L32-L58 | 任何 `import core` 都会拖入完整 Qt 栈，内核无法无头运行 |
| `handle_data` 同时解析、换算、刷新 QLabel、写缓存、更新文本区 | [`src/sensors/ph/ph_sensor.py`](../src/sensors/ph/ph_sensor.py) L1180-L1252 | 数据流与 UI 刷新强耦合 |
| `api_snapshot()` 直接读 Widget 的通道列表 | [`src/sensors/ph/ph_sensor.py`](../src/sensors/ph/ph_sensor.py) L1438-L1465 | 接口层依赖具体页面对象 |
| `DataService` 通过 `mode_combo` / `port_combo` / `api_command` 反射操作控件 | [`src/core.py`](../src/core.py) L6838-L6925 | 接口是隐式约定，不是稳定契约 |
| `DataService` 是 `QObject` + `QTimer` | [`src/core.py`](../src/core.py) L6697-L6713 | 数据总线依赖 GUI 事件循环，命令需绕回 GUI 线程执行 |
| `ChartPanel` 内嵌 AI 按钮与数据提供回调 | [`src/core.py`](../src/core.py) L1350-L1420 | 图表组件同时承担展示与 AI 业务入口 |

### 2.3 已有的可复用缝隙

`flaskserver` 插件只依赖 `DataService`，不直接认识任何传感器控件，见 [`src/flaskserver/server.py`](../src/flaskserver/server.py) L129-L288。这说明“数据总线”这一层已经被验证可行，只需把它从 Qt/Widget 中解耦出来。

## 3. 目标与非目标

### 3.1 目标

1. 内核层不依赖任何 Qt / FluentWidgets，可在无 `QApplication` 的环境下运行。
2. 传感器模块只保留界面与交互，采集、换算、校准、缓存、导出全部交给内核。
3. 数据总线、HTTP 插件、未来的 CLI / MCP / WebSocket 共用同一套内核 API。
4. 保持现有外部契约不变：配置字段、CSV 表头、快照结构、固件协议。
5. 保持“丢一个文件夹就是新传感器”的模块化体验。

### 3.2 非目标

- 不拆进程、不做 RPC / WebSocket 内部通信；
- 不重写 UI，不更换 Qt / FluentWidgets；
- 不修改固件输出格式与波特率；
- 不修改现有 CSV 列名与 `sensor_config.json` 字段语义；
- 不在本次方案中做数据库、历史回放、多用户权限等新功能。

## 4. 目标架构

```text
┌─────────────────────────────────────────────────────────────┐
│ UI 层（PySide6 / FluentWidgets）                            │
│  页面 / 卡片 / 图表 ChartPanel / 对话框 / 主题 / 导航        │
│  只调用内核公开 API；不直接操作串口、不直接改数据数组        │
└───────────────────────────┬─────────────────────────────────┘
                            │ 调用 API
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ 应用编排层（app）                                           │
│  启动装配 / 模块发现 / _kernel.py 加载 / 插件注入 / 退出清理 │
└───────────────────────────┬─────────────────────────────────┘
                            │ 装配
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ 内核层（kernel，纯 Python，零 Qt）                          │
│  SensorKernel / Transport / Config / Logging / DataBus / AI │
└───────────────────────────┬─────────────────────────────────┘
                            │ 事件 / 快照
                            ▲
┌───────────────────────────┴─────────────────────────────────┐
│ 事件桥（ui/adapters/QtKernelBridge）                         │
│  后台线程入队 → GUI 线程 QTimer 取出 → emit Qt Signal        │
└─────────────────────────────────────────────────────────────┘

外部接口：flaskserver / MCP / CLI ──只依赖──► kernel.bus.DataBus
```

依赖方向只有一条：**UI → 内核**。内核通过回调/事件通知 UI，不反向 import 任何 UI 模块。

### 4.1 分层职责

| 层 | 职责 | 允许依赖 | 禁止依赖 |
|---|---|---|---|
| `kernel` | 配置、日志、传输、通道生命周期、采样过滤、换算校准、缓存、统计、CSV、快照、命令、数据总线、AI 请求 | 标准库、numpy、可选 pyserial | PySide6、qfluentwidgets、`core`、`ui`、`sensors` |
| `app` | 启动、模块发现、内核实例化、插件注入、退出清理 | `kernel`、`ui` | 具体传感器内部实现 |
| `ui` | 页面、图表、卡片、对话框、主题、导航、Qt 事件桥 | `kernel` | 串口、配置文件写入、内核数据数组 |
| `plugins` | HTTP / MCP 等传输层 | `kernel.bus` | `ui`、具体 Widget |

### 4.2 线程模型

当前实现使用 `QThread` + Qt 信号直接回调模块。分离后建议：

- 内核传输层使用普通 `threading.Thread`，`SerialTransport` / `SimulatorTransport` 只负责“读一行、回调一行”；
- 每个通道一个读线程，由 `TransportSupervisor` 统一管理启动、停止、超时回收；
- 通道数据缓冲加锁，`snapshot()` / `series()` 在锁内拷贝，UI 不直接持有内核数组；
- UI 侧新增 `QtKernelBridge(QObject)`：后台线程只把事件放进 `queue.Queue`，GUI 线程用 `QTimer(50ms)` 批量取出并 emit Qt 信号；
- `DataBus` 不再需要 `QTimer` 和 GUI 线程队列，`submit_command()` 直接调用内核线程安全命令。

这样可以同时解决两个问题：内核脱离 Qt，以及后台线程直接操作 QLabel 的跨线程风险。

## 5. 内核契约

### 5.1 `SensorKernel` 基类

```python
# kernel/sensors/base.py
from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass
class ChannelSpec:
    id: int
    name: str
    color: str
    mode: str = "serial"          # serial | simulator
    port: str = ""
    sample_interval_ms: int = 100
    sensor_params: dict | None = None


@dataclass
class Result:
    ok: bool
    message: str = ""
    error: str = ""


class SensorKernel:
    key: str
    title: str

    # ---- 通道与连接 ----
    def add_channel(self, spec: ChannelSpec) -> int: ...
    def update_channel(self, cid: int, **fields) -> None: ...
    def remove_channel(self, cid: int) -> None: ...
    def connect(self, cid: int) -> Result: ...
    def disconnect(self, cid: int) -> None: ...
    def connect_all(self) -> None: ...
    def disconnect_all(self) -> None: ...

    # ---- 采集与数据 ----
    def start_collection(self) -> None: ...
    def stop_collection(self) -> None: ...
    def clear_data(self) -> None: ...
    def snapshot(self, max_points: int = 0) -> dict: ...
    def series(self, cid: int | None = None, limit: int = 2000) -> list: ...
    def stats(self) -> dict: ...
    def export_csv(self, path=None): ...

    # ---- 外部接口 ----
    def command(self, action: str, params: dict) -> Result: ...
    def subscribe(self, cb: Callable[[object], None]) -> Callable[[], None]: ...
    def shutdown(self) -> None: ...

    # ---- 子类只实现物理差异 ----
    def decode_line(self, line: str) -> float | None: ...
    def convert(self, channel, raw: float) -> float: ...
```

### 5.2 事件类型

建议先控制在 5 类，避免事件总线过度设计：

```text
ChannelStateChanged   连接 / 断开 / 错误
SamplePreview         最新值，用于实时行
SampleRecorded        已入库样本，用于图表增量
CollectionChanged     开始 / 停止采集
ChannelsChanged       通道增删改
```

事件在后台线程产生，`QtKernelBridge` 负责跨线程投递；内核本身不创建任何 `QObject`。

**实现说明（落地版本）**：没有引入 `QtKernelBridge` 类，实际用 `core.EventBus` +
`EventSubscription`（有界队列，满时优先丢 `sample_preview`）；View 订阅后由
`QTimer(50ms)` 在 GUI 线程批量 `drain()`。`channels_changed` 不只在通道增删时发出：
View 的本地修改（改名/改色/换模式/改采样间隔/校准/显隐）必须调用
`kernel.notify_change()` 发布，保证网页与 CLI 端同步。`KernelRegistry` 会订阅每个
内核的事件总线，汇总成带单调序号的环形日志，供 `GET /api/events`（SSE）推送。

### 5.3 通道配置与持久化

`ChannelSpec` 只放可持久化字段。各传感器的差异参数放在 `sensor_params` 子结构：

- pH：校准点、校准模式、理论斜率、拟合系数；
- 电压：ADC 位数、分压比、放大倍数、HX711 / ADS1115 参数、去皮零点；
- 电流：ACS712 量程、VCC、零点电压、分压比、DC/AC 模式、RMS 窗口；
- 力：去皮 offset、标定 scale、单位；
- 超声波：回波窗口、速度差分窗口。

配置读写由 `kernel.config` 统一完成，支持：

- 旧版顶层字段 + `channels` 列表的兼容读取；
- `schema_version` 迁移；
- 临时文件 + `os.replace` 原子写；
- `configPersistenceEnabled` 开关。

## 6. 目标目录

```text
src/
├─ kernel/                     # 纯 Python，零 Qt
│  ├─ config/                  # sensor_config.json、schema 迁移、原子写
│  ├─ logging/                 # logs.json、级别控制
│  ├─ transport/               # SerialTransport / SimulatorTransport / 线程回收
│  ├─ sensors/                 # SensorKernel / Channel / 采样门控 / 校准基类
│  ├─ bus/                     # DataBus（纯 Python）
│  └─ ai/                      # prompt 组装 + OpenAI 兼容 HTTP 客户端
├─ ui/                         # 只放 Qt
│  ├─ charts/                  # ChartPanel + matplotlib/pyqtgraph 引擎
│  ├─ widgets/                 # FluentCard / CollapsibleCard / 通道卡 / 文本区
│  ├─ dialogs/                 # 校准 / 采样率 / AI / 字体
│  ├─ pages/                   # 各传感器页面（薄）
│  ├─ shell/                   # MainWindow / Home / Settings
│  ├─ theme/                   # 字体 / QSS / 主题
│  └─ adapters/                # QtKernelBridge
├─ app/                        # 启动装配、模块发现、插件注入
├─ sensors/                    # 保持“丢文件夹即插件”
│  └─ ph/
│     ├─ ph_sensor.py          # 只留 View
│     ├─ _kernel.py            # PhKernel
│     └─ ...
├─ core.py                     # 过渡期兼容门面，最终删除
└─ flaskserver/                # 只依赖 kernel.bus
```

### 6.1 模块加载器改造

当前加载器只认 `.py` 头部的 `MODULE META`，见 [`src/main.py`](../src/main.py) L341-L412。建议：

1. 视图文件继续留在 `src/sensors/<device>/<name>.py`；
2. 同目录增加 `_kernel.py`，定义 `Kernel` 类；
3. `MODULE META` 增加可选字段：
   ```text
   # kernel: _kernel:Kernel
   ```
4. 加载器发现视图文件后，按同目录 `_kernel.py` 用 `importlib` 加载为唯一模块名，实例化内核，再传给视图：
   ```python
   widget = view_cls(kernel) if kernel_cls else view_cls()
   ```
5. 没有 `_kernel.py` 的旧模块走兼容分支，仍然原样实例化，保证迁移期间不破；
6. 加载器已经会跳过 `_` 开头的文件，`_kernel.py` 不会被误当成传感器模块；
7. PyInstaller 的 spec 已经收集 `src/sensors/**/*.py`，`_kernel.py` 会自动进包；共享 `kernel` 包由 `main.py` 静态 import，也会被正常收集。

## 7. `core.py` 拆分映射

| 当前区段 | 内容 | 去向 |
|---|---|---|
| L129-L1021 | AppConfig、字体、日志、sensor_config 读写 | `kernel/config` + `kernel/logging` + `ui/theme/fonts` |
| L3348-L3522 | `SerialThread` / `SimulatorThread` / `stop_thread` | `kernel/transport` |
| L1350-L2666 | `ChartPanel` 及拟合/离群点/AI 按钮 | `ui/charts` |
| L2668-L2856 | AI prompt、数据格式化、HTTP 请求线程 | `kernel/ai` |
| L2857-L3346 | AI 设置/信息/对话窗口 | `ui/dialogs/ai.py` |
| L3524-L4489 | 文本区、浮动面板、折叠卡、FluentCard | `ui/widgets` |
| L4489-L5390 | `VIConnectionUnit` + 连接面板 | 逻辑去 `kernel/sensors/vi.py`，面板去 `ui/widgets/vi_panel.py` |
| L5390-L6031 | 主题、QSS、按钮/ComboBox 样式 | `ui/theme` + `ui/widgets` |
| L6032-L6676 | 校准/采样率对话框 | 对话框去 `ui/dialogs`，拟合计算去 `kernel/sensors/calibration.py` |
| L6676-L6983 | `DataService` | `kernel/bus/service.py` |

阶段一先保留兼容门面：

```python
# core.py（过渡期）
from kernel.logging import get_logger
from kernel.transport import SerialThread, SimulatorThread, stop_thread
from kernel.config import load_sensor_config, save_sensor_config
```

现有模块一行不改也能继续运行；后续逐个把 `from core import ...` 改成 `from kernel...`，最后删除 `core.py`。

## 8. 传感器模块拆分映射

以 pH 为例，现有 `PhSensorWidget` 可按方法类别切分：

| 现有方法类别 | 去向 |
|---|---|
| `load_config` / `save_config` / `_restore_channels` / `_make_channel` / `add_channel` / `_delete_channel` | `_kernel.py` |
| `_calc_coeffs_for` / `adc_to_ph` / `calculate_calibration_coefficients` | `_kernel.py` |
| `_connect_channel` / `_disconnect_channel` / `connect_device` / `disconnect_all` | `_kernel.py` 的 `TransportSupervisor` |
| `handle_data` 中的解析、换算、采样过滤、入库 | `_kernel.py` |
| `start_collection` / `stop_collection` / `clear_data` / `update_stats` | `_kernel.py` |
| `save_data` / `api_snapshot` / `api_command` / `_ai_data` | `_kernel.py` |
| `init_ui` / `_build_channel_card` / `_build_live_row` / `_refresh_*` / `_on_*` / `apply_theme` | 留在 View |
| `fluent_message_box` 弹窗、颜色下拉、主题刷新 | 留在 View |

拆分后 View 只做三件事：

1. 构造控件；
2. 调 `kernel.add_channel / connect / start_collection`；
3. 订阅 `QtKernelBridge` 事件，刷新标签、实时行、图表。

`api_snapshot` / `_ai_data` 的字段名和结构保持不变，直接由内核实现。这样 `flaskserver` 的 HTTP 接口和网页前端无需改动。

## 9. 迁移路线

| 阶段 | 动作 | 完成判据 |
|---|---|---|
| P0 基线 | 增加 `scripts/check_layers.py`（AST 扫描 import）、无头冒烟脚本、固定 ADC→物理量黄金值 | 能自动判定“kernel 是否 import PySide6” |
| P1 抽底座 | 把日志、sensor_config、Serial/Simulator、stop 线程迁到 `kernel`；`core.py` 做重导出 | 6 个模块不改业务代码仍能启动；配置/串口行为不变 |
| P2 抽通用内核 | 实现 `SensorKernel`、`ChannelSpec`、`SampleBuffer`、采样门控、统计、事件订阅 | 无 Qt 环境下可跑模拟器、得到样本、快照、CSV |
| P3 pH 试点 | pH 拆 `_kernel.py` + 薄 View；加载器注入；`DataBus` 同时支持内核对象和旧 Widget | pH 页面功能对齐；HTTP 返回结构不变 |
| P4 推广其余 5 个 | 顺序：超声波位移 → 超声波速度 → 电压 → 力 → 电流（AC RMS 最复杂放最后） | 6 个模块的采集/换算/导出全部由内核完成 |
| P5 拆 UI 与 shell | `ChartPanel`、主题、对话框、卡片迁 `ui/`；`main.py` 拆成 `app/bootstrap.py` + `ui/shell/*` | `main.py` 只做启动；`core.py` 只剩兼容重导出 |
| P6 清理固化 | 删除兼容门面、旧侧边栏；更新 AGENTS/README/spec；跑打包回归 | kernel 无 Qt；PyInstaller onedir 可运行；插件零改动 |

建议每个阶段一个 PR，**一个 PR 只做一层迁移**，不夹带 UI 改版或功能新增。

## 10. 风险与对策

| 风险 | 对策 |
|---|---|
| `QThread` 换普通线程后退出崩溃 | 保留现有 `running=True` 初值、`stop() + join(timeout)`、超时线程保活列表；统一封装在 `TransportSupervisor` |
| UI 读内核数组产生竞态 | 内核缓冲加锁，`snapshot()` / `series()` 拷贝；UI 不直接拿 `channel.time_data` |
| 配置迁移丢校准数据 | `sensor_config.json` 加 `schema_version`；读写兼容旧顶层字段 + `channels`；原子写 |
| 打包漏掉 `_kernel.py` | 现有 spec 已收集 `src/sensors/**/*.py`；共享 `kernel` 包由 `main.py` 静态引用；打包后单独验证 |
| DataBus 行为不一致 | P3 起保留双模式：内核对象走新协议，旧 Widget 走原反射逻辑；HTTP 端到端对比 |
| 图表刷新性能 | 先沿用当前定时拉取；数据量大再增加 `since_index` 增量接口，不提前优化 |
| 范围失控 | 明确不做：不改固件协议、不改 CSV 列名、不改配置字段名、不重写 UI、不拆进程 |

## 11. 验收标准

1. `src/kernel/**` 中 `PySide6` / `qfluentwidgets` / `Qt` 导入数为 0，并纳入脚本检查。
2. 无头脚本能在没有 `QApplication` 的情况下，对 6 个内核各跑通：建通道 → 模拟器采集 → 快照 → 统计 → CSV → `start/stop/clear` 命令。
3. `flaskserver` 的全部 HTTP 端点返回结构与迁移前一致。
4. 每个模块做一次 offscreen UI 冒烟：页面能创建、通道能增删、图表能渲染、主题能切换。
5. 传感器 Widget 文件行数明显下降：业务方法基本清空，View 只保留约 300–500 行 UI 代码。
6. `main.py` 最终只保留启动入口，模块发现、插件加载、窗口装配分别进 `app/` 和 `ui/shell/`。
7. PyInstaller onedir 打包后启动、连接模拟器、保存 CSV、打开网页接口均正常。

## 12. 已定取舍

- **不拆进程、不做 RPC**：当前数据率只有 10Hz 级别，单进程包级隔离足够。
- **不重写 UI**：`ChartPanel`、Fluent 卡片、主题体系保留，只搬家、只改数据来源。
- **不一次性改 6 个模块**：先 pH 试点，跑通“内核 + 桥 + DataBus 双模式”后再推广。
- **不改变外部契约**：`api_snapshot` 字段、CSV 表头、配置键名、固件 `timestamp,value` 格式全部保持。
- **内核用普通线程 + 回调**，Qt 适配只存在于 `ui/adapters/QtKernelBridge`。
- **`_kernel.py` 与传感器同目录**，保住“丢一个文件夹就是新传感器”的插件体验，同时不破坏 PyInstaller 的 datas 收集。

## 13. 实施起点

建议先完成 P0 + P1：

1. 增加 `scripts/check_layers.py`，把“内核禁止 import Qt”变成可执行的硬检查；
2. 把日志、sensor_config、Serial/Simulator、线程回收抽到 `kernel/`；
3. `core.py` 改为兼容重导出，六个模块暂时不改；
4. 跑一遍现有启动、模拟器采集、CSV 保存、HTTP 接口，确认行为不变。

这一步不改任何界面，风险最低，但会把后续所有拆分的地基打好。
