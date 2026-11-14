# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

# -*- coding: utf-8 -*-
"""
core_ui.py — PhysChem-DigitizerP 公共 UI

依赖 PySide6 / qfluentwidgets，包含：
- AppConfig / 主题 / 字体 / 样式
- ChartPanel
- 通用卡片、对话框、AI 分析 UI

纯内核（日志、配置、事件、传输、SensorKernel、KernelRegistry）在 core.py。
"""

import os
import sys
import json
import bisect
import importlib
import importlib.util

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QWidget, QPushButton, QFrame, QSizePolicy, QTextEdit,
    QApplication, QScrollArea, QListWidget, QListWidgetItem,
    QStyledItemDelegate, QStyle,
)
from PySide6.QtCore import (Qt, Signal, QThread, QPoint, QSize, QTimer,
                            QEvent, QAbstractNativeEventFilter)
from PySide6.QtGui import (
    QFont, QColor, QPainter, QPen, QBrush, QPainterPath,
    QFontMetrics, QTextOption, QIcon, QPixmap,
)

# FluentWidgets — WinUI3 风格组件库（导入时它会向 stdout 打印一行 Pro 推广
# 横幅；应用要求控制台默认完全静默，这里在导入期间临时重定向 stdout 吞掉）
import io as _io
import contextlib as _contextlib
with _contextlib.redirect_stdout(_io.StringIO()):
    from qfluentwidgets import (
        PushButton, PrimaryPushButton, HyperlinkButton, ComboBox, EditableComboBox,
        SwitchButton, DoubleSpinBox, ToolButton, SpinBox,
        LineEdit, TextEdit, Dialog, MessageBox, MessageBoxBase, StrongBodyLabel,
        SubtitleLabel, BodyLabel, CaptionLabel,
        isDarkTheme, qconfig, QConfig, ConfigItem, OptionsConfigItem, OptionsValidator,
        ConfigSerializer,
        ExpandGroupSettingCard, FluentIcon, RadioButton, CheckBox, FlowLayout,
    )
from qfluentwidgets.components.dialog_box import ColorDialog

from core import (
    SERIAL_AVAILABLE, get_logger, list_serial_ports, serial_unavailable_hint, clear_sensor_config,
    set_config_persistence, CHANNEL_COLORS,
    setup_logging as _kernel_setup_logging,
    set_log_enabled as _kernel_set_log_enabled,
    set_log_level as _kernel_set_log_level,
    set_log_max_entries as _kernel_set_log_max_entries,
)

log = get_logger('core_ui')

# ============================================================
# matplotlib 全局字体设置（图表引擎为 matplotlib 时才需要；
# 未安装 matplotlib 的环境跳过，pyqtgraph 引擎不受影响）
# ============================================================
try:
    import matplotlib.pyplot as plt

    def _set_mpl_base_font():
        """matplotlib 中文字体兜底（内嵌字体注册后会被 _apply_mpl_font 覆盖）。"""
        plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
        plt.rcParams['axes.unicode_minus'] = False

    _set_mpl_base_font()
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

# 安装状态提示延迟到日志系统就绪后输出（见下方 setup_logging 之后）


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

# 应用默认主题色（蓝色）。qfluentwidgets 库默认是青色 #009faa，
# 本应用统一使用 Fluent Design 标准蓝 #0078d4（与项目强调色一致）。
DEFAULT_THEME_COLOR = '#0078d4'

# ---- 应用字体 ----
# 内嵌字体：独立 .ttf 随程序分发，启动时经 QFontDatabase.addApplicationFont()
# 注册进 Qt，无需编译进 Python 源码（见 load_embedded_font）。
# 两者均为免费商用字体，许可证随文件放在 assets/fonts/ 下：
#   - MiSans（小米）：默认字体
#   - HarmonyOS Sans SC（华为）：注意必须用 **SC** 版本，
#     HarmonyOS_Sans/ 目录下的 HarmonyOS_Sans_Regular.ttf 是纯拉丁面
#     （cmap 仅 874 个码位，0 个汉字），装了中文会整片回退到系统字体
EMBEDDED_FONT_DIR = ('assets', 'fonts')
#: 内嵌字体清单 (字体族名, 文件名)；第一个为 config 默认值
EMBEDDED_FONTS = (
    ('MiSans', 'MiSans-Regular.ttf'),
    ('HarmonyOS Sans SC', 'HarmonyOS_Sans_SC_Regular.ttf'),
)
#: 默认内嵌字体族名（首次启动写入 app_config.json 的值）
EMBEDDED_FONT_FAMILY = EMBEDDED_FONTS[0][0]
#: 兼容旧代码：默认内嵌字体文件名
EMBEDDED_FONT_FILE = EMBEDDED_FONTS[0][1]
#: 等宽字体：数据记录 / 原始数据 / 数值读数专用，不随应用字体切换
MONO_FONT_FAMILY = 'Cascadia Code'
_MONO_FALLBACKS = ('Cascadia Mono', 'Consolas', 'Courier New')

# app_config.json 默认值（首次启动与「恢复默认设置」共用）
_APP_CONFIG_DEFAULT = {
    "Chart": {"Engine": "pyqtgraph"},
    "General": {
        "ConfigPersistenceEnabled": True,
        "ThemeColorMode": "custom",
        "PinnedModules": [],
        "LogEnabled": True,
        "LogLevel": "info",
        "LogMaxEntries": 5000,
        "FontFamily": EMBEDDED_FONT_FAMILY,
    },
    "Window": {
        "Geometry": {},
        "Maximized": True,
    },
    "QFluentWidgets": {
        "FontFamilies": ["Segoe UI", "Microsoft YaHei", "PingFang SC"],
        "ThemeColor": "#ff0078d4",
        "ThemeMode": "Light",
    },
}


class StringListSerializer(ConfigSerializer):
    """字符串列表序列化器：列表直接以 JSON 数组写入 app_config.json。

    qconfig 原生 ConfigItem 默认只支持标量值（字符串/数字/布尔），
    主页「模块置顶」需要持久化一个模块名列表，故自定义序列化器
    保证读写两端都是 list（qconfig.save 的 json.dump 原生支持数组）。
    deserialize 兼容旧版本写入的 JSON 字符串（如 "[]"），平滑升级。
    """

    def serialize(self, value):
        try:
            return list(value or [])
        except Exception:
            return []

    def deserialize(self, value):
        try:
            if isinstance(value, list):
                return list(value)
            if isinstance(value, str):
                return json.loads(value or "[]")
            return []
        except Exception:
            return []


class JsonDictSerializer(ConfigSerializer):
    """JSON 字典序列化器：嵌套 dict 直接以 JSON 对象写入 app_config.json。

    用于按模块名记住 AI 实验信息（实验名称/目的/条件备注），
    deserialize 兼容旧版本可能写入的 JSON 字符串。
    """

    def serialize(self, value):
        try:
            return dict(value or {})
        except Exception:
            return {}

    def deserialize(self, value):
        try:
            if isinstance(value, dict):
                return dict(value)
            if isinstance(value, str):
                parsed = json.loads(value or "{}")
                return dict(parsed) if isinstance(parsed, dict) else {}
            return {}
        except Exception:
            return {}


# 应用自身配置 — 独立文件存放，不受传感器配置开关影响。
# 开关状态若存进 sensor_config.json 会出现悖论：
# 「关闭保存」后无人写入 → 下次启动没人记得开关是关的。
class AppConfig(QConfig):
    """应用级配置（app_config.json，始终持久化）"""
    # 传感器配置持久化开关：False 时不读取也不写入 sensor_config.json，
    # 所有更改仅本次会话有效（默认开启，保持原有行为）
    configPersistenceEnabled = ConfigItem("General", "ConfigPersistenceEnabled", True)
    # 运行日志：默认开启；控制台始终输出，开启时同时写入 src/ 目录 logs.json
    logEnabled = ConfigItem("General", "LogEnabled", True)
    # 日志详细度：warning=简略（仅警告/错误）/ info=标准（应用事件）/ debug=详细
    logLevel = OptionsConfigItem(
        "General", "LogLevel", "info",
        OptionsValidator(["warning", "info", "debug"]),
    )
    # logs.json 最大保留条数（超出后自动裁剪最旧记录）
    logMaxEntries = ConfigItem("General", "LogMaxEntries", 5000)
    # 主题色模式：system=跟随系统强调色（Windows）/ custom=自定义（默认蓝色）
    themeColorMode = OptionsConfigItem(
        "General", "ThemeColorMode", "custom",
        OptionsValidator(["system", "custom"]),
    )
    # 应用字体族名（设置页「应用字体」）：默认内嵌 MiSans；
    # 空字符串 = 系统默认字体。任意已安装字体名均可写入（如「楷体」）
    fontFamily = ConfigItem("General", "FontFamily", EMBEDDED_FONT_FAMILY)
    # 浏览器仪表盘（flaskserver 插件）字体：默认内嵌 HarmonyOS Sans SC。
    # 与桌面端 fontFamily 分开存——网页端面向局域网访客（可能用手机），
    # 其字体偏好与操作者本机的桌面设置是两回事。空字符串 = 系统默认。
    webFontFamily = ConfigItem("WebDashboard", "FontFamily",
                               'HarmonyOS Sans SC')
    # 图表引擎：pyqtgraph（默认，高性能交互）/ matplotlib（静态美观）
    chartEngine = OptionsConfigItem(
        "Chart", "Engine", "pyqtgraph",
        OptionsValidator(["matplotlib", "pyqtgraph"]),
    )
    # 主页模块置顶列表（模块名列表，置顶的磁贴排在每组最前面）
    pinnedModules = ConfigItem(
        "General", "PinnedModules", [],
        serializer=StringListSerializer(),
    )
    # 窗口记忆：上次退出时的窗口位置与大小 {"x","y","w","h"}（退出时落盘，
    # 下次启动自动还原；多屏拔插/分辨率变化导致越界时回退默认尺寸）
    windowGeometry = ConfigItem(
        "Window", "Geometry", {},
        serializer=JsonDictSerializer(),
    )
    # 窗口记忆：上次退出时是否最大化（默认 True，保持原有“启动即最大化”行为）
    windowMaximized = ConfigItem("Window", "Maximized", True)
    # 启动时自动弹出「项目信息」卡片（首次运行默认开启；卡片内
    # 「启动时自动显示」复选框可关闭，关掉后不再主动弹出）
    showIntroOnStartup = ConfigItem("General", "ShowIntroOnStartup", True)
    # AI 分析实验：OpenAI 兼容端点 + API Key + 模型（图表卡「AI分析实验」按钮用）
    aiEndpoint = ConfigItem("General", "AIEndpoint", "")
    aiApiKey = ConfigItem("General", "AIApiKey", "")
    aiModel = ConfigItem("General", "AIModel", "deepseek-v4-flash")
    # 生成参数：温度（0~2）与最大输出 token（0=不限制）
    aiTemperature = ConfigItem("General", "AITemperature", 0.3)
    aiMaxTokens = ConfigItem("General", "AIMaxTokens", 0)
    # 用户自定义系统提示词（叠加在模块预置提示词之后）
    aiUserPrompt = ConfigItem("General", "AIUserPrompt", "")
    # 附带实验数据的上限行数（超出按均匀抽样；百万上下文模型可调大）
    aiDataLimit = ConfigItem("General", "AIDataLimit", 5000)
    # 按模块记住的实验信息 {模块名: {name, purpose, notes}}，
    # 进入 AI 分析时的信息框据此预填（下次实验免重复输入）
    aiExperimentInfo = ConfigItem(
        "General", "AIExperimentInfo", {},
        serializer=JsonDictSerializer(),
    )
    # 按模块记住的预置系统提示词覆盖 {模块名: 提示词文本}，
    # 由 AI 设置窗口编辑（内容与内置相同即视为未覆盖，读取时回退内置）
    aiModulePrompts = ConfigItem(
        "General", "AIModulePrompts", {},
        serializer=JsonDictSerializer(),
    )
    # 数据接口（HTTP 服务，flaskserver 插件消费这些配置项）
    serverPort = ConfigItem("DataAPI", "Port", 8765)
    serverLanAccess = ConfigItem("DataAPI", "LanAccess", False)
    serverCors = ConfigItem("DataAPI", "CorsEnabled", False)
    # 访问密钥鉴权开关：关闭后所有读写请求均免密钥（回环本机自用时可选）
    serverAuth = ConfigItem("DataAPI", "TokenRequired", True)
    # 访问密钥：首次开启服务时自动生成并持久化，重启后书签仍可用
    serverToken = ConfigItem("DataAPI", "Token", "")


app_cfg = AppConfig()


# ============================================================
# 应用字体：内嵌 MiSans（独立字体文件）+ 设置页可切换系统字体
#
# MiSans 以 assets/fonts/MiSans-Regular.ttf 独立文件随程序分发，
# 启动时用 QFontDatabase.addApplicationFont() 注册进 Qt——不需要
# 把字体编进 Python 源码（pyrcc 已被 PySide6 移除），也不占用额外
# 常驻内存：Qt 直接持有文件句柄，按需读取字形。
#
# 想换字体不必重新打包：设置页「应用字体」下拉框可填任意系统已装
# 字体名（如「楷体」「Microsoft YaHei」），写入 app_config.json 的
# General.FontFamily，重启或即时生效。
# ============================================================
#: addApplicationFont 的返回值（-1 表示失败）；进程内只需注册一次
_embedded_font_ids = None


def get_embedded_font_path(filename=None):
    """某个内嵌字体文件的绝对路径；文件缺失时返回 None。

    filename 缺省取清单里的第一个（默认字体）。同时兼容源码运行与
    PyInstaller 打包（onedir 下 sys._MEIPASS 指向 _internal/，与 datas
    收集目录一致）。传感器模块可能把源码目录（src/）插到 sys.path 前面，
    故除 __file__ 同级外再按 sys.path 兜底搜索。
    """
    filename = filename or EMBEDDED_FONT_FILE
    root = os.path.dirname(os.path.abspath(__file__))
    candidates = []
    if getattr(sys, '_MEIPASS', None):
        candidates.append(os.path.join(sys._MEIPASS, *EMBEDDED_FONT_DIR, filename))
    candidates.append(os.path.join(root, *EMBEDDED_FONT_DIR, filename))
    for base in sys.path:
        if not base:
            continue
        candidates.append(os.path.join(base, *EMBEDDED_FONT_DIR, filename))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def load_embedded_font():
    """把清单里的内嵌字体全部注册进 Qt，返回成功注册的数量。

    需在 QApplication 创建之后调用。重复调用只注册一次；单个字体失败
    仅记日志并跳过（缺字体不致命，Qt 会回退到系统字体）。
    """
    global _embedded_font_ids
    if _embedded_font_ids is not None:
        return len(_embedded_font_ids)
    from PySide6.QtGui import QFontDatabase
    ok = []
    for family, filename in EMBEDDED_FONTS:
        path = get_embedded_font_path(filename)
        if path is None:
            log.warning("未找到内嵌字体 %s（%s），该字体不可用",
                        family, os.path.join(*EMBEDDED_FONT_DIR, filename))
            continue
        try:
            fid = QFontDatabase.addApplicationFont(path)
            if fid == -1:
                log.warning("内嵌字体注册失败：%s", path)
                continue
            registered = QFontDatabase.applicationFontFamilies(fid)
            ok.append(family)
            log.info("✓ 已加载内嵌字体 %s（%s）→ Qt 族名 %s",
                     family, filename, registered or ['?'])
        except Exception as e:
            log.warning("内嵌字体 %s 加载异常: %s", family, e)
    _embedded_font_ids = ok
    return len(ok)


def embedded_font_families():
    """内嵌字体中已成功注册的族名列表（用于选择器置顶展示）。"""
    load_embedded_font()
    installed = available_font_families()
    return [f for f, _ in EMBEDDED_FONTS if f in installed]


def available_font_families():
    """当前系统已安装的字体族名集合。

    注意：Qt6 在中文系统上返回的就是**本地化名称**（微软雅黑 / 宋体 /
    楷体 / 隶书），无需再去读注册表或字体 name 表做映射。
    必须用类方法 QFontDatabase.families()——实例化后调用会得到空集合。
    """
    try:
        from PySide6.QtGui import QFontDatabase
        return set(QFontDatabase.families())
    except Exception:
        return set()


def list_font_families():
    """已安装字体族列表（含内嵌 MiSans），排序：常用中文名在前，再按名称。

    排序键说明：以 ASCII 字母开头的西文字体排在后面，中文名字体 +
    内嵌 MiSans 排前面——与 Word 字体下拉的观感一致，常用的不用翻。
    """
    families = available_font_families()

    def _key(name):
        first = name[0] if name else ''
        is_ascii = first.isascii() and first.isalpha()
        return (1 if is_ascii else 0, name.lower())
    return sorted(families, key=_key)


def resolve_app_font_family(config_value=None):
    """把配置值解析为实际可用的字体族名。

    - 值为空 → ''（交给 Qt 用系统默认字体）
    - 字体已注册/已安装 → 原样返回
    - 字体不存在（换机器后未装）→ 回退内嵌 MiSans
    """
    value = (app_cfg.fontFamily.value if config_value is None
             else config_value) or ''
    value = str(value).strip()
    if not value:
        return ''
    families = available_font_families()
    if value in families:
        return value
    if EMBEDDED_FONT_FAMILY in families:
        log.warning("字体「%s」不可用，回退 %s", value, EMBEDDED_FONT_FAMILY)
        return EMBEDDED_FONT_FAMILY
    return ''


def mono_font_family():
    """等宽字体族名：优先 Cascadia Code，其次常见等宽字体，最后回退默认。"""
    families = available_font_families()
    if MONO_FONT_FAMILY in families:
        return MONO_FONT_FAMILY
    for name in _MONO_FALLBACKS:
        if name in families:
            return name
    return ''


def _apply_mpl_font():
    """让 matplotlib 中文标签跟随应用字体（引擎 = matplotlib 时生效）。"""
    if plt is None:
        return
    try:
        name = resolve_app_font_family() or EMBEDDED_FONT_FAMILY
        plt.rcParams['font.sans-serif'] = [name, 'Microsoft YaHei', 'SimHei']
        plt.rcParams['axes.unicode_minus'] = False
    except Exception:
        pass


def apply_app_font(family=None, refresh_widgets=False):
    """应用字体到 FluentWidgets 与自定义控件。

    Args:
        family: 目标字体族名；None 时读 app_cfg.fontFamily。
                '' 表示系统默认字体。
        refresh_widgets: True 时把已显式设置过字体的控件一并改写
                （保留各自字号、字重与等宽字体）。仅在设置页切换字体时
                需要——启动阶段控件尚未创建，走默认继承即可。

    Returns:
        str: 实际生效的字体族名（'' 表示系统默认）
    """
    resolved = resolve_app_font_family(family)
    from qfluentwidgets import setFontFamilies
    # 字体族列表：目标字体在前，其余作回退，避免个别字符缺字显示为方块。
    # 用户显式选「系统默认」时不掺入 MiSans——否则等于没切回系统字体。
    if resolved:
        candidates = (resolved, EMBEDDED_FONT_FAMILY, 'Microsoft YaHei', 'Segoe UI')
    else:
        candidates = ('Microsoft YaHei', 'Segoe UI')
    families = [f for f in candidates if f]
    seen, ordered = set(), []
    for f in families:
        if f not in seen:
            seen.add(f)
            ordered.append(f)
    try:
        setFontFamilies(ordered, save=False)
    except Exception as e:
        log.warning("设置字体族失败: %s", e)
    # QSS 里的 font-family 由 LibraryStyleSheet 模板渲染，改完字体族必须
    # 重刷已注册控件的样式表，否则界面不会立刻变色（库不会自动重刷）
    try:
        from qfluentwidgets.common.style_sheet import updateStyleSheet
        updateStyleSheet(lazy=True)
    except Exception as e:
        log.warning("重刷字体样式失败: %s", e)
    # 应用级默认字体：新建控件直接继承
    try:
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            font = QFont(app.font())
            font.setFamilies(ordered)
            app.setFont(font)
    except Exception as e:
        log.warning("设置应用字体失败: %s", e)
    if refresh_widgets:
        _retarget_declared_fonts(ordered)
    _apply_mpl_font()
    log.info("应用字体已切换为：%s", resolved or "系统默认")
    return resolved


def _retarget_declared_fonts(families):
    """把已显式 setFont 过的控件改到新字体族，保留字号与字重。

    等宽字体（数据记录 / 原始数据读数）不参与切换——它们是刻意的
    等宽排版，跟着变会破坏数字对齐。
    """
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QWidget
    app = QApplication.instance()
    if app is None:
        return
    mono = mono_font_family()
    for widget in app.allWidgets():
        if not isinstance(widget, QWidget):
            continue
        font = widget.font()
        current = font.family() if hasattr(font, 'family') else ''
        if not current or current in (mono, MONO_FONT_FAMILY):
            continue
        new_font = QFont(font)
        new_font.setFamilies(families)
        widget.setFont(new_font)


# 首次启动（app_config.json 不存在）：先写入默认配置再加载，
# 保证默认主题色为蓝色（qfluentwidgets 库默认是青色 #009faa，不符合项目主题）
_app_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app_config.json')
_created_default_app_config = False
if not os.path.exists(_app_config_path):
    try:
        with open(_app_config_path, 'w', encoding='utf-8') as _f:
            json.dump(_APP_CONFIG_DEFAULT, _f, ensure_ascii=False, indent=4)
        _created_default_app_config = True   # 提示延迟到日志系统就绪后输出
    except Exception as _e:
        _app_config_create_error = _e
    else:
        _app_config_create_error = None
else:
    _app_config_create_error = None

qconfig.load(_app_config_path, app_cfg)


# ============================================================
# 运行日志（标准库 logging，零依赖，线程安全）
#
# 由设置页「运行日志」开关控制（默认开启，app_config.json 的 General.*）：


# ============================================================
# 运行日志（标准库 logging，零依赖，线程安全）
#
# 由设置页「运行日志」开关控制（默认开启，app_config.json 的 General.*）：
# - LogEnabled   ：是否写入 logs.json；控制台始终输出（关闭时仅不落盘）
# - LogLevel     ：warning / info / debug 三档详细度（开启后生效，默认 info）
# - LogMaxEntries：logs.json 最大保留条数，超出后裁剪最旧记录
# 日志文件为 src/ 目录 logs.json，JSON Lines 格式（每条一行 JSON 对象），
# 跨会话追加、即写即刷；文件属于本机运行数据，已在 .gitignore 中忽略。
# ============================================================


# ============================================================
# 日志设置：持久化到 app_config.json，再把值注入纯内核
# ============================================================
def setup_logging():
    """按 app_config.json 初始化内核日志，并同步配置持久化开关。"""
    _kernel_setup_logging(
        enabled=bool(app_cfg.logEnabled.value),
        level=str(app_cfg.logLevel.value),
        max_entries=int(app_cfg.logMaxEntries.value or 5000),
    )
    set_config_persistence(bool(app_cfg.configPersistenceEnabled.value))


def set_log_enabled(enabled):
    qconfig.set(app_cfg.logEnabled, bool(enabled))
    _kernel_set_log_enabled(bool(enabled))


def set_log_level(level):
    level = str(level).lower()
    qconfig.set(app_cfg.logLevel, level)
    _kernel_set_log_level(level)


def set_log_max_entries(max_entries):
    value = max(100, int(max_entries))
    qconfig.set(app_cfg.logMaxEntries, value)
    _kernel_set_log_max_entries(value)


def reset_all_config():
    """将 app_config.json 和 sensor_config.json 恢复为默认值。"""
    here = os.path.dirname(os.path.abspath(__file__))
    app_config_path = os.path.join(here, 'app_config.json')
    try:
        with open(app_config_path, 'w', encoding='utf-8') as f:
            json.dump(_APP_CONFIG_DEFAULT, f, ensure_ascii=False, indent=4)
        log.info("已恢复应用配置：%s", app_config_path)
    except Exception as e:
        return False, f"恢复应用配置失败: {e}"

    if not clear_sensor_config():
        return False, "删除传感器配置失败"

    try:
        qconfig.load(app_config_path, app_cfg)
    except Exception:
        pass

    return True, "所有设置已恢复默认值，重启后完全生效"


# 启动诊断：日志系统就绪后输出（关闭时控制台也保留启动/模块/配置提示）
setup_logging()
if _created_default_app_config:
    log.info('✓ 已生成默认应用配置：%s', _app_config_path)
if _app_config_create_error is not None:
    log.error('生成默认应用配置失败: %s', _app_config_create_error)
if not SERIAL_AVAILABLE:
    log.warning('未安装pyserial，何意味？你想不连接下位机吗（狗头）？')
for _engine in CHART_ENGINES:
    log.info('图表引擎 %s: %s', _engine,
             '✓ 已安装' if CHART_ENGINE_AVAILABLE[_engine] else '✗ 未安装')
if not any(CHART_ENGINE_AVAILABLE.values()):
    log.warning('？？？你为什么不安装图表引擎？行，那你别想看实时图表了（狗头）')

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


def current_theme_mode():
    """当前主题模式：'light' / 'dark' / 'auto'。

    主题状态的唯一事实来源是 qconfig.themeMode（持久化在
    app_config.json 的 QFluentWidgets.ThemeMode）。qconfig.theme 会把
    AUTO 解析成实际亮暗，因此判断「跟随系统」必须读 themeMode，
    不能用 isDarkTheme()。
    """
    from qfluentwidgets import Theme
    mode = qconfig.get(qconfig.themeMode)
    if mode == Theme.DARK:
        return 'dark'
    if mode == Theme.AUTO:
        return 'auto'
    return 'light'


def set_app_theme_mode(mode):
    """切换主题模式（light/dark/auto）并写入 app_config.json。

    注意 setTheme 的 save 默认是 False，必须显式 save=True 才会把
    QFluentWidgets.ThemeMode 落盘；自定义控件的刷新由
    qconfig.themeChanged 信号统一驱动（固定模式与跟随系统同一路径），
    调用方无需再手动遍历模块刷新。
    """
    from qfluentwidgets import Theme, setTheme
    mapping = {'light': Theme.LIGHT, 'dark': Theme.DARK, 'auto': Theme.AUTO}
    if mode not in mapping:
        return
    setTheme(mapping[mode], save=True)


def restore_app_theme():
    """启动时恢复上次主题模式（QApplication 之后、主窗口创建之前调用）。

    qconfig.load 只把 ThemeMode 读进配置，不会主动刷新 Fluent 组件
    样式；不显式 setTheme 一次，就会出现「配置是深色、组件仍浅色」
    的混合界面。save=False：仅应用，不重写配置文件。
    """
    from qfluentwidgets import setTheme
    setTheme(qconfig.get(qconfig.themeMode), save=False)


class SystemAccentListener(QAbstractNativeEventFilter):
    """监听 Windows 系统强调色变化（WM_DWMCOLORIZATIONCOLORCHANGED）。

    仅当配置为「跟随系统主题色」时生效：收到系统广播后重读注册表并
    刷新主题色。非 Windows 平台收不到该消息，无需额外判断。
    """

    WM_DWMCOLORIZATIONCOLORCHANGED = 0x0320

    def nativeEventFilter(self, eventType, message):
        try:
            if eventType == b'windows_generic_MSG' and message:
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
# 字体选择器（仿 Word 字体下拉）
#
# 列出**系统已安装的全部字体**（Qt6 在中文系统上直接返回本地化名称，
# 如「微软雅黑」「宋体」「楷体」「隶书」，无需查注册表映射），用字体
# 自身的字形渲染每个条目，右侧实时预览选中效果。
# 列表用 QListWidget + 自绘 delegate：全量字体只创建轻量条目对象，
# 不逐个实例化控件，200+ 字体下依然流畅。
# ============================================================
def _has_cjk(text):
    """是否含中日韩表意文字（用于把中文字体排到列表前面）。"""
    return any('\u4e00' <= ch <= '\u9fff' for ch in text or '')


class _FontItemDelegate(QStyledItemDelegate):
    """字体列表条目：用该字体自身的字形画字体名。"""

    def paint(self, painter, option, index):
        family = index.data(Qt.ItemDataRole.UserRole) or ''
        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
            painter.setPen(option.palette.highlightedText().color())
        else:
            painter.setPen(option.palette.text().color())
        # 条目文本可能带「（内嵌）」标记（用于搜索/辨识），但渲染时必须
        # 只用纯字体族名——用带标记的串去构造 QFont 会得到默认字体
        font = QFont(family) if family else QFont()
        font.setPixelSize(16)
        painter.setFont(font)
        rect = option.rect.adjusted(10, 0, -10, 0)
        label = index.data(Qt.ItemDataRole.DisplayRole) or family
        text = painter.fontMetrics().elidedText(
            label, Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter, text)
        painter.restore()

    def sizeHint(self, option, index):
        """固定行高，不调用基类实现。

        基类 QStyledItemDelegate.sizeHint 会为每个条目构造字体并测量文本，
        200+ 字体时首次打开对话框要额外几百毫秒。这里返回常量即可——
        绘制时已按 rect 垂直居中并做省略号处理，不需要精确测量。
        """
        return QSize(0, 34)


class FontPickerDialog(Dialog):
    """字体选择对话框（搜索框 + 字体自身字形列表 + 实时预览）。

    用法：
        dlg = FontPickerDialog(current_family, parent)
        if dlg.exec():
            family = dlg.selected_family()   # '' 表示系统默认字体
    """

    #: 预览文案（中英数混排，便于同时判断中文与西文字形）
    PREVIEW_TEXT = ("永远相信美好的事情即将发生\n"
                    "Hello, thank you, are you OK\n"
                    "0123456789  ！？，。、；：（）【】")

    def __init__(self, current='', parent=None):
        # content 传空串：Dialog 会额外插入一个显示 content 的标签，
        # 非空时会与顶部 windowTitleLabel 重复显示同一句话
        super().__init__("选择字体", "", parent)
        self._current = current or ''
        self._all = list_font_families()

        # ---- 搜索框 ----
        self.search_edit = LineEdit(self)
        self.search_edit.setPlaceholderText("搜索字体名（如「楷」「黑」「Arial」）…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._apply_filter)

        # ---- 字体列表（自绘条目，字体名用其自身字形） ----
        self.list_widget = QListWidget(self)
        self.list_widget.setItemDelegate(_FontItemDelegate(self.list_widget))
        # 行高固定：让 Qt 只问一次 sizeHint，而不是每个条目问一遍
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.setMinimumWidth(300)
        self.list_widget.currentItemChanged.connect(self._on_current_changed)
        self.list_widget.itemDoubleClicked.connect(lambda _i: self.accept())

        # 「系统默认」置顶：置空字体族，交给 Qt 决定
        default_item = QListWidgetItem("系统默认")
        default_item.setData(Qt.ItemDataRole.UserRole, '')
        self.list_widget.addItem(default_item)
        # 内嵌字体紧随其后（带「内嵌」标记）：它们随程序分发，任何机器都有，
        # 是最稳的选择，不该埋在 200 多个系统字体里让人翻找
        for family in embedded_font_families():
            item = QListWidgetItem(f"{family}（内嵌）")
            item.setData(Qt.ItemDataRole.UserRole, family)
            self.list_widget.addItem(item)
        for family in self._all:
            item = QListWidgetItem(family)
            item.setData(Qt.ItemDataRole.UserRole, family)
            self.list_widget.addItem(item)

        # ---- 预览区 ----
        self.preview_label = QLabel(self.PREVIEW_TEXT)
        self.preview_label.setWordWrap(True)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignTop |
                                       Qt.AlignmentFlag.AlignLeft)
        self.preview_label.setMinimumWidth(460)
        self.preview_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.preview_label.setMargin(12)
        self.preview_label.setStyleSheet(
            f"border: 1px solid {_theme_colors()['card_border']};"
            f" border-radius: 6px; padding: 12px;"
            f" background: {_theme_colors()['card_bg']};")

        right = QVBoxLayout()
        right.setSpacing(8)
        self._pick_hint = CaptionLabel("")
        right.addWidget(self._pick_hint)
        right.addWidget(self.preview_label, 1)

        left = QVBoxLayout()
        left.setSpacing(8)
        left.addWidget(self.search_edit)
        left.addWidget(self.list_widget, 1)

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addLayout(left, 1)
        body.addLayout(right, 1)
        self.textLayout.addLayout(body)

        self.yesButton.setText("使用该字体")
        self.cancelButton.setText("取消")

        self._select_family(self._current)
        # Dialog.__init__ 末尾有 setFixedSize(self.size())（当时布局还没算完，
        # 只有 240×192），之后 setFixedWidth/setMinimumHeight 一律无效。
        # 必须等内容填好后再显式锁一次尺寸，列表才有足够高度显示字体。
        self.setFixedSize(880, 620)
        self.list_widget.scrollToItem(self.list_widget.currentItem())

    # ---------------- 内部 ----------------
    def _select_family(self, family):
        """在列表中定位并选中指定字体（未找到则选中「系统默认」）。"""
        for i in range(self.list_widget.count()):
            if self.list_widget.item(i).data(Qt.ItemDataRole.UserRole) == family:
                self.list_widget.setCurrentRow(i)
                return
        if family:
            # 配置里的字体本机已卸载：仍如实显示，允许用户重新挑一个
            item = QListWidgetItem(f"{family}（未安装）")
            item.setData(Qt.ItemDataRole.UserRole, family)
            self.list_widget.insertItem(0, item)
            self.list_widget.setCurrentRow(0)
            return
        self.list_widget.setCurrentRow(0)

    def _apply_filter(self, text):
        """按关键字过滤列表（大小写不敏感）。"""
        key = (text or '').strip().lower()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            family = item.data(Qt.ItemDataRole.UserRole) or ''
            item.setHidden(bool(key) and key not in family.lower())

    def _on_current_changed(self, current, _previous):
        if current is None:
            return
        family = current.data(Qt.ItemDataRole.UserRole) or ''
        font = QFont()
        if family:
            font.setFamilies([family])
        font.setPixelSize(17)
        self.preview_label.setFont(font)
        self._pick_hint.setText(
            f"当前选择：{family}" if family else "当前选择：系统默认字体")

    def selected_family(self):
        """返回选中的字体族名；'' 表示系统默认。"""
        item = self.list_widget.currentItem()
        if item is None:
            return ''
        return item.data(Qt.ItemDataRole.UserRole) or ''


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
        self._fit_target = None       # 拟合对象 series_id；None=自动（各子图第一条）
        self._fit_target_combo = None  # ComboBox 拟合对象（仅多曲线时显示）
        self._fit_target_row = None   # 「拟合对象」整行容器（单曲线时隐藏）
        self._fit_target_sig = ()     # 上次构建下拉用的曲线集合签名
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
        # AI 分析实验：右上角浮动按钮 + 模块数据提供回调
        self._ai_data_provider = None   # callable() -> dict 或 None（模块注册）
        self._ai_btn = PushButton("AI分析实验", self)
        self._ai_btn.setFixedSize(116, 30)
        self._ai_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ai_btn.setToolTip("把当前实验数据发送给 AI 分析（需配置 API 端点与 Key）")
        self._ai_btn.clicked.connect(self._on_ai_clicked)
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

    def plot(self, x, y, color='#0078d4', width=2, label=None, index=0,
             series_id=None):
        """在第 index 个子图上绘制一条曲线。

        series_id: 曲线的稳定标识（模块传通道 id），用于「拟合对象」选择。
        不传时退回用 label 作标识；两者都没有时该曲线不参与单独选择。
        """
        self._spec[index]['plot'].append(
            {'x': list(x), 'y': list(y), 'color': _normalize_color(color),
             'width': width, 'label': label, 'series_id': series_id})

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
        spec = self._spec
        self._spec = None
        self._last = spec
        self._commit(spec)
        # 曲线集合变化（增删通道/改名）时重建「拟合对象」下拉；
        # 若当前选择失效（通道被删/隐藏）会回落「自动」，需要重绘一次
        if self._refresh_fit_target_options() and self._fit_mode > 0:
            self._commit(spec)

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
        # 「拟合对象」下拉随图表清空隐藏，并作废曲线签名；下次有数据时
        # 重建选项并按 series_id 恢复之前的选择（该通道仍存在的话）
        if self._fit_target_row is not None:
            self._fit_target_sig = None
            self._fit_target_row.setVisible(False)
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

    # ---------------- AI 分析实验 ----------------
    def set_ai_data_provider(self, provider):
        """注册实验数据回调（模块在 __init__ 调用）。

        provider() 返回 dict 或 None：
            {'title', 'x_label', 'y_label',
             'points': [(x, y), ...], 'extra': str(可选)}
        无数据时返回 None（按钮点击会提示先采集）。
        """
        self._ai_data_provider = provider

    def _on_ai_clicked(self):
        """「AI分析实验」：无数据时提示，有数据则先采集实验信息再打开 AI 窗口。

        进入对话前弹出 AIExperimentInfoDialog 可填写实验名称、实验目的、
        条件与备注（均为选填，留空可直接开始）；信息按模块记住并注入
        system 提示词，AI 结合实验背景作答。对话窗口持有数据回调（而非
        一次性快照）——每轮提问都实时取最新数据与参数，持续采集时 AI
        看到的始终是最新状态。
        """
        payload = None
        if self._ai_data_provider is not None:
            try:
                payload = self._ai_data_provider()
            except Exception as e:
                log.warning("AI 数据回调异常: %s", e)
        # 对话框 parent 用顶层窗口：qfluentwidgets 掩码对话框会以 parent 为
        # 基准铺满遮罩；传 ChartPanel 这类子控件会导致窗口 transient parent
        # 指向非顶层句柄（Qt 告警 “must be a top level window”）且遮罩尺寸
        # 只覆盖图表区
        host = self.window()
        if not payload or not payload.get('points'):
            fluent_message_box(
                host, "AI 分析实验",
                "当前没有可分析的数据。\n请先「开始采集」积累数据后再试。")
            return
        module_title = str(payload.get('title') or '实验')
        info_dlg = AIExperimentInfoDialog(
            module_title, initial=load_experiment_info(module_title),
            parent=host)
        if not info_dlg.exec():
            info_dlg.deleteLater()
            return
        experiment_info = info_dlg.get_info()
        info_dlg.deleteLater()
        save_experiment_info(module_title, experiment_info)
        dlg = AIChatDialog(
            self._ai_data_provider, experiment_info=experiment_info, parent=host)
        dlg.exec()
        dlg.deleteLater()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if getattr(self, '_ai_btn', None) is not None:
            # 浮动按钮钉在图表右上角（不占布局，主题由 Fluent 组件自动适配）
            self._ai_btn.move(self.width() - self._ai_btn.width() - 12, 12)
            self._ai_btn.raise_()

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

        # 拟合对象：多曲线时选择用哪一路做拟合；单曲线时整行隐藏
        self._fit_target_combo = ComboBox()
        self._fit_target_combo.addItem("自动（第一条）", userData=None)
        self._fit_target_combo.setMinimumWidth(120)
        self._fit_target_combo.currentIndexChanged.connect(
            self._on_fit_target_changed)

        row_target = QWidget()
        lay_target = QHBoxLayout(row_target)
        lay_target.setContentsMargins(0, 0, 0, 0)
        lay_target.setSpacing(8)
        lay_target.addWidget(BodyLabel("拟合对象"))
        lay_target.addWidget(self._fit_target_combo)
        lay_target.addStretch(1)
        row_target.setVisible(False)
        self._fit_target_row = row_target

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
        vlay.addWidget(row_target)
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

    # ---------------- 拟合对象（多曲线时选择哪条做拟合） ----------------
    @staticmethod
    def _series_identity(series):
        """曲线的稳定标识：优先 series_id，其次 label。"""
        sid = series.get('series_id')
        if sid not in (None, ''):
            return str(sid)
        label = series.get('label')
        return 'label:%s' % label if label else ''

    def _target_series(self, subplot):
        """返回当前拟合目标在该子图里的曲线 dict；找不到返回 None。

        _fit_target 为 None 时取该子图第一条曲线（保持旧行为）。
        """
        plots = subplot.get('plot') or []
        if not plots:
            return None
        if self._fit_target is None:
            return plots[0]
        for series in plots:
            if self._series_identity(series) == self._fit_target:
                return series
        return None

    def _series_options(self, spec):
        """按子图顺序收集可拟合曲线 [(identity, label), ...]（去重保序）。"""
        options, seen = [], set()
        for subplot in spec or []:
            for series in subplot.get('plot') or []:
                ident = self._series_identity(series)
                if not ident or ident in seen:
                    continue
                seen.add(ident)
                options.append((ident, series.get('label')
                                or '曲线%d' % (len(options) + 1)))
        return options

    def _refresh_fit_target_options(self):
        """重建「拟合对象」下拉；返回当前选择是否发生变化。

        仅多曲线时显示该行；选择按 series_id 保留，目标消失则回落「自动」。
        """
        combo = self._fit_target_combo
        if combo is None:
            return False
        options = self._series_options(self._last)
        multi = len(options) > 1
        if self._fit_target_row is not None:
            self._fit_target_row.setVisible(multi)
        signature = tuple(options)
        if self._fit_target_sig != signature:
            self._fit_target_sig = signature
            previous = self._fit_target
            combo.blockSignals(True)
            try:
                combo.clear()
                combo.addItem("自动（第一条）", userData=None)
                for ident, label in options:
                    combo.addItem(label, userData=ident)
                index = combo.findData(previous) if previous is not None else 0
                if index < 0:
                    index = 0
                combo.setCurrentIndex(index)
                self._fit_target = combo.currentData()
            finally:
                combo.blockSignals(False)
            return self._fit_target != previous
        if not multi and self._fit_target is not None:
            self._fit_target = None
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
            return True
        return False

    def _on_fit_target_changed(self, _index):
        """用户切换拟合对象：旧目标的剔除掩码作废，重绘拟合。"""
        combo = self._fit_target_combo
        if combo is None:
            return
        target = combo.currentData()
        if target == self._fit_target:
            return
        self._fit_target = target
        self._reset_outlier_state()   # 掩码按旧目标长度算，切换后不能复用
        self._pg_cache = None
        self._scatter_hidden = False
        self._update_fit_hint()
        if self._last is not None:
            self._commit(self._last)

    # ---------------- 离群点剔除（残差比例法 + 多级撤销） ----------------
    def _visible_spec(self, spec):
        """返回剔除掩码作用后的可见事务副本。

        掩码只作用于当前「拟合对象」那条曲线（每个子图各一条，其余
        曲线原样保留）。无掩码时直接返回原对象（零开销，实时路径不触发
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
            target = self._target_series(sp) if sp['plot'] else None
            if m is None or target is None:
                out.append(sp)
                continue
            x, y = target['x'], target['y']
            if not len(x):
                out.append(sp)
                continue
            m = np.asarray(m[:len(x)], dtype=bool)
            if len(m) < len(x):          # 新追加的点不在掩码内 → 保留
                m = np.concatenate([m, np.ones(len(x) - len(m), dtype=bool)])
            if bool(m.all()):
                out.append(sp)
                continue
            ti = next(j for j, p in enumerate(sp['plot']) if p is target)
            plots = list(sp['plot'])
            plots[ti] = dict(target, x=np.asarray(x)[m], y=np.asarray(y)[m])
            ns = dict(sp)
            ns['plot'] = plots
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
            target = self._target_series(sp)
            if target is None or not len(target['x']):
                new_masks.append(old_masks[len(new_masks)]
                                 if old_masks and len(new_masks) < len(old_masks)
                                 else None)
                continue
            x = np.asarray(target['x'], dtype=float)
            y = np.asarray(target['y'], dtype=float)
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
            for sp in self._last:
                target = self._target_series(sp)
                if target is not None and len(target['x']) >= 2:
                    has_data = True
                    break
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
            s = self._target_series(sp)   # 用户选择的拟合对象（默认第一条）
            if s is None or not len(s['x']):
                continue
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
            # 方程文本：锚定视口左上角，纵向让开图例（图例默认也在左上）。
            # anchor=(0,0)：文本框左上角对齐 setPos；图例高度随曲线数变化，
            # 按当前图例的包围盒下移，避免方程与图例叠在一起。
            ti = TextItem(text, color=fg, anchor=(0, 0))
            vb = pi.getViewBox()
            ti.setParentItem(vb)
            offset = 8
            legend = getattr(pi, 'legend', None)
            if legend is not None:
                try:
                    offset = max(8, legend.boundingRect().height() + 8)
                except Exception:
                    pass
            ti.setPos(8, offset)
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
# AI 分析实验（OpenAI 兼容端点；图表卡「AI分析实验」按钮）
# ============================================================
# 通用分析规范（每次请求都带上；模块预置提示词 / 用户补充叠加其后）
_AI_BASE_PROMPT = (
    "你是严谨的物理/化学实验数据分析助手，正在与应用内的实验采集模块对话。"
    "用户是实验操作者，会就当前实验数据提问，也可能要求统计、拟合、误差分析"
    "或实验改进建议。实验数据与配置参数由系统自动附带在系统消息中，请基于"
    "这些真实数据回答，不要编造数据中没有的信息；数据不足时明确说明还缺什么。"
    "回答要求：①结论先行，再分点给出依据；②涉及计算时给出公式、代入过程与结果，"
    "保留合理有效数字并标注单位；③明确区分随机误差与系统误差，尽量量化不确定度"
    "（标准差、漂移速率、分辨率等）；④改进建议要具体可执行（改哪个参数、怎么操作）；"
    "⑤时间序列数据需注意采样间隔与数据点数量，结论注明适用范围与局限。"
    "回答用中文，简洁准确。"
)


def _ai_fmt_num(v):
    """数值紧凑格式化；非数值（None/字符串等异常数据）原样输出防崩溃。"""
    try:
        return f"{float(v):.4g}"
    except (TypeError, ValueError):
        return str(v)


def _format_ai_data(context, limit=5000):
    """把实验数据整理为文本表；超过 limit 行时均匀抽样保持趋势。"""
    pts = context.get('points') or []
    n = len(pts)
    limit = max(100, int(limit or 5000))
    step = max(1, (n + limit - 1) // limit)
    rows = pts[::step]
    lines = [
        f"实验: {context.get('title', '')}",
        f"数据列: {context.get('x_label', 'X')}, {context.get('y_label', 'Y')}",
        f"数据点总数: {n}（均匀抽样至 {len(rows)} 行）",
        "数据:",
    ]
    for x, y in rows:
        lines.append(f"{_ai_fmt_num(x)}, {_ai_fmt_num(y)}")
    extra = context.get('extra')
    if extra:
        lines.append("补充说明: " + str(extra))
    return "\n".join(lines)


def load_experiment_info(module_title):
    """读取某模块上次填写的实验信息（实验名称/目的/条件备注）。

    由 ChartPanel 进入 AI 分析时调用，预填 AIExperimentInfoDialog；
    从未填写过返回空 dict（不报错）。
    """
    try:
        store = app_cfg.aiExperimentInfo.value or {}
        info = store.get(module_title) if isinstance(store, dict) else None
        return dict(info) if isinstance(info, dict) else {}
    except Exception:
        return {}


def save_experiment_info(module_title, info):
    """按模块记住实验信息（写入 app_config.json，下次实验自动带回）。"""
    try:
        store = dict(app_cfg.aiExperimentInfo.value or {})
        store[module_title] = dict(info or {})
        qconfig.set(app_cfg.aiExperimentInfo, store)
    except Exception as e:
        log.warning("保存实验信息失败: %s", e)


def module_default_prompt(context):
    """返回模块内置（出厂）系统提示词：优先新键 system_prompt，兼容旧键 prompt。"""
    if not context:
        return ''
    return str(context.get('system_prompt') or context.get('prompt') or '')


def get_module_prompt(module_title, default):
    """返回模块当前生效的系统提示词。

    用户覆盖（AIModulePrompts，含显式清空为空串）优先；未覆盖回退内置。
    """
    try:
        overrides = app_cfg.aiModulePrompts.value
        if isinstance(overrides, dict) and module_title in overrides:
            return str(overrides.get(module_title) or '')
    except Exception:
        pass
    return default


def set_module_prompt(module_title, text, default):
    """保存模块系统提示词覆盖；与内置相同则清除覆盖（回退内置）。

    text 为空串表示用户显式清空预置提示词（保留空覆盖，不回退内置）。
    """
    try:
        store = dict(app_cfg.aiModulePrompts.value or {})
        if text == default:
            store.pop(module_title, None)
        else:
            store[module_title] = text
        qconfig.set(app_cfg.aiModulePrompts, store)
    except Exception as e:
        log.warning("保存模块提示词失败: %s", e)


def build_ai_system_prompt(context, experiment_info=None):
    """组装 system 消息。

    分层顺序（越靠后越具体）：
    通用规范 → 模块专属系统提示词（可被用户覆盖）→ 本次实验信息（名称/目的/备注）
    → 用户补充要求 → 实验配置参数 → 实验数据。
    """
    parts = [_AI_BASE_PROMPT]
    if context:
        module_prompt = get_module_prompt(
            str(context.get('title') or ''), module_default_prompt(context))
        if module_prompt:
            parts.append("【模块专属系统提示词】\n" + module_prompt)
    info = experiment_info or {}
    info_lines = []
    if str(info.get('name') or '').strip():
        info_lines.append("实验名称：" + str(info['name']).strip())
    if str(info.get('purpose') or '').strip():
        info_lines.append("实验目的：" + str(info['purpose']).strip())
    if str(info.get('notes') or '').strip():
        info_lines.append("实验条件与备注：" + str(info['notes']).strip())
    if info_lines:
        parts.append("【本次实验信息】\n" + "\n".join(info_lines))
    if context:
        user_prompt = (app_cfg.aiUserPrompt.value or "").strip()
        if user_prompt:
            parts.append("【用户补充要求】\n" + user_prompt)
        if context.get('params'):
            parts.append("【实验配置参数】\n" + str(context['params']))
        parts.append("【实验数据】\n" + _format_ai_data(
            context, app_cfg.aiDataLimit.value))
    return "\n\n".join(parts)


class AIRequestThread(QThread):
    """把对话消息发送到 OpenAI 兼容端点（后台线程，不阻塞 UI）。"""

    finished_ok = Signal(str)   # AI 回复正文
    finished_err = Signal(str)  # 错误描述

    def __init__(self, endpoint, api_key, model, messages,
                 temperature=0.3, max_tokens=0):
        super().__init__()
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.messages = messages
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)

    def run(self):
        try:
            import json
            import urllib.request
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            body = {
                "model": self.model or "deepseek-v4-flash",
                "messages": self.messages,
                "temperature": self.temperature,
            }
            if self.max_tokens > 0:
                body["max_tokens"] = self.max_tokens
            req = urllib.request.Request(
                self.endpoint,
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            try:
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                # 非标准响应结构：原样返回 JSON 便于排查
                content = json.dumps(data, ensure_ascii=False, indent=2)
            self.finished_ok.emit(content)
        except Exception as e:
            self.finished_err.emit(str(e))


class AIExperimentInfoDialog(Dialog):
    """进入 AI 分析前的实验信息采集框（全部选填）。

    由 ChartPanel「AI分析实验」按钮弹出，可填写：
    - 实验名称
    - 实验目的
    - 实验条件与备注
    三个字段均为选填，留空可直接「开始分析」；信息按模块名记住
    （app_config.json），下次进入自动预填，填写后以【本次实验信息】
    注入 system 提示词，AI 结合背景作答。
    """

    def __init__(self, module_title, initial=None, parent=None):
        super().__init__(
            "实验信息",
            f"可填写本次实验的基本信息（选填），AI 将结合这些信息分析「{module_title}」的数据",
            parent)
        self.setFixedWidth(540)
        # 紧凑布局：减小默认行距与内边距
        self.textLayout.setSpacing(4)
        self.textLayout.setContentsMargins(16, 12, 16, 8)
        self.buttonGroup.setFixedHeight(64)
        self.buttonLayout.setContentsMargins(16, 8, 16, 8)
        info = initial or {}

        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText(
            f"实验名称（选填），如：{module_title}探究实验")
        self.name_edit.setText(str(info.get('name') or ''))
        self.name_edit.setClearButtonEnabled(True)

        self.purpose_edit = TextEdit(self)
        self.purpose_edit.setPlaceholderText(
            "实验目的（选填），如：探究质量与重力的关系")
        self.purpose_edit.setPlainText(str(info.get('purpose') or ''))
        self.purpose_edit.setMinimumHeight(56)

        self.notes_edit = TextEdit(self)
        self.notes_edit.setPlaceholderText(
            "实验条件与备注（选填），如：室温 25℃、使用 100g 标准砝码、采样 60 秒")
        self.notes_edit.setPlainText(str(info.get('notes') or ''))
        self.notes_edit.setMinimumHeight(56)

        self.textLayout.addWidget(BodyLabel("实验名称"))
        self.textLayout.addWidget(self.name_edit)
        self.textLayout.addWidget(BodyLabel("实验目的"))
        self.textLayout.addWidget(self.purpose_edit)
        self.textLayout.addWidget(BodyLabel("实验条件与备注"))
        self.textLayout.addWidget(self.notes_edit)

        self.yesButton.setText("开始分析")
        self.cancelButton.setText("取消")

    def get_info(self):
        """返回实验信息 dict（用于 system 提示词与按模块持久化）。"""
        return {
            'name': self.name_edit.text().strip(),
            'purpose': self.purpose_edit.toPlainText().strip(),
            'notes': self.notes_edit.toPlainText().strip(),
        }


class AISettingsDialog(Dialog):
    """AI 参数设置：端点 / Key / 模型 / 温度 / 最大输出 / 模块预置提示词 / 用户提示词 / 数据上限。

    context（模块数据上下文）用于显示并编辑该模块的预置系统提示词：
    修改后按模块保存（app_config.json 的 General.AIModulePrompts），
    「恢复默认」还原模块内置内容；未提供 context 时该区域禁用。
    """

    def __init__(self, parent=None, context=None):
        super().__init__("AI 设置", "", parent)
        self.setFixedWidth(560)
        # 紧凑布局：默认行距 12px / 内边距 24px 过松，整体压缩
        self.textLayout.setSpacing(4)
        self.textLayout.setContentsMargins(16, 12, 16, 8)
        self.buttonGroup.setFixedHeight(64)
        self.buttonLayout.setContentsMargins(16, 8, 16, 8)
        self._context = context or {}
        self._module_title = str(self._context.get('title') or '')
        self._default_module_prompt = module_default_prompt(self._context)
        has_module_prompt = bool(self._default_module_prompt)

        self.endpoint_edit = LineEdit(self)
        self.endpoint_edit.setText(app_cfg.aiEndpoint.value)
        self.endpoint_edit.setPlaceholderText(
            "OpenAI 兼容端点，如 https://api.deepseek.com/v1/chat/completions")
        self.endpoint_edit.setToolTip(
            "任意 OpenAI 兼容 /chat/completions 端点（含本地 Ollama 等）")

        self.key_edit = LineEdit(self)
        self.key_edit.setText(app_cfg.aiApiKey.value)
        self.key_edit.setEchoMode(LineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("API Key（本地端点可留空）")

        self.model_edit = LineEdit(self)
        self.model_edit.setText(app_cfg.aiModel.value)
        self.model_edit.setPlaceholderText("模型名，如 deepseek-v4-flash / qwen2.5")

        self.temp_spin = DoubleSpinBox(self)
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setDecimals(2)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setValue(float(app_cfg.aiTemperature.value))

        self.maxtok_spin = SpinBox(self)
        self.maxtok_spin.setRange(0, 200000)
        self.maxtok_spin.setSingleStep(256)
        self.maxtok_spin.setValue(int(app_cfg.aiMaxTokens.value))
        self.maxtok_spin.setToolTip("单次回复的最大 token 数，0 = 不限制")

        self.limit_spin = SpinBox(self)
        self.limit_spin.setRange(100, 200000)
        self.limit_spin.setSingleStep(500)
        self.limit_spin.setValue(int(app_cfg.aiDataLimit.value))
        self.limit_spin.setToolTip("每轮附带的数据行数上限（超出均匀抽样）")

        # 模块预置系统提示词：可编辑并保存（仅影响当前模块），恢复默认还原内置内容
        self.module_prompt_edit = TextEdit(self)
        self.module_prompt_edit.setPlainText(
            get_module_prompt(self._module_title, self._default_module_prompt))
        self.module_prompt_edit.setPlaceholderText(
            "当前模块未提供预置提示词（未获取到模块上下文时禁用）")
        self.module_prompt_edit.setMinimumHeight(84)
        self.module_prompt_edit.setEnabled(has_module_prompt)

        self.reset_module_prompt_btn = PushButton("恢复默认", self)
        self.reset_module_prompt_btn.setFixedHeight(30)
        self.reset_module_prompt_btn.setEnabled(has_module_prompt)
        self.reset_module_prompt_btn.setToolTip("还原为模块内置的分析提示词")
        self.reset_module_prompt_btn.clicked.connect(self._on_reset_module_prompt)

        module_hint = CaptionLabel(
            "可修改并保存，仅对当前模块生效；与内置相同时自动回退内置")
        module_row = QHBoxLayout()
        module_row.setSpacing(8)
        module_row.addWidget(module_hint, 1)
        module_row.addWidget(self.reset_module_prompt_btn)
        module_row_w = QWidget(self)
        module_row_w.setLayout(module_row)

        self.user_prompt_edit = TextEdit(self)
        self.user_prompt_edit.setPlainText(app_cfg.aiUserPrompt.value or "")
        self.user_prompt_edit.setPlaceholderText(
            "自定义系统提示词（可选，所有模块生效），叠加在模块预置提示词之后")
        self.user_prompt_edit.setMinimumHeight(52)

        self.textLayout.addWidget(BodyLabel("API 端点"))
        self.textLayout.addWidget(self.endpoint_edit)
        self.textLayout.addWidget(BodyLabel("API Key"))
        self.textLayout.addWidget(self.key_edit)
        self.textLayout.addWidget(BodyLabel("模型"))
        self.textLayout.addWidget(self.model_edit)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(BodyLabel("温度"))
        row.addWidget(self.temp_spin)
        row.addSpacing(12)
        row.addWidget(BodyLabel("最大输出 token"))
        row.addWidget(self.maxtok_spin)
        row.addSpacing(12)
        row.addWidget(BodyLabel("数据行上限"))
        row.addWidget(self.limit_spin)
        row.addStretch(1)
        row_w = QWidget(self)
        row_w.setLayout(row)
        self.textLayout.addWidget(row_w)

        self.textLayout.addWidget(BodyLabel("模块预置系统提示词"))
        self.textLayout.addWidget(self.module_prompt_edit)
        self.textLayout.addWidget(module_row_w)
        self.textLayout.addWidget(BodyLabel("自定义系统提示词（用户补充）"))
        self.textLayout.addWidget(self.user_prompt_edit)

        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")
        try:
            self.yesButton.clicked.disconnect()
        except Exception:
            pass
        self.yesButton.clicked.connect(self._on_save)

    def _on_reset_module_prompt(self):
        """恢复默认：编辑框还原为模块内置提示词（保存后清除覆盖）。"""
        self.module_prompt_edit.setPlainText(self._default_module_prompt)

    def _on_save(self):
        try:
            qconfig.set(app_cfg.aiEndpoint, self.endpoint_edit.text().strip())
            qconfig.set(app_cfg.aiApiKey, self.key_edit.text().strip())
            qconfig.set(app_cfg.aiModel, self.model_edit.text().strip())
            qconfig.set(app_cfg.aiTemperature, float(self.temp_spin.value()))
            qconfig.set(app_cfg.aiMaxTokens, int(self.maxtok_spin.value()))
            qconfig.set(app_cfg.aiDataLimit, int(self.limit_spin.value()))
            qconfig.set(app_cfg.aiUserPrompt,
                        self.user_prompt_edit.toPlainText())
            if self._module_title and self._default_module_prompt:
                set_module_prompt(
                    self._module_title,
                    self.module_prompt_edit.toPlainText().strip(),
                    self._default_module_prompt)
        except Exception as e:
            log.warning("保存 AI 配置失败: %s", e)
        self.accept()


class AIChatDialog(Dialog):
    """对话式 AI 分析窗口。

    - 进入前由 AIExperimentInfoDialog 采集实验信息（名称/目的/备注），
      窗口内「实验信息」按钮可随时修改，每轮发送注入最新信息；
    - 每轮发送时实时调用 context_provider() 取最新数据/参数，组装 system
      消息（通用规范 + 模块专属提示词 + 本次实验信息 + 用户补充 + 参数 +
      数据），再附上完整对话历史；数据持续采集时无需手动刷新即是最新值；
    - 右上角「设置」打开 AISettingsDialog（模型参数 / 系统提示词）；
    - 请求在后台线程执行，发送中禁用输入；关闭窗口线程自动收尾不崩溃。
    """

    def __init__(self, context_provider, experiment_info=None, parent=None):
        super().__init__("AI 分析实验", "", parent)
        self._provider = context_provider   # callable() -> context dict / None
        self._experiment_info = dict(experiment_info or {})  # 实验名称/目的/备注
        self._messages = []                 # 对话历史（不含 system）
        self._thread = None
        self.setFixedWidth(680)
        self.setMinimumHeight(520)

        # ---- 顶部工具行：数据摘要 + 实验信息 / 同步 / 清空 / 设置 ----
        self.summary_label = CaptionLabel("")
        self.info_btn = PushButton("实验信息", self)
        self.info_btn.setFixedHeight(30)
        self.info_btn.setToolTip("查看/修改实验名称、目的与备注（每轮分析生效）")
        self.info_btn.clicked.connect(self._on_edit_info)
        self.sync_btn = PushButton("同步数据", self)
        self.sync_btn.setFixedHeight(30)
        self.sync_btn.clicked.connect(self._on_sync)
        self.clear_btn = PushButton("清空对话", self)
        self.clear_btn.setFixedHeight(30)
        self.clear_btn.clicked.connect(self._on_clear)
        self.settings_btn = ToolButton(FluentIcon.SETTING, self)
        self.settings_btn.setFixedSize(30, 30)
        self.settings_btn.setToolTip("AI 设置（模型参数 / 系统提示词）")
        self.settings_btn.clicked.connect(self._on_settings)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self.summary_label, 1)
        top.addWidget(self.info_btn)
        top.addWidget(self.sync_btn)
        top.addWidget(self.clear_btn)
        top.addWidget(self.settings_btn)
        top_w = QWidget(self)
        top_w.setLayout(top)
        self.textLayout.addWidget(top_w)

        # ---- 对话区（滚动的左右气泡） ----
        self.chat_scroll = QScrollArea(self)
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chat_scroll.setMinimumHeight(320)
        self.chat_body = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_body)
        self.chat_layout.setContentsMargins(4, 4, 4, 4)
        self.chat_layout.setSpacing(8)
        self.chat_layout.addStretch(1)
        self.chat_scroll.setWidget(self.chat_body)
        self.textLayout.addWidget(self.chat_scroll, 1)

        # ---- 输入区（Enter 发送，Shift+Enter 换行） ----
        self.input_edit = TextEdit(self)
        self.input_edit.setPlaceholderText(
            "输入问题，Enter 发送（Shift+Enter 换行）…")
        self.input_edit.setFixedHeight(64)
        self.input_edit.installEventFilter(self)
        self.send_btn = PrimaryPushButton("发送", self)
        self.send_btn.setFixedSize(80, 64)
        self.send_btn.clicked.connect(self._on_send)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        bottom.addWidget(self.input_edit, 1)
        bottom.addWidget(self.send_btn)
        bottom_w = QWidget(self)
        bottom_w.setLayout(bottom)
        self.textLayout.addWidget(bottom_w)

        self.yesButton.hide()
        self.cancelButton.setText("关闭")

        self._refresh_summary()
        name = self._experiment_info.get('name')
        if name:
            self._add_bubble(
                f"已记录实验「{name}」，当前实验数据和参数已带上。"
                "可以直接提问，比如：总结数据趋势、判断异常点、推荐拟合函数、"
                "分析误差来源与改进方法。",
                False)
        else:
            self._add_bubble(
                "你好，我已经带上当前实验的数据和参数。可以直接提问，"
                "比如：帮我总结数据趋势、这段数据有没有异常、适合用什么函数拟合。",
                False)

    # ---------------- 上下文 ----------------
    def _get_context(self):
        if self._provider is None:
            return None
        try:
            return self._provider()
        except Exception as e:
            log.warning("AI 数据回调异常: %s", e)
            return None

    def _refresh_summary(self):
        ctx = self._get_context()
        if not ctx or not ctx.get('points'):
            self.summary_label.setText("当前没有可用的实验数据")
            return
        n = len(ctx.get('points') or [])
        name = str(self._experiment_info.get('name') or '').strip()
        prefix = f"{name} · " if name else ""
        self.summary_label.setText(
            f"{prefix}{ctx.get('title', '实验')}：{n} 个数据点"
            f"（{ctx.get('x_label', 'X')} / {ctx.get('y_label', 'Y')}）")

    # ---------------- 气泡 ----------------
    def _add_bubble(self, text, is_user):
        label = QLabel(text)
        label.setWordWrap(True)
        # 富文本：AI 回复按 Markdown 渲染（Qt 内置 GitHub 方言，支持标题、
        # 列表、粗体、代码块、表格、链接等）；用户输入保持纯文本，避免其
        # 内容被当作标记解析。AI 输出不可信，链接只放行 http/https。
        label.setTextFormat(
            Qt.TextFormat.PlainText if is_user else Qt.TextFormat.MarkdownText)
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse)
        label.linkActivated.connect(self._on_bubble_link)
        label.setMaximumWidth(560)
        c = _theme_colors()
        if is_user:
            label.setStyleSheet(
                f"background-color: {c['accent']}; color: #ffffff;"
                " border-radius: 8px; padding: 8px 12px;")
        else:
            label.setStyleSheet(
                f"background-color: {c['hover_bg']};"
                f" color: {c['text_primary']};"
                " border-radius: 8px; padding: 8px 12px;")
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if is_user:
            row.addStretch(1)
            row.addWidget(label)
        else:
            row.addWidget(label)
            row.addStretch(1)
        row_w = QWidget(self.chat_body)
        row_w.setLayout(row)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, row_w)
        self._scroll_to_bottom()

    @staticmethod
    def _on_bubble_link(url):
        """气泡内链接点击：仅放行 http/https，用系统默认浏览器打开。

        AI 回复内容不可信，file:// 等本地协议一律忽略，避免误开本地文件。
        """
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        u = QUrl(url)
        if u.scheme().lower() in ("http", "https"):
            QDesktopServices.openUrl(u)

    def _scroll_to_bottom(self):
        vsb = self.chat_scroll.verticalScrollBar()
        QTimer.singleShot(0, lambda: vsb.setValue(vsb.maximum()))

    # ---------------- 交互 ----------------
    def eventFilter(self, obj, event):
        if obj is self.input_edit and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                    self._on_send()
                    return True
        return super().eventFilter(obj, event)

    def _on_settings(self):
        dlg = AISettingsDialog(self, context=self._get_context())
        dlg.exec()
        dlg.deleteLater()
        self._refresh_summary()

    def _on_sync(self):
        ctx = self._get_context()
        if ctx and ctx.get('points'):
            self._refresh_summary()
            self._add_bubble(
                f"已同步最新数据（{len(ctx['points'])} 个数据点），"
                "之后提问会基于最新数据。", False)
        else:
            self._add_bubble("当前没有可用的实验数据。", False)

    def _on_edit_info(self):
        """查看/修改实验信息：确认后按模块保存，之后的每轮分析生效。"""
        ctx = self._get_context() or {}
        module_title = str(ctx.get('title') or '实验')
        dlg = AIExperimentInfoDialog(
            module_title, initial=self._experiment_info, parent=self)
        if not dlg.exec():
            dlg.deleteLater()
            return
        self._experiment_info = dlg.get_info()
        dlg.deleteLater()
        save_experiment_info(module_title, self._experiment_info)
        self._refresh_summary()
        self._add_bubble(
            f"已更新实验信息：{self._experiment_info.get('name', '')}。"
            "之后的提问将基于新的实验信息。", False)

    def _on_clear(self):
        self._messages = []
        while self.chat_layout.count() > 1:
            item = self.chat_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._refresh_summary()

    def _set_busy(self, busy):
        self.send_btn.setEnabled(not busy)
        self.send_btn.setText("分析中…" if busy else "发送")
        self.settings_btn.setEnabled(not busy)

    def _on_send(self):
        if self._thread is not None and self._thread.isRunning():
            return
        text = self.input_edit.toPlainText().strip()
        if not text:
            return
        endpoint = (app_cfg.aiEndpoint.value or "").strip()
        if not endpoint:
            self._add_bubble("请先点右上角「设置」填写 API 端点。", False)
            return
        ctx = self._get_context()
        if not ctx or not ctx.get('points'):
            self._add_bubble("当前没有可用的实验数据，请先采集一些数据。", False)
            return

        self.input_edit.clear()
        self._add_bubble(text, True)
        self._messages.append({'role': 'user', 'content': text})
        self._refresh_summary()
        self._set_busy(True)

        msgs = ([{'role': 'system',
                  'content': build_ai_system_prompt(ctx, self._experiment_info)}]
                + self._messages)
        # 线程不挂 parent：发送中关闭窗口时线程继续运行，完成后自毁
        # （挂 parent 会随对话框析构触发「QThread destroyed while running」
        #  的 Qt fail-fast 崩溃 0xC0000409）
        self._thread = AIRequestThread(
            endpoint,
            (app_cfg.aiApiKey.value or "").strip(),
            (app_cfg.aiModel.value or "").strip(),
            msgs,
            temperature=app_cfg.aiTemperature.value,
            max_tokens=app_cfg.aiMaxTokens.value,
        )
        self._thread.finished_ok.connect(self._on_done_ok)
        self._thread.finished_err.connect(self._on_done_err)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_done_ok(self, content):
        self._messages.append({'role': 'assistant', 'content': content})
        self._add_bubble(content, False)
        self._set_busy(False)
        self._thread = None

    def _on_done_err(self, err_text):
        # 失败的一轮从历史里移除，避免污染后续上下文
        if self._messages and self._messages[-1]['role'] == 'user':
            self._messages.pop()
        self._add_bubble(f"请求失败：{err_text}", False)
        self._set_busy(False)
        self._thread = None

# ============================================================
# 串口通信线程
# ============================================================
#: 退出清理时未在限时内结束的线程（保活引用，避免正在运行的 QThread
#: 被 Python 回收触发 Qt fail-fast 崩溃）
_retired_threads = []




def stop_thread(thread, timeout=2000, name="通信线程"):
    """请求线程停止并限时等待，退出清理专用。

    正常线程 20ms 内结束；串口打开阻塞等极端情况下超时不阻塞退出，
    并把线程引用收进 _retired_threads 保活（正在运行的 QThread 被
    Python 回收会触发 Qt fail-fast 崩溃）。
    """
    if thread is None:
        return
    try:
        thread.stop()
    except Exception as e:
        log.warning("停止%s失败: %s", name, e)
    try:
        if not thread.wait(timeout):
            log.warning("%s未在 %dms 内退出，保留引用等待其自行收尾", name, timeout)
            _retired_threads.append(thread)
    except Exception as e:
        log.warning("等待%s退出失败: %s", name, e)



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

    def __init__(self, title, content_widget=None, expanded=True, parent=None,
                 icon=None):
        super().__init__(icon or self.__class__.ICON or FluentIcon.FOLDER,
                         title, None, parent)

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

        # 折叠/展开动画的终点是启动时记录的滚动条最大值，若动画期间
        # 内容高度变化（面板显隐、宽度回流），折叠后卡片会停在半途
        # 高度，header 下方残留一片空白。动画结束后按当前内容重算一次。
        self.expandAni.finished.connect(self._syncHeightAfterAni)

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
    def _syncHeightAfterAni(self):
        """折叠/展开动画结束后把高度收敛到当前内容的真实高度。

        折叠：无论动画停在哪里，都收回 header 高度；展开：按内容
        sizeHint 重算。直接 setFixedHeight，不再播动画。
        """
        try:
            if self.isExpand:
                h = self.viewLayout.sizeHint().height()
                self.setFixedHeight(self.card.height() + h)
                self.verticalScrollBar().setValue(0)
            else:
                self.setFixedHeight(self.card.height())
        except Exception:
            pass

    def _adjustViewSize(self):
        """用自定义内容高度重算卡片高度（替代原生基于 group 行数的算法）。"""
        h = self.body.sizeHint().height()
        self.spaceWidget.setFixedHeight(h)
        if self.isExpand:
            self.setFixedHeight(self.card.height() + h)

    def refresh_height(self):
        """内容显隐或文字变化后重算卡片高度。

        默认只在构造与展开动画结束时算一次；子面板显隐（如 16 位时的
        ADS1115 参数行）、标签文案变长后不会自动重算，内容会被裁切，
        需折叠再展开才恢复。模块在内容变化后调用本方法即可。
        """
        # 子面板刚 setVisible 时，body.sizeHint() 仍可能按旧状态缓存，
        # 必须先强制失效并激活一次，才能量到真实高度
        self.body.invalidate()
        self.body.activate()
        self._adjustViewSize()

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
# 多连接控制面板（电学综合系列模块共用：电功率 / 欧姆定律）
#
# 「连接」抽象为可动态增删的单元：默认一个连接单元，点「＋ 添加连接」
# 追加新的，每个单元 = 一路完整的 电压+电流 测量装置（连接方式 / 采样
# 方式 / 电压串口 / 一体固件 / 电流串口 / 图线颜色），独立串口或模拟
# 线程并行采集，换算后的 (时间, 电压, 电流) 经 on_sample 回调交给模块。
# ============================================================

# 预设图线颜色（多路曲线在图表中的区分色，可在单元卡中自行更换）
LINE_COLORS = [
    '#0078d4',  # 蓝
    '#f7630c',  # 橙
    '#107c10',  # 绿
    '#d13438',  # 红
    '#825a2c',  # 棕
    '#7030a0',  # 紫
    '#00b294',  # 青
    '#e3008c',  # 品红
]


def _pick_line_color(index):
    """按序号循环取图线颜色。"""
    return LINE_COLORS[index % len(LINE_COLORS)]












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
    # 双向语义色映射：light ↔ dark 成对替换，覆盖 _theme_colors() 全部主色
    # 及历史硬编码别名（#444/#888 等）。替换按键长降序，避免 #444 抢先
    # 命中 #444444 之类的子串。
    light_to_dark = {
        '#f3f3f3': '#202020',   # page_bg
        '#ffffff': '#2d2d2d',   # card_bg / input_bg
        '#e5e5e5': '#404040',   # card_border
        '#f6f6f6': '#3d3d3d',   # content_bg
        '#1a1a1a': '#ffffff',   # text_primary
        '#444444': '#c0c0c0',   # text_secondary
        '#0078d4': '#60cdff',   # accent
        '#106ebe': '#7dd8ff',   # accent_hover
        '#f0f0f0': '#3d3d3d',   # hover_bg
        '#ebebeb': '#3a3a3a',   # separator
        # 历史硬编码别名 → 暗色语义色
        '#1A1A1A': c['text_primary'],
        '#444':    c['text_secondary'],
        '#666666': c['text_secondary'],
        '#888888': c['text_hint'],
        '#888':    c['text_hint'],
        '#999999': c['text_hint'],
        '#999':    c['text_hint'],
        '#fafafa': c['card_bg'],
        '#f5f5f5': c['card_bg'],
        '#ececec': c['card_border'],
        '#d0d0d0': c['card_border'],
        '#b0b0b0': c['card_border'],
        '#333333': c['text_secondary'],
        '#333':    c['text_secondary'],
    }
    dark_to_light = {
        '#202020': '#f3f3f3',   # page_bg
        '#2d2d2d': '#ffffff',   # card_bg / input_bg
        '#404040': '#e5e5e5',   # card_border
        '#3d3d3d': '#f6f6f6',   # content_bg
        '#ffffff': '#1a1a1a',   # text_primary（仅在深色 QSS 上反向，安全）
        '#c0c0c0': '#444444',   # text_secondary
        '#60cdff': '#0078d4',   # accent
        '#7dd8ff': '#106ebe',   # accent_hover
        '#454545': '#e5e5e5',   # pressed_bg
        '#3a3a3a': '#ebebeb',   # separator
    }
    # 深色特征色：浅色 QSS 几乎不会出现的暗色背景/边框值，
    # 用于判断缓存的原始 QSS 是否诞生于深色主题。
    dark_features = ('#202020', '#2d2d2d', '#404040', '#3d3d3d',
                     '#454545', '#3a3a3a', '#60cdff', '#7dd8ff')

    def _looks_dark(qss):
        low = qss.lower()
        return any(k in low for k in dark_features)

    def _remap(qss, mapping):
        # 两阶段替换：先统一换成占位符，再换成目标色。目标色可能恰好是
        # 另一条规则的源色（如 #ffffff ↔ #2d2d2d 互映射），单阶段顺序
        # 替换会把刚换好的颜色再次改掉（实测背景无法还原浅色）。
        keys = sorted(mapping, key=len, reverse=True)
        for i, old in enumerate(keys):
            qss = qss.replace(old, "__THEME_%d__" % i)
        for i, old in enumerate(keys):
            qss = qss.replace("__THEME_%d__" % i, mapping[old])
        return qss

    def _derive_qss(orig_qss: str) -> str:
        """从原始 QSS 派生当前主题的 QSS（双向、与创建时主题无关）。

        旧实现切亮色时直接回 orig，导致「深色主题下创建的模块永远
        无法变浅」（issue #13）。现在按 orig 的实际配色选择方向：
        已是目标配色则原样使用，否则按映射表整体换算。
        """
        if not orig_qss:
            return orig_qss
        if dark:
            return orig_qss if _looks_dark(orig_qss) else _remap(orig_qss, light_to_dark)
        return _remap(orig_qss, dark_to_light) if _looks_dark(orig_qss) else orig_qss

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

    # 4. 重刷「开始/停止采集」按钮配色（播放器风格，主题切换后自动跟随）
    #    按钮带 update_collect_btn 打的 _is_collect_btn 标记才处理
    try:
        from PySide6.QtWidgets import QPushButton as _QPButton
        for btn in widget.findChildren(_QPButton):
            if btn.property('_is_collect_btn'):
                update_collect_btn(btn, bool(btn.property('_is_collecting')))
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
    （如 serial_panel 等未设 objectName 的 QWidget）继承
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


# ============================================================
# 采集按钮统一样式（播放器风格：开始 ▶ 主题色底白字 / 停止 ⏸ 白底）
# 所有传感器模块的「开始/停止采集」按钮统一走本函数切换
# ============================================================
ACTION_BUTTON_WIDTH = 120  # 操作按钮统一紧凑宽度，便于多个按钮一行放下
# 注意：collect_btn（开始/停止采集）不设固定宽度——qfluentwidgets 自绘
# 图标位置按 minimumSizeHint 推算，固定宽度会把图标推向文字造成重叠；
# 保持自适应宽度即 Fluent 官方「▶ 图标 + 36px 左留白」的布局。


def set_action_button_width(btn, width=ACTION_BUTTON_WIDTH):
    """操作按钮统一紧凑宽度（保存/清除/校准等无图标按钮，一行放下）。"""
    btn.setFixedWidth(width)
    return btn


def update_collect_btn(btn, collecting):
    """「开始/停止采集」按钮的播放器风格状态刷新。

    Args:
        btn: 采集按钮（collect_btn / 全屏浮动栏按钮共用）
        collecting: True=采集中（显示 ⏸ 停止采集，白底）；
                    False=未采集（显示 ▶ 开始采集，主题色底白字）

    样式颜色取自 core._theme_colors()（当前亮/暗主题）；
    按钮会打上 `_is_collect_btn`/`_is_collecting` 属性标记，
    apply_module_theme() 主题切换时会自动重刷，无需各模块处理。
    """
    from qfluentwidgets import FluentIcon as _FIF
    btn.setText("停止采集" if collecting else "开始采集")
    btn.setIcon(_FIF.PAUSE if collecting else _FIF.PLAY)
    btn.setProperty('_is_collect_btn', True)
    btn.setProperty('_is_collecting', bool(collecting))
    c = _theme_colors()
    if collecting:
        # 采集中 → 停止：白底（暗色为深灰底）+ 正文色 + 边框
        if isDarkTheme():
            bg, fg, bd, hov = (c['content_bg'], c['text_primary'],
                               c['card_border'], c['hover_bg'])
        else:
            bg, fg, bd, hov = ('#ffffff', '#1a1a1a', '#d0d0d0', '#f5f5f5')
        qss = (
            f"QPushButton {{ background-color: {bg}; color: {fg};"
            f" border: 1px solid {bd}; border-radius: 6px;"
            # 左侧 36px 与库内规则一致：qfluentwidgets 自绘图标占位
            " padding: 0 14px 0 36px; }"
            f" QPushButton:hover {{ background-color: {hov}; }}"
            f" QPushButton:disabled {{ background-color: {bg};"
            " color: #888888; }"
        )
    else:
        # 未采集 → 开始：主题色底 + 白字（Primary 视觉）
        qss = (
            f"QPushButton {{ background-color: {c['accent']}; color: #ffffff;"
            " border: none; border-radius: 6px;"
            " padding: 0 14px 0 36px; }"
            f" QPushButton:hover {{ background-color: {c['accent_hover']}; }}"
            " QPushButton:disabled { background-color: #888888;"
            " color: #dddddd; }"
        )
    btn.setStyleSheet(qss)


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
    模式单选实时切换输入行；单点模式额外显示「理论斜率」（mV/pH，
    默认 -280 = SEN0161 放大板等效斜率，可按电极/放大板实测值修改），
    确定前做 pH / ADC / 理论斜率输入校验。
    API 与旧 CalibrationDialog 兼容（exec 返回 QDialog.Accepted = 1）。
    """

    def __init__(self, calibration_points, parent=None, theoretical_slope=None):
        super().__init__(parent)
        points = list(calibration_points) if calibration_points else []
        self.calibration_points = points
        self.calibration_mode = len(points) if points else 2
        self.point_widgets = []
        # 单点校准的理论斜率（mV/pH，pH 升电压降为负）；None 时显示默认 -280
        self._initial_slope = theoretical_slope
        self._parsed_slope = None
        self.slope_row = None
        self.slope_input = None

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
            (1, "单点校准", "仅一个参考点，配下方可调理论斜率（默认 -280mV/pH）"),
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

        # 单点校准的「理论斜率」输入（仅模式 1 显示）：mV/pH。
        # 指 SEN0161 放大板 PO 端口等效斜率（含板上增益，约 -280mV/pH；
        # 电极裸 Nernst 斜率约 -59.16mV/pH，未含放大幅度），pH 升电压降为负；
        # 可按电极/放大板实测斜率修改（换电极或老化后），换算见模块的
        # calculate_calibration_coefficients（mV/pH → ADC 域）
        self.slope_row = QWidget()
        slope_lay = QHBoxLayout(self.slope_row)
        slope_lay.setContentsMargins(0, 0, 0, 0)
        slope_lay.setSpacing(10)
        slope_lay.addWidget(BodyLabel("理论斜率"))
        self.slope_input = LineEdit()
        self.slope_input.setFixedWidth(72)
        self.slope_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.slope_input.setText(f"{float(self._initial_slope):g}"
                                 if self._initial_slope else "-280")
        self.slope_input.setToolTip(
            "单点校准的电极理论斜率（mV/pH）：pH 升高 1 电压下降即为负值，\n"
            "SEN0161 放大板等效典型值约 -280；也可按实测（两点缓冲液）填实际斜率")
        slope_lay.addWidget(self.slope_input)
        slope_lay.addWidget(CaptionLabel("mV/pH（pH 升电压降，典型 -280）"), 1)
        view.addWidget(self.slope_row)

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

        # 理论斜率仅单点校准需要（两点/三点由拟合直接得到斜率）
        if self.slope_row is not None:
            self.slope_row.setVisible(self.calibration_mode == 1)

    def _on_mode_toggled(self):
        rb = self.sender()
        if rb is not None and rb.isChecked():
            self.calibration_mode = rb.property("mode")
            self._create_point_inputs()
            self._error_label.hide()

    def validate(self):
        """确定前校验输入：pH 须为 0~14 数值、ADC 须为数值、
        单点模式的理论斜率须为非零数值；非法时提示并阻止关闭。"""
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
        if self.calibration_mode == 1:
            slope_text = (self.slope_input.text().strip()
                          if self.slope_input is not None else "")
            try:
                slope_val = float(slope_text)
            except ValueError:
                self._fail(f"理论斜率「{slope_text}」不是有效数字（mV/pH）")
                return False
            if slope_val == 0:
                self._fail("理论斜率不能为 0（无法换算 pH）")
                return False
            if not (-1000.0 <= slope_val <= 1000.0):
                self._fail("理论斜率超出合理范围（-1000~1000 mV/pH，请检查符号/数值）")
                return False
            self._parsed_slope = slope_val
        else:
            self._parsed_slope = None
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

    def get_theoretical_slope(self):
        """单点校准使用的理论斜率（mV/pH）。

        模式 1 返回校验后的输入值；其余模式返回初始值（与本次校准无关）。
        """
        if self.calibration_mode == 1 and self._parsed_slope is not None:
            return self._parsed_slope
        return self._initial_slope


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


def sync_kernel_channel_row(refs, channel):
    """把内核通道状态同步回一行连接控件。

    HTTP / MCP 直接修改内核后，内核发布 channels_changed；View 在 GUI 线程
    消费事件时调用本函数，保证采样频率、连接方式、端口、连接按钮与内核一致。
    只同步已存在的控件，不创建/访问任何新的 QWidget。
    """
    if not refs or channel is None:
        return
    combo = refs.get('sample_rate_combo')
    if combo is not None:
        combo.blockSignals(True)
        try:
            combo.setSampleInterval(channel.sample_interval_ms)
        finally:
            combo.blockSignals(False)

    mode_combo = refs.get('mode_combo')
    if mode_combo is not None:
        target = 1 if getattr(channel, 'mode', 'serial') == 'simulator' else 0
        if mode_combo.count() > target:
            mode_combo.blockSignals(True)
            mode_combo.setCurrentIndex(target)
            mode_combo.blockSignals(False)

    port_combo = refs.get('port_combo')
    port = getattr(channel, 'port', '') or ''
    if port_combo is not None and port:
        idx = port_combo.findText(port)
        if idx >= 0:
            port_combo.blockSignals(True)
            port_combo.setCurrentIndex(idx)
            port_combo.blockSignals(False)

    btn = refs.get('connect_btn')
    if btn is not None:
        connected = bool(getattr(channel, 'connected', False))
        btn.setText("断开" if connected else "连接")

    name_edit = refs.get('name_edit')
    if name_edit is not None and name_edit.hasFocus():
        name_edit = None
    if name_edit is not None and name_edit.text() != channel.name:
        name_edit.blockSignals(True)
        name_edit.setText(channel.name or '')
        name_edit.blockSignals(False)

    card = refs.get('card')
    if card is not None:
        # FluentCard 的标题在内部 HeaderSettingCard 上（card.card.titleLabel）
        try:
            card.card.setTitle(channel.name)
        except Exception:
            pass

    color_combo = refs.get('color_combo')
    if color_combo is not None:
        idx = color_combo.findData(channel.color)
        if idx >= 0 and color_combo.currentIndex() != idx:
            color_combo.blockSignals(True)
            color_combo.setCurrentIndex(idx)
            color_combo.blockSignals(False)


def sync_kernel_channels(view):
    """按内核通道列表增删 View 的连接卡/实时行。

    桌面 UI 原本只在本地 add_channel 时创建卡片；网页端直接调内核新增通道后，
    View 必须在这里补建/移除对应控件，才能真正与内核保持一致。
    """
    kernel = getattr(view, 'kernel', None)
    if kernel is None:
        return
    rows = getattr(view, '_rows', None)
    live_rows = getattr(view, '_live_rows', None)
    if rows is None or live_rows is None:
        return

    current_ids = {ch.id for ch in kernel.channels}

    # 删除内核里已经不存在的通道控件
    for cid in list(rows.keys()):
        if cid in current_ids:
            continue
        refs = rows.pop(cid, None) or {}
        card = refs.get('card')
        layout = getattr(view, 'channels_layout', None)
        if card is not None and layout is not None:
            layout.removeWidget(card)
            card.deleteLater()
        live = live_rows.pop(cid, None)
        live_layout = getattr(view, '_live_layout', None)
        if live is not None and live_layout is not None:
            live_layout.removeWidget(live['row'])
            live['row'].deleteLater()

    # 补建缺失通道，并同步已有通道的控件状态
    for ch in kernel.channels:
        if ch.id not in rows:
            view._build_channel_card(ch)
            view._build_live_row(ch)
        sync_kernel_channel_row(rows.get(ch.id), ch)
        apply_mode = getattr(view, '_apply_channel_mode_visibility', None)
        if callable(apply_mode):
            try:
                apply_mode(ch)
            except Exception:
                pass
        live = live_rows.get(ch.id)
        if live:
            label = live.get('name_label')
            if label is not None and label.text() != ch.name:
                label.setText(ch.name)
        # 各模块可选钩子：把通道颜色同步到实时行的大字标签
        apply_color = getattr(view, '_apply_channel_color', None)
        if callable(apply_color):
            try:
                apply_color(ch)
            except Exception:
                pass

    for name in (
        '_refresh_chart_visibility_row', '_update_delete_btns',
        '_sync_compat_aliases', '_refresh_active_channel_combo',
        '_refresh_summary_text', '_refresh_data_card_height',
        '_sync_conn_card_height',
    ):
        fn = getattr(view, name, None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass


# ============================================================
# 多通道连接面板公共实现（六个传感器 View 共用）
# ============================================================
#: 颜色下拉中「自定义…」项的 userData 标记（选中后弹 Fluent 取色对话框）
CUSTOM_COLOR_KEY = '__custom__'


def make_color_icon(hex_color, size=24):
    """生成实心圆色块 QIcon（颜色下拉项的预览图标）。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(hex_color))
    p.drawEllipse(2, 2, size - 4, size - 4)
    p.end()
    return QIcon(pm)


class FlowFixedWidth(QWidget):
    """FlowLayout 按控件 sizeHint() 排版，setFixedWidth 不会改变排版宽度。

    该容器把内部控件宽度锁定为 width，并让 sizeHint 返回这个宽度，
    使 FlowLayout 按紧凑宽度排列（参数行数字框用）。
    """

    def __init__(self, inner, width, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(inner)
        self._width = int(width)

    def sizeHint(self):
        return QSize(self._width, super().sizeHint().height())


class FlowWrapBox(QWidget):
    """承载 FlowLayout 的容器：按可用宽度返回换行后的真实高度。

    FlowLayout.sizeHint() 只返回「单项最大尺寸」，不含换行后的总高度；
    QWidget 默认的 heightForWidth 也不会委托给布局。因此首次显示时父布局
    按过小的高度分配，勾选行被压扁（折叠再展开才恢复）。这里显式实现
    heightForWidth，让父布局按实际宽度算高度。
    """

    def __init__(self, flow, parent=None):
        super().__init__(parent)
        self._flow = flow
        self.setLayout(flow)
        sp = self.sizePolicy()
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        if width <= 0:
            width = 600
        return self._flow.heightForWidth(width)

    def sizeHint(self):
        width = self.width() if self.width() > 0 else 600
        return QSize(self._flow.sizeHint().width(), self.heightForWidth(width))

    def minimumSizeHint(self):
        m = self._flow.minimumSize()
        return QSize(m.width(), m.height())


class ChannelPanelMixin:
    """多通道连接卡的公共 UI 行为。

    宿主 View 在 ``__init__`` 中准备好这些属性后即可获得完整的通道增删、
    子卡、实时行、端口刷新、显示勾选、连接/断开与采集按钮联动能力：

        kernel / channels / _rows / _live_rows / _live_layout
        channels_layout / channels_container / card_conn / card_data
        _visibility_flow / _visibility_container / _collecting
        collect_btn / float_collect_btn / _event_timer / _events

    模块只实现物理差异钩子（均非必需）：
        _channel_extra_params()        新建通道时传给内核的额外参数
        _live_row_spec(ch)             实时行显示字段
        _sync_active_channel_controls(ch)  参数卡「当前连接」下拉联动
        _on_channel_connection_changed(ch, connected)  单路连接后的模块按钮/文案
        _on_connection_state_changed() 批量连接/断开后的模块按钮状态
        _after_channels_built()        通道重建后的模块级收尾
    """

    # ---------------- 子类钩子 ----------------
    def _channel_extra_params(self):
        """新建通道时传给 kernel.add_channel 的额外关键字。"""
        return {}

    def _live_row_spec(self, ch):
        """一路实时行的显示描述：大字标签 + 若干次要标签。"""
        return {
            'big_key': 'value_label',
            'big_text': '--.-',
            'secondary': [('raw_label', f'{ch.name} ADC: ------')],
        }

    def _sync_active_channel_controls(self, ch):
        """参数卡「当前连接」下拉切换后的控件刷新（模块按需覆盖）。"""
        pass

    def _on_channel_connection_changed(self, ch, connected):
        """单路连接/断开后的模块级联动（去皮按钮、实时行文案等）。"""
        pass

    def _on_connection_state_changed(self):
        """批量连接/断开后的模块级按钮状态。"""
        pass

    def _after_channels_built(self):
        """按内核通道重建 UI 后的模块级收尾。"""
        pass

    # ---------------- 配置兼容 ----------------
    def load_config(self):
        return self.kernel.config

    def save_config(self):
        return self.kernel.save_config()

    # ---------------- 通道增删 ----------------
    def _make_channel(self, color=None, mode='serial', port='', name=None,
                      sample_interval_ms=None, **params):
        """创建内核通道，并为它建立对应的 UI 子卡/实时行。"""
        extra = self._channel_extra_params()
        extra.update(params)
        ch = self.kernel.add_channel(
            color=color, mode=mode, port=port, name=name,
            sample_interval_ms=sample_interval_ms, **extra)
        self._build_channel_card(ch)
        self._build_live_row(ch)
        self._refresh_chart_visibility_row()
        self._update_delete_btns()
        self._sync_conn_card_height()
        return ch

    def add_channel(self):
        """「新建连接」按钮：增加一路连接（缺 pyserial 时用模拟器）。"""
        self._make_channel(mode='serial' if SERIAL_AVAILABLE else 'simulator')
        self._sync_compat_aliases()
        self._refresh_active_channel_combo()

    def _build_channels_from_kernel(self):
        """按内核已有通道重建 UI 行（内核负责配置恢复）。"""
        for ch in self.channels:
            self._build_channel_card(ch)
            self._build_live_row(ch)
        self._refresh_active_channel_combo()
        self._after_channels_built()
        self._refresh_chart_visibility_row()
        self._update_delete_btns()
        self._sync_compat_aliases()
        self._refresh_summary_text()

    def _delete_channel(self, ch):
        """删除一路连接（正在连接的通道须先断开；至少保留一路）。"""
        if getattr(ch, 'connected', False):
            fluent_message_box(self, "提示", f"{ch.name} 正在连接，请先断开再删除")
            return
        refs = self._rows.pop(ch.id, None)
        if refs:
            self.channels_layout.removeWidget(refs['card'])
            refs['card'].deleteLater()
        self.kernel.remove_channel(ch.id)
        self._remove_live_row(ch)
        self._refresh_chart_visibility_row()
        self._update_delete_btns()
        self._sync_compat_aliases()
        self._refresh_active_channel_combo()
        self._sync_conn_card_height()

    # ---------------- 实时行 ----------------
    def _build_live_row(self, ch):
        """为一路通道创建实时明细行：名称 + 大字值 + 若干次要字段。"""
        spec = self._live_row_spec(ch)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(16)

        name_label = CaptionLabel(ch.name)
        h.addWidget(name_label)

        big_key = spec.get('big_key', 'value_label')
        big_label = BodyLabel(spec.get('big_text', '--.-'))
        big_label.setFont(QFont("Cascadia Code", 20, QFont.Weight.Bold))
        big_label.setStyleSheet(f"color: {ch.color};")
        h.addWidget(big_label)
        h.addStretch()

        refs = {'row': row, 'name_label': name_label, 'big_key': big_key,
                big_key: big_label}
        for key, text in spec.get('secondary', []):
            label = CaptionLabel(text)
            label.setFont(QFont("Cascadia Code", 11))
            h.addWidget(label)
            refs[key] = label

        self._live_layout.addWidget(row)
        self._live_rows[ch.id] = refs
        self._refresh_data_card_height()

    def _remove_live_row(self, ch):
        """删除通道的实时明细行（删除通道时调用）。"""
        refs = self._live_rows.pop(ch.id, None)
        if refs:
            self._live_layout.removeWidget(refs['row'])
            refs['row'].deleteLater()
        self._refresh_summary_text()
        self._refresh_data_card_height()

    def _refresh_data_card_height(self):
        """实时数据卡行数变化后重算高度。"""
        card = getattr(self, 'card_data', None)
        if card is not None:
            live = getattr(self, '_live_layout', None)
            if live is not None:
                live.invalidate()
                live.activate()
            card.refresh_height()
            QTimer.singleShot(0, self._refresh_data_card_height_deferred)

    def _refresh_data_card_height_deferred(self):
        card = getattr(self, 'card_data', None)
        if card is not None:
            card.refresh_height()

    # ---------------- 图表显示勾选 ----------------
    def _refresh_chart_visibility_row(self):
        """重建图表卡顶部的通道显示勾选行（通道增删/改名后调用）。"""
        while self._visibility_flow.count():
            item = self._visibility_flow.takeAt(0)
            w = item if isinstance(item, QWidget) else (
                item.widget() if item else None)
            if w is not None:
                w.hide()
                w.deleteLater()
        for ch in self.channels:
            cb = CheckBox(ch.name)
            cb.setChecked(ch.visible)
            cb.setToolTip(f"勾选后「{ch.name}」的曲线显示在图表上，取消则隐藏\n"
                          f"（仅影响图表显示，采集/统计/保存不受影响）")
            cb.toggled.connect(
                lambda on, c=ch: self._on_channel_visible_toggled(c, on))
            self._visibility_flow.addWidget(cb)
            cb.show()
        self._visibility_container.setVisible(bool(self.channels))
        self._visibility_flow.invalidate()
        self._visibility_flow.setGeometry(
            self._visibility_container.contentsRect())
        self._visibility_container.updateGeometry()

    def _on_channel_visible_toggled(self, ch, checked):
        ch.visible = bool(checked)
        self.kernel.notify_change(ch.id)
        self.update_chart()

    # ---------------- 卡片高度 / 按钮状态 ----------------
    def _sync_conn_card_height(self):
        """连接控制卡高度随子卡实际高度自适应。"""
        try:
            card = self.card_conn
            h = card.body.sizeHint().height()
            cont = self.channels_container
            cards = [self._rows[ch.id]['card']
                     for ch in self.channels if ch.id in self._rows]
            if cont is not None and cards:
                actual = sum(c.height() for c in cards) + 8 * (len(cards) - 1)
                h = h - cont.sizeHint().height() + actual
            h = max(int(h), 1)
            card.spaceWidget.setFixedHeight(h)
            if card.isExpand:
                card.setFixedHeight(card.card.height() + h)
        except Exception:
            pass

    def _update_delete_btns(self):
        """仅剩一路时禁用其删除按钮（至少保留一路连接行）。"""
        single = len(self.channels) <= 1
        for ch in self.channels:
            refs = self._rows.get(ch.id)
            if refs:
                refs['delete_btn'].setEnabled(not single)

    def _sync_compat_aliases(self):
        """KernelRegistry / 网页端兼容：对外仍暴露单一 mode_combo/port_combo。"""
        if self.channels:
            refs = self._rows[self.channels[0].id]
            self.mode_combo = refs['mode_combo']
            self.port_combo = refs['port_combo']

    # ---------------- 连接子卡 ----------------
    def _build_channel_card(self, ch):
        """为通道创建一张连接子卡：名称 / 颜色 / 删除 + 连接参数。"""
        card = FluentCard(ch.default_name, None, True, self)

        name_edit = LineEdit(card)
        name_edit.setText(ch.name)
        name_edit.setPlaceholderText("自定义名称")
        name_edit.setFixedWidth(112)
        name_edit.setToolTip("图表图例/实时数据中显示的名称（留空恢复默认「通道N」）")
        name_edit.editingFinished.connect(
            lambda c=ch, e=name_edit: self._on_channel_name_edited(c, e.text()))
        card.add_header_widget(name_edit)

        color_combo = ComboBox(card)
        color_combo.setMinimumWidth(96)
        color_combo.setToolTip("该连接的图线颜色")
        color_combo.currentIndexChanged.connect(
            lambda i, c=ch: self._on_channel_color_changed(c, i))
        card.add_header_widget(color_combo)

        delete_btn = ToolButton(FluentIcon.DELETE, card)
        delete_btn.setFixedSize(28, 28)
        delete_btn.setToolTip("删除这一路连接（需先断开）")
        delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_btn.clicked.connect(lambda _=False, c=ch: self._delete_channel(c))
        card.add_header_widget(delete_btn)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.addWidget(BodyLabel("连接方式"))
        mode_combo = ComboBox()
        mode_combo.addItems(["有线串口", "模拟器"])
        mode_combo.setCurrentIndex(1 if ch.mode == 'simulator' else 0)
        mode_combo.currentIndexChanged.connect(
            lambda i, c=ch: self._on_channel_mode_changed(c, i))
        row1.addWidget(mode_combo)

        port_combo = ComboBox()
        port_combo.setMinimumWidth(80)
        self._fill_channel_ports(ch, port_combo)
        port_combo.currentTextChanged.connect(
            lambda t, c=ch: self._on_channel_port_changed(c, t))
        port_label = BodyLabel("串口")
        row1.addWidget(port_label)
        row1.addWidget(port_combo)

        refresh_btn = PushButton("刷新")
        refresh_btn.setFixedHeight(30)
        refresh_btn.setToolTip("重新枚举本路的串口列表")
        refresh_btn.clicked.connect(
            lambda _=False, c=ch: self._refresh_channel_ports(c))
        row1.addWidget(refresh_btn)

        row1.addWidget(BodyLabel("采样频率"))
        sample_rate_combo = SampleRateComboBox()
        sample_rate_combo.setSampleInterval(ch.sample_interval_ms)
        sample_rate_combo.setMaximumWidth(110)
        sample_rate_combo.sampleIntervalChanged.connect(
            lambda ms, c=ch: self._on_channel_sample_interval_changed(c, ms))
        row1.addWidget(sample_rate_combo)

        row1.addStretch()

        connect_btn = PrimaryPushButton("连接")
        connect_btn.setFixedHeight(30)
        connect_btn.clicked.connect(
            lambda _=False, c=ch: self._toggle_channel_connection(c))
        row1.addWidget(connect_btn)
        w1 = QWidget()
        w1.setLayout(row1)
        card.add_widget(w1)

        card.expandAni.valueChanged.connect(self._sync_conn_card_height)
        card.expandAni.finished.connect(self._sync_conn_card_height)

        self.channels_layout.addWidget(card)
        self._rows[ch.id] = {
            'card': card, 'name_edit': name_edit, 'color_combo': color_combo,
            'delete_btn': delete_btn, 'mode_combo': mode_combo,
            'port_combo': port_combo, 'port_label': port_label,
            'refresh_btn': refresh_btn,
            'connect_btn': connect_btn, 'sample_rate_combo': sample_rate_combo,
        }
        self._init_channel_color_combo(ch)
        self._apply_channel_mode_visibility(ch)

    # ---------------- 颜色 / 名称 ----------------
    def _init_channel_color_combo(self, ch):
        """（重建）填充颜色下拉：预设色 + 已存自定义色 + 「自定义…」项。"""
        refs = self._rows.get(ch.id)
        if not refs:
            return
        combo = refs['color_combo']
        combo.blockSignals(True)
        combo.clear()
        for c in CHANNEL_COLORS:
            combo.addItem(c, make_color_icon(c), userData=c)
        if ch.color and combo.findData(ch.color) < 0:
            combo.addItem(ch.color, make_color_icon(ch.color), userData=ch.color)
        combo.addItem("自定义…", QIcon(), userData=CUSTOM_COLOR_KEY)
        idx = combo.findData(ch.color)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    def _apply_channel_color(self, ch):
        """把通道曲线颜色同步到该路实时行的大字标签。"""
        live = self._live_rows.get(ch.id)
        if live:
            key = live.get('big_key')
            label = live.get(key) if key else None
            if label is not None:
                label.setStyleSheet(f"color: {ch.color};")

    def _on_channel_color_changed(self, ch, index):
        """颜色下拉选中：预设色直接生效；「自定义…」弹 Fluent 取色对话框。"""
        refs = self._rows.get(ch.id)
        if not refs:
            return
        combo = refs['color_combo']
        data = combo.itemData(index)
        if data == CUSTOM_COLOR_KEY:
            state = {'ok': False, 'color': None}
            dialog = ColorDialog(QColor(ch.color),
                                 f"选择 {ch.name} 的曲线颜色", self)
            dialog.colorChanged.connect(
                lambda c: state.__setitem__('color', c))
            dialog.yesButton.clicked.connect(
                lambda: state.__setitem__('ok', True))
            dialog.exec()
            color = state['color'] or getattr(dialog, 'color', None)
            if not (state['ok'] and color is not None and color.isValid()):
                self._init_channel_color_combo(ch)
                return
            ch.color = color.name()
            combo.blockSignals(True)
            combo.setItemText(index, ch.color)
            combo.setItemIcon(index, make_color_icon(ch.color))
            combo.setItemData(index, ch.color)
            combo.addItem("自定义…", QIcon(), userData=CUSTOM_COLOR_KEY)
            combo.blockSignals(False)
        else:
            ch.color = data
        self.kernel.notify_change(ch.id)
        self.update_chart()

    def _on_channel_name_edited(self, ch, text):
        """名称编辑完成：写回通道名（留空恢复默认「通道N」）。"""
        t = text.strip()
        ch.name = t or ch.default_name
        refs = self._rows.get(ch.id)
        if refs:
            try:
                refs['card'].card.setTitle(ch.name)
            except Exception:
                pass
        live = self._live_rows.get(ch.id)
        if live:
            live['name_label'].setText(ch.name)
            # 次要标签重新按新名称生成（原始 ADC / 回波等前缀含通道名）
            for key, label_text in self._live_row_spec(ch).get('secondary', []):
                if key in live:
                    live[key].setText(label_text)
        self._refresh_active_channel_combo()
        self._refresh_chart_visibility_row()
        self.kernel.notify_change(ch.id)
        self.update_chart()

    # ---------------- 串口 / 模式 / 采样频率 ----------------
    def _fill_channel_ports(self, ch, combo):
        """重填串口列表：保留已保存的端口，不静默改选其它设备。"""
        want = (ch.port or '').strip()
        combo.blockSignals(True)
        try:
            combo.clear()
            ports = list_serial_ports()
            for device, _desc in ports:
                combo.addItem(device)
            if not ports:
                combo.addItem("未安装 pyserial" if not SERIAL_AVAILABLE
                              else "无可用串口")
            if want:
                idx = combo.findText(want)
                if idx < 0:
                    # 已保存端口当前没扫描到：保留并选中，避免刷新后
                    # 悄悄换成第一个可用设备（插回即可直接连接）
                    combo.addItem(want)
                    idx = combo.findText(want)
                combo.setCurrentIndex(idx)
            elif combo.count():
                combo.setCurrentIndex(0)
        finally:
            combo.blockSignals(False)

    def _on_channel_port_changed(self, ch, text):
        """用户选择串口：忽略占位项，写回通道并广播（网页端同步）。"""
        t = (text or '').strip()
        if not t or '未安装' in t or '无可用' in t or ch.port == t:
            return
        ch.port = t
        self.kernel.notify_change(ch.id)

    def refresh_ports(self):
        """刷新所有通道的串口列表（网页端 refresh_ports 命令也走这里）。"""
        for ch in self.channels:
            self._refresh_channel_ports(ch)

    def _refresh_channel_ports(self, ch):
        refs = self._rows.get(ch.id)
        if refs:
            self._fill_channel_ports(ch, refs['port_combo'])

    def _on_channel_mode_changed(self, ch, index):
        ch.mode = 'simulator' if index == 1 else 'serial'
        self._apply_channel_mode_visibility(ch)
        self.kernel.notify_change(ch.id)

    def _apply_channel_mode_visibility(self, ch):
        """模拟器模式下隐藏本路的串口标签/下拉与刷新按钮。"""
        refs = self._rows.get(ch.id)
        if refs:
            is_sim = ch.mode == 'simulator'
            refs['port_label'].setVisible(not is_sim)
            refs['port_combo'].setVisible(not is_sim)
            refs['refresh_btn'].setVisible(not is_sim)
            try:
                refs['card']._adjustViewSize()
            except Exception:
                pass
            self._sync_conn_card_height()

    def _on_channel_sample_interval_changed(self, ch, interval_ms):
        """本路采样频率改变：更新该路间隔并保存配置。"""
        ch.sample_interval_ms = interval_ms
        if self.channels and ch is self.channels[0]:
            self.sample_interval_ms = interval_ms
            self.kernel.sample_interval_ms = interval_ms
        self.kernel.notify_change(ch.id)

    # ---------------- 单路连接 / 断开 ----------------
    def _toggle_channel_connection(self, ch):
        if getattr(ch, 'connected', False):
            self._disconnect_channel(ch)
        else:
            self._connect_channel(ch)

    def _connect_channel(self, ch):
        """连接单路：串口或模拟器（其余通道不受影响）。"""
        refs = self._rows.get(ch.id)
        if ch.mode == 'serial':
            if not SERIAL_AVAILABLE:
                fluent_message_box(self, "提示", serial_unavailable_hint())
                return
            port = refs['port_combo'].currentText() if refs else ch.port
            if not port or "未安装" in port or "无可用" in port:
                fluent_message_box(self, "错误", f"{ch.name}: 请选择串口")
                return
            ch.port = port
        res = self.kernel.connect(ch.id)
        if not res.get('ok'):
            fluent_message_box(self, "连接错误",
                               res.get('message', f'{ch.name} 连接失败'))
            return
        if refs:
            refs['connect_btn'].setText("断开")
        log.info("%s 已连接（%s）", ch.name,
                 '模拟器' if ch.mode == 'simulator' else ch.port)
        self._set_collect_enabled(True)
        self._on_channel_connection_changed(ch, True)

    def _disconnect_channel(self, ch):
        """断开单路（其余通道不受影响）。"""
        self.kernel.disconnect(ch.id)
        refs = self._rows.get(ch.id)
        if refs:
            refs['connect_btn'].setText("连接")
        log.info("%s 已断开", ch.name)
        self._on_channel_connection_changed(ch, False)
        self._refresh_summary_text()
        self._set_collect_enabled(self.kernel.connected_any())

    def connect_device(self):
        """连接全部未连接的通道（网页端 connect=true 也走这里）。"""
        self.kernel.connect_all()
        for ch in self.channels:
            refs = self._rows.get(ch.id)
            if refs:
                refs['connect_btn'].setText(
                    "断开" if getattr(ch, 'connected', False) else "连接")
        self._set_collect_enabled(self.kernel.connected_any())
        self._on_connection_state_changed()

    def disconnect_all(self):
        """断开全部通道（退出清理 / 网页端命令也走这里）。"""
        self.kernel.disconnect_all()
        for ch in self.channels:
            refs = self._rows.get(ch.id)
            if refs:
                refs['connect_btn'].setText("连接")
        self._set_collect_enabled(False)
        self._on_connection_state_changed()

    # ---------------- 「当前连接」下拉 ----------------
    def _active_channel_obj(self):
        """参数卡当前选中的通道对象（无通道/未初始化返回 None）。"""
        combo = getattr(self, '_active_channel_combo', None)
        if combo is None:
            return None
        cid = combo.currentData()
        return next((ch for ch in self.channels if ch.id == cid), None)

    def _refresh_active_channel_combo(self, keep_id=None):
        """通道增删/改名后重建「当前连接」下拉，尽量保住原选中。"""
        combo = getattr(self, '_active_channel_combo', None)
        if combo is None:
            return
        if keep_id is None and combo.count():
            keep_id = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for ch in self.channels:
            combo.addItem(ch.name, userData=ch.id)
        idx = next((i for i in range(combo.count())
                    if combo.itemData(i) == keep_id), 0)
        if combo.count():
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)
        self._sync_active_channel_controls(self._active_channel_obj())

    # ---------------- 采集按钮 / 数据操作 ----------------
    def start_collection(self):
        """开始数据采集（数据清空与时间基准由内核负责）。"""
        self.kernel.start_collection()
        self._apply_started_ui()

    def stop_collection(self):
        """停止数据采集。"""
        self.kernel.stop_collection()
        self._apply_stopped_ui()

    def toggle_collection(self):
        """合并的开始/停止按钮：按当前采集状态切换。"""
        if self._collecting:
            self.stop_collection()
        else:
            self.start_collection()

    def _drain_kernel_events(self):
        """GUI 线程消费内核事件（由 View 的 QTimer 调用）。"""
        for event in self._events.drain(200):
            if event is None:
                return
            self._handle_kernel_event(event)

    # ---------------- 页面骨架（操作按钮 / 全屏浮层 / 定时器） ----------------
    def _build_conn_card(self, layout, add_channel_tooltip):
        """连接控制卡：说明行 + 通道子卡容器 + 新建连接按钮。"""
        content = QWidget()
        card_layout = QVBoxLayout(content)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(10)
        self._conn_card_layout = card_layout

        card_layout.addWidget(CaptionLabel(
            "每路连接可单独选择串口/模拟器与曲线颜色，多路数据同图叠加对比"))

        self.channels_container = QWidget()
        self.channels_layout = QVBoxLayout(self.channels_container)
        self.channels_layout.setContentsMargins(0, 0, 0, 0)
        self.channels_layout.setSpacing(8)
        card_layout.addWidget(self.channels_container)

        self.card_conn = FluentCard("连接控制", content, expanded=True,
                                    icon=FluentIcon.CONNECT)
        self.add_channel_btn = PushButton("＋ 新建连接")
        self.add_channel_btn.setFixedHeight(30)
        self.add_channel_btn.setToolTip(add_channel_tooltip)
        self.add_channel_btn.clicked.connect(lambda: self.add_channel())
        self.card_conn.add_header_widget(self.add_channel_btn)
        self.card_conn.expandAni.finished.connect(self._sync_conn_card_height)
        layout.addWidget(self.card_conn)

    def _build_data_card(self, extra_rows=()):
        """构建实时数据卡（每路一行实时明细 + 统计行），返回卡片控件。

        extra_rows：模块自定义的说明行（如单位提示、速度统计），放在统计行上方。
        """
        content = QWidget()
        content.setObjectName("card")
        content.setStyleSheet(card_style())
        data_layout = QVBoxLayout(content)
        data_layout.setContentsMargins(20, 4, 20, 16)
        data_layout.setSpacing(8)

        self._live_rows = {}
        self._live_container = QWidget()
        self._live_layout = QVBoxLayout(self._live_container)
        self._live_layout.setContentsMargins(0, 0, 0, 0)
        self._live_layout.setSpacing(4)
        data_layout.addWidget(self._live_container)

        for widget in extra_rows:
            data_layout.addWidget(widget)

        self.stats_label = CaptionLabel("暂无数据")
        data_layout.addWidget(self.stats_label)

        self.card_data = FluentCard("实时数据", content, expanded=True,
                                    icon=FluentIcon.HISTORY)
        return self.card_data

    def _build_chart_card(self, layout, title, summary_label, n_plots=1):
        """图表卡：通道勾选行 + 数据记录 + ChartPanel + 全屏浮层。"""
        content = QWidget()
        content.setObjectName("card")
        content.setStyleSheet(card_style())
        chart_layout = QVBoxLayout(content)
        chart_layout.setContentsMargins(20, 4, 20, 16)
        chart_layout.setSpacing(12)

        self._visibility_flow = FlowLayout(isTight=True)
        self._visibility_flow.setHorizontalSpacing(14)
        self._visibility_flow.setVerticalSpacing(4)
        self._visibility_container = FlowWrapBox(self._visibility_flow)
        chart_layout.addWidget(self._visibility_container)

        content_row = QHBoxLayout()
        content_row.setSpacing(16)

        left_col = QVBoxLayout()
        left_col.setSpacing(10)
        self.data_text = ExpandableTextEdit()
        left_col.addWidget(self.data_text)

        self.chart = ChartPanel(n_plots=n_plots)
        self.chart.set_ai_data_provider(self._ai_data)
        left_col.addWidget(self.chart.get_analysis_panel())
        content_row.addLayout(left_col, stretch=0)

        content_row.addWidget(self.chart, stretch=2)
        chart_layout.addLayout(content_row, 1)

        card = CollapsibleCard(title, content, expanded=True, fullscreen=True)
        card.set_chart_min_height(400)
        self._setup_chart_overlay(card, summary_label)
        self.card_chart = card
        layout.addWidget(card)
        return card

    def _setup_chart_overlay(self, card_chart, summary_label):
        """图表卡全屏浮层：数据记录 + 分析面板 + 底部开始/停止按钮。"""
        self.float_collect_btn = PrimaryPushButton("开始采集")
        self.float_collect_btn.setFixedHeight(34)
        update_collect_btn(self.float_collect_btn, False)
        self.float_collect_btn.clicked.connect(self.toggle_collection)
        self.float_collect_btn.setEnabled(False)
        card_chart.set_fullscreen_overlay(
            self.data_text, summary_label,
            extra_widgets=[self.chart.get_analysis_panel()],
            footer_widget=self.float_collect_btn)

    def _build_action_card(self, layout):
        """操作按钮卡：开始/停止、保存数据、清除数据。"""
        content = QWidget()
        content.setObjectName("card")
        content.setStyleSheet(card_style())
        actions_layout = QHBoxLayout(content)
        actions_layout.setContentsMargins(20, 4, 20, 12)
        actions_layout.setSpacing(10)

        self.collect_btn = PrimaryPushButton("开始采集")
        self.collect_btn.setFixedHeight(38)
        update_collect_btn(self.collect_btn, False)
        self.collect_btn.clicked.connect(self.toggle_collection)
        self.collect_btn.setEnabled(False)
        actions_layout.addWidget(self.collect_btn)

        self.save_btn = PushButton("保存数据")
        self.save_btn.setFixedHeight(38)
        set_action_button_width(self.save_btn)
        self.save_btn.clicked.connect(self.save_data)
        self.save_btn.setEnabled(False)
        actions_layout.addWidget(self.save_btn)

        self.clear_btn = PushButton("清除数据")
        self.clear_btn.setFixedHeight(38)
        set_action_button_width(self.clear_btn)
        self.clear_btn.clicked.connect(self.clear_data)
        actions_layout.addWidget(self.clear_btn)

        actions_layout.addStretch()
        layout.addWidget(FluentCard("操作按钮", content, expanded=True,
                                    icon=FluentIcon.PLAY))

    def _finish_page(self, layout, scroll, content, main_layout):
        """收尾：滚动区入页，启动图表刷新与内核事件消费定时器。"""
        layout.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_chart)
        self.timer.start(100)

        self._events = self.kernel.subscribe()
        self._event_timer = QTimer(self)
        self._event_timer.timeout.connect(self._drain_kernel_events)
        self._event_timer.start(50)

    # ---------------- 网页 / HTTP 适配 ----------------
    def _ai_data(self):
        """AI 分析实验数据回调（数据由内核生成，View 只补系统提示词）。"""
        data = self.kernel.ai_data()
        if not data:
            return None
        data = dict(data)
        module = sys.modules.get(type(self).__module__)
        data['system_prompt'] = getattr(module, 'AI_SYSTEM_PROMPT', '')
        return data

    def api_snapshot(self):
        """当前实验数据快照（由内核生成，任意线程可读）。"""
        return self.kernel.snapshot()

    def api_csv(self):
        """HTTP 导出用 CSV（由内核统一生成长表）。"""
        return self.kernel.csv_text()

    def api_actions(self):
        """本模块支持的控制动作（供 KernelRegistry / HTTP 层展示）。"""
        return self.kernel.actions()

    def api_command(self, action, params=None):
        """执行控制动作（由 KernelRegistry 直接调用内核）。"""
        return self.kernel.command(action, params)

    def _set_collect_enabled(self, enabled):
        """连接/断开时同步合并按钮与浮动栏按钮的可用性。"""
        self.collect_btn.setEnabled(enabled)
        self.float_collect_btn.setEnabled(enabled)

    def _refresh_collect_btn(self):
        """合并按钮与浮动栏按钮：文案随采集状态切换。"""
        update_collect_btn(self.collect_btn, self._collecting)
        update_collect_btn(self.float_collect_btn, self._collecting)

    def _total_points(self):
        return sum(len(self.kernel.channel_values(ch)) for ch in self.channels)

    def save_data(self):
        """保存数据到文件（由内核生成 CSV）。"""
        total = self._total_points()
        if total == 0:
            fluent_message_box(self, "警告", "没有数据可保存")
            return
        try:
            filename = self.kernel.export_csv()
            log.info("数据已保存到: %s（%d 点）", filename, total)
            fluent_message_box(self, "成功", f"数据已保存到: {filename}")
        except Exception as e:
            log.error("保存失败: %s", e)
            fluent_message_box(self, "错误", f"保存失败: {e}")

    def clear_data(self):
        """清除数据。"""
        self.kernel.clear_data()
        self._apply_cleared_ui()
        log.info("已清除数据")

    # ---------------- 生命周期 / 主题 ----------------
    def shutdown(self):
        """退出清理：停止事件消费、关闭传输并关闭事件总线。"""
        try:
            self._event_timer.stop()
        except Exception:
            pass
        try:
            self._events.close()
        except Exception:
            pass
        self.kernel.shutdown()

    def showEvent(self, e):
        """首次显示后按子卡真实高度收敛连接控制卡。"""
        super().showEvent(e)
        self._sync_conn_card_height()

    def apply_theme(self, theme):
        """主题切换：刷新本模块内所有与主题相关的硬编码样式。"""
        apply_module_theme(self, theme)
        try:
            from qfluentwidgets import isDarkTheme
            self.chart.apply_chart_theme(isDarkTheme())
        except Exception:
            pass

