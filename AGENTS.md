# AGENTS.md

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

Flash via Arduino IDE. Board packages:
- ESP8266: `http://arduino.esp8266.com/stable/package_esp8266com_index.json`
- ESP32: `https://dl.espressif.com/dl/package_esp32_index.json`

## Architecture notes

- Single-file Python app (`mainwithbt.py`, ~1500+ lines) — all widgets, serial threads, BLE logic in one file
- Each sensor module is a `QWidget` subclass (e.g. `UltrasonicWidget`, `PhSensorWidget`, `ForceSensorWidget`, `VoltageSensorWidget`)
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
