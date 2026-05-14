"""
ADB 命令执行器 — 从 common 包重新导出。

本文件作为向后兼容层，保持 install-magisk 模块内部导入路径不变。
实际实现已迁移至 common.adb_executor。
"""

from common.adb_executor import AdbError, AdbExecutor, list_devices

__all__ = ["AdbError", "AdbExecutor", "list_devices"]
