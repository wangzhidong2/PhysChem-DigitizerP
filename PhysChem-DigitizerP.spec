# -*- mode: python ; coding: utf-8 -*-
# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

"""PhysChem-DigitizerP 打包配置（PyInstaller onedir 模式）

用法：
    pip install pyinstaller
    pyinstaller --noconfirm PhysChem-DigitizerP.spec

产物：dist/PhysChem-DigitizerP/ 整个目录即绿色程序，压缩后即可分发。

原理（无需改动源码）：
- 传感器模块由 main.py 用 importlib 按 `__file__` 相对路径动态加载，
  PyInstaller 静态分析发现不了，必须作为数据文件手动收集；
  onedir 模式下 main 脚本的 `__file__` 指向 _internal/（PyInstaller 6+），
  datas 收集的文件恰好落在同一目录，运行时路径自然对上。
- 窗口图标 docs/images/icon.ico 同理按 `__file__` 相对路径查找，一并打包。
- qfluentwidgets 的 FluentIcon SVG 资源用 collect_data_files 收集。

注意事项：
- onedir 目录模式（非单文件）：onefile 每次运行解压到临时目录，启动慢且
  sensor_config.json / app_config.json 无法跨次持久。
- console=True 保留控制台窗口，传感器加载、串口收发日志实时可见。
- 新增传感器模块后重新打包；打包产物内也可以直接往
  _internal/传感器代码/<子目录>/ 丢 .py 实现免重打包热插拔。
"""

import os
from PyInstaller.utils.hooks import collect_data_files

# --- 只收集传感器模块源码，排除商家资料 / 缓存 / 测试文件 ---
sensor_datas = []
for dirpath, dirnames, filenames in os.walk('传感器代码'):
    if '__pycache__' in dirpath:
        continue
    # 排除「资料（xxx商家提供的）」等非代码目录，避免包体膨胀
    if '资料' in dirpath:
        continue
    for fn in filenames:
        if fn.endswith('.py') and not fn.startswith('_') and not fn.startswith('test'):
            sensor_datas.append((os.path.join(dirpath, fn), dirpath))

datas = sensor_datas + [
    # 窗口图标：main.py 按 __file__ 相对 docs/images/icon.ico 加载
    (os.path.join('docs', 'images', 'icon.ico'), os.path.join('docs', 'images')),
    # Gitee / GitCode 平台 logo：主页与设置页按 docs/images/ 相对路径加载，
    # 加载失败仅回退 FluentIcon，但正常分发应带全
    (os.path.join('docs', 'images', 'gitee.svg'), os.path.join('docs', 'images')),
    (os.path.join('docs', 'images', 'gitcode.svg'), os.path.join('docs', 'images')),
]
# docs/images 其余 png 为 README 截图，运行时用不到，不打包以控包体
# FluentWidgets 的 FluentIcon 资源（SVG/QSS）
datas += collect_data_files('qfluentwidgets')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # qfluentwidgets 图标渲染依赖 QtSvg（静态扫描可能漏掉）
        'PySide6.QtSvg',
        'PySide6.QtSvgWidgets',
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
    icon=os.path.join('docs', 'images', 'icon.ico'),   # exe 文件图标
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='PhysChem-DigitizerP',
)
