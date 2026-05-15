"""
通用共享模块 — ADB 命令执行器、数据模型与 CLI 工具。

由各功能模块（install_magisk、install_modules、load_device）共享。

公共 API：
    - AdbExecutor: ADB 命令执行器（支持 shell, shell_su, push, reboot 等）
    - AdbError: ADB 错误异常
    - CommandResult: 命令执行结果数据类
    - DeviceInfo: 设备信息数据类
    - list_devices(): 列出已连接 ADB 设备
    - setup_logging(): 配置日志系统
    - auto_detect_serial(): 自动检测设备序列号
"""

from .adb_executor import AdbError, AdbExecutor, list_devices
from .cli import auto_detect_serial, setup_logging
from .models import CommandResult, DeviceInfo

__all__ = [
    "AdbError",
    "AdbExecutor",
    "CommandResult",
    "DeviceInfo",
    "auto_detect_serial",
    "list_devices",
    "setup_logging",
]
