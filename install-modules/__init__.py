"""
Install Modules — Magisk 模块批量安装模块。

严格按照 6.0-Install Modules.pcapng 抓包还原的命令序列，
通过 Magisk CLI 批量安装模块。

命令序列（10 步）：
    1.  adb shell su -c "id"                    → 验证 root
    2.  adb shell su -c "magisk --remove-modules -n" → 移除旧模块
    3.  adb shell su -c "rm -rf /data/adb/modules/*" → 清空模块目录
    4.  adb shell rm -rf /sdcard/modules        → 清理临时目录
    5-6. adb push modules/ /sdcard/modules/     → 推送模块文件
    7.  adb shell ls -1 /sdcard/modules/*.zip   → 验证推送
    8.  adb shell su -c "magisk --install-module ..." × N → 安装
    9.  adb shell rm -rf /sdcard/modules        → 清理
    10. adb reboot                              → 重启

公共 API：
    - install_modules(): 执行完整模块安装流程
    - InstallModulesResult: 整体安装结果数据类
    - ModuleInstallResult: 单模块安装结果数据类
    - ModuleInfo: 模块信息数据类
"""

from common.adb_executor import AdbError, AdbExecutor, list_devices
from common.models import CommandResult, DeviceInfo

from .install_modules import install_modules
from .models import InstallModulesResult, ModuleInfo, ModuleInstallResult

__all__ = [
    "AdbError",
    "AdbExecutor",
    "CommandResult",
    "DeviceInfo",
    "InstallModulesResult",
    "ModuleInfo",
    "ModuleInstallResult",
    "install_modules",
    "list_devices",
]
