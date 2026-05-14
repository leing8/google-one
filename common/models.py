"""
通用数据模型 — ADB 命令执行结果与设备信息。

所有模型均使用 frozen=True 保证不可变性（PEP 557）。
由各功能模块（install-magisk、install-modules 等）共享。

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
