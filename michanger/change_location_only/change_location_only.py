"""
Change Location Only — 核心业务逻辑。

严格按照 15.0-Change Location Only.pcapng 抓包还原的命令序列，
清除位置历史、在 TWRP Recovery 中替换 mi_info.json、深度清理位置数据并重启。

与 14.0 Random & Change SIM Info Only 的差异：
    - 新增 Phase 1: pm clear com.google.android.gms.location.history（预清理位置历史）
    - 新增 Phase 6: rm -rf 6 个位置历史数据目录（TWRP 中深度清理）

pcapng 命令序列（35 步，分 8 阶段）：
    Phase 1 (Step 1):      pm clear 位置历史包（Android 正常模式）
    Phase 2 (Step 2):      reboot:recovery → 等待 TWRP 就绪
    Phase 3 (Step 3-17):   TWRP 验证 + 挂载 7 分区 + remount rw 7 分区
    Phase 4 (Step 18-27):  路径探测 + 读取当前 mi_info.json
    Phase 5 (Step 28-31):  mi_info.json 替换（rm -rf → printf 写入）
    Phase 6 (Step 32):     位置历史数据目录深度清理（rm -rf 6 目录）
    Phase 7 (Step 33):     正常重启 → 等待设备就绪
    Phase 8 (Step 34-35):  pm enable vending + pm list packages -3

参考：
- https://docs.python.org/3/library/subprocess.html#subprocess.run
- https://docs.python.org/3/library/pathlib.html
- https://docs.python.org/3/library/logging.html
"""

from __future__ import annotations

import logging
from pathlib import Path

from michanger.common import (
    AdbError,
    AdbExecutor,
    DeviceProfile,
    detect_mi_dir,
    load_profile,
    mount_all_partitions,
)
from .models import ChangeLocationResult, PhaseResult

logger = logging.getLogger(__name__)

# 启动等待超时（秒）
_BOOT_WAIT_TIMEOUT: float = 180.0

# ------------------------------------------------------------------
# 位置历史常量（从 pcapng 抓包提取）
# ------------------------------------------------------------------

# 位置历史包名（Step 1 pm clear + Step 32 rm -rf 的目标）
LOCATION_HISTORY_PACKAGE: str = (
    "com.google.android.gms.location.history"
)

# 位置历史数据目录路径（Step 32 rm -rf 的 6 个目标路径）
# 从 15.0/15.1 pcapng 中提取，两份抓包完全一致
LOCATION_HISTORY_DATA_PATHS: tuple[str, ...] = (
    "/data/data/com.google.android.gms.location.history",
    "/data/user_de/0/com.google.android.gms.location.history",
    "/data/user/0/com.google.android.gms.location.history",
    "/sdcard/Android/data/com.google.android.gms.location.history",
    "/data/misc/profiles/ref/com.google.android.gms.location.history",
    "/data/misc/profiles/cur/0/com.google.android.gms.location.history",
)


# ------------------------------------------------------------------
# 各阶段实现
# ------------------------------------------------------------------


def _phase1_clear_location_history(
    adb: AdbExecutor,
) -> tuple[PhaseResult, str]:
    """Phase 1: pm clear 位置历史包（pcapng Step 1）。

    在 Android 正常模式下清除位置历史包数据。
    pcapng 中此命令返回 "Failed"（包可能未安装），
    这是正常行为，不中断流程——与抓包行为一致。

    Args:
        adb: ADB 执行器

    Returns:
        (PhaseResult, pm_clear_output) 元组
    """
    logger.info(
        "清除位置历史包: %s", LOCATION_HISTORY_PACKAGE
    )
    result = adb.shell(
        f"pm clear {LOCATION_HISTORY_PACKAGE}"
    )
    pm_output = result.output
    logger.info(
        "pm clear %s → %s", LOCATION_HISTORY_PACKAGE, pm_output
    )

    # 与抓包行为一致：即使返回 "Failed" 也视为成功（best-effort）
    return (
        PhaseResult(
            phase_name="Clear Location History",
            phase_number=1,
            success=True,
            message=f"pm clear → {pm_output}",
            commands_executed=1,
        ),
        pm_output,
    )


def _phase2_reboot_recovery(adb: AdbExecutor) -> PhaseResult:
    """Phase 2: 重启进入 TWRP Recovery（pcapng Step 2）。

    Args:
        adb: ADB 执行器

    Returns:
        PhaseResult
    """
    count = 0

    logger.info("重启到 Recovery 模式")
    adb.reboot("recovery")
    count += 1

    # 等待设备进入 recovery 状态
    logger.info("等待设备进入 Recovery 模式...")
    adb.wait_for_device("recovery", timeout=120.0)

    # 等待 TWRP 完全就绪
    logger.info("等待 TWRP 就绪...")
    ready = adb.wait_for_twrp_ready(timeout=120.0)

    if not ready:
        return PhaseResult(
            phase_name="Reboot Recovery",
            phase_number=2,
            success=False,
            message="TWRP 未就绪（超时）",
            commands_executed=count,
        )

    return PhaseResult(
        phase_name="Reboot Recovery",
        phase_number=2,
        success=True,
        message="已进入 TWRP Recovery",
        commands_executed=count,
    )


def _phase3_mount_partitions(adb: AdbExecutor) -> PhaseResult:
    """Phase 3: TWRP 验证 + 挂载分区 + remount rw（pcapng Step 3-17）。

    使用 common.twrp.mount_all_partitions() 通用逻辑。

    Args:
        adb: ADB 执行器

    Returns:
        PhaseResult
    """
    count = mount_all_partitions(adb)

    # ls 验证文件系统可访问（pcapng Step 18）
    ls_result = adb.shell("ls /system_root/system/etc")
    count += 1
    if ls_result.success:
        logger.info("文件系统可访问: /system_root/system/etc")
    else:
        logger.warning(
            "文件系统访问失败: %s", ls_result.output[:100]
        )

    return PhaseResult(
        phase_name="Mount Partitions",
        phase_number=3,
        success=True,
        message=f"挂载完成, {count} 条命令",
        commands_executed=count,
    )


def _phase4_detect_and_read(
    adb: AdbExecutor,
) -> tuple[PhaseResult, str]:
    """Phase 4: 路径探测 + 读取当前 mi_info.json（pcapng Step 18-27）。

    按 pcapng 中的顺序：
    1. ls 三个候选路径探测 mi 目录（Step 19-21）
    2. 重复 ls 确认 mi_info 路径（Step 22-25）
    3. ls 确认 mi_info.json 文件（Step 26）
    4. cat 读取当前内容（Step 27）

    Args:
        adb: ADB 执行器

    Returns:
        (PhaseResult, mi_dir_path) 元组
    """
    count = 0

    # 探测 mi 目录（pcapng Step 19-21）
    mi_dir, detect_count = detect_mi_dir(adb)
    count += detect_count

    if not mi_dir:
        return (
            PhaseResult(
                phase_name="Detect & Read",
                phase_number=4,
                success=False,
                message="未找到 mi 目录",
                commands_executed=count,
            ),
            "",
        )

    # 重复 ls 确认（pcapng Step 22-25，与探测序列相同）
    for candidate in ("/system/etc/mi", "/system/system/etc/mi"):
        adb.shell(f"ls {candidate}")
        count += 1

    # 确认 mi 目录（两次 ls）
    adb.shell(f"ls {mi_dir}")
    count += 1
    adb.shell(f"ls {mi_dir}")
    count += 1

    # 确认 mi_info.json 文件存在（pcapng Step 26）
    mi_info_path = f"{mi_dir}/mi_info.json"
    ls_file_result = adb.shell(f"ls {mi_info_path}")
    count += 1

    if "No such file" in ls_file_result.output:
        return (
            PhaseResult(
                phase_name="Detect & Read",
                phase_number=4,
                success=False,
                message=f"mi_info.json 不存在: {mi_info_path}",
                commands_executed=count,
            ),
            mi_dir,
        )

    # 读取当前内容（pcapng Step 27）
    cat_result = adb.shell(f"cat {mi_info_path}")
    count += 1
    logger.info(
        "当前 mi_info.json 长度: %d 字符",
        len(cat_result.output),
    )

    return (
        PhaseResult(
            phase_name="Detect & Read",
            phase_number=4,
            success=True,
            message=f"mi 目录: {mi_dir}, 文件已读取",
            commands_executed=count,
        ),
        mi_dir,
    )


def _phase5_replace_mi_info(
    adb: AdbExecutor,
    mi_dir: str,
    mi_info_data: str,
) -> PhaseResult:
    """Phase 5: 替换 mi_info.json（pcapng Step 28-31）。

    执行步骤：
    1. ls 确认目录（Step 28）
    2. rm -rf 删除旧文件（Step 29）
    3. printf 写入第一行（> 覆盖）（Step 30）
    4. printf 追加第二行（>>）（Step 31）

    Args:
        adb: ADB 执行器
        mi_dir: mi 目录路径（如 /system_root/system/etc/mi）
        mi_info_data: 新的 mi_info 数据（格式 "LINE1\\nLINE2"）

    Returns:
        PhaseResult
    """
    count = 0
    mi_info_path = f"{mi_dir}/mi_info.json"

    # 写入前确认目录（pcapng Step 28）
    adb.shell(f"ls {mi_dir}")
    count += 1

    # 删除旧文件（pcapng Step 29）
    rm_result = adb.shell(f"rm -rf {mi_info_path}")
    count += 1
    if rm_result.success:
        logger.info("已删除旧 mi_info.json")
    else:
        logger.warning(
            "删除旧 mi_info.json 失败: %s", rm_result.output
        )

    # 写入新内容（pcapng Step 30-31）
    mi_lines = mi_info_data.split("\n")

    # 第一行：printf '...\n' > path（覆盖写入）
    adb.shell(f"printf '{mi_lines[0]}\\n' > {mi_info_path}")
    count += 1
    logger.info(
        "写入 mi_info.json 第一行 (%d 字符)", len(mi_lines[0])
    )

    # 第二行：printf '...' >> path（追加写入）
    if len(mi_lines) > 1:
        adb.shell(
            f"printf '{mi_lines[1]}' >> {mi_info_path}"
        )
        count += 1
        logger.info(
            "追加 mi_info.json 第二行 (%d 字符)",
            len(mi_lines[1]),
        )

    return PhaseResult(
        phase_name="Replace mi_info",
        phase_number=5,
        success=True,
        message=f"mi_info.json 已替换 ({len(mi_info_data)} 字符)",
        commands_executed=count,
    )


def _phase6_cleanup_location_data(
    adb: AdbExecutor,
) -> PhaseResult:
    """Phase 6: 位置历史数据目录深度清理（pcapng Step 32）。

    在 TWRP Recovery 中 rm -rf 6 个位置历史相关数据目录。
    这是 Change Location Only 的独有步骤（14.0 SIM Info 无此步骤）。

    pcapng 中使用单条 rm -rf 命令同时删除所有 6 个路径。

    Args:
        adb: ADB 执行器

    Returns:
        PhaseResult
    """
    # 构建 rm -rf 命令（与 pcapng 完全一致：单条命令 6 个路径）
    paths_str = " ".join(LOCATION_HISTORY_DATA_PATHS)
    rm_cmd = f"rm -rf {paths_str}"

    logger.info(
        "清理位置历史数据 (%d 个目录)",
        len(LOCATION_HISTORY_DATA_PATHS),
    )
    result = adb.shell(rm_cmd)

    if result.success:
        logger.info("位置历史数据已清理")
    else:
        logger.warning(
            "位置历史数据清理异常: %s", result.output[:200]
        )

    return PhaseResult(
        phase_name="Cleanup Location Data",
        phase_number=6,
        success=True,
        message=f"rm -rf {len(LOCATION_HISTORY_DATA_PATHS)} 个目录",
        commands_executed=1,
    )


def _phase7_reboot(adb: AdbExecutor) -> PhaseResult:
    """Phase 7: 正常重启（pcapng Step 33）。

    Args:
        adb: ADB 执行器

    Returns:
        PhaseResult
    """
    count = 0

    logger.info("正常重启设备")
    adb.reboot()
    count += 1

    # 等待设备重启完成
    logger.info("等待设备重启完成...")
    adb.wait_for_device("device", timeout=_BOOT_WAIT_TIMEOUT)

    # 等待 shell 就绪
    logger.info("等待 shell 就绪...")
    ready = adb.wait_for_shell_ready(timeout=_BOOT_WAIT_TIMEOUT)

    if not ready:
        return PhaseResult(
            phase_name="Reboot",
            phase_number=7,
            success=False,
            message="设备重启后 shell 未就绪（超时）",
            commands_executed=count,
        )

    return PhaseResult(
        phase_name="Reboot",
        phase_number=7,
        success=True,
        message="设备已重启",
        commands_executed=count,
    )


def _phase8_enable_and_verify(
    adb: AdbExecutor,
) -> tuple[PhaseResult, tuple[str, ...]]:
    """Phase 8: 启用 Play Store + 列出第三方应用（pcapng Step 34-35）。

    Args:
        adb: ADB 执行器

    Returns:
        (PhaseResult, third_party_packages) 元组
    """
    count = 0

    # pm enable com.android.vending（pcapng Step 34）
    enable_result = adb.shell("pm enable com.android.vending")
    count += 1
    logger.info(
        "pm enable com.android.vending → %s",
        enable_result.output,
    )

    # pm list packages -3（pcapng Step 35）
    pkg_result = adb.shell("pm list packages -3")
    count += 1

    # 解析第三方包列表
    packages = tuple(
        line.replace("package:", "").strip()
        for line in pkg_result.output.splitlines()
        if line.startswith("package:")
    )
    logger.info(
        "第三方应用 (%d 个):\n%s",
        len(packages),
        pkg_result.output,
    )

    return (
        PhaseResult(
            phase_name="Enable & Verify",
            phase_number=8,
            success=True,
            message=(
                f"Play Store 已启用, "
                f"{len(packages)} 个第三方应用"
            ),
            commands_executed=count,
        ),
        packages,
    )


# ------------------------------------------------------------------
# 公共 API
# ------------------------------------------------------------------


def change_location_only(
    *,
    adb_path: Path,
    serial: str,
    profile: DeviceProfile | None = None,
    profile_name: str | None = None,
) -> ChangeLocationResult:
    """执行 Change Location Only 完整流程。

    严格按照 15.0-Change Location Only.pcapng 还原的
    8 阶段 / 35 步命令序列。

    与 random_change_sim_info（14.0 pcapng）的差异：
    - 新增 Phase 1: pm clear 位置历史包
    - 新增 Phase 6: rm -rf 6 个位置历史数据目录

    使用 DeviceProfile.mi_info_data 作为新 mi_info.json 数据来源。

    Args:
        adb_path: adb 可执行文件路径
        serial: 设备序列号
        profile: 设备配置（优先使用）
        profile_name: 配置名称（当 profile 为 None 时使用）

    Returns:
        ChangeLocationResult 包含各阶段结果和检测到的第三方应用

    Raises:
        AdbError: 关键步骤失败
    """
    if profile is None:
        profile = load_profile(profile_name)

    adb = AdbExecutor(adb_path=adb_path, serial=serial)
    phases: list[PhaseResult] = []

    logger.info("=" * 60)
    logger.info(
        "Change Location Only — 设备 [%s]", serial
    )
    logger.info(
        "目标: %s (%s)", profile.model, profile.device
    )
    logger.info("=" * 60)

    # Phase 1: pm clear 位置历史包（Step 1）
    logger.info("[Phase 1/8] 清除位置历史包数据")
    p1, pm_clear_output = _phase1_clear_location_history(adb)
    phases.append(p1)

    # Phase 2: 重启进入 Recovery（Step 2）
    logger.info("[Phase 2/8] 重启进入 TWRP Recovery")
    p2 = _phase2_reboot_recovery(adb)
    phases.append(p2)
    if not p2.success:
        raise AdbError("TWRP Recovery 未就绪，无法继续")

    # Phase 3: 挂载分区（Step 3-17）
    logger.info("[Phase 3/8] TWRP 挂载分区")
    phases.append(_phase3_mount_partitions(adb))

    # Phase 4: 路径探测 + 读取（Step 18-27）
    logger.info("[Phase 4/8] 路径探测 + 读取 mi_info.json")
    p4, mi_dir = _phase4_detect_and_read(adb)
    phases.append(p4)
    if not p4.success:
        raise AdbError(f"mi_info 路径探测失败: {p4.message}")

    # Phase 5: 替换 mi_info.json（Step 28-31）
    logger.info("[Phase 5/8] 替换 mi_info.json")
    phases.append(
        _phase5_replace_mi_info(adb, mi_dir, profile.mi_info_data)
    )

    # Phase 6: 位置历史数据深度清理（Step 32）
    logger.info("[Phase 6/8] 清理位置历史数据目录")
    phases.append(_phase6_cleanup_location_data(adb))

    # Phase 7: 正常重启（Step 33）
    logger.info("[Phase 7/8] 正常重启")
    p7 = _phase7_reboot(adb)
    phases.append(p7)
    if not p7.success:
        raise AdbError("设备重启后未就绪")

    # Phase 8: 启用 Play Store + 验证（Step 34-35）
    logger.info("[Phase 8/8] 启用 Play Store + 验证")
    p8, packages = _phase8_enable_and_verify(adb)
    phases.append(p8)

    overall = all(p.success for p in phases)
    total_cmds = sum(p.commands_executed for p in phases)

    logger.info("=" * 60)
    logger.info(
        "Change Location Only 完成 — %d/%d 阶段成功, %d 条命令",
        sum(1 for p in phases if p.success),
        len(phases),
        total_cmds,
    )
    logger.info("=" * 60)

    return ChangeLocationResult(
        serial=serial,
        phase_results=tuple(phases),
        mi_dir_path=mi_dir,
        third_party_packages=packages,
        pm_clear_output=pm_clear_output,
        success=overall,
    )
