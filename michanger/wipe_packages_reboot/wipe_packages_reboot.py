"""
Wipe Packages & Reboot — 核心逻辑。

严格按照 11.0-Wipe Packages & Reboot.pcapng 抓包还原的命令序列实现。
所有命令按原始顺序执行，不做任何跳过或短路优化。

pcapng 命令序列（77-80 步，分 7 个阶段）：
    Phase 1 (Step 1-19+):  pm clear 固定 19 包 + 额外包
    Phase 2 (Step 20):     reboot:recovery → 等待 TWRP 就绪
    Phase 3 (Step 21-35):  TWRP mount + remount rw（7+7 分区）
    Phase 4 (Step 36-55):  验证文件系统 + rm -rf 深度清理 19 包
    Phase 5 (Step 56-61):  ls /data/app/* → 动态清理 APK 目录
    Phase 6 (Step 62-75):  系统数据清理 + packages.xml 修改 + touch + 额外清理
    Phase 7 (Step 76-77):  reboot: → pm enable com.android.vending

三份抓包 packages.xml diff 分析确认修改内容：
    - 仅 com.android.vending 和 com.google.android.gms 两个包
    - 仅 ft, it, ut 三个时间戳字段统一为同一值（当前时间 hex 毫秒）
    - <version>, <permissions>, <shared-user> 等所有其他元素完全不变

参考：
- https://docs.python.org/3/library/subprocess.html#subprocess.run
- https://docs.python.org/3/library/xml.etree.elementtree.html
- https://docs.python.org/3/library/tempfile.html
- https://docs.python.org/3/library/json.html
- https://docs.python.org/3/library/logging.html
"""

from __future__ import annotations

import json
import logging
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from michanger.common import AdbExecutor
from .models import (
    APP_DATA_DIR_TEMPLATES,
    APP_WIPE_PACKAGES,
    EXTRA_CLEANUP_PATHS,
    FIXED_CLEANUP_PACKAGES,
    GMS_DATA_DIR_TEMPLATES,
    PACKAGES_TIMESTAMP_TARGETS,
    REMOUNT_RW_PARTITIONS,
    SYSTEM_CLEANUP_PATHS,
    TOUCH_TARGETS,
    TWRP_MOUNT_PARTITIONS,
    PhaseResult,
    WipeConfig,
    WipeResult,
)

logger = logging.getLogger(__name__)

# packages.xml 设备端路径
_PACKAGES_XML_PATH: str = "/data/system/packages.xml"

# 默认配置文件路径
_DEFAULT_CONFIG_PATH: Path = Path(__file__).resolve().parent / "wipe_config.json"


def load_config() -> WipeConfig:
    """从模块目录下的 wipe_config.json 加载配置。

    配置文件格式：
        {
            "extra_cleanup_packages": [
                "com.google.android.apps.subscriptions.red",
                "gr.nikolasspyr.integritycheck"
            ]
        }

    Returns:
        WipeConfig 实例
    """
    path = _DEFAULT_CONFIG_PATH

    if not path.is_file():
        logger.info("配置文件不存在，使用默认配置: %s", path)
        return WipeConfig()

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("配置文件读取失败，使用默认配置: %s", exc)
        return WipeConfig()

    extra = tuple(data.get("extra_cleanup_packages", []))
    logger.info("加载配置: %s (额外包: %d 个)", path.name, len(extra))

    return WipeConfig(extra_cleanup_packages=extra)


# ------------------------------------------------------------------
# Phase 1: pm clear
# ------------------------------------------------------------------

def _phase1_pm_clear(
    adb: AdbExecutor,
    config: WipeConfig,
) -> PhaseResult:
    """Phase 1: 批量 pm clear 清理应用数据。

    对应 pcapng Step 1-19+ (shell,v2,raw:pm clear)。
    pm clear 失败（EXIT:1）不影响流程 — 抓包中大量包返回 EXIT:1。

    Args:
        adb: ADB 执行器
        config: 清理配置

    Returns:
        PhaseResult
    """
    count = 0

    # 固定 19 包（三份抓包完全一致）
    for pkg in FIXED_CLEANUP_PACKAGES:
        result = adb.shell(f"pm clear {pkg}")
        status = "Success" if "Success" in result.output else "Failed"
        logger.info("pm clear %s → %s", pkg, status)
        count += 1

    # 额外包（动态，来自 config）
    for pkg in config.extra_cleanup_packages:
        result = adb.shell(f"pm clear {pkg}")
        status = "Success" if "Success" in result.output else "Failed"
        logger.info("pm clear (extra) %s → %s", pkg, status)
        count += 1

    return PhaseResult(
        phase_name="pm clear",
        phase_number=1,
        success=True,
        message=f"已清理 {count} 个包",
        commands_executed=count,
    )


# ------------------------------------------------------------------
# Phase 2: Reboot to Recovery
# ------------------------------------------------------------------

def _phase2_reboot_recovery(adb: AdbExecutor) -> PhaseResult:
    """Phase 2: 重启到 Recovery + 等待 TWRP 就绪。

    对应 pcapng Step 20 (reboot:recovery) + Step 21 (twrp --version)。

    Args:
        adb: ADB 执行器

    Returns:
        PhaseResult
    """
    count = 0

    # reboot:recovery
    logger.info("重启到 Recovery 模式")
    adb.reboot("recovery")
    count += 1

    # 等待设备进入 recovery 状态
    logger.info("等待设备进入 Recovery 模式...")
    adb.wait_for_device("recovery")
    count += 1

    # 等待 TWRP 完全就绪
    logger.info("等待 TWRP 就绪...")
    twrp_ready = adb.wait_for_twrp_ready()
    count += 1

    if not twrp_ready:
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


# ------------------------------------------------------------------
# Phase 3: TWRP mount + remount rw
# ------------------------------------------------------------------

def _phase3_mount_partitions(adb: AdbExecutor) -> PhaseResult:
    """Phase 3: TWRP 挂载分区 + 重新挂载为 rw。

    对应 pcapng Step 22-35。
    部分分区（/odm, /firmware）可能不存在 — 这是正常行为。

    Args:
        adb: ADB 执行器

    Returns:
        PhaseResult
    """
    count = 0

    # 验证 TWRP 版本
    twrp_ver = adb.shell("twrp --version")
    count += 1
    logger.info("TWRP 版本: %s", twrp_ver.output.strip())

    # TWRP 挂载 7 个分区
    for partition in TWRP_MOUNT_PARTITIONS:
        result = adb.shell(f"twrp mount {partition}")
        count += 1
        if "Unable to find partition" in result.output:
            logger.debug("分区不存在（正常）: %s", partition)
        else:
            logger.info("已挂载: %s", partition)

    # 重新挂载为 rw
    for partition in REMOUNT_RW_PARTITIONS:
        result = adb.shell(f"mount -o remount,rw {partition}")
        count += 1
        if result.success:
            logger.info("已 remount rw: %s", partition)
        else:
            logger.debug("remount rw 失败（可能正常）: %s", partition)

    return PhaseResult(
        phase_name="Mount Partitions",
        phase_number=3,
        success=True,
        message=f"挂载 {len(TWRP_MOUNT_PARTITIONS)} 分区 + remount {len(REMOUNT_RW_PARTITIONS)} 分区",
        commands_executed=count,
    )


# ------------------------------------------------------------------
# Phase 4: 深度清理应用数据
# ------------------------------------------------------------------

def _phase4_deep_clean_app_data(adb: AdbExecutor) -> PhaseResult:
    """Phase 4: 验证文件系统 + rm -rf 深度清理固定 19 包的数据目录。

    对应 pcapng Step 36-55。
    com.google.android.gms 使用通配符 /* 不删除目录本身。

    Args:
        adb: ADB 执行器

    Returns:
        PhaseResult
    """
    count = 0

    # 验证文件系统可访问
    ls_result = adb.shell("ls /system_root/system/etc")
    count += 1
    if ls_result.success:
        logger.info("文件系统可访问: /system_root/system/etc")
    else:
        logger.warning("文件系统访问失败: %s", ls_result.output[:100])

    # 深度清理固定 19 包的 6 个数据目录
    for pkg in FIXED_CLEANUP_PACKAGES:
        if pkg == "com.google.android.gms":
            # GMS 特殊处理：使用通配符（pcapng 命令确认）
            paths = " ".join(GMS_DATA_DIR_TEMPLATES)
        else:
            paths = " ".join(
                tpl.format(pkg=pkg) for tpl in APP_DATA_DIR_TEMPLATES
            )
        adb.shell(f"rm -rf {paths}")
        count += 1
        logger.debug("rm -rf app data: %s", pkg)

    return PhaseResult(
        phase_name="Deep Clean App Data",
        phase_number=4,
        success=True,
        message=f"深度清理 {len(FIXED_CLEANUP_PACKAGES)} 个包的数据目录",
        commands_executed=count,
    )


# ------------------------------------------------------------------
# Phase 5: 清理 /data/app/ APK 目录
# ------------------------------------------------------------------

def _find_app_path(ls_output: str, package_name: str) -> str:
    """从 ls -1 /data/app/* 输出中找到包的完整安装路径。

    ls 输出格式：
        /data/app/~~hash==:
        com.pkg-hash==

    Args:
        ls_output: ls 命令输出
        package_name: 包名

    Returns:
        完整路径（如 /data/app/~~hash==/com.pkg-hash==）或空字符串
    """
    lines = ls_output.splitlines()
    current_parent = ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("/data/app/") and stripped.endswith(":"):
            current_parent = stripped.rstrip(":")
        elif package_name in stripped and current_parent:
            return f"{current_parent}/{stripped}"
    return ""


def _phase5_clean_data_app(adb: AdbExecutor) -> PhaseResult:
    """Phase 5: 清理 /data/app/ 下特定包的 APK 目录。

    对应 pcapng Step 56-61。
    流程：ls → 解析 → 对每个目标包 rm-rf + ls 验证 → 最终 ls。

    Args:
        adb: ADB 执行器

    Returns:
        PhaseResult
    """
    count = 0

    # 第一次 ls — 发现已安装包
    ls_result = adb.shell("ls -1 /data/app/*")
    count += 1

    if not ls_result.success:
        logger.warning("无法列出 /data/app/*: %s", ls_result.output)
        return PhaseResult(
            phase_name="Clean /data/app/",
            phase_number=5,
            success=True,
            message="/data/app/ 为空或不可访问",
            commands_executed=count,
        )

    output_text = ls_result.output

    # 查找目标包的实际路径
    packages_to_clean: list[str] = []
    for pkg in APP_WIPE_PACKAGES:
        full_path = _find_app_path(output_text, pkg)
        if full_path:
            packages_to_clean.append(full_path)
            logger.debug("找到 APK 目录: %s → %s", pkg, full_path)

    # 交替 rm-rf → ls 验证（与抓包一致）
    for app_path in packages_to_clean:
        adb.shell(f"rm -rf {app_path}/*")
        count += 1
        logger.info("清理 APK 目录: %s", app_path)

        adb.shell("ls -1 /data/app/*")
        count += 1

    # 最终 ls 验证
    adb.shell("ls -1 /data/app/*")
    count += 1

    return PhaseResult(
        phase_name="Clean /data/app/",
        phase_number=5,
        success=True,
        message=f"清理 {len(packages_to_clean)} 个 APK 目录",
        commands_executed=count,
    )


# ------------------------------------------------------------------
# Phase 6: 系统清理 + packages.xml + touch + 额外清理
# ------------------------------------------------------------------

def _modify_packages_xml(tree: ET.ElementTree) -> None:
    """修改 packages.xml 中的包时间戳。

    三份抓包 diff 分析确认：
    - 仅 com.android.vending 和 com.google.android.gms
    - 仅 ft, it, ut 三个字段统一为当前时间（十六进制毫秒）
    - <version>, <permissions> 等完全不变

    Args:
        tree: 已解析的 XML 树（就地修改）
    """
    root = tree.getroot()
    now_hex = format(int(time.time() * 1000), "x")

    for pkg_elem in root.findall("package"):
        name = pkg_elem.get("name", "")
        if name in PACKAGES_TIMESTAMP_TARGETS:
            old_ft = pkg_elem.get("ft", "")
            old_it = pkg_elem.get("it", "")
            old_ut = pkg_elem.get("ut", "")

            pkg_elem.set("ft", now_hex)
            pkg_elem.set("it", now_hex)
            pkg_elem.set("ut", now_hex)

            logger.debug(
                "packages.xml %s: ft=%s→%s, it=%s→%s, ut=%s→%s",
                name, old_ft, now_hex, old_it, now_hex, old_ut, now_hex,
            )


def _pull_modify_push_packages_xml(
    adb: AdbExecutor,
    work_dir: Path,
) -> int:
    """Pull → 修改 → Push packages.xml。

    对应 pcapng Step 64-65 (sync: pull + push)。

    Args:
        adb: ADB 执行器
        work_dir: 临时工作目录

    Returns:
        执行的命令数量
    """
    count = 0
    local_path = work_dir / "packages.xml"

    # Pull
    pull_result = adb.pull(_PACKAGES_XML_PATH, local_path)
    count += 1
    if not pull_result.success:
        logger.error("拉取 packages.xml 失败: %s", pull_result.output)
        return count

    # Parse & Modify
    try:
        tree = ET.parse(local_path)
        _modify_packages_xml(tree)
        tree.write(local_path, encoding="utf-8", xml_declaration=True)
        logger.info("本地修改 packages.xml 完成")
    except ET.ParseError as exc:
        logger.error("XML 解析失败: %s", exc)
        return count

    # Push
    push_result = adb.push(local_path, _PACKAGES_XML_PATH)
    count += 1
    if not push_result.success:
        logger.error("推送 packages.xml 失败: %s", push_result.output)

    return count


def _phase6_system_cleanup_and_xml(
    adb: AdbExecutor,
    config: WipeConfig,
) -> PhaseResult:
    """Phase 6: 系统数据清理 + packages.xml 修改 + touch APK + 额外清理。

    对应 pcapng Step 62-75。

    Args:
        adb: ADB 执行器
        config: 清理配置

    Returns:
        PhaseResult
    """
    count = 0

    # Step 62: 批量删除系统数据路径
    paths = " ".join(SYSTEM_CLEANUP_PATHS)
    adb.shell(f"rm -rf {paths}")
    count += 1
    logger.info("系统数据目录已清理")

    # Step 63: 清理 /data/system_de/0/（保留 spblob）
    adb.shell(
        "find /data/system_de/0/* | grep -v 'spblob' | xargs rm -rf"
    )
    count += 1
    logger.info("system_de/0 已清理（保留 spblob）")

    # Step 64-65: packages.xml pull → modify → push
    with tempfile.TemporaryDirectory(prefix="michanger_wipe_") as tmp:
        count += _pull_modify_push_packages_xml(adb, Path(tmp))

    # Step 66-71: Touch 系统 APK 时间戳
    for target in TOUCH_TARGETS:
        adb.shell(f"find {target} -exec touch -m -a {{}} +")
        count += 1
    logger.info("Touch 系统 APK 时间戳完成 (%d 个)", len(TOUCH_TARGETS))

    # 额外包的 rm -rf（动态，11.0 无，11.1 有 1 个，11.2 有 2 个）
    for pkg in config.extra_cleanup_packages:
        paths = " ".join(
            tpl.format(pkg=pkg) for tpl in APP_DATA_DIR_TEMPLATES
        )
        adb.shell(f"rm -rf {paths}")
        count += 1
        logger.info("rm -rf extra: %s", pkg)

    # Step 72-75: 清理系统脚本
    for path in EXTRA_CLEANUP_PATHS:
        adb.shell(f"rm -rf {path}")
        count += 1
    logger.info("系统脚本清理完成")

    return PhaseResult(
        phase_name="System Cleanup & XML",
        phase_number=6,
        success=True,
        message="系统数据 + packages.xml + touch + 额外清理完成",
        commands_executed=count,
    )


# ------------------------------------------------------------------
# Phase 7: 正常重启 + 启用 Play Store
# ------------------------------------------------------------------

def _phase7_reboot_and_enable(adb: AdbExecutor) -> PhaseResult:
    """Phase 7: 正常重启 + pm enable com.android.vending。

    对应 pcapng Step 76-77。

    Args:
        adb: ADB 执行器

    Returns:
        PhaseResult
    """
    count = 0

    # reboot:（正常重启，无 target）
    logger.info("正常重启设备")
    adb.reboot()
    count += 1

    # 等待设备重启完成
    logger.info("等待设备重启完成...")
    adb.wait_for_device("device")
    count += 1

    # 等待 shell 就绪
    logger.info("等待 shell 就绪...")
    shell_ready = adb.wait_for_shell_ready()
    count += 1

    if not shell_ready:
        return PhaseResult(
            phase_name="Reboot & Enable",
            phase_number=7,
            success=False,
            message="设备重启后 shell 未就绪（超时）",
            commands_executed=count,
        )

    # pm enable com.android.vending
    enable_result = adb.shell("pm enable com.android.vending")
    count += 1
    logger.info("pm enable com.android.vending → %s", enable_result.output)

    return PhaseResult(
        phase_name="Reboot & Enable",
        phase_number=7,
        success=True,
        message="设备已重启，Play Store 已启用",
        commands_executed=count,
    )


# ------------------------------------------------------------------
# 主入口
# ------------------------------------------------------------------

def wipe_packages_and_reboot(
    adb_path: Path,
    serial: str,
    config: WipeConfig | None = None,
) -> WipeResult:
    """执行 Wipe Packages & Reboot 完整流程。

    严格按照 11.0-Wipe Packages & Reboot.pcapng 抓包还原的 7 个阶段。
    所有命令按原始顺序依次执行，不做跳过或优化。

    Args:
        adb_path: adb 可执行文件的绝对路径
        serial: 设备序列号
        config: 清理配置（默认无额外包）

    Returns:
        WipeResult 完整执行结果

    Raises:
        michanger.common.AdbError: adb 进程启动失败或超时
    """
    if config is None:
        config = WipeConfig()

    adb = AdbExecutor(adb_path=adb_path, serial=serial)
    phases: list[PhaseResult] = []

    logger.info("=" * 60)
    logger.info("Wipe Packages & Reboot 开始: 设备 [%s]", serial)
    logger.info(
        "  固定包: %d, 额外包: %d",
        len(FIXED_CLEANUP_PACKAGES),
        len(config.extra_cleanup_packages),
    )
    logger.info("=" * 60)

    # Phase 1: pm clear
    logger.info("--- Phase 1/7: pm clear ---")
    phase1 = _phase1_pm_clear(adb, config)
    phases.append(phase1)
    logger.info("Phase 1 完成: %s", phase1.message)

    # Phase 2: Reboot to Recovery
    logger.info("--- Phase 2/7: Reboot Recovery ---")
    phase2 = _phase2_reboot_recovery(adb)
    phases.append(phase2)
    logger.info("Phase 2 完成: %s", phase2.message)

    if not phase2.success:
        return WipeResult(
            serial=serial,
            phase_results=tuple(phases),
            success=False,
        )

    # Phase 3: Mount Partitions
    logger.info("--- Phase 3/7: Mount Partitions ---")
    phase3 = _phase3_mount_partitions(adb)
    phases.append(phase3)
    logger.info("Phase 3 完成: %s", phase3.message)

    # Phase 4: Deep Clean App Data
    logger.info("--- Phase 4/7: Deep Clean App Data ---")
    phase4 = _phase4_deep_clean_app_data(adb)
    phases.append(phase4)
    logger.info("Phase 4 完成: %s", phase4.message)

    # Phase 5: Clean /data/app/
    logger.info("--- Phase 5/7: Clean /data/app/ ---")
    phase5 = _phase5_clean_data_app(adb)
    phases.append(phase5)
    logger.info("Phase 5 完成: %s", phase5.message)

    # Phase 6: System Cleanup & XML
    logger.info("--- Phase 6/7: System Cleanup & XML ---")
    phase6 = _phase6_system_cleanup_and_xml(adb, config)
    phases.append(phase6)
    logger.info("Phase 6 完成: %s", phase6.message)

    # Phase 7: Reboot & Enable
    logger.info("--- Phase 7/7: Reboot & Enable ---")
    phase7 = _phase7_reboot_and_enable(adb)
    phases.append(phase7)
    logger.info("Phase 7 完成: %s", phase7.message)

    result = WipeResult(
        serial=serial,
        phase_results=tuple(phases),
        success=all(p.success for p in phases),
    )

    logger.info("=" * 60)
    logger.info(
        "Wipe Packages & Reboot 完成: %d/%d 阶段成功, %d 条命令",
        result.success_count, result.total_phases, result.total_commands,
    )
    logger.info("=" * 60)

    return result
