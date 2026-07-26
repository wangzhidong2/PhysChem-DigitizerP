#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PhysChem-DigitizerP 主程序（QML + FluentPySide 版）

架构：
- main.py 启动 QApplication → fluentpyside.apply() 启用 FluentWinUI3 风格
- 扫描 传感器代码/ 目录，importlib 加载各传感器 Backend 类
- 把所有 Backend 实例 + modulesModel + backendsMap 注入 QML context
- 注册 backends.ChartItem 到 QML
- 加载 qml/Main.qml

新增传感器模块无需修改本文件，只需：
1. 在 传感器代码/ 下新建子目录，放入 .ino 和 .py
2. .py 头部识别区声明 class / icon / name / category / qml（可选）
3. 可选：在 qml/modules/ 下放 <module_id>.qml 定制界面
"""

import sys
import os
import re
import glob
import importlib.util
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QUrl, QAbstractListModel, QModelIndex, Qt, QByteArray, Property, Signal, Slot
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType
from PySide6.QtQuickControls2 import QQuickStyle

import fluentpyside

from backends import BackendBase, ChartItem


# ============================================================
# FluentPySide 集成
# ============================================================
def _find_fluentwinui3_style():
    """定位 FluentWinUI3 样式文件夹。

    fluentpyside 自带的 find_installed_style() 只查找 PySide6/qml/...，
    但官方 PySide6 wheels 实际把 QML 放在 PySide6/Qt/qml/...，
    这里覆盖查找逻辑，依次尝试：
      1) fluentpyside 包内自带的 QtQuick/Controls/FluentWinUI3
      2) PySide6/Qt/qml/QtQuick/Controls/FluentWinUI3  (官方 wheels 实际位置)
      3) PySide6/qml/QtQuick/Controls/FluentWinUI3      (上游 find_installed_style 查找的位置)
    """
    candidates = []

    # 1) fluentpyside 包内
    try:
        pkg_default = fluentpyside.default_style_path()
        if pkg_default:
            candidates.append(Path(pkg_default))
    except Exception:
        pass

    # 2/3) PySide6 内
    try:
        import PySide6
        pyside_pkg = Path(PySide6.__file__).parent
        candidates.append(pyside_pkg / "Qt" / "qml" / "QtQuick" / "Controls" / "FluentWinUI3")
        candidates.append(pyside_pkg / "qml" / "QtQuick" / "Controls" / "FluentWinUI3")
    except Exception:
        pass

    for c in candidates:
        try:
            if c.exists() and (c / "qmldir").exists():
                return c
        except Exception:
            continue
    return None


def apply_fluent_style(engine):
    """应用 FluentWinUI3 样式到给定的 QQmlEngine。

    优先使用 fluentpyside.set_style（它正确处理了 QML2_IMPORT_PATH 的层级
    以及 QQuickStyle.setStyle），但如果包内未安装 assets，则手动回退到
    PySide6 自带的 FluentWinUI3 文件夹。
    """
    style_path = _find_fluentwinui3_style()
    if style_path is None:
        print("⚠️ 未找到 FluentWinUI3 样式资源，回退到默认样式")
        return None

    try:
        # 传 engine 进去，让 set_style 同时调用 engine.addImportPath()
        fluentpyside.set_style(path=style_path, engine=engine)
    except Exception as e:
        # 即便 set_style 失败，也手动确保 QQuickStyle + import path 设置
        print(f"⚠️ fluentpyside.set_style 失败：{e}，手动应用样式")
        try:
            qml_root = style_path.parent.parent.parent  # .../QtQuick/Controls/FluentWinUI3 -> .../Qt/qml
            engine.addImportPath(str(qml_root))
            os.environ["QML2_IMPORT_PATH"] = (
                str(qml_root) + os.pathsep + os.environ.get("QML2_IMPORT_PATH", "")
            ).rstrip(os.pathsep)
        except Exception:
            pass

    # 显式设置 QQuickStyle（set_style 内部已尝试，这里兜底）
    try:
        QQuickStyle.setStyle("FluentWinUI3")
    except Exception:
        pass

    print(f"✓ FluentWinUI3 样式已应用: {style_path}")
    print(f"  QQuickStyle.name = {QQuickStyle.name()}")
    return style_path


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
    """解析模块文件头部的识别区注释块。"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
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

    if 'class' not in meta:
        return None

    meta.setdefault('icon', '?')
    meta.setdefault('name', meta.get('class', 'Module'))
    meta.setdefault('category', 'physics')
    meta.setdefault('qml', '')  # 留空则使用 qml/modules/<id>.qml 或通用模板
    return meta


def scan_modules(modules_dir, qml_modules_dir, default_qml):
    """扫描 传感器代码/ 目录，发现并加载所有传感器 Backend 类。"""
    discovered = []
    if not os.path.isdir(modules_dir):
        print(f"⚠️ 模块目录不存在: {modules_dir}")
        return discovered

    # 仓库根加入 sys.path，使模块能 `from core import ...` 和 `from backends import ...`
    repo_root = os.path.dirname(os.path.abspath(__file__))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    for sub in sorted(os.listdir(modules_dir)):
        sub_path = os.path.join(modules_dir, sub)
        if not os.path.isdir(sub_path):
            continue

        for py_file in sorted(glob.glob(os.path.join(sub_path, '*.py'))):
            base = os.path.basename(py_file)
            if base.startswith('_') or base.startswith('test'):
                continue

            meta = parse_module_meta(py_file)
            if not meta:
                continue

            mod_name = f"_sensor_module_{base[:-3]}"
            spec = importlib.util.spec_from_file_location(mod_name, py_file)
            if spec is None or spec.loader is None:
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

            # 决定模块 QML 文件路径
            module_id = base[:-3]
            if meta['qml']:
                qml_path = os.path.join(sub_path, meta['qml'])
            else:
                # 优先 qml/modules/<id>.qml
                candidate = os.path.join(qml_modules_dir, f"{module_id}.qml")
                if os.path.exists(candidate):
                    qml_path = candidate
                else:
                    qml_path = default_qml  # 通用模板

            discovered.append({
                'id': module_id,
                'name': meta['name'],
                'icon': meta['icon'],
                'category': meta['category'],
                'class_name': class_name,
                'module': mod,
                'file_path': py_file,
                'qml_path': qml_path,
                'backend_key': module_id,
            })
            print(f"✓ 已加载模块: {meta['name']} ({meta['category']}) <- {base}")

    discovered.sort(key=lambda x: (x['category'], x['name']))
    return discovered


# ============================================================
# QML 端使用的 ListModel（QAbstractListModel 实现）
# ============================================================
class ModulesModel(QAbstractListModel):
    """把模块列表以 QML ListModel 形式暴露，支持 Repeater/ListView 直接绑定。

    Roles:
        - name (display): 模块显示名
        - icon: 图标文本
        - category: physics / chemistry
        - backendKey: backendsMap 中的 key
        - qmlPath: 该模块 QML 文件的 file:/// URL
        - moduleId: 模块 id
        - index: 在 modulesModel 中的索引
    """
    NameRole = Qt.UserRole + 1
    IconRole = Qt.UserRole + 2
    CategoryRole = Qt.UserRole + 3
    BackendKeyRole = Qt.UserRole + 4
    QmlPathRole = Qt.UserRole + 5
    ModuleIdRole = Qt.UserRole + 6
    IndexRole = Qt.UserRole + 7

    _ROLE_NAMES = {
        NameRole: QByteArray(b"name"),
        IconRole: QByteArray(b"icon"),
        CategoryRole: QByteArray(b"category"),
        BackendKeyRole: QByteArray(b"backendKey"),
        QmlPathRole: QByteArray(b"qmlPath"),
        ModuleIdRole: QByteArray(b"moduleId"),
        IndexRole: QByteArray(b"index"),
    }

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self._items = items
        for i, it in enumerate(items):
            it['index'] = i

    countChanged = Signal()

    def _count_getter(self):
        return len(self._items)

    count = Property(int, _count_getter, notify=countChanged)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._items)

    def roleNames(self):
        return self._ROLE_NAMES

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        it = self._items[index.row()]
        if role == self.NameRole:
            return it.get('name', '')
        if role == self.IconRole:
            return it.get('icon', '')
        if role == self.CategoryRole:
            return it.get('category', '')
        if role == self.BackendKeyRole:
            return it.get('backendKey', '')
        if role == self.QmlPathRole:
            return it.get('qmlPath', '')
        if role == self.ModuleIdRole:
            return it.get('id', '')
        if role == self.IndexRole:
            return it.get('index', 0)
        return None

    # QML 通过 modulesModel.get(index) 调用，返回 dict-like
    @Slot(int, result="QVariant")
    def get(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return {}


# ============================================================
# 主入口
# ============================================================
def main():
    repo_root = os.path.dirname(os.path.abspath(__file__))
    modules_dir = os.path.join(repo_root, '传感器代码')
    qml_dir = os.path.join(repo_root, 'qml')
    qml_modules_dir = os.path.join(qml_dir, 'modules')
    default_qml = os.path.join(qml_dir, 'ModuleView.qml')
    main_qml = os.path.join(qml_dir, 'Main.qml')

    # 注册 ChartItem 到 QML
    qmlRegisterType(ChartItem, "Charts", 1, 0, "ChartItem")

    app = QApplication(sys.argv)
    app.setApplicationName("PhysChem-DigitizerP")
    app.setApplicationVersion("2.0.0")

    # 扫描并加载模块
    discovered = scan_modules(modules_dir, qml_modules_dir, default_qml)
    if not discovered:
        print("⚠️ 未发现任何传感器模块")

    # 实例化每个 Backend
    backends_map = {}
    for it in discovered:
        cls = getattr(it['module'], it['class_name'])
        try:
            inst = cls()  # BackendBase 子类构造需无参
        except Exception as e:
            print(f"❌ 实例化 Backend {it['class_name']} 失败: {e}")
            continue
        backends_map[it['backend_key']] = inst

    # 构造 QML 端 ListModel
    # 字段名按 QML 约定：name/icon/category/backendKey/qmlPath/index
    items_for_qml = []
    physics_items = []
    chemistry_items = []
    for it in discovered:
        entry = {
            'index': len(items_for_qml),
            'id': it['id'],
            'name': it['name'],
            'icon': it['icon'],
            'category': it['category'],
            'backendKey': it['backend_key'],
            'qmlPath': QUrl.fromLocalFile(it['qml_path']).toString(),
        }
        items_for_qml.append(entry)
        if it['category'] == 'physics':
            physics_items.append(entry)
        else:
            chemistry_items.append(entry)

    modules_model = ModulesModel(items_for_qml)
    physics_model = ModulesModel(physics_items)
    chemistry_model = ModulesModel(chemistry_items)

    engine = QQmlApplicationEngine()
    engine.addImportPath(qml_dir)

    # 真正接入 FluentPySide：在 engine 创建后、load QML 之前应用 FluentWinUI3 样式
    apply_fluent_style(engine)

    ctx = engine.rootContext()
    ctx.setContextProperty("modulesModel", modules_model)
    ctx.setContextProperty("physicsModel", physics_model)
    ctx.setContextProperty("chemistryModel", chemistry_model)
    ctx.setContextProperty("backendsMap", backends_map)

    engine.load(QUrl.fromLocalFile(main_qml))

    if not engine.rootObjects():
        print("❌ 无法加载 Main.qml")
        sys.exit(1)

    # 应用退出时清理所有 Backend
    def cleanup():
        for b in backends_map.values():
            try:
                b.cleanup()
            except Exception:
                pass
    app.aboutToQuit.connect(cleanup)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
