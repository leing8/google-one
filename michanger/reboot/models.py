"""
Reboot 数据模型 — 设备重启操作结果。

所有模型均使用 frozen=True 保证不可变性（PEP 557）。

参考：
- https://docs.python.org/3/library/dataclasses.html
- 9.0-Reboot.pcapng 抓包分析：仅 1 条 ADB reboot 命令 + OKAY 响应
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RebootResult:
    """设备重启操作的执行结果。

    对应 9.0-Reboot.pcapng 中唯一的 ADB 交互：
        Frame 7-8:  OPEN reboot:    → 打开重启服务通道
        Frame 9-10: "reboot:\\0"    → 发送重启命令载荷
        Frame 11-12: OKAY           → 设备确认开始重启

    Attributes:
        serial: 设备序列号
        success: 重启命令是否成功发送（OKAY 响应）
        command: 执行的完整命令字符串
        stdout: 标准输出（已 strip）
        stderr: 标准错误（已 strip）
        returncode: 进程返回码
    """

    serial: str
    success: bool
    command: str
    stdout: str
    stderr: str
    returncode: int
