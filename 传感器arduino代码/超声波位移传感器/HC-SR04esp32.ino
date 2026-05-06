// ESP32 驱动 HC-SR04 超声波模块 
// 高频采集版    
// 改进点：去掉delay阻塞，提高采样率；输出时间戳+回波时间 
// 波特率：115200 
// 
// 输出格式：时间戳(us),回波时间(us) 
// 电脑端 Python 脚本读取后换算：距离 s = echoTime / 58.0 (cm) 
//                                或   s = echoTime * 0.017   (cm) 

#define TRIG_PIN 5   // ESP32 触发引脚 (GPIO5)    备用方案 1：GPIO4  备用方案 2：GPIO2 
#define ECHO_PIN 18  // ESP32 接收引脚 (GPIO18)   备用方案 1：GPIO16 备用方案 2：GPIO15

// 超时阈值：超过此值认为无回波
// 6000us = 6ms，对应约1米距离（适合您的实验轨道）
#define ECHO_TIMEOUT 6000

// 两次触发之间的最小间隔（us）
// HC-SR04 建议至少 60ms，但实测 20-30ms 也可工作
// 设为 20ms → 理论最高采样率 ~50Hz
#define MIN_INTERVAL 20000

unsigned long lastTriggerTime = 0;

void setup() {
  Serial.begin(115200);

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);

  // ESP32 特有：设置 ADC 分辨率（可选，提高稳定性）
  analogReadResolution(12);
  
  // 启动提示（电脑端可据此判断设备已连接）
  Serial.println("START");
}

void loop() {
  unsigned long now = micros();

  // 控制两次触发的最小间隔，避免回波干扰
  if (now - lastTriggerTime < MIN_INTERVAL) {
    return;
  }

  lastTriggerTime = now;

  // 发送触发信号：10us 高电平脉冲
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  // 读取回波时间，设置超时防止死等
  unsigned long echoTime = pulseIn(ECHO_PIN, HIGH, ECHO_TIMEOUT);

  // 输出时间戳和回波时间（逗号分隔，便于Python解析）
  if (echoTime > 0) {
    Serial.print(now);
    Serial.print(",");
    Serial.println(echoTime);
  }
  // 无回波时跳过，不输出任何内容
  // 这样电脑端可以根据时间戳判断丢包
}