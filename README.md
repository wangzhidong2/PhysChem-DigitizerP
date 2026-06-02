# PhysChem-DigitizerP

基于 Arduino/ESP32/ESP8266 开发的低成本理化实验数字化采集系统

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GitHub](https://img.shields.io/badge/GitHub-Repository-blue?logo=github)](https://github.com/wangzhidong2/PhysChem-DigitizerP)
[![Gitee](https://img.shields.io/badge/Gitee-Repository-red?logo=gitee)](https://gitee.com/wangzhidong2/PhysChem-DigitizerP/)
[![GitCode](https://img.shields.io/badge/GitCode-Repository-orange?logo=gitcode)](https://gitcode.com/wangzhidong2/PhysChem-DigitizerP)

## 📦 核心依赖库

| 库 | 版本 | 用途 |
|----|------|------|
| **PyQt6** | ≥6.4.0 | 图形界面框架 |
| **pyserial** | ≥3.5 | 串口通信 |
| **matplotlib** | ≥3.5.0 | 数据可视化 |
| **numpy** | ≥1.21.0 | 数值计算 |

安装命令：
```bash
pip install PyQt6>=6.4.0 pyserial>=3.5 matplotlib>=3.5.0 numpy>=1.21.0
```

## 📖 项目简介

**PhysChem-DigitizerP** 是一个开源的物理化学实验数字化采集系统，旨在为中学物理/化学实验室提供低成本的传感器解决方案。项目包含硬件（ESP32/ESP8266/Arduino）和软件（Python + PyQt6）两部分，实现了从传感器数据采集、实时可视化到数据导出的完整功能。

<p align="center">
  <img src="docs/images/home.png" alt="主界面" width="800"/>
</p>
<p align="center">图1: 软件主界面 — 模块导航与项目概览</p>

### 🎯 项目目标

- **低成本替代**：为昂贵的商业理化实验传感器提供经济实惠的开源替代方案
- **开源透明**：所有硬件设计和软件代码完全开源，支持二次开发和定制
- **易于使用**：现代化的图形界面，直观的操作流程
- **高扩展性**：模块化设计，支持多种传感器类型的快速接入

---

## 📋 硬件准备 (BOM)

### 所需材料

| 组件 | 型号/规格 | 数量 | 备注 |
|------|-----------|------|------|
| 开发板 | ESP32 或 ESP8266 (WeMOS D1) | 1 | 推荐使用 ESP32 |
| 传感器模块 | 根据实验需求选择 | 1 | HC-SR04 / SEN0161 / HX711 等 |
| 杜邦线 | 公对母 | 若干 | 根据传感器需求 |
| USB 线 | Micro-USB 或 Type-C | 1 | 数据通信和供电 |

> 💡 **成本估算**：单传感器成本 < ¥30（商业方案通常 > ¥500）

---

## 🔌 接线指南

### HC-SR04 超声波传感器接线

> 📖 详细接线说明和注意事项请参考：[超声波位移传感器使用说明](传感器arduino代码/超声波位移传感器/README.md)

**ESP8266 (WeMOS D1) 连接：**
```
WeMOS D1          HC-SR04
─────────         ───────
5V (VIN)    →     VCC
GND         →     GND
D14 (D5)    →     TRIG
D12 (D6)    →     ECHO
```

**ESP32 连接：**
```
ESP32             HC-SR04
─────             ───────
5V (VIN)    →     VCC
GND         →     GND
GPIO 5      →     TRIG
GPIO 18     →     ECHO
```

**⚠️ 注意**：请根据具体传感器模块的电压要求连接电源引脚。

### HX711 力/质量传感器接线

> 📖 详细接线说明、校准方法和常见问题请参考：[力传感器使用说明](传感器arduino代码/力传感器/README.md)

**ESP32-S3 连接：**
```
ESP32-S3          HX711 模块
─────────         ──────────
3.3V        →     VCC
GND         →     GND
GPIO4       →     DT (DOUT)
GPIO5       →     SCK (PD_SCK)
```

**HX711 模块 ↔ 称重传感器：**
```
HX711 模块        称重传感器
─────────        ──────────
E+          →    激励正极（红色线）
E-          →    激励负极（黑色线）
A+          →    通道A正极（绿色线）
A-          →    通道A负极（白色线）
```

**⚠️ 注意**：称重传感器线序因厂家不同可能有所差异，请以传感器标注为准。

---

## 🚀 核心功能

### 硬件特性

- **主控板**：支持 ESP32 和 ESP8266（WeMOS D1 等），支持 WiFi 连接（预留功能）
- **精确测量**：支持多种传感器模块，测量精度高
- **多传感器支持**：已实现超声波位移、pH 值、力/质量传感器，预留温度、光电门等接口

### 软件特性

#### ✅ 已实现功能

1. **位移测量模块**
   - 实时距离测量（精度：±0.3cm）
   - 距离 - 时间曲线实时绘制
   - 数据统计（平均值、最大值、最小值）
   - CSV 格式数据导出

<p align="center">
  <img src="docs/images/displacement.png" alt="超声波位移" width="800"/>
</p>
<p align="center">图2: 超声波位移测量界面</p>

2. **速度测量模块**
   - 基于连续距离测量的速度计算
   - 双图表显示（距离 - 时间、速度 - 时间）
   - 速度统计分析

<p align="center">
  <img src="docs/images/velocity.png" alt="超声波速度" width="800"/>
</p>
<p align="center">图3: 超声波速度测量界面</p>

3. **pH 传感器模块**
   - 多模式校准功能（**单点 / 两点 / 三点校准**）
     - **单点校准**：使用 Nernst 理论斜率（-59mV/pH），快速粗略校准
     - **两点校准**：线性拟合，适用于一般测量场景
     - **三点校准**：二次多项式拟合，高精度测量
   - 校准模式动态切换，UI 根据所选模式自动调整
   - 支持 ADC 原始值 / 电压值输入（适配带信号调理的传感器）
   - 实时 pH 值显示和曲线绘制
   - Python 程序内校准（非模块校准）
   - 数据统计（平均值、标准差）

> 📖 详细接线、校准方法和电极保养请参考：[pH 传感器使用说明](传感器arduino代码/ph传感器/README.md)

<p align="center">
  <img src="docs/images/ph_sensor.png" alt="pH传感器" width="800"/>
</p>
<p align="center">图4: pH 传感器测量界面（含多模式校准）</p>

4. **力/质量传感器模块**
   - 基于 HX711 24位高精度 ADC 的力/质量测量
   - 去皮（TARE）功能，支持清零当前负载
   - 两点校准（空载 + 已知砝码），自动保存校准参数
   - 实时力/质量值显示和曲线绘制
   - 数据统计（平均值、最大值、最小值、标准差）
   - CSV 格式数据导出

> 📖 详细接线、校准方法和常见问题请参考：[力传感器使用说明](传感器arduino代码/力传感器/README.md)

<p align="center">
  <img src="docs/images/force.png" alt="力传感器" width="800"/>
</p>
<p align="center">图5: 力/质量传感器测量界面（含去皮与校准）</p>

5. **电压传感器模块**
   - 基于 ESP32-S3 内置 12 位 ADC 的模拟电压采集（0-3.3V）
   - 支持通过分压电阻网络扩展测量范围至更高电压
   - 实时电压值显示和曲线绘制
   - 数据统计（平均值、最大值、最小值、标准差）
   - CSV 格式数据导出
   - 支持偏移校准和增益校准

> 📖 详细接线、固件说明和扩展建议请参考：[电压传感器使用说明](传感器arduino代码/电压/README.md)

<p align="center">
  <img src="docs/images/voltage.png" alt="电压传感器" width="800"/>
</p>
<p align="center">图6: 电压传感器测量界面</p>

6. **现代化界面**
   - Win11 风格设计语言
   - 侧边栏模块化导航
   - 响应式布局
   - 实时数据可视化

#### 🔧 规划中功能

- 温度传感器模块
- 光电门模块
- WiFi 无线数据传输

---

## 📦 项目结构

```
PhysChem-DigitizerP/
├── main.py                      # Python 主程序（PyQt6 界面）
├── run.py                       # 启动脚本
├── test_serial.py               # 串口连接测试工具
├── README.md                    # 主文档（本文件）
├── .gitignore                   # Git 忽略配置
├── LICENSE                      # MIT 许可证
└── 传感器arduino代码/
    ├── README.md                # Arduino 代码说明
    ├── ESP32_ADC_Raw_Data.ino   # 通用 ADC 采集代码
    ├── 超声波位移传感器/
    │   ├── HC-SR04esp8266.ino   # ESP8266 传感器固件
    │   └── HC-SR04esp32.ino     # ESP32 传感器固件
    ├── ph传感器/
    │   ├── README.md            # pH 传感器使用说明
    │   ├── ph esp32.ino         # ESP32 pH 传感器固件
    │   └── PH传感器原理图.pdf    # 传感器接线原理图
    ├── 力传感器/
    │   ├── README.md            # 力传感器使用说明
    │   └── force.ino            # ESP32-S3 HX711 传感器固件
    └── 电压/
        ├── README.md            # 电压传感器使用说明
        └── ESP32_ADC_Raw_Data.ino   # ESP32-S3 ADC 采集固件
```

---

## 🛠️ 软件安装

### 软件特性
- **Win11 风格界面**：现代化的界面设计，符合 Windows 11 设计语言
- **侧边栏导航**：支持多个传感器模块的快速切换
- **响应式布局**：自适应窗口大小，提供良好的用户体验
- **模块化设计**：便于添加新的传感器模块

#### 1. 环境要求

- **操作系统**：Windows 10/11（推荐），macOS，Linux
- **Python 版本**：Python 3.8 或更高
- **Arduino IDE**：1.8.x 或 2.x（用于烧录固件）

#### 2. 烧录 Arduino 固件

1. 安装 Arduino IDE 并添加开发板支持：
   - **ESP8266**：添加 `http://arduino.esp8266.com/stable/package_esp8266com_index.json`
   - **ESP32**：添加 `https://dl.espressif.com/dl/package_esp32_index.json`
   - 工具 → 开发板 → 开发板管理器 → 搜索并安装

2. 上传代码：
   - 根据你的开发板选择对应的固件文件
   - ESP8266：选择开发板 **WeMos D1 R1**
   - ESP32：选择开发板 **ESP32 Dev Module**
   - 选择正确的端口（如 COM3）
   - 点击上传按钮

3. 验证固件工作：
   - 打开 Arduino IDE 串口监视器
   - 设置波特率：**115200**
   - 应看到 "START" 启动信息和数据输出

#### 3. 安装 Python 软件

```bash
# 克隆或下载项目到本地
cd PhysChem-DigitizerP

# 安装依赖包（或使用 pip install 手动安装）
pip install PyQt6>=6.4.0 pyserial>=3.5 matplotlib>=3.5.0 numpy>=1.21.0
```

---

## 💻 使用指南

### 启动软件

```bash
# 方式 1：使用启动脚本（推荐）
python run.py

# 方式 2：直接运行主程序
python main.py
```

### 操作流程

#### 1. 位移测量

1. **连接硬件**：将 ESP32/ESP8266 通过 USB 连接到电脑
2. **选择模块**：在软件左侧选择 "位移测量" 模块
3. **选择串口**：点击 "刷新" 按钮，选择对应的 COM 端口
4. **建立连接**：点击 "连接" 按钮，状态显示 "已连接"
5. **开始采集**：点击 "开始采集"，实时显示距离数据
6. **观察数据**：
   - 文本区域显示详细数据记录
   - 图表区域显示距离 - 时间曲线
   - 统计信息实时更新
7. **停止采集**：点击 "停止采集" 结束
8. **保存数据**：点击 "保存数据"，导出为 CSV 文件

#### 2. 速度测量（回声定位法）

操作流程与位移测量类似，不同之处：
- 选择 "速度测量" 模块
- 软件自动计算瞬时速度
- 显示双图表：距离 - 时间 + 速度 - 时间

### 数据格式说明

#### 串口通信协议

**输出格式**：`时间戳 (us),测量值 (us)`

**示例**：
```
123456,1450
123476,1465
123496,1440
```

#### CSV 导出格式

**位移数据** (`sensor_data_YYYYMMDD_HHMMSS.csv`)：
```csv
timestamp_ms,distance_cm
0,12.345
100,12.567
200,12.789
```

**速度数据** (`velocity_data_YYYYMMDD_HHMMSS.csv`)：
```csv
time_s,distance_cm,velocity_cm_s
0.000,12.345,
0.100,12.567,2.22
0.200,12.789,2.20
```

---

## 📐 计算原理与数学表达式

### 1. 速度测量（回声定位法）

**原理**：通过连续两次超声波回波时间的差值，结合声速和测量间隔计算物体运动速度。

**数学表达式**：

```
v = (t₀ - t₁)/2 × vₛ / [(t₁ + t₀)/2 + Δt]
```

其中：
- `t₀`：第一次回波时间 (µs)
- `t₁`：第二次回波时间 (µs)
- `Δt`：两次发射的时间间隔 (s)
- `vₛ`：声速 = 34000 cm/s

**代码实现**（参考 [main.py](file:///workspace/main.py#L632-L675)）：

```python
def calculate_velocity(self):
    # 获取最近两次测量的数据
    t0 = self.echo_time_data[-2]  # 第一次回波时间 (µs)
    t1 = self.echo_time_data[-1]  # 第二次回波时间 (µs)
    
    # 计算两次发射的时间间隔 Δt (秒)
    delta_t = 0.02  # 默认 20ms
    
    # 声速 (cm/s)
    v_sound = 34000  # 340 m/s = 34000 cm/s
    
    # 计算速度 (cm/s)
    # v = (t₀ - t₁)/2 × vₛ / [(t₁ + t₀)/2 + Δt]
    numerator = (t0 - t1) / 2.0 * v_sound
    denominator = (t1 + t0) / 2.0 + delta_t * 1000000  # 将 Δt 转换为 µs
    
    velocity_cm_s = numerator / denominator
    
    return velocity_cm_s
```

---

### 2. pH 传感器（多模式校准）

**原理**：支持单点、两点、三点三种校准模式，根据精度需求和实验条件灵活选择。

#### 校准模式说明

| 模式 | 拟合方法 | 适用场景 | 精度 |
|------|----------|----------|------|
| **单点校准** | Nernst 理论斜率（-59mV/pH） | 快速粗略校准，已知理论斜率时 | 一般 |
| **两点校准** | 线性拟合 `pH = k·ADC + b` | 一般测量场景，覆盖常用 pH 范围 | 较高 |
| **三点校准** | 二次多项式拟合 `pH = a·ADC² + b·ADC + c` | 高精度测量，非线性补偿 | 最高 |

**数学表达式**：

**单点校准**（Nernst 方程）：
```
pH = pH_ref + slope × (V - V_ref)
```
其中 `slope` 为 Nernst 理论斜率（-59.16 mV/pH @25°C）

**两点校准**（线性拟合）：
```
pH = k·ADC + b
```

**三点校准**（二次多项式拟合）：
```
pH = a·ADC² + b·ADC + c
```

其中：
- `a`、`b`、`c`：二次拟合系数（通过三点校准获得）
- `k`、`b`：线性拟合系数（通过两点校准获得）
- `ADC`：传感器输出的原始 ADC 值（0-4095），或电压值（适配信号调理传感器）

**代码实现**（参考 [main.py](file:///workspace/main.py#L1112-L1130)）：

```python
def calculate_calibration_coefficients(self):
    """根据校准点数量自动选择拟合方法"""
    ph_values = [p[0] for p in self.calibration_points]
    adc_values = [p[1] for p in self.calibration_points]
    n_points = len(ph_values)

    if n_points == 1:
        # 单点校准：使用 Nernst 理论斜率
        pass  # 使用固定斜率计算
    elif n_points == 2:
        # 两点校准：线性拟合
        coefficients = np.polyfit(adc_values, ph_values, 1)
        self.cal_coeffs = coefficients  # [k, b]
    elif n_points >= 3:
        # 三点校准：二次多项式拟合
        coefficients = np.polyfit(adc_values, ph_values, 2)
        self.cal_coeffs = coefficients  # [a, b, c]

def adc_to_ph(self, adc_value):
    """将ADC原始值转换为pH值"""
    # 根据校准模式动态选择转换公式
    ...
```

**默认校准参数**：
```python
default_calibration = [
    (4.00, 2555),   # 酸性缓冲液 (pH 4.00 → ADC 2555)
    (6.86, 2281),   # 中性缓冲液 (pH 6.86 → ADC 2281)
    (9.18, 2030)    # 碱性缓冲液 (pH 9.18 → ADC 2030)
]
```

---

### 3. 力/质量传感器（HX711 两点校准线性换算）

**原理**：使用 HX711 24位高精度 ADC 读取称重传感器的原始值，通过两点校准（空载 + 已知砝码）建立 ADC 原始值与实际质量之间的线性换算关系。

**数学表达式**：

```
质量 = (ADC - offset) × scale
```

其中：
- `offset`：空载时的 ADC 原始值（去皮偏移量）
- `scale`：校准比例系数 = 已知质量 / (加载ADC - 空载ADC)
- `ADC`：传感器输出的 24位有符号原始值

**校准步骤**：
1. 空载时记录 ADC 值作为 offset
2. 放置已知质量砝码（如 100g），记录加载 ADC 值
3. 计算 scale = 已知质量 / (加载ADC - 空载ADC)

**示例**：
```
空载 ADC = -58720
加载 100g 砝码后 ADC = -52720
ADC 差值 = -52720 - (-58720) = 6000
scale = 100 / 6000 = 0.016667
offset = -58720

当 ADC = -55720 时：
质量 = (-55720 - (-58720)) × 0.016667 = 3000 × 0.016667 = 50.0g
```

> 校准参数自动保存到 `sensor_config.json`，下次启动时自动加载。

---

## 🧪 典型应用场景

### 1. 匀速直线运动研究
- 测量小车在轨道上的运动
- 验证 s = vt 关系
- 分析运动轨迹

### 2. 匀加速直线运动
- 斜面小车实验
- 自由落体运动（需调整传感器位置）
- 计算加速度 a = Δv/Δt

### 3. 简谐振动
- 弹簧振子实验
- 单摆运动
- 分析周期和频率

### 4. 动能定理验证
- 测量不同高度下滑物体的速度
- 验证：mgh = ½mv²

### 5. 力的测量与胡克定律
- 弹簧弹力与伸长量关系验证（F = kx）
- 摩擦力测量
- 重力测量

### 6. 质量测量
- 精确称量物体质量
- 化学实验药品称量
- 密度测量（结合体积测量）

---

## 🔍 故障排除

### 问题现象
软件能打开，但无法连接传感器，无法接收数据。

### 快速诊断步骤

#### 1. 运行串口测试脚本
```bash
python test_serial.py
```
这个脚本会自动检测所有串口并测试连接状态。

#### 2. 检查硬件连接
- ✅ **USB 连接**: 确保开发板通过 USB 线正确连接到电脑
- ✅ **电源指示灯**: 开发板上的电源指示灯应该亮起
- ✅ **传感器接线**: 检查传感器模块接线是否正确

#### 3. 检查 Arduino 代码
- ✅ **代码上传**: 确认固件已正确上传到开发板
- ✅ **波特率**: 确认代码中设置的波特率为 115200

### 详细故障排除

#### 步骤 1: 验证 Arduino 代码工作

1. **使用 Arduino IDE 测试**:
   - 打开 Arduino IDE
   - 选择正确的开发板和端口
   - 打开串口监视器
   - 设置波特率为 115200
   - 观察是否能看到 "START" 和后续数据

2. **如果 Arduino IDE 能收到数据**:
   - 说明硬件和代码都正常
   - 问题在 Python 软件端

3. **如果 Arduino IDE 收不到数据**:
   - 检查硬件连接
   - 重新上传代码
   - 检查传感器模块是否正常工作

#### 步骤 2: 检查 Python 软件

1. **运行测试脚本**:
   ```bash
   python test_serial.py
   ```

2. **检查依赖包**:
   ```bash
   pip list | grep -E "(PyQt6|pyserial|matplotlib|numpy)"
   ```
   应该能看到:
   - PyQt6
   - pyserial
   - matplotlib
   - numpy

3. **检查串口权限 (Windows)**:
   - 打开设备管理器
   - 查看 "端口 (COM 和 LPT)"
   - 确认开发板对应的 COM 端口存在

#### 步骤 3: 软件操作流程

1. **启动软件**:
   ```bash
   python run.py
   ```

2. **正确操作顺序**:
   - 选择对应的传感器模块
   - 点击 "刷新" 按钮查看可用串口
   - 选择正确的 COM 端口
   - 点击 "连接" 按钮
   - 状态应显示 "已连接，等待数据..."
   - 点击 "开始采集"
   - 观察数据接收

### 常见问题及解决方案

#### 问题 1: "未检测到任何串口设备"
**原因**: USB 驱动问题或设备未识别
**解决**:
- 重新插拔 USB 线
- 检查设备管理器中的串口设备
- 安装 CH340G 驱动程序（常用）

#### 问题 2: "串口连接失败"
**原因**: 串口被占用或权限问题
**解决**:
- 关闭 Arduino IDE 和其他可能占用串口的程序
- 以管理员身份运行 Python 软件
- 重启电脑

#### 问题 3: "连接成功但无数据"
**原因**: 波特率不匹配或代码问题
**解决**:
- 确认 Arduino 代码波特率为 115200
- 检查传感器模块是否正常工作
- 在 Arduino IDE 中测试代码

#### 问题 4: "数据格式错误"
**原因**: 数据解析问题
**解决**:
- 确认数据格式正确
- 检查是否有额外的空格或特殊字符

### 常见问题速查

| 问题 | 可能原因 | 解决方案 |
|------|----------|----------|
| 找不到串口 | 驱动未安装/USB 未连接 | 安装 CH340G/CP210x 驱动，重新插拔 USB |
| 连接后无数据 | 波特率错误/固件未上传 | 确认波特率 115200，重新上传固件 |
| 数据跳变异常 | 传感器干扰/接线松动 | 检查接线，远离干扰源 |
| 图表不显示 | matplotlib 问题 | 重新安装 matplotlib |

### 诊断工具

项目提供了专用的串口测试工具：

```bash
python test_serial.py
```

该工具会：
- 自动检测所有可用串口
- 测试每个串口的连接状态
- 显示接收到的原始数据
- 提供详细的故障诊断建议

### 驱动程序安装

#### CH340G 驱动
1. 下载 CH340G 驱动程序
2. 安装驱动程序
3. 重新插拔 USB 线
4. 在设备管理器中确认设备识别

### 硬件测试

#### 测试传感器模块
1. 使用万用表测试 VCC 和 GND 电压
2. 检查信号线连接
3. 尝试更换传感器模块

#### 测试开发板
1. 上传简单的 LED 闪烁代码测试开发板
2. 检查开发板上的指示灯
3. 尝试更换 USB 线或电脑 USB 端口

### 如果以上方法都无效

1. **提供详细错误信息**:
   - 运行 `test_serial.py` 的输出
   - Python 软件中的错误提示
   - 设备管理器截图

2. **尝试替代方案**:
   - 使用不同的电脑测试
   - 尝试不同的 USB 端口
   - 使用其他串口调试工具

---

## 📚 技术文档

- **[Arduino 代码说明](传感器arduino代码/README.md)** - 传感器固件开发指南、目录结构与代码规范
- **[超声波位移传感器使用说明](传感器arduino代码/超声波位移传感器/README.md)** - HC-SR04 接线指南、固件说明、校准方法与性能优化
- **[pH 传感器使用说明](传感器arduino代码/ph传感器/README.md)** - pH 传感器接线、多模式校准步骤（单点/两点/三点）、电极保养与常见问题
- **[力传感器使用说明](传感器arduino代码/力传感器/README.md)** - HX711 力/质量传感器接线、去皮校准、数据采集与常见问题
- **[电压传感器使用说明](传感器arduino代码/电压/README.md)** - ESP32 ADC 电压采集接线指南、分压扩展方法、精度优化与常见问题

---

## 🔧 扩展开发

### 添加新传感器模块

项目采用模块化设计，添加新传感器非常简单：

1. **硬件层**：编写 Arduino 代码，定义数据输出格式
2. **软件层**：创建新的 `QWidget` 子类，实现数据采集和显示逻辑
3. **集成**：在 `MainWindow` 中注册新模块

### 示例代码结构

```python
class NewSensorWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()
    
    def init_ui(self):
        # 创建界面布局和控件
        pass

# 在主窗口中添加
new_module = NewSensorWidget()
self.content_stack.addWidget(new_module)
self.modules["新模块名称"] = new_module
```

### 支持的传感器类型（规划）

| 传感器 | 测量物理量 | 状态 |
|--------|------------|------|
| HC-SR04 超声波 | 距离/速度 | ✅ 已完成 |
| pH 传感器 | pH 值 | ✅ 已完成 |
| HX711 力传感器 | 力/质量 | ✅ 已完成 |
| ESP32 ADC 电压采集 | 电压 (0-3.3V) | ✅ 已完成 |
| 光电门 | 时间/速度 | 🔧 开发中 |

---

## 🖥️ 软件界面说明

### 主界面布局
- **左侧侧边栏**：模块选择区域
- **右侧内容区**：当前模块的功能界面

<p align="center">
  <img src="docs/images/settings.png" alt="设置界面" width="800"/>
</p>
<p align="center">图7: 设置界面 — 外观主题切换</p>

### 通用界面元素

#### 控制面板
- **串口选择**：选择连接的串口设备
- **刷新按钮**：刷新可用串口列表
- **连接/断开按钮**：控制串口连接状态
- **采样率设置**：部分模块支持调节数据采集频率

#### 实时数据显示
- **当前数据**：显示最新的测量数据
- **统计信息**：显示数据点的统计信息
- **数据记录**：显示详细的数据记录列表
- **实时图表**：显示数据曲线

#### 控制按钮
- **开始采集**：开始数据采集
- **停止采集**：停止数据采集
- **保存数据**：将数据保存为 CSV 文件
- **清除数据**：清空当前所有数据

---

## 🤝 贡献指南

欢迎贡献代码、报告问题或提出建议！

### 贡献方式

1. **提交 Issue**：报告 Bug 或提出功能建议
2. **提交 PR**：修复问题或添加新功能
3. **改进文档**：完善使用说明或添加示例
4. **硬件测试**：测试不同传感器并提供反馈

### 开发环境设置

```bash
# 克隆项目（GitHub）
git clone https://github.com/wangzhidong2/PhysChem-DigitizerP.git
cd PhysChem-DigitizerP

# 或克隆 Gitee 镜像（国内用户推荐）
git clone https://gitee.com/wangzhidong2/PhysChem-DigitizerP.git
cd PhysChem-DigitizerP

# 或克隆 GitCode 镜像
git clone https://gitcode.com/wangzhidong2/PhysChem-DigitizerP.git
cd PhysChem-DigitizerP

# 安装依赖
pip install PyQt6>=6.4.0 pyserial>=3.5 matplotlib>=3.5.0 numpy>=1.21.0
```




## 📄 许可证

本项目采用 **MIT 许可证** - 详见 [LICENSE](LICENSE) 文件

---

## 👥 致谢

- **硬件平台**：[ESP32](https://www.espressif.com/) / [ESP8266 Community](https://www.esp8266.com/)
- **图形界面**：[PyQt6](https://www.riverbankcomputing.com/software/pyqt/)
- **数据可视化**：[Matplotlib](https://matplotlib.org/)
- **串口通信**：[pyserial](https://github.com/pyserial/pyserial)

---

## 📧 联系方式

如有问题或建议，请：
1. 提交 [GitHub Issue](https://github.com/wangzhidong2/PhysChem-DigitizerP/issues)
2. 提交 [Gitee Issue](https://gitee.com/wangzhidong2/PhysChem-DigitizerP/issues)
3. 提交 [GitCode Issue](https://gitcode.com/wangzhidong2/PhysChem-DigitizerP/issues)
4. 查看本文件的故障排除章节

## 🌐 项目地址

- **GitHub**: [https://github.com/wangzhidong2/PhysChem-DigitizerP](https://github.com/wangzhidong2/PhysChem-DigitizerP)
- **Gitee**: [https://gitee.com/wangzhidong2/PhysChem-DigitizerP/](https://gitee.com/wangzhidong2/PhysChem-DigitizerP/)
- **GitCode**: [https://gitcode.com/wangzhidong2/PhysChem-DigitizerP](https://gitcode.com/wangzhidong2/PhysChem-DigitizerP)

---

## 🌟 项目亮点

- ✅ **完全开源**：硬件设计 + 软件代码全部开源
- ✅ **低成本**：单传感器成本<¥30（商业方案通常>¥500）
- ✅ **高精度**：50Hz 采样率，±0.3cm 测量精度（部分传感器）
- ✅ **多平台**：支持 ESP32 和 ESP8266 开发板
- ✅ **易用性**：Win11 风格现代化界面
- ✅ **可扩展**：支持多种传感器类型
- ✅ **教育友好**：适合中学物理实验教学



**Happy Experimenting! 🔬📊**
