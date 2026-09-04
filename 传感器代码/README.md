# 传感器代码

本目录存放各传感器的下位机固件（`.ino`）和上位机模块（`.py`），两者在同一子目录中。上位机模块文件头带识别区（meta header），主程序 `main.py` 启动时自动扫描并加载，新增传感器不需要改主程序。

## 1.目录结构

```
传感器代码/
├── README.md                                # 本文件
├── 超声波位移传感器/                          # HC-SR04 超声波
│   ├── HC-SR04esp32.ino                     # ESP32 固件
│   ├── HC-SR04esp8266.ino                   # ESP8266 固件
│   ├── csbwithbt.ino                        # ESP32-S3 + BLE 固件
│   ├── ultrasonic_displacement.py           # 位移测量
│   └── ultrasonic_velocity.py               # 速度测量
├── ph传感器/
│   ├── ph esp32.ino                         # ESP32-S3 固件
│   └── ph_sensor.py
├── 力传感器/
│   ├── force.ino                            # ESP32-S3 固件
│   ├── force_sensor.py
│   └── 资料（HX711称重模块商家提供的）/
├── 电压传感器/
│   ├── ESP32_Voltage_Sensor.ino             # 内置 ADC
│   ├── HX711_Voltage.ino                    # HX711 24 位
│   ├── ADS1115_Voltage.ino                  # ADS1115 16 位
│   └── voltage_sensor.py
└── 电流传感器/
    ├── ESP32_ADC_Raw_Data.ino               # ESP32-S3 固件
    └── current_sensor.py
└── 电学综合/                                  # 欧姆定律 + 电功率
    ├── VI_ESP32_ADC.ino                      # 电压(内置ADC)+ACS712 一体固件
    ├── VI_ADS1115.ino                        # 电压(ADS1115 16位)+ACS712 一体固件
    ├── VI_HX711.ino                          # 电压(HX711 24位)+ACS712 一体固件
    ├── ohm_sensor.py                         # 欧姆定律（R=U/I）
    ├── power_sensor.py                       # 电功率（P=UI）
    └── README.md                             # 接线/校准说明
```

## 2.支持的传感器

| 传感器 | 型号 | 开发板 | 上位机模块 |
|--------|------|--------|-----------|
| 超声波位移 | HC-SR04 | ESP32 / ESP8266 / ESP32-S3 | `ultrasonic_displacement.py` |
| 超声波速度 | HC-SR04 | （共享上述固件） | `ultrasonic_velocity.py` |
| pH | SEN0161 | ESP32-S3 | `ph_sensor.py` |
| 力/质量 | HX711 | ESP32-S3 | `force_sensor.py` |
| 电压 | ESP32 内置 ADC / HX711 / ADS1115 | ESP32-S3 | `voltage_sensor.py` |
| 电流 | ACS712 | ESP32-S3 | `current_sensor.py` |
| 欧姆定律 | ESP32 ADC / ADS1115 / HX711 + ACS712 | ESP32-S3 | `ohm_sensor.py`（单板一体/双板分测/模拟器） |
| 电功率 | 同上 | ESP32-S3 | `power_sensor.py` |

## 3.通用约定

- 波特率：115200
- 数据格式：`时间戳,测量值`（CSV）
- 固件启动时输出一行 `START`
- 上位机模块统一从 `core.py` 导入共享组件（通信线程 / 配置 / 样式），不重复实现

## 4.添加新传感器

1. 在本目录下新建子目录，放入 `.ino` 和 `.py`
2. 在 `.py` 文件头写识别区：`icon` / `name` / `category` / `class`
3. 重启 `main.py`，模块自动出现在侧边栏和主页

更多细节见根目录 [AGENTS.md](../AGENTS.md#添加新传感器模块)。