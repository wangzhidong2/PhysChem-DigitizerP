// ============================================================
//  pH 传感器模块 - ESP32-S3 固件
//  模块名称：pH 采集模块（pH Sensor）
//  传感器：DFRobot SEN0161 pH 计（配信号放大模块）
//  功能：读取 pH 电极模拟输出，通过串口传输 ADC 原始值
//  测量范围：pH 0-14
//  数据格式：时间戳(ms),ADC原始值
//  校准方式：Python 上位机内校准（单点/两点/三点），参数存于 sensor_config.json
//  详细说明：参见 README.md
// ============================================================

#define ADC_PIN 1        // GPIO1 (ADC1_CH0)，ESP32-S3 推荐 ADC 引脚 → 接 pH 模块 PO
#define SAMPLE_INTERVAL 100  // 采样间隔 100ms (10Hz)

// ADC 配置参数
#define ADC_WIDTH_BIT ADC_WIDTH_BIT_12  // 12位分辨率，量化范围 0-4095

unsigned long lastSampleTime = 0;

void setup() {
  Serial.begin(115200);

  // 配置 ADC 参数
  analogReadResolution(12);           // 12位分辨率

  // 设置 11dB 衰减，量程 0-3.3V（pH 模块 PO 输出范围）
  // 兼容不同版本 ESP32 库的衰减常量命名
  #if defined(ADC_ATTEN_DB_11)
    analogSetAttenuation(ADC_ATTEN_DB_11);
  #elif defined(ADC_ATTEN_11db)
    analogSetAttenuation(ADC_ATTEN_11db);
  #else
    analogSetAttenuation((adc_attenuation_t)3);
  #endif
  
  // 配置 ADC 引脚
  pinMode(ADC_PIN, INPUT);
  
  // 启动信息
  Serial.println("ESP32 ADC Raw Data Collector");
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

  // 按采样间隔读取 pH 模块 ADC 值并通过串口输出
  if (currentTime - lastSampleTime >= SAMPLE_INTERVAL) {
    lastSampleTime = currentTime;

    int adcValue = analogRead(ADC_PIN);

    // 输出格式：时间戳,ADC值 （上位机接收后经校准转换为 pH 值）
    Serial.print(currentTime);
    Serial.print(",");
    Serial.println(adcValue);
  }
  
  // 短暂延迟，避免过度占用 CPU
  delay(1);
}
