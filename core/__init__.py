# -*- coding: utf-8 -*-
"""core 包 — PhysChem-DigitizerP 公共模块

提供各传感器 Backend 共享的基础能力：
- 配置管理（load/save_sensor_config）
- 串口通信线程（SerialThread + list_serial_ports）
- BLE 通信线程（BLESerialThread + scan_ble_devices，bleak 可选）
"""

from .config import (
    CONFIG_FILENAME,
    load_sensor_config,
    save_sensor_config,
)
from .serial_thread import SerialThread, list_serial_ports
from .ble_thread import (
    BLE_AVAILABLE,
    BLE_NUS_RX_UUID,
    BLE_NUS_SERVICE_UUID,
    BLE_NUS_TX_UUID,
    BLESerialThread,
    scan_ble_devices,
)

__all__ = [
    "CONFIG_FILENAME",
    "load_sensor_config",
    "save_sensor_config",
    "SerialThread",
    "list_serial_ports",
    "BLE_AVAILABLE",
    "BLE_NUS_SERVICE_UUID",
    "BLE_NUS_TX_UUID",
    "BLE_NUS_RX_UUID",
    "BLESerialThread",
    "scan_ble_devices",
]
