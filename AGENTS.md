# 项目说明 / AGENTS.md

**[English](#english-version)** | **[中文版](#项目简介)**

---

# 中文版

## 项目简介

基于 PyQt6 的 GUI 应用 + Arduino/ESP32 固件，用于低成本物理化学实验室数据采集（传感器：超声波、pH、HX711 力传感器、电压）。采用**模块化架构**，新增传感器只需丢文件，无需修改主程序。

## 入口文件

- **Python 主程序**: `python main.py`（模块化架构，动态加载各传感器模块）
- **公共模块**: `core.py`（SerialThread / BLESerialThread / 配置管理 / 通用对话框 / 现代化样式）
- **串口诊断工具**: `python test_serial.py`
- **历史存档**: `main_legacy.py`（迁移前单文件版本，5000 行，**不再维护**，仅供对照参考）

## 安装依赖

```bash
pip install PyQt6>=6.4.0 pyserial>=3.5 matplotlib>=3.5.0 numpy>=1.21.0
# 可选（BLE 无线通信）:
pip install bleak
```

本项目没有 `requirements.txt`、`setup.py` 或 `pyproject.toml`。

## 运行与调试

- 串口波特率：**115200**（所有固件和 Python 代码中硬编码）
- 固件输出格式：`timestamp,value`（CSV），Python 直接解析
- `sensor_config.json` 存储校准参数（运行时自动创建/更新）
- Matplotlib 字体：微软雅黑（在 `core.py` 中全局设置）

## 目录结构

```
PhysChem-DigitizerP/
├── main.py                     ← 主程序：主页 + 侧边栏 + 动态加载器
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

通过 Arduino IDE 烧录。开发板管理器地址：
- ESP8266: `http://arduino.esp8266.com/stable/package_esp8266com_index.json`
- ESP32: `https://dl.espressif.com/dl/package_esp32_index.json`
- ESP32 国内镜像: `https://jihulab.com/esp-mirror/espressif/arduino-esp32/-/raw/gh-pages/package_esp32_index_cn.json`

## 架构说明

- **模块化架构**：主程序 `main.py` 启动时扫描 `传感器代码/` 目录，用 `importlib` 动态加载各模块
- **core.py**：集中存放共享代码——`SerialThread`、`BLESerialThread`、`scan_ble_devices`、`load/save_sensor_config`、`CalibrationDialog`、`SampleRateDialog`、现代化样式函数（`card_style`/`primary_btn_style`/`accent_btn_style`/`modern_combo_style`）
- **main.py**：主页（`HomePageWidget`）、侧边栏（`SidebarWidget` + `NavButton`）、设置（`SettingsWidget`）、主窗口（`MainWindow`）+ 动态加载器（`scan_modules`/`parse_module_meta`）
- UI 采用现代化风格卡片布局；侧边栏 `NavButton` 自绘图标 + 选中指示条
- 下拉框 `QComboBox` 使用 `modern_combo_style()` 统一为现代化风格
- `VoltageSensorWidget` 支持：HX711 24 位 ADC 模式（通道 A/B、增益 128/32）、kV/V/mV 单位切换、去皮（Tare）功能
- 配置持久化：`load_sensor_config()` / `save_sensor_config()` 读写 `sensor_config.json`
- 无自动化测试——`test_serial.py` 仅为手动诊断工具
- 无 CI/CD、代码检查或类型检查配置

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

from core import (
    SerialThread, load_sensor_config, save_sensor_config,
    card_style, primary_btn_style, accent_btn_style, modern_combo_style,
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

## 注意事项

- `sensor_config.json` 在 `.gitignore` 中——它是用户本地校准数据
- `.ino` 文件名含空格（如 `ph esp32.ino`），某些系统可能出问题
- Arduino 代码目录使用中文命名
- `main_legacy.py` 是迁移前单文件存档，**不再维护**，新功能请改 `main.py` + 模块文件
- 模块文件名使用英文蛇形命名（如 `voltage_sensor.py`），与 PEP 8 一致
- BLE 功能需要 `bleak`（可选依赖），未安装时会自动降级
- 动态加载依赖识别区格式严格，字段名/冒号/空格写错会导致模块加载失败

---

# English Version {#english-version}

**[English](#english-version)** | **[中文版](#项目简介)**

## What is this

PyQt6 GUI application + Arduino/ESP32 firmware for low-cost physics/chemistry lab data acquisition (sensors: ultrasonic, pH, HX711 force, voltage). Uses a **modular architecture** — adding a sensor requires only dropping a file, no changes to the main program.

## Entry points

- **Python app**: `python main.py` (modular architecture, dynamically loads sensor modules)
- **Core module**: `core.py` (SerialThread / BLESerialThread / config / dialogs / modern styles)
- **Serial diagnostics**: `python test_serial.py`
- **Legacy archive**: `main_legacy.py` (pre-refactor single-file version, 5000 lines, **no longer maintained**, kept for reference only)

## Install

```bash
pip install PyQt6>=6.4.0 pyserial>=3.5 matplotlib>=3.5.0 numpy>=1.21.0
# Optional (for BLE wireless):
pip install bleak
```

No `requirements.txt`, `setup.py`, or `pyproject.toml` exists.

## Run & debug

- Serial baud rate: **115200** (hardcoded across all firmware and Python)
- All firmware output CSV: `timestamp,value` — Python parses this directly
- `sensor_config.json` stores calibration params (auto-created/updated at runtime)
- Matplotlib font: Microsoft YaHei (set globally in `core.py`)

## Directory structure

```
PhysChem-DigitizerP/
├── main.py                     ← Main: home + sidebar + dynamic loader
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

Flash via Arduino IDE. Board packages:
- ESP8266: `http://arduino.esp8266.com/stable/package_esp8266com_index.json`
- ESP32: `https://dl.espressif.com/dl/package_esp32_index.json`
- ESP32 CN mirror: `https://jihulab.com/esp-mirror/espressif/arduino-esp32/-/raw/gh-pages/package_esp32_index_cn.json`

## Architecture notes

- **Modular architecture**: `main.py` scans `传感器代码/` at startup, dynamically loads modules via `importlib`
- **core.py**: shared code — `SerialThread`, `BLESerialThread`, `scan_ble_devices`, `load/save_sensor_config`, `CalibrationDialog`, `SampleRateDialog`, modern style functions (`card_style`/`primary_btn_style`/`accent_btn_style`/`modern_combo_style`)
- **main.py**: home (`HomePageWidget`), sidebar (`SidebarWidget` + `NavButton`), settings (`SettingsWidget`), main window (`MainWindow`) + dynamic loader (`scan_modules`/`parse_module_meta`)
- UI uses modern-style card layout; sidebar `NavButton` custom-paints icon + selection indicator
- `QComboBox` uses `modern_combo_style()` for unified modern look
- `VoltageSensorWidget` supports: HX711 24-bit ADC mode (channel A/B, gain 128/32), kV/V/mV unit switching, Tare function
- Config persistence: `load_sensor_config()` / `save_sensor_config()` write to `sensor_config.json`
- No automated tests — `test_serial.py` is a manual diagnostic tool
- No CI/CD, linting, or type-checking configured

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

from core import (
    SerialThread, load_sensor_config, save_sensor_config,
    card_style, primary_btn_style, accent_btn_style, modern_combo_style,
)

class TemperatureSensorWidget(QWidget):
    def __init__(self):
        ...
```

Restart `main.py` — the module auto-appears in sidebar + home cards + content stack.

### Meta header fields

| Field | Required | Description |
|-------|----------|-------------|
| `icon` | Yes | Icon text (e.g. `x`, `V`, `pH`), shown in sidebar and home |
| `name` | Yes | Display name (e.g. `Ultrasonic`), for sidebar and home cards |
| `category` | Yes | Category: `physics` or `chemistry`, determines home grouping |
| `class` | Yes | Main class name (e.g. `UltrasonicWidget`), must subclass `QWidget` |

## Gotchas

- `sensor_config.json` is in `.gitignore` — it's user-local calibration data
- `.ino` filenames with spaces (e.g. `ph esp32.ino`) may cause issues on some systems
- Chinese directory/file names throughout the firmware folder
- `main_legacy.py` is the pre-refactor single-file archive, **no longer maintained** — edit `main.py` + module files for new features
- Module filenames use English snake_case (e.g. `voltage_sensor.py`), per PEP 8
- BLE requires `bleak` (optional dependency) — graceful fallback if missing
- Dynamic loading depends on strict meta header format — typos in field names/colons/spaces will cause load failures
