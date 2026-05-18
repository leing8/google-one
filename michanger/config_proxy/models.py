"""
Config Proxy — 数据模型。

所有模型均使用 frozen=True 保证不可变性（PEP 557）。

参考：
- https://docs.python.org/3/library/dataclasses.html
- 16.0/16.1 pcapng 双份抓包对比分析
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConfigProxyResult:
    """Config Proxy 执行结果。

    Attributes:
        serial: 设备序列号
        previous_proxy: 设置前的代理值（可能为 "null" 或 "host:port"）
        new_proxy: 设置后的代理值（"host:port" 格式）
        set_success: settings put 是否成功
        success: 整体是否成功
        commands_executed: 执行的命令数量
    """

    serial: str
    previous_proxy: str = ""
    new_proxy: str = ""
    set_success: bool = False
    success: bool = False
    commands_executed: int = 0
