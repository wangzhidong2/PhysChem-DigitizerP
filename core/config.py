# -*- coding: utf-8 -*-
"""core/config.py — 统一配置管理

所有传感器模块的校准参数保存在同一个 JSON 文件 sensor_config.json 中，
位于仓库根目录。模块名作为 key 区分各传感器配置。
"""

import os
import json

# 配置文件名（位于仓库根目录）
CONFIG_FILENAME = 'sensor_config.json'


def _get_config_file_path():
    """获取统一配置文件的绝对路径。

    配置文件始终位于仓库根目录（main.py 所在目录），
    与具体模块文件位置无关。
    """
    # core/ 是包，__file__ 是 core/config.py，上溯一级即仓库根
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    return os.path.join(root, CONFIG_FILENAME)


def load_sensor_config(module_name):
    """从统一配置文件中读取指定模块的配置。

    Args:
        module_name: 模块名称，如 'ph_sensor'、'force_sensor'

    Returns:
        dict: 该模块的配置字典，不存在则返回空字典
    """
    config_path = _get_config_file_path()
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                all_config = json.load(f)
            module_config = all_config.get(module_name, {})
            if module_config:
                print(f"✓ 已加载 [{module_name}] 配置")
            else:
                print(f"ℹ️ [{module_name}] 无已保存配置，使用默认值")
            return module_config
        else:
            print(f"ℹ️ 配置文件不存在：{config_path}，所有模块使用默认值")
            return {}
    except Exception as e:
        print(f"⚠️ 读取配置文件失败：{e}")
        return {}


def save_sensor_config(module_name, config_dict):
    """将指定模块的配置写入统一配置文件。

    Args:
        module_name: 模块名称
        config_dict: 该模块的配置字典

    Returns:
        bool: 是否保存成功
    """
    config_path = _get_config_file_path()
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                all_config = json.load(f)
        else:
            all_config = {}

        all_config[module_name] = config_dict

        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(all_config, f, ensure_ascii=False, indent=2)

        print(f"✓ [{module_name}] 配置已保存到 {config_path}")
        return True
    except Exception as e:
        print(f"⚠️ 保存 [{module_name}] 配置失败：{e}")
        return False
