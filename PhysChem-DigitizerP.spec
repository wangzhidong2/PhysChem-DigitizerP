# -*- mode: python ; coding: utf-8 -*-
# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

"""PhysChem-DigitizerP 打包配置（PyInstaller onedir 模式）

用法：
    pip install pyinstaller
    pyinstaller --noconfirm PhysChem-DigitizerP.spec

产物：dist/PhysChem-DigitizerP/ 整个目录即绿色程序，压缩后即可分发。

原理（无需改动源码）：
- 入口脚本为 src/main.py，源码根目录 src/ 同时是运行时资源根：
  core.py 的配置/日志、内嵌字体、传感器与插件目录都按 `__file__` 定位。
- 传感器模块由 main.py 用 importlib 按 `__file__` 相对路径动态加载，
  PyInstaller 静态分析发现不了，必须作为数据文件手动收集；
  onedir 模式下 main 脚本的 `__file__` 指向 _internal/（PyInstaller 6+），
  datas 收集的文件恰好落在同一目录，运行时路径自然对上。
  注意 datas 的 dest 必须去掉 `src/` 前缀（落到 _internal/sensors，
  而不是 _internal/src/sensors），否则运行期路径对不上。
- flaskserver 插件同理整目录手动收集，含 web/ 静态资源。
- 窗口图标 src/assets/images/icon.ico、内嵌字体 src/assets/fonts/ 均按
  `__file__` 相对路径查找，一并打包。
- qfluentwidgets 的 FluentIcon SVG/QSS 资源用 collect_data_files 收集
  （含 i18n 翻译，缺了界面文案会回退英文）。

注意事项：
- onedir 目录模式（非单文件）：onefile 每次运行解压到临时目录，启动慢且
  sensor_config.json / app_config.json 无法跨次持久。
- console=True 保留控制台窗口，传感器加载、串口收发日志实时可见。
- 新增传感器模块后重新打包；打包产物内也可以直接往
  _internal/sensors/<子目录>/ 丢 .py 实现免重打包热插拔。
- pyserial 未安装时打包仍可成功，但产物只能跑「模拟器」模式；
  要支持真实串口请先 `pip install pyserial` 再打包。
"""

import os
from PyInstaller.utils.hooks import collect_data_files

# --- 只收集传感器模块源码，排除商家资料 / 缓存 / 测试文件 ---
# 源码在 src/sensors/ 下，datas 的 dest 去掉 src/ 前缀，
# 使打包后落点为 _internal/sensors/…（与 main.py 的 __file__ 同级）。
sensor_datas = []
for dirpath, dirnames, filenames in os.walk('src/sensors'):
    if '__pycache__' in dirpath:
        continue
    # 排除 vendor-docs（商家资料，原「资料（HX711称重模块商家提供的）」）等非代码目录，避免包体膨胀
    if 'vendor-docs' in dirpath:
        continue
    dest = os.path.relpath(dirpath, 'src')
    for fn in filenames:
        if fn.endswith('.py') and not fn.startswith('_') and not fn.startswith('test'):
            sensor_datas.append((os.path.join(dirpath, fn), dest))

# --- flaskserver 插件：整目录手动收集（.py 与 web/ 静态资源都要）---
# 插件由 main.py 按路径 importlib 动态加载，PyInstaller 静态分析发现不了；
# collect_data_files 依赖包可被 import 定位，源码在 src/ 下不可靠，故直接 walk。
plugin_datas = []
for dirpath, dirnames, filenames in os.walk('src/flaskserver'):
    if '__pycache__' in dirpath:
        continue
    dest = os.path.relpath(dirpath, 'src')
    for fn in filenames:
        if fn.endswith('.pyc'):
            continue
        plugin_datas.append((os.path.join(dirpath, fn), dest))

datas = sensor_datas + plugin_datas + [
    # 窗口图标：main.py 按 __file__ 相对 assets/images/icon.ico 加载
    (os.path.join('src', 'assets', 'images', 'icon.ico'),
     os.path.join('assets', 'images')),
    # Gitee / GitCode 平台 logo：主页与设置页按 assets/images/ 相对路径加载，
    # 加载失败仅回退 FluentIcon，但正常分发应带全
    (os.path.join('src', 'assets', 'images', 'gitee.svg'),
     os.path.join('assets', 'images')),
    (os.path.join('src', 'assets', 'images', 'gitcode.svg'),
     os.path.join('assets', 'images')),
    # 内嵌字体：core.load_embedded_font() 按 __file__ 相对 assets/fonts/ 注册，
    # 漏带则回退系统字体（界面不会崩，但默认字体失效）。许可证随字体一并分发。
    (os.path.join('src', 'assets', 'fonts', 'MiSans-Regular.ttf'),
     os.path.join('assets', 'fonts')),
    (os.path.join('src', 'assets', 'fonts', 'HarmonyOS_Sans_SC_Regular.ttf'),
     os.path.join('assets', 'fonts')),
    (os.path.join('src', 'assets', 'fonts', 'HarmonyOS_Sans_SC_LICENSE.txt'),
     os.path.join('assets', 'fonts')),
    # 浏览器仪表盘内嵌字体：flaskserver 经 /font.css + /font-file 提供。
    # 只带 woff2（4 MB）——TTF 7.9 MB 是桌面端 Qt 用的，网页端用不上，不再进包体
    (os.path.join('src', 'assets', 'fonts', 'HarmonyOS_Sans_SC_Regular.woff2'),
     os.path.join('assets', 'fonts')),
]
# docs/images 其余 png 为 README 截图，运行时用不到，不打包以控包体
# FluentWidgets 的 FluentIcon 资源（SVG/QSS）
datas += collect_data_files('qfluentwidgets')

a = Analysis(
    ['src/main.py'],
    pathex=['src'],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # qfluentwidgets 图标渲染依赖 QtSvg（静态扫描可能漏掉）
        'PySide6.QtSvg',
        'PySide6.QtSvgWidgets',
        # flaskserver 插件延迟导入 flask（插件顶层不 import），静态分析漏掉
        'flask',
        'werkzeug',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PhysChem-DigitizerP',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,           # 保留控制台：传感器加载/串口日志直接可见，便于排障
    icon=os.path.join('src', 'assets', 'images', 'icon.ico'),   # exe 文件图标
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='PhysChem-DigitizerP',
)
