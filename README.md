![Screenshot_20260901_222222.jpg](https://gitcode.com/wangzhidong2/PhysChem-DigitizerP/blob/main/docs/images/icon.svg)
# PhysChem-DigitizerP

基于 Arduino/ESP32与Python开发的低成本理化实验数字化采集系统
![image.png](https://raw.gitcode.com/user-images/assets/9825261/8b40706c-3ba8-4e17-bb6f-1860efdb9a05/image.png 'image.png')

[![AtomGitStars](https://www.gitcode.com/wangzhidong2/PhysChem-DigitizerP/star/new_badge.svg)](https://www.gitcode.com/wangzhidong2/PhysChem-DigitizerP/)

[![License: GPL v3](https://img.shields.io/badge/License-GPL_v3-blue.svg)](LICENSE)
[![GitHub](https://img.shields.io/badge/GitHub-Repository-blue?logo=github)](https://github.com/wangzhidong2/PhysChem-DigitizerP)
[![Gitee](https://img.shields.io/badge/Gitee-Repository-red?logo=gitee)](https://gitee.com/wangzhidong2/PhysChem-DigitizerP/)
[![GitCode](https://img.shields.io/badge/GitCode-Repository-orange?logo=gitcode)](https://gitcode.com/wangzhidong2/PhysChem-DigitizerP)

>## 1.写在前面
>雷军：“一个小时后，动手能力强的MIUI负责人洪锋便做好一台净化器——他仅在家中的电风扇里面挂了三层过滤网。”

>同样。在我看来，传感器就是一堆基本元器件加上软件与算法。

>本项目的开源协议是`GPLv3`,为什么用GPLv3开源呢?因为b人也是一个开源爱好者，想把自由一直传递下去，同时我的上游库`PySide6`与`Fluent-Widgets`库也都是GPL类的。请在制作自己的分支的时候，遵守GPL相关协议，耗子尾汁哦:) 如果你的项目是商用项目，实在不想公开源代码的话，那你跟PySide6与Fluent-Widgets库商量，违反GPL,(你的胆子真是肥嘟嘟的)，反正我不会去追究你，因为我还要上晚自习😒😒，如果跟上游库商量好之后，你想要闭源进行商用的话，跟我说一声不过分吧？要不然…我会在生日许愿时祝你电脑蓝屏:(  哦。

## 2.项目简介

**PhysChem-DigitizerP** 是一个开源的物理化学实验数字化传感器系统，目的在于为中学物理/化学实验提供低成本，可视化的传感器解决方案。项目包含硬件（`ESP32/ESP8266/Arduino`）和软件（`Python `）两部分，实现了从传感器数据采集、实时可视化到数据导出的功能。该项目处于维护中，但鉴于本人是个高中生，没有办法及时更新，所以更新不规律。

- **低成本替代**：单传感器成本 < ¥80（商业方案通常 > ¥200）
- **开源透明**：`GPL-3.0` 协议，硬件设计和软件代码完全开源，同时提供我认为写的比较详细的教程
- **模块化设计**：新增传感器只需丢文件，详情参看`Agents.md`，同时也方便AI Agent开发
- **现代化界面**：`PySide6 `+`Fluent-widgets`库图形界面，UI美观，尽可能的复刻`fluent design`；**字体可换**（内嵌 MiSans，也可从系统字体里任选，见 6.9）
- **数据接口**：可选插件把数据开放给 **AI Agent**（REST / MCP）与**浏览器仪表盘**，手机也能看（见 6.10）

![image.png](https://raw.gitcode.com/user-images/assets/9825261/5e684b3a-bff0-4c48-8284-f5a23525a62a/image.png 'image.png')
## 3.快速上手上位机
### 3.1.使用预打包文件（无需配置环境）
#### 3.1.1.在 releases 页面下载打包好的程序
[AtomGit](https://gitcode.com/wangzhidong2/PhysChem-DigitizerP/releases/)
[GitHub](https://github.com/wangzhidong2/PhysChem-DigitizerP/releases/)
![image.png](https://raw.gitcode.com/user-images/assets/9825261/b3ff419c-13e0-4858-9748-a3a51d6e1dfe/image.png 'image.png')
#### 3.1.2.解压，打开主程序
![image.png](https://raw.gitcode.com/user-images/assets/9825261/3c8e2021-48eb-4ce6-8a39-dc7cb063d59f/image.png 'image.png')
### 3.2.从源码打开（需要 python 环境，git 可选）
#### 3.2.1.[安装 python](https://www.python.org/downloads/)
**注意，版本号大于3.10**
#### 3.2.2.创建虚拟环境（推荐）

虚拟环境可以避免与系统 Python 的库版本冲突，也便于随时重建/卸载依赖。在项目根目录执行：

```powershell
# Windows（PowerShell / CMD）
python -m venv .venv
.\.venv\Scripts\Activate.ps1     # PowerShell 激活虚拟环境
# 若提示“禁止运行脚本”，先执行：Set-ExecutionPolicy -Scope Process Bypass
# CMD 用户改用：.venv\Scripts\activate.bat
```

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

激活成功后终端提示符前会出现 `(.venv)`，之后的 `pip` / `python` 都作用于该环境；输入 `deactivate` 可退出。`.venv/` 已在 `.gitignore` 中，不会被提交。

> 不想用虚拟环境也可以跳过本节，直接在系统 Python 上安装依赖（效果相同，只是库会装到全局）。

#### 3.2.3.安装库

依赖库

| 库 | 版本 | 用途 |
|----|------|------|
| **PySide6** | ≥6.4.0 | 图形界面框架 |
| **PySide6-Fluent-Widgets** | — | WinUI3 风格组件库 |
| **pyserial** | ≥3.5 | 串口通信（可选依赖，未安装时串口功能优雅降级，模拟器模式不受影响） |
| **matplotlib** | ≥3.5.0 | 数据可视化（默认绘图引擎，与 pyqtgraph 至少安装其一） |
| **pyqtgraph** | ≥0.13.0 | 高性能交互式绘图（与 matplotlib 至少安装其一） |
| **numpy** | ≥1.21.0 | 数值计算 |
| **flask** | ≥3.0 | 数据接口插件 flaskserver/（可选依赖，未安装时主页「数据接口」卡片灰显，程序照常运行） |

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
# 可选（数据接口插件 flaskserver/，供 AI Agent / 浏览器仪表盘）:
pip install flask
```
或者
```bash
pip install PySide6 PySide6-Fluent-Widgets numpy pyserial matplotlib pyqtgraph bleak flask
```
或者，项目根目录已提供[requirements.txt](requirements.txt)，包含所有必需与可选依赖。
在项目根目录（即 `main.py` 所在目录）打开终端，执行：
```bash
pip install -r requirements.txt
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
pip install flask
```
#### 3.2.4.用 uv 一键管理环境（推荐，可选）

项目根目录已提供 `pyproject.toml`（依赖清单）。如果你用 [uv](https://docs.astral.sh/uv/)（Rust 写的极速 Python 包管理器），**不必手工建虚拟环境、也不必逐条 pip**——一条命令搞定：

```bash
# 安装 uv（任选其一）
winget install --id=astral-sh.uv -e          # Windows
pip install uv                                # 已有 Python 时最省事
# macOS / Linux: curl -LsSf https://astral.sh/uv/install.sh | sh

uv sync          # 自动下载 Python（若需要）+ 创建 .venv + 按 uv.lock 精确安装依赖
uv run main.py   # 启动主程序（自动使用项目环境，无需手动激活）
```

要点：

- **`uv sync` 会自动生成 `uv.lock` 锁文件**（记录每个依赖的精确版本），提交到仓库后，其他人和 CI 都能装出**完全一致**的环境，不会出现“我这儿能跑你那儿报错”。
- **`uv run <命令>`** 不用先 `activate`，它临时把项目环境放到最前面执行命令，例如 `uv run test_serial.py`、`uv run python -c "import PySide6"`。
- **默认走清华 PyPI 镜像**（写在 `pyproject.toml` 的 `[[tool.uv.index]]`），国内无需再加 `-i`。海外网络想换回官方源：`uv sync --default-index https://pypi.org/simple`。
- **打包工具单独分组**：`uv sync` 默认会装 `dev` 组里的 PyInstaller；要纯净的运行时环境用 `uv sync --no-dev`。
- 想升级依赖版本：`uv lock --upgrade` 后重新 `uv sync`。
- 项目是「脚本式应用」而非可安装的包，`pyproject.toml` 里已用 `[tool.uv] package = false` 声明，因此 `uv build` 会被跳过——打包仍走 `PhysChem-DigitizerP.spec`：

```bash
uv sync                       # 确保 dev 组（PyInstaller）已装
uv run pyinstaller --noconfirm PhysChem-DigitizerP.spec
```

- **`uv` 与 `pip` 可以共存**：不想用 uv 时，`pip install -r requirements.txt` 的老流程完全不受影响（`requirements.txt` 会继续保留）。
- 注意在**项目根目录**（即 `main.py` 所在目录）执行 `uv sync` / `uv run`——程序的 `sensor_config.json`、`app_config.json`、`logs.json` 都以 `main.py` 所在目录为基准路径。

#### 3.2.5.下载代码（如有git）
```bash
# GitHub
git clone https://github.com/wangzhidong2/PhysChem-DigitizerP.git
# Gitee
git clone https://gitee.com/wangzhidong2/PhysChem-DigitizerP.git
# GitCode（国内推荐）
git clone https://gitcode.com/wangzhidong2/PhysChem-DigitizerP.git

cd PhysChem-DigitizerP
# 使用虚拟环境时先激活（Windows PowerShell；macOS/Linux 用 source .venv/bin/activate）
.\.venv\Scripts\Activate.ps1
python ./main.py
```
#### 3.2.6.或者，使用平台的源代码打包功能
##### 3.2.6.1.下载代码
![image.png](https://raw.gitcode.com/user-images/assets/9825261/e776925b-b898-4fe4-82b9-1b01bd4260e2/image.png 'image.png')
##### 3.2.6.2.解压，双击 `main.py` 打开
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
| 欧姆定律 | ESP32 ADC / ADS1115 / HX711 + ACS712（一体或双板） | ESP32-S3 | 物理 | [使用说明](传感器代码/电学综合/README.md) |
| 电功率 | 同上 | ESP32-S3 | 物理 | [使用说明](传感器代码/电学综合/README.md) |

## 4.下位机固件烧录
### 4.1.安装 [Arduino IDE](https://www.arduino.cc/en/software)
### 4.2.添加开发板支持
- **ESP8266**：`http://arduino.esp8266.com/stable/package_esp8266com_index.json`

- **ESP32**：`https://dl.espressif.com/dl/package_esp32_index.json`

- **ESP32 国内镜像（推荐）**：`https://jihulab.com/esp-mirror/espressif/arduino-esp32/-/raw/gh-pages/package_esp32_index_cn.json`（[镜像使用教程](https://blog.csdn.net/2501_91081681/article/details/159542001)）
- 文件 → 首选项 → 附加开发板管理器网址 → 粘贴上述地址
- 在搜索框中输入 `esp32`，找到 `esp32 by Espressif Systems` ⚠️ 注意：下拉列表中会有多个选项，选择带有 `-cn` 后缀的版本，这是针对国内网络优化的版本。

### 4.3.选择开发板并烧录

- ESP8266：开发板选 `WeMos D1 R1`
- ESP32：开发板选 `ESP32 S3 Dev Module`
- 选择正确端口，点击上传

### 4.4.验证固件

打开串口监视器（波特率 **115200**），应看到 `START` 和 `时间戳,数值` 的数据输出。

## 5.项目结构

```
PhysChem-DigitizerP/
├── main.py                     # 主程序：FluentWindow + 主页 + 动态加载器
├── core.py                     # 公共模块：通信线程 / 配置 / 图表分析（拟合/离群点剔除）/ 对话框 / AI 分析 / 字体 / 现代样式
├── test_serial.py              # 串口连接测试工具
├── sensor_config.json          # 传感器校准配置（运行时自动生成，.gitignore）
├── app_config.json             # 应用配置（主题/字体/引擎/置顶/日志等，运行时生成，.gitignore）
├── logs.json                   # 运行日志（JSON Lines，默认开启记录，.gitignore）
├── requirements.txt            # 依赖清单（pip install -r requirements.txt）
├── pyproject.toml              # PEP 621 依赖清单 + uv 配置（uv sync / uv run；首次 uv sync 会生成 uv.lock）
├── CONTRIBUTING.md             # 贡献指南
├── PhysChem-DigitizerP.spec    # PyInstaller 打包配置
├── .venv/                      # 虚拟环境（可选，.gitignore；创建方法见 3.2.2）
├── README.md                   # 主文档（本文件）
├── AGENTS.md                   # 开发者指南（含添加新模块教程）
├── LICENSE                     # GPL-3.0 许可证
├── assets/
│   └── fonts/                  # 内嵌字体（随程序分发，见 6.9）
│       ├── MiSans-Regular.ttf              # 桌面端默认字体（小米 MiSans）
│       ├── HarmonyOS_Sans_SC_Regular.ttf   # 可选内嵌字体（华为 HarmonyOS Sans SC）
│       ├── HarmonyOS_Sans_SC_Regular.woff2 # 同上，网页仪表盘专用（体积约为 TTF 一半）
│       └── HarmonyOS_Sans_SC_LICENSE.txt   # 华为字体许可证（随字体分发所必需）
├── flaskserver/                # 数据接口插件（HTTP + 浏览器仪表盘 + MCP，见 6.10）
│   ├── __init__.py             # 插件生命周期（启停/密钥/可用性探测）
│   ├── server.py               # Flask 路由：REST API + 字体托管 + 静态仪表盘
│   ├── mcp_server.py           # MCP stdio 代理（供 AI Agent 调用，需单独装 mcp）
│   ├── README.md               # 插件接口文档（端点一览 / curl 示例 / MCP 配置）
│   └── web/                    # 仪表盘前端（零构建、零 CDN，离线可用）
│       ├── index.html          # 桌面式界面骨架
│       ├── style.css           # 样式（字体由 --app-font 变量驱动）
│       ├── app.js              # 前端逻辑（窗口/任务栏/密钥/字体设置）
│       └── echarts.min.js      # 图表库（本地内置，不联网）
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
    │   ├── ADS1115_Voltage.ino       # ADS1115 16 位 ADC 固件
    │   └── voltage_sensor.py         # 电压上位机模块（支持 HX711 / ADS1115 模式）
    └── 电流传感器/              # ACS712 电流（5A/20A/30A，AC/DC，零点校准/去皮）
        ├── ESP32_ADC_Raw_Data.ino   # ESP32-S3 固件
        └── current_sensor.py        # 电流上位机模块（5A/20A/30A 量程，AC/DC）
    └── 电学综合/                # 欧姆定律 + 电功率（上位机模块开发中）
        ├── README.md               # 使用说明（接线/校准/双板接线）
        ├── VI_ESP32_ADC.ino        # 电压(内置ADC)+ACS712电流 一体固件
        ├── VI_ADS1115.ino          # 电压(ADS1115 16位)+ACS712电流 一体固件
        ├── VI_HX711.ino            # 电压(HX711 24位)+ACS712电流 一体固件
        └── V_*.ino / I_ACS712.ino  # 双板分测单通道副本（电压/电流各一板）
```

> 模块加载机制、识别区格式与添加新模块的完整教程请参考 [AGENTS.md](AGENTS.md)。

## 6.使用方法

### 6.1.启动软件

```bash
python main.py
```

### 6.2.通用操作流程

1. 通过 USB 连接开发板到电脑
2. 在软件左侧选择对应传感器模块
3. 点击"刷新"选择 COM 端口，点击"连接"
4. （可选）**去皮 / 零点校准**：连接后即有实时数据，不必先开始采集。力传感器在"校准与去皮"卡、电压传感器在图表卡左侧、电流传感器在"ACS712 参数"卡（设置区）内，点一下就以当前读数归零；**可以反复点**，每次都以最新读数重新归零、不会叠加，用来消除零点漂移很顺手
5. 点击"开始采集"实时显示数据与曲线
6. 点击"停止采集"结束
7. 点击"保存数据"导出为 CSV 文件

> 想去掉漂移或换量程后重新归零，随时再点一次"去皮"即可；已有数据会按新零点自动重算，曲线同步归零。

### 6.3.切换绘图引擎

进入 **设置 → 个性化 → 图表引擎** 切换，换完之后已经画出来的曲线会自动重画，不用重新采集；选择存在配置里，下次启动还是这个引擎。

| 引擎 | 特点 |
|------|------|
| **pyqtgraph（默认）** | 能缩放拖动，鼠标放上去显示数值，实时监视用它最合适；图表分析面板也只有它有 |
| matplotlib | 出图好看，但没有分析面板（主要是我懒，懒得搞了，哈哈） |

### 6.4.图表分析

图表卡左侧有个分析栏，pyqtgraph 下才会出现，matplotlib 下没有。里面这几项：

- 视图窗口：选"显示整个范围"或"滚动窗口"，滚动窗口只留最近 N 秒的数据，0.1 秒到 3 小时都能填
- 曲线拟合：线性、二次、三次、对数、幂函数五种，拟合线用同色虚线叠在图上，方程和 R² 标在左上角，R² 越接近 1 说明拟合得越准；定义域外的点不参与
- 离群点剔除：在当前数据上重新拟合，去掉残差最大的前 x%（默认 5%），剔错了可以多级撤销；只影响显示和拟合，原始数据不动
- 清除离散点：把拟合时叠的散点层清掉，重新选一个拟合方式就恢复

### 6.5.引擎缺失时的表现（程序不会崩溃，数据采集/保存不受影响）：
- 未安装的引擎在设置页下拉框中**灰显不可点击**（标注"未安装"）
- 配置的引擎被卸载时，启动自动降级到另一个可用引擎
- 两个引擎都未安装时，图表区域显示"未检测到图表引擎"占位提示，安装后重启即可恢复绘图

### 6.6.pyserial 未安装时的表现（程序不会崩溃，模拟器/BLE 模式不受影响）：
- 启动时控制台打印缺失提示，各传感器模块自动切换到"模拟器"模式
- 串口下拉框显示"未安装 pyserial"占位；手动选择串口模式并连接时，弹窗提示安装命令 `pip install pyserial`
- 安装后重启程序即可恢复串口连接功能

### 6.7.AI 分析实验。
>后面我想搞MCP，让OpenCode，DSH等等agent调用，不过还有一段时间。对话式AI肯定不如Agent框架。

采集到数据后，点击图表卡右上角「**AI分析实验**」，可填写本次实验的**实验名称、实验目的、实验条件与备注（均为选填，留空直接开始）**——信息按模块记住，下次进入自动预填；确认后进入对话窗口：

- 每轮提问自动附带当前最新数据与实验参数，可直接问：总结趋势、判断异常点、推荐拟合函数、分析误差来源、给出改进建议
- AI 回复按 **Markdown 富文本**渲染（标题 / 列表 / 粗体 / 代码 / 表格 / 链接），链接点击仅放行 http/https；用户输入保持原文显示
- 每个传感器模块内置**专属系统提示词**（测量原理 / 数据特征 / 误差来源 / 分析要求），可在窗口「设置 → **模块预置系统提示词**」中查看并修改（仅对当前模块生效，「恢复默认」还原内置内容）
- 窗口右上角「设置」配置 API 端点 / Key / 模型（任意 OpenAI 兼容 `/chat/completions` 端点，如 DeepSeek、通义、本地 Ollama），可调温度、最大输出、数据行上限与自定义提示词
- 「实验信息」可随时修改本次实验信息，「同步数据」「清空对话」管理会话

> 数据只发送到你自己配置的端点；未配置端点时可在窗口内点击「设置」填写。

> 各模块的具体接线、校准步骤和实验方法请参考对应的模块 README。

### 6.8.运行日志（排障用）

运行日志**始终在控制台显示**（启动信息、模块加载、配置读写、连接/采集/校准等提示照常输出）；**设置 → 个性化 → 运行日志**开关（**默认开启**）决定是否同时写入项目目录下的 `logs.json`（JSON Lines 格式，每行一个 JSON 对象，跨次运行追加）。

![image.png](https://raw.gitcode.com/user-images/assets/9825261/3211fb3d-8d7c-41de-9d1e-531a1c0d4999/image.png 'image.png')
![image.png](https://raw.gitcode.com/user-images/assets/9825261/4d512b66-a5de-4b75-b9e0-03ed314908d9/image.png 'image.png')

- **详细度**（同时作用于控制台与日志文件，默认「标准」）：
  - 简略：只记录警告与错误（连接失败、依赖缺失等）
  - 标准（默认）：记录应用事件（模块加载、连接/断开、开始/停止采集、校准、保存/清空、引擎切换、AI 请求等）
  - 详细：再记录串口原始数据等调试信息（数据量大，长采集时建议配合上限）
- **最大条数**：`logs.json` 最多保留的记录条数（默认 5000），超出后自动裁剪最旧记录
- 「打开日志」按钮用系统默认程序打开 `logs.json`（未开启或尚无记录时弹提示）
- 控制台输出带 `[时:分:秒.毫秒] [级别] 模块` 前缀；`logs.json` 与 `sensor_config.json` 一样是本机运行数据，已在 `.gitignore` 中忽略

### 6.9.应用字体（可自定义，含内嵌字体）

界面默认使用**内嵌的 MiSans 字体**（assets/fonts/MiSans-Regular.ttf，小米出品，免费商用）。字体会随程序一起分发并在启动时注册进 Qt，所以**换电脑、换系统都不依赖本机装过该字体**，显示效果始终一致。

想换字体：进入 **设置 → 外观 → 应用字体 → 「选择…」**，会打开一个仿 Word 的字体选择器——列出系统里**已安装的全部字体**（Qt 直接给出中文名，如微软雅黑／宋体／楷体／隶书），每条用**该字体自身的字形**渲染，支持搜索与实时预览。选中即生效，无需重启，并写入 `app_config.json` 的 `General.FontFamily` 下次沿用。
![image.png](https://raw.gitcode.com/user-images/assets/9825261/f5188488-b8ca-4ac2-a398-33310a63c837/image.png 'image.png')
> - 除 MiSans 外还内嵌了 **HarmonyOS Sans SC**（华为，含许可证），在字体选择器里带「（内嵌）」标记，属于"任何机器上都有"的稳妥选择。
>   ⚠️ 注意必须用 **SC** 版本：`HarmonyOS_Sans/` 目录下的 `HarmonyOS_Sans_Regular.ttf` 是纯拉丁面（仅 874 个码位、不含任何汉字），拿它当中文字体会整片回退到系统字体。
> - **数据记录区与原始数据读数固定使用等宽字体**（Cascadia Code），不随此项切换——等宽才能保证数字对齐。
> - 图表坐标轴文字会跟随新字体重绘。

### 6.10.数据接口与浏览器仪表盘（flaskserver）
![image.png](https://raw.gitcode.com/user-images/assets/9825261/f90dec07-d72d-49e6-b33b-defa0a472f4f/image.png 'image.png')
把实验数据开放给 **AI Agent**（REST / MCP）与**浏览器仪表盘**。这是**可选插件**：删掉整个 `flaskserver/` 目录，主程序行为完全不变（主页卡片消失、不占端口）。
**开启**：主页 →「数据接口」卡片 →「打开…」→ 打开「数据接口」开关（默认监听 `http://127.0.0.1:8765`）；浏览器访问该地址即为实时仪表盘，首次开启自动生成访问密钥。
![image.png](https://raw.gitcode.com/user-images/assets/9825261/55356cfd-de46-44d8-bc32-f472ef38535a/image.png 'image.png')
![QQ_1791700657467.png](https://raw.gitcode.com/user-images/assets/9825261/11b6548a-4571-489c-afa3-8a1a1d7778d3/QQ_1791700657467.png 'QQ_1791700657467.png')
| 能力 | 说明 |
|------|------|
| **浏览器仪表盘** | 桌面式界面（窗口／任务栏／开始菜单），实时曲线、模块控制、连接管理（串口／模拟器／蓝牙，与主程序复用同一套逻辑） |
| **仪表盘登录** | 开启鉴权后先显示登录页，输对密钥才进桌面；登录后地址栏自动带 `?token=`，刷新或分享链接可直接进入 |
| **REST API** | `/api/health`、`/api/modules`、`/api/modules/<key>`、`/series`、`/export.csv`，以及 `collect`／`command`／`params` 控制端点 |
| **MCP 代理** | `flaskserver/mcp_server.py` 把 REST 暴露为 MCP 工具（`list_modules`／`get_snapshot`／`get_series`／`control_collect`／`send_command`），供 AI Agent 通过 stdio 调用（需另装 `mcp`） |

仪表盘的**默认字体是内嵌的 HarmonyOS Sans SC**（`assets/fonts/*.woff2`，由服务端 `/font.css` + `/font-file` 提供）——手机等**从未安装该字体**的设备打开也能正常显示。在仪表盘 **开始菜单 → 外观 → 字体** 里可随时切换，选择保存在服务端（`app_config.json` 的 `WebDashboard.FontFamily`），因此局域网内多台设备、多个浏览器表现一致，且与桌面端的「应用字体」互不干扰。

⚠️ 「局域网访问」开关会把监听地址改为 `0.0.0.0`（手机／其他电脑可访问）。**同一网络内的任何人都能查看并控制实验，甚至可能通过漏洞提权，请仅在可信网络中开启。**

```bash
pip install flask          # 插件依赖（可选；未装时主页「数据接口」卡片灰显，程序照常运行）
pip install mcp            # 仅 MCP 代理需要
```

完整的端点清单、curl 示例与 MCP 配置见 [flaskserver/README.md](flaskserver/README.md)。

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
| 需要排查问题 / 记录运行日志 | 日志文件默认不写盘 | 设置 → 个性化 → 开启「运行日志」，再用「打开日志」查看 `logs.json`（控制台始终有输出） |
| 界面字体不是 MiSans | 内嵌字体文件缺失，或配置里选了其他字体 | 确认 `assets/fonts/MiSans-Regular.ttf` 存在（打包分发时该目录须一并带上）；再在 设置 → 外观 → 应用字体 中选回 MiSans |
| 仪表盘中文显示成方块 | 内嵌网页字体未随包分发 | 确认 `assets/fonts/HarmonyOS_Sans_SC_Regular.woff2` 存在；缺失时服务端 `/font.css` 返回空样式并回退系统字体 |
| 主页「数据接口」卡片灰显 | flask 未安装 | `pip install flask` 后重启程序 |
| 仪表盘能打开但图表空白 | 打包时漏收 `flaskserver/web/echarts.min.js` | 用仓库内的 `PhysChem-DigitizerP.spec` 重新打包（插件目录是整目录收集的） |

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

>  完整字段说明与注意事项请参考 [AGENTS.md](AGENTS.md)。

## 10.软件界面

![image.png](https://raw.gitcode.com/user-images/assets/9825261/e7d3888f-da91-4db5-aee3-5100408917c3/image.png 'image.png')  主页
![image.png](https://raw.gitcode.com/user-images/assets/9825261/7313933f-bb07-4691-9939-af60d01c1896/image.png 'image.png')  ph
![image.png](https://raw.gitcode.com/user-images/assets/9825261/cd961db4-69ad-4a86-91b8-7c1bf6d550c6/image.png 'image.png') 力
![image.png](https://raw.gitcode.com/user-images/assets/9825261/cc8116e5-2a32-4b76-aacf-31abf2cd98ee/image.png 'image.png') 电压
![image.png](https://raw.gitcode.com/user-images/assets/9825261/97d87d7d-ab8a-44ba-960a-87556c20454a/image.png 'image.png') 电流
![image.png](https://raw.gitcode.com/user-images/assets/9825261/6298a83d-4c05-43bc-9ec9-ec97bf0c0469/image.png 'image.png') 距离
![image.png](https://raw.gitcode.com/user-images/assets/9825261/c18e0bc1-a84f-43b3-baf0-523489428314/image.png 'image.png') 速度
![image.png](https://raw.gitcode.com/user-images/assets/9825261/3b7ce065-f78b-4fa0-8c01-cf3352e6de0c/image.png 'image.png') 设置
## 许可证

本项目采用 `GNU General Public License v3.0 `- 详见 [LICENSE](LICENSE) 文件

##  致谢

- **硬件平台**：[ESP32](https://www.espressif.com/) / [ESP8266 Community](https://www.esp8266.com/)
- **图形界面**：[PySide6](https://www.qt.io/qt-for-python)
- **数据可视化**：[Matplotlib](https://matplotlib.org/) / [pyqtgraph](https://www.pyqtgraph.org/)
- **串口通信**：[pyserial](https://github.com/pyserial/pyserial)

##  联系方式

如有问题或建议，请提交 [GitHub Issue](https://github.com/wangzhidong2/PhysChem-DigitizerP/issues) 或 [Gitcode Issue](https://gitcode.com/wangzhidong2/PhysChem-DigitizerP/issues)。

## 项目地址

- **GitHub**: [https://github.com/wangzhidong2/PhysChem-DigitizerP](https://github.com/wangzhidong2/PhysChem-DigitizerP)
- **Gitee**: [https://gitee.com/wangzhidong2/PhysChem-DigitizerP/](https://gitee.com/wangzhidong2/PhysChem-DigitizerP/)
- **GitCode**: [https://gitcode.com/wangzhidong2/PhysChem-DigitizerP](https://gitcode.com/wangzhidong2/PhysChem-DigitizerP)

---


