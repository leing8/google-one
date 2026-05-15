"""
Google 账号管理器。

通过 Settings UI 自动化删除设备上的 Google 账号。
仅在 dumpsys account 检测到已登录的 Gmail 账号时触发。

来自 7.1-Randomly change device.pcapng 命令 B[3]-B[18]：
    3.  am force-stop com.google.android.gms
    4.  am start -a android.settings.SETTINGS
    5-6.   input swipe 向上滑动 ×2
    7-8.   uiautomator dump + cat（定位"账号"）
    9.     input tap（点击"账号"）
    10-11. uiautomator dump + cat（定位 Google 账号）
    12.    input tap（点击 Google 账号）
    13-14. uiautomator dump + cat（定位"删除"按钮）
    15.    input tap（点击"删除账号"）
    16-17. uiautomator dump + cat（定位确认按钮）
    18.    input tap（确认删除）

参考：
- https://developer.android.com/tools/adb
"""

from __future__ import annotations

import logging
import time

from michanger.common import AdbExecutor

logger = logging.getLogger(__name__)

# UI 操作间隔（秒）
_UI_WAIT: float = 1.5


def has_gmail_account(adb: AdbExecutor) -> bool:
    """检测设备是否存在已登录的 Gmail 账号。

    来自 pcapng 命令 2: dumpsys account | grep '@gmail.com, type=com.google}'
    - 7.0.1（首次）: 无响应 → False
    - 7.1（二次）: 返回 Account {...} → True

    Args:
        adb: ADB 执行器

    Returns:
        True 如果检测到 Gmail 账号
    """
    result = adb.shell(
        "dumpsys account | grep '@gmail.com, type=com.google}'"
    )
    found = "@gmail.com" in result.output
    logger.info("Gmail 账号检测: %s", "已登录" if found else "无")
    return found


def remove_google_account(adb: AdbExecutor) -> int:
    """通过 Settings UI 自动化删除 Google 账号。

    严格按照 7.1 pcapng 命令 B[3]-B[18] 的坐标执行。
    坐标基于 Pixel 4 XL 分辨率（1440×3040）。

    Args:
        adb: ADB 执行器

    Returns:
        执行的命令数量
    """
    count = 0

    # 1. 强制停止 GMS（命令 B[3]）
    adb.shell("am force-stop com.google.android.gms")
    count += 1

    # 2. 打开系统设置（命令 B[4]）
    adb.shell("am start -a android.settings.SETTINGS")
    count += 1
    time.sleep(_UI_WAIT)

    # 3. 向上滑动两次（命令 B[5-6]）
    adb.shell("input swipe 555 1755 555 855 80")
    count += 1
    time.sleep(0.5)
    adb.shell("input swipe 555 1755 555 855 80")
    count += 1
    time.sleep(_UI_WAIT)

    # 4. dump UI + 点击"账号"（命令 B[7-9]）
    adb.shell("uiautomator dump -x")
    count += 1
    adb.shell("cat /sdcard/window_dump.xml")
    count += 1
    adb.shell("input tap 373 1427")
    count += 1
    time.sleep(_UI_WAIT)

    # 5. dump UI + 点击 Google 账号（命令 B[10-12]）
    adb.shell("uiautomator dump -x")
    count += 1
    adb.shell("cat /sdcard/window_dump.xml")
    count += 1
    adb.shell("input tap 470 568")
    count += 1
    time.sleep(_UI_WAIT)

    # 6. dump UI + 点击"删除账号"（命令 B[13-15]）
    adb.shell("uiautomator dump -x")
    count += 1
    adb.shell("cat /sdcard/window_dump.xml")
    count += 1
    adb.shell("input tap 906 1413")
    count += 1
    time.sleep(_UI_WAIT)

    # 7. dump UI + 确认删除（命令 B[16-18]）
    adb.shell("uiautomator dump -x")
    count += 1
    adb.shell("cat /sdcard/window_dump.xml")
    count += 1
    adb.shell("input tap 904 1682")
    count += 1
    time.sleep(_UI_WAIT)

    # 8. 按 HOME 键回到桌面（命令 B[19]）
    adb.shell("input keyevent HOME")
    count += 1

    logger.info("Google 账号删除 UI 自动化完成: %d 条命令", count)
    return count
