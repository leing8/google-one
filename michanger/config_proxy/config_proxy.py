"""
Config Proxy — 核心业务逻辑。

严格按照 16.0-Config Proxy.pcapng 抓包还原的命令序列，
读取当前代理设置并配置新的 HTTP 代理。

pcapng 命令序列（2 步）：
    Step 1: shell:settings get global http_proxy          → 读取当前代理
    Step 2: shell,v2,raw:settings put global http_proxy   → 设置新代理

16.0 vs 16.1 对比：
    - 命令结构 100% 一致（仅代理地址不同）
    - 16.0: null → 192.168.31.182:10808（无代理 → 设置代理）
    - 16.1: 192.168.31.182:10808 → 192.168.31.72:7890（切换代理）
    - 说明：无论当前是否有代理，都直接 put 新值

参考：
- https://docs.python.org/3/library/subprocess.html#subprocess.run
- https://docs.python.org/3/library/logging.html
- https://developer.android.com/reference/android/provider/Settings.Global
"""

from __future__ import annotations

import logging
from pathlib import Path

from michanger.common import AdbExecutor
from .models import ConfigProxyResult

logger = logging.getLogger(__name__)

# Android 全局代理设置键名
_PROXY_SETTING_KEY: str = "global http_proxy"


def _validate_proxy_address(proxy: str) -> None:
    """验证代理地址格式。

    合法格式: host:port（如 192.168.31.182:10808）

    Args:
        proxy: 代理地址字符串

    Raises:
        ValueError: 格式不合法
    """
    if ":" not in proxy:
        raise ValueError(
            f"代理地址格式错误（缺少端口）: {proxy!r}，"
            f"应为 host:port 格式"
        )

    host, _, port_str = proxy.rpartition(":")
    if not host:
        raise ValueError(
            f"代理地址格式错误（缺少主机）: {proxy!r}"
        )

    try:
        port = int(port_str)
    except ValueError:
        raise ValueError(
            f"代理端口不是数字: {port_str!r}"
        ) from None

    if not (1 <= port <= 65535):
        raise ValueError(
            f"代理端口超出范围 (1-65535): {port}"
        )


def config_proxy(
    *,
    adb_path: Path,
    serial: str,
    proxy: str,
) -> ConfigProxyResult:
    """执行 Config Proxy 完整流程。

    严格按照 16.0-Config Proxy.pcapng 还原的 2 步命令序列：
    1. settings get global http_proxy → 读取当前代理
    2. settings put global http_proxy host:port → 设置新代理

    Args:
        adb_path: adb 可执行文件路径
        serial: 设备序列号
        proxy: 新代理地址（host:port 格式，如 "192.168.31.182:10808"）

    Returns:
        ConfigProxyResult 包含设置前后的代理值

    Raises:
        AdbError: ADB 命令执行失败
        ValueError: 代理地址格式不合法
    """
    _validate_proxy_address(proxy)

    adb = AdbExecutor(adb_path=adb_path, serial=serial)
    count = 0

    logger.info("=" * 60)
    logger.info("Config Proxy — 设备 [%s]", serial)
    logger.info("目标代理: %s", proxy)
    logger.info("=" * 60)

    # Step 1: 读取当前代理（pcapng Step 1）
    logger.info("[Step 1/2] 读取当前代理设置")
    get_result = adb.shell(
        f"settings get {_PROXY_SETTING_KEY}"
    )
    count += 1
    previous = get_result.output.strip()
    logger.info("当前代理: %s", previous)

    # Step 2: 设置新代理（pcapng Step 2）
    logger.info("[Step 2/2] 设置新代理: %s", proxy)
    put_result = adb.shell(
        f"settings put {_PROXY_SETTING_KEY} {proxy}"
    )
    count += 1
    set_ok = put_result.success
    logger.info(
        "settings put → %s",
        "成功" if set_ok else f"失败: {put_result.output}",
    )

    logger.info("=" * 60)
    logger.info(
        "Config Proxy 完成 — %s → %s (%d 条命令)",
        previous,
        proxy,
        count,
    )
    logger.info("=" * 60)

    return ConfigProxyResult(
        serial=serial,
        previous_proxy=previous,
        new_proxy=proxy,
        set_success=set_ok,
        success=set_ok,
        commands_executed=count,
    )
