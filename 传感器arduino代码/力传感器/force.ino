// ESP32-S3 HX711 力传感器数据采集程序
// 功能：通过串口实时传输 HX711 24位ADC原始值
// 数据格式：timestamp_ms,raw_adc_value
// 接线：DOUT->GPIO4, PD_SCK->GPIO5

#define HX711_DOUT_PIN 4
#define HX711_SCK_PIN  5
#define SAMPLE_INTERVAL 80

long offset = 0;
float scale = 1.0;
bool calibrated = false;

long readHX711Raw() {
  while (digitalRead(HX711_DOUT_PIN) == HIGH) {
    delay(1);
  }

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

  // Channel A, Gain 128: 25th pulse
  digitalWrite(HX711_SCK_PIN, HIGH);
  delayMicroseconds(1);
  digitalWrite(HX711_SCK_PIN, LOW);
  delayMicroseconds(1);

  // Convert 24-bit signed value
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

  tare(10);

  Serial.println("HX711 Mass Sensor - ESP32-S3");
  Serial.println("Configuration:");
  Serial.println("- Channel: A (Gain 128)");
  Serial.println("- Sample Rate: 12.5Hz (80ms interval)");
  Serial.println("- Output: timestamp_ms,raw_adc_value");
  Serial.println("- Tare offset: " + String(offset));
  Serial.println("START");

  delay(500);
}

void loop() {
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

  if (currentTime - lastSampleTime >= SAMPLE_INTERVAL) {
    lastSampleTime = currentTime;

    long rawValue = readHX711Raw();

    Serial.print(currentTime);
    Serial.print(",");
    Serial.println(rawValue);
  }

  delay(1);
}
