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
                            QStyle, QDialog, QLineEdit, QRadioButton, QScrollArea)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QSize
from PyQt6.QtGui import QFont, QIcon, QPalette, QColor
import serial
import serial.tools.list_ports
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np

# 设置 matplotlib 全局字体为微软雅黑
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题


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


class HomePageWidget(QWidget):
    """主页面 - 显示主README和按学科分类的模块导航"""
    
    module_clicked = pyqtSignal(str)  # 信号：点击模块时发送模块名称
    
    def __init__(self):
        super().__init__()
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(15)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setSpacing(15)
        
        # 标题区域
        title_widget = QWidget()
        title_layout = QVBoxLayout(title_widget)
        
        app_title = QLabel("PhysChem-DigitizerP")
        app_title.setFont(QFont("Microsoft YaHei", 36, QFont.Weight.Bold))
        app_title.setStyleSheet("color: #0078d4; margin: 10px;")
        title_layout.addWidget(app_title)
        
        subtitle = QLabel("基于 Arduino/ESP32 的低成本理化实验数字化采集系统")
        subtitle.setFont(QFont("Microsoft YaHei", 14))
        subtitle.setStyleSheet("color: #666; margin-bottom: 15px;")
        title_layout.addWidget(subtitle)
        
        version = QLabel("版本 v1.2.2 | MIT 开源协议 | Win11 风格界面")
        version.setFont(QFont("Microsoft YaHei", 10))
        version.setStyleSheet("color: #999;")
        title_layout.addWidget(version)
        
        content_layout.addWidget(title_widget)
        
        # 项目简介
        intro_group = QGroupBox("📖 项目简介")
        intro_layout = QVBoxLayout()
        
        intro_text = QLabel(
            "PhysChem-DigitizerP 是一个开源的物理化学实验数字化采集系统，"
            "旨在为中学和大学物理/化学实验室提供低成本、高精度的传感器解决方案。"
            "\n\n"
            "✅ 完全开源（硬件+软件） | "
            "💰 单传感器成本 < ¥30 | "
            "📊 测量精度 ±0.3cm | "
            "🔬 适合教学实验"
        )
        intro_text.setWordWrap(True)
        intro_text.setStyleSheet("font-size: 13px; line-height: 1.6; color: #333;")
        intro_text.setTextFormat(Qt.TextFormat.RichText)
        intro_layout.addWidget(intro_text)
        
        intro_group.setLayout(intro_layout)
        content_layout.addWidget(intro_group)
        
        # 学科分类区域
        category_widget = QWidget()
        category_layout = QHBoxLayout(category_widget)
        category_layout.setSpacing(20)
        
        # 物理学科
        physics_group = QGroupBox("⚛️ 物理实验模块")
        physics_layout = QVBoxLayout(physics_group)
        
        physics_modules = [
            {
                'name': '超声波位移',
                'icon': 'x',
                'desc': '测量物体位移和运动轨迹',
                'detail': '实时距离测量 | 距离-时间曲线 | CSV导出'
            },
            {
                'name': '超声波速度',
                'icon': 'v',
                'desc': '回声定位法测量物体速度',
                'detail': '双图表显示 | 速度统计分析 | 瞬时速度计算'
            },
            {
                'name': '力传感器',
                'icon': 'F',
                'desc': 'HX711力/质量传感器测量',
                'detail': '24位高精度ADC | 去皮校准 | 实时质量测量'
            }
        ]
        
        for module in physics_modules:
            module_card = self.create_clickable_module_card(module, '#28a745')
            module_card.setProperty('module_name', module['name'])
            physics_layout.addWidget(module_card)
        
        physics_layout.addStretch()
        category_layout.addWidget(physics_group, stretch=1)
        
        # 化学学科
        chemistry_group = QGroupBox("🧪 化学实验模块")
        chemistry_layout = QVBoxLayout(chemistry_group)
        
        chemistry_modules = [
            {
                'name': 'pH传感器',
                'icon': 'pH',
                'desc': '测量溶液酸碱度',
                'detail': '三点校准 | 实时pH值 | 标准差统计'
            }
        ]
        
        for module in chemistry_modules:
            module_card = self.create_clickable_module_card(module, '#fd7e14')
            module_card.setProperty('module_name', module['name'])
            chemistry_layout.addWidget(module_card)
        
        chemistry_layout.addStretch()
        category_layout.addWidget(chemistry_group, stretch=1)
        
        content_layout.addWidget(category_widget, stretch=1)
        
        # 技术特性
        tech_group = QGroupBox("🔧 技术特性与支持平台")
        tech_layout = QHBoxLayout()
        
        left_tech = QWidget()
        left_layout = QVBoxLayout(left_tech)
        
        tech_features = [
            ("硬件平台", "ESP32 / ESP8266 (WeMOS D1)"),
            ("软件框架", "Python + PyQt6 + Matplotlib"),
            ("测量精度", "±0.3cm (超声波) / ±0.01 pH"),
            ("采样频率", "最高 100Hz (可调)"),
            ("数据格式", "CSV 导出，兼容 Excel")
        ]
        
        for label, value in tech_features:
            item_layout = QHBoxLayout()
            name_label = QLabel(f"• {label}: ")
            name_label.setStyleSheet("font-weight: bold; font-size: 12px; color: #555;")
            value_label = QLabel(value)
            value_label.setStyleSheet("font-size: 12px; color: #666;")
            item_layout.addWidget(name_label)
            item_layout.addWidget(value_label)
            item_layout.addStretch()
            left_layout.addLayout(item_layout)
        
        tech_layout.addWidget(left_tech, stretch=1)
        
        right_tech = QWidget()
        right_layout = QVBoxLayout(right_tech)
        
        support_features = [
            "✅ Win11 风格现代化界面",
            "✅ 支持深色/浅色主题",
            "✅ 配置自动保存 (JSON)",
            "✅ 多种传感器支持",
            "✅ 实时数据可视化"
        ]
        
        for feature in support_features:
            feat_label = QLabel(feature)
            feat_label.setStyleSheet("font-size: 12px; color: #666; padding: 2px;")
            right_layout.addWidget(feat_label)
        
        tech_layout.addWidget(right_tech, stretch=1)
        tech_group.setLayout(tech_layout)
        content_layout.addWidget(tech_group)
        
        # 快速开始
        quick_start_group = QGroupBox("🚀 快速开始")
        quick_start_layout = QVBoxLayout()
        
        steps_text = (
            "<b>步骤 1:</b> 连接 ESP32/ESP8266 到电脑 USB<br>"
            "<b>步骤 2:</b> 选择左侧对应的功能模块<br>"
            "<b>步骤 3:</b> 选择串口并点击连接<br>"
            "<b>步骤 4:</b> 配置参数（校准/采样频率）<br>"
            "<b>步骤 5:</b> 点击开始采集数据<br>"
            "<b>步骤 6:</b> 查看图表并保存数据"
        )
        steps_label = QLabel(steps_text)
        steps_label.setTextFormat(Qt.TextFormat.RichText)
        steps_label.setStyleSheet("font-size: 13px; line-height: 1.8; color: #444;")
        quick_start_layout.addWidget(steps_label)
        
        quick_start_group.setLayout(quick_start_layout)
        content_layout.addWidget(quick_start_group)
        
        # 底部信息
        footer_widget = QWidget()
        footer_layout = QHBoxLayout(footer_widget)
        
        status_label = QLabel("就绪 | 点击上方模块卡片快速进入对应功能")
        status_label.setStyleSheet("color: #888; font-size: 11px;")
        footer_layout.addWidget(status_label)
        
        footer_layout.addStretch()
        
        link_label = QLabel(
            '<a href="https://github.com/wangzhidong2/PhysChem-DigitizerP">'
            '🌐 GitHub 项目主页</a>'
        )
        link_label.setTextFormat(Qt.TextFormat.RichText)
        link_label.setOpenExternalLinks(True)
        link_label.setStyleSheet("color: #0078d4; font-size: 11px;")
        link_label.setToolTip("在浏览器中打开 GitHub 仓库页面")
        footer_layout.addWidget(link_label)
        
        copyright_label = QLabel("© 2026 PhysChem-DigitizerP | MIT License")
        copyright_label.setStyleSheet("color: #999; font-size: 11px;")
        footer_layout.addWidget(copyright_label)
        
        content_layout.addWidget(footer_widget)
        
        scroll.setWidget(content_widget)
        layout.addWidget(scroll)
        
        self.setLayout(layout)
    
    def create_clickable_module_card(self, module_info, color):
        """创建可点击的模块卡片"""
        card = QPushButton()  # 使用 QPushButton 以支持点击事件
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setFixedHeight(100)
        card.setStyleSheet(f"""
            QPushButton {{
                background-color: white;
                border: 2px solid {color};
                border-radius: 8px;
                padding: 10px;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {color}10;
                border-color: {color};
                box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            }}
            QPushButton:pressed {{
                background-color: {color}20;
            }}
        """)
        
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(15, 10, 15, 10)
        
        # 第一行：图标 + 名称 + 箭头
        header_layout = QHBoxLayout()
        icon_label = QLabel(module_info['icon'])
        icon_label.setFont(QFont("Arial", 24, QFont.Weight.Bold))
        icon_label.setStyleSheet(f"color: {color};")
        header_layout.addWidget(icon_label)
        
        name_label = QLabel(module_info['name'])
        name_label.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        name_label.setStyleSheet("color: #333;")
        header_layout.addWidget(name_label)
        
        header_layout.addStretch()
        arrow_label = QLabel("→")
        arrow_label.setFont(QFont("Arial", 18))
        arrow_label.setStyleSheet(f"color: {color};")
        header_layout.addWidget(arrow_label)
        
        card_layout.addLayout(header_layout)
        
        # 第二行：描述
        desc_label = QLabel(module_info['desc'])
        desc_label.setFont(QFont("Microsoft YaHei", 11))
        desc_label.setStyleSheet("color: #555;")
        card_layout.addWidget(desc_label)
        
        # 第三行：详细信息
        detail_label = QLabel(module_info['detail'])
        detail_label.setFont(QFont("Microsoft YaHei", 9))
        detail_label.setStyleSheet("color: #888;")
        card_layout.addWidget(detail_label)
        
        # 点击事件：发送信号
        card.clicked.connect(lambda: self.on_module_clicked(module_info['name']))
        
        return card
    
    def on_module_clicked(self, module_name):
        """处理模块卡片点击事件"""
        self.module_clicked.emit(module_name)


class PhSensorWidget(QWidget):
    """pH传感器模块界面 - 支持三点校准"""
    
    def __init__(self):
        super().__init__()
        self.serial_thread = None
        self.ph_data = []          # pH 值数据
        self.time_data = []        # 时间数据
        self.adc_data = []         # 原始 ADC 数据
        self.start_timestamp_ms = 0
        
        # 采样频率设置（毫秒）
        self.sample_interval_ms = 100  # 默认 100ms (10Hz)
        self.last_sample_time_ms = 0   # 上次采样时间
        
        # 加载保存的配置
        self.config = self.load_config()
        
        # 三点校准参数 (pH, ADC) - 在 init_ui() 之前定义
        # 优先使用保存的配置，如果没有则使用默认值
        default_calibration = [
            (4.00, 2555),   # 酸性缓冲液
            (6.86, 2281),   # 中性缓冲液
            (9.18, 2030)    # 碱性缓冲液
        ]
        self.calibration_points = self.config.get('calibration_points', default_calibration)
        
        # 计算校准系数（二次拟合）
        self.calculate_calibration_coefficients()
        
        self.init_ui()
    
    def get_config_path(self):
        """获取配置文件路径"""
        # 配置文件保存在程序同目录下
        config_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(config_dir, 'ph_sensor_config.json')
    
    def load_config(self):
        """加载配置文件"""
        config_path = self.get_config_path()
        
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                print(f"✓ 已加载配置文件：{config_path}")
                return config
            else:
                print(f"ℹ️ 配置文件不存在，使用默认配置：{config_path}")
                return {}
        except Exception as e:
            print(f"⚠️ 加载配置文件失败：{e}，使用默认配置")
            return {}
    
    def save_config(self):
        """保存配置文件"""
        config_path = self.get_config_path()
        
        try:
            config = {
                'calibration_points': self.calibration_points,
                'sample_interval_ms': self.sample_interval_ms
            }
            
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            
            print(f"✓ 配置已保存：{config_path}")
            return True
        except Exception as e:
            print(f"⚠️ 保存配置文件失败：{e}")
            return False
    
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
        
        # 采样频率显示
        control_layout.addWidget(QLabel("采样:"))
        self.sample_rate_label = QLabel(f"{1000//self.sample_interval_ms}Hz")
        self.sample_rate_label.setStyleSheet("color: #0078d4; font-weight: bold;")
        control_layout.addWidget(self.sample_rate_label)
        
        # 采样频率设置按钮
        sample_settings_btn = QPushButton("⚙️")
        sample_settings_btn.setFixedWidth(40)
        sample_settings_btn.setToolTip("设置采样频率")
        sample_settings_btn.clicked.connect(self.edit_sample_rate)
        sample_settings_btn.setStyleSheet("""
            QPushButton {
                background-color: #f0f0f0;
                border: 1px solid #ccc;
                border-radius: 4px;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
            QPushButton:pressed {
                background-color: #d0d0d0;
            }
        """)
        control_layout.addWidget(sample_settings_btn)
        
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
        
        # 校准参数显示
        self.cal_text = QLabel(
            f"• pH 4.00 → ADC {self.calibration_points[0][1]}\n"
            f"• pH 6.86 → ADC {self.calibration_points[1][1]}\n"
            f"• pH 9.18 → ADC {self.calibration_points[2][1]}"
        )
        self.cal_text.setStyleSheet("font-size: 12px; color: #666;")
        cal_info_layout.addWidget(self.cal_text)
        
        # 编辑按钮
        edit_btn = QPushButton("✏️ 编辑校准参数")
        edit_btn.clicked.connect(self.edit_calibration)
        edit_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
            QPushButton:pressed {
                background-color: #005a9e;
            }
        """)
        cal_info_layout.addWidget(edit_btn)
        
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
        self.last_sample_time_ms = 0  # 重置采样时间
        
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
                    
                    # 过滤无效 ADC 值（0-4095 范围）
                    if adc_value < 0 or adc_value > 4095:
                        return
                    
                    # 采样频率控制：检查是否达到采样间隔
                    if timestamp_ms - self.last_sample_time_ms < self.sample_interval_ms:
                        return  # 未达到采样间隔，跳过此数据
                    
                    # 更新上次采样时间
                    self.last_sample_time_ms = timestamp_ms
                    
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
                                   f"数据已保存到：{filename}\n"
                                   f"共 {len(self.ph_data)} 个数据点")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败：{e}")
    
    def edit_sample_rate(self):
        """编辑采样频率对话框"""
        dialog = SampleRateDialog(self.sample_interval_ms, self)
        if dialog.exec() == 1:  # QDialog.Accepted
            # 获取新的采样间隔
            new_interval_ms = dialog.get_sample_interval()
            
            # 更新采样间隔
            self.sample_interval_ms = new_interval_ms
            
            # 更新显示
            freq = 1000 // new_interval_ms
            self.sample_rate_label.setText(f"{freq}Hz")
            
            # 保存配置到文件
            self.save_config()
            
            QMessageBox.information(self, "成功", 
                                   f"采样频率已更新为 {freq} Hz！\n"
                                   f"采样间隔：{new_interval_ms} ms\n"
                                   f"配置已自动保存，下次启动时生效。")
    
    def clear_data(self):
        """清除数据"""
        self.ph_data.clear()
        self.time_data.clear()
        self.adc_data.clear()
        self.data_text.clear()
        self.stats_label.setText("统计信息：暂无数据")
        self.current_ph_label.setText("pH: --.-")
        self.current_adc_label.setText("ADC: ----")
        self.figure.clear()
        self.canvas.draw()
        self.save_btn.setEnabled(False)
    
    def edit_calibration(self):
        """编辑校准参数对话框"""
        dialog = CalibrationDialog(self.calibration_points, self)
        if dialog.exec() == 1:  # QDialog.Accepted
            # 获取新的校准参数
            new_points = dialog.get_calibration_points()
            
            # 更新校准参数
            self.calibration_points = new_points
            
            # 重新计算校准系数
            self.calculate_calibration_coefficients()
            
            # 更新显示
            self.cal_text.setText(
                f"• pH {new_points[0][0]:.2f} → ADC {new_points[0][1]}\n"
                f"• pH {new_points[1][0]:.2f} → ADC {new_points[1][1]}\n"
                f"• pH {new_points[2][0]:.2f} → ADC {new_points[2][1]}"
            )
            
            # 保存配置到文件
            self.save_config()
            
            QMessageBox.information(self, "成功", 
                                   "校准参数已更新并保存！\n新的校准曲线将立即生效。\n下次启动程序时会自动加载此配置。")


class ForceSensorWidget(QWidget):
    """力传感器（HX711）模块界面 - 支持去皮和校准"""
    
    def __init__(self):
        super().__init__()
        self.serial_thread = None
        self.ble_thread = None
        self.flask_server = None
        self.force_data = []
        self.time_data = []
        self.raw_data = []
        self.start_timestamp_ms = 0
        
        self.offset = 0
        self.scale = 1.0
        self.calibrated = False
        self.cal_known_weight = 100.0
        self.cal_raw_before = 0
        self.cal_raw_after = 0
        self.cal_step = 0
        
        self.config = self.load_config()
        self.offset = self.config.get('offset', 0)
        self.scale = self.config.get('scale', 1.0)
        self.calibrated = self.config.get('calibrated', False)
        self.cal_known_weight = self.config.get('cal_known_weight', 100.0)
        
        self.init_ui()
    
    def set_flask_server(self, server):
        self.flask_server = server
    
    def get_config_path(self):
        config_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(config_dir, 'force_sensor_config.json')
    
    def load_config(self):
        config_path = self.get_config_path()
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                print(f"✓ 已加载力传感器配置：{config_path}")
                return config
            return {}
        except Exception as e:
            print(f"⚠️ 加载力传感器配置失败：{e}")
            return {}
    
    def save_config(self):
        config_path = self.get_config_path()
        try:
            config = {
                'offset': self.offset,
                'scale': self.scale,
                'calibrated': self.calibrated,
                'cal_known_weight': self.cal_known_weight
            }
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            print(f"✓ 力传感器配置已保存：{config_path}")
            return True
        except Exception as e:
            print(f"⚠️ 保存力传感器配置失败：{e}")
            return False
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # 连接方式选择
        conn_group = QGroupBox("连接方式")
        conn_layout = QHBoxLayout()
        
        conn_layout.addWidget(QLabel("连接方式:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["有线串口", "BLE蓝牙"])
        if not BLE_AVAILABLE:
            self.mode_combo.setItemData(1, 0, Qt.ItemDataRole.UserRole - 1)
            self.mode_combo.setItemText(1, "BLE蓝牙（未安装bleak）")
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        conn_layout.addWidget(self.mode_combo)
        
        # 串口面板
        self.serial_panel = QWidget()
        serial_layout = QHBoxLayout(self.serial_panel)
        serial_layout.setContentsMargins(0, 0, 0, 0)
        
        serial_layout.addWidget(QLabel("串口:"))
        self.port_combo = QComboBox()
        self.refresh_ports()
        serial_layout.addWidget(self.port_combo)
        
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        serial_layout.addWidget(self.refresh_btn)
        
        # BLE 面板
        self.ble_panel = QWidget()
        ble_layout = QHBoxLayout(self.ble_panel)
        ble_layout.setContentsMargins(0, 0, 0, 0)
        
        self.ble_device_combo = QComboBox()
        ble_layout.addWidget(self.ble_device_combo)
        
        self.ble_scan_btn = QPushButton("扫描BLE")
        self.ble_scan_btn.clicked.connect(self.scan_ble)
        if not BLE_AVAILABLE:
            self.ble_scan_btn.setEnabled(False)
        ble_layout.addWidget(self.ble_scan_btn)
        
        conn_layout.addWidget(self.serial_panel)
        conn_layout.addWidget(self.ble_panel)
        self.ble_panel.hide()
        
        conn_layout.addStretch()
        
        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(self.connect_device)
        conn_layout.addWidget(self.connect_btn)
        
        self.disconnect_btn = QPushButton("断开")
        self.disconnect_btn.clicked.connect(self.disconnect_all)
        self.disconnect_btn.setEnabled(False)
        conn_layout.addWidget(self.disconnect_btn)
        
        conn_group.setLayout(conn_layout)
        layout.addWidget(conn_group)
        
        # 校准面板
        cal_group = QGroupBox("校准与去皮")
        cal_layout = QVBoxLayout()
        
        cal_info_layout = QHBoxLayout()
        self.cal_status_label = QLabel("校准状态: 未校准" if not self.calibrated else f"校准状态: ✓ 已校准 (比例={self.scale:.6f}, 偏移={self.offset})")
        self.cal_status_label.setStyleSheet("color: green; font-weight: bold;" if self.calibrated else "color: red; font-weight: bold;")
        cal_info_layout.addWidget(self.cal_status_label)
        cal_layout.addLayout(cal_info_layout)
        
        cal_btn_layout = QHBoxLayout()
        
        self.tare_btn = QPushButton("去皮（TARE）")
        self.tare_btn.clicked.connect(self.send_tare)
        self.tare_btn.setEnabled(False)
        self.tare_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078d4; color: white;
                border: none; padding: 8px 16px; border-radius: 4px;
            }
            QPushButton:hover { background-color: #106ebe; }
            QPushButton:pressed { background-color: #005a9e; }
        """)
        cal_btn_layout.addWidget(self.tare_btn)
        
        self.calibrate_btn = QPushButton("校准（CALIBRATE）")
        self.calibrate_btn.clicked.connect(self.start_calibration)
        self.calibrate_btn.setEnabled(False)
        self.calibrate_btn.setStyleSheet("""
            QPushButton {
                background-color: #fd7e14; color: white;
                border: none; padding: 8px 16px; border-radius: 4px;
            }
            QPushButton:hover { background-color: #e06b00; }
            QPushButton:pressed { background-color: #c55a00; }
        """)
        cal_btn_layout.addWidget(self.calibrate_btn)
        
        cal_btn_layout.addStretch()
        cal_layout.addLayout(cal_btn_layout)
        
        cal_group.setLayout(cal_layout)
        layout.addWidget(cal_group)
        
        # 数据显示区域
        data_group = QGroupBox("实时数据")
        data_layout = QHBoxLayout()
        
        text_widget = QWidget()
        text_layout = QVBoxLayout()
        
        self.current_force_label = QLabel("力/质量: --.-")
        self.current_force_label.setFont(QFont("Arial", 28, QFont.Weight.Bold))
        self.current_force_label.setStyleSheet("color: #0078d4; padding: 10px;")
        text_layout.addWidget(self.current_force_label)
        
        self.current_raw_label = QLabel("原始ADC: ------")
        self.current_raw_label.setFont(QFont("Arial", 14))
        text_layout.addWidget(self.current_raw_label)
        
        self.current_unit_label = QLabel("单位: g（未校准则显示原始值）")
        self.current_unit_label.setStyleSheet("color: #666; font-size: 12px;")
        text_layout.addWidget(self.current_unit_label)
        
        self.stats_label = QLabel("统计信息: 暂无数据")
        text_layout.addWidget(self.stats_label)
        
        self.data_text = QTextEdit()
        self.data_text.setMaximumHeight(120)
        text_layout.addWidget(QLabel("数据记录:"))
        text_layout.addWidget(self.data_text)
        
        text_widget.setLayout(text_layout)
        data_layout.addWidget(text_widget)
        
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
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_chart)
        self.timer.start(100)
    
    def on_mode_changed(self, index):
        if index == 0:
            self.serial_panel.show()
            self.ble_panel.hide()
        else:
            self.serial_panel.hide()
            self.ble_panel.show()
    
    def refresh_ports(self):
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.port_combo.addItem(port.device)
    
    def scan_ble(self):
        if not BLE_AVAILABLE:
            QMessageBox.warning(self, "提示", "请先安装 bleak 库：pip install bleak")
            return
        
        self.ble_scan_btn.setEnabled(False)
        self.ble_scan_btn.setText("扫描中...")
        
        self._ble_scan_thread = threading.Thread(target=self._do_scan_ble, daemon=True)
        self._ble_scan_thread.start()
    
    def _do_scan_ble(self):
        try:
            devices = scan_ble_devices()
            self.ble_device_combo.clear()
            for name, addr in devices:
                self.ble_device_combo.addItem(f"{name} ({addr})")
            if not devices:
                self.ble_device_combo.addItem("未找到设备")
        except Exception as e:
            print(f"BLE 扫描错误: {e}")
        finally:
            self.ble_scan_btn.setEnabled(BLE_AVAILABLE)
            self.ble_scan_btn.setText("扫描BLE")
    
    def connect_device(self):
        mode = self.mode_combo.currentText()
        if "BLE" in mode:
            self.connect_ble()
        else:
            self.connect_serial()
    
    def connect_serial(self):
        port = self.port_combo.currentText()
        if not port:
            QMessageBox.warning(self, "错误", "请选择串口")
            return
        try:
            self.serial_thread = SerialThread(port)
            self.serial_thread.data_received.connect(self.handle_data)
            self.serial_thread.start()
            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(True)
            self.start_btn.setEnabled(True)
            self.tare_btn.setEnabled(True)
            self.calibrate_btn.setEnabled(True)
            self.current_force_label.setText("力/质量: 等待数据...")
            self.current_raw_label.setText("原始ADC: 连接中...")
        except Exception as e:
            QMessageBox.critical(self, "连接错误", f"无法连接串口: {e}")
    
    def connect_ble(self):
        if not BLE_AVAILABLE:
            QMessageBox.warning(self, "提示", "请先安装 bleak 库：pip install bleak")
            return
        
        device_text = self.ble_device_combo.currentText()
        if not device_text or "未找到" in device_text:
            QMessageBox.warning(self, "提示", "请先扫描并选择 BLE 设备")
            return
        
        try:
            address = device_text.split("(")[-1].rstrip(")")
        except:
            QMessageBox.warning(self, "提示", "无法解析设备地址")
            return
        
        try:
            self.ble_thread = BLESerialThread(address)
            self.ble_thread.data_received.connect(self.handle_data)
            self.ble_thread.connection_status.connect(self.on_ble_status)
            self.ble_thread.start()
            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(True)
            self.start_btn.setEnabled(True)
            self.tare_btn.setEnabled(True)
            self.calibrate_btn.setEnabled(True)
            self.current_force_label.setText("力/质量: BLE连接中...")
            self.current_raw_label.setText("原始ADC: BLE连接中...")
        except Exception as e:
            QMessageBox.critical(self, "连接错误", f"BLE 连接失败: {e}")
    
    def on_ble_status(self, status):
        if status == "connected":
            self.current_force_label.setText("力/质量: BLE已连接，等待数据...")
            self.current_raw_label.setText("原始ADC: 等待数据...")
    
    def disconnect_all(self):
        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread.wait()
            self.serial_thread = None
        if self.ble_thread:
            self.ble_thread.stop()
            self.ble_thread.wait()
            self.ble_thread = None
        
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.tare_btn.setEnabled(False)
        self.calibrate_btn.setEnabled(False)
        self.current_force_label.setText("力/质量: --.-")
        self.current_raw_label.setText("原始ADC: 已断开")
    
    def send_tare(self):
        if self.serial_thread and self.serial_thread.isRunning():
            try:
                ser = serial.Serial(self.port_combo.currentText(), 115200, timeout=1)
                ser.write(b"TARE\n")
                ser.close()
                self.current_force_label.setText("力/质量: 去皮中...")
            except:
                pass
        if self.ble_thread and self.ble_thread.isRunning():
            pass
    
    def start_calibration(self):
        if self.cal_step == 0:
            self.cal_step = 1
            self.calibrate_btn.setText("1. 请空载，点击记录零点")
            self.calibrate_btn.setStyleSheet("""
                QPushButton {
                    background-color: #dc3545; color: white;
                    border: none; padding: 8px 16px; border-radius: 4px;
                }
                QPushButton:hover { background-color: #c82333; }
            """)
        elif self.cal_step == 1:
            if len(self.raw_data) > 0:
                self.cal_raw_before = self.raw_data[-1]
            self.cal_step = 2
            weight, ok = QInputDialog.getDouble(
                self, "校准 - 已知质量",
                "请放上已知质量的砝码，\n输入砝码质量（克）：",
                self.cal_known_weight, 0.01, 100000, 2
            )
            if ok:
                self.cal_known_weight = weight
                self.calibrate_btn.setText(f"2. 已放{weight}g砝码，点击记录")
            else:
                self.cal_step = 0
                self.calibrate_btn.setText("校准（CALIBRATE）")
                self.calibrate_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #fd7e14; color: white;
                        border: none; padding: 8px 16px; border-radius: 4px;
                    }
                    QPushButton:hover { background-color: #e06b00; }
                """)
        elif self.cal_step == 2:
            if len(self.raw_data) > 0:
                self.cal_raw_after = self.raw_data[-1]
                diff = self.cal_raw_after - self.cal_raw_before
                if diff != 0:
                    self.scale = self.cal_known_weight / diff
                    self.offset = self.cal_raw_before
                    self.calibrated = True
                    self.save_config()
                    self.cal_status_label.setText(f"校准状态: ✓ 已校准 (比例={self.scale:.6f}, 偏移={self.offset})")
                    self.cal_status_label.setStyleSheet("color: green; font-weight: bold;")
                    self.current_unit_label.setText(f"单位: g（校准比例={self.scale:.6f}）")
                    QMessageBox.information(self, "校准成功",
                        f"校准完成！\n"
                        f"空载ADC: {self.cal_raw_before}\n"
                        f"加载ADC: {self.cal_raw_after}\n"
                        f"ADC差值: {diff}\n"
                        f"校准比例: {self.scale:.6f}\n"
                        f"砝码质量: {self.cal_known_weight}g")
                else:
                    QMessageBox.warning(self, "校准失败", "ADC差值为0，请检查传感器是否正常工作")
            
            self.cal_step = 0
            self.calibrate_btn.setText("校准（CALIBRATE）")
            self.calibrate_btn.setStyleSheet("""
                QPushButton {
                    background-color: #fd7e14; color: white;
                    border: none; padding: 8px 16px; border-radius: 4px;
                }
                QPushButton:hover { background-color: #e06b00; }
            """)
    
    def start_collection(self):
        self.force_data.clear()
        self.time_data.clear()
        self.raw_data.clear()
        self.data_text.clear()
        
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.save_btn.setEnabled(False)
        
        self.current_force_label.setText("力/质量: 采集中...")
        self.current_raw_label.setText("原始ADC: 采集中...")
    
    def stop_collection(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.save_btn.setEnabled(len(self.force_data) > 0)
        
        if len(self.force_data) > 0:
            avg_force = np.mean(self.force_data)
            self.current_force_label.setText(f"力/质量: {avg_force:.2f}")
    
    def handle_data(self, data):
        if data.startswith("ERROR:"):
            QMessageBox.critical(self, "连接错误", data[6:])
            self.disconnect_all()
            return
        
        if data == "START":
            self.current_force_label.setText("力/质量: 设备就绪")
            self.current_raw_label.setText("原始ADC: 等待数据...")
            return
        
        if data.startswith("TARE_DONE"):
            parts = data.split(",")
            if len(parts) == 2:
                try:
                    self.offset = int(parts[1])
                    self.current_force_label.setText("力/质量: 去皮完成")
                except:
                    pass
            return
        
        if data.startswith("CALIBRATE_READY"):
            self.current_force_label.setText("力/质量: 请放置已知质量砝码")
            return
        
        if not self.stop_btn.isEnabled():
            try:
                if "," in data:
                    parts = data.split(",")
                    if len(parts) == 2:
                        timestamp_ms = int(parts[0])
                        raw_value = int(parts[1])
                        self.raw_data.append(raw_value)
                        
                        if self.calibrated:
                            force_value = (raw_value - self.offset) * self.scale
                        else:
                            force_value = float(raw_value)
                        
                        self.current_raw_label.setText(f"原始ADC: {raw_value}")
                        self.current_force_label.setText(f"力/质量: {force_value:.2f}")
            except ValueError:
                pass
            return
        
        try:
            if "," in data:
                parts = data.split(",")
                if len(parts) == 2:
                    timestamp_ms = int(parts[0])
                    raw_value = int(parts[1])
                    
                    if len(self.time_data) == 0:
                        self.start_timestamp_ms = timestamp_ms
                    
                    relative_time_s = (timestamp_ms - self.start_timestamp_ms) / 1000.0
                    
                    self.raw_data.append(raw_value)
                    
                    if self.calibrated:
                        force_value = (raw_value - self.offset) * self.scale
                    else:
                        force_value = float(raw_value)
                    
                    self.force_data.append(force_value)
                    self.time_data.append(relative_time_s)
                    
                    current_time = datetime.now()
                    time_str = current_time.strftime("%H:%M:%S.%f")[:-3]
                    
                    unit = "g" if self.calibrated else "raw"
                    display_text = f"时间: {time_str} | ADC: {raw_value} | {unit}: {force_value:.2f}"
                    self.current_raw_label.setText(f"原始ADC: {raw_value}")
                    self.current_force_label.setText(f"力/质量: {force_value:.2f} {unit}")
                    
                    self.data_text.append(display_text)
                    self.data_text.verticalScrollBar().setValue(
                        self.data_text.verticalScrollBar().maximum()
                    )
                    
                    self.update_stats()
                    
                    if self.flask_server:
                        self.flask_server.update_data('force', {
                            'force': force_value,
                            'raw_adc': raw_value,
                            'timestamp': time_str,
                            'connected': True,
                            'collecting': True,
                            'history': [(time_str, force_value)]
                        })
                    
        except ValueError:
            pass
    
    def update_stats(self):
        if len(self.force_data) > 0:
            avg_force = np.mean(self.force_data)
            max_force = np.max(self.force_data)
            min_force = np.min(self.force_data)
            std_force = np.std(self.force_data)
            
            unit = "g" if self.calibrated else "raw"
            stats_text = (f"统计: 数据点 {len(self.force_data)} | "
                         f"平均={avg_force:.2f}{unit} | "
                         f"最大={max_force:.2f}{unit} | "
                         f"最小={min_force:.2f}{unit} | "
                         f"标准差 σ={std_force:.3f}")
            self.stats_label.setText(stats_text)
    
    def update_chart(self):
        if len(self.force_data) > 0:
            self.figure.clear()
            ax = self.figure.add_subplot(111)
            
            unit = "质量 (g)" if self.calibrated else "原始ADC值"
            ax.plot(self.time_data, self.force_data, '#0078d4', linewidth=2, label=unit)
            
            ax.set_xlabel('时间 (秒)')
            ax.set_ylabel(unit)
            ax.set_title('力传感器实时数据', fontsize=14, fontweight='bold')
            ax.grid(True, alpha=0.3)
            ax.legend(loc='upper right')
            
            if len(self.time_data) > 1:
                ax.set_xlim(min(self.time_data), max(self.time_data))
            
            self.figure.tight_layout()
            self.canvas.draw()
    
    def save_data(self):
        if len(self.force_data) == 0:
            QMessageBox.warning(self, "警告", "没有数据可保存")
            return
        
        try:
            unit = "g" if self.calibrated else "raw"
            filename = f"force_sensor_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"time_s,raw_adc,force_{unit}\n")
                for i, (time_val, force_val, raw_val) in enumerate(
                    zip(self.time_data, self.force_data, self.raw_data[-len(self.time_data):])):
                    f.write(f"{time_val:.3f},{raw_val},{force_val:.3f}\n")
            
            QMessageBox.information(self, "成功",
                                   f"数据已保存到：{filename}\n"
                                   f"共 {len(self.force_data)} 个数据点")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败：{e}")
    
    def clear_data(self):
        self.force_data.clear()
        self.time_data.clear()
        self.raw_data.clear()
        self.data_text.clear()
        self.stats_label.setText("统计信息: 暂无数据")
        self.current_force_label.setText("力/质量: --.-")
        self.current_raw_label.setText("原始ADC: ------")
        self.figure.clear()
        self.canvas.draw()
        self.save_btn.setEnabled(False)


class CalibrationDialog(QDialog):
    """校准参数编辑对话框"""
    
    def __init__(self, calibration_points, parent=None):
        super().__init__(parent)
        self.calibration_points = calibration_points
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("编辑校准参数")
        self.setModal(True)
        self.setFixedSize(450, 350)
        
        layout = QVBoxLayout()
        
        # 说明文字
        info_label = QLabel(
            "请输入三点校准的标准缓冲液 pH 值及其对应的 ADC 原始值：\n"
            "• 酸性缓冲液（如 pH 4.00）\n"
            "• 中性缓冲液（如 pH 6.86）\n"
            "• 碱性缓冲液（如 pH 9.18）"
        )
        info_label.setStyleSheet("color: #666; padding: 10px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # 创建输入框
        self.point_widgets = []
        point_names = ["酸性缓冲液 (点 1)", "中性缓冲液 (点 2)", "碱性缓冲液 (点 3)"]
        
        for i, (name, (ph_val, adc_val)) in enumerate(zip(point_names, self.calibration_points)):
            group = QGroupBox(name)
            group_layout = QHBoxLayout()
            
            # pH 值输入
            ph_label = QLabel("pH 值:")
            group_layout.addWidget(ph_label)
            
            self.ph_input = QLineEdit(str(ph_val))
            self.ph_input.setFixedWidth(80)
            self.ph_input.setAlignment(Qt.AlignmentFlag.AlignRight)
            group_layout.addWidget(self.ph_input)
            
            group_layout.addWidget(QLabel("→"))
            
            # ADC 值输入
            adc_label = QLabel("ADC 值:")
            group_layout.addWidget(adc_label)
            
            self.adc_input = QLineEdit(str(adc_val))
            self.adc_input.setFixedWidth(80)
            self.adc_input.setAlignment(Qt.AlignmentFlag.AlignRight)
            group_layout.addWidget(self.adc_input)
            
            group_layout.addStretch()
            group.setLayout(group_layout)
            layout.addWidget(group)
            
            self.point_widgets.append({
                'ph': self.ph_input,
                'adc': self.adc_input
            })
        
        # 按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #f0f0f0;
                color: #333;
                border: 1px solid #ccc;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
        """)
        button_layout.addWidget(cancel_btn)
        
        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(self.accept)
        ok_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
            QPushButton:pressed {
                background-color: #005a9e;
            }
        """)
        button_layout.addWidget(ok_btn)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def get_calibration_points(self):
        """获取校准参数"""
        points = []
        for widget in self.point_widgets:
            ph_val = float(widget['ph'].text())
            adc_val = int(widget['adc'].text())
            points.append((ph_val, adc_val))
        return points


class SampleRateDialog(QDialog):
    """采样频率设置对话框"""
    
    def __init__(self, current_interval_ms, parent=None):
        super().__init__(parent)
        self.current_interval_ms = current_interval_ms
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("设置采样频率")
        self.setModal(True)
        self.setFixedSize(400, 280)
        
        layout = QVBoxLayout()
        
        # 说明文字
        info_label = QLabel(
            "请选择数据采集的采样频率：\n"
            "频率越高，数据点越密集，但会增加数据传输负担。"
        )
        info_label.setStyleSheet("color: #666; padding: 10px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # 预设频率选项
        preset_group = QGroupBox("预设频率")
        preset_layout = QVBoxLayout()
        
        self.preset_buttons = []
        presets = [
            (20, "50 Hz", "高速采样，适合快速变化的信号"),
            (10, "100 Hz", "超高速采样，适合瞬态信号捕捉"),
            (50, "20 Hz", "中速采样，适合一般实验"),
            (100, "10 Hz", "标准采样，适合大多数实验"),
            (200, "5 Hz", "低速采样，适合缓慢变化的信号"),
            (500, "2 Hz", "超低速采样，节省存储空间"),
            (1000, "1 Hz", "最低速采样，长时间监测")
        ]
        
        for interval_ms, label, desc in presets:
            rb_layout = QHBoxLayout()
            rb = QRadioButton(f"{label}")
            rb.setProperty("interval", interval_ms)
            rb.setToolTip(desc)
            
            # 如果当前值匹配，则选中
            if interval_ms == self.current_interval_ms:
                rb.setChecked(True)
            
            rb_layout.addWidget(rb)
            rb_layout.addWidget(QLabel(f"({desc})"))
            rb_layout.addStretch()
            preset_layout.addLayout(rb_layout)
            
            self.preset_buttons.append(rb)
        
        preset_group.setLayout(preset_layout)
        layout.addWidget(preset_group)
        
        # 自定义频率
        custom_group = QGroupBox("自定义频率")
        custom_layout = QHBoxLayout()
        
        custom_layout.addWidget(QLabel("采样间隔:"))
        self.custom_input = QSpinBox()
        self.custom_input.setRange(10, 10000)
        self.custom_input.setValue(self.current_interval_ms)
        self.custom_input.setSuffix(" ms")
        self.custom_input.setFixedWidth(120)
        custom_layout.addWidget(self.custom_input)
        
        custom_layout.addWidget(QLabel("(对应 "))
        self.custom_freq_label = QLabel(f"{1000//self.current_interval_ms} Hz")
        self.custom_freq_label.setStyleSheet("font-weight: bold; color: #0078d4;")
        custom_layout.addWidget(self.custom_freq_label)
        custom_layout.addWidget(QLabel(")"))
        
        custom_layout.addStretch()
        custom_group.setLayout(custom_layout)
        layout.addWidget(custom_group)
        
        # 连接信号
        for rb in self.preset_buttons:
            rb.toggled.connect(self.on_preset_changed)
        
        self.custom_input.valueChanged.connect(self.on_custom_changed)
        
        # 按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #f0f0f0;
                color: #333;
                border: 1px solid #ccc;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
        """)
        button_layout.addWidget(cancel_btn)
        
        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(self.accept)
        ok_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
            QPushButton:pressed {
                background-color: #005a9e;
            }
        """)
        button_layout.addWidget(ok_btn)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def on_preset_changed(self, checked):
        """预设选项改变"""
        if checked:
            rb = self.sender()
            interval = rb.property("interval")
            self.custom_input.setValue(interval)
    
    def on_custom_changed(self, value):
        """自定义输入改变"""
        freq = 1000 // value
        self.custom_freq_label.setText(f"{freq} Hz")
    
    def get_sample_interval(self):
        """获取采样间隔"""
        return self.custom_input.value()


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
            "主页": self.create_text_icon("🏠"),       # 主页图标
            "超声波位移": self.create_text_icon("x"),  # 位移符号 x
            "超声波速度": self.create_text_icon("v"),
            "力传感器": self.create_text_icon("F"),
            "pH传感器": self.create_text_icon("pH"),
            "设置": self.create_text_icon("⚙")
        }
        
        # 添加模块项（主页放在第一位）
        self.modules = [
            ("主页", "项目介绍与功能导航"),
            ("超声波位移", "测量物体位移和运动轨迹"),
            ("超声波速度", "回声定位法测量物体速度"),
            ("力传感器", "HX711力/质量传感器测量"),
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
        
        # 设置全局字体为微软雅黑
        font = QFont("Microsoft YaHei", 9)
        self.setFont(font)
        
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
        
        # 主页
        home_page_widget = HomePageWidget()
        home_page_widget.module_clicked.connect(self.on_home_module_clicked)
        self.content_stack.addWidget(home_page_widget)
        self.modules["主页"] = home_page_widget
        
        # 超声波位移模块
        ultrasonic_widget = UltrasonicWidget()
        self.content_stack.addWidget(ultrasonic_widget)
        self.modules["超声波位移"] = ultrasonic_widget
        
        # 超声波速度模块
        ultrasonic_velocity_widget = UltrasonicVelocityWidget()
        self.content_stack.addWidget(ultrasonic_velocity_widget)
        self.modules["超声波速度"] = ultrasonic_velocity_widget
        
        # 力传感器模块
        force_sensor_widget = ForceSensorWidget()
        if hasattr(self, 'flask_server') and self.flask_server:
            force_sensor_widget.set_flask_server(self.flask_server)
        self.content_stack.addWidget(force_sensor_widget)
        self.modules["力传感器"] = force_sensor_widget
        
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
    
    def on_home_module_clicked(self, module_name):
        """处理主页模块卡片点击事件"""
        # 根据模块名称找到对应的索引
        module_index = None
        for i, (name, desc) in enumerate(self.sidebar.modules):
            if name == module_name:
                module_index = i
                break
        
        if module_index is not None:
            self.sidebar.set_current_row(module_index)
            self.switch_module(module_index)
    
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
