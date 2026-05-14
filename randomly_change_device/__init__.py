"""randomly_change_device — 设备信息随机化的独立模块.

公共 API:
    randomly_change_device() → 执行完整随机化流程
    RandomDeviceResult       → 执行结果数据模型
    AdbExecutor              → ADB 命令执行器
    AdbError                 → ADB 错误异常
"""

from .adb_executor import AdbError, AdbExecutor
from .core import main, randomly_change_device
from .models import RandomDeviceResult

__all__ = [
    "randomly_change_device",
    "main",
    "AdbExecutor",
    "AdbError",
    "RandomDeviceResult",
]
