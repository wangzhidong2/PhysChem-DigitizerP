# HC-SR04 超声波传感器模块 - 高频采集版

## 项目简介

本项目提供了一个基于 WeMOS D1 (ESP8266) 开发板的 HC-SR04 超声波传感器驱动代码。采用高频采集方式，理论采样率可达 50Hz，输出时间戳和回波时间数据，便于电脑端进行精确的物理分析。

## 硬件需求

- WeMOS D1 开发板或其他 ESP8266 开发板
- HC-SR04 超声波传感器模块
- 面包板和连接线

## 硬件连接

| HC-SR04 引脚 | WeMOS D1 引脚 |
|-------------|---------------|
| VCC         | 5V            |
| GND         | GND           |
| TRIG        | D5            |
| ECHO        | D6            |

## 代码特性

### 高频采集
- 去掉 `delay()` 阻塞，使用 `micros()` 精确控制触发间隔
- 理论采样率可达 50Hz（每秒 50 次测量）
- 适合捕捉快速运动物体，满足动能定理实验需求

### 数据格式
- 输出格式：`时间戳(us),回波时间(us)`
- 示例：`123456,1450` 表示在 123.456 毫秒时，回波时间为 1450 微秒
- 无回波时不输出数据，避免垃圾数据干扰

### 可靠性设计
- 超时处理：6ms（对应约 1 米距离，适合实验轨道）
- 最小触发间隔：20ms，避免回波干扰
- 启动提示 "START"，便于电脑端判断设备连接状态

## 使用方法

1. 将代码上传到 WeMOS D1 开发板
2. 按照上述硬件连接方式连接 HC-SR04 模块
3. 打开串口监视器，设置波特率为 115200
4. 观察串口输出的时间戳和回波时间数据
5. 使用电脑端 Python 脚本接收和处理数据

## 电脑端数据处理

### Python 示例代码

```python
import serial
import time

# 配置串口（根据实际情况修改COM口）
ser = serial.Serial('COM3', 115200, timeout=1)
time.sleep(2)  # 等待串口初始化

# 等待启动信号
while True:
    if ser.in_waiting > 0:
        line = ser.readline().decode('utf-8').strip()
        if line == 'START':
            print("设备已连接")
            break

# 打开文件保存数据
with open('ultrasonic_data.csv', 'w') as f:
    f.write('timestamp_us,echo_time_us\n')
    
    try:
        while True:
            if ser.in_waiting > 0:
                line = ser.readline().decode('utf-8').strip()
                if line and line != 'START':
                    # 解析数据
                    parts = line.split(',')
                    if len(parts) == 2:
                        timestamp = int(parts[0])
                        echo_time = int(parts[1])
                        
                        # 计算距离（厘米）
                        distance_cm = echo_time / 58.0
                        
                        # 写入文件
                        f.write(f'{timestamp},{echo_time}\n')
                        f.flush()
                        
                        # 打印到控制台
                        print(f'时间: {timestamp/1000:.2f}ms, 回波: {echo_time}us, 距离: {distance_cm:.2f}cm')
    
    except KeyboardInterrupt:
        print("\n数据采集已停止")
        ser.close()
```

### 数据分析示例

```python
import pandas as pd
import matplotlib.pyplot as plt

# 读取数据
data = pd.read_csv('ultrasonic_data.csv')

# 转换时间戳为秒
data['timestamp_s'] = data['timestamp_us'] / 1000000

# 计算距离（厘米）
data['distance_cm'] = data['echo_time_us'] / 58.0

# 绘制距离-时间曲线
plt.figure(figsize=(10, 6))
plt.plot(data['timestamp_s'], data['distance_cm'])
plt.xlabel('时间 (s)')
plt.ylabel('距离 (cm)')
plt.title('物体运动轨迹')
plt.grid(True)
plt.show()

# 计算速度（通过距离差分）
data['velocity_cm_s'] = data['distance_cm'].diff() / data['timestamp_s'].diff()

# 计算加速度
data['acceleration_cm_s2'] = data['velocity_cm_s'].diff() / data['timestamp_s'].diff()

# 计算动能（需要知道物体质量）
mass_kg = 0.1  # 假设物体质量为 100 克
data['kinetic_energy_J'] = 0.5 * mass_kg * (data['velocity_cm_s'] / 100) ** 2

# 计算势能（需要知道高度变化）
# 假设轨道倾斜角度为 theta
theta = 30  # 度
import math
data['height_m'] = data['distance_cm'] / 100 * math.sin(math.radians(theta))
data['potential_energy_J'] = mass_kg * 9.8 * data['height_m']

# 验证机械能守恒
data['total_energy_J'] = data['kinetic_energy_J'] + data['potential_energy_J']
```

## 应用场景

- **物理实验**：探究动能定理与机械能守恒
- **运动分析**：测量物体运动轨迹、速度、加速度
- **距离测量**：高精度距离检测
- **机器人避障**：实时距离监测

## 误差分析

### 系统误差
- 触发信号长度（10微秒）对应的物理长度约为 3.4 毫米
- `pulseIn()` 函数的测量精度约为 4 微秒
- 超声波传播速度受温度影响（约 0.6 m/s/℃）

### 随机误差
- 空气湿度变化
- 反射面角度和材质
- 电路噪声干扰

### 改进建议
- 在电脑端进行温度补偿
- 使用滤波算法平滑数据
- 多次测量取平均值

## 参数调整

根据实验需求，可以调整以下参数：

```cpp
// 超时时间（根据轨道长度调整）
#define ECHO_TIMEOUT 6000  // 6ms，对应约1米距离

// 最小触发间隔（根据需要的采样率调整）
#define MIN_INTERVAL 20000  // 20ms，理论采样率50Hz
```

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request 来改进这个项目！
