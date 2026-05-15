"""
Reboot — 设备重启核心逻辑。

严格按照 9.0-Reboot.pcapng 抓包还原的命令序列实现。
所有命令按原始顺序执行，不做任何跳过或短路优化。

pcapng 命令序列（12 帧）：
    Frame 1-6:   USB 枚举握手（设备识别 → Google Nexus/Pixel 0x18d1:0x4ee7）
    Frame 7-8:   ADB OPEN reboot:    → 打开重启服务通道
    Frame 9-10:  "reboot:\\0"         → 发送重启命令载荷（正常重启，无 target）
    Frame 11-12: OKAY                 → 设备确认开始重启

等效 ADB CLI：
    adb reboot

注意：
    - pcapng 中 Frame 11 OKAY 后无后续帧，说明抓包在设备开始重启时即结束
    - 因此本模块仅发送重启命令，不等待设备重新上线（与抓包行为一致）

参考：
- https://docs.python.org/3/library/subprocess.html#subprocess.run
- https://docs.python.org/3/library/subprocess.html#security-considerations
- https://docs.python.org/3/library/logging.html
"""

from __future__ import annotations

import logging
from pathlib import Path

from michanger.common import AdbExecutor
from .models import RebootResult

logger = logging.getLogger(__name__)


def reboot_device(
    adb_path: Path,
    serial: str,
) -> RebootResult:
    """执行设备重启。

    严格按照 9.0-Reboot.pcapng 抓包还原：
        1. adb reboot  → 对应 OPEN reboot: + OKAY

    pcapng 中无等待设备重连逻辑，因此本函数仅发送重启命令，
    不等待设备重新上线（与抓包行为一致）。

    遵循 Python 官方最佳实践：
    - subprocess.run() 参数列表传递（不使用 shell=True）
    - capture_output=True 捕获输出
    - encoding="utf-8" + errors="replace" 容错解码
    - timeout 防止无限挂起
    - creationflags=CREATE_NO_WINDOW（Windows 隐藏控制台）

    Args:
        adb_path: adb 可执行文件的绝对路径
        serial: 设备序列号（对应 adb -s 参数）

    Returns:
        RebootResult 不可变结果对象

    Raises:
        michanger.common.AdbError: adb 进程启动失败或超时
    """
    adb = AdbExecutor(adb_path=adb_path, serial=serial)

    logger.info("="*60)
    logger.info("Reboot 开始: 设备 [%s]", serial)
    logger.info("="*60)

    # ------------------------------------------------------------------
    # Step 1: adb reboot
    # 对应 pcapng Frame 7-12:
    #   Frame 7-8:   OPEN reboot:   (打开 ADB reboot 服务)
    #   Frame 9-10:  "reboot:\0"    (命令载荷: 正常重启, 无 target)
    #   Frame 11-12: OKAY           (设备确认)
    # 等效命令: adb -s {serial} reboot
    # ------------------------------------------------------------------
    logger.info("Step 1/1: adb reboot（正常重启，无 target 参数）")
    cmd_result = adb.reboot()

    result = RebootResult(
        serial=serial,
        success=cmd_result.success,
        command=cmd_result.command,
        stdout=cmd_result.stdout,
        stderr=cmd_result.stderr,
        returncode=cmd_result.returncode,
    )

    if result.success:
        logger.info("重启命令已发送，设备开始重启")
    else:
        logger.error(
            "重启命令失败: returncode=%d, stderr=%r",
            result.returncode,
            result.stderr[:200],
        )

    logger.info("="*60)
    logger.info("Reboot 完成: 设备 [%s], success=%s", serial, result.success)
    logger.info("="*60)

    return result
