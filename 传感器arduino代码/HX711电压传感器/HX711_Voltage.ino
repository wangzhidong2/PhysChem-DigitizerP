// ============================================================
//  HX711 电压传感器模块 - ESP32-S3 固件
//  模块名称：HX711 电压采集模块（Voltage Sensor）
//  功能：基于 HX711 24位 ADC 实现微小电压测量，通过串口输出原始 ADC 值
//  测量范围：±156mV 差分输入（通道 B，增益 32，AVDD=5V）
//  数据格式：时间戳(ms),ADC原始值
//  详细说明：参见 README.md
// ============================================================

#define HX711_DOUT_PIN 4        // GPIO4，HX711 数据引脚
#define HX711_SCK_PIN  5        // GPIO5，HX711 时钟引脚
#define SAMPLE_INTERVAL 100  // 采样间隔 100ms (10Hz)

unsigned long lastSampleTime = 0;

void setup() {
  Serial.begin(115200);

  // 配置 HX711 引脚
  pinMode(HX711_DOUT_PIN, INPUT);
  pinMode(HX711_SCK_PIN, OUTPUT);
  digitalWrite(HX711_SCK_PIN, LOW);

  // HX711 上电后需要等待芯片就绪
  delay(500);

  // 丢弃首次读取，用于从默认通道 A 切换到通道 B
  readHX711Raw();

  // 启动信息
  Serial.println("HX711 Voltage Sensor Collector");
  Serial.println("ADC Configuration:");
  Serial.println("- Resolution: 24 bits (signed)");
  Serial.println("- Channel: B (Gain 32, +-156mV)");
  Serial.println("- Sample Rate: 10Hz");
  Serial.println("- Output: Raw ADC Value (-8388608 ~ +8388607)");
  Serial.println("START");

  delay(1000); // 等待串口稳定
}

void loop() {
  unsigned long currentTime = millis();

  // 按采样间隔读取 ADC 并通过串口输出
  if (currentTime - lastSampleTime >= SAMPLE_INTERVAL) {
    lastSampleTime = currentTime;

    long adcValue = readHX711Raw();

    // 输出格式：时间戳,ADC值 （供上位机解析）
    Serial.print(currentTime);
    Serial.print(",");
    Serial.println(adcValue);
  }

  delay(1);
}

// 读取 HX711 原始 24 位有符号值（通道 B，增益 32）
long readHX711Raw() {
  // 等待 DOUT 拉低，表示数据就绪
  while (digitalRead(HX711_DOUT_PIN) == HIGH) {
    delay(1);
  }

  // 读取 24 位数据
  long value = 0;
  for (int i = 0; i < 24; i++) {
    digitalWrite(HX711_SCK_PIN, HIGH);
    delayMicroseconds(1);
    value = value << 1;
    if (digitalRead(HX711_DOUT_PIN) == HIGH) {
      value |= 1;
    }
    digitalWrite(HX711_SCK_PIN, LOW);
    delayMicroseconds(1);
  }

  // 发送 2 个额外脉冲设置下一次读取为 通道 B / 增益 32
  for (int i = 0; i < 2; i++) {
    digitalWrite(HX711_SCK_PIN, HIGH);
    delayMicroseconds(1);
    digitalWrite(HX711_SCK_PIN, LOW);
    delayMicroseconds(1);
  }

  // 24 位有符号数转换为 32 位有符号数
  if (value & 0x800000) {
    value |= 0xFF000000;
  }

  return value;
}
