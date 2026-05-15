"""
Import File to Phone — 核心业务逻辑。

严格按照 13.0-Import File to Phone.pcapng 抓包还原的命令序列，
将本地文件推送到设备并触发媒体扫描。

抓包命令序列（3 步）：
    1. sync: → adb push <file> /sdcard/<file>
       - SYNC 协议：STA2 检查目标 → SEND 传输 → OKAY 确认 → QUIT
    2. shell,v2,raw:content call --uri content://media/
       --method scan_volume --arg external_primary
       - 通过 ContentProvider 触发 MediaStore 卷扫描
       - 响应：Result: Bundle[{}]
    3. shell,v2,raw:am broadcast
       -a android.intent.action.MEDIA_SCANNER_SCAN_FILE
       -d file:///sdcard
       - 发送媒体扫描广播，确保文件被索引
       - 响应：Broadcast completed: result=0

参考：
- https://docs.python.org/3/library/subprocess.html#subprocess.run
- https://docs.python.org/3/library/pathlib.html
- https://docs.python.org/3/library/logging.html
"""

from __future__ import annotations

import logging
from pathlib import Path

from michanger.common import AdbError, AdbExecutor
from .models import FileInfo, FileTransferResult, ImportResult

logger = logging.getLogger(__name__)

# 设备端目标目录（与 pcapng 中 STA2 检查的路径一致）
_REMOTE_DIR: str = "/sdcard"

# 媒体扫描命令（与 pcapng Step 2 完全一致）
_MEDIA_SCAN_COMMAND: str = (
    "content call --uri content://media/"
    " --method scan_volume --arg external_primary"
)

# 媒体广播命令（与 pcapng Step 3 完全一致）
_MEDIA_BROADCAST_COMMAND: str = (
    "am broadcast"
    " -a android.intent.action.MEDIA_SCANNER_SCAN_FILE"
    " -d file:///sdcard"
)


# ------------------------------------------------------------------
# 内部辅助函数
# ------------------------------------------------------------------


def _collect_files(
    push_dir: Path,
    remote_dir: str,
) -> tuple[FileInfo, ...]:
    """收集待推送文件列表。

    遍历目录中所有文件（不递归子目录），按文件名排序保证确定性。

    Args:
        push_dir: 本地推送文件目录
        remote_dir: 设备端目标目录

    Returns:
        文件信息的不可变元组

    Raises:
        AdbError: 目录为空或不存在
    """
    resolved = push_dir.resolve()
    if not resolved.is_dir():
        raise AdbError(f"推送目录不存在：{resolved}")

    files = sorted(
        (f for f in resolved.iterdir() if f.is_file()),
        key=lambda f: f.name,
    )

    if not files:
        raise AdbError(f"推送目录为空：{resolved}")

    return tuple(
        FileInfo(
            name=f.name,
            local_path=str(f),
            remote_path=f"{remote_dir}/{f.name}",
            size_bytes=f.stat().st_size,
        )
        for f in files
    )


def _push_files(
    adb: AdbExecutor,
    files: tuple[FileInfo, ...],
) -> tuple[FileTransferResult, ...]:
    """Phase 1: 逐个推送文件到设备。

    与 pcapng 中的 sync: → STA2 + SEND + OKAY 流程对应。
    adb push 命令内部自动执行 SYNC 协议。

    Args:
        adb: ADB 执行器
        files: 待推送文件列表

    Returns:
        各文件传输结果的不可变元组
    """
    results: list[FileTransferResult] = []

    for file_info in files:
        logger.info(
            "推送文件: %s → %s (%.2f KB)",
            file_info.name,
            file_info.remote_path,
            file_info.size_bytes / 1024,
        )

        try:
            result = adb.push(
                local_path=Path(file_info.local_path),
                remote_path=file_info.remote_path,
            )

            if result.success:
                logger.info("推送成功: %s — %s", file_info.name, result.output)
                results.append(FileTransferResult(
                    file_info=file_info,
                    success=True,
                    message=result.output,
                ))
            else:
                error_msg = result.stderr or result.stdout or "未知错误"
                logger.error("推送失败: %s — %s", file_info.name, error_msg)
                results.append(FileTransferResult(
                    file_info=file_info,
                    success=False,
                    message=error_msg,
                ))
        except AdbError as exc:
            logger.error("推送异常: %s — %s", file_info.name, exc)
            results.append(FileTransferResult(
                file_info=file_info,
                success=False,
                message=str(exc),
            ))

    return tuple(results)


def _scan_media_volume(adb: AdbExecutor) -> bool:
    """Phase 2: 通过 ContentProvider 触发媒体卷扫描。

    对应 pcapng Step 2：
        shell,v2,raw:content call --uri content://media/
        --method scan_volume --arg external_primary
    预期响应：Result: Bundle[{}]

    Args:
        adb: ADB 执行器

    Returns:
        True 如果扫描成功
    """
    logger.info("触发媒体卷扫描: content call scan_volume")

    result = adb.shell(_MEDIA_SCAN_COMMAND)

    if result.success:
        logger.info("媒体卷扫描成功: %s", result.output)
        return True

    logger.error("媒体卷扫描失败: %s", result.output)
    return False


def _broadcast_media_scan(adb: AdbExecutor) -> bool:
    """Phase 3: 发送媒体扫描广播。

    对应 pcapng Step 3：
        shell,v2,raw:am broadcast
        -a android.intent.action.MEDIA_SCANNER_SCAN_FILE
        -d file:///sdcard
    预期响应：Broadcast completed: result=0

    Args:
        adb: ADB 执行器

    Returns:
        True 如果广播成功
    """
    logger.info("发送媒体扫描广播: MEDIA_SCANNER_SCAN_FILE")

    result = adb.shell(_MEDIA_BROADCAST_COMMAND)

    if result.success and "Broadcast completed" in result.output:
        logger.info("媒体扫描广播成功: %s", result.output)
        return True

    logger.error("媒体扫描广播失败: %s", result.output)
    return False


# ------------------------------------------------------------------
# 公共 API
# ------------------------------------------------------------------


def import_files(
    *,
    adb_path: Path,
    serial: str,
    push_dir: Path,
    remote_dir: str = _REMOTE_DIR,
) -> ImportResult:
    """执行完整的 Import File to Phone 流程。

    严格按照 13.0-Import File to Phone.pcapng 还原的 3 步命令序列：
    1. adb push — 推送文件到 /sdcard/
    2. content call scan_volume — MediaStore 卷扫描
    3. am broadcast MEDIA_SCANNER_SCAN_FILE — 媒体扫描广播

    Args:
        adb_path: adb 可执行文件路径
        serial: 设备序列号
        push_dir: 本地推送文件目录
        remote_dir: 设备端目标目录（默认 /sdcard）

    Returns:
        ImportResult 包含各文件传输结果和媒体扫描状态

    Raises:
        AdbError: adb 不存在、设备不可达或目录为空
    """
    logger.info(
        "===== Import File to Phone 开始 ===== serial=%s", serial,
    )

    adb = AdbExecutor(adb_path=adb_path, serial=serial)

    # 收集待推送文件
    files = _collect_files(push_dir, remote_dir)
    logger.info(
        "共 %d 个文件待推送，总大小 %.2f KB",
        len(files),
        sum(f.size_bytes for f in files) / 1024,
    )

    # Phase 1: 推送文件（对应 pcapng Step 1）
    file_results = _push_files(adb, files)
    all_pushed = all(r.success for r in file_results)

    if not all_pushed:
        logger.error(
            "文件推送不完整: %d/%d 成功",
            sum(1 for r in file_results if r.success),
            len(file_results),
        )

    # Phase 2: 媒体卷扫描（对应 pcapng Step 2）
    media_scan_ok = _scan_media_volume(adb)

    # Phase 3: 媒体扫描广播（对应 pcapng Step 3）
    media_broadcast_ok = _broadcast_media_scan(adb)

    overall_success = all_pushed and media_scan_ok and media_broadcast_ok

    logger.info(
        "===== Import File to Phone %s =====",
        "成功" if overall_success else "失败",
    )

    return ImportResult(
        serial=serial,
        file_results=file_results,
        media_scan_success=media_scan_ok,
        media_broadcast_success=media_broadcast_ok,
        success=overall_success,
    )
