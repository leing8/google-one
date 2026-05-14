"""
Install Modules 数据模型。

所有模型均使用 frozen=True 保证不可变性（PEP 557）。

参考：
- https://docs.python.org/3/library/dataclasses.html
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModuleInfo:
    """单个 Magisk 模块文件信息。

    Attributes:
        name: 模块文件名（如 "1.Zygisk-Next-1.3.3.zip"）
        local_path: 本地文件绝对路径
        remote_path: 设备端目标路径（如 "/sdcard/modules/1.Zygisk-Next-1.3.3.zip"）
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
class ModuleInstallResult:
    """单个模块的安装结果。

    从 magisk --install-module 命令的输出解析。

    Attributes:
        module_name: 模块文件名
        boot_slot: 当前 boot slot（如 "_b"）
        platform: 设备平台（如 "arm64"）
        install_log: 完整安装日志行（不可变元组）
        success: 安装是否成功（基于 "- Done" 判断）
    """

    module_name: str
    boot_slot: str
    platform: str
    install_log: tuple[str, ...]
    success: bool


@dataclass(frozen=True)
class InstallModulesResult:
    """整体模块安装结果。

    Attributes:
        root_verified: root 权限验证是否通过
        modules_removed: 旧模块是否成功移除
        modules_pushed: 模块文件是否成功推送到设备
        pushed_modules: 推送的模块信息列表
        install_results: 各模块安装结果列表
        cleanup_done: 临时文件是否已清理
        reboot_initiated: 是否已发起重启
        success: 整体安装是否成功（所有模块均成功）
    """

    root_verified: bool
    modules_removed: bool
    modules_pushed: bool
    pushed_modules: tuple[ModuleInfo, ...]
    install_results: tuple[ModuleInstallResult, ...]
    cleanup_done: bool
    reboot_initiated: bool
    success: bool

    @property
    def success_count(self) -> int:
        """成功安装的模块数量。"""
        return sum(1 for r in self.install_results if r.success)

    @property
    def failure_count(self) -> int:
        """安装失败的模块数量。"""
        return sum(1 for r in self.install_results if not r.success)

    @property
    def total_count(self) -> int:
        """总模块数量。"""
        return len(self.install_results)
