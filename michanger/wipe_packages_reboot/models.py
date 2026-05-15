"""
Wipe Packages & Reboot — 数据模型。

所有模型均使用 frozen=True 保证不可变性（PEP 557）。

参考：
- https://docs.python.org/3/library/dataclasses.html
- 11.0/11.1/11.2 pcapng 三份抓包对比分析
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ------------------------------------------------------------------
# 固定包列表（三份抓包完全一致的 19 个包）
# ------------------------------------------------------------------

FIXED_CLEANUP_PACKAGES: tuple[str, ...] = (
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

# /data/app/ 中仅清理 APK 目录的包（三份抓包一致）
APP_WIPE_PACKAGES: tuple[str, ...] = (
    "com.android.vending",
    "com.google.android.gms",
)

# packages.xml 中统一时间戳的包（三份抓包 diff 分析确认）
PACKAGES_TIMESTAMP_TARGETS: tuple[str, ...] = (
    "com.android.vending",
    "com.google.android.gms",
)

# TWRP 挂载分区列表（三份抓包完全一致）
TWRP_MOUNT_PARTITIONS: tuple[str, ...] = (
    "/system",
    "/system_ext",
    "/vendor",
    "/product",
    "/odm",
    "/persist",
    "/firmware",
)

# 重新挂载为 rw 的分区（三份抓包完全一致）
REMOUNT_RW_PARTITIONS: tuple[str, ...] = (
    "/system_root",
    "/system_ext",
    "/vendor",
    "/product",
    "/odm",
    "/persist",
    "/firmware",
)

# 应用数据目录模板（rm -rf 清理目标）
APP_DATA_DIR_TEMPLATES: tuple[str, ...] = (
    "/data/data/{pkg}",
    "/data/user_de/0/{pkg}",
    "/data/user/0/{pkg}",
    "/sdcard/Android/data/{pkg}",
    "/data/misc/profiles/ref/{pkg}",
    "/data/misc/profiles/cur/0/{pkg}",
)

# GMS 特殊处理模板（使用通配符 /*，不删除目录本身）
GMS_DATA_DIR_TEMPLATES: tuple[str, ...] = (
    "/data/data/com.google.android.gms/*",
    "/data/user_de/0/com.google.android.gms/*",
    "/data/user/0/com.google.android.gms/*",
    "/sdcard/Android/data/com.google.android.gms/*",
    "/data/misc/profiles/ref/com.google.android.gms/*",
    "/data/misc/profiles/cur/0/com.google.android.gms/*",
)

# 系统数据清理路径（三份抓包完全一致）
SYSTEM_CLEANUP_PATHS: tuple[str, ...] = (
    "/data/system/dropbox/*",
    "/data/system/procexitstore/*",
    "/data/system/environ/*",
    "/data/system/blobstore/*",
    "/data/system/appops/*",
    "/data/system_de/0/persisted_taskIds.txt",
    "/data/tombstones",
    "/data/system/users/0/settings_ssaid.xml",
    "/data/system_de/0/snapshots*",
    "/data/system_de/0/accounts*",
    "/data/system_ce/0/recent*",
    "/data/system_ce/0/accounts*",
    "/data/backup",
    "/data/system_ce/0/launch_params/*",
    "/data/system/package_cache",
    "/data/anr/*",
    "/data/drm/*",
    "/data/local/*",
    "/data/misc/keystore/user_0/*",
    "/data/system/users/0/registered_services",
    "/data/system/uiderrors.txt",
    "/data/system/watchlist*",
    "/data/system/sync",
    "/data/system/slice",
    "/data/system/recoverablekeystore*",
    "/data/system/profiles.xml",
    "/data/system/notification_log*",
    "/data/system/job",
    "/data/system/diskstats_cache.json",
    "/data/system/device_policies.xml",
    "/data/system/cachequota.xml",
    "/data/system/appops.xml",
    "/data/system/entropy.dat",
    "/data/system/last-fstrim",
    "/data/system/last-header.txt",
    "/data/system/log-files.xml",
    "/data/system/syncmanager-log/*",
    "/data/system/usagestats/*",
    "/data/system/procstats/*",
    "/data/system/netstats/*",
    "/data/system/graphicsstats/*",
)

# Touch 系统 APK 路径（三份抓包完全一致的 6 个路径）
TOUCH_TARGETS: tuple[str, ...] = (
    "./system/priv-app/Phonesky",
    "./system/priv-app/Phonesky/Phonesky.apk",
    "./system/priv-app/PrebuiltGmsCorePi",
    "./system/priv-app/PrebuiltGmsCorePi/PrebuiltGmsCorePi.apk",
    "./system/priv-app/GoogleServicesFramework",
    "./system/priv-app/GoogleServicesFramework/GoogleServicesFramework.apk",
)

# 额外清理路径（三份抓包完全一致的 4 个路径）
EXTRA_CLEANUP_PATHS: tuple[str, ...] = (
    "/system/addon.d",
    "/system/bin/install-recovery.sh",
    "/vendor/bin/install-recovery.sh",
    "/sdcard/TWRP",
)


# ------------------------------------------------------------------
# 配置与结果数据类
# ------------------------------------------------------------------

@dataclass(frozen=True)
class WipeConfig:
    """Wipe Packages & Reboot 的可定制配置。

    固定 19 包由常量提供，此配置类仅管理动态部分。

    Attributes:
        extra_cleanup_packages: 额外需要 pm clear + rm -rf 的包名列表
            - 11.0: 无额外包
            - 11.1: ("com.google.android.apps.subscriptions.red",)
            - 11.2: ("com.google.android.apps.subscriptions.red",
                      "gr.nikolasspyr.integritycheck")
    """

    extra_cleanup_packages: tuple[str, ...] = ()


@dataclass(frozen=True)
class PhaseResult:
    """单阶段执行结果。

    Attributes:
        phase_name: 阶段名称
        phase_number: 阶段编号（1-7）
        success: 是否成功
        message: 结果描述
        commands_executed: 执行的命令数量
    """

    phase_name: str
    phase_number: int
    success: bool
    message: str
    commands_executed: int = 0


@dataclass(frozen=True)
class WipeResult:
    """完整的 Wipe Packages & Reboot 执行结果。

    Attributes:
        serial: 设备序列号
        phase_results: 各阶段的执行结果
        success: 整体是否成功（所有关键阶段均成功）
    """

    serial: str
    phase_results: tuple[PhaseResult, ...] = field(default_factory=tuple)
    success: bool = False

    @property
    def total_phases(self) -> int:
        """总阶段数。"""
        return len(self.phase_results)

    @property
    def success_count(self) -> int:
        """成功阶段数。"""
        return sum(1 for r in self.phase_results if r.success)

    @property
    def total_commands(self) -> int:
        """执行的总命令数。"""
        return sum(r.commands_executed for r in self.phase_results)
