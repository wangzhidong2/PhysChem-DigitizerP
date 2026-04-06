#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
物理实验数据采集软件 - 启动脚本
"""

import sys
import os

# 添加当前目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from main import main
    
    if __name__ == '__main__':
        main()
        
except ImportError as e:
    print("错误: 缺少必要的依赖包")
    print("请运行以下命令安装依赖:")
    print("pip install -r requirements.txt")
    print(f"详细错误: {e}")
    input("按回车键退出...")