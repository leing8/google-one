"""
应用数据清理器。

对应 pcapng 第 3 阶段（pm clear）和第 9 阶段（rm -rf 深度清理）的命令序列。

第 3 阶段（命令 10-32）：
    pm clear <package> — 清理应用数据

第 9 阶段（命令 270-296）：
    270-288: rm -rf 应用数据目录（每包 6 目录）
    289-294: ls -1 /data/app/* → 按输出路径 rm -rf APK 目录
    295:     rm -rf 系统数据路径
    296:     find ... | grep -v 'spblob' | xargs rm -rf

参考：
- https://docs.python.org/3/library/logging.html
"""

from __future__ import annotations

import logging

from michanger.common import AdbExecutor
from .models import DeviceProfile

logger = logging.getLogger(__name__)

# 应用数据目录模板（来自 pcapng 命令 270-288）
_APP_DATA_DIRS: tuple[str, ...] = (
    "/data/data/{pkg}",
    "/data/user_de/0/{pkg}",
    "/data/user/0/{pkg}",
    "/sdcard/Android/data/{pkg}",
    "/data/misc/profiles/ref/{pkg}",
    "/data/misc/profiles/cur/0/{pkg}",
)

# GMS 特殊处理：使用通配符（来自 pcapng 命令 271）
_GMS_DATA_DIRS: tuple[str, ...] = (
    "/data/data/com.google.android.gms/*",
    "/data/user_de/0/com.google.android.gms/*",
    "/data/user/0/com.google.android.gms/*",
    "/sdcard/Android/data/com.google.android.gms/*",
    "/data/misc/profiles/ref/com.google.android.gms/*",
    "/data/misc/profiles/cur/0/com.google.android.gms/*",
)

# 需要在 /data/app/ 下清理的包名（pcapng 命令 289-294）
_DATA_APP_TARGETS: tuple[str, ...] = (
    "com.android.vending",
)


def pm_clear_packages(
    adb: AdbExecutor,
    profile: DeviceProfile,
) -> int:
    """批量执行 pm clear 清理应用数据。

    对应 pcapng 第 3 阶段（命令 10-32）。
    pm clear 失败（Failed）不影响流程，抓包中也有多个失败情况。

    Args:
        adb: ADB 执行器
        profile: 设备配置

    Returns:
        执行的命令数量
    """
    count = 0
    for pkg in profile.pm_clear_packages:
        result = adb.shell(f"pm clear {pkg}")
        status = "Success" if "Success" in result.output else "Failed"
        logger.info("pm clear %s → %s", pkg, status)
        count += 1
    return count


def rm_rf_app_data(
    adb: AdbExecutor,
    profile: DeviceProfile,
) -> int:
    """深度清理应用数据目录。

    对应 pcapng 命令 270-288。
    对每个包名删除 6 个数据目录。
    注意：com.google.android.gms 使用通配符（不删除目录本身，仅内容）。

    Args:
        adb: ADB 执行器
        profile: 设备配置

    Returns:
        执行的命令数量
    """
    count = 0
    for pkg in profile.rm_rf_packages:
        if pkg == "com.google.android.gms":
            # GMS 特殊处理：使用通配符（pcapng 命令 271）
            paths = " ".join(_GMS_DATA_DIRS)
        else:
            paths = " ".join(
                tpl.format(pkg=pkg) for tpl in _APP_DATA_DIRS
            )
        adb.shell(f"rm -rf {paths}")
        logger.debug("rm -rf app data: %s", pkg)
        count += 1
    return count


def cleanup_data_app(adb: AdbExecutor) -> int:
    """清理 /data/app/ 下的特定应用目录。

    严格按 pcapng 命令 289-294 的逻辑：
    1. ls -1 /data/app/* → 获取安装目录列表
    2. 解析输出，找到 com.android.vending 的目录 → rm -rf <dir>/*
    3. ls -1 /data/app/* → 再次列出
    4. 解析输出，找到 com.google.android.gms 的目录 → rm -rf <apk>/*
    5. ls -1 /data/app/* × 2（验证清理结果）

    由于目录名包含随机哈希（如 ~~fB_HPHka0A8kHD2sErlnUA==），
    需要先 ls 再从输出中匹配。

    Args:
        adb: ADB 执行器

    Returns:
        执行的命令数量
    """
    count = 0

    for target in _DATA_APP_TARGETS:
        # Step 1: ls 获取目录列表
        ls_result = adb.shell("ls -1 /data/app/*")
        count += 1

        if not ls_result.success:
            logger.warning("无法列出 /data/app/*: %s", ls_result.output)
            continue

        # Step 2: 从输出中查找包含目标包名的路径
        # pcapng 输出格式如:
        #   /data/app/~~fB_HPHka0A8kHD2sErlnUA==/com.android.vending-Mb...==/
        found_path = ""
        for line in ls_result.output.splitlines():
            stripped = line.strip()
            if target in stripped and stripped.startswith("/data/app/"):
                # 取到包含目标包名的完整路径
                found_path = stripped
                break

        if not found_path:
            # 尝试从子目录列表中查找
            # ls -1 /data/app/* 的输出可能是先列出目录头再列内容
            for line in ls_result.output.splitlines():
                stripped = line.strip()
                if target in stripped:
                    found_path = stripped
                    break

        if found_path:
            adb.shell(f"rm -rf {found_path}/*")
            logger.info("清理 APK 目录: %s", found_path)
            count += 1
        else:
            logger.debug("%s 未在 /data/app/ 中找到", target)

    # pcapng 命令 293-294: 两次额外的 ls 验证
    adb.shell("ls -1 /data/app/*")
    count += 1
    adb.shell("ls -1 /data/app/*")
    count += 1

    return count


def cleanup_system_data(
    adb: AdbExecutor,
    profile: DeviceProfile,
) -> int:
    """清理系统数据目录。

    对应 pcapng 命令 295-296：
    295. rm -rf 大量系统数据路径
    296. find /data/system_de/0/* | grep -v 'spblob' | xargs rm -rf

    Args:
        adb: ADB 执行器
        profile: 设备配置

    Returns:
        执行的命令数量
    """
    count = 0

    # pcapng 命令 295: 批量删除系统数据目录
    paths = " ".join(profile.system_cleanup_paths)
    adb.shell(f"rm -rf {paths}")
    count += 1
    logger.info("系统数据目录已清理")

    # pcapng 命令 296: 清理 /data/system_de/0/（保留 spblob）
    adb.shell(
        "find /data/system_de/0/* | grep -v 'spblob' | xargs rm -rf"
    )
    count += 1
    logger.info("system_de/0 已清理（保留 spblob）")

    return count
