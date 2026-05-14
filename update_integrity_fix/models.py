"""Update Integrity Fix 数据模型.

仅包含本模块所需的不可变数据类。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IntegrityFixResult:
    """Update Integrity Fix 的完整执行结果.

    属性:
        root_verified: 步骤 1 — su -c "id" 是否确认 uid=0(root)。
        root_uid: 步骤 1 — id 命令的完整输出。
        tricky_store_installed: 步骤 2-6 — Tricky Store OSS 模块是否安装成功。
        tricky_store_output: 步骤 5 — magisk --install-module 的完整输出。
        pif_installed: 步骤 7-11 — OneChanger PIF Premium 模块是否安装成功。
        pif_output: 步骤 10 — magisk --install-module 的完整输出。
        config_written: 步骤 12-19 — Tricky Store config 哈希是否写入成功。
        security_patch_written: 步骤 20-27 — security_patch.txt 是否写入成功。
    """

    root_verified: bool
    root_uid: str
    tricky_store_installed: bool
    tricky_store_output: str
    pif_installed: bool
    pif_output: str
    config_written: bool
    security_patch_written: bool
