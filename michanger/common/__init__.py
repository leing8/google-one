"""
通用共享模块 — ADB 执行器、数据模型、CLI 工具、TWRP 操作与设备配置。

由各功能模块（install_magisk、install_modules、load_device 等）共享。

公共 API：
    - AdbExecutor: ADB 命令执行器（支持 shell, shell_su, push, reboot 等）
    - AdbError: ADB 错误异常
    - CommandResult: 命令执行结果数据类
    - DeviceInfo: 设备信息数据类
    - DeviceProfile: 目标设备完整配置数据类
    - list_devices(): 列出已连接 ADB 设备
    - setup_logging(): 配置日志系统
    - auto_detect_serial(): 自动检测设备序列号
    - load_profile(): 加载设备配置 + 随机化动态字段
    - TWRP_MOUNT_PARTITIONS: TWRP 挂载分区常量
    - REMOUNT_RW_PARTITIONS: remount rw 分区常量
    - MI_DIR_CANDIDATES: mi_info 目录探测候选路径
    - mount_all_partitions(): 挂载所有分区 + remount rw
    - detect_mi_dir(): 探测 mi_info 目录路径
"""

from .adb_executor import AdbError, AdbExecutor, list_devices
from .cli import auto_detect_serial, setup_logging
from .device_profile import DeviceProfile, load_profile
from .models import CommandResult, DeviceInfo
from .twrp import (
    MI_DIR_CANDIDATES,
    REMOUNT_RW_PARTITIONS,
    TWRP_MOUNT_PARTITIONS,
    detect_mi_dir,
    mount_all_partitions,
)

__all__ = [
    "AdbError",
    "AdbExecutor",
    "CommandResult",
    "DeviceInfo",
    "DeviceProfile",
    "MI_DIR_CANDIDATES",
    "REMOUNT_RW_PARTITIONS",
    "TWRP_MOUNT_PARTITIONS",
    "auto_detect_serial",
    "detect_mi_dir",
    "list_devices",
    "load_profile",
    "mount_all_partitions",
    "setup_logging",
]

