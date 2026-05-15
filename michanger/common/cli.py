"""
CLI 通用工具 — 日志配置与设备自动检测。

从各子模块 __main__.py 中提取的共享函数，消除重复。

公共 API：
    - setup_logging(): 配置日志系统
    - auto_detect_serial(): 自动检测第一台可用设备的序列号
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from .adb_executor import list_devices


def setup_logging(*, verbose: bool) -> None:
    """配置日志系统。

    遵循 Python logging 官方最佳实践：
    - 使用 logging.basicConfig() 进行简单配置
    - 日志输出到 stderr（不干扰 stdout 的结构化输出）
    - 使用 %-style 格式化（logging 推荐）

    参考：https://docs.python.org/3/howto/logging.html

    Args:
        verbose: 是否启用 DEBUG 级别日志
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def auto_detect_serial(
    adb_path: Path,
    *,
    allow_recovery: bool = False,
) -> str:
    """自动检测第一台可用设备的序列号。

    Args:
        adb_path: adb 可执行文件路径
        allow_recovery: 是否允许 Recovery 模式设备作为候选

    Returns:
        设备序列号

    Raises:
        SystemExit: 无可用设备
    """
    devices = list_devices(adb_path=adb_path)

    if not devices:
        print("错误：未检测到已连接的 ADB 设备", file=sys.stderr)
        sys.exit(1)

    # 优先查找在线设备（state == "device"）
    online = [d for d in devices if d.is_online]
    if online:
        serial = online[0].serial
        print(f"自动检测到在线设备: {serial}", file=sys.stderr)
        return serial

    # 可选：查找 Recovery 模式设备
    if allow_recovery:
        recovery = [d for d in devices if d.is_recovery]
        if recovery:
            serial = recovery[0].serial
            print(
                f"自动检测到 Recovery 模式设备: {serial}",
                file=sys.stderr,
            )
            return serial

    # 列出所有设备状态
    for device in devices:
        print(
            f"  设备 {device.serial}: {device.state}",
            file=sys.stderr,
        )
    print("错误：无可用设备", file=sys.stderr)
    sys.exit(1)
