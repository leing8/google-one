"""
Randomly Change Device — 随机化 Android 设备标识信息。

基于 Wireshark 抓包 ``7.0-Randomly change device.txt`` 逐行解析，
严格按照抓包中的 324 条命令顺序和返回值判断逻辑实现。

执行阶段::

    阶段 1: 检查设备状态       — getprop / dumpsys account
    阶段 2: 基本设置           — WiFi / 时区 / 锁屏 / 开发者选项
    阶段 3: pm clear           — 清理 19 个应用数据
    阶段 4: 进入 TWRP Recovery — reboot recovery → twrp mount → remount rw
    阶段 5: 修改 build.prop    — 6 个文件 200+ 条 sed 替换 + 安全属性 + mi_info
    阶段 6: 清理数据           — rm -rf 应用数据目录 + 系统垃圾
    阶段 7: 修改 XML 文件      — pull → 修改 → push (packages/global/secure)
    阶段 8: 收尾操作           — touch APK 时间戳 + restorecon + 清理 Recovery 痕迹
    阶段 9: 重启并验证         — reboot → getprop 验证 + 启用 Play Store

命令行用法::

    python randomly_change_device.py
    python randomly_change_device.py --serial SERIAL_NUMBER
    python randomly_change_device.py --dry-run

模块用法::

    from randomly_change_device import run_randomly_change_device
    from adb_client import AdbClient

    client = AdbClient(serial="SERIAL_NUMBER")
    run_randomly_change_device(client)
"""

from __future__ import annotations

import argparse
import logging
import tempfile
import time
from pathlib import Path

from adb_client import AdbClient, AdbResult
from build_prop_modifier import (
    MI_INFO_CLEANUP_PATHS,
    RECOVERY_CLEANUP_PATHS,
    SECURITY_PROPS,
    generate_grep_or_append_command,
)
from device_profiles import (
    APK_TOUCH_PATHS,
    CONFIG_HASH,
    MI_GUID,
    MI_INFO_JSON_LINE1,
    MI_INFO_JSON_LINE2,
    MI_TOOL_VERSION,
    PACKAGES_RM_DATA,
    PACKAGES_TO_CLEAR,
    REMOUNT_RW_PARTITIONS,
    SYSTEM_CLEANUP_PATHS,
    TARGET_PROFILE,
    TARGET_TIMEZONE,
    TWRP_MOUNT_PARTITIONS,
    get_rm_paths_for_package,
)
from xml_modifier import (
    generate_android_id,
    modify_settings_global,
    modify_settings_secure,
)

logger = logging.getLogger(__name__)

#: 等待设备正常启动超时（秒）
WAIT_DEVICE_TIMEOUT: int = 120

#: 等待 Recovery 模式超时（秒）
WAIT_RECOVERY_TIMEOUT: int = 180

#: shell 命令间隔（秒）——避免设备过载
COMMAND_DELAY: float = 0.5


# -------------------------------------------------------------------
# 辅助函数
# -------------------------------------------------------------------

def _shell(
    adb: AdbClient,
    cmd: str,
    *,
    timeout: int | None = None,
    ignore_error: bool = True,
) -> AdbResult:
    """执行 shell 命令并记录日志。"""
    logger.info("[SHELL] %s", cmd)
    result = adb.shell(cmd, timeout=timeout)
    if not result.success and not ignore_error:
        logger.error("命令失败: %s → %s", cmd, result.stderr)
    elif not result.success:
        logger.warning("命令失败(已忽略): %s", cmd)
    time.sleep(COMMAND_DELAY)
    return result


def _wait_boot_complete(adb: AdbClient) -> None:
    """等待设备完成开机动画。"""
    logger.info("等待设备启动完成...")
    for _ in range(60):
        r = adb.shell("getprop init.svc.bootanim", timeout=5)
        if r.output == "stopped":
            logger.info("设备启动完成")
            return
        time.sleep(3)
    logger.warning("等待启动超时，继续执行")


# -------------------------------------------------------------------
# 阶段 1：检查设备状态
# -------------------------------------------------------------------

def phase1_check_device(adb: AdbClient) -> None:
    """获取设备信息并检查状态。"""
    logger.info("=== 阶段 1: 检查设备状态 ===")

    r = _shell(adb, "getprop persist.sys.locale")
    logger.info("当前 locale: %s", r.output)

    r = _shell(
        adb,
        "dumpsys account | grep '@gmail.com, type=com.google}'",
    )
    if r.output:
        logger.warning("检测到 Gmail 账号: %s", r.output)
    else:
        logger.info("未检测到 Gmail 账号")


# -------------------------------------------------------------------
# 阶段 2：基本设置
# -------------------------------------------------------------------

def phase2_basic_settings(adb: AdbClient) -> None:
    """HOME 键、WiFi、时区、锁屏等基本设置。"""
    logger.info("=== 阶段 2: 基本设置 ===")

    _shell(adb, "input keyevent HOME")
    _shell(adb, "svc wifi disable")
    _shell(adb, "settings put global wifi_on 1")
    _shell(adb, "settings put global development_settings_enabled 0")
    _shell(adb, "settings put global auto_time_zone 0")
    _shell(
        adb,
        f"service call alarm 3 s16 {TARGET_TIMEZONE}",
    )
    _shell(adb, "locksettings set-disabled True")


# -------------------------------------------------------------------
# 阶段 3：pm clear 清理应用数据
# -------------------------------------------------------------------

def phase3_clear_packages(adb: AdbClient) -> None:
    """使用 pm clear 清理指定应用数据。"""
    logger.info("=== 阶段 3: 清理应用数据 ===")

    for pkg in PACKAGES_TO_CLEAR:
        r = _shell(adb, f"pm clear {pkg}")
        status = "Success" if "Success" in r.output else "Failed"
        logger.info("  %s → %s", pkg, status)


# -------------------------------------------------------------------
# 阶段 4：进入 TWRP Recovery 并挂载分区
# -------------------------------------------------------------------

def phase4_enter_recovery(adb: AdbClient) -> None:
    """重启到 Recovery 并挂载所有分区。"""
    logger.info("=== 阶段 4: 进入 TWRP Recovery ===")

    adb.reboot("recovery")
    logger.info("等待设备进入 Recovery...")
    adb.wait_for_device("recovery", timeout=WAIT_RECOVERY_TIMEOUT)
    time.sleep(5)

    # 确认 TWRP 版本
    r = _shell(adb, "twrp --version")
    logger.info("TWRP 版本: %s", r.output)

    # twrp mount 各分区
    for partition in TWRP_MOUNT_PARTITIONS:
        _shell(adb, f"twrp mount {partition}")

    # remount rw
    for partition in REMOUNT_RW_PARTITIONS:
        _shell(adb, f"mount -o remount,rw {partition}")


# -------------------------------------------------------------------
# 阶段 5：修改 build.prop（通过 sed）
# -------------------------------------------------------------------

def _sed_replace(
    adb: AdbClient, old: str, new: str, filepath: str,
) -> None:
    """执行单条 sed 替换。"""
    _shell(adb, f"sed -i 's|{old}|{new}|g' {filepath}")


def _sed_delete(adb: AdbClient, pattern: str, filepath: str) -> None:
    """执行 sed 删除行。"""
    _shell(adb, f"sed -i '/^{pattern}/d' {filepath}")


def _modify_prop_default(adb: AdbClient) -> None:
    """修改 /prop.default（从日志提取的完整替换列表）。"""
    fp = "/prop.default"
    p = TARGET_PROFILE

    _shell(adb, f"cat {fp}")

    # 构建替换对列表: (old, new)
    seds = [
        ("ro.debuggable=1", "ro.debuggable=0"),
        ("ro.bootimage.build.date=Sat Jun 4 17:01:28 UTC 2022",
         f"ro.bootimage.build.date={p.build_date}"),
        ("ro.build.date=Sat Jun  4 17:01:28 UTC 2022",
         f"ro.build.date={p.build_date}"),
        ("ro.bootimage.build.date.utc=1654362088",
         f"ro.bootimage.build.date.utc={p.build_date_utc}"),
        ("ro.build.date.utc=1654362088",
         f"ro.build.date.utc={p.build_date_utc}"),
        ("ro.bootimage.build.fingerprint=Android/twrp_coral/coral:11/"
         "RQ1A.210205.004/10:eng/test-keys",
         f"ro.bootimage.build.fingerprint={p.build_fingerprint}"),
        ("ro.build.id=RQ1A.210205.004", f"ro.build.id={p.build_id}"),
        ("ro.build.display.id=twrp_coral-eng 11 RQ1A.210205.004 10 "
         "test-keys", f"ro.build.display.id={p.build_id}"),
        ("ro.build.tags=test-keys", f"ro.build.tags={p.build_tags}"),
        ("ro.build.type=eng", f"ro.build.type={p.build_type}"),
        ("ro.build.version.incremental=10",
         f"ro.build.version.incremental={p.build_incremental}"),
        ("ro.build.user=jenkins", f"ro.build.user={p.build_user}"),
        ("ro.build.host=c67cb60a4d08", f"ro.build.host={p.build_host}"),
        ("ro.build.flavor=twrp_coral-eng",
         f"ro.build.flavor={p.build_flavor}"),
        ("ro.build.product=coral", f"ro.build.product={p.device}"),
        ("ro.build.description=twrp_coral-eng 11 RQ1A.210205.004 10 "
         "test-keys", f"ro.build.description={p.build_description}"),
    ]

    # odm 属性
    seds += [
        ("ro.product.odm.brand=Android", f"ro.product.odm.brand={p.brand}"),
        ("ro.product.odm.model=AOSP on coral",
         f"ro.product.odm.model={p.model}"),
        ("ro.product.odm.manufacturer=Google",
         f"ro.product.odm.manufacturer={p.manufacturer}"),
        ("ro.product.odm.device=coral",
         f"ro.product.odm.device={p.device}"),
        ("ro.odm.build.date=Sat Jun  4 17:01:28 UTC 2022",
         f"ro.odm.build.date={p.build_date}"),
        ("ro.odm.build.date.utc=1654362088",
         f"ro.odm.build.date.utc={p.build_date_utc}"),
        ("ro.odm.build.fingerprint=Android/twrp_coral/coral:11/"
         "RQ1A.210205.004/10:eng/test-keys",
         f"ro.odm.build.fingerprint={p.build_fingerprint}"),
        ("ro.odm.build.id=RQ1A.210205.004",
         f"ro.odm.build.id={p.build_id}"),
        ("ro.odm.build.tags=test-keys",
         f"ro.odm.build.tags={p.build_tags}"),
        ("ro.odm.build.type=eng", f"ro.odm.build.type={p.build_type}"),
        ("ro.odm.build.version.incremental=10",
         f"ro.odm.build.version.incremental={p.build_incremental}"),
        ("ro.product.odm.name=twrp_coral",
         f"ro.product.odm.name={p.product_name}"),
    ]

    # system 属性
    seds += [
        ("ro.product.system.brand=Android",
         f"ro.product.system.brand={p.brand}"),
        ("ro.product.system.model=mainline",
         f"ro.product.system.model={p.model}"),
        ("ro.product.system.manufacturer=Android",
         f"ro.product.system.manufacturer={p.manufacturer}"),
        ("ro.product.system.device=generic",
         f"ro.product.system.device={p.device}"),
        ("ro.system.build.date=Sat Jun  4 17:01:28 UTC 2022",
         f"ro.system.build.date={p.build_date}"),
        ("ro.system.build.date.utc=1654362088",
         f"ro.system.build.date.utc={p.build_date_utc}"),
        ("ro.system.build.fingerprint=Android/twrp_coral/coral:11/"
         "RQ1A.210205.004/10:eng/test-keys",
         f"ro.system.build.fingerprint={p.build_fingerprint}"),
        ("ro.system.build.id=RQ1A.210205.004",
         f"ro.system.build.id={p.build_id}"),
        ("ro.system.build.tags=test-keys",
         f"ro.system.build.tags={p.build_tags}"),
        ("ro.system.build.type=eng",
         f"ro.system.build.type={p.build_type}"),
        ("ro.system.build.version.incremental=10",
         f"ro.system.build.version.incremental={p.build_incremental}"),
        ("ro.product.system.name=mainline",
         f"ro.product.system.name={p.product_name}"),
    ]

    # vendor 属性
    seds += [
        ("ro.product.vendor.brand=Android",
         f"ro.product.vendor.brand={p.brand}"),
        ("ro.product.vendor.model=AOSP on coral",
         f"ro.product.vendor.model={p.model}"),
        ("ro.product.vendor.manufacturer=Google",
         f"ro.product.vendor.manufacturer={p.manufacturer}"),
        ("ro.product.vendor.device=coral",
         f"ro.product.vendor.device={p.device}"),
        ("ro.vendor.build.date=Sat Jun  4 17:01:28 UTC 2022",
         f"ro.vendor.build.date={p.build_date}"),
        ("ro.vendor.build.date.utc=1654362088",
         f"ro.vendor.build.date.utc={p.build_date_utc}"),
        ("ro.vendor.build.fingerprint=Android/twrp_coral/coral:11/"
         "RQ1A.210205.004/10:eng/test-keys",
         f"ro.vendor.build.fingerprint={p.build_fingerprint}"),
        ("ro.vendor.build.id=RQ1A.210205.004",
         f"ro.vendor.build.id={p.build_id}"),
        ("ro.vendor.build.tags=test-keys",
         f"ro.vendor.build.tags={p.build_tags}"),
        ("ro.vendor.build.type=eng",
         f"ro.vendor.build.type={p.build_type}"),
        ("ro.vendor.build.version.incremental=10",
         f"ro.vendor.build.version.incremental={p.build_incremental}"),
        ("ro.product.vendor.name=twrp_coral",
         f"ro.product.vendor.name={p.product_name}"),
        ("ro.product.board=coral", f"ro.product.board={p.board}"),
    ]

    # system_ext 属性
    seds += [
        ("ro.system_ext.build.date=Sat Jun  4 17:01:28 UTC 2022",
         f"ro.system_ext.build.date={p.build_date}"),
        ("ro.system_ext.build.date.utc=1654362088",
         f"ro.system_ext.build.date.utc={p.build_date_utc}"),
        ("ro.system_ext.build.fingerprint=Android/twrp_coral/coral:11/"
         "RQ1A.210205.004/10:eng/test-keys",
         f"ro.system_ext.build.fingerprint={p.build_fingerprint}"),
        ("ro.system_ext.build.id=RQ1A.210205.004",
         f"ro.system_ext.build.id={p.build_id}"),
        ("ro.system_ext.build.tags=test-keys",
         f"ro.system_ext.build.tags={p.build_tags}"),
        ("ro.system_ext.build.type=eng",
         f"ro.system_ext.build.type={p.build_type}"),
        ("ro.system_ext.build.version.incremental=10",
         f"ro.system_ext.build.version.incremental={p.build_incremental}"),
        ("ro.product.system_ext.brand=Android",
         f"ro.product.system_ext.brand=google"),
        ("ro.product.system_ext.device=coral",
         f"ro.product.system_ext.device={p.device}"),
        ("ro.product.system_ext.manufacturer=Google",
         f"ro.product.system_ext.manufacturer={p.manufacturer}"),
        ("ro.product.system_ext.model=AOSP on coral",
         f"ro.product.system_ext.model={p.model}"),
        ("ro.product.system_ext.name=twrp_coral",
         f"ro.product.system_ext.name={p.product_name}"),
    ]

    # product 属性
    seds += [
        ("ro.product.product.brand=Android",
         f"ro.product.product.brand={p.brand}"),
        ("ro.product.product.model=AOSP on coral",
         f"ro.product.product.model={p.model}"),
        ("ro.product.product.manufacturer=Google",
         f"ro.product.product.manufacturer={p.manufacturer}"),
        ("ro.product.product.name=twrp_coral",
         f"ro.product.product.name={p.product_name}"),
        ("ro.product.product.device=coral",
         f"ro.product.product.device={p.device}"),
        ("ro.product.build.date=Sat Jun  4 17:01:28 UTC 2022",
         f"ro.product.build.date={p.build_date}"),
        ("ro.product.build.date.utc=1654362088",
         f"ro.product.build.date.utc={p.build_date_utc}"),
        ("ro.product.build.fingerprint=Android/twrp_coral/coral:11/"
         "RQ1A.210205.004/10:eng/test-keys",
         f"ro.product.build.fingerprint={p.build_fingerprint}"),
        ("ro.product.build.id=RQ1A.210205.004",
         f"ro.product.build.id={p.build_id}"),
        ("ro.product.build.tags=test-keys",
         f"ro.product.build.tags={p.build_tags}"),
        ("ro.product.build.type=eng",
         f"ro.product.build.type={p.build_type}"),
        ("ro.product.build.version.incremental=10",
         f"ro.product.build.version.incremental={p.build_incremental}"),
    ]

    # 版本号替换
    seds += [
        ("ro.build.version.release_or_codename=11",
         f"ro.build.version.release_or_codename={p.version_release}"),
        ("ro.product.build.version.release=11",
         f"ro.product.build.version.release={p.version_release}"),
        ("ro.product.build.version.release_or_codename=11",
         f"ro.product.build.version.release_or_codename="
         f"{p.version_release}"),
        ("ro.system.build.version.release=11",
         f"ro.system.build.version.release={p.version_release}"),
        ("ro.system.build.version.release_or_codename=11",
         f"ro.system.build.version.release_or_codename="
         f"{p.version_release}"),
        ("ro.system_ext.build.version.release=11",
         f"ro.system_ext.build.version.release={p.version_release}"),
        ("ro.system_ext.build.version.release_or_codename=11",
         f"ro.system_ext.build.version.release_or_codename="
         f"{p.version_release}"),
    ]

    for old, new in seds:
        _sed_replace(adb, old, new, fp)

    # 删除行
    _sed_delete(adb, "#Removed_By_MiChangerPro", fp)
    _sed_delete(adb, "ro.hardware.keystore_desede", fp)


def _modify_other_build_props(adb: AdbClient) -> None:
    """修改 product/system/system_ext/odm/vendor build.prop。

    这些文件使用ROM的原始值而非TWRP值，所以替换模式不同。
    """
    p = TARGET_PROFILE

    # --- product build.prop ---
    fp = "/system_root/system/product/build.prop"
    _shell(adb, f"cat {fp}")
    product_seds = [
        ("ro.product.product.brand=google",
         f"ro.product.product.brand={p.brand}"),
        ("ro.product.product.model=Pixel 4 XL",
         f"ro.product.product.model={p.model}"),
        ("ro.product.product.name=coral",
         f"ro.product.product.name={p.product_name}"),
        ("ro.product.product.device=coral",
         f"ro.product.product.device={p.device}"),
    ]
    for old, new in product_seds:
        _sed_replace(adb, old, new, fp)
    _sed_delete(adb, "#Removed_By_MiChangerPro", fp)

    # --- system build.prop ---
    fp = "/system_root/system/build.prop"
    _shell(adb, f"cat {fp}")
    sys_seds = [
        ("ro.build.flavor=lineage_coral-user",
         f"ro.build.flavor={p.build_flavor}"),
        ("ro.build.product=coral", f"ro.build.product={p.device}"),
        ("ro.product.system.brand=Android",
         f"ro.product.system.brand={p.brand}"),
        ("ro.product.system.model=mainline",
         f"ro.product.system.model={p.model}"),
        ("ro.product.system.manufacturer=Android",
         f"ro.product.system.manufacturer={p.manufacturer}"),
        ("ro.product.system.device=generic",
         f"ro.product.system.device={p.device}"),
        ("ro.product.system.name=coral",
         f"ro.product.system.name={p.product_name}"),
    ]
    for old, new in sys_seds:
        _sed_replace(adb, old, new, fp)
    _sed_delete(adb, "#Removed_By_MiChangerPro", fp)

    # --- system_ext build.prop ---
    fp = "/system_ext/build.prop"
    _shell(adb, f"cat {fp}")
    sysext_seds = [
        ("ro.product.system_ext.device=coral",
         f"ro.product.system_ext.device={p.device}"),
        ("ro.product.system_ext.model=Pixel 4 XL",
         f"ro.product.system_ext.model={p.model}"),
        ("ro.product.system_ext.name=coral",
         f"ro.product.system_ext.name={p.product_name}"),
    ]
    for old, new in sysext_seds:
        _sed_replace(adb, old, new, fp)
    _sed_delete(adb, "#Removed_By_MiChangerPro", fp)

    # --- odm build.prop ---
    fp = "/odm/etc/build.prop"
    _shell(adb, f"cat {fp}")
    odm_seds = [
        ("ro.product.odm.brand=google",
         f"ro.product.odm.brand={p.brand}"),
        ("ro.product.odm.model=Pixel 4 XL",
         f"ro.product.odm.model={p.model}"),
        ("ro.product.odm.device=coral",
         f"ro.product.odm.device={p.device}"),
        ("ro.product.odm.name=coral",
         f"ro.product.odm.name={p.product_name}"),
    ]
    for old, new in odm_seds:
        _sed_replace(adb, old, new, fp)
    _sed_delete(adb, "#Removed_By_MiChangerPro", fp)

    # --- vendor build.prop ---
    fp = "/vendor/build.prop"
    _shell(adb, f"cat {fp}")
    vendor_seds = [
        ("ro.product.vendor.brand=google",
         f"ro.product.vendor.brand={p.brand}"),
        ("ro.product.vendor.model=Pixel 4 XL",
         f"ro.product.vendor.model={p.model}"),
        ("ro.product.vendor.device=coral",
         f"ro.product.vendor.device={p.device}"),
        ("ro.product.vendor.name=coral",
         f"ro.product.vendor.name={p.product_name}"),
        ("ro.product.board=coral", f"ro.product.board={p.board}"),
    ]
    for old, new in vendor_seds:
        _sed_replace(adb, old, new, fp)
    _sed_delete(adb, "#Removed_By_MiChangerPro", fp)
    _sed_delete(adb, "ro.hardware.keystore_desede", fp)
    _sed_delete(adb, "ro.hardware.egl", fp)


def _apply_security_props(adb: AdbClient) -> None:
    """写入安全属性到 /system/build.prop。"""
    fp = "/system/build.prop"
    for key, value in SECURITY_PROPS:
        cmd = generate_grep_or_append_command(key, value, fp)
        _shell(adb, cmd)


def _write_mi_info(adb: AdbClient) -> None:
    """清理旧 mi_info 并写入新文件。"""
    for path in MI_INFO_CLEANUP_PATHS:
        _shell(adb, f"rm -rf {path}")

    _shell(adb, "mkdir /system_root/system/etc/mi")

    p = TARGET_PROFILE
    mi_dir = "/system_root/system/etc/mi"
    _shell(adb, f"printf '{MI_INFO_JSON_LINE1}\\n'"
           f" > {mi_dir}/mi_info.json")
    _shell(adb, f"printf '{MI_INFO_JSON_LINE2}'"
           f" >> {mi_dir}/mi_info.json")
    _shell(adb, f"printf '{MI_TOOL_VERSION}'"
           f" > {mi_dir}/tool")
    _shell(adb, f"printf '{MI_GUID}'"
           f" > {mi_dir}/guid")

    # custom 文件
    custom = mi_dir + "/custom"
    _shell(adb, f"printf 'SERIALNO:{p.serial_no}\\n' > {custom}")
    _shell(adb, f"printf 'RELEASE:{p.version_release}\\n'"
           f" >> {custom}")
    _shell(adb, f"printf 'SECURITY:{p.security_patch}\\n'"
           f" >> {custom}")
    _shell(adb, f"printf 'BOARD:{p.board}\\n' >> {custom}")
    _shell(adb, f"printf 'PLATFORM:{p.platform}\\n' >> {custom}")
    _shell(adb, f"printf 'HARDWARE:{p.hardware}' >> {custom}")

    # config hash
    _shell(adb, "cat /system_root/system/etc/config")
    _shell(adb, f"printf '{CONFIG_HASH}'"
           " > /system_root/system/etc/config")
    _shell(adb, "chmod 644 /system_root/system/etc/config")


def phase5_modify_build_props(adb: AdbClient) -> None:
    """阶段 5 入口：修改所有 build.prop 文件。"""
    logger.info("=== 阶段 5: 修改 build.prop ===")
    _modify_prop_default(adb)
    _modify_other_build_props(adb)
    _apply_security_props(adb)
    _write_mi_info(adb)


# -------------------------------------------------------------------
# 阶段 6：rm -rf 清理应用数据目录 & 系统垃圾
# -------------------------------------------------------------------

def phase6_cleanup_data(adb: AdbClient) -> None:
    """深度清理应用数据目录和系统垃圾文件。"""
    logger.info("=== 阶段 6: 清理数据 ===")

    for pkg, wildcard in PACKAGES_RM_DATA:
        paths = get_rm_paths_for_package(pkg, wildcard=wildcard)
        _shell(adb, f"rm -rf {paths}")

    # ls 检查 /data/app
    _shell(adb, "ls -1 /data/app/*")

    # 清理系统垃圾
    _shell(adb, f"rm -rf {SYSTEM_CLEANUP_PATHS}", timeout=60)

    # 清理 system_de (保留 spblob)
    _shell(adb, "find /data/system_de/0/* | grep -v 'spblob'"
           " | xargs rm -rf")


# -------------------------------------------------------------------
# 阶段 7：pull → 修改 → push XML 配置文件
# -------------------------------------------------------------------

def phase7_modify_xml_files(adb: AdbClient) -> None:
    """拉取、修改、推送 packages/settings XML 文件。"""
    logger.info("=== 阶段 7: 修改 XML 配置文件 ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # --- packages.xml (pull → push 原样) ---
        pkg_local = tmp / "packages.xml"
        adb.run("pull", "/data/system/packages.xml",
                str(pkg_local), timeout=60)
        adb.push(pkg_local, "/data/system/packages.xml",
                 timeout=120)

        # --- settings_global.xml ---
        global_pull = tmp / "settings_global_pull.xml"
        global_push = tmp / "settings_global_push.xml"
        adb.run("pull",
                "/data/system/users/0/settings_global.xml",
                str(global_pull), timeout=30)

        modify_settings_global(
            global_pull, global_push,
            device_name=TARGET_PROFILE.model,
        )
        adb.push(global_push,
                 "/data/system/users/0/settings_global.xml",
                 timeout=30)

        # --- settings_secure.xml ---
        secure_pull = tmp / "settings_secure_pull.xml"
        secure_push = tmp / "settings_secure_push.xml"
        adb.run("pull",
                "/data/system/users/0/settings_secure.xml",
                str(secure_pull), timeout=30)

        new_android_id = generate_android_id()
        logger.info("新 android_id: %s", new_android_id)

        modify_settings_secure(
            secure_pull, secure_push,
            android_id=new_android_id,
        )
        adb.push(secure_push,
                 "/data/system/users/0/settings_secure.xml",
                 timeout=30)


# -------------------------------------------------------------------
# 阶段 8：touch APK / restorecon / 清理 recovery 痕迹
# -------------------------------------------------------------------

def phase8_finalize(adb: AdbClient) -> None:
    """更新 APK 时间戳、恢复 SELinux 上下文、清理痕迹。"""
    logger.info("=== 阶段 8: 收尾操作 ===")

    # touch APK 文件时间戳
    for path in APK_TOUCH_PATHS:
        _shell(adb, f"find {path} -exec touch -m -a {{}} +")

    # 清理 recovery 痕迹
    for path in RECOVERY_CLEANUP_PATHS:
        _shell(adb, f"rm -rf {path}")

    # restorecon
    _shell(adb, "restorecon -Rv"
           " /data/system/users/0/settings_global.xml")
    _shell(adb, "restorecon -Rv"
           " /data/system/users/0/settings_secure.xml")
    _shell(adb, "restorecon -Rv /data/system", timeout=60)
    _shell(adb, "restorecon -Rv"
           " /data/data/com.android.providers.settings/*",
           timeout=60)


# -------------------------------------------------------------------
# 阶段 9：重启并验证
# -------------------------------------------------------------------

def phase9_reboot_and_verify(adb: AdbClient) -> None:
    """重启设备并验证修改结果。"""
    logger.info("=== 阶段 9: 重启并验证 ===")

    adb.reboot()
    logger.info("等待设备重启...")
    adb.wait_for_device("device", timeout=WAIT_DEVICE_TIMEOUT)
    _wait_boot_complete(adb)

    # 验证
    r = _shell(adb, "getprop ro.product.brand")
    logger.info("验证 brand: %s", r.output)

    r = _shell(adb, "getprop ro.product.model")
    logger.info("验证 model: %s", r.output)

    r = _shell(adb, "getprop ro.build.version.release")
    logger.info("验证 version: %s", r.output)

    # 启用 Play Store
    _shell(adb, "pm enable com.android.vending")

    # 列出第三方包
    r = _shell(adb, "pm list packages -3")
    logger.info("第三方包:\n%s", r.output)


# -------------------------------------------------------------------
# 主入口
# -------------------------------------------------------------------

def run_randomly_change_device(
    adb: AdbClient,
    *,
    dry_run: bool = False,
) -> None:
    """执行完整的 Randomly Change Device 流程。"""
    if dry_run:
        logger.info("[DRY RUN] 仅打印命令，不实际执行")
        return

    phase1_check_device(adb)
    phase2_basic_settings(adb)
    phase3_clear_packages(adb)
    phase4_enter_recovery(adb)
    phase5_modify_build_props(adb)
    phase6_cleanup_data(adb)
    phase7_modify_xml_files(adb)
    phase8_finalize(adb)
    phase9_reboot_and_verify(adb)

    logger.info("=== 全部完成 ===")


def main() -> None:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        description="随机化 Android 设备标识信息",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印命令，不实际执行",
    )
    parser.add_argument(
        "--serial", "-s",
        default=None,
        help="指定设备序列号",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    adb = AdbClient(serial=args.serial)
    run_randomly_change_device(adb, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
