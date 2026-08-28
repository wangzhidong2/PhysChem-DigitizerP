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
- 动态模块加载器：扫描 传感器代码/ 目录，importlib 加载各传感器模块

新增传感器模块时无需修改本文件，只需在 传感器代码/ 下新建子目录并放入
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
    QPushButton, QFrame, QStackedWidget, QScrollArea, QLineEdit,
    QFileDialog,
)
from PySide6.QtCore import Qt, Signal, QSize, QRect
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter, QColor, QFontMetrics, QGuiApplication

# FluentWidgets — WinUI3 风格组件库（社区版，GPLv3 + 商业双协议）
# 文档：https://qfluentwidgets.com/
from qfluentwidgets import (
    FluentWindow, FluentIcon as FIF, NavigationItemPosition,
    Theme, setTheme, PushButton, PrimaryPushButton,
    ComboBox, InfoBar, InfoBarPosition, BodyLabel,
    TitleLabel, SubtitleLabel, CaptionLabel, HyperlinkButton,
    SettingCard, SettingCardGroup, ExpandGroupSettingCard, isDarkTheme,
    SwitchSettingCard, MessageBox, qconfig, IndicatorPosition,
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
    patch_combobox_arrow_flip, CollapsibleCard,
    page_bg_style, scroll_area_style, _theme_colors, app_cfg,
    ChartPanel, chart_engine_available, resolve_chart_engine,
    clear_sensor_config, export_sensor_config, import_sensor_config,
)


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

    # 三种状态：Normal(深色文字)/Active(强调色)/Selected(白色，选中时背景已是 accent)
    for mode, color in (
        (QIcon.Normal, QColor("#1a1a1a")),
        (QIcon.Active, QColor("#005fb8")),
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
        print(f"⚠️ 读取模块文件失败 {file_path}: {e}")
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
        modules_dir: 传感器代码目录的绝对路径

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
        print(f"⚠️ 模块目录不存在: {modules_dir}")
        return discovered

    # 遍历 传感器代码/ 下的每个子目录
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
                print(f"⏭️ 跳过（无识别区）: {py_file}")
                continue

            # importlib 动态加载
            mod_name = f"_sensor_module_{base[:-3]}"
            spec = importlib.util.spec_from_file_location(mod_name, py_file)
            if spec is None or spec.loader is None:
                print(f"⚠️ 无法加载模块: {py_file}")
                continue

            mod = importlib.util.module_from_spec(spec)
            try:
                sys.modules[mod_name] = mod
                spec.loader.exec_module(mod)
            except Exception as e:
                print(f"❌ 模块加载失败 {py_file}: {e}")
                continue

            class_name = meta['class']
            if not hasattr(mod, class_name):
                print(f"❌ 模块未定义类 {class_name}: {py_file}")
                continue

            discovered.append({
                'name': meta['name'],
                'icon': meta['icon'],
                'category': meta['category'],
                'class_name': class_name,
                'module': mod,
                'file_path': py_file,
            })
            print(f"✓ 已加载模块: {meta['name']} ({meta['category']}) <- {base}")

    discovered.sort(key=lambda x: (x['category'], x['name']))
    return discovered


# ============================================================
# 主页
# ============================================================
class HomePageWidget(QWidget):
    """主页面 - 基于 FluentWidgets 原生可折叠卡片（ExpandGroupSettingCard）"""

    module_clicked = Signal(str)

    # 卡片统一白色背景样式（覆盖 ExpandSettingCard 默认半透明灰）
    CARD_QSS = """
        ExpandSettingCard {
            border: 1px solid #e5e5e5;
            border-radius: 8px;
            background-color: #ffffff !important;
        }
        ExpandSettingCard > #view {
            background: #ffffff !important;
            border: none;
            border-bottom-left-radius: 8px;
            border-bottom-right-radius: 8px;
        }
        ExpandSettingCard > #scrollWidget {
            border: none;
            background-color: #ffffff !important;
        }
        /* 内容物容器继承卡片白色（默认是 #f3f3f3 浅灰） */
        ExpandSettingCard #view GroupWidget,
        ExpandSettingCard #view GroupSeparator,
        ExpandSettingCard #view SettingIconWidget,
        ExpandSettingCard #view QWidget#scrollWidget {
            background-color: #ffffff !important;
            border: none;
        }
        /* BodyLabel 默认透明，但叠在浅灰容器上显灰，强制白底 */
        ExpandSettingCard #view BodyLabel {
            background-color: #ffffff !important;
            border: none;
        }
    """

    def __init__(self):
        super().__init__()
        self._modules = []  # [(icon, name, category), ...]
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
        self.content_layout.setContentsMargins(24, 16, 24, 18)
        self.content_layout.setSpacing(10)

        # 页面标题：用 FluentWidgets TitleLabel 自动适配主题
        title = TitleLabel("主页")
        self.content_layout.addWidget(title)

        # ========== 项目信息卡片（不可折叠） ==========
        info_card = self._build_info_card()
        self._expand_and_lock(info_card)

        # ========== 项目地址（可折叠卡片，默认展开） ==========
        repo_card = self._build_repo_card()
        self._default_expand(repo_card)

        # ========== 传感器模块（动态填充可折叠卡片，默认展开） ==========
        self.modules_container = QWidget()
        self.modules_container_layout = QVBoxLayout(self.modules_container)
        self.modules_container_layout.setContentsMargins(0, 0, 0, 0)
        self.modules_container_layout.setSpacing(10)
        self.content_layout.addWidget(self.modules_container)

        self.content_layout.addStretch()
        self.scroll.setWidget(self.content)
        main_layout.addWidget(self.scroll)

    def _apply_card_style(self, card):
        """给 ExpandGroupSettingCard 应用统一白色背景样式。

        样式表对某些 FluentWidgets 子组件（GroupWidget/SettingIconWidget 等）不生效，
        因为它们用 paintEvent 直接绘制背景。所以除样式表外，再递归给所有子 QWidget
        设置 autoFillBackground + 白色 palette，强制白底。
        """
        card.setStyleSheet(self.CARD_QSS)
        try:
            from PySide6.QtGui import QPalette, QColor
            white = QPalette()
            white.setColor(QPalette.ColorRole.Window, QColor("#ffffff"))
            # 卡片自身
            card.setAutoFillBackground(True)
            card.setPalette(white)
            # view + scrollWidget
            for name in ("view", "scrollWidget"):
                w = getattr(card, name, None)
                if w is not None:
                    w.setAutoFillBackground(True)
                    w.setPalette(white)
                    w.setStyleSheet("background-color: #ffffff; border: none;")
            # 递归所有子 QWidget
            for child in card.findChildren(QWidget):
                # 保留标签自身的彩色背景（如 GPL-3.0 开源绿底）
                if isinstance(child, QLabel) and child.styleSheet() and "background-color" in child.styleSheet():
                    continue
                child.setAutoFillBackground(True)
                child.setPalette(white)
        except Exception as e:
            print(f"⚠️ _apply_card_style palette: {e}")
        return card

    def _build_info_card(self):
        """项目信息卡片：项目名 + 简介 + 标签（不可折叠）。"""
        card = ExpandGroupSettingCard(
            FIF.HOME, "PhysChem-DigitizerP",
            "基于 Arduino/ESP32 的低成本理化实验数字化采集系统")
        self._apply_card_style(card)

        # 项目简介（content 留空，避免与副标题重复的灰色注释）
        desc = BodyLabel(
            "为中学和大学物理/化学实验室提供低成本、高精度的传感器解决方案。"
            "采用模块化架构，新增传感器只需丢文件，无需修改主程序。"
        )
        desc.setWordWrap(True)
        card.addGroup(FIF.INFO, "项目简介", "", desc)

        # 标签
        tags = QHBoxLayout()
        tags.setSpacing(8)
        for text, bg, fg in (
            ("GPL-3.0 开源", "#e8f5e9", "#2e7d32"),
            ("教学实验", "#f3e5f5", "#7b1fa2"),
            ("模块化架构", "#e3f2fd", "#1565c0"),
        ):
            tag = QLabel(text)
            tag.setFont(QFont("Segoe UI", 9))
            tag.setStyleSheet(f"""
                background-color: {bg};
                color: {fg};
                border-radius: 10px;
                padding: 4px 12px;
            """)
            tags.addWidget(tag)
        tags.addStretch()

        tags_widget = QWidget()
        tags_widget.setLayout(tags)
        card.addGroup(FIF.TAG, "标签", "", tags_widget)

        self.content_layout.addWidget(card)
        return card

    def _load_platform_icon(self, svg_name, fallback=FIF.CODE):
        """加载本地 SVG 平台 logo，失败回退 FluentIcon。"""
        path = os.path.join(self._img_dir, svg_name)
        pix = QPixmap(path)
        if not pix.isNull():
            return QIcon(pix)
        return fallback

    def _build_repo_card(self):
        """项目地址可折叠卡片：3 平台 URL，可复制可访问。"""
        gitee_icon = self._load_platform_icon("gitee.svg")
        gitcode_icon = self._load_platform_icon("gitcode.svg")

        card = ExpandGroupSettingCard(
            FIF.LINK, "项目地址",
            "GitHub / Gitee / GitCode 三平台仓库地址")
        self._apply_card_style(card)

        repo_urls = [
            ("GitHub", "https://github.com/wangzhidong2/PhysChem-DigitizerP",
             FIF.GITHUB),
            ("Gitee", "https://gitee.com/wangzhidong2/PhysChem-DigitizerP",
             gitee_icon),
            ("GitCode", "https://gitcode.com/wangzhidong2/PhysChem-DigitizerP",
             gitcode_icon),
        ]

        # 每个平台一行：URL 输入框（加宽完整显示）+ 复制按钮 + 访问按钮
        for name, url, icon in repo_urls:
            row = QHBoxLayout()
            row.setSpacing(8)

            url_edit = QLineEdit(url)
            url_edit.setReadOnly(True)
            url_edit.setFont(QFont("Consolas", 10))
            url_edit.setCursor(Qt.CursorShape.IBeamCursor)
            url_edit.setMinimumWidth(420)  # 加宽，完整显示整个 URL
            url_edit.setToolTip("点击全选，Ctrl+C 复制")
            row.addWidget(url_edit, stretch=1)

            copy_btn = PushButton("复制")
            copy_btn.setFixedHeight(30)
            copy_btn.setFixedWidth(64)
            copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            copy_btn.clicked.connect(lambda _=False, u=url: self._copy_to_clipboard(u))
            row.addWidget(copy_btn)

            open_btn = PushButton("访问")
            open_btn.setFixedHeight(30)
            open_btn.setFixedWidth(64)
            open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            open_btn.clicked.connect(lambda _=False, u=url: webbrowser.open(u))
            row.addWidget(open_btn)

            row_widget = QWidget()
            row_widget.setLayout(row)
            # content 留空，避免灰色重复注释
            card.addGroup(icon, name, "", row_widget)

        self.content_layout.addWidget(card)
        return card

    def _rebuild_module_cards(self):
        """根据 self._modules 重建模块卡片（按物理/化学分组）。"""
        # 清空旧卡片
        while self.modules_container_layout.count():
            item = self.modules_container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 按类别分组
        categories = {}
        for icon, name, cat in self._modules:
            categories.setdefault(cat, []).append((icon, name))

        if categories:
            card = self._build_module_card(categories)
            self.modules_container_layout.addWidget(card)

    def _build_module_card(self, categories):
        """创建传感器模块可折叠卡片，按物理/化学分组。

        每个模块一行：模块自己的图标文字 + 名称 + 进入按钮。
        """
        card = ExpandGroupSettingCard(
            FIF.MENU, "传感器模块",
            "点击展开查看所有传感器模块")
        self._apply_card_style(card)

        cat_names = {
            'physics': '物理实验模块',
            'chemistry': '化学实验模块',
        }

        for cat_key in ['physics', 'chemistry']:
            if cat_key not in categories or not categories[cat_key]:
                continue

            display_name = cat_names.get(cat_key, cat_key)
            mods = categories[cat_key]

            for icon_text, name in mods:
                enter_btn = PushButton("进入")
                enter_btn.setFixedHeight(30)
                enter_btn.setFixedWidth(64)
                enter_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                enter_btn.clicked.connect(
                    lambda _=False, n=name: self.on_module_clicked(n))

                # 用模块自己的图标文字（icon_text）作为图标
                module_icon = make_text_icon(icon_text, size=64)
                content = f"{display_name} · {len(mods)} 个模块"
                card.addGroup(module_icon, name, content, enter_btn)

        # 模块卡片默认展开
        self._default_expand(card)
        return card

    @staticmethod
    def _default_expand(card):
        """默认展开可折叠卡片（保留折叠功能）。"""
        try:
            card.setExpand(True)
        except Exception:
            pass

    @staticmethod
    def _expand_and_lock(card):
        """默认展开可折叠卡片，并隐藏折叠按钮使其不可折叠。

        同时把内部 #view 背景设为透明，让展开内容区继承卡片整体背景色，
        避免 header（透明）与 view（半透明白）背景不一致的视觉割裂。
        """
        try:
            card.setExpand(True)
        except Exception:
            pass
        try:
            card.card.expandButton.hide()
            # 断开折叠按钮的点击信号，防止点击 header 任意位置触发折叠
            try:
                card.card.expandButton.clicked.disconnect()
            except Exception:
                pass
            # 阻断 HeaderSettingCard.eventFilter 里的"点击→折叠"链路
            card.card.eventFilter = lambda obj, e: False
        except Exception:
            pass

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
        """主题切换：FluentWidgets 原生组件自动适配，仅刷新页面背景。"""
        self.scroll.setStyleSheet(scroll_area_style())
        self.content.setStyleSheet(page_bg_style())


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
    样式自动适配亮/暗主题。当前包含三组：
    - 个性化：应用主题（亮色可用；深色模式 / 跟随系统开发中）
    - 关于：项目名、版本、许可证、源码仓库
    - 反馈：issue 链接
    """

    theme_change_requested = Signal(str)  # 'light' / 'dark'
    engine_change_requested = Signal(str)  # 'matplotlib' / 'pyqtgraph'

    APP_VERSION = "1.3.1"

    def __init__(self):
        super().__init__()
        # 深色模式 / 跟随系统暂未完成（字体颜色有问题），先只做浅色；
        # 后两项仅占位，灰显不可点击并标注「（开发中）」。
        self._theme_combo_items = ["浅色模式", "深色模式", "跟随系统"]
        self._theme_combo_values = ["light", "dark", "auto"]
        # 「清除用户设置」程序内开启保存开关时，跳过开启确认框（用户已确认过）
        self._suppress_persistence_confirm = False
        self.init_ui()
        # 仅支持浅色：固定选中亮色
        self._theme_combo.setCurrentIndex(0)

    def init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(scroll_area_style())

        self._content = QWidget()
        self._content.setStyleSheet(page_bg_style())
        layout = QVBoxLayout(self._content)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)

        # 页面标题：用 TitleLabel 自动适配主题
        title = TitleLabel("设置")
        layout.addWidget(title)

        # ===== 个性化分组 =====
        group_personal = SettingCardGroup("个性化", self._content)
        self._theme_card = self._build_theme_card(group_personal)
        group_personal.addSettingCard(self._theme_card)
        group_personal.addSettingCard(self._build_persistence_card())
        group_personal.addSettingCard(self._build_config_management_card())
        group_personal.addSettingCard(self._build_engine_card())
        layout.addWidget(group_personal)

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

        深色模式 / 跟随系统尚未完成，仅作占位：禁用且标注「（开发中）」，
        当前只允许选择亮色。
        """
        card = SettingCard(FIF.PALETTE, "应用主题",
                           "切换亮色 / 深色模式 / 跟随系统", parent)
        combo = ComboBox(card)
        combo.addItems(self._theme_combo_items)
        combo.setMinimumWidth(160)
        # 占位项灰显不可点击 + 标注开发中
        combo.setItemEnabled(1, False)  # 深色模式
        combo.setItemEnabled(2, False)  # 跟随系统
        combo.setItemText(1, "深色模式（开发中）")
        combo.setItemText(2, "跟随系统（开发中）")
        combo.currentIndexChanged.connect(self._on_theme_combo_changed)
        card.hBoxLayout.addWidget(combo)
        card.hBoxLayout.addSpacing(16)
        self._theme_combo = combo
        return card

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
            InfoBar.success(
                title="导出成功",
                content=f"配置已导出到 {msg}",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self,
            )
        else:
            InfoBar.error(
                title="导出失败",
                content=msg,
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )

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
            InfoBar.success(
                title="导入成功",
                content=f"{msg}，重启程序后生效",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self,
            )
        else:
            InfoBar.error(
                title="导入失败",
                content=msg,
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )

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
            InfoBar.success(
                title="已清除",
                content="用户配置已删除，重启程序后全部恢复默认值",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )
        else:
            InfoBar.error(
                title="清除失败",
                content="配置文件删除失败，请查看控制台输出",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )

    def _build_engine_card(self):
        """图表引擎切换卡片：matplotlib / pyqtgraph 运行时热切换。

        - matplotlib：默认引擎，静态渲染美观
        - pyqtgraph：高性能，内置缩放/平移交互
        选择立即生效：所有已打开模块的图表原地换引擎并重放当前数据；
        同时写入 app_config.json，下次启动沿用。

        引擎缺失时优雅降级：
        - 未安装的引擎选项灰显不可点击（副标题标注缺失情况）
        - 配置的引擎被卸载时显示实际生效引擎（已自动降级）
        """
        self._engine_values = ["matplotlib", "pyqtgraph"]
        labels = ["matplotlib（默认）", "pyqtgraph（高性能）"]
        available = []
        for i, engine in enumerate(self._engine_values):
            if chart_engine_available(engine):
                available.append(engine)
            else:
                labels[i] += "（未安装）"
        # 副标题按安装情况给出提示
        if len(available) == len(self._engine_values):
            content = "matplotlib 静态美观 / pyqtgraph 高性能可交互，切换立即生效"
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
            ("bleak", "MIT License",
             "BLE 无线通信（可选依赖）",
             "https://github.com/hbldh/bleak"),
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
        if mode == "auto":
            # 跟随系统：交给 FluentWidgets 处理 AUTO 主题
            setTheme(Theme.AUTO)
            # 实际亮/暗由系统决定，通知主窗口刷新自定义 widget
            actual = "dark" if isDarkTheme() else "light"
            self.theme_change_requested.emit(actual)
        else:
            self.theme_change_requested.emit(mode)

    def _sync_theme_combo_from_current(self):
        """根据当前 FluentWidgets 主题，反向同步下拉框选项。

        当前仅支持浅色，始终选中亮色；深色 / 跟随系统为占位项不选中。
        """
        self._theme_combo.setCurrentIndex(0)

    def apply_theme(self, theme):
        """主题切换时刷新本页背景与下拉框同步。"""
        # 用存储的引用刷新页面/滚动区背景
        self._scroll.setStyleSheet(scroll_area_style())
        self._content.setStyleSheet(page_bg_style())
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
        self.modules = {}  # name -> widget
        self.module_widgets = []  # 按注册顺序排列的 widget 列表

        self.init_ui()
        self.apply_modern_style()

    def init_ui(self):
        self.setWindowTitle("PhysChem-DigitizerP")
        self.resize(1200, 800)
        # FluentWindow 自带 NavigationInterface + stackedWidget，无需手动布局

        # === 加载模块 ===
        # 确定传感器代码目录（与 main.py 同级）
        app_dir = os.path.dirname(os.path.abspath(__file__))
        modules_dir = os.path.join(app_dir, '传感器代码')

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
                print(f"❌ 实例化模块 {info['name']} 失败: {e}")
                continue

            # FluentWindow.addSubInterface 要求 widget 有 objectName
            # 用模块名作为唯一标识（去掉空格等特殊字符）
            obj_name = "module_" + info['name'].replace(" ", "_").replace("（", "_").replace("）", "_")
            widget.setObjectName(obj_name)
            # 把识别区文字图标（V/F/x/pH/v/A）画成 QIcon
            text_icon = make_text_icon(info.get('icon', '?'))
            self.addSubInterface(widget, text_icon, info['name'])
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

        # 默认显示主页
        self.switchTo(home_page)

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
        """切换应用主题（light/dark）。

        流程：
        1. 先切换 FluentWidgets 主题（setTheme）—— 这会自动刷新所有
           FluentWidgets 组件（ComboBox/PushButton/SettingCard/...）的颜色；
        2. 再通知各页面 apply_theme() 刷新自定义 widget 的硬编码颜色
           （QScrollArea 背景、QLabel 颜色、CollapsibleCard 等）。
        """
        if theme not in ("light", "dark"):
            return
        self.current_theme = theme
        self.apply_theme(theme)

        # 先刷新设置页（主题下拉框需要反向同步当前主题）
        if "设置" in self.modules:
            try:
                self.modules["设置"].apply_theme(theme)
            except Exception as e:
                print(f"⚠️ 设置页主题切换失败: {e}")

        # 主页（卡片、滚动区背景）
        if "主页" in self.modules:
            try:
                self.modules["主页"].apply_theme(theme)
            except Exception as e:
                print(f"⚠️ 主页主题切换失败: {e}")

        # 各传感器模块若支持主题切换则一并刷新
        for name, widget in self.modules.items():
            if name in ("主页", "设置"):
                continue
            if hasattr(widget, 'apply_theme'):
                try:
                    widget.apply_theme(theme)
                except Exception as e:
                    print(f"⚠️ 模块 {name} 主题切换失败: {e}")

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
            print(f"⚠️ 图表引擎 {engine} 未安装，忽略切换请求")
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
                    print(f"⚠️ [{name}] 图表引擎切换失败: {e}")
        print(f"✓ 图表引擎已切换为 {engine}（{count} 个图表面板）")

    def apply_modern_style(self):
        self.current_theme = "light"
        self.apply_theme("light")


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
                'PhysChem.DigitizerP')
        except Exception:
            pass


def main():
    _set_windows_appusermodelid()
    app = QApplication(sys.argv)
    # 应用图标（.ico 同时设在 app 和 window 上）
    icon_path = str(Path(__file__).parent / "docs" / "images" / "icon.ico")
    app_icon = QIcon(icon_path)
    # 显式注册各尺寸，避免任务栏按需缩放时取不到合适位图
    for size in (16, 24, 32, 48, 64, 128, 256):
        app_icon.addFile(icon_path, QSize(size, size))
    app.setWindowIcon(app_icon)
    # 让 ComboBox 展开时箭头朝上（FluentWidgets 默认始终朝下）
    patch_combobox_arrow_flip()
    # FluentWidgets 自带 WinUI3 风格，不再需要 Fusion
    window = MainWindow()
    window.setWindowIcon(app_icon)
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
