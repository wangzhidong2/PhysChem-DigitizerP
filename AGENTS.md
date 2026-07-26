# 项目说明 / AGENTS.md

**[English](#english-version)** | **[中文版](#项目简介)**

---

# 中文版

## 项目简介

基于 PySide6 + QML + FluentPySide 的 GUI 应用 + Arduino/ESP32 固件，用于低成本物理化学实验室数据采集（传感器：超声波、pH、HX711 力传感器、电压、电流）。采用**模块化架构**，新增传感器只需丢文件，无需修改主程序。

## 入口文件

- **Python 主程序**: `python main.py`（QML 架构，扫描 `传感器代码/` 动态加载 Backend 类 + QML 视图）
- **公共包**: `core/`（`config.py` / `serial_thread.py` / `ble_thread.py`）
- **Backend 包**: `backends/`（`backend_base.py` 基类 + `chart_item.py` pyqtgraph 桥接）
- **QML 界面**: `qml/`（`Main.qml` 主窗口 + 各页面/组件 + `FluentTheme/` 主题色 token 单例 + `modules/` 各模块视图）
- **串口诊断工具**: `python test_serial.py`
- **历史存档**: `main_legacy.py`（迁移前 QtWidgets 单文件版本，**不再维护**，仅供对照参考）

## 安装依赖

```bash
pip install PySide6>=6.4.0 fluentpyside>=0.1.0 pyqtgraph>=0.13.0 pyserial>=3.5 numpy>=1.21.0
# 可选（BLE 无线通信）:
pip install bleak
```

本项目没有 `requirements.txt`、`setup.py` 或 `pyproject.toml`。

## 运行与调试

- 串口波特率：**115200**（所有固件和 Python 代码中硬编码）
- 固件输出格式：`timestamp,value`（CSV），Backend 直接解析
- `sensor_config.json` 存储校准参数（运行时自动创建/更新）
- 主题：FluentWinUI3（WinUI3 风格），自动跟随系统深浅色
- Linux 沙箱/无显示环境调试：`QT_QPA_PLATFORM=offscreen python main.py`

## 目录结构

```
PhysChem-DigitizerP/
├── main.py                     ← 主程序：QML 入口 + 模块扫描 + Backend 注册
├── core/                       ← 公共包：配置 / 串口 / BLE
│   ├── __init__.py             ←   统一导出
│   ├── config.py               ←   sensor_config.json 读写
│   ├── serial_thread.py        ←   SerialThread + list_serial_ports
│   └── ble_thread.py           ←   BLESerialThread + scan_ble_devices（bleak 可选）
├── backends/                   ← Backend 包：QML↔Python 桥接
│   ├── __init__.py
│   ├── backend_base.py         ←   BackendBase（QObject 基类，提供 Property/Slot）
│   └── chart_item.py           ←   ChartItem（QQuickPaintedItem，封装 pyqtgraph）
├── qml/                        ← QML 界面
│   ├── Main.qml                ←   主窗口：侧边栏 + StackLayout
│   ├── HomePage.qml            ←   主页：项目卡片 + 模块网格
│   ├── SettingsPage.qml        ←   设置页
│   ├── SidebarButton.qml       ←   侧边栏按钮组件
│   ├── ModuleCard.qml          ←   模块卡片组件
│   ├── SensorToolbar.qml       ←   通用串口工具栏
│   ├── ChartPanel.qml          ←   通用图表面板（含当前值/统计/日志）
│   ├── ActionBar.qml           ←   通用操作栏（开始/停止/保存/清除）
│   ├── ModuleView.qml          ←   通用模块视图模板
│   ├── FluentTheme/            ←   Fluent 主题色 token 单例（来源 fluentpyside, MIT）
│   │   ├── qmldir              ←     注册 singleton Fluent
│   │   └── Fluent.qml          ←     深浅色自适应主题色（accent/background/textPrimary...）
│   └── modules/                ←   各模块定制 QML
│       ├── ultrasonic_displacement.qml
│       ├── ultrasonic_velocity.qml
│       ├── ph_sensor.qml
│       ├── force_sensor.qml
│       ├── voltage_sensor.qml
│       └── current_sensor.qml
├── main_legacy.py              ← 历史存档（迁移前 QtWidgets 单文件版本，不再维护）
├── test_serial.py              ← 串口连接测试工具
├── sensor_config.json          ← 本地校准数据（.gitignore，运行时生成）
├── README.md
├── AGENTS.md                   ← 本文件
├── LICENSE                     ← GPL-3.0
└── 传感器代码/                  ← 下位机 .ino + 上位机 Backend .py 同目录
    ├── 超声波位移传感器/
    │   ├── HC-SR04esp32.ino
    │   ├── HC-SR04esp8266.ino
    │   ├── csbwithbt.ino
    │   ├── ultrasonic_displacement.py   ← Backend（带识别区）
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
```

## Arduino 固件

位于 `传感器代码/` 目录下（中文目录名）。每个子文件夹包含 `.ino` 文件和上位机 Backend `.py` 模块。

| 传感器 | 开发板 | 固件路径 | 上位机 Backend |
|--------|--------|----------|----------------|
| HC-SR04 超声波 | ESP32 | `传感器代码/超声波位移传感器/HC-SR04esp32.ino` | `ultrasonic_displacement.py` |
| HC-SR04 超声波 | ESP8266 | `传感器代码/超声波位移传感器/HC-SR04esp8266.ino` | `ultrasonic_displacement.py` |
| HC-SR04 + BLE | ESP32-S3 | `传感器代码/超声波位移传感器/csbwithbt.ino` | `ultrasonic_displacement.py` |
| 超声波速度 | — | （共享上述固件） | `ultrasonic_velocity.py` |
| pH (SEN0161) | ESP32-S3 | `传感器代码/ph传感器/ph esp32.ino` | `ph_sensor.py` |
| HX711 力传感器 | ESP32-S3 | `传感器代码/力传感器/force.ino` | `force_sensor.py` |
| 电压采集 | ESP32-S3 | `传感器代码/电压传感器/ESP32_Voltage_Sensor.ino` | `voltage_sensor.py` |
| HX711 电压采集 | ESP32-S3 | `传感器代码/电压传感器/HX711_Voltage.ino` | `voltage_sensor.py`（含 HX711 模式） |
| 电流 (ACS712) | ESP32-S3 | `传感器代码/电流传感器/ESP32_ADC_Raw_Data.ino` | `current_sensor.py`（5A/20A/30A，AC/DC，零点校准） |

通过 Arduino IDE 烧录。开发板管理器地址：
- ESP8266: `http://arduino.esp8266.com/stable/package_esp8266com_index.json`
- ESP32: `https://dl.espressif.com/dl/package_esp32_index.json`
- ESP32 国内镜像: `https://jihulab.com/esp-mirror/espressif/arduino-esp32/-/raw/gh-pages/package_esp32_index_cn.json`

## 架构说明

### 整体架构（QML + Backend + FluentPySide）

```
┌─────────────────────────────────────────────────────────────┐
│  main.py（Python）                                           │
│  ├─ QApplication + QQuickStyle.setStyle("FluentWinUI3")     │
│  ├─ fluentpyside.set_style(path, engine)  ← 应用样式         │
│  ├─ scan_modules() 扫描 传感器代码/ 加载 Backend 类           │
│  ├─ 实例化每个 Backend（BackendBase 子类，QObject）           │
│  ├─ 注册 ChartItem 到 QML（qmlRegisterType）                 │
│  └─ QQmlApplicationEngine.load(qml/Main.qml)                │
│        ↓ rootContext().setContextProperty(...)              │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  QML 层（qml/）                                              │
│  ├─ Main.qml：侧边栏 + StackLayout（HomePage/SettingsPage/  │
│  │            Loader 动态加载模块 QML）                      │
│  ├─ 通用组件：SensorToolbar / ChartPanel / ActionBar / ...  │
│  ├─ FluentTheme/Fluent.qml：主题色 token 单例                │
│  └─ modules/<id>.qml：各模块定制视图                        │
│        ↓ item.backend = backendsMap[key]                    │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  Backend 层（backends/）                                     │
│  ├─ BackendBase（QObject 基类）                              │
│  │   ├─ Property: ports / connected / collecting / ...      │
│  │   ├─ Slot: refreshPorts / connectPort / startCollecting  │
│  │   ├─ Signal: chartUpdated / statsUpdated / logAppended   │
│  │   └─ 通用：串口连接 / 数据采集 / CSV 保存 / 统计 / 日志   │
│  ├─ ChartItem（QQuickPaintedItem）                           │
│  │   └─ 封装 pyqtgraph.PlotWidget，setData/setLabels        │
│  └─ 各传感器 Backend 子类                                    │
│      └─ 重写 parse_line / build_csv_header / build_csv_row  │
└─────────────────────────────────────────────────────────────┘
```

### 关键点

- **模块化架构**：`main.py` 启动时扫描 `传感器代码/` 目录，用 `importlib` 动态加载各 Backend 类；QML 文件由 `Loader` 动态加载
- **core/**：集中存放共享代码——`config.py`（配置）、`serial_thread.py`（串口）、`ble_thread.py`（BLE）
- **backends/**：`BackendBase` 提供 `Property`/`Slot`/`Signal` 桥接 QML；`ChartItem` 用 `QQuickPaintedItem` 把 pyqtgraph 嵌入 QML
- **qml/Main.qml**：主页（`HomePage`）、侧边栏（`SidebarButton` + `Repeater`）、设置（`SettingsPage`）、主窗口（`ApplicationWindow`）+ `StackLayout` + `Loader`
- **qml/FluentTheme/**：本地注册的 `Fluent` 单例，暴露深浅色自适应主题色 token（详见下方 FluentPySide 集成章节）
- **配置持久化**：`load_sensor_config()` / `save_sensor_config()` 读写 `sensor_config.json`
- **无自动化测试**——`test_serial.py` 仅为手动诊断工具
- **无 CI/CD、代码检查或类型检查配置**（QMMLint 可手动调用，见下）

## FluentPySide 真实接入

本项目**真正接入** [FluentPySide](https://pypi.org/project/fluentpyside/) —— QtQuick.Controls FluentWinUI3 主题。包含两层：

### Python 端（`main.py` 的 `apply_fluent_style(engine)`）

1. **定位样式资源**（`_find_fluentwinui3_style()`）：
   - 优先 fluentpyside 包内副本（`fluentpyside/QtQuick/Controls/FluentWinUI3`）
   - 回退到 PySide6 官方 wheels 实际位置（`PySide6/Qt/qml/QtQuick/Controls/FluentWinUI3`）
   - 再回退到上游查找位置（`PySide6/qml/QtQuick/Controls/FluentWinUI3`）
2. **应用样式**：调用 `fluentpyside.set_style(path=..., engine=engine)`，它会：
   - 把 `QtQuick` 父目录加入 `QML2_IMPORT_PATH` 环境变量
   - 调用 `engine.addImportPath()` 让引擎找到样式
   - 调用 `QQuickStyle.setStyle("FluentWinUI3")` 按名称应用样式
3. **兜底**：即便 `set_style` 失败，也手动 `QQuickStyle.setStyle("FluentWinUI3")` 并设置 import path

> ⚠️ **为何不直接调 `fluentpyside.apply()`？**
> fluentpyside 0.2.1 的 `find_installed_style()` 只查找 `PySide6/qml/...`，
> 但官方 PySide6 wheels 实际把 QML 放在 `PySide6/Qt/qml/...`，
> 导致 `apply()` 静默失败、样式从未生效。本项目用自定义查找逻辑修复此问题。

### QML 端（`qml/FluentTheme/`）

由于 PySide6 官方 FluentWinUI3 样式的 qmldir 只注册了 `Config` 单例（内部样式参数），
未暴露用户可用的主题色 token，本项目从 fluentpyside 包（MIT 协议）复制 `Fluent.qml`
到 `qml/FluentTheme/`，并通过 qmldir 注册为本地单例模块：

```qml
// qml/FluentTheme/qmldir
module FluentTheme
singleton Fluent 1.0 Fluent.qml
singleton Fluent 6.0 Fluent.qml
```

`Fluent` 单例暴露以下属性（自动跟随 `Application.styleHints.colorScheme` 切换深浅色）：

| 类别 | 示例属性 |
|------|----------|
| 表面/背景 | `background` / `backgroundSecondary` / `cardBackground` / `layerAltBackground` |
| 文本 | `textPrimary` / `textSecondary` / `textTertiary` / `textOnAccent` |
| 强调色 | `accent` / `accentHover` / `accentPressed` / `accentSelected` |
| 控件 | `controlBackground` / `controlBackgroundHover` / `controlAltBackgroundHover` |
| 输入框 | `inputBackground` / `inputBorder` / `inputBorderFocus` |
| 边框/分割线 | `border` / `borderStrong` / `divider` |
| 状态色 | `success` / `caution` / `warning` / `critical` / `informational` |
| 排版 | `fontFamily` / `fontCaptionSize`(12) / `fontBodySize`(14) / `fontTitleSize`(28) |
| 间距 | `spacingXXS`(2) / `spacingXS`(4) / `spacingS`(8) / `spacingM`(12) / `spacingL`(16) |
| 圆角 | `radiusSmall`(4) / `radiusMedium`(8) / `radiusLarge`(12) / `radiusXLarge`(16) |
| 其他 | `isDark`（bool，当前是否深色模式） / `shadow` / `shadowAmbient` |

### 在 QML 中使用

```qml
import QtQuick
import QtQuick.Controls
import FluentTheme 1.0

Rectangle {
    color: Fluent.cardBackground
    radius: Fluent.radiusMedium

    Label {
        text: "标题"
        color: Fluent.textPrimary
        font.pixelSize: Fluent.fontTitleSize
        font.bold: true
    }

    Label {
        text: "副标题"
        color: Fluent.textSecondary
        font.pixelSize: Fluent.fontCaptionSize
    }

    Button {
        text: "强调按钮"
        highlighted: true  // 自动用 Fluent.accent 着色
    }
}
```

> **样式应用范围**：所有 `import QtQuick.Controls` 的控件（Button/ComboBox/TextField/...）
> 会自动获得 FluentWinUI3 外观，无需逐个定制。`Fluent` 单例仅用于自定义绘制
> （Rectangle 背景、Label 颜色等）需要主题色 token 时。

### 验证接入生效

启动 `main.py` 时控制台会输出：

```
✓ FluentWinUI3 样式已应用: <...>/PySide6/Qt/qml/QtQuick/Controls/FluentWinUI3
  QQuickStyle.name = FluentWinUI3
```

判定真实接入生效的 3 个标志：

1. **`QQuickStyle.name() == "FluentWinUI3"`** — QtQuick.Controls 全局样式确实切到 FluentWinUI3
2. **样式路径包含 `libqtquickcontrols2fluentwinui3styleplugin.so`** — 用的是 PySide6 自带的**真样式插件**（C++ 编译，不是 QSS 仿真）
3. **QML 中 `Fluent.accent` / `Fluent.background` 等可读** — 本地 `qml/FluentTheme/Fluent.qml` 单例注册成功

实测值（浅色模式下）：

| 属性 | 值 |
|------|-----|
| `Fluent.accent` | `#005fb8` |
| `Fluent.background` | `#f3f3f3` |
| `Fluent.cardBackground` | `#ffffff` |
| `Fluent.textPrimary` | `#1a1a1a` |
| `Fluent.isDark` | `false` |
| `Fluent.fontBodySize` | `14` |
| `Fluent.radiusMedium` | `8` |

> ⚠️ **常见坑**：`fluentpyside` 0.2.x 的 `find_installed_style()` 只查找 `PySide6/qml/...`，
> 但官方 PySide6 wheels 实际把 QML 放在 `PySide6/Qt/qml/...`，
> 直接调 `fluentpyside.apply()` 会静默失败、`QQuickStyle.name()` 仍是 `Fusion`。
> 本项目 `main.py:_find_fluentwinui3_style()` 通过覆盖查找逻辑修复此问题。

## 添加新传感器模块

新增传感器**无需修改 `main.py`**，只需 3 步：

### 1. 建目录 + 丢文件

在 `传感器代码/` 下新建子目录，放入下位机 `.ino` 和上位机 Backend `.py`：

```
传感器代码/
└── 温度传感器/                  ← 新建目录
    ├── ds18b20.ino              ← 下位机固件
    └── temperature_sensor.py    ← 上位机 Backend（继承 BackendBase）
```

### 2. 在 `.py` 文件头写识别区

```python
# === MODULE META ===
# icon: T
# name: 温度传感器
# category: physics          # physics 或 chemistry
# class: TemperatureBackend
# ===================

# -*- coding: utf-8 -*-
"""温度传感器 Backend"""

from backends import BackendBase

class TemperatureBackend(BackendBase):
    def __init__(self, parent=None):
        super().__init__('temperature_sensor', parent=parent)

    def parse_line(self, line: str):
        # 解析固件输出的 CSV 行：timestamp,value
        # 返回 (relative_time_s, value, display_text) 或 (None, None, None)
        ...

    def build_csv_header(self) -> str:
        return "# PhysChem-DigitizerP 温度数据\n# timestamp_s,temperature_c\ntimestamp_s,temperature_c\n"
```

### 3. 创建对应 QML 视图（可选）

在 `qml/modules/` 下创建 `<module_id>.qml`（缺失则使用通用 `ModuleView.qml`）：

```qml
// qml/modules/temperature_sensor.qml
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import FluentTheme 1.0
import Charts 1.0
import ".."

Item {
    id: root
    property var backend: null

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12

        Label {
            text: "温度传感器"
            font.pixelSize: Fluent.fontSubtitleSize; font.bold: true
            color: Fluent.textPrimary
        }

        SensorToolbar { Layout.fillWidth: true; backend: root.backend }

        ChartPanel {
            Layout.fillWidth: true; Layout.fillHeight: true
            backend: root.backend
            xLabel: "时间 (s)"; yLabel: "温度 (°C)"
        }

        ActionBar { Layout.fillWidth: true; backend: root.backend }
    }
}
```

重启 `main.py` 即自动出现在侧边栏 + 主页卡片 + 内容栈。

### 识别区字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `icon` | 是 | 模块图标文本（如 `T`、`V`、`pH`），显示在侧边栏和主页 |
| `name` | 是 | 模块显示名（如 `超声波位移`），用于侧边栏和主页卡片 |
| `category` | 是 | 模块类别：`physics`（物理）/ `chemistry`（化学），决定主页分组 |
| `class` | 是 | Backend 类名（如 `TemperatureBackend`），必须继承 `BackendBase` |
| `qml` | 否 | 自定义 QML 文件名（默认查找 `qml/modules/<module_id>.qml`） |

### BackendBase 关键接口

| 类型 | 名称 | 用途 |
|------|------|------|
| Property | `ports` | 可用串口列表（QML ComboBox 绑定） |
| Property | `connected` / `collecting` | 连接/采集状态 |
| Property | `sampleRateHz` / `currentValue` / `statsText` / `logText` | 实时数据 |
| Slot | `refreshPorts()` / `connectPort(port)` / `disconnectPort()` | 串口控制 |
| Slot | `startCollecting()` / `stopCollecting()` / `clearData()` | 采集控制 |
| Slot | `saveData(file_path)` | 保存 CSV |
| Slot | `timeData()` / `valueData()` | 返回数据列表（ChartPanel 调用） |
| Signal | `chartUpdated` / `statsUpdated` / `currentValueUpdated` / `logAppended` | 通知 QML 刷新 |
| 虚方法 | `parse_line(line)` | 子类必须重写，解析一行 CSV |
| 虚方法 | `build_csv_header()` / `build_csv_row()` | 子类可重写，自定义导出格式 |

## 静态检查

```bash
# QML 静态检查（qmllint 随 PySide6 附带）
QML_IMPORT_PATH=<PySide6>/Qt/qml:<repo>/qml:<repo>/qml/modules \
  <PySide6>/qmllint qml/*.qml qml/modules/*.qml
```

常见警告：
- `Unqualified access` — 在嵌套组件中访问父 id 属性未加 `root.` 前缀（建议加前缀）
- `Failed to import Charts` — `Charts` 模块由 `qmlRegisterType` 在 Python 端动态注册，qmllint 静态分析无法发现，运行时正常
- `Failed to import FluentTheme` — 需把 `<repo>/qml` 加入 `QML_IMPORT_PATH`

## 注意事项

- `sensor_config.json` 在 `.gitignore` 中——它是用户本地校准数据
- `.ino` 文件名含空格（如 `ph esp32.ino`），某些系统可能出问题
- Arduino 代码目录使用中文命名
- `main_legacy.py` 是迁移前 QtWidgets 单文件存档，**不再维护**，新功能请改 `main.py` + Backend + QML 文件
- 模块文件名使用英文蛇形命名（如 `voltage_sensor.py`），与 PEP 8 一致
- BLE 功能需要 `bleak`（可选依赖），未安装时会自动降级
- 动态加载依赖识别区格式严格，字段名/冒号/空格写错会导致模块加载失败
- `Fluent.qml` 来源 fluentpyside 包（MIT 协议），保留原始版权声明；本项目整体 GPL-3.0
- **QML 调试**：用 `QT_QPA_PLATFORM=offscreen python main.py` 可在无显示环境运行；用 `QT_LOGGING_RULES="qt.qml=true"` 可看 QML 详细日志

---

# English Version {#english-version}

**[English](#english-version)** | **[中文版](#项目简介)**

## What is this

PySide6 + QML + FluentPySide GUI application + Arduino/ESP32 firmware for low-cost physics/chemistry lab data acquisition (sensors: ultrasonic, pH, HX711 force, voltage, current). Uses a **modular architecture** — adding a sensor requires only dropping a file, no changes to the main program.

## Entry points

- **Python app**: `python main.py` (QML architecture, scans `传感器代码/` to dynamically load Backend classes + QML views)
- **Shared package**: `core/` (`config.py` / `serial_thread.py` / `ble_thread.py`)
- **Backend package**: `backends/` (`backend_base.py` base class + `chart_item.py` pyqtgraph bridge)
- **QML UI**: `qml/` (`Main.qml` main window + pages/components + `FluentTheme/` theme singleton + `modules/` per-module views)
- **Serial diagnostics**: `python test_serial.py`
- **Legacy archive**: `main_legacy.py` (pre-migration QtWidgets single-file version, **no longer maintained**)

## Install

```bash
pip install PySide6>=6.4.0 fluentpyside>=0.1.0 pyqtgraph>=0.13.0 pyserial>=3.5 numpy>=1.21.0
# Optional (for BLE wireless):
pip install bleak
```

No `requirements.txt`, `setup.py`, or `pyproject.toml` exists.

## Run & debug

- Serial baud rate: **115200** (hardcoded across all firmware and Python)
- All firmware output CSV: `timestamp,value` — Backend parses this directly
- `sensor_config.json` stores calibration params (auto-created/updated at runtime)
- Theme: FluentWinUI3 (WinUI3 style), auto-follows system light/dark
- Headless/sandbox debugging: `QT_QPA_PLATFORM=offscreen python main.py`

## Directory structure

```
PhysChem-DigitizerP/
├── main.py                     ← Main: QML entry + module scan + Backend registration
├── core/                       ← Shared package: config / serial / BLE
│   ├── __init__.py             ←   Unified exports
│   ├── config.py               ←   sensor_config.json read/write
│   ├── serial_thread.py        ←   SerialThread + list_serial_ports
│   └── ble_thread.py           ←   BLESerialThread + scan_ble_devices (bleak optional)
├── backends/                   ← Backend package: QML↔Python bridge
│   ├── __init__.py
│   ├── backend_base.py         ←   BackendBase (QObject base, provides Property/Slot)
│   └── chart_item.py           ←   ChartItem (QQuickPaintedItem, wraps pyqtgraph)
├── qml/                        ← QML UI
│   ├── Main.qml                ←   Main window: sidebar + StackLayout
│   ├── HomePage.qml            ←   Home: project card + module grids
│   ├── SettingsPage.qml        ←   Settings page
│   ├── SidebarButton.qml       ←   Sidebar button component
│   ├── ModuleCard.qml          ←   Module card component
│   ├── SensorToolbar.qml       ←   Common serial toolbar
│   ├── ChartPanel.qml          ←   Common chart panel (current value/stats/log)
│   ├── ActionBar.qml           ←   Common action bar (start/stop/save/clear)
│   ├── ModuleView.qml          ←   Generic module view template
│   ├── FluentTheme/            ←   Fluent theme color token singleton (from fluentpyside, MIT)
│   │   ├── qmldir              ←     Registers singleton Fluent
│   │   └── Fluent.qml          ←     Light/dark adaptive theme colors
│   └── modules/                ←   Per-module custom QML
│       └── ...
├── main_legacy.py              ← Legacy archive (single-file QtWidgets, unmaintained)
├── test_serial.py              ← Serial diagnostics
├── sensor_config.json          ← Local calibration (.gitignore, runtime-generated)
├── README.md
├── AGENTS.md                   ← This file
├── LICENSE                     ← GPL-3.0
└── 传感器代码/                  ← Firmware .ino + host Backend .py in same dir
```

## Arduino firmware

Located in `传感器代码/` (Chinese directory names). Each subfolder contains `.ino` files and a host Backend `.py` module.

| Sensor | Board | Firmware path | Host Backend |
|--------|-------|---------------|--------------|
| HC-SR04 ultrasonic | ESP32 | `传感器代码/超声波位移传感器/HC-SR04esp32.ino` | `ultrasonic_displacement.py` |
| HC-SR04 ultrasonic | ESP8266 | `传感器代码/超声波位移传感器/HC-SR04esp8266.ino` | `ultrasonic_displacement.py` |
| HC-SR04 + BLE | ESP32-S3 | `传感器代码/超声波位移传感器/csbwithbt.ino` | `ultrasonic_displacement.py` |
| Ultrasonic velocity | — | (shares above firmware) | `ultrasonic_velocity.py` |
| pH (SEN0161) | ESP32-S3 | `传感器代码/ph传感器/ph esp32.ino` | `ph_sensor.py` |
| HX711 force | ESP32-S3 | `传感器代码/力传感器/force.ino` | `force_sensor.py` |
| Voltage ADC | ESP32-S3 | `传感器代码/电压传感器/ESP32_Voltage_Sensor.ino` | `voltage_sensor.py` |
| HX711 voltage | ESP32-S3 | `传感器代码/电压传感器/HX711_Voltage.ino` | `voltage_sensor.py` (HX711 mode) |
| Current (ACS712) | ESP32-S3 | `传感器代码/电流传感器/ESP32_ADC_Raw_Data.ino` | `current_sensor.py` (5A/20A/30A, AC/DC, zero calibration) |

Flash via Arduino IDE. Board packages:
- ESP8266: `http://arduino.esp8266.com/stable/package_esp8266com_index.json`
- ESP32: `https://dl.espressif.com/dl/package_esp32_index.json`
- ESP32 CN mirror: `https://jihulab.com/esp-mirror/espressif/arduino-esp32/-/raw/gh-pages/package_esp32_index_cn.json`

## Architecture notes

- **Modular architecture**: `main.py` scans `传感器代码/` at startup, dynamically loads Backend classes via `importlib`; QML views loaded dynamically by `Loader`
- **core/**: shared code — `config.py` (config), `serial_thread.py` (serial), `ble_thread.py` (BLE)
- **backends/**: `BackendBase` provides `Property`/`Slot`/`Signal` bridging QML; `ChartItem` uses `QQuickPaintedItem` to embed pyqtgraph into QML
- **qml/Main.qml**: home (`HomePage`), sidebar (`SidebarButton` + `Repeater`), settings (`SettingsPage`), main window (`ApplicationWindow`) + `StackLayout` + `Loader`
- **qml/FluentTheme/**: locally registered `Fluent` singleton exposing light/dark adaptive theme color tokens (see FluentPySide Integration section)
- Config persistence: `load_sensor_config()` / `save_sensor_config()` write to `sensor_config.json`
- No automated tests — `test_serial.py` is a manual diagnostic tool
- No CI/CD, linting, or type-checking configured (qmllint can be invoked manually, see below)

## FluentPySide Integration

This project **truly integrates** [FluentPySide](https://pypi.org/project/fluentpyside/) — the QtQuick.Controls FluentWinUI3 theme. Two layers:

### Python side (`main.py`'s `apply_fluent_style(engine)`)

1. **Locate style assets** (`_find_fluentwinui3_style()`):
   - First tries fluentpyside package-local copy (`fluentpyside/QtQuick/Controls/FluentWinUI3`)
   - Falls back to PySide6 official wheels location (`PySide6/Qt/qml/QtQuick/Controls/FluentWinUI3`)
   - Then falls back to upstream lookup location (`PySide6/qml/QtQuick/Controls/FluentWinUI3`)
2. **Apply style**: calls `fluentpyside.set_style(path=..., engine=engine)`, which:
   - Adds the `QtQuick` parent directory to `QML2_IMPORT_PATH` env var
   - Calls `engine.addImportPath()` so the engine finds the style
   - Calls `QQuickStyle.setStyle("FluentWinUI3")` to apply the style by name
3. **Fallback**: even if `set_style` fails, manually calls `QQuickStyle.setStyle("FluentWinUI3")` and sets import path

> ⚠️ **Why not just call `fluentpyside.apply()`?**
> fluentpyside 0.2.1's `find_installed_style()` only looks at `PySide6/qml/...`,
> but official PySide6 wheels actually place QML at `PySide6/Qt/qml/...`,
> causing `apply()` to fail silently and the style to never take effect.
> This project fixes that with custom lookup logic.

### QML side (`qml/FluentTheme/`)

Because PySide6's official FluentWinUI3 qmldir only registers a `Config` singleton (internal style params),
without user-facing theme color tokens, this project copies `Fluent.qml` from the fluentpyside package (MIT)
into `qml/FluentTheme/` and registers it as a local singleton module via qmldir:

```qml
// qml/FluentTheme/qmldir
module FluentTheme
singleton Fluent 1.0 Fluent.qml
singleton Fluent 6.0 Fluent.qml
```

The `Fluent` singleton exposes (auto-switches light/dark via `Application.styleHints.colorScheme`):

| Category | Example properties |
|----------|-------------------|
| Surface | `background` / `backgroundSecondary` / `cardBackground` / `layerAltBackground` |
| Text | `textPrimary` / `textSecondary` / `textTertiary` / `textOnAccent` |
| Accent | `accent` / `accentHover` / `accentPressed` / `accentSelected` |
| Control | `controlBackground` / `controlBackgroundHover` / `controlAltBackgroundHover` |
| Input | `inputBackground` / `inputBorder` / `inputBorderFocus` |
| Border/Divider | `border` / `borderStrong` / `divider` |
| Status | `success` / `caution` / `warning` / `critical` / `informational` |
| Typography | `fontFamily` / `fontCaptionSize`(12) / `fontBodySize`(14) / `fontTitleSize`(28) |
| Spacing | `spacingXXS`(2) / `spacingXS`(4) / `spacingS`(8) / `spacingM`(12) / `spacingL`(16) |
| Radius | `radiusSmall`(4) / `radiusMedium`(8) / `radiusLarge`(12) / `radiusXLarge`(16) |
| Other | `isDark` (bool, current dark mode) / `shadow` / `shadowAmbient` |

### Usage in QML

```qml
import QtQuick
import QtQuick.Controls
import FluentTheme 1.0

Rectangle {
    color: Fluent.cardBackground
    radius: Fluent.radiusMedium

    Label {
        text: "Title"
        color: Fluent.textPrimary
        font.pixelSize: Fluent.fontTitleSize
        font.bold: true
    }
}
```

> **Scope of style application**: all `import QtQuick.Controls` widgets (Button/ComboBox/TextField/...)
> automatically get FluentWinUI3 appearance. The `Fluent` singleton is only for custom drawing
> (Rectangle backgrounds, Label colors, etc.) that need theme color tokens.

## Adding a new sensor module

Adding a sensor requires **no changes to `main.py`** — just 3 steps:

### 1. Create directory + drop files

Create a subfolder under `传感器代码/`, drop in firmware `.ino` and host Backend `.py`:

```
传感器代码/
└── temperature_sensor/         ← new folder
    ├── ds18b20.ino             ← firmware
    └── temperature_sensor.py   ← host Backend (subclasses BackendBase)
```

### 2. Write meta header in the `.py` file

```python
# === MODULE META ===
# icon: T
# name: Temperature Sensor
# category: physics          # physics or chemistry
# class: TemperatureBackend
# ===================

# -*- coding: utf-8 -*-
"""Temperature sensor Backend"""

from backends import BackendBase

class TemperatureBackend(BackendBase):
    def __init__(self, parent=None):
        super().__init__('temperature_sensor', parent=parent)

    def parse_line(self, line: str):
        # Parse CSV line from firmware: timestamp,value
        # Returns (relative_time_s, value, display_text) or (None, None, None)
        ...

    def build_csv_header(self) -> str:
        return "# PhysChem-DigitizerP temperature data\n# timestamp_s,temperature_c\ntimestamp_s,temperature_c\n"
```

### 3. Create matching QML view (optional)

Create `qml/modules/<module_id>.qml` (falls back to generic `ModuleView.qml` if missing):

```qml
// qml/modules/temperature_sensor.qml
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import FluentTheme 1.0
import Charts 1.0
import ".."

Item {
    id: root
    property var backend: null

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12

        Label {
            text: "Temperature Sensor"
            font.pixelSize: Fluent.fontSubtitleSize; font.bold: true
            color: Fluent.textPrimary
        }

        SensorToolbar { Layout.fillWidth: true; backend: root.backend }

        ChartPanel {
            Layout.fillWidth: true; Layout.fillHeight: true
            backend: root.backend
            xLabel: "Time (s)"; yLabel: "Temperature (°C)"
        }

        ActionBar { Layout.fillWidth: true; backend: root.backend }
    }
}
```

Restart `main.py` — the module auto-appears in sidebar + home cards + content stack.

### Meta header fields

| Field | Required | Description |
|-------|----------|-------------|
| `icon` | Yes | Icon text (e.g. `T`, `V`, `pH`), shown in sidebar and home |
| `name` | Yes | Display name (e.g. `Ultrasonic`), for sidebar and home cards |
| `category` | Yes | Category: `physics` or `chemistry`, determines home grouping |
| `class` | Yes | Backend class name (e.g. `TemperatureBackend`), must subclass `BackendBase` |
| `qml` | No | Custom QML filename (default: `qml/modules/<module_id>.qml`) |

### BackendBase key interface

| Type | Name | Purpose |
|------|------|---------|
| Property | `ports` | Available serial ports (QML ComboBox binding) |
| Property | `connected` / `collecting` | Connection/acquisition state |
| Property | `sampleRateHz` / `currentValue` / `statsText` / `logText` | Real-time data |
| Slot | `refreshPorts()` / `connectPort(port)` / `disconnectPort()` | Serial control |
| Slot | `startCollecting()` / `stopCollecting()` / `clearData()` | Acquisition control |
| Slot | `saveData(file_path)` | Save CSV |
| Slot | `timeData()` / `valueData()` | Return data lists (called by ChartPanel) |
| Signal | `chartUpdated` / `statsUpdated` / `currentValueUpdated` / `logAppended` | Notify QML to refresh |
| Virtual | `parse_line(line)` | Subclass MUST override, parses one CSV line |
| Virtual | `build_csv_header()` / `build_csv_row()` | Subclass can override for custom export format |

## Static checks

```bash
# QML static analysis (qmllint ships with PySide6)
QML_IMPORT_PATH=<PySide6>/Qt/qml:<repo>/qml:<repo>/qml/modules \
  <PySide6>/qmllint qml/*.qml qml/modules/*.qml
```

Common warnings:
- `Unqualified access` — accessing parent id properties inside nested components without `root.` prefix (recommend adding prefix)
- `Failed to import Charts` — `Charts` module is dynamically registered via `qmlRegisterType` in Python, qmllint can't find it statically; works at runtime
- `Failed to import FluentTheme` — add `<repo>/qml` to `QML_IMPORT_PATH`

## Gotchas

- `sensor_config.json` is in `.gitignore` — it's user-local calibration data
- `.ino` filenames with spaces (e.g. `ph esp32.ino`) may cause issues on some systems
- Chinese directory/file names throughout the firmware folder
- `main_legacy.py` is the pre-migration QtWidgets single-file archive, **no longer maintained** — edit `main.py` + Backend + QML files for new features
- Module filenames use English snake_case (e.g. `voltage_sensor.py`), per PEP 8
- BLE requires `bleak` (optional dependency) — graceful fallback if missing
- Dynamic loading depends on strict meta header format — typos in field names/colons/spaces will cause load failures
- `Fluent.qml` is from fluentpyside package (MIT license), original copyright notice preserved; whole project is GPL-3.0
- **QML debugging**: use `QT_QPA_PLATFORM=offscreen python main.py` to run headless; use `QT_LOGGING_RULES="qt.qml=true"` for detailed QML logs
