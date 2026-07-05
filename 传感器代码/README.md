# 传感器代码总览

此文件夹存放各种传感器的**下位机固件**（`.ino`）和**上位机模块**（`.py`），两者在同一个子目录中。上位机模块文件头带有识别区（meta header），主程序 `main.py` 启动时通过 `importlib` 自动扫描并加载。

## 📁 目录结构

```
传感器代码/
├── README.md                                # 本文件
├── 超声波位移传感器/                          # HC-SR04 超声波模块
│   ├── README.md                            # 使用说明
│   ├── HC-SR04esp32.ino                     # ESP32 固件
│   ├── HC-SR04esp8266.ino                   # ESP8266 固件
│   ├── csbwithbt.ino                        # ESP32-S3 + BLE 固件
│   ├── ultrasonic_displacement.py           # 位移测量上位机模块
│   └── ultrasonic_velocity.py               # 速度测量上位机模块
├── ph传感器/                                  # pH 传感器模块
│   ├── README.md                            # 使用说明
│   ├── ph esp32.ino                         # ESP32-S3 固件
│   ├── PH传感器原理图.pdf                     # 接线原理图
│   └── ph_sensor.py                         # pH 上位机模块
├── 力传感器/                                   # HX711 力/质量传感器模块
│   ├── README.md                            # 使用说明
│   ├── force.ino                            # ESP32-S3 固件
│   ├── force_sensor.py                      # 力/质量上位机模块
│   └── 资料（HX711称重模块商家提供的）/
├── 电压传感器/                                 # ESP32 ADC + HX711 电压采集模块
│   ├── README.md                            # 使用说明
│   ├── ESP32_Voltage_Sensor.ino             # ESP32-S3 内置 ADC 固件
│   ├── HX711_Voltage.ino                    # HX711 24 位 ADC 固件
│   └── voltage_sensor.py                    # 电压上位机模块（支持 HX711 模式）
└── 电流传感器/                                 # 仅下位机，上位机模块待添加
    └── ESP32_ADC_Raw_Data.ino               # ESP32-S3 ADC 原始数据固件
```

## 📋 支持的传感器

| 传感器 | 型号 | 支持开发板 | 上位机模块 | 状态 |
|--------|------|-----------|-----------|------|
| 超声波位移 | HC-SR04 | ESP32 / ESP8266 / ESP32-S3 | `ultrasonic_displacement.py` | ✅ 已完成 |
| 超声波速度 | HC-SR04 | （共享上述固件） | `ultrasonic_velocity.py` | ✅ 已完成 |
| pH 值检测 | SEN0161 | ESP32-S3 | `ph_sensor.py` | ✅ 已完成 |
| 力/质量测量 | HX711 | ESP32-S3 | `force_sensor.py` | ✅ 已完成 |
| 电压采集 | ESP32 内置 ADC / HX711 | ESP32-S3 | `voltage_sensor.py` | ✅ 已完成 |
| 电流采集 | ESP32 内置 ADC | ESP32-S3 | （待添加） | 🚧 待开发 |

## 🔧 通用配置

- **波特率**：115200
- **数据格式**：`时间戳,测量值`（CSV，Python 直接解析）
- **编码**：UTF-8
- **启动信号**：固件启动时输出 `START`

## 📝 添加新传感器

新增传感器**无需修改 `main.py`**，只需 2 步：

1. 在本目录下新建子目录，放入 `.ino` 和 `.py`
2. 在 `.py` 文件头写识别区（`icon` / `name` / `category` / `class`）

> 📖 完整教程请参考根目录 [AGENTS.md - 添加新传感器模块](../AGENTS.md#添加新传感器模块)。

## 📝 代码规范

1. 下位机固件使用 Arduino 标准编码风格，输出格式遵守 `时间戳,测量值`
2. 上位机模块文件名使用英文蛇形命名（如 `voltage_sensor.py`），与 PEP 8 一致
3. 上位机模块文件头**必须**包含识别区，字段名/冒号/空格写错会导致加载失败
4. 上位机模块从 `core` 导入共享代码（`SerialThread` / 配置 / Win11 样式），不要重复实现
