# PhysChem-DigitizerP

基于 Arduino/ESP32/ESP8266 开发的低成本理化实验数字化采集系统

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GitHub](https://img.shields.io/badge/GitHub-Repository-blue?logo=github)](https://github.com/wangzhidong2/PhysChem-DigitizerP)
[![Gitee](https://img.shields.io/badge/Gitee-Repository-red?logo=gitee)](https://gitee.com/wangzhidong2/PhysChem-DigitizerP/)

## 📖 项目简介

**PhysChem-DigitizerP** 是一个开源的物理化学实验数字化采集系统，旨在为中学和大学物理/化学实验室提供低成本、高精度的传感器解决方案。项目包含硬件（ESP32/ESP8266/Arduino）和软件（Python + PyQt6）两部分，实现了从传感器数据采集、实时可视化到数据导出的完整功能。

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
| 传感器模块 | 根据实验需求选择 | 1 | 如 HC-SR04 等 |
| 杜邦线 | 公对母 | 若干 | 根据传感器需求 |
| USB 线 | Micro-USB 或 Type-C | 1 | 数据通信和供电 |

> 💡 **成本估算**：单传感器成本 < ¥30（商业方案通常 > ¥500）

---

## 🔌 接线指南

### HC-SR04 超声波传感器接线

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

---

## 🚀 核心功能

### 硬件特性

- **主控板**：支持 ESP32 和 ESP8266（WeMOS D1 等），支持 WiFi 连接（预留功能）
- **精确测量**：支持多种传感器模块，测量精度高
- **多传感器支持**：预留温度、光电门、力传感器等接口

### 软件特性

#### ✅ 已实现功能

1. **位移测量模块**
   - 实时距离测量（精度：±0.3cm）
   - 距离 - 时间曲线实时绘制
   - 数据统计（平均值、最大值、最小值）
   - CSV 格式数据导出

2. **速度测量模块**
   - 基于连续距离测量的速度计算
   - 双图表显示（距离 - 时间、速度 - 时间）
   - 速度统计分析

3. **pH 传感器模块**
   - 三点校准功能（pH 4.00/6.86/9.18）
   - 实时 pH 值显示和曲线绘制
   - Python 程序内校准（非模块校准）
   - 数据统计（平均值、标准差）

4. **现代化界面**
   - Win11 风格设计语言
   - 侧边栏模块化导航
   - 响应式布局
   - 实时数据可视化

#### 🔧 规划中功能

- 温度传感器模块
- 光电门模块
- 力传感器模块
- WiFi 无线数据传输

---

## 📦 项目结构

```
PhysChem-DigitizerP/
├── main.py                    # Python 主程序（PyQt6 界面）
├── run.py                     # 启动脚本
├── test_serial.py             # 串口连接测试工具
├── requirements.txt           # Python 依赖包列表
├── README.md                  # 主文档（本文件）
├── README_PYTHON.md           # Python 软件详细文档
├── TROUBLESHOOTING.md         # 故障排除指南
├── .gitignore                 # Git 忽略配置
├── LICENSE                    # MIT 许可证
└── 传感器 arduino 代码/
    ├── README.md              # Arduino 代码说明
    └── 超声波位移传感器/
        ├── HC-SR04esp8266.ino # ESP8266 传感器固件
        └── HC-SR04esp32.ino   # ESP32 传感器固件
```

---

## 🛠️ 软件安装

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

# 安装依赖包
pip install -r requirements.txt
```

**依赖包说明**：
- `PyQt6>=6.4.0` - 图形界面框架
- `pyserial>=3.5` - 串口通信
- `matplotlib>=3.5.0` - 数据可视化
- `numpy>=1.21.0` - 数值计算

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

---

## 🔍 故障排除

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

### 详细故障排除

更详细的故障排除指南请查看：[TROUBLESHOOTING.md](TROUBLESHOOTING.md)

---

## 📚 技术文档

- **[Python 软件详细文档](README_PYTHON.md)** - Python 图形界面的完整使用说明
- **[Arduino 代码说明](传感器 arduino 代码/README.md)** - 传感器固件开发指南
- **[故障排除指南](TROUBLESHOOTING.md)** - 常见问题和解决方案

---

## 🔧 扩展开发

### 添加新传感器模块

项目采用模块化设计，添加新传感器非常简单：

1. **硬件层**：编写 Arduino 代码，定义数据输出格式
2. **软件层**：创建新的 `QWidget` 子类，实现数据采集和显示逻辑
3. **集成**：在 `MainWindow` 中注册新模块

详细开发指南请参考 [README_PYTHON.md](README_PYTHON.md#扩展开发)

### 支持的传感器类型（规划）

| 传感器 | 测量物理量 | 状态 |
|--------|------------|------|
| HC-SR04 超声波 | 距离/速度 | ✅ 已完成 |
| 光电门 | 时间/速度 | 🔧 开发中 |

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
```
# 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt




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
3. 查看 [故障排除指南](TROUBLESHOOTING.md)

## 🌐 项目地址

- **GitHub**: [https://github.com/wangzhidong2/PhysChem-DigitizerP](https://github.com/wangzhidong2/PhysChem-DigitizerP)
- **Gitee**: [https://gitee.com/wangzhidong2/PhysChem-DigitizerP/](https://gitee.com/wangzhidong2/PhysChem-DigitizerP/)

---

## 🌟 项目亮点

- ✅ **完全开源**：硬件设计 + 软件代码全部开源
- ✅ **低成本**：单传感器成本<¥30（商业方案通常>¥500）
- ✅ **高精度**：50Hz 采样率，±0.3cm 测量精度
- ✅ **多平台**：支持 ESP32 和 ESP8266 开发板
- ✅ **易用性**：Win11 风格现代化界面
- ✅ **可扩展**：支持多种传感器类型
- ✅ **教育友好**：适合中学和大学物理实验教学



**Happy Experimenting! 🔬📊**
