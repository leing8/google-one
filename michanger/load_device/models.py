"""
Load Device 数据模型。

设备探测模块专用模型。
通用模型（CommandResult、DeviceInfo）请从 michanger.common 导入。

所有模型均使用 frozen=True 保证不可变性（PEP 557）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MiChangerInfo:
    """MiChanger ROM 检测结果。

    Attributes:
        rom_version: MiChanger ROM 版本字符串（如 "michanger_4xl_11_v3"），
                     未检测到则为 None
        config_path: 找到的 mi 配置目录路径，未找到则为 None
    """

    rom_version: str | None
    config_path: str | None

    @property
    def is_michanger(self) -> bool:
        """设备是否安装了 MiChanger ROM。"""
        return self.rom_version is not None


@dataclass(frozen=True)
class DeviceProperties:
    """Android 系统属性。

    Attributes:
        brand: 设备品牌（ro.product.brand）
        model: 设备型号（ro.product.model）
        android_version: Android 版本号（ro.build.version.release）
    """

    brand: str
    model: str
    android_version: str


@dataclass(frozen=True)
class LoadDeviceResult:
    """Load Device 完整探测结果（单台设备）。

    Attributes:
        serial: 设备序列号（来自 adb devices）
        state: 设备连接状态（device / offline / unauthorized / bootloader 等）
        michanger: MiChanger ROM 检测结果
        properties: 设备系统属性
        third_party_packages: 第三方应用包名列表（pm list packages -3）
    """

    serial: str
    state: str
    michanger: MiChangerInfo
    properties: DeviceProperties
    third_party_packages: tuple[str, ...]
