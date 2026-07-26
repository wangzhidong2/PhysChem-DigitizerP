# -*- coding: utf-8 -*-
"""core/ble_thread.py — BLE 通信线程（基于 bleak）

连接 ESP32-S3 的 Nordic NUS 服务，按行解析 BLE 通知数据并以信号形式发射。
bleak 为可选依赖：未安装时 BLE_AVAILABLE=False，相关方法会优雅降级。
"""

import asyncio

from PySide6.QtCore import QThread, Signal


# Nordic UART Service (NUS) UUID
BLE_NUS_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
BLE_NUS_TX_UUID      = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
BLE_NUS_RX_UUID      = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"

try:
    from bleak import BleakClient, BleakScanner
    BLE_AVAILABLE = True
except ImportError:
    BLE_AVAILABLE = False


class BLESerialThread(QThread):
    """BLE 串口通信线程。

    Signals:
        data_received(str): 一行数据，错误为 "ERROR:<msg>"，连接成功为 "START"。
        connection_status(str): 连接状态信号，"connected" / "disconnected"。
    """
    data_received = Signal(str)
    connection_status = Signal(str)

    def __init__(self, device_address, device_name=""):
        super().__init__()
        self.device_address = device_address
        self.device_name = device_name
        self.running = False
        self._buffer = ""
        self._client = None

    def run(self):
        if not BLE_AVAILABLE:
            self.data_received.emit("ERROR:bleak 库未安装，请运行 pip install bleak")
            return

        self.running = True
        try:
            asyncio.run(self._ble_loop())
        except asyncio.CancelledError:
            pass
        except Exception as e:
            error_msg = str(e)
            low = error_msg.lower()
            if "not found" in low or "could not find" in low:
                self.data_received.emit("ERROR:设备未找到，请确保 ESP32-S3 已上电并配对")
            elif "timeout" in low:
                self.data_received.emit("ERROR:连接超时，请检查设备是否在范围内")
            else:
                self.data_received.emit(f"ERROR:BLE 连接失败: {error_msg}")

    async def _ble_loop(self):
        try:
            self._client = BleakClient(
                self.device_address,
                timeout=10.0,
                disconnected_callback=self._on_disconnected
            )
            await self._client.connect()

            if self._client.is_connected:
                self.connection_status.emit("connected")
                self.data_received.emit("START")
            else:
                self.data_received.emit("ERROR:连接建立失败")
                return

            try:
                await self._client.start_notify(BLE_NUS_TX_UUID, self._notification_handler)
            except Exception as e:
                self.data_received.emit(f"ERROR:无法订阅数据通知: {e}")
                return

            while self.running and self._client.is_connected:
                await asyncio.sleep(0.05)

            if self._client.is_connected:
                try:
                    await self._client.stop_notify(BLE_NUS_TX_UUID)
                except Exception:
                    pass
                try:
                    await self._client.disconnect()
                except Exception:
                    pass
        except Exception as e:
            raise e

    def _notification_handler(self, sender, data):
        try:
            text = data.decode('utf-8', errors='ignore')
            self._buffer += text
            while '\n' in self._buffer:
                line, self._buffer = self._buffer.split('\n', 1)
                line = line.strip()
                if line:
                    self.data_received.emit(line)
        except Exception as e:
            print(f"BLE 数据处理错误: {e}")

    def _on_disconnected(self, client):
        if self.running:
            self.data_received.emit("ERROR:设备意外断开连接")
            self.running = False

    def stop(self):
        self.running = False
        if self._client and self._client.is_connected:
            try:
                asyncio.run(self._client.disconnect())
            except Exception:
                pass


def scan_ble_devices():
    """扫描附近的 BLE 设备，返回 [(名称, 地址), ...]。"""
    if not BLE_AVAILABLE:
        return []
    try:
        devices = asyncio.run(BleakScanner.discover(timeout=5.0))
        result = []
        for d in devices:
            name = d.name or "未知设备"
            result.append((name, d.address))
        return sorted(result, key=lambda x: x[0])
    except Exception as e:
        print(f"BLE 扫描错误: {e}")
        return []
