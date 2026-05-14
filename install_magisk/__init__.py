"""install_magisk — 安装 Magisk 并 Root 手机的独立模块.

公共 API:
    install_magisk()       → 执行完整安装流程
    MagiskInstallResult    → 安装结果数据模型
    AdbExecutor            → ADB 命令执行器
    AdbError               → ADB 错误异常
"""

from .adb_executor import AdbError, AdbExecutor
from .core import install_magisk, main
from .models import MagiskInstallResult

__all__ = [
    "install_magisk",
    "main",
    "AdbExecutor",
    "AdbError",
    "MagiskInstallResult",
]
