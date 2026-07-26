# -*- coding: utf-8 -*-
"""core/serial_thread.py — 串口通信线程

基于 QThread 的串口数据接收线程，逐行读取并以信号形式发射。
所有固件统一输出 CSV：`timestamp,value`，本线程只负责把每一行原样上抛，
解析工作交给各传感器 Backend。
"""

import serial
import serial.tools.list_ports

from PySide6.QtCore import QThread, Signal


def list_serial_ports():
    """枚举当前可用串口，返回 [(device, description), ...]。"""
    result = []
    for p in serial.tools.list_ports.comports():
        result.append((p.device, p.description or p.device))
    return result


class SerialThread(QThread):
    """串口通信线程。

    Signals:
        data_received(str): 收到一行数据（已 strip）。
                            错误时形如 "ERROR:<msg>"，启动信号为 "START"。
    """
    data_received = Signal(str)

    def __init__(self, port, baudrate=115200):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.serial = None
        self.running = False

    def run(self):
        try:
            self.serial = serial.Serial(self.port, self.baudrate, timeout=1)
            self.running = True
            self.serial.reset_input_buffer()

            while self.running:
                try:
                    if self.serial.in_waiting > 0:
                        line = self.serial.readline().decode(
                            'utf-8', errors='ignore').strip()
                        if line:
                            self.data_received.emit(line)
                except Exception as e:
                    print(f"读取串口数据错误: {e}")
                    break
        except Exception as e:
            print(f"串口错误: {e}")
            self.data_received.emit(f"ERROR:{e}")

    def stop(self):
        self.running = False
        if self.serial:
            try:
                self.serial.close()
            except Exception:
                pass
