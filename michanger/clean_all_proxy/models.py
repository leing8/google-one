"""
Clean All Proxy — 数据模型。

所有模型均使用 frozen=True 保证不可变性（PEP 557）。

参考：
- https://docs.python.org/3/library/dataclasses.html
- 17.0-Clean All Proxy.pcapng 抓包分析
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CleanProxyResult:
    """Clean All Proxy 执行结果。

    Attributes:
        serial: 设备序列号
        clean_success: settings put :0 是否成功
        success: 整体是否成功
        commands_executed: 执行的命令数量
    """

    serial: str
    clean_success: bool = False
    success: bool = False
    commands_executed: int = 0
