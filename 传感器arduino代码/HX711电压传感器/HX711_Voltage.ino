// ============================================================
//  HX711 电压传感器模块 - ESP32-S3 固件
//  模块名称：HX711 微小电压采集（通道 B）
//  功能：基于 HX711 24位 ADC 的通道 B（固定增益 32）测量 ~100mV 级电压
//        通过串口输出原始 ADC 值，由上位机进行换算
//  测量范围：±156mV 差分输入（AVDD=5V，增益 32）
//  接线：DOUT->GPIO4, PD_SCK->GPIO5
//        被测电压差分接入 B+ / B- 引脚
//  数据格式：时间戳(ms),ADC原始值
//  说明：
//    - 通道 B 固定增益 32，满量程差分输入约 ±156mV，适合测量 100mV 信号
//    - 通道 A 增益 128 满量程仅 ±39mV，测量 100mV 会饱和，因此必须使用通道 B
//    - HX711 上电默认通道 A 增益 128，首次读取后通过 2 个额外脉冲切换至通道 B
//    - HX711 输出为 24 位有符号数，范围 -8388608 ~ +8388607
//  详细说明：参见 README.md
// ============================================================

#define HX711_DOUT_PIN 4
#define HX711_SCK_PIN  5
#define SAMPLE_INTERVAL 100  // 采样间隔 100ms (10Hz)，与 HX711 默认输出速率匹配

unsigned long lastSampleTime = 0;

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

  // 关键：发送 2 个额外脉冲设置下一次读取为 通道 B / 增益 32
  // （1 个脉冲 = 通道A/Gain128；2 个脉冲 = 通道B/Gain32；3 个脉冲 = 通道A/Gain64）
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

void setup() {
  Serial.begin(115200);

  pinMode(HX711_DOUT_PIN, INPUT);
  pinMode(HX711_SCK_PIN, OUTPUT);
  digitalWrite(HX711_SCK_PIN, LOW);

  // HX711 上电后需要等待芯片就绪
  delay(500);

  // HX711 上电默认通道 A 增益 128，先丢弃一次读数以切换到通道 B 增益 32
  // 切换后所有后续 readHX711Raw() 都会自动维持通道 B
  readHX711Raw();
  delay(100);

  // 启动信息
  Serial.println("HX711 Voltage Sensor Collector");
  Serial.println("ADC Configuration:");
  Serial.println("- Resolution: 24 bits (signed)");
  Serial.println("- Channel: B (Gain 32, fixed)");
  Serial.println("- Full Scale: ~+-156mV (AVDD=5V)");
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
