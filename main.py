#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
物理实验数据采集软件
基于 PyQt6 的 Win11 风格界面
支持多种传感器模块的数据采集和管理
"""

import sys
import os
import json
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLabel, QPushButton, QFrame, QStackedWidget,
                            QListWidget, QListWidgetItem, QMessageBox, QComboBox,
                            QTextEdit, QGroupBox, QSpinBox, QDoubleSpinBox, QCheckBox,
                            QStyle)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QSize
from PyQt6.QtGui import QFont, QIcon, QPalette, QColor
import serial
import serial.tools.list_ports
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np


class SerialThread(QThread):
    """串口通信线程"""
    data_received = pyqtSignal(str)
    
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
            
            # 清空串口缓冲区
            self.serial.reset_input_buffer()
            
            while self.running:
                try:
                    if self.serial.in_waiting > 0:
                        line = self.serial.readline().decode('utf-8', errors='ignore').strip()
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
            self.serial.close()


class UltrasonicWidget(QWidget):
    """超声波位移模块界面"""
    
    def __init__(self):
        super().__init__()
        self.serial_thread = None
        self.data_points = []
        self.timestamps = []
        self.start_time = None
        self.start_timestamp_us = 0  # 记录第一个数据点的时间戳
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # 控制面板
        control_group = QGroupBox("控制面板")
        control_layout = QHBoxLayout()
        
        # 串口选择
        control_layout.addWidget(QLabel("串口:"))
        self.port_combo = QComboBox()
        self.refresh_ports()
        control_layout.addWidget(self.port_combo)
        
        # 刷新按钮
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        control_layout.addWidget(self.refresh_btn)
        
        # 连接按钮
        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(self.toggle_connection)
        control_layout.addWidget(self.connect_btn)
        
        control_layout.addStretch()
        
        # 采样率设置
        control_layout.addWidget(QLabel("采样率:"))
        self.sample_rate_spin = QSpinBox()
        self.sample_rate_spin.setRange(1, 100)
        self.sample_rate_spin.setValue(50)
        self.sample_rate_spin.setSuffix(" Hz")
        control_layout.addWidget(self.sample_rate_spin)
        
        control_group.setLayout(control_layout)
        layout.addWidget(control_group)
        
        # 数据显示区域
        data_group = QGroupBox("实时数据")
        data_layout = QHBoxLayout()
        
        # 左侧：文本数据显示
        text_widget = QWidget()
        text_layout = QVBoxLayout()
        
        # 当前数据
        self.current_data_label = QLabel("当前数据: 等待连接...")
        self.current_data_label.setFont(QFont("Arial", 12))
        text_layout.addWidget(self.current_data_label)
        
        # 数据统计
        self.stats_label = QLabel("统计信息: 暂无数据")
        text_layout.addWidget(self.stats_label)
        
        # 数据记录
        self.data_text = QTextEdit()
        self.data_text.setMaximumHeight(150)
        text_layout.addWidget(QLabel("数据记录:"))
        text_layout.addWidget(self.data_text)
        
        text_widget.setLayout(text_layout)
        data_layout.addWidget(text_widget)
        
        # 右侧：图表显示
        self.figure = Figure(figsize=(8, 6))
        self.canvas = FigureCanvas(self.figure)
        data_layout.addWidget(self.canvas)
        
        data_group.setLayout(data_layout)
        layout.addWidget(data_group)
        
        # 控制按钮
        button_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("开始采集")
        self.start_btn.clicked.connect(self.start_collection)
        self.start_btn.setEnabled(False)
        button_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("停止采集")
        self.stop_btn.clicked.connect(self.stop_collection)
        self.stop_btn.setEnabled(False)
        button_layout.addWidget(self.stop_btn)
        
        self.save_btn = QPushButton("保存数据")
        self.save_btn.clicked.connect(self.save_data)
        self.save_btn.setEnabled(False)
        button_layout.addWidget(self.save_btn)
        
        self.clear_btn = QPushButton("清除数据")
        self.clear_btn.clicked.connect(self.clear_data)
        button_layout.addWidget(self.clear_btn)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
        
        # 定时器用于更新图表
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_chart)
        self.timer.start(100)  # 每100ms更新一次图表
    
    def refresh_ports(self):
        """刷新可用串口列表"""
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.port_combo.addItem(port.device)
    
    def toggle_connection(self):
        """切换串口连接状态"""
        if self.serial_thread and self.serial_thread.isRunning():
            self.disconnect_serial()
        else:
            self.connect_serial()
    
    def connect_serial(self):
        """连接串口"""
        port = self.port_combo.currentText()
        if not port:
            QMessageBox.warning(self, "错误", "请选择串口")
            return
        
        try:
            self.serial_thread = SerialThread(port)
            self.serial_thread.data_received.connect(self.handle_data)
            self.serial_thread.start()
            
            self.connect_btn.setText("断开")
            self.start_btn.setEnabled(True)
            self.current_data_label.setText("当前数据: 已连接，等待数据...")
            
        except Exception as e:
            QMessageBox.critical(self, "连接错误", f"无法连接串口: {e}")
    
    def disconnect_serial(self):
        """断开串口连接"""
        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread.wait()
            self.serial_thread = None
        
        self.connect_btn.setText("连接")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.current_data_label.setText("当前数据: 已断开")
    
    def start_collection(self):
        """开始数据采集"""
        self.data_points.clear()
        self.timestamps.clear()
        self.start_time = datetime.now()
        self.data_text.clear()
        
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.save_btn.setEnabled(False)
        
        self.current_data_label.setText("当前数据: 采集进行中...")
    
    def stop_collection(self):
        """停止数据采集"""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.save_btn.setEnabled(len(self.data_points) > 0)
        
        self.current_data_label.setText("当前数据: 采集已停止")
    
    def handle_data(self, data):
        """处理接收到的数据"""
        # 检查是否是错误信息
        if data.startswith("ERROR:"):
            QMessageBox.critical(self, "串口错误", data[6:])
            self.disconnect_serial()
            return
        
        # 检查是否是启动信号
        if data == "START":
            self.current_data_label.setText("当前数据: 设备已启动，等待数据...")
            return
        
        if not self.stop_btn.isEnabled():  # 如果没有在采集状态，忽略数据
            return
        
        try:
            # 解析数据格式: timestamp,echo_time
            if "," in data:
                parts = data.split(",")
                if len(parts) == 2:
                    timestamp_us = int(parts[0])  # 微秒时间戳
                    echo_time = int(parts[1])
                    
                    # 过滤无效数据（回波时间过小或过大）
                    if echo_time < 100 or echo_time > 60000:  # 100µs - 60ms
                        return
                    
                    # 计算距离（厘米）
                    distance_cm = echo_time / 58.0
                    
                    # 记录数据
                    current_time = datetime.now()
                    time_str = current_time.strftime("%H:%M:%S.%f")[:-3]
                    
                    # 如果是第一个数据点，记录起始时间
                    if len(self.timestamps) == 0:
                        self.start_timestamp_us = timestamp_us
                    
                    # 计算相对于起始时间的秒数
                    relative_time_s = (timestamp_us - self.start_timestamp_us) / 1000000.0
                    
                    self.data_points.append(distance_cm)
                    self.timestamps.append(relative_time_s)  # 相对时间（秒）
                    
                    # 更新显示
                    display_text = f"时间: {time_str} | 回波: {echo_time}µs | 距离: {distance_cm:.2f}cm | 相对时间: {relative_time_s:.3f}s"
                    self.current_data_label.setText(f"当前数据: {display_text}")
                    
                    # 添加到数据记录
                    self.data_text.append(display_text)
                    
                    # 自动滚动到底部
                    self.data_text.verticalScrollBar().setValue(
                        self.data_text.verticalScrollBar().maximum()
                    )
                    
                    # 更新统计信息
                    self.update_stats()
                    
        except ValueError:
            pass  # 忽略无法解析的数据
    
    def update_stats(self):
        """更新统计信息"""
        if len(self.data_points) > 0:
            avg_distance = np.mean(self.data_points)
            max_distance = np.max(self.data_points)
            min_distance = np.min(self.data_points)
            
            stats_text = f"统计信息: 数据点 {len(self.data_points)} | " \
                        f"平均 {avg_distance:.2f}cm | " \
                        f"最大 {max_distance:.2f}cm | " \
                        f"最小 {min_distance:.2f}cm"
            self.stats_label.setText(stats_text)
    
    def update_chart(self):
        """更新图表"""
        if len(self.data_points) > 0:
            self.figure.clear()
            ax = self.figure.add_subplot(111)
            
            ax.plot(self.timestamps, self.data_points, 'b-', linewidth=2)
            ax.set_xlabel('时间 (秒)')
            ax.set_ylabel('距离 (厘米)')
            ax.set_title('距离传感器的距离 - 实时数据')
            ax.grid(True, alpha=0.3)
            
            # 自动调整坐标轴范围
            if len(self.timestamps) > 1:
                time_range = max(self.timestamps) - min(self.timestamps)
                distance_range = max(self.data_points) - min(self.data_points)
                
                if time_range > 0:
                    ax.set_xlim(min(self.timestamps), max(self.timestamps))
                if distance_range > 0:
                    ax.set_ylim(min(self.data_points) - 0.1 * distance_range,
                               max(self.data_points) + 0.1 * distance_range)
            
            self.canvas.draw()
    
    def save_data(self):
        """保存数据到文件"""
        if len(self.data_points) == 0:
            QMessageBox.warning(self, "警告", "没有数据可保存")
            return
        
        try:
            filename = f"ultrasonic_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("timestamp_ms,distance_cm\n")
                for i, (timestamp, distance) in enumerate(zip(self.timestamps, self.data_points)):
                    f.write(f"{timestamp*1000:.0f},{distance:.3f}\n")
            
            QMessageBox.information(self, "成功", f"数据已保存到: {filename}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")
    
    def clear_data(self):
        """清除数据"""
        self.data_points.clear()
        self.timestamps.clear()
        self.data_text.clear()
        self.stats_label.setText("统计信息: 暂无数据")
        self.current_data_label.setText("当前数据: 等待数据...")
        self.figure.clear()
        self.canvas.draw()
        self.save_btn.setEnabled(False)


class UltrasonicVelocityWidget(QWidget):
    """超声波速度模块界面 - 回声定位法"""
    
    def __init__(self):
        super().__init__()
        self.serial_thread = None
        self.distance_data = []    # 距离数据
        self.time_data = []        # 时间数据
        self.velocity_data = []    # 速度数据
        self.echo_time_data = []   # 原始回波时间数据 (µs)
        self.start_timestamp_us = 0
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # 控制面板
        control_group = QGroupBox("控制面板")
        control_layout = QHBoxLayout()
        
        # 串口选择
        control_layout.addWidget(QLabel("串口:"))
        self.port_combo = QComboBox()
        self.refresh_ports()
        control_layout.addWidget(self.port_combo)
        
        # 刷新按钮
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        control_layout.addWidget(self.refresh_btn)
        
        # 连接按钮
        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(self.toggle_connection)
        control_layout.addWidget(self.connect_btn)
        
        control_layout.addStretch()
        
        # 速度计算参数
        control_layout.addWidget(QLabel("采样窗口:"))
        self.window_size_spin = QSpinBox()
        self.window_size_spin.setRange(5, 100)
        self.window_size_spin.setValue(10)
        self.window_size_spin.setSuffix(" 点")
        control_layout.addWidget(self.window_size_spin)
        
        control_group.setLayout(control_layout)
        layout.addWidget(control_group)
        
        # 数据显示区域
        data_group = QGroupBox("实时数据")
        data_layout = QHBoxLayout()
        
        # 左侧：文本数据显示
        text_widget = QWidget()
        text_layout = QVBoxLayout()
        
        # 当前数据
        self.current_data_label = QLabel("当前数据: 等待连接...")
        self.current_data_label.setFont(QFont("Arial", 12))
        text_layout.addWidget(self.current_data_label)
        
        # 速度统计
        self.velocity_stats_label = QLabel("速度统计: 暂无数据")
        text_layout.addWidget(self.velocity_stats_label)
        
        # 数据记录
        self.data_text = QTextEdit()
        self.data_text.setMaximumHeight(150)
        text_layout.addWidget(QLabel("速度记录:"))
        text_layout.addWidget(self.data_text)
        
        text_widget.setLayout(text_layout)
        data_layout.addWidget(text_widget)
        
        # 右侧：图表显示
        self.figure = Figure(figsize=(8, 6))
        self.canvas = FigureCanvas(self.figure)
        data_layout.addWidget(self.canvas)
        
        data_group.setLayout(data_layout)
        layout.addWidget(data_group)
        
        # 控制按钮
        button_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("开始采集")
        self.start_btn.clicked.connect(self.start_collection)
        self.start_btn.setEnabled(False)
        button_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("停止采集")
        self.stop_btn.clicked.connect(self.stop_collection)
        self.stop_btn.setEnabled(False)
        button_layout.addWidget(self.stop_btn)
        
        self.save_btn = QPushButton("保存数据")
        self.save_btn.clicked.connect(self.save_data)
        self.save_btn.setEnabled(False)
        button_layout.addWidget(self.save_btn)
        
        self.clear_btn = QPushButton("清除数据")
        self.clear_btn.clicked.connect(self.clear_data)
        button_layout.addWidget(self.clear_btn)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
        
        # 定时器用于更新图表
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_chart)
        self.timer.start(100)  # 每100ms更新一次图表
    
    def refresh_ports(self):
        """刷新可用串口列表"""
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.port_combo.addItem(port.device)
    
    def toggle_connection(self):
        """切换串口连接状态"""
        if self.serial_thread and self.serial_thread.isRunning():
            self.disconnect_serial()
        else:
            self.connect_serial()
    
    def connect_serial(self):
        """连接串口"""
        port = self.port_combo.currentText()
        if not port:
            QMessageBox.warning(self, "错误", "请选择串口")
            return
        
        try:
            self.serial_thread = SerialThread(port)
            self.serial_thread.data_received.connect(self.handle_data)
            self.serial_thread.start()
            
            self.connect_btn.setText("断开")
            self.start_btn.setEnabled(True)
            self.current_data_label.setText("当前数据: 已连接，等待数据...")
            
        except Exception as e:
            QMessageBox.critical(self, "连接错误", f"无法连接串口: {e}")
    
    def disconnect_serial(self):
        """断开串口连接"""
        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread.wait()
            self.serial_thread = None
        
        self.connect_btn.setText("连接")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.current_data_label.setText("当前数据: 已断开")
    
    def start_collection(self):
        """开始数据采集"""
        self.distance_data.clear()
        self.time_data.clear()
        self.velocity_data.clear()
        self.echo_time_data.clear()  # 清除回波时间数据
        self.data_text.clear()
        
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.save_btn.setEnabled(False)
        
        self.current_data_label.setText("当前数据: 采集进行中...")
    
    def stop_collection(self):
        """停止数据采集"""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.save_btn.setEnabled(len(self.distance_data) > 0)
        
        self.current_data_label.setText("当前数据: 采集已停止")
    
    def handle_data(self, data):
        """处理接收到的数据 - 回声定位法计算速度"""
        # 检查是否是错误信息
        if data.startswith("ERROR:"):
            QMessageBox.critical(self, "串口错误", data[6:])
            self.disconnect_serial()
            return
        
        # 检查是否是启动信号
        if data == "START":
            self.current_data_label.setText("当前数据: 设备已启动，等待数据...")
            return
        
        if not self.stop_btn.isEnabled():  # 如果没有在采集状态，忽略数据
            return
        
        try:
            # 解析数据格式: timestamp,echo_time
            if "," in data:
                parts = data.split(",")
                if len(parts) == 2:
                    timestamp_us = int(parts[0])  # 微秒时间戳
                    echo_time = int(parts[1])
                    
                    # 过滤无效数据
                    if echo_time < 100 or echo_time > 60000:
                        return
                    
                    # 计算距离（厘米）
                    distance_cm = echo_time / 58.0
                    
                    # 如果是第一个数据点，记录起始时间
                    if len(self.time_data) == 0:
                        self.start_timestamp_us = timestamp_us
                    
                    # 计算相对于起始时间的秒数
                    relative_time_s = (timestamp_us - self.start_timestamp_us) / 1000000.0
                    
                    # 记录距离、时间和原始回波时间数据
                    self.distance_data.append(distance_cm)
                    self.time_data.append(relative_time_s)
                    self.echo_time_data.append(echo_time)  # 保存原始回波时间
                    
                    # 回声定位法计算速度
                    velocity = self.calculate_velocity()
                    if velocity is not None:
                        self.velocity_data.append(velocity)
                    
                    # 更新显示
                    current_time = datetime.now()
                    time_str = current_time.strftime("%H:%M:%S.%f")[:-3]
                    
                    if velocity is not None:
                        display_text = f"时间: {time_str} | 距离: {distance_cm:.2f}cm | 速度: {velocity:.2f}cm/s"
                        self.current_data_label.setText(f"当前数据: {display_text}")
                        
                        # 添加到数据记录
                        self.data_text.append(display_text)
                        
                        # 自动滚动到底部
                        self.data_text.verticalScrollBar().setValue(
                            self.data_text.verticalScrollBar().maximum()
                        )
                    
                    # 更新统计信息
                    self.update_stats()
                    
        except ValueError:
            pass  # 忽略无法解析的数据
    
    def calculate_velocity(self):
        """回声定位法计算速度 - 基于两次测量的时间差
        
        算法原理：
        v = (t₀ - t₁)/2 × vₛ / [(t₁ + t₀)/2 + Δt]
        
        其中：
        - t₀: 第一次回波时间 (µs)
        - t₁: 第二次回波时间 (µs)
        - Δt: 两次发射的时间间隔 (s)
        - vₛ: 声速 = 34000 cm/s
        """
        if len(self.distance_data) < 2:
            return None
        
        try:
            # 获取最近两次测量的数据
            t0 = self.echo_time_data[-2]  # 第一次回波时间 (µs)
            t1 = self.echo_time_data[-1]  # 第二次回波时间 (µs)
            
            # 计算两次发射的时间间隔 Δt (秒)
            # 使用 Arduino 的测量间隔 (MIN_INTERVAL = 20000 µs = 0.02s)
            delta_t = 0.02  # 默认 20ms
            if len(self.time_data) >= 2:
                delta_t = self.time_data[-1] - self.time_data[-2]
            
            # 声速 (cm/s)
            v_sound = 34000  # 340 m/s = 34000 cm/s
            
            # 计算速度 (cm/s)
            # v = (t₀ - t₁)/2 × vₛ / [(t₁ + t₀)/2 + Δt]
            numerator = (t0 - t1) / 2.0 * v_sound
            denominator = (t1 + t0) / 2.0 + delta_t * 1000000  # 将 Δt 转换为 µs
            
            if denominator == 0:
                return None
            
            velocity_cm_s = numerator / denominator
            
            return velocity_cm_s
            
        except Exception as e:
            print(f"速度计算错误: {e}")
            return None
    
    def update_stats(self):
        """更新速度统计信息"""
        if len(self.velocity_data) > 0:
            avg_velocity = np.mean(self.velocity_data)
            max_velocity = np.max(self.velocity_data)
            min_velocity = np.min(self.velocity_data)
            
            stats_text = f"速度统计: 数据点 {len(self.velocity_data)} | " \
                        f"平均 {avg_velocity:.2f}cm/s | " \
                        f"最大 {max_velocity:.2f}cm/s | " \
                        f"最小 {min_velocity:.2f}cm/s"
            self.velocity_stats_label.setText(stats_text)
    
    def update_chart(self):
        """更新速度图表"""
        if len(self.velocity_data) > 0:
            self.figure.clear()
            
            # 创建子图
            ax1 = self.figure.add_subplot(211)  # 距离-时间图
            ax2 = self.figure.add_subplot(212)  # 速度-时间图
            
            # 绘制距离-时间图
            ax1.plot(self.time_data, self.distance_data, 'b-', linewidth=2)
            ax1.set_xlabel('时间 (秒)')
            ax1.set_ylabel('距离 (厘米)')
            ax1.set_title('距离传感器的距离')
            ax1.grid(True, alpha=0.3)
            
            # 绘制速度-时间图
            ax2.plot(self.time_data[len(self.time_data)-len(self.velocity_data):], 
                    self.velocity_data, 'r-', linewidth=2)
            ax2.set_xlabel('时间 (秒)')
            ax2.set_ylabel('速度 (厘米/秒)')
            ax2.set_title('物体运动速度 - 回声定位法')
            ax2.grid(True, alpha=0.3)
            
            # 自动调整布局
            self.figure.tight_layout()
            self.canvas.draw()
    
    def save_data(self):
        """保存数据到文件"""
        if len(self.distance_data) == 0:
            QMessageBox.warning(self, "警告", "没有数据可保存")
            return
        
        try:
            filename = f"ultrasonic_velocity_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("time_s,distance_cm,velocity_cm_s\n")
                for i, (time_val, distance, velocity) in enumerate(
                    zip(self.time_data, self.distance_data, 
                        self.velocity_data + [None] * (len(self.distance_data) - len(self.velocity_data)))):
                    
                    velocity_str = f"{velocity:.3f}" if velocity is not None else ""
                    f.write(f"{time_val:.3f},{distance:.3f},{velocity_str}\n")
            
            QMessageBox.information(self, "成功", f"数据已保存到: {filename}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")
    
    def clear_data(self):
        """清除数据"""
        self.distance_data.clear()
        self.time_data.clear()
        self.velocity_data.clear()
        self.echo_time_data.clear()  # 清除回波时间数据
        self.data_text.clear()
        self.velocity_stats_label.setText("速度统计: 暂无数据")
        self.current_data_label.setText("当前数据: 等待数据...")
        self.figure.clear()
        self.canvas.draw()
        self.save_btn.setEnabled(False)


class PhSensorWidget(QWidget):
    """pH传感器模块界面 - 支持三点校准"""
    
    def __init__(self):
        super().__init__()
        self.serial_thread = None
        self.ph_data = []          # pH 值数据
        self.time_data = []        # 时间数据
        self.adc_data = []         # 原始 ADC 数据
        self.start_timestamp_ms = 0
        
        # 三点校准参数 (pH, ADC) - 在 init_ui() 之前定义
        self.calibration_points = [
            (4.00, 2555),   # 酸性缓冲液
            (6.86, 2281),   # 中性缓冲液
            (9.18, 2030)    # 碱性缓冲液
        ]
        
        # 计算校准系数（二次拟合）
        self.calculate_calibration_coefficients()
        
        self.init_ui()
    
    def calculate_calibration_coefficients(self):
        """计算三点校准的二次拟合系数"""
        ph_values = [p[0] for p in self.calibration_points]
        adc_values = [p[1] for p in self.calibration_points]
        
        # 使用二次多项式拟合: pH = a*ADC^2 + b*ADC + c
        coefficients = np.polyfit(adc_values, ph_values, 2)
        self.cal_coeffs = coefficients  # [a, b, c]
    
    def adc_to_ph(self, adc_value):
        """将ADC原始值转换为pH值（使用三点校准）"""
        if not hasattr(self, 'cal_coeffs'):
            return 7.0
        
        a, b, c = self.cal_coeffs
        ph_value = a * (adc_value ** 2) + b * adc_value + c
        
        # 限制pH值在合理范围内（0-14）
        return max(0.0, min(14.0, ph_value))
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # 控制面板
        control_group = QGroupBox("控制面板")
        control_layout = QHBoxLayout()
        
        # 串口选择
        control_layout.addWidget(QLabel("串口:"))
        self.port_combo = QComboBox()
        self.refresh_ports()
        control_layout.addWidget(self.port_combo)
        
        # 刷新按钮
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        control_layout.addWidget(self.refresh_btn)
        
        # 连接按钮
        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(self.toggle_connection)
        control_layout.addWidget(self.connect_btn)
        
        control_layout.addStretch()
        
        # 校准信息显示
        control_layout.addWidget(QLabel("校准状态:"))
        self.calibration_label = QLabel("✓ 三点校准")
        self.calibration_label.setStyleSheet("color: green; font-weight: bold;")
        control_layout.addWidget(self.calibration_label)
        
        control_group.setLayout(control_layout)
        layout.addWidget(control_group)
        
        # 校准参数显示卡片
        cal_info_group = QGroupBox("校准参数")
        cal_info_layout = QVBoxLayout()
        
        cal_text = QLabel(
            f"• pH 4.00 → ADC {self.calibration_points[0][1]}\n"
            f"• pH 6.86 → ADC {self.calibration_points[1][1]}\n"
            f"• pH 9.18 → ADC {self.calibration_points[2][1]}"
        )
        cal_text.setStyleSheet("font-size: 12px; color: #666;")
        cal_info_layout.addWidget(cal_text)
        
        cal_info_group.setLayout(cal_info_layout)
        layout.addWidget(cal_info_group)
        
        # 数据显示区域
        data_group = QGroupBox("实时数据")
        data_layout = QHBoxLayout()
        
        # 左侧：文本数据显示
        text_widget = QWidget()
        text_layout = QVBoxLayout()
        
        # 当前pH值（大字显示）
        self.current_ph_label = QLabel("pH: --.-")
        self.current_ph_label.setFont(QFont("Arial", 28, QFont.Weight.Bold))
        self.current_ph_label.setStyleSheet("color: #0078d4; padding: 10px;")
        text_layout.addWidget(self.current_ph_label)
        
        # 当前ADC值
        self.current_adc_label = QLabel("ADC: ----")
        self.current_adc_label.setFont(QFont("Arial", 14))
        text_layout.addWidget(self.current_adc_label)
        
        # 统计信息
        self.stats_label = QLabel("统计信息: 暂无数据")
        text_layout.addWidget(self.stats_label)
        
        # 数据记录
        self.data_text = QTextEdit()
        self.data_text.setMaximumHeight(120)
        text_layout.addWidget(QLabel("数据记录:"))
        text_layout.addWidget(self.data_text)
        
        text_widget.setLayout(text_layout)
        data_layout.addWidget(text_widget)
        
        # 右侧：图表显示
        self.figure = Figure(figsize=(8, 5))
        self.canvas = FigureCanvas(self.figure)
        data_layout.addWidget(self.canvas)
        
        data_group.setLayout(data_layout)
        layout.addWidget(data_group)
        
        # 控制按钮
        button_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("开始采集")
        self.start_btn.clicked.connect(self.start_collection)
        self.start_btn.setEnabled(False)
        button_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("停止采集")
        self.stop_btn.clicked.connect(self.stop_collection)
        self.stop_btn.setEnabled(False)
        button_layout.addWidget(self.stop_btn)
        
        self.save_btn = QPushButton("保存数据")
        self.save_btn.clicked.connect(self.save_data)
        self.save_btn.setEnabled(False)
        button_layout.addWidget(self.save_btn)
        
        self.clear_btn = QPushButton("清除数据")
        self.clear_btn.clicked.connect(self.clear_data)
        button_layout.addWidget(self.clear_btn)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
        
        # 定时器用于更新图表
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_chart)
        self.timer.start(100)
    
    def refresh_ports(self):
        """刷新可用串口列表"""
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.port_combo.addItem(port.device)
    
    def toggle_connection(self):
        """切换串口连接状态"""
        if self.serial_thread and self.serial_thread.isRunning():
            self.disconnect_serial()
        else:
            self.connect_serial()
    
    def connect_serial(self):
        """连接串口"""
        port = self.port_combo.currentText()
        if not port:
            QMessageBox.warning(self, "错误", "请选择串口")
            return
        
        try:
            self.serial_thread = SerialThread(port)
            self.serial_thread.data_received.connect(self.handle_data)
            self.serial_thread.start()
            
            self.connect_btn.setText("断开")
            self.start_btn.setEnabled(True)
            self.current_ph_label.setText("pH: --.-")
            self.current_adc_label.setText("ADC: ----")
            
        except Exception as e:
            QMessageBox.critical(self, "连接错误", f"无法连接串口: {e}")
    
    def disconnect_serial(self):
        """断开串口连接"""
        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread.wait()
            self.serial_thread = None
        
        self.connect_btn.setText("连接")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.current_ph_label.setText("pH: --.-")
        self.current_adc_label.setText("ADC: 已断开")
    
    def start_collection(self):
        """开始数据采集"""
        self.ph_data.clear()
        self.time_data.clear()
        self.adc_data.clear()
        self.data_text.clear()
        
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.save_btn.setEnabled(False)
        
        self.current_ph_label.setText("pH: 采集中...")
        self.current_adc_label.setText("ADC: 采集中...")
    
    def stop_collection(self):
        """停止数据采集"""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.save_btn.setEnabled(len(self.ph_data) > 0)
        
        if len(self.ph_data) > 0:
            avg_ph = np.mean(self.ph_data)
            self.current_ph_label.setText(f"pH: {avg_ph:.2f}")
    
    def handle_data(self, data):
        """处理接收到的数据"""
        if data.startswith("ERROR:"):
            QMessageBox.critical(self, "串口错误", data[6:])
            self.disconnect_serial()
            return
        
        if data == "START":
            self.current_ph_label.setText("pH: 等待数据...")
            self.current_adc_label.setText("ADC: 设备就绪")
            return
        
        if not self.stop_btn.isEnabled():
            return
        
        try:
            if "," in data:
                parts = data.split(",")
                if len(parts) == 2:
                    timestamp_ms = int(parts[0])  # 毫秒时间戳
                    adc_value = int(parts[1])
                    
                    # 过滤无效ADC值（0-4095范围）
                    if adc_value < 0 or adc_value > 4095:
                        return
                    
                    # 记录起始时间
                    if len(self.time_data) == 0:
                        self.start_timestamp_ms = timestamp_ms
                    
                    # 计算相对时间（秒）
                    relative_time_s = (timestamp_ms - self.start_timestamp_ms) / 1000.0
                    
                    # 使用三点校准转换pH值
                    ph_value = self.adc_to_ph(adc_value)
                    
                    # 存储数据
                    self.ph_data.append(ph_value)
                    self.time_data.append(relative_time_s)
                    self.adc_data.append(adc_value)
                    
                    # 更新显示
                    current_time = datetime.now()
                    time_str = current_time.strftime("%H:%M:%S.%f")[:-3]
                    
                    display_text = f"时间: {time_str} | ADC: {adc_value} | pH: {ph_value:.2f}"
                    self.current_ph_label.setText(f"pH: {ph_value:.2f}")
                    self.current_adc_label.setText(f"ADC: {adc_value}")
                    
                    # 添加到数据记录
                    self.data_text.append(display_text)
                    self.data_text.verticalScrollBar().setValue(
                        self.data_text.verticalScrollBar().maximum()
                    )
                    
                    # 更新统计信息
                    self.update_stats()
                    
        except ValueError:
            pass
    
    def update_stats(self):
        """更新统计信息"""
        if len(self.ph_data) > 0:
            avg_ph = np.mean(self.ph_data)
            max_ph = np.max(self.ph_data)
            min_ph = np.min(self.ph_data)
            std_ph = np.std(self.ph_data)
            
            stats_text = (f"统计: 数据点 {len(self.ph_data)} | "
                         f"平均 pH={avg_ph:.2f} | "
                         f"最大 pH={max_ph:.2f} | "
                         f"最小 pH={min_ph:.2f} | "
                         f"标准差 σ={std_ph:.3f}")
            self.stats_label.setText(stats_text)
    
    def update_chart(self):
        """更新pH值图表"""
        if len(self.ph_data) > 0:
            self.figure.clear()
            ax = self.figure.add_subplot(111)
            
            # 绘制pH值曲线
            ax.plot(self.time_data, self.ph_data, 'b-', linewidth=2, label='pH值')
            
            # 添加参考线（中性pH=7）
            ax.axhline(y=7.0, color='r', linestyle='--', alpha=0.5, label='中性(pH=7)')
            
            ax.set_xlabel('时间 (秒)')
            ax.set_ylabel('pH值')
            ax.set_title('pH传感器实时数据', fontsize=14, fontweight='bold')
            ax.set_ylim(0, 14)
            ax.grid(True, alpha=0.3)
            ax.legend(loc='upper right')
            
            # 自动调整坐标轴范围
            if len(self.time_data) > 1:
                ax.set_xlim(min(self.time_data), max(self.time_data))
            
            self.figure.tight_layout()
            self.canvas.draw()
    
    def save_data(self):
        """保存数据到文件"""
        if len(self.ph_data) == 0:
            QMessageBox.warning(self, "警告", "没有数据可保存")
            return
        
        try:
            filename = f"ph_sensor_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("time_s,adc_raw,ph_value\n")
                for i, (time_val, ph_val, adc_val) in enumerate(
                    zip(self.time_data, self.ph_data, self.adc_data)):
                    f.write(f"{time_val:.3f},{adc_val},{ph_val:.3f}\n")
            
            QMessageBox.information(self, "成功", 
                                   f"数据已保存到: {filename}\n"
                                   f"共 {len(self.ph_data)} 个数据点")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")
    
    def clear_data(self):
        """清除数据"""
        self.ph_data.clear()
        self.time_data.clear()
        self.adc_data.clear()
        self.data_text.clear()
        self.stats_label.setText("统计信息: 暂无数据")
        self.current_ph_label.setText("pH: --.-")
        self.current_adc_label.setText("ADC: ----")
        self.figure.clear()
        self.canvas.draw()
        self.save_btn.setEnabled(False)


class SidebarWidget(QWidget):
    """可折叠侧边栏组件"""
    
    module_changed = pyqtSignal(int)
    
    def __init__(self):
        super().__init__()
        self.is_collapsed = False
        self.expanded_width = 200
        self.collapsed_width = 50
        self.init_ui()
    
    def init_ui(self):
        self.setFixedWidth(self.expanded_width)
        
        # 获取Qt标准图标
        self.style = QApplication.style()
        
        # 主布局
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        # 顶部折叠按钮
        self.toggle_button = QPushButton()
        self.toggle_button.setIcon(self.style.standardIcon(QStyle.StandardPixmap.SP_ArrowRight))
        self.toggle_button.setFixedSize(50, 50)
        self.toggle_button.setStyleSheet("""
            QPushButton {
                background-color: #f3f3f3;
                border: none;
                border-bottom: 1px solid #e0e0e0;
            }
            QPushButton:hover {
                background-color: #e8e8e8;
            }
            QPushButton:pressed {
                background-color: #d0d0d0;
            }
        """)
        self.toggle_button.clicked.connect(self.toggle_collapse)
        self.layout.addWidget(self.toggle_button)
        
        # 模块列表
        self.module_list = QListWidget()
        self.module_list.setStyleSheet("""
            QListWidget {
                background-color: #f3f3f3;
                border: none;
                font-size: 14px;
            }
            QListWidget::item {
                padding: 12px;
                padding-left: 15px;
                border-bottom: 1px solid #e0e0e0;
                border-left: 3px solid transparent;
                height: 48px;
            }
            QListWidget::item:selected {
                background-color: #e8e8e8;
                color: black;
                border-left: 3px solid #0078d4;
            }
            QListWidget::item:hover {
                background-color: #f0f0f0;
            }
        """)
        self.module_list.setIconSize(QSize(24, 24))
        self.module_list.currentRowChanged.connect(self.module_changed.emit)
        self.layout.addWidget(self.module_list)
        
        # 图标映射 - 使用物理定义符号字母
        self.icon_map = {
            "超声波位移": self.create_text_icon("x"),  # 位移符号 x
            "超声波速度": self.create_text_icon("v"),  # 速度符号 v
            "pH传感器": self.create_text_icon("pH"),   # pH符号
            "设置": self.create_text_icon("⚙")        # 设置齿轮符号
        }
        
        # 添加模块项
        self.modules = [
            ("超声波位移", "测量物体位移和运动轨迹"),
            ("超声波速度", "回声定位法测量物体速度"),
            ("pH传感器", "测量溶液酸碱度"),
            ("设置", "应用设置与偏好")
        ]
        
        for name, description in self.modules:
            item = QListWidgetItem()
            item.setText(name)
            item.setToolTip(description)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setIcon(self.icon_map[name])
            self.module_list.addItem(item)
        
        self.setLayout(self.layout)
    
    def toggle_collapse(self):
        """切换折叠/展开状态"""
        self.is_collapsed = not self.is_collapsed
        
        if self.is_collapsed:
            self.setFixedWidth(self.collapsed_width)
            self.toggle_button.setIcon(self.style.standardIcon(QStyle.StandardPixmap.SP_ArrowLeft))
            for i in range(self.module_list.count()):
                item = self.module_list.item(i)
                item.setText("")
        else:
            self.setFixedWidth(self.expanded_width)
            self.toggle_button.setIcon(self.style.standardIcon(QStyle.StandardPixmap.SP_ArrowRight))
            for i, (name, _) in enumerate(self.modules):
                item = self.module_list.item(i)
                item.setText(name)
    
    def set_current_row(self, row):
        """设置当前选中的行"""
        self.module_list.setCurrentRow(row)
    
    def get_current_row(self):
        """获取当前选中的行"""
        return self.module_list.currentRow()
    
    def apply_theme(self, theme):
        """应用主题到侧边栏"""
        if theme == "dark":
            dark_style = """
                QPushButton {
                    background-color: #2d2d2d;
                    border: none;
                    border-bottom: 1px solid #3d3d3d;
                    color: white;
                }
                QPushButton:hover {
                    background-color: #3d3d3d;
                }
                QListWidget {
                    background-color: #2d2d2d;
                    border: none;
                    font-size: 14px;
                    color: white;
                }
                QListWidget::item {
                    padding: 12px;
                    padding-left: 15px;
                    border-bottom: 1px solid #3d3d3d;
                    border-left: 3px solid transparent;
                    height: 48px;
                    color: white;
                }
                QListWidget::item:selected {
                    background-color: #3d3d3d;
                    color: white;
                    border-left: 3px solid #0078d4;
                }
                QListWidget::item:hover {
                    background-color: #3d3d3d;
                }
            """
            self.setStyleSheet(dark_style)
        else:
            light_style = """
                QPushButton {
                    background-color: #f3f3f3;
                    border: none;
                    border-bottom: 1px solid #e0e0e0;
                }
                QPushButton:hover {
                    background-color: #e8e8e8;
                }
                QPushButton:pressed {
                    background-color: #d0d0d0;
                }
                QListWidget {
                    background-color: #f3f3f3;
                    border: none;
                    font-size: 14px;
                    color: black;
                }
                QListWidget::item {
                    padding: 12px;
                    padding-left: 15px;
                    border-bottom: 1px solid #e0e0e0;
                    border-left: 3px solid transparent;
                    height: 48px;
                    color: black;
                }
                QListWidget::item:selected {
                    background-color: #e8e8e8;
                    color: black;
                    border-left: 3px solid #0078d4;
                }
                QListWidget::item:hover {
                    background-color: #f0f0f0;
                }
            """
            self.setStyleSheet(light_style)
    
    def create_text_icon(self, text):
        """创建文本图标"""
        from PyQt6.QtGui import QPixmap, QPainter, QFont, QColor
        from PyQt6.QtCore import Qt
        
        # 创建 24x24 像素的图像
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        # 创建绘图器
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 设置字体
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        painter.setFont(font)
        
        # 设置颜色
        painter.setPen(QColor(0, 0, 0))  # 黑色文字
        
        # 绘制文本（居中显示）
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)
        painter.end()
        
        return QIcon(pixmap)


class SettingsWidget(QWidget):
    """设置界面组件"""
    
    theme_changed = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.current_theme = "light"
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # 标题
        title = QLabel("设置")
        title.setFont(QFont("Arial", 24, QFont.Weight.Bold))
        layout.addWidget(title)
        
        # 外观设置卡片
        appearance_group = QGroupBox("外观")
        appearance_layout = QVBoxLayout()
        appearance_layout.setSpacing(15)
        
        # 应用主题选项
        theme_label = QLabel("应用主题")
        theme_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        appearance_layout.addWidget(theme_label)
        
        theme_desc = QLabel("选择要显示的应用主题")
        theme_desc.setStyleSheet("color: #666; font-size: 11px;")
        appearance_layout.addWidget(theme_desc)
        
        # Win11风格的主题选择按钮组
        self.theme_button_group = QVBoxLayout()
        self.theme_button_group.setSpacing(8)
        
        self.theme_buttons = {}
        themes = [
            ("system", "使用系统设置"),
            ("light", "浅色"),
            ("dark", "深色")
        ]
        
        for theme_id, theme_name in themes:
            btn = QPushButton(f"  {theme_name}")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(40)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: white;
                    border: 1px solid #e0e0e0;
                    border-radius: 4px;
                    text-align: left;
                    padding-left: 15px;
                    font-size: 13px;
                    color: #333;
                }
                QPushButton:hover {
                    background-color: #f5f5f5;
                    border-color: #0078d4;
                }
                QPushButton:checked {
                    background-color: #e6f2ff;
                    border-left: 3px solid #0078d4;
                    color: #0078d4;
                    font-weight: bold;
                }
            """)
            btn.clicked.connect(lambda checked, tid=theme_id: self.change_theme(tid))
            self.theme_buttons[theme_id] = btn
            self.theme_button_group.addWidget(btn)
        
        appearance_layout.addLayout(self.theme_button_group)
        appearance_group.setLayout(appearance_layout)
        layout.addWidget(appearance_group)
        
        layout.addStretch()
        self.setLayout(layout)
        
        # 默认选中浅色模式
        self.theme_buttons["light"].setChecked(True)
    
    def change_theme(self, theme_id):
        """切换主题"""
        for btn in self.theme_buttons.values():
            btn.setChecked(False)
        self.theme_buttons[theme_id].setChecked(True)
        self.current_theme = theme_id
        self.theme_changed.emit(theme_id)
    
    def apply_theme(self, theme):
        """应用主题到设置界面本身"""
        if theme == "dark":
            dark_style = """
                QWidget {
                    background-color: #202020;
                    color: #ffffff;
                }
                QGroupBox {
                    font-weight: bold;
                    border: 2px solid #3d3d3d;
                    border-radius: 8px;
                    margin-top: 10px;
                    padding-top: 10px;
                    color: #ffffff;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px 0 5px;
                    color: #ffffff;
                }
                QLabel {
                    color: #ffffff;
                }
                QPushButton {
                    background-color: #333333;
                    border: 1px solid #444444;
                    color: #ffffff;
                    border-radius: 4px;
                    padding: 8px 16px;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #404040;
                    border-color: #0078d4;
                }
                QPushButton:checked {
                    background-color: #003366;
                    border-left: 3px solid #0078d4;
                    color: #0078d4;
                    font-weight: bold;
                }
            """
            self.setStyleSheet(dark_style)
        else:
            light_style = """
                QWidget {
                    background-color: #fafafa;
                    color: #000000;
                }
                QGroupBox {
                    font-weight: bold;
                    border: 2px solid #e0e0e0;
                    border-radius: 8px;
                    margin-top: 10px;
                    padding-top: 10px;
                    color: #000000;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px 0 5px;
                    color: #000000;
                }
                QLabel {
                    color: #000000;
                }
                QPushButton {
                    background-color: white;
                    border: 1px solid #e0e0e0;
                    color: #333333;
                    border-radius: 4px;
                    padding: 8px 16px;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #f5f5f5;
                    border-color: #0078d4;
                }
                QPushButton:checked {
                    background-color: #e6f2ff;
                    border-left: 3px solid #0078d4;
                    color: #0078d4;
                    font-weight: bold;
                }
            """
            self.setStyleSheet(light_style)


class MainWindow(QMainWindow):
    """主窗口"""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.apply_win11_style()
    
    def init_ui(self):
        self.setWindowTitle("PhysChem-DigitizerP")
        self.setGeometry(100, 100, 1200, 800)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QHBoxLayout()
        
        # 侧边栏
        self.sidebar = SidebarWidget()
        self.sidebar.module_changed.connect(self.switch_module)
        main_layout.addWidget(self.sidebar)
        
        # 内容区域
        self.content_stack = QStackedWidget()
        main_layout.addWidget(self.content_stack)
        
        # 创建各个模块的界面
        self.modules = {}
        
        # 超声波位移模块
        ultrasonic_widget = UltrasonicWidget()
        self.content_stack.addWidget(ultrasonic_widget)
        self.modules["超声波位移"] = ultrasonic_widget
        
        # 超声波速度模块
        ultrasonic_velocity_widget = UltrasonicVelocityWidget()
        self.content_stack.addWidget(ultrasonic_velocity_widget)
        self.modules["超声波速度"] = ultrasonic_velocity_widget
        
        # pH传感器模块
        ph_sensor_widget = PhSensorWidget()
        self.content_stack.addWidget(ph_sensor_widget)
        self.modules["pH传感器"] = ph_sensor_widget
        
        # 设置模块
        self.settings_widget = SettingsWidget()
        self.settings_widget.theme_changed.connect(self.change_app_theme)
        self.content_stack.addWidget(self.settings_widget)
        self.modules["设置"] = self.settings_widget
        
        central_widget.setLayout(main_layout)
        
        # 默认选择第一个模块
        self.sidebar.set_current_row(0)
    
    def switch_module(self, index):
        """切换模块"""
        if index >= 0:
            self.content_stack.setCurrentIndex(index)
    
    def change_app_theme(self, theme):
        """切换应用主题"""
        self.current_theme = theme
        self.apply_theme(theme)
        
        # 更新设置界面的主题
        if hasattr(self, 'settings_widget'):
            self.settings_widget.apply_theme(theme)
        
        # 更新侧边栏的主题
        if hasattr(self, 'sidebar'):
            self.sidebar.apply_theme(theme)
    
    def apply_theme(self, theme):
        """应用指定主题"""
        if theme == "dark":
            dark_style = """
                QMainWindow {
                    background-color: #202020;
                    color: white;
                }
                QGroupBox {
                    font-weight: bold;
                    border: 2px solid #3d3d3d;
                    border-radius: 8px;
                    margin-top: 10px;
                    padding-top: 10px;
                    color: white;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px 0 5px;
                    color: white;
                }
                QPushButton {
                    background-color: #0078d4;
                    border: none;
                    color: white;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #106ebe;
                }
                QPushButton:disabled {
                    background-color: #444444;
                    color: #888888;
                }
                QLabel {
                    font-size: 14px;
                    color: white;
                }
                QTextEdit, QComboBox, QSpinBox {
                    border: 1px solid #444444;
                    border-radius: 4px;
                    padding: 4px;
                    font-size: 14px;
                    color: white;
                    background-color: #333333;
                }
                QListWidget {
                    background-color: #2d2d2d;
                    border: none;
                    font-size: 14px;
                    color: white;
                }
                QListWidget::item {
                    padding: 15px;
                    border-bottom: 1px solid #3d3d3d;
                    color: white;
                }
                QListWidget::item:selected {
                    background-color: #0078d4;
                    color: white;
                }
                QListWidget::item:hover {
                    background-color: #3d3d3d;
                }
            """
            self.setStyleSheet(dark_style)
        else:
            light_style = """
                QMainWindow {
                    background-color: #fafafa;
                    color: black;
                }
                QGroupBox {
                    font-weight: bold;
                    border: 2px solid #e0e0e0;
                    border-radius: 8px;
                    margin-top: 10px;
                    padding-top: 10px;
                    color: black;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px 0 5px;
                    color: black;
                }
                QPushButton {
                    background-color: #0078d4;
                    border: none;
                    color: white;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #106ebe;
                }
                QPushButton:disabled {
                    background-color: #cccccc;
                    color: #666666;
                }
                QLabel {
                    font-size: 14px;
                    color: black;
                }
                QTextEdit, QComboBox, QSpinBox {
                    border: 1px solid #cccccc;
                    border-radius: 4px;
                    padding: 4px;
                    font-size: 14px;
                    color: black;
                    background-color: white;
                }
                QListWidget {
                    background-color: #f3f3f3;
                    border: none;
                    font-size: 14px;
                    color: black;
                }
                QListWidget::item {
                    padding: 15px;
                    border-bottom: 1px solid #e0e0e0;
                    color: black;
                }
                QListWidget::item:selected {
                    background-color: #0078d4;
                    color: white;
                }
                QListWidget::item:hover {
                    background-color: #f0f0f0;
                }
            """
            self.setStyleSheet(light_style)
    
    def apply_win11_style(self):
        """应用 Win11 风格样式（默认浅色模式）"""
        self.current_theme = "light"
        self.apply_theme("light")


def main():
    app = QApplication(sys.argv)
    
    # 设置应用程序样式
    app.setStyle('Fusion')
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
