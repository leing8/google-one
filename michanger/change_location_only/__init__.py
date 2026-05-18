"""
Change Location Only — 位置信息变更模块。

严格按照 15.0-Change Location Only.pcapng 抓包还原的命令序列，
清除位置历史、在 TWRP Recovery 中替换 mi_info.json、深度清理位置数据并重启。

与 random_change_sim_info（14.0 pcapng）的差异：
    - 新增 Phase 1: pm clear 位置历史包（预清理，可能 "Failed"）
    - 新增 Phase 6: rm -rf 6 个位置历史数据目录（TWRP 中深度清理）

命令序列（35 步 / 8 阶段）：
    1. pm clear 位置历史包（Android 正常模式）
    2. 重启进入 Recovery
    3. TWRP 验证 + 挂载 7 分区 + remount rw
    4. 路径探测 + 读取当前 mi_info.json
    5. mi_info.json 替换（rm -rf → printf 写入新数据）
    6. 位置历史数据目录深度清理（rm -rf 6 目录）
    7. 正常重启
    8. pm enable vending + pm list packages -3

公共 API：
    - change_location_only(): 执行完整位置信息变更流程
    - ChangeLocationResult: 执行结果数据类
    - PhaseResult: 单阶段结果数据类
    - LOCATION_HISTORY_PACKAGE: 位置历史包名常量
    - LOCATION_HISTORY_DATA_PATHS: 位置历史数据目录常量
"""

from .change_location_only import (
    LOCATION_HISTORY_DATA_PATHS,
    LOCATION_HISTORY_PACKAGE,
    change_location_only,
)
from .models import ChangeLocationResult, PhaseResult

__all__ = [
    "LOCATION_HISTORY_DATA_PATHS",
    "LOCATION_HISTORY_PACKAGE",
    "ChangeLocationResult",
    "PhaseResult",
    "change_location_only",
]
