"""
应用数据清理器。

对应 pcapng 第 3 阶段（pm clear）和第 9 阶段（rm -rf 深度清理）。

统一清理配置：cleanup_packages 列表中的每个包会自动执行：
    1. pm clear <pkg>                          （阶段 3）
    2. rm -rf 6 个数据目录                      （阶段 9）
    3. rm -rf /data/app/~~hash/<pkg>-hash/*     （阶段 9，路径通过 ls 动态发现）

阶段 3 执行流程（来自 pcapng 命令 10-32）：
    - pm clear × cleanup_packages（每个包）
    - pm clear × finalize_clear_packages（gms/gsf/vending 再次清理）

阶段 9 执行流程（来自 pcapng 命令 270-296）：
    270-288: rm -rf 6 个数据目录（每个 cleanup_packages 包）
    289-294: ls -1 /data/app/* → 解析路径 → rm -rf 匹配的包 APK 目录
    295:     rm -rf 系统数据路径
    296:     find ... | grep -v 'spblob' | xargs rm -rf

参考：
- https://docs.python.org/3/library/logging.html
"""

from __future__ import annotations

import logging

from michanger.common import AdbExecutor
from michanger.common import DeviceProfile

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


def pm_clear_packages(
    adb: AdbExecutor,
    profile: DeviceProfile,
) -> int:
    """批量执行 pm clear 清理应用数据。

    对应 pcapng 第 3 阶段（命令 10-32）。
    执行顺序：cleanup_packages → finalize_clear_packages。
    pm clear 失败（Failed）不影响流程（抓包中也有多个失败情况）。

    Args:
        adb: ADB 执行器
        profile: 设备配置

    Returns:
        执行的命令数量
    """
    count = 0

    # 清理 cleanup_packages 中的所有包
    for pkg in profile.cleanup_packages:
        result = adb.shell(f"pm clear {pkg}")
        status = "Success" if "Success" in result.output else "Failed"
        logger.info("pm clear %s → %s", pkg, status)
        count += 1

    # 清理 extra_cleanup_packages 中的额外包
    for pkg in profile.extra_cleanup_packages:
        result = adb.shell(f"pm clear {pkg}")
        status = "Success" if "Success" in result.output else "Failed"
        logger.info("pm clear (extra) %s → %s", pkg, status)
        count += 1

    # 最终阶段：再次清理 gms/gsf/vending（pcapng 命令 30-32）
    for pkg in profile.finalize_clear_packages:
        result = adb.shell(f"pm clear {pkg}")
        status = "Success" if "Success" in result.output else "Failed"
        logger.info("pm clear (finalize) %s → %s", pkg, status)
        count += 1

    return count


def rm_rf_app_data(
    adb: AdbExecutor,
    profile: DeviceProfile,
) -> int:
    """深度清理应用数据目录。

    对应 pcapng 命令 270-288。
    对 cleanup_packages 中每个包删除 6 个数据目录。
    注意：com.google.android.gms 使用通配符（不删除目录本身，仅内容）。

    Args:
        adb: ADB 执行器
        profile: 设备配置

    Returns:
        执行的命令数量
    """
    count = 0
    for pkg in profile.cleanup_packages:
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


def cleanup_data_app(adb: AdbExecutor, profile: DeviceProfile) -> int:
    """清理 /data/app/ 下的特定应用 APK 目录。

    严格按 pcapng 命令 299-305 的逻辑：
    1. ls -1 /data/app/* → 查找 cleanup_packages 中实际存在的包
    2. 对每个找到的包执行: rm -rf → ls -1（验证）
    3. 最后一次 ls 作为最终验证

    抓包中只清理了 cleanup_packages 中实际存在于 /data/app/ 的包
    （如 vending、gms、ims），其他不存在的包自动跳过。

    Args:
        adb: ADB 执行器
        profile: 设备配置

    Returns:
        执行的命令数量
    """
    count = 0

    # 第一次 ls — 获取 /data/app/ 下的所有内容
    ls_result = adb.shell("ls -1 /data/app/*")
    count += 1

    if not ls_result.success:
        logger.warning("无法列出 /data/app/*: %s", ls_result.output)
        return count

    output_text = ls_result.output

    # 查找 cleanup_packages 中实际存在于 /data/app/ 的包
    packages_to_clean: list[str] = []
    for pkg in profile.cleanup_packages:
        full_path = _find_app_path(output_text, pkg)
        if full_path:
            packages_to_clean.append(full_path)
            logger.debug("在 /data/app/ 中找到: %s → %s", pkg, full_path)

    # 交替执行 rm-rf → ls（与抓包一致）
    for app_path in packages_to_clean:
        adb.shell(f"rm -rf {app_path}/*")
        count += 1
        logger.info("清理 APK 目录: %s", app_path)

        # 每次清理后 ls 验证
        ls_result = adb.shell("ls -1 /data/app/*")
        count += 1

    # 如果没有需要清理的包，也做一次最终 ls 验证
    if not packages_to_clean:
        adb.shell("ls -1 /data/app/*")
        count += 1

    return count


def _find_app_path(ls_output: str, package_name: str) -> str:
    """从 ls -1 /data/app/* 输出中找到包的完整安装路径。

    ls 输出格式为：
        /data/app/~~hash==:
        com.pkg-hash==

    Returns:
        完整路径（如 /data/app/~~hash==/com.pkg-hash==）或空字符串
    """
    lines = ls_output.splitlines()
    current_parent = ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("/data/app/") and stripped.endswith(":"):
            current_parent = stripped.rstrip(":")
        elif package_name in stripped and current_parent:
            return f"{current_parent}/{stripped}"
    return ""


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
