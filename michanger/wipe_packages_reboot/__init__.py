"""
Wipe Packages & Reboot — 包清理与重启模块。

严格按照 11.0-Wipe Packages & Reboot.pcapng 抓包还原的命令序列，
执行包数据清理、Recovery 模式深度清理、packages.xml 修改和设备重启。

公共 API：
    - wipe_packages_and_reboot(): 执行完整流程
    - load_config(): 从 JSON 配置文件加载 WipeConfig
    - WipeConfig: 清理配置
    - WipeResult: 执行结果
    - PhaseResult: 单阶段结果
"""

from .models import PhaseResult, WipeConfig, WipeResult
from .wipe_packages_reboot import load_config, wipe_packages_and_reboot

__all__ = [
    "PhaseResult",
    "WipeConfig",
    "WipeResult",
    "load_config",
    "wipe_packages_and_reboot",
]
