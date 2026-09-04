// Copyright (c) 2026 wangzhidong2
// SPDX-License-Identifier: GPL-3.0-only

// ============================================================
//  欧姆定律 / 电功率综合模块固件（方案一：ESP32 内置 ADC 双通道）
//  功能：同时测量 电压（分压后接 GPIO1） + 电流（ACS712 输出接 GPIO2）
//  输出格式：时间戳(ms),电压ADC原始值,电流ADC原始值
//  上位机匹配：欧姆定律模块 / 电功率模块 → 电压方式选「ESP32 内置 ADC」
//  测量范围：电压 0-3.3V（可加分压电阻扩展，上位机设分压比）；
//            电流由 ACS712 量程决定（5A/20A/30A，上位机选）
//  详细说明：参见 传感器代码/电学综合/README.md
// ============================================================

#define ADC_V_PIN 1        // GPIO1 (ADC1_CH0)，电压输入（分压后 0-3.3V）
#define ADC_I_PIN 2        // GPIO2 (ADC1_CH1)，ACS712 模拟输出
#define SAMPLE_INTERVAL 100  // 采样间隔 100ms (10Hz)

// ADC 配置参数
#define ADC_WIDTH_BIT ADC_WIDTH_BIT_12  // 12位分辨率，量化范围 0-4095

unsigned long lastSampleTime = 0;

void setup() {
  Serial.begin(115200);

  // 配置 ADC 参数
  analogReadResolution(12);           // 12位分辨率

  // 设置 11dB 衰减，量程 0-3.3V
  // 兼容不同版本 ESP32 库的衰减常量命名
  #if defined(ADC_ATTEN_DB_11)
    analogSetAttenuation(ADC_ATTEN_DB_11);
  #elif defined(ADC_ATTEN_11db)
    analogSetAttenuation(ADC_ATTEN_11db);
  #else
    analogSetAttenuation((adc_attenuation_t)3);
  #endif

  pinMode(ADC_V_PIN, INPUT);
  pinMode(ADC_I_PIN, INPUT);

  // 启动信息
  Serial.println("ESP32 VI Collector (Built-in ADC)");
  Serial.println("ADC Configuration:");
  Serial.println("- Resolution: 12 bits");
  Serial.println("- Attenuation: 11dB (0-3.3V)");
  Serial.println("- V channel: GPIO1, I channel: GPIO2 (ACS712)");
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

    int adcV = analogRead(ADC_V_PIN);
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