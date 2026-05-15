"""
Load Device — Android 设备探测模块。

严格按照 4.0-Load Device.pcapng 抓包还原的命令序列，
探测设备的 MiChanger ROM 状态、系统属性和第三方应用列表。

公共 API：
    - load_device(): 执行单台设备探测
    - load_all_devices(): 列出并探测所有已连接设备
    - LoadDeviceResult: 探测结果数据类
    - DeviceProperties: 设备属性数据类
    - MiChangerInfo: MiChanger ROM 信息数据类
"""

from .load_device import load_all_devices, load_device
from .models import DeviceProperties, LoadDeviceResult, MiChangerInfo

__all__ = [
    "DeviceProperties",
    "LoadDeviceResult",
    "MiChangerInfo",
    "load_all_devices",
    "load_device",
]
