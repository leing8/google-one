"""
Install Modules — 核心业务逻辑。

严格按照 6.0-Install Modules.pcapng 抓包还原的命令序列实现。
所有命令按原始顺序执行，不做任何跳过或短路优化。

pcapng 命令序列（10 步）：
    1.  shell:su -c "id"                           → 验证 root 权限
    2.  shell:su -c "magisk --remove-modules -n"   → 移除已安装模块
    3.  shell:su -c "rm -rf /data/adb/modules/*"   → 清空模块目录
    4.  shell,v2,raw:rm -rf /sdcard/modules        → 删除临时目录
    5.  sync: STA2 /sdcard/modules                 → （push 自动处理）
    6.  sync: SND2 + DATA × 4 files                → 推送模块文件
    7.  shell:ls -1 /sdcard/modules/*.zip           → 验证推送成功
    8.  shell:su -c "magisk --install-module ..." × 4 → 逐个安装模块
    9.  shell,v2,raw:rm -rf /sdcard/modules        → 清理临时文件
    10. reboot:                                    → 重启设备

参考：
- https://docs.python.org/3/library/subprocess.html#subprocess.run
- https://docs.python.org/3/library/pathlib.html
- https://docs.python.org/3/library/logging.html
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from michanger.common import AdbError, AdbExecutor
from .models import InstallModulesResult, ModuleInfo, ModuleInstallResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量（来自 pcapng 抓包）
# ---------------------------------------------------------------------------

# 设备端模块临时目录（pcapng 中的推送目标）
_REMOTE_MODULES_DIR: str = "/sdcard/modules"

# 模块安装命令模板（pcapng Step 8）
_INSTALL_MODULE_CMD: str = "magisk --install-module {remote_path}"

# 模块安装超时（秒）— 安装过程涉及解压和验证
_INSTALL_TIMEOUT: float = 120.0

# 推送超时（秒）— 多个大文件传输
_PUSH_TIMEOUT: float = 600.0

# 等待正常启动超时（秒）
_BOOT_WAIT_TIMEOUT: float = 180.0

# 推送后文件验证重试次数
_PUSH_VERIFY_RETRIES: int = 3


# ---------------------------------------------------------------------------
# Step 1: Root 权限验证
# ---------------------------------------------------------------------------

# id 命令输出格式：uid=0(root) gid=0(root) groups=0(root) context=u:r:magisk:s0
_UID_PATTERN: re.Pattern[str] = re.compile(r"uid=(\d+)")


def _verify_root(output: str) -> bool:
    """验证 su -c id 的输出确认 root 权限。

    pcapng 中的期望输出：
        uid=0(root) gid=0(root) groups=0(root) context=u:r:magisk:s0

    Args:
        output: su -c "id" 的标准输出

    Returns:
        True 如果 uid=0（root）
    """
    match = _UID_PATTERN.search(output)
    if match is None:
        return False
    return match.group(1) == "0"


# ---------------------------------------------------------------------------
# Step 7: 推送验证
# ---------------------------------------------------------------------------

def _verify_pushed_files(
    ls_output: str,
    expected_modules: tuple[ModuleInfo, ...],
) -> bool:
    """验证 ls -1 输出与期望的模块文件列表一致。

    pcapng 中的期望输出：
        /sdcard/modules/1.Zygisk-Next-1.3.3.zip
        /sdcard/modules/2.Shamiko-v1.2.5.zip
        /sdcard/modules/3.Tricky-Store-v1.4.1.zip
        /sdcard/modules/4.PlayIntegrity-v37.0.zip

    Args:
        ls_output: shell:ls -1 /sdcard/modules/*.zip 的输出
        expected_modules: 期望的模块信息列表

    Returns:
        True 如果所有文件都存在
    """
    found_files = frozenset(
        line.strip()
        for line in ls_output.splitlines()
        if line.strip()
    )
    expected_paths = frozenset(m.remote_path for m in expected_modules)

    missing = expected_paths - found_files
    if missing:
        logger.error("设备上缺少模块文件: %s", missing)
        return False

    return True


# ---------------------------------------------------------------------------
# Step 8: 模块安装输出解析
# ---------------------------------------------------------------------------

# 从安装日志中提取的关键信息模式
_BOOT_SLOT_PATTERN: re.Pattern[str] = re.compile(
    r"Current boot slot:\s*(\S+)"
)
_PLATFORM_PATTERN: re.Pattern[str] = re.compile(
    r"Device platform:\s*(\S+)"
)


def _parse_module_install_output(
    module_name: str,
    output: str,
) -> ModuleInstallResult:
    """解析 magisk --install-module 命令的输出。

    从 pcapng 中观察到的输出提取关键信息：
    - Boot slot
    - Device platform
    - 安装是否成功（"- Done" 且无 "!" 错误行）

    Args:
        module_name: 模块文件名
        output: magisk --install-module 命令的完整输出

    Returns:
        ModuleInstallResult 安装结果
    """
    lines = tuple(
        line.strip()
        for line in output.splitlines()
        if line.strip()
    )

    # 提取 boot slot（默认 "unknown"）
    slot_match = _BOOT_SLOT_PATTERN.search(output)
    boot_slot = slot_match.group(1) if slot_match else "unknown"

    # 提取 device platform（默认 "unknown"）
    platform_match = _PLATFORM_PATTERN.search(output)
    platform = platform_match.group(1) if platform_match else "unknown"

    # 判断安装成功：
    # 1. 必须包含 "- Done" 标志
    # 2. 不能包含 "!" 开头的错误行或 "Error" 关键字
    has_done = any(line.startswith("- Done") for line in lines)
    has_error = any(
        line.startswith("!") or "Error" in line
        for line in lines
    )
    success = has_done and not has_error

    result = ModuleInstallResult(
        module_name=module_name,
        boot_slot=boot_slot,
        platform=platform,
        install_log=lines,
        success=success,
    )

    logger.info(
        "模块安装结果: %s, slot=%s, platform=%s, success=%s",
        module_name, boot_slot, platform, success,
    )

    return result


# ---------------------------------------------------------------------------
# 模块文件发现
# ---------------------------------------------------------------------------

def _discover_modules(modules_dir: Path) -> tuple[ModuleInfo, ...]:
    """发现并排序模块目录中的 .zip 文件。

    按文件名自然排序（pcapng 中按编号前缀排序）。

    Args:
        modules_dir: 模块文件目录

    Returns:
        按名称排序的模块信息元组

    Raises:
        AdbError: 目录不存在或为空
    """
    resolved_dir = modules_dir.resolve()
    if not resolved_dir.is_dir():
        raise AdbError(f"模块目录不存在：{resolved_dir}")

    zip_files = sorted(
        f for f in resolved_dir.iterdir()
        if f.is_file() and f.suffix.lower() == ".zip"
    )

    if not zip_files:
        raise AdbError(f"模块目录中未找到 .zip 文件：{resolved_dir}")

    modules = tuple(
        ModuleInfo(
            name=f.name,
            local_path=str(f),
            remote_path=f"{_REMOTE_MODULES_DIR}/{f.name}",
            size_bytes=f.stat().st_size,
        )
        for f in zip_files
    )

    logger.info(
        "发现 %d 个模块文件: %s",
        len(modules),
        ", ".join(m.name for m in modules),
    )

    return modules


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def install_modules(
    adb_path: Path,
    serial: str,
    modules_dir: Path,
    *,
    dry_run: bool = False,
) -> InstallModulesResult:
    """执行 Magisk 模块批量安装。

    严格按照 6.0-Install Modules.pcapng 抓包还原的
    完整命令序列，所有命令按原始顺序依次执行。

    步骤：
        1.  adb shell su -c "id"                            → 验证 root
        2.  adb shell su -c "magisk --remove-modules -n"    → 移除旧模块
        3.  adb shell su -c "rm -rf /data/adb/modules/*"    → 清空模块目录
        4.  adb shell rm -rf /sdcard/modules                → 清理临时目录
        5-6. adb push modules/ /sdcard/modules/             → 推送模块文件
        7.  adb shell ls -1 /sdcard/modules/*.zip           → 验证推送
        8.  adb shell su -c "magisk --install-module ..." × N → 安装模块
        9.  adb shell rm -rf /sdcard/modules                → 清理
        10. adb reboot                                      → 重启

    Args:
        adb_path: adb.exe 的路径
        serial: 设备序列号
        modules_dir: 本地模块文件目录
        dry_run: 如果为 True，仅打印命令序列，不实际执行

    Returns:
        InstallModulesResult 安装结果

    Raises:
        AdbError: 任一关键步骤失败
    """
    # 发现模块文件
    modules = _discover_modules(modules_dir)

    if dry_run:
        return _dry_run(serial, modules)

    adb = AdbExecutor(adb_path=adb_path, serial=serial)

    logger.info("=" * 60)
    logger.info("Install Modules — 设备 [%s]", serial)
    logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Step 1: 验证 root 权限（pcapng Frame 7: shell:su -c "id"）
    # ------------------------------------------------------------------
    logger.info("[Step 1/10] 验证 root 权限")
    id_result = adb.shell_su("id")

    root_verified = _verify_root(id_result.output)
    if not root_verified:
        raise AdbError(
            f"root 权限验证失败，输出：{id_result.output!r}\n"
            "请确保设备已安装 Magisk 并已授权 root。"
        )
    logger.info("[Step 1/10] root 权限验证通过: %s", id_result.output)

    # ------------------------------------------------------------------
    # Step 2: 移除已安装模块（pcapng Frame 22）
    # ------------------------------------------------------------------
    logger.info("[Step 2/10] 移除已安装模块: magisk --remove-modules -n")
    remove_result = adb.shell_su(
        "magisk --remove-modules -n",
        timeout=60.0,
    )
    modules_removed = remove_result.success
    if not modules_removed:
        logger.warning(
            "magisk --remove-modules 返回非零（可能无已安装模块）: %s",
            remove_result.output,
        )
    logger.info("[Step 2/10] 模块移除完成")

    # ------------------------------------------------------------------
    # Step 3: 清空模块目录（pcapng Frame 33）
    # ------------------------------------------------------------------
    logger.info("[Step 3/10] 清空模块目录: rm -rf /data/adb/modules/*")
    adb.shell_su("rm -rf /data/adb/modules/*")
    logger.info("[Step 3/10] 模块目录已清空")

    # ------------------------------------------------------------------
    # Step 4: 清理 sdcard 临时目录（pcapng Frame 43）
    # ------------------------------------------------------------------
    logger.info("[Step 4/10] 清理 sdcard 临时目录: rm -rf /sdcard/modules")
    adb.shell("rm -rf /sdcard/modules")
    logger.info("[Step 4/10] sdcard 临时目录已清理")

    # ------------------------------------------------------------------
    # Step 5-6: 推送模块文件（pcapng Frame 67-463）
    # ------------------------------------------------------------------
    logger.info(
        "[Step 5-6/10] 推送 %d 个模块文件到设备",
        len(modules),
    )
    push_result = adb.push_directory(
        modules_dir,
        _REMOTE_MODULES_DIR,
        timeout=_PUSH_TIMEOUT,
    )
    modules_pushed = push_result.success
    if not modules_pushed:
        raise AdbError(
            f"模块文件推送失败：{push_result.output}"
        )
    logger.info("[Step 5-6/10] 模块文件推送完成")

    # ------------------------------------------------------------------
    # Step 7: 验证推送成功（pcapng Frame 473）
    # ------------------------------------------------------------------
    logger.info("[Step 7/10] 验证推送成功: ls -1 /sdcard/modules/*.zip")
    ls_result = adb.shell(
        "ls -1 /sdcard/modules/*.zip",
    )

    if not ls_result.success:
        raise AdbError(
            f"模块文件验证失败：{ls_result.output}"
        )

    if not _verify_pushed_files(ls_result.output, modules):
        raise AdbError(
            "设备上的模块文件与期望不匹配。\n"
            f"期望: {[m.name for m in modules]}\n"
            f"实际: {ls_result.output}"
        )

    logger.info(
        "[Step 7/10] 文件验证通过:\n%s", ls_result.output
    )

    # ------------------------------------------------------------------
    # Step 8: 逐个安装模块（pcapng Frame 489-1129）
    # ------------------------------------------------------------------
    install_results: list[ModuleInstallResult] = []

    for idx, module in enumerate(modules, start=1):
        install_cmd = _INSTALL_MODULE_CMD.format(
            remote_path=module.remote_path,
        )
        logger.info(
            "[Step 8/10] 安装模块 (%d/%d): %s",
            idx, len(modules), module.name,
        )
        logger.info("[Step 8/10] 执行: su -c \"%s\"", install_cmd)

        result = adb.shell_su(install_cmd, timeout=_INSTALL_TIMEOUT)

        module_result = _parse_module_install_output(
            module.name,
            result.output,
        )
        install_results.append(module_result)

        # 打印安装日志
        for line in module_result.install_log:
            logger.info("  %s", line)

        if not module_result.success:
            logger.error(
                "[Step 8/10] 模块 %s 安装失败！", module.name
            )
        else:
            logger.info(
                "[Step 8/10] 模块 %s 安装成功", module.name
            )

    # ------------------------------------------------------------------
    # Step 9: 清理临时文件（pcapng Frame 1141）
    # ------------------------------------------------------------------
    logger.info("[Step 9/10] 清理临时文件: rm -rf /sdcard/modules")
    cleanup_result = adb.shell("rm -rf /sdcard/modules")
    cleanup_done = cleanup_result.success
    if not cleanup_done:
        logger.warning(
            "清理命令执行失败（非致命）：%s", cleanup_result.output
        )
    logger.info("[Step 9/10] 临时文件已清理")

    # ------------------------------------------------------------------
    # Step 10: 重启设备（pcapng Frame 1165）
    # ------------------------------------------------------------------
    logger.info("[Step 10/10] 重启设备")
    adb.reboot()

    # 等待设备启动完成
    logger.info("[Step 10/10] 等待设备启动...")
    adb.wait_for_device("device", timeout=_BOOT_WAIT_TIMEOUT)

    boot_ready = adb.wait_for_shell_ready(
        probe_command="echo ready",
        timeout=60.0,
        poll_interval=3.0,
    )
    if not boot_ready:
        logger.warning(
            "设备启动后 shell 未就绪，但模块安装可能已成功"
        )
    reboot_initiated = True

    # 汇总结果
    all_success = all(r.success for r in install_results)

    final_result = InstallModulesResult(
        root_verified=root_verified,
        modules_removed=modules_removed,
        modules_pushed=modules_pushed,
        pushed_modules=modules,
        install_results=tuple(install_results),
        cleanup_done=cleanup_done,
        reboot_initiated=reboot_initiated,
        success=all_success,
    )

    logger.info("=" * 60)
    logger.info(
        "Install Modules 完成 — 设备 [%s] — %d/%d 成功",
        serial, final_result.success_count, final_result.total_count,
    )
    logger.info("=" * 60)

    return final_result


def _dry_run(
    serial: str,
    modules: tuple[ModuleInfo, ...],
) -> InstallModulesResult:
    """Dry-run 模式：仅打印命令序列。

    Args:
        serial: 设备序列号
        modules: 模块信息列表

    Returns:
        包含空数据的 InstallModulesResult
    """
    print()
    print("=" * 60)
    print(f"Install Modules — Dry Run — 设备 [{serial}]")
    print("=" * 60)
    print()
    print(f"  [Step  1/10] adb -s {serial} shell su -c \"id\"")
    print(f"  [Step  2/10] adb -s {serial} shell "
          f"su -c \"magisk --remove-modules -n\"")
    print(f"  [Step  3/10] adb -s {serial} shell "
          f"su -c \"rm -rf /data/adb/modules/*\"")
    print(f"  [Step  4/10] adb -s {serial} shell "
          f"rm -rf /sdcard/modules")
    print(f"  [Step 5-6/10] adb -s {serial} push "
          f"modules/ /sdcard/modules/")

    for m in modules:
        print(f"               → {m.name} ({m.size_mb:.1f} MB)")

    print(f"  [Step  7/10] adb -s {serial} shell "
          f"ls -1 /sdcard/modules/*.zip")

    for idx, m in enumerate(modules, start=1):
        print(f"  [Step  8/10] adb -s {serial} shell "
              f"su -c \"magisk --install-module "
              f"{m.remote_path}\" ({idx}/{len(modules)})")

    print(f"  [Step  9/10] adb -s {serial} shell "
          f"rm -rf /sdcard/modules")
    print(f"  [Step 10/10] adb -s {serial} reboot")
    print()

    return InstallModulesResult(
        root_verified=False,
        modules_removed=False,
        modules_pushed=False,
        pushed_modules=modules,
        install_results=(),
        cleanup_done=False,
        reboot_initiated=False,
        success=False,
    )
