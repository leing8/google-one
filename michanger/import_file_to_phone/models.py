"""
Import File to Phone — 数据模型。

所有模型均使用 frozen=True 保证不可变性（PEP 557）。

参考：
- https://docs.python.org/3/library/dataclasses.html
- 13.0-Import File to Phone.pcapng 抓包分析
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FileInfo:
    """待推送文件信息。

    Attributes:
        name: 文件名（如 "noavatar_20260514_113359_480884.png"）
        local_path: 本地文件绝对路径
        remote_path: 设备端目标路径（如 "/sdcard/noavatar_20260514_113359_480884.png"）
        size_bytes: 文件大小（字节）
    """

    name: str
    local_path: str
    remote_path: str
    size_bytes: int

    @property
    def size_mb(self) -> float:
        """文件大小（MB）。"""
        return self.size_bytes / (1024 * 1024)


@dataclass(frozen=True)
class FileTransferResult:
    """单个文件传输结果。

    Attributes:
        file_info: 文件信息
        success: 传输是否成功
        message: 结果描述（成功时为 adb push 输出，失败时为错误信息）
    """

    file_info: FileInfo
    success: bool
    message: str


@dataclass(frozen=True)
class ImportResult:
    """完整 Import File to Phone 执行结果。

    Attributes:
        serial: 设备序列号
        file_results: 各文件传输结果（不可变元组）
        media_scan_success: 媒体卷扫描是否成功
        media_broadcast_success: 媒体扫描广播是否成功
        success: 整体是否成功（所有文件推送 + 媒体扫描均成功）
    """

    serial: str
    file_results: tuple[FileTransferResult, ...]
    media_scan_success: bool
    media_broadcast_success: bool
    success: bool

    @property
    def total_files(self) -> int:
        """总文件数。"""
        return len(self.file_results)

    @property
    def success_count(self) -> int:
        """成功传输的文件数。"""
        return sum(1 for r in self.file_results if r.success)

    @property
    def failure_count(self) -> int:
        """传输失败的文件数。"""
        return sum(1 for r in self.file_results if not r.success)

    @property
    def total_size_bytes(self) -> int:
        """所有文件的总大小（字节）。"""
        return sum(r.file_info.size_bytes for r in self.file_results)
