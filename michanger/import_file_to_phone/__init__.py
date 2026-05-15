"""
Import File to Phone — 文件导入模块。

严格按照 13.0-Import File to Phone.pcapng 抓包还原的命令序列，
将本地文件推送到设备 /sdcard/ 并触发媒体扫描。

命令序列（3 步）：
    1. adb push <file> /sdcard/<file>       → SYNC 协议文件推送
    2. adb shell content call scan_volume   → MediaStore 卷扫描
    3. adb shell am broadcast MEDIA_SCANNER → 媒体扫描广播

公共 API：
    - import_files(): 执行完整文件导入流程
    - ImportResult: 整体导入结果
    - FileTransferResult: 单文件传输结果
    - FileInfo: 文件信息
"""

from .import_file_to_phone import import_files
from .models import FileInfo, FileTransferResult, ImportResult

__all__ = [
    "FileInfo",
    "FileTransferResult",
    "ImportResult",
    "import_files",
]
