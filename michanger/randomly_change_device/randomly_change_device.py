"""
Randomly Change Device — 核心业务逻辑。

严格按照 7.0-Randomly change device.pcapng 抓包还原的命令序列实现。
所有命令按原始 11 个阶段顺序执行。

pcapng 命令序列（11 阶段 / 333 条命令）：
    1.  设备信息探测（locale、Gmail 账号）
    2.  系统设置初始化（HOME、WiFi、开发者选项、时区、锁屏）
    3.  pm clear 清理应用数据（23 个包）
    4.  重启进入 TWRP Recovery
    5.  TWRP 挂载分区 + remount rw
    6.  修改 /prop.default
    7.  修改各分区 build.prop
    8.  安全属性 + mi_info 写入
    9.  深度清理应用与系统数据
    10. XML 文件 pull/modify/push + restorecon
    11. 重启 → 等待启动 → 验证

参考：
- https://docs.python.org/3/library/subprocess.html#subprocess.run
- https://docs.python.org/3/library/pathlib.html
- https://docs.python.org/3/library/json.html
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from michanger.common import AdbError, AdbExecutor
from . import app_cleaner, prop_modifier, xml_modifier
from .models import ChangeDeviceResult, DeviceProfile, PhaseResult

logger = logging.getLogger(__name__)

# 默认设备配置目录
_PROFILES_DIR: Path = Path(__file__).resolve().parent / "device_profiles"

# TWRP 挂载分区列表（pcapng 命令 35-41）
_TWRP_MOUNT_PARTITIONS: tuple[str, ...] = (
    "/system", "/system_ext", "/vendor",
    "/product", "/odm", "/persist", "/firmware",
)

# remount rw 分区列表（pcapng 命令 42-48）
_REMOUNT_PARTITIONS: tuple[str, ...] = (
    "/system_root", "/system_ext", "/vendor",
    "/product", "/odm", "/persist", "/firmware",
)

# mi_info 清理路径（pcapng 命令 249-255）
_MI_INFO_CLEANUP_PATHS: tuple[str, ...] = (
    "/data/mi_info",
    "/system/system/etc/mi_info",
    "/system/etc/mi_info",
    "/system_root/system/etc/mi_info",
    "/system/system/etc/mi",
    "/system/etc/mi",
    "/system_root/system/etc/mi",
)

# Boot animation 检测超时（秒）
_BOOT_WAIT_TIMEOUT: float = 180.0


def load_profile(name: str | None = None) -> DeviceProfile:
    """加载设备配置文件。

    Args:
        name: 配置名称（不含 .json 后缀），None 则使用默认

    Returns:
        DeviceProfile 实例

    Raises:
        AdbError: 配置文件不存在或格式错误
    """
    if name is None:
        # 使用目录中的第一个 JSON 文件
        json_files = sorted(_PROFILES_DIR.glob("*.json"))
        if not json_files:
            raise AdbError(f"未找到设备配置文件: {_PROFILES_DIR}")
        profile_path = json_files[0]
    else:
        profile_path = _PROFILES_DIR / f"{name}.json"

    if not profile_path.is_file():
        raise AdbError(f"设备配置文件不存在: {profile_path}")

    try:
        with open(profile_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        raise AdbError(f"配置文件读取失败: {profile_path}: {exc}") from exc

    return DeviceProfile(
        device=data["device"],
        model=data["model"],
        brand=data["brand"],
        manufacturer=data["manufacturer"],
        product=data["product"],
        board=data["board"],
        platform=data["platform"],
        hardware=data["hardware"],
        build_id=data["build_id"],
        fingerprint=data["fingerprint"],
        android_version=data["android_version"],
        security_patch=data["security_patch"],
        incremental=data["incremental"],
        build_date=data["build_date"],
        build_date_utc=data["build_date_utc"],
        build_user=data["build_user"],
        build_host=data["build_host"],
        build_tags=data["build_tags"],
        build_type=data["build_type"],
        timezone=data["timezone"],
        serial_no=data["serial_no"],
        guid=data["guid"],
        mi_tool_version=data["mi_tool_version"],
        mi_info_data=data["mi_info_data"],
        config_hash=data["config_hash"],
        android_id=data["android_id"],
        pm_clear_packages=tuple(data["pm_clear_packages"]),
        rm_rf_packages=tuple(data["rm_rf_packages"]),
        system_cleanup_paths=tuple(data["system_cleanup_paths"]),
    )


# ------------------------------------------------------------------
# 各阶段实现
# ------------------------------------------------------------------

def _phase1_probe(adb: AdbExecutor) -> PhaseResult:
    """阶段 1: 设备信息探测（pcapng 命令 1-2）。"""
    count = 0

    locale_result = adb.shell("getprop persist.sys.locale")
    count += 1
    locale = locale_result.output.strip()
    logger.info("设备 locale: %s", locale)

    gmail_result = adb.shell(
        "dumpsys account | grep '@gmail.com, type=com.google}'"
    )
    count += 1
    gmail = gmail_result.output.strip()
    logger.info("Gmail 账号: %s", gmail if gmail else "(无)")

    return PhaseResult(
        phase_name="设备信息探测",
        phase_number=1,
        success=True,
        message=f"locale={locale}",
        commands_executed=count,
    )


def _phase2_system_settings(
    adb: AdbExecutor,
    profile: DeviceProfile,
) -> PhaseResult:
    """阶段 2: 系统设置初始化（pcapng 命令 3-9）。"""
    count = 0

    # 按 HOME 键（命令 3）
    adb.shell("input keyevent HOME")
    count += 1

    # 关闭 WiFi（命令 4）
    adb.shell("svc wifi disable")
    count += 1

    # 设置 WiFi 开关为 1（命令 5）
    adb.shell("settings put global wifi_on 1")
    count += 1

    # 关闭开发者选项（命令 6）
    adb.shell("settings put global development_settings_enabled 0")
    count += 1

    # 关闭自动时区（命令 7）
    adb.shell("settings put global auto_time_zone 0")
    count += 1

    # 设置时区（命令 8）
    adb.shell(f"service call alarm 3 s16 {profile.timezone}")
    count += 1

    # 禁用锁屏（命令 9）
    adb.shell("locksettings set-disabled True")
    count += 1

    return PhaseResult(
        phase_name="系统设置初始化",
        phase_number=2,
        success=True,
        message="WiFi/开发者/时区/锁屏已配置",
        commands_executed=count,
    )


def _phase3_pm_clear(
    adb: AdbExecutor,
    profile: DeviceProfile,
) -> PhaseResult:
    """阶段 3: pm clear 清理应用数据（pcapng 命令 10-32）。"""
    count = app_cleaner.pm_clear_packages(adb, profile)
    return PhaseResult(
        phase_name="pm clear 清理",
        phase_number=3,
        success=True,
        message=f"已清理 {count} 个应用",
        commands_executed=count,
    )


def _phase4_reboot_recovery(adb: AdbExecutor) -> PhaseResult:
    """阶段 4: 重启进入 TWRP Recovery（pcapng 命令 33）。"""
    adb.reboot("recovery")
    logger.info("等待 TWRP Recovery 就绪...")

    adb.wait_for_device("recovery", timeout=120.0)
    ready = adb.wait_for_twrp_ready(timeout=120.0)

    return PhaseResult(
        phase_name="重启进入 Recovery",
        phase_number=4,
        success=ready,
        message="TWRP 已就绪" if ready else "TWRP 等待超时",
        commands_executed=1,
    )


def _phase5_mount_partitions(adb: AdbExecutor) -> PhaseResult:
    """阶段 5: TWRP 挂载分区 + remount rw（pcapng 命令 34-50）。"""
    count = 0

    # 验证 TWRP 版本（命令 34, 50）
    adb.shell("twrp --version")
    count += 1

    # 挂载分区（命令 35-41）
    for partition in _TWRP_MOUNT_PARTITIONS:
        adb.shell(f"twrp mount {partition}")
        count += 1

    # remount rw（命令 42-48）
    for partition in _REMOUNT_PARTITIONS:
        adb.shell(f"mount -o remount,rw {partition}")
        count += 1

    # ls 验证（命令 49）
    adb.shell("ls /system_root/system/etc")
    count += 1

    # TWRP 版本再次验证（命令 50）
    adb.shell("twrp --version")
    count += 1

    return PhaseResult(
        phase_name="挂载分区",
        phase_number=5,
        success=True,
        message=f"已挂载 {len(_TWRP_MOUNT_PARTITIONS)} 个分区",
        commands_executed=count,
    )


def _phase6_modify_prop_default(
    adb: AdbExecutor,
    profile: DeviceProfile,
) -> PhaseResult:
    """阶段 6: 修改 /prop.default（pcapng 命令 51-138）。"""
    count = prop_modifier.modify_prop_default(adb, profile)
    return PhaseResult(
        phase_name="修改 /prop.default",
        phase_number=6,
        success=True,
        message=f"执行 {count} 条 sed 命令",
        commands_executed=count,
    )


def _phase7_modify_build_props(
    adb: AdbExecutor,
    profile: DeviceProfile,
) -> PhaseResult:
    """阶段 7: 修改各分区 build.prop（pcapng 命令 139-238）。"""
    count = 0
    count += prop_modifier.modify_product_build_prop(adb, profile)
    count += prop_modifier.modify_system_build_prop(adb, profile)
    count += prop_modifier.modify_system_ext_build_prop(adb, profile)
    count += prop_modifier.modify_odm_build_prop(adb, profile)
    count += prop_modifier.modify_vendor_build_prop(adb, profile)

    return PhaseResult(
        phase_name="修改各分区 build.prop",
        phase_number=7,
        success=True,
        message=f"5 个分区, {count} 条命令",
        commands_executed=count,
    )


def _phase8_security_and_mi_info(
    adb: AdbExecutor,
    profile: DeviceProfile,
) -> PhaseResult:
    """阶段 8: 安全属性 + mi_info 写入（pcapng 命令 239-268）。"""
    count = 0

    # 安全属性（命令 241-248）
    count += prop_modifier.set_security_props(adb)

    # 清理 mi_info 旧目录（命令 249-255）
    for path in _MI_INFO_CLEANUP_PATHS:
        adb.shell(f"rm -rf {path}")
        count += 1

    # 创建新 mi 目录（命令 256）
    adb.shell("mkdir /system_root/system/etc/mi")
    count += 1

    # 写入 mi_info.json（命令 257-258）
    mi_lines = profile.mi_info_data.split("\n")
    mi_path = "/system_root/system/etc/mi/mi_info.json"
    adb.shell(f"printf '{mi_lines[0]}\\n' > {mi_path}")
    count += 1
    if len(mi_lines) > 1:
        adb.shell(f"printf '{mi_lines[1]}' >> {mi_path}")
        count += 1

    # 写入 tool 版本（命令 259）
    adb.shell(
        f"printf '{profile.mi_tool_version}' "
        f"> /system_root/system/etc/mi/tool"
    )
    count += 1

    # 写入 guid（命令 260）
    adb.shell(
        f"printf '{profile.guid}' "
        f"> /system_root/system/etc/mi/guid"
    )
    count += 1

    # 写入 custom 信息（命令 261-266）
    custom_path = "/system_root/system/etc/mi/custom"
    custom_lines = (
        (f"SERIALNO:{profile.serial_no}\\n", ">"),
        (f"RELEASE:{profile.android_version}\\n", ">>"),
        (f"SECURITY:{profile.security_patch}\\n", ">>"),
        (f"BOARD:{profile.board}\\n", ">>"),
        (f"PLATFORM:{profile.platform}\\n", ">>"),
        (f"HARDWARE:{profile.hardware}", ">>"),
    )
    for content, redirect in custom_lines:
        adb.shell(f"printf '{content}' {redirect} {custom_path}")
        count += 1

    # 读取 config（命令 267）
    adb.shell("cat /system_root/system/etc/config")
    count += 1

    # 写入 config hash（命令 268）
    adb.shell(
        f"printf '{profile.config_hash}' "
        f"> /system_root/system/etc/config"
    )
    count += 1

    # chmod config（命令 269）
    adb.shell("chmod 644 /system_root/system/etc/config")
    count += 1

    return PhaseResult(
        phase_name="安全属性 + mi_info",
        phase_number=8,
        success=True,
        message="安全属性/mi_info/config 已写入",
        commands_executed=count,
    )


def _phase9_deep_cleanup(
    adb: AdbExecutor,
    profile: DeviceProfile,
) -> PhaseResult:
    """阶段 9: 深度清理（pcapng 命令 270-296）。

    注意：命令 299-309 的 touch/rm-rf 操作穿插在 XML 处理中间，
    已移至 xml_modifier.modify_xml_files()（阶段 10）中按原始顺序执行。
    """
    count = 0

    # pcapng 命令 270-288: rm -rf 应用数据
    count += app_cleaner.rm_rf_app_data(adb, profile)

    # pcapng 命令 289-294: 清理 /data/app/ 目录
    count += app_cleaner.cleanup_data_app(adb)

    # pcapng 命令 295-296: 系统数据清理
    count += app_cleaner.cleanup_system_data(adb, profile)

    return PhaseResult(
        phase_name="深度清理",
        phase_number=9,
        success=True,
        message=f"执行 {count} 条清理命令",
        commands_executed=count,
    )


def _phase10_xml_files(
    adb: AdbExecutor,
    profile: DeviceProfile,
) -> PhaseResult:
    """阶段 10: XML 文件处理（pcapng 命令 297-317）。"""
    count = xml_modifier.modify_xml_files(adb, profile)
    return PhaseResult(
        phase_name="XML 文件处理",
        phase_number=10,
        success=True,
        message="packages/settings XML 已修改",
        commands_executed=count,
    )


def _phase11_reboot_verify(
    adb: AdbExecutor,
    profile: DeviceProfile,
) -> PhaseResult:
    """阶段 11: 重启 → 等待启动 → 验证（pcapng 命令 318-333）。"""
    count = 0

    # 重启（命令 318）
    adb.reboot()
    count += 1

    # 等待设备在线
    adb.wait_for_device("device", timeout=_BOOT_WAIT_TIMEOUT)

    # 轮询 boot animation（命令 319-328）
    boot_ready = adb.wait_for_shell_ready(
        probe_command="getprop init.svc.bootanim",
        timeout=_BOOT_WAIT_TIMEOUT,
        poll_interval=3.0,
    )
    count += 10  # 约 10 次轮询

    if not boot_ready:
        logger.warning("等待启动超时")

    # 验证设备属性（命令 329-331）
    brand = adb.shell("getprop ro.product.brand").output.strip()
    model = adb.shell("getprop ro.product.model").output.strip()
    version = adb.shell("getprop ro.build.version.release").output.strip()
    count += 3
    logger.info("验证: brand=%s, model=%s, version=%s", brand, model, version)

    # 启用 Play Store（命令 332）
    adb.shell("pm enable com.android.vending")
    count += 1

    # 列出第三方应用（命令 333）
    pkg_result = adb.shell("pm list packages -3")
    count += 1
    logger.info("第三方应用:\n%s", pkg_result.output)

    verified = (
        brand.lower() == profile.brand.lower()
        and model == profile.model
    )

    return PhaseResult(
        phase_name="重启验证",
        phase_number=11,
        success=verified,
        message=f"brand={brand}, model={model}, ver={version}",
        commands_executed=count,
    )


# ------------------------------------------------------------------
# 主入口
# ------------------------------------------------------------------

def randomly_change_device(
    adb_path: Path,
    serial: str,
    profile: DeviceProfile | None = None,
    *,
    profile_name: str | None = None,
    dry_run: bool = False,
) -> ChangeDeviceResult:
    """执行设备信息随机化。

    严格按照 7.0-Randomly change device.pcapng 的 11 个阶段
    顺序执行全部命令。

    Args:
        adb_path: adb.exe 路径
        serial: 设备序列号
        profile: 设备配置（优先使用）
        profile_name: 配置名称（当 profile 为 None 时使用）
        dry_run: 仅打印命令序列

    Returns:
        ChangeDeviceResult

    Raises:
        AdbError: 关键步骤失败
    """
    if profile is None:
        profile = load_profile(profile_name)

    logger.info("目标设备: %s (%s)", profile.model, profile.device)

    if dry_run:
        return _dry_run(serial, profile)

    adb = AdbExecutor(adb_path=adb_path, serial=serial)

    logger.info("=" * 60)
    logger.info("Randomly Change Device — 设备 [%s]", serial)
    logger.info("目标: %s (%s) Android %s",
                profile.model, profile.device, profile.android_version)
    logger.info("=" * 60)

    phases: list[PhaseResult] = []
    locale = ""
    gmail = ""

    # 阶段 1: 设备信息探测
    logger.info("[Phase 1/11] 设备信息探测")
    p1 = _phase1_probe(adb)
    phases.append(p1)
    locale = p1.message.replace("locale=", "")

    # 阶段 2: 系统设置初始化
    logger.info("[Phase 2/11] 系统设置初始化")
    phases.append(_phase2_system_settings(adb, profile))

    # 阶段 3: pm clear
    logger.info("[Phase 3/11] pm clear 清理应用数据")
    phases.append(_phase3_pm_clear(adb, profile))

    # 阶段 4: 重启进入 Recovery
    logger.info("[Phase 4/11] 重启进入 TWRP Recovery")
    p4 = _phase4_reboot_recovery(adb)
    phases.append(p4)
    if not p4.success:
        raise AdbError("TWRP Recovery 未就绪，无法继续")

    # 阶段 5: 挂载分区
    logger.info("[Phase 5/11] TWRP 挂载分区")
    phases.append(_phase5_mount_partitions(adb))

    # 阶段 6: 修改 /prop.default
    logger.info("[Phase 6/11] 修改 /prop.default")
    phases.append(_phase6_modify_prop_default(adb, profile))

    # 阶段 7: 修改各分区 build.prop
    logger.info("[Phase 7/11] 修改各分区 build.prop")
    phases.append(_phase7_modify_build_props(adb, profile))

    # 阶段 8: 安全属性 + mi_info
    logger.info("[Phase 8/11] 安全属性 + mi_info 写入")
    phases.append(_phase8_security_and_mi_info(adb, profile))

    # 阶段 9: 深度清理
    logger.info("[Phase 9/11] 深度清理应用与系统数据")
    phases.append(_phase9_deep_cleanup(adb, profile))

    # 阶段 10: XML 文件处理
    logger.info("[Phase 10/11] XML 文件处理")
    phases.append(_phase10_xml_files(adb, profile))

    # 阶段 11: 重启验证
    logger.info("[Phase 11/11] 重启验证")
    phases.append(_phase11_reboot_verify(adb, profile))

    all_success = all(p.success for p in phases)
    total_cmds = sum(p.commands_executed for p in phases)

    logger.info("=" * 60)
    logger.info(
        "Randomly Change Device 完成 — %d/%d 阶段成功, %d 条命令",
        sum(1 for p in phases if p.success), len(phases), total_cmds,
    )
    logger.info("=" * 60)

    return ChangeDeviceResult(
        phase_results=tuple(phases),
        locale=locale,
        gmail_account=gmail,
        success=all_success,
    )


# ------------------------------------------------------------------
# Dry Run
# ------------------------------------------------------------------

def _dry_run(
    serial: str,
    profile: DeviceProfile,
) -> ChangeDeviceResult:
    """仅打印命令序列。"""
    print()
    print("=" * 60)
    print(f"Randomly Change Device — Dry Run — 设备 [{serial}]")
    print(f"目标: {profile.model} ({profile.device}) "
          f"Android {profile.android_version}")
    print("=" * 60)
    print()

    phases = (
        (" 1", "getprop persist.sys.locale"),
        (" 1", "dumpsys account | grep '@gmail.com...'"),
        (" 2", "input keyevent HOME"),
        (" 2", "svc wifi disable"),
        (" 2", "settings put global wifi_on 1"),
        (" 2", "settings put global development_settings_enabled 0"),
        (" 2", "settings put global auto_time_zone 0"),
        (" 2", f"service call alarm 3 s16 {profile.timezone}"),
        (" 2", "locksettings set-disabled True"),
    )
    for phase, cmd in phases:
        print(f"  [Phase {phase}/11] adb shell {cmd}")

    print(f"\n  [Phase  3/11] pm clear × {len(profile.pm_clear_packages)} 个包")
    for pkg in profile.pm_clear_packages:
        print(f"               → pm clear {pkg}")

    print(f"\n  [Phase  4/11] adb reboot recovery")
    print(f"  [Phase  5/11] twrp mount × {len(_TWRP_MOUNT_PARTITIONS)} 分区")
    print(f"  [Phase  6/11] 修改 /prop.default (sed × ~88)")
    print(f"  [Phase  7/11] 修改 5 个 build.prop (sed × ~100)")
    print(f"  [Phase  8/11] 安全属性 × 8 + mi_info 写入")

    print(f"\n  [Phase  9/11] rm -rf × {len(profile.rm_rf_packages)} 个包数据")
    print(f"               + 系统数据清理")

    print(f"\n  [Phase 10/11] XML pull/modify/push × 3 文件")
    print(f"               + restorecon × 4 路径")
    print(f"\n  [Phase 11/11] adb reboot + 验证")
    print()

    return ChangeDeviceResult(success=False)
