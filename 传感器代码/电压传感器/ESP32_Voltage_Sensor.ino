// ============================================================
//  电压传感器模块 - ESP32-S3 固件
//  模块名称：电压采集模块（Voltage Sensor）
//  功能：基于 ESP32-S3 内置 ADC 实现电压测量，通过串口输出原始 ADC 值
//  测量范围：0-3.3V DC（可通过分压电阻扩展）
//  数据格式：时间戳(ms),ADC原始值
//  详细说明：参见 README.md
// ============================================================

#define ADC_PIN 1        // GPIO1 (ADC1_CH0)，ESP32-S3 推荐 ADC 引脚
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

  pinMode(ADC_PIN, INPUT);

  // 启动信息
  Serial.println("ESP32 Voltage Sensor Collector");
  Serial.println("ADC Configuration:");
  Serial.println("- Resolution: 12 bits");
  Serial.println("- Attenuation: 11dB (0-3.3V)");
  Serial.println("- Sample Rate: 10Hz");
  Serial.println("- Output: Raw ADC Value (0-4095)");
  Serial.println("START");

  delay(1000); // 等待串口稳定
}

void loop() {
  unsigned long currentTime = millis();

  // 按采样间隔读取 ADC 并通过串口输出
  if (currentTime - lastSampleTime >= SAMPLE_INTERVAL) {
    lastSampleTime = currentTime;

    int adcValue = analogRead(ADC_PIN);

    // 输出格式：时间戳,ADC值 （供上位机解析）
    Serial.print(currentTime);
    Serial.print(",");
    Serial.println(adcValue);
  }

  delay(1);
}
