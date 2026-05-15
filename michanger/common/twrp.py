"""
TWRP Recovery 通用工具 — 分区挂载与系统路径探测。

从各模块（wipe_packages_reboot、randomly_change_device、random_change_sim_info）
中提取的共享 TWRP 操作逻辑。

三份抓包确认的分区列表和挂载顺序完全一致：
    - twrp mount: /system, /system_ext, /vendor, /product, /odm, /persist, /firmware
    - remount rw: /system_root, /system_ext, /vendor, /product, /odm, /persist, /firmware

部分分区（/odm, /firmware）可能不存在于目标设备 — 这是正常行为，不影响流程。

参考：
- https://docs.python.org/3/library/logging.html
"""

from __future__ import annotations

import logging

from .adb_executor import AdbExecutor

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# 分区常量（多份抓包验证完全一致）
# ------------------------------------------------------------------

# TWRP 挂载的分区列表（twrp mount 命令的参数）
TWRP_MOUNT_PARTITIONS: tuple[str, ...] = (
    "/system",
    "/system_ext",
    "/vendor",
    "/product",
    "/odm",
    "/persist",
    "/firmware",
)

# 重新挂载为 rw 的分区列表（mount -o remount,rw 命令的参数）
# 注意 /system → /system_root（TWRP 将 system 挂载到 system_root）
REMOUNT_RW_PARTITIONS: tuple[str, ...] = (
    "/system_root",
    "/system_ext",
    "/vendor",
    "/product",
    "/odm",
    "/persist",
    "/firmware",
)

# mi_info 目录探测候选路径（按 pcapng 中的探测顺序）
MI_DIR_CANDIDATES: tuple[str, ...] = (
    "/system/etc/mi",
    "/system/system/etc/mi",
    "/system_root/system/etc/mi",
)


# ------------------------------------------------------------------
# 公共函数
# ------------------------------------------------------------------


def mount_all_partitions(adb: AdbExecutor) -> int:
    """在 TWRP Recovery 中挂载所有分区并 remount 为 rw。

    执行步骤（与 pcapng 完全一致）：
    1. twrp --version — 验证 TWRP 可用
    2. twrp mount × 7 — 挂载分区
    3. mount -o remount,rw × 7 — 重新挂载为读写

    部分分区挂载失败（Unable to find partition）是正常行为，不影响流程。

    Args:
        adb: ADB 执行器（设备须处于 Recovery 模式）

    Returns:
        执行的命令数量
    """
    count = 0

    # 验证 TWRP 版本
    twrp_ver = adb.shell("twrp --version")
    count += 1
    logger.info("TWRP 版本: %s", twrp_ver.output.strip())

    # 挂载分区
    for partition in TWRP_MOUNT_PARTITIONS:
        result = adb.shell(f"twrp mount {partition}")
        count += 1
        if "Unable to find partition" in result.output:
            logger.debug("分区不存在（正常）: %s", partition)
        else:
            logger.info("已挂载: %s", partition)

    # 重新挂载为 rw
    for partition in REMOUNT_RW_PARTITIONS:
        result = adb.shell(f"mount -o remount,rw {partition}")
        count += 1
        if result.success:
            logger.info("已 remount rw: %s", partition)
        else:
            logger.debug("remount rw 失败（可能正常）: %s", partition)

    return count


def detect_mi_dir(adb: AdbExecutor) -> tuple[str, int]:
    """探测 mi_info 目录的实际路径。

    按 pcapng 中的探测顺序（Step 19-21）依次 ls 三个候选路径，
    返回第一个存在的路径。

    Args:
        adb: ADB 执行器

    Returns:
        (mi_dir_path, commands_executed) 元组。
        mi_dir_path 为空字符串表示未找到。
    """
    count = 0
    mi_dir = ""

    for candidate in MI_DIR_CANDIDATES:
        result = adb.shell(f"ls {candidate}")
        count += 1

        if result.success and "No such file" not in result.output:
            mi_dir = candidate
            logger.info("mi 目录已找到: %s", mi_dir)
            break
        logger.debug("mi 目录不存在: %s", candidate)

    return mi_dir, count
