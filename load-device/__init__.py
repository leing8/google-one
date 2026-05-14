"""
Load Device — Android 设备探测模块。

严格按照 4.0-Load Device.pcapng 抓包还原的命令序列，
探测设备的 MiChanger ROM 状态、系统属性和第三方应用列表。

公共 API：
    - list_devices(): 列出已连接 ADB 设备
    - load_device(): 执行单台设备探测
    - load_all_devices(): 列出并探测所有已连接设备
    - DeviceInfo: 已连接设备信息数据类
    - LoadDeviceResult: 探测结果数据类
    - DeviceProperties: 设备属性数据类
    - MiChangerInfo: MiChanger ROM 信息数据类
    - AdbExecutor: ADB 命令执行器
    - AdbError: ADB 错误异常
"""

from .adb_executor import AdbError, AdbExecutor, list_devices
from .load_device import load_all_devices, load_device
from .models import (
    CommandResult,
    DeviceInfo,
    DeviceProperties,
    LoadDeviceResult,
    MiChangerInfo,
)

__all__ = [
    "AdbError",
    "AdbExecutor",
    "CommandResult",
    "DeviceInfo",
    "DeviceProperties",
    "LoadDeviceResult",
    "MiChangerInfo",
    "list_devices",
    "load_all_devices",
    "load_device",
]
