"""
Update Integrity Fix — 更新 Integrity Fix 模块。

严格按照 8.0-Update Integrity Fix.pcapng 抓包还原的命令序列，
逐个安装 Tricky Store OSS 和 OneChanger PIF Premium 模块，
并写入系统配置（config 哈希 + security_patch 日期）。

命令序列（28 步）：
    Phase A: Root 验证 + 清理
        1.  shell:su -c "id"                          → 验证 root
        2.  shell:rm -rf /sdcard/modules/*.zip        → 清理旧模块
    Phase B: Tricky Store OSS
        3.  adb push fix.zip → /sdcard/modules/fix.zip
        4.  shell:ls -1 /sdcard/modules/*.zip         → 验证
        5.  shell:su -c "magisk --install-module ..."  → 安装
        6-7. shell:rm -rf /sdcard/modules/            → 清理
    Phase C: OneChanger PIF Premium
        8.  adb push fix.zip → /sdcard/modules/fix.zip
        9.  shell:ls -1 /sdcard/modules/*.zip         → 验证
        10. shell:su -c "magisk --install-module ..."  → 安装
        11. shell:rm -rf /sdcard/modules/             → 清理
    Phase D: 系统配置写入
        12-14. mount -o rw,remount / /product /vendor
        15-19. printf config hash → /system/etc/config
        20-22. mount -o rw,remount / /product /vendor
        23-27. printf security_patch → tricky_store/
    Phase E: 重启
        28. reboot:

公共 API：
    - update_integrity_fix(): 执行完整流程
    - UpdateIntegrityFixResult: 整体结果数据类
    - ModuleInstallResult: 单模块安装结果数据类
    - SystemConfigResult: 系统配置写入结果数据类
    - ModuleFileInfo: 模块文件信息数据类
"""

from .models import (
    ModuleFileInfo,
    ModuleInstallResult,
    SystemConfigResult,
    UpdateIntegrityFixResult,
)
from .update_integrity_fix import update_integrity_fix

__all__ = [
    "ModuleFileInfo",
    "ModuleInstallResult",
    "SystemConfigResult",
    "UpdateIntegrityFixResult",
    "update_integrity_fix",
]
