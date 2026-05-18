"""
ONOFF Screen — 数据模型。

所有模型均使用 frozen=True 保证不可变性（PEP 557）。

参考：
- https://docs.python.org/3/library/dataclasses.html
- 19.0/19.1 pcapng 双份抓包对比分析
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OnOffScreenResult:
    """ONOFF Screen 执行结果。

    Attributes:
        serial: 设备序列号
        keyevent_success: input keyevent 是否成功
        success: 整体是否成功
        commands_executed: 执行的命令数量
    """

    serial: str
    keyevent_success: bool = False
    success: bool = False
    commands_executed: int = 0
