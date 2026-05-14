"""Randomly Change Device — 阶段 A-C: 设备检查、系统准备、Recovery 挂载.

严格按照 7.0-Randomly change device.pcapng 步骤 1-47。

阶段 A (步骤 1-2):   设备状态检查
阶段 B (步骤 3-31):  系统准备 & 清理应用数据
阶段 C (步骤 32-47): 重启到 Recovery & 挂载分区
"""

from __future__ import annotations

import logging

from .adb_executor import AdbExecutor

logger = logging.getLogger(__name__)

# 步骤 10-31: pm clear 的应用包列表（严格按照抓包日志顺序）
_PM_CLEAR_PACKAGES: tuple[str, ...] = (
    "com.android.vending",                    # 步骤 10
    "com.google.android.gms",                 # 步骤 11
    "com.android.chrome",                     # 步骤 12
    "com.google.android.gm",                  # 步骤 13
    "com.google.android.gsf",                 # 步骤 14
    "com.google.android.gsf.login",           # 步骤 15
    "com.google.android.ext.services",        # 步骤 16
    "com.google.android.onetimeinitializer",  # 步骤 17
    "com.google.android.ext.shared",          # 步骤 18
    "com.android.webview",                    # 步骤 19
    "com.google.android.webview",             # 步骤 20
    "org.lineageos.jelly",                    # 步骤 21
    "com.android.htmlviewer",                 # 步骤 22
    "com.google.android.gms.location.history",  # 步骤 23
    "com.google.android.apps.maps",           # 步骤 24
    "com.google.android.syncadapters.contacts",  # 步骤 25
    "com.google.android.ims",                 # 步骤 26
    "com.google.android.play.games",          # 步骤 27
    "com.google.android.backuptransport",     # 步骤 28
    "com.google.android.gms",                 # 步骤 29（重复清理）
    "com.google.android.gsf",                 # 步骤 30（重复清理）
    "com.android.vending",                    # 步骤 31（重复清理）
)

# 步骤 34-40: TWRP 挂载的分区列表
_TWRP_MOUNT_PARTITIONS: tuple[str, ...] = (
    "/system",      # 步骤 34
    "/system_ext",  # 步骤 35
    "/vendor",      # 步骤 36
    "/product",     # 步骤 37
    "/odm",         # 步骤 38
    "/persist",     # 步骤 39
    "/firmware",    # 步骤 40
)

# 步骤 41-47: remount rw 的分区列表
_REMOUNT_RW_PARTITIONS: tuple[str, ...] = (
    "/system_root",  # 步骤 41
    "/system_ext",   # 步骤 42
    "/vendor",       # 步骤 43
    "/product",      # 步骤 44
    "/odm",          # 步骤 45
    "/persist",      # 步骤 46
    "/firmware",     # 步骤 47
)

_SHELL_TIMEOUT: int = 30
_REBOOT_TIMEOUT: int = 30


# ── 阶段 A: 设备状态检查 (步骤 1-2) ──────────────────────────────


def check_device_state(
    executor: AdbExecutor,
) -> tuple[str, tuple[str, ...]]:
    """阶段 A: 检查设备状态.

    步骤 1: getprop persist.sys.locale
    步骤 2: dumpsys account | grep '@gmail.com, type=com.google}'

    返回:
        (locale, gmail_accounts) 元组。
    """
    # 步骤 1: getprop persist.sys.locale
    logger.info("步骤 1: getprop persist.sys.locale")
    result = executor.run_shell(
        "getprop persist.sys.locale",
        timeout=_SHELL_TIMEOUT,
    )
    locale = result.stdout if result.success else ""
    logger.info("  Locale: %s", locale or "(空)")

    # 步骤 2: dumpsys account | grep '@gmail.com, type=com.google}'
    logger.info("步骤 2: dumpsys account | grep '@gmail.com, type=com.google}'")
    result = executor.run_shell(
        "dumpsys account | grep '@gmail.com, type=com.google}'",
        timeout=_SHELL_TIMEOUT,
    )
    accounts: list[str] = []
    if result.stdout:
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped:
                accounts.append(stripped)
    logger.info("  Gmail 账户: %d 个", len(accounts))
    for acct in accounts:
        logger.info("    %s", acct)

    return locale, tuple(accounts)


# ── 阶段 B: 系统准备 & 清理应用数据 (步骤 3-31) ─────────────────


def prepare_system(executor: AdbExecutor) -> bool:
    """阶段 B: 系统准备和应用数据清理.

    返回:
        所有步骤是否成功（pm clear 允许 Failed）。
    """
    all_success = True

    # 步骤 3: input keyevent HOME
    logger.info("步骤 3: input keyevent HOME")
    result = executor.run_shell("input keyevent HOME", timeout=_SHELL_TIMEOUT)
    if not result.success:
        logger.warning("  HOME 键事件失败: %s", result.stderr)
        all_success = False
    else:
        logger.info("  [exit code: 0]")

    # 步骤 4: svc wifi disable
    logger.info("步骤 4: svc wifi disable")
    result = executor.run_shell("svc wifi disable", timeout=_SHELL_TIMEOUT)
    if not result.success:
        logger.warning("  WiFi 禁用失败: %s", result.stderr)
        all_success = False
    else:
        logger.info("  [exit code: 0]")

    # 步骤 5: settings put global wifi_on 1
    logger.info("步骤 5: settings put global wifi_on 1")
    result = executor.run_shell(
        "settings put global wifi_on 1",
        timeout=_SHELL_TIMEOUT,
    )
    if not result.success:
        logger.warning("  设置 wifi_on 失败: %s", result.stderr)
        all_success = False
    else:
        logger.info("  [exit code: 0]")

    # 步骤 6: settings put global development_settings_enabled 0
    logger.info("步骤 6: settings put global development_settings_enabled 0")
    result = executor.run_shell(
        "settings put global development_settings_enabled 0",
        timeout=_SHELL_TIMEOUT,
    )
    if not result.success:
        logger.warning("  设置 development_settings 失败: %s", result.stderr)
        all_success = False
    else:
        logger.info("  [exit code: 0]")

    # 步骤 7: settings put global auto_time_zone 0
    logger.info("步骤 7: settings put global auto_time_zone 0")
    result = executor.run_shell(
        "settings put global auto_time_zone 0",
        timeout=_SHELL_TIMEOUT,
    )
    if not result.success:
        logger.warning("  设置 auto_time_zone 失败: %s", result.stderr)
        all_success = False
    else:
        logger.info("  [exit code: 0]")

    # 步骤 8: service call alarm 3 s16 America/Adak
    logger.info("步骤 8: service call alarm 3 s16 America/Adak")
    result = executor.run_shell(
        "service call alarm 3 s16 America/Adak",
        timeout=_SHELL_TIMEOUT,
    )
    logger.info("  输出: %s", result.stdout)

    # 步骤 9: locksettings set-disabled True
    logger.info("步骤 9: locksettings set-disabled True")
    result = executor.run_shell(
        "locksettings set-disabled True",
        timeout=_SHELL_TIMEOUT,
    )
    logger.info("  输出: %s", result.stdout)

    # 步骤 10-31: pm clear × 22
    for i, package in enumerate(_PM_CLEAR_PACKAGES):
        step_num = 10 + i
        logger.info("步骤 %d: pm clear %s", step_num, package)
        result = executor.run_shell(
            f"pm clear {package}",
            timeout=_SHELL_TIMEOUT,
        )
        # pm clear 可能返回 Failed（包不存在），这在抓包日志中是正常的
        output = result.stdout if result.stdout else result.stderr
        logger.info("  输出: %s", output)

    return all_success


# ── 阶段 C: 重启到 Recovery & 挂载分区 (步骤 32-47) ──────────────


def reboot_and_mount(executor: AdbExecutor) -> bool:
    """阶段 C: 重启到 Recovery 模式并挂载所有分区.

    返回:
        Recovery 挂载是否完成。
    """
    # 步骤 32: reboot:recovery
    logger.info("步骤 32: reboot:recovery")
    executor.reboot("recovery", timeout=_REBOOT_TIMEOUT)
    logger.info("  重启到 Recovery 命令已发送")

    executor.wait_for_recovery(timeout=120, poll_interval=2.0)

    # 步骤 33: twrp --version
    logger.info("步骤 33: twrp --version")
    result = executor.run_shell("twrp --version", timeout=_SHELL_TIMEOUT)
    logger.info("  输出: %s", result.stdout)

    # 步骤 34-40: twrp mount × 7
    for i, partition in enumerate(_TWRP_MOUNT_PARTITIONS):
        step_num = 34 + i
        logger.info("步骤 %d: twrp mount %s", step_num, partition)
        result = executor.run_shell(
            f"twrp mount {partition}",
            timeout=_SHELL_TIMEOUT,
        )
        output = result.stdout if result.stdout else result.stderr
        logger.info("  输出: %s", output)

    # 步骤 41-47: mount -o remount,rw × 7
    for i, partition in enumerate(_REMOUNT_RW_PARTITIONS):
        step_num = 41 + i
        logger.info("步骤 %d: mount -o remount,rw %s", step_num, partition)
        result = executor.run_shell(
            f"mount -o remount,rw {partition}",
            timeout=_SHELL_TIMEOUT,
        )
        output = result.stdout if result.stdout else result.stderr
        if output:
            logger.info("  输出: %s", output)
        else:
            logger.info("  [exit code: %d]", result.returncode)

    return True
