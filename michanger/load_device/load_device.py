"""
Load Device — 设备探测核心逻辑。

严格按照 4.0-Load Device.pcapng 抓包还原的命令序列实现。
所有命令按原始顺序执行，不做任何跳过或短路优化。

pcapng 命令序列：
    1. cat /system/bin/mi         → 检测 MiChanger ROM 版本
    2. ls /system/etc/mi          → 探测 mi 配置路径 1
    3. ls /system/system/etc/mi   → 探测 mi 配置路径 2
    4. ls /system_root/system/etc/mi → 探测 mi 配置路径 3
    5. ls /data/mi                → 探测 mi 配置路径 4
    6. getprop ro.product.brand   → 获取设备品牌
    7. getprop ro.product.model   → 获取设备型号
    8. getprop ro.build.version.release → 获取 Android 版本
    9. pm list packages -3        → 列出第三方应用包名
"""

from __future__ import annotations

import logging
from pathlib import Path

from michanger.common import AdbExecutor, list_devices as _list_devices
from .models import (
    DeviceProperties,
    LoadDeviceResult,
    MiChangerInfo,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MiChanger ROM 检测
# ---------------------------------------------------------------------------

# MiChanger ROM 版本文件路径
_MICHANGER_BIN_PATH: str = "/system/bin/mi"

# MiChanger ROM 版本标识前缀
_ROM_VERSION_PREFIX: str = "rom.version="

# MiChanger 配置目录探测路径（按 pcapng 中的顺序）
_MI_CONFIG_PROBE_PATHS: tuple[str, ...] = (
    "/system/etc/mi",
    "/system/system/etc/mi",
    "/system_root/system/etc/mi",
    "/data/mi",
)


def _parse_rom_version(output: str) -> str | None:
    """从 cat /system/bin/mi 的输出中解析 ROM 版本。

    Args:
        output: cat 命令的标准输出

    Returns:
        ROM 版本字符串（如 "michanger_4xl_11_v3"），解析失败返回 None
    """
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith(_ROM_VERSION_PREFIX):
            version = stripped[len(_ROM_VERSION_PREFIX):]
            return version if version else None
    return None


def _detect_michanger(adb: AdbExecutor) -> MiChangerInfo:
    """检测 MiChanger ROM 信息。

    严格按 pcapng 顺序执行：
    1. cat /system/bin/mi → 读取版本
    2. ls 4 个路径 → 探测配置目录（全部执行，不短路）

    Args:
        adb: ADB 命令执行器

    Returns:
        MiChangerInfo 检测结果
    """
    # Step 1: 读取 MiChanger ROM 版本
    logger.info("检测 MiChanger ROM: cat %s", _MICHANGER_BIN_PATH)
    cat_result = adb.shell(f"cat {_MICHANGER_BIN_PATH}")
    rom_version = _parse_rom_version(cat_result.output)

    if rom_version is not None:
        logger.info("MiChanger ROM 版本: %s", rom_version)
    else:
        logger.info("未检测到 MiChanger ROM")

    # Step 2: 依次探测所有配置路径（与 pcapng 一致，全部执行）
    config_path: str | None = None
    for probe_path in _MI_CONFIG_PROBE_PATHS:
        logger.info("探测 mi 配置路径: ls %s", probe_path)
        ls_result = adb.shell(f"ls {probe_path}")

        if ls_result.success:
            logger.info("找到 mi 配置路径: %s", probe_path)
            # 记录第一个找到的路径
            if config_path is None:
                config_path = probe_path
        else:
            logger.debug("路径不存在: %s → %s", probe_path, ls_result.output)

    return MiChangerInfo(rom_version=rom_version, config_path=config_path)


# ---------------------------------------------------------------------------
# 设备属性获取
# ---------------------------------------------------------------------------

# 需要查询的系统属性（按 pcapng 中的顺序）
_DEVICE_PROPERTIES: tuple[tuple[str, str], ...] = (
    ("ro.product.brand", "brand"),
    ("ro.product.model", "model"),
    ("ro.build.version.release", "android_version"),
)


def _get_device_properties(adb: AdbExecutor) -> DeviceProperties:
    """获取设备系统属性。

    严格按 pcapng 顺序执行 3 个 getprop 命令。

    Args:
        adb: ADB 命令执行器

    Returns:
        DeviceProperties 设备属性

    Raises:
        ValueError: 任一属性获取失败
    """
    props: dict[str, str] = {}

    for prop_name, field_name in _DEVICE_PROPERTIES:
        logger.info("获取属性: getprop %s", prop_name)
        result = adb.shell(f"getprop {prop_name}")

        value = result.stdout if result.stdout else result.output
        if not value:
            logger.warning("属性为空: %s", prop_name)
            value = ""

        props[field_name] = value
        logger.info("%s = %s", prop_name, value)

    return DeviceProperties(
        brand=props["brand"],
        model=props["model"],
        android_version=props["android_version"],
    )


# ---------------------------------------------------------------------------
# 第三方应用包列表
# ---------------------------------------------------------------------------

_PM_LIST_COMMAND: str = "pm list packages -3"

# pm list packages 输出的每行前缀
_PACKAGE_PREFIX: str = "package:"


def _parse_packages(output: str) -> tuple[str, ...]:
    """解析 pm list packages -3 的输出。

    每行格式：package:com.example.app

    Args:
        output: pm list packages 命令的标准输出

    Returns:
        包名元组（不可变）
    """
    packages: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith(_PACKAGE_PREFIX):
            pkg = stripped[len(_PACKAGE_PREFIX):]
            if pkg:
                packages.append(pkg)
    return tuple(sorted(packages))


def _list_third_party_packages(adb: AdbExecutor) -> tuple[str, ...]:
    """列出第三方应用包名。

    Args:
        adb: ADB 命令执行器

    Returns:
        排序后的包名元组
    """
    logger.info("列出第三方应用: %s", _PM_LIST_COMMAND)
    result = adb.shell(_PM_LIST_COMMAND)
    packages = _parse_packages(result.output)
    logger.info("第三方应用数量: %d", len(packages))
    return packages


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def load_device(
    adb_path: Path,
    serial: str,
    state: str,
) -> LoadDeviceResult:
    """执行 Load Device 单台设备探测。

    严格按照 4.0-Load Device.pcapng 抓包还原的完整命令序列。
    所有命令按原始顺序依次执行，不做跳过或优化。

    命令序列：
        1. cat /system/bin/mi             → MiChanger ROM 版本
        2. ls /system/etc/mi              → 配置路径探测
        3. ls /system/system/etc/mi       → 配置路径探测
        4. ls /system_root/system/etc/mi  → 配置路径探测
        5. ls /data/mi                    → 配置路径探测
        6. getprop ro.product.brand       → 品牌
        7. getprop ro.product.model       → 型号
        8. getprop ro.build.version.release → Android 版本
        9. pm list packages -3            → 第三方应用

    Args:
        adb_path: adb.exe 的路径
        serial: 设备序列号
        state: 设备连接状态（来自 adb devices）

    Returns:
        LoadDeviceResult 完整探测结果
    """
    adb = AdbExecutor(adb_path=adb_path, serial=serial)

    logger.info("探测设备 [%s] 开始", serial)

    # Phase 1: MiChanger ROM 检测（命令 1-5）
    michanger = _detect_michanger(adb)

    # Phase 2: 设备属性（命令 6-8）
    properties = _get_device_properties(adb)

    # Phase 3: 第三方应用列表（命令 9）
    packages = _list_third_party_packages(adb)

    result = LoadDeviceResult(
        serial=serial,
        state=state,
        michanger=michanger,
        properties=properties,
        third_party_packages=packages,
    )

    logger.info("探测设备 [%s] 完成", serial)

    return result


def load_all_devices(
    adb_path: Path,
) -> tuple[LoadDeviceResult, ...]:
    """列出并探测所有已连接的 ADB 设备。

    流程：
        1. 执行 adb devices 获取已连接设备列表
        2. 对每台在线设备（state == "device"）执行完整探测
        3. 非在线设备跳过探测，仅记录序列号和状态

    Args:
        adb_path: adb.exe 的路径

    Returns:
        所有已连接设备的探测结果元组（包含在线和非在线设备）
    """
    devices = _list_devices(adb_path=adb_path)

    if not devices:
        logger.warning("未检测到已连接的 ADB 设备")
        return ()

    logger.info("检测到 %d 台设备", len(devices))

    results: list[LoadDeviceResult] = []
    for device in devices:
        if device.is_online:
            result = load_device(
                adb_path=adb_path,
                serial=device.serial,
                state=device.state,
            )
            results.append(result)
        else:
            # 非在线设备：只记录基本信息，属性留空
            logger.warning(
                "设备 [%s] 状态为 %s，跳过探测",
                device.serial, device.state,
            )
            results.append(LoadDeviceResult(
                serial=device.serial,
                state=device.state,
                michanger=MiChangerInfo(rom_version=None, config_path=None),
                properties=DeviceProperties(brand="", model="", android_version=""),
                third_party_packages=(),
            ))

    return tuple(results)
