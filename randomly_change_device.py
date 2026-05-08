"""Randomly Change Device — 主流程编排.

严格按照 WiresharkLog/7.0-Randomly change device/7.0-Randomly change device.pcapng
抓包日志中的 332 步 ADB 命令序列一比一实现设备信息随机化功能。

命令序列（332 步，10 个阶段）：
    阶段 A (步骤 1-2):     设备状态检查
    阶段 B (步骤 3-31):    系统准备 & 清理应用数据
    阶段 C (步骤 32-47):   重启到 Recovery & 挂载分区
    阶段 D (步骤 48-138):  修改 /prop.default
    阶段 E (步骤 139-155): 修改 /system_root/system/product/build.prop
    阶段 F (步骤 156-186): 修改 /system_root/system/build.prop
    阶段 G (步骤 187-203): 修改 /system_ext/build.prop
    阶段 H (步骤 204-218): 修改 /odm/etc/build.prop
    阶段 I (步骤 219-239): 修改 /vendor/build.prop
    阶段 J (步骤 240-268): 安全属性 & MiChanger 文件写入
    阶段 K (步骤 269-315): 数据清理 & XML 文件推送
    阶段 L (步骤 316-332): 重启 & 验证

Python 官方最佳实践：
    - argparse 模块处理命令行参数
    - logging 模块进行结构化日志
    - tempfile 模块用于安全的临时文件操作
    - pathlib.Path 用于路径操作

参考:
    https://docs.python.org/3/library/argparse.html
    https://docs.python.org/3/library/logging.html
    https://docs.python.org/3/library/tempfile.html
"""

from __future__ import annotations

import logging
import sys
import tempfile
from pathlib import Path

from adb_executor import AdbError, AdbExecutor
from models import RandomDeviceResult
from randomly_change_device_data import (
    cleanup_and_push,
    reboot_and_verify,
    set_security_props_and_mi_files,
)
from randomly_change_device_prep import (
    check_device_state,
    prepare_system,
    reboot_and_mount,
)
from randomly_change_device_prop import (
    modify_odm_build_prop,
    modify_product_build_prop,
    modify_prop_default,
    modify_system_build_prop,
    modify_system_ext_build_prop,
    modify_vendor_build_prop,
)

logger = logging.getLogger(__name__)

# 目标设备信息（严格按照抓包日志中的值）
_TARGET_DEVICE_NAME: str = "Pixel 10 Pro"
_TARGET_ANDROID_ID: str = "dce5d1470ae48e43"


def randomly_change_device(
    executor: AdbExecutor,
) -> RandomDeviceResult:
    """执行 Randomly Change Device 完整流程。

    严格按照 7.0-Randomly change device.pcapng 抓包日志中的
    332 步命令序列逐行执行。

    参数:
        executor: ADB 命令执行器实例。

    返回:
        包含所有阶段执行结果的 RandomDeviceResult。

    抛出:
        AdbError: 如果 ADB 不可用或设备未连接。
    """
    logger.info("=" * 60)
    logger.info("Randomly Change Device — 开始执行")
    logger.info("=" * 60)

    # ── 阶段 A: 设备状态检查 (步骤 1-2) ─────────────────────
    logger.info("")
    logger.info("━" * 40)
    logger.info("阶段 A: 设备状态检查 (步骤 1-2)")
    logger.info("━" * 40)
    locale, gmail_accounts = check_device_state(executor)

    # ── 阶段 B: 系统准备 (步骤 3-31) ────────────────────────
    logger.info("")
    logger.info("━" * 40)
    logger.info("阶段 B: 系统准备 & 清理应用数据 (步骤 3-31)")
    logger.info("━" * 40)
    prepare_success = prepare_system(executor)

    # ── 阶段 C: 重启到 Recovery & 挂载 (步骤 32-47) ─────────
    logger.info("")
    logger.info("━" * 40)
    logger.info("阶段 C: 重启到 Recovery & 挂载分区 (步骤 32-47)")
    logger.info("━" * 40)
    recovery_mounted = reboot_and_mount(executor)

    # ── 阶段 D: 修改 /prop.default (步骤 48-138) ───────────
    logger.info("")
    logger.info("━" * 40)
    logger.info("阶段 D: 修改 /prop.default (步骤 48-138)")
    logger.info("━" * 40)
    prop_default_ok = modify_prop_default(executor)

    # ── 阶段 E: 修改 product/build.prop (步骤 139-155) ──────
    logger.info("")
    logger.info("━" * 40)
    logger.info("阶段 E: 修改 product/build.prop (步骤 139-155)")
    logger.info("━" * 40)
    product_ok = modify_product_build_prop(executor)

    # ── 阶段 F: 修改 system/build.prop (步骤 156-186) ───────
    logger.info("")
    logger.info("━" * 40)
    logger.info("阶段 F: 修改 system/build.prop (步骤 156-186)")
    logger.info("━" * 40)
    system_ok = modify_system_build_prop(executor)

    # ── 阶段 G: 修改 system_ext/build.prop (步骤 187-203) ───
    logger.info("")
    logger.info("━" * 40)
    logger.info("阶段 G: 修改 system_ext/build.prop (步骤 187-203)")
    logger.info("━" * 40)
    sysext_ok = modify_system_ext_build_prop(executor)

    # ── 阶段 H: 修改 odm/etc/build.prop (步骤 204-218) ──────
    logger.info("")
    logger.info("━" * 40)
    logger.info("阶段 H: 修改 odm/etc/build.prop (步骤 204-218)")
    logger.info("━" * 40)
    odm_ok = modify_odm_build_prop(executor)

    # ── 阶段 I: 修改 vendor/build.prop (步骤 219-239) ───────
    logger.info("")
    logger.info("━" * 40)
    logger.info("阶段 I: 修改 vendor/build.prop (步骤 219-239)")
    logger.info("━" * 40)
    vendor_ok = modify_vendor_build_prop(executor)

    # 收集修改成功的 prop 文件列表
    prop_files: list[str] = []
    if prop_default_ok:
        prop_files.append("/prop.default")
    if product_ok:
        prop_files.append("/system_root/system/product/build.prop")
    if system_ok:
        prop_files.append("/system_root/system/build.prop")
    if sysext_ok:
        prop_files.append("/system_ext/build.prop")
    if odm_ok:
        prop_files.append("/odm/etc/build.prop")
    if vendor_ok:
        prop_files.append("/vendor/build.prop")

    # ── 阶段 J: 安全属性 & MiChanger (步骤 240-268) ────────
    logger.info("")
    logger.info("━" * 40)
    logger.info("阶段 J: 安全属性 & MiChanger 文件 (步骤 240-268)")
    logger.info("━" * 40)
    security_ok, mi_ok = set_security_props_and_mi_files(executor)

    # ── 阶段 K: 数据清理 & 推送 (步骤 269-315) ─────────────
    logger.info("")
    logger.info("━" * 40)
    logger.info("阶段 K: 数据清理 & 文件推送 (步骤 269-315)")
    logger.info("━" * 40)

    # 使用临时目录存放 pull/push 的 XML 文件
    # Python 官方推荐：tempfile.mkdtemp() 创建安全临时目录
    work_dir = Path(tempfile.mkdtemp(prefix="rcd_"))
    logger.info("  工作目录: %s", work_dir)

    pkg_ok, settings_ok, data_cleaned = cleanup_and_push(
        executor, work_dir,
        device_name=_TARGET_DEVICE_NAME,
        android_id=_TARGET_ANDROID_ID,
    )

    # ── 阶段 L: 重启 & 验证 (步骤 316-332) ─────────────────
    logger.info("")
    logger.info("━" * 40)
    logger.info("阶段 L: 重启 & 验证 (步骤 316-332)")
    logger.info("━" * 40)
    reboot_ok, brand, model, version, vending_ok, packages = (
        reboot_and_verify(executor)
    )

    result = RandomDeviceResult(
        locale=locale,
        gmail_accounts=gmail_accounts,
        prepare_success=prepare_success,
        recovery_mounted=recovery_mounted,
        prop_files_modified=tuple(prop_files),
        security_props_set=security_ok,
        mi_files_written=mi_ok,
        data_cleaned=data_cleaned,
        packages_xml_pushed=pkg_ok,
        settings_pushed=settings_ok,
        reboot_success=reboot_ok,
        verified_brand=brand,
        verified_model=model,
        verified_version=version,
        vending_enabled=vending_ok,
        third_party_packages=packages,
    )

    _print_summary(result)
    return result


# ── 结果输出 ───────────────────────────────────────────────────────


def _print_summary(result: RandomDeviceResult) -> None:
    """打印可读的执行结果汇总。"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("Randomly Change Device — 执行结果汇总")
    logger.info("=" * 60)
    logger.info("  Locale:            %s", result.locale or "(空)")
    logger.info("  Gmail 账户:        %d 个", len(result.gmail_accounts))
    logger.info("  系统准备:          %s", result.prepare_success)
    logger.info("  Recovery 挂载:     %s", result.recovery_mounted)
    logger.info("  修改的 prop 文件:  %d 个", len(result.prop_files_modified))
    for f in result.prop_files_modified:
        logger.info("    - %s", f)
    logger.info("  安全属性:          %s", result.security_props_set)
    logger.info("  MiChanger 文件:    %s", result.mi_files_written)
    logger.info("  数据清理:          %s", result.data_cleaned)
    logger.info("  packages.xml:      %s", result.packages_xml_pushed)
    logger.info("  settings XML:      %s", result.settings_pushed)
    logger.info("  重启:              %s", result.reboot_success)
    logger.info("  验证品牌:          %s", result.verified_brand)
    logger.info("  验证型号:          %s", result.verified_model)
    logger.info("  验证版本:          %s", result.verified_version)
    logger.info("  Play Store:        %s", result.vending_enabled)
    logger.info("  第三方包:          %s", list(result.third_party_packages))
    logger.info("=" * 60)


# ── CLI 入口 ───────────────────────────────────────────────────────


def main() -> None:
    """Randomly Change Device 的命令行入口。

    用法:
        python randomly_change_device.py
    """
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Randomly Change Device — 设备信息随机化",
    )
    parser.parse_args()

    # 使用项目内置的 platform-tools/adb.exe
    project_root = Path(__file__).resolve().parent
    adb_path = project_root / "platform-tools" / "adb.exe"

    if not adb_path.exists():
        logger.error("未找到 ADB: %s", adb_path)
        sys.exit(1)

    logger.info("ADB: %s", adb_path)

    executor = AdbExecutor(adb_path=adb_path)

    try:
        result = randomly_change_device(executor)
    except AdbError as e:
        logger.error("ADB 错误: %s", e)
        sys.exit(1)

    sys.exit(0 if result.reboot_success else 1)


if __name__ == "__main__":
    main()
