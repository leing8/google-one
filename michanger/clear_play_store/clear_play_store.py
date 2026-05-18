"""
Clear Google Play Store — 核心业务逻辑。

严格按照 18.0-Clear Google Play Store.pcapng 抓包还原的命令序列，
清除 Google Play Store（com.android.vending）的应用数据。

pcapng 命令序列（1 步）：
    Step 1: shell,v2,raw:pm clear com.android.vending  → "Success" [EXIT:0]

说明：
    pm clear 会清除指定应用的所有用户数据、缓存和已注册的账户信息。
    对于 Google Play Store (com.android.vending)，这会：
    - 清除所有登录的 Google 账户缓存
    - 重置 Play Store 的本地数据
    - 清除下载队列和更新状态

    此命令在设备伪装完成后执行，确保 Play Store
    下次启动时使用新的设备身份。

参考：
- https://docs.python.org/3/library/subprocess.html#subprocess.run
- https://docs.python.org/3/library/logging.html
"""

from __future__ import annotations

import logging
from pathlib import Path

from michanger.common import AdbExecutor
from .models import ClearPlayStoreResult

logger = logging.getLogger(__name__)

# Google Play Store 包名
_PLAY_STORE_PACKAGE: str = "com.android.vending"


def clear_play_store(
    *,
    adb_path: Path,
    serial: str,
) -> ClearPlayStoreResult:
    """执行 Clear Google Play Store 完整流程。

    严格按照 18.0-Clear Google Play Store.pcapng 还原的 1 步命令：
    pm clear com.android.vending

    Args:
        adb_path: adb 可执行文件路径
        serial: 设备序列号

    Returns:
        ClearPlayStoreResult 包含清除结果

    Raises:
        AdbError: ADB 命令执行失败
    """
    adb = AdbExecutor(adb_path=adb_path, serial=serial)

    logger.info("=" * 60)
    logger.info(
        "Clear Google Play Store — 设备 [%s]", serial
    )
    logger.info("=" * 60)

    # Step 1: pm clear com.android.vending（pcapng Step 1）
    logger.info(
        "[Step 1/1] 清除 Play Store 数据: pm clear %s",
        _PLAY_STORE_PACKAGE,
    )
    result = adb.shell(f"pm clear {_PLAY_STORE_PACKAGE}")
    pm_output = result.output.strip()
    clear_ok = result.success and "Success" in pm_output

    logger.info(
        "pm clear %s → %s",
        _PLAY_STORE_PACKAGE,
        pm_output,
    )

    logger.info("=" * 60)
    logger.info(
        "Clear Google Play Store 完成 — %s (1 条命令)",
        pm_output,
    )
    logger.info("=" * 60)

    return ClearPlayStoreResult(
        serial=serial,
        pm_clear_output=pm_output,
        clear_success=clear_ok,
        success=clear_ok,
        commands_executed=1,
    )
