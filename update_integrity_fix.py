"""Update Integrity Fix — 更新 Play Integrity 修复.

严格按照 WiresharkLog/8.0-Update Integrity Fix/8.0-Update Integrity Fix.pcapng
抓包日志中的 ADB 命令序列一比一实现。

命令序列（28 步）：
    1.  su -c "id"                                    → 验证 root 权限
    2.  rm -rf /sdcard/modules/*.zip                  → 清理旧模块
    3.  push → /sdcard/modules/fix.zip                → 推送 Tricky Store zip
    4.  ls -1 /sdcard/modules/*.zip                   → 验证推送
    5.  su -c "magisk --install-module ..."            → 安装 Tricky Store OSS
    6.  rm -rf /sdcard/modules/                       → 清理
    7.  rm -rf /sdcard/modules/*.zip                  → 清理旧模块
    8.  push → /sdcard/modules/fix.zip                → 推送 PIF Premium zip
    9.  ls -1 /sdcard/modules/*.zip                   → 验证推送
    10. su -c "magisk --install-module ..."            → 安装 PIF Premium
    11. rm -rf /sdcard/modules/                       → 清理
    12-14. su -c mount -o rw,remount /,/product,/vendor → 挂载可写
    15-19. 写入 Tricky Store config 到 /system/etc/config
    20-22. su -c mount -o rw,remount /,/product,/vendor → 挂载可写
    23-27. 写入 security_patch.txt 到 /data/adb/tricky_store/
    28. reboot                                        → 重启

抓包上下文：
    - 设备: Pixel 4 XL (coral), Magisk 30.1, boot slot _b
    - 模块:
        Tricky Store OSS v24.ultra (by OneChanger)
        OneChanger PIF Premium (by OneChanger)

Python 官方最佳实践：
    - subprocess.run() 是推荐方法（Python 3.14 文档）
    - 参数列表（不使用 shell=True）防止命令注入
    - pathlib.Path 用于文件路径操作
    - dataclasses(frozen=True) 实现不可变数据模型
    - logging 模块进行结构化日志
    - argparse 模块处理命令行参数

参考:
    https://docs.python.org/3/library/subprocess.html#subprocess.run
    https://docs.python.org/3/library/pathlib.html
    https://docs.python.org/3/library/logging.html
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from adb_executor import AdbError, AdbExecutor
from models import IntegrityFixResult

logger = logging.getLogger(__name__)

# ── 常量 ───────────────────────────────────────────────────────────

# 设备上模块临时目录（严格按照抓包日志）
_REMOTE_MODULES_DIR: str = "/sdcard/modules"

# 设备上模块远程路径（严格按照抓包日志步骤 3/8）
_REMOTE_FIX_ZIP: str = "/sdcard/modules/fix.zip"

# 默认 push 文件目录
_DEFAULT_PUSH_DIR: str = "WiresharkLog/8.0-Update Integrity Fix/push"

# 挂载分区列表（严格按照抓包日志步骤 12-14 / 20-22）
_REMOUNT_PARTITIONS: tuple[str, ...] = ("/", "/product", "/vendor")

# Tricky Store config（严格按照抓包日志步骤 17）
_DEFAULT_CONFIG_HASH: str = (
    "cd0315e9f43897fcd9eef362b4a43b77d801d99b6f18fe3845028e92b6a1b836"
)

# Security patch 日期（严格按照抓包日志步骤 25）
_DEFAULT_SECURITY_PATCH: str = "all=2026-04-05"

# 超时设置（秒）
_SHELL_TIMEOUT: int = 30
_PUSH_TIMEOUT: int = 120
_INSTALL_TIMEOUT: int = 300
_REBOOT_TIMEOUT: int = 30

# 成功标志
_INSTALL_DONE_MARKER: str = "- Done"
_ROOT_UID_MARKER: str = "uid=0(root)"


# ── Step 1: 验证 Root 权限 ─────────────────────────────────────────


def _verify_root(executor: AdbExecutor) -> tuple[bool, str]:
    """步骤 1: su -c "id"

    对应抓包日志:
        [Frame 7] OUT OPEN arg0=3454 arg1=0 len=17 | shell:su -c "id"
        [Frame 13] IN  WRTE ... | uid=0(root) gid=0(root) groups=0(root)
                                   context=u:r:magisk:s0

    返回:
        (是否验证通过, id 命令完整输出) 的元组。
    """
    logger.info('步骤 1: su -c "id"')

    result = executor.run_shell('su -c "id"', timeout=_SHELL_TIMEOUT)

    uid_output = result.stdout if result.success else ""
    verified = _ROOT_UID_MARKER in uid_output

    if verified:
        logger.info("  Root 验证通过: %s", uid_output)
    else:
        logger.error("  Root 验证失败: %s", uid_output or result.stderr)

    return verified, uid_output


# ── Step 2-6 / 7-11: 安装单个 Magisk 模块 ─────────────────────────


def _install_module(
    executor: AdbExecutor,
    local_zip: Path,
    step_base: int,
    module_name: str,
) -> tuple[bool, str]:
    """安装单个 Magisk 模块（清理→推送→验证→安装→清理）。

    步骤 2-6 和步骤 7-11 命令模式完全相同：
        step_base+0: rm -rf /sdcard/modules/*.zip
        step_base+1: push → /sdcard/modules/fix.zip
        step_base+2: ls -1 /sdcard/modules/*.zip
        step_base+3: su -c "magisk --install-module /sdcard/modules/fix.zip"
        step_base+4: rm -rf /sdcard/modules/

    对应抓包日志:
        步骤 2-6:  安装 Tricky Store OSS v24.ultra
        步骤 7-11: 安装 OneChanger PIF Premium

    参数:
        executor: ADB 执行器实例。
        local_zip: 本地 zip 文件路径。
        step_base: 起始步骤编号（2 或 7）。
        module_name: 模块名称（用于日志）。

    返回:
        (安装是否成功, 安装输出) 的元组。
    """
    # step_base+0: rm -rf /sdcard/modules/*.zip
    logger.info("步骤 %d: rm -rf %s/*.zip", step_base, _REMOTE_MODULES_DIR)
    executor.run_shell(
        f"rm -rf {_REMOTE_MODULES_DIR}/*.zip",
        timeout=_SHELL_TIMEOUT,
    )

    # step_base+1: push → /sdcard/modules/fix.zip
    logger.info(
        "步骤 %d: push %s → %s",
        step_base + 1,
        local_zip.name,
        _REMOTE_FIX_ZIP,
    )
    push_result = executor.push(
        local_path=local_zip,
        remote_path=_REMOTE_FIX_ZIP,
        timeout=_PUSH_TIMEOUT,
    )
    if not push_result.success:
        logger.error("  推送失败: %s", push_result.stderr)
        return False, ""

    logger.info("  推送成功 ✓")

    # step_base+2: ls -1 /sdcard/modules/*.zip
    logger.info(
        "步骤 %d: ls -1 %s/*.zip", step_base + 2, _REMOTE_MODULES_DIR
    )
    ls_result = executor.run_shell(
        f"ls -1 {_REMOTE_MODULES_DIR}/*.zip",
        timeout=_SHELL_TIMEOUT,
    )
    if ls_result.stdout:
        logger.info("  %s", ls_result.stdout)

    # step_base+3: su -c "magisk --install-module /sdcard/modules/fix.zip"
    logger.info(
        '步骤 %d: su -c "magisk --install-module %s"',
        step_base + 3,
        _REMOTE_FIX_ZIP,
    )
    install_result = executor.run_shell(
        f'su -c "magisk --install-module {_REMOTE_FIX_ZIP}"',
        timeout=_INSTALL_TIMEOUT,
    )

    output = install_result.stdout if install_result.success else install_result.stderr

    # 打印安装输出（严格按照抓包日志格式）
    logger.info("  安装输出:")
    for line in output.splitlines():
        logger.info("    | %s", line)

    install_success = _INSTALL_DONE_MARKER in output

    if install_success:
        logger.info("  %s 安装成功 ✓", module_name)
    else:
        logger.error(
            "  %s 安装失败 — 未找到 '%s' 标志",
            module_name,
            _INSTALL_DONE_MARKER,
        )

    # step_base+4: rm -rf /sdcard/modules/
    logger.info("步骤 %d: rm -rf %s/", step_base + 4, _REMOTE_MODULES_DIR)
    executor.run_shell(
        f"rm -rf {_REMOTE_MODULES_DIR}/",
        timeout=_SHELL_TIMEOUT,
    )

    return install_success, output


# ── Step 12-14 / 20-22: 挂载分区为可写 ────────────────────────────


def _remount_partitions(
    executor: AdbExecutor,
    step_base: int,
) -> bool:
    """挂载分区为可写。

    步骤 12-14 和步骤 20-22 命令完全相同：
        su -c mount -o rw,remount /
        su -c mount -o rw,remount /product
        su -c mount -o rw,remount /vendor

    对应抓包日志:
        步骤 12-14: [Frame 361-431] shell,v2,raw: 挂载后写入 config
        步骤 20-22: [Frame 483-552] shell,v2,raw: 挂载后写入 security_patch

    参数:
        executor: ADB 执行器实例。
        step_base: 起始步骤编号（12 或 20）。

    返回:
        所有分区是否挂载成功。
    """
    all_success = True

    for i, partition in enumerate(_REMOUNT_PARTITIONS):
        step_num = step_base + i
        logger.info(
            "步骤 %d: su -c mount -o rw,remount %s", step_num, partition
        )
        result = executor.run_shell(
            f'su -c "mount -o rw,remount {partition}"',
            timeout=_SHELL_TIMEOUT,
        )
        if result.success:
            logger.info("  [exit code: 0]")
        else:
            logger.warning("  挂载失败: %s", result.stderr)
            all_success = False

    return all_success


# ── Step 15-19: 写入 Tricky Store config ──────────────────────────


def _write_config_file(
    executor: AdbExecutor,
    config_hash: str,
) -> bool:
    """步骤 15-19: 写入 Tricky Store config 到 /system/etc/config。

    对应抓包日志:
        [Frame 433] 步骤 15: su -c "rm -rf /sdcard/config"
        [Frame 443] 步骤 16: su -c "rm -rf /system/etc/config"
        [Frame 453] 步骤 17: su -c "printf '<hash>' > /sdcard/config"
        [Frame 463] 步骤 18: su -c "mv /sdcard/config /system/etc/config"
        [Frame 473] 步骤 19: su -c "chmod 644 /system/etc/config"

    参数:
        executor: ADB 执行器实例。
        config_hash: Tricky Store 密钥哈希值。

    返回:
        所有步骤是否成功。
    """
    # 步骤 15: rm -rf /sdcard/config
    logger.info('步骤 15: su -c "rm -rf /sdcard/config"')
    executor.run_shell(
        'su -c "rm -rf /sdcard/config"',
        timeout=_SHELL_TIMEOUT,
    )

    # 步骤 16: rm -rf /system/etc/config
    logger.info('步骤 16: su -c "rm -rf /system/etc/config"')
    executor.run_shell(
        'su -c "rm -rf /system/etc/config"',
        timeout=_SHELL_TIMEOUT,
    )

    # 步骤 17: printf '<hash>' > /sdcard/config
    logger.info("步骤 17: su -c \"printf '%s' > /sdcard/config\"", config_hash)
    result = executor.run_shell(
        f"su -c \"printf '{config_hash}' > /sdcard/config\"",
        timeout=_SHELL_TIMEOUT,
    )
    if not result.success:
        logger.error("  写入 config 失败: %s", result.stderr)
        return False

    # 步骤 18: mv /sdcard/config /system/etc/config
    logger.info('步骤 18: su -c "mv /sdcard/config /system/etc/config"')
    result = executor.run_shell(
        'su -c "mv /sdcard/config /system/etc/config"',
        timeout=_SHELL_TIMEOUT,
    )
    if not result.success:
        logger.error("  移动 config 失败: %s", result.stderr)
        return False

    # 步骤 19: chmod 644 /system/etc/config
    logger.info('步骤 19: su -c "chmod 644 /system/etc/config"')
    result = executor.run_shell(
        'su -c "chmod 644 /system/etc/config"',
        timeout=_SHELL_TIMEOUT,
    )
    if not result.success:
        logger.error("  设置权限失败: %s", result.stderr)
        return False

    logger.info("  config 写入成功 ✓")
    return True


# ── Step 23-27: 写入 security patch ───────────────────────────────


def _write_security_patch(
    executor: AdbExecutor,
    security_patch: str,
) -> bool:
    """步骤 23-27: 写入 security_patch.txt 到 Tricky Store 目录。

    对应抓包日志:
        [Frame 555] 步骤 23: su -c "rm -rf /sdcard/security_patch.txt"
        [Frame 565] 步骤 24: su -c "rm -rf /data/adb/tricky_store/security_patch.txt"
        [Frame 575] 步骤 25: su -c "printf 'all=2026-04-05' > /sdcard/security_patch.txt"
        [Frame 585] 步骤 26: su -c "mv /sdcard/security_patch.txt
                                     /data/adb/tricky_store/security_patch.txt"
        [Frame 595] 步骤 27: su -c "chmod 644
                                     /data/adb/tricky_store/security_patch.txt"

    参数:
        executor: ADB 执行器实例。
        security_patch: 安全补丁内容（例如 "all=2026-04-05"）。

    返回:
        所有步骤是否成功。
    """
    # 步骤 23: rm -rf /sdcard/security_patch.txt
    logger.info('步骤 23: su -c "rm -rf /sdcard/security_patch.txt"')
    executor.run_shell(
        'su -c "rm -rf /sdcard/security_patch.txt"',
        timeout=_SHELL_TIMEOUT,
    )

    # 步骤 24: rm -rf /data/adb/tricky_store/security_patch.txt
    logger.info(
        '步骤 24: su -c "rm -rf /data/adb/tricky_store/security_patch.txt"'
    )
    executor.run_shell(
        'su -c "rm -rf /data/adb/tricky_store/security_patch.txt"',
        timeout=_SHELL_TIMEOUT,
    )

    # 步骤 25: printf 'all=2026-04-05' > /sdcard/security_patch.txt
    logger.info(
        "步骤 25: su -c \"printf '%s' > /sdcard/security_patch.txt\"",
        security_patch,
    )
    result = executor.run_shell(
        f"su -c \"printf '{security_patch}' > /sdcard/security_patch.txt\"",
        timeout=_SHELL_TIMEOUT,
    )
    if not result.success:
        logger.error("  写入 security_patch 失败: %s", result.stderr)
        return False

    # 步骤 26: mv /sdcard/security_patch.txt → tricky_store 目录
    logger.info(
        '步骤 26: su -c "mv /sdcard/security_patch.txt'
        ' /data/adb/tricky_store/security_patch.txt"'
    )
    result = executor.run_shell(
        'su -c "mv /sdcard/security_patch.txt'
        ' /data/adb/tricky_store/security_patch.txt"',
        timeout=_SHELL_TIMEOUT,
    )
    if not result.success:
        logger.error("  移动 security_patch 失败: %s", result.stderr)
        return False

    # 步骤 27: chmod 644 /data/adb/tricky_store/security_patch.txt
    logger.info(
        '步骤 27: su -c "chmod 644'
        ' /data/adb/tricky_store/security_patch.txt"'
    )
    result = executor.run_shell(
        'su -c "chmod 644 /data/adb/tricky_store/security_patch.txt"',
        timeout=_SHELL_TIMEOUT,
    )
    if not result.success:
        logger.error("  设置权限失败: %s", result.stderr)
        return False

    logger.info("  security_patch 写入成功 ✓")
    return True


# ── Step 28: 重启设备 ────────────────────────────────────────────


def _reboot_device(executor: AdbExecutor) -> None:
    """步骤 28: reboot

    对应抓包日志:
        [Frame 605] OUT OPEN arg0=3500 arg1=0 len=8 | reboot:
        [Frame 609] IN  OKAY

    重启设备到正常系统，使配置生效。
    """
    logger.info("步骤 28: reboot")

    executor.reboot(timeout=_REBOOT_TIMEOUT)
    logger.info("  重启命令已发送，设备将启动到系统")


# ── 主流程 ─────────────────────────────────────────────────────────


def update_integrity_fix(
    executor: AdbExecutor,
    push_dir: Path,
    config_hash: str = _DEFAULT_CONFIG_HASH,
    security_patch: str = _DEFAULT_SECURITY_PATCH,
) -> IntegrityFixResult:
    """更新 Play Integrity 修复。

    严格按照 8.0-Update Integrity Fix.pcapng 抓包日志中的命令顺序执行 28 步：
        1.     su -c "id"                        → 验证 root
        2-6.   安装 Tricky Store OSS             → 清理→推送→验证→安装→清理
        7-11.  安装 OneChanger PIF Premium       → 清理→推送→验证→安装→清理
        12-14. su -c mount -o rw,remount         → 挂载分区可写
        15-19. 写入 config 哈希                  → /system/etc/config
        20-22. su -c mount -o rw,remount         → 挂载分区可写
        23-27. 写入 security_patch               → tricky_store 目录
        28.    reboot                            → 重启设备

    push 目录中应有 2 个 zip 文件，按文件名排序后：
        第 1 个 → Tricky Store（对应步骤 3）
        第 2 个 → PIF Premium（对应步骤 8）

    参数:
        executor: ADB 命令执行器实例。
        push_dir: 包含 2 个 fix.zip 文件的本地目录。
        config_hash: Tricky Store config 哈希值。
        security_patch: 安全补丁内容。

    返回:
        包含所有步骤执行结果的 IntegrityFixResult。

    抛出:
        AdbError: 如果 ADB 不可用或设备未连接。
    """
    logger.info("=" * 60)
    logger.info("Update Integrity Fix — 开始更新 Play Integrity 修复")
    logger.info("=" * 60)

    # 验证 push 目录（Python pathlib 最佳实践）
    resolved_dir = push_dir.resolve()
    if not resolved_dir.is_dir():
        msg = f"push 目录不存在: {resolved_dir}"
        logger.error(msg)
        raise AdbError(msg)

    # 发现 push 文件（按文件名排序，严格对应抓包日志时序）
    zip_files = sorted(resolved_dir.glob("*.zip"))
    if len(zip_files) != 2:
        msg = f"push 目录中应有 2 个 zip 文件，实际发现 {len(zip_files)} 个"
        logger.error(msg)
        raise AdbError(msg)

    tricky_store_zip = zip_files[0]
    pif_zip = zip_files[1]

    logger.info("push 目录: %s", resolved_dir)
    logger.info("  Tricky Store: %s (%.1f KB)", tricky_store_zip.name,
                tricky_store_zip.stat().st_size / 1024)
    logger.info("  PIF Premium:  %s (%.1f KB)", pif_zip.name,
                pif_zip.stat().st_size / 1024)

    # Step 1: 验证 Root 权限
    root_verified, root_uid = _verify_root(executor)

    if not root_verified:
        logger.error("Root 验证失败，中止操作")
        return IntegrityFixResult(
            root_verified=False,
            root_uid=root_uid,
            tricky_store_installed=False,
            tricky_store_output="",
            pif_installed=False,
            pif_output="",
            config_written=False,
            security_patch_written=False,
        )

    # Step 2-6: 安装 Tricky Store OSS
    ts_installed, ts_output = _install_module(
        executor, tricky_store_zip, step_base=2,
        module_name="Tricky Store OSS",
    )

    # Step 7-11: 安装 OneChanger PIF Premium
    pif_installed, pif_output = _install_module(
        executor, pif_zip, step_base=7,
        module_name="OneChanger PIF Premium",
    )

    # Step 12-14: 挂载分区为可写（用于写入 config）
    _remount_partitions(executor, step_base=12)

    # Step 15-19: 写入 Tricky Store config
    config_written = _write_config_file(executor, config_hash)

    # Step 20-22: 挂载分区为可写（用于写入 security_patch）
    _remount_partitions(executor, step_base=20)

    # Step 23-27: 写入 security patch
    sp_written = _write_security_patch(executor, security_patch)

    # Step 28: 重启设备
    _reboot_device(executor)

    result = IntegrityFixResult(
        root_verified=root_verified,
        root_uid=root_uid,
        tricky_store_installed=ts_installed,
        tricky_store_output=ts_output,
        pif_installed=pif_installed,
        pif_output=pif_output,
        config_written=config_written,
        security_patch_written=sp_written,
    )

    _print_summary(result)
    return result


# ── 结果输出 ───────────────────────────────────────────────────────


def _print_summary(result: IntegrityFixResult) -> None:
    """打印可读的 Integrity Fix 结果汇总。"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("Update Integrity Fix — 执行结果汇总")
    logger.info("=" * 60)
    logger.info("  Root 验证:            %s (%s)",
                result.root_verified, result.root_uid)
    logger.info("  Tricky Store 安装:    %s", result.tricky_store_installed)
    logger.info("  PIF Premium 安装:     %s", result.pif_installed)
    logger.info("  Config 写入:          %s", result.config_written)
    logger.info("  Security Patch 写入:  %s", result.security_patch_written)

    all_ok = all([
        result.tricky_store_installed,
        result.pif_installed,
        result.config_written,
        result.security_patch_written,
    ])

    if all_ok:
        logger.info("  状态: ✓ Integrity Fix 更新完成，设备重启中")
    else:
        logger.error("  状态: ✗ 部分步骤失败，请检查日志")

    logger.info("=" * 60)


# ── CLI 入口 ───────────────────────────────────────────────────────


def main() -> None:
    """Update Integrity Fix 的命令行入口。

    用法:
        python update_integrity_fix.py [--push-dir <path>]
                                       [--config-hash <hash>]
                                       [--security-patch <patch>]
    """
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Python 官方推荐：使用 argparse 模块处理命令行参数
    parser = argparse.ArgumentParser(
        description="Update Integrity Fix — 更新 Play Integrity 修复",
    )
    parser.add_argument(
        "--push-dir",
        type=Path,
        default=None,
        help="包含 fix.zip 文件的目录 (默认: 项目内置路径)",
    )
    parser.add_argument(
        "--config-hash",
        type=str,
        default=_DEFAULT_CONFIG_HASH,
        help="Tricky Store config 哈希值",
    )
    parser.add_argument(
        "--security-patch",
        type=str,
        default=_DEFAULT_SECURITY_PATCH,
        help="安全补丁内容 (默认: all=2026-04-05)",
    )

    args = parser.parse_args()

    # 使用项目内置的 platform-tools/adb.exe
    project_root = Path(__file__).resolve().parent
    adb_path = project_root / "platform-tools" / "adb.exe"

    if not adb_path.exists():
        logger.error("未找到 ADB: %s", adb_path)
        sys.exit(1)

    # 确定 push 目录路径
    if args.push_dir is not None:
        push_dir = args.push_dir
    else:
        push_dir = project_root / _DEFAULT_PUSH_DIR

    logger.info("ADB:              %s", adb_path)
    logger.info("Push 目录:        %s", push_dir)
    logger.info("Config Hash:      %s", args.config_hash)
    logger.info("Security Patch:   %s", args.security_patch)

    executor = AdbExecutor(adb_path=adb_path)

    try:
        result = update_integrity_fix(
            executor, push_dir,
            config_hash=args.config_hash,
            security_patch=args.security_patch,
        )
    except AdbError as e:
        logger.error("ADB 错误: %s", e)
        sys.exit(1)

    # 根据结果设置退出码
    all_ok = all([
        result.tricky_store_installed,
        result.pif_installed,
        result.config_written,
        result.security_patch_written,
    ])
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
