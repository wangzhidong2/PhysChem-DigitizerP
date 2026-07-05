// ============================================================
//  HX711 电压测量模块 - ESP32-S3 固件
//  模块名称：HX711 微小电压采集（通道 B）
//  功能：使用 HX711 24位 ADC 的通道 B（固定增益 32）测量 ~100mV 级电压
//  接线：DOUT->GPIO4, PD_SCK->GPIO5
//        被测电压差分接入 B+ / B- 引脚
//  数据格式：timestamp_ms,raw_adc_value  （与上位机 ForceSensorWidget 解析一致）
//  说明：
//    - 通道 B 固定增益 32，AVDD=5V 时满量程差分输入约 ±156mV，适合测量 100mV 信号
//    - 通道 A 增益 128 满量程仅 ±39mV，测量 100mV 会饱和，因此必须使用通道 B
//    - HX711 上电后默认通道 A 增益 128，首次读取后通过 2 个额外脉冲切换至通道 B 增益 32
// ============================================================

#define HX711_DOUT_PIN 4
#define HX711_SCK_PIN  5
#define SAMPLE_INTERVAL 80   // 采样间隔 80ms (12.5Hz)，与 HX711 输出速率匹配

long offset = 0;
float scale = 1.0;
bool calibrated = false;

// 读取 HX711 原始 24 位有符号值（通道 B，增益 32）
// 关键：在 24 个数据位之后，发送 2 个额外脉冲以选择下一次读取为 通道B/Gain32
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

long readAverage(int times) {
  long sum = 0;
  for (int i = 0; i < times; i++) {
    sum += readHX711Raw();
  }
  return sum / times;
}

void tare(int times) {
  offset = readAverage(times);
}

float getUnits(int times) {
  long raw = readAverage(times);
  return (raw - offset) * scale;
}

void powerDown() {
  digitalWrite(HX711_SCK_PIN, LOW);
  digitalWrite(HX711_SCK_PIN, HIGH);
}

void powerUp() {
  digitalWrite(HX711_SCK_PIN, LOW);
}

unsigned long lastSampleTime = 0;

void setup() {
  Serial.begin(115200);

  pinMode(HX711_DOUT_PIN, INPUT);
  pinMode(HX711_SCK_PIN, OUTPUT);
  digitalWrite(HX711_SCK_PIN, LOW);

  powerUp();
  delay(500);

  // HX711 上电默认通道 A 增益 128，先丢弃一次读数以切换到通道 B 增益 32
  // 切换后所有后续 readHX711Raw() 都会自动维持通道 B
  readHX711Raw();
  delay(100);

  // 在通道 B 上做初始去皮
  tare(10);

  Serial.println("HX711 Voltage Sensor - ESP32-S3 (Channel B)");
  Serial.println("Configuration:");
  Serial.println("- Channel: B (Gain 32, fixed)");
  Serial.println("- Full Scale: ~+-156mV (AVDD=5V)");
  Serial.println("- Sample Rate: 12.5Hz (80ms interval)");
  Serial.println("- Output: timestamp_ms,raw_adc_value");
  Serial.println("- Tare offset: " + String(offset));
  Serial.println("START");

  delay(500);
}

void loop() {
  // 处理上位机命令
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd == "TARE") {
      tare(10);
      Serial.println("TARE_DONE," + String(offset));
    } else if (cmd == "CALIBRATE") {
      Serial.println("CALIBRATE_READY,place_known_weight");
    }
  }

  unsigned long currentTime = millis();

  // 按采样间隔输出原始 ADC 值
  if (currentTime - lastSampleTime >= SAMPLE_INTERVAL) {
    lastSampleTime = currentTime;

    long rawValue = readHX711Raw();

    Serial.print(currentTime);
    Serial.print(",");
    Serial.println(rawValue);
  }

  delay(1);
}
