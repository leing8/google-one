"""Install Modules — 安装 Magisk 模块.

严格按照 WiresharkLog/6.0-Install Modules/6.0-Install Modules.pcapng 抓包日志中的
ADB 命令序列一比一实现 Magisk 模块安装功能。

命令序列（12 步）：
    1. shell:su -c "id"                            → 验证 root 权限
    2. shell:su -c "magisk --remove-modules -n"    → 移除已有模块（不重启）
    3. shell:su -c "rm -rf /data/adb/modules/*"    → 清理模块数据目录
    4. shell,v2:rm -rf /sdcard/modules             → 清理设备临时目录
    5. push → /sdcard/modules/*.zip                → 推送所有模块文件（4 个）
    6. shell:ls -1 /sdcard/modules/*.zip           → 列出并验证推送结果
    7-10. magisk --install-module                  → 安装各模块
    11. shell,v2:rm -rf /sdcard/modules            → 清理设备临时目录
    12. reboot:                                    → 重启到系统

参考:
    https://docs.python.org/3/library/subprocess.html#subprocess.run
    https://docs.python.org/3/library/pathlib.html
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from .adb_executor import AdbError, AdbExecutor
from .models import ModuleInstallDetail, ModulesInstallResult

logger = logging.getLogger(__name__)

# ── 常量 ───────────────────────────────────────────────────────────

_REMOTE_MODULES_DIR: str = "/sdcard/modules"
_DEFAULT_MODULES_DIR: str = "data/modules"

_SHELL_TIMEOUT: int = 30
_PUSH_TIMEOUT: int = 120
_INSTALL_TIMEOUT: int = 300
_REBOOT_TIMEOUT: int = 30

_INSTALL_DONE_MARKER: str = "- Done"
_ROOT_UID_MARKER: str = "uid=0(root)"


# ── Step 1: 验证 Root 权限 ─────────────────────────────────────────

def _verify_root(executor: AdbExecutor) -> tuple[bool, str]:
    """步骤 1: su -c "id"."""
    logger.info("步骤 1: su -c \"id\"")

    result = executor.run_shell('su -c "id"', timeout=_SHELL_TIMEOUT)

    uid_output = result.stdout if result.success else ""
    verified = _ROOT_UID_MARKER in uid_output

    if verified:
        logger.info("  Root 验证通过: %s", uid_output)
    else:
        logger.error("  Root 验证失败: %s", uid_output or result.stderr)

    return verified, uid_output


# ── Step 2: 移除已有模块 ──────────────────────────────────────────

def _remove_existing_modules(executor: AdbExecutor) -> bool:
    """步骤 2: su -c "magisk --remove-modules -n"."""
    logger.info('步骤 2: su -c "magisk --remove-modules -n"')

    result = executor.run_shell(
        'su -c "magisk --remove-modules -n"',
        timeout=_SHELL_TIMEOUT,
    )

    if result.success:
        logger.info("  模块移除完成")
    else:
        logger.warning("  模块移除失败: %s", result.stderr)

    return result.success


# ── Step 3: 清理模块数据目录 ──────────────────────────────────────

def _clean_modules_data(executor: AdbExecutor) -> bool:
    """步骤 3: su -c "rm -rf /data/adb/modules/*"."""
    logger.info('步骤 3: su -c "rm -rf /data/adb/modules/*"')

    result = executor.run_shell(
        'su -c "rm -rf /data/adb/modules/*"',
        timeout=_SHELL_TIMEOUT,
    )

    if result.success:
        logger.info("  模块数据目录已清理")
    else:
        logger.warning("  清理失败: %s", result.stderr)

    return result.success


# ── Step 4: 清理设备临时目录 ──────────────────────────────────────

def _clean_sdcard_staging(executor: AdbExecutor) -> bool:
    """步骤 4: rm -rf /sdcard/modules."""
    logger.info("步骤 4: rm -rf %s", _REMOTE_MODULES_DIR)

    result = executor.run_shell(
        f"rm -rf {_REMOTE_MODULES_DIR}",
        timeout=_SHELL_TIMEOUT,
    )

    if result.success:
        logger.info("  临时目录已清理")
    else:
        logger.warning("  清理失败: %s", result.stderr)

    return result.success


# ── Step 5: 推送所有模块文件 ──────────────────────────────────────

def _push_all_modules(
    executor: AdbExecutor,
    modules_dir: Path,
) -> tuple[tuple[str, ...], bool]:
    """步骤 5: push → /sdcard/modules/*.zip."""
    logger.info("步骤 5: push 模块文件到 %s/", _REMOTE_MODULES_DIR)

    zip_files = sorted(modules_dir.glob("*.zip"))

    if not zip_files:
        logger.error("  模块目录中未找到 .zip 文件: %s", modules_dir)
        return (), False

    logger.info("  发现 %d 个模块文件:", len(zip_files))
    for f in zip_files:
        size_mb = f.stat().st_size / (1024 * 1024)
        logger.info("    %s (%.2f MB)", f.name, size_mb)

    pushed: list[str] = []
    all_success = True

    for zip_file in zip_files:
        remote_path = f"{_REMOTE_MODULES_DIR}/{zip_file.name}"
        logger.info("  推送: %s → %s", zip_file.name, remote_path)

        result = executor.push(
            local_path=zip_file,
            remote_path=remote_path,
            timeout=_PUSH_TIMEOUT,
        )

        if result.success:
            logger.info("    推送成功 ✓")
            pushed.append(zip_file.name)
        else:
            logger.error("    推送失败: %s", result.stderr)
            all_success = False

    return tuple(pushed), all_success


# ── Step 6: 验证推送文件 ──────────────────────────────────────────

def _verify_pushed_files(executor: AdbExecutor) -> tuple[str, ...]:
    """步骤 6: ls -1 /sdcard/modules/*.zip."""
    logger.info("步骤 6: ls -1 %s/*.zip", _REMOTE_MODULES_DIR)

    result = executor.run_shell(
        f"ls -1 {_REMOTE_MODULES_DIR}/*.zip",
        timeout=_SHELL_TIMEOUT,
    )

    if not result.success or not result.stdout:
        logger.error("  设备上未找到模块文件: %s", result.stderr)
        return ()

    files = tuple(
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip()
    )

    logger.info("  设备上的模块文件 (%d 个):", len(files))
    for f in files:
        logger.info("    %s", f)

    return files


# ── Step 7-10: 安装单个模块 ───────────────────────────────────────

def _install_single_module(
    executor: AdbExecutor,
    remote_path: str,
    step_num: int,
) -> ModuleInstallDetail:
    """步骤 7-10: su -c "magisk --install-module <path>"."""
    filename = remote_path.rsplit("/", maxsplit=1)[-1]

    logger.info(
        '步骤 %d: su -c "magisk --install-module %s"',
        step_num,
        remote_path,
    )

    result = executor.run_shell(
        f'su -c "magisk --install-module {remote_path}"',
        timeout=_INSTALL_TIMEOUT,
    )

    output = result.stdout if result.success else result.stderr

    logger.info("  安装输出:")
    for line in output.splitlines():
        logger.info("    | %s", line)

    install_success = _INSTALL_DONE_MARKER in output

    if install_success:
        logger.info("  %s 安装成功 ✓", filename)
    else:
        logger.error("  %s 安装失败 — 未找到 '%s' 标志", filename, _INSTALL_DONE_MARKER)

    return ModuleInstallDetail(
        filename=filename,
        remote_path=remote_path,
        install_output=output,
        install_success=install_success,
    )


# ── Step 11: 清理临时目录 ────────────────────────────────────────

def _cleanup_staging(executor: AdbExecutor) -> bool:
    """步骤 11: rm -rf /sdcard/modules."""
    logger.info("步骤 11: rm -rf %s", _REMOTE_MODULES_DIR)

    result = executor.run_shell(
        f"rm -rf {_REMOTE_MODULES_DIR}",
        timeout=_SHELL_TIMEOUT,
    )

    if result.success:
        logger.info("  临时目录已清理 ✓")
    else:
        logger.warning("  清理失败: %s", result.stderr)

    return result.success


# ── Step 12: 重启设备 ────────────────────────────────────────────

def _reboot_device(executor: AdbExecutor) -> None:
    """步骤 12: reboot."""
    logger.info("步骤 12: reboot")

    executor.reboot(timeout=_REBOOT_TIMEOUT)
    logger.info("  重启命令已发送，设备将启动到系统")


# ── 主流程 ─────────────────────────────────────────────────────────

def install_modules(
    executor: AdbExecutor,
    modules_dir: Path,
) -> ModulesInstallResult:
    """安装 Magisk 模块.

    参数:
        executor: ADB 命令执行器实例。
        modules_dir: 本地模块 zip 文件所在目录。

    返回:
        包含所有步骤执行结果的 ModulesInstallResult。
    """
    logger.info("=" * 60)
    logger.info("Install Modules — 开始安装 Magisk 模块")
    logger.info("=" * 60)

    resolved_dir = modules_dir.resolve()
    if not resolved_dir.exists():
        msg = f"模块目录不存在: {resolved_dir}"
        logger.error(msg)
        raise AdbError(msg)

    if not resolved_dir.is_dir():
        msg = f"路径不是目录: {resolved_dir}"
        logger.error(msg)
        raise AdbError(msg)

    logger.info("模块目录: %s", resolved_dir)

    root_verified, root_uid = _verify_root(executor)

    if not root_verified:
        logger.error("Root 验证失败，中止安装")
        return ModulesInstallResult(
            root_verified=False,
            root_uid=root_uid,
            remove_modules_success=False,
            clean_data_success=False,
            clean_sdcard_success=False,
            pushed_files=(),
            push_success=False,
            verified_files=(),
            module_results=(),
            cleanup_success=False,
            all_modules_installed=False,
        )

    remove_success = _remove_existing_modules(executor)
    clean_data_success = _clean_modules_data(executor)
    clean_sdcard_success = _clean_sdcard_staging(executor)

    pushed_files, push_success = _push_all_modules(executor, resolved_dir)

    if not push_success:
        logger.error("模块推送失败，中止安装")
        return ModulesInstallResult(
            root_verified=root_verified,
            root_uid=root_uid,
            remove_modules_success=remove_success,
            clean_data_success=clean_data_success,
            clean_sdcard_success=clean_sdcard_success,
            pushed_files=pushed_files,
            push_success=False,
            verified_files=(),
            module_results=(),
            cleanup_success=False,
            all_modules_installed=False,
        )

    verified_files = _verify_pushed_files(executor)

    module_results: list[ModuleInstallDetail] = []
    for step_num, remote_path in enumerate(verified_files, start=7):
        detail = _install_single_module(executor, remote_path, step_num)
        module_results.append(detail)

    all_installed = all(m.install_success for m in module_results)

    cleanup_success = _cleanup_staging(executor)
    _reboot_device(executor)

    result = ModulesInstallResult(
        root_verified=root_verified,
        root_uid=root_uid,
        remove_modules_success=remove_success,
        clean_data_success=clean_data_success,
        clean_sdcard_success=clean_sdcard_success,
        pushed_files=pushed_files,
        push_success=push_success,
        verified_files=verified_files,
        module_results=tuple(module_results),
        cleanup_success=cleanup_success,
        all_modules_installed=all_installed,
    )

    _print_summary(result)
    return result


# ── 结果输出 ───────────────────────────────────────────────────────

def _print_summary(result: ModulesInstallResult) -> None:
    """打印可读的模块安装结果汇总."""
    logger.info("")
    logger.info("=" * 60)
    logger.info("Install Modules — 安装结果汇总")
    logger.info("=" * 60)
    logger.info("  Root 验证:        %s (%s)", result.root_verified, result.root_uid)
    logger.info("  移除旧模块:      %s", result.remove_modules_success)
    logger.info("  清理数据目录:    %s", result.clean_data_success)
    logger.info("  清理临时目录:    %s", result.clean_sdcard_success)
    logger.info("  推送文件:        %d 个", len(result.pushed_files))
    for f in result.pushed_files:
        logger.info("    - %s", f)
    logger.info("  推送全部成功:    %s", result.push_success)
    logger.info("  设备验证文件:    %d 个", len(result.verified_files))
    logger.info("  模块安装结果:")
    for m in result.module_results:
        status = "✓" if m.install_success else "✗"
        logger.info("    %s %s", status, m.filename)
    logger.info("  最终清理:        %s", result.cleanup_success)

    if result.all_modules_installed:
        logger.info("  状态: ✓ 所有模块安装完成，设备重启中")
    else:
        logger.error("  状态: ✗ 部分模块安装失败，请检查日志")

    logger.info("=" * 60)


# ── CLI 入口 ───────────────────────────────────────────────────────

def main() -> None:
    """Install Modules 的命令行入口.

    用法:
        python -m install_modules [--modules-dir <path>]
    """
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Install Modules — 安装 Magisk 模块",
    )
    parser.add_argument(
        "--modules-dir",
        type=Path,
        default=None,
        help="模块 zip 文件所在目录 (默认: 模块内置路径)",
    )

    args = parser.parse_args()

    module_root = Path(__file__).resolve().parent
    adb_path = module_root.parent / "platform-tools" / "adb.exe"

    if not adb_path.exists():
        logger.error("未找到 ADB: %s", adb_path)
        sys.exit(1)

    if args.modules_dir is not None:
        modules_dir = args.modules_dir
    else:
        modules_dir = module_root / _DEFAULT_MODULES_DIR

    logger.info("ADB:         %s", adb_path)
    logger.info("模块目录:    %s", modules_dir)

    executor = AdbExecutor(adb_path=adb_path)

    try:
        result = install_modules(executor, modules_dir)
    except AdbError as e:
        logger.error("ADB 错误: %s", e)
        sys.exit(1)

    sys.exit(0 if result.all_modules_installed else 1)
