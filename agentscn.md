# agentscn.md

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

通过 Arduino IDE 烧录。开发板管理器地址：
- ESP8266: `http://arduino.esp8266.com/stable/package_esp8266com_index.json`
- ESP32: `https://dl.espressif.com/dl/package_esp32_index.json`

## 架构说明

- 单文件 Python 应用（`mainwithbt.py`，约 1500+ 行）——所有 Widget、串口线程、BLE 逻辑都在一个文件中
- 每个传感器模块对应一个 `QWidget` 子类（如 `UltrasonicWidget`、`PhSensorWidget`、`ForceSensorWidget`、`VoltageSensorWidget`）
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
