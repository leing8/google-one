"""设备信息数据模型。

Load Device 结果的不可变数据容器。
所有模型都遵循 Python 最佳实践使用冻结的（frozen）数据类。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RomVersion:
    """来自 /system/bin/mi 的 ROM 版本信息。

    属性:
        raw: 原始文件内容，保持原样（例如 "rom.version=michanger_4xl_11_v3"）。
        found: 是否成功读取了文件。
    """

    raw: str
    found: bool


@dataclass(frozen=True)
class ConfigPaths:
    """配置路径探测结果。

    每个布尔值指示设备上是否存在相应的路径。
    found_path 保存第一个存在的路径，如果未找到则为 None。

    属性:
        system_etc: /system/etc/mi 是否存在。
        system_system_etc: /system/system/etc/mi 是否存在。
        system_root_system_etc: /system_root/system/etc/mi 是否存在。
        data: /data/mi 是否存在。
        found_path: 第一个存在的路径，或者 None。
    """

    system_etc: bool
    system_system_etc: bool
    system_root_system_etc: bool
    data: bool
    found_path: str | None


@dataclass(frozen=True)
class DeviceInfo:
    """Load Device 收集到的完整设备信息。

    属性:
        rom_version: 来自 /system/bin/mi 的 ROM 版本。
        config_paths: 配置路径探测结果。
        brand: 设备品牌 (ro.product.brand)。
        model: 设备型号 (ro.product.model)。
        android_version: Android 版本 (ro.build.version.release)。
        third_party_packages: 第三方应用包名列表。
    """

    rom_version: RomVersion
    config_paths: ConfigPaths
    brand: str
    model: str
    android_version: str
    third_party_packages: tuple[str, ...]


@dataclass(frozen=True)
class MagiskInstallResult:
    """Install Magisk && Root Phone 的完整执行结果。

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


@dataclass(frozen=True)
class ModuleInstallDetail:
    """单个 Magisk 模块的安装结果。

    严格对应 6.0-Install Modules.pcapng 抓包日志中步骤 7-10 的
    magisk --install-module 输出。

    属性:
        filename: 模块文件名（例如 "1.Zygisk-Next-1.3.3.zip"）。
        remote_path: 设备上的完整路径（例如 "/sdcard/modules/1.Zygisk-Next-1.3.3.zip"）。
        install_output: magisk --install-module 的完整标准输出。
        install_success: 输出是否包含 "- Done" 标志。
    """

    filename: str
    remote_path: str
    install_output: str
    install_success: bool


@dataclass(frozen=True)
class ModulesInstallResult:
    """Install Modules 的完整执行结果。

    严格对应 6.0-Install Modules.pcapng 抓包日志中的 12 步操作。

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


@dataclass(frozen=True)
class RandomDeviceResult:
    """Randomly Change Device 的完整执行结果。

    严格对应 7.0-Randomly change device.pcapng 抓包日志中的 332 步操作。

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


@dataclass(frozen=True)
class IntegrityFixResult:
    """Update Integrity Fix 的完整执行结果。

    严格对应 8.0-Update Integrity Fix.pcapng 抓包日志中的 28 步操作。

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
