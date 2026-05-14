"""Randomly Change Device — 阶段 J-L: 安全属性、数据清理、重启验证.

严格按照 7.0-Randomly change device.pcapng 步骤 240-332。

阶段 J (步骤 240-268): 安全属性 & MiChanger 文件写入
阶段 K (步骤 269-315): 数据清理 & 文件推送
阶段 L (步骤 316-332): 重启 & 验证
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from .adb_executor import AdbExecutor
from .xml_modifier import (
    modify_packages_xml,
    modify_settings_global_xml,
    modify_settings_secure_xml,
)

logger = logging.getLogger(__name__)

_SHELL_TIMEOUT: int = 30
_LONG_TIMEOUT: int = 60

# 步骤 240-247: grep -q && sed || echo 安全属性
_SECURITY_PROPS: tuple[tuple[int, str, str], ...] = (
    (240, "ro.secure", "1"),
    (241, "ro.debuggable", "0"),
    (242, "ro.crypto.state", "encrypted"),
    (243, "init.svc.flash_recovery", "stop"),
    (244, "ro.boot.verifiedbootstate", "green"),
    (245, "ro.boot.flash.locked", "1"),
    (246, "sys.oem_unlock_allowed", "0"),
    (247, "ro.secureboot.lockstate", "locked"),
)

# 步骤 248-254: rm -rf 清理路径
_MI_CLEANUP_PATHS: tuple[tuple[int, str], ...] = (
    (248, "/data/mi_info"),
    (249, "/system/system/etc/mi_info"),
    (250, "/system/etc/mi_info"),
    (251, "/system_root/system/etc/mi_info"),
    (252, "/system/system/etc/mi"),
    (253, "/system/etc/mi"),
    (254, "/system_root/system/etc/mi"),
)

# 步骤 269-287: rm -rf 应用数据清理包列表
_APP_DATA_PACKAGES: tuple[tuple[int, str], ...] = (
    (269, "com.android.vending"),
    (270, "com.google.android.gms"),
    (271, "com.android.chrome"),
    (272, "com.google.android.gm"),
    (273, "com.google.android.gsf"),
    (274, "com.google.android.gsf.login"),
    (275, "com.google.android.ext.services"),
    (276, "com.google.android.onetimeinitializer"),
    (277, "com.google.android.ext.shared"),
    (278, "com.android.webview"),
    (279, "com.google.android.webview"),
    (280, "org.lineageos.jelly"),
    (281, "com.android.htmlviewer"),
    (282, "com.google.android.gms.location.history"),
    (283, "com.google.android.apps.maps"),
    (284, "com.google.android.syncadapters.contacts"),
    (285, "com.google.android.ims"),
    (286, "com.google.android.play.games"),
    (287, "com.google.android.backuptransport"),
)

# 步骤 298-303: find touch APK 时间戳
_TOUCH_PATHS: tuple[tuple[int, str], ...] = (
    (298, "./system/priv-app/Phonesky"),
    (299, "./system/priv-app/Phonesky/Phonesky.apk"),
    (300, "./system/priv-app/PrebuiltGmsCorePi"),
    (301, "./system/priv-app/PrebuiltGmsCorePi/PrebuiltGmsCorePi.apk"),
    (302, "./system/priv-app/GoogleServicesFramework"),
    (303, "./system/priv-app/GoogleServicesFramework/GoogleServicesFramework.apk"),
)

# MiChanger mi_info.json base64 内容（步骤 257）
_MI_INFO_B64: str = (
    "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"
    "2TkNPKx1DisdZyD/9vqQ=="
)


def _shell(
    executor: AdbExecutor, step: int, cmd: str, timeout: int = _SHELL_TIMEOUT,
) -> bool:
    """执行 shell 命令并记录日志."""
    logger.info("步骤 %d: %s", step, cmd[:120])
    result = executor.run_shell(cmd, timeout=timeout)
    out = result.stdout or result.stderr
    if out:
        logger.info("  输出: %s", out[:200])
    return result.success


def set_security_props_and_mi_files(
    executor: AdbExecutor,
) -> tuple[bool, bool]:
    """阶段 J: 步骤 240-268."""

    # 步骤 240-247: 安全属性
    for step, prop, val in _SECURITY_PROPS:
        cmd = (
            f"grep -q '^{prop}=' /system/build.prop "
            f"&& sed -i 's/^{prop}=.*/{prop}={val}/' /system/build.prop "
            f"|| echo '{prop}={val}' >> /system/build.prop"
        )
        _shell(executor, step, cmd)

    # 步骤 248-254: rm -rf 清理 mi 目录
    for step, path in _MI_CLEANUP_PATHS:
        _shell(executor, step, f"rm -rf {path}")

    # 步骤 255: mkdir
    _shell(executor, 255, "mkdir /system_root/system/etc/mi")

    # 步骤 256-257: printf mi_info.json
    logger.info("步骤 256-257: 写入 mi_info.json")
    executor.run_shell(
        r"printf 'gs0O2me1MWHKmZwGpABcFw==\n' > /system_root/system/etc/mi/mi_info.json",
        timeout=_SHELL_TIMEOUT,
    )
    executor.run_shell(
        f"printf '{_MI_INFO_B64}' >> /system_root/system/etc/mi/mi_info.json",
        timeout=_SHELL_TIMEOUT,
    )

    # 步骤 258: tool 文件
    _shell(executor, 258,
           "printf 'MiChangerPro_v3.2.7' > /system_root/system/etc/mi/tool")

    # 步骤 259: guid 文件
    _shell(executor, 259,
           "printf 'b95609b5-350e-46a4-b149-c56f5973a967' > /system_root/system/etc/mi/guid")

    # 步骤 260-265: custom 文件
    custom_lines = [
        (260, r"printf 'SERIALNO:06VIEJBES4\n' > /system_root/system/etc/mi/custom"),
        (261, r"printf 'RELEASE:16\n' >> /system_root/system/etc/mi/custom"),
        (262, r"printf 'SECURITY:2026-02-05\n' >> /system_root/system/etc/mi/custom"),
        (263, r"printf 'BOARD:blazer\n' >> /system_root/system/etc/mi/custom"),
        (264, r"printf 'PLATFORM:laguna\n' >> /system_root/system/etc/mi/custom"),
        (265, "printf 'HARDWARE:powervr' >> /system_root/system/etc/mi/custom"),
    ]
    for step, cmd in custom_lines:
        _shell(executor, step, cmd)

    # 步骤 266: cat /system_root/system/etc/config
    _shell(executor, 266, "cat /system_root/system/etc/config")

    # 步骤 267: 写入 config
    _shell(executor, 267,
           "printf 'cd0315e9f43897fcd9eef362b4a43b77d801d99b6f18fe3845028e92b6a1b836'"
           " > /system_root/system/etc/config")

    # 步骤 268: chmod 644
    _shell(executor, 268, "chmod 644 /system_root/system/etc/config")

    return True, True


def cleanup_and_push(
    executor: AdbExecutor,
    work_dir: Path,
    device_name: str,
    android_id: str,
) -> tuple[bool, bool, bool]:
    """阶段 K: 步骤 269-315."""

    # 步骤 269-287: rm -rf 应用数据
    data_dirs = (
        "/data/data/{pkg}", "/data/user_de/0/{pkg}", "/data/user/0/{pkg}",
        "/sdcard/Android/data/{pkg}", "/data/misc/profiles/ref/{pkg}",
        "/data/misc/profiles/cur/0/{pkg}",
    )
    for step, pkg in _APP_DATA_PACKAGES:
        suffix = "/*" if pkg == "com.google.android.gms" else ""
        paths = " ".join(
            d.format(pkg=pkg) + suffix for d in data_dirs
        )
        _shell(executor, step, f"rm -rf {paths}", timeout=_LONG_TIMEOUT)

    # 步骤 288: ls -1 /data/app/*
    _shell(executor, 288, "ls -1 /data/app/*")

    # 步骤 289: rm -rf vending app cache
    _shell(executor, 289,
           "rm -rf /data/app/~~fc3-AkLo_0lQ65l77BoqoA==/com.android.vending-NDADmVdHRR3Q1DbjfL4wlQ==/*")

    # 步骤 290: ls
    _shell(executor, 290, "ls -1 /data/app/*")

    # 步骤 291: rm -rf gms app cache
    _shell(executor, 291,
           "rm -rf /data/app/~~XWmL507Qg9jSo49loqFFCg==/com.google.android.gms--yMlngOCRVCV9oqJYgpqEg==/*")

    # 步骤 292-293: ls
    _shell(executor, 292, "ls -1 /data/app/*")
    _shell(executor, 293, "ls -1 /data/app/*")

    # 步骤 294: 大批量系统目录清理
    cleanup_paths = (
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
        "/data/system/device_policies.xml /data/system/cachequota.xml "
        "/data/system/appops.xml /data/system/entropy.dat "
        "/data/system/last-fstrim /data/system/last-header.txt "
        "/data/system/log-files.xml /data/system/syncmanager-log/* "
        "/data/system/usagestats/* /data/system/procstats/* "
        "/data/system/netstats/* /data/system/graphicsstats/*"
    )
    _shell(executor, 294, f"rm -rf {cleanup_paths}", timeout=_LONG_TIMEOUT)

    # 步骤 295: find ... | grep -v 'spblob' | xargs rm -rf
    _shell(executor, 295,
           "find /data/system_de/0/* | grep -v 'spblob' | xargs rm -rf",
           timeout=_LONG_TIMEOUT)

    # 步骤 296-297: push packages.xml
    logger.info("步骤 296-297: push packages.xml")
    pkg_ok = modify_packages_xml(executor, work_dir)

    # 步骤 298-303: find touch APK 时间戳
    for step, path in _TOUCH_PATHS:
        _shell(executor, step, f"find {path} -exec touch -m -a {{}} +")

    # 步骤 304-307: rm -rf 清理
    _shell(executor, 304, "rm -rf /system/addon.d")
    _shell(executor, 305, "rm -rf /system/bin/install-recovery.sh")
    _shell(executor, 306, "rm -rf /vendor/bin/install-recovery.sh")
    _shell(executor, 307, "rm -rf /sdcard/TWRP")

    # 步骤 308-310: push settings_global.xml + restorecon
    logger.info("步骤 308-309: push settings_global.xml")
    global_ok = modify_settings_global_xml(executor, work_dir, device_name)
    _shell(executor, 310,
           "restorecon -Rv /data/system/users/0/settings_global.xml")

    # 步骤 311-313: push settings_secure.xml + restorecon
    logger.info("步骤 311-312: push settings_secure.xml")
    secure_ok = modify_settings_secure_xml(executor, work_dir, android_id)
    _shell(executor, 313,
           "restorecon -Rv /data/system/users/0/settings_secure.xml")

    # 步骤 314: restorecon -Rv /data/system
    _shell(executor, 314, "restorecon -Rv /data/system")

    # 步骤 315: restorecon -Rv /data/data/com.android.providers.settings/*
    _shell(executor, 315,
           "restorecon -Rv /data/data/com.android.providers.settings/*")

    settings_ok = global_ok and secure_ok
    return pkg_ok, settings_ok, True


def reboot_and_verify(
    executor: AdbExecutor,
) -> tuple[bool, str, str, str, bool, tuple[str, ...]]:
    """阶段 L: 步骤 316-332."""

    # 步骤 316: reboot
    logger.info("步骤 316: reboot")
    executor.reboot(timeout=_SHELL_TIMEOUT)
    logger.info("  重启命令已发送")

    # 步骤 317-327: 轮询 getprop init.svc.bootanim
    logger.info("步骤 317-327: 等待启动完成...")
    boot_ok = False
    for attempt in range(60):
        time.sleep(5)
        try:
            result = executor.run_shell(
                "getprop init.svc.bootanim", timeout=10,
            )
            status = result.stdout.strip() if result.success else ""
            logger.info("  bootanim: %s", status)
            if status == "stopped":
                boot_ok = True
                break
        except Exception:
            pass

    if not boot_ok:
        logger.error("  启动超时")

    # 步骤 328: getprop ro.product.brand
    logger.info("步骤 328: getprop ro.product.brand")
    result = executor.run_shell("getprop ro.product.brand", timeout=_SHELL_TIMEOUT)
    brand = result.stdout.strip() if result.success else ""
    logger.info("  品牌: %s", brand)

    # 步骤 329: getprop ro.product.model
    logger.info("步骤 329: getprop ro.product.model")
    result = executor.run_shell("getprop ro.product.model", timeout=_SHELL_TIMEOUT)
    model = result.stdout.strip() if result.success else ""
    logger.info("  型号: %s", model)

    # 步骤 330: getprop ro.build.version.release
    logger.info("步骤 330: getprop ro.build.version.release")
    result = executor.run_shell("getprop ro.build.version.release", timeout=_SHELL_TIMEOUT)
    version = result.stdout.strip() if result.success else ""
    logger.info("  版本: %s", version)

    # 步骤 331: pm enable com.android.vending
    logger.info("步骤 331: pm enable com.android.vending")
    result = executor.run_shell("pm enable com.android.vending", timeout=_SHELL_TIMEOUT)
    vending_ok = result.success
    logger.info("  输出: %s", result.stdout)

    # 步骤 332: pm list packages -3
    logger.info("步骤 332: pm list packages -3")
    result = executor.run_shell("pm list packages -3", timeout=_SHELL_TIMEOUT)
    packages: list[str] = []
    if result.stdout:
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                packages.append(line[len("package:"):])
    logger.info("  第三方包: %s", packages)

    return boot_ok, brand, model, version, vending_ok, tuple(packages)
