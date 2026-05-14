"""
通用共享模块 — ADB 命令执行器与数据模型。

由各功能模块（install-magisk、install-modules 等）共享。

公共 API：
    - AdbExecutor: ADB 命令执行器（支持 shell, shell_su, push, reboot 等）
    - AdbError: ADB 错误异常
    - CommandResult: 命令执行结果数据类
    - DeviceInfo: 设备信息数据类
    - list_devices(): 列出已连接 ADB 设备
"""

from .adb_executor import AdbError, AdbExecutor, list_devices
from .models import CommandResult, DeviceInfo

__all__ = [
    "AdbError",
    "AdbExecutor",
    "CommandResult",
    "DeviceInfo",
    "list_devices",
]
