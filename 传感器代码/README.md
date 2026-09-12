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
└── 电学综合/                                  # 欧姆定律 + 电功率（上位机模块开发中）
    ├── VI_ESP32_ADC.ino                      # 电压(内置ADC)+ACS712 一体固件
    ├── VI_ADS1115.ino                        # 电压(ADS1115 16位)+ACS712 一体固件
    ├── VI_HX711.ino                          # 电压(HX711 24位)+ACS712 一体固件
    ├── V_*.ino / I_ACS712.ino                # 双板分测单通道副本
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
| 欧姆定律 | ESP32 ADC / ADS1115 / HX711 + ACS712 | ESP32-S3 | `ohm_sensor.py`（电压/电流独立连接板块：模拟器·串口任意混搭、一体 VI_* 或双板） |
| 电功率 | 同上 | ESP32-S3 | `power_sensor.py`（同上） |

## 3.通用约定

- 波特率：115200
- 数据格式：`时间戳,测量值`（CSV）
- 固件启动时输出一行 `START`
- 上位机模块统一从 `core.py` 导入共享组件（通信线程 / 配置 / 样式），不重复实现

## 4.上位机通用功能

### 4.1.图表引擎

设置页里能换图表引擎，换完已画的曲线自动重画，不用重新采集：

| 引擎 | 特点 |
|------|------|
| **pyqtgraph（默认）** | 能缩放拖动，鼠标放上去显示数值，实时监视用它最合适；图表分析面板也只有它有 |
| matplotlib | 出图好看，但没有分析面板 |

### 4.2.图表分析

图表卡左侧是分析栏，pyqtgraph 才有：

- 视图窗口：显示整个范围 / 滚动窗口，滚动窗口把 x 轴锁在最近 N 秒
- 曲线拟合：线性、二次、三次、对数、幂函数五种，拟合线用同色虚线画出来，方程和 R² 直接标在图上，定义域外的点不参与
- 离群点剔除：重新拟合后把残差最大的前 x% 点（默认 5%）去掉，剔错了能多级撤销，原始数据不受影响
- 清除离散点：清掉拟合时叠的散点层，换个拟合方式就恢复

## 5.添加新传感器

1. 在本目录下新建子目录，放入 `.ino` 和 `.py`
2. 在 `.py` 文件头写识别区：`icon` / `name` / `category` / `class`
3. 重启 `main.py`，模块自动出现在侧边栏和主页

更多细节见根目录 [AGENTS.md](../AGENTS.md#添加新传感器模块)。