"""update_integrity_fix — 更新 Play Integrity 修复的独立模块.

公共 API:
    update_integrity_fix() → 执行完整更新流程
    IntegrityFixResult     → 更新结果数据模型
    AdbExecutor            → ADB 命令执行器
    AdbError               → ADB 错误异常
"""

from .adb_executor import AdbError, AdbExecutor
from .core import main, update_integrity_fix
from .models import IntegrityFixResult

__all__ = [
    "update_integrity_fix",
    "main",
    "AdbExecutor",
    "AdbError",
    "IntegrityFixResult",
]
