"""install_modules — 安装 Magisk 模块的独立模块.

公共 API:
    install_modules()      → 执行完整安装流程
    ModulesInstallResult   → 安装结果数据模型
    ModuleInstallDetail    → 单个模块安装详情
    AdbExecutor            → ADB 命令执行器
    AdbError               → ADB 错误异常
"""

from .adb_executor import AdbError, AdbExecutor
from .core import install_modules, main
from .models import ModuleInstallDetail, ModulesInstallResult

__all__ = [
    "install_modules",
    "main",
    "AdbExecutor",
    "AdbError",
    "ModulesInstallResult",
    "ModuleInstallDetail",
]
