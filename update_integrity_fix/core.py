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

参考:
    https://docs.python.org/3/library/subprocess.html#subprocess.run
    https://docs.python.org/3/library/pathlib.html
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from .adb_executor import AdbError, AdbExecutor
from .models import IntegrityFixResult

logger = logging.getLogger(__name__)

# ── 常量 ───────────────────────────────────────────────────────────

_REMOTE_MODULES_DIR: str = "/sdcard/modules"
_REMOTE_FIX_ZIP: str = "/sdcard/modules/fix.zip"
_DEFAULT_PUSH_DIR: str = "data/push"
_REMOUNT_PARTITIONS: tuple[str, ...] = ("/", "/product", "/vendor")

_DEFAULT_CONFIG_HASH: str = (
    "cd0315e9f43897fcd9eef362b4a43b77d801d99b6f18fe3845028e92b6a1b836"
)
_DEFAULT_SECURITY_PATCH: str = "all=2026-04-05"

_SHELL_TIMEOUT: int = 30
_PUSH_TIMEOUT: int = 120
_INSTALL_TIMEOUT: int = 300
_REBOOT_TIMEOUT: int = 30

_INSTALL_DONE_MARKER: str = "- Done"
_ROOT_UID_MARKER: str = "uid=0(root)"


# ── Step 1: 验证 Root 权限 ─────────────────────────────────────────

def _verify_root(executor: AdbExecutor) -> tuple[bool, str]:
    """步骤 1: su -c "id"."""
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
    """安装单个 Magisk 模块（清理→推送→验证→安装→清理）."""
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
    """挂载分区为可写."""
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
    """步骤 15-19: 写入 Tricky Store config 到 /system/etc/config."""
    logger.info('步骤 15: su -c "rm -rf /sdcard/config"')
    executor.run_shell(
        'su -c "rm -rf /sdcard/config"',
        timeout=_SHELL_TIMEOUT,
    )

    logger.info('步骤 16: su -c "rm -rf /system/etc/config"')
    executor.run_shell(
        'su -c "rm -rf /system/etc/config"',
        timeout=_SHELL_TIMEOUT,
    )

    logger.info("步骤 17: su -c \"printf '%s' > /sdcard/config\"", config_hash)
    result = executor.run_shell(
        f"su -c \"printf '{config_hash}' > /sdcard/config\"",
        timeout=_SHELL_TIMEOUT,
    )
    if not result.success:
        logger.error("  写入 config 失败: %s", result.stderr)
        return False

    logger.info('步骤 18: su -c "mv /sdcard/config /system/etc/config"')
    result = executor.run_shell(
        'su -c "mv /sdcard/config /system/etc/config"',
        timeout=_SHELL_TIMEOUT,
    )
    if not result.success:
        logger.error("  移动 config 失败: %s", result.stderr)
        return False

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
    """步骤 23-27: 写入 security_patch.txt 到 Tricky Store 目录."""
    logger.info('步骤 23: su -c "rm -rf /sdcard/security_patch.txt"')
    executor.run_shell(
        'su -c "rm -rf /sdcard/security_patch.txt"',
        timeout=_SHELL_TIMEOUT,
    )

    logger.info(
        '步骤 24: su -c "rm -rf /data/adb/tricky_store/security_patch.txt"'
    )
    executor.run_shell(
        'su -c "rm -rf /data/adb/tricky_store/security_patch.txt"',
        timeout=_SHELL_TIMEOUT,
    )

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
    """步骤 28: reboot."""
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
    """更新 Play Integrity 修复.

    参数:
        executor: ADB 命令执行器实例。
        push_dir: 包含 2 个 fix.zip 文件的本地目录。
        config_hash: Tricky Store config 哈希值。
        security_patch: 安全补丁内容。

    返回:
        包含所有步骤执行结果的 IntegrityFixResult。
    """
    logger.info("=" * 60)
    logger.info("Update Integrity Fix — 开始更新 Play Integrity 修复")
    logger.info("=" * 60)

    resolved_dir = push_dir.resolve()
    if not resolved_dir.is_dir():
        msg = f"push 目录不存在: {resolved_dir}"
        logger.error(msg)
        raise AdbError(msg)

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

    ts_installed, ts_output = _install_module(
        executor, tricky_store_zip, step_base=2,
        module_name="Tricky Store OSS",
    )

    pif_installed, pif_output = _install_module(
        executor, pif_zip, step_base=7,
        module_name="OneChanger PIF Premium",
    )

    _remount_partitions(executor, step_base=12)
    config_written = _write_config_file(executor, config_hash)

    _remount_partitions(executor, step_base=20)
    sp_written = _write_security_patch(executor, security_patch)

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
    """打印可读的 Integrity Fix 结果汇总."""
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
    """Update Integrity Fix 的命令行入口.

    用法:
        python -m update_integrity_fix [--push-dir <path>]
    """
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Update Integrity Fix — 更新 Play Integrity 修复",
    )
    parser.add_argument(
        "--push-dir",
        type=Path,
        default=None,
        help="包含 fix.zip 文件的目录 (默认: 模块内置路径)",
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

    module_root = Path(__file__).resolve().parent
    adb_path = module_root.parent / "platform-tools" / "adb.exe"

    if not adb_path.exists():
        logger.error("未找到 ADB: %s", adb_path)
        sys.exit(1)

    if args.push_dir is not None:
        push_dir = args.push_dir
    else:
        push_dir = module_root / _DEFAULT_PUSH_DIR

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

    all_ok = all([
        result.tricky_store_installed,
        result.pif_installed,
        result.config_written,
        result.security_patch_written,
    ])
    sys.exit(0 if all_ok else 1)
