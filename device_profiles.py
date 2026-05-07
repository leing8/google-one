"""
Device Profiles — 设备配置数据与常量定义。

基于 Wireshark 抓包 ``7.0-Randomly change device.txt`` 逐行解析，
从中提取目标设备 Pixel 10 Pro (blazer) 的完整标识信息，
以及流程所需的所有常量数据。

数据分类::

    - DeviceProfile        — 目标设备 build 属性（brand/model/fingerprint 等）
    - PACKAGES_TO_CLEAR    — pm clear 清理列表（19 个包，严格按抓包顺序）
    - PACKAGES_RM_DATA     — rm -rf 清理列表（含 wildcard 标记）
    - SYSTEM_CLEANUP_PATHS — /data 下的系统垃圾路径
    - TWRP_MOUNT_PARTITIONS — TWRP Recovery 分区挂载列表
    - APK_TOUCH_PATHS      — APK 时间戳更新路径
    - MI_INFO_*            — MiChangerPro 工具信息文件内容

模块用法::

    from device_profiles import TARGET_PROFILE, PACKAGES_TO_CLEAR

    print(TARGET_PROFILE.model)        # "Pixel 10 Pro"
    print(TARGET_PROFILE.build_id)     # "BP4A.260205.001"
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# 目标设备 Profile（从日志中提取）
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class DeviceProfile:
    """目标设备的完整标识信息。

    所有字段均从 Wireshark 抓包中 ``sed`` 替换的目标值提取。
    使用 ``frozen=True`` 确保实例不可变。

    Attributes:
        brand: 设备品牌, e.g. ``"Google"``。
        model: 设备型号, e.g. ``"Pixel 10 Pro"``。
        device: 设备代号, e.g. ``"blazer"``。
        build_fingerprint: 完整 build fingerprint 字符串。
        serial_no: 设备序列号, e.g. ``"43VIG8UOAB"``。
    """

    # 基本设备信息
    brand: str
    model: str
    device: str          # 代号, e.g. "blazer"
    product_name: str    # e.g. "blazer"
    manufacturer: str

    # Build 信息
    build_id: str        # e.g. "BP4A.260205.001"
    build_date: str      # e.g. "Wed Jul 30 03:34:28 UTC 2025"
    build_date_utc: str  # e.g. "1753846468"
    build_fingerprint: str
    build_flavor: str    # e.g. "blazer-user"
    build_incremental: str  # e.g. "14624666"
    build_type: str      # e.g. "user"
    build_tags: str      # e.g. "release-keys"
    build_user: str      # e.g. "user"
    build_host: str      # e.g. "7e95205b9461"
    build_description: str
    version_release: str  # e.g. "16"
    board: str            # e.g. "blazer"

    # 安全信息
    security_patch: str   # e.g. "2026-02-05"
    serial_no: str        # e.g. "43VIG8UOAB"
    platform: str         # e.g. "laguna"
    hardware: str         # e.g. "powervr"


#: 从 Wireshark 日志中提取的目标设备配置（Pixel 10 Pro / blazer）
TARGET_PROFILE = DeviceProfile(
    brand="Google",
    model="Pixel 10 Pro",
    device="blazer",
    product_name="blazer",
    manufacturer="Google",
    build_id="BP4A.260205.001",
    build_date="Wed Jul 30 03:34:28 UTC 2025",
    build_date_utc="1753846468",
    build_fingerprint=(
        "google/blazer/blazer:16/BP4A.260205.001"
        "/14624666:user/release-keys"
    ),
    build_flavor="blazer-user",
    build_incremental="14624666",
    build_type="user",
    build_tags="release-keys",
    build_user="user",
    build_host="7e95205b9461",
    build_description=(
        "blazer-user 16 BP4A.260205.001 14624666 release-keys"
    ),
    version_release="16",
    board="blazer",
    security_patch="2026-02-05",
    serial_no="43VIG8UOAB",
    platform="laguna",
    hardware="powervr",
)


# ---------------------------------------------------------------------------
# 时区
# ---------------------------------------------------------------------------

#: 目标时区（对应抓包命令 ``service call alarm 3 s16 America/Adak``）
TARGET_TIMEZONE: str = "America/Adak"


# ---------------------------------------------------------------------------
# 应用数据清理
# ---------------------------------------------------------------------------

#: ``pm clear`` 清理目标列表（严格按抓包中 19 条 ``pm clear`` 命令的顺序）
#: 部分包可能清理失败（如 ``gsf.login``），属预期行为，不影响流程。
PACKAGES_TO_CLEAR: tuple[str, ...] = (
    "com.android.vending",
    "com.google.android.gms",
    "com.android.chrome",
    "com.google.android.gm",
    "com.google.android.gsf",
    "com.google.android.gsf.login",
    "com.google.android.ext.services",
    "com.google.android.onetimeinitializer",
    "com.google.android.ext.shared",
    "com.android.webview",
    "com.google.android.webview",
    "org.lineageos.jelly",
    "com.android.htmlviewer",
    "com.google.android.gms.location.history",
    "com.google.android.apps.maps",
    "com.google.android.syncadapters.contacts",
    "com.google.android.ims",
    "com.google.android.play.games",
    "com.google.android.backuptransport",
)


# ---------------------------------------------------------------------------
# rm -rf 清理路径模板
# ---------------------------------------------------------------------------

#: 每个包需要清理的 6 个数据目录模板
#: 对应抓包中的 ``rm -rf /data/data/{pkg} /data/user_de/0/{pkg} ...`` 命令
_RM_PATH_TEMPLATES: tuple[str, ...] = (
    "/data/data/{pkg}",
    "/data/user_de/0/{pkg}",
    "/data/user/0/{pkg}",
    "/sdcard/Android/data/{pkg}",
    "/data/misc/profiles/ref/{pkg}",
    "/data/misc/profiles/cur/0/{pkg}",
)


def get_rm_paths_for_package(
    package_name: str,
    *,
    wildcard: bool = False,
) -> str:
    """为指定包名生成 rm -rf 路径列表。

    Args:
        package_name: Android 包名
        wildcard: 如果为 True, 在路径末尾加上 /*

    Returns:
        空格分隔的路径字符串
    """
    suffix = "/*" if wildcard else ""
    paths = [
        t.format(pkg=package_name) + suffix
        for t in _RM_PATH_TEMPLATES
    ]
    return " ".join(paths)


# ---------------------------------------------------------------------------
# 需要 rm -rf 的包列表（与 PACKAGES_TO_CLEAR 相同，部分用 wildcard）
# gms 使用 wildcard (/*), 其余不使用
# ---------------------------------------------------------------------------

PACKAGES_RM_DATA: tuple[tuple[str, bool], ...] = (
    ("com.android.vending", False),
    ("com.google.android.gms", True),  # 注意：gms 用 /*
    ("com.android.chrome", False),
    ("com.google.android.gm", False),
    ("com.google.android.gsf", False),
    ("com.google.android.gsf.login", False),
    ("com.google.android.ext.services", False),
    ("com.google.android.onetimeinitializer", False),
    ("com.google.android.ext.shared", False),
    ("com.android.webview", False),
    ("com.google.android.webview", False),
    ("org.lineageos.jelly", False),
    ("com.android.htmlviewer", False),
    ("com.google.android.gms.location.history", False),
    ("com.google.android.apps.maps", False),
    ("com.google.android.syncadapters.contacts", False),
    ("com.google.android.ims", False),
    ("com.google.android.play.games", False),
    ("com.google.android.backuptransport", False),
)


# ---------------------------------------------------------------------------
# 系统垃圾清理路径（从日志中提取）
# ---------------------------------------------------------------------------

SYSTEM_CLEANUP_PATHS: str = (
    "/data/system/dropbox/* /data/system/procexitstore/* "
    "/data/system/environ/* /data/system/blobstore/* "
    "/data/system/appops/* /data/system_de/0/persisted_taskIds.txt "
    "/data/tombstones /data/system/users/0/settings_ssaid.xml "
    "/data/system_de/0/snapshots* /data/system_de/0/accounts* "
    "/data/system_ce/0/recent* /data/system_ce/0/accounts* "
    "/data/backup /data/system_ce/0/launch_params/* "
    "/data/system/package_cache /data/anr/* /data/drm/* "
    "/data/local/* /data/misc/keystore/user_0/* "
    "/data/system/users/0/registered_services "
    "/data/system/uiderrors.txt /data/system/watchlist* "
    "/data/system/sync /data/system/slice "
    "/data/system/recoverablekeystore* /data/system/profiles.xml "
    "/data/system/notification_log* /data/system/job "
    "/data/system/diskstats_cache.json "
    "/data/system/device_policies.xml "
    "/data/system/cachequota.xml /data/system/appops.xml "
    "/data/system/entropy.dat /data/system/last-fstrim "
    "/data/system/last-header.txt /data/system/log-files.xml "
    "/data/system/syncmanager-log/* /data/system/usagestats/* "
    "/data/system/procstats/* /data/system/netstats/* "
    "/data/system/graphicsstats/*"
)


# ---------------------------------------------------------------------------
# TWRP 分区挂载列表
# ---------------------------------------------------------------------------

TWRP_MOUNT_PARTITIONS: tuple[str, ...] = (
    "/system",
    "/system_ext",
    "/vendor",
    "/product",
    "/odm",
    "/persist",
    "/firmware",
)

REMOUNT_RW_PARTITIONS: tuple[str, ...] = (
    "/system_root",
    "/system_ext",
    "/vendor",
    "/product",
    "/odm",
    "/persist",
    "/firmware",
)


# ---------------------------------------------------------------------------
# APK 时间戳触发路径（从日志中提取）
# ---------------------------------------------------------------------------

APK_TOUCH_PATHS: tuple[str, ...] = (
    "./system/priv-app/Phonesky",
    "./system/priv-app/Phonesky/Phonesky.apk",
    "./system/priv-app/PrebuiltGmsCorePi",
    "./system/priv-app/PrebuiltGmsCorePi/PrebuiltGmsCorePi.apk",
    "./system/priv-app/GoogleServicesFramework",
    "./system/priv-app/GoogleServicesFramework/GoogleServicesFramework.apk",
)


# ---------------------------------------------------------------------------
# Mi 信息文件内容（从日志中提取）
# ---------------------------------------------------------------------------

MI_INFO_JSON_LINE1: str = "/rjnPvtfvUGe44yUyczs/A=="

MI_INFO_JSON_LINE2: str = (
    "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"
    "/dyhCuLKFCvM="
)

MI_TOOL_VERSION: str = "MiChangerPro_v3.2.7"
MI_GUID: str = "8677bd04-7085-41c6-a0ab-53f12d771ad5"

# config hash（从日志中提取）
CONFIG_HASH: str = (
    "cd0315e9f43897fcd9eef362b4a43b77d801d99b"
    "6f18fe3845028e92b6a1b836"
)
