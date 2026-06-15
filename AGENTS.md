# AGENTS.md / 项目说明

---

## [EN] What is this | [CN] 项目简介

**[EN]** PyQt6 GUI application + Arduino/ESP32 firmware for low-cost physics/chemistry lab data acquisition (sensors: ultrasonic, pH, HX711 force, voltage).

**[CN]** 基于 PyQt6 的 GUI 应用 + Arduino/ESP32 固件，用于低成本物理化学实验室数据采集（传感器：超声波、pH、HX711 力传感器、电压）。

---

## [EN] Entry points | [CN] 入口文件

- **Python app / 主程序**: `python mainwithbt.py`（the main GUI; there is no `main.py` or `run.py` despite what README says / README 中提到的 `main.py` 和 `run.py` 不存在，请用此文件）
- **Serial diagnostics / 串口诊断工具**: `python test_serial.py`

---

## [EN] Install | [CN] 安装依赖

```bash
pip install PyQt6>=6.4.0 pyserial>=3.5 matplotlib>=3.5.0 numpy>=1.21.0
# Optional / 可选（for BLE wireless / BLE 无线通信）:
pip install bleak
```

No `requirements.txt`, `setup.py`, or `pyproject.toml` exists. / 本项目没有 `requirements.txt`、`setup.py` 或 `pyproject.toml`。

---

## [EN] Run & debug | [CN] 运行与调试

- Serial baud rate / 串口波特率：**115200**（hardcoded across all firmware and Python / 所有固件和 Python 代码中硬编码）
- All firmware output CSV: `timestamp,value` — Python parses this directly / 固件输出格式：`timestamp,value`（CSV），Python 直接解析
- `sensor_config.json` stores calibration params (auto-created/updated at runtime) / 存储校准参数（运行时自动创建/更新）
- Matplotlib font: Microsoft YaHei (set globally in `mainwithbt.py`) / 字体：微软雅黑（在 `mainwithbt.py` 中全局设置）

---

## [EN] Arduino firmware | [CN] Arduino 固件

Located in `传感器arduino代码/` (Chinese directory names). Each subfolder has a `.ino` file and sensor-specific README. / 位于 `传感器arduino代码/` 目录下（中文目录名）。每个子文件夹包含 `.ino` 文件和传感器说明文档。

| Sensor / 传感器 | Board / 开发板 | File / 文件路径 |
|--------|-------|------|
| HC-SR04 ultrasonic / 超声波 | ESP32 | `传感器arduino代码/超声波位移传感器/HC-SR04esp32.ino` |
| HC-SR04 ultrasonic / 超声波 | ESP8266 | `传感器arduino代码/超声波位移传感器/HC-SR04esp8266.ino` |
| HC-SR04 + BLE | ESP32-S3 | `传感器arduino代码/超声波位移传感器/csbwithbt.ino` |
| pH (SEN0161) | ESP32-S3 | `传感器arduino代码/ph传感器/ph esp32.ino` |
| HX711 force / 力传感器 | ESP32-S3 | `传感器arduino代码/力传感器/force.ino` |
| Voltage ADC / 电压采集 | ESP32-S3 | `传感器arduino代码/电压/ESP32_Voltage_Sensor.ino` |

Flash via Arduino IDE. Board packages: / 通过 Arduino IDE 烧录。开发板管理器地址：
- ESP8266: `http://arduino.esp8266.com/stable/package_esp8266com_index.json`
- ESP32: `https://dl.espressif.com/dl/package_esp32_index.json`

---

## [EN] Architecture notes | [CN] 架构说明

- Single-file Python app (`mainwithbt.py`, ~1500+ lines) — all widgets, serial threads, BLE logic in one file / 单文件 Python 应用（约 1500+ 行）——所有 Widget、串口线程、BLE 逻辑都在一个文件中
- Each sensor module is a `QWidget` subclass (e.g. `UltrasonicWidget`, `PhSensorWidget`, `ForceSensorWidget`, `VoltageSensorWidget`) / 每个传感器模块对应一个 `QWidget` 子类
- `SerialThread` (QThread) handles USB serial; `BLESerialThread` handles BLE via `bleak` / 处理 USB 串口通信；通过 `bleak` 处理 BLE 通信
- Config persistence: `load_sensor_config()` / `save_sensor_config()` write to `sensor_config.json` / 配置持久化：读写 `sensor_config.json`
- No automated tests — `test_serial.py` is a manual diagnostic tool / 无自动化测试——仅为手动诊断工具
- No CI/CD, linting, or type-checking configured / 无 CI/CD、代码检查或类型检查配置

---

## [EN] Gotchas | [CN] 注意事项

- `sensor_config.json` is in `.gitignore` — it's user-local calibration data / 在 `.gitignore` 中——它是用户本地校准数据
- `.ino` filenames with spaces (e.g. `ph esp32.ino`) may cause issues on some systems / 文件名含空格，某些系统可能出问题
- Chinese directory/file names throughout the Arduino code folder / Arduino 代码目录使用中文命名
- README references `main.py` and `run.py` which do not exist — use `mainwithbt.py` / README 中提到的 `main.py` 和 `run.py` 实际不存在——请使用 `mainwithbt.py`
- BLE requires `bleak` (optional dependency) — graceful fallback if missing / BLE 功能需要 `bleak`（可选依赖），未安装时会自动降级
