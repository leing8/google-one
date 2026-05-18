"""
Clean All Proxy — 核心业务逻辑。

严格按照 17.0-Clean All Proxy.pcapng 抓包还原的命令序列，
清除设备上的全局 HTTP 代理设置。

pcapng 命令序列（1 步）：
    Step 1: shell,v2,raw:settings put global http_proxy :0  → [EXIT:0]

说明：
    Android 使用 `:0` 作为代理清除的特殊值（host 为空, port 为 0），
    等效于移除全局代理设置。这是 Android settings 命令的标准用法。

    与 16.0-Config Proxy.pcapng 形成完整的代理生命周期：
    - 16.0: settings put global http_proxy host:port  → 设置代理
    - 17.0: settings put global http_proxy :0          → 清除代理

参考：
- https://docs.python.org/3/library/subprocess.html#subprocess.run
- https://docs.python.org/3/library/logging.html
- https://developer.android.com/reference/android/provider/Settings.Global
"""

from __future__ import annotations

import logging
from pathlib import Path

from michanger.common import AdbExecutor
from .models import CleanProxyResult

logger = logging.getLogger(__name__)

# Android 全局代理设置键名
_PROXY_SETTING_KEY: str = "global http_proxy"

# 清除代理的特殊值（host 为空, port 为 0）
_PROXY_CLEAR_VALUE: str = ":0"


def clean_all_proxy(
    *,
    adb_path: Path,
    serial: str,
) -> CleanProxyResult:
    """执行 Clean All Proxy 完整流程。

    严格按照 17.0-Clean All Proxy.pcapng 还原的 1 步命令序列：
    settings put global http_proxy :0

    Args:
        adb_path: adb 可执行文件路径
        serial: 设备序列号

    Returns:
        CleanProxyResult 包含清除结果

    Raises:
        AdbError: ADB 命令执行失败
    """
    adb = AdbExecutor(adb_path=adb_path, serial=serial)

    logger.info("=" * 60)
    logger.info("Clean All Proxy — 设备 [%s]", serial)
    logger.info("=" * 60)

    # Step 1: 清除代理（pcapng Step 1）
    logger.info(
        "[Step 1/1] 清除全局代理: "
        "settings put %s %s",
        _PROXY_SETTING_KEY,
        _PROXY_CLEAR_VALUE,
    )
    result = adb.shell(
        f"settings put {_PROXY_SETTING_KEY} {_PROXY_CLEAR_VALUE}"
    )
    clean_ok = result.success
    logger.info(
        "settings put → %s",
        "成功" if clean_ok else f"失败: {result.output}",
    )

    logger.info("=" * 60)
    logger.info(
        "Clean All Proxy 完成 — %s (1 条命令)",
        "成功" if clean_ok else "失败",
    )
    logger.info("=" * 60)

    return CleanProxyResult(
        serial=serial,
        clean_success=clean_ok,
        success=clean_ok,
        commands_executed=1,
    )
