# HC-SR04 超声波模块使用说明

## 📦 上位机模块

本目录包含 2 个上位机模块，均带识别区，由 `main.py` 自动加载：

| 模块文件 | 模块名 | 类别 | 主类 |
|----------|--------|------|------|
| [ultrasonic_displacement.py](ultrasonic_displacement.py) | 超声波位移 | physics | `UltrasonicWidget` |
| [ultrasonic_velocity.py](ultrasonic_velocity.py) | 超声波速度 | physics | `UltrasonicVelocityWidget` |

两个模块共享本目录下的 `.ino` 固件。位移模块用于实时距离测量，速度模块基于回声定位法计算瞬时速度。

## 📋 BOM 物料清单

| 组件 | 规格/型号 | 数量 | 备注 |
|------|-----------|------|------|
| 开发板 | ESP32 或 ESP8266 (WeMOS D1) | 1 | 任选其一 |
| 超声波模块 | HC-SR04 | 1 | 测距模块 |
| 杜邦线 | 公对母 | 4 | VCC, GND, TRIG, ECHO |
| USB 线 | Micro-USB 或 Type-C | 1 | 根据开发板类型 |

---

## 🔌 接线指南

### ESP32 s3 接线方式

```
ESP32 开发板        HC-SR04 模块
─────────────        ───────────
   5V (VIN)      →      VCC
   GND           →      GND
   GPIO5         →      TRIG (触发)
   GPIO6        →      ECHO (回波)
```

**固件代码**: [HC-SR04esp32.ino](HC-SR04esp32.ino)

**引脚定义**:
```cpp
#define TRIG_PIN 5   // GPIO5
#define ECHO_PIN 18  // GPIO18
```

### ESP8266 (WeMOS D1) 接线方式

```
ESP8266 (WeMOS D1)   HC-SR04 模块
─────────────────    ───────────
   5V (VIN)      →      VCC
   GND           →      GND
   D5 (GPIO14)   →      TRIG
   D6 (GPIO12)   →      ECHO
```

**固件代码**: [HC-SR04esp8266.ino](HC-SR04esp8266.ino)

**引脚定义**:
```cpp
#define TRIG_PIN 14  // D5 (GPIO14)
#define ECHO_PIN 12  // D6 (GPIO12)
```

### ️ 接线注意事项

1. **电压匹配**：HC-SR04 需要 5V/3.3V 工作电压，两个电压引脚均可
2. **电平转换**：ESP32/ESP8266 的 GPIO 为 3.3V，但 HC-SR04 的 ECHO 输出为 5V（供电5V时）
   - 实际测试中，3.3V供电的模块可直接连接
   - 若模块只支持5V，如需保险，可添加电平转换电路或分压电阻
3. **TRIG 引脚**：触发信号输入，需要 10µs 的高电平脉冲
4. **ECHO 引脚**：回波信号输出，高电平持续时间与距离成正比

---

##  模块简介

HC-SR04 是一款常用的超声波测距模块，广泛应用于距离测量、避障、液位检测等场景。本模块具有成本低、精度高、使用简单等特点，非常适合物理实验教学。

### 🎯 技术参数

| 参数 | 规格 |
|------|------|
| 工作电压 | 5V/3.3V DC |
| 工作电流 | 15mA |
| 测量范围 | 2cm - 400cm |
| 测量精度 | ±0.3cm |
| 测量角度 | <15° |
| 响应频率 | 40kHz |

### 🔧 工作原理

HC-SR04 模块通过发射 40kHz 的超声波脉冲，并接收从物体反射回来的回波，通过计算发射和接收的时间差来计算距离。

**距离计算公式：**
```
距离 (cm) = 回波时间 (µs) ÷ 58.0
距离 (cm) = 回波时间 (µs) × 0.017
```

---

## 💻 固件说明

### 数据输出格式

**串口输出：** `时间戳(us),回波时间(us)`

**示例数据：**
```
123456,1450
123476,1465
123496,1440
```

**Python 处理代码：**
```python
# 距离换算
distance_cm = echo_time / 58.0
# 或
distance_cm = echo_time * 0.017
```

### 固件核心代码示例（ESP32）

```cpp
#define TRIG_PIN 5   // GPIO5
#define ECHO_PIN 18  // GPIO18
#define ECHO_TIMEOUT 6000    // 超时阈值 (6ms)
#define MIN_INTERVAL 20000   // 最小触发间隔 (20ms)

void setup() {
  Serial.begin(115200);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  Serial.println("START");
}

void loop() {
  unsigned long now = micros();
  
  if (now - lastTriggerTime < MIN_INTERVAL) return;
  lastTriggerTime = now;
  
  // 发送触发脉冲
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  
  // 读取回波时间
  unsigned long echoTime = pulseIn(ECHO_PIN, HIGH, ECHO_TIMEOUT);
  
  if (echoTime > 0) {
    Serial.print(now);
    Serial.print(",");
    Serial.println(echoTime);
  }
}
```

---

## 🧪 实验应用

### 1. 位移测量实验
- **实验目的**：测量物体的直线运动位移
- **应用场景**：小车在轨道上的运动、弹簧振子位移
- **数据输出**：距离-时间曲线

### 2. 速度测量实验（回声定位法）
- **实验目的**：通过连续距离测量计算瞬时速度
- **应用场景**：匀加速运动、自由落体

#### 计算原理

通过连续两次超声波回波时间的差值，结合声速和测量间隔计算物体运动速度。

**数学表达式**：

```
v = (t₀ - t₁)/2 × vₛ / [(t₁ + t₀)/2 + Δt]
```

其中：
- `t₀`：第一次回波时间 (µs)
- `t₁`：第二次回波时间 (µs)
- `Δt`：两次发射的时间间隔 (s)
- `vₛ`：声速 = 34000 cm/s

**代码实现**（参考 [ultrasonic_velocity.py](ultrasonic_velocity.py) 中的 `calculate_velocity` 方法）：

```python
def calculate_velocity(self):
    # 获取最近两次测量的数据
    t0 = self.echo_time_data[-2]  # 第一次回波时间 (µs)
    t1 = self.echo_time_data[-1]  # 第二次回波时间 (µs)

    # 计算两次发射的时间间隔 Δt (秒)
    delta_t = 0.02  # 默认 20ms

    # 声速 (cm/s)
    v_sound = 34000  # 340 m/s = 34000 cm/s

    # 计算速度 (cm/s)
    # v = (t₀ - t₁)/2 × vₛ / [(t₁ + t₀)/2 + Δt]
    numerator = (t0 - t1) / 2.0 * v_sound
    denominator = (t1 + t0) / 2.0 + delta_t * 1000000  # 将 Δt 转换为 µs

    velocity_cm_s = numerator / denominator

    return velocity_cm_s
```

### 3. 简谐振动实验
- **实验目的**：分析周期性运动的规律
- **测量参数**：振幅、周期、频率
- **应用场景**：弹簧振子、单摆

---

## 🔍 性能优化

### 提高测量精度

1. **环境因素**：
   - 避免强风、温度剧烈变化
   - 测量表面应平整，避免吸音材料

2. **硬件优化**：
   - 使用稳定的电源
   - 缩短传感器与物体的距离（2-200cm 最佳）
   - 避免多路径反射干扰

3. **软件滤波**：
   - 多次测量取平均值
   - 中值滤波去除异常值
   - 卡尔曼滤波平滑数据

### 提高采样率

当前固件设置：
- **最小间隔**：20ms → **理论采样率**：50Hz
- **实际采样率**：约 40-45Hz（考虑处理时间）

**可调整参数：**
```cpp
// 降低间隔可提高采样率，但可能影响稳定性
#define MIN_INTERVAL 15000   // 15ms → ~66Hz
#define MIN_INTERVAL 10000   // 10ms → ~100Hz
```

---

## ⚠️ 常见问题

### Q1: 测量数据跳动大
**原因**：环境干扰、测量表面不平、电源不稳定
**解决**：
- 确保测量表面平整
- 使用稳定的电源
- 软件端添加滤波算法

### Q2: 超出测量范围
**原因**：物体距离太近（<2cm）或太远（>400cm）
**解决**：
- 调整传感器位置
- 检查是否有障碍物遮挡

### Q3: 无数据输出
**原因**：接线错误、模块损坏、波特率不匹配
**解决**：
- 检查 VCC、GND、TRIG、ECHO 连接
- 确认波特率为 115200
- 使用 Arduino 串口监视器测试

### Q4: 测量值偏小或偏大
**原因**：温度影响声速、模块个体差异
**解决**：
- 根据环境温度修正声速
- 进行校准：测量已知距离并调整系数

---

## 📊 校准方法

### 声速温度补偿

声速随温度变化：
```
声速 (m/s) = 331.4 + 0.6 × 温度 (°C)
```

**修正后的距离公式：**
```python
def calculate_distance(echo_time, temperature=20):
    speed_of_sound = 331.4 + 0.6 * temperature  # m/s
    distance = (echo_time * 1e-6 * speed_of_sound * 100) / 2  # cm
    return distance
```

### 实际校准步骤

1. 在已知距离（如 50cm）处放置物体
2. 测量回波时间
3. 计算校准系数：
   ```
   校准系数 = 已知距离 × 2 ÷ (回波时间 × 声速)
   ```
4. 更新距离计算公式

---

## 🔧 扩展应用

### 多传感器阵列
可连接多个 HC-SR04 模块，实现：
- 三维空间定位
- 物体尺寸测量
- 运动轨迹跟踪

### 与其他传感器结合
- **温度传感器**：自动声速补偿
- **惯性测量单元**：融合运动数据
- **摄像头**：视觉辅助定位

### 无线传输
利用 ESP32/ESP8266 的 WiFi 功能：
- 实时数据传输到云端
- 手机 App 远程监控
- 多设备同步采集

---

**Happy Measuring! 🔊**
