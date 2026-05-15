"""
Update Integrity Fix 数据模型。

所有模型均使用 frozen=True 保证不可变性（PEP 557）。

参考：
- https://docs.python.org/3/library/dataclasses.html
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModuleFileInfo:
    """单个模块文件信息。

    Attributes:
        name: 模块显示名称（如 "Tricky Store OSS"）
        local_path: 本地文件绝对路径
        remote_path: 设备端目标路径（pcapng 中统一为 /sdcard/modules/fix.zip）
        size_bytes: 文件大小（字节）
        download_url: 下载地址（Google Drive）
    """

    name: str
    local_path: str
    remote_path: str
    size_bytes: int
    download_url: str

    @property
    def size_mb(self) -> float:
        """文件大小（MB）。"""
        return self.size_bytes / (1024 * 1024)


@dataclass(frozen=True)
class ModuleInstallResult:
    """单个模块的安装结果。

    从 magisk --install-module 命令的输出解析。

    Attributes:
        module_name: 模块显示名称
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
class SystemConfigResult:
    """系统配置文件写入结果。

    Attributes:
        config_written: /system/etc/config 是否写入成功
        config_hash: 写入的 config 哈希值
        security_patch_written: security_patch.txt 是否写入成功
        security_patch_value: 写入的 security_patch 值（如 "all=2026-04-05"）
    """

    config_written: bool
    config_hash: str
    security_patch_written: bool
    security_patch_value: str


@dataclass(frozen=True)
class UpdateIntegrityFixResult:
    """整体 Update Integrity Fix 结果。

    Attributes:
        root_verified: root 权限验证是否通过
        modules_cleaned: 旧模块文件是否已清理
        tricky_store_result: Tricky Store OSS 安装结果
        pif_premium_result: OneChanger PIF Premium 安装结果
        system_config: 系统配置写入结果
        reboot_initiated: 是否已发起重启
        success: 整体是否成功
    """

    root_verified: bool
    modules_cleaned: bool
    tricky_store_result: ModuleInstallResult | None
    pif_premium_result: ModuleInstallResult | None
    system_config: SystemConfigResult | None
    reboot_initiated: bool
    success: bool
