"""
Random & Change SIM Info Only — SIM 信息随机化模块。

严格按照 14.0-Random & Change SIM Info Only.pcapng 抓包还原的命令序列，
在 TWRP Recovery 中替换 mi_info.json 并重启。

此功能是 randomly_change_device（7.0 pcapng, 333 命令/11 阶段）的精简子集。

命令序列（34 步 / 6 阶段）：
    1. 重启进入 Recovery
    2. TWRP 验证 + 挂载 7 分区 + remount rw
    3. 路径探测 + 读取当前 mi_info.json
    4. mi_info.json 替换（rm -rf → printf 写入新数据）
    5. 正常重启
    6. pm enable vending + pm list packages -3

公共 API：
    - random_change_sim_info(): 执行完整 SIM 信息随机化流程
    - ChangeSIMResult: 执行结果数据类
    - PhaseResult: 单阶段结果数据类
"""

from .models import ChangeSIMResult, PhaseResult
from .random_change_sim_info import random_change_sim_info

__all__ = [
    "ChangeSIMResult",
    "PhaseResult",
    "random_change_sim_info",
]
