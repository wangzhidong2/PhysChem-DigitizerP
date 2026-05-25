// ESP32-S3 ADC 原始数据采集程序 - 蓝牙虚拟串口版
// 功能：通过蓝牙虚拟串口(BLE SPP)实时传输 ADC 模拟原始值
// 设置：ADC 衰减为 3.3V，最高精度配置
// 蓝牙设备名：ESP32_ADC_BT

#include "BluetoothSerial.h"

#if !defined(CONFIG_BT_ENABLED) || !defined(CONFIG_BLUEDROID_ENABLED)
#error Bluetooth is not enabled! Please run `make menuconfig` to enable BT and Bluedroid.
#endif

BluetoothSerial SerialBT;

#define ADC_PIN 1
#define SAMPLE_INTERVAL 100
#define BT_DEVICE_NAME "ESP32_ADC_BT"

#define ADC_WIDTH_BIT ADC_WIDTH_BIT_12

unsigned long lastSampleTime = 0;
bool btConnected = false;

void setup() {
  Serial.begin(115200);

  analogReadResolution(12);

  #if defined(ADC_ATTEN_DB_11)
    analogSetAttenuation(ADC_ATTEN_DB_11);
  #elif defined(ADC_ATTEN_11db)
    analogSetAttenuation(ADC_ATTEN_11db);
  #else
    analogSetAttenuation((adc_attenuation_t)3);
  #endif

  pinMode(ADC_PIN, INPUT);

  SerialBT.begin(BT_DEVICE_NAME);

  Serial.println("ESP32 ADC Raw Data Collector - Bluetooth Edition");
  Serial.println("ADC Configuration:");
  Serial.println("- Resolution: 12 bits");
  Serial.println("- Attenuation: 11dB (0-3.3V)");
  Serial.println("- Sample Rate: 10Hz");
  Serial.println("- Output: Raw ADC Value (0-4095)");
  Serial.print("- Bluetooth Device Name: ");
  Serial.println(BT_DEVICE_NAME);
  Serial.println("Waiting for Bluetooth connection...");

  SerialBT.println("ESP32 ADC Raw Data Collector - Bluetooth Edition");
  SerialBT.println("ADC Configuration:");
  SerialBT.println("- Resolution: 12 bits");
  SerialBT.println("- Attenuation: 11dB (0-3.3V)");
  SerialBT.println("- Sample Rate: 10Hz");
  SerialBT.println("- Output: Raw ADC Value (0-4095)");
  SerialBT.println("START");

  delay(1000);
}

void loop() {
  if (SerialBT.hasClient()) {
    if (!btConnected) {
      btConnected = true;
      Serial.println("Bluetooth client connected!");
    }
  } else {
    if (btConnected) {
      btConnected = false;
      Serial.println("Bluetooth client disconnected!");
    }
  }

  if (SerialBT.available()) {
    String cmd = SerialBT.readStringUntil('\n');
    cmd.trim();
    if (cmd == "START") {
      SerialBT.println("OK: Data stream active");
      Serial.println("BT CMD: START");
    } else if (cmd == "STOP") {
      SerialBT.println("OK: Data stream paused");
      Serial.println("BT CMD: STOP");
    } else if (cmd == "INFO") {
      SerialBT.println("INFO: ESP32 ADC, 12bit, 11dB atten, 10Hz, GPIO1");
      Serial.println("BT CMD: INFO");
    }
  }

  unsigned long currentTime = millis();

  if (currentTime - lastSampleTime >= SAMPLE_INTERVAL) {
    lastSampleTime = currentTime;

    int adcValue = analogRead(ADC_PIN);

    Serial.print(currentTime);
    Serial.print(",");
    Serial.println(adcValue);

    if (btConnected) {
      SerialBT.print(currentTime);
      SerialBT.print(",");
      SerialBT.println(adcValue);
    }
  }

  delay(1);
}
