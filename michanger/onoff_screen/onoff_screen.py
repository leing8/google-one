"""
ONOFF Screen — 核心业务逻辑。

严格按照 19.0-ONOFF Screen.pcapng 抓包还原的命令序列，
通过模拟电源键按下来切换屏幕开关状态。

pcapng 命令序列（1 步）：
    Step 1: shell,v2,raw:input keyevent KEYCODE_POWER  → [EXIT:0]

19.0 vs 19.1 对比：
    - 命令 100% 一致（input keyevent KEYCODE_POWER）
    - 19.0: 亮屏状态 → 熄屏（或反之）
    - 19.1: 熄屏状态 → 亮屏（或反之）
    - 说明：KEYCODE_POWER 是切换键，每次按下反转屏幕状态

参考：
- https://docs.python.org/3/library/subprocess.html#subprocess.run
- https://docs.python.org/3/library/logging.html
- https://developer.android.com/reference/android/view/KeyEvent#KEYCODE_POWER
"""

from __future__ import annotations

import logging
from pathlib import Path

from michanger.common import AdbExecutor
from .models import OnOffScreenResult

logger = logging.getLogger(__name__)

# Android 电源键事件名（与 pcapng 完全一致）
_POWER_KEYEVENT: str = "KEYCODE_POWER"


def onoff_screen(
    *,
    adb_path: Path,
    serial: str,
) -> OnOffScreenResult:
    """执行 ONOFF Screen 完整流程。

    严格按照 19.0-ONOFF Screen.pcapng 还原的 1 步命令：
    input keyevent KEYCODE_POWER

    每次调用切换屏幕状态（亮屏 ↔ 熄屏）。

    Args:
        adb_path: adb 可执行文件路径
        serial: 设备序列号

    Returns:
        OnOffScreenResult 包含执行结果

    Raises:
        AdbError: ADB 命令执行失败
    """
    adb = AdbExecutor(adb_path=adb_path, serial=serial)

    logger.info("=" * 60)
    logger.info("ONOFF Screen — 设备 [%s]", serial)
    logger.info("=" * 60)

    # Step 1: 模拟电源键（pcapng Step 1）
    logger.info(
        "[Step 1/1] 模拟电源键: input keyevent %s",
        _POWER_KEYEVENT,
    )
    result = adb.shell(
        f"input keyevent {_POWER_KEYEVENT}"
    )
    key_ok = result.success
    logger.info(
        "input keyevent → %s",
        "成功" if key_ok else f"失败: {result.output}",
    )

    logger.info("=" * 60)
    logger.info(
        "ONOFF Screen 完成 — %s (1 条命令)",
        "成功" if key_ok else "失败",
    )
    logger.info("=" * 60)

    return OnOffScreenResult(
        serial=serial,
        keyevent_success=key_ok,
        success=key_ok,
        commands_executed=1,
    )
