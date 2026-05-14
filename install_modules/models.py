"""Install Modules 数据模型.

仅包含本模块所需的不可变数据类。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModuleInstallDetail:
    """单个 Magisk 模块的安装结果.

    属性:
        filename: 模块文件名（例如 "1.Zygisk-Next-1.3.3.zip"）。
        remote_path: 设备上的完整路径。
        install_output: magisk --install-module 的完整标准输出。
        install_success: 输出是否包含 "- Done" 标志。
    """

    filename: str
    remote_path: str
    install_output: str
    install_success: bool


@dataclass(frozen=True)
class ModulesInstallResult:
    """Install Modules 的完整执行结果.

    属性:
        root_verified: 步骤 1 — su -c "id" 是否确认 uid=0(root)。
        root_uid: 步骤 1 — id 命令的完整输出。
        remove_modules_success: 步骤 2 — magisk --remove-modules -n 是否成功。
        clean_data_success: 步骤 3 — rm -rf /data/adb/modules/* 是否成功。
        clean_sdcard_success: 步骤 4 — rm -rf /sdcard/modules 是否成功。
        pushed_files: 步骤 5 — 成功推送的文件名元组。
        push_success: 步骤 5 — 是否所有文件都推送成功。
        verified_files: 步骤 6 — ls 验证的设备文件路径元组。
        module_results: 步骤 7-10 — 各模块安装结果元组。
        cleanup_success: 步骤 11 — 最终清理是否成功。
        all_modules_installed: 所有模块是否都安装成功。
    """

    root_verified: bool
    root_uid: str
    remove_modules_success: bool
    clean_data_success: bool
    clean_sdcard_success: bool
    pushed_files: tuple[str, ...]
    push_success: bool
    verified_files: tuple[str, ...]
    module_results: tuple[ModuleInstallDetail, ...]
    cleanup_success: bool
    all_modules_installed: bool
