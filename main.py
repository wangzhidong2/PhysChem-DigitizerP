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
                            QTextEdit, QGroupBox, QSpinBox, QDoubleSpinBox, QCheckBox)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread
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


class MainWindow(QMainWindow):
    """主窗口"""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.apply_win11_style()
    
    def init_ui(self):
        self.setWindowTitle("物理实验数据采集软件")
        self.setGeometry(100, 100, 1200, 800)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QHBoxLayout()
        
        # 侧边栏
        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(200)
        self.sidebar.setStyleSheet("""
            QListWidget {
                background-color: #f3f3f3;
                border: none;
                font-size: 14px;
            }
            QListWidget::item {
                padding: 15px;
                border-bottom: 1px solid #e0e0e0;
            }
            QListWidget::item:selected {
                background-color: #0078d4;
                color: white;
            }
        """)
        
        # 添加模块项
        modules = [
            ("超声波位移", "测量物体位移和运动轨迹"),
            ("超声波速度", "回声定位法测量物体速度"),
            ("温度传感器", "测量环境温度"),
            ("光电门", "测量物体通过时间"),
            ("力传感器", "测量力的大小")
        ]
        
        for name, description in modules:
            item = QListWidgetItem(f"{name}\n{description}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.sidebar.addItem(item)
        
        self.sidebar.currentRowChanged.connect(self.switch_module)
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
        
        # 占位模块（其他模块待实现）
        for module_name in ["温度传感器", "光电门", "力传感器"]:
            placeholder = QLabel(f"{module_name}模块 - 开发中...")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("font-size: 18px; color: #666;")
            self.content_stack.addWidget(placeholder)
            self.modules[module_name] = placeholder
        
        central_widget.setLayout(main_layout)
        
        # 默认选择第一个模块
        self.sidebar.setCurrentRow(0)
    
    def switch_module(self, index):
        """切换模块"""
        if index >= 0:
            self.content_stack.setCurrentIndex(index)
    
    def apply_win11_style(self):
        """应用 Win11 风格样式"""
        self.setStyleSheet("""
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
        """)


def main():
    app = QApplication(sys.argv)
    
    # 设置应用程序样式
    app.setStyle('Fusion')
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
