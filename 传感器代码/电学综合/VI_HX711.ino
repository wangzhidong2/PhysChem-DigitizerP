// Copyright (c) 2026 wangzhidong2
// SPDX-License-Identifier: GPL-3.0-only

// ============================================================
//  欧姆定律 / 电功率综合模块固件（方案三：HX711 24位电压 + ACS712 电流）
//  功能：同时测量 电压（HX711，GPIO4/GPIO5）+ 电流（ACS712 输出接 GPIO2）
//  输出格式：时间戳(ms),电压ADC原始值(有符号24位),电流ADC原始值
//  上位机匹配：欧姆定律模块 / 电功率模块 → 电压方式选「HX711 (24位)」
//  测量范围：±156mV 差分输入（通道 B，增益 32，AVDD=5V）
//  硬件接线：
//   ESP32-S3        HX711
//   GPIO4     --->  DOUT
//   GPIO5     --->  SCK
//   3.3V/5V   --->  VCC / AVDD
//   GND       --->  GND
//   电压输入   --->  IN+ / IN-（差分）
//   ESP32-S3 GPIO2 <--->  ACS712 模拟输出（电流通道）
//  详细说明：参见 传感器代码/电学综合/README.md
// ============================================================

#define HX711_DOUT_PIN 4        // GPIO4，HX711 数据引脚
#define HX711_SCK_PIN  5        // GPIO5，HX711 时钟引脚
#define ADC_I_PIN 2             // GPIO2 (ADC1_CH1)，ACS712 模拟输出
#define SAMPLE_INTERVAL 100     // 采样间隔 100ms (10Hz)

unsigned long lastSampleTime = 0;

void setup() {
  Serial.begin(115200);

  // 配置电流通道 ADC
  analogReadResolution(12);
  #if defined(ADC_ATTEN_DB_11)
    analogSetAttenuation(ADC_ATTEN_DB_11);
  #elif defined(ADC_ATTEN_11db)
    analogSetAttenuation(ADC_ATTEN_11db);
  #else
    analogSetAttenuation((adc_attenuation_t)3);
  #endif
  pinMode(ADC_I_PIN, INPUT);

  // 配置 HX711 引脚
  pinMode(HX711_DOUT_PIN, INPUT);
  pinMode(HX711_SCK_PIN, OUTPUT);
  digitalWrite(HX711_SCK_PIN, LOW);

  // HX711 上电后需要等待芯片就绪
  delay(500);

  // 丢弃首次读取，用于从默认通道 A 切换到通道 B
  readHX711Raw();

  // 启动信息
  Serial.println("ESP32 VI Collector (HX711 + ACS712)");
  Serial.println("ADC Configuration:");
  Serial.println("- V channel: HX711 24-bit (signed, Channel B, gain 32)");
  Serial.println("- I channel: GPIO2 (ACS712), 12-bit");
  Serial.println("- Sample Rate: 10Hz");
  Serial.println("- Output: timestamp,adc_v,adc_i");
  Serial.println("START");

  delay(1000); // 等待串口稳定
}

void loop() {
  unsigned long currentTime = millis();

  // 按采样间隔读取两路 ADC 并通过串口输出
  if (currentTime - lastSampleTime >= SAMPLE_INTERVAL) {
    lastSampleTime = currentTime;

    long adcV = readHX711Raw();
    int adcI = analogRead(ADC_I_PIN);

    // 输出格式：时间戳,电压ADC原始值,电流ADC原始值 （供上位机解析）
    Serial.print(currentTime);
    Serial.print(",");
    Serial.print(adcV);
    Serial.print(",");
    Serial.println(adcI);
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
  unsigned long raw = 0;
  for (int i = 0; i < 24; i++) {
    digitalWrite(HX711_SCK_PIN, HIGH);
    raw = (raw << 1) | digitalRead(HX711_DOUT_PIN);
    digitalWrite(HX711_SCK_PIN, LOW);
  }

  // 第 25 个脉冲：设置增益 32（通道 B）
  digitalWrite(HX711_SCK_PIN, HIGH);
  digitalWrite(HX711_SCK_PIN, LOW);

  // 24 位有符号扩展
  if (raw & 0x800000) {
    raw |= 0xFF000000;
  }
  return (long)raw;
}