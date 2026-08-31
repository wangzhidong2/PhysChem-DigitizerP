# PhysChem-DigitizerP

基于 Arduino/ESP32与Python开发的低成本理化实验数字化采集系统
[![AtomGitStars](gitcode.com/wangzhidong2/PhysChem-DigitizerP//star/new_badge.svg)](gitcode.com/wangzhidong2/PhysChem-DigitizerP/)

[![License: GPL v3](https://img.shields.io/badge/License-GPL_v3-blue.svg)](LICENSE)
[![GitHub](https://img.shields.io/badge/GitHub-Repository-blue?logo=github)](https://github.com/wangzhidong2/PhysChem-DigitizerP)
[![Gitee](https://img.shields.io/badge/Gitee-Repository-red?logo=gitee)](https://gitee.com/wangzhidong2/PhysChem-DigitizerP/)
[![GitCode](https://img.shields.io/badge/GitCode-Repository-orange?logo=gitcode)](https://gitcode.com/wangzhidong2/PhysChem-DigitizerP)

## 1.写在前面
本项目的开源协议是GPLv3,为什么用GPLv3开源呢?因为b人也是一个开源爱好者，想把自由一直传递下去，同时我的上游库PySide6与Fluent-Widgets库也都是GPL类的。请在制作自己的分支的时候，遵守GPL相关协议，耗子尾汁哦:) 如果你的项目是商用项目，实在不想公开源代码的话，那你跟PySide6与Fluent-Widgets库商量，违反GPL,反正我不会去追究你，因为我还要上晚自习😒😒，如果跟上游库商量好之后，你想要闭源进行商用的话，跟我说一声不过分吧？要不然…我会在生日许愿时祝你电脑蓝屏:(  哦。

## 2.项目简介

**PhysChem-DigitizerP** 是一个开源的物理化学实验数字化传感器系统，目的在于为中学物理/化学实验提供低成本，可视化的传感器解决方案。项目包含硬件（ESP32/ESP8266/Arduino）和软件（Python ）两部分，实现了从传感器数据采集、实时可视化到数据导出的功能。该项目处于维护中，但鉴于本人是个高中生，没有办法及时更新，所以更新不规律。

- **低成本替代**：单传感器成本 < ¥80（商业方案通常 > ¥200）
- **开源透明**：GPL-3.0 协议，硬件设计和软件代码完全开源，同时提供我认为写的比较详细的教程
- **模块化设计**：新增传感器只需丢文件，详情参看Agents.md，同时也方便AI Agent开发
- **现代化界面**：PySide6 +Fluent-widgets库图形界面，UI美观，尽可能的复刻fluent design

![image.png](https://raw.gitcode.com/user-images/assets/9825261/1f6418ee-c7c5-48d0-948f-c704f9c59442/image.png 'image.png')

## 3.快速上手上位机
### 3.1.使用预打包文件（无需配置环境）
#### 3.1.1.在 releases 页面下载打包好的程序
![image.png](https://raw.gitcode.com/user-images/assets/9825261/b3ff419c-13e0-4858-9748-a3a51d6e1dfe/image.png 'image.png')
#### 3.1.2.解压，打开主程序
![image.png](https://raw.gitcode.com/user-images/assets/9825261/3c8e2021-48eb-4ce6-8a39-dc7cb063d59f/image.png 'image.png')
### 3.2.从源码打开（需要 python 环境，git 可选）
#### 3.2.1.[安装 python](https://www.python.org)
**注意，版本号大于3.10**
#### 3.2.2.安装库

依赖库

| 库 | 版本 | 用途 |
|----|------|------|
| **PySide6** | ≥6.4.0 | 图形界面框架 |
| **PySide6-Fluent-Widgets** | — | WinUI3 风格组件库 |
| **pyserial** | ≥3.5 | 串口通信（可选依赖，未安装时串口功能优雅降级，模拟器模式不受影响） |
| **matplotlib** | ≥3.5.0 | 数据可视化（默认绘图引擎，与 pyqtgraph 至少安装其一） |
| **pyqtgraph** | ≥0.13.0 | 高性能交互式绘图（与 matplotlib 至少安装其一） |
| **numpy** | ≥1.21.0 | 数值计算 |

```bash
pip install PySide6 numpy
# 串口通信（连接真实下位机需要；未安装时可用模拟器模式，程序不会崩溃）
pip install pyserial
# 绘图引擎（matplotlib / pyqtgraph 至少安装其一）
pip install matplotlib pyqtgraph
# WinUI3 风格组件库（必需）
pip install PySide6-Fluent-Widgets
# 可选（BLE 无线通信）:
pip install bleak
```
或者
```bash
pip install PySide6 PySide6-Fluent-Widgets numpy pyserial matplotlib pyqtgraph bleak
```
如果你所在的shell（powershell）不支持一次输入多个模块，依次输入以下命令
```powershell
pip install PySide6
pip install PySide6-Fluent-Widgets
pip install numpy
pip install pyserial
pip install pyqtgraph
pip install matplotlib
pip install bleak
```
#### 3.2.3.下载代码（如有git）
```bash
# GitHub
git clone https://github.com/wangzhidong2/PhysChem-DigitizerP.git
# Gitee
git clone https://gitee.com/wangzhidong2/PhysChem-DigitizerP.git
# GitCode（国内推荐）
git clone https://gitcode.com/wangzhidong2/PhysChem-DigitizerP.git

cd PhysChem-DigitizerP
python ./main.py
```
#### 3.2.4.或者，使用平台的源代码打包功能
##### 3.2.4.1.下载代码
![image.png](https://raw.gitcode.com/user-images/assets/9825261/e776925b-b898-4fe4-82b9-1b01bd4260e2/image.png 'image.png')
##### 3.2.4.2.解压，双击 `main.py` 打开
### 3.3.功能模块

项目采用**模块化架构**——主程序 `main.py` 启动时扫描 `传感器代码/` 目录，自动加载每个传感器的上位机模块。每个模块的 BOM 物料清单、接线指南、校准方法、计算原理和常见问题均在各自的 README 中。

| 模块 | 传感器 | 开发板 | 类别 |  说明文档 |
|------|--------|--------|------|----------|
| 超声波位移 | HC-SR04 | ESP32 / ESP8266 / ESP32-S3 | 物理 |[使用说明](传感器代码/超声波位移传感器/README.md) |
| 超声波速度 | HC-SR04 | （共享上述固件） | 物理 | [使用说明](传感器代码/超声波位移传感器/README.md) |
| pH 传感器 | SEN0161 | ESP32-S3 | 化学 | [使用说明](传感器代码/ph传感器/README.md) |
| 力/质量传感器 | HX711 | ESP32-S3 | 物理 | [使用说明](传感器代码/力传感器/README.md) |
| 电压传感器 | ESP32 ADC / HX711等AD转换模块 | ESP32-S3 | 物理 |  [使用说明](传感器代码/电压传感器/README.md) |
| 电流传感器 | ACS712 | ESP32-S3 | 物理 |  [使用说明](传感器代码/电流传感器/README.md) |

## 4.下位机固件烧录
### 4.1.安装 [Arduino IDE](https://www.arduino.cc/en/software)
### 4.2.添加开发板支持
- **ESP8266**：`http://arduino.esp8266.com/stable/package_esp8266com_index.json`

- **ESP32**：`https://dl.espressif.com/dl/package_esp32_index.json`

- **ESP32 国内镜像（推荐）**：`https://jihulab.com/esp-mirror/espressif/arduino-esp32/-/raw/gh-pages/package_esp32_index_cn.json`（[镜像使用教程](https://blog.csdn.net/2501_91081681/article/details/159542001)）
- 文件 → 首选项 → 附加开发板管理器网址 → 粘贴上述地址
- 在搜索框中输入 esp32，找到 esp32 by Espressif Systems ⚠️ 注意：下拉列表中会有多个选项，选择带有 `-cn` 后缀的版本，这是针对国内网络优化的版本。

### 4.3.选择开发板并烧录

- ESP8266：开发板选 **WeMos D1 R1**
- ESP32：开发板选 **ESP32 S3 Dev Module**
- 选择正确端口，点击上传

### 4.4.验证固件

打开串口监视器（波特率 **115200**），应看到 `START` 和 `时间戳,数值` 的数据输出。

## 5.项目结构

```
PhysChem-DigitizerP/
├── main.py                     # 主程序：FluentWindow + 主页 + 动态加载器
├── core.py                     # 公共模块：SerialThread / BLESerialThread / 配置 / 对话框 / 现代化样式
├── main_legacy.py              # 历史存档（迁移前单文件版本，不再维护）
├── test_serial.py              # 串口连接测试工具
├── sensor_config.json          # 传感器校准配置（运行时自动生成，.gitignore）
├── README.md                   # 主文档（本文件）
├── AGENTS.md                   # 开发者指南（含添加新模块教程）
├── LICENSE                     # GPL-3.0 许可证
├── docs/
│   └── images/                 # 文档图片
└── 传感器代码/                  # 下位机 .ino + 上位机 .py 同目录
    ├── README.md               # 各传感器固件与模块总览
    ├── 超声波位移传感器/
    │   ├── README.md           # 使用说明（接线/校准/原理/FAQ）
    │   ├── HC-SR04esp32.ino    # ESP32 固件
    │   ├── HC-SR04esp8266.ino  # ESP8266 固件
    │   ├── csbwithbt.ino       # ESP32-S3 + BLE 固件
    │   ├── ultrasonic_displacement.py  # 位移测量上位机模块
    │   └── ultrasonic_velocity.py      # 速度测量上位机模块
    ├── ph传感器/
    │   ├── README.md           # 使用说明（接线/多模式校准/电极保养/FAQ）
    │   ├── ph esp32.ino        # ESP32-S3 固件
    │   ├── PH传感器原理图.pdf
    │   └── ph_sensor.py        # pH 上位机模块
    ├── 力传感器/
    │   ├── README.md           # 使用说明（接线/去皮校准/串口命令/FAQ）
    │   ├── force.ino           # ESP32-S3 HX711 固件
    │   ├── force_sensor.py     # 力/质量上位机模块
    │   └── 资料（HX711称重模块商家提供的）/
    ├── 电压传感器/
    │   ├── README.md           # 使用说明（接线/分压扩展/ADC配置/FAQ）
    │   ├── ESP32_Voltage_Sensor.ino  # ESP32-S3 内置 ADC 固件
    │   ├── HX711_Voltage.ino         # HX711 24 位 ADC 固件
    │   └── voltage_sensor.py         # 电压上位机模块（支持 HX711 模式）
    └── 电流传感器/              # ACS712 电流（5A/20A/30A，AC/DC，零点校准）
        ├── ESP32_ADC_Raw_Data.ino   # ESP32-S3 固件
        └── current_sensor.py        # 电流上位机模块（5A/20A/30A 量程，AC/DC）
```

> 📖 模块加载机制、识别区格式与添加新模块的完整教程请参考 [AGENTS.md](AGENTS.md)。

## 6.使用方法

### 6.1.启动软件

```bash
python main.py
```

### 6.2.通用操作流程

1. 通过 USB 连接开发板到电脑
2. 在软件左侧选择对应传感器模块
3. 点击"刷新"选择 COM 端口，点击"连接"
4. 点击"开始采集"实时显示数据与曲线
5. 点击"停止采集"结束
6. 点击"保存数据"导出为 CSV 文件

### 6.3.切换绘图引擎

进入 **设置 → 个性化 → 图表引擎**，可在两种引擎间即时切换：

| 引擎 | 特点 |
|------|------|
| **matplotlib** |美观|
| **pyqtgraph（Default）** | GPU 加速、缩放/平移拖拽，鼠标悬停弹出标签显示时间与数值，适合数据实时监视 |

切换立即对所有传感器模块生效，已绘制的曲线自动重放到新引擎；选择会保存到配置，下次启动沿用。

### 6.4.引擎缺失时的表现（程序不会崩溃，数据采集/保存不受影响）：
- 未安装的引擎在设置页下拉框中**灰显不可点击**（标注"未安装"）
- 配置的引擎被卸载时，启动自动降级到另一个可用引擎
- 两个引擎都未安装时，图表区域显示"未检测到图表引擎"占位提示，安装后重启即可恢复绘图

### 6.5.pyserial 未安装时的表现（程序不会崩溃，模拟器/BLE 模式不受影响）：
- 启动时控制台打印缺失提示，各传感器模块自动切换到"模拟器"模式
- 串口下拉框显示"未安装 pyserial"占位；手动选择串口模式并连接时，弹窗提示安装命令 `pip install pyserial`
- 安装后重启程序即可恢复串口连接功能

> 📖 各模块的具体接线、校准步骤和实验方法请参考对应的模块 README。

## 7.故障排除

### 7.1.快速诊断

```bash
python test_serial.py
```

### 7.2.常见问题

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 找不到串口 | 驱动未安装/USB 未连接 | 安装 CH340G/CP210x 驱动，重新插拔 USB |
| 串口下拉框显示"未安装 pyserial" | pyserial 未安装 | `pip install pyserial` 后重启程序（期间可用模拟器模式） |
| 连接后无数据 | 波特率错误/固件未上传 | 确认波特率 115200，重新上传固件 |
| 数据跳变异常 | 传感器干扰/接线松动 | 检查接线，远离干扰源 |
| 图表不显示 / 显示"未检测到图表引擎" | 绘图引擎未安装 | `pip install matplotlib pyqtgraph`（至少其一）后重启 |

## 8.技术文档

- **[AGENTS.md](AGENTS.md)** — 开发者指南
- **[传感器代码总览](传感器代码/README.md)** — 各传感器固件与上位机模块对照表
- **[超声波位移传感器](传感器代码/超声波位移传感器/README.md)** 
- **[pH 传感器](传感器代码/ph传感器/README.md)** 
- **[力传感器](传感器代码/力传感器/README.md)** 
- **[电压传感器](传感器代码/电压传感器/README.md)** 
- **[电流传感器](传感器代码/电流传感器/README.md)** 

## 9.扩展开发

新增传感器**无需修改 `main.py`**，只需 2 步：

1. 在 `传感器代码/` 下新建子目录，放入 `.ino` 和 `.py`
2. 在 `.py` 文件头写识别区：

```python
# === MODULE META ===
# icon: T
# name: 温度传感器
# category: physics          # physics 或 chemistry
# class: TemperatureSensorWidget
# ===================
```

重启 `main.py` 即自动出现在侧边栏 + 主页卡片 + 内容栈。

> 📖 完整字段说明与注意事项请参考 [AGENTS.md](AGENTS.md)。

## 10.软件界面

![image.png](https://raw.gitcode.com/user-images/assets/9825261/f9f05bf8-eff3-44c9-a936-0506706a98b7/image.png 'image.png')
![image.png](https://raw.gitcode.com/user-images/assets/9825261/b33d6c6d-4ca0-4fda-916b-e172bcdd46a5/image.png 'image.png')
![image.png](https://raw.gitcode.com/user-images/assets/9825261/bb43d395-bfac-457f-b4f4-c64c6dfdf07b/image.png 'image.png')
![image.png](https://raw.gitcode.com/user-images/assets/9825261/e889a4f2-e905-4b78-ad44-3b16f0306423/image.png 'image.png')
![image.png](https://raw.gitcode.com/user-images/assets/9825261/688d7b86-ef42-4db4-a0b7-e4548eb0715e/image.png 'image.png')
![image.png](https://raw.gitcode.com/user-images/assets/9825261/f5efa7dd-d849-4b55-9987-3f4d5a8cc738/image.png 'image.png')
![image.png](https://raw.gitcode.com/user-images/assets/9825261/2079c7dc-a898-4b7e-befe-b9b0215b053b/image.png 'image.png')
![image.png](https://raw.gitcode.com/user-images/assets/9825261/fa47701f-39b1-4a8a-846f-303207164ae2/image.png 'image.png')


## 📄 许可证

本项目采用 **GNU General Public License v3.0** - 详见 [LICENSE](LICENSE) 文件

## 👥 致谢

- **硬件平台**：[ESP32](https://www.espressif.com/) / [ESP8266 Community](https://www.esp8266.com/)
- **图形界面**：[PySide6](https://www.qt.io/qt-for-python)
- **数据可视化**：[Matplotlib](https://matplotlib.org/) / [pyqtgraph](https://www.pyqtgraph.org/)
- **串口通信**：[pyserial](https://github.com/pyserial/pyserial)

## 📧 联系方式

如有问题或建议，请提交 [GitHub Issue](https://github.com/wangzhidong2/PhysChem-DigitizerP/issues) 或 [Gitcode Issue](https://gitcode.com/wangzhidong2/PhysChem-DigitizerP/issues)。

## 🌐 项目地址

- **GitHub**: [https://github.com/wangzhidong2/PhysChem-DigitizerP](https://github.com/wangzhidong2/PhysChem-DigitizerP)
- **Gitee**: [https://gitee.com/wangzhidong2/PhysChem-DigitizerP/](https://gitee.com/wangzhidong2/PhysChem-DigitizerP/)
- **GitCode**: [https://gitcode.com/wangzhidong2/PhysChem-DigitizerP](https://gitcode.com/wangzhidong2/PhysChem-DigitizerP)

---

**Happy Experimenting! 🔬📊**
