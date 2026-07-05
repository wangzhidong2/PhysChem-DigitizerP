# PhysChem-DigitizerP

> 基于 Arduino/ESP32/ESP8266 + PyQt6 的低成本理化实验数字化采集系统。**模块化架构**——新增传感器只需丢一个 `.py` 文件，主程序零修改。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-≥3.8-blue?logo=python)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/PyQt6-≥6.4-green?logo=qt)](https://www.riverbankcomputing.com/software/pyqt/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)](#)
[![GitHub](https://img.shields.io/badge/GitHub-Repository-blue?logo=github)](https://github.com/wangzhidong2/PhysChem-DigitizerP)
[![Gitee](https://img.shields.io/badge/Gitee-Repository-red?logo=gitee)](https://gitee.com/wangzhidong2/PhysChem-DigitizerP/)
[![GitCode](https://img.shields.io/badge/GitCode-Repository-orange?logo=gitcode)](https://gitcode.com/wangzhidong2/PhysChem-DigitizerP)

---

## ✨ 项目亮点

- 🧩 **模块化架构**：主程序启动时扫描 `传感器代码/` 目录，用 `importlib` 自动加载带识别区的 `.py` 文件。新增传感器**无需修改主程序**，只需丢文件 + 写文件头
- 💰 **低成本替代**：单传感器成本 < ¥30，商业方案通常 > ¥500
- 🎨 **Win11 风格 UI**：卡片布局 + 自绘侧边栏 + WinUI3 风格 ComboBox
- 📡 **双连接方式**：支持 USB 有线串口和 BLE 蓝牙无线（需 `bleak`）
- 🔬 **多模式校准**：pH 支持单点/两点/三点校准，HX711 支持两点校准 + 去皮
- 📊 **实时可视化**：Matplotlib 实时曲线 + 统计信息 + CSV 导出
- 🔓 **完全开源**：硬件固件 + 上位机软件 + 文档，支持二次开发

---

## 📦 核心依赖

| 库 | 版本 | 用途 | 必选 |
|----|------|------|------|
| **PyQt6** | ≥6.4.0 | 图形界面框架 | ✅ |
| **pyserial** | ≥3.5 | 串口通信 | ✅ |
| **matplotlib** | ≥3.5.0 | 数据可视化 | ✅ |
| **numpy** | ≥1.21.0 | 数值计算（校准拟合） | ✅ |
| **bleak** | ≥0.20 | BLE 蓝牙无线通信 | ⬜ 可选 |

```bash
pip install PyQt6>=6.4.0 pyserial>=3.5 matplotlib>=3.5.0 numpy>=1.21.0
# 可选：BLE 无线通信
pip install bleak
```

---

## 📖 项目简介

**PhysChem-DigitizerP** 是一个开源的物理化学实验数字化采集系统，为中学物理/化学实验室提供低成本的传感器解决方案。项目由两部分组成：

- **下位机**：ESP32 / ESP8266 / Arduino 固件（`.ino`），负责采集传感器数据并通过串口输出 `时间戳,测量值` CSV
- **上位机**：Python + PyQt6 桌面应用（`main.py` + `core.py` + 各传感器模块），负责接收、可视化、校准、导出

<p align="center">
  <img src="docs/images/home.png" alt="主界面" width="800"/>
</p>
<p align="center">软件主界面 — 模块导航与项目概览</p>

### 🎯 项目目标

| 目标 | 说明 |
|------|------|
| **低成本替代** | 为昂贵的商业理化实验传感器提供经济实惠的开源替代方案 |
| **开源透明** | 所有硬件设计和软件代码完全开源，支持二次开发和定制 |
| **易于使用** | 现代化 Win11 风格界面，直观的操作流程 |
| **高扩展性** | 模块化设计，新增传感器只需 2 步，不动主程序 |

---

## 📋 硬件准备 (BOM)

| 组件 | 型号/规格 | 数量 | 备注 |
|------|-----------|------|------|
| 开发板 | ESP32 / ESP32-S3 / ESP8266 (WeMOS D1) | 1 | 推荐 ESP32-S3 |
| 传感器模块 | 根据实验需求选择 | 1 | HC-SR04 / SEN0161 / HX711 等 |
| 杜邦线 | 公对母 | 若干 | 根据传感器需求 |
| USB 线 | Micro-USB 或 Type-C | 1 | 数据通信和供电 |

> 💡 **成本估算**：单传感器成本 < ¥30（商业方案通常 > ¥500）

---

## 🚀 核心功能

### 已实现传感器模块

| 模块 | 类别 | 开发板 | 核心功能 | 上位机模块 |
|------|------|--------|----------|-----------|
| **超声波位移** | physics | ESP32 / ESP8266 / ESP32-S3 | 实时距离测量（±0.3cm）+ 距离-时间曲线 + 统计 + CSV 导出 | `ultrasonic_displacement.py` |
| **超声波速度** | physics | （共享上述固件） | 回声定位法计算瞬时速度 + 双图表（距离/速度） | `ultrasonic_velocity.py` |
| **pH 传感器** | chemistry | ESP32-S3 | 单点/两点/三点校准 + 实时 pH 曲线 + 电极保养指南 | `ph_sensor.py` |
| **力/质量传感器** | physics | ESP32-S3 | HX711 24位 ADC + 去皮（Tare）+ 两点校准 + BLE 支持 | `force_sensor.py` |
| **电压传感器** | physics | ESP32-S3 | ESP32 内置 ADC + HX711 24位 ADC 双模式 + kV/V/mV 单位切换 + Tare | `voltage_sensor.py` |
| **电流传感器** | physics | ESP32-S3 | ADC 原始数据采集（仅下位机，上位机待开发） | 🚧 待添加 |

### 软件特性

- 🎨 **Win11 风格 UI**：卡片布局 + 自绘侧边栏（NavButton 图标 + 选中指示条）+ WinUI3 风格 QComboBox
- 📡 **双连接方式**：USB 串口（SerialThread）+ BLE 蓝牙（BLESerialThread，需 `bleak`）
- 🧪 **多模式校准**：pH 单点（Nernst 理论斜率）/ 两点（线性拟合）/ 三点（二次多项式拟合）
- ⚖️ **去皮与校准**：HX711 力/电压模块支持 Tare 清零 + 两点校准，参数自动保存到 `sensor_config.json`
- 📊 **实时可视化**：Matplotlib 实时曲线 + 平均值/最大值/最小值/标准差统计
- 💾 **CSV 导出**：采集数据一键导出为 CSV（含时间戳、原始值、换算值）
- ⚙️ **可配置采样率**：每个模块支持调整采样频率（默认 10Hz）

### 规划中功能

- 🌡️ 温度传感器模块（DS18B20）
- 💡 光电门模块
- 📡 WiFi 无线数据传输
- 🔊 声音传感器模块

---

## 📦 项目结构

项目采用**模块化架构**——主程序 `main.py` 启动时扫描 `传感器代码/` 目录，通过 `importlib` 自动加载每个带识别区的 `.py` 模块文件。新增传感器**无需修改主程序**。

```
PhysChem-DigitizerP/
├── main.py                     # 主程序：主页 + 侧边栏 + 动态加载器
├── core.py                     # 公共模块：SerialThread / BLESerialThread / 配置 / 对话框 / Win11 样式
├── main_legacy.py              # 历史存档（迁移前单文件版本，不再维护）
├── test_serial.py              # 串口连接测试工具
├── sensor_config.json          # 传感器校准配置（.gitignore，运行时自动生成）
├── README.md                   # 主文档（本文件）
├── AGENTS.md                   # 开发者指南（含添加新模块完整教程）
├── LICENSE                     # MIT 许可证
├── docs/
│   └── images/                 # 文档图片
└── 传感器代码/                  # 下位机 .ino + 上位机 .py 同目录
    ├── README.md               # 各传感器固件与模块总览
    ├── 超声波位移传感器/
    │   ├── HC-SR04esp32.ino        # ESP32 固件
    │   ├── HC-SR04esp8266.ino      # ESP8266 固件
    │   ├── csbwithbt.ino           # ESP32-S3 + BLE 固件
    │   ├── ultrasonic_displacement.py  # 位移测量上位机模块
    │   └── ultrasonic_velocity.py      # 速度测量上位机模块
    ├── ph传感器/
    │   ├── ph esp32.ino            # ESP32-S3 pH 传感器固件
    │   ├── PH传感器原理图.pdf
    │   └── ph_sensor.py            # pH 上位机模块
    ├── 力传感器/
    │   ├── force.ino               # ESP32-S3 HX711 传感器固件
    │   ├── force_sensor.py         # 力/质量上位机模块
    │   └── 资料（HX711称重模块商家提供的）/
    ├── 电压传感器/
    │   ├── ESP32_Voltage_Sensor.ino  # ESP32-S3 内置 ADC 固件
    │   ├── HX711_Voltage.ino         # HX711 24 位 ADC 电压固件
    │   └── voltage_sensor.py         # 电压上位机模块（支持 HX711 模式）
    └── 电流传感器/                  # 仅下位机，上位机模块待添加
        └── ESP32_ADC_Raw_Data.ino
```

> 📖 模块加载机制、识别区格式与添加新模块的完整教程请参考 [AGENTS.md](AGENTS.md)。

---

## 🛠️ 安装与运行

### 1. 环境要求

- **操作系统**：Windows 10/11（推荐），macOS，Linux
- **Python**：3.8 或更高
- **Arduino IDE**：1.8.x 或 2.x（用于烧录固件）

### 2. 烧录 Arduino 固件

1. 安装 Arduino IDE 并添加开发板支持：
   - **ESP8266**：`http://arduino.esp8266.com/stable/package_esp8266com_index.json`
   - **ESP32**：`https://dl.espressif.com/dl/package_esp32_index.json`
   - **ESP32 国内镜像（推荐）**：`https://jihulab.com/esp-mirror/espressif/arduino-esp32/-/raw/gh-pages/package_esp32_index_cn.json`
   - 文件 → 首选项 → 附加开发板管理器网址 → 粘贴上述地址
   - 工具 → 开发板 → 开发板管理器 → 搜索 "esp32" → 安装

2. 上传固件：
   - 根据开发板选择对应 `.ino` 文件（参见上表）
   - ESP8266：选择开发板 **WeMos D1 R1**
   - ESP32：选择开发板 **ESP32 Dev Module** / **ESP32S3 Dev Module**
   - 选择正确的端口（如 COM3）
   - 点击上传

3. 验证固件：
   - 打开 Arduino IDE 串口监视器
   - 设置波特率：**115200**
   - 应看到 `START` 启动信息和 `时间戳,测量值` 数据输出

### 3. 安装 Python 依赖

```bash
pip install PyQt6>=6.4.0 pyserial>=3.5 matplotlib>=3.5.0 numpy>=1.21.0
# 可选（BLE 无线通信）:
pip install bleak
```

### 4. 启动软件

```bash
python main.py
```

> ⚠️ 注意：请使用 `main.py` 启动。`main_legacy.py` 是迁移前的单文件版本（5000 行），仅供对照参考，不再维护。

---

## 💻 使用指南

### 通用操作流程

1. **连接硬件**：将开发板通过 USB 连接到电脑
2. **选择模块**：在软件左侧侧边栏点击对应传感器模块
3. **选择串口**：点击 "刷新" 按钮，选择对应 COM 端口（或扫描 BLE 设备）
4. **建立连接**：点击 "连接" 按钮，状态显示 "已连接"
5. **开始采集**：点击 "开始采集"，实时显示数据 + 曲线
6. **观察数据**：文本区域显示详细记录，图表区域显示实时曲线，统计信息实时更新
7. **停止采集**：点击 "停止采集" 结束
8. **保存数据**：点击 "保存数据"，导出为 CSV 文件

### 串口通信协议

**输出格式**：`时间戳,测量值`（CSV）

**示例**：
```
START
123456,1450
123476,1465
123496,1440
```

| 字段 | 单位 | 说明 |
|------|------|------|
| 时间戳 | µs 或 ms | 取决于固件（超声波为 µs，其他多为 ms） |
| 测量值 | 取决于传感器 | 回波时间 / ADC 原始值 / HX711 24位原始值 |

### CSV 导出格式

**位移数据**（`sensor_data_YYYYMMDD_HHMMSS.csv`）：
```csv
timestamp_ms,distance_cm
0,12.345
100,12.567
200,12.789
```

**速度数据**（`velocity_data_YYYYMMDD_HHMMSS.csv`）：
```csv
time_s,distance_cm,velocity_cm_s
0.000,12.345,
0.100,12.567,2.22
0.200,12.789,2.20
```

---

## 🔌 接线指南

> ⚠️ **以下为简要接线参考，详细接线、注意事项及故障排查请参阅各模块文档：**
> - [超声波位移传感器](传感器代码/超声波位移传感器/README.md)
> - [pH 传感器](传感器代码/ph传感器/README.md)
> - [力传感器](传感器代码/力传感器/README.md)
> - [电压传感器](传感器代码/电压传感器/README.md)

### HC-SR04 超声波传感器

**ESP32 连接**：
```
ESP32             HC-SR04
─────             ───────
5V (VIN)    →     VCC
GND         →     GND
GPIO 5      →     TRIG
GPIO 18     →     ECHO
```

**ESP8266 (WeMOS D1) 连接**：
```
WeMOS D1          HC-SR04
─────────         ───────
5V (VIN)    →     VCC
GND         →     GND
D5 (GPIO14) →     TRIG
D6 (GPIO12) →     ECHO
```

> 📖 详细说明：[超声波位移传感器使用说明](传感器代码/超声波位移传感器/README.md)

### HX711 力/质量传感器

**ESP32-S3 ↔ HX711 模块**：
```
ESP32-S3          HX711 模块
─────────         ──────────
3.3V        →     VCC
GND         →     GND
GPIO4       →     DT (DOUT)
GPIO5       →     SCK (PD_SCK)
```

**HX711 模块 ↔ 称重传感器**：
```
HX711 模块        称重传感器
─────────        ──────────
E+          →    激励正极（红色线）
E-          →    激励负极（黑色线）
A+          →    通道A正极（绿色线）
A-          →    通道A负极（白色线）
```

> 📖 详细说明：[力传感器使用说明](传感器代码/力传感器/README.md)

---

## 📐 计算原理与数学表达式

### 1. 超声波速度测量（回声定位法）

**原理**：通过连续两次超声波回波时间的差值，结合声速和测量间隔计算物体运动速度。

**数学表达式**：
```
v = (t₀ - t₁) / 2 × vₛ / [(t₁ + t₀) / 2 + Δt]
```

其中：
- `t₀`、`t₁`：连续两次回波时间 (µs)
- `Δt`：两次发射的时间间隔 (s)，默认 20ms
- `vₛ`：声速 = 34000 cm/s（340 m/s）

**代码实现**：参考 [ultrasonic_velocity.py](传感器代码/超声波位移传感器/ultrasonic_velocity.py) 中的 `calculate_velocity` 方法。

### 2. pH 传感器多模式校准

| 模式 | 拟合方法 | 数学模型 | 适用场景 | 精度 |
|------|----------|----------|----------|------|
| **单点校准** | Nernst 理论斜率 | `pH = pH_ref + slope × (V - V_ref)` | 快速粗略校准 | 一般 |
| **两点校准** | 线性拟合 | `pH = k·ADC + b` | 一般测量场景 | 较高 |
| **三点校准** | 二次多项式拟合 | `pH = a·ADC² + b·ADC + c` | 高精度测量，非线性补偿 | 最高 |

其中 `slope` 为 Nernst 理论斜率（-59.16 mV/pH @25°C），`ADC` 为传感器原始值（0-4095）。

**默认校准参数**：
```python
default_calibration = [
    (4.00, 2555),   # 酸性缓冲液 (pH 4.00 → ADC 2555)
    (6.86, 2281),   # 中性缓冲液 (pH 6.86 → ADC 2281)
    (9.18, 2030)    # 碱性缓冲液 (pH 9.18 → ADC 2030)
]
```

**代码实现**：参考 [ph_sensor.py](传感器代码/ph传感器/ph_sensor.py) 中的 `calculate_calibration_coefficients` 和 `adc_to_ph` 方法。

### 3. 力/质量传感器（HX711 两点校准）

**原理**：HX711 24位高精度 ADC 读取称重传感器原始值，通过两点校准建立 ADC 与质量的线性关系。

**数学表达式**：
```
质量 = (ADC - offset) × scale
```

其中：
- `offset`：空载时的 ADC 值（去皮偏移量）
- `scale`：校准比例 = 已知质量 / (加载ADC - 空载ADC)

**校准示例**：
```
空载 ADC = -58720
加载 100g 砝码后 ADC = -52720
ADC 差值 = 6000
scale = 100 / 6000 = 0.016667
offset = -58720

当 ADC = -55720 时：
质量 = (-55720 - (-58720)) × 0.016667 = 50.0g
```

> 校准参数自动保存到 `sensor_config.json`，下次启动自动加载。

**代码实现**：参考 [force_sensor.py](传感器代码/力传感器/force_sensor.py)。

### 4. 电压传感器（双模式）

- **ESP32 内置 ADC 模式**：12 位分辨率，0-3.3V 量程，`实测电压 = ADC × 3.3 / 4095`
- **HX711 24 位 ADC 模式**：通道 A/B、增益 128/32，更高精度
- 支持 kV/V/mV 单位切换 + 去皮（Tare）

**代码实现**：参考 [voltage_sensor.py](传感器代码/电压传感器/voltage_sensor.py)。

---

## 🔍 故障排除

### 快速诊断

```bash
python test_serial.py
```

该脚本自动检测所有串口并测试连接状态。

### 常见问题

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 找不到串口 | 驱动未安装 / USB 未连接 | 安装 CH340G/CP210x 驱动，重新插拔 USB |
| 连接后无数据 | 波特率错误 / 固件未上传 | 确认波特率 115200，重新上传固件 |
| 数据跳变异常 | 传感器干扰 / 接线松动 | 检查接线，远离干扰源，加滤波电容 |
| 图表不显示 | matplotlib 问题 | `pip install --upgrade matplotlib` |
| BLE 连接失败 | 未安装 bleak / 设备未配对 | `pip install bleak`，先在系统配对设备 |
| 模块未出现在侧边栏 | 识别区格式错误 | 检查 `.py` 文件头的 `# === MODULE META ===` 块 |

### 诊断步骤

1. **验证固件**：打开 Arduino IDE 串口监视器（波特率 115200），应看到 `START` 和数据输出
2. **检查驱动**：设备管理器 → 端口 (COM 和 LPT)，确认开发板 COM 端口存在
3. **运行测试**：`python test_serial.py` 查看详细诊断信息
4. **查看模块加载**：启动 `main.py` 时观察控制台输出，确认各模块识别区被正确解析

---

## 🔧 扩展开发

### 添加新传感器模块（2 步）

项目采用**模块化架构**——主程序 `main.py` 启动时通过 `importlib` 扫描 `传感器代码/` 目录，自动加载带有识别区的 `.py` 模块文件。新增传感器**无需修改主程序**。

**步骤 1**：在 `传感器代码/` 下新建子目录，放入下位机 `.ino` 和上位机 `.py`：

```
传感器代码/
└── 温度传感器/                  ← 新建目录
    ├── ds18b20.ino              ← 下位机固件
    └── temperature_sensor.py    ← 上位机模块（带识别区）
```

**步骤 2**：在 `.py` 文件头写识别区：

```python
# === MODULE META ===
# icon: T
# name: 温度传感器
# category: physics          # physics 或 chemistry
# class: TemperatureSensorWidget
# ===================

# -*- coding: utf-8 -*-
"""温度传感器模块"""

from core import (
    SerialThread, load_sensor_config, save_sensor_config,
    card_style, primary_btn_style, accent_btn_style, win11_combo_style,
)

class TemperatureSensorWidget(QWidget):
    def __init__(self):
        ...
```

重启 `main.py` 即自动出现在侧边栏 + 主页卡片 + 内容栈。

### 识别区字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `icon` | 是 | 模块图标文本（如 `x`、`V`、`pH`），显示在侧边栏和主页 |
| `name` | 是 | 模块显示名（如 `超声波位移`），用于侧边栏和主页卡片 |
| `category` | 是 | 模块类别：`physics`（物理）/ `chemistry`（化学），决定主页分组 |
| `class` | 是 | 模块的主类名（如 `UltrasonicWidget`），必须继承 `QWidget` |

> 📖 完整教程、目录结构示例与注意事项请参考 [AGENTS.md - 添加新传感器模块](AGENTS.md#添加新传感器模块)。

---

## 🖥️ 软件界面

<p align="center">
  <img src="docs/images/home.png" alt="主界面" width="800"/>
</p>
<p align="center">主界面 — 模块导航与项目概览</p>

### 界面元素

- **左侧侧边栏**：模块选择导航（自绘 NavButton，图标 + 选中指示条）
- **主页卡片**：按 `physics` / `chemistry` 类别分组的模块卡片
- **串口控制**：选择端口、刷新、连接/断开（或 BLE 设备扫描）
- **实时数据**：当前值大字显示、统计信息、数据记录
- **图表区域**：Matplotlib 实时曲线
- **操作按钮**：开始/停止采集、保存数据、清除数据、校准、去皮
- **Win11 风格**：卡片布局 + WinUI3 风格 QComboBox（圆角、悬停高亮、蓝色聚焦边框）

<p align="center">
  <img src="docs/images/settings.png" alt="设置界面" width="800"/>
</p>
<p align="center">设置界面 — 外观主题切换</p>

---

## 📚 技术文档

| 文档 | 说明 |
|------|------|
| **[AGENTS.md](AGENTS.md)** | 开发者指南：模块化架构说明、识别区格式、添加新模块完整教程（双语） |
| **[传感器代码总览](传感器代码/README.md)** | 各传感器固件与上位机模块对照表 |
| **[超声波位移传感器使用说明](传感器代码/超声波位移传感器/README.md)** | HC-SR04 接线指南、固件说明、校准方法与性能优化 |
| **[pH 传感器使用说明](传感器代码/ph传感器/README.md)** | pH 传感器接线、多模式校准步骤（单点/两点/三点）、电极保养与常见问题 |
| **[力传感器使用说明](传感器代码/力传感器/README.md)** | HX711 力/质量传感器接线、去皮校准、数据采集与常见问题 |
| **[电压传感器使用说明](传感器代码/电压传感器/README.md)** | ESP32 ADC / HX711 电压采集接线、分压扩展、精度优化与常见问题 |

---

## 🤝 贡献指南

欢迎贡献代码、报告问题或提出建议！

### 开发环境设置

```bash
# GitHub
git clone https://github.com/wangzhidong2/PhysChem-DigitizerP.git

# Gitee（国内推荐）
git clone https://gitee.com/wangzhidong2/PhysChem-DigitizerP.git

# GitCode
git clone https://gitcode.com/wangzhidong2/PhysChem-DigitizerP.git

cd PhysChem-DigitizerP
pip install PyQt6>=6.4.0 pyserial>=3.5 matplotlib>=3.5.0 numpy>=1.21.0
# 可选（BLE 无线通信）:
pip install bleak
```

### 贡献方式

- 🐛 [提交 Issue](https://github.com/wangzhidong2/PhysChem-DigitizerP/issues) 报告问题
- 🔀 [提交 Pull Request](https://github.com/wangzhidong2/PhysChem-DigitizerP/pulls) 改进代码
- 📝 完善文档或翻译
- 🧪 贡献新的传感器模块（参考 [添加新传感器模块](#🔧-扩展开发)）

---

## 📄 许可证

本项目采用 **MIT 许可证** — 详见 [LICENSE](LICENSE) 文件

---

## 👥 致谢

- **硬件平台**：[ESP32](https://www.espressif.com/) / [ESP8266 Community](https://www.esp8266.com/)
- **图形界面**：[PyQt6](https://www.riverbankcomputing.com/software/pyqt/)
- **数据可视化**：[Matplotlib](https://matplotlib.org/)
- **串口通信**：[pyserial](https://github.com/pyserial/pyserial)
- **BLE 通信**：[bleak](https://github.com/hbldh/bleak)

---

## 🌐 项目地址

| 平台 | 地址 |
|------|------|
| **GitHub** | https://github.com/wangzhidong2/PhysChem-DigitizerP |
| **Gitee** | https://gitee.com/wangzhidong2/PhysChem-DigitizerP/ |
| **GitCode** | https://gitcode.com/wangzhidong2/PhysChem-DigitizerP |

---

## 📧 联系方式

如有问题或建议，请提交 [GitHub Issue](https://github.com/wangzhidong2/PhysChem-DigitizerP/issues) 或 [Gitee Issue](https://gitee.com/wangzhidong2/PhysChem-DigitizerP/issues)。

---

**Happy Experimenting! 🔬📊**
