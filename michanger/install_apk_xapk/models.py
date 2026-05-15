"""
Install Apk-XApk 数据模型。

所有模型均使用 frozen=True 保证不可变性（PEP 557）。

参考：
- https://docs.python.org/3/library/dataclasses.html
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ApkInfo:
    """单个 APK 文件信息。

    Attributes:
        name: APK 文件名（如 "com.google.android.apps.subscriptions.red.apk"）
        path: 本地文件绝对路径
        size_bytes: 文件大小（字节）
        split_id: manifest.json 中的 id（如 "base"、"config.ar"），
                  None 表示不来自 XAPK manifest
    """

    name: str
    path: Path
    size_bytes: int
    split_id: str | None = None

    @property
    def size_mb(self) -> float:
        """文件大小（MB）。"""
        return self.size_bytes / (1024 * 1024)


@dataclass(frozen=True)
class XapkInfo:
    """XAPK 包信息（解析自 manifest.json）。

    Attributes:
        xapk_name: XAPK 文件名
        package_name: Android 包名（如 "com.google.android.apps.subscriptions.red"）
        version_name: 版本名称（如 "1.305.896021434"）
        version_code: 版本号（如 633778）
        apk_files: 分割 APK 文件信息列表（base 在前，config 在后）
        total_size_bytes: 所有 APK 文件的总大小
    """

    xapk_name: str
    package_name: str
    version_name: str
    version_code: int
    apk_files: tuple[ApkInfo, ...]
    total_size_bytes: int

    @property
    def total_size_mb(self) -> float:
        """所有 APK 文件总大小（MB）。"""
        return self.total_size_bytes / (1024 * 1024)

    @property
    def apk_count(self) -> int:
        """APK 文件数量。"""
        return len(self.apk_files)


@dataclass(frozen=True)
class PackageInstallResult:
    """单个包（APK 或 XAPK）的安装结果。

    Attributes:
        package_name: Android 包名
        xapk_name: 来源 XAPK 文件名（普通 APK 为 None）
        apk_count: 安装的 APK 文件数量
        install_output: adb install-multiple 的完整输出
        success: 安装是否成功
        error_message: 失败时的错误信息
    """

    package_name: str
    xapk_name: str | None
    apk_count: int
    install_output: str
    success: bool
    error_message: str = ""


@dataclass(frozen=True)
class InstallApkXapkResult:
    """整体 APK/XAPK 安装结果。

    Attributes:
        install_results: 各包安装结果列表
        play_store_enabled: Google Play Store 是否已启用
        success: 整体安装是否成功（所有包安装 + Play Store 启用）
    """

    install_results: tuple[PackageInstallResult, ...]
    play_store_enabled: bool
    success: bool

    @property
    def success_count(self) -> int:
        """安装成功的包数量。"""
        return sum(1 for r in self.install_results if r.success)

    @property
    def failure_count(self) -> int:
        """安装失败的包数量。"""
        return sum(1 for r in self.install_results if not r.success)

    @property
    def total_count(self) -> int:
        """总包数量。"""
        return len(self.install_results)
