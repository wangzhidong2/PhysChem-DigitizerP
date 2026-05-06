// ESP32-S3 ADC 原始数据采集程序
// 功能：通过串口实时传输 ADC 模拟原始值
// 设置：ADC 衰减为 3.3V，最高精度配置

#define ADC_PIN 1        // 使用 GPIO1 (ADC1_CH0)，ESP32-S3 推荐引脚
#define SAMPLE_INTERVAL 100  // 采样间隔 100ms (10Hz)

// ADC 配置参数
#define ADC_WIDTH_BIT ADC_WIDTH_BIT_12  // 12位精度（ESP32 最高）
#define ADC_ATTEN_DB ADC_ATTEN_DB_11     // 11dB 衰减，对应 3.3V 量程

unsigned long lastSampleTime = 0;

void setup() {
  Serial.begin(115200);
  
  // 配置 ADC
  analogReadResolution(12);           // 设置 ADC 分辨率为 12 位
  analogSetAttenuation(ADC_ATTEN_DB_11); // 设置衰减为 11dB (0-3.3V)
  
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
  
  // 检查是否到达采样间隔
  if (currentTime - lastSampleTime >= SAMPLE_INTERVAL) {
    lastSampleTime = currentTime;
    
    // 读取 ADC 原始值
    int adcValue = analogRead(ADC_PIN);
    
    // 输出时间戳和 ADC 原始值
    Serial.print(currentTime);
    Serial.print(",");
    Serial.println(adcValue);
  }
  
  // 短暂延迟，避免过度占用 CPU
  delay(1);
}
