"""
Clear Google Play Store — 数据模型。

所有模型均使用 frozen=True 保证不可变性（PEP 557）。

参考：
- https://docs.python.org/3/library/dataclasses.html
- 18.0-Clear Google Play Store.pcapng 抓包分析
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClearPlayStoreResult:
    """Clear Google Play Store 执行结果。

    Attributes:
        serial: 设备序列号
        pm_clear_output: pm clear 的输出（如 "Success"）
        clear_success: pm clear 是否成功
        success: 整体是否成功
        commands_executed: 执行的命令数量
    """

    serial: str
    pm_clear_output: str = ""
    clear_success: bool = False
    success: bool = False
    commands_executed: int = 0
