// ============================================================
// ESP32-S3 驱动 HC-SR04 超声波模块 — 高频采集版 + BLE 串口传输
// ============================================================
// 改进点：
//   1. 去掉 delay() 阻塞，提高采样率
//   2. 输出时间戳 + 回波时间，便于后续分析
//   3. 使用 BLE NUS（Nordic UART Service）实现无线串口传输
//      兼容 ESP32-S3（仅支持 BLE，不支持蓝牙经典 SPP）
//      设备名 csbsenior
//
// 有线串口波特率：115200
// BLE 串口：Nordic UART Service (NUS) 协议
//
// 输出格式（双通道相同）：时间戳(us),回波时间(us)
//   例：12345678,580
//
// 电脑端 Python 脚本读取后换算距离：
//   距离 s = echoTime / 58.0  (cm)    ← HC-SR04 声速约 340m/s 标准换算
//        或 s = echoTime * 0.017 (cm)   ← 等价写法
//
// BLE 连接方式：
//   - 上传代码后，ESP32-S3 广播 BLE 设备名 "csbsenior"
//   - 手机端：使用 nRF Connect、Serial Bluetooth Terminal 等 APP
//     搜索 "csbsenior" → 连接 → 找到 NUS 服务 → 开启 Notify 即可接收数据
//   - 电脑端 Python：使用 bleak 库连接，订阅 TX 特征值的 Notify
//     TX 特征 UUID：6E400003-B5A3-F393-E0A9-E50E24DCCA9E
//   - Windows 10/11 也可在蓝牙设置中配对后，通过 "设备管理器" 查看
//     但 BLE 不像经典蓝牙那样自动生成 COM 口，需用 bleak 库直接通信
//
// ESP32-S3 接线说明：
//   HC-SR04 VCC → 5V (或 VIN)
//   HC-SR04 GND → GND
//   HC-SR04 TRIG → GPIO5
//   HC-SR04 ECHO → 电阻分压后接 GPIO6（见下方注释）
//
//   ⚠️ ECHO 分压电路（HC-SR04 输出 5V，ESP32-S3 GPIO 仅耐 3.3V）：
//     ECHO ──[ 1kΩ ]──┬── GPIO6
//                      │
//                    [ 2kΩ ]
//                      │
//                     GND
//     分压后 ≈ 3.33V，安全。若使用 HC-SR04P（3.3V 版）则无需分压。
// ============================================================

// ---------- BLE 头文件 ----------
// ESP32 Arduino 核心自带，无需额外安装
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

// ---------- 引脚定义（ESP32-S3 安全引脚）----------
// TRIG_PIN：触发信号输出引脚，用于向 HC-SR04 发送 10us 高电平脉冲启动测距
//   GPIO5 为 ESP32-S3 安全通用引脚 | 备选：GPIO4, GPIO7, GPIO8
#define TRIG_PIN 5

// ECHO_PIN：回波信号输入引脚，HC-SR04 收到回波后拉高，高电平持续时间 = 往返时间
//   GPIO6 为 ESP32-S3 安全通用引脚 | 备选：GPIO7, GPIO8, GPIO9
//   ⚠️ 必须通过电阻分压将 5V 信号降至 3.3V，否则可能损坏 ESP32-S3
#define ECHO_PIN 6

// ---------- 超时阈值 ----------
// pulseIn() 等待 ECHO_PIN 变高的最大时间（微秒）
// 超过此值认为无回波（目标超出量程或声波被吸收）
// 6000us ≈ 6ms，对应单程距离约 103cm（适合实验轨道 ~1m 量程）
// 如需更大量程可增大此值，但会降低无回波时的采样率
#define ECHO_TIMEOUT 6000

// ---------- 最小触发间隔 ----------
// 两次触发之间的最小间隔（微秒）
// HC-SR04 数据手册建议 ≥ 60ms，但实测 20-30ms 也能正常工作
// 设为 20000us = 20ms → 理论最高采样率约 50Hz
// 若出现误触发或回波串扰，可增大此值至 60000（60ms）以提高稳定性
#define MIN_INTERVAL 20000

// ---------- BLE NUS 服务 UUID ----------
// Nordic UART Service (NUS) 是 BLE 串口通信的事实标准
// 大多数 BLE 串口终端 APP（nRF Connect、Serial Bluetooth Terminal 等）都支持此协议
// 三个 UUID 分别对应：服务、RX 特征（手机→设备）、TX 特征（设备→手机）
#define SERVICE_UUID           "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
#define CHARACTERISTIC_UUID_RX "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
#define CHARACTERISTIC_UUID_TX "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

// ---------- 全局对象与变量 ----------
// BLE 相关对象指针
BLEServer *pServer = nullptr;             // BLE 服务器，管理连接和广播
BLECharacteristic *pTxCharacteristic = nullptr;  // TX 特征，用于向手机/电脑发送数据（Notify）

// deviceConnected：BLE 连接状态标志
//   true = 有客户端已连接，可以向 TX 特征发送 Notify 数据
//   false = 无连接，跳过 BLE 发送以节省资源
bool deviceConnected = false;

// lastTriggerTime：记录上一次触发测距的时刻（micros() 返回值）
//   用于控制两次触发之间的最小间隔，避免回波干扰
unsigned long lastTriggerTime = 0;

// ==================== BLE 连接回调类 ====================
// 继承 BLEServerCallbacks，重写 onConnect / onDisconnect
// 当手机/电脑连接或断开 BLE 时自动触发，更新 deviceConnected 标志
class MyServerCallbacks : public BLEServerCallbacks {
  // 客户端连接时的回调
  // 参数 pServer 指向触发回调的 BLE 服务器对象
  void onConnect(BLEServer *pServer) {
    deviceConnected = true;
    Serial.println("BLE 客户端已连接");
  }

  // 客户端断开时的回调
  // 断开后自动重启广播，等待新的客户端连接
  void onDisconnect(BLEServer *pServer) {
    deviceConnected = false;
    Serial.println("BLE 客户端已断开，重启广播...");
    // 重启广播，使其他设备可以再次发现并连接
    BLEDevice::startAdvertising();
  }
};

// ==================== BLE 接收回调类 ====================
// 继承 BLECharacteristicCallbacks，重写 onWrite
// 当手机/电脑通过 RX 特征发送数据时触发
// 本程序暂不处理接收数据，但保留接口以便后续扩展（如远程控制采样率）
class MyCharacteristicCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *pCharacteristic) {
    String rxValue = pCharacteristic->getValue().c_str();
    if (rxValue.length() > 0) {
      Serial.print("BLE 收到: ");
      Serial.println(rxValue);
    }
  }
};

// ==================== 初始化 ====================
void setup() {
  // 初始化 USB 有线串口，波特率 115200
  // 用于通过 USB 线直接在串口监视器或 Python 端查看数据
  Serial.begin(115200);

  // 配置引脚模式
  pinMode(TRIG_PIN, OUTPUT);  // 触发引脚设为输出，用于发送脉冲
  pinMode(ECHO_PIN, INPUT);   // 回波引脚设为输入，用于读取高电平持续时间

  // ESP32 特有：设置 ADC 分辨率为 12 位（0-4095）
  // 本程序未直接使用 ADC，但设置后可提高系统定时精度和稳定性
  analogReadResolution(12);

  // ---------- BLE 初始化 ----------
  // 1. 创建 BLE 设备，设置设备名为 "csbsenior"
  //    该名称会出现在手机/电脑的 BLE 扫描列表中
  BLEDevice::init("csbsenior");

  // 2. 创建 BLE 服务器，并注册连接/断开回调
  //    服务器负责管理客户端连接和 GATT 服务
  pServer = BLEDevice::createServer();
  pServer->setCallbacks(new MyServerCallbacks());

  // 3. 创建 NUS 服务
  //    使用 Nordic UART Service 的标准 UUID
  //    该服务包含两个特征：TX（设备→客户端）和 RX（客户端→设备）
  BLEService *pService = pServer->createService(SERVICE_UUID);

  // 4. 创建 TX 特征（设备 → 手机/电脑）
  //    属性：NOTIFY — 设备主动推送数据给客户端，客户端无需轮询
  //    BLE2902 是 Notify 的描述符，客户端通过它订阅/取消订阅通知
  pTxCharacteristic = pService->createCharacteristic(
    CHARACTERISTIC_UUID_TX,
    BLECharacteristic::PROPERTY_NOTIFY
  );
  pTxCharacteristic->addDescriptor(new BLE2902());

  // 5. 创建 RX 特征（手机/电脑 → 设备）
  //    属性：WRITE — 客户端可向此特征写入数据
  //    目前仅打印收到的内容，可用于后续扩展远程控制功能
  BLECharacteristic *pRxCharacteristic = pService->createCharacteristic(
    CHARACTERISTIC_UUID_RX,
    BLECharacteristic::PROPERTY_WRITE
  );
  pRxCharacteristic->setCallbacks(new MyCharacteristicCallbacks());

  // 6. 启动服务
  //    服务启动后，客户端才能发现并使用其中的特征
  pService->start();

  // 7. 开始广播
  //    广播使其他 BLE 设备能够发现 "csbsenior" 并发起连接
  //    连接建立后广播自动停止；断开后在 onDisconnect 回调中重启广播
  BLEDevice::startAdvertising();
  Serial.println("BLE 广播已启动，等待连接...");

  // 通过 USB 有线串口发送启动提示
  // 电脑端 Python 脚本可据此判断设备已连接并开始采集
  Serial.println("START");
}

// ==================== 主循环 ====================
void loop() {
  // 获取当前时间（微秒），用于时间戳输出和触发间隔控制
  // micros() 在 ESP32-S3 上约 70 分钟溢出一次，实验场景下可忽略
  unsigned long now = micros();

  // 控制两次触发的最小间隔，避免前一次回波干扰下一次测量
  // 若距上次触发不足 MIN_INTERVAL，则跳过本次循环，立即返回
  if (now - lastTriggerTime < MIN_INTERVAL) {
    return;
  }

  // 记录本次触发时刻，供下一轮循环判断间隔
  lastTriggerTime = now;

  // ---------- 发送触发信号 ----------
  // HC-SR04 要求：先拉低 ≥ 2us，再拉高 ≥ 10us，最后拉低
  // 模块检测到 10us 上升沿后自动发送 8 个 40kHz 超声脉冲
  digitalWrite(TRIG_PIN, LOW);       // 先拉低，确保干净的上升沿
  delayMicroseconds(2);              // 保持低电平 ≥ 2us
  digitalWrite(TRIG_PIN, HIGH);      // 拉高，开始触发脉冲
  delayMicroseconds(10);             // 保持高电平 10us（HC-SR04 最低要求）
  digitalWrite(TRIG_PIN, LOW);       // 拉低，结束触发脉冲

  // ---------- 读取回波时间 ----------
  // pulseIn() 测量 ECHO_PIN 保持高电平的时间（微秒）
  // 高电平时间 = 超声波从发射到接收的往返时间
  // 第三个参数 ECHO_TIMEOUT 为超时值，防止无回波时死等导致程序卡住
  // 返回 0 表示超时（无回波）
  unsigned long echoTime = pulseIn(ECHO_PIN, HIGH, ECHO_TIMEOUT);

  // ---------- 数据输出 ----------
  // 仅在有效回波时输出（echoTime > 0），无回波时跳过
  // 这样电脑端可根据时间戳间隔判断丢包情况
  if (echoTime > 0) {
    // 构造数据字符串：时间戳(us),回波时间(us)\n
    // 例："12345678,580\n"
    char buffer[32];
    snprintf(buffer, sizeof(buffer), "%lu,%lu\n", now, echoTime);

    // USB 有线串口输出
    Serial.print(buffer);

    // BLE 串口输出（仅在有客户端连接时发送，避免无连接时的无效操作）
    // pTxCharacteristic->setValue() 设置要发送的数据
    // pTxCharacteristic->notify() 主动推送给已订阅的客户端
    if (deviceConnected) {
      pTxCharacteristic->setValue((uint8_t *)buffer, strlen(buffer));
      pTxCharacteristic->notify();
    }
  }
  // 无回波时（echoTime == 0）不输出任何内容
  // 原因：避免输出无效数据干扰电脑端解析
  // 电脑端可根据连续两条数据的时间戳差值判断是否有丢包
}
