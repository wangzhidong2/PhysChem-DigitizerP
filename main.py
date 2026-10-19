#!/usr/bin/env python3
# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

# -*- coding: utf-8 -*-
"""
PhysChem-DigitizerP 主程序

功能：
- 主页（HomePageWidget）
- 侧边栏（SidebarWidget）+ 导航按钮（NavButton）
- 设置（SettingsWidget）
- 动态模块加载器：扫描 sensors/ 目录，importlib 加载各传感器模块

新增传感器模块时无需修改本文件，只需在 sensors/ 下新建子目录并放入
带识别区的 .py 文件即可被自动发现并注册。
"""

import sys
import os
import re
import glob
import webbrowser
import importlib.util
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QStackedWidget, QScrollArea,
    QFileDialog,
)
from PySide6.QtCore import Qt, Signal, QSize, QRect, QTimer, QUrl
from PySide6.QtGui import (QFont, QIcon, QPixmap, QPainter, QColor,
                           QFontMetrics, QGuiApplication, QDesktopServices,
                           QTextDocument)

# FluentWidgets — WinUI3 风格组件库（社区版，GPLv3 + 商业双协议）
# 文档：https://qfluentwidgets.com/
# 导入时它会向 stdout 打印一行 Pro 推广横幅；应用要求控制台默认完全静默
# （运行日志开关关闭时），这里在导入期间临时重定向 stdout 吞掉
import io as _io
import contextlib as _contextlib
with _contextlib.redirect_stdout(_io.StringIO()):
    from qfluentwidgets import (
        FluentWindow, FluentIcon as FIF, NavigationItemPosition,
        Theme, setTheme, PushButton, PrimaryPushButton,
        ComboBox, InfoBar, InfoBarPosition, BodyLabel,
        TitleLabel, SubtitleLabel, CaptionLabel, HyperlinkButton,
        SettingCard, SettingCardGroup, ExpandGroupSettingCard, isDarkTheme,
        SwitchSettingCard, SwitchButton, SpinBox, MessageBox, MessageBoxBase, Dialog,
        qconfig, IndicatorPosition,
        LineEdit,
        CardWidget, IconWidget, PillToolButton, CheckBox,
        AdaptiveFlowLayout, ToolTipFilter,
    )


class ZhSwitchSettingCard(SwitchSettingCard):
    """中文开关设置卡片。

    SwitchSettingCard.setValue 用 self.tr('On'/'Off') 设置开关文字，
    无中文翻译器时回退英文。此处覆写为硬编码中文。
    """

    def setValue(self, isChecked: bool):
        if self.configItem:
            qconfig.set(self.configItem, isChecked)
        self.switchButton.setChecked(isChecked)
        self.switchButton.setText("开" if isChecked else "关")


# 公共模块（与各传感器模块共享）
from core import (
    card_style, primary_btn_style, accent_btn_style,
    patch_combobox_arrow_flip, CollapsibleCard, FluentCard,
    page_bg_style, scroll_area_style, _theme_colors, app_cfg,
    ChartPanel, chart_engine_available, resolve_chart_engine,
    clear_sensor_config, export_sensor_config, import_sensor_config, reset_all_config,
    DEFAULT_THEME_COLOR, system_accent_color, set_app_theme_color,
    get_logger, get_log_file_path, setup_logging,
    set_log_enabled, set_log_level, set_log_max_entries,
    DataService,
    # 应用字体：内嵌 MiSans 注册 / 解析 / 应用 / 系统字体选择器
    EMBEDDED_FONT_FAMILY, load_embedded_font, apply_app_font,
    resolve_app_font_family, available_font_families, FontPickerDialog,
)

log = get_logger("main")


# ============================================================
# 模块图标工具
# ============================================================
def make_text_icon(text: str, size: int = 128) -> QIcon:
    """把识别区里的文字（如 V/F/x/pH/v/A）画成方形 QIcon。

    传感器模块识别区写的是文字图标（# icon: V），
    FluentIcon 枚举里没有对应"电压/电流/pH/力/超声波"的图标，
    所以直接用文字渲染成图标，保留模块化设计。

    Args:
        text: 图标文字（1-3 个字符，如 "V"、"pH"）
        size: 画布像素尺寸（实际显示时按比例缩放）

    Returns:
        QIcon: 带 theme（Normal/Active/Selected）的文字图标
    """
    icon = QIcon()
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)

    # 字号自适应：从大字号起用 QFontMetrics 测量，缩到刚好填满画布（留 8% 边距）。
    # 这样 "V"、"pH"、"x" 都能最大化显示，不会因固定比例而偏小。
    # 之前用 0.55/0.40 固定比例，单字符偏小、多字符更小，实测不够大。
    font = QFont("Segoe UI", int(size * 0.9))
    font.setBold(True)
    margin = int(size * 0.08)  # 上下左右各留 8% 边距
    target = QSize(size - margin * 2, size - margin * 2)
    fm = QFontMetrics(font)
    while font.pointSize() > 4:
        br = fm.boundingRect(text)
        if br.width() <= target.width() and br.height() <= target.height():
            break
        font.setPointSize(font.pointSize() - 2)
        fm = QFontMetrics(font)
    p.setFont(font)

    # 三种状态：Normal(主题文字色)/Active(强调色)/Selected(白色，选中时背景已是 accent)
    # Normal 颜色随主题：深色模式下导航背景变暗，文字图标用浅色
    _normal_color = "#f3f3f3" if isDarkTheme() else "#1a1a1a"
    for mode, color in (
        (QIcon.Normal, QColor(_normal_color)),
        (QIcon.Active, QColor("#005fb8" if not isDarkTheme() else "#60cdff")),
        (QIcon.Selected, QColor("#ffffff")),
    ):
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.eraseRect(0, 0, size, size)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.setPen(color)
        p.drawText(QRect(0, 0, size, size), Qt.AlignCenter, text)
        icon.addPixmap(pix, mode, QIcon.Off)
        icon.addPixmap(pix, mode, QIcon.On)

    p.end()
    return icon


# ============================================================
# 主页模块磁贴（文件夹卡片）
# ============================================================
class ModuleFolderTile(CardWidget):
    """主页模块磁贴：模块文字图标 + 模块名 + 右上角图钉（置顶开关）。

    - 图标沿用侧边栏同款文字图标（V/F/x/pH/v/A，`make_text_icon()` 渲染），
      亮/暗主题下文字颜色随主题（`apply_theme` 时重绘刷新）
    - 点击磁贴任意位置 → 进入对应传感器模块（CardWidget.clicked）
    - 右上角 PillToolButton（FIF.PIN）为 toggle：选中态自动填充主题色，
      置顶的模块排在本组最前面；状态持久化到 app_config.json
    - 外观完全由 FluentWidgets 渲染：CardWidget 自带圆角边框 + 悬停
      背景动画，亮/暗主题自动适配
    """

    def __init__(self, name: str, icon_text: str, pinned: bool = False, parent=None):
        super().__init__(parent)
        self.setBorderRadius(8)
        self.setFixedHeight(118)
        self.setMinimumWidth(160)
        self.setClickEnabled(True)
        self._name = name
        self._icon_text = icon_text or '?'

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 8)
        lay.setSpacing(2)

        # 顶部行：图钉右对齐（Pin 置顶切换）
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(0)
        top.addStretch(1)
        self.pin_btn = PillToolButton(FIF.PIN, self)
        self.pin_btn.setFixedSize(24, 24)
        self.pin_btn.setChecked(pinned)
        self.pin_btn.setToolTip("取消置顶" if pinned else "置顶")
        self.pin_btn.installEventFilter(ToolTipFilter(self.pin_btn))
        top.addWidget(self.pin_btn)
        lay.addLayout(top)

        # 模块文字图标（识别区文字，如 V/F/x/pH/v/A）
        self.icon_widget = IconWidget(QIcon(make_text_icon(self._icon_text, size=128)), self)
        self.icon_widget.setFixedSize(44, 44)
        lay.addWidget(self.icon_widget, 0, Qt.AlignmentFlag.AlignHCenter)

        # 模块名
        self.name_label = BodyLabel(name, self)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setWordWrap(True)
        lay.addWidget(self.name_label)

    def refresh_icon(self):
        """按当前主题重绘文字图标（主题切换时调用）。"""
        self.icon_widget.setIcon(QIcon(make_text_icon(self._icon_text, size=128)))


# ============================================================
# 模块元数据解析
# ============================================================
META_PATTERN = re.compile(
    r'#\s*===\s*MODULE META\s*===\s*\n'
    r'(.*?)'
    r'#\s*===+\s*',
    re.DOTALL
)


def parse_module_meta(file_path):
    """解析模块文件头的识别区注释块。

    Args:
        file_path: 模块 .py 文件的绝对路径

    Returns:
        dict: {'icon': ..., 'name': ..., 'category': ..., 'class': ...}
        解析失败返回 None
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            # 只读前 50 行，识别区在文件头
            head = ''.join(f.readline() for _ in range(50))
    except Exception as e:
        log.warning("读取模块文件失败 %s: %s", file_path, e)
        return None

    m = META_PATTERN.search(head)
    if not m:
        return None

    meta = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if line.startswith('#'):
            line = line.lstrip('#').strip()
        if ':' in line:
            key, _, value = line.partition(':')
            meta[key.strip().lower()] = value.strip()

    if 'name' not in meta or 'class' not in meta:
        return None

    meta.setdefault('icon', '?')
    meta.setdefault('category', 'physics')
    return meta


def scan_modules(modules_dir):
    """扫描模块目录，发现并加载所有传感器模块。

    Args:
        modules_dir: 传感器模块目录的绝对路径

    Returns:
        list of dict: 每项包含
            - name: 模块显示名
            - icon: 模块图标文本
            - category: 模块类别（physics/chemistry）
            - class_name: 模块类名
            - module: 加载后的 Python 模块对象
            - file_path: 模块文件路径
        按模块名排序
    """
    discovered = []
    if not os.path.isdir(modules_dir):
        log.warning("模块目录不存在: %s", modules_dir)
        return discovered

    # 遍历 sensors/ 下的每个子目录
    for sub in sorted(os.listdir(modules_dir)):
        sub_path = os.path.join(modules_dir, sub)
        if not os.path.isdir(sub_path):
            continue

        # 子目录下所有 .py 文件
        for py_file in sorted(glob.glob(os.path.join(sub_path, '*.py'))):
            base = os.path.basename(py_file)
            if base.startswith('_') or base.startswith('test'):
                continue

            meta = parse_module_meta(py_file)
            if not meta:
                log.info("跳过（无识别区）: %s", py_file)
                continue

            # importlib 动态加载
            mod_name = f"_sensor_module_{base[:-3]}"
            spec = importlib.util.spec_from_file_location(mod_name, py_file)
            if spec is None or spec.loader is None:
                log.warning("无法加载模块: %s", py_file)
                continue

            mod = importlib.util.module_from_spec(spec)
            try:
                sys.modules[mod_name] = mod
                spec.loader.exec_module(mod)
            except Exception as e:
                log.error("模块加载失败 %s: %s", py_file, e)
                continue

            class_name = meta['class']
            if not hasattr(mod, class_name):
                log.error("模块未定义类 %s: %s", class_name, py_file)
                continue

            discovered.append({
                'name': meta['name'],
                'icon': meta['icon'],
                'category': meta['category'],
                'class_name': class_name,
                'module': mod,
                'file_path': py_file,
            })
            log.info("✓ 已加载模块: %s (%s) <- %s",
                     meta['name'], meta['category'], base)

    discovered.sort(key=lambda x: (x['category'], x['name']))
    return discovered


# ============================================================
# 插件加载（flaskserver 等）
#
# 扫描仓库根目录下的一级子目录：内有 __init__.py 且文件头 50 行含
# 「=== PLUGIN META ===」识别区即视为插件。按显式路径加载成正规包
# （不进 sys.path），失败只记日志并跳过，不影响主程序启动。
# ============================================================

PLUGIN_META_PATTERN = re.compile(r'#\s*===\s*PLUGIN\s+META\s*===\s*(.*)', re.S)


def parse_plugin_meta(init_path):
    """解析插件 __init__.py 头部识别区，返回 meta dict 或 None。"""
    try:
        with open(init_path, 'r', encoding='utf-8') as f:
            head = ''.join(f.readline() for _ in range(50))
    except Exception as e:
        log.warning("读取插件文件失败 %s: %s", init_path, e)
        return None
    m = PLUGIN_META_PATTERN.search(head)
    if not m:
        return None
    meta = {}
    for line in m.group(1).splitlines():
        line = line.strip().lstrip('#').strip()
        if ':' in line:
            key, _, value = line.partition(':')
            meta[key.strip().lower()] = value.strip()
    if 'name' not in meta or 'class' not in meta:
        return None
    return meta


def load_plugins(app_dir):
    """扫描并加载 app_dir 下的插件，返回插件实例列表。"""
    plugins = []
    if not os.path.isdir(app_dir):
        return plugins
    for sub in sorted(os.listdir(app_dir)):
        plugin_dir = os.path.join(app_dir, sub)
        init_path = os.path.join(plugin_dir, '__init__.py')
        if not os.path.isfile(init_path):
            continue
        meta = parse_plugin_meta(init_path)
        if not meta:
            continue
        mod_name = 'physchem_plugin_%s' % sub
        try:
            spec = importlib.util.spec_from_file_location(
                mod_name, init_path,
                submodule_search_locations=[plugin_dir])
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
            cls = getattr(mod, meta['class'])
            plugin = cls()
            plugins.append(plugin)
            log.info("✓ 已加载插件: %s <- %s/", meta['name'], sub)
        except Exception as e:
            log.error("插件加载失败 %s: %s", sub, e)
    return plugins


def lan_ip():
    """本机在局域网中的出口 IP；离线/无网卡时返回空串。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))   # UDP connect 不发包，只为让系统选出出口网卡
        return s.getsockname()[0]
    except OSError:
        return ''
    finally:
        s.close()


# ============================================================
# 主页
# ============================================================
class HomePageWidget(QWidget):
    """主页面 —— 项目信息入口按钮 + 传感器模块磁贴网格。

    项目介绍与三平台仓库地址不再常驻页面：默认聚合为一行
    「项目信息」按钮（见 `_build_project_entry`），点击弹出
    `ProjectInfoDialog` 卡片展示详情，卡片底部「返回」按钮关回主页。

    模块区采用 Windows 资源管理器磁贴风格：每个模块一张卡片，
    模块文字图标 + 名称 + 右上角图钉（置顶）。网格由
    AdaptiveFlowLayout 驱动，随窗口宽度自动换行铺满；图钉状态
    持久化在 app_config.json 的 General.PinnedModules。
    """

    module_clicked = Signal(str)

    def __init__(self):
        super().__init__()
        self._modules = []  # [(icon, name, category), ...]
        self._tiles = {}    # name -> ModuleFolderTile（磁贴跨重建复用）
        self._project_dialog = None  # 项目信息卡片（首次打开时创建并复用）
        # 自绘 Gitee / GitCode logo（FluentWidgets 没有内置）
        self._img_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "docs", "images")
        self.init_ui()

    def set_modules(self, modules):
        """设置模块列表并重建模块卡片区域。

        Args:
            modules: list of (icon, name, category)
        """
        self._modules = modules
        self._rebuild_module_cards()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(scroll_area_style())

        self.content = QWidget()
        self.content.setObjectName("home_content")
        self.content.setStyleSheet(page_bg_style())
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(20, 10, 20, 12)
        self.content_layout.setSpacing(8)

        # 页面标题：用 FluentWidgets TitleLabel 自动适配主题
        title = TitleLabel("主页")
        self.content_layout.addWidget(title)

        # ========== 项目信息入口（聚合按钮，点击弹出详情卡片） ==========
        # 项目简介 / 标签 / 三平台仓库地址统一收进弹窗，页面上只留一行
        self.content_layout.addWidget(self._build_project_entry())

        # ========== 数据接口入口卡片（插件存在时才显示） ==========
        self._data_card = self._build_data_card()
        self._data_card.setVisible(False)
        self.content_layout.addWidget(self._data_card)

        # ========== 传感器模块（文字图标磁贴网格，按物理/化学分组） ==========
        self._phys_title = TitleLabel("物理实验模块")
        self._chem_title = TitleLabel("化学实验模块")

        self._phys_flow = AdaptiveFlowLayout()
        self._phys_flow.setHorizontalSpacing(10)
        self._phys_flow.setVerticalSpacing(10)
        self._phys_flow.setWidgetMinimumWidth(160)

        self._chem_flow = AdaptiveFlowLayout()
        self._chem_flow.setHorizontalSpacing(10)
        self._chem_flow.setVerticalSpacing(10)
        self._chem_flow.setWidgetMinimumWidth(160)

        self.content_layout.addWidget(self._phys_title)
        self.content_layout.addLayout(self._phys_flow)
        self.content_layout.addSpacing(8)
        self.content_layout.addWidget(self._chem_title)
        self.content_layout.addLayout(self._chem_flow)

        self.content_layout.addStretch()
        self.scroll.setWidget(self.content)
        main_layout.addWidget(self.scroll)

    def _build_project_entry(self):
        """项目信息入口卡片：默认聚合为一行按钮，点击弹出详情卡片。

        样式对齐「数据接口」入口卡片（CardWidget + IconWidget +
        BodyLabel/CaptionLabel），整行可点；右侧 CHEVRON_RIGHT 图标
        提示可展开（不用「❯」等字符：内嵌 MiSans 无该字形，会显示成方框）。
        """
        card = CardWidget(self)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setFixedHeight(76)
        row = QHBoxLayout(card)
        row.setContentsMargins(18, 10, 18, 10)
        row.setSpacing(12)

        icon = IconWidget(FIF.INFO, card)
        icon.setFixedSize(28, 28)
        row.addWidget(icon)

        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(BodyLabel("项目信息", card))
        col.addWidget(CaptionLabel(
            "项目简介 · GPL-3.0 开源 · GitHub / Gitee / GitCode 仓库地址", card))
        row.addLayout(col, stretch=1)

        chevron = IconWidget(FIF.CHEVRON_RIGHT, card)
        chevron.setFixedSize(12, 12)
        row.addWidget(chevron)

        card.setToolTip("点击查看项目简介与仓库地址")
        card.mousePressEvent = lambda e: self._open_project_dialog()
        return card

    def _open_project_dialog(self):
        """打开「项目信息」卡片（弹窗，复用同一实例）。"""
        if self._project_dialog is None:
            self._project_dialog = ProjectInfoDialog(self.window())
        self._project_dialog.refresh()
        self._project_dialog.exec()

    def set_data_plugin(self, plugin):
        """注入数据接口插件（None = 插件缺失，整张卡片不显示）。"""
        self._data_plugin = plugin
        self._refresh_data_card()

    def _build_data_card(self):
        """数据接口可折叠卡片（与设置页同款的 FluentCard 折叠交互）。

        折叠时：标题 + 运行状态 + 数据接口启停开关；展开后显示地址 /
        密钥 / 局域网 / 鉴权 / 打开仪表盘等完整内容。服务生命周期只由
        开关决定，与卡片展开状态解耦。
        """
        card = FluentCard("数据接口", expanded=True, icon=FIF.IOT)
        self._data_card = card  # 先持有引用，供构建过程中的 _make_addr_row 等使用
        self._restart_busy = False

        # ---- header 右侧：状态点 + 状态文字 + 启停开关（折叠时可见） ----
        self._data_status_dot = QLabel(card)
        self._data_status_dot.setFixedSize(10, 10)
        self._data_status_text = CaptionLabel("未运行")
        self._sw_server = SwitchButton("数据接口")
        self._sw_server.setOnText("数据接口")  # 勾选后标签仍显示名称（默认会变成 On）
        self._sw_server.checkedChanged.connect(self._on_server_switch)
        card.add_header_widget(self._data_status_dot)
        card.add_header_widget(self._data_status_text)
        card.add_header_widget(self._sw_server)

        # ---- 内容区（展开后显示） ----
        card.add_widget(CaptionLabel(
            "把实验数据开放给 AI Agent 与浏览器仪表盘"))

        self._addr_rows = {}
        self._addr_rows['local'] = self._make_addr_row(
            "本机", self._local_url(), copy=True)
        self._lan_row = self._make_addr_row(
            "局域网", self._lan_url(), copy=True)
        self._addr_rows['lan'] = self._lan_row
        self._token_row = self._make_addr_row(
            "访问密钥", '', copy=True, regen=True)  # 运行中才显示，文本由刷新回填

        self._sw_lan = SwitchButton("局域网访问")
        self._sw_lan.setOnText("局域网访问")
        self._sw_lan.checkedChanged.connect(self._on_lan_switch)
        card.add_widget(self._sw_lan)

        self._sw_auth = SwitchButton("访问密钥鉴权")
        self._sw_auth.setOnText("访问密钥鉴权")
        self._sw_auth.setChecked(bool(app_cfg.serverAuth.value))
        self._sw_auth.checkedChanged.connect(self._on_auth_switch)
        card.add_widget(self._sw_auth)

        # ---- 打开仪表盘（仅服务运行中可见） ----
        open_row = QHBoxLayout()
        self._open_label = BodyLabel("在浏览器打开")
        open_row.addWidget(self._open_label)
        open_row.addStretch()
        self._open_btn = PrimaryPushButton("打开仪表盘")
        self._open_btn.clicked.connect(self._open_browser)
        open_row.addWidget(self._open_btn)
        self._open_row = QWidget()
        self._open_row.setLayout(open_row)
        card.add_widget(self._open_row)

        # ---- flask 未装提示（默认隐藏） ----
        self._hint = CaptionLabel("")
        self._hint.setVisible(False)
        card.add_widget(self._hint)

        # 行距放宽一点，地址/开关行不至于太挤；内容齐了重算一次卡片高度
        card.body.setContentsMargins(20, 12, 20, 16)
        card.body.setSpacing(12)
        card._adjustViewSize()
        return card

    def _make_addr_row(self, name, url, copy=False, regen=False):
        """卡片内容区的一行「名称 + 只读地址 + 复制(+重生)」。

        复制按钮在点击时读取输入框当前文本（地址会随端口/密钥动态刷新）。
        """
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        cap = CaptionLabel(name)
        cap.setFixedWidth(56)
        h.addWidget(cap)
        edit = LineEdit()
        edit.setText(url)
        edit.setReadOnly(True)
        edit.setFont(QFont("Consolas", 10))
        h.addWidget(edit, stretch=1)
        if copy:
            btn = PushButton("复制")
            btn.setFixedHeight(30)
            btn.clicked.connect(
                lambda _=False, e=edit: self._copy_to_clipboard(e.text()))
            h.addWidget(btn)
        if regen:
            rbtn = PushButton("重生")
            rbtn.setFixedHeight(30)
            rbtn.clicked.connect(self._regen_token)
            h.addWidget(rbtn)
            self._token_regen_btn = rbtn
        row._edit = edit
        self._data_card.add_widget(row)
        return row

    def _refresh_data_card(self):
        """按插件可用性与服务状态刷新数据接口卡片（含动态显示规则）。"""
        plugin = getattr(self, '_data_plugin', None)
        if self._data_card is None:
            return
        self._data_card.setVisible(plugin is not None)
        if plugin is None:
            return
        ok, hint = plugin.available()
        running = plugin.is_running()
        color = "#2e7d32" if running else "#9e9e9e"
        self._data_status_dot.setStyleSheet(
            "background-color: %s; border-radius: 5px;" % color)
        self._data_status_text.setText(
            ("运行中  %s" % plugin.url) if running else "未运行")
        # 开关状态回填（不发信号）
        self._sw_server.blockSignals(True); self._sw_server.setChecked(running); self._sw_server.blockSignals(False)
        self._sw_server.setEnabled(ok)
        lan_on = bool(app_cfg.serverLanAccess.value)
        self._sw_lan.blockSignals(True); self._sw_lan.setChecked(lan_on); self._sw_lan.blockSignals(False)
        self._sw_lan.setEnabled(ok)
        # 局域网地址行：仅局域网开关 = 开 且有 IP
        self._lan_row.setVisible(lan_on and bool(self._lan_url()))
        self._lan_row._edit.setText(self._lan_url())
        # 密钥行：仅服务运行中且鉴权开启；鉴权关闭时整行隐藏
        auth_on = bool(app_cfg.serverAuth.value)
        self._token_row.setVisible(running and auth_on)
        self._token_row._edit.setText(self._data_plugin.token or '')
        # 「在浏览器打开」整行：仅服务运行中
        self._open_row.setVisible(running)
        # flask 未装提示
        self._hint.setText(hint)
        self._hint.setVisible(not ok)
        # 行显隐变了，重算卡片高度（否则展开高度停在旧行数，内容被截断）
        try:
            self._data_card._adjustViewSize()
        except Exception:
            pass

    # ---- 数据接口卡片：地址/URL 帮手 ----
    def _copy_to_clipboard(self, text: str):
        """把文本拷到系统剪贴板。"""
        clip = QGuiApplication.clipboard()
        if clip and text:
            clip.setText(text)

    def _local_url(self):
        return 'http://127.0.0.1:%s' % app_cfg.serverPort.value

    def _lan_url(self):
        ip = lan_ip()
        if not ip:
            return ''
        return 'http://%s:%s' % (ip, app_cfg.serverPort.value)

    # ---- 数据接口卡片：控件行为 ----
    def _on_server_switch(self, checked):
        """开 → 启动服务；关 → 停止。flask 未装时置灰不会进到这里。"""
        if self._restart_busy:
            return
        if checked:
            ok, msg = self._data_plugin.start(
                port=app_cfg.serverPort.value,
                allow_lan=app_cfg.serverLanAccess.value,
                enable_cors=app_cfg.serverCors.value)
            if not ok:
                InfoBar.error(title="启动失败", content=msg, duration=3000,
                              position=InfoBarPosition.TOP, parent=self.window())
                self._sw_server.blockSignals(True); self._sw_server.setChecked(False); self._sw_server.blockSignals(False)  # 回弹
        else:
            self._data_plugin.stop()
        self._refresh_data_card()

    def _on_lan_switch(self, checked):
        """切局域网：先风险确认，确认后写配置并重启服务以重新绑定网卡。"""
        if self._restart_busy:
            return
        ip = lan_ip()
        if checked and not ip:
            InfoBar.warning(title="无法开启", content="未检测到局域网网卡",
                            duration=3000, position=InfoBarPosition.TOP,
                            parent=self.window())
            self._sw_lan.blockSignals(True); self._sw_lan.setChecked(False); self._sw_lan.blockSignals(False)
            return
        if checked:
            box = MessageBox(
                "开启局域网访问？",
                "同一网络内的任何人都能访问并控制本机实验。\n请仅在可信网络中开启。",
                self.window())
            if not box.exec():
                self._sw_lan.blockSignals(True); self._sw_lan.setChecked(False); self._sw_lan.blockSignals(False)
                return
        app_cfg.serverLanAccess.value = bool(checked)
        # 重启服务以重新绑定网卡；期间禁用两个开关防连点
        self._restart_busy = True
        self._sw_server.setEnabled(False)
        self._sw_lan.setEnabled(False)
        if self._data_plugin.is_running():
            self._data_plugin.stop()
            ok, msg = self._data_plugin.start(
                port=app_cfg.serverPort.value,
                allow_lan=bool(checked),
                enable_cors=app_cfg.serverCors.value)
            if not ok:
                InfoBar.error(title="重启失败", content=msg, duration=3000,
                              position=InfoBarPosition.TOP, parent=self.window())
                self._sw_server.blockSignals(True); self._sw_server.setChecked(False); self._sw_server.blockSignals(False)
        self._restart_busy = False
        self._sw_server.setEnabled(True)
        self._sw_lan.setEnabled(True)
        self._refresh_data_card()

    def _on_auth_switch(self, checked):
        """切鉴权开关：写配置并重启服务使其生效（重启期间禁用开关防连点）。"""
        if self._restart_busy:
            return
        app_cfg.serverAuth.value = bool(checked)
        self._restart_busy = True
        for sw in (self._sw_server, self._sw_lan, self._sw_auth):
            sw.setEnabled(False)
        if self._data_plugin.is_running():
            self._data_plugin.stop()
            ok, msg = self._data_plugin.start(
                port=app_cfg.serverPort.value,
                allow_lan=app_cfg.serverLanAccess.value,
                enable_cors=app_cfg.serverCors.value)
            if not ok:
                InfoBar.error(title="重启失败", content=msg, duration=3000,
                              position=InfoBarPosition.TOP, parent=self.window())
                self._sw_server.blockSignals(True); self._sw_server.setChecked(False); self._sw_server.blockSignals(False)
        self._restart_busy = False
        for sw in (self._sw_server, self._sw_lan, self._sw_auth):
            sw.setEnabled(True)
        self._refresh_data_card()

    def _regen_token(self):
        """重生成访问密钥（仅运行中可用），旧密钥立即失效。"""
        if not self._data_plugin.is_running():
            return
        token = self._data_plugin.regenerate_token()
        self._data_plugin.stop()
        self._data_plugin.start(port=app_cfg.serverPort.value,
                                allow_lan=app_cfg.serverLanAccess.value,
                                enable_cors=app_cfg.serverCors.value,
                                token=token)
        self._refresh_data_card()
        InfoBar.success(title="密钥已重生", content="旧密钥立即失效",
                        duration=2000, position=InfoBarPosition.TOP,
                        parent=self.window())

    def _open_browser(self):
        url = self._data_plugin.url or self._local_url()
        # 鉴权开启时自动带上密钥：浏览器端 app.js 会读取 ?token= 免手输
        if app_cfg.serverAuth.value:
            token = self._data_plugin.token or ''
            if token:
                sep = '&' if '?' in url else '?'
                url = f"{url}{sep}token={token}"
        QDesktopServices.openUrl(QUrl(url))

    def _load_platform_icon(self, svg_name, fallback=FIF.CODE):
        """加载本地 SVG 平台 logo，失败回退 FluentIcon。"""
        path = os.path.join(self._img_dir, svg_name)
        pix = QPixmap(path)
        if not pix.isNull():
            return QIcon(pix)
        return fallback

    def _rebuild_module_cards(self):
        """根据 self._modules 重建磁贴网格（置顶优先，物理/化学分组）。

        磁贴控件跨重建复用（self._tiles），只做取回 + 重排序；
        图钉状态以 app_cfg.pinnedModules 为准（配置重载/主题切换安全）。
        """
        # 清空两个网格（不删除磁贴）
        # 注意：qfluentwidgets 的 FlowLayout.takeAt() 直接返回 widget 本身
        # （不是 QLayoutItem），不可再调用 item.widget()
        for flow in (self._phys_flow, self._chem_flow):
            while flow.count():
                w = flow.takeAt(0)
                if w is not None:
                    w.setParent(None)

        pinned = set(app_cfg.pinnedModules.value or [])

        def _sort_key(m):
            return (0 if m[1] in pinned else 1, m[1])

        phys = [m for m in self._modules if m[2] == 'physics']
        chem = [m for m in self._modules if m[2] == 'chemistry']
        phys.sort(key=_sort_key)
        chem.sort(key=_sort_key)

        for title, flow, mods in (
            (self._phys_title, self._phys_flow, phys),
            (self._chem_title, self._chem_flow, chem),
        ):
            title.setVisible(bool(mods))
            for icon_text, name, _cat in mods:
                tile = self._tiles.get(name)
                if tile is None:
                    tile = ModuleFolderTile(
                        name, icon_text, pinned=(name in pinned))
                    tile.clicked.connect(
                        lambda n=name: self.on_module_clicked(n))
                    tile.pin_btn.toggled.connect(
                        lambda checked, n=name: self._on_pin_toggled(n, checked))
                    self._tiles[name] = tile
                else:
                    # 复用时同步图钉状态（blockSignals 防触发重排）
                    tile.pin_btn.blockSignals(True)
                    tile.pin_btn.setChecked(name in pinned)
                    tile.pin_btn.blockSignals(False)
                    tile.pin_btn.setToolTip(
                        "取消置顶" if name in pinned else "置顶")
                flow.addWidget(tile)

    def _on_pin_toggled(self, name, checked):
        """图钉切换：更新置顶列表（持久化到 app_config.json）并重排磁贴。"""
        pinned = list(app_cfg.pinnedModules.value or [])
        if checked and name not in pinned:
            pinned.append(name)
        elif not checked and name in pinned:
            pinned.remove(name)
        try:
            qconfig.set(app_cfg.pinnedModules, pinned)
        except Exception as e:
            log.warning("保存置顶配置失败: %s", e)
        self._rebuild_module_cards()

    def _copy_to_clipboard(self, text: str):
        """把文本拷到系统剪贴板，并在状态栏给一个轻提示。"""
        clip = QGuiApplication.clipboard()
        if clip:
            clip.setText(text)
        try:
            InfoBar.success(
                title="已复制",
                content=text,
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT,
                duration=1500,
                parent=self,
            )
        except Exception:
            pass

    def on_module_clicked(self, module_name):
        self.module_clicked.emit(module_name)

    def apply_theme(self, theme):
        """主题切换：刷新页面/滚动区背景，重绘磁贴文字图标。

        磁贴为 FluentWidgets 原生组件（CardWidget/PillToolButton/
        BodyLabel），亮暗主题自动适配；文字图标（make_text_icon）的
        Normal 状态颜色随主题变化，需按新主题重绘。
        """
        self.scroll.setStyleSheet(scroll_area_style())
        self.content.setStyleSheet(page_bg_style())
        for tile in self._tiles.values():
            try:
                tile.refresh_icon()
            except Exception as e:
                log.warning("磁贴图标主题刷新失败 [%s]: %s", tile._name, e)
        if self._project_dialog is not None:
            self._project_dialog.apply_theme()


# ============================================================
# 自由软件声明（「项目信息」卡片与设置页共用）
# ============================================================
def free_software_notice_text():
    """声明文案（含主题相关的高亮色，主题切换后需重设）。"""
    accent = "#ffd166" if isDarkTheme() else "#b45309"   # 暖色强调
    return (
        "本软件是自由软件，你可以自由使用、修改和分发；"
        "分发时请遵守许可证约定，保留版权与许可声明。<br>"
        "<b><span style='color:%s'>官方目前没有提供付费服务</span></b>，"
        "如果你认为你的自由受到了侵害，请"
        "<b><span style='color:%s'>提交 Issue</span></b>给我，"
        "并与卖家协商解决。" % (accent, accent))


def free_software_notice_style():
    """声明块外观：淡色面板 + 左侧竖条，底色/边框随主题。"""
    if isDarkTheme():
        bg, border, bar = "#3a3320", "#4d4326", "#ffd166"
    else:
        bg, border, bar = "#fff8e6", "#f0dfae", "#e0a020"
    return ("""
        #freeSoftwareNotice {
            background: %s;
            border: 1px solid %s;
            border-left: 3px solid %s;
            border-radius: 6px;
        }
        #freeSoftwareNotice QLabel { background: transparent; }
    """ % (bg, border, bar))


def apply_notice_theme(notice):
    """按当前主题刷新声明块（文案高亮色、正文色、面板底色一起换）。"""
    if notice is None:
        return
    fg = _theme_colors()['text_primary']
    notice.setStyleSheet(free_software_notice_style())
    label = notice.findChild(_WrappedLabel)
    if label is not None:
        label.setStyleSheet("color: %s;" % fg)
        label.setText(free_software_notice_text())
    title = notice.findChild(QLabel, "freeSoftwareNoticeTitle")
    if title is not None:
        title.setStyleSheet("color: %s; background: transparent;" % fg)


def build_free_software_notice(parent, title_size=12, body_size=11):
    """构建自由软件声明块（设置页顶部与「项目信息」卡片共用）。

    文案分三层：定性（本软件是自由软件）→ 义务（分发遵守许可证）→
    维权路径（官方无付费服务；被收费时先提 Issue，再与卖家协商）。
    维权路径那句用强调色加粗，即"异色"部分；配色随主题切换。

    Args:
        parent: 父控件
        title_size: 标题字号（卡片里 12，设置页顶部 13）
        body_size: 正文字号（卡片里 11）
    """
    notice = QWidget(parent)
    notice.setObjectName("freeSoftwareNotice")
    col = QVBoxLayout(notice)
    col.setContentsMargins(12, 10, 12, 10)
    col.setSpacing(6)

    head = QHBoxLayout()
    head.setSpacing(8)
    icon = IconWidget(FIF.INFO, notice)
    icon.setFixedSize(18, 18)
    head.addWidget(icon, 0, Qt.AlignVCenter)
    title = QLabel("自由软件声明", notice)
    title.setObjectName("freeSoftwareNoticeTitle")
    title.setFont(QFont("Segoe UI", title_size, QFont.Weight.DemiBold))
    head.addWidget(title)
    head.addStretch()
    col.addLayout(head)

    label = _WrappedLabel(parent=notice)
    label.setFont(QFont("Segoe UI", body_size))
    col.addWidget(label)

    apply_notice_theme(notice)
    return notice


# ============================================================
# 「项目信息」卡片（主页聚合按钮弹出）
# ============================================================
class _WrappedLabel(QLabel):
    """自动换行且高度随宽度变化的富文本标签。

    普通 QLabel 在垂直布局里只上报单行 sizeHint，多行富文本会被压扁；
    这里补上 heightForWidth，把文档按当前宽度排版后回填最小高度，长段落
    才能完整显示。内容里的 `<br>` 由富文本渲染，避免依赖具体字体换行。
    """

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.RichText)
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        """按给定宽度计算所需高度（宽度未定时退回单行高度）。"""
        if width <= 0:
            return self.sizeHint().height()
        doc = QTextDocument()
        doc.setDefaultFont(self.font())
        doc.setHtml(self.text())
        doc.setTextWidth(width)
        return int(doc.size().height()) + 2

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setMinimumHeight(self.heightForWidth(self.width()))


class ProjectInfoDialog(MessageBoxBase):
    """项目信息卡片：项目简介 + 标签 + 自由软件声明 + 三平台仓库地址。

    主页把「项目介绍」与「项目地址」聚合为一行按钮，详情收在本卡片里；
    底部按钮改写为「返回」，点它（或 Esc）关回主页。卡片内容超出高度时
    在内部滚动区滚动，地址行的复制 / 访问按钮行为保持与原卡片一致。
    """

    #: 三平台仓库地址（名称, URL, SVG 文件名；SVG 缺失时回退 FluentIcon）
    REPOS = (
        ("GitHub", "https://github.com/wangzhidong2/PhysChem-DigitizerP",
         "github.svg", FIF.GITHUB),
        ("Gitee", "https://gitee.com/wangzhidong2/PhysChem-DigitizerP",
         "gitee.svg", FIF.CODE),
        ("GitCode", "https://gitcode.com/wangzhidong2/PhysChem-DigitizerP",
         "gitcode.svg", FIF.CODE),
    )

    #: 标签配色（亮色底 + 深色字，明暗主题下都是浅色胶囊，故固定色值）
    TAGS = (
        ("GPL-3.0 开源", "#e8f5e9", "#2e7d32"),
        ("教学实验", "#f3e5f5", "#7b1fa2"),
        ("模块化架构", "#e3f2fd", "#1565c0"),
    )

    #: 内容超出时的最大高度上限（小屏 / 高 DPI 时内部滚动，不撑破弹窗）
    MAX_SCROLL_H = 320

    def __init__(self, parent=None):
        super().__init__(parent)
        self._svg_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "docs", "images")
        self._tag_labels = []
        self._fitted = False

        # 只需「返回」：隐藏确定按钮，取消按钮改文案
        self.yesButton.hide()
        self.cancelButton.setText("返回")
        self.cancelButton.setMinimumWidth(80)
        # 弹框宽度自适应屏幕：理想 680（容下整条仓库 URL，约 55 字符），
        # 小屏 / 高 DPI 缩放时不超出屏幕，避免左右内容被裁掉
        screen = QGuiApplication.primaryScreen()
        avail_w = screen.availableGeometry().width() if screen else 1280
        self.widget.setFixedWidth(min(680, int(avail_w * 0.9)))

        subtitle = SubtitleLabel("项目信息", self)
        _f = subtitle.font()
        _f.setPixelSize(14)
        subtitle.setFont(_f)
        self.viewLayout.addWidget(subtitle)

        # 内容超高（小屏 / 高 DPI）时内部滚动，不撑破弹窗
        self.content = QWidget()
        self.content.setObjectName("projectBody")   # 供 apply_theme 的背景 QSS 定位
        body = QVBoxLayout(self.content)
        body.setContentsMargins(12, 8, 12, 8)
        body.setSpacing(6)

        # 自由软件声明：字号加大后置于卡片顶部（最需要先被看到的一段）
        body.addWidget(self._build_notice())

        body.addWidget(CaptionLabel("项目简介", self.content))
        desc = BodyLabel(
            "PhysChem-DigitizerP —— 基于 Arduino/ESP32 的低成本理化实验"
            "数字化采集系统。为中学和大学物理/化学实验室提供低成本、"
            "高精度的传感器解决方案；采用模块化架构，新增传感器只需"
            "丢文件，无需修改主程序。", self.content)
        desc.setWordWrap(True)
        desc.setFont(QFont("Segoe UI", 9))
        body.addWidget(desc)

        body.addLayout(self._build_tags())

        sep = QFrame(self.content)
        sep.setFrameShape(QFrame.HLine)
        body.addWidget(sep)

        body.addWidget(CaptionLabel("项目地址", self.content))
        for name, url, svg, fallback in self.REPOS:
            body.addLayout(self._build_repo_row(name, url, svg, fallback))

        # 末尾伸缩项放在滚动区之外（见 _fit_scroll 的说明），这里不留空白

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setWidget(self.content)
        self._scroll.setMinimumHeight(160)
        self._scroll.setMaximumHeight(self.MAX_SCROLL_H)
        self.viewLayout.addWidget(self._scroll)
        self.viewLayout.addStretch()
        self.viewLayout.addWidget(self._build_autoshow_box())
        self.apply_theme()

    def _build_autoshow_box(self):
        """「下次启动不再弹出」复选框：直接读写 app_config.json。

        勾选态与配置项 ShowIntroOnStartup 语义相反（勾选 = 不再自动弹出），
        映射只在 _on_autoshow_toggled 里做一次。
        """
        self._autoshow = CheckBox("下次启动不再弹出", self)
        self._autoshow.setFont(QFont("Segoe UI", 9))
        self._autoshow.setChecked(not bool(app_cfg.showIntroOnStartup.value))
        self._autoshow.setToolTip(
            "勾选后启动不再自动弹出；随时可从主页「项目信息」重新打开")
        self._autoshow.toggled.connect(self._on_autoshow_toggled)
        return self._autoshow

    def _on_autoshow_toggled(self, checked):
        """勾选 = 下次启动不再弹出，故写入配置时取反。"""
        try:
            qconfig.set(app_cfg.showIntroOnStartup, not bool(checked))
        except Exception as e:
            log.warning("保存启动弹出配置失败: %s", e)

    # ---- 高度自适应 ----
    def showEvent(self, event):
        """首次显示后按内容量一次高度，避免出现多余的滚动条。"""
        super().showEvent(event)
        if not self._fitted:
            self._fitted = True
            QTimer.singleShot(0, self._fit_scroll)

    def _fit_scroll(self):
        """把滚动区高度收到内容自然高度（超出上限才滚动）。

        不用 `content.sizeHint()`：QWidget 的 sizeHint 受滚动区宽度与
        布局约束影响，实测与"刚好放下"的高度不一致（会白挂一条滚动条）。
        这里改为累加各级布局的实际高度，结果就是内容的自然高度。
        """
        layout = self.content.layout()
        if layout is None:
            return
        margin = layout.contentsMargins()
        total = margin.top() + margin.bottom()
        total += layout.spacing() * max(0, layout.count() - 1)
        for i in range(layout.count()):
            item = layout.itemAt(i)
            widget = item.widget()
            if widget is not None:
                total += widget.sizeHint().height()
            elif item.layout() is not None:
                total += item.layout().sizeHint().height()
        self._scroll.setFixedHeight(min(total, self.MAX_SCROLL_H))


    # ---- 内容构建 ----
    def _build_notice(self):
        """自由软件声明块：与设置页顶部共用同一个构建函数。

        字号比正文大一档（正文 11pt / 标题 12pt），且置于卡片顶部——
        这是最需要先被看到的一段。
        """
        self._notice = build_free_software_notice(
            self.content, title_size=11, body_size=10)
        self._notice_label = self._notice.findChild(_WrappedLabel)
        self._notice_title = self._notice.findChild(
            QLabel, "freeSoftwareNoticeTitle")
        return self._notice

    def _style_notice(self, notice=None, label=None):
        """按当前主题刷新声明块（薄封装，便于 apply_theme 直接调用）。"""
        apply_notice_theme(notice if notice is not None
                           else getattr(self, '_notice', None))

    def _build_tags(self):
        """标签胶囊行（配色固定，亮暗主题下都清晰）。"""
        row = QHBoxLayout()
        row.setSpacing(8)
        for text, bg, fg in self.TAGS:
            tag = QLabel(text, self.content)
            tag.setFont(QFont("Segoe UI", 8))
            tag.setStyleSheet(
                f"background-color: {bg}; color: {fg};"
                "border-radius: 9px; padding: 3px 10px;")
            row.addWidget(tag)
            self._tag_labels.append(tag)
        row.addStretch()
        return row

    def _build_repo_row(self, name, url, svg, fallback=FIF.CODE):
        """一行「平台名 + 只读 URL + 复制 + 访问」。"""
        row = QHBoxLayout()
        row.setSpacing(8)

        # 不设固定宽度：CaptionLabel 按内容取自然宽度（GitHub/GitCode 长度不同）
        row.addWidget(CaptionLabel(name, self.content))

        url_edit = LineEdit(self.content)
        url_edit.setText(url)
        url_edit.setReadOnly(True)
        url_edit.setFont(QFont("Consolas", 9))
        url_edit.setCursor(Qt.CursorShape.IBeamCursor)
        url_edit.setMinimumWidth(300)   # 加宽，完整显示整个 URL
        url_edit.setToolTip("点击全选，Ctrl+C 复制")
        row.addWidget(url_edit, stretch=1)

        copy_btn = PushButton("复制", self.content)
        copy_btn.setFixedHeight(30)
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.clicked.connect(
            lambda _=False, u=url: self._copy_to_clipboard(u))
        row.addWidget(copy_btn)

        # 访问按钮只放平台 logo（图标自带宽度差异，固定宽度会挤扁图标）
        open_btn = PushButton(self.content)
        open_btn.setFixedHeight(30)
        open_btn.setIcon(self._load_icon(svg, fallback))
        open_btn.setToolTip("在浏览器中打开 %s" % name)
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.clicked.connect(lambda _=False, u=url: webbrowser.open(u))
        row.addWidget(open_btn)
        return row

    def _load_icon(self, svg_name, fallback=FIF.CODE):
        """加载本地 SVG 平台 logo，失败回退 FluentIcon。"""
        pix = QPixmap(os.path.join(self._svg_dir, svg_name))
        return QIcon(pix) if not pix.isNull() else fallback

    # ---- 行为 ----
    def _copy_to_clipboard(self, text):
        """复制到剪贴板，并在本卡片右下方轻提示（不依赖主页）。"""
        clip = QGuiApplication.clipboard()
        if clip and text:
            clip.setText(text)
        try:
            InfoBar.success(
                title="已复制", content=text,
                orient=Qt.Orientation.Horizontal, isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT,
                duration=1500, parent=self)
        except Exception as e:
            log.warning("复制提示失败: %s", e)

    def refresh(self):
        """每次打开前同步主题与「启动时自动显示」勾选态。

        主题可能在两次打开之间切过；配置项也可能被外部改写（如手改
        app_config.json），所以打开前以配置为准回填复选框。
        """
        self.apply_theme()
        if hasattr(self, '_autoshow'):
            self._autoshow.blockSignals(True)
            self._autoshow.setChecked(not bool(app_cfg.showIntroOnStartup.value))
            self._autoshow.blockSignals(False)

    def apply_theme(self):
        """按当前主题刷新内容区与滚动区样式，亮 ↔ 暗双向可切。

        背景必须同时落在 `#projectBody`（内容区）与 QScrollArea 上：
        只给 QScrollArea 设 QSS 时，内层 QWidget 仍带系统浅色调色板并
        自绘背景，暗色主题下会出现"浅底 + 浅字"。滚动条也在这里统一
        配色，避免落到默认外观。
        """
        c = _theme_colors()
        self.content.setStyleSheet(
            "#projectBody { background: %s; }" % c['content_bg'])
        self._style_notice()    # 声明块：底色/边框/高亮色都随主题
        self._scroll.setStyleSheet("""
            QScrollArea {{
                border: 1px solid {sep};
                border-radius: 6px;
                background: {bg};
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 10px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {handle};
                border-radius: 4px;
                min-height: 32px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {handle_hover}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
        """.format(sep=c['separator'], bg=c['content_bg'],
                   handle=c['text_hint'], handle_hover=c['text_secondary']))


# ============================================================
# 侧边栏导航按钮
# ============================================================
class NavButton(QPushButton):
    """现代化风格侧边栏导航按钮"""

    def __init__(self, icon_text, label, tooltip="", parent=None):
        super().__init__(parent)
        self.icon_text = icon_text
        self.label = label
        self.tooltip = tooltip
        self._is_selected = False
        self._is_collapsed = False
        self._theme = "light"

        self.setCheckable(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip)
        self.setFixedHeight(40)
        self.setMinimumWidth(40)

        self._update_style()

    def set_selected(self, selected):
        self._is_selected = selected
        self._update_style()

    def set_collapsed(self, collapsed):
        self._is_collapsed = collapsed
        self._update_style()

    def set_theme(self, theme):
        self._theme = theme
        self._update_style()

    def _update_style(self):
        if self._theme == "dark":
            bg = "#2d2d2d"
            bg_hover = "#3d3d3d"
            bg_selected = "#3d3d3d"
            text_color = "#ffffff"
        else:
            bg = "transparent"
            bg_hover = "#e9e9e9"
            bg_selected = "#e9e9e9"
            text_color = "#1a1a1a"

        border_radius = "8px"
        if self._is_selected:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {bg_selected};
                    border: none;
                    border-radius: {border_radius};
                    color: {text_color};
                    font-size: 14px;
                    font-weight: 500;
                    text-align: left;
                    padding-left: 14px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {bg};
                    border: none;
                    border-radius: {border_radius};
                    color: {text_color};
                    font-size: 14px;
                    text-align: left;
                    padding-left: 14px;
                }}
                QPushButton:hover {{ background-color: {bg_hover}; }}
            """)

    def paintEvent(self, event):
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._theme == "dark":
            icon_color = QColor("#ffffff") if not self._is_selected else QColor("#60cdff")
            text_color = QColor("#ffffff")
            indicator_color = QColor("#60cdff")
        else:
            icon_color = QColor("#1a1a1a") if not self._is_selected else QColor("#0067c0")
            text_color = QColor("#1a1a1a")
            indicator_color = QColor("#0067c0")

        rect = self.rect()

        # 选中态左侧蓝色指示条
        if self._is_selected:
            indicator_width = 3
            indicator_height = 16
            indicator_x = 0
            indicator_y = (rect.height() - indicator_height) // 2
            painter.setBrush(indicator_color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(indicator_x, indicator_y, indicator_width, indicator_height, 2, 2)

        # 图标
        icon_size = 20
        icon_x = 12 if not self._is_collapsed else (rect.width() - icon_size) // 2
        icon_y = (rect.height() - icon_size) // 2

        font = QFont("Segoe MDL2 Assets", 14)
        painter.setFont(font)
        painter.setPen(icon_color)
        painter.drawText(QRect(icon_x, icon_y, icon_size, icon_size), Qt.AlignmentFlag.AlignCenter, self.icon_text)

        # 展开时绘制文字
        if not self._is_collapsed:
            painter.setPen(text_color)
            label_font = QFont("Segoe UI", 10)
            painter.setFont(label_font)
            text_x = 42
            text_rect = QRect(text_x, 0, rect.width() - text_x - 8, rect.height())
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.label)

        painter.end()


# ============================================================
# 侧边栏
# ============================================================
class SidebarWidget(QWidget):
    """现代化风格可折叠侧边栏组件（动态接收模块列表）"""

    module_changed = Signal(int)

    def __init__(self):
        super().__init__()
        self.is_collapsed = False
        self.expanded_width = 220
        self.collapsed_width = 60
        self.current_index = 0
        self.theme = "light"
        self.nav_buttons = []
        # modules 列表：[(icon, name, desc), ...]
        # 第 0 项固定为主页，最后一项固定为设置
        self.modules = []
        self.init_ui()

    def init_ui(self):
        self.setFixedWidth(self.expanded_width)
        self.setStyleSheet("background-color: #f0f0f0; border: none;")

        self.main_layout = QVBoxLayout()
        self.main_layout.setContentsMargins(8, 8, 8, 8)
        self.main_layout.setSpacing(2)

        # 顶部汉堡菜单按钮
        self.hamburger_btn = QPushButton()
        self.hamburger_btn.setFixedSize(44, 44)
        self.hamburger_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hamburger_btn.setToolTip("折叠/展开侧边栏")
        self.hamburger_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 8px;
            }
            QPushButton:hover { background-color: #e9e9e9; }
        """)
        self.hamburger_btn.clicked.connect(self.toggle_collapse)
        self.main_layout.addWidget(self.hamburger_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # 导航容器
        self.nav_container = QWidget()
        self.nav_layout = QVBoxLayout()
        self.nav_layout.setContentsMargins(0, 4, 0, 0)
        self.nav_layout.setSpacing(2)
        self.nav_container.setLayout(self.nav_layout)
        self.main_layout.addWidget(self.nav_container)

        self.setLayout(self.main_layout)
        self._update_hamburger_icon()

    def set_modules(self, modules):
        """设置模块列表并重建导航按钮。

        Args:
            modules: list of (icon, name, desc)
                    不含主页和设置，主页自动加在第 0 位，设置自动加在末尾
        """
        # 清空旧按钮
        while self.nav_layout.count():
            item = self.nav_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.nav_buttons = []

        # 主页始终在第 0 位
        all_modules = [("🏠", "主页", "项目介绍与功能导航")] + list(modules)
        all_modules.append(("⚙", "设置", "应用设置与偏好"))

        self.modules = all_modules

        for icon, name, desc in all_modules:
            btn = NavButton(icon, name, desc)
            btn.set_theme(self.theme)
            btn.set_collapsed(self.is_collapsed)
            btn.clicked.connect(lambda checked, idx=len(self.nav_buttons): self.on_nav_clicked(idx))
            self.nav_buttons.append(btn)
            self.nav_layout.addWidget(btn)

        self.nav_layout.addStretch()

        # 设置按钮移到底部（最后一个 NavButton）
        if self.nav_buttons:
            self.nav_layout.removeWidget(self.nav_buttons[-1])
            self.main_layout.addWidget(self.nav_buttons[-1])

        self.set_current_row(0)

    def toggle_collapse(self):
        self.is_collapsed = not self.is_collapsed
        if self.is_collapsed:
            self.setFixedWidth(self.collapsed_width)
        else:
            self.setFixedWidth(self.expanded_width)
        for btn in self.nav_buttons:
            btn.set_collapsed(self.is_collapsed)
        self._update_hamburger_icon()

    def _update_hamburger_icon(self):
        pixmap = QPixmap(20, 20)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.theme == "dark":
            color = QColor("#ffffff")
        else:
            color = QColor("#1a1a1a")

        painter.setPen(color)
        font = QFont("Segoe MDL2 Assets", 14)
        painter.setFont(font)
        painter.drawText(QRect(0, 0, 20, 20), Qt.AlignmentFlag.AlignCenter, "\uE700")
        painter.end()

        self.hamburger_btn.setIcon(QIcon(pixmap))
        self.hamburger_btn.setIconSize(QSize(20, 20))

    def set_current_row(self, row):
        if 0 <= row < len(self.nav_buttons):
            self.current_index = row
            for i, btn in enumerate(self.nav_buttons):
                btn.set_selected(i == row)

    def get_current_row(self):
        return self.current_index

    def on_nav_clicked(self, index):
        self.set_current_row(index)
        self.module_changed.emit(index)

    def apply_theme(self, theme):
        self.theme = theme
        if theme == "dark":
            self.setStyleSheet("background-color: #202020; border: none;")
            self.hamburger_btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: none;
                    border-radius: 8px;
                }
                QPushButton:hover { background-color: #3d3d3d; }
            """)
        else:
            self.setStyleSheet("background-color: #f0f0f0; border: none;")
            self.hamburger_btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: none;
                    border-radius: 8px;
                }
                QPushButton:hover { background-color: #e9e9e9; }
            """)
        for btn in self.nav_buttons:
            btn.set_theme(theme)
        self._update_hamburger_icon()


# ============================================================
# 设置（主题切换 + 关于信息）
# ============================================================
class SettingsWidget(QWidget):
    """设置页 —— 主题切换 / 关于。

    用 FluentWidgets 的 SettingCardGroup + SettingCard 系列组件搭建，
    样式自动适配亮/暗主题。当前分组：
    - 外观：应用主题（亮/深/跟随系统）、主题色
    - 图表：绘图引擎切换
    - 数据与配置：保存配置开关、传感器配置管理、恢复默认设置
    - 运行日志：日志开关、详细度
    - 关于：项目名、版本、许可证
    - 源码 & 反馈：仓库与 issue 链接
    """

    theme_change_requested = Signal(str)  # 'light' / 'dark'
    engine_change_requested = Signal(str)  # 'matplotlib' / 'pyqtgraph'

    APP_VERSION = "1.8"

    def __init__(self):
        super().__init__()
        # 主题模式：浅色 / 深色 / 跟随系统
        self._theme_combo_items = ["浅色模式", "深色模式", "跟随系统"]
        self._theme_combo_values = ["light", "dark", "auto"]
        self._notice = None              # 顶部「自由软件声明」块（init_ui 里创建）
        # 当前主题模式（显式记录：qconfig.theme 会把 AUTO 解析成 LIGHT/DARK，
        # 无法据此区分「跟随系统」，故单独维护；同步下拉框用）
        self._theme_mode = "light"
        # 「清除用户设置」程序内开启保存开关时，跳过开启确认框（用户已确认过）
        self._suppress_persistence_confirm = False
        # 自定义主题色（默认蓝色；「跟随系统主题色」模式下系统色不落盘，此值保留）
        self._custom_theme_color = qconfig.get(qconfig.themeColor).name()
        self._theme_color_combo = None   # 主题色模式下拉框（懒创建引用）
        self._theme_color_preview = None # 当前主题色预览色块
        self._pick_color_btn = None      # 「选择颜色」按钮
        self.init_ui()
        # 按当前 FluentWidgets 主题同步下拉框选中项
        self._sync_theme_combo_from_current()

    def init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setStyleSheet(scroll_area_style())

        self._content = QWidget()
        self._content.setStyleSheet(page_bg_style())
        # 最小宽度：窗口过窄时出横向滚动条，而不是把卡片的文字压到不可见
        self._content.setMinimumWidth(720)
        layout = QVBoxLayout(self._content)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)

        # 页面标题：用 TitleLabel 自动适配主题
        title = TitleLabel("设置")
        layout.addWidget(title)

        # 自由软件声明（置顶，与「项目信息」卡片同一份文案/配色）
        self._notice = build_free_software_notice(
            self._content, title_size=13, body_size=11)
        layout.addWidget(self._notice)

        # ===== 外观分组（主题） =====
        group_appearance = SettingCardGroup("外观", self._content)
        self._theme_card = self._build_theme_card(group_appearance)
        group_appearance.addSettingCard(self._theme_card)
        group_appearance.addSettingCard(self._build_theme_color_card())
        group_appearance.addSettingCard(self._build_font_card())
        layout.addWidget(group_appearance)

        # ===== 图表分组 =====
        group_chart = SettingCardGroup("图表", self._content)
        group_chart.addSettingCard(self._build_engine_card())
        layout.addWidget(group_chart)

        # ===== 数据与配置分组 =====
        group_data = SettingCardGroup("数据与配置", self._content)
        group_data.addSettingCard(self._build_persistence_card())
        group_data.addSettingCard(self._build_config_management_card())
        group_data.addSettingCard(self._build_reset_all_card())
        layout.addWidget(group_data)

        # ===== 数据接口分组（flaskserver 插件的不常改项） =====
        group_api = SettingCardGroup("数据接口", self._content)
        group_api.addSettingCard(self._build_api_port_card())
        group_api.addSettingCard(self._build_api_lan_card())
        group_api.addSettingCard(self._build_api_cors_card())
        group_api.addSettingCard(self._build_api_token_card())
        layout.addWidget(group_api)

        # ===== 运行日志分组 =====
        group_log = SettingCardGroup("运行日志", self._content)
        group_log.addSettingCard(self._build_log_card())
        group_log.addSettingCard(self._build_log_detail_card())
        layout.addWidget(group_log)

        # ===== 关于分组 =====
        group_about = SettingCardGroup("关于", self._content)
        group_about.addSettingCard(self._build_about_card(
            FIF.APPLICATION, "应用名称", "PhysChem-DigitizerP"))
        group_about.addSettingCard(self._build_about_card(
            FIF.INFO, "版本", f"v{self.APP_VERSION}"))
        group_about.addSettingCard(self._build_about_card(
            FIF.COPY, "版权", "Copyright © 2026 wangzhidong2"))
        group_about.addSettingCard(self._build_about_card(
            FIF.CERTIFICATE, "开源许可证", "GPL-3.0-only",
            "本应用遵循 GPL-3.0-only 协议开源"))
        layout.addWidget(group_about)

        # ===== 内嵌字体（致谢 + 官网链接） =====
        # 两家字体的许可条款都要求「在软件中特别注明使用了该字体」
        # （MiSans FAQ「是否可以用作嵌入式字体」、HarmonyOS Sans 许可 2.1 条），
        # 这栏同时满足署名要求与致谢
        group_fonts = SettingCardGroup("内嵌字体", self._content)
        credit = CaptionLabel("感谢对应字体提供方的免费支持", group_fonts)
        credit.setAlignment(Qt.AlignmentFlag.AlignLeft
                            | Qt.AlignmentFlag.AlignVCenter)
        # 插在标题之后（vBoxLayout 的 0 是标题，1 是标题下方的间距）
        group_fonts.vBoxLayout.insertWidget(1, credit)
        for family, vendor, url in (
            ("MiSans",
             "小米科技有限责任公司（Xiaomi）",
             "https://hyperos.mi.com/font/zh"),
            ("HarmonyOS Sans SC",
             "华为终端有限公司（Huawei Device Co., Ltd.）",
             "https://developer.huawei.com/consumer/cn/design/resource-V1/"),
        ):
            group_fonts.addSettingCard(
                self._build_font_credit_card(family, vendor, url))
        layout.addWidget(group_fonts)

        # ===== 开源信息（可折叠卡片） =====
        layout.addWidget(self._build_open_source_card())

        # ===== 源码与反馈分组 =====
        # 自绘 Gitee / GitCode logo（FluentWidgets 没有内置）
        _img_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "images")
        gitee_icon = self._load_icon(os.path.join(_img_dir, "gitee.svg")) or FIF.CODE
        gitcode_icon = self._load_icon(os.path.join(_img_dir, "gitcode.svg")) or FIF.CODE

        group_repo = SettingCardGroup("源码 & 反馈", self._content)
        group_repo.addSettingCard(self._build_repo_card(
            FIF.GITHUB, "GitHub 仓库",
            "https://github.com/wangzhidong2/PhysChem-DigitizerP"))
        group_repo.addSettingCard(self._build_repo_card(
            gitee_icon, "Gitee 仓库",
            "https://gitee.com/wangzhidong2/PhysChem-DigitizerP"))
        group_repo.addSettingCard(self._build_repo_card(
            gitcode_icon, "GitCode 仓库",
            "https://gitcode.com/wangzhidong2/PhysChem-DigitizerP"))
        group_repo.addSettingCard(self._build_feedback_card(
            FIF.FEEDBACK, "问题反馈", "提交 Issue / 功能建议", [
                ("GitHub Issue",
                 "https://github.com/wangzhidong2/PhysChem-DigitizerP/issues"),
                ("GitCode Issue",
                 "https://gitcode.com/wangzhidong2/PhysChem-DigitizerP/issues"),
            ]))
        layout.addWidget(group_repo)

        layout.addStretch()
        self._scroll.setWidget(self._content)
        outer.addWidget(self._scroll)

    def _build_theme_card(self, parent):
        """主题切换卡片：自定义 SettingCard，内嵌一个 ComboBox。

        支持亮色 / 深色 / 跟随系统三种模式。
        """
        card = SettingCard(FIF.PALETTE, "应用主题",
                           "切换亮色 / 深色模式 / 跟随系统", parent)
        combo = ComboBox(card)
        combo.addItems(self._theme_combo_items)
        combo.setMinimumWidth(160)
        combo.currentIndexChanged.connect(self._on_theme_combo_changed)
        card.hBoxLayout.addWidget(combo)
        card.hBoxLayout.addSpacing(16)
        self._theme_combo = combo
        return card

    def _build_font_card(self):
        """应用字体卡片：默认内嵌 MiSans，点「选择…」打开系统字体选择器。

        选择器列出系统已安装的**全部字体**（Qt6 在中文系统上直接给出
        本地化名称：微软雅黑 / 宋体 / 楷体 / 隶书…），用字体自身字形
        渲染条目并实时预览——与 Word 的字体下拉同思路，不局限几个预设。

        MiSans 以 assets/fonts/MiSans-Regular.ttf 独立文件随程序分发，
        启动时注册进 Qt，因此不依赖本机是否装过该字体。
        结果写入 app_config.json 的 General.FontFamily，下次启动沿用。

        等宽字体（数据记录 / 原始数据读数）不随此项变化——见 core.MONO_FONT_FAMILY。
        """
        card = SettingCard(FIF.FONT, "应用字体",
                           "点「选择…」从系统已装字体中挑选（仿 Word 字体列表）",
                           None)
        # 当前字体名用其自身字形显示，一眼看出效果
        preview = BodyLabel("")
        preview.setMinimumWidth(190)
        card.hBoxLayout.addWidget(preview)
        pick_btn = PushButton("选择…", card)
        pick_btn.setFixedHeight(30)
        pick_btn.clicked.connect(self._on_pick_font)
        card.hBoxLayout.addWidget(pick_btn)
        card.hBoxLayout.addSpacing(16)
        self._font_preview = preview
        self._refresh_font_preview()
        return card

    def _on_pick_font(self):
        """打开仿 Word 的系统字体选择器，确认后应用并落盘。"""
        dlg = FontPickerDialog(str(app_cfg.fontFamily.value or ''),
                               parent=self.window())
        if not dlg.exec():
            dlg.deleteLater()
            return
        family = dlg.selected_family()
        dlg.deleteLater()
        self._on_font_family_changed(family)

    def _on_font_family_changed(self, family):
        """应用并持久化字体选择。

        存的是用户原始输入（未做可用性回退），换到装该字体的机器上
        仍能生效；本机缺失时 core 会回退内嵌 MiSans 并记警告。
        """
        family = '' if family is None else str(family).strip()
        if family == str(app_cfg.fontFamily.value or ''):
            self._refresh_font_preview()
            return
        qconfig.set(app_cfg.fontFamily, family)     # 落盘
        # 就地重刷已创建的控件（保留各自字号/字重，等宽字体不动）
        apply_app_font(family, refresh_widgets=True)
        self._refresh_font_preview()
        self._scroll.setStyleSheet(scroll_area_style())
        self._content.setStyleSheet(page_bg_style())
        # 图表里的轴标签是引擎自己画的，需按新字体重绘
        window = self.window()
        if hasattr(window, 'refresh_chart_fonts'):
            try:
                window.refresh_chart_fonts()
            except Exception as e:
                log.warning("刷新图表字体失败: %s", e)
        families = available_font_families()
        if family and family not in families:
            InfoBar.warning(
                title="字体不可用", content=f"未找到「{family}」，已回退内嵌 MiSans",
                duration=3000, position=InfoBarPosition.TOP, parent=self)
        else:
            InfoBar.success(
                title="字体已切换", content=family or "系统默认",
                duration=2000, position=InfoBarPosition.TOP, parent=self)

    def _refresh_font_preview(self):
        """用当前字体自身的字形显示字体名（未设置则显示「系统默认」）。"""
        preview = getattr(self, '_font_preview', None)
        if preview is None:
            return
        configured = str(app_cfg.fontFamily.value or '')
        resolved = resolve_app_font_family()
        preview.setText(configured or "系统默认")
        font = QFont(preview.font())
        if resolved:
            font.setFamilies([resolved])
        preview.setFont(font)

    def _build_theme_color_card(self):
        """主题色卡片：跟随系统主题色 / 自定义主题色（默认蓝色）。

        - 「跟随系统主题色」：读取并跟随 Windows 系统强调色
          （任务栏/开始菜单强调色，监听 DWM 广播实时更新；系统色不落盘）
        - 「自定义主题色」：点击「选择颜色」弹取色器，选择即持久化
        """
        card = SettingCard(
            FIF.PALETTE, "主题色",
            "跟随系统主题色或自定义（默认蓝色）", None)
        self._theme_color_combo = ComboBox(card)
        self._theme_color_combo.addItems(["跟随系统主题色", "自定义主题色"])
        self._theme_color_combo.setMinimumWidth(150)
        self._theme_color_combo.setCurrentIndex(
            0 if app_cfg.themeColorMode.value == "system" else 1)
        self._theme_color_combo.currentIndexChanged.connect(
            self._on_theme_color_combo_changed)
        card.hBoxLayout.addWidget(self._theme_color_combo)
        card.hBoxLayout.addSpacing(10)

        # 当前主题色预览色块
        self._theme_color_preview = QLabel()
        self._theme_color_preview.setFixedSize(24, 20)
        self._theme_color_preview.setToolTip("当前主题色")
        card.hBoxLayout.addWidget(self._theme_color_preview)

        # 取色按钮（仅自定义主题色模式下可用）
        self._pick_color_btn = PushButton("选择颜色", card)
        self._pick_color_btn.setFixedHeight(30)
        self._pick_color_btn.clicked.connect(self._on_pick_theme_color)
        card.hBoxLayout.addWidget(self._pick_color_btn)
        card.hBoxLayout.addSpacing(16)
        self._sync_theme_color_controls()
        return card

    def _sync_theme_color_controls(self):
        """同步主题色预览色块与取色按钮状态（模式切换/取色后调用）。"""
        if self._pick_color_btn is not None:
            self._pick_color_btn.setEnabled(
                app_cfg.themeColorMode.value != "system")
        if self._theme_color_preview is not None:
            color = (system_accent_color()
                     if app_cfg.themeColorMode.value == "system"
                     else self._custom_theme_color or DEFAULT_THEME_COLOR)
            self._theme_color_preview.setStyleSheet(
                f"background-color: {color}; border-radius: 4px;"
                " border: 1px solid #808080;")

    def _on_theme_color_combo_changed(self, idx: int):
        """主题色模式切换：system=读取系统强调色（不落盘）；custom=恢复自定义色。"""
        mode = "system" if idx == 0 else "custom"
        if mode == app_cfg.themeColorMode.value:
            return
        qconfig.set(app_cfg.themeColorMode, mode)   # 落盘模式
        if mode == "system":
            set_app_theme_color(system_accent_color(), save=False)
        else:
            set_app_theme_color(
                self._custom_theme_color or DEFAULT_THEME_COLOR, save=False)
        self._sync_theme_color_controls()

    def _on_pick_theme_color(self):
        """自定义主题色取色：弹出 WinUI3 风格取色对话框。"""
        from qfluentwidgets.components.dialog_box import ColorDialog
        current = QColor(self._custom_theme_color or DEFAULT_THEME_COLOR)
        dialog = ColorDialog(current, "选择主题色", self)
        dialog.colorChanged.connect(self._on_custom_theme_color_changed)
        dialog.exec()

    def _on_custom_theme_color_changed(self, color: QColor):
        """取色完成：记录自定义色并切到自定义模式（选择即持久化）。"""
        self._custom_theme_color = color.name()
        # ComboBox 同步到「自定义主题色」（blockSignals 防递归）
        if self._theme_color_combo is not None:
            self._theme_color_combo.blockSignals(True)
            self._theme_color_combo.setCurrentIndex(1)
            self._theme_color_combo.blockSignals(False)
        qconfig.set(app_cfg.themeColorMode, "custom")
        set_app_theme_color(self._custom_theme_color, save=True)
        self._sync_theme_color_controls()

    def _build_persistence_card(self):
        """配置持久化开关卡片：FluentWidgets 原生 SwitchSettingCard。

        与 AppConfig.configPersistenceEnabled 双向绑定：
        - 拨动开关 → qconfig.set() 自动写入 app_config.json
        - 配置变化（含程序内 set）→ 开关 UI 自动同步
        关闭后：不读取 sensor_config.json 旧配置（core.load_sensor_config
        返回空），不写入新配置（save_sensor_config 静默丢弃），
        本次运行的所有更改退出后销毁。
        """
        card = ZhSwitchSettingCard(
            FIF.SAVE, "保存配置",
            "关闭后不读取已保存的校准配置，本次所有更改退出程序时销毁",
            configItem=app_cfg.configPersistenceEnabled,
        )
        # setChecked 内部 _updateText 读 onText/offText，同步设中文避免闪烁
        card.switchButton.setOnText("开")
        card.switchButton.setOffText("关")
        self._persistence_card = card
        card.checkedChanged.connect(self._on_persistence_changed)
        return card

    def _on_persistence_changed(self, checked: bool):
        """开关切换处理。

        开 → 关：无风险，直接生效（此后不再写盘）。
        关 → 开：当前会话是「默认值 + 本次随手修改」的状态，恢复写入后
        下一次任何模块 save_config() 会把这套状态写进磁盘，可能覆盖
        之前校准好的数据，因此先弹确认框；拒绝则切回关闭。
        （「清除用户设置」程序内开启时跳过确认：磁盘配置已删，无覆盖风险）
        """
        if not checked:
            return
        if self._suppress_persistence_confirm:
            self._suppress_persistence_confirm = False
            return
        # 确认是否覆盖：从关闭切到开启
        box = MessageBox(
            "开启配置保存",
            "开启后将恢复保存配置。当前会话内的更改会随下次修改写入磁盘，"
            "可能覆盖之前保存的校准数据。\n是否继续？",
            self,
        )
        box.yesButton.setText("确定")
        box.cancelButton.setText("取消")
        if not box.exec():
            # 拒绝：切回关闭（qconfig.set 会同步翻转开关 UI 并落盘）
            qconfig.set(app_cfg.configPersistenceEnabled, False)

    def _build_api_port_card(self):
        """监听端口设置卡片（1024–65535，默认 8765；运行中修改下次启动生效）。"""
        card = SettingCard(FIF.GLOBE, "监听端口",
                           "数据接口的 HTTP 端口（重启服务后生效）", None)
        spin = SpinBox(card)
        spin.setRange(1024, 65535)
        spin.setValue(int(app_cfg.serverPort.value))
        spin.setMinimumWidth(120)
        spin.valueChanged.connect(
            lambda v: setattr(app_cfg.serverPort, 'value', int(v)))
        card.hBoxLayout.addWidget(spin)
        card.hBoxLayout.addSpacing(16)
        return card

    def _build_api_lan_card(self):
        """允许局域网访问开关卡片（开启前弹风险确认框）。"""
        card = SettingCard(FIF.WIFI, "允许局域网访问",
                           "开启后同一网络的设备可访问数据接口（含控制）", None)
        sw = SwitchButton(card)
        sw.setOnText("开"); sw.setOffText("关")
        sw.setChecked(bool(app_cfg.serverLanAccess.value))
        sw.checkedChanged.connect(self._on_setting_lan_changed)
        card.hBoxLayout.addWidget(sw)
        card.hBoxLayout.addSpacing(16)
        return card

    def _on_setting_lan_changed(self, checked):
        """设置页局域网开关：同样先风险确认，再写配置。"""
        if checked:
            box = MessageBox(
                "开启局域网访问？",
                "同一网络内的任何人都能访问并控制本机实验。\n请仅在可信网络中开启。",
                self)
            if not box.exec():
                # 回弹（sender 是 SwitchButton）
                sw = self.sender()
                if sw is not None:
                    sw.blockSignals(True); sw.setChecked(False); sw.blockSignals(False)
                return
        app_cfg.serverLanAccess.value = bool(checked)

    def _build_api_cors_card(self):
        """允许跨域 (CORS) 开关卡片。"""
        card = SettingCard(FIF.CODE, "允许跨域 (CORS)",
                           "允许网页前端跨域调用数据接口（默认关闭）", None)
        sw = SwitchButton(card)
        sw.setOnText("开"); sw.setOffText("关")
        sw.setChecked(bool(app_cfg.serverCors.value))
        sw.checkedChanged.connect(
            lambda c: setattr(app_cfg.serverCors, 'value', bool(c)))
        card.hBoxLayout.addWidget(sw)
        card.hBoxLayout.addSpacing(16)
        return card

    def _build_api_token_card(self):
        """重新生成 token 卡片（旧密钥立即失效）。"""
        card = SettingCard(FIF.CERTIFICATE, "重新生成访问密钥",
                           "旧密钥立即失效，已连接的客户端需更新", None)
        btn = PushButton("重新生成", card)
        btn.setFixedHeight(30)
        btn.clicked.connect(self._on_regenerate_token)
        card.hBoxLayout.addWidget(btn)
        card.hBoxLayout.addSpacing(16)
        return card

    def _on_regenerate_token(self):
        """重生成访问密钥并持久化；服务运行中则带新密钥重启。"""
        from core import app_cfg as _cfg
        token = None
        window = self.window()
        plugin = getattr(window, 'data_plugin', None)
        if plugin is not None:
            token = plugin.regenerate_token()
            if plugin.is_running():
                plugin.stop()
                ok, msg = plugin.start(
                    port=_cfg.serverPort.value,
                    allow_lan=_cfg.serverLanAccess.value,
                    enable_cors=_cfg.serverCors.value,
                    token=token)
                if not ok:
                    log.warning("数据接口带新密钥重启失败: %s", msg)
        InfoBar.success(title="密钥已重生", content="旧密钥立即失效",
                        duration=2000, position=InfoBarPosition.TOP,
                        parent=self)

    def _build_log_card(self):
        """运行日志卡片：控制台始终输出；开关控制是否写入 logs.json。

        控制台保留原有启动/模块/配置等提示；开启（默认）时额外把运行日志以
        JSON Lines 追加写入项目目录 logs.json（跨会话、超上限裁剪最旧记录）。
        """
        card = SettingCard(
            FIF.HISTORY, "运行日志",
            "控制台始终显示运行日志；开启后同时写入项目目录 logs.json（默认开启）",
            None)
        self._log_switch = SwitchButton(card)
        self._log_switch.setOnText("开")
        self._log_switch.setOffText("关")
        self._log_switch.setChecked(bool(app_cfg.logEnabled.value))
        self._log_switch.checkedChanged.connect(self._on_log_switch_changed)
        card.hBoxLayout.addWidget(self._log_switch)
        card.hBoxLayout.addSpacing(10)

        self._open_log_btn = PushButton("打开日志", card)
        self._open_log_btn.setFixedHeight(30)
        self._open_log_btn.setToolTip("用系统默认程序打开项目目录下的 logs.json")
        self._open_log_btn.clicked.connect(self._on_open_log_clicked)
        card.hBoxLayout.addWidget(self._open_log_btn)
        card.hBoxLayout.addSpacing(16)
        return card

    def _build_log_detail_card(self):
        """日志详细度卡片：详细度下拉 + 最大保留条数（随即时生效并持久化）。"""
        card = SettingCard(
            FIF.FONT, "日志详细度",
            "控制台与日志文件的详细度：简略=仅警告/错误；标准=应用事件；详细=含串口原始数据", None)
        self._log_level_values = ["warning", "info", "debug"]
        self._log_level_combo = ComboBox(card)
        self._log_level_combo.addItems(["简略", "标准", "详细"])
        current = str(app_cfg.logLevel.value).lower()
        self._log_level_combo.setCurrentIndex(
            self._log_level_values.index(current)
            if current in self._log_level_values else 1)
        self._log_level_combo.currentIndexChanged.connect(self._on_log_level_changed)
        card.hBoxLayout.addWidget(self._log_level_combo)
        card.hBoxLayout.addSpacing(10)

        self._log_max_spin = SpinBox(card)
        self._log_max_spin.setRange(100, 200000)
        self._log_max_spin.setSingleStep(100)
        try:
            max_entries = int(app_cfg.logMaxEntries.value)
        except (TypeError, ValueError):
            max_entries = 5000      # 配置文件被手工改坏时回退默认值
        self._log_max_spin.setValue(max_entries)
        self._log_max_spin.setSuffix(" 条")
        self._log_max_spin.setToolTip("logs.json 最大保留条数，超出后自动裁剪最旧记录")
        self._log_max_spin.valueChanged.connect(self._on_log_max_changed)
        card.hBoxLayout.addWidget(self._log_max_spin)
        card.hBoxLayout.addSpacing(16)
        self._sync_log_detail_enabled()
        return card

    def _sync_log_detail_enabled(self):
        """详细度控件仅在运行日志开启时可用。"""
        enabled = bool(app_cfg.logEnabled.value)
        if getattr(self, '_log_level_combo', None) is not None:
            self._log_level_combo.setEnabled(enabled)
        if getattr(self, '_log_max_spin', None) is not None:
            self._log_max_spin.setEnabled(enabled)

    def _on_log_switch_changed(self, checked: bool):
        qconfig.set(app_cfg.logEnabled, bool(checked))
        set_log_enabled(bool(checked))
        self._sync_log_detail_enabled()

    def _on_log_level_changed(self, idx: int):
        if not (0 <= idx < len(self._log_level_values)):
            return
        level = self._log_level_values[idx]
        qconfig.set(app_cfg.logLevel, level)
        set_log_level(level)

    def _on_log_max_changed(self, value: int):
        qconfig.set(app_cfg.logMaxEntries, int(value))
        set_log_max_entries(int(value))

    def _on_open_log_clicked(self):
        """用系统默认程序打开 logs.json；文件不存在时提示先开启日志。"""
        path = get_log_file_path()
        if not os.path.exists(path):
            InfoBar.warning(
                title="暂无日志文件",
                content="请先开启「运行日志」并产生记录后重试",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT,
                duration=2500,
                parent=self,
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _build_config_management_card(self):
        """传感器配置管理卡片：清除、导出、导入传感器校准配置。"""
        card = SettingCard(
            FIF.SETTING, "传感器配置管理",
            "清除、导入或导出传感器校准配置（sensor_config.json）", None)
        for text, handler in (
            ("清除", self._on_clear_config_clicked),
            ("导出", self._on_export_config_clicked),
            ("导入", self._on_import_config_clicked),
        ):
            btn = PushButton(text, card)
            btn.setFixedHeight(34)
            btn.clicked.connect(handler)
            card.hBoxLayout.addWidget(btn)
            card.hBoxLayout.addSpacing(8)
        card.hBoxLayout.addSpacing(16)
        return card

    def _on_export_config_clicked(self):
        """导出配置：弹出系统文件夹选择对话框，将 sensor_config.json 复制到目标目录。"""
        folder = QFileDialog.getExistingDirectory(
            self, "选择导出目录", "",
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks,
        )
        if not folder:
            return  # 用户取消
        ok, msg = export_sensor_config(folder)
        if ok:
            box = MessageBox(
                "导出成功",
                f"配置已导出到 {msg}",
                self,
            )
            box.hideYesButton()
            box.cancelButton.setText("关闭")
            box.cancelButton.setStyleSheet("color: #28a745;")
            box.exec()
        else:
            box = MessageBox(
                "导出失败",
                msg,
                self,
            )
            box.hideYesButton()
            box.cancelButton.setText("关闭")
            box.cancelButton.setStyleSheet("color: #dc3545;")
            box.exec()

    def _on_import_config_clicked(self):
        """导入配置：弹出系统文件选择对话框，将选中的 JSON 文件写入 sensor_config.json。"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择配置文件", "",
            "JSON 文件 (*.json);;所有文件 (*)",
        )
        if not file_path:
            return  # 用户取消
        ok, msg = import_sensor_config(file_path)
        if ok:
            box = MessageBox(
                "导入成功",
                f"{msg}，重启程序后生效",
                self,
            )
            box.hideYesButton()
            box.cancelButton.setText("关闭")
            box.cancelButton.setStyleSheet("color: #28a745;")
            box.exec()
        else:
            box = MessageBox(
                "导入失败",
                msg,
                self,
            )
            box.hideYesButton()
            box.cancelButton.setText("关闭")
            box.cancelButton.setStyleSheet("color: #dc3545;")
            box.exec()

    def _on_clear_config_clicked(self):
        """清除用户设置：确认后清空 sensor_config.json，保存开关置为开。"""
        box = MessageBox(
            "清除用户设置",
            "将删除已保存的所有传感器校准配置，恢复默认值。\n是否继续？",
            self,
        )
        box.yesButton.setText("确定")
        box.cancelButton.setText("取消")
        if not box.exec():
            return
        ok = clear_sensor_config()
        if ok:
            # 保存开关置为开：跳过开启确认框（磁盘配置已删，无覆盖风险）
            self._suppress_persistence_confirm = True
            qconfig.set(app_cfg.configPersistenceEnabled, True)
            self._suppress_persistence_confirm = False
            box = MessageBox(
                "已清除",
                "用户配置已删除，重启程序后全部恢复默认值",
                self,
            )
            box.hideYesButton()
            box.cancelButton.setText("关闭")
            box.exec()
        else:
            box = MessageBox(
                "清除失败",
                "配置文件删除失败，请查看控制台输出",
                self,
            )
            box.hideYesButton()
            box.cancelButton.setText("关闭")
            box.cancelButton.setStyleSheet("color: #dc3545;")
            box.exec()

    def _build_reset_all_card(self):
        """恢复默认设置卡片：清除 app_config.json 与 sensor_config.json 到默认值。"""
        card = SettingCard(
            FIF.UPDATE, "恢复默认设置",
            "将应用配置和传感器校准配置全部恢复为默认值", None)
        btn = PushButton("恢复", card)
        btn.setFixedHeight(34)
        btn.clicked.connect(self._on_reset_all_clicked)
        card.hBoxLayout.addWidget(btn)
        card.hBoxLayout.addSpacing(16)
        return card

    def _on_reset_all_clicked(self):
        """恢复默认设置：确认后重置 app_config.json 和 sensor_config.json。"""
        box = MessageBox(
            "恢复默认设置",
            "将清除应用配置（主题/引擎等）和所有传感器校准配置，\n"
            "恢复为出厂默认值。\n是否继续？",
            self,
        )
        box.yesButton.setText("确定")
        box.cancelButton.setText("取消")
        if not box.exec():
            return
        ok, msg = reset_all_config()
        if ok:
            box = MessageBox("已恢复", msg, self)
            box.hideYesButton()
            box.cancelButton.setText("关闭")
            box.exec()
        else:
            box = MessageBox("恢复失败", msg, self)
            box.hideYesButton()
            box.cancelButton.setText("关闭")
            box.cancelButton.setStyleSheet("color: #dc3545;")
            box.exec()

    def _build_engine_card(self):
        """图表引擎切换卡片：matplotlib / pyqtgraph 运行时热切换。

        选择立即生效：所有已打开模块的图表原地换引擎并重放当前数据；
        同时写入 app_config.json，下次启动沿用。
        """
        self._engine_values = ["matplotlib", "pyqtgraph"]
        _default = app_cfg.chartEngine.value
        labels = [
            f"matplotlib{'（默认）' if _default == 'matplotlib' else ''}",
            f"pyqtgraph{'（默认）' if _default == 'pyqtgraph' else ''}",
        ]
        available = []
        for i, engine in enumerate(self._engine_values):
            if chart_engine_available(engine):
                available.append(engine)
            else:
                labels[i] += "（未安装）"
        # 副标题按安装情况给出提示
        if len(available) == len(self._engine_values):
            content = "切换立即生效"
        elif len(available) == 1:
            missing = "pyqtgraph" if available[0] == "matplotlib" else "matplotlib"
            content = f"当前仅 {available[0]} 可用（{missing} 未安装）"
        else:
            content = "未检测到图表引擎，图表区域将显示占位提示"

        card = SettingCard(FIF.TILES, "图表引擎", content, None)
        combo = ComboBox(card)
        combo.addItems(labels)
        for i, engine in enumerate(self._engine_values):
            if not chart_engine_available(engine):
                combo.setItemEnabled(i, False)   # 灰显 + 不可点击
        combo.setMinimumWidth(180)
        # 显示实际生效引擎：配置引擎被卸载时 resolve 已自动降级
        current = resolve_chart_engine(app_cfg.chartEngine.value)
        combo.setCurrentIndex(
            self._engine_values.index(current)
            if current in self._engine_values else 0)
        combo.currentIndexChanged.connect(self._on_engine_combo_changed)
        card.hBoxLayout.addWidget(combo)
        card.hBoxLayout.addSpacing(16)
        self._engine_combo = combo
        return card

    def _on_engine_combo_changed(self, idx: int):
        if not (0 <= idx < len(self._engine_values)):
            return
        engine = self._engine_values[idx]
        if not chart_engine_available(engine):
            return   # 未安装引擎的选项已禁用，此处为双保险
        # 从 pyqtgraph 切换到 matplotlib 时弹确认框（pyqtgraph 推荐）
        if engine == "matplotlib" and app_cfg.chartEngine.value == "pyqtgraph":
            box = MessageBox(
                "切换到 matplotlib",
                "matplotlib 在 PySide6 中存在一些兼容性 bug，\n"
                "pyqtgraph 可以提供更好的兼容性与性能，\n"
                "建议保留在 pyqtgraph。\n"
                "是否继续切换？\n\n"
                "已知 bug：使用滚轮在模块内翻页时，到图标这个区域时，滚轮会失效",
                self,
            )
            box.yesButton.setText("继续切换")
            box.cancelButton.setText("保留 pyqtgraph")
            if not box.exec():
                # 取消：下拉框切回 pyqtgraph（blockSignals 防递归）
                self._engine_combo.blockSignals(True)
                self._engine_combo.setCurrentIndex(
                    self._engine_values.index("pyqtgraph"))
                self._engine_combo.blockSignals(False)
                return
        qconfig.set(app_cfg.chartEngine, engine)   # 落盘 + 下次启动沿用
        self.engine_change_requested.emit(engine)  # 通知主窗口热切换

    def _build_about_card(self, icon, title, value, content=None):
        """只读信息卡片：右侧显示 value 文本，content 为副标题（可选）"""
        card = SettingCard(icon, title, content)
        value_lbl = BodyLabel(value)
        # 次要文字色，比标题弱一档
        value_lbl.setStyleSheet("color: #888888;")
        card.hBoxLayout.addWidget(value_lbl)
        card.hBoxLayout.addSpacing(16)
        return card

    def _build_link_card(self, icon, title, content, url):
        """带"访问"按钮的链接卡片（使用 PushButton 打开超链接）。"""
        card = SettingCard(icon, title, content)
        link_btn = self._make_link_button("访问", url)
        link_btn.setFixedHeight(34)
        card.hBoxLayout.addWidget(link_btn)
        card.hBoxLayout.addSpacing(16)
        return card

    def _build_repo_card(self, icon, title, url):
        """仓库链接卡片：图标 + 标题 + "访问" PushButton。"""
        card = SettingCard(icon, title, url)
        btn = self._make_link_button("访问", url)
        btn.setFixedHeight(34)
        card.hBoxLayout.addWidget(btn)
        card.hBoxLayout.addSpacing(16)
        return card

    def _build_feedback_card(self, icon, title, content, links):
        """反馈卡片：支持多个按钮（如 GitHub Issue / GitCode Issue）。

        Args:
            links: list of (btn_text, url)
        """
        card = SettingCard(icon, title, content)
        for btn_text, url in links:
            btn = self._make_link_button(btn_text, url)
            btn.setFixedHeight(34)
            card.hBoxLayout.addWidget(btn)
            card.hBoxLayout.addSpacing(8)
        card.hBoxLayout.addSpacing(16)
        return card

    @staticmethod
    def _load_icon(path):
        """从本地图片加载 QIcon，失败返回 None。"""
        try:
            from PySide6.QtGui import QPixmap
            pix = QPixmap(path)
            if not pix.isNull():
                return QIcon(pix)
        except Exception:
            pass
        return None

    def _make_link_button(self, text, url):
        """带超链接的 PushButton：点击用 webbrowser 打开 url。"""
        btn = PushButton(text)
        if url:
            btn.clicked.connect(lambda _=False, u=url: webbrowser.open(u))
        return btn

    def _build_font_credit_card(self, family, vendor, url):
        """内嵌字体致谢卡片：字体名 + 出品公司 + 官网链接。

        两家字体的许可条款都要求「在软件中特别注明使用了该字体」，
        这栏既是署名，也是致谢——故 content 统一写明"由…免费提供，
        谨致谢意"。右侧「官网」按钮用 webbrowser 打开对应字体主页。
        """
        card = SettingCard(
            FIF.FONT, family,
            "%s 免费提供，谨致谢意" % vendor)
        link_btn = self._make_link_button("官网", url)
        link_btn.setFixedHeight(34)
        card.hBoxLayout.addWidget(link_btn)
        card.hBoxLayout.addSpacing(16)
        return card

    def _build_open_source_card(self):
        """开源信息可折叠卡片：展示本项目依赖的开源库、协议与官网。

        使用 FluentWidgets 原生的 ExpandGroupSettingCard，自动适配亮/暗主题，
        自带展开/折叠箭头。每个库一行：图标 + 名称 + 协议/用途描述 + 访问按钮。
        """
        card = ExpandGroupSettingCard(
            FIF.HEART, "开源信息",
            "本项目依赖的开源库、协议与官网，点击展开查看详情")

        # 依赖的开源库（名称, 协议, 用途, 官网/仓库链接）
        for lib_name, lib_license, lib_purpose, lib_url in (
            ("PySide6", "LGPLv3 / 商业双协议", "Qt for Python 图形界面框架",
             "https://www.qt.io/"),
            ("PySide6-Fluent-Widgets", "GPLv3 / 商业双协议",
             "WinUI3 风格组件库（主窗口基于 FluentWindow）",
             "https://qfluentwidgets.com/"),
            ("pyserial", "Python Software Foundation License",
             "串口通信", "https://github.com/pyserial/pyserial"),
            ("matplotlib", "Matplotlib License (PSF based)",
             "数据可视化", "https://matplotlib.org/"),
            ("numpy", "BSD 3-Clause License",
             "数值计算", "https://numpy.org/"),
        ):
            link_btn = self._make_link_button("访问", lib_url)
            content = f"{lib_license} · {lib_purpose}"
            card.addGroup(FIF.CODE, lib_name, content, link_btn)

        # 分组分隔：协议链接
        for proto_name, proto_url, proto_desc in (
            ("PhysChem-DigitizerP 协议",
             "https://github.com/wangzhidong2/PhysChem-DigitizerP/blob/main/LICENSE",
             "GPL-3.0-only · 本应用遵循此协议开源"),
            ("PySide6 许可证",
             "https://www.qt.io/licensing/",
             "LGPLv3 / 商业双协议 · Qt 官方授权说明"),
            ("Fluent-Widgets 许可证",
             "https://github.com/zhiyiYo/PyQt-Fluent-Widgets/blob/main/LICENSE",
             "GPLv3 / 商业双协议 · 组件库授权说明"),
        ):
            link_btn = self._make_link_button("查看", proto_url)
            card.addGroup(FIF.CERTIFICATE, proto_name, proto_desc, link_btn)

        self._open_source_card = card
        return card

    def _on_theme_combo_changed(self, idx: int):
        if not (0 <= idx < len(self._theme_combo_values)):
            return
        # 占位项（深色模式 / 跟随系统）已被禁用，不应触发；防御性忽略。
        if not self._theme_combo.items[idx].isEnabled:
            return
        mode = self._theme_combo_values[idx]
        self._theme_mode = mode
        if mode == "auto":
            # 跟随系统：交给 FluentWidgets 处理 AUTO 主题。
            # 传 "auto" 而非解析后的实际亮暗——change_app_theme 收到 auto
            # 时不再 setTheme(固定主题)，避免把 AUTO 覆盖掉导致主题模式
            # 反复横跳 + 全量刷新死循环。
            setTheme(Theme.AUTO)
            self.theme_change_requested.emit("auto")
        else:
            self.theme_change_requested.emit(mode)

    def _sync_theme_combo_from_current(self):
        """按当前主题模式反向同步下拉框选项。

        用显式维护的 _theme_mode（qconfig.theme 会把 AUTO 解析成
        LIGHT/DARK，无法区分「跟随系统」）。

        必须 blockSignals：setCurrentIndex 会触发 currentIndexChanged，
        进而回调 _on_theme_combo_changed 二次 emit → change_app_theme
        全量刷新递归（主题切换被放大数倍、跟随系统时反复横跳卡死）。
        本方法只是 UI 同步，不应触发任何事件。
        """
        idx = {"light": 0, "dark": 1, "auto": 2}.get(self._theme_mode, 0)
        self._theme_combo.blockSignals(True)
        try:
            self._theme_combo.setCurrentIndex(idx)
        finally:
            self._theme_combo.blockSignals(False)

    def apply_theme(self, theme):
        """主题切换时刷新本页背景、声明块配色与下拉框同步。"""
        # 用存储的引用刷新页面/滚动区背景
        self._scroll.setStyleSheet(scroll_area_style())
        self._content.setStyleSheet(page_bg_style())
        # 自由软件声明块（自定义 QSS 面板，Fluent 不会自动换色）
        apply_notice_theme(getattr(self, '_notice', None))
        # 同步下拉框
        self._sync_theme_combo_from_current()



# ============================================================
# 主窗口 + 动态加载器
# ============================================================
class MainWindow(FluentWindow):
    """主窗口 - 启动时扫描模块目录并动态加载各传感器模块

    基于 FluentWindow（PySide6-Fluent-Widgets），自动获得 WinUI3 风格的
    NavigationInterface（左侧导航）+ stackedWidget（内容栈）+ 主题切换。
    各传感器 widget 通过 addSubInterface 注册到导航。
    """

    def __init__(self):
        super().__init__()

        font = QFont("Segoe UI", 9)
        self.setFont(font)

        self.current_theme = "light"
        # 主题模式（light/dark/auto）：auto 下监听 qconfig.themeChanged，
        # 系统主题变化时自动刷新自定义控件（跟随系统真实生效）
        self._theme_mode = "light"
        # 退出确认状态：closeEvent 延迟弹框（详见 closeEvent 注释）
        self._exit_confirmed = False
        self._exit_dialog_open = False
        self._intro_shown = False   # 启动弹出「项目信息」每次运行只弹一次
        self.modules = {}  # name -> widget
        self.module_widgets = []  # 按注册顺序排列的 widget 列表
        self._nav_icons = {}  # name -> (icon_text, nav_item)，主题切换时重建图标

        self.init_ui()
        # 跟随系统模式下，qfluentwidgets 系统主题监听器改变主题时会广播
        # themeChanged；仅 auto 模式响应，固定模式由 change_app_theme 负责
        from qfluentwidgets import qconfig
        qconfig.themeChanged.connect(self._on_fluent_theme_changed)
        self.apply_modern_style()

    def init_ui(self):
        self.setWindowTitle("PhysChem-DigitizerP")
        # 默认尺寸按屏幕可用区自适应（85%）：小屏（如 1280×680 工作区）
        # 不会溢出屏幕、大屏也不至过大。窗口记忆（上次退出的位置/大小、
        # 最大化状态）优先于此默认值，见 _restore_window_geometry
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            self.resize(int(avail.width() * 0.85), int(avail.height() * 0.85))
        # 窗口记忆：最大化状态取上次退出时的值；位置/大小优先还原记忆值
        self.start_maximized = bool(app_cfg.windowMaximized.value)
        self._restore_window_geometry()
        # FluentWindow 自带 NavigationInterface + stackedWidget，无需手动布局

        # === 加载模块 ===
        # 确定传感器模块目录（与 main.py 同级）
        app_dir = os.path.dirname(os.path.abspath(__file__))
        modules_dir = os.path.join(app_dir, 'sensors')

        discovered = scan_modules(modules_dir)

        # 主页（始终在第 0 位）—— 用 FluentIcon.HOME 注册到导航顶部
        home_page = HomePageWidget()
        home_page.module_clicked.connect(self.on_home_module_clicked)
        home_page.setObjectName("home_page")
        self.addSubInterface(home_page, FIF.HOME, "主页")
        self.modules["主页"] = home_page
        self.module_widgets.append(home_page)

        # 各传感器模块（按发现顺序加载）
        # 图标：用识别区里的文字（V/F/x/pH/v/A）渲染成 QIcon，
        #       而不是 FluentIcon.PLAY（那个是三角形播放图标，不适合传感器）
        home_modules = []  # [(icon, name, category), ...] 给主页用

        for info in discovered:
            cls = getattr(info['module'], info['class_name'])
            try:
                widget = cls()
            except Exception as e:
                log.error("实例化模块 %s 失败: %s", info['name'], e)
                continue

            # FluentWindow.addSubInterface 要求 widget 有 objectName
            # 用模块名作为唯一标识（去掉空格等特殊字符）
            obj_name = "module_" + info['name'].replace(" ", "_").replace("（", "_").replace("）", "_")
            widget.setObjectName(obj_name)
            # 把识别区文字图标（V/F/x/pH/v/A）画成 QIcon
            text_icon = make_text_icon(info.get('icon', '?'))
            nav_item = self.addSubInterface(widget, text_icon, info['name'])
            self._nav_icons[info['name']] = (info.get('icon', '?'), nav_item)
            self.modules[info['name']] = widget
            self.module_widgets.append(widget)

            home_modules.append((info['icon'], info['name'], info['category']))

        # 设置（始终在最后）—— 用 FluentIcon.SETTING 注册到导航底部
        # 用 FluentWidgets SettingCard 系列组件实现的真实设置页
        settings_widget = SettingsWidget()
        settings_widget.setObjectName("settings_page")
        settings_widget.theme_change_requested.connect(self.change_app_theme)
        settings_widget.engine_change_requested.connect(self.change_chart_engine)
        self.addSubInterface(
            settings_widget, FIF.SETTING, "设置",
            position=NavigationItemPosition.BOTTOM
        )
        self.modules["设置"] = settings_widget
        self.module_widgets.append(settings_widget)

        # 把模块列表传给主页
        home_page.set_modules(home_modules)
        # 主页引用（启动时的「项目信息」卡片经它弹出，见 _maybe_show_project_intro）
        self.home_page = home_page

        # 默认显示主页
        self.switchTo(home_page)

        # === 数据总线（核心能力，与插件无关）===
        # 模块 key 用识别区英文名约定：取 objectName 去掉 module_ 前缀；
        # 更稳妥的是模块在 api_snapshot 里自报 key（DataService 兼容两种）
        self.data_service = DataService()
        self._module_keys = {}  # widget -> key
        for info, widget in zip(
                [d for d in discovered if d['name'] in self.modules],
                [self.modules[d['name']] for d in discovered
                 if d['name'] in self.modules]):
            key = self._module_key(info, widget)
            # 优先采用模块 api_snapshot() 自报的 key（如 ultrasonic_displacement），
            # 与模块快照里的 'key' 字段保持一致，避免 URL 与数据错位
            try:
                snap_key = (widget.api_snapshot() or {}).get('key')
                if snap_key:
                    key = snap_key
            except Exception:
                pass
            self._module_keys[widget] = key
            self.data_service.register(key, info['name'], widget)

        # === 插件加载（失败静默，不影响主程序）===
        self.plugins = load_plugins(app_dir)
        self.data_plugin = None
        for plugin in self.plugins:
            try:
                plugin.attach({
                    'service': self.data_service,
                    'app_cfg': app_cfg,
                    'log': log,
                })
                if getattr(plugin, 'name', '') == 'flaskserver':
                    self.data_plugin = plugin
            except Exception as e:
                log.error("插件 attach 失败 %s: %s", plugin, e)
        # 主页数据接口入口卡片（插件缺失时主页保持原样）
        if hasattr(home_page, 'set_data_plugin'):
            home_page.set_data_plugin(self.data_plugin)

    @staticmethod
    def _module_key(info, widget):
        """模块在 API 里的稳定 key：类名蛇形化并去掉 Widget 后缀。"""
        key = info.get('key')
        if key:
            return key
        cls = info['class_name']
        snake = re.sub(r'(?<!^)(?=[A-Z])', '_', cls).lower()
        # 去掉 _widget 后缀与尾随下划线（如 PHSensorWidget -> ph_sensor）
        if snake.endswith('_widget'):
            snake = snake[:-len('_widget')]
        return snake.strip('_')

    def showEvent(self, event):
        """首次显示主窗口后，按配置自动弹出「项目信息」卡片。

        延迟到事件循环里弹（不阻塞 show 本身），且每次运行只弹一次；
        关掉窗口内「启动时自动显示」复选框后，下次启动不再弹出。
        """
        super().showEvent(event)
        if self._intro_shown or not bool(app_cfg.showIntroOnStartup.value):
            return
        self._intro_shown = True
        QTimer.singleShot(400, self._show_project_intro)

    def _show_project_intro(self):
        """弹出「项目信息」卡片（复用主页持有的那一份实例）。"""
        home = getattr(self, 'home_page', None)
        if home is None:
            return
        try:
            home._open_project_dialog()
        except Exception as e:
            log.warning("启动弹出项目信息失败: %s", e)

    def _get_module_desc(self, name):
        """根据模块名返回简短描述"""
        descs = {
            '超声波位移': '测量物体位移和运动轨迹',
            '超声波速度': '回声定位法测量物体速度',
            '力传感器': 'HX711 力/质量传感器测量',
            '电压传感器': 'ADC 电压采集与分压电路换算',
            'pH传感器': '测量溶液酸碱度',
            '电流传感器': 'ADC 原始数据采集',
        }
        return descs.get(name, '传感器数据采集')

    def switch_module(self, index):
        """兼容旧接口：按索引切换（实际用 switchTo(widget)）"""
        if 0 <= index < len(self.module_widgets):
            self.switchTo(self.module_widgets[index])

    def on_home_module_clicked(self, module_name):
        """主页模块卡片点击 → 切换到对应模块"""
        if module_name in self.modules:
            self.switchTo(self.modules[module_name])

    def change_app_theme(self, theme):
        """切换应用主题（light / dark / auto）。

        auto（跟随系统）：设置页已把 qconfig 主题置为 Theme.AUTO，这里
        只按系统实际亮暗刷新自定义控件，**不再调用 setTheme**——否则会把
        AUTO 覆盖成固定主题，导致主题模式与下拉框反复横跳、每次系统主题
        变化都触发秒级全量刷新，界面卡死。
        """
        if theme not in ("light", "dark", "auto"):
            return
        self._theme_mode = theme
        if theme == "auto":
            actual = "dark" if isDarkTheme() else "light"
            self.current_theme = actual
            self._refresh_custom_theme(actual)
            return
        self.current_theme = theme
        self.apply_theme(theme)       # setTheme 固定主题（刷新 FluentWidgets）
        self._refresh_custom_theme(theme)

    def _on_fluent_theme_changed(self, _theme=None):
        """qconfig.themeChanged 回调：仅跟随系统模式下重刷自定义控件。

        固定模式下 setTheme 由 change_app_theme 驱动，其已做全量刷新，
        这里再刷会造成重复开销；auto 模式下系统主题（由 qfluentwidgets
        系统监听器触发）改变时，FluentWidgets 组件自动变色，而自定义
        QSS 控件需要手动刷新——本回调补齐这部分。
        """
        if self._theme_mode != "auto":
            return
        try:
            actual = "dark" if isDarkTheme() else "light"
            self.current_theme = actual
            self._refresh_custom_theme(actual)
        except Exception as e:
            log.warning("跟随系统主题刷新失败: %s", e)

    def _refresh_custom_theme(self, theme):
        """按当前亮/暗主题刷新自定义 widget 颜色（不调用 setTheme）。

        覆盖：导航文字图标重绘 + 设置页 / 主页 / 各传感器模块 apply_theme
        （QScrollArea 背景、QLabel 颜色、图表主题等）。FluentWidgets 组件
        的颜色由 setTheme 统一刷新，不在本方法职责内。
        """
        # 重建侧边栏文字图标（深/浅色下 Normal 状态颜色不同）
        for name, (icon_text, nav_item) in self._nav_icons.items():
            try:
                nav_item.setIcon(make_text_icon(icon_text))
            except Exception as e:
                log.warning("重建模块 %s 导航图标失败: %s", name, e)

        # 先刷新设置页（主题下拉框需要反向同步当前主题）
        if "设置" in self.modules:
            try:
                self.modules["设置"].apply_theme(theme)
            except Exception as e:
                log.warning("设置页主题切换失败: %s", e)

        # 主页（卡片、滚动区背景）
        if "主页" in self.modules:
            try:
                self.modules["主页"].apply_theme(theme)
            except Exception as e:
                log.warning("主页主题切换失败: %s", e)

        # 各传感器模块若支持主题切换则一并刷新
        for name, widget in self.modules.items():
            if name in ("主页", "设置"):
                continue
            if hasattr(widget, 'apply_theme'):
                try:
                    widget.apply_theme(theme)
                except Exception as e:
                    log.warning("模块 %s 主题切换失败: %s", name, e)

    def apply_theme(self, theme):
        """切换 FluentWidgets 主题（light/dark）。

        FluentWindow 自带 WinUI3 风格样式，不再需要手动 QSS。
        setTheme 会自动刷新所有 FluentWidgets 组件的颜色。
        """
        if theme == "dark":
            setTheme(Theme.DARK)
        else:
            setTheme(Theme.LIGHT)

    def change_chart_engine(self, engine):
        """热切换图表引擎：所有已加载模块的 ChartPanel 原地换引擎。

        ChartPanel.set_engine 内部重建控件并重放最近一次绘制内容，
        当前数据无需重新采集即可在另一引擎下显示。
        未安装的引擎请求在此拦截（设置页已灰显，此处为双保险）。
        """
        if not chart_engine_available(engine):
            log.warning("图表引擎 %s 未安装，忽略切换请求", engine)
            return
        count = 0
        for name, widget in self.modules.items():
            if name in ("主页", "设置"):
                continue
            for panel in widget.findChildren(ChartPanel):
                try:
                    panel.set_engine(engine)
                    count += 1
                except Exception as e:
                    log.warning("[%s] 图表引擎切换失败: %s", name, e)
        log.info("✓ 图表引擎已切换为 %s（%d 个图表面板）", engine, count)

    def refresh_chart_fonts(self):
        """按新字体重绘所有图表面板（切换应用字体后调用）。

        matplotlib 的文字由 rcParams 决定（plot 时读取），pyqtgraph 的
        轴标签同理——两者都要重放一次最近事务才会用上新字体。
        """
        count = 0
        for name, widget in self.modules.items():
            if name in ("主页", "设置"):
                continue
            for panel in widget.findChildren(ChartPanel):
                try:
                    if panel._last is not None:
                        panel._commit(panel._last)   # 重放最近一次事务
                    count += 1
                except Exception as e:
                    log.warning("[%s] 图表字体重绘失败: %s", name, e)
        log.info("✓ 已按新字体重绘 %d 个图表面板", count)

    def apply_modern_style(self):
        self.current_theme = "light"
        self.apply_theme("light")

    def _restore_window_geometry(self):
        """窗口记忆：还原上次退出时记住的窗口位置与大小。

        仅在记忆数据合法（尺寸不小于 640×480）且窗口至少一部分仍落在
        当前某块屏幕的可用区内时应用。多屏拔插、分辨率变化导致记忆
        位置跑到屏幕外时放弃还原，保持默认尺寸，避免“打开后找不到窗口”。
        """
        try:
            geo = app_cfg.windowGeometry.value or {}
            rect = QRect(int(geo["x"]), int(geo["y"]),
                         int(geo["w"]), int(geo["h"]))
        except (KeyError, TypeError, ValueError):
            return
        if rect.width() < 640 or rect.height() < 480:
            return
        for screen in QGuiApplication.screens():
            inter = screen.availableGeometry().intersected(rect)
            if inter.width() >= 160 and inter.height() >= 80:
                break
        else:
            log.info("窗口记忆的位置已不在任何屏幕内，使用默认尺寸")
            return
        self.setGeometry(rect)

    def _save_window_state(self):
        """窗口记忆：退出前把位置/大小与最大化状态写入 app_config.json。

        最大化/最小化时记录 normalGeometry（还原前的窗口几何），否则记录
        当前几何；下次启动由 _restore_window_geometry / start_maximized 还原。
        """
        try:
            state = self.windowState()
            maximized = bool(state & Qt.WindowState.WindowMaximized)
            qconfig.set(app_cfg.windowMaximized, maximized)
            if state & (Qt.WindowState.WindowMaximized |
                        Qt.WindowState.WindowMinimized):
                geo = self.normalGeometry()
            else:
                geo = self.geometry()
            qconfig.set(app_cfg.windowGeometry, {
                "x": geo.x(), "y": geo.y(),
                "w": geo.width(), "h": geo.height(),
            })
        except Exception as e:
            log.warning("保存窗口记忆失败: %s", e)

    def closeEvent(self, event):
        """关闭前先弹确认框：未保存实验数据将被销毁。确认后才停止各模块线程。

        注意：确认框**不能**在 closeEvent 内直接 exec()——窗口正处于关闭
        状态时弹出模态对话框，对话框可能无法激活、按钮点击无响应（表现为
        界面卡死）。正确做法：先 event.ignore() 取消本次关闭，再用
        QTimer.singleShot(0) 延迟到正常事件循环里弹框；确认后置
        _exit_confirmed 并再次 close()，此次直接走清理 + 接受关闭。

        子页面销毁不会触发模块自身的 closeEvent，若串口/模拟器线程
        仍在运行，QThread 对象被销毁时会触发 Qt fail-fast 闪退
        （0xC0000409）。确认退出后逐模块调用断开方法（不同模块方法名
        不同：disconnect_all / disconnect_serial）停线程。
        """
        if self._exit_confirmed:
            self._save_window_state()   # 窗口记忆：退出前落盘位置/大小/最大化
            self._stop_module_threads()
            super().closeEvent(event)
            return

        event.ignore()
        if self._exit_dialog_open:
            return  # 已有确认框在等待，避免重复弹框
        self._exit_dialog_open = True
        QTimer.singleShot(0, self._prompt_exit)

    def _prompt_exit(self):
        """在正常事件循环中弹出退出确认框（避免 closeEvent 内嵌套模态循环）。

        用 qfluentwidgets `Dialog`（真正的顶层窗口）而不是 `MessageBox`：
        MessageBox 基于 MaskDialogBase，会被改造成父窗口内部的 WS_CHILD
        叠加层，输入路由依赖 Qt 内部子控件路径，在部分环境下会出现窗口
        能显示但鼠标点击无效（表现为弹窗卡死）。Dialog 是独立顶层窗口，
        输入与焦点处理可靠（与 AI 分析窗口同一组件）。
        """
        self._exit_dialog_open = False
        box = Dialog(
            "退出确认",
            "程序即将退出，所有未保存的实验数据将被销毁。\n确定要退出吗？",
            self,
        )
        box.yesButton.setText("确认退出")
        box.cancelButton.setText("取消")
        box.raise_()
        box.activateWindow()
        if box.exec():
            self._exit_confirmed = True
            self.close()

    def _stop_module_threads(self):
        """逐模块调用断开方法停止串口/模拟器线程（退出清理）。"""
        for name, widget in self.modules.items():
            if name in ("主页", "设置"):
                continue
            for meth in ("disconnect_all", "disconnect_serial"):
                dispose = getattr(widget, meth, None)
                if callable(dispose):
                    try:
                        dispose()
                    except Exception as e:
                        log.warning("退出清理 [%s.%s] 失败: %s", name, meth, e)
                    break


APP_USER_MODEL_ID = 'PhysChem.DigitizerP'


def _set_windows_appusermodelid():
    """设置 Windows AppUserModelID。

    用 python.exe 启动时，任务栏按 AppUserModelID 分组图标；未设置时
    沿用 python.exe 自身图标，窗口 QIcon 对任务栏无效。设置唯一 ID 后
    任务栏才会显示窗口图标（标题栏图标不受影响，一直正常）。
    """
    if sys.platform == 'win32':
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                APP_USER_MODEL_ID)
        except Exception:
            pass


def _apply_taskbar_identity(window):
    """给主窗口写入任务栏身份属性（显示名 / 图标 / AUMID / 重启命令）。

    仅设置进程级 AUMID 只影响分组：任务栏按钮的名称与图标仍会回退到
    宿主的 python.exe（显示为“Python”）。参照 Chromium 的做法，在窗口
    首次显示前通过 SHGetPropertyStoreForWindow 写入 PKEY_AppUserModel_*：
      - ID                          : 与进程 AUMID 一致，保证分组唯一
      - RelaunchCommand             : 固定到任务栏后的启动命令
      - RelaunchDisplayNameResource : 任务栏按钮 / 跳转列表显示名
      - RelaunchIconResource        : 任务栏按钮图标（docs/images/icon.ico）

    属性必须在 window.show() **之前**写入，Windows 才会采用；
    失败静默忽略（仅影响任务栏外观，不影响功能）。
    """
    if sys.platform != 'win32':
        return
    import ctypes
    from ctypes import wintypes, byref, POINTER

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8),
        ]

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

    class _PropUnion(ctypes.Union):
        _fields_ = [("pwszVal", wintypes.LPWSTR), ("pad", ctypes.c_byte * 16)]

    class PROPVARIANT(ctypes.Structure):
        _fields_ = [
            ("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort),
            ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
            ("u", _PropUnion),
        ]

    def _guid(text):
        import uuid
        u = uuid.UUID(text)
        return GUID(u.time_low, u.time_mid, u.time_hi_version,
                    (ctypes.c_ubyte * 8)(*u.bytes[8:]))

    try:
        # winId() 会立即创建原生窗口，保证属性写入先于首次显示
        hwnd = int(window.winId())
        store = ctypes.c_void_p()
        shell32 = ctypes.windll.shell32
        shell32.SHGetPropertyStoreForWindow.restype = ctypes.c_long
        shell32.SHGetPropertyStoreForWindow.argtypes = [
            wintypes.HWND, POINTER(GUID), POINTER(ctypes.c_void_p)]
        hr = shell32.SHGetPropertyStoreForWindow(
            wintypes.HWND(hwnd),
            byref(_guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")),
            byref(store))
        if hr != 0 or not store:
            return

        # IPropertyStore vtable: ... GetValue(5) / SetValue(6) / Commit(7)
        vtbl = ctypes.cast(store, POINTER(POINTER(ctypes.c_void_p))).contents
        SetValue = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, POINTER(PROPERTYKEY),
            POINTER(PROPVARIANT))(vtbl[6])
        Commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtbl[7])

        main_script = os.path.abspath(__file__)
        if getattr(sys, 'frozen', False):      # PyInstaller 打包：exe 自身
            relaunch = f'"{sys.executable}"'
        else:                                  # 源码运行：python + main.py
            relaunch = f'"{sys.executable}" "{main_script}"'
        icon_path = os.path.join(
            os.path.dirname(main_script), 'docs', 'images', 'icon.ico')

        appid_fmtid = _guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3")
        # 属性 pid：2=RelaunchCommand 3=RelaunchIconResource
        #          4=RelaunchDisplayNameResource 5=ID
        for pid, value in (
            (5, APP_USER_MODEL_ID),
            (2, relaunch),
            (4, 'PhysChem-DigitizerP'),
            (3, icon_path),
        ):
            buf = ctypes.create_unicode_buffer(value)
            pv = PROPVARIANT()
            pv.vt = 31                          # VT_LPWSTR
            pv.u.pwszVal = ctypes.cast(buf, wintypes.LPWSTR)
            SetValue(store, byref(PROPERTYKEY(appid_fmtid, pid)), byref(pv))
        Commit(store)
    except Exception as e:
        log.warning("设置任务栏身份失败: %s", e)


def _install_qt_warning_filter():
    """过滤两条已知无害的 Qt 内部告警，避免控制台刷屏（不影响功能）。

    - QFont::setPointSize: Point size <= 0 ...：Qt 富文本/Markdown 文本引擎
      在像素字号字体（qfluentwidgets 组件统一用像素字号）上换算点值时触发。
    - QWidgetWindow(...) must be a top level window.：Qt 为窗口设置 transient
      parent 时对 qfluentwidgets 掩码对话框（AI 分析/校准等）父窗口的内部
      检查，对话框功能与显示不受影响。

    仅屏蔽这两条文案；其余 Qt 消息原样交给安装前的处理器（无则写 stderr）。
    """
    from PySide6.QtCore import qInstallMessageHandler

    suppressed = ("QFont::setPointSize: Point size <= 0",
                  "must be a top level window")
    state = {"prev": None}

    def handler(msg_type, context, message):
        if any(k in message for k in suppressed):
            return
        prev = state["prev"]
        if prev is not None:
            prev(msg_type, context, message)
        else:
            sys.stderr.write(message + "\n")

    state["prev"] = qInstallMessageHandler(handler)


def main():
    _set_windows_appusermodelid()
    _install_qt_warning_filter()
    setup_logging()          # 按 app_config.json 初始化运行日志（默认静默）
    app = QApplication(sys.argv)
    # 应用图标（.ico 同时设在 app 和 window 上）
    icon_path = str(Path(__file__).parent / "docs" / "images" / "icon.ico")
    app_icon = QIcon(icon_path)
    # 显式注册各尺寸，避免任务栏按需缩放时取不到合适位图
    for size in (16, 24, 32, 48, 64, 128, 256):
        app_icon.addFile(icon_path, QSize(size, size))
    app.setWindowIcon(app_icon)
    # 内嵌字体：把 assets/fonts/MiSans-Regular.ttf 注册进 Qt（需在 QApplication
    # 之后），再按 app_config.json 的 General.FontFamily 应用。必须在建窗口前
    # 完成——FluentWidgets 组件的字体族来自 qconfig.fontFamilies，晚了就得全量重刷
    try:
        load_embedded_font()
        apply_app_font()
    except Exception as e:
        log.warning("应用字体初始化失败: %s", e)
    # 让 ComboBox 展开时箭头朝上（FluentWidgets 默认始终朝下）
    patch_combobox_arrow_flip()
    # 主题色：「跟随系统主题色」模式读取 Windows 强调色（不落盘）；
    # 自定义模式沿用配置（默认蓝色）。在窗口创建前应用，组件直接以新色渲染
    try:
        if app_cfg.themeColorMode.value == "system":
            set_app_theme_color(system_accent_color(), save=False)
    except Exception as e:
        log.warning("应用系统主题色失败: %s", e)
    # 监听 Windows 系统强调色变化（仅「跟随系统主题色」模式生效）；
    # 引用挂在 app 上防止被垃圾回收
    try:
        from core import SystemAccentListener
        app._system_accent_listener = SystemAccentListener()
        app.installNativeEventFilter(app._system_accent_listener)
    except Exception as e:
        log.warning("安装系统强调色监听失败: %s", e)
    # FluentWidgets 自带 WinUI3 风格，不再需要 Fusion
    window = MainWindow()
    window.setWindowIcon(app_icon)
    # 任务栏身份（显示名/图标）必须在首次 show() 前写入
    _apply_taskbar_identity(window)
    # 窗口记忆：上次退出时最大化则最大化启动，否则按记忆的位置/大小显示
    # （init_ui 已还原窗口几何；首次启动/记忆失效时为自适应的默认尺寸）
    if window.start_maximized:
        window.showMaximized()
    else:
        window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
