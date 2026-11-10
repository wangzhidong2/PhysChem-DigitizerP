# Copyright (c) 2026 wangzhidong2
# SPDX-License-Identifier: GPL-3.0-only

# -*- coding: utf-8 -*-
"""
module_loader.py — 传感器模块与插件加载器

只负责扫描目录、解析识别区、importlib 动态加载，不含任何 UI。
main.py 只做 UI 编排，通过 scan_modules() / load_plugins() 取得结果。
"""

import os
import sys
import glob
import re
import importlib.util

from core import get_logger

log = get_logger('module_loader')


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
        dict: {'icon': ..., 'name': ..., 'category': ..., 'class': ...,
               可选 'icon_file': ...（assets/ 下图标文件名，多模块共目录时区分图标）}
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


def load_module_kernel(module_file, meta):
    """按 MODULE META 的 kernel 字段加载同目录内核类。

    格式：
        # kernel: _kernel_displacement:DisplacementKernel
    没有 kernel 字段时返回 None（旧模块继续走原 QWidget 逻辑）。
    """
    spec_text = str(meta.get('kernel') or '').strip()
    if not spec_text:
        return None
    if ':' in spec_text:
        rel_path, cls_name = spec_text.split(':', 1)
    else:
        rel_path, cls_name = spec_text, 'Kernel'
    rel_path = rel_path.strip()
    cls_name = cls_name.strip()
    if not rel_path.endswith('.py'):
        rel_path += '.py'
    kernel_path = os.path.join(os.path.dirname(module_file), rel_path)
    if not os.path.isfile(kernel_path):
        log.warning("模块内核文件不存在: %s", kernel_path)
        return None
    mod_name = '_sensor_kernel_%s' % os.path.splitext(
        os.path.basename(kernel_path))[0].lstrip('_')
    try:
        spec = importlib.util.spec_from_file_location(mod_name, kernel_path)
        if spec is None or spec.loader is None:
            log.warning("无法加载模块内核: %s", kernel_path)
            return None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        kernel_cls = getattr(mod, cls_name)
        log.info("✓ 已加载内核: %s (%s)", cls_name, kernel_path)
        return kernel_cls
    except Exception as e:
        log.error("模块内核加载失败 %s: %s", kernel_path, e)
        return None


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
                'key': meta.get('key'),
                'icon': meta['icon'],
                'icon_file': meta.get('icon_file'),
                'category': meta['category'],
                'class_name': class_name,
                'module': mod,
                'file_path': py_file,
                'kernel_class': load_module_kernel(py_file, meta),
            })
            log.info("✓ 已加载模块: %s (%s) <- %s",
                     meta['name'], meta['category'], base)

    discovered.sort(key=lambda x: (x['category'], x['name']))
    return discovered


# ============================================================
# 插件加载（flaskserver 等）
#
# 扫描 main.py 所在目录（src/）下的一级子目录：内有 __init__.py 且文件头 50 行含
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
