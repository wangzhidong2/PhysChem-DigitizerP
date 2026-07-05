# 项目说明 / AGENTS.md

**[English](#english-version)** | **[中文版](#项目简介)**

---

# 中文版

## 项目简介

基于 PyQt6 的 GUI 应用 + Arduino/ESP32 固件，用于低成本物理化学实验室数据采集（传感器：超声波、pH、HX711 力传感器、电压）。

## 入口文件

- **Python 主程序**: `python mainwithbt.py`（README 中提到的 `main.py` 和 `run.py` 不存在，请用此文件）
- **串口诊断工具**: `python test_serial.py`

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
- Matplotlib 字体：微软雅黑（在 `mainwithbt.py` 中全局设置）

## Arduino 固件

位于 `传感器arduino代码/` 目录下（中文目录名）。每个子文件夹包含 `.ino` 文件和传感器说明文档。

| 传感器 | 开发板 | 文件路径 |
|--------|--------|----------|
| HC-SR04 超声波 | ESP32 | `传感器arduino代码/超声波位移传感器/HC-SR04esp32.ino` |
| HC-SR04 超声波 | ESP8266 | `传感器arduino代码/超声波位移传感器/HC-SR04esp8266.ino` |
| HC-SR04 + BLE | ESP32-S3 | `传感器arduino代码/超声波位移传感器/csbwithbt.ino` |
| pH (SEN0161) | ESP32-S3 | `传感器arduino代码/ph传感器/ph esp32.ino` |
| HX711 力传感器 | ESP32-S3 | `传感器arduino代码/力传感器/force.ino` |
| 电压采集 | ESP32-S3 | `传感器arduino代码/电压/ESP32_Voltage_Sensor.ino` |
| HX711 电压采集 | ESP32-S3 | `传感器arduino代码/HX711电压传感器/HX711_Voltage.ino` |
| 电流（ADC 原始） | ESP32-S3 | `传感器arduino代码/电流传感器/ESP32_ADC_Raw_Data.ino` |

通过 Arduino IDE 烧录。开发板管理器地址：
- ESP8266: `http://arduino.esp8266.com/stable/package_esp8266com_index.json`
- ESP32: `https://dl.espressif.com/dl/package_esp32_index.json`
- ESP32 国内镜像: `https://jihulab.com/esp-mirror/espressif/arduino-esp32/-/raw/gh-pages/package_esp32_index_cn.json`

## 架构说明

- 单文件 Python 应用（`mainwithbt.py`，约 5000 行）——所有 Widget、串口线程、BLE 逻辑都在一个文件中
- UI 采用 Windows 11 风格卡片布局；侧边栏使用自定义 `NavButton` 类（`paintEvent` 自绘图标 + 选中指示条），不再使用 `QListWidget`
- 每个传感器模块对应一个 `QWidget` 子类（如 `UltrasonicWidget`、`PhSensorWidget`、`ForceSensorWidget`、`VoltageSensorWidget`）
- `VoltageSensorWidget` 支持：HX711 24 位 ADC 模式（通道 A/B、增益 128/32）、kV/V/mV 单位切换、去皮（Tare）功能
- `SerialThread`（QThread）处理 USB 串口通信；`BLESerialThread` 通过 `bleak` 处理 BLE 通信
- 配置持久化：`load_sensor_config()` / `save_sensor_config()` 读写 `sensor_config.json`
- 无自动化测试——`test_serial.py` 仅为手动诊断工具
- 无 CI/CD、代码检查或类型检查配置

## 注意事项

- `sensor_config.json` 在 `.gitignore` 中——它是用户本地校准数据
- `.ino` 文件名含空格（如 `ph esp32.ino`），某些系统可能出问题
- Arduino 代码目录使用中文命名
- README 中提到的 `main.py` 和 `run.py` 实际不存在——请使用 `mainwithbt.py`
- BLE 功能需要 `bleak`（可选依赖），未安装时会自动降级

---

# English Version {#english-version}

**[English](#english-version)** | **[中文版](#项目简介)**

## What is this

PyQt6 GUI application + Arduino/ESP32 firmware for low-cost physics/chemistry lab data acquisition (sensors: ultrasonic, pH, HX711 force, voltage).

## Entry points

- **Python app**: `python mainwithbt.py` (the main GUI; there is no `main.py` or `run.py` despite what README says)
- **Serial diagnostics**: `python test_serial.py`

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
- Matplotlib font: Microsoft YaHei (set globally in `mainwithbt.py`)

## Arduino firmware

Located in `传感器arduino代码/` (Chinese directory names). Each subfolder has a `.ino` file and sensor-specific README.

| Sensor | Board | File |
|--------|-------|------|
| HC-SR04 ultrasonic | ESP32 | `传感器arduino代码/超声波位移传感器/HC-SR04esp32.ino` |
| HC-SR04 ultrasonic | ESP8266 | `传感器arduino代码/超声波位移传感器/HC-SR04esp8266.ino` |
| HC-SR04 + BLE | ESP32-S3 | `传感器arduino代码/超声波位移传感器/csbwithbt.ino` |
| pH (SEN0161) | ESP32-S3 | `传感器arduino代码/ph传感器/ph esp32.ino` |
| HX711 force | ESP32-S3 | `传感器arduino代码/力传感器/force.ino` |
| Voltage ADC | ESP32-S3 | `传感器arduino代码/电压/ESP32_Voltage_Sensor.ino` |
| HX711 voltage | ESP32-S3 | `传感器arduino代码/HX711电压传感器/HX711_Voltage.ino` |
| Current (raw ADC) | ESP32-S3 | `传感器arduino代码/电流传感器/ESP32_ADC_Raw_Data.ino` |

Flash via Arduino IDE. Board packages:
- ESP8266: `http://arduino.esp8266.com/stable/package_esp8266com_index.json`
- ESP32: `https://dl.espressif.com/dl/package_esp32_index.json`
- ESP32 CN mirror: `https://jihulab.com/esp-mirror/espressif/arduino-esp32/-/raw/gh-pages/package_esp32_index_cn.json`

## Architecture notes

- Single-file Python app (`mainwithbt.py`, ~5000 lines) — all widgets, serial threads, BLE logic in one file
- UI uses Windows 11-style card layout; sidebar is built on a custom `NavButton` class (custom `paintEvent` for icon + selection indicator), no longer `QListWidget`
- Each sensor module is a `QWidget` subclass (e.g. `UltrasonicWidget`, `PhSensorWidget`, `ForceSensorWidget`, `VoltageSensorWidget`)
- `VoltageSensorWidget` supports: HX711 24-bit ADC mode (channel A/B, gain 128/32), kV/V/mV unit switching, Tare function
- `SerialThread` (QThread) handles USB serial; `BLESerialThread` handles BLE via `bleak`
- Config persistence: `load_sensor_config()` / `save_sensor_config()` write to `sensor_config.json`
- No automated tests — `test_serial.py` is a manual diagnostic tool
- No CI/CD, linting, or type-checking configured

## Gotchas

- `sensor_config.json` is in `.gitignore` — it's user-local calibration data
- `.ino` filenames with spaces (e.g. `ph esp32.ino`) may cause issues on some systems
- Chinese directory/file names throughout the Arduino code folder
- README references `main.py` and `run.py` which do not exist — use `mainwithbt.py`
- BLE requires `bleak` (optional dependency) — graceful fallback if missing
