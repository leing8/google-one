"""Install Magisk 数据模型.

仅包含本模块所需的不可变数据类。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MagiskInstallResult:
    """Install Magisk && Root Phone 的完整执行结果.

    严格对应 5.0-Install Magisk && Root Phone.pcapng 抓包日志中的 6 步操作。

    属性:
        twrp_version: TWRP 版本号（例如 "3.6.2_11-0"）。
        magisk_zip_path: 本地 Magisk.zip 文件路径。
        magisk_version: Magisk 版本号（例如 "30.1"），从安装输出中提取。
        push_success: 步骤 3 push 是否成功。
        install_output: 步骤 4 twrp install 的完整输出文本。
        install_success: 步骤 4 安装是否成功（输出包含 "Done"）。
        cleanup_success: 步骤 5 rm 清理是否成功。
    """

    twrp_version: str
    magisk_zip_path: str
    magisk_version: str
    push_success: bool
    install_output: str
    install_success: bool
    cleanup_success: bool
