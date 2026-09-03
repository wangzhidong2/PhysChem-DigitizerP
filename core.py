# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

# -*- coding: utf-8 -*-
"""
core.py — PhysChem-DigitizerP 公共模块

集中存放各传感器模块共享的代码：
- 配置管理（load/save_sensor_config）
- 串口通信线程（SerialThread）
- BLE 通信线程（BLESerialThread）+ 设备扫描
- 通用对话框（CalibrationDialog / SampleRateDialog）
- 共享样式（卡片 / 按钮 / 现代化风格 ComboBox）
- 主题工具函数

各传感器模块应通过 `from core import ...` 调用本模块的内容，
避免模块间互相依赖。
"""

import os
import json
import time
import random
import asyncio
import bisect
import threading
import importlib
import importlib.util

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QRadioButton, QWidget, QPushButton, QFrame, QSizePolicy, QTextEdit,
    QApplication,
)
from PySide6.QtCore import Qt, Signal, QThread, QPoint, QTimer, QAbstractNativeEventFilter
from PySide6.QtGui import (
    QFont, QColor, QPainter, QPen, QBrush, QPainterPath,
    QFontMetrics, QTextOption,
)

from qfluentwidgets import (
    PushButton, PrimaryPushButton, HyperlinkButton, ComboBox, EditableComboBox,
    SwitchButton, DoubleSpinBox,
    LineEdit, TextEdit, Dialog, MessageBox, MessageBoxBase, StrongBodyLabel,
    TitleLabel, SubtitleLabel, BodyLabel, CaptionLabel,
    isDarkTheme, qconfig, QConfig, ConfigItem, OptionsConfigItem, OptionsValidator,
    ExpandGroupSettingCard, FluentIcon, RadioButton, SettingCard,
)

# pyserial 为可选依赖：未安装时程序仍可运行（模拟器模式不受影响），
# 串口连接相关功能优雅降级（列表为空 + 连接时弹提示装库）
try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    serial = None
    SERIAL_AVAILABLE = False
    # 启动控制台提示（用户指定文案）：未装库不致命，模拟器照常可用
    print("未安装pyserial，何意味？你想不连接下位机吗（狗头）？")

# ============================================================
# matplotlib 全局字体设置（图表引擎为 matplotlib 时才需要；
# 未安装 matplotlib 的环境跳过，pyqtgraph 引擎不受影响）
# ============================================================
try:
    import matplotlib.pyplot as plt
    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei']
    plt.rcParams['axes.unicode_minus'] = False
except ImportError:
    plt = None

# ============================================================
# 图表引擎可用性检测（引擎缺失时优雅降级，程序仍可运行）
# ============================================================
CHART_ENGINES = ('matplotlib', 'pyqtgraph')


def _detect_chart_engine(name):
    """检测引擎是否已安装且可正常导入（损坏的安装同样视为不可用）。"""
    try:
        if importlib.util.find_spec(name) is None:
            return False
        importlib.import_module(name)
        return True
    except Exception:
        return False


#: 各引擎可用性（导入 core 时检测一次）。任一可用即可绘图；
#: 都不可用时 ChartPanel 显示「请安装图表引擎」占位，程序其余功能不受影响
CHART_ENGINE_AVAILABLE = {name: _detect_chart_engine(name) for name in CHART_ENGINES}

# 启动控制台提示（用户指定文案）：打印图表引擎安装状态
for _engine in CHART_ENGINES:
    print(f"图表引擎 {_engine}: {'✓ 已安装' if CHART_ENGINE_AVAILABLE[_engine] else '✗ 未安装'}")
if not any(CHART_ENGINE_AVAILABLE.values()):
    print("？？？你为什么不安装图表引擎？行，那你别想看实时图表了（狗头）")


def chart_engine_available(engine):
    """返回指定图表引擎在当前环境是否可用。"""
    return CHART_ENGINE_AVAILABLE.get(engine, False)


def resolve_chart_engine(engine):
    """把期望引擎解析为实际可用引擎；两个引擎都不可用时返回 None（占位模式）。

    配置里保存的引擎被卸载时，自动降级到另一个可用引擎，
    避免启动即崩溃。
    """
    if chart_engine_available(engine):
        return engine
    for name in CHART_ENGINES:
        if CHART_ENGINE_AVAILABLE[name]:
            return name
    return None

# ============================================================
# 统一配置管理 — 所有传感器校准配置保存在同一个 JSON 文件
# ============================================================
CONFIG_FILENAME = 'sensor_config.json'

# 应用默认主题色（蓝色）。qfluentwidgets 库默认是青色 #009faa，
# 本应用统一使用 Fluent Design 标准蓝 #0078d4（与项目强调色一致）。
DEFAULT_THEME_COLOR = '#0078d4'

# app_config.json 默认值（首次启动与「恢复默认设置」共用）
_APP_CONFIG_DEFAULT = {
    "Chart": {"Engine": "pyqtgraph"},
    "General": {"ConfigPersistenceEnabled": True, "ThemeColorMode": "custom"},
    "QFluentWidgets": {
        "FontFamilies": ["Segoe UI", "Microsoft YaHei", "PingFang SC"],
        "ThemeColor": "#ff0078d4",
        "ThemeMode": "Light",
    },
}


# 应用自身配置 — 独立文件存放，不受传感器配置开关影响。
# 开关状态若存进 sensor_config.json 会出现悖论：
# 「关闭保存」后无人写入 → 下次启动没人记得开关是关的。
class AppConfig(QConfig):
    """应用级配置（app_config.json，始终持久化）"""
    # 传感器配置持久化开关：False 时不读取也不写入 sensor_config.json，
    # 所有更改仅本次会话有效（默认开启，保持原有行为）
    configPersistenceEnabled = ConfigItem("General", "ConfigPersistenceEnabled", True)
    # 主题色模式：system=跟随系统强调色（Windows）/ custom=自定义（默认蓝色）
    themeColorMode = OptionsConfigItem(
        "General", "ThemeColorMode", "custom",
        OptionsValidator(["system", "custom"]),
    )
    # 图表引擎：pyqtgraph（默认，高性能交互）/ matplotlib（静态美观）
    chartEngine = OptionsConfigItem(
        "Chart", "Engine", "pyqtgraph",
        OptionsValidator(["matplotlib", "pyqtgraph"]),
    )


app_cfg = AppConfig()

# 首次启动（app_config.json 不存在）：先写入默认配置再加载，
# 保证默认主题色为蓝色（qfluentwidgets 库默认是青色 #009faa，不符合项目主题）
_app_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app_config.json')
if not os.path.exists(_app_config_path):
    try:
        with open(_app_config_path, 'w', encoding='utf-8') as _f:
            json.dump(_APP_CONFIG_DEFAULT, _f, ensure_ascii=False, indent=4)
        print(f"✓ 已生成默认应用配置：{_app_config_path}")
    except Exception as _e:
        print(f"⚠️ 生成默认应用配置失败: {_e}")

qconfig.load(_app_config_path, app_cfg)


def _get_config_file_path():
    """获取统一配置文件的绝对路径。

    配置文件始终位于主程序所在目录（即仓库根目录），与具体模块文件位置无关。
    """
    # 取 main.py 所在目录：模块文件位于 传感器代码/xxx/ 下，
    # 上溯两级即为仓库根目录。
    here = os.path.dirname(os.path.abspath(__file__))
    # core.py 在根目录，直接用 here
    return os.path.join(here, CONFIG_FILENAME)


def load_sensor_config(module_name):
    """从统一配置文件中读取指定模块的配置。

    Args:
        module_name: 模块名称，如 'ph_sensor'、'force_sensor'

    Returns:
        dict: 该模块的配置字典，不存在则返回空字典
    """
    # 持久化开关关闭：不读取旧配置，各模块使用默认值
    if not app_cfg.configPersistenceEnabled.value:
        print(f"ℹ️ 配置保存已关闭，[{module_name}] 跳过读取，使用默认值")
        return {}

    config_path = _get_config_file_path()
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                all_config = json.load(f)
            module_config = all_config.get(module_name, {})
            if module_config:
                print(f"✓ 已加载 [{module_name}] 配置")
            else:
                print(f"ℹ️ [{module_name}] 无已保存配置，使用默认值")
            return module_config
        else:
            print(f"ℹ️ 配置文件不存在：{config_path}，所有模块使用默认值")
            return {}
    except Exception as e:
        print(f"⚠️ 读取配置文件失败：{e}")
        return {}


def save_sensor_config(module_name, config_dict):
    """将指定模块的配置写入统一配置文件。

    Args:
        module_name: 模块名称，如 'ph_sensor'、'force_sensor'
        config_dict: 该模块的配置字典

    Returns:
        bool: 是否保存成功
    """
    # 持久化开关关闭：静默丢弃写入（视为成功，避免 UI 报保存失败），
    # 更改仅保留在各模块内存中，退出程序后销毁
    if not app_cfg.configPersistenceEnabled.value:
        return True

    config_path = _get_config_file_path()
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                all_config = json.load(f)
        else:
            all_config = {}

        all_config[module_name] = config_dict

        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(all_config, f, ensure_ascii=False, indent=2)

        print(f"✓ [{module_name}] 配置已保存到 {config_path}")
        return True
    except Exception as e:
        print(f"⚠️ 保存 [{module_name}] 配置失败: {e}")
        return False


def export_sensor_config(target_dir):
    """将 sensor_config.json 导出到指定目录。

    由设置页「导出配置」调用（系统文件夹选择对话框）。

    Args:
        target_dir: 目标目录路径（用户通过 QFileDialog 选择）

    Returns:
        tuple[bool, str]: (是否成功, 消息文件路径或错误描述)
    """
    import shutil
    config_path = _get_config_file_path()
    if not os.path.exists(config_path):
        return False, "配置文件不存在，无需导出"
    try:
        dest = os.path.join(target_dir, CONFIG_FILENAME)
        shutil.copy2(config_path, dest)
        print(f"✓ 配置已导出到 {dest}")
        return True, dest
    except Exception as e:
        print(f"⚠️ 导出配置失败: {e}")
        return False, str(e)


def import_sensor_config(source_file):
    """从指定文件导入 sensor_config.json，覆盖当前配置。

    由设置页「导入配置」调用（系统文件选择对话框）。

    Args:
        source_file: 源文件路径（用户通过 QFileDialog 选择的 .json 文件）

    Returns:
        tuple[bool, str]: (是否成功, 消息描述)
    """
    try:
        with open(source_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError:
        return False, "文件格式错误，不是有效的 JSON 文件"
    except Exception as e:
        return False, f"读取文件失败: {e}"

    if not isinstance(data, dict):
        return False, "文件内容格式错误，期望 JSON 对象"

    config_path = _get_config_file_path()
    try:
        # 先写临时文件再重命名，避免 Windows 文件锁导致 PermissionError
        import tempfile
        dir_name = os.path.dirname(config_path)
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, config_path)
        except Exception:
            # 清理临时文件
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        print(f"✓ 配置已从 {source_file} 导入到 {config_path}")
        return True, f"已导入 {len(data)} 个模块的配置"
    except Exception as e:
        print(f"⚠️ 导入配置失败: {e}")
        return False, f"写入配置文件失败: {e}"


def clear_sensor_config():
    """删除统一配置文件 sensor_config.json，所有校准配置恢复默认值。

    由设置页「清除用户设置」调用（确认框后）。
    已加载模块内存中的配置不受影响，重启程序后全部使用默认值。

    Returns:
        bool: 是否成功（文件本就不存在也视为成功）
    """
    config_path = _get_config_file_path()
    try:
        if os.path.exists(config_path):
            os.remove(config_path)
            print(f"✓ 已清除用户配置文件：{config_path}")
        else:
            print("ℹ️ 配置文件不存在，无需清除")
        return True
    except Exception as e:
        print(f"⚠️ 清除配置文件失败: {e}")
        return False


def reset_all_config():
    """将 app_config.json 和 sensor_config.json 恢复为默认值。

    由设置页「恢复默认设置」调用（确认框后）。
    恢复后重启程序完全生效。

    Returns:
        tuple[bool, str]: (是否成功, 消息描述)
    """
    here = os.path.dirname(os.path.abspath(__file__))

    # 1. 恢复 app_config.json
    app_config_path = os.path.join(here, 'app_config.json')
    try:
        with open(app_config_path, 'w', encoding='utf-8') as f:
            json.dump(_APP_CONFIG_DEFAULT, f, ensure_ascii=False, indent=4)
        print(f"✓ 已恢复应用配置：{app_config_path}")
    except Exception as e:
        return False, f"恢复应用配置失败: {e}"

    # 2. 删除 sensor_config.json
    sensor_config_path = _get_config_file_path()
    try:
        if os.path.exists(sensor_config_path):
            os.remove(sensor_config_path)
            print(f"✓ 已清除传感器配置：{sensor_config_path}")
    except Exception as e:
        return False, f"删除传感器配置失败: {e}"

    # 3. 重新加载 app_config 到内存
    try:
        qconfig.load(app_config_path, app_cfg)
    except Exception:
        pass

    return True, "所有设置已恢复默认值，重启后完全生效"


# ============================================================
# 应用主题色：跟随系统强调色（Windows）/ 自定义（默认蓝色）
# ============================================================
def system_accent_color():
    """读取 Windows 系统强调色，返回 '#rrggbb'；失败回退默认蓝色。

    优先读 Explorer 的 AccentColorMenu（任务栏/开始菜单强调色，0x00BBGGRR），
    缺失时回退 DWM 的 ColorizationColor（标题栏颜色，0xAABBGGRR）——
    两者低 24 位均为 BBGGRR，统一按该格式解析。
    """
    def _read_dword(path, name):
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            value, _ = winreg.QueryValueEx(key, name)
        return value

    for path, name in (
        (r'Software\Microsoft\Windows\CurrentVersion\Explorer\Accent', 'AccentColorMenu'),
        (r'Software\Microsoft\Windows\DWM', 'ColorizationColor'),
    ):
        try:
            value = _read_dword(path, name)
            if not value:
                continue
            r, g, b = value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF
            if (r | g | b) == 0:      # 全 0 视为无效值
                continue
            return '#%02x%02x%02x' % (r, g, b)
        except Exception:
            continue
    return DEFAULT_THEME_COLOR


def set_app_theme_color(color, save=True):
    """设置应用主题色并刷新全部 FluentWidgets 组件。

    save=True 持久化到 app_config.json（QFluentWidgets.ThemeColor）；
    「跟随系统主题色」模式应传 save=False（系统色不落盘，保留自定义色）。
    """
    from PySide6.QtGui import QColor
    from qfluentwidgets.common.style_sheet import setThemeColor
    setThemeColor(QColor(color), save=save)


class SystemAccentListener(QAbstractNativeEventFilter):
    """监听 Windows 系统强调色变化（WM_DWMCOLORIZATIONCOLORCHANGED）。

    仅当配置为「跟随系统主题色」时生效：收到系统广播后重读注册表并
    刷新主题色。非 Windows 平台收不到该消息，无需额外判断。
    """

    WM_DWMCOLORIZATIONCOLORCHANGED = 0x0320

    def nativeEventFilter(self, eventType, message):
        try:
            if eventType == b'windows_generic_MSG' and message:
                import ctypes
                from ctypes import wintypes
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == self.WM_DWMCOLORIZATIONCOLORCHANGED:
                    if app_cfg.themeColorMode.value == 'system':
                        set_app_theme_color(system_accent_color(), save=False)
        except Exception:
            pass
        return False


def fluent_message_box(parent, title, text):
    """WinUI3 风格提示弹窗，替代原生 QMessageBox 的 warning/critical/information。

    单「确定」按钮模态对话框，标题与按钮均为中文，样式随 Fluent 主题。

    Args:
        parent: 父窗口（各传感器模块传 self）
        title: 弹窗标题（如 "连接错误"）
        text: 提示内容
    """
    box = MessageBox(title, text, parent)
    box.yesButton.setText("确定")
    box.cancelButton.hide()
    box.buttonLayout.insertStretch(0, 1)
    box.exec()


# ============================================================
# 双引擎图表面板：matplotlib / pyqtgraph 统一 API
# ============================================================
# matplotlib 单字母颜色 → 十六进制（pyqtgraph 不识别 'r' 这类缩写）
_MPL_COLOR_ALIASES = {
    'r': '#ff0000', 'b': '#0000ff', 'g': '#008000', 'k': '#000000',
    'y': '#ffff00', 'm': '#ff00ff', 'c': '#00ffff', 'w': '#ffffff',
}


def _normalize_color(color):
    """把 matplotlib 单字母颜色规范为 pyqtgraph 也能用的 '#rrggbb'。"""
    if isinstance(color, str):
        return _MPL_COLOR_ALIASES.get(color, color)
    return color


class ChartPanel(QWidget):
    """双引擎图表面板：设置页可切换 matplotlib / pyqtgraph。

    统一绘制 API（在 begin() 与 end() 之间调用，end() 时一次性提交）：

        c = ChartPanel(n_plots=1)          # n_plots=2 时上下双子图
        c.begin()
        c.plot(x, y, color='#0078d4', width=2, label='曲线')
        c.hline(7.0, color='r', style='dash', alpha=0.5, label='参考')
        c.set_labels('时间 (秒)', 'pH值')   # 第 index 个子图
        c.set_title('标题')
        c.set_ylim(0, 14)                  # 不调用则自动范围
        c.legend()                         # 有 label 的曲线进图例
        c.end()

    引擎差异由面板内部吸收：
    - matplotlib：end() 时按既有「清空-重建-绘制-布局-重绘」流程全量绘制
    - pyqtgraph：end() 时重建数据项并 setData，交互（缩放/平移）内置
    切换引擎时自动重放最近一次绘制内容，无需各模块额外处理。

    引擎缺失时的优雅降级：
    - 配置的引擎未安装 → 自动降级到另一个可用引擎
    - 两个引擎都未安装 → 显示「请安装图表引擎」占位提示，
      绘制 API 变为空操作（数据采集/保存等其余功能不受影响）
    """

    def __init__(self, n_plots=1, parent=None):
        super().__init__(parent)
        self._n_plots = max(1, int(n_plots))
        # 期望引擎经可用性解析：未安装则降级到另一引擎，都缺则为 None（占位模式）
        self._engine = resolve_chart_engine(app_cfg.chartEngine.value)
        self._dark = isDarkTheme()
        self._spec = None       # 当前事务（begin~end 之间累积）
        self._last = None       # 最近一次已提交事务（引擎切换时重放）
        self._pg_hover_vline = None   # pyqtgraph 悬停指示线（懒创建）
        self._pg_hover_label = None   # pyqtgraph 悬停数据标签（懒创建）
        self._pg_hover_view = None    # 最近悬停位置 (子图索引, 视图x)，重绘后据此恢复
        # 视图窗口控制 + 曲线拟合 + 离群点剔除（仅 pyqtgraph）：紧凑分析面板
        self._analysis_panel = None   # 面板控件（懒创建，模块嵌入图表卡左侧栏）
        self._win_switch = None       # SwitchButton「显示整个范围」
        self._win_spin = None         # DoubleSpinBox 窗口秒数（支持小数）
        self._win_full_range = True   # True=整个范围（默认），False=最近 N 秒
        self._win_seconds = 5.0       # 滚动窗口长度（秒）
        self._fit_combo = None        # ComboBox 拟合方式（多项式/对数/幂函数）
        self._fit_mode = 0            # 0=不拟合，1~3=多项式次数，4=对数，5=幂函数
        self._fit_hint = None         # CaptionLabel 拟合方式注解（随选择动态更新）
        self._pg_fit_texts = []       # 拟合方程文本（TextItem 锚定视口左上角，
                                      # pi.clear() 不会移除，需手动管理生命周期）
        self._pg_fit_scatter = []     # 拟合时原始数据散点层（PlotDataItem 列表，
                                      # 随 pi.clear() 移除，仅需清引用防悬挂）
        self._scatter_hidden = False  # True=散点已被用户清除（重新选拟合方式恢复）
        self._clear_btn = None        # 「清除离散点」按钮（二次点击确认）
        self._clear_timer = None      # 确认态超时复位定时器（防悬置）
        # 离群点剔除（仅 pyqtgraph）：残差比例法 + 多级撤销栈。
        # _outlier_masks：每子图一个 bool 掩码（True=保留）或 None（全部保留），
        # 长度等于该子图第一条曲线在「剔除那一刻」的数据长度；之后新追加的
        # 数据点不在掩码范围内，默认保留。_outlier_stack 记录每次剔除前的掩码，
        # 供多级撤销（退到底即全部恢复）。
        self._outlier_spin = None     # 比例输入（0.5%~50%，默认 5%）
        self._outlier_btn = None      # 「剔除离群点」按钮
        self._outlier_undo_btn = None  # 「撤销」按钮
        self._outlier_label = None    # 已移除点数计数
        self._outlier_masks = None    # 每子图掩码列表（None=未启用剔除）
        self._outlier_stack = []      # 撤销栈：每项为上一步的多子图掩码列表
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._lay = lay
        self._widget = None     # 当前引擎实际控件
        self._pg_plots = []     # pyqtgraph: PlotItem 列表
        # 增量更新缓存：记录最近一次全量重建时各子图的 PlotDataItem /
        # InfiniteLine 与结构签名；实时流式路径结构未变时只 setData 复用，
        # 避免每 100ms 全量 pi.clear()+重建控件（pyqtgraph 实时绘制卡顿主因）
        self._pg_cache = None
        self._build_widget()

    # ---------------- 引擎控件构建 ----------------
    def _build_widget(self):
        if self._engine is None:
            self._build_placeholder_widget()
        elif self._engine == 'pyqtgraph':
            self._build_pg_widget()
        else:
            self._build_mpl_widget()

    def _build_mpl_widget(self):
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure
        self.figure = Figure(figsize=(8, 5), dpi=100)
        self.figure.set_facecolor('#2d2d2d' if self._dark else '#fafafa')
        self._widget = FigureCanvasQTAgg(self.figure)
        self._widget.setStyleSheet("border: 1px solid #e5e5e5; border-radius: 6px;")
        self._widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._lay.addWidget(self._widget)

    def _build_pg_widget(self):
        import pyqtgraph as pg
        pg.setConfigOptions(antialias=True)
        # 旧 widget 的悬停元素已随旧场景销毁，重置引用防止悬挂
        # （_pg_hover_view 保留：坐标语义一致，数据重放后据此恢复悬停）
        self._pg_hover_vline = None
        self._pg_hover_label = None
        # 拟合方程文本同理：随旧视口销毁，引用作废
        self._pg_fit_texts = []
        self._pg_fit_scatter = []
        self._widget = pg.GraphicsLayoutWidget()
        self._pg_plots = []
        for i in range(self._n_plots):
            pi = self._widget.addPlot(row=i, col=0)
            pi.showGrid(x=True, y=True, alpha=0.3)
            self._pg_plots.append(pi)
        self._apply_pg_theme()
        # 悬停交互：鼠标移动时在最近数据点上弹出标签（时间 + 数值）
        self._widget.scene().sigMouseMoved.connect(self._on_pg_mouse_moved)
        self._lay.addWidget(self._widget)

    def _apply_pg_theme(self):
        """pyqtgraph 亮/暗主题：背景、轴、刻度文字颜色全套适配。"""
        from pyqtgraph import mkPen
        # 丢弃旧主题配色的悬停元素，按新配色重建（若鼠标仍在图表上）
        self._discard_pg_hover()
        bg = '#2d2d2d' if self._dark else '#fafafa'
        fg = '#e0e0e0' if self._dark else '#1a1a1a'
        self._widget.setBackground(bg)
        for pi in self._pg_plots:
            for loc in ('left', 'bottom'):
                ax = pi.getAxis(loc)
                ax.setPen(mkPen(fg, width=1))
                ax.setTextPen(fg)
        # 拟合开启时按新前景色重画方程文本（同引擎不重建控件，需手动刷新）
        if self._fit_mode > 0 and self._last is not None:
            self._draw_pg_fit(self._last)
        self._restore_pg_hover()

    # ---------------- pyqtgraph 悬停交互 ----------------
    @staticmethod
    def _nearest_point(xs, ys, x):
        """返回 (|dx|, x, y) 横坐标最接近 x 的数据点；空序列返回 None。

        时间序列（横坐标递增）用二分定位，长序列下鼠标移动不掉帧；
        横坐标非递增时退回线性扫描保证结果正确。
        """
        if len(xs) == 0:
            return None
        if len(xs) > 64 and xs[0] <= xs[-1]:
            k = bisect.bisect_left(xs, x)
            best = None
            for j in (k - 1, k):
                if 0 <= j < len(xs):
                    d = abs(xs[j] - x)
                    if best is None or d < best[0]:
                        best = (d, xs[j], ys[j])
            return best
        return min(((abs(px - x), px, py) for px, py in zip(xs, ys)),
                   default=None)

    @staticmethod
    def _fmt_num(v):
        """紧凑数字格式：最多 4 位有效数字，去掉多余尾零。"""
        return f"{v:.4g}"

    def _discard_pg_hover(self):
        """从各子图移除悬停辅助元素并丢弃引用（重绘/主题切换时调用）。"""
        for pi in self._pg_plots:
            if self._pg_hover_vline is not None and self._pg_hover_vline in pi.items:
                pi.removeItem(self._pg_hover_vline)
            if self._pg_hover_label is not None and self._pg_hover_label in pi.items:
                pi.removeItem(self._pg_hover_label)
        self._pg_hover_vline = None
        self._pg_hover_label = None

    def _ensure_pg_hover_items(self, pi):
        """懒创建悬停指示线与标签，并迁移到鼠标所在的子图。"""
        import pyqtgraph as pg
        fg = '#e0e0e0' if self._dark else '#1a1a1a'
        if self._pg_hover_vline is None:
            self._pg_hover_vline = pg.InfiniteLine(
                angle=90, movable=False,
                pen=pg.mkPen(fg, width=1, style=Qt.PenStyle.DashLine))
        if self._pg_hover_label is None:
            fill = QColor('#2d2d2d' if self._dark else '#fafafa')
            fill.setAlpha(220)
            self._pg_hover_label = pg.TextItem(
                anchor=(0.5, 1), color=fg,
                border=pg.mkPen(fg, width=1), fill=fill)
            self._pg_hover_label.setZValue(100)   # 置顶，不被曲线遮挡
        # 多子图场景：鼠标切换子图时先从原子图移除
        for other in self._pg_plots:
            if other is pi:
                continue
            if self._pg_hover_vline in other.items:
                other.removeItem(self._pg_hover_vline)
            if self._pg_hover_label in other.items:
                other.removeItem(self._pg_hover_label)
        # ignoreBounds：指示线/标签不参与自动量程计算
        if self._pg_hover_vline not in pi.items:
            pi.addItem(self._pg_hover_vline, ignoreBounds=True)
        if self._pg_hover_label not in pi.items:
            pi.addItem(self._pg_hover_label, ignoreBounds=True)

    def _on_pg_mouse_moved(self, pos):
        """pyqtgraph 悬停：定位最近数据点，显示指示线 + 时间/数值标签。"""
        if self._engine != 'pyqtgraph':
            return
        if self._last is None:
            self._pg_hover_view = None
            self._hide_pg_hover()
            return
        for i, pi in enumerate(self._pg_plots):
            if not pi.sceneBoundingRect().contains(pos):
                continue
            mouse_x = pi.vb.mapSceneToView(pos).x()
            # 记录悬停位置：数据高频重绘后据此恢复，标签不随重绘闪烁消失
            self._pg_hover_view = (i, mouse_x)
            self._update_pg_hover(i, mouse_x)
            return
        # 鼠标不在任何子图数据区：清除记录并隐藏
        self._pg_hover_view = None
        self._hide_pg_hover()

    def _update_pg_hover(self, index, mouse_x, spec=None):
        """在 index 子图上按视图横坐标鼠标定位最近数据点并更新悬停元素。

        鼠标移动与数据重绘后的恢复共用本方法。spec 缺省用剔除掩码作用
        后的可见数据，保证悬停读值与图上显示的曲线一致（被剔除的离群
        点不参与定位）。
        """
        if spec is None:
            spec = self._visible_spec(self._last)
        pi = self._pg_plots[index]
        sp = spec[index]
        # 每条曲线取横坐标最接近鼠标的数据点；nearest 为全图最近点
        rows, nearest = [], None
        for s in sp['plot']:
            best = self._nearest_point(s['x'], s['y'], mouse_x)
            if best is None:
                continue
            rows.append((s['label'] or '数值', best[2]))
            if nearest is None or best[0] < nearest[0]:
                nearest = best
        if nearest is None:
            self._hide_pg_hover()
            return
        self._ensure_pg_hover_items(pi)
        self._pg_hover_vline.setPos(nearest[1])
        # 标签内容：横轴（时间）+ 各曲线数值
        lines = [f"{sp['xlabel'] or 'X'}: {self._fmt_num(nearest[1])}"]
        for label, y in rows:
            lines.append(f"{label}: {self._fmt_num(y)}")
        self._pg_hover_label.setText('\n'.join(lines))
        # 标签默认在数据点上方；点位于视图上沿附近时翻到下方，避免出界
        (ymin, ymax) = pi.vb.viewRange()[1]
        span = (ymax - ymin) or 1.0
        above = (nearest[2] - ymin) / span < 0.7
        self._pg_hover_label.setAnchor((0.5, 1) if above else (0.5, 0))
        self._pg_hover_label.setPos(nearest[1], nearest[2])
        self._pg_hover_vline.setVisible(True)
        self._pg_hover_label.setVisible(True)

    def _hide_pg_hover(self):
        """隐藏悬停元素（不销毁，重绘后可恢复）。"""
        if self._pg_hover_vline is not None:
            self._pg_hover_vline.setVisible(False)
        if self._pg_hover_label is not None:
            self._pg_hover_label.setVisible(False)

    def _restore_pg_hover(self):
        """按最近悬停位置恢复悬停元素（数据重绘/主题切换后调用）。

        数据更新后最近数据点可能变化，本方法按记录的视图横坐标在新数据
        上重新定位，保证实时采集时鼠标不动也能持续显示最新数值。
        """
        if (self._engine != 'pyqtgraph' or self._pg_hover_view is None
                or self._last is None):
            return
        index, mouse_x = self._pg_hover_view
        if not (0 <= index < len(self._pg_plots)):
            self._pg_hover_view = None
            return
        try:
            self._update_pg_hover(index, mouse_x,
                                  self._visible_spec(self._last))
        except Exception:
            # 恢复失败（元素失效等）：丢弃引用，下次鼠标移动时重建
            self._discard_pg_hover()

    def _build_placeholder_widget(self):
        """无可用引擎时的占位控件：提示安装图表引擎，其余功能不受影响。"""
        bg = '#333333' if self._dark else '#fafafa'
        fg = '#9a9a9a' if self._dark else '#666666'
        border = '#555555' if self._dark else '#c8c8c8'
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ border: 1px dashed {border}; border-radius: 6px;"
            f" background-color: {bg}; }}"
        )
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        lay = QVBoxLayout(frame)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl = QLabel("未检测到图表引擎")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            f"color: {fg}; font-size: 16px; font-weight: bold;"
            " background: transparent; border: none;"
        )
        hint = QLabel("请安装 matplotlib 或 pyqtgraph 后重启程序：\n"
                      "pip install matplotlib pyqtgraph")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(
            f"color: {fg}; font-size: 13px;"
            " background: transparent; border: none;"
        )
        lay.addStretch(1)
        lay.addWidget(lbl)
        lay.addSpacing(8)
        lay.addWidget(hint)
        lay.addStretch(1)
        self._widget = frame
        self._lay.addWidget(self._widget)

    # ---------------- 统一绘制 API ----------------
    def begin(self):
        """开始一次绘制事务。"""
        self._spec = [
            {'plot': [], 'hline': [], 'xlabel': '', 'ylabel': '',
             'title': '', 'xlim': None, 'ylim': None, 'legend': False}
            for _ in range(self._n_plots)
        ]

    def plot(self, x, y, color='#0078d4', width=2, label=None, index=0):
        """在第 index 个子图上绘制一条曲线。"""
        self._spec[index]['plot'].append(
            {'x': list(x), 'y': list(y), 'color': _normalize_color(color),
             'width': width, 'label': label})

    def hline(self, y, color='#aaaaaa', style='dash', width=1.5, alpha=1.0,
              label=None, index=0):
        """在第 index 个子图上添加水平参考线。

        style: 'dash' 虚线 / 'dot' 点线 / 'solid' 实线
        """
        self._spec[index]['hline'].append(
            {'y': y, 'color': _normalize_color(color), 'style': style,
             'width': width, 'alpha': alpha, 'label': label})

    def set_labels(self, xlabel, ylabel, index=0):
        self._spec[index]['xlabel'] = xlabel
        self._spec[index]['ylabel'] = ylabel

    def set_title(self, title, index=0):
        self._spec[index]['title'] = title

    def set_xlim(self, a, b, index=0):
        self._spec[index]['xlim'] = (a, b)

    def set_ylim(self, a, b, index=0):
        self._spec[index]['ylim'] = (a, b)

    def legend(self, index=0):
        """启用第 index 个子图的图例（有 label 的曲线/参考线才显示）。"""
        self._spec[index]['legend'] = True

    def end(self):
        """提交事务并渲染。无 begin 直接调用 end 时忽略。"""
        if self._spec is None:
            return
        self._commit(self._spec)
        self._last = self._spec
        self._spec = None

    # ---------------- 渲染实现 ----------------
    def _commit(self, spec, force_autorange=False):
        """渲染提交的事务。

        force_autorange（仅 pyqtgraph）：True 时立即同步重算自动量程
        （用户显式操作如切回整范围、首次渲染时用）；实时提交路径保持
        False，交给 pyqtgraph 的延迟 autoRange（合并到重绘帧，避免每次
        采集都同步 O(N) 计算拖慢刷新）。
        """
        if self._engine is None:      # 占位模式：仅记录事务，不渲染
            return
        if self._engine == 'pyqtgraph':
            self._commit_pg(spec, force_autorange=force_autorange)
        else:
            self._commit_mpl(spec)

    def _commit_mpl(self, spec):
        n = self._n_plots
        self.figure.clear()
        if n == 1:
            axes = [self.figure.add_subplot(111)]
        else:
            axes = [self.figure.add_subplot(n, 1, i + 1) for i in range(n)]
        for ax, sp in zip(axes, spec):
            for s in sp['plot']:
                ax.plot(s['x'], s['y'], s['color'],
                        linewidth=s['width'], label=s['label'])
            for h in sp['hline']:
                ls = {'dash': '--', 'dot': ':', 'solid': '-'}[h['style']]
                kw = {'color': h['color'], 'linestyle': ls,
                      'linewidth': h['width'], 'alpha': h['alpha']}
                if h['label']:
                    kw['label'] = h['label']
                ax.axhline(h['y'], **kw)
            if sp['xlabel']:
                ax.set_xlabel(sp['xlabel'])
            if sp['ylabel']:
                ax.set_ylabel(sp['ylabel'])
            if sp['title']:
                ax.set_title(sp['title'], fontsize=14, fontweight='bold')
            ax.grid(True, alpha=0.3)
            if sp['legend'] and any(
                    s['label'] for s in sp['plot'] + sp['hline']):
                ax.legend(loc='upper right')
            if sp['xlim']:
                ax.set_xlim(*sp['xlim'])
            if sp['ylim']:
                ax.set_ylim(*sp['ylim'])
        self.figure.tight_layout()
        self._widget.draw()

    def _commit_pg(self, spec, force_autorange=False):
        import pyqtgraph as pg
        from pyqtgraph import mkPen
        # 离群点剔除掩码：渲染前把第一曲线按掩码过滤（只影响显示结果，
        # _last 保持原始数据，撤销/引擎重放都从这里重新过滤）
        spec = self._visible_spec(spec)
        # 实时流式路径：结构未变（曲线/参考线数量、图例、轴模式一致）时
        # 只 setData 复用已有控件，避开每帧全量 pi.clear()+重建 PlotDataItem
        # 的控件抖动——pyqtgraph 大流量实时绘制卡顿的主因之一。拟合开启时
        # 散点/拟合曲线每帧重建，不走增量。
        if (not force_autorange and self._fit_mode <= 0
                and self._pg_incremental_ok(spec)):
            self._incremental_pg(spec)
            self._restore_pg_hover()
            self._draw_pg_fit(spec)      # 拟合关闭时为快速空操作
            self._update_view_window(spec)
            return
        # 注意：pi.clear() 会把悬停元素移出场景，但不销毁——重绘完成后由
        # _restore_pg_hover() 按记录位置重新加回并定位。高频实时更新下
        # 悬停标签持续显示且数值跟随最新数据，不会随重绘闪烁消失。
        pen_style = {'dash': Qt.PenStyle.DashLine,
                     'dot': Qt.PenStyle.DotLine,
                     'solid': Qt.PenStyle.SolidLine}
        cache = []
        for pi, sp in zip(self._pg_plots, spec):
            pi.clear()
            # 显式清空上一轮图例条目：旧版 pyqtgraph 的 pi.clear() 不清图例，
            # 每次重绘（含实时数据更新）都会累积条目直至撑爆图表
            if pi.legend is not None:
                pi.legend.clear()
            legend_on = bool(sp['legend'] and any(
                s['label'] for s in sp['plot'] + sp['hline']))
            legend = pi.addLegend() if legend_on else None
            curves, hlines = [], []
            for s in sp['plot']:
                pen = mkPen(s['color'], width=s['width'])
                curve = pi.plot(s['x'], s['y'], pen=pen,
                                name=s['label'] if sp['legend'] else None)
                # 大数据实时优化：峰值降采样（视图内保留峰值形状）+ 只画
                # 可见区域 + 跳过有限性检查。pyqtgraph 自动选择采样率，
                # 点少时退化为全量绘制，不影响数据与拟合/悬停逻辑。
                # 0.14 把 mode 参数改名为 method，跨版本兼容处理
                try:
                    curve.setDownsampling(None, True, method='peak')
                except TypeError:
                    curve.setDownsampling(None, True, mode='peak')
                curve.setClipToView(True)
                curve.setSkipFiniteCheck(True)
                curves.append(curve)
            for h in sp['hline']:
                c = QColor(h['color'])
                c.setAlpha(int(h['alpha'] * 255))
                pen = mkPen(c, width=h['width'], style=pen_style[h['style']])
                ln = pg.InfiniteLine(pos=h['y'], angle=0, pen=pen)
                pi.addItem(ln)
                hlines.append(ln)
                if legend is not None and h['label']:
                    # InfiniteLine 无 opts 属性，旧版 pyqtgraph 的图例
                    # 绘制（ItemSample.paint）会直接崩溃并拖垮整棵控件树
                    # 的 paint 链；改用同款画笔的空曲线作图例样本
                    legend.addItem(pg.PlotDataItem(pen=pen), h['label'])
            pi.setLabel('bottom', sp['xlabel'])
            pi.setLabel('left', sp['ylabel'])
            pi.setTitle(sp['title'])
            if sp['xlim']:
                pi.setXRange(*sp['xlim'], padding=0)
            else:
                pi.enableAutoRange(x=True)
                # enableAutoRange 是「打开开关+延迟生效」，实际重算要等下次
                # 重绘；仅用户显式操作（切回整范围等）时强制立即重算，
                # 实时提交路径交由 pyqtgraph 延迟到重绘帧自动算，避免
                # 每次采集同步 O(N) 范围计算拖慢刷新
                if force_autorange:
                    pi.vb.updateAutoRange()
            if sp['ylim']:
                pi.setYRange(*sp['ylim'], padding=0)
            else:
                pi.enableAutoRange(y=True)
                if force_autorange:
                    pi.vb.updateAutoRange()
            cache.append({'curves': curves, 'hlines': hlines,
                          'n_plot': len(curves), 'n_hline': len(hlines),
                          'legend': legend_on,
                          'xlim': bool(sp['xlim']), 'ylim': bool(sp['ylim'])})
        self._pg_cache = cache
        # 重绘完成：若鼠标正悬停在图表上，按记录位置恢复悬停（数值已更新）
        self._restore_pg_hover()
        # 拟合开启时在最新数据上重画拟合曲线（实时采集自动跟随更新）
        self._draw_pg_fit(spec)
        # 滚动窗口模式：覆盖提交时恢复的自动量程，把 x 轴锁定为最近 N 秒
        # （传当次 spec 而非 _last：end() 在提交后才写 _last，用 _last 会落后一拍）
        self._update_view_window(spec)

    def _pg_incremental_ok(self, spec):
        """增量复用判断：结构与最近一次全量重建一致时返回 True。

        结构 = 子图数、每子图曲线/参考线数量、图例开关、显式轴范围开关。
        任何一项变化（模块切换曲线、单位切换增删参考线、拟合开关等）
        都会导致不匹配，退回全量重建。
        """
        c = self._pg_cache
        if c is None or len(c) != len(spec):
            return False
        for sp, e in zip(spec, c):
            if len(sp['plot']) != e['n_plot'] or len(sp['hline']) != e['n_hline']:
                return False
            if bool(sp['legend'] and any(
                    s['label'] for s in sp['plot'] + sp['hline'])) != e['legend']:
                return False
            if bool(sp['xlim']) != e['xlim'] or bool(sp['ylim']) != e['ylim']:
                return False
        return True

    def _incremental_pg(self, spec):
        """增量更新：复用缓存中的曲线/参考线控件，只 setData 刷数据。

        调用前已用 _pg_incremental_ok 确认结构与缓存一致。曲线/参考线
        setData / setValue / setPen 都不重建对象，图例、轴、标题为廉价
        操作每帧照刷，悬停元素因不执行 pi.clear() 而原地保留不抖动。
        """
        import pyqtgraph as pg
        from pyqtgraph import mkPen
        pen_style = {'dash': Qt.PenStyle.DashLine,
                     'dot': Qt.PenStyle.DotLine,
                     'solid': Qt.PenStyle.SolidLine}
        for pi, sp, e in zip(self._pg_plots, spec, self._pg_cache):
            for curve, s in zip(e['curves'], sp['plot']):
                curve.setData(s['x'], s['y'])
                curve.setPen(mkPen(s['color'], width=s['width']))
            for ln, h in zip(e['hlines'], sp['hline']):
                c = QColor(h['color'])
                c.setAlpha(int(h['alpha'] * 255))
                ln.setValue(h['y'])
                ln.setPen(mkPen(c, width=h['width'], style=pen_style[h['style']]))
            if e['legend']:
                legend = pi.legend if pi.legend is not None else pi.addLegend()
                legend.clear()
                for curve, s in zip(e['curves'], sp['plot']):
                    legend.addItem(curve, s['label'])
                for h in sp['hline']:
                    if h['label']:
                        c = QColor(h['color'])
                        c.setAlpha(int(h['alpha'] * 255))
                        legend.addItem(pg.PlotDataItem(pen=mkPen(
                            c, width=h['width'],
                            style=pen_style[h['style']])), h['label'])
            pi.setLabel('bottom', sp['xlabel'])
            pi.setLabel('left', sp['ylabel'])
            pi.setTitle(sp['title'])
            # 轴范围与全量路径一致：显式范围跟随模块设定，自动范围保持开启
            # （增量路径不强制同步重算，交由 pyqtgraph 在 setData 后按需扩展）
            if sp['xlim']:
                pi.setXRange(*sp['xlim'], padding=0)
            else:
                pi.enableAutoRange(x=True)
            if sp['ylim']:
                pi.setYRange(*sp['ylim'], padding=0)
            else:
                pi.enableAutoRange(y=True)

    # ---------------- 引擎 / 主题 / 清空 ----------------
    def _rebuild_widget(self):
        """销毁当前控件并按 self._engine 重建，随后重放最近一次绘制内容。"""
        old = self._widget
        self._widget = None
        self._pg_plots = []
        # 拟合文本/散点随旧场景销毁，引用作废（引擎切换后重建）
        self._pg_fit_texts = []
        self._pg_fit_scatter = []
        # 增量缓存指向旧场景控件，随控件一起作废
        self._pg_cache = None
        if old is not None:
            self._lay.removeWidget(old)
            old.setParent(None)
            old.deleteLater()
        self._build_widget()
        if self._engine is not None and self._last is not None:
            self._commit(self._last)

    def set_engine(self, engine):
        """运行时切换引擎：重建控件并重放最近一次绘制内容。

        未安装的引擎请求会被拒绝（设置页已将其灰显，此处为双保险）。
        """
        if not chart_engine_available(engine) or engine == self._engine:
            return
        self._engine = engine
        self._rebuild_widget()
        self._sync_view_window_visibility()

    def apply_chart_theme(self, dark):
        """亮/暗主题切换（由各模块 apply_theme 调用）。"""
        self._dark = dark
        if self._engine is None:
            self._rebuild_widget()   # 占位控件按新主题重建配色
        elif self._engine == 'pyqtgraph':
            self._apply_pg_theme()
        else:
            self.figure.set_facecolor('#2d2d2d' if dark else '#fafafa')
            self._widget.draw()

    def clear_chart(self):
        """清空图表（各模块 clear_data 调用）。"""
        self._last = None
        self._spec = None
        if self._engine is None:
            return
        if self._engine == 'pyqtgraph':
            # 清数据同时清除悬停记录，避免恢复逻辑定位到已清空的图
            self._pg_hover_view = None
            self._hide_pg_hover()
            self._remove_pg_fit_texts()
            self._pg_fit_scatter = []   # 散点随 pi.clear() 移除，仅清引用
            # 增量缓存指向被清空的控件，作废（下次提交走全量重建重建缓存）
            self._pg_cache = None
            # 新数据到来散点恢复显示（清除状态不跨数据段）
            self._scatter_hidden = False
            # 离群点剔除状态一并重置（掩码/撤销栈/计数）
            self._reset_outlier_state()
            self._reset_clear_confirm()
            for pi in self._pg_plots:
                pi.clear()
        else:
            self.figure.clear()
            self._widget.draw()

    # ------------ 视图窗口控制 + 曲线拟合 + 离群点剔除（仅 pyqtgraph） ------------
    def get_analysis_panel(self):
        """返回紧凑纵向的图表分析面板（视图窗口 + 拟合 + 离群点剔除）。

        模块把该面板放进图表卡左侧栏（数据记录下方）即可；仅 pyqtgraph
        引擎下可见可用，matplotlib / 占位模式下自动隐藏（隐藏后不占布局
        空间）。懒创建：同一 ChartPanel 多次调用返回同一控件实例。
        """
        if self._analysis_panel is None:
            self._build_view_window_widget()
        return self._analysis_panel

    def _build_view_window_widget(self):
        """构建紧凑纵向的图表分析面板：视图窗口 + 曲线拟合 + 离群点剔除。

        面向图表卡左侧栏（窄列）排布：每个控件独占一行、按钮全宽紧凑，
        拟合注解用 CaptionLabel 自动换行，说明该方式的公式与数据要求
        （如定义域），用户无需查文档即可选对拟合类型。

        SwitchButton 的 on/off 文字必须用 setOnText/setOffText 指定中文：
        构造参数传入的文字会在 setChecked 时被默认的英文 On/Off 覆盖
        （无中文翻译器环境下）。
        """
        box = QWidget()
        box.setMinimumWidth(180)
        vlay = QVBoxLayout(box)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(8)

        self._win_switch = SwitchButton()
        self._win_switch.setOnText("显示整个范围")   # 勾选=显示全部数据
        self._win_switch.setOffText("滚动窗口")       # 取消=最近 N 秒
        self._win_switch.setChecked(True)          # 默认勾选＝现有自动量程行为
        self._win_switch.checkedChanged.connect(self._on_win_switch_changed)

        self._win_spin = DoubleSpinBox()
        self._win_spin.setRange(0.1, 10800.0)      # 0.1 秒 ~ 3 小时，支持小数
        self._win_spin.setDecimals(1)
        self._win_spin.setValue(self._win_seconds)
        self._win_spin.setSuffix(" 秒")
        self._win_spin.setMinimumWidth(96)
        self._win_spin.setEnabled(False)            # 整范围模式下输入框不可用
        self._win_spin.valueChanged.connect(self._on_win_seconds_changed)

        self._fit_combo = ComboBox()
        self._fit_combo.addItems(["无拟合", "线性拟合", "二次拟合", "三次拟合",
                                  "对数拟合", "幂函数拟合"])
        self._fit_combo.setCurrentIndex(0)
        self._fit_combo.setMinimumWidth(120)
        self._fit_combo.currentIndexChanged.connect(self._on_fit_type_changed)

        row_win = QWidget()
        lay_win = QHBoxLayout(row_win)
        lay_win.setContentsMargins(0, 0, 0, 0)
        lay_win.setSpacing(8)
        lay_win.addWidget(BodyLabel("最近"))
        lay_win.addWidget(self._win_spin)
        lay_win.addStretch(1)

        row_fit = QWidget()
        lay_fit = QHBoxLayout(row_fit)
        lay_fit.setContentsMargins(0, 0, 0, 0)
        lay_fit.setSpacing(8)
        lay_fit.addWidget(BodyLabel("拟合"))
        lay_fit.addWidget(self._fit_combo)
        lay_fit.addStretch(1)

        # 清除离散点：二次点击确认，防止误触删掉拟合时的原始散点。
        # 第一次点击进入确认态（文字变为「再次点击确认清除」+ 红色强调），
        # 3 秒内再次点击才真正清除；超时自动复位。
        self._clear_btn = PushButton("清除离散点")
        self._clear_btn.setFixedHeight(32)
        self._clear_btn.clicked.connect(self._on_clear_btn_clicked)
        self._clear_btn.setEnabled(False)   # 拟合未开启时不可用
        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.setInterval(3000)
        self._clear_timer.timeout.connect(self._reset_clear_confirm)

        # 离群点剔除：残差比例法。比例输入 + 剔除按钮 + 多级撤销 + 计数。
        # 仅拟合开启时可用（需要拟合曲线算残差）；剔除对显示曲线/散点/拟合/
        # R²/悬停/视图范围生效，不影响模块原始数据（见 _visible_spec）。
        self._outlier_spin = DoubleSpinBox()
        self._outlier_spin.setRange(0.5, 50.0)
        self._outlier_spin.setDecimals(1)
        self._outlier_spin.setValue(5.0)
        self._outlier_spin.setSuffix(" %")
        self._outlier_spin.setMinimumWidth(80)
        self._outlier_spin.setEnabled(False)
        self._outlier_spin.valueChanged.connect(self._sync_outlier_btn_state)

        self._outlier_btn = PushButton("剔除离群点")
        self._outlier_btn.setFixedHeight(32)
        self._outlier_btn.setEnabled(False)
        self._outlier_btn.clicked.connect(self._on_outlier_remove_clicked)

        self._outlier_undo_btn = PushButton("撤销")
        self._outlier_undo_btn.setFixedHeight(32)
        self._outlier_undo_btn.setEnabled(False)
        self._outlier_undo_btn.clicked.connect(self._on_outlier_undo_clicked)

        self._outlier_label = CaptionLabel("已移除 0 点")
        self._outlier_label.setFixedHeight(28)

        row_pct = QWidget()
        lay_pct = QHBoxLayout(row_pct)
        lay_pct.setContentsMargins(0, 0, 0, 0)
        lay_pct.setSpacing(8)
        lay_pct.addWidget(BodyLabel("剔除比例"))
        lay_pct.addWidget(self._outlier_spin)
        lay_pct.addStretch(1)

        row_undo = QWidget()
        lay_undo = QHBoxLayout(row_undo)
        lay_undo.setContentsMargins(0, 0, 0, 0)
        lay_undo.setSpacing(8)
        lay_undo.addWidget(self._outlier_undo_btn)
        lay_undo.addWidget(self._outlier_label)
        lay_undo.addStretch(1)

        # 拟合方式注解：次要说明文字，CaptionLabel 主题自适应（不设硬编码色）
        self._fit_hint = CaptionLabel()
        self._fit_hint.setWordWrap(True)
        self._update_fit_hint()

        vlay.addWidget(self._win_switch)
        vlay.addWidget(row_win)
        vlay.addWidget(row_fit)
        vlay.addWidget(self._clear_btn)
        vlay.addWidget(row_pct)
        vlay.addWidget(self._outlier_btn)
        vlay.addWidget(row_undo)
        vlay.addWidget(self._fit_hint)

        self._analysis_panel = box
        self._sync_view_window_visibility()

    def _on_win_switch_changed(self, checked):
        """勾选=显示整个范围（恢复自动量程/模块 xlim）；取消勾选=启用滚动窗口。"""
        self._win_full_range = checked
        if self._win_spin is not None:
            self._win_spin.setEnabled(not checked)
        self._apply_view_window()

    def _on_win_seconds_changed(self, value):
        """窗口秒数变化：滚动窗口模式下即时生效。"""
        self._win_seconds = value
        if not self._win_full_range:
            self._update_view_window()

    def _apply_view_window(self):
        """按开关状态应用视图范围（仅 pyqtgraph 生效）。"""
        if self._engine != 'pyqtgraph':
            return
        if self._win_full_range:
            # 回到整范围：重放最近一次事务，恢复模块设定的 xlim / 自动量程
            # （用户显式操作，强制立即重算量程，视图即时正确）
            if self._last is not None:
                self._commit(self._last, force_autorange=True)
            else:
                for pi in self._pg_plots:
                    pi.enableAutoRange(x=True)
                    pi.vb.updateAutoRange()
            return
        self._update_view_window()

    def _update_view_window(self, spec=None):
        """滚动窗口：把每个子图的 x 轴锁定为最近 N 秒。

        右边缘取该子图各曲线的最新横坐标，左边缘为「右边缘 - N 秒」；
        数据不足 N 秒时左边缘让位到最早数据点，不显示大片空白区。
        spec 缺省用最近一次已提交事务；数据提交路径（_commit_pg）传当次
        事务，保证窗口右边缘跟踪最新数据而非上一次事务。
        """
        if spec is None:
            spec = self._visible_spec(self._last)
        if (self._engine != 'pyqtgraph' or self._win_full_range
                or spec is None):
            return
        for pi, sp in zip(self._pg_plots, spec):
            x_first = x_last = None
            for s in sp['plot']:
                if not len(s['x']):
                    continue
                x0, x1 = s['x'][0], s['x'][-1]
                x_first = x0 if x_first is None else min(x_first, x0)
                x_last = x1 if x_last is None else max(x_last, x1)
            if x_last is None:              # 该子图暂无数据：回退自动量程
                pi.enableAutoRange(x=True)
                pi.vb.updateAutoRange()
                continue
            x_left = x_last - self._win_seconds
            if x_first is not None and x_left < x_first:
                x_left = x_first
            pi.setXRange(x_left, x_last, padding=0)

    def _sync_view_window_visibility(self):
        """分析面板仅在 pyqtgraph 引擎下显示。"""
        if self._analysis_panel is not None:
            self._analysis_panel.setVisible(self._engine == 'pyqtgraph')
        self._sync_clear_btn_state()
        self._sync_outlier_btn_state()

    # ---------------- 离群点剔除（残差比例法 + 多级撤销） ----------------
    def _visible_spec(self, spec):
        """返回剔除掩码作用后的可见事务副本。

        掩码只作用于每个子图的第一条曲线（拟合/剔除的对象曲线），其余
        曲线原样保留。无掩码时直接返回原对象（零开销，实时路径不触发
        复制）。掩码长度不足当前数据时按 True 补齐——新采集到的点
        不在掩码范围内，默认保留。
        """
        masks = self._outlier_masks
        if masks is None or spec is None:
            return spec
        import numpy as np
        out, changed = [], False
        for i, sp in enumerate(spec):
            m = masks[i] if i < len(masks) else None
            if m is None or not sp['plot']:
                out.append(sp)
                continue
            s = sp['plot'][0]
            x, y = s['x'], s['y']
            if not len(x):
                out.append(sp)
                continue
            m = np.asarray(m[:len(x)], dtype=bool)
            if len(m) < len(x):          # 新追加的点不在掩码内 → 保留
                m = np.concatenate([m, np.ones(len(x) - len(m), dtype=bool)])
            if bool(m.all()):
                out.append(sp)
                continue
            ns = dict(sp)
            ns['plot'] = [dict(s, x=np.asarray(x)[m], y=np.asarray(y)[m]),
                          *sp['plot'][1:]]
            out.append(ns)
            changed = True
        return out if changed else spec

    def _outlier_residuals(self, x, y):
        """当前拟合方式下每个点的 |残差|；定义域外的点返回 nan（不参与剔除）。

        与 _fit_points 使用同一套拟合定义：多项式对全部点、对数要求
        x>0、幂函数要求 x>0 且 y>0——定义域外的点只是不参与拟合，
        不应被当作离群点剔除，故标记为 nan。
        """
        import numpy as np
        mode = self._fit_mode
        if mode in (1, 2, 3):
            if len(x) < mode + 1:
                return None
            try:
                coef = np.polyfit(x, y, mode)
            except Exception:
                return None
            return np.abs(y - np.polyval(coef, x))
        if mode == 4:                    # 对数 y = a·ln(x) + b
            idx = np.flatnonzero(x > 0)
            if len(idx) < 2:
                return None
            try:
                a, b = np.polyfit(np.log(x[idx]), y[idx], 1)
            except Exception:
                return None
            res = np.full(len(x), np.nan)
            res[idx] = np.abs(y[idx] - (a * np.log(x[idx]) + b))
            return res
        if mode == 5:                    # 幂函数 y = a·x^b
            idx = np.flatnonzero((x > 0) & (y > 0))
            if len(idx) < 2:
                return None
            try:
                b_, ln_a = np.polyfit(np.log(x[idx]), np.log(y[idx]), 1)
                a = float(np.exp(ln_a))
            except Exception:
                return None
            res = np.full(len(x), np.nan)
            res[idx] = np.abs(y[idx] - a * x[idx] ** b_)
            return res
        return None

    def _on_outlier_remove_clicked(self):
        """「剔除离群点」：对当前剩余数据重拟合，移除残差最大的前 x% 点。

        每次点击都在**当前剩余数据**上剔除（多次点击可反复剔除）；
        剔除前把当前掩码压入撤销栈，供多级撤销。保证剩余点数满足
        当前拟合的最低要求（多项式 deg+1，对数/幂至少 2 点）。
        """
        if (self._engine != 'pyqtgraph' or self._fit_mode <= 0
                or self._last is None):
            return
        import numpy as np
        pct = self._outlier_spin.value() if self._outlier_spin else 5.0
        min_keep = self._fit_mode + 1 if self._fit_mode in (1, 2, 3) else 2
        old_masks = self._outlier_masks
        new_masks, removed_total = [], 0
        for sp in self._last:
            if not sp['plot'] or not len(sp['plot'][0]['x']):
                new_masks.append(old_masks[len(new_masks)]
                                 if old_masks and len(new_masks) < len(old_masks)
                                 else None)
                continue
            s = sp['plot'][0]
            x = np.asarray(s['x'], dtype=float)
            y = np.asarray(s['y'], dtype=float)
            # 当前可见数据的掩码（含 True 补齐），剔除只作用于可见点
            cur = old_masks[len(new_masks)] if (old_masks
                    and len(new_masks) < len(old_masks)) else None
            keep = None
            if cur is not None:
                # np.array() 强制拷贝：np.asarray(bool切片, dtype=bool) 会返回
                # 原掩码的视图，后续 keep[...] = False 会就地改掉栈里已保存的
                # 旧掩码，导致撤销失效（多级撤销链被上一帧污染）。
                keep = np.array(cur[:len(x)], dtype=bool, copy=True)
                if len(keep) < len(x):
                    keep = np.concatenate(
                        [keep, np.ones(len(x) - len(keep), dtype=bool)])
            vx = x if keep is None else x[keep]
            vy = y if keep is None else y[keep]
            res = self._outlier_residuals(vx, vy)
            if res is None:
                new_masks.append(cur)
                continue
            valid = np.flatnonzero(~np.isnan(res))   # 定义域内的候选点
            n_rem = max(1, int(round(len(valid) * pct / 100.0)))
            n_rem = min(n_rem, max(0, len(valid) - min_keep))
            if n_rem <= 0:
                new_masks.append(cur)
                continue
            order = valid[np.argsort(res[valid])[::-1]][:n_rem]  # 残差最大者
            if keep is None:
                keep = np.ones(len(x), dtype=bool)
            remove_orig = np.flatnonzero(keep)[order]            # 映射回原始下标
            keep[remove_orig] = False
            new_masks.append(keep)
            removed_total += int(n_rem)
        if removed_total == 0:
            return
        # 压栈（多级撤销）+ 应用新掩码 + 重绘
        self._outlier_stack.append(old_masks)
        self._outlier_masks = new_masks
        self._sync_outlier_btn_state()
        self._commit(self._last)

    def _on_outlier_undo_clicked(self):
        """「撤销」：回退到上一次剔除前的掩码（一步步恢复，退到底即全部恢复）。"""
        if self._outlier_stack:
            self._outlier_masks = self._outlier_stack.pop()
            self._sync_outlier_btn_state()
            if self._last is not None:
                self._commit(self._last)

    def _reset_outlier_state(self):
        """清空剔除状态（clear_chart 调用）：掩码、撤销栈、计数全部复位。"""
        self._outlier_masks = None
        self._outlier_stack = []
        self._sync_outlier_btn_state()

    def _update_outlier_label(self):
        """刷新「已移除 N 点」计数（按各子图掩码里的 False 数累加）。"""
        if self._outlier_label is None:
            return
        total = 0
        if self._outlier_masks is not None:
            import numpy as np
            for m in self._outlier_masks:
                if m is not None and m.size:
                    total += int(m.size - np.asarray(m, dtype=bool).sum())
        self._outlier_label.setText(f"已移除 {total} 点")

    def _sync_outlier_btn_state(self, *_args):
        """剔除控件可用性：仅 pyqtgraph + 拟合开启且有待处理数据时可用；
        撤销按钮有栈可退时可用；计数随掩码变化实时更新。"""
        if self._outlier_btn is None:
            return
        active = self._engine == 'pyqtgraph' and self._fit_mode > 0
        has_data = False
        if self._last is not None:
            has_data = any(
                sp['plot'] and len(sp['plot'][0]['x']) >= 2 for sp in self._last)
        if self._outlier_spin is not None:
            self._outlier_spin.setEnabled(active)
        self._outlier_btn.setEnabled(active and has_data)
        if self._outlier_undo_btn is not None:
            self._outlier_undo_btn.setEnabled(bool(self._outlier_stack))
        self._update_outlier_label()

    # ---------------- 曲线拟合（仅 pyqtgraph） ----------------
    # 拟合方式注解文案（索引与 _fit_combo / _fit_mode 一致）
    _FIT_HINTS = (
        "拟合：选择拟合方式后，在曲线上叠加同色虚线拟合曲线，并显示方程与 R²（越接近 1 拟合越好）。",
        "线性拟合 y = a·x + b：直线趋势，适合匀速变化的数据。",
        "二次拟合 y = a·x² + b·x + c：抛物线趋势，适合匀加速变化（如自由落体位移）。",
        "三次拟合 y = a·x³ + b·x² + c·x + d：S 形趋势，适合更复杂的变化。",
        "对数拟合 y = a·ln(x) + b：先快后缓并趋于平稳的趋势，要求数据 x > 0（x ≤ 0 的点自动剔除）。",
        "幂函数拟合 y = a·x^b：按比例缩放的关系（b=2 面积、b=3 体积类规律），要求数据 x > 0 且 y > 0。",
    )

    def _update_fit_hint(self):
        """按当前拟合方式刷新注解文字（选择变化时调用）。"""
        if self._fit_hint is not None:
            idx = self._fit_mode if self._fit_mode is not None else 0
            self._fit_hint.setText(self._FIT_HINTS[idx])

    def _on_fit_type_changed(self, index):
        """拟合方式切换：更新注解，重放最近一次事务叠加/移除拟合曲线。"""
        self._fit_mode = index    # 0=无拟合，1~3=多项式次数，4=对数，5=幂函数
        # 拟合状态属于结构：开关变化会使缓存中的结构签名失配，作废缓存
        # 强制下次提交走全量重建（顺带清掉旧拟合曲线/散点的场景残留）
        self._pg_cache = None
        # 重新选择拟合方式 → 散点恢复显示（清除状态只针对上一次选择）
        self._scatter_hidden = False
        self._update_fit_hint()
        self._sync_clear_btn_state()
        self._sync_outlier_btn_state()
        if self._last is not None:
            self._commit(self._last)

    def _on_clear_btn_clicked(self):
        """「清除离散点」按钮：二次点击才真正清除（防误触）。

        第一次点击进入确认态（按钮文字变警告提示 + 启动 3 秒定时器），
        3 秒内第二次点击才执行清除；超时自动复位。
        """
        if self._scatter_hidden or self._fit_mode <= 0:
            return
        if (self._clear_btn is not None
                and self._clear_btn.text() == "再次点击确认清除"):
            # 第二次点击：确认清除散点
            self._scatter_hidden = True
            self._pg_fit_scatter = []   # 引用作废（散点 item 随重绘 pi.clear 移除）
            self._reset_clear_confirm()
            self._sync_clear_btn_state()
            if self._last is not None:
                self._commit(self._last)   # 重绘：_draw_pg_fit 不再画散点
        else:
            # 第一次点击：进入确认态
            if self._clear_btn is not None:
                self._clear_btn.setText("再次点击确认清除")
            if self._clear_timer is not None:
                self._clear_timer.start()

    def _reset_clear_confirm(self):
        """退出确认态（清除完成或超时）：复位按钮文字与定时器。"""
        if self._clear_timer is not None and self._clear_timer.isActive():
            self._clear_timer.stop()
        if self._clear_btn is not None:
            self._clear_btn.setText("清除离散点")

    def _sync_clear_btn_state(self):
        """清除离散点按钮仅 pyqtgraph + 拟合开启 + 散点未被清除时可用。"""
        if self._clear_btn is not None:
            self._clear_btn.setEnabled(
                self._engine == 'pyqtgraph' and self._fit_mode > 0
                and not self._scatter_hidden)

    def _remove_pg_fit_texts(self):
        """从视口移除拟合方程文本（pi.clear() 不会移除，需手动清理）。"""
        for ti in self._pg_fit_texts:
            if ti.scene() is not None:
                ti.setParent(None)
        self._pg_fit_texts = []

    def _draw_pg_fit(self, spec):
        """对每个子图的第一条曲线做拟合并叠加显示。

        拟合曲线用同色虚线绘制，原始数据点以半透明散点叠加，便于直观
        对比数据分布与拟合贴合度；方程与 R² 以 TextItem 锚定视口左上角
        （跟随视口而非数据坐标，缩放/滚动窗口时位置稳定）。
        各模式共用本渲染骨架，数值计算见 _fit_points。
        """
        from pyqtgraph import mkPen, TextItem
        import numpy as np
        self._remove_pg_fit_texts()
        self._pg_fit_scatter = []         # 散点随 pi.clear() 移除，仅清引用
        if self._engine != 'pyqtgraph' or self._fit_mode <= 0:
            return
        fg = '#e0e0e0' if self._dark else '#1a1a1a'
        for pi, sp in zip(self._pg_plots, spec):
            if not sp['plot'] or not len(sp['plot'][0]['x']):
                continue
            s = sp['plot'][0]             # 拟合第一条曲线（模块主数据曲线）
            x = np.asarray(s['x'], dtype=float)
            y = np.asarray(s['y'], dtype=float)
            # 原始数据散点层：半透明小圆点（数据量过大时省略防卡顿；
            # 用户经「清除离散点」二次确认清除后不再绘制）
            if len(x) <= 3000 and not self._scatter_hidden:
                br = QColor(s['color']); br.setAlpha(90)
                pn = QColor(s['color']); pn.setAlpha(160)
                sc = pi.plot(x, y, pen=None, symbol='o', symbolSize=5,
                             symbolBrush=br, symbolPen=mkPen(pn, width=1))
                self._pg_fit_scatter.append(sc)
            fit = self._fit_points(x, y)
            if fit is None:               # 点数不足/定义域不满足：静默跳过
                continue
            xs, ys, text = fit
            # 拟合曲线：数据范围内 200 点虚线（颜色与原曲线一致）
            pen = mkPen(s['color'], width=2,
                        style=Qt.PenStyle.DashLine)
            pi.plot(xs, ys, pen=pen)
            # 方程文本：锚定视口左上角（视口本地坐标，不随数据缩放变化；
            # anchor=(0,0) 表示文本框左上角对齐 setPos 位置，pyqtgraph 0.14
            # 的 anchor 是构造参数/属性而非旧版锚定方法）
            ti = TextItem(text, color=fg, anchor=(0, 0))
            ti.setParentItem(pi.getViewBox())
            ti.setPos(8, 8)
            self._pg_fit_texts.append(ti)

    def _fit_points(self, x, y):
        """按当前拟合方式计算拟合曲线与方程文本。

        返回 (xs, ys, equation_text) 或 None（点数不足、数据不在函数
        定义域内、或拟合数值失败时静默跳过该子图）。

        各模式：
        - 1~3 多项式：y = aₙxⁿ + ... + a₀，np.polyfit 直接最小二乘
        - 4 对数：y = a·ln(x) + b，要求 x > 0（非正点剔除后拟合）
        - 5 幂函数：y = a·x^b，要求 x > 0 且 y > 0；对数线性化
          （ln y = b·ln x + ln a）求参，R² 按原始 y 尺度报告
        """
        import numpy as np
        mode = self._fit_mode
        if mode in (1, 2, 3):            # ---- 多项式 ----
            if len(x) < mode + 1:
                return None
            try:
                coef = np.polyfit(x, y, mode)
            except Exception:
                return None
            r2 = self._r_squared(y, np.polyval(coef, x))
            xs = np.linspace(float(x.min()), float(x.max()), 200)
            return xs, np.polyval(coef, xs), self._format_poly_equation(coef, r2)
        if mode == 4:                    # ---- 对数 y = a·ln(x) + b ----
            mask = x > 0                 # ln(x) 仅正数有定义
            if int(mask.sum()) < 2:
                return None
            xv, yv = x[mask], y[mask]
            try:
                a, b = np.polyfit(np.log(xv), yv, 1)
            except Exception:
                return None
            r2 = self._r_squared(yv, a * np.log(xv) + b)
            xs = np.linspace(float(xv.min()), float(xv.max()), 200)
            text = self._format_log_power_equation('log', float(a), float(b), r2)
            return xs, a * np.log(xs) + b, text
        if mode == 5:                    # ---- 幂函数 y = a·x^b ----
            mask = (x > 0) & (y > 0)     # 双对数线性化要求全为正
            if int(mask.sum()) < 2:
                return None
            xv, yv = x[mask], y[mask]
            try:
                b, ln_a = np.polyfit(np.log(xv), np.log(yv), 1)
            except Exception:
                return None
            a = float(np.exp(ln_a))
            r2 = self._r_squared(yv, a * xv ** b)
            xs = np.linspace(float(xv.min()), float(xv.max()), 200)
            text = self._format_log_power_equation('power', a, float(b), r2)
            return xs, a * xs ** b, text
        return None

    @staticmethod
    def _r_squared(y, y_pred):
        """决定系数 R² = 1 − SS_res / SS_tot（SS_tot 为 0 时返回 1）。"""
        import numpy as np
        ss_res = float(np.sum((y - y_pred) ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        return 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0

    @staticmethod
    def _format_poly_equation(coef, r2):
        """多项式方程文本：y = aₙxⁿ + ... + a₁x + a₀（4 位有效数字）。"""
        deg = len(coef) - 1
        sup = {1: '', 2: '²', 3: '³'}
        text = 'y = '
        for k, c in enumerate(coef):
            p = deg - k
            if k > 0:
                text += ' − ' if c < 0 else ' + '
            elif c < 0:
                text += '−'
            text += f"{abs(c):.4g}"
            if p > 0:
                text += 'x' + sup.get(p, f'^{p}')
        text += f"\nR² = {r2:.4f}"
        return text

    @staticmethod
    def _format_log_power_equation(kind, a, b, r2):
        """对数/幂函数方程文本（4 位有效数字，负号用 Unicode −）。

        kind='log'   → y = a·ln(x) + b
        kind='power' → y = a·x^b
        """
        if kind == 'log':
            sa = '−' if a < 0 else ''
            sb = ' − ' if b < 0 else ' + '
            text = f"y = {sa}{abs(a):.4g}·ln(x){sb}{abs(b):.4g}"
        else:
            sa = '−' if a < 0 else ''
            sb = '−' if b < 0 else ''
            text = f"y = {sa}{abs(a):.4g}·x^{sb}{abs(b):.4g}"
        text += f"\nR² = {r2:.4f}"
        return text


# ============================================================
# 串口通信线程
# ============================================================
class SerialThread(QThread):
    """串口通信线程"""
    data_received = Signal(str)

    def __init__(self, port, baudrate=115200):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.serial = None
        self.running = False

    def run(self):
        # pyserial 未安装：不发 ERROR 文本（各模块按连接失败弹窗处理）
        if not SERIAL_AVAILABLE:
            print("⚠️ pyserial 未安装，串口连接不可用")
            return
        try:
            self.serial = serial.Serial(self.port, self.baudrate, timeout=1)
            self.running = True
            self.serial.reset_input_buffer()

            while self.running:
                try:
                    if self.serial.in_waiting > 0:
                        line = self.serial.readline().decode('utf-8', errors='ignore').strip()
                        if line:
                            self.data_received.emit(line)
                except Exception as e:
                    print(f"读取串口数据错误: {e}")
                    break
        except Exception as e:
            print(f"串口错误: {e}")
            self.data_received.emit(f"ERROR:{e}")

    def stop(self):
        self.running = False
        if self.serial:
            self.serial.close()


def list_serial_ports():
    """枚举可用串口，返回 [(device, description), ...]。

    pyserial 未安装时返回空列表（调用方据此提示安装），
    其余情况任何异常都吞掉返回空列表，避免刷新按钮崩溃。
    """
    if not SERIAL_AVAILABLE:
        return []
    try:
        return [(p.device, p.description or "") for p in serial.tools.list_ports.comports()]
    except Exception as e:
        print(f"⚠️ 枚举串口失败: {e}")
        return []


def serial_unavailable_hint():
    """pyserial 未安装时的用户提示文案（供各模块弹窗使用）。"""
    return "未安装 pyserial，串口连接不可用。\n\n请安装后重启程序：\npip install pyserial\n\n提示：当前仍可使用「模拟器」模式体验全部功能。"


class SimulatorThread(QThread):
    """模拟器通信线程 — 无需传感器硬件，随机生成数据用于界面/逻辑调试。

    与 SerialThread 保持完全相同的信号接口（data_received = Signal(str)），
    因此可直接替换 SerialThread 使用。输出数据格式与真实固件一致：
    连接后先发送 "START"，随后按固定间隔发送 "timestamp_ms,raw_value"。

    数据生成方式：围绕一个缓慢漂移的基准值叠加随机噪声，保证曲线既有波动
    又连续自然（而非纯白噪声）。raw_value 范围由构造参数控制，以适配不同
    传感器的 ADC/物理量量程。

    Args:
        value_min: 生成原始值的下限（含）
        value_max: 生成原始值的上限（含）
        interval_ms: 发送间隔（毫秒），默认 100ms
        start_value: 初始基准值，默认取量程中点
        timestamp_scale: 时间戳单位缩放。1=毫秒（默认，与大多数固件一致），
                         1000=微秒（超声波固件 timestamp 以微秒计）
    """

    data_received = Signal(str)

    def __init__(self, value_min=0, value_max=4095, interval_ms=100, start_value=None,
                 timestamp_scale=1):
        super().__init__()
        self.value_min = int(value_min)
        self.value_max = int(value_max)
        self.interval_ms = max(10, int(interval_ms))
        self.timestamp_scale = max(1, int(timestamp_scale))
        self.running = False
        span = self.value_max - self.value_min
        self._value = float(start_value) if start_value is not None else self.value_min + span / 2.0
        # 每步基准值最大漂移量（量程的 0.5%），使曲线缓慢游走
        self._drift_step = max(1.0, span * 0.005)
        # 叠加的随机噪声幅度（量程的 1%）
        self._noise_amp = max(1.0, span * 0.01)

    def run(self):
        self.running = True
        # 与真实固件一致：连接成功后先发 START
        self.data_received.emit("START")
        start_s = time.time()
        while self.running:
            # 基准值随机游走
            self._value += random.uniform(-self._drift_step, self._drift_step)
            # 软边界：超出量程时向中心回弹
            if self._value < self.value_min:
                self._value = self.value_min + abs(self._value - self.value_min) * 0.5
            elif self._value > self.value_max:
                self._value = self.value_max - abs(self._value - self.value_max) * 0.5
            # 叠加噪声并取整
            raw = self._value + random.uniform(-self._noise_amp, self._noise_amp)
            raw = int(round(max(self.value_min, min(self.value_max, raw))))
            elapsed = int((time.time() - start_s) * 1000 * self.timestamp_scale)
            self.data_received.emit(f"{elapsed},{raw}")
            # 分段 sleep 以便 stop() 能快速响应
            slept = 0.0
            while self.running and slept < self.interval_ms / 1000.0:
                time.sleep(0.02)
                slept += 0.02

    def stop(self):
        self.running = False


# ============================================================
# BLE 通信（可选依赖 bleak）
# ============================================================
BLE_NUS_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
BLE_NUS_TX_UUID      = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
BLE_NUS_RX_UUID      = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"

try:
    from bleak import BleakClient, BleakScanner
    BLE_AVAILABLE = True
except ImportError:
    BLE_AVAILABLE = False
    # 启动控制台提示（用户指定文案）：蓝牙功能优雅降级，其余不受影响
    print("未安装bleak，蓝牙连接不可用。")


class BLESerialThread(QThread):
    """BLE 串口通信线程 — 基于 bleak 库连接 ESP32-S3 的 NUS 服务"""
    data_received = Signal(str)
    connection_status = Signal(str)

    def __init__(self, device_address, device_name=""):
        super().__init__()
        self.device_address = device_address
        self.device_name = device_name
        self.running = False
        self._buffer = ""
        self._client = None

    def run(self):
        if not BLE_AVAILABLE:
            self.data_received.emit("ERROR:bleak 库未安装，请运行 pip install bleak")
            return

        self.running = True
        try:
            asyncio.run(self._ble_loop())
        except asyncio.CancelledError:
            pass
        except Exception as e:
            error_msg = str(e)
            if "not found" in error_msg.lower() or "could not find" in error_msg.lower():
                self.data_received.emit("ERROR:设备未找到，请确保 ESP32-S3 已上电并配对")
            elif "timeout" in error_msg.lower():
                self.data_received.emit("ERROR:连接超时，请检查设备是否在范围内")
            else:
                self.data_received.emit(f"ERROR:BLE 连接失败: {error_msg}")

    async def _ble_loop(self):
        try:
            self._client = BleakClient(
                self.device_address,
                timeout=10.0,
                disconnected_callback=self._on_disconnected
            )
            await self._client.connect()

            if self._client.is_connected:
                self.connection_status.emit("connected")
                self.data_received.emit("START")
            else:
                self.data_received.emit("ERROR:连接建立失败")
                return

            try:
                await self._client.start_notify(BLE_NUS_TX_UUID, self._notification_handler)
            except Exception as e:
                self.data_received.emit(f"ERROR:无法订阅数据通知: {e}")
                return

            while self.running and self._client.is_connected:
                await asyncio.sleep(0.05)

            if self._client.is_connected:
                try:
                    await self._client.stop_notify(BLE_NUS_TX_UUID)
                except:
                    pass
                try:
                    await self._client.disconnect()
                except:
                    pass
        except Exception as e:
            raise e

    def _notification_handler(self, sender, data):
        try:
            text = data.decode('utf-8', errors='ignore')
            self._buffer += text
            while '\n' in self._buffer:
                line, self._buffer = self._buffer.split('\n', 1)
                line = line.strip()
                if line:
                    self.data_received.emit(line)
        except Exception as e:
            print(f"BLE 数据处理错误: {e}")

    def _on_disconnected(self, client):
        if self.running:
            self.data_received.emit("ERROR:设备意外断开连接")
            self.running = False

    def stop(self):
        self.running = False
        if self._client and self._client.is_connected:
            try:
                asyncio.run(self._client.disconnect())
            except:
                pass


def scan_ble_devices():
    """扫描附近的 BLE 设备，返回 [(名称, 地址), ...]"""
    if not BLE_AVAILABLE:
        return []
    try:
        devices = asyncio.run(BleakScanner.discover(timeout=5.0))
        result = []
        for d in devices:
            name = d.name or "未知设备"
            result.append((name, d.address))
        return sorted(result, key=lambda x: x[0])
    except Exception as e:
        print(f"BLE 扫描错误: {e}")
        return []


# ============================================================
# 可展开/收起的文本记录区
# ============================================================
class ExpandableTextEdit(QWidget):
    """可展开/收起的文本记录区。

    - 默认收起：只显示约 3 行高度（紧凑视图）
    - 点击"展开 ▼"按钮：向上扩展高度，显示更多内容
    - 点击"收起 ▲"按钮：恢复 3 行高度

    内部使用 qfluentwidgets.TextEdit 显示只读文本。
    用 setMaximumHeight 限制高度，避免抢占图表空间。
    """

    # 收起时高度（约 3 行 + 边距）
    COLLAPSED_HEIGHT = 64
    # 展开时高度（约 12 行）
    EXPANDED_HEIGHT = 280

    def __init__(self, parent=None):
        super().__init__(parent)
        self._expanded = False
        self._embedded = False
        self._longest_line_width = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 顶部行：标题 + 展开/收起按钮（用容器包裹，便于嵌入浮动面板时整体隐藏）
        self._header_container = QWidget()
        top_row = QHBoxLayout(self._header_container)
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)
        # 使用 fluent 主题化标签，自动适配亮/暗主题
        self.title_label = StrongBodyLabel("数据记录")
        top_row.addWidget(self.title_label)
        top_row.addStretch()

        self.toggle_btn = HyperlinkButton()
        self.toggle_btn.setText("展开 ▼")
        self.toggle_btn.setFixedHeight(24)
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.clicked.connect(self._toggle)
        top_row.addWidget(self.toggle_btn)
        layout.addWidget(self._header_container)

        # 文本区：小字号 + 不自动换行，宽度按最长一行数据动态预留
        self.text_edit = TextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont("Cascadia Code", 8))
        opt = QTextOption()
        opt.setWrapMode(QTextOption.WrapMode.NoWrap)
        self.text_edit.document().setDefaultTextOption(opt)
        self.text_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.text_edit, 1)

        # 初始应用折叠状态
        self._apply_state()

    def _toggle(self):
        """切换展开/收起状态"""
        self._expanded = not self._expanded
        self._apply_state()

    def _apply_state(self):
        """根据当前状态应用高度约束和文字"""
        if self._embedded:
            # 嵌入模式：由父容器控制大小，自身不设高度约束
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            self.text_edit.setMaximumHeight(16777215)
            self.toggle_btn.setText("收起 ▲" if self._expanded else "展开 ▼")
        elif self._expanded:
            # 展开状态：文本区最大 EXPANDED_HEIGHT，外部 widget 自适应
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            self.text_edit.setMaximumHeight(self.EXPANDED_HEIGHT)
            self.toggle_btn.setText("收起 ▲")
        else:
            # 折叠状态：固定高度为 COLLAPSED_HEIGHT + 标题行
            header_h = self._header_container.sizeHint().height()
            total_h = header_h + 4 + self.COLLAPSED_HEIGHT
            self.setFixedHeight(total_h)
            self.text_edit.setMaximumHeight(self.COLLAPSED_HEIGHT)
            self.toggle_btn.setText("展开 ▼")

    # 代理 TextEdit 的常用方法，保持与原 data_text 调用兼容
    def append(self, text):
        self.text_edit.append(text)
        self._track_line_width(text)

    def setPlainText(self, text):
        self.text_edit.setPlainText(text)
        self._longest_line_width = 0
        for line in text.split("\n"):
            self._track_line_width(line)

    def _track_line_width(self, text):
        """记录最长一行数据的像素宽度，动态调整预留宽度，
        保证左侧数据记录区始终能完整放下一行数据。"""
        w = QFontMetrics(self.text_edit.font()).horizontalAdvance(text)
        if w > self._longest_line_width:
            self._longest_line_width = w
            # 文本区左右内边距 + 垂直滚动条 + 少量余量
            self.text_edit.setMinimumWidth(w + 48)

    def clear(self):
        self.text_edit.clear()

    def toPlainText(self):
        return self.text_edit.toPlainText()

    def verticalScrollBar(self):
        return self.text_edit.verticalScrollBar()

    def set_embedded_mode(self, enabled=True):
        """嵌入模式：隐藏自身标题栏（用于浮动面板内，避免与面板标题重复）"""
        self._embedded = enabled
        self._header_container.setVisible(not enabled)
        self._apply_state()


# ============================================================
# 浮动数据面板（全屏图表模式）
# ============================================================
class FloatingDataPanel(QWidget):
    """可拖动、可折叠的浮动数据面板。

    全屏图表模式下，实时数据以浮动小窗形式显示在图表上方。
    - 展开态：标题 + 完整实时数据内容 + 折叠按钮
    - 折叠态：标题 + 主实时值摘要 + 展开按钮
    - 鼠标按住面板空白区域可拖动，自动限制在父控件范围内
    """

    MAX_SUMMARY_LEN = 50

    def __init__(self, content_widget, summary_widget=None, title="数据记录",
                 footer_widget=None, parent=None):
        super().__init__(parent)
        self._content_widget = content_widget
        self._summary_widget = summary_widget
        self._footer_widget = footer_widget
        self._collapsed = False
        self._dragging = False
        self._drag_offset = QPoint()

        self.setObjectName("floating_panel")
        self.setMaximumWidth(420)
        self.setMinimumWidth(280)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 8, 12, 10)
        main_layout.setSpacing(6)

        # 标题行
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        self.title_label = StrongBodyLabel(title)
        self.title_label.setStyleSheet("background: transparent; border: none;")
        header_layout.addWidget(self.title_label)

        self.summary_label = QLabel("")
        self.summary_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self.summary_label.setStyleSheet("color: #0078d4; background: transparent; border: none;")
        self.summary_label.hide()
        header_layout.addWidget(self.summary_label)
        header_layout.addStretch()

        self.toggle_btn = PrimaryPushButton("折叠")
        self.toggle_btn.setFixedHeight(26)
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.clicked.connect(self._toggle)
        header_layout.addWidget(self.toggle_btn)

        main_layout.addLayout(header_layout)

        # 完整内容
        self._content_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        main_layout.addWidget(self._content_widget, 1)

        # 底部常驻控件：折叠内容后仍可见（如开始/停止按钮）
        if self._footer_widget is not None:
            main_layout.addWidget(self._footer_widget)

        # 定时刷新折叠态摘要文本（实时值在持续更新）
        self._summary_timer = QTimer(self)
        self._summary_timer.timeout.connect(self._update_summary)
        self._summary_timer.start(100)

        self._update_summary()

        # 默认展开尺寸
        self.resize(380, 360)

    def _toggle(self):
        """切换折叠/展开状态"""
        self._collapsed = not self._collapsed
        self._content_widget.setVisible(not self._collapsed)
        self.summary_label.setVisible(self._collapsed)
        self.toggle_btn.setText("展开" if self._collapsed else "折叠")
        self._update_summary()
        self.adjustSize()

    def _update_summary(self):
        """从 summary_widget 读取当前实时值，更新折叠态摘要显示"""
        if self._summary_widget is not None:
            text = self._summary_widget.text()
            # 去掉常见前缀，保持摘要简洁
            for prefix in ("当前数据: ", "电压: ", "电流: "):
                if text.startswith(prefix):
                    text = text[len(prefix):]
                    break
            if len(text) > self.MAX_SUMMARY_LEN:
                text = text[:self.MAX_SUMMARY_LEN - 3] + "..."
            self.summary_label.setText(text)

    def release_content(self):
        """将内容控件从面板中移出（reparent 到 None），返回内容控件。

        在销毁浮动面板前调用，避免内容控件随面板一起被删除。
        """
        if self._content_widget is not None:
            self.layout().removeWidget(self._content_widget)
            self._content_widget.setParent(None)
            widget = self._content_widget
            self._content_widget = None
            return widget
        return None

    def release_footer(self):
        """把底部常驻控件从面板布局中移出并返回，避免它随面板销毁。

        退出全屏后模块仍持有该控件（如开始/停止按钮），再次全屏复用。
        """
        if self._footer_widget is not None:
            self.layout().removeWidget(self._footer_widget)
            self._footer_widget.setParent(None)
            w = self._footer_widget
            self._footer_widget = None
            return w
        return None

    def paintEvent(self, e):
        """绘制半透明圆角背景，颜色随主题切换。"""
        c = _theme_colors()
        if isDarkTheme():
            bg = QColor(45, 45, 45, 245)
            border = QColor("#5d5d5d")
        else:
            bg = QColor(255, 255, 255, 245)
            border = QColor("#b0b0b0")
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(bg))
        painter.setPen(QPen(border, 1))
        path = QPainterPath()
        path.addRoundedRect(0.5, 0.5, self.width() - 1, self.height() - 1, 8, 8)
        painter.drawPath(path)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            # 点击按钮时不启动拖动
            child = self.childAt(e.position().toPoint())
            if child is not self.toggle_btn:
                self._dragging = True
                self._drag_offset = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._dragging:
            new_pos = self.pos() + e.position().toPoint() - self._drag_offset
            parent = self.parent()
            if parent is not None:
                new_pos.setX(max(0, min(new_pos.x(), parent.width() - self.width())))
                new_pos.setY(max(0, min(new_pos.y(), parent.height() - self.height())))
            self.move(new_pos)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._dragging = False
        super().mouseReleaseEvent(e)

    def clamp_position(self):
        """限制面板位置在父控件范围内（父控件 resize 时调用）"""
        parent = self.parent()
        if parent is None:
            return
        x = max(0, min(self.x(), parent.width() - self.width()))
        y = max(0, min(self.y(), parent.height() - self.height()))
        self.move(x, y)


# ============================================================
# 可折叠卡片
# ============================================================
class CollapsibleCard(QWidget):
    """可折叠卡片：点击标题区切换内容显示/隐藏。

    - 折叠时：只显示标题 + 向下箭头 ▼
    - 展开时：显示标题 + 全部内容 + 向上箭头 ▲

    外观为白底 + 圆角 + 浅灰边框，与主页卡片一致。
    用 paintEvent 直接绘制白色背景，避免父级样式表级联覆盖。

    使用方式：
        content = QWidget()
        content_layout = QVBoxLayout(content)
        ...  # 添加内容控件
        card = CollapsibleCard("卡片标题", content, expanded=True)
        parent_layout.addWidget(card)
    """

    CARD_STYLE = """
        QWidget#collapsible_card QWidget {
            background: transparent;
        }
        /* 卡片内部内容容器（QWidget#card）不需要重复边框，
           外层 CollapsibleCard 已通过 paintEvent 绘制圆角边框；
           否则其顶部 border 会显示为标题与内容之间的分割线 */
        QWidget#collapsible_card QWidget#card {
            border: none;
        }
        QWidget#collapsible_card QComboBox,
        QWidget#collapsible_card QTextEdit,
        QWidget#collapsible_card QPlainTextEdit,
        QWidget#collapsible_card QSpinBox,
        QWidget#collapsible_card QDoubleSpinBox,
        QWidget#collapsible_card QLineEdit,
        QWidget#collapsible_card QListView,
        QWidget#collapsible_card QTreeView,
        QWidget#collapsible_card QTableView,
        QWidget#collapsible_card QScrollArea,
        QWidget#collapsible_card QAbstractScrollArea {
            background: #ffffff;
        }
        QFrame#collapsible_header {
            background: transparent;
            border: none;
            border-radius: 8px;
        }
        QFrame#collapsible_header:hover {
            background: #fafafa;
        }
    """

    class _Header(QFrame):
        """可点击的标题栏（QFrame + mouseReleaseEvent）。"""

        clicked = Signal()

        def mouseReleaseEvent(self, e):
            if e.button() == Qt.MouseButton.LeftButton:
                self.clicked.emit()
            super().mouseReleaseEvent(e)

    def __init__(self, title, content_widget, parent=None, expanded=True, fullscreen=False):
        super().__init__(parent)
        self._expanded = expanded
        self._content_widget = content_widget
        self._fullscreen = False  # 当前是否处于全屏状态
        self._fullscreen_enabled = fullscreen  # 是否启用全屏按钮
        self._orig_parent = None  # 全屏前的父控件
        self._orig_layout = None  # 全屏前所在的布局
        self._orig_index = -1     # 全屏前在布局中的索引
        self._host = None         # 全屏时的宿主 viewport
        self._scroll = None       # 全屏时的 QScrollArea
        # 全屏浮动面板相关
        self._overlay_content_widget = None   # 全屏时浮于图表上方的控件（如数据记录区）
        self._overlay_summary_widget = None   # 折叠态显示的摘要标签（如实时值）
        self._overlay_extra_widgets = []      # 一并浮起的附加控件（如拟合分析面板）
        self._overlay_footer_widget = None    # 浮动栏底部常驻控件（折叠时也可见）
        self._overlay_orig_records = []       # 每个浮动控件的 (控件, 原父, 布局, 索引, stretch)
        self._floating_panel = None           # 全屏时的 FloatingDataPanel 实例
        self._fullscreen_hidden_widgets = []  # 全屏时需隐藏的控件
        self._chart_min_height = 0            # 图表内容区最小高度（0 表示不限制）

        self.setObjectName("collapsible_card")
        self.setStyleSheet(self.CARD_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题栏（可点击 QFrame）
        self.header = self._Header()
        self.header.setObjectName("collapsible_header")
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(24, 14, 24, 14)
        header_layout.setSpacing(8)

        # 用 SubtitleLabel 替代手写 QLabel，自动随 FluentWidgets 主题切换文字颜色
        self.title_label = SubtitleLabel(title)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        # 全屏按钮（可选）
        if self._fullscreen_enabled:
            # 醒目文字提示：点击与按钮一样触发全屏
            self.fullscreen_hint = QLabel("全屏查看图表")
            self.fullscreen_hint.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            self.fullscreen_hint.setCursor(Qt.CursorShape.PointingHandCursor)
            self.fullscreen_hint.setObjectName("card_accent_text")
            self.fullscreen_hint.mouseReleaseEvent = lambda e: (
                self.toggle_fullscreen()
                if e.button() == Qt.MouseButton.LeftButton else None)
            header_layout.addWidget(self.fullscreen_hint)

            self.fullscreen_btn = QPushButton("⛶")
            self.fullscreen_btn.setFixedSize(28, 28)
            self.fullscreen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.fullscreen_btn.setToolTip("全屏显示 / 退出全屏")
            self.fullscreen_btn.setObjectName("card_accent_btn")
            self.fullscreen_btn.clicked.connect(self.toggle_fullscreen)
            header_layout.addWidget(self.fullscreen_btn)

        self.arrow_label = QLabel("▲" if expanded else "▼")
        self.arrow_label.setFont(QFont("Segoe UI", 12))
        self.arrow_label.setObjectName("card_arrow")
        header_layout.addWidget(self.arrow_label)

        self.header.clicked.connect(self._toggle)
        layout.addWidget(self.header)

        # 内容区（stretch=1 填满标题栏下方剩余空间）
        # 必须先 addWidget（设置父级）再 setVisible，
        # 否则无父级的 content_widget 会被当作顶级窗口闪现
        layout.addWidget(self._content_widget, 1)
        self._content_widget.setVisible(expanded)

        # 应用一次主题样式（标题色、箭头色、全屏按钮色等）
        self._apply_theme_style()

    def set_chart_min_height(self, height):
        """设置图表内容区的最小高度（用于加高图表卡片）。

        通过同时抬高 sizeHint 与 minimumSizeHint，让外层滚动区布局
        为图表卡片分配足够高度，页面滚动查看即可，不要求一页放下。
        """
        self._chart_min_height = height
        self._content_widget.setMinimumHeight(height)

    def apply_theme(self, theme):
        """主题切换时刷新卡片内部硬编码颜色（箭头、全屏按钮等）。

        title_label 用 SubtitleLabel，会自动随 FluentWidgets 主题更新；
        但全屏按钮、全屏提示文字、箭头是用 QLabel/QPushButton + 硬编码
        QSS 画的，需要在这里手动刷新。
        """
        self._apply_theme_style()
        # 内容区里的卡片（QWidget#card）样式表也需要刷新
        # 通过查找子 widget 并刷新同名样式表即可，但更稳的做法是让
        # 外层模块自己刷新——这里只负责卡片自身 header。

    def _apply_theme_style(self):
        """按当前主题刷新 header 内的箭头、全屏按钮、全屏提示文字颜色。"""
        c = _theme_colors()
        # 箭头：使用次要文字色
        self.arrow_label.setStyleSheet(
            f"color: {c['text_secondary']}; background: transparent;")
        # 全屏提示文字与按钮：使用强调色
        if hasattr(self, 'fullscreen_hint'):
            self.fullscreen_hint.setStyleSheet(
                f"color: {c['accent']}; padding: 0 2px; background: transparent;")
        if hasattr(self, 'fullscreen_btn'):
            self.fullscreen_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    border-radius: 4px;
                    font-size: 16px;
                    color: {c['accent']};
                }}
                QPushButton:hover {{ background: {c['hover_bg']}; color: {c['accent']}; }}
            """)

    def sizeHint(self):
        hint = super().sizeHint()
        if self._chart_min_height > 0 and self._expanded:
            hint.setHeight(max(hint.height(),
                               self.header.sizeHint().height() + self._chart_min_height))
        return hint

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        if self._chart_min_height > 0 and self._expanded:
            hint.setHeight(max(hint.height(),
                               self.header.sizeHint().height() + self._chart_min_height))
        return hint

    def paintEvent(self, e):
        """直接用 QPainter 绘制圆角背景，绕过样式表级联覆盖。

        颜色按当前 FluentWidgets 主题切换：亮色画白底浅灰边，
        暗色画深灰底深灰边，与 FluentWidgets 自带卡片视觉一致。
        """
        c = _theme_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(QColor(c['card_bg'])))
        painter.setPen(QPen(QColor(c['card_border']), 1))
        path = QPainterPath()
        path.addRoundedRect(0.5, 0.5, self.width() - 1, self.height() - 1, 8, 8)
        painter.drawPath(path)

    def _toggle(self):
        """切换展开/折叠状态，并同步箭头方向"""
        self._expanded = not self._expanded
        self._content_widget.setVisible(self._expanded)
        self.arrow_label.setText("▲" if self._expanded else "▼")

    def toggle_fullscreen(self):
        """切换全屏/还原。

        全屏时：把卡片 reparent 到模块的滚动区 viewport 上，作为覆盖层填满整个内容区，
        不覆盖侧边栏和标题栏（因为 viewport 本身就在内容区内）。
        还原时：把卡片 reparent 回原父控件，插回原布局原位置。
        """
        if not self._fullscreen:
            self._enter_fullscreen()
        else:
            self._exit_fullscreen()

    # ---------- 全屏浮动面板接口 ----------
    def set_fullscreen_overlay(self, content_widget, summary_widget=None,
                               extra_widgets=None, footer_widget=None):
        """设置全屏时浮动面板的内容控件。

        Args:
            content_widget: 全屏时浮于图表上方的控件（如数据记录区文本框）。
                            全屏时该控件会被移入可拖动、可折叠的浮动面板；
                            退出全屏时自动恢复到原布局原位置。
            summary_widget: 折叠态显示的摘要标签（如实时值标签，可选）
            extra_widgets: 一并浮起的附加控件列表（如拟合分析面板，可选）
            footer_widget: 浮动栏底部常驻控件，折叠时也可见
                           （如开始/停止按钮，可选）
        """
        self._overlay_content_widget = content_widget
        self._overlay_summary_widget = summary_widget
        self._overlay_extra_widgets = list(extra_widgets or [])
        self._overlay_footer_widget = footer_widget

    def add_fullscreen_hidden_widget(self, widget):
        """注册全屏时需隐藏的控件"""
        self._fullscreen_hidden_widgets.append(widget)

    def _detach_overlay_widgets(self):
        """从原布局中移除全部浮动内容控件，并记录原位置以便恢复。

        Returns: 被移除的控件列表（可能为空）
        """
        widgets = [self._overlay_content_widget, *self._overlay_extra_widgets]
        self._overlay_orig_records = []
        detached = []
        for widget in widgets:
            if widget is None:
                continue
            orig_parent = widget.parentWidget()
            orig_layout, orig_index, orig_stretch = None, -1, 0
            if orig_parent is not None:
                # 在父控件的布局树中递归查找包含该 widget 的布局及索引
                result = self._find_widget_in_layout_tree(
                    orig_parent.layout(), widget)
                if result is not None:
                    orig_layout, orig_index = result
            if orig_layout is not None:
                # 记录 stretch factor
                item = orig_layout.itemAt(orig_index)
                if item is not None:
                    try:
                        orig_stretch = orig_layout.stretch(orig_index)
                    except Exception:
                        orig_stretch = 0
                orig_layout.removeWidget(widget)
            widget.setParent(None)
            self._overlay_orig_records.append(
                (widget, orig_parent, orig_layout, orig_index, orig_stretch))
            detached.append(widget)
        return detached

    @staticmethod
    def _find_widget_in_layout_tree(layout, target):
        """在布局树中递归查找 target widget，返回 (layout, index) 或 None"""
        if layout is None:
            return None
        for i in range(layout.count()):
            it = layout.itemAt(i)
            if it is None:
                continue
            if it.widget() is target:
                return (layout, i)
            sub = it.layout()
            if sub is not None:
                r = CollapsibleCard._find_widget_in_layout_tree(sub, target)
                if r is not None:
                    return r
        return None

    def _restore_overlay_widgets(self):
        """将浮动内容控件恢复到原布局原位置。

        按原索引升序恢复同一布局内的多个控件，保持相对顺序正确。
        Returns: 已恢复的控件列表
        """
        restored = []
        for widget, orig_parent, orig_layout, orig_index, orig_stretch in sorted(
                self._overlay_orig_records, key=lambda r: r[3]):
            if orig_layout is None:
                continue
            widget.setParent(orig_parent)
            if orig_index >= 0:
                orig_layout.insertWidget(orig_index, widget, orig_stretch)
            else:
                orig_layout.addWidget(widget, orig_stretch)
            widget.show()
            restored.append(widget)
        self._overlay_orig_records = []
        return restored

    def _find_content_host(self):
        """向上查找适合作为全屏宿主的滚动区 viewport。

        传感器模块结构：模块widget -> main_layout -> scroll(QScrollArea) -> content。
        全屏时覆盖到 scroll 的 viewport 上，这样能利用整个内容区，且不覆盖侧边栏/标题栏。
        """
        from PySide6.QtWidgets import QScrollArea
        p = self.parent()
        while p is not None:
            if isinstance(p, QScrollArea):
                return p.viewport()  # scroll 的 viewport
            p = p.parent()
        return None

    def _find_scroll_area(self):
        """向上查找 QScrollArea，用于监听尺寸变化"""
        from PySide6.QtWidgets import QScrollArea
        p = self.parent()
        while p is not None:
            if isinstance(p, QScrollArea):
                return p
            p = p.parent()
        return None

    def _enter_fullscreen(self):
        """进入全屏：reparent 到 viewport，绝对定位填满"""
        from PySide6.QtWidgets import QScrollArea
        host = self._find_content_host()
        if host is None:
            return
        scroll = self._find_scroll_area()
        if scroll is None:
            return

        # 记录原位置
        self._orig_parent = self.parent()
        pl = self._orig_parent.layout()
        self._orig_layout = None
        self._orig_index = -1
        if pl is not None:
            for i in range(pl.count()):
                it = pl.itemAt(i)
                if it and it.widget() is self:
                    self._orig_index = i
                    self._orig_layout = pl
                    break

        # 从原布局移除（不删除 widget）
        if self._orig_layout is not None:
            self._orig_layout.removeWidget(self)

        # reparent 到 viewport，绝对定位填满
        self.setParent(host)
        self._host = host
        self._scroll = scroll
        self._fullscreen = True
        if hasattr(self, 'fullscreen_hint'):
            self.fullscreen_hint.setText("退出全屏")

        # 隐藏滚动条（全屏时不滚动）
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # 安装事件过滤器监听 viewport 尺寸变化
        host.installEventFilter(self)

        # 隐藏注册的控件（如数据记录区），让图表 canvas 填满整个区域
        for w in self._fullscreen_hidden_widgets:
            w.setVisible(False)

        # reparent 后必须显式 show()，否则 Qt 可能将卡片及其内容（含图表）标记为不可见
        self.show()
        self.header.setVisible(True)
        self.title_label.setVisible(True)
        self.arrow_label.setVisible(True)
        if hasattr(self, 'fullscreen_btn'):
            self.fullscreen_btn.setVisible(True)
        # 内容区（含 FigureCanvas）必须可见
        self._content_widget.setVisible(True)

        # 立即设置一次几何，再用延迟回调修正（隐藏滚动条后 viewport 尺寸会变化）
        self.setGeometry(0, 0, host.width(), host.height())
        self.raise_()
        # 强制布局重算，确保图表 canvas 拿到正确尺寸
        if self.layout() is not None:
            self.layout().activate()

        # 创建浮动数据面板：将数据记录区与分析控件浮于图表上方
        if self._overlay_content_widget is not None:
            detached = self._detach_overlay_widgets()
            if detached:
                # 嵌入模式：隐藏 data_text 自身标题栏，避免与浮动面板标题重复
                for w in detached:
                    if hasattr(w, 'set_embedded_mode'):
                        w.set_embedded_mode(True)
                # 多个浮动控件（如数据记录区 + 拟合分析面板）纵向堆叠进一个容器
                overlay_box = QWidget()
                box_lay = QVBoxLayout(overlay_box)
                box_lay.setContentsMargins(0, 0, 0, 0)
                box_lay.setSpacing(10)
                for w in detached:
                    box_lay.addWidget(w)
                self._floating_panel = FloatingDataPanel(
                    overlay_box,
                    summary_widget=self._overlay_summary_widget,
                    footer_widget=self._overlay_footer_widget,
                    parent=self,
                )
                self._floating_panel.move(16, 16)
                self._floating_panel.show()
                self._floating_panel.raise_()

        # 延迟修正几何：等滚动条隐藏、viewport 尺寸更新后再最终定位
        def _fix_geom():
            if self._fullscreen and self._host is not None:
                self.setGeometry(0, 0, self._host.width(), self._host.height())
                if self.layout() is not None:
                    self.layout().activate()
                # 触发内部 matplotlib canvas 重绘
                self._redraw_canvas()
                # 浮动面板可能需要调整位置
                if self._floating_panel is not None:
                    self._floating_panel.clamp_position()
        QTimer.singleShot(0, _fix_geom)

    def _redraw_canvas(self):
        """查找卡片内的 FigureCanvas 并触发重绘，避免全屏后图表空白"""
        try:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        except Exception:
            return
        # 在内容区递归查找 FigureCanvas
        def _find(w):
            if isinstance(w, FigureCanvasQTAgg):
                return w
            for child in w.children():
                r = _find(child)
                if r is not None:
                    return r
            return None
        canvas = _find(self._content_widget)
        if canvas is not None:
            try:
                canvas.draw()
            except Exception:
                pass

    def _exit_fullscreen(self):
        """退出全屏：reparent 回原父控件，插回原位置"""
        if self._host is None:
            return
        # 移除事件过滤器
        self._host.removeEventFilter(self)

        # 恢复滚动条
        if self._scroll is not None:
            self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # 销毁浮动数据面板，恢复内容控件到原布局
        if self._floating_panel is not None:
            released = self._floating_panel.release_content()
            self._floating_panel.release_footer()
            self._floating_panel.deleteLater()
            self._floating_panel = None
            # 关闭嵌入模式，恢复 data_text 自身标题栏
            for w in self._restore_overlay_widgets():
                if hasattr(w, 'set_embedded_mode'):
                    w.set_embedded_mode(False)
            # released 是临时容器，子控件已恢复回原布局，直接销毁
            if released is not None:
                released.deleteLater()

        # 恢复全屏时隐藏的控件
        for w in self._fullscreen_hidden_widgets:
            w.setVisible(True)

        # reparent 回原父控件
        self.setParent(self._orig_parent)
        if self._orig_layout is not None and self._orig_index >= 0:
            self._orig_layout.insertWidget(self._orig_index, self)

        self._fullscreen = False
        self._host = None
        self._scroll = None
        if hasattr(self, 'fullscreen_hint'):
            self.fullscreen_hint.setText("全屏查看图表")

        # reparent 后显式 show，确保卡片及其内容可见
        self.show()
        self._content_widget.setVisible(self._expanded)
        if self.layout() is not None:
            self.layout().activate()
        # 延迟重绘 canvas，等布局稳定
        QTimer.singleShot(0, self._redraw_canvas)

    def eventFilter(self, obj, e):
        """监听 viewport 尺寸变化，全屏时跟随"""
        from PySide6.QtCore import QEvent
        if obj is self._host and e.type() == QEvent.Type.Resize:
            if self._fullscreen and self._host is not None:
                self.setGeometry(0, 0, self._host.width(), self._host.height())
                if self._floating_panel is not None:
                    self._floating_panel.clamp_position()
        return super().eventFilter(obj, e)


class FluentCard(ExpandGroupSettingCard):
    """基于 FluentWidgets 原生 ExpandGroupSettingCard 的紧凑卡片适配层。

    用于替换模块内的普通自绘 CollapsibleCard（连接控制/参数/实时数据/
    操作按钮等），让卡片视觉贴合 WinUI3 原生风格：

    - 继承原生 ExpandGroupSettingCard：自带主题自适应背景/分隔线/展开
      箭头（带旋转动画），亮暗主题切换无需手动刷 QSS。
    - 内容用紧凑 QVBoxLayout（20px 内边距 / 10px 行距），替代原生分组
      行的稀疏 60px 行高布局；模块经 add_row(...) 或 body() 填充。
    - header 右侧可追加按钮（add_header_widget），供图表卡放全屏等操作。
    - 修正原生卡的滚动冲突：wheelEvent 透传给父级，避免它在模块外层
      QScrollArea 内吞掉滚轮。
    - apply_theme() 兼容 apply_module_theme 的递归调用约定。

    图表卡片（需要全屏/浮动面板能力）仍用 CollapsibleCard，不替换。
    """
    ICON = None  # 子类可替换 header 图标（FluentIcon）

    def __init__(self, title, content_widget=None, expanded=True):
        super().__init__(self.__class__.ICON or FluentIcon.FOLDER, title, None, None)

        # 内容容器：紧凑布局
        self.content = QWidget()
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(20, 8, 20, 16)
        self.body.setSpacing(10)

        # 兼容 CollapsibleCard 旧调用：直接传入已构建好的内容控件。
        # 剥离其旧的 objectName='card' + card_style()（原生卡自带背景，
        # 避免双层边框/背景），并填满内容区。
        if content_widget is not None:
            if content_widget.objectName() == 'card':
                content_widget.setObjectName('')
                content_widget.setStyleSheet('')
            self.body.addWidget(content_widget, 1)
        else:
            self.body.addStretch(0)

        self.viewLayout.setContentsMargins(0, 0, 0, 0)
        self.viewLayout.setSpacing(0)
        self.viewLayout.addWidget(self.content)

        self.setExpand(expanded)

    # ---------- 内容填充 ----------
    def add_row(self, label, widget):
        """添加一行「标签 + 控件」的紧凑行。"""
        row = QHBoxLayout()
        row.setSpacing(8)
        if label:
            row.addWidget(BodyLabel(label))
        row.addWidget(widget)
        row.addStretch()
        self.body.insertLayout(self.body.count() - 1, row)
        return row

    def add_widget(self, widget):
        """直接向内容区追加一个控件。"""
        self.body.insertWidget(self.body.count() - 1, widget)
        return widget

    def add_layout(self, layout):
        """直接向内容区追加一个布局。"""
        self.body.insertLayout(self.body.count() - 1, layout)

    def add_header_widget(self, widget):
        """在 header 右侧（展开箭头左侧）追加控件，如全屏按钮。"""
        self.card.addWidget(widget)
        return widget

    # ---------- 折叠 ----------
    def toggle(self):
        self.toggleExpand()

    def is_expanded(self):
        return self.isExpand

    # ---------- 尺寸 ----------
    def _adjustViewSize(self):
        """用自定义内容高度重算卡片高度（替代原生基于 group 行数的算法）。"""
        h = self.body.sizeHint().height()
        self.spaceWidget.setFixedHeight(h)
        if self.isExpand:
            self.setFixedHeight(self.card.height() + h)

    # ---------- 滚动透传 ----------
    def wheelEvent(self, e):
        p = self.parentWidget()
        if p is not None:
            QApplication.sendEvent(p, e)
        else:
            e.ignore()

    # ---------- 主题 ----------
    def apply_theme(self, theme=None):
        """原生卡自动适配主题，无需手动刷新样式（兼容 apply_module_theme 契约）。"""


# ============================================================
# 共享样式 — 现代化风格
# ============================================================
def _theme_colors():
    """返回当前主题对应的常用颜色字典。

    用 isDarkTheme() 判断 FluentWidgets 当前主题，返回一组配套颜色，
    避免在样式表里硬编码 #ffffff/#1a1a1a 等亮色值——这些在暗色主题下
    会变成"白底白字"或刺眼的高对比块。

    Returns:
        dict: 颜色键值对，键为语义名（page_bg/card_bg/text_primary/...）
    """
    if isDarkTheme():
        return {
            'page_bg':     '#202020',
            'card_bg':     '#2d2d2d',
            'card_border': '#404040',
            'content_bg':  '#3d3d3d',   # 卡片内容区灰色（亮于 card_bg，形成"白标题+灰内容"分层）
            'text_primary':'#ffffff',
            'text_secondary':'#c0c0c0',
            'text_hint':   '#888888',
            'accent':      '#60cdff',
            'accent_hover':'#7dd8ff',
            'input_bg':    '#2d2d2d',
            'hover_bg':    '#3d3d3d',
            'pressed_bg':  '#454545',
            'separator':   '#3a3a3a',
        }
    return {
        'page_bg':     '#f3f3f3',
        'card_bg':     '#ffffff',
        'card_border': '#e5e5e5',
        'content_bg':  '#f6f6f6',   # 卡片内容区灰色（深于 card_bg，形成内容区灰底分层）
        'text_primary':'#1a1a1a',
        'text_secondary':'#444444',
        'text_hint':   '#888888',
        'accent':      '#0078d4',
        'accent_hover':'#106ebe',
        'input_bg':    '#ffffff',
        'hover_bg':    '#f0f0f0',
        'pressed_bg':  '#e5e5e5',
        'separator':   '#ebebeb',
    }


def page_bg_style():
    """页面（QScrollArea 内层 content widget）的背景样式，适配当前主题。"""
    c = _theme_colors()
    return f"background: {c['page_bg']};"


def scroll_area_style():
    """QScrollArea 的边框/背景样式，适配当前主题。"""
    c = _theme_colors()
    return f"QScrollArea {{ border: none; background: {c['page_bg']}; }}"


def apply_module_theme(widget, theme=None):
    """刷新传感器模块 widget 内所有与主题相关的硬编码样式。

    传感器模块的 init_ui 在加载时按当前主题生成 QSS（如 `background: #f3f3f3;`），
    主题切换后这些 QSS 不会自动更新。本函数递归查找模块 widget 内的：
      - QScrollArea：重新应用 scroll_area_style()
      - 直接子 QWidget（页面 content）：重新应用 page_bg_style()
      - objectName=='card' 的 QWidget：重新应用 card_style()
      - CollapsibleCard：调用其 apply_theme(theme) 刷新 header 颜色
      - QLabel / QLineEdit / QFrame：把样式表里的硬编码文字色（#1a1a1a/#444/#888）
        按当前主题替换为语义色（亮→暗用浅色，暗→亮还原为深色）
    并触发一次全树 polish，让 FluentWidgets 子组件重新读取主题色。

    实现要点：第一次调用时把每个控件的原始 QSS 缓存到 dynamic property
    `_orig_qss`，后续主题切换始终从原始 QSS 重新派生，避免反复替换导致
    "切回亮色后仍是浅色字"的问题。

    Args:
        widget: 传感器模块的根 QWidget（self）
        theme: 'light' / 'dark' / None。None 时按当前 FluentWidgets 主题
               （isDarkTheme()）刷新——这是推荐用法，因为 setTheme 已经
               在调用方先执行，isDarkTheme() 能反映新主题。
    """
    from PySide6.QtWidgets import (
        QScrollArea, QWidget as _QW, QLabel as _QLabel,
        QLineEdit as _QLineEdit, QFrame as _QFrame,
    )

    c = _theme_colors()
    dark = isDarkTheme()
    # 亮色硬编码色 → 暗色语义色
    light_to_dark = {
        '#1a1a1a': c['text_primary'],
        '#1A1A1A': c['text_primary'],
        '#444444': c['text_secondary'],
        '#444':    c['text_secondary'],
        '#666666': c['text_secondary'],
        '#888888': c['text_hint'],
        '#888':    c['text_hint'],
        '#999999': c['text_hint'],
        '#999':    c['text_hint'],
        '#fafafa': c['card_bg'],
        '#f5f5f5': c['card_bg'],
        '#f0f0f0': c['hover_bg'],
        '#e5e5e5': c['card_border'],
        '#ebebeb': c['separator'],
        '#ececec': c['card_border'],
        '#d0d0d0': c['card_border'],
        '#b0b0b0': c['card_border'],
        '#333333': c['text_secondary'],
        '#333':    c['text_secondary'],
    }

    def _derive_qss(orig_qss: str) -> str:
        """从原始 QSS 派生当前主题的 QSS。"""
        if not orig_qss:
            return orig_qss
        if dark:
            out = orig_qss
            for old, new in light_to_dark.items():
                out = out.replace(old, new)
            return out
        # 亮色：直接用原始 QSS
        return orig_qss

    # 1. 递归刷新 QScrollArea 与 QWidget#card 的样式表，并 remap QLabel/QLineEdit/QFrame 颜色
    def _refresh(w):
        # FluentCard 是原生卡（QScrollArea 子类），自带主题自适应
        # 样式，不能套用 scroll_area_style()（会覆盖其原生背景）
        if isinstance(w, FluentCard):
            return
        if isinstance(w, QScrollArea):
            w.setStyleSheet(scroll_area_style())
        if isinstance(w, _QW) and w.objectName() == 'card':
            w.setStyleSheet(card_style())
        # CollapsibleCard 自己有 apply_theme，单独调用
        if isinstance(w, CollapsibleCard):
            try:
                w.apply_theme(theme or ('dark' if dark else 'light'))
            except Exception:
                pass
        for child in w.findChildren(_QW):
            if isinstance(child, FluentCard):
                continue
            if isinstance(child, (QScrollArea,)):
                _refresh(child)
            elif child.objectName() == 'card':
                _refresh(child)
            elif isinstance(child, CollapsibleCard):
                _refresh(child)
            elif isinstance(child, (_QLabel, _QLineEdit, _QFrame)):
                # 第一次：缓存原始 QSS；后续：从原始 QSS 派生
                orig = child.property('_orig_qss')
                if orig is None:
                    orig = child.styleSheet() or ''
                    child.setProperty('_orig_qss', orig)
                new_qss = _derive_qss(orig)
                if new_qss != child.styleSheet():
                    child.setStyleSheet(new_qss)

    _refresh(widget)

    # 2. 找到模块内最外层的 QScrollArea，刷新其 content widget（页面背景）
    #    排除 FluentCard（原生卡是 QScrollArea 子类，内容背景由原生管理）
    scrolls = widget.findChildren(QScrollArea)
    for s in scrolls:
        if isinstance(s, FluentCard):
            continue
        content = s.widget()
        if content is not None:
            content.setStyleSheet(page_bg_style())

    # 3. unpolish/polish 触发 FluentWidgets 子组件重读主题色
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            # 让 widget 及子 widget 的样式重算
            widget.style().unpolish(widget)
            widget.style().polish(widget)
    except Exception:
        pass


def card_style():
    """卡片内容区容器样式（适配当前主题）。

    背景用 content_bg（内容区灰色）而非 card_bg，使卡片内容区呈现
    "白标题(头部 card_bg) + 灰内容区"的两层分层，与 FluentCard 视觉统一。
    目前该样式仅被图表卡（CollapsibleCard）内容使用；普通卡片走 FluentCard
    （构造时会剥离 objectName='card' + card_style）。

    注意：页面容器常写 `content.setStyleSheet("background: #f3f3f3;")`，
    该无选择器的样式表会级联到所有子 widget，导致卡片内的中间容器
    （如 serial_panel、ble_panel 等未设 objectName 的 QWidget）继承
    灰色背景。这里用 `QWidget#card QWidget` 把卡片内所有子 widget
    背景置透明，使其透出卡片灰底；各控件（ComboBox/TextEdit/
    QPushButton 等）自身的样式表优先级更高，不受影响。
    """
    c = _theme_colors()
    return f"""
        QWidget#card {{
            background-color: {c['content_bg']};
            border: 1px solid {c['card_border']};
            border-radius: 8px;
        }}
        QWidget#card QWidget {{
            background-color: transparent;
        }}
        QWidget#card QComboBox,
        QWidget#card QTextEdit,
        QWidget#card QPlainTextEdit,
        QWidget#card QSpinBox,
        QWidget#card QDoubleSpinBox,
        QWidget#card QLineEdit,
        QWidget#card QListView,
        QWidget#card QTreeView,
        QWidget#card QTableView,
        QWidget#card QScrollArea,
        QWidget#card QAbstractScrollArea {{
            background-color: {c['input_bg']};
        }}
    """


def primary_btn_style():
    """主操作按钮样式（蓝色填充）"""
    c = _theme_colors()
    return f"""
        QPushButton {{
            background-color: {c['accent']};
            border: none;
            color: white;
            border-radius: 6px;
            font-size: 13px;
            padding: 0 16px;
        }}
        QPushButton:hover {{ background-color: {c['accent_hover']}; }}
        QPushButton:pressed {{ background-color: {c['accent']}; }}
        QPushButton:disabled {{ background-color: #cccccc; color: #888888; }}
    """


def accent_btn_style(normal, hover, pressed):
    """次操作按钮样式（自定义颜色，带边框）"""
    c = _theme_colors()
    border = c['card_border']
    text = c['text_primary']
    return f"""
        QPushButton {{
            background-color: {normal};
            border: 1px solid {border};
            color: {text};
            border-radius: 6px;
            font-size: 13px;
            padding: 0 16px;
        }}
        QPushButton:hover {{ background-color: {hover}; }}
        QPushButton:pressed {{ background-color: {pressed}; }}
        QPushButton:disabled {{ background-color: #f5f5f5; color: #aaaaaa; }}
    """


def modern_combo_style():
    """现代化风格 QComboBox 样式（浅色主题）。

    特征：
    - 圆角 6px，浅灰背景
    - 悬停时边框加深
    - 聚焦时蓝色边框
    - 下拉箭头使用 Segoe Fluent Icons 字符
    - 下拉列表圆角，选中项蓝色高亮
    """
    return """
        QComboBox {
            background-color: #ffffff;
            border: 1px solid #d0d0d0;
            border-radius: 6px;
            padding: 6px 32px 6px 12px;
            min-height: 20px;
            font-size: 13px;
            color: #1a1a1a;
        }
        QComboBox:hover {
            border: 1px solid #b0b0b0;
            background-color: #fafafa;
        }
        QComboBox:focus {
            border: 1px solid #0078d4;
        }
        QComboBox:on {
            border: 1px solid #0078d4;
            border-bottom-left-radius: 0px;
            border-bottom-right-radius: 0px;
        }
        QComboBox::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 28px;
            border: none;
            background: transparent;
        }
        QComboBox::drop-down:hover {
            background-color: #f0f0f0;
            border-top-right-radius: 6px;
            border-bottom-right-radius: 6px;
        }
        QComboBox::down-arrow {
            image: none;
            border: none;
            width: 14px;
            height: 14px;
        }
        QComboBox QAbstractItemView {
            background-color: #ffffff;
            border: 1px solid #d0d0d0;
            border-radius: 6px;
            padding: 4px;
            outline: none;
            selection-background-color: #f0f6ff;
            selection-color: #0078d4;
            color: #1a1a1a;
        }
        QComboBox QAbstractItemView::item {
            min-height: 32px;
            padding: 4px 12px;
            border-radius: 4px;
            color: #1a1a1a;
        }
        QComboBox QAbstractItemView::item:hover {
            background-color: #f5f5f5;
        }
        QComboBox QAbstractItemView::item:selected {
            background-color: #f0f6ff;
            color: #0078d4;
        }
    """


def modern_combo_style_dark():
    """现代化风格 QComboBox 样式（深色主题）"""
    return """
        QComboBox {
            background-color: #2d2d2d;
            border: 1px solid #3d3d3d;
            border-radius: 6px;
            padding: 6px 32px 6px 12px;
            min-height: 20px;
            font-size: 13px;
            color: #ffffff;
        }
        QComboBox:hover {
            border: 1px solid #5d5d5d;
            background-color: #323232;
        }
        QComboBox:focus, QComboBox:on {
            border: 1px solid #60cdff;
        }
        QComboBox::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 28px;
            border: none;
            background: transparent;
        }
        QComboBox::drop-down:hover {
            background-color: #3d3d3d;
            border-top-right-radius: 6px;
            border-bottom-right-radius: 6px;
        }
        QComboBox::down-arrow {
            image: none;
            border: none;
            width: 14px;
            height: 14px;
        }
        QComboBox QAbstractItemView {
            background-color: #2d2d2d;
            border: 1px solid #3d3d3d;
            border-radius: 6px;
            padding: 4px;
            outline: none;
            selection-background-color: #1f3a5f;
            selection-color: #60cdff;
            color: #ffffff;
        }
        QComboBox QAbstractItemView::item {
            min-height: 32px;
            padding: 4px 12px;
            border-radius: 4px;
            color: #ffffff;
        }
        QComboBox QAbstractItemView::item:hover {
            background-color: #3d3d3d;
        }
        QComboBox QAbstractItemView::item:selected {
            background-color: #1f3a5f;
            color: #60cdff;
        }
    """


# ============================================================
# ComboBox 箭头翻转补丁
# ============================================================
def patch_combobox_arrow_flip():
    """让 FluentWidgets 的 ComboBox / EditableComboBox 展开下拉时箭头朝上。

    FluentWidgets 的 ComboBox 继承自 QPushButton（非 QComboBox），
    paintEvent 中硬编码绘制 FIF.ARROW_DOWN，无论是否展开都朝下。
    本函数 monkey-patch 其 paintEvent，当下拉菜单（dropMenu）存在时
    将箭头绕中心旋转 180°，实现「展开朝上 / 收起朝下」的交互。
    同时处理 EditableComboBox 的 LineEditButton 箭头按钮。
    """
    from qfluentwidgets.components.widgets.combo_box import (
        ComboBox as _CBox, EditableComboBox as _EBox, ComboBoxBase as _CBase,
    )
    from qfluentwidgets.components.widgets.line_edit import LineEditButton as _LEBtn
    from qfluentwidgets.common.icon import (
        FluentIcon as _FIF, isDarkTheme, drawIcon as _drawIcon,
    )
    from PySide6.QtWidgets import QPushButton as _QPB, QToolButton as _QTB
    from PySide6.QtGui import QPainter as _QPainter
    from PySide6.QtCore import QRectF as _QRectF

    if getattr(_CBox, '_arrow_flip_patched', False):
        return

    # --- ComboBox.paintEvent：展开时箭头旋转 180° ---
    def _combo_paint(self, e):
        _QPB.paintEvent(self, e)
        painter = _QPainter(self)
        painter.setRenderHints(_QPainter.Antialiasing)
        if self.isHover:
            painter.setOpacity(0.8)
        elif self.isPressed:
            painter.setOpacity(0.7)
        rect = _QRectF(self.width()-22, self.height()/2-5+self.arrowAni.y, 10, 10)
        flipped = self.dropMenu is not None
        if flipped:
            painter.save()
            c = rect.center()
            painter.translate(c.x(), c.y())
            painter.rotate(180)
            painter.translate(-c.x(), -c.y())
        if isDarkTheme():
            _FIF.ARROW_DOWN.render(painter, rect)
        else:
            _FIF.ARROW_DOWN.render(painter, rect, fill="#646464")
        if flipped:
            painter.restore()
    _CBox.paintEvent = _combo_paint

    # --- LineEditButton.paintEvent：EditableComboBox 的箭头按钮，展开时翻转 ---
    _orig_leb_paint = _LEBtn.paintEvent

    def _leb_paint(self, e):
        parent = self.parent()
        flip = (parent is not None
                and getattr(parent, 'dropMenu', None) is not None
                and getattr(self, '_icon', None) is _FIF.ARROW_DOWN)
        if not flip:
            _orig_leb_paint(self, e)
            return
        _QTB.paintEvent(self, e)
        painter = _QPainter(self)
        painter.setRenderHints(_QPainter.Antialiasing | _QPainter.SmoothPixmapTransform)
        iw, ih = self.iconSize().width(), self.iconSize().height()
        w, h = self.width(), self.height()
        rect = _QRectF((w - iw)/2, (h - ih)/2, iw, ih)
        if self.isPressed:
            painter.setOpacity(0.7)
        painter.save()
        c = rect.center()
        painter.translate(c.x(), c.y())
        painter.rotate(180)
        painter.translate(-c.x(), -c.y())
        if isDarkTheme():
            _drawIcon(self._icon, painter, rect)
        else:
            _drawIcon(self._icon, painter, rect, fill='#656565')
        painter.restore()
    _LEBtn.paintEvent = _leb_paint

    # --- 菜单打开/关闭后触发重绘，确保箭头方向同步 ---
    from PySide6.QtCore import QTimer as _QTimer

    def _refresh(self):
        self.update()
        db = getattr(self, 'dropButton', None)
        if db is not None:
            db.update()

    _orig_show = _CBase._showComboMenu

    def _show(self):
        # _orig_show 内部会同步执行 menu.exec()（进入新的事件循环阻塞），
        # 若直接在 _orig_show 返回后调用 _refresh，那时菜单已关闭、
        # dropMenu 已被置 None，箭头翻转永远无法触发。
        # 用 QTimer.singleShot(0) 把 _refresh 投递到下一个事件循环迭代：
        # 当 _orig_show 内部 dropMenu 设置完毕并调用 menu.exec() 进入
        # 嵌套事件循环时，QTimer 回调会被处理，此时 dropMenu 已存在，
        # 箭头会被正确翻转重绘。
        _QTimer.singleShot(0, lambda: _refresh(self))
        _orig_show(self)
    _CBase._showComboMenu = _show

    _orig_close = _CBase._closeComboMenu

    def _close(self):
        _orig_close(self)
        _refresh(self)
    _CBase._closeComboMenu = _close

    _orig_onclose = _CBase._onDropMenuClosed

    def _onclose(self):
        _orig_onclose(self)
        _refresh(self)
    _CBase._onDropMenuClosed = _onclose

    _orig_onclose_e = _EBox._onDropMenuClosed

    def _onclose_e(self):
        _orig_onclose_e(self)
        _refresh(self)
    _EBox._onDropMenuClosed = _onclose_e

    _CBox._arrow_flip_patched = True


# ============================================================
# 通用对话框
# ============================================================
class CalibrationDialog(QDialog):
    """校准参数编辑对话框 - 支持单点/两点/三点校准

    FluentUI 风格：卡片式布局 + 原生控件（RadioButton / LineEdit / PushButton）。
    """

    def __init__(self, calibration_points, parent=None):
        super().__init__(parent)
        self.calibration_points = calibration_points
        self.calibration_mode = len(calibration_points) if calibration_points else 2
        self.init_ui()

    # ---------- 卡片容器（带圆角 + 边框，跟随主题） ----------
    class _Card(QWidget):
        """轻量卡片：圆角背景 + 边框，跟随 FluentWidgets 主题。"""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        def paintEvent(self, e):
            c = _theme_colors()
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(QBrush(QColor(c['card_bg'])))
            painter.setPen(QPen(QColor(c['card_border']), 1))
            path = QPainterPath()
            path.addRoundedRect(0.5, 0.5, self.width() - 1, self.height() - 1, 8, 8)
            painter.drawPath(path)

    def init_ui(self):
        self.setWindowTitle("编辑校准参数")
        self.setModal(True)
        self.setFixedSize(520, 520)

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 16, 20, 16)
        main_layout.setSpacing(12)

        # 说明文字
        info = CaptionLabel("请选择校准模式并输入标准缓冲液 pH 值及其对应的 ADC 原始值：")
        main_layout.addWidget(info)

        # ===== 卡片1：校准模式 =====
        mode_card = self._Card()
        mode_inner = QVBoxLayout(mode_card)
        mode_inner.setContentsMargins(16, 12, 16, 12)
        mode_inner.setSpacing(8)

        mode_title = StrongBodyLabel("校准模式")
        mode_inner.addWidget(mode_title)

        self.mode_buttons = []
        modes = [
            (1, "单点校准", "仅使用一个参考点，需要已知理论斜率（约 -0.5 pH/V）"),
            (2, "两点校准", "线性拟合，适合大多数常规测量"),
            (3, "三点校准", "二次拟合，精度最高，推荐用于精确实验"),
        ]

        for count, label, desc in modes:
            row = QHBoxLayout()
            row.setSpacing(8)
            rb = RadioButton(f"{label}")
            rb.setProperty("mode", count)
            rb.setToolTip(desc)
            if count == self.calibration_mode:
                rb.setChecked(True)
            rb.toggled.connect(self.on_mode_changed)
            row.addWidget(rb)
            desc_lbl = CaptionLabel(desc)
            row.addWidget(desc_lbl, 1)
            mode_inner.addLayout(row)
            self.mode_buttons.append(rb)

        main_layout.addWidget(mode_card)

        # ===== 卡片2：校准点设置 =====
        self.points_card = self._Card()
        self.points_inner = QVBoxLayout(self.points_card)
        self.points_inner.setContentsMargins(16, 12, 16, 12)
        self.points_inner.setSpacing(8)

        points_title = StrongBodyLabel("校准点设置")
        self.points_inner.addWidget(points_title)

        self.point_widgets = []
        self._create_point_inputs()

        main_layout.addWidget(self.points_card)

        main_layout.addStretch()

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = PushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        ok_btn = PrimaryPushButton("确定")
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        main_layout.addLayout(btn_layout)

        self.setLayout(main_layout)

    def _create_point_inputs(self):
        """重建校准点输入行（根据当前模式动态生成）。"""
        self.point_widgets.clear()
        # 删除 points_inner 中标题之后的所有子项（逆序安全删除）
        while self.points_inner.count() > 1:
            item = self.points_inner.takeAt(self.points_inner.count() - 1)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                lay = item.layout()
                while lay.count():
                    sub = lay.takeAt(lay.count() - 1)
                    if sub.widget():
                        sub.widget().deleteLater()

        point_names_1 = ["参考缓冲液 (点 1)"]
        point_names_2 = ["低 pH 缓冲液 (点 1)", "高 pH 缓冲液 (点 2)"]
        point_names_3 = ["酸性缓冲液 (点 1)", "中性缓冲液 (点 2)", "碱性缓冲液 (点 3)"]

        names_map = {1: point_names_1, 2: point_names_2, 3: point_names_3}
        point_names = names_map.get(self.calibration_mode, point_names_2)

        defaults = {
            1: [(7.00, 2281)],
            2: [(4.00, 2555), (9.18, 2030)],
            3: [(4.00, 2555), (6.86, 2281), (9.18, 2030)],
        }
        default_points = defaults.get(self.calibration_mode, defaults[2])

        for i, name in enumerate(point_names):
            row = QHBoxLayout()
            row.setSpacing(10)

            name_lbl = BodyLabel(name)
            row.addWidget(name_lbl)
            row.addSpacing(8)

            row.addWidget(BodyLabel("pH"))
            ph_input = LineEdit()
            ph_input.setText(
                str(default_points[i][0]) if i < len(default_points) else "7.00"
            )
            ph_input.setFixedWidth(72)
            ph_input.setAlignment(Qt.AlignmentFlag.AlignRight)
            row.addWidget(ph_input)

            row.addWidget(CaptionLabel("→"))

            row.addWidget(BodyLabel("ADC"))
            adc_input = LineEdit()
            adc_input.setText(
                str(default_points[i][1]) if i < len(default_points) else "2281"
            )
            adc_input.setFixedWidth(72)
            adc_input.setAlignment(Qt.AlignmentFlag.AlignRight)
            row.addWidget(adc_input)

            row.addStretch()
            self.points_inner.addLayout(row)

            self.point_widgets.append({
                'row': row, 'ph': ph_input, 'adc': adc_input,
            })

    def on_mode_changed(self):
        sender = self.sender()
        if sender.isChecked():
            self.calibration_mode = sender.property("mode")
            self._create_point_inputs()

    def get_calibration_mode(self):
        return self.calibration_mode

    def get_calibration_points(self):
        """获取校准参数"""
        points = []
        for widget in self.point_widgets:
            ph_val = float(widget['ph'].text())
            adc_val = float(widget['adc'].text())
            points.append((ph_val, adc_val))
        return points


class CalibrationMessageBox(MessageBoxBase):
    """校准参数编辑弹窗 — 基于 Fluent-Widgets 原生 MessageBoxBase。

    WinUI3 掩码弹窗：居中浮窗 + 阴影 + 确定/取消按钮，样式随 Fluent 主题，
    与主程序其他 MessageBox 视觉一致。支持单点 / 两点 / 三点校准：
    模式单选实时切换输入行，确定前做 pH→ADC 输入校验。
    API 与旧 CalibrationDialog 兼容（exec 返回 QDialog.Accepted = 1）。
    """

    def __init__(self, calibration_points, parent=None):
        super().__init__(parent)
        points = list(calibration_points) if calibration_points else []
        self.calibration_points = points
        self.calibration_mode = len(points) if points else 2
        self.point_widgets = []

        self.yesButton.setText("确定")
        self.cancelButton.setText("取消")
        # 只固定宽度：竖向高度交由表单内容自适应（MessageBoxBase 未固定尺寸，
        # 若不限宽会随掩码撑满整个父窗口）
        self.widget.setFixedWidth(520)

        self._build_form()

    def _build_form(self):
        view = self.viewLayout
        view.addWidget(SubtitleLabel("编辑校准参数"))

        info = CaptionLabel("请选择校准模式并输入标准缓冲液 pH 值及其对应的 ADC 原始值：")
        info.setWordWrap(True)
        view.addWidget(info)

        # 校准模式单选
        modes = [
            (1, "单点校准", "仅一个参考点，使用已知理论斜率"),
            (2, "两点校准", "线性拟合，适合大多数常规测量"),
            (3, "三点校准", "二次拟合，精度最高，适合精确实验"),
        ]
        self.mode_buttons = []
        for count, label, desc in modes:
            row = QHBoxLayout()
            row.setSpacing(8)
            rb = RadioButton(label)
            rb.setProperty("mode", count)
            rb.setToolTip(desc)
            rb.setChecked(count == self.calibration_mode)
            rb.toggled.connect(self._on_mode_toggled)
            row.addWidget(rb)
            row.addWidget(CaptionLabel(desc), 1)
            view.addLayout(row)
            self.mode_buttons.append(rb)

        # 校准点输入行容器（模式切换时重建）
        self.points_inner = QVBoxLayout()
        self.points_inner.setSpacing(8)
        view.addLayout(self.points_inner)
        self._create_point_inputs()

        # 校验失败提示（红色，亮/暗主题均可见）
        self._error_label = CaptionLabel("")
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet("color: #e5484d;")
        self._error_label.hide()
        view.addWidget(self._error_label)

    def _create_point_inputs(self):
        """重建校准点输入行：按当前模式动态生成，优先回填已保存的校准点。"""
        # 清空旧行
        while self.points_inner.count():
            item = self.points_inner.takeAt(self.points_inner.count() - 1)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            elif item.layout() is not None:
                lay = item.layout()
                while lay.count():
                    sub = lay.takeAt(lay.count() - 1)
                    if sub.widget() is not None:
                        sub.widget().deleteLater()

        self.point_widgets.clear()
        point_names = {
            1: ["参考缓冲液 (点 1)"],
            2: ["低 pH 缓冲液 (点 1)", "高 pH 缓冲液 (点 2)"],
            3: ["酸性缓冲液 (点 1)", "中性缓冲液 (点 2)", "碱性缓冲液 (点 3)"],
        }[self.calibration_mode]
        defaults = {
            1: [(7.00, 2281)],
            2: [(4.00, 2555), (9.18, 2030)],
            3: [(4.00, 2555), (6.86, 2281), (9.18, 2030)],
        }[self.calibration_mode]

        for i, name in enumerate(point_names):
            row = QHBoxLayout()
            row.setSpacing(10)
            row.addWidget(BodyLabel(name), 1)
            row.addSpacing(4)

            row.addWidget(BodyLabel("pH"))
            ph_input = LineEdit()
            saved = self.calibration_points[i] if i < len(self.calibration_points) else None
            ph_input.setText(f"{saved[0]:g}" if saved else f"{defaults[i][0]:g}")
            ph_input.setFixedWidth(72)
            ph_input.setAlignment(Qt.AlignmentFlag.AlignRight)
            row.addWidget(ph_input)

            row.addWidget(CaptionLabel("→"))

            row.addWidget(BodyLabel("ADC"))
            adc_input = LineEdit()
            adc_input.setText(f"{saved[1]:g}" if saved else f"{defaults[i][1]:g}")
            adc_input.setFixedWidth(72)
            adc_input.setAlignment(Qt.AlignmentFlag.AlignRight)
            row.addWidget(adc_input)

            self.points_inner.addLayout(row)
            self.point_widgets.append({'row': row, 'ph': ph_input, 'adc': adc_input})

    def _on_mode_toggled(self):
        rb = self.sender()
        if rb is not None and rb.isChecked():
            self.calibration_mode = rb.property("mode")
            self._create_point_inputs()
            self._error_label.hide()

    def validate(self):
        """确定前校验输入：pH 须为 0~14 数值、ADC 须为数值；非法时提示并阻止关闭。"""
        points = []
        for i, w in enumerate(self.point_widgets, 1):
            ph_text = w['ph'].text().strip()
            adc_text = w['adc'].text().strip()
            if not ph_text or not adc_text:
                self._fail(f"第 {i} 点的 pH 或 ADC 值为空")
                return False
            try:
                ph_val = float(ph_text)
            except ValueError:
                self._fail(f"第 {i} 点的 pH 值「{ph_text}」不是有效数字")
                return False
            try:
                adc_val = float(adc_text)
            except ValueError:
                self._fail(f"第 {i} 点的 ADC 值「{adc_text}」不是有效数字")
                return False
            if not (0.0 <= ph_val <= 14.0):
                self._fail(f"第 {i} 点的 pH 值须在 0~14 之间")
                return False
            points.append((ph_val, adc_val))
        self._parsed_points = points
        self._error_label.hide()
        return True

    def _fail(self, msg):
        self._error_label.setText(f"输入有误：{msg}")
        self._error_label.show()

    def get_calibration_mode(self):
        return self.calibration_mode

    def get_calibration_points(self):
        """返回校验无误的校准点（未点确定时返回初始值）。"""
        return list(getattr(self, '_parsed_points', self.calibration_points))


class SampleRateDialog(QDialog):
    """采样频率设置对话框

    使用 EditableComboBox：既可从预设频率下拉选择，也可直接输入自定义频率值。
    输入格式：纯数字（视为 Hz）或带 "Hz"/"hz" 后缀，范围 0.1~10 Hz，
    对应采样间隔 100~10000 ms（下位机最大输出频率为 10 Hz）。
    """

    # 预设频率：(interval_ms, 显示文本, 说明)
    PRESETS = [
        (100,  "10 Hz",   "全速接收（下位机最大频率），适合大多数实验"),
        (200,  "5 Hz",    "中速采样，适合一般变化信号"),
        (500,  "2 Hz",    "低速采样，适合缓慢变化的信号"),
        (1000, "1 Hz",    "超低速采样，长时间监测"),
        (2000, "0.5 Hz",  "极低速采样，每2秒一个点"),
        (5000, "0.2 Hz",  "最低速采样，每5秒一个点"),
    ]

    # 允许的频率范围（Hz）：下位机最大 10 Hz，最低 0.1 Hz（10000ms）
    FREQ_MIN = 0.1
    FREQ_MAX = 10.0

    def __init__(self, current_interval_ms, parent=None):
        super().__init__(parent)
        self.current_interval_ms = current_interval_ms
        self._interval_ms = current_interval_ms  # 当前选中/输入对应的间隔
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("设置采样频率")
        self.setModal(True)
        self.setFixedSize(420, 280)

        layout = QVBoxLayout()
        layout.setSpacing(12)

        info_label = QLabel(
            "请选择或输入数据采集的采样频率：\n"
            "下位机最大输出频率为 10 Hz，设定高于此值将接收全部数据。\n"
            "频率越低，数据点越稀疏，适合长时间监测。"
        )
        info_label.setStyleSheet("color: #666; padding: 4px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # 可编辑下拉框：预设项 + 自由输入
        self.combo = EditableComboBox()
        self.combo.setPlaceholderText("选择预设频率，或直接输入 Hz 值（如 3 或 0.5Hz）")
        for interval_ms, label, _ in self.PRESETS:
            self.combo.addItem(label, userData=interval_ms)

        # 当前值回填：优先匹配预设，否则显示换算后的 Hz 文本
        current_text = self._interval_to_text(self.current_interval_ms)
        self.combo.setCurrentText(current_text)
        self.combo.currentTextChanged.connect(self._on_text_changed)
        self.combo.setFixedHeight(34)
        layout.addWidget(self.combo)

        # 实时反馈：显示当前频率 ↔ 采样间隔，以及合法性提示
        self.feedback_label = QLabel()
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setStyleSheet("padding: 4px;")
        layout.addWidget(self.feedback_label)

        layout.addStretch()

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = PushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        ok_btn = PrimaryPushButton("确定")
        ok_btn.clicked.connect(self._on_accept)
        button_layout.addWidget(ok_btn)

        layout.addLayout(button_layout)
        self.setLayout(layout)

        self._on_text_changed(self.combo.currentText())

    # ---------- 解析与反馈 ----------
    def _interval_to_text(self, interval_ms):
        """采样间隔 → 显示文本（优先匹配预设项，否则换算 Hz）"""
        for iv, label, _ in self.PRESETS:
            if iv == interval_ms:
                return label
        freq = 1000.0 / interval_ms
        return f"{freq:g} Hz"

    def _parse_freq(self, text):
        """解析输入文本为频率（Hz）。失败返回 None。

        接受格式：'10'、'10Hz'、'10 Hz'、'0.5hz' 等
        """
        s = text.strip().lower().replace("hz", "").strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None

    def _on_text_changed(self, text):
        freq = self._parse_freq(text)
        if freq is None or freq <= 0:
            self._interval_ms = None
            self.feedback_label.setText(
                '<span style="color:#c0392b;">⚠ 无法识别，请输入数字频率（Hz），如 10、2、0.5</span>'
            )
            return

        # 超出范围时仍换算显示，但标红提示
        interval_ms = round(1000.0 / freq)
        self._interval_ms = interval_ms

        in_range = self.FREQ_MIN <= freq <= self.FREQ_MAX
        color = "#0078d4" if in_range else "#c0392b"
        warn = "" if in_range else "  （超出 0.1~10 Hz 范围，将被限制）"
        self.feedback_label.setText(
            f'<span style="color:#444;">当前：'
            f'<b style="color:{color};">{freq:g} Hz</b> '
            f'（采样间隔 {interval_ms} ms）{warn}</span>'
        )

    def _on_accept(self):
        # 输入非法时不允许确定
        if self._interval_ms is None:
            return
        # 限制到允许范围
        interval = max(100, min(10000, self._interval_ms))
        self._interval_ms = interval
        self.accept()

    def get_sample_interval(self):
        """返回当前采样间隔（ms）。"""
        return self._interval_ms if self._interval_ms is not None else self.current_interval_ms


class SampleRateComboBox(EditableComboBox):
    """采样频率内联可编辑下拉框（直接嵌入主界面，无需弹对话框）。

    传感器模块用本组件替换原先的「频率 QLabel + ⚙设置按钮」：
    - 下拉选预设频率（10/5/2/1/0.5/0.2 Hz）
    - 或手动输入 Hz 值（如 3、0.5Hz），文本改变时即时生效
    - 范围 0.1~10 Hz，对应采样间隔 100~10000 ms（下位机最大 10 Hz）

    信号：
        sampleIntervalChanged(int): 采样间隔改变时发射，参数为新间隔（ms）
    """

    # 预设频率：(interval_ms, 显示文本, 说明)
    PRESETS = [
        (100,  "10 Hz",   "全速接收（下位机最大频率）"),
        (200,  "5 Hz",    "中速采样"),
        (500,  "2 Hz",    "低速采样"),
        (1000, "1 Hz",    "超低速采样"),
        (2000, "0.5 Hz",  "极低速采样"),
        (5000, "0.2 Hz",  "最低速采样"),
    ]

    FREQ_MIN = 0.1   # Hz
    FREQ_MAX = 10.0  # Hz

    sampleIntervalChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._interval_ms = 100
        self._block_signal = True  # 初始化期间抑制信号

        for interval_ms, label, _ in self.PRESETS:
            self.addItem(label, userData=interval_ms)

        self.setPlaceholderText("采样频率")
        self.setMaxVisibleItems(10)
        self.setFixedHeight(32)
        self.setMinimumWidth(110)
        self.currentTextChanged.connect(self._on_text_changed)

        self._block_signal = False

    # ---------- 公共接口 ----------
    def setSampleInterval(self, interval_ms):
        """设置当前采样间隔（ms），不会重复发射信号。"""
        prev = self._interval_ms
        self._block_signal = True
        self._interval_ms = interval_ms
        self.setCurrentText(self._interval_to_text(interval_ms))
        self._block_signal = False
        if prev != interval_ms:
            self.sampleIntervalChanged.emit(interval_ms)

    def getSampleInterval(self):
        """返回当前采样间隔（ms）。"""
        return self._interval_ms

    # ---------- 内部 ----------
    def _interval_to_text(self, interval_ms):
        for iv, label, _ in self.PRESETS:
            if iv == interval_ms:
                return label
        freq = 1000.0 / interval_ms
        return f"{freq:g} Hz"

    def _parse_freq(self, text):
        s = text.strip().lower().replace("hz", "").strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None

    def _on_text_changed(self, text):
        if self._block_signal:
            return
        freq = self._parse_freq(text)
        if freq is None or freq <= 0:
            return  # 解析失败（输入中间态），保持上一次有效值
        interval_ms = round(1000.0 / freq)
        interval_ms = max(100, min(10000, interval_ms))
        if interval_ms != self._interval_ms:
            self._interval_ms = interval_ms
            self.sampleIntervalChanged.emit(interval_ms)
