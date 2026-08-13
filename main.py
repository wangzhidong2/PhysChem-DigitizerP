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

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QStackedWidget, QScrollArea, QLineEdit,
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
    SettingCard, SettingCardGroup, qconfig, isDarkTheme,
)

# 公共模块（与各传感器模块共享）
from core import (
    card_style, primary_btn_style, accent_btn_style,
    patch_combobox_arrow_flip, CollapsibleCard,
    page_bg_style, scroll_area_style, _theme_colors,
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
    font = QFont("Microsoft YaHei", int(size * 0.9))
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
    """主页面 - 现代化风格卡片布局（动态接收模块列表）"""

    module_clicked = Signal(str)

    CARD_STYLE = """
        QWidget#card {
            background-color: #ffffff;
            border: 1px solid #e5e5e5;
            border-radius: 8px;
        }
        QWidget#card QWidget {
            background-color: transparent;
        }
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
        QWidget#card QAbstractScrollArea {
            background-color: #ffffff;
        }
    """

    CARD_HOVER_STYLE = """
        QPushButton#module_item {
            background-color: transparent;
            border: none;
            border-radius: 6px;
            text-align: left;
            padding: 12px 16px;
        }
        QPushButton#module_item:hover { background-color: #f0f0f0; }
        QPushButton#module_item:pressed { background-color: #e5e5e5; }
    """

    def __init__(self):
        super().__init__()
        self._modules = []  # [(icon, name, category), ...]
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
        self.content.setStyleSheet(
            f"QWidget#home_content {{ background: {_theme_colors()['page_bg']}; }}")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(24, 16, 24, 18)
        self.content_layout.setSpacing(10)

        # 页面标题：用 FluentWidgets TitleLabel 自动适配主题
        title = TitleLabel("主页")
        self.content_layout.addWidget(title)

        # ========== 卡片1：项目信息 ==========
        card1 = QWidget()
        card1.setObjectName("card")
        card1.setStyleSheet(self.CARD_STYLE)
        card1_layout = QVBoxLayout(card1)
        card1_layout.setContentsMargins(24, 16, 24, 16)
        card1_layout.setSpacing(10)

        # 顶部：标题区（左）+ 仓库按钮（右）
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(20)

        # 左：项目名（用 SubtitleLabel 自动适配主题）
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        app_name = SubtitleLabel("PhysChem-DigitizerP")
        info_layout.addWidget(app_name)

        header_row.addLayout(info_layout)
        header_row.addStretch()

        card1_layout.addLayout(header_row)

        # 分隔线
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("color: #ebebeb;")
        card1_layout.addWidget(separator)

        # 项目简介
        desc_label = QLabel(
            "基于 Arduino/ESP32 的低成本理化实验数字化采集系统，"
            "为中学和大学物理/化学实验室提供低成本、高精度的传感器解决方案。"
        )
        desc_label.setWordWrap(True)
        desc_label.setFont(QFont("Microsoft YaHei", 11))
        desc_label.setStyleSheet("color: #444444; line-height: 1.6;")
        card1_layout.addWidget(desc_label)

        # 标签
        tags_layout = QHBoxLayout()
        tags_layout.setSpacing(8)
        tags = [
            ("GPL-3.0 开源", "#e8f5e9", "#2e7d32"),
            ("教学实验", "#f3e5f5", "#7b1fa2"),
            ("模块化架构", "#e3f2fd", "#1565c0"),
        ]
        for text, bg, fg in tags:
            tag = QLabel(text)
            tag.setFont(QFont("Microsoft YaHei", 9))
            tag.setStyleSheet(f"""
                background-color: {bg};
                color: {fg};
                border-radius: 10px;
                padding: 4px 12px;
            """)
            tags_layout.addWidget(tag)
        tags_layout.addStretch()
        card1_layout.addLayout(tags_layout)

        self.content_layout.addWidget(card1)

        # ========== 卡片2：项目地址（可折叠，3 平台，可复制可访问） ==========
        # 内容区（不含标题，标题由 CollapsibleCard 的 header 提供）
        repo_content = QWidget()
        repo_card_layout = QVBoxLayout(repo_content)
        repo_card_layout.setContentsMargins(24, 4, 24, 14)
        repo_card_layout.setSpacing(6)

        repo_card_layout.addSpacing(2)

        # 收集所有 url_edit 以便主题切换时刷新（它们用 _theme_colors() 预烘焙了 QSS）
        self._url_edits = []

        # 3 个平台 URL 行
        repo_urls = [
            ("GitHub",  "https://github.com/wangzhidong2/PhysChem-DigitizerP"),
            ("Gitee",   "https://gitee.com/wangzhidong2/PhysChem-DigitizerP"),
            ("GitCode", "https://gitcode.com/wangzhidong2/PhysChem-DigitizerP"),
        ]
        for i, (name, url) in enumerate(repo_urls):
            row = QHBoxLayout()
            row.setSpacing(10)

            name_lbl = QLabel(name)
            name_lbl.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
            name_lbl.setStyleSheet("color: #0078d4;")
            name_lbl.setFixedWidth(64)
            row.addWidget(name_lbl)

            url_edit = QLineEdit(url)
            url_edit.setReadOnly(True)
            url_edit.setFont(QFont("Consolas", 10))
            url_edit.setStyleSheet(self._url_edit_qss())
            url_edit.setCursor(Qt.CursorShape.IBeamCursor)
            url_edit.setToolTip("点击全选，Ctrl+C 复制")
            row.addWidget(url_edit, stretch=1)
            self._url_edits.append(url_edit)

            copy_btn = PushButton("复制")
            copy_btn.setFixedHeight(26)
            copy_btn.setFixedWidth(64)
            copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            copy_btn.clicked.connect(lambda _=False, u=url: self._copy_to_clipboard(u))
            row.addWidget(copy_btn)

            open_btn = PushButton("访问")
            open_btn.setFixedHeight(26)
            open_btn.setFixedWidth(64)
            open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            open_btn.clicked.connect(lambda _=False, u=url: webbrowser.open(u))
            row.addWidget(open_btn)

            repo_card_layout.addLayout(row)

            # 行间细分隔线（最后一行不画）
            if i < len(repo_urls) - 1:
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                line.setStyleSheet("color: #f0f0f0;")
                repo_card_layout.addWidget(line)

        # 用 CollapsibleCard 包裹，标题"项目地址"显示在 header，可点击折叠
        repo_collapsible = CollapsibleCard("项目地址", repo_content, expanded=True)
        self.content_layout.addWidget(repo_collapsible)

        # 模块卡片容器（动态填充）
        self.modules_container = QWidget()
        self.modules_container_layout = QVBoxLayout(self.modules_container)
        self.modules_container_layout.setContentsMargins(0, 0, 0, 0)
        self.modules_container_layout.setSpacing(10)
        self.content_layout.addWidget(self.modules_container)

        self.content_layout.addStretch()
        self.scroll.setWidget(self.content)
        main_layout.addWidget(self.scroll)

    def _rebuild_module_cards(self):
        """根据 self._modules 重建模块卡片"""
        # 清空旧卡片
        while self.modules_container_layout.count():
            item = self.modules_container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 按类别分组
        categories = {}
        for icon, name, cat in self._modules:
            categories.setdefault(cat, []).append((icon, name))

        # 物理和化学合并到一个可折叠卡片，用分割线隔开
        if categories:
            card = self._create_combined_module_card(categories)
            self.modules_container_layout.addWidget(card)

    def _create_combined_module_card(self, categories):
        """创建合并了物理/化学模块的可折叠卡片。

        各类别之间用水平分割线隔开，每个类别带小标题 + 模块网格。
        """
        # 类别显示名映射
        cat_names = {
            'physics': '物理实验模块',
            'chemistry': '化学实验模块',
        }

        # 内容区
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(18, 4, 18, 12)
        content_layout.setSpacing(0)

        from PySide6.QtWidgets import QGridLayout

        first = True
        for cat_key in ['physics', 'chemistry']:
            if cat_key not in categories or not categories[cat_key]:
                continue

            # 类别之间用分割线隔开（第一个类别前不画）
            if not first:
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.HLine)
                sep.setStyleSheet("color: #e5e5e5; background: transparent;")
                content_layout.addWidget(sep)
                content_layout.addSpacing(8)
            first = False

            display_name = cat_names.get(cat_key, cat_key)
            mods = categories[cat_key]

            # 类别小标题
            cat_label = QLabel(display_name)
            cat_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
            cat_label.setStyleSheet("color: #444444; background: transparent; margin-top: 4px;")
            content_layout.addWidget(cat_label)

            count_label = QLabel(f"{len(mods)} 个模块")
            count_label.setFont(QFont("Microsoft YaHei", 9))
            count_label.setStyleSheet("color: #999999; background: transparent; margin-bottom: 6px;")
            content_layout.addWidget(count_label)

            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(8)

            for i, (icon_text, name) in enumerate(mods):
                row, col = divmod(i, 2)
                item = self._create_grid_module_item(icon_text, name)
                grid.addWidget(item, row, col)

            content_layout.addLayout(grid)
            content_layout.addSpacing(4)

        return CollapsibleCard("传感器模块", content, expanded=True)

    def _create_grid_module_item(self, icon_text, name):
        """创建网格内的单个模块项"""
        btn = QPushButton()
        btn.setObjectName("module_item")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(42)
        btn.setMaximumWidth(200)
        btn.setStyleSheet(self.CARD_HOVER_STYLE)

        btn_layout = QHBoxLayout(btn)
        btn_layout.setContentsMargins(12, 4, 12, 4)
        btn_layout.setSpacing(10)

        icon_label = QLabel(icon_text)
        icon_label.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        icon_label.setFixedSize(32, 32)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("""
            background-color: #ffffff;
            color: #000000;
        """)
        btn_layout.addWidget(icon_label)

        name_label = QLabel(name)
        name_label.setFont(QFont("Microsoft YaHei", 12))
        name_label.setStyleSheet("color: #1a1a1a;")
        btn_layout.addWidget(name_label)

        arrow = QLabel(">")
        arrow.setFont(QFont("Arial", 12))
        arrow.setStyleSheet("color: #999999;")
        btn_layout.addWidget(arrow)

        btn.clicked.connect(lambda: self.on_module_clicked(name))
        return btn

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
        """主题切换：刷新主页背景、卡片样式、滚动区。

        委托给 core.apply_module_theme() 统一处理：刷新 QScrollArea/QWidget#card/
        CollapsibleCard/QLabel/QLineEdit/QFrame 的样式表，并触发 polish。
        同时也刷新 self.CARD_STYLE / self.CARD_HOVER_STYLE（用于动态重建的模块卡片）。
        """
        from core import apply_module_theme
        c = _theme_colors()
        self.CARD_STYLE = f"""
            QWidget#card {{
                background-color: {c['card_bg']};
                border: 1px solid {c['card_border']};
                border-radius: 8px;
            }}
            QWidget#card QLabel,
            QWidget#card QFrame {{
                background-color: transparent;
            }}
        """
        self.CARD_HOVER_STYLE = f"""
            QPushButton#module_item {{
                background-color: transparent;
                border: none;
                border-radius: 6px;
                text-align: left;
                padding: 12px 16px;
            }}
            QPushButton#module_item:hover {{ background-color: {c['hover_bg']}; }}
            QPushButton#module_item:pressed {{ background-color: {c['pressed_bg']}; }}
        """

        # 委托通用主题刷新：刷新滚动区/卡片/QLabel/QLineEdit 等
        apply_module_theme(self, theme)

        # url_edit 用 _theme_colors() 预烘焙 QSS，需要单独刷新
        for url_edit in getattr(self, '_url_edits', []):
            url_edit.setStyleSheet(self._url_edit_qss())

        # 刷新已显示的模块卡片（apply_module_theme 不处理动态创建的 QPushButton#module_item）
        self._rebuild_module_cards()

    def _url_edit_qss(self):
        """主题感知的只读 QLineEdit 样式（用于主页项目地址行）"""
        c = _theme_colors()
        return f"""
            QLineEdit {{
                background-color: {c['input_bg']};
                border: 1px solid {c['card_border']};
                border-radius: 5px;
                padding: 5px 10px;
                color: {c['text_secondary']};
                selection-background-color: {c['accent']};
                selection-color: #ffffff;
            }}
            QLineEdit:focus {{ border: 1px solid {c['accent']}; background-color: {c['card_bg']}; }}
        """


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
            label_font = QFont("Microsoft YaHei", 10)
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
    - 个性化：应用主题（亮色/暗色/跟随系统）
    - 关于：项目名、版本、许可证、源码仓库
    - 反馈：issue 链接
    """

    theme_change_requested = Signal(str)  # 'light' / 'dark'

    APP_VERSION = "1.0.0"

    def __init__(self):
        super().__init__()
        self._theme_combo_items = ["亮色", "暗色", "跟随系统"]
        self._theme_combo_values = ["light", "dark", "auto"]
        self.init_ui()
        # 同步初始主题选项
        self._sync_theme_combo_from_current()

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
        layout.addWidget(group_personal)

        # ===== 关于分组 =====
        group_about = SettingCardGroup("关于", self._content)
        group_about.addSettingCard(self._build_about_card(
            FIF.APPLICATION, "应用名称", "PhysChem-DigitizerP",
            "低成本理化实验数字化采集系统"))
        group_about.addSettingCard(self._build_about_card(
            FIF.INFO, "版本", f"v{self.APP_VERSION}",
            "基于 PySide6 + FluentWidgets + Arduino/ESP32"))
        group_about.addSettingCard(self._build_about_card(
            FIF.CERTIFICATE, "开源许可证", "GPL-3.0-only",
            "本应用遵循 GPL-3.0-only 协议开源"))
        layout.addWidget(group_about)

        # ===== 源码与反馈分组 =====
        group_repo = SettingCardGroup("源码 & 反馈", self._content)
        group_repo.addSettingCard(self._build_link_card(
            FIF.GITHUB, "GitHub 仓库", "wangzhidong2/PhysChem-DigitizerP",
            "https://github.com/wangzhidong2/PhysChem-DigitizerP"))
        group_repo.addSettingCard(self._build_link_card(
            FIF.GITHUB, "Gitee 仓库", "wangzhidong2/PhysChem-DigitizerP",
            "https://gitee.com/wangzhidong2/PhysChem-DigitizerP"))
        group_repo.addSettingCard(self._build_link_card(
            FIF.FEEDBACK, "问题反馈", "提交 Issue / 功能建议",
            "https://github.com/wangzhidong2/PhysChem-DigitizerP/issues"))
        layout.addWidget(group_repo)

        layout.addStretch()
        self._scroll.setWidget(self._content)
        outer.addWidget(self._scroll)

    def _build_theme_card(self, parent):
        """主题切换卡片：自定义 SettingCard，内嵌一个 ComboBox。"""
        card = SettingCard(FIF.PALETTE, "应用主题", "切换亮色 / 暗色 / 跟随系统", parent)
        combo = ComboBox(card)
        combo.addItems(self._theme_combo_items)
        combo.setMinimumWidth(140)
        combo.currentIndexChanged.connect(self._on_theme_combo_changed)
        card.hBoxLayout.addWidget(combo)
        card.hBoxLayout.addSpacing(16)
        self._theme_combo = combo
        return card

    def _build_about_card(self, icon, title, value, content):
        """只读信息卡片：右侧显示 value 文本"""
        card = SettingCard(icon, title, content)
        value_lbl = BodyLabel(value)
        # 次要文字色，比标题弱一档
        value_lbl.setStyleSheet("color: #888888;")
        card.hBoxLayout.addWidget(value_lbl)
        card.hBoxLayout.addSpacing(16)
        return card

    def _build_link_card(self, icon, title, content, url):
        """带"访问"按钮的链接卡片"""
        card = SettingCard(icon, title, content)
        link_btn = HyperlinkButton()
        link_btn.setText("访问")
        link_btn.setUrl(url)
        link_btn.setFixedHeight(34)
        card.hBoxLayout.addWidget(link_btn)
        card.hBoxLayout.addSpacing(16)
        return card

    def _on_theme_combo_changed(self, idx: int):
        if not (0 <= idx < len(self._theme_combo_values)):
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
        """根据当前 FluentWidgets 主题，反向同步下拉框选项。"""
        try:
            t = qconfig.theme
        except Exception:
            return
        if t == Theme.AUTO:
            self._theme_combo.setCurrentIndex(2)
        elif t == Theme.DARK:
            self._theme_combo.setCurrentIndex(1)
        else:
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

        font = QFont("Microsoft YaHei", 9)
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

    def apply_modern_style(self):
        self.current_theme = "light"
        self.apply_theme("light")


def main():
    app = QApplication(sys.argv)
    # 让 ComboBox 展开时箭头朝上（FluentWidgets 默认始终朝下）
    patch_combobox_arrow_flip()
    # FluentWidgets 自带 WinUI3 风格，不再需要 Fusion
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
