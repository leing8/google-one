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
    7. shell:su -c "magisk --install-module /sdcard/modules/1.Zygisk-Next-1.3.3.zip"
    8. shell:su -c "magisk --install-module /sdcard/modules/2.Shamiko-v1.2.5.zip"
    9. shell:su -c "magisk --install-module /sdcard/modules/3.Tricky-Store-v1.4.1.zip"
    10. shell:su -c "magisk --install-module /sdcard/modules/4.PlayIntegrity-v37.0.zip"
    11. shell,v2:rm -rf /sdcard/modules            → 清理设备临时目录
    12. reboot:                                    → 重启到系统

抓包上下文：
    - 设备: Pixel 4 XL (coral), Magisk 30.1, boot slot _b
    - 模块:
        1. Zygisk-Next 1.3.3
        2. Shamiko v1.2.5
        3. Tricky Store v1.4.1
        4. PlayIntegrity v37.0

Python 官方最佳实践：
    - subprocess.run() 是推荐方法（Python 3.14 文档）
    - 参数列表（不使用 shell=True）防止命令注入
    - pathlib.Path 用于文件路径操作（glob、resolve、exists）
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
from models import ModuleInstallDetail, ModulesInstallResult

logger = logging.getLogger(__name__)

# ── 常量 ───────────────────────────────────────────────────────────

# 设备上模块临时目录（严格按照抓包日志）
_REMOTE_MODULES_DIR: str = "/sdcard/modules"

# 默认本地模块目录（相对于项目根目录）
_DEFAULT_MODULES_DIR: str = "WiresharkLog/6.0-Install Modules/modules"

# 超时设置（秒）
_SHELL_TIMEOUT: int = 30
_PUSH_TIMEOUT: int = 120
_INSTALL_TIMEOUT: int = 300
_REBOOT_TIMEOUT: int = 30

# magisk --install-module 输出中的成功标志
_INSTALL_DONE_MARKER: str = "- Done"

# root 验证：id 命令输出应包含 uid=0(root)
_ROOT_UID_MARKER: str = "uid=0(root)"


# ── Step 1: 验证 Root 权限 ─────────────────────────────────────────

def _verify_root(executor: AdbExecutor) -> tuple[bool, str]:
    """步骤 1: su -c "id"

    对应抓包日志:
        [Frame 7] OUT OPEN arg0=2358 arg1=0 len=17 | shell:su -c "id"
        [Frame 13] IN  WRTE ... | uid=0(root) gid=0(root) groups=0(root)
                                   context=u:r:magisk:s0

    验证设备已 Root 且具有 uid=0(root) 权限。

    返回:
        (是否验证通过, id 命令完整输出) 的元组。
    """
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
    """步骤 2: su -c "magisk --remove-modules -n"

    对应抓包日志:
        [Frame 25] OUT OPEN arg0=2359 arg1=0 len=41 |
            shell:su -c "magisk --remove-modules -n"
        [Frame 31] IN  CLSE（无输出，直接关闭 — 命令成功静默完成）

    使用 Magisk 的 --remove-modules 命令移除所有已安装的模块。
    -n 参数表示不重启（no reboot）。

    返回:
        命令是否成功执行。
    """
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
    """步骤 3: su -c "rm -rf /data/adb/modules/*"

    对应抓包日志:
        [Frame 35] OUT OPEN arg0=2360 arg1=0 len=41 |
            shell:su -c "rm -rf /data/adb/modules/*"
        [Frame 41] IN  CLSE（无输出，直接关闭 — 成功静默完成）

    清理 Magisk 模块数据目录下的所有内容。

    返回:
        命令是否成功执行。
    """
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
    """步骤 4: rm -rf /sdcard/modules

    对应抓包日志:
        [Frame 45] OUT OPEN arg0=2363 arg1=0 len=36 |
            shell,v2,raw:rm -rf /sdcard/modules
        [Frame 57] IN  WRTE ... | [exit code: 0]

    清理设备上的模块临时目录，为推送新文件做准备。

    返回:
        命令是否成功执行（退出码 0）。
    """
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
    """步骤 5: push → /sdcard/modules/*.zip

    对应抓包日志:
        [Frame 69] OUT OPEN arg0=2366 arg1=0 len=6 | sync:
        [Frame 75-465] 多帧数据传输，推送 4 个 zip 文件

    抓包中步骤 6 的 ls 输出证实了 4 个文件全部推送成功:
        /sdcard/modules/1.Zygisk-Next-1.3.3.zip
        /sdcard/modules/2.Shamiko-v1.2.5.zip
        /sdcard/modules/3.Tricky-Store-v1.4.1.zip
        /sdcard/modules/4.PlayIntegrity-v37.0.zip

    使用 pathlib.Path.glob() 遍历目录中所有 .zip 文件，
    按文件名排序确保安装顺序与抓包日志一致（1., 2., 3., 4.）。

    参数:
        executor: ADB 执行器实例。
        modules_dir: 本地模块文件所在目录。

    返回:
        (成功推送的文件名元组, 是否全部成功) 的元组。
    """
    logger.info("步骤 5: push 模块文件到 %s/", _REMOTE_MODULES_DIR)

    # Python pathlib 推荐：使用 Path.glob() 遍历文件
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
    """步骤 6: ls -1 /sdcard/modules/*.zip

    对应抓包日志:
        [Frame 475] OUT OPEN arg0=2368 arg1=0 len=34 |
            shell:ls -1 /sdcard/modules/*.zip
        [Frame 481] IN  WRTE ... |
            /sdcard/modules/1.Zygisk-Next-1.3.3.zip
            /sdcard/modules/2.Shamiko-v1.2.5.zip
            /sdcard/modules/3.Tricky-Store-v1.4.1.zip
            /sdcard/modules/4.PlayIntegrity-v37.0.zip

    列出设备上已推送的模块文件，验证推送完整性。

    返回:
        设备上的模块文件路径元组。
    """
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
    """步骤 7-10: su -c "magisk --install-module <path>"

    对应抓包日志（以步骤 7 为例）:
        [Frame 492] OUT OPEN arg0=2369 arg1=0 len=78 |
            shell:su -c "magisk --install-module
                /sdcard/modules/1.Zygisk-Next-1.3.3.zip"
        [Frame 499-703] IN  WRTE（多帧安装输出）
        最终输出 "- Done" 表示安装成功

    使用 Magisk 的 --install-module 命令安装单个模块 zip。
    每个模块安装完成后检查输出中是否包含 "- Done" 标志。

    参数:
        executor: ADB 执行器实例。
        remote_path: 设备上的模块 zip 文件路径。
        step_num: 步骤编号（7-10），用于日志。

    返回:
        包含安装结果的 ModuleInstallDetail。
    """
    # 从路径中提取文件名
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

    # 打印安装输出（严格按照抓包日志格式）
    logger.info("  安装输出:")
    for line in output.splitlines():
        logger.info("    | %s", line)

    # 检查安装成功标志
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
    """步骤 11: rm -rf /sdcard/modules

    对应抓包日志:
        [Frame 1115] OUT OPEN arg0=2376 arg1=0 len=36 |
            shell,v2,raw:rm -rf /sdcard/modules
        [Frame 1127] IN  WRTE ... | [exit code: 0]

    安装完成后清理设备上的临时模块目录。

    返回:
        命令是否成功执行（退出码 0）。
    """
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
    """步骤 12: reboot

    对应抓包日志:
        [Frame 1139] OUT OPEN arg0=2378 arg1=0 len=8 | reboot:
        [Frame 1143] IN  OKAY

    重启设备到正常系统，使新安装的模块生效。
    """
    logger.info("步骤 12: reboot")

    executor.reboot(timeout=_REBOOT_TIMEOUT)
    logger.info("  重启命令已发送，设备将启动到系统")


# ── 主流程 ─────────────────────────────────────────────────────────

def install_modules(
    executor: AdbExecutor,
    modules_dir: Path,
) -> ModulesInstallResult:
    """安装 Magisk 模块。

    严格按照 6.0-Install Modules.pcapng 抓包日志中的命令顺序执行 12 步：
        1. su -c "id"                           → 验证 root
        2. su -c "magisk --remove-modules -n"   → 移除已有模块
        3. su -c "rm -rf /data/adb/modules/*"   → 清理数据目录
        4. rm -rf /sdcard/modules               → 清理临时目录
        5. push *.zip → /sdcard/modules/        → 推送模块
        6. ls -1 /sdcard/modules/*.zip          → 验证推送
        7-10. magisk --install-module <zip>     → 安装各模块
        11. rm -rf /sdcard/modules              → 清理临时目录
        12. reboot                              → 重启设备

    参数:
        executor: ADB 命令执行器实例。
        modules_dir: 本地模块 zip 文件所在目录。

    返回:
        包含所有步骤执行结果的 ModulesInstallResult。

    抛出:
        AdbError: 如果 ADB 不可用或设备未连接。
    """
    logger.info("=" * 60)
    logger.info("Install Modules — 开始安装 Magisk 模块")
    logger.info("=" * 60)

    # 验证模块目录存在性（Python pathlib 最佳实践）
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

    # Step 1: 验证 Root 权限
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

    # Step 2: 移除已有模块
    remove_success = _remove_existing_modules(executor)

    # Step 3: 清理模块数据目录
    clean_data_success = _clean_modules_data(executor)

    # Step 4: 清理设备临时目录
    clean_sdcard_success = _clean_sdcard_staging(executor)

    # Step 5: 推送所有模块文件
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

    # Step 6: 验证推送文件
    verified_files = _verify_pushed_files(executor)

    # Step 7-10: 按顺序安装各模块
    module_results: list[ModuleInstallDetail] = []

    for step_num, remote_path in enumerate(verified_files, start=7):
        detail = _install_single_module(executor, remote_path, step_num)
        module_results.append(detail)

    all_installed = all(m.install_success for m in module_results)

    # Step 11: 清理临时目录
    cleanup_success = _cleanup_staging(executor)

    # Step 12: 重启设备
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
    """打印可读的模块安装结果汇总。"""
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
    """Install Modules 的命令行入口。

    用法:
        python install_modules.py [--modules-dir <path>]

    参数:
        --modules-dir: 模块 zip 文件所在目录。
                      默认: WiresharkLog/6.0-Install Modules/modules
    """
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Python 官方推荐：使用 argparse 模块处理命令行参数
    parser = argparse.ArgumentParser(
        description="Install Modules — 安装 Magisk 模块",
    )
    parser.add_argument(
        "--modules-dir",
        type=Path,
        default=None,
        help="模块 zip 文件所在目录 (默认: 项目内置路径)",
    )

    args = parser.parse_args()

    # 使用项目内置的 platform-tools/adb.exe
    project_root = Path(__file__).resolve().parent
    adb_path = project_root / "platform-tools" / "adb.exe"

    if not adb_path.exists():
        logger.error("未找到 ADB: %s", adb_path)
        sys.exit(1)

    # 确定模块目录路径
    if args.modules_dir is not None:
        modules_dir = args.modules_dir
    else:
        modules_dir = project_root / _DEFAULT_MODULES_DIR

    logger.info("ADB:         %s", adb_path)
    logger.info("模块目录:    %s", modules_dir)

    executor = AdbExecutor(adb_path=adb_path)

    try:
        result = install_modules(executor, modules_dir)
    except AdbError as e:
        logger.error("ADB 错误: %s", e)
        sys.exit(1)

    # 根据安装结果设置退出码
    sys.exit(0 if result.all_modules_installed else 1)


if __name__ == "__main__":
    main()
