"""Randomly Change Device 数据模型.

仅包含本模块所需的不可变数据类。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RandomDeviceResult:
    """Randomly Change Device 的完整执行结果.

    属性:
        locale: 步骤 1 — getprop persist.sys.locale 的输出。
        gmail_accounts: 步骤 2 — dumpsys account 找到的 Gmail 账户。
        prepare_success: 步骤 3-31 — 系统准备阶段是否全部成功。
        recovery_mounted: 步骤 32-47 — Recovery 挂载是否完成。
        prop_files_modified: 步骤 48-239 — 修改的 build.prop 文件路径元组。
        security_props_set: 步骤 240-247 — 安全属性是否设置成功。
        mi_files_written: 步骤 248-268 — MiChanger 文件是否写入成功。
        data_cleaned: 步骤 269-295 — 数据清理是否成功。
        packages_xml_pushed: 步骤 296-297 — packages.xml 是否推送成功。
        settings_pushed: 步骤 308-315 — settings XML 是否推送成功。
        reboot_success: 步骤 316 — 重启是否成功。
        verified_brand: 步骤 328 — 验证后的品牌。
        verified_model: 步骤 329 — 验证后的型号。
        verified_version: 步骤 330 — 验证后的 Android 版本。
        vending_enabled: 步骤 331 — Play Store 是否启用成功。
        third_party_packages: 步骤 332 — 第三方应用列表。
    """

    locale: str
    gmail_accounts: tuple[str, ...]
    prepare_success: bool
    recovery_mounted: bool
    prop_files_modified: tuple[str, ...]
    security_props_set: bool
    mi_files_written: bool
    data_cleaned: bool
    packages_xml_pushed: bool
    settings_pushed: bool
    reboot_success: bool
    verified_brand: str
    verified_model: str
    verified_version: str
    vending_enabled: bool
    third_party_packages: tuple[str, ...]
