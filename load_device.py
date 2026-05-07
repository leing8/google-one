"""Load Device — 加载设备信息.

严格按照 WiresharkLog/4.0-Load Device.pcapng 抓包日志中的 ADB 命令序列
一比一实现设备信息加载功能。

命令序列（9 步）：
    1. shell:cat /system/bin/mi           → 读取 ROM 版本
    2. shell:ls /system/etc/mi            → 检查路径是否存在
    3. shell:ls /system/system/etc/mi     → 检查路径是否存在
    4. shell:ls /system_root/system/etc/mi → 检查路径是否存在
    5. shell:ls /data/mi                  → 检查路径是否存在
    6. shell:getprop ro.product.brand     → 读取设备品牌
    7. shell:getprop ro.product.model     → 读取设备型号
    8. shell:getprop ro.build.version.release → 读取 Android 版本
    9. shell:pm list packages -3          → 列出第三方安装包
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from adb_executor import AdbError, AdbExecutor
from models import ConfigPaths, DeviceInfo, RomVersion

logger = logging.getLogger(__name__)

# ── 配置路径探测顺序（严格按照抓包日志） ────────────────────────────

_CONFIG_PATHS: tuple[str, ...] = (
    "/system/etc/mi",
    "/system/system/etc/mi",
    "/system_root/system/etc/mi",
    "/data/mi",
)


# ── Step 1: 读取 ROM 版本 ──────────────────────────────────────────

def _read_rom_version(executor: AdbExecutor) -> RomVersion:
    """步骤 1: shell:cat /system/bin/mi

    读取 ROM 配置文件内容。文件格式为原始键值对文本，
    严格按照抓包日志保留原始内容不做解析。

    返回:
        包含原始内容和查找状态的 RomVersion。
    """
    logger.info("步骤 1: cat /system/bin/mi")

    result = executor.run_shell("cat /system/bin/mi")

    if result.success and result.stdout:
        logger.info("  ROM 版本: %s", result.stdout)
        return RomVersion(raw=result.stdout, found=True)

    logger.warning("  未找到 ROM 版本文件或文件为空")
    return RomVersion(raw="", found=False)


# ── Step 2-5: 配置路径探测 ──────────────────────────────────────────

def _probe_config_paths(executor: AdbExecutor) -> ConfigPaths:
    """步骤 2-5: ls /system/etc/mi, ls /system/system/etc/mi, 等等。

    依次检查 4 个可能的 mi 配置目录路径。
    严格按照抓包日志中的顺序和判断逻辑：
    - ls 成功（returncode=0）→ 路径存在
    - ls 失败（"No such file or directory"）→ 路径不存在

    返回:
        包含存在标志和第一个找到的路径的 ConfigPaths。
    """
    results: list[bool] = []
    found_path: str | None = None

    for i, path in enumerate(_CONFIG_PATHS):
        step_num = i + 2
        logger.info("步骤 %d: ls %s", step_num, path)

        result = executor.run_shell(f"ls {path}")

        exists = result.success and "No such file or directory" not in result.stdout
        results.append(exists)

        if exists:
            logger.info("  已找到: %s", path)
            if found_path is None:
                found_path = path
        else:
            logger.info("  未找到: %s", path)

    return ConfigPaths(
        system_etc=results[0],
        system_system_etc=results[1],
        system_root_system_etc=results[2],
        data=results[3],
        found_path=found_path,
    )


# ── Step 6: 读取设备品牌 ───────────────────────────────────────────

def _read_brand(executor: AdbExecutor) -> str:
    """步骤 6: shell:getprop ro.product.brand

    返回:
        设备品牌字符串（例如 "google"）。
    """
    logger.info("步骤 6: getprop ro.product.brand")

    result = executor.run_shell("getprop ro.product.brand")
    brand = result.stdout if result.success else ""

    logger.info("  品牌: %s", brand)
    return brand


# ── Step 7: 读取设备型号 ───────────────────────────────────────────

def _read_model(executor: AdbExecutor) -> str:
    """步骤 7: shell:getprop ro.product.model

    返回:
        设备型号字符串（例如 "Pixel 4 XL"）。
    """
    logger.info("步骤 7: getprop ro.product.model")

    result = executor.run_shell("getprop ro.product.model")
    model = result.stdout if result.success else ""

    logger.info("  型号: %s", model)
    return model


# ── Step 8: 读取 Android 版本 ──────────────────────────────────────

def _read_android_version(executor: AdbExecutor) -> str:
    """步骤 8: shell:getprop ro.build.version.release

    返回:
        Android 版本字符串（例如 "11"）。
    """
    logger.info("步骤 8: getprop ro.build.version.release")

    result = executor.run_shell("getprop ro.build.version.release")
    version = result.stdout if result.success else ""

    logger.info("  Android 版本: %s", version)
    return version


# ── Step 9: 列出第三方安装包 ───────────────────────────────────────

def _list_third_party_packages(executor: AdbExecutor) -> tuple[str, ...]:
    """步骤 9: shell:pm list packages -3

    列出第三方安装包。返回格式为 "package:<包名>" 的多行文本。
    严格按照抓包日志：如果没有第三方包，返回空元组。

    返回:
        包名元组（不包含 "package:" 前缀）。
    """
    logger.info("步骤 9: pm list packages -3")

    result = executor.run_shell("pm list packages -3")

    if not result.success or not result.stdout:
        logger.info("  没有第三方包")
        return ()

    # 解析 "package:<name>" 格式
    packages: list[str] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            packages.append(line[len("package:"):])

    logger.info("  第三方包数量: %d", len(packages))
    for pkg in packages:
        logger.debug("    %s", pkg)

    return tuple(packages)


# ── 主流程 ─────────────────────────────────────────────────────────

def load_device(executor: AdbExecutor) -> DeviceInfo:
    """加载设备信息。

    严格按照 4.0-Load Device.pcapng 抓包日志中的命令顺序执行 9 步：
    1. cat /system/bin/mi        → ROM 版本
    2. ls /system/etc/mi         → 路径探测
    3. ls /system/system/etc/mi  → 路径探测
    4. ls /system_root/system/etc/mi → 路径探测
    5. ls /data/mi               → 路径探测
    6. getprop ro.product.brand  → 品牌
    7. getprop ro.product.model  → 型号
    8. getprop ro.build.version.release → Android 版本
    9. pm list packages -3       → 第三方应用

    参数:
        executor: ADB 命令执行器实例。

    返回:
        包含所有收集到的信息的 DeviceInfo。

    抛出:
        AdbError: 如果 ADB 不可用或设备未连接。
    """
    logger.info("=" * 60)
    logger.info("Load Device — 开始加载设备信息")
    logger.info("=" * 60)

    # Step 1: ROM 版本
    rom_version = _read_rom_version(executor)

    # Steps 2-5: 配置路径探测
    config_paths = _probe_config_paths(executor)

    # Step 6: 品牌
    brand = _read_brand(executor)

    # Step 7: 型号
    model = _read_model(executor)

    # Step 8: Android 版本
    android_version = _read_android_version(executor)

    # Step 9: 第三方应用列表
    third_party_packages = _list_third_party_packages(executor)

    device_info = DeviceInfo(
        rom_version=rom_version,
        config_paths=config_paths,
        brand=brand,
        model=model,
        android_version=android_version,
        third_party_packages=third_party_packages,
    )

    _print_summary(device_info)
    return device_info


# ── 结果输出 ───────────────────────────────────────────────────────

def _print_summary(info: DeviceInfo) -> None:
    """打印可读的加载设备信息汇总。"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("Load Device — 设备信息汇总")
    logger.info("=" * 60)
    logger.info("  ROM 版本:        %s (已找到=%s)", info.rom_version.raw, info.rom_version.found)
    logger.info("  配置路径:")
    logger.info("    /system/etc/mi:                %s", info.config_paths.system_etc)
    logger.info("    /system/system/etc/mi:         %s", info.config_paths.system_system_etc)
    logger.info("    /system_root/system/etc/mi:    %s", info.config_paths.system_root_system_etc)
    logger.info("    /data/mi:                      %s", info.config_paths.data)
    logger.info("    首个找到的路径:                 %s", info.config_paths.found_path)
    logger.info("  品牌:             %s", info.brand)
    logger.info("  型号:             %s", info.model)
    logger.info("  Android 版本:     %s", info.android_version)
    logger.info("  第三方包数量:      %d", len(info.third_party_packages))
    for pkg in info.third_party_packages:
        logger.info("    - %s", pkg)
    logger.info("=" * 60)


# ── CLI 入口 ───────────────────────────────────────────────────────

def main() -> None:
    """Load Device 的命令行入口。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # 使用项目内置的 platform-tools/adb.exe
    project_root = Path(__file__).resolve().parent
    adb_path = project_root / "platform-tools" / "adb.exe"

    if not adb_path.exists():
        logger.error("未找到 ADB: %s", adb_path)
        sys.exit(1)

    executor = AdbExecutor(adb_path=adb_path)

    try:
        device_info = load_device(executor)
    except AdbError as e:
        logger.error("ADB 错误: %s", e)
        sys.exit(1)

    # 返回成功
    sys.exit(0)


if __name__ == "__main__":
    main()
