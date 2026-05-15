"""
Install Magisk 数据模型。

Magisk 安装模块专用模型。
通用模型（CommandResult、DeviceInfo）请从 michanger.common 导入。

所有模型均使用 frozen=True 保证不可变性（PEP 557）。

参考：
- https://docs.python.org/3/library/dataclasses.html
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TwrpInfo:
    """TWRP Recovery 版本信息。

    Attributes:
        version: TWRP 版本号（如 "3.6.2_11-0"）
        full_output: twrp --version 的完整输出
    """

    version: str
    full_output: str


@dataclass(frozen=True)
class MagiskInstallResult:
    """Magisk 安装完整结果。

    所有字段来自 pcapng 中 twrp install 命令的输出解析。

    Attributes:
        twrp_version: TWRP 版本号
        magisk_version: Magisk 版本号（如 "30.1"）
        boot_slot: 当前 boot slot（如 "_b"）
        target_image: 目标 boot 镜像路径（如 "/dev/block/by-name/boot_b"）
        platform: 设备平台（如 "arm64-v8a"）
        install_log: 完整安装日志行（不可变元组）
        success: 安装是否成功（基于日志中 "- Done" 判断）
    """

    twrp_version: str
    magisk_version: str
    boot_slot: str
    target_image: str
    platform: str
    install_log: tuple[str, ...]
    success: bool
