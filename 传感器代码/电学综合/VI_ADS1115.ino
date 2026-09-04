// Copyright (c) 2026 wangzhidong2
// SPDX-License-Identifier: GPL-3.0-only

// ============================================================
//  欧姆定律 / 电功率综合模块固件（方案二：ADS1115 16位电压 + ACS712 电流）
//  功能：同时测量 电压（ADS1115，I2C）+ 电流（ACS712 输出接 GPIO2）
//  输出格式：时间戳(ms),电压ADC原始值(有符号16位),电流ADC原始值
//  上位机匹配：欧姆定律模块 / 电功率模块 → 电压方式选「ADS1115 (16位)」
//  硬件接线：
//   ESP32-S3          ADS1115
//   3.3V/5V    --->   VDD
//   GND        --->   GND
//   GPIO21(SDA)--->   SDA
//   GPIO22(SCL)--->   SCL
//   GND        --->   ADDR（I2C 地址 0x48）
//   电压输入    --->   AIN0
//   ESP32-S3 GPIO2 <--->  ACS712 模拟输出（电流通道）
//
//  依赖库：Adafruit ADS1X15（Arduino IDE 库管理器搜索安装）
//  详细说明：参见 传感器代码/电学综合/README.md
// ============================================================

#include <Wire.h>
#include <Adafruit_ADS1X15.h>

Adafruit_ADS1115 ads;   // 16 位版本（ADS1015 改为 Adafruit_ADS1015）

#define ADC_I_PIN 2          // GPIO2 (ADC1_CH1)，ACS712 模拟输出
#define SAMPLE_INTERVAL 100  // 采样间隔 100ms (10Hz)
#define I2C_SDA_PIN 21       // ESP32-S3 默认 I2C SDA
#define I2C_SCL_PIN 22       // ESP32-S3 默认 I2C SCL

// ============================================================
// 用户配置区：与上位机「电压采样方式→ADS1115」参数保持一致
// ============================================================

// PGA 量程设置（6 档，对应数据手册 PGA[2:0]）
// 取消注释其一，与上位机 PGA 下拉框一致
#define PGA_RANGE GAIN_TWOTHIRDS    // ±6.144V (PGA=000)
// #define PGA_RANGE GAIN_ONE         // ±4.096V (PGA=001)
// #define PGA_RANGE GAIN_TWO         // ±2.048V (PGA=010，默认)
// #define PGA_RANGE GAIN_FOUR        // ±1.024V (PGA=011)
// #define PGA_RANGE GAIN_EIGHT       // ±0.512V (PGA=100)
// #define PGA_RANGE GAIN_SIXTEEN     // ±0.256V (PGA=101)

// 输入通道选择（MUX）：与上位机通道下拉框一致
#define MUX_CHANNEL ADS_PIN_AIN0    // 单端 AIN0
// #define MUX_CHANNEL ADS_PIN_AIN1  // 单端 AIN1
// #define MUX_CHANNEL ADS_PIN_AIN2  // 单端 AIN2
// #define MUX_CHANNEL ADS_PIN_AIN3  // 单端 AIN3
// #define MUX_CHANNEL ADS_PIN_DIFF_01  // 差分 AIN0-AIN1
// #define MUX_CHANNEL ADS_PIN_DIFF_23  // 差分 AIN2-AIN3

// 数据率（SPS）
// ADS1115 支持 8/16/32/64/128/250/475/860 SPS
// 注意：采样间隔应 ≥ 1000/SPS，否则读到的会是旧值
#define DATA_RATE ADSRATE_128       // 128 SPS（配合 10Hz 采样）

// ============================================================

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

  // 初始化 ADS1115
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  ads.setGain(PGA_RANGE);
  ads.setDataRate(DATA_RATE);
  if (!ads.begin()) {
    Serial.println("ERROR:ADS1115 not found");
    while (1) { delay(100); }
  }

  // 启动信息
  Serial.println("ESP32 VI Collector (ADS1115 + ACS712)");
  Serial.println("ADC Configuration:");
  Serial.println("- V channel: ADS1115 16-bit (signed), FSR by PGA");
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

    // 电压通道：按 MUX 配置读单端或差分
    int16_t adcV;
    if (MUX_CHANNEL == ADS_PIN_DIFF_01) {
      adcV = ads.readADC_Differential_0_1();
    } else if (MUX_CHANNEL == ADS_PIN_DIFF_23) {
      adcV = ads.readADC_Differential_2_3();
    } else {
      adcV = ads.readADC_SingleEnded(channelOf(MUX_CHANNEL));
    }
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

// 把 MUX 常量映射为单端通道号（差分通道走单独分支）
int channelOf(int mux) {
  switch (mux) {
    case ADS_PIN_AIN0: return 0;
    case ADS_PIN_AIN1: return 1;
    case ADS_PIN_AIN2: return 2;
    case ADS_PIN_AIN3: return 3;
    default: return 0;
  }
}