# AGENTS.md

本文件是给 AI 编码助手的**约束清单**。项目使用方法、架构讲解、传感器文档见 `README.md` 与各模块目录下的 `README.md`，不要在本文件里重复。

## 1. 硬性禁令

- **禁止 `print`**：日志一律 `from core import get_logger` + `log = get_logger('模块名')`。控制台始终输出；「运行日志」开关只决定是否额外写入 `logs.json`。
- **禁止直接 `import serial`**：串口一律走 `core.list_serial_ports()` / `core.SERIAL_AVAILABLE` / `core.serial_unavailable_hint()`。pyserial 是可选依赖，未装时各模块须自动降级到模拟器模式。
- **禁止用 matplotlib / pyqtgraph 原生控件画图**：不得创建 `Figure` / `FigureCanvas` / `pg.PlotWidget`，一律用 `core.ChartPanel`，否则设置页的引擎热切换对该模块失效。
- **禁止构造原生 Qt 控件**：不得使用 `QLabel` / `QFrame` / `QGroupBox` / `QSpinBox` / `QDoubleSpinBox` / `QCheckBox`，一律用 FluentWidgets 对应组件。
- **禁止直接 `import bleak`**：BLE 是可选依赖，未装时须自动降级并提示。
- **禁止改 `main_legacy.py`**：迁移前的单文件存档，不再维护。新功能只改 `main.py` + 模块文件。
- **禁止基于 `NavButton` / `SidebarWidget` 开发**：迁移前的遗留侧边栏，`MainWindow` 已改用 `FluentWindow` 自带导航。
- **禁止在 `sensor_config.json` 之外散落校准数据**：校准参数统一经 `load_sensor_config()` / `save_sensor_config()` 读写。
- **禁止把运行产物提交进仓库**：`sensor_config.json` / `app_config.json` / `logs.json` / `build/` / `dist/` 均已被 `.gitignore` 忽略。

## 2. 新增传感器模块

**不改 `main.py`**，只需两步：

### 2.1 建目录丢文件

在 `传感器代码/` 下新建目录，放入下位机 `.ino` 与上位机 `.py`（`.py` 用英文蛇形命名，如 `temperature_sensor.py`）。

### 2.2 在 `.py` 文件头写识别区

```python
# === MODULE META ===
# icon: T
# name: 温度传感器
# category: physics
# class: TemperatureSensorWidget
# ===================
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `icon` | 是 | 图标文字，经 `make_text_icon()` 渲染成侧边栏图标（如 `V` / `pH` / `A`） |
| `name` | 是 | 模块显示名，用于侧边栏与主页磁贴 |
| `category` | 是 | `physics` 或 `chemistry`，决定主页分组 |
| `class` | 是 | 主类名，须继承 `QWidget` |

**格式严格**：字段名、冒号、空格写错会导致模块加载失败（`importlib` 动态加载依赖此格式）。

### 2.3 模块必须实现

- `self.chart = core.ChartPanel(...)`，并在 `__init__` 里 `self.chart.set_ai_data_provider(self._ai_data)`。
- `apply_theme(self, theme)`：委托 `core.apply_module_theme(self, theme)`，再调 `self.chart.apply_chart_theme(isDarkTheme())`。
- `_ai_data()`：返回 `{title, x_label, y_label, points, params, system_prompt}`，无数据返回 `None`；模块顶部定义 `AI_SYSTEM_PROMPT` 常量，经 `'system_prompt'` 键返回（旧键 `'prompt'` 兼容）。
- 用 `core.stop_thread()` 回收自己起的通信线程，不要只调 `stop()`。

### 2.4 组件选型对照

| 用途 | 用什么 |
|------|--------|
| 静态表单标签（「连接方式:」） | `BodyLabel` |
| 次要说明 / 统计小字（原先硬编码 `#666` 的灰色小字） | `CaptionLabel`（不设硬编码颜色） |
| 数字输入 | `SpinBox` / `DoubleSpinBox` |
| 模式开关 | `SwitchButton`，信号是 `checkedChanged`（**不是** `toggled`） |
| 普通卡片（连接控制 / 参数 / 实时数据 / 操作按钮） | `core.FluentCard` |
| 图表卡（需要全屏 / 浮动面板） | `core.CollapsibleCard` |
| 页面标题 | `TitleLabel` |
| 滚动区 / 页面背景 | `scroll_area_style()` / `page_bg_style()` |

**不要**再拼 `QWidget#card QLabel { color: ... }` 这类硬编码样式，Fluent 组件本身已随主题变色。

## 3. 图表（`core.ChartPanel`）

事务式 API，两种引擎行为一致：

```python
c = self.chart
c.begin()
c.plot(x, y, color='#0078d4', width=2, label='温度')
c.hline(0, color='#999', label='参考线')
c.set_labels('时间 (秒)', '温度 (°C)')
c.set_xlim(0, 60); c.set_ylim(-10, 110)
c.legend()
c.end()
```

- 多子图用 `ChartPanel(n_plots=N)`，各调用通过 `index` 参数寻址。
- 切换引擎时 `ChartPanel` 自动重放最近一次事务，无需手动重绘。
- 分析面板（拟合 / 离群点剔除 / 滚动窗口）用 `get_analysis_panel()` 取得，仅 pyqtgraph 下可见，matplotlib / 占位模式下自动隐藏。
- **水平参考线不得直接加入图例**：`InfiniteLine` 没有 `opts` 属性，旧版 pyqtgraph 的 `ItemSample.paint` 会崩，并拖垮整棵控件树的绘制。

## 4. 主题

- 所有模块须实现 `apply_theme(theme)`，亮 ↔ 暗双向可切。
- `core.apply_module_theme()` 用缓存的 `_orig_qss` 动态属性实现双向切换，**不要自己重写样式替换逻辑**。
- `FluentCard` 会被 `apply_module_theme` 跳过（它自带 Fluent 样式，套自定义 QSS 反而破坏背景）。

## 5. 环境与构建

- 依赖清单以 `pyproject.toml` 为唯一来源（`[dependency-groups].dev` 放 PyInstaller）。改依赖须同步更新 `requirements.txt`。
- 用 uv：`uv sync` 建环境、`uv run main.py` 启动、`uv run test_serial.py` 诊断。
- 用 pip：`pip install -r requirements.txt`。
- **命令的工作目录必须是项目根目录**（`main.py` 所在目录）：`sensor_config.json` / `app_config.json` / `logs.json` 均以 `main.py` 所在目录为基准路径。
- 本项目是脚本式应用（无 `build-system`），`pyproject.toml` 里已声明 `[tool.uv] package = false`，`uv build` 会被跳过；打包走 `PhysChem-DigitizerP.spec`：

```bash
uv sync
uv run pyinstaller --noconfirm PhysChem-DigitizerP.spec
```

- PyInstaller **必须用 onedir**（不是 onefile）：onefile 每次解压到临时目录，启动慢，且 `sensor_config.json` / `app_config.json` 无法跨次持久化。
- 传感器模块由 `importlib` 按 `__file__` 相对路径动态加载，PyInstaller 静态分析发现不了，**必须在 spec 的 `datas` 里作为数据文件收集**。
- 无自动化测试、无 CI/CD、无 lint / 类型检查配置。`test_serial.py` 只是手动诊断工具。

## 6. 约定

- 串口波特率固定 **115200**（固件与 Python 两侧硬编码）。
- 固件输出格式固定 `timestamp,value`（CSV）。
- 校准弹窗若为非模态或需要 `exec()`，返回后用 `deleteLater()` 释放，**不要**用 `WA_DeleteOnClose`（会立即销毁 C++ 对象，后续访问控件报 `RuntimeError: Internal C++ object already deleted`）。
- 新代码的标识符用英文；**保留**既有中文注释与中文命名。
- 文档与注释用中文。

## 7. 已知陷阱

### 中文路径

`传感器代码/` 及传感器子目录用中文命名（实测 golang/Python/git 均可正常工作，无需改名）。但以下位置用中文路径会踩坑：

- **Arduino Sketch 的目录名与 `.ino` 文件名必须完全一致**，这是 Arduino IDE 的硬性要求，与本项目的中文命名互相冲突——现有 `.ino` 全部不符合此要求（如 `传感器代码/力传感器/force.ino`）。**结果是这些固件必须在 Arduino IDE 里新建同名 sketch 粘贴烧录，无法直接打开编译**。新增固件时避免此坑：把 `.ino` 放在与其同名的目录下，或直接接受「粘贴烧录」的现状。
- 含空格的 `.ino` 文件名（现有 `ph esp32.ino`）在部分系统 / 构建链上会出问题。
- `git` 默认转义中文路径（`core.quotepath=true`），`git status` 显示为 `\346\204...`。要看清中文路径需临时关掉：

```bash
git -c core.quotepath=false status
```

### 退出确认框

**禁止在 `closeEvent` 内直接 `exec()`**：父窗口处于关闭状态时弹模态框会无法激活、按钮点击无响应（界面看似卡死，定时器仍在跑）。

正确做法见 `MainWindow.closeEvent` / `_prompt_exit`：

1. `event.ignore()` 取消本次关闭；
2. `QTimer.singleShot(0, ...)` 延迟到正常事件循环弹**顶层 `Dialog`**；
3. 确认后置 `_exit_confirmed` 并再次 `close()`。

### 线程回收

- 断开模块线程一律用 `core.stop_thread()`：内部 `stop()` + 限时 `wait(2000)`，超时的线程收进 `_retired_threads` 保活，避免 QThread 被回收时 fail-fast 崩溃。
- 通信线程的 `running` 初值须为 `True`，并在 `run()` 首行检查，防止 `stop()` 先于 `run()` 执行导致线程永不退出、`wait()` 卡死。
- `AIRequestThread` 不挂 parent，发送中关窗可自动收尾，避免 QThread 析构崩溃。

### Qt 告警与任务栏

- `main._install_qt_warning_filter()` 只屏蔽两条已知无害告警（`QFont::setPointSize: Point size <= 0`、`QWidgetWindow ... must be a top level window`），其余照常输出。
- `_apply_taskbar_identity(window)` **必须在 `window.show()` 之前**调用（写入 `PKEY_AppUserModel_*`），否则任务栏显示宿主 `python.exe` 的「Python」名称与图标。
