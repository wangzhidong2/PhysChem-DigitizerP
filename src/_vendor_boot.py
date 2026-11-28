# -*- coding: utf-8 -*-
"""
_vendor_boot — 第三方 UI 库的加载引导（优先内嵌，回退已安装）

WinUI3 风格组件库有三个包：`qfluentwidgets`、`qframelesswindow`、`darkdetect`。
本项目**同时支持**两种来源：

1. **优先用 `src/` 内嵌副本**（默认）：用户不必 pip 安装，开箱即用；
2. **内嵌目录缺失时，回退到 pip 已安装的库**：方便开发者升级/调试新版库，
   或用户不小心删掉了内嵌目录时仍能启动。

为什么需要这个模块而不是靠 `sys.path` 默认顺序
--------------------------------------------------
脚本方式运行时（`python src/main.py`），`src/` 天然在 `sys.path[0]`，内嵌副本
会被优先找到。但这依赖调用方式：
- `python -m` / `-c` / PyInstaller 冻结后，`sys.path[0]` 不一定是 `src/`；
- 用户的 `PYTHONPATH` 或虚拟环境可能把 site-packages 排在前面；
- 三个包必须**来源一致**，否则可能出现 `qfluentwidgets` 用内嵌、
  `qframelesswindow` 用 site-packages 的混搭（版本不匹配会崩）。

所以这里显式判断：内嵌目录齐备 → 把 `src/` 插到 `sys.path` 最前；
不齐备 → 保持原样，让 Python 去 site-packages 找。

用法：在 `main.py` / `core_ui.py` **导入 qfluentwidgets 之前** `import _vendor_boot`。
"""

import os
import sys

#: 必须成套存在的内嵌包目录名
_VENDOR_PACKAGES = ('qfluentwidgets', 'qframelesswindow', 'darkdetect')

#: `src/` 绝对路径（本文件所在目录）
SRC_DIR = os.path.dirname(os.path.abspath(__file__))

#: 最终采用的来源：'vendored' / 'installed' / 'missing'
SOURCE = 'missing'


def _vendored_ready():
    """内嵌的三个包是否齐全（每个都要有 __init__.py）。"""
    for name in _VENDOR_PACKAGES:
        init = os.path.join(SRC_DIR, name, '__init__.py')
        if not os.path.isfile(init):
            return False
    return True


def ensure_vendor_first():
    """确保内嵌副本优先；内嵌缺失时不动 sys.path（回退到已安装库）。

    Returns:
        str: 'vendored'（用内嵌）/ 'installed'（回退到已安装）/ 'missing'（两者都无）
    """
    global SOURCE

    ready = _vendored_ready()
    if ready:
        # 放到最前，压过 site-packages 与环境变量里的同名包
        if SRC_DIR in sys.path:
            sys.path.remove(SRC_DIR)
        sys.path.insert(0, SRC_DIR)
        # 已加载过同名模块则清掉，避免拿到旧来源（只在本模块首次调用时有意义）
        for name in _VENDOR_PACKAGES:
            mod = sys.modules.get(name)
            if mod is not None:
                origin = getattr(mod, '__file__', '') or ''
                if not os.path.abspath(origin).startswith(SRC_DIR):
                    # 已从别处加载：清空以便重新按新顺序导入
                    for k in [k for k in sys.modules if k == name
                              or k.startswith(name + '.')]:
                        del sys.modules[k]
        SOURCE = 'vendored'
        return SOURCE

    # 内嵌不全：回退到已安装库
    try:
        import importlib.util
        have = all(importlib.util.find_spec(n) is not None
                   for n in _VENDOR_PACKAGES)
    except Exception:
        have = False
    SOURCE = 'installed' if have else 'missing'
    return SOURCE


def describe():
    """给日志/报错用的一行说明：用了哪套库、在哪。"""
    ensure_vendor_first()
    if SOURCE == 'vendored':
        return '内嵌组件库（src/%s）' % _VENDOR_PACKAGES[0]
    if SOURCE == 'installed':
        try:
            import qfluentwidgets
            where = os.path.dirname(os.path.dirname(
                os.path.abspath(qfluentwidgets.__file__)))
            return '已安装组件库（%s）' % where
        except Exception:
            return '已安装组件库'
    return '未找到组件库'


# 导入本模块即生效（放在文件顶部 import 即可）
ensure_vendor_first()
