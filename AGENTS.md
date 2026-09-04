# 项目说明 / AGENTS.md

**[English](#english-version)** | **[中文版](#项目简介)**

---

# 中文版

## 项目简介

基于 PySide6 + FluentWidgets（WinUI3 风格）的 GUI 应用 + Arduino/ESP32 固件，用于低成本物理化学实验室数据采集（传感器：超声波、pH、HX711 力/电压、ACS712 电流）。采用**模块化架构**，新增传感器只需丢文件，无需修改主程序。

## 入口文件

- **Python 主程序**: `python main.py`（模块化架构，动态加载各传感器模块）
- **公共模块**: `core.py`（SerialThread / BLESerialThread / 配置管理 / 通用对话框 / 现代化样式）
- **串口诊断工具**: `python test_serial.py`
- **历史存档**: `main_legacy.py`（迁移前单文件版本，5000 行，**不再维护**，仅供对照参考）

## 安装依赖

```bash
pip install PySide6>=6.4.0 numpy>=1.21.0
# 串口通信（连接真实下位机需要；未安装时串口功能优雅降级，可用模拟器模式）
pip install pyserial>=3.5
# 绘图引擎（matplotlib / pyqtgraph 至少安装其一，推荐都装）
pip install matplotlib>=3.5.0 pyqtgraph>=0.13.0
# WinUI3 风格组件库（必需，主窗口基于 FluentWindow）
pip install PySide6-Fluent-Widgets
# 可选（BLE 无线通信）:
pip install bleak
```

本项目没有 `requirements.txt`、`setup.py` 或 `pyproject.toml`。

## 运行与调试

- 串口波特率：**115200**（所有固件和 Python 代码中硬编码）
- 固件输出格式：`timestamp,value`（CSV），Python 直接解析
- `sensor_config.json` 存储校准参数（运行时自动创建/更新）
- 双绘图引擎：matplotlib（默认）/ pyqtgraph，应用配置项 `app_cfg.chartEngine` 持久化，设置页可运行时热切换；matplotlib 字体（微软雅黑）在 `core.py` 中全局设置
- 引擎缺失时优雅降级：未安装的引擎选项在设置页灰显不可选；配置的引擎被卸载时自动降级到另一可用引擎；两个都缺时 `ChartPanel` 显示"未检测到图表引擎"占位提示，绘图 API 变为空操作，其余功能不受影响
- pyserial 缺失时优雅降级：`core.SERIAL_AVAILABLE` 检测可用性；`core.list_serial_ports()` 统一枚举（未装返回空列表）；未装时各模块自动切"模拟器"模式、串口下拉框显示占位、连接弹安装指引（`core.serial_unavailable_hint()`）
- 启动控制台会打印可选依赖状态：pyserial / bleak 缺失提示与图表引擎安装状态（含双引擎均缺失的幽默提示）
- 沙箱无显示环境运行验证：`QT_QPA_PLATFORM=offscreen python main.py`

## 目录结构

```
PhysChem-DigitizerP/
├── main.py                     ← 主程序：FluentWindow + 主页 + 动态加载器
├── core.py                     ← 公共模块：通信线程 / 配置 / 对话框 / 样式
├── main_legacy.py              ← 历史存档（单文件版，不再维护）
├── test_serial.py              ← 串口诊断工具
├── sensor_config.json          ← 本地校准数据（.gitignore，运行时生成）
└── 传感器代码/                  ← 下位机 .ino + 上位机 .py 同目录
    ├── 超声波位移传感器/
    │   ├── HC-SR04esp32.ino
    │   ├── HC-SR04esp8266.ino
    │   ├── csbwithbt.ino
    │   ├── ultrasonic_displacement.py   ← 模块文件（带识别区）
    │   └── ultrasonic_velocity.py
    ├── ph传感器/
    │   ├── ph esp32.ino
    │   └── ph_sensor.py
    ├── 力传感器/
    │   ├── force.ino
    │   └── force_sensor.py
    ├── 电压传感器/
    │   ├── ESP32_Voltage_Sensor.ino
    │   ├── HX711_Voltage.ino
    │   └── voltage_sensor.py
    └── 电流传感器/
        ├── ESP32_ADC_Raw_Data.ino
        └── current_sensor.py      ← ACS712 电流（5A/20A/30A 量程，AC/DC）
    └── 电学综合/
        ├── VI_ESP32_ADC.ino       ← 电压(内置ADC)+电流(ACS712) 一体固件
        ├── VI_ADS1115.ino         ← 电压(ADS1115 16位)+电流 一体固件
        ├── VI_HX711.ino           ← 电压(HX711 24位)+电流 一体固件
        ├── ohm_sensor.py          ← 欧姆定律模块（R=U/I，识别区 icon: R）
        ├── power_sensor.py        ← 电功率模块（P=UI，识别区 icon: P）
        └── README.md
```

## Arduino 固件

位于 `传感器代码/` 目录下（中文目录名）。每个子文件夹包含 `.ino` 文件和上位机 `.py` 模块。

| 传感器 | 开发板 | 固件路径 | 上位机模块 |
|--------|--------|----------|-----------|
| HC-SR04 超声波 | ESP32 | `传感器代码/超声波位移传感器/HC-SR04esp32.ino` | `ultrasonic_displacement.py` |
| HC-SR04 超声波 | ESP8266 | `传感器代码/超声波位移传感器/HC-SR04esp8266.ino` | `ultrasonic_displacement.py` |
| HC-SR04 + BLE | ESP32-S3 | `传感器代码/超声波位移传感器/csbwithbt.ino` | `ultrasonic_displacement.py` |
| 超声波速度 | — | （共享上述固件） | `ultrasonic_velocity.py` |
| pH (SEN0161) | ESP32-S3 | `传感器代码/ph传感器/ph esp32.ino` | `ph_sensor.py` |
| HX711 力传感器 | ESP32-S3 | `传感器代码/力传感器/force.ino` | `force_sensor.py` |
| 电压采集 | ESP32-S3 | `传感器代码/电压传感器/ESP32_Voltage_Sensor.ino` | `voltage_sensor.py` |
| HX711 电压采集 | ESP32-S3 | `传感器代码/电压传感器/HX711_Voltage.ino` | `voltage_sensor.py`（含 HX711 模式） |
| 电流 (ACS712) | ESP32-S3 | `传感器代码/电流传感器/ESP32_ADC_Raw_Data.ino` | `current_sensor.py`（5A/20A/30A 量程，AC/DC，零点校准） |
| 欧姆定律 (R=U/I) | ESP32-S3 | `传感器代码/电学综合/VI_*.ino`（内置ADC/ADS1115/HX711 三选一，电压+ACS712 电流一体；双板分测用同目录 `V_*.ino`+`I_ACS712.ino` 单通道副本） | `ohm_sensor.py`（电压/电流两个独立连接板块：模拟器·串口任意混搭，一体固件 VI_* 或双板；I-U 曲线线性拟合斜率倒数=电阻） |
| 电功率 (P=UI) | ESP32-S3 | `传感器代码/电学综合/VI_*.ino`（同上） | `power_sensor.py`（P=UI，梯形积分累计电能 W） |

通过 Arduino IDE 烧录。开发板管理器地址：
- ESP8266: `http://arduino.esp8266.com/stable/package_esp8266com_index.json`
- ESP32: `https://dl.espressif.com/dl/package_esp32_index.json`
- ESP32 国内镜像: `https://jihulab.com/esp-mirror/espressif/arduino-esp32/-/raw/gh-pages/package_esp32_index_cn.json`

## 架构说明

### 整体架构（FluentWindow 主体）

- **主窗口 `MainWindow`** 继承 `FluentWindow`（来自 `PySide6-Fluent-Widgets`），自动获得 WinUI3 风格的左侧 `NavigationInterface` + 内容栈 `stackedWidget`。各传感器 widget 通过 `addSubInterface(widget, icon, name)` 注册到导航。
- **模块化加载**：`main.py` 启动时扫描 `传感器代码/` 目录，用 `importlib` 动态加载各模块（`scan_modules` / `parse_module_meta`）。
- **导航注册顺序**：主页（`FIF.HOME`，顶部）→ 各传感器模块（文字图标，中部）→ 设置（`FIF.SETTING`，底部 `NavigationItemPosition.BOTTOM`）。

### main.py 组成

- **`make_text_icon(text, size=128)`**：把识别区里的文字（如 `V`/`F`/`x`/`pH`/`v`/`A`）画成方形 `QIcon`。FluentIcon 枚举没有对应"电压/电流/pH/力/超声波"的图标，所以直接用文字渲染成图标，保留模块化设计。字号用 `QFontMetrics` 自适应测量（从 `size*0.9` 起步缩到刚好填满画布，留 8% 边距），支持 Normal/Active/Selected 三种状态颜色。
- **`HomePageWidget`**：主页。上半部分为项目信息卡 + 三平台仓库地址卡（`ExpandGroupSettingCard`）；下半部分为**传感器模块磁贴网格**——每个模块一张 `ModuleFolderTile`（`CardWidget` 子类）：模块文字图标（识别区 `V`/`F`/`x`/`pH`/`v`/`A`，`make_text_icon()` 渲染，随主题变色的 `refresh_icon()`）+ 模块名 + 右上角图钉（`PillToolButton` + `FIF.PIN`，置顶开关）。网格用 `AdaptiveFlowLayout`（`setWidgetMinimumWidth(160)` 自动算列数、随窗口换行铺满）。置顶模块排在本组最前，状态持久化到 `app_config.json` 的 `General.PinnedModules`（`core.StringListSerializer` 序列化为 JSON 数组）；点击磁贴 → `module_clicked` 信号 → 切换模块。标题用 FluentWidgets `TitleLabel` / `SubtitleLabel`，自动适配亮/暗主题；`apply_theme()` 刷新页面/滚动区背景 + 重绘各磁贴文字图标（磁贴本体为 FluentWidgets 原生组件，主题自动适配，无需重建）。
- **`SettingsWidget`**：设置页，基于 FluentWidgets `SettingCardGroup` + `SettingCard` 系列组件实现，包含多组设置：①个性化（应用主题切换：亮色 / 暗色 / 跟随系统；**保存配置开关**：关闭后不读写 sensor_config.json；**清除用户设置**：确认后调用 `core.clear_sensor_config()` 删除 sensor_config.json 并把保存开关置为开；**图表引擎切换**：matplotlib / pyqtgraph，未安装的引擎选项通过 `ComboBox.setItemEnabled` 灰显不可点击并在文案中标注"未安装"）②关于（应用名 / 版本 / 许可证）③源码 & 反馈（GitHub / Gitee / Issue 链接）。主题切换通过 `theme_change_requested` 信号、引擎切换通过 `engine_change_requested` 信号分别与 `MainWindow.change_app_theme` / `MainWindow.change_chart_engine` 打通。
- **`MainWindow(FluentWindow)`**：主窗口 + 动态加载器，负责模块发现、实例化、注册到导航、主题切换、绘图引擎切换。`change_app_theme(theme)` 流程：先 `setTheme()` 切换 FluentWidgets 主题（自动刷新所有 FluentWidgets 子组件），再依次调用设置页 / 主页 / 各传感器模块的 `apply_theme()` 刷新自定义 widget 的硬编码颜色。`change_chart_engine(engine)` 流程：先用 `chart_engine_available()` 拦截未安装引擎的请求，再遍历各传感器模块 `findChildren(ChartPanel)`，调用 `panel.set_engine(engine)` 重建引擎控件并重放最近一次绘制事务，曲线无缝衔接不丢数据。
- **遗留代码**：`NavButton` / `SidebarWidget` 是迁移到 FluentWindow 前的手写侧边栏实现，**已不再被 `MainWindow` 使用**（FluentWindow 自带导航），仍保留在 `main.py` 中供对照参考，新功能不要基于它们开发。

### core.py 组成

集中存放共享代码——`SerialThread`、`BLESerialThread`、`scan_ble_devices`、`load/save_sensor_config`、`CalibrationDialog`、`SampleRateDialog`、现代化样式函数（`card_style`/`primary_btn_style`/`accent_btn_style`/`modern_combo_style`/`modern_combo_style_dark`）。

**主题基础设施**（亮/暗主题全链路支持）：
- `_theme_colors()`：按 `isDarkTheme()` 返回当前主题对应的语义颜色字典（`page_bg`/`card_bg`/`content_bg`/`text_primary`/`accent` 等）。
- `page_bg_style()` / `scroll_area_style()`：页面与滚动区背景样式，适配当前主题。
- `card_style()` / `primary_btn_style()` / `accent_btn_style()`：卡片与按钮样式，按 `isDarkTheme()` 切换颜色。`card_style()` 的背景用 `content_bg`（内容区灰色，亮色 `#f6f6f6` / 暗色 `#3d3d3d`），使卡片内容区比头部（`card_bg`）更深/更浅，形成「白标题 + 灰内容区」分层，与 FluentCard 视觉统一。
- `apply_module_theme(widget, theme=None)`：通用主题刷新助手，递归刷新模块 widget 内的 QScrollArea / `QWidget#card` / `CollapsibleCard` / QLabel / QLineEdit / QFrame 样式表，并通过缓存 `_orig_qss` dynamic property 实现亮↔暗双向切换（避免反复替换导致"切回亮色后仍是浅色字"）。各传感器模块的 `apply_theme()` 应委托本函数。**注意**：`FluentCard`（原生卡）会被本函数跳过——它自带 Fluent 主题样式，套用自定义 QSS 反而会破坏原生背景。
- `CollapsibleCard`：自绘可折叠卡片（圆角 + 边框 + 可点击 header），标题用 `SubtitleLabel`（暗色下白色、亮色下黑色），头部背景 `card_bg`、内容区背景 `content_bg`（由 `card_style()` 提供，形成「白标题 + 灰内容区」分层），`paintEvent` / `_apply_theme_style` 主题感知；`apply_theme(theme)` 刷新箭头、全屏按钮颜色。**仅图表卡片仍在用**（需要全屏 + 浮动面板能力）。
- `FluentCard`：基于 FluentWidgets 原生 `ExpandGroupSettingCard` 的紧凑卡片适配层，用于模块内**普通卡片**（连接控制/参数/实时数据/操作按钮等）。自带 WinUI3 原生视觉：主题自适应背景与分隔线、带旋转动画的展开箭头。API：`FluentCard(title, content_widget=None, expanded=True)` 兼容旧 `CollapsibleCard(title, content, expanded=...)` 调用；构造时自动剥离传入 content 的 `objectName='card'` + `card_style()`（避免双层边框）；也可用 `add_row(label, widget)` / `add_widget(w)` / `add_layout(l)` 从零填充；`add_header_widget(w)` 往 header 右侧追加按钮；`toggle()` / `is_expanded()` 控制折叠。内部重写了 `_adjustViewSize()`（按内容高度定高）并把 `wheelEvent` 透传给父级（解决嵌套外层 QScrollArea 的滚动冲突）。
- `FloatingDataPanel`：绘制背景主题感知。

**双绘图引擎 `ChartPanel`**（matplotlib / pyqtgraph 统一抽象）：
- 所有传感器模块的图表一律通过 `ChartPanel` 绘制，**不要直接使用** `Figure`/`FigureCanvas` 或 `pg.PlotWidget`。
- 事务式 API：`begin()` 开启一次绘制 → `plot(x, y, color, width, label, index)` 画曲线 → `hline(y, ...)` 画水平参考线 → `set_labels()` / `set_title()` / `set_xlim()` / `set_ylim()` / `legend()` 设置装饰 → `end()` 提交渲染。多子图用 `ChartPanel(n_plots=N)` + `index` 参数寻址。
- 引擎选择：构造时读 `app_cfg.chartEngine` 并经 `resolve_chart_engine()` 按可用性解析；`set_engine(engine)` 运行时重建底层控件并**重放最近一次提交的事务**（内部缓存 `_last`），切换引擎曲线不丢。
- 主题适配：`apply_chart_theme(dark)` 同时处理 matplotlib（figure/axes 背景与轴色）和 pyqtgraph（`setBackground` / 轴文本颜色），各模块 `apply_theme()` 中调用即可。
- **悬停交互（pyqtgraph）**：鼠标移动时自动定位最近数据点，显示垂直虚线指示线 + 跟随标签（横轴名/时间 + 各曲线数值，点靠近上沿时标签翻到下方防出界）。数据点定位对时间序列走二分（5 万点单次 < 0.1ms）。面板记录最近悬停位置（`_pg_hover_view`），`_commit_pg` 高频重绘后按记录位置在新数据上重新定位恢复——实时采集时鼠标不动标签也持续显示且数值跟随最新数据，不随重绘闪烁消失；主题切换按新配色重建，多子图场景下自动迁移，`clear_chart` 清除记录。
- **图例内部管理**：pyqtgraph 图例条目每次重绘前显式 `legend.clear()`（旧版 pyqtgraph 的 `pi.clear()` 不清图例，实时更新会无限累积）；参考线（InfiniteLine）**不得直接加入图例**——它没有 `opts` 属性，旧版 pyqtgraph 的 `ItemSample.paint` 会崩并拖垮整棵控件树的绘制链（图表异常、点击后界面空白）。图例样本用同款画笔的空 `PlotDataItem` 代替。

**引擎可用性与优雅降级**：
- `CHART_ENGINE_AVAILABLE`：导入 core 时用 `importlib` 探测一次的引擎可用性字典；`chart_engine_available(engine)` 为查询接口，`resolve_chart_engine(engine)` 把期望引擎解析为实际可用引擎（配置引擎被卸载时自动降级到另一个，都缺返回 `None`）。
- 占位模式（`_engine is None`）：`_build_placeholder_widget()` 显示"未检测到图表引擎"提示（含安装命令），绘制 API 变为空操作（事务仍记录到 `_last`），`clear_chart()` / `apply_chart_theme()` / `set_engine()` 全部安全。
- 设置页与 `MainWindow.change_chart_engine` 都以 `chart_engine_available()` 守卫，未安装引擎的切换请求会被拒绝。

### 模块能力要点

- `VoltageSensorWidget` 支持：HX711 24 位 ADC 模式（通道 A/B、增益 128/32）、kV/V/mV 单位切换、去皮（Tare）功能。
- `ForceSensorWidget` 支持：去皮（Tare）、两点校准、有线串口和 BLE 两种连接方式。
- `PhSensorWidget` 支持：单点 / 两点 / 三点校准（Nernst 斜率 / 线性拟合 / 二次多项式拟合）。
- `CurrentSensorWidget` 支持：ACS712 5A/20A/30A 量程切换、AC/DC 测量、零点校准。
- **主题支持**：所有传感器模块均实现 `apply_theme(theme)` 方法，委托 `core.apply_module_theme()` 刷新页面/卡片/QLabel 颜色，并调用 `ChartPanel.apply_chart_theme()` 切换图表背景/轴色（双引擎均生效）。页面标题统一使用 FluentWidgets `TitleLabel`，滚动区/页面背景使用 `scroll_area_style()` / `page_bg_style()`。
- 配置持久化：`load_sensor_config()` / `save_sensor_config()` 读写 `sensor_config.json`。
- 无自动化测试——`test_serial.py` 仅为手动诊断工具。
- 无 CI/CD、代码检查或类型检查配置。

## 添加新传感器模块

新增传感器**无需修改 `main.py`**，只需 2 步：

### 1. 建目录 + 丢文件

在 `传感器代码/` 下新建子目录，放入下位机 `.ino` 和上位机 `.py`：

```
传感器代码/
└── 温度传感器/                  ← 新建目录
    ├── ds18b20.ino              ← 下位机固件
    └── temperature_sensor.py    ← 上位机模块（带识别区）
```

### 2. 在 `.py` 文件头写识别区

```python
# === MODULE META ===
# icon: T
# name: 温度传感器
# category: physics          # physics 或 chemistry
# class: TemperatureSensorWidget
# ===================

# -*- coding: utf-8 -*-
"""温度传感器模块"""

from qfluentwidgets import PushButton, PrimaryPushButton, ComboBox, TextEdit, TitleLabel, isDarkTheme
from core import (
    SerialThread, load_sensor_config, save_sensor_config, ChartPanel,
    card_style, primary_btn_style, accent_btn_style, modern_combo_style,
    scroll_area_style, page_bg_style, apply_module_theme,
)

class TemperatureSensorWidget(QWidget):
    def __init__(self):
        ...
        # 图表：ChartPanel 双引擎抽象（matplotlib / pyqtgraph 由设置决定）
        self.chart = ChartPanel()

    def update_chart(self):
        """绘制曲线：事务式 API，两种引擎下行为一致"""
        c = self.chart
        c.begin()
        c.plot(self.time_data, self.temp_data, color='#0078d4', width=2, label='温度')
        c.set_labels('时间 (秒)', '温度 (°C)')
        c.legend()
        c.end()

    def apply_theme(self, theme):
        """主题切换：委托通用刷新助手 + 切换图表主题（双引擎均生效）"""
        apply_module_theme(self, theme)
        self.chart.apply_chart_theme(isDarkTheme())
```

重启 `main.py` 即自动出现在侧边栏（文字图标）+ 主页卡片 + 内容栈。

**主题支持要点**（新模块若想适配亮/暗主题）：
1. 页面标题用 `TitleLabel`（自动适配主题），不要用 `QLabel` + 硬编码颜色。
2. 滚动区用 `scroll.setStyleSheet(scroll_area_style())`，页面背景用 `content.setStyleSheet(page_bg_style())`。
3. 实现 `apply_theme(self, theme)` 方法，委托 `apply_module_theme(self, theme)` 刷新页面/卡片/QLabel 颜色，再调用 `self.chart.apply_chart_theme(...)` 切换图表背景（双引擎均生效）。

**UI 组件规约**（贴合 WinUI3 风格，2026-08 统一打磨）：
1. 一律使用 FluentWidgets 组件，**禁止**构造原生 `QLabel` / `QFrame` / `QGroupBox` / `QSpinBox` / `QDoubleSpinBox` / `QCheckBox`。
2. 标签语义化映射：静态表单标签（"连接方式:""串口:"等）用 `BodyLabel`；次要说明/统计信息（原硬编码 `#666/#888` 灰色小字）用 `CaptionLabel`（不设硬编码色，主题自适应）；实时大数值与状态强调保留 `setFont` + 强调色（主题切换由 `apply_module_theme` 自动 remap）。
3. 数字输入用 `SpinBox` / `DoubleSpinBox`（Fluent 样式，API 与 Qt 原生兼容）。
4. 模式开关用 `SwitchButton`（WinUI3 开关）替代复选框，信号为 `checkedChanged`（**不是** `toggled`）。
5. 卡片容器用 `FluentCard`（core 提供，基于原生 ExpandGroupSettingCard），可传已构建内容控件或 `add_row/add_widget` 填充；仅图表卡（需要全屏/浮动面板）用 `CollapsibleCard`。**不要**再拼接 `QWidget#card QLabel { color: ... }` 硬编码（FluentLabel 已随主题变色）。

**图表开发要点**（新模块必须遵守）：
1. 图表控件一律用 `core.ChartPanel`，**禁止**直接创建 matplotlib `Figure`/`FigureCanvas` 或 pyqtgraph `PlotWidget`——绕过抽象会导致设置页引擎切换对该模块失效。
2. 绘制走 `begin()` → `plot()`/`hline()`/`set_labels()`/... → `end()` 事务流程，切换引擎时 `ChartPanel` 会自动重放最近一次事务。
3. 多子图场景用 `ChartPanel(n_plots=N)`，各调用通过 `index` 参数指定子图。

### 识别区字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `icon` | 是 | 图标文字（如 `x`、`V`、`pH`），由 `make_text_icon()` 渲染成 `QIcon` 显示在侧边栏 |
| `name` | 是 | 模块显示名（如 `超声波位移`），用于侧边栏和主页卡片 |
| `category` | 是 | 模块类别：`physics`（物理）/ `chemistry`（化学），决定主页分组 |
| `class` | 是 | 模块的主类名（如 `UltrasonicWidget`），必须继承 `QWidget` |

## 注意事项

- `sensor_config.json` 在 `.gitignore` 中——它是用户本地校准数据
- `.ino` 文件名含空格（如 `ph esp32.ino`），某些系统可能出问题
- Arduino 代码目录使用中文命名
- `main_legacy.py` 是迁移前单文件存档，**不再维护**，新功能请改 `main.py` + 模块文件
- `NavButton` / `SidebarWidget` 是遗留代码，`MainWindow` 已改用 `FluentWindow` 自带导航，不要基于它们开发新功能
- 设置页已实现主题切换（亮色 / 暗色 / 跟随系统）、图表引擎切换（matplotlib / pyqtgraph，热切换，未安装的引擎灰显不可选）、关于信息、仓库链接（`SettingsWidget`）
- 图表引擎是**可选依赖**：matplotlib / pyqtgraph 至少安装其一；两个都缺时程序照常启动，图表区域显示"未检测到图表引擎"占位提示
- **pyserial 是可选依赖**：未安装时程序照常启动，各传感器模块自动切"模拟器"模式，串口连接弹安装指引；模块代码**禁止**直接 `import serial`，一律走 `core.list_serial_ports()` / `core.SERIAL_AVAILABLE` / `core.serial_unavailable_hint()`
- 新增传感器模块时建议实现 `apply_theme()` 方法以适配亮/暗主题（委托 `core.apply_module_theme()`）；图表一律用 `core.ChartPanel`，保证引擎热切换与占位降级对模块生效
- 模块文件名使用英文蛇形命名（如 `voltage_sensor.py`），与 PEP 8 一致
- BLE 功能需要 `bleak`（可选依赖），未安装时会自动降级
- 动态加载依赖识别区格式严格，字段名/冒号/空格写错会导致模块加载失败

---

# English Version {#english-version}

**[English](#english-version)** | **[中文版](#项目简介)**

## What is this

PySide6 + FluentWidgets (WinUI3 style) GUI application + Arduino/ESP32 firmware for low-cost physics/chemistry lab data acquisition (sensors: ultrasonic, pH, HX711 force/voltage, ACS712 current). Uses a **modular architecture** — adding a sensor requires only dropping a file, no changes to the main program.

## Entry points

- **Python app**: `python main.py` (modular architecture, dynamically loads sensor modules)
- **Core module**: `core.py` (SerialThread / BLESerialThread / config / dialogs / modern styles)
- **Serial diagnostics**: `python test_serial.py`
- **Legacy archive**: `main_legacy.py` (pre-refactor single-file version, 5000 lines, **no longer maintained**, kept for reference only)

## Install

```bash
pip install PySide6>=6.4.0 numpy>=1.21.0
# Serial communication (needed for real hardware; without it serial features degrade gracefully and the simulator still works)
pip install pyserial>=3.5
# Chart engines (install at least one of matplotlib / pyqtgraph; both recommended)
pip install matplotlib>=3.5.0 pyqtgraph>=0.13.0
# WinUI3 style component library (required, main window is based on FluentWindow)
pip install PySide6-Fluent-Widgets
# Optional (for BLE wireless):
pip install bleak
```

No `requirements.txt`, `setup.py`, or `pyproject.toml` exists.

## Run & debug

- Serial baud rate: **115200** (hardcoded across all firmware and Python)
- All firmware output CSV: `timestamp,value` — Python parses this directly
- `sensor_config.json` stores calibration params (auto-created/updated at runtime)
- Dual chart engines: matplotlib (default) / pyqtgraph, persisted via the `app_cfg.chartEngine` config item, hot-switchable at runtime from the settings page; matplotlib font (Microsoft YaHei) is set globally in `core.py`
- Graceful degradation when an engine is missing: unavailable engine options are grayed out (disabled) in the settings combo box; if the configured engine is uninstalled, the app falls back to the other available engine at startup; when both are missing, `ChartPanel` shows a "no chart engine detected" placeholder and drawing APIs become no-ops — all other features keep working
- Graceful degradation when pyserial is missing: `core.SERIAL_AVAILABLE` detects availability; `core.list_serial_ports()` is the single port-enumeration entry (returns an empty list when missing); without it every sensor module auto-switches to simulator mode, the port combo shows a placeholder, and connecting pops an install hint (`core.serial_unavailable_hint()`)
- The startup console prints optional-dependency status: pyserial / bleak missing hints and chart engine installation status (including a humorous line when both chart engines are missing)
- Headless sandbox verification: `QT_QPA_PLATFORM=offscreen python main.py`

## Directory structure

```
PhysChem-DigitizerP/
├── main.py                     ← Main: FluentWindow + home + dynamic loader
├── core.py                     ← Shared: comm threads / config / dialogs / styles
├── main_legacy.py              ← Legacy archive (single-file, unmaintained)
├── test_serial.py              ← Serial diagnostics
├── sensor_config.json          ← Local calibration (.gitignore, runtime-generated)
└── 传感器代码/                  ← Firmware .ino + host .py in same dir
    ├── 超声波位移传感器/
    │   ├── HC-SR04esp32.ino
    │   ├── HC-SR04esp8266.ino
    │   ├── csbwithbt.ino
    │   ├── ultrasonic_displacement.py   ← Module file (with meta header)
    │   └── ultrasonic_velocity.py
    ├── ph传感器/
    │   ├── ph esp32.ino
    │   └── ph_sensor.py
    ├── 力传感器/
    │   ├── force.ino
    │   └── force_sensor.py
    ├── 电压传感器/
    │   ├── ESP32_Voltage_Sensor.ino
    │   ├── HX711_Voltage.ino
    │   └── voltage_sensor.py
    └── 电流传感器/
        ├── ESP32_ADC_Raw_Data.ino
        └── current_sensor.py      ← ACS712 current (5A/20A/30A ranges, AC/DC)
```

## Arduino firmware

Located in `传感器代码/` (Chinese directory names). Each subfolder contains `.ino` files and a host `.py` module.

| Sensor | Board | Firmware path | Host module |
|--------|-------|---------------|-------------|
| HC-SR04 ultrasonic | ESP32 | `传感器代码/超声波位移传感器/HC-SR04esp32.ino` | `ultrasonic_displacement.py` |
| HC-SR04 ultrasonic | ESP8266 | `传感器代码/超声波位移传感器/HC-SR04esp8266.ino` | `ultrasonic_displacement.py` |
| HC-SR04 + BLE | ESP32-S3 | `传感器代码/超声波位移传感器/csbwithbt.ino` | `ultrasonic_displacement.py` |
| Ultrasonic velocity | — | (shares above firmware) | `ultrasonic_velocity.py` |
| pH (SEN0161) | ESP32-S3 | `传感器代码/ph传感器/ph esp32.ino` | `ph_sensor.py` |
| HX711 force | ESP32-S3 | `传感器代码/力传感器/force.ino` | `force_sensor.py` |
| Voltage ADC | ESP32-S3 | `传感器代码/电压传感器/ESP32_Voltage_Sensor.ino` | `voltage_sensor.py` |
| HX711 voltage | ESP32-S3 | `传感器代码/电压传感器/HX711_Voltage.ino` | `voltage_sensor.py` (HX711 mode) |
| Current (ACS712) | ESP32-S3 | `传感器代码/电流传感器/ESP32_ADC_Raw_Data.ino` | `current_sensor.py` (5A/20A/30A ranges, AC/DC, zero calibration) |
| Ohm's law (R=U/I) | ESP32-S3 | `传感器代码/电学综合/VI_*.ino` (built-in ADC / ADS1115 / HX711 + ACS712, one board; dual-board mode uses the `V_*.ino` + `I_ACS712.ino` single-channel copies in the same folder) | `ohm_sensor.py` (two independent connection panels for voltage & current — simulator/serial freely mixable, merged VI_* firmware or dual boards; linear fit of I-U curve gives 1/R) |
| Electric power (P=UI) | ESP32-S3 | `传感器代码/电学综合/VI_*.ino` (same as above) | `power_sensor.py` (P=UI, trapezoidal integration accumulates energy W) |

Flash via Arduino IDE. Board packages:
- ESP8266: `http://arduino.esp8266.com/stable/package_esp8266com_index.json`
- ESP32: `https://dl.espressif.com/dl/package_esp32_index.json`
- ESP32 CN mirror: `https://jihulab.com/esp-mirror/espressif/arduino-esp32/-/raw/gh-pages/package_esp32_index_cn.json`

## Architecture notes

### Overall architecture (FluentWindow main body)

- **Main window `MainWindow`** subclasses `FluentWindow` (from `PySide6-Fluent-Widgets`), automatically getting the WinUI3-style left `NavigationInterface` + content `stackedWidget`. Each sensor widget is registered to navigation via `addSubInterface(widget, icon, name)`.
- **Modular loading**: `main.py` scans `传感器代码/` at startup, dynamically loads modules via `importlib` (`scan_modules` / `parse_module_meta`).
- **Navigation order**: home (`FIF.HOME`, top) → sensor modules (text icons, middle) → settings (`FIF.SETTING`, bottom `NavigationItemPosition.BOTTOM`).

### main.py composition

- **`make_text_icon(text, size=128)`**: renders the meta-header text (e.g. `V`/`F`/`x`/`pH`/`v`/`A`) into a square `QIcon`. FluentIcon enum has no icons for "voltage/current/pH/force/ultrasonic", so text is rendered directly into an icon to preserve the modular design. Font size is auto-measured with `QFontMetrics` (starts at `size*0.9` and shrinks to just fill the canvas, leaving 8% margin), supporting Normal/Active/Selected state colors.
- **`HomePageWidget`**: home page. The upper half holds the project info card + 3-platform repo address card (`ExpandGroupSettingCard`); the lower half is the **sensor module tile grid** — one `ModuleFolderTile` (`CardWidget` subclass) per module: a module text icon (meta `V`/`F`/`x`/`pH`/`v`/`A`, rendered via `make_text_icon()` with a theme-reactive `refresh_icon()`) + module name + a pin button in the top-right (`PillToolButton` + `FIF.PIN`, pin-to-top toggle). The grid uses `AdaptiveFlowLayout` (`setWidgetMinimumWidth(160)` computes columns automatically and wraps to fill rows as the window resizes). Pinned modules sort first within their group; the state persists to `General.PinnedModules` in `app_config.json` (serialized as a JSON array by `core.StringListSerializer`); clicking a tile emits `module_clicked` → switches to that module. Titles use FluentWidgets `TitleLabel` / `SubtitleLabel` for automatic light/dark theme adaptation; `apply_theme()` refreshes the page/scroll background and redraws each tile's text icon (tiles themselves are native FluentWidgets components and adapt automatically — no rebuild needed).
- **`SettingsWidget`**: settings page built on FluentWidgets `SettingCardGroup` + `SettingCard` components. Groups: ① Personalization (app theme: light / dark / follow system; **config persistence switch**: when off, sensor_config.json is neither read nor written; **clear user settings**: after confirmation, calls `core.clear_sensor_config()` to delete sensor_config.json and turns the persistence switch back on; **chart engine: matplotlib / pyqtgraph** — unavailable engines are grayed out via `ComboBox.setItemEnabled` and labeled "未安装/not installed") ② About (app name / version / license) ③ Source & feedback (GitHub / Gitee / Issue links). Theme switching is wired to `MainWindow.change_app_theme` via `theme_change_requested`; engine switching is wired to `MainWindow.change_chart_engine` via `engine_change_requested`.
- **`MainWindow(FluentWindow)`**: main window + dynamic loader, responsible for module discovery, instantiation, navigation registration, theme switching, and chart engine switching. `change_app_theme(theme)` flow: first `setTheme()` to switch the FluentWidgets theme (auto-refreshes all FluentWidgets child components), then calls `apply_theme()` on the settings page / home page / each sensor module to refresh hardcoded widget colors. `change_chart_engine(engine)` flow: first rejects requests for uninstalled engines via `chart_engine_available()`, then iterates each sensor module via `findChildren(ChartPanel)` and calls `panel.set_engine(engine)` to rebuild the engine widget and replay the last committed draw transaction — curves carry over seamlessly without data loss.
- **Legacy code**: `NavButton` / `SidebarWidget` are the hand-written sidebar implementation from before the FluentWindow migration, **no longer used by `MainWindow`** (FluentWindow has its own navigation). They are still kept in `main.py` for reference — do not build new features on them.

### core.py composition

Centralized shared code — `SerialThread`, `BLESerialThread`, `scan_ble_devices`, `load/save_sensor_config`, `CalibrationDialog`, `SampleRateDialog`, modern style functions (`card_style`/`primary_btn_style`/`accent_btn_style`/`modern_combo_style`/`modern_combo_style_dark`).

**Theme infrastructure** (full light/dark theme support):
- `_theme_colors()`: returns a dict of semantic colors for the current theme based on `isDarkTheme()` (`page_bg`/`card_bg`/`text_primary`/`accent`, etc.).
- `page_bg_style()` / `scroll_area_style()`: page and scroll area background styles, theme-aware.
- `card_style()` / `primary_btn_style()` / `accent_btn_style()`: card and button styles that switch colors based on `isDarkTheme()`.
- `apply_module_theme(widget, theme=None)`: generic theme refresh helper that recursively refreshes QScrollArea / `QWidget#card` / `CollapsibleCard` / QLabel / QLineEdit / QFrame stylesheets within a module widget. Uses a cached `_orig_qss` dynamic property to enable bidirectional light↔dark switching (avoids "stuck light colors after switching back"). Sensor modules' `apply_theme()` should delegate to this. **Note**: `FluentCard` (the native card) is skipped — it ships its own Fluent theme styles, and applying custom QSS would break its native background.
- `CollapsibleCard`: hand-drawn collapsible card (rounded corners + border + clickable header), title uses `SubtitleLabel`; `paintEvent` / `_apply_theme_style` are theme-aware; `apply_theme(theme)` refreshes arrow and fullscreen button colors. **Only the chart card still uses it** (it needs fullscreen + floating-panel capability).
- `FluentCard`: a compact card adapter over the native `ExpandGroupSettingCard`, used for the modules' **regular cards** (connection control / parameters / live data / action buttons). Native WinUI3 look out of the box: theme-adaptive background & separator, rotating expand arrow with animation. API: `FluentCard(title, content_widget=None, expanded=True)` is drop-in compatible with the old `CollapsibleCard(title, content, expanded=...)` call; it automatically strips the passed content's `objectName='card'` + `card_style()` (avoids double borders); or fill from scratch with `add_row(label, widget)` / `add_widget(w)` / `add_layout(l)`; `add_header_widget(w)` appends a button to the header's right side; `toggle()` / `is_expanded()` control collapsing. It overrides `_adjustViewSize()` (sizes by content height) and forwards `wheelEvent` to the parent widget (fixes the scroll conflict when nested inside the module's outer QScrollArea).
- `FloatingDataPanel`: theme-aware background painting.

**Dual chart engine `ChartPanel`** (unified abstraction over matplotlib / pyqtgraph):
- All sensor module charts are drawn exclusively through `ChartPanel` — do **not** use `Figure`/`FigureCanvas` or `pg.PlotWidget` directly.
- Transactional API: `begin()` opens a draw → `plot(x, y, color, width, label, index)` draws curves → `hline(y, ...)` draws horizontal reference lines → `set_labels()` / `set_title()` / `set_xlim()` / `set_ylim()` / `legend()` add decorations → `end()` commits and renders. Multi-plot layouts use `ChartPanel(n_plots=N)` with the `index` parameter.
- Engine selection: reads `app_cfg.chartEngine` at construction and resolves it against availability via `resolve_chart_engine()`; `set_engine(engine)` rebuilds the underlying widget at runtime and **replays the last committed transaction** (cached in `_last`), so no curve data is lost on engine switch.
- Theme adaptation: `apply_chart_theme(dark)` handles both matplotlib (figure/axes background & axis colors) and pyqtgraph (`setBackground` / axis text colors); call it from each module's `apply_theme()`.
- **Hover interaction (pyqtgraph)**: on mouse move the panel locates the nearest data point and shows a dashed vertical guide line plus a following label (x-axis name/time + each curve's value; the label flips below the point near the top edge to stay in view). Nearest-point lookup uses binary search for time series (50k points in < 0.1ms per move). The panel records the last hover position (`_pg_hover_view`) and re-positions the hover items on the freshest data after every `_commit_pg` redraw — during live acquisition the label keeps showing with updated values even when the mouse is still, instead of flickering away on each redraw; hover items are restyled on theme change, migrate across sub-plots automatically, and the record is cleared by `clear_chart`.
- **Legend managed internally**: legend entries are explicitly `legend.clear()`-ed before every redraw (older pyqtgraph's `pi.clear()` does not clear the legend, so live updates would accumulate entries indefinitely); reference lines (`InfiniteLine`) must **never** be added to the legend directly — they lack the `opts` attribute, and older pyqtgraph's `ItemSample.paint` crashes on them, taking down the whole widget tree's paint chain (broken charts, blank UI after clicks). Legend samples use an empty `PlotDataItem` with the same pen instead.

**Engine availability & graceful degradation**:
- `CHART_ENGINE_AVAILABLE`: dict probed once via `importlib` at core import; `chart_engine_available(engine)` is the query API, `resolve_chart_engine(engine)` maps the desired engine to an actually available one (falls back to the other engine when the configured one is uninstalled; returns `None` when both are missing).
- Placeholder mode (`_engine is None`): `_build_placeholder_widget()` shows a "no chart engine detected" hint (with install commands); drawing APIs become no-ops (transactions are still recorded into `_last`); `clear_chart()` / `apply_chart_theme()` / `set_engine()` are all safe.
- Both the settings page and `MainWindow.change_chart_engine` guard with `chart_engine_available()` — switch requests for uninstalled engines are rejected.

### Module capability notes

- `VoltageSensorWidget` supports: HX711 24-bit ADC mode (channel A/B, gain 128/32), kV/V/mV unit switching, Tare function.
- `ForceSensorWidget` supports: Tare, two-point calibration, wired serial and BLE connections.
- `PhSensorWidget` supports: single-point / two-point / three-point calibration (Nernst slope / linear fit / quadratic polynomial fit).
- `CurrentSensorWidget` supports: ACS712 5A/20A/30A range switching, AC/DC measurement, zero calibration.
- **Theme support**: all sensor modules implement `apply_theme(theme)`, delegating to `core.apply_module_theme()` to refresh page/card/QLabel colors and calling `ChartPanel.apply_chart_theme()` to switch chart background/axis colors (works on both engines). Page titles uniformly use FluentWidgets `TitleLabel`; scroll area / page background use `scroll_area_style()` / `page_bg_style()`.
- Config persistence: `load_sensor_config()` / `save_sensor_config()` write to `sensor_config.json`.
- No automated tests — `test_serial.py` is a manual diagnostic tool.
- No CI/CD, linting, or type-checking configured.

## Adding a new sensor module

Adding a sensor requires **no changes to `main.py`** — just 2 steps:

### 1. Create directory + drop files

Create a subfolder under `传感器代码/`, drop in firmware `.ino` and host `.py`:

```
传感器代码/
└── temperature_sensor/         ← new folder
    ├── ds18b20.ino             ← firmware
    └── temperature_sensor.py   ← host module (with meta header)
```

### 2. Write meta header in the `.py` file

```python
# === MODULE META ===
# icon: T
# name: Temperature Sensor
# category: physics          # physics or chemistry
# class: TemperatureSensorWidget
# ===================

# -*- coding: utf-8 -*-
"""Temperature sensor module"""

from qfluentwidgets import PushButton, PrimaryPushButton, ComboBox, TextEdit, TitleLabel, isDarkTheme
from core import (
    SerialThread, load_sensor_config, save_sensor_config, ChartPanel,
    card_style, primary_btn_style, accent_btn_style, modern_combo_style,
    scroll_area_style, page_bg_style, apply_module_theme,
)

class TemperatureSensorWidget(QWidget):
    def __init__(self):
        ...
        # Chart: ChartPanel dual-engine abstraction (matplotlib / pyqtgraph, per settings)
        self.chart = ChartPanel()

    def update_chart(self):
        """Draw curves via the transactional API — identical behavior on both engines"""
        c = self.chart
        c.begin()
        c.plot(self.time_data, self.temp_data, color='#0078d4', width=2, label='Temperature')
        c.set_labels('Time (s)', 'Temperature (°C)')
        c.legend()
        c.end()

    def apply_theme(self, theme):
        """Theme switch: delegate to generic helper + switch chart theme (both engines)"""
        apply_module_theme(self, theme)
        self.chart.apply_chart_theme(isDarkTheme())
```

Restart `main.py` — the module auto-appears in sidebar (text icon) + home cards + content stack.

**Theme support tips** (for new modules to adapt to light/dark themes):
1. Use `TitleLabel` for the page title (auto-adapts to theme) — avoid `QLabel` with hardcoded colors.
2. Use `scroll.setStyleSheet(scroll_area_style())` for the scroll area and `content.setStyleSheet(page_bg_style())` for the page background.
3. Implement `apply_theme(self, theme)` that delegates to `apply_module_theme(self, theme)` to refresh page/card/QLabel colors, then call `self.chart.apply_chart_theme(...)` to switch the chart theme (works on both engines).

**UI component conventions** (WinUI3-style polish, standardized 2026-08):
1. Always use FluentWidgets components — **never** construct native `QLabel` / `QFrame` / `QGroupBox` / `QSpinBox` / `QDoubleSpinBox` / `QCheckBox`.
2. Semantic label mapping: static form labels (e.g. "连接方式:", "串口:") use `BodyLabel`; secondary hints/statistics (previously hardcoded `#666/#888` gray small text) use `CaptionLabel` (no hardcoded colors — theme-adaptive); large live values and emphasized status keep `setFont` + accent color (theme switching is auto-remapped by `apply_module_theme`).
3. Numeric input uses `SpinBox` / `DoubleSpinBox` (Fluent-styled, API-compatible with the Qt natives).
4. Mode toggles use `SwitchButton` (WinUI3 switch) instead of checkboxes; its signal is `checkedChanged` (not `toggled`).
5. Card containers use `FluentCard` (from core, based on the native ExpandGroupSettingCard) — pass a pre-built content widget or fill with `add_row`/`add_widget`; only the chart card (needing fullscreen/floating panel) uses `CollapsibleCard`. Do **not** append `QWidget#card QLabel { color: ... }` hardcodes — Fluent labels already adapt to the theme.

**Chart development rules** (mandatory for new modules):
1. Always use `core.ChartPanel` for charts — **never** create matplotlib `Figure`/`FigureCanvas` or pyqtgraph `PlotWidget` directly; bypassing the abstraction makes the settings-page engine switch ineffective for that module.
2. Draw via the `begin()` → `plot()`/`hline()`/`set_labels()`/... → `end()` transaction flow; on engine switch `ChartPanel` automatically replays the last transaction.
3. For multi-plot layouts use `ChartPanel(n_plots=N)` and target sub-plots via the `index` parameter.

### Meta header fields

| Field | Required | Description |
|-------|----------|-------------|
| `icon` | Yes | Icon text (e.g. `x`, `V`, `pH`), rendered into a `QIcon` by `make_text_icon()` and shown in the sidebar |
| `name` | Yes | Display name (e.g. `Ultrasonic`), for sidebar and home cards |
| `category` | Yes | Category: `physics` or `chemistry`, determines home grouping |
| `class` | Yes | Main class name (e.g. `UltrasonicWidget`), must subclass `QWidget` |

## Gotchas

- `sensor_config.json` is in `.gitignore` — it's user-local calibration data
- `.ino` filenames with spaces (e.g. `ph esp32.ino`) may cause issues on some systems
- Chinese directory/file names throughout the firmware folder
- `main_legacy.py` is the pre-refactor single-file archive, **no longer maintained** — edit `main.py` + module files for new features
- `NavButton` / `SidebarWidget` are legacy code; `MainWindow` now uses `FluentWindow`'s built-in navigation — do not build new features on them
- The settings page now implements theme switching (light / dark / follow system), chart engine switching (matplotlib / pyqtgraph, hot-switch; uninstalled engines grayed out and unselectable), about info, and repo links (`SettingsWidget`)
- Chart engines are **optional dependencies**: install at least one of matplotlib / pyqtgraph; when both are missing the app still starts and chart areas show a "no chart engine detected" placeholder
- **pyserial is an optional dependency**: without it the app still starts, every sensor module auto-switches to simulator mode, and serial connection pops an install hint; module code must **never** `import serial` directly — always go through `core.list_serial_ports()` / `core.SERIAL_AVAILABLE` / `core.serial_unavailable_hint()`
- When adding a new sensor module, implement `apply_theme()` to support light/dark themes (delegate to `core.apply_module_theme()`); always draw charts via `core.ChartPanel` so engine hot-switching and placeholder degradation work for the module
- Module filenames use English snake_case (e.g. `voltage_sensor.py`), per PEP 8
- BLE requires `bleak` (optional dependency) — graceful fallback if missing
- Dynamic loading depends on strict meta header format — typos in field names/colons/spaces will cause load failures
