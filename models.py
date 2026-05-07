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
