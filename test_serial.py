#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
串口连接测试脚本
用于诊断串口连接问题
"""

import serial
import serial.tools.list_ports
import time

def test_serial_connection():
    """测试串口连接"""
    print("=== 串口连接测试 ===")
    
    # 列出所有可用串口
    print("\n1. 检测可用串口:")
    ports = serial.tools.list_ports.comports()
    
    if not ports:
        print("   ❌ 未检测到任何串口设备")
        print("   请检查:")
        print("   - USB 线是否连接")
        print("   - 设备管理器中的串口驱动")
        print("   - WeMOS D1 是否正常工作")
        return
    
    for i, port in enumerate(ports):
        print(f"   {i+1}. {port.device} - {port.description}")
    
    # 测试每个串口
    print("\n2. 测试串口连接:")
    for port in ports:
        print(f"\n   测试 {port.device}:")
        
        try:
            # 尝试连接
            ser = serial.Serial(port.device, 115200, timeout=2)
            print("   ✅ 串口连接成功")
            
            # 清空缓冲区
            ser.reset_input_buffer()
            
            # 尝试读取数据
            print("   等待数据接收(5秒)...")
            start_time = time.time()
            data_received = False
            
            while time.time() - start_time < 5:
                if ser.in_waiting > 0:
                    try:
                        line = ser.readline().decode('utf-8', errors='ignore').strip()
                        if line:
                            print(f"   ✅ 接收到数据: {line}")
                            data_received = True
                            break
                    except Exception as e:
                        print(f"   ❌ 数据解码错误: {e}")
                time.sleep(0.1)
            
            if not data_received:
                print("   ⚠️  未接收到数据")
                print("   可能原因:")
                print("   - Arduino 代码未正确上传")
                print("   - 波特率不匹配(应为115200)")
                print("   - 传感器模块未正常工作")
            
            ser.close()
            
        except Exception as e:
            print(f"   ❌ 连接失败: {e}")
            print("   可能原因:")
            print("   - 串口被其他程序占用")
            print("   - 权限问题")
            print("   - 驱动问题")
    
    print("\n3. 故障排除建议:")
    print("   a. 检查 Arduino IDE 串口监视器是否能正常接收数据")
    print("   b. 确认 WeMOS D1 开发板选择正确")
    print("   c. 确认 HC-SR04 模块接线正确")
    print("   d. 尝试重新插拔 USB 线")
    print("   e. 重启电脑或 Arduino IDE")

if __name__ == '__main__':
    test_serial_connection()
    input("\n按回车键退出...")