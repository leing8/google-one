"""
Randomly Change Device — 数据模型。

所有模型均使用 frozen=True 保证不可变性（PEP 557）。

参考：
- https://docs.python.org/3/library/dataclasses.html
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DeviceProfile:
    """目标设备完整配置。

    从 device_profiles/*.json 加载，包含伪装目标设备所需的
    全部属性。所有字段均来自 pcapng 抓包中的 sed 替换目标值。

    Attributes:
        device: 设备代号（如 blazer）
        model: 设备型号（如 Pixel 10 Pro）
        brand: 品牌（如 Google）
        manufacturer: 制造商（如 Google）
        product: 产品名（如 blazer）
        board: 主板代号（如 blazer）
        platform: 平台（如 laguna）
        hardware: 硬件（如 powervr）
        build_id: 构建 ID（如 BP4A.260205.001）
        fingerprint: 构建指纹
        android_version: Android 版本（如 16）
        security_patch: 安全补丁日期（如 2026-02-05）
        incremental: 增量版本号（如 14624666）
        build_date: 构建日期字符串
        build_date_utc: 构建日期 UTC 时间戳
        build_user: 构建用户
        build_host: 构建主机
        build_tags: 构建标签（如 release-keys）
        build_type: 构建类型（如 user）
        timezone: 目标时区（如 Pacific/Honolulu）
        serial_no: 序列号（如 26JIK8TVGH）
        guid: 唯一标识 GUID
        mi_tool_version: MiChangerPro 版本标识
        mi_info_data: mi_info.json 加密数据（Base64）
        config_hash: /system/etc/config 哈希值
        android_id: 目标 android_id（16 位十六进制）
        cleanup_packages: 固定清理的应用包名列表（pm clear + rm -rf 数据 + APK 目录，阶段 3/9）
        extra_cleanup_packages: 额外清理的应用包名列表（pm clear + rm -rf，阶段 3/10）
        finalize_clear_packages: pm clear 最后阶段再次清理的包（默认 gms/gsf/vending）
        system_cleanup_paths: 系统数据清理路径列表
    """

    device: str
    model: str
    brand: str
    manufacturer: str
    product: str
    board: str
    platform: str
    hardware: str
    build_id: str
    fingerprint: str
    android_version: str
    security_patch: str
    incremental: str
    build_date: str
    build_date_utc: str
    build_user: str
    build_host: str
    build_tags: str
    build_type: str
    timezone: str
    serial_no: str
    guid: str
    mi_tool_version: str
    mi_info_data: str
    config_hash: str
    android_id: str
    cleanup_packages: tuple[str, ...]
    extra_cleanup_packages: tuple[str, ...]
    system_cleanup_paths: tuple[str, ...]
    finalize_clear_packages: tuple[str, ...] = (
        "com.google.android.gms",
        "com.google.android.gsf",
        "com.android.vending",
    )


@dataclass(frozen=True)
class PhaseResult:
    """单阶段执行结果。

    Attributes:
        phase_name: 阶段名称
        phase_number: 阶段编号
        success: 是否成功
        message: 结果描述
        commands_executed: 执行的命令数量
    """

    phase_name: str
    phase_number: int
    success: bool
    message: str
    commands_executed: int = 0


@dataclass(frozen=True)
class ChangeDeviceResult:
    """设备信息随机化的最终执行结果。

    Attributes:
        phase_results: 各阶段的执行结果
        locale: 设备 locale
        gmail_account: 检测到的 Gmail 账号（空字符串表示未检测到）
        success: 整体是否成功
    """

    phase_results: tuple[PhaseResult, ...] = field(default_factory=tuple)
    locale: str = ""
    gmail_account: str = ""
    success: bool = False

    @property
    def total_phases(self) -> int:
        """总阶段数。"""
        return len(self.phase_results)

    @property
    def success_count(self) -> int:
        """成功阶段数。"""
        return sum(1 for r in self.phase_results if r.success)

    @property
    def total_commands(self) -> int:
        """执行的总命令数。"""
        return sum(r.commands_executed for r in self.phase_results)
