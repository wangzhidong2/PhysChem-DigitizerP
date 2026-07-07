#!/usr/bin/env python3
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
import importlib.util

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QStackedWidget, QScrollArea, QGroupBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QRect
from PyQt6.QtGui import QFont, QIcon, QPixmap, QPainter, QColor, QFontMetrics

# 公共模块（与各传感器模块共享）
from core import card_style, primary_btn_style, accent_btn_style


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

    module_clicked = pyqtSignal(str)

    CARD_STYLE = """
        QWidget#card {
            background-color: #ffffff;
            border: 1px solid #e5e5e5;
            border-radius: 8px;
        }
        QWidget#card QLabel,
        QWidget#card QFrame {
            background-color: transparent;
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
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: #f3f3f3; }")

        self.content = QWidget()
        self.content.setStyleSheet("background: #f3f3f3;")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(24, 20, 24, 24)
        self.content_layout.setSpacing(16)

        # 页面标题
        title = QLabel("主页")
        title.setFont(QFont("Microsoft YaHei", 28, QFont.Weight.Bold))
        title.setStyleSheet("color: #1a1a1a; margin-bottom: 4px;")
        self.content_layout.addWidget(title)

        # ========== 卡片1：版本信息 + 项目简介 ==========
        card1 = QWidget()
        card1.setObjectName("card")
        card1.setStyleSheet(self.CARD_STYLE)
        card1_layout = QVBoxLayout(card1)
        card1_layout.setContentsMargins(20, 20, 20, 20)
        card1_layout.setSpacing(12)

        top_row = QWidget()
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(16)

        icon_label = QLabel("🔬")
        icon_label.setFont(QFont("Segoe MDL2 Assets", 36))
        icon_label.setFixedSize(64, 64)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("""
            background-color: #e8f0fe;
            border-radius: 12px;
            color: #0067c0;
        """)
        top_layout.addWidget(icon_label)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        app_name = QLabel("PhysChem-DigitizerP")
        app_name.setFont(QFont("Microsoft YaHei", 18, QFont.Weight.Bold))
        app_name.setStyleSheet("color: #1a1a1a;")
        info_layout.addWidget(app_name)

        version_label = QLabel("版本 1.3.0 | MIT 开源协议 | 模块化架构")
        version_label.setFont(QFont("Microsoft YaHei", 10))
        version_label.setStyleSheet("color: #666666;")
        info_layout.addWidget(version_label)

        top_layout.addLayout(info_layout)
        top_layout.addStretch()

        github_btn = QPushButton("  GitHub")
        github_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        github_btn.setFixedHeight(36)
        github_btn.setStyleSheet("""
            QPushButton {
                background-color: #0067c0;
                border: none;
                border-radius: 6px;
                color: white;
                font-size: 13px;
                padding: 0 16px;
            }
            QPushButton:hover { background-color: #005a9e; }
            QPushButton:pressed { background-color: #004578; }
        """)
        github_btn.clicked.connect(self.open_github)
        top_layout.addWidget(github_btn)

        card1_layout.addWidget(top_row)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("color: #e0e0e0;")
        card1_layout.addWidget(separator)

        desc_label = QLabel(
            "基于 Arduino/ESP32 的低成本理化实验数字化采集系统，"
            "为中学和大学物理/化学实验室提供低成本、高精度的传感器解决方案。"
        )
        desc_label.setWordWrap(True)
        desc_label.setFont(QFont("Microsoft YaHei", 11))
        desc_label.setStyleSheet("color: #444444; line-height: 1.5;")
        card1_layout.addWidget(desc_label)

        tags_layout = QHBoxLayout()
        tags_layout.setSpacing(8)
        tags = [
            ("MIT 开源", "#e8f5e9", "#2e7d32"),
            ("教学实验", "#f3e5f5", "#7b1fa2"),
            ("模块化架构", "#e3f2fd", "#1565c0"),
        ]
        for text, bg, fg in tags:
            tag = QLabel(text)
            tag.setFont(QFont("Microsoft YaHei", 9))
            tag.setStyleSheet(f"""
                background-color: {bg};
                color: {fg};
                border-radius: 4px;
                padding: 4px 10px;
            """)
            tags_layout.addWidget(tag)
        tags_layout.addStretch()
        card1_layout.addLayout(tags_layout)

        self.content_layout.addWidget(card1)

        # 模块卡片容器（动态填充）
        self.modules_container = QWidget()
        self.modules_container_layout = QVBoxLayout(self.modules_container)
        self.modules_container_layout.setContentsMargins(0, 0, 0, 0)
        self.modules_container_layout.setSpacing(16)
        self.content_layout.addWidget(self.modules_container)

        self.content_layout.addStretch()
        self.scroll.setWidget(self.content)
        main_layout.addWidget(self.scroll)
        self.setLayout(main_layout)

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

        # 类别显示名映射
        cat_names = {
            'physics': ('物理实验模块', '⚛️', '#0067c0'),
            'chemistry': ('化学实验模块', '🧪', '#7b1fa2'),
        }

        # 物理和化学并排
        if 'physics' in categories or 'chemistry' in categories:
            row_layout = QHBoxLayout()
            row_layout.setSpacing(16)

            for cat_key in ['physics', 'chemistry']:
                if cat_key not in categories:
                    continue
                display_name, icon_char, color = cat_names.get(
                    cat_key, (cat_key, '📦', '#666666')
                )
                mods = categories[cat_key]
                card = self._create_grid_module_card(
                    display_name,
                    f"{len(mods)} 个模块",
                    mods,
                    icon_char,
                    color,
                )
                row_layout.addWidget(card, stretch=2)

            self.modules_container_layout.addLayout(row_layout)

    def _create_grid_module_card(self, title, subtitle, modules, title_icon, title_color):
        """创建现代化设置风格的网格卡片"""
        card = QWidget()
        card.setObjectName("card")
        card.setStyleSheet(self.CARD_STYLE)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 16)
        card_layout.setSpacing(0)

        title_label = QLabel(title)
        title_label.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #1a1a1a;")
        card_layout.addWidget(title_label)

        subtitle_label = QLabel(subtitle)
        subtitle_label.setFont(QFont("Microsoft YaHei", 10))
        subtitle_label.setStyleSheet("color: #666666; margin-bottom: 12px;")
        card_layout.addWidget(subtitle_label)

        from PyQt6.QtWidgets import QGridLayout
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)

        for i, (icon_text, name) in enumerate(modules):
            row, col = divmod(i, 2)
            item = self._create_grid_module_item(icon_text, name)
            grid.addWidget(item, row, col)

        card_layout.addLayout(grid)
        card_layout.addSpacing(4)
        return card

    def _create_grid_module_item(self, icon_text, name):
        """创建网格内的单个模块项"""
        btn = QPushButton()
        btn.setObjectName("module_item")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(48)
        btn.setMaximumWidth(200)
        btn.setStyleSheet(self.CARD_HOVER_STYLE)

        btn_layout = QHBoxLayout(btn)
        btn_layout.setContentsMargins(12, 6, 12, 6)
        btn_layout.setSpacing(10)

        icon_label = QLabel(icon_text)
        icon_label.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        icon_label.setFixedSize(32, 32)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("""
            background-color: #e8f0fe;
            border-radius: 6px;
            color: #0067c0;
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

    def open_github(self):
        import webbrowser
        webbrowser.open("https://github.com/wangzhidong2/PhysChem-DigitizerP")

    def on_module_clicked(self, module_name):
        self.module_clicked.emit(module_name)

    def apply_theme(self, theme):
        if theme == "dark":
            self.CARD_STYLE = """
                QWidget#card {
                    background-color: #2d2d2d;
                    border: 1px solid #404040;
                    border-radius: 8px;
                }
                QWidget#card QLabel,
                QWidget#card QFrame {
                    background-color: transparent;
                }
            """
            self.CARD_HOVER_STYLE = """
                QPushButton#module_item {
                    background-color: transparent;
                    border: none;
                    border-radius: 6px;
                    text-align: left;
                    padding: 12px 16px;
                }
                QPushButton#module_item:hover { background-color: #404040; }
                QPushButton#module_item:pressed { background-color: #505050; }
            """
            self.scroll.setStyleSheet("QScrollArea { border: none; background: #202020; }")
            self.content.setStyleSheet("background: #202020;")
        else:
            self.CARD_STYLE = """
                QWidget#card {
                    background-color: #ffffff;
                    border: 1px solid #e5e5e5;
                    border-radius: 8px;
                }
                QWidget#card QLabel,
                QWidget#card QFrame {
                    background-color: transparent;
                }
            """
            self.CARD_HOVER_STYLE = """
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
            self.scroll.setStyleSheet("QScrollArea { border: none; background: #f3f3f3; }")
            self.content.setStyleSheet("background: #f3f3f3;")

        # 刷新已显示的卡片样式
        self._rebuild_module_cards()


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

    module_changed = pyqtSignal(int)

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
# 设置
# ============================================================
class SettingsWidget(QWidget):
    """设置界面组件"""

    theme_changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.current_theme = "light"
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        title = QLabel("设置")
        title.setFont(QFont("Microsoft YaHei", 24, QFont.Weight.Bold))
        layout.addWidget(title)

        appearance_group = QGroupBox("外观")
        appearance_layout = QVBoxLayout()
        appearance_layout.setSpacing(15)

        theme_label = QLabel("应用主题")
        theme_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        appearance_layout.addWidget(theme_label)

        theme_desc = QLabel("选择要显示的应用主题")
        theme_desc.setStyleSheet("color: #666; font-size: 11px;")
        appearance_layout.addWidget(theme_desc)

        self.theme_button_group = QVBoxLayout()
        self.theme_button_group.setSpacing(8)

        self.theme_buttons = {}
        themes = [
            ("system", "使用系统设置"),
            ("light", "浅色"),
            ("dark", "深色"),
        ]

        for theme_id, theme_name in themes:
            btn = QPushButton(f"  {theme_name}")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(40)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: white;
                    border: 1px solid #e0e0e0;
                    border-radius: 4px;
                    text-align: left;
                    padding-left: 15px;
                    font-size: 13px;
                    color: #333;
                }
                QPushButton:hover {
                    background-color: #f5f5f5;
                    border-color: #0078d4;
                }
                QPushButton:checked {
                    background-color: #e6f2ff;
                    border-left: 3px solid #0078d4;
                    color: #0078d4;
                    font-weight: bold;
                }
            """)
            btn.clicked.connect(lambda checked, tid=theme_id: self.change_theme(tid))
            self.theme_buttons[theme_id] = btn
            self.theme_button_group.addWidget(btn)

        appearance_layout.addLayout(self.theme_button_group)
        appearance_group.setLayout(appearance_layout)
        layout.addWidget(appearance_group)

        layout.addStretch()
        self.setLayout(layout)
        self.theme_buttons["light"].setChecked(True)

    def change_theme(self, theme_id):
        for btn in self.theme_buttons.values():
            btn.setChecked(False)
        self.theme_buttons[theme_id].setChecked(True)
        self.current_theme = theme_id
        self.theme_changed.emit(theme_id)

    def apply_theme(self, theme):
        if theme == "dark":
            self.setStyleSheet("""
                QWidget { background-color: #202020; color: #ffffff; }
                QGroupBox {
                    font-weight: bold;
                    border: 2px solid #3d3d3d;
                    border-radius: 8px;
                    margin-top: 10px;
                    padding-top: 10px;
                    color: #ffffff;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px 0 5px;
                    color: #ffffff;
                }
                QLabel { color: #ffffff; }
                QPushButton {
                    background-color: #333333;
                    border: 1px solid #444444;
                    color: #ffffff;
                    border-radius: 4px;
                    padding: 8px 16px;
                    font-size: 14px;
                }
                QPushButton:hover { background-color: #404040; border-color: #0078d4; }
                QPushButton:checked {
                    background-color: #003366;
                    border-left: 3px solid #0078d4;
                    color: #0078d4;
                    font-weight: bold;
                }
            """)
        else:
            self.setStyleSheet("""
                QWidget { background-color: #fafafa; color: #000000; }
                QGroupBox {
                    font-weight: bold;
                    border: 2px solid #e0e0e0;
                    border-radius: 8px;
                    margin-top: 10px;
                    padding-top: 10px;
                    color: #000000;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px 0 5px;
                    color: #000000;
                }
                QLabel { color: #000000; }
                QPushButton {
                    background-color: white;
                    border: 1px solid #e0e0e0;
                    color: #333333;
                    border-radius: 4px;
                    padding: 8px 16px;
                    font-size: 14px;
                }
                QPushButton:hover { background-color: #f5f5f5; border-color: #0078d4; }
                QPushButton:checked {
                    background-color: #e6f2ff;
                    border-left: 3px solid #0078d4;
                    color: #0078d4;
                    font-weight: bold;
                }
            """)


# ============================================================
# 主窗口 + 动态加载器
# ============================================================
class MainWindow(QMainWindow):
    """主窗口 - 启动时扫描模块目录并动态加载各传感器模块"""

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
        self.setGeometry(100, 100, 1200, 800)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout()

        # 侧边栏
        self.sidebar = SidebarWidget()
        self.sidebar.module_changed.connect(self.switch_module)
        main_layout.addWidget(self.sidebar)

        # 内容栈
        self.content_stack = QStackedWidget()
        main_layout.addWidget(self.content_stack)

        # === 加载模块 ===
        # 确定传感器代码目录（与 main.py 同级）
        app_dir = os.path.dirname(os.path.abspath(__file__))
        modules_dir = os.path.join(app_dir, '传感器代码')

        discovered = scan_modules(modules_dir)

        # 主页（始终在第 0 位）
        home_page = HomePageWidget()
        home_page.module_clicked.connect(self.on_home_module_clicked)
        self.content_stack.addWidget(home_page)
        self.modules["主页"] = home_page
        self.module_widgets.append(home_page)

        # 各传感器模块（按发现顺序加载）
        sidebar_modules = []  # [(icon, name, desc), ...] 给侧边栏用
        home_modules = []  # [(icon, name, category), ...] 给主页用

        for info in discovered:
            cls = getattr(info['module'], info['class_name'])
            try:
                widget = cls()
            except Exception as e:
                print(f"❌ 实例化模块 {info['name']} 失败: {e}")
                continue

            self.content_stack.addWidget(widget)
            self.modules[info['name']] = widget
            self.module_widgets.append(widget)

            desc = self._get_module_desc(info['name'])
            sidebar_modules.append((info['icon'], info['name'], desc))
            home_modules.append((info['icon'], info['name'], info['category']))

        # 设置（始终在最后）
        settings_widget = SettingsWidget()
        settings_widget.theme_changed.connect(self.change_app_theme)
        self.content_stack.addWidget(settings_widget)
        self.modules["设置"] = settings_widget
        self.module_widgets.append(settings_widget)

        # 把模块列表传给侧边栏和主页
        self.sidebar.set_modules(sidebar_modules)
        home_page.set_modules(home_modules)

        central_widget.setLayout(main_layout)
        self.sidebar.set_current_row(0)

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
        if 0 <= index < self.content_stack.count():
            self.content_stack.setCurrentIndex(index)

    def on_home_module_clicked(self, module_name):
        """主页模块卡片点击 → 切换到对应模块"""
        for i, (icon, name, desc) in enumerate(self.sidebar.modules):
            if name == module_name:
                self.sidebar.set_current_row(i)
                self.switch_module(i)
                return

    def change_app_theme(self, theme):
        self.current_theme = theme
        self.apply_theme(theme)

        if hasattr(self, 'sidebar'):
            self.sidebar.apply_theme(theme)

        if "设置" in self.modules:
            self.modules["设置"].apply_theme(theme)

        if "主页" in self.modules:
            self.modules["主页"].apply_theme(theme)

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
        if theme == "dark":
            self.setStyleSheet("""
                QMainWindow {
                    background-color: #202020;
                    color: white;
                }
                QGroupBox {
                    font-weight: bold;
                    border: 2px solid #3d3d3d;
                    border-radius: 8px;
                    margin-top: 10px;
                    padding-top: 10px;
                    color: white;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px 0 5px;
                    color: white;
                }
                QPushButton {
                    background-color: #0078d4;
                    border: none;
                    color: white;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-size: 14px;
                }
                QPushButton:hover { background-color: #106ebe; }
                QPushButton:disabled { background-color: #444444; color: #888888; }
                QLabel { font-size: 14px; color: white; }
            """)
        else:
            self.setStyleSheet("""
                QMainWindow {
                    background-color: #f3f3f3;
                    color: black;
                }
                QGroupBox {
                    font-weight: bold;
                    border: 2px solid #e0e0e0;
                    border-radius: 8px;
                    margin-top: 10px;
                    padding-top: 10px;
                    color: black;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px 0 5px;
                    color: black;
                }
                QPushButton {
                    background-color: #0078d4;
                    border: none;
                    color: white;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-size: 14px;
                }
                QPushButton:hover { background-color: #106ebe; }
                QPushButton:disabled { background-color: #cccccc; color: #666666; }
                QLabel { font-size: 14px; color: black; }
            """)

    def apply_modern_style(self):
        self.current_theme = "light"
        self.apply_theme("light")


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
