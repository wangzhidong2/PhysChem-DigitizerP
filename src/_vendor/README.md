# 内嵌第三方库（vendored）

本目录存放随源码分发的第三方 Python 包及其许可证原文。

**为什么内嵌**：减少安装步骤——用户只需 `pip install PySide6` 等少量核心依赖，
不必再单独装 UI 组件库。这些库都是纯 Python，可直接放进 `src/` 随源码运行。

**重要**：升级这些库时请同步更新本目录的版本号与许可证文件，并核对
`README.md` 与 `AGENTS.md` 中记录的版本。

---

## 1. qfluentwidgets — WinUI3 风格组件库

| 项 | 值 |
|---|---|
| PyPI 包名 | `PySide6-Fluent-Widgets` |
| 内嵌版本 | **1.11.3** |
| 导入名 | `qfluentwidgets` |
| 位置 | `src/qfluentwidgets/` |
| 许可证 | **GPLv3**（与本项目 GPL-3.0-only 兼容） |
| 许可证原文 | `qfluentwidgets-LICENSE.txt` |
| 上游 | https://github.com/zhiyiYo/PyQt-Fluent-Widgets/tree/PySide6 |
| 作者 | zhiyiYo |

## 2. qframelesswindow — 无边框窗口基础库（FluentWindow 的依赖）

| 项 | 值 |
|---|---|
| PyPI 包名 | `PySideSix-Frameless-Window` |
| 内嵌版本 | **0.8.2** |
| 导入名 | `qframelesswindow` |
| 位置 | `src/qframelesswindow/` |
| 许可证 | **LGPLv3** |
| 许可证原文 | `qframelesswindow-LICENSE.txt` |
| 上游 | https://github.com/zhiyiYo/PyQt-Frameless-Window |

> `FluentWindow`、`FramelessDialog`、`TitleBar` 等都依赖它，**不可省略**。

## 3. darkdetect — 系统深色模式探测

| 项 | 值 |
|---|---|
| PyPI 包名 | `darkdetect` |
| 内嵌版本 | **0.8.0** |
| 导入名 | `darkdetect` |
| 位置 | `src/darkdetect/` |
| 许可证 | **BSD-3-Clause** |
| 许可证原文 | `darkdetect-LICENSE.txt` |
| 上游 | https://github.com/albertosottile/darkdetect |
| 作者 | Alberto Sottile |

> 主题「跟随系统」功能依赖它探测 Windows 深色模式，**不可省略**。

---

## 不再随附的可选依赖

以下包 qfluentwidgets 只在**可选功能**里用到，本项目的界面不使用这些功能，
因此不内嵌，也不需要在 `requirements.txt` 中声明：

| 包 | 用途 | 本项目是否使用 |
|---|---|---|
| `PIL` / Pillow | `common/image_utils.py` 的图片处理 | 否 |
| `scipy` | 高斯模糊（亚克力背景） | 否 |
| `colorthief` | 从图片提取主色 | 否 |
| `numpy` | `image_utils.py`；**但项目内核自身需要** | 是（保留在 requirements.txt） |

已实测：上述四个包全部缺失时，`import qfluentwidgets` 仍可成功，
`FluentWindow` 与全部常用控件（含 `SpinBox` / `DoubleSpinBox`）工作正常。

---

## 维护须知

1. **升级**：从新版 wheel 里拷 `qfluentwidgets/`、`qframelesswindow/`、
   `darkdetect/` 三个目录覆盖，删除其中的 `__pycache__/` 与 `*.pyc`
   （`.gitignore` 也会排除），同时更新本文件的版本号与 `*LICENSE*.txt`。
2. **体积**：当前内嵌约 4.0 MB / 126 个文件。其中 `qfluentwidgets/_rc/`
   占大部分（编译进资源的图标、QSS、字体），**不可删除**。
3. **打包**：PyInstaller 的 spec 已把 `src/` 整体收集，内嵌库会自动带上；
   无需额外的 `hiddenimports`。
