# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 — PhysChem-DigitizerP

用法（在 Windows 上）：
    pyinstaller physchem.spec

输出：
    dist/PhysChem-DigitizerP/PhysChem-DigitizerP.exe   （onedir 模式）

说明：
- onedir 模式：启动快，便于排查问题，可热更新 传感器代码/ 下的 .py
- 传感器代码/ 目录作为 datas 打包，运行时从 _MEIPASS/传感器代码/ 加载
- 配置文件 sensor_config.json 不打包，运行时在 EXE 同级目录自动生成
- bleak 为可选依赖，安装后会自动包含；未安装则 BLE 功能降级
"""

import os

block_cipher = None

# 传感器代码目录（含 .py 模块 + .ino 固件参考）
# datas 格式：(源路径, 打包后目标目录)
datas = [
    ('传感器代码', '传感器代码'),
]

# 隐式依赖（PyInstaller 静态分析检测不到的）
hiddenimports = [
    # 动态加载的传感器模块（importlib.util.spec_from_file_location 加载）
    # 虽然作为 datas 打包，但显式声明可确保其依赖被正确收集
    'bleak',  # BLE 可选依赖，未安装时会被 PyInstaller 自动忽略
]

# 排除的模块（减小体积）
# 注意：bleak 依赖 socket/ssl/http 等，不可排除
excludes = [
    'test_serial',
    'main_legacy',
    'tkinter',
    'unittest',
    'pydoc',
    'doctest',
    'pdb',
    'profile',
    'pstats',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 收集 matplotlib 数据文件（字体、样式等）
from PyInstaller.utils.hooks import collect_data_files
a.datas += collect_data_files('matplotlib')

# 收集 PyQt6 平台插件和翻译（通常 PyInstaller 会自动处理，显式声明更稳妥）
a.datas += collect_data_files('PyQt6')

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PhysChem-DigitizerP',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI 程序，不显示控制台
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='docs/images/icon.ico',  # 如有图标可取消注释
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PhysChem-DigitizerP',
)
