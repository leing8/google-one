"""
设备配置模型与加载器 — 通用共享模块。

DeviceProfile 包含伪装目标设备所需的全部属性，
由 randomly_change_device 和 random_change_sim_info 共享。

load_profile() 从 device_profiles/*.json 加载配置并随机化动态字段。
默认配置目录为 randomly_change_device/device_profiles/。

参考：
- https://docs.python.org/3/library/dataclasses.html
- https://docs.python.org/3/library/json.html
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .adb_executor import AdbError
from .randomizer import random_guid, random_serial_no, random_timezone

logger = logging.getLogger(__name__)

# 默认设备配置目录（randomly_change_device 模块下）
_DEFAULT_PROFILES_DIR: Path = (
    Path(__file__).resolve().parent.parent
    / "randomly_change_device"
    / "device_profiles"
)


@dataclass(frozen=True)
class DeviceProfile:
    """目标设备完整配置。

    从 device_profiles/*.json 加载，包含伪装目标设备所需的
    全部属性。所有字段均来自 pcapng 抓包中的 sed 替换目标值。

    Attributes:
        device: 设备代号（如 blazer）
        model: 设备型号（如 Pixel 10 Pro）
        brand: 品牌（如 Google）
        manufacturer: 制造商（如 Google）
        product: 产品名（如 blazer）
        board: 主板代号（如 blazer）
        platform: 平台（如 laguna）
        hardware: 硬件（如 powervr）
        build_id: 构建 ID（如 BP4A.260205.001）
        fingerprint: 构建指纹
        android_version: Android 版本（如 16）
        security_patch: 安全补丁日期（如 2026-02-05）
        incremental: 增量版本号（如 14624666）
        build_date: 构建日期字符串
        build_date_utc: 构建日期 UTC 时间戳
        build_user: 构建用户
        build_host: 构建主机
        build_tags: 构建标签（如 release-keys）
        build_type: 构建类型（如 user）
        timezone: 目标时区（如 Pacific/Honolulu）
        serial_no: 序列号（如 26JIK8TVGH）
        guid: 唯一标识 GUID
        mi_tool_version: MiChangerPro 版本标识
        mi_info_data: mi_info.json 加密数据（Base64）
        config_hash: /system/etc/config 哈希值
        android_id: 目标 android_id（16 位十六进制）
        cleanup_packages: 固定清理的应用包名列表（pm clear + rm -rf 数据 + APK 目录）
        extra_cleanup_packages: 额外清理的应用包名列表（pm clear + rm -rf）
        finalize_clear_packages: pm clear 最后阶段再次清理的包（默认 gms/gsf/vending）
        system_cleanup_paths: 系统数据清理路径列表
    """

    device: str
    model: str
    brand: str
    manufacturer: str
    product: str
    board: str
    platform: str
    hardware: str
    build_id: str
    fingerprint: str
    android_version: str
    security_patch: str
    incremental: str
    build_date: str
    build_date_utc: str
    build_user: str
    build_host: str
    build_tags: str
    build_type: str
    timezone: str
    serial_no: str
    guid: str
    mi_tool_version: str
    mi_info_data: str
    config_hash: str
    android_id: str
    cleanup_packages: tuple[str, ...]
    extra_cleanup_packages: tuple[str, ...]
    system_cleanup_paths: tuple[str, ...]
    finalize_clear_packages: tuple[str, ...] = (
        "com.google.android.gms",
        "com.google.android.gsf",
        "com.android.vending",
    )


def load_profile(
    name: str | None = None,
    *,
    profiles_dir: Path | None = None,
) -> DeviceProfile:
    """加载设备配置文件，并为可随机化字段生成运行时值。

    以下字段在每次执行时随机生成（基于 7.0 vs 7.0.1 对齐分析）：
    - timezone:  从预设时区池中随机选择
    - guid:      UUID v4 随机生成
    - serial_no: 10 位大写字母+数字随机序列号

    Args:
        name: 配置名称（不含 .json 后缀），None 则使用默认
        profiles_dir: 配置文件目录，None 则使用默认目录

    Returns:
        DeviceProfile 实例（含随机化字段）

    Raises:
        AdbError: 配置文件不存在或格式错误
    """
    search_dir = profiles_dir or _DEFAULT_PROFILES_DIR

    if name is None:
        # 使用目录中的第一个 JSON 文件
        json_files = sorted(search_dir.glob("*.json"))
        if not json_files:
            raise AdbError(f"未找到设备配置文件: {search_dir}")
        profile_path = json_files[0]
    else:
        profile_path = search_dir / f"{name}.json"

    if not profile_path.is_file():
        raise AdbError(f"设备配置文件不存在: {profile_path}")

    try:
        with open(profile_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        raise AdbError(
            f"配置文件读取失败: {profile_path}: {exc}"
        ) from exc

    # 运行时随机化字段
    tz = random_timezone()
    guid = random_guid()
    serial = random_serial_no()
    logger.info(
        "随机化: timezone=%s, guid=%s, serial_no=%s", tz, guid, serial,
    )

    return DeviceProfile(
        device=data["device"],
        model=data["model"],
        brand=data["brand"],
        manufacturer=data["manufacturer"],
        product=data["product"],
        board=data["board"],
        platform=data["platform"],
        hardware=data["hardware"],
        build_id=data["build_id"],
        fingerprint=data["fingerprint"],
        android_version=data["android_version"],
        security_patch=data["security_patch"],
        incremental=data["incremental"],
        build_date=data["build_date"],
        build_date_utc=data["build_date_utc"],
        build_user=data["build_user"],
        build_host=data["build_host"],
        build_tags=data["build_tags"],
        build_type=data["build_type"],
        timezone=tz,
        serial_no=serial,
        guid=guid,
        mi_tool_version=data["mi_tool_version"],
        mi_info_data=data["mi_info_data"],
        config_hash=data["config_hash"],
        android_id=data["android_id"],
        cleanup_packages=tuple(data["cleanup_packages"]),
        extra_cleanup_packages=tuple(data.get("extra_cleanup_packages", [])),
        system_cleanup_paths=tuple(data["system_cleanup_paths"]),
    )
