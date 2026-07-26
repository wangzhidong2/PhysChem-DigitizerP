# PhysChem-DigitizerP

基于 Arduino/ESP32/ESP8266 开发的低成本理化实验数字化采集系统

[![License: GPL v3](https://img.shields.io/badge/License-GPL_v3-blue.svg)](LICENSE)
[![GitHub](https://img.shields.io/badge/GitHub-Repository-blue?logo=github)](https://github.com/wangzhidong2/PhysChem-DigitizerP)
[![Gitee](https://img.shields.io/badge/Gitee-Repository-red?logo=gitee)](https://gitee.com/wangzhidong2/PhysChem-DigitizerP/)
[![GitCode](https://img.shields.io/badge/GitCode-Repository-orange?logo=gitcode)](https://gitcode.com/wangzhidong2/PhysChem-DigitizerP)

## 📖 项目简介

**PhysChem-DigitizerP** 是一个开源的物理化学实验数字化采集系统，旨在为中学物理/化学实验室提供低成本的传感器解决方案。项目包含硬件（ESP32/ESP8266/Arduino）和软件（Python + QML + FluentPySide）两部分，实现了从传感器数据采集、实时可视化到数据导出的完整功能。

- **低成本替代**：单传感器成本 < ¥30（商业方案通常 > ¥500）
- **开源透明**：GPL-3.0 协议，硬件设计和软件代码完全开源
- **模块化设计**：新增传感器只需丢文件，无需修改主程序
- **WinUI3 风格界面**：基于 [FluentPySide](https://pypi.org/project/fluentpyside/) 实现的 QtQuick Controls FluentWinUI3 主题
- **高性能绘图**：使用 [pyqtgraph](https://pyqtgraph.org/) 替代 matplotlib，渲染性能大幅提升

<p align="center">
  <img src="docs/images/home.png" alt="主界面" width="800"/>
</p>
<p align="center">软件主界面 — 模块导航与项目概览</p>

## 📦 核心依赖库

| 库 | 版本 | 用途 |
|----|------|------|
| **PySide6** | ≥6.4.0 | Qt for Python（QML 引擎 + QtWidgets 兼容层） |
| **fluentpyside** | ≥0.1.0 | QtQuick.Controls FluentWinUI3 主题资源 |
| **pyqtgraph** | ≥0.13.0 | 实时数据可视化（高性能替代 matplotlib） |
| **pyserial** | ≥3.5 | 串口通信 |
| **numpy** | ≥1.21.0 | 数值计算（pH 校准拟合） |
| **bleak** | （可选） | BLE 无线通信 |

```bash
pip install PySide6>=6.4.0 fluentpyside>=0.1.0 pyqtgraph>=0.13.0 pyserial>=3.5 numpy>=1.21.0
# 可选（BLE 无线通信）:
pip install bleak
```

## 🧩 功能模块

项目采用**模块化架构**——主程序 `main.py` 启动时扫描 `传感器代码/` 目录，自动加载每个传感器的 Backend 类与对应 QML 文件。每个模块的 BOM 物料清单、接线指南、校准方法、计算原理和常见问题均在各自的 README 中。

| 模块 | 传感器 | 开发板 | 类别 | 模块开源协议 | 说明文档 |
|------|--------|--------|------|--------------|----------|
| 超声波位移 | HC-SR04 | ESP32 / ESP8266 / ESP32-S3 | 物理 | GPL-3.0 | [使用说明](传感器代码/超声波位移传感器/README.md) |
| 超声波速度 | HC-SR04 | （共享上述固件） | 物理 | GPL-3.0 | [使用说明](传感器代码/超声波位移传感器/README.md) |
| pH 传感器 | SEN0161 | ESP32-S3 | 化学 | GPL-3.0 | [使用说明](传感器代码/ph传感器/README.md) |
| 力/质量传感器 | HX711 | ESP32-S3 | 物理 | GPL-3.0 | [使用说明](传感器代码/力传感器/README.md) |
| 电压传感器 | ESP32 ADC / HX711 | ESP32-S3 | 物理 | GPL-3.0 | [使用说明](传感器代码/电压传感器/README.md) |
| 电流传感器 | ACS712 | ESP32-S3 | 物理 | GPL-3.0 | 📝 开发中（[上位机模块](传感器代码/电流传感器/current_sensor.py)） |

## 📂 项目结构

```
PhysChem-DigitizerP/
├── main.py                     # 主程序：QML 入口 + 模块扫描 + Backend 注册
├── core/                       # 公共包：配置 / 串口 / BLE
│   ├── __init__.py             #   统一导出
│   ├── config.py               #   sensor_config.json 读写
│   ├── serial_thread.py        #   SerialThread + list_serial_ports
│   └── ble_thread.py           #   BLESerialThread + scan_ble_devices（bleak 可选）
├── backends/                   # Backend 包：QML↔Python 桥接
│   ├── __init__.py
│   ├── backend_base.py         #   BackendBase（QObject 基类，提供 Property/Slot）
│   └── chart_item.py           #   ChartItem（QQuickPaintedItem，封装 pyqtgraph）
├── qml/                        # QML 界面
│   ├── Main.qml                #   主窗口：侧边栏 + StackLayout
│   ├── HomePage.qml            #   主页：项目卡片 + 模块网格
│   ├── SettingsPage.qml        #   设置页
│   ├── SidebarButton.qml       #   侧边栏按钮组件
│   ├── ModuleCard.qml          #   模块卡片组件
│   ├── SensorToolbar.qml       #   通用串口工具栏
│   ├── ChartPanel.qml          #   通用图表面板（含当前值/统计/日志）
│   ├── ActionBar.qml           #   通用操作栏（开始/停止/保存/清除）
│   ├── ModuleView.qml          #   通用模块视图模板
│   ├── FluentTheme/            #   Fluent 主题色 token 单例（来源 fluentpyside, MIT）
│   │   ├── qmldir              #     注册 singleton Fluent
│   │   └── Fluent.qml          #     深浅色自适应主题色（accent/background/textPrimary...）
│   └── modules/                #   各模块定制 QML
│       ├── ultrasonic_displacement.qml
│       ├── ultrasonic_velocity.qml
│       ├── ph_sensor.qml
│       ├── force_sensor.qml
│       ├── voltage_sensor.qml
│       └── current_sensor.qml
├── main_legacy.py              # 历史存档（迁移前 QtWidgets 单文件版本，不再维护）
├── test_serial.py              # 串口连接测试工具
├── sensor_config.json          # 传感器校准配置（运行时自动生成，.gitignore）
├── README.md                   # 主文档（本文件）
├── AGENTS.md                   # 开发者指南（含添加新模块教程）
├── LICENSE                     # GPL-3.0 许可证
├── docs/
│   └── images/                 # 文档图片
└── 传感器代码/                  # 下位机 .ino + 上位机 Backend .py 同目录
    ├── README.md               # 各传感器固件与模块总览
    ├── 超声波位移传感器/
    │   ├── README.md           # 使用说明（接线/校准/原理/FAQ）
    │   ├── HC-SR04esp32.ino    # ESP32 固件
    │   ├── HC-SR04esp8266.ino  # ESP8266 固件
    │   ├── csbwithbt.ino       # ESP32-S3 + BLE 固件
    │   ├── ultrasonic_displacement.py  # 位移 Backend
    │   └── ultrasonic_velocity.py      # 速度 Backend
    ├── ph传感器/
    │   ├── README.md           # 使用说明（接线/多模式校准/电极保养/FAQ）
    │   ├── ph esp32.ino        # ESP32-S3 固件
    │   ├── PH传感器原理图.pdf
    │   └── ph_sensor.py        # pH Backend（单点/两点/三点校准）
    ├── 力传感器/
    │   ├── README.md           # 使用说明（接线/去皮校准/串口命令/FAQ）
    │   ├── force.ino           # ESP32-S3 HX711 固件
    │   ├── force_sensor.py     # 力/质量 Backend
    │   └── 资料（HX711称重模块商家提供的）/
    ├── 电压传感器/
    │   ├── README.md           # 使用说明（接线/分压扩展/ADC配置/FAQ）
    │   ├── ESP32_Voltage_Sensor.ino  # ESP32-S3 内置 ADC 固件
    │   ├── HX711_Voltage.ino         # HX711 24 位 ADC 固件
    │   └── voltage_sensor.py         # 电压 Backend（支持 HX711 模式）
    └── 电流传感器/              # ACS712 电流（5A/20A/30A，AC/DC，零点校准）
        ├── ESP32_ADC_Raw_Data.ino   # ESP32-S3 固件
        └── current_sensor.py        # 电流 Backend
```

> 📖 模块加载机制、识别区格式与添加新模块的完整教程请参考 [AGENTS.md](AGENTS.md)。

## 🛠️ 软件安装

### 1. 环境要求

- **操作系统**：Windows 10/11（推荐），macOS，Linux
- **Python**：3.9 或更高（推荐 3.11+）
- **Arduino IDE**：1.8.x 或 2.x（用于烧录固件）
- **显卡驱动**：需要 OpenGL 2.0+ 支持（QtQuick 渲染要求）

### 2. 烧录 Arduino 固件

1. 安装 Arduino IDE 并添加开发板支持：
   - **ESP8266**：`http://arduino.esp8266.com/stable/package_esp8266com_index.json`
   - **ESP32**：`https://dl.espressif.com/dl/package_esp32_index.json`
   - **ESP32 国内镜像（推荐）**：`https://jihulab.com/esp-mirror/espressif/arduino-esp32/-/raw/gh-pages/package_esp32_index_cn.json`
   - 文件 → 首选项 → 附加开发板管理器网址 → 粘贴上述地址
   - 工具 → 开发板 → 开发板管理器 → 搜索 "esp32" → 安装

2. 选择对应固件烧录（各模块固件路径见上方"功能模块"表）：
   - ESP8266：开发板选 **WeMos D1 R1**
   - ESP32：开发板选 **ESP32 Dev Module**
   - 选择正确端口，点击上传

3. 验证固件：打开串口监视器（波特率 **115200**），应看到 `START` 和数据输出

### 3. 安装 Python 软件

```bash
pip install PySide6>=6.4.0 fluentpyside>=0.1.0 pyqtgraph>=0.13.0 pyserial>=3.5 numpy>=1.21.0
# 可选（BLE 无线通信）:
pip install bleak
```

> **Linux 用户**：如遇 `libEGL.so.1: cannot open shared object file`，请安装
> `sudo apt install libegl1 libgl1-mesa-glx libglib2.0-0`。

## 💻 使用方法

### 启动软件

```bash
python main.py
```

### FluentPySide 主题集成说明

本项目**真正接入** [FluentPySide](https://pypi.org/project/fluentpyside/) ——QtQuick Controls FluentWinUI3 主题：

- **Python 端**（`main.py`）：`apply_fluent_style(engine)` 在 `QQmlApplicationEngine` 创建后调用：
  1. 自动定位 FluentWinUI3 样式资源（依次查找 `fluentpyside` 包内 → `PySide6/Qt/qml/...` → `PySide6/qml/...`，兼容官方 wheels 与 fluentpyside 包内副本）
  2. 调用 `fluentpyside.set_style(path, engine=engine)` 设置 `QML2_IMPORT_PATH` 与 `engine.addImportPath()`
  3. 显式 `QQuickStyle.setStyle("FluentWinUI3")` 兜底
- **QML 端**（`qml/FluentTheme/`）：本地注册 `Fluent` 单例（来源 fluentpyside 包，MIT 协议），暴露深浅色自适应主题色 token：
  - `Fluent.accent` / `Fluent.background` / `Fluent.textPrimary` / `Fluent.accentSelected` …
  - `Fluent.fontTitleSize` / `Fluent.radiusMedium` / `Fluent.spacingM` …
  - 自动跟随 `Application.styleHints.colorScheme`（系统深浅色）
- **使用方式**：QML 文件中 `import FluentTheme 1.0`，然后用 `Fluent.xxx` 替代硬编码颜色，例如：
  ```qml
  import FluentTheme 1.0
  Rectangle { color: Fluent.accentSelected }
  Label { color: Fluent.textPrimary; font.pixelSize: Fluent.fontBodySize }
  ```

### 验证接入生效

启动 `main.py` 时控制台会输出：

```
✓ FluentWinUI3 样式已应用: <...>/PySide6/Qt/qml/QtQuick/Controls/FluentWinUI3
  QQuickStyle.name = FluentWinUI3
```

只要 `QQuickStyle.name = FluentWinUI3` 且**无 QML 警告**，就说明：

- ✅ QtQuick.Controls 全局样式已切到 FluentWinUI3（用的是 PySide6 自带的 `libqtquickcontrols2fluentwinui3styleplugin.so` **真样式插件**，不是 QSS 仿真）
- ✅ `Fluent` 单例在 QML 中可读：`Fluent.accent = #005fb8`（浅色）/ `#60cdff`（深色），`Fluent.background = #f3f3f3` / `#202020`
- ✅ 自动跟随系统深浅色（`Application.styleHints.colorScheme`）

> ⚠️ 若 `QQuickStyle.name` 显示 `Fusion`/`Basic`/`Default`，则样式未生效——通常是 `fluentpyside` 与 PySide6 wheel 的 QML 路径不一致导致；本项目 `apply_fluent_style()` 已通过自定义路径查找逻辑修复此问题。

### 通用操作流程

1. 通过 USB 连接开发板到电脑
2. 在软件左侧侧边栏选择对应传感器模块
3. 点击"刷新"选择 COM 端口，点击"连接"
4. 点击"开始采集"实时显示数据与曲线
5. 点击"停止采集"结束
6. 点击"保存数据"导出为 CSV 文件

> 📖 各模块的具体接线、校准步骤和实验方法请参考对应的模块 README。

## 🔍 故障排除

### 快速诊断

```bash
python test_serial.py
```

### 常见问题

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 找不到串口 | 驱动未安装/USB 未连接 | 安装 CH340G/CP210x 驱动，重新插拔 USB |
| 连接后无数据 | 波特率错误/固件未上传 | 确认波特率 115200，重新上传固件 |
| 数据跳变异常 | 传感器干扰/接线松动 | 检查接线，远离干扰源 |
| 启动崩溃 `libEGL.so.1` | Linux 缺 OpenGL 库 | `sudo apt install libegl1 libgl1-mesa-glx` |
| 模块未出现在侧边栏 | 识别区格式错误 | 检查 `.py` 文件头 `# === MODULE META ===` 块 |
| QML 报 `is not a type` | import 路径错 | 模块 QML 需 `import ".."` 引用父目录组件 |

## 📚 技术文档

- **[AGENTS.md](AGENTS.md)** — 开发者指南：模块化架构说明、识别区格式、添加新模块完整教程
- **[传感器代码总览](传感器代码/README.md)** — 各传感器固件与上位机模块对照表
- **[超声波位移传感器](传感器代码/超声波位移传感器/README.md)** — 接线指南、固件说明、校准方法与计算原理
- **[pH 传感器](传感器代码/ph传感器/README.md)** — 接线、多模式校准（单点/两点/三点）、电极保养
- **[力传感器](传感器代码/力传感器/README.md)** — HX711 接线、去皮校准、串口命令
- **[电压传感器](传感器代码/电压传感器/README.md)** — ADC 接线、分压扩展、精度优化

## 🔧 扩展开发

新增传感器**无需修改 `main.py`**，只需 3 步：

1. 在 `传感器代码/` 下新建子目录，放入 `.ino` 和 `.py`（Backend 类继承 `BackendBase`）
2. 在 `.py` 文件头写识别区：

```python
# === MODULE META ===
# icon: T
# name: 温度传感器
# category: physics          # physics 或 chemistry
# class: TemperatureBackend
# ===================
```

3. 在 `qml/modules/` 下创建同名 `<module_id>.qml`（如缺失则使用通用 `ModuleView.qml`）

重启 `main.py` 即自动出现在侧边栏 + 主页卡片 + 内容栈。

> 📖 完整字段说明、BackendBase 接口与示例请参考 [AGENTS.md](AGENTS.md)。

## 🖥️ 软件界面

<p align="center">
  <img src="docs/images/settings.png" alt="设置界面" width="800"/>
</p>
<p align="center">设置界面 — 关于 / 主题 / 项目链接</p>

- **左侧侧边栏**：模块选择导航（主页 + 各模块 + 设置）
- **串口控制**：选择端口、刷新、连接/断开
- **实时数据**：当前值、统计信息、操作日志
- **图表区域**：pyqtgraph 实时数据曲线
- **操作按钮**：开始/停止采集、保存数据、清除数据
- **模块特有控件**：校准、单位切换、量程选择等

## 🤝 贡献指南

```bash
# GitHub
git clone https://github.com/wangzhidong2/PhysChem-DigitizerP.git
# Gitee（国内推荐）
git clone https://gitee.com/wangzhidong2/PhysChem-DigitizerP.git
# GitCode
git clone https://gitcode.com/wangzhidong2/PhysChem-DigitizerP.git

cd PhysChem-DigitizerP
pip install PySide6>=6.4.0 fluentpyside>=0.1.0 pyqtgraph>=0.13.0 pyserial>=3.5 numpy>=1.21.0
```

## 📄 许可证

本项目采用 **GNU General Public License v3.0** - 详见 [LICENSE](LICENSE) 文件

## 👥 致谢

- **硬件平台**：[ESP32](https://www.espressif.com/) / [ESP8266 Community](https://www.esp8266.com/)
- **图形界面**：[PySide6](https://www.qt.io/qt-for-python)（Qt for Python）
- **UI 主题**：[FluentPySide](https://pypi.org/project/fluentpyside/)（QtQuick.Controls FluentWinUI3 风格）
- **数据可视化**：[pyqtgraph](https://pyqtgraph.org/)（高性能科学绘图）
- **串口通信**：[pyserial](https://github.com/pyserial/pyserial)

## 📧 联系方式

如有问题或建议，请提交 [GitHub Issue](https://github.com/wangzhidong2/PhysChem-DigitizerP/issues) 或 [Gitee Issue](https://gitee.com/wangzhidong2/PhysChem-DigitizerP/issues)。

## 🌐 项目地址

- **GitHub**: [https://github.com/wangzhidong2/PhysChem-DigitizerP](https://github.com/wangzhidong2/PhysChem-DigitizerP)
- **Gitee**: [https://gitee.com/wangzhidong2/PhysChem-DigitizerP/](https://gitee.com/wangzhidong2/PhysChem-DigitizerP/)
- **GitCode**: [https://gitcode.com/wangzhidong2/PhysChem-DigitizerP](https://gitcode.com/wangzhidong2/PhysChem-DigitizerP)

---

**Happy Experimenting! 🔬📊**
