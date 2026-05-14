"""
Install Magisk 数据模型。

所有模型均使用 frozen=True 保证不可变性（PEP 557）。

参考：
- https://docs.python.org/3/library/dataclasses.html
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandResult:
    """单条 ADB 命令的执行结果。

    Attributes:
        command: 执行的命令字符串
        stdout: 标准输出（已 strip）
        stderr: 标准错误（已 strip）
        returncode: 进程返回码
    """

    command: str
    stdout: str
    stderr: str
    returncode: int

    @property
    def success(self) -> bool:
        """命令是否成功执行（返回码为 0）。"""
        return self.returncode == 0

    @property
    def output(self) -> str:
        """返回 stdout（优先）或 stderr 的内容。"""
        return self.stdout if self.stdout else self.stderr


@dataclass(frozen=True)
class DeviceInfo:
    """已连接设备的基本信息（来自 adb devices）。

    Attributes:
        serial: 设备序列号
        state: 设备状态（device / offline / unauthorized / recovery 等）
    """

    serial: str
    state: str

    @property
    def is_online(self) -> bool:
        """设备是否在线且已授权。"""
        return self.state == "device"

    @property
    def is_recovery(self) -> bool:
        """设备是否处于 Recovery 模式。"""
        return self.state == "recovery"


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
