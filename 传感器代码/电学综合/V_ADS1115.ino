// Copyright (c) 2026 wangzhidong2
// SPDX-License-Identifier: GPL-3.0-only

// 注意：本文件是 电压传感器/ADS1115_Voltage.ino 的副本，
// 「双板分测」模式下的电压板固件（只测电压）。修改请同步更新原文件。

// ============================================================
//  ADS1115 电压传感器模块 - ESP32-S3 固件
//  模块名称：ADS1115 电压采集模块（Voltage Sensor）
//  功能：基于 TI ADS1115 16位 I2C ADC 实现高精度电压测量
//        通过串口输出原始有符号 ADC 值（-32768 ~ +32767）
//  数据格式：时间戳(ms),ADC原始值
//  详细说明：参见 README.md
// ============================================================
//
// 硬件接线：
//   ESP32-S3          ADS1115
//   3.3V/5V    --->   VDD
//   GND        --->   GND
//   GPIO21(SDA)--->   SDA
//   GPIO22(SCL)--->   SCL
//   GND        --->   ADDR（I2C 地址 0x48）
//
// 依赖库：Adafruit ADS1X15（Arduino IDE 库管理器搜索安装）
//   https://github.com/adafruit/Adafruit_ADS1X15
//
// 上位机匹配：voltage_sensor.py 的 ADS1115 模式
//   - ADC 位数选 16 位
//   - 勾选「ADS1115 模式」
//   - PGA 量程与下方 PGA_CONFIG 保持一致
//   - 通道与下方 MUX_CHANNEL 保持一致
// ============================================================

#include <Wire.h>
#include <Adafruit_ADS1X15.h>

Adafruit_ADS1115 ads;   // 16 位版本（ADS1015 改为 Adafruit_ADS1015）

#define SAMPLE_INTERVAL 100   // 采样间隔 100ms (10Hz)
#define I2C_SDA_PIN 21        // ESP32-S3 默认 I2C SDA
#define I2C_SCL_PIN 22        // ESP32-S3 默认 I2C SCL

// ============================================================
// 用户配置区：与上位机 ADS1115 模式参数保持一致
// ============================================================

// PGA 量程设置（6 档，对应数据手册 PGA[2:0]）
// 取消注释其一，与上位机 PGA 下拉框一致
#define PGA_RANGE GAIN_TWOTHIRDS    // ±6.144V (PGA=000)
// #define PGA_RANGE GAIN_ONE         // ±4.096V (PGA=001)
// #define PGA_RANGE GAIN_TWO         // ±2.048V (PGA=010，默认)
// #define PGA_RANGE GAIN_FOUR        // ±1.024V (PGA=011)
// #define PGA_RANGE GAIN_EIGHT       // ±0.512V (PGA=100)
// #define PGA_RANGE GAIN_SIXTEEN     // ±0.256V (PGA=101)

// 输入通道选择（MUX）
// 单端：读取 AIN0/AIN1/AIN2/AIN3 相对 GND 的电压
// 差分：读取两通道电压差（AINP - AINN）
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

  // 初始化 I2C（ESP32-S3 指定引脚）
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);

  // 初始化 ADS1115（地址 0x48，ADDR 接 GND）
  if (!ads.begin(0x48)) {
    Serial.println("ERROR: ADS1115 not found, check wiring/address");
    while (1) delay(10);
  }

  // 设置 PGA 量程
  ads.setGain(PGA_RANGE);

  // 设置数据率
  ads.setDataRate(DATA_RATE);

  // 启动信息（供上位机识别）
  Serial.println("ADS1115 Voltage Sensor Collector");
  Serial.println("ADC Configuration:");
  Serial.println("- Chip: TI ADS1115 (16-bit signed two's complement)");
  Serial.println("- Resolution: 16 bits (-32768 ~ +32767)");
  Serial.print  ("- PGA: ");
  Serial.println(pgaToString(PGA_RANGE));
  Serial.print  ("- Channel: ");
  Serial.println(channelToString(MUX_CHANNEL));
  Serial.print  ("- Data Rate: ");
  Serial.print(dataRateToSPS(DATA_RATE));
  Serial.println(" SPS");
  Serial.println("- Output: Raw ADC Value (signed int16)");
  Serial.println("- Formula: voltage = raw / 32768 * FSR");
  Serial.println("START");

  delay(1000);  // 等待串口稳定
}

void loop() {
  unsigned long currentTime = millis();

  if (currentTime - lastSampleTime >= SAMPLE_INTERVAL) {
    lastSampleTime = currentTime;

    // 读取 ADC 原始值（int16_t 有符号，已自动转换补码）
    int16_t adcValue = ads.readADC(MUX_CHANNEL);

    // 输出格式：时间戳,ADC值（供上位机解析）
    Serial.print(currentTime);
    Serial.print(",");
    Serial.println(adcValue);
  }

  delay(1);
}

// ============================================================
// 辅助函数：将配置枚举转为字符串，便于启动日志打印
// ============================================================
String pgaToString(adsGain_t g) {
  switch (g) {
    case GAIN_TWOTHIRDS: return "±6.144V (GAIN_TWOTHIRDS)";
    case GAIN_ONE:       return "±4.096V (GAIN_ONE)";
    case GAIN_TWO:       return "±2.048V (GAIN_TWO)";
    case GAIN_FOUR:      return "±1.024V (GAIN_FOUR)";
    case GAIN_EIGHT:     return "±0.512V (GAIN_EIGHT)";
    case GAIN_SIXTEEN:   return "±0.256V (GAIN_SIXTEEN)";
    default:             return "Unknown";
  }
}

String channelToString(adsChannel_t c) {
  switch (c) {
    case ADS_PIN_AIN0:     return "AIN0 (single-ended)";
    case ADS_PIN_AIN1:     return "AIN1 (single-ended)";
    case ADS_PIN_AIN2:     return "AIN2 (single-ended)";
    case ADS_PIN_AIN3:     return "AIN3 (single-ended)";
    case ADS_PIN_DIFF_01:  return "AIN0-AIN1 (differential)";
    case ADS_PIN_DIFF_23:  return "AIN2-AIN3 (differential)";
    default:               return "Unknown";
  }
}

uint16_t dataRateToSPS(adsDataRate_t r) {
  switch (r) {
    case ADSRATE_8:   return 8;
    case ADSRATE_16:  return 16;
    case ADSRATE_32:  return 32;
    case ADSRATE_64:  return 64;
    case ADSRATE_128: return 128;
    case ADSRATE_250: return 250;
    case ADSRATE_475: return 475;
    case ADSRATE_860: return 860;
    default:          return 0;
  }
}
