"""Install Magisk && Root Phone — 安装 Magisk 并 Root 手机.

严格按照 WiresharkLog/5.0-Install Magisk && Root Phone.pcapng 抓包日志中的
ADB 命令序列一比一实现 Magisk 安装功能。

命令序列（6 步）：
    1. reboot:recovery             → 重启到 TWRP Recovery
    2. shell:twrp --version        → 验证 TWRP 版本
    3. push → /sdcard/Magisk.zip   → 推送 Magisk.zip 到设备
    4. shell:twrp install /sdcard/Magisk.zip → TWRP 安装 Magisk
    5. shell,v2:rm -rf /sdcard/Magisk.zip   → 清理临时文件
    6. reboot:                     → 重启到系统

抓包上下文：
    - 设备: Pixel 4 XL (coral), TWRP 3.6.2_11-0
    - Magisk 版本: 30.1
    - Boot slot: _b (A/B 分区)
    - 架构: arm64-v8a

Python 官方最佳实践：
    - subprocess.run() 是推荐方法（Python 3.14 文档）
    - 参数列表（不使用 shell=True）防止命令注入
    - pathlib.Path 用于文件路径操作
    - dataclasses(frozen=True) 实现不可变数据模型
    - logging 模块进行结构化日志

TWRP 官方最佳实践：
    - 使用轮询 adb devices 检测 'recovery' 状态（而非 adb wait-for-device）
    - 通过 twrp --version 验证 TWRP shell 可用性
    - 使用 twrp install 命令安装 zip（OpenRecoveryScript 命令行工具）

参考:
    https://docs.python.org/3/library/subprocess.html#subprocess.run
    https://docs.python.org/3/library/pathlib.html
    https://twrp.me/faq/openrecoveryscript.html
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

from adb_executor import AdbError, AdbExecutor
from models import MagiskInstallResult

logger = logging.getLogger(__name__)

# ── 常量 ───────────────────────────────────────────────────────────

# 设备上 Magisk.zip 的目标路径（严格按照抓包日志）
_REMOTE_MAGISK_PATH: str = "/sdcard/Magisk.zip"

# 默认 Magisk.zip 本地路径（相对于项目根目录）
_DEFAULT_MAGISK_ZIP: str = (
    "WiresharkLog/5.0-Install Magisk && Root Phone/Magisk.zip"
)

# 超时设置（秒）
_REBOOT_TIMEOUT: int = 30
_RECOVERY_WAIT_TIMEOUT: int = 120
_TWRP_COMMAND_TIMEOUT: int = 30
_PUSH_TIMEOUT: int = 120
_INSTALL_TIMEOUT: int = 300
_CLEANUP_TIMEOUT: int = 30

# TWRP install 输出中的成功标志
_INSTALL_DONE_MARKER: str = "Done processing script file"

# 正则：从 twrp --version 输出中提取版本号
_TWRP_VERSION_PATTERN: re.Pattern[str] = re.compile(
    r"TWRP version\s+([\d._-]+)"
)

# 正则：从安装输出中提取 Magisk 版本号
_MAGISK_VERSION_PATTERN: re.Pattern[str] = re.compile(
    r"Magisk\s+([\d.]+)\s+Installer"
)


# ── Step 1: 重启到 Recovery ────────────────────────────────────────

def _reboot_to_recovery(executor: AdbExecutor) -> None:
    """步骤 1: reboot:recovery

    对应抓包日志:
        [Frame 7] OUT OPEN arg0=2175 arg1=0 len=16 | reboot:recovery

    重启设备到 TWRP Recovery 模式，然后等待设备就绪。

    TWRP 官方最佳实践：
    - 使用轮询 adb devices 检测 'recovery' 状态
    - 不使用 adb wait-for-device（TWRP 报告 'recovery' 而非 'device'）

    抛出:
        AdbError: 如果重启失败或等待超时。
    """
    logger.info("步骤 1: reboot:recovery")

    executor.reboot(target="recovery", timeout=_REBOOT_TIMEOUT)
    logger.info("  重启命令已发送，等待设备进入 TWRP...")

    # TWRP 最佳实践：轮询 adb devices 检测 recovery 状态
    executor.wait_for_recovery(timeout=_RECOVERY_WAIT_TIMEOUT)
    logger.info("  设备已进入 TWRP Recovery")


# ── Step 2: 验证 TWRP 版本 ─────────────────────────────────────────

def _verify_twrp(executor: AdbExecutor) -> str:
    """步骤 2: shell:twrp --version

    对应抓包日志:
        [Frame 35] OUT OPEN arg0=2230 arg1=0 len=21 | shell:twrp --version
        [Frame 41] IN  WRTE ... | TWRP openrecoveryscript command line tool,
                                   TWRP version 3.6.2_11-0

    验证 TWRP 可用并提取版本号。

    返回:
        TWRP 版本号字符串（例如 "3.6.2_11-0"）。

    抛出:
        AdbError: 如果 TWRP 未就绪或版本无法解析。
    """
    logger.info("步骤 2: twrp --version")

    result = executor.run_shell("twrp --version", timeout=_TWRP_COMMAND_TIMEOUT)

    if not result.success:
        msg = f"TWRP 命令执行失败: {result.stderr}"
        logger.error("  %s", msg)
        raise AdbError(msg, result=result)

    logger.info("  输出: %s", result.stdout)

    # 从输出中提取版本号
    match = _TWRP_VERSION_PATTERN.search(result.stdout)
    version = match.group(1) if match else result.stdout.strip()

    logger.info("  TWRP 版本: %s", version)
    return version


# ── Step 3: 推送 Magisk.zip ────────────────────────────────────────

def _push_magisk_zip(
    executor: AdbExecutor,
    local_path: Path,
) -> bool:
    """步骤 3: push → /sdcard/Magisk.zip

    对应抓包日志:
        [Frame 53] OUT OPEN arg0=2235 arg1=0 len=6 | sync:
        [Frame 59] OUT WRTE ... | STA2 .../sdcard/Magisk.zip
        ... (多帧数据传输，总计 11.58 MB)
        [Frame 335] IN  WRTE ... | OKAY

    按照 Python 官方推荐：
    - pathlib.Path 进行路径操作和存在性校验
    - subprocess.run() 参数列表形式调用 adb push

    参数:
        executor: ADB 执行器实例。
        local_path: 本地 Magisk.zip 文件路径。

    返回:
        推送是否成功。

    抛出:
        AdbError: 如果文件不存在。
    """
    logger.info("步骤 3: push %s → %s", local_path.name, _REMOTE_MAGISK_PATH)

    file_size_mb = local_path.stat().st_size / (1024 * 1024)
    logger.info("  文件大小: %.2f MB", file_size_mb)

    result = executor.push(
        local_path=local_path,
        remote_path=_REMOTE_MAGISK_PATH,
        timeout=_PUSH_TIMEOUT,
    )

    if result.success:
        logger.info("  推送成功: %s", result.stdout)
        return True

    logger.error("  推送失败: %s", result.stderr)
    return False


# ── Step 4: TWRP 安装 Magisk ──────────────────────────────────────

def _install_magisk_zip(executor: AdbExecutor) -> tuple[str, str, bool]:
    """步骤 4: shell:twrp install /sdcard/Magisk.zip

    对应抓包日志:
        [Frame 351] OUT OPEN ... | shell:twrp install /sdcard/Magisk.zip
        [Frame 357] IN  WRTE ... | Installing zip file '/sdcard/Magisk.zip'
        ... (多帧安装输出)
        [Frame 459] IN  WRTE ... | - Done / Done processing script file

    期望输出关键信息（严格按照抓包日志）：
        - Magisk 30.1 Installer
        - Current boot slot: _b
        - Device is system-as-root
        - Stock boot image detected
        - Flashing new boot image
        - Done processing script file

    TWRP 官方命令格式:
        twrp install FILENAME — 安装 FILENAME zip 文件

    返回:
        (完整输出, Magisk 版本号, 安装是否成功) 的元组。
    """
    logger.info("步骤 4: twrp install %s", _REMOTE_MAGISK_PATH)

    result = executor.run_shell(
        f"twrp install {_REMOTE_MAGISK_PATH}",
        timeout=_INSTALL_TIMEOUT,
    )

    output = result.stdout if result.success else result.stderr
    logger.info("  安装输出:")
    for line in output.splitlines():
        logger.info("    | %s", line)

    # 提取 Magisk 版本号
    magisk_match = _MAGISK_VERSION_PATTERN.search(output)
    magisk_version = magisk_match.group(1) if magisk_match else "unknown"
    logger.info("  Magisk 版本: %s", magisk_version)

    # 检查安装成功标志
    install_success = _INSTALL_DONE_MARKER in output
    if install_success:
        logger.info("  安装成功 ✓")
    else:
        logger.error("  安装输出中未找到成功标志 '%s'", _INSTALL_DONE_MARKER)

    return output, magisk_version, install_success


# ── Step 5: 清理临时文件 ──────────────────────────────────────────

def _cleanup_magisk_zip(executor: AdbExecutor) -> bool:
    """步骤 5: shell,v2:rm -rf /sdcard/Magisk.zip

    对应抓包日志:
        [Frame 473] OUT OPEN ... | shell,v2,raw:rm -rf /sdcard/Magisk.zip
        [Frame 485] IN  WRTE ... | [exit code: 0]

    返回:
        清理是否成功（退出码 0）。
    """
    logger.info("步骤 5: rm -rf %s", _REMOTE_MAGISK_PATH)

    result = executor.run_shell(
        f"rm -rf {_REMOTE_MAGISK_PATH}",
        timeout=_CLEANUP_TIMEOUT,
    )

    if result.success:
        logger.info("  清理成功 ✓")
        return True

    logger.warning("  清理失败: %s", result.stderr)
    return False


# ── Step 6: 重启到系统 ────────────────────────────────────────────

def _reboot_to_system(executor: AdbExecutor) -> None:
    """步骤 6: reboot:

    对应抓包日志:
        [Frame 497] OUT OPEN arg0=2244 arg1=0 len=8 | reboot:

    重启设备到正常系统。
    """
    logger.info("步骤 6: reboot")

    executor.reboot(timeout=_REBOOT_TIMEOUT)
    logger.info("  重启命令已发送，设备将启动到系统")


# ── 主流程 ─────────────────────────────────────────────────────────

def install_magisk(
    executor: AdbExecutor,
    magisk_zip_path: Path,
) -> MagiskInstallResult:
    """安装 Magisk 并 Root 手机。

    严格按照 5.0-Install Magisk && Root Phone.pcapng 抓包日志中的
    命令顺序执行 6 步：
        1. reboot:recovery             → 重启到 TWRP
        2. twrp --version              → 验证 TWRP
        3. push Magisk.zip             → 推送文件
        4. twrp install /sdcard/Magisk.zip → 安装 Magisk
        5. rm -rf /sdcard/Magisk.zip   → 清理
        6. reboot                      → 重启到系统

    参数:
        executor: ADB 命令执行器实例。
        magisk_zip_path: 本地 Magisk.zip 文件的路径。

    返回:
        包含所有步骤执行结果的 MagiskInstallResult。

    抛出:
        AdbError: 如果关键步骤失败（重启、TWRP 不可用等）。
    """
    logger.info("=" * 60)
    logger.info("Install Magisk && Root Phone — 开始安装")
    logger.info("=" * 60)

    # 验证 Magisk.zip 文件存在性（Python pathlib 最佳实践）
    resolved_path = magisk_zip_path.resolve()
    if not resolved_path.exists():
        msg = f"Magisk.zip 文件不存在: {resolved_path}"
        logger.error(msg)
        raise AdbError(msg)

    if not resolved_path.is_file():
        msg = f"路径不是文件: {resolved_path}"
        logger.error(msg)
        raise AdbError(msg)

    logger.info("Magisk.zip: %s", resolved_path)

    # Step 1: 重启到 Recovery
    _reboot_to_recovery(executor)

    # Step 2: 验证 TWRP
    twrp_version = _verify_twrp(executor)

    # Step 3: 推送 Magisk.zip
    push_success = _push_magisk_zip(executor, resolved_path)

    if not push_success:
        logger.error("推送失败，中止安装")
        return MagiskInstallResult(
            twrp_version=twrp_version,
            magisk_zip_path=str(resolved_path),
            magisk_version="unknown",
            push_success=False,
            install_output="",
            install_success=False,
            cleanup_success=False,
        )

    # Step 4: TWRP 安装 Magisk
    install_output, magisk_version, install_success = _install_magisk_zip(
        executor,
    )

    # Step 5: 清理临时文件（无论安装成功与否都执行清理）
    cleanup_success = _cleanup_magisk_zip(executor)

    # Step 6: 重启到系统
    _reboot_to_system(executor)

    result = MagiskInstallResult(
        twrp_version=twrp_version,
        magisk_zip_path=str(resolved_path),
        magisk_version=magisk_version,
        push_success=push_success,
        install_output=install_output,
        install_success=install_success,
        cleanup_success=cleanup_success,
    )

    _print_summary(result)
    return result


# ── 结果输出 ───────────────────────────────────────────────────────

def _print_summary(result: MagiskInstallResult) -> None:
    """打印可读的安装结果汇总。"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("Install Magisk && Root Phone — 安装结果汇总")
    logger.info("=" * 60)
    logger.info("  TWRP 版本:      %s", result.twrp_version)
    logger.info("  Magisk 版本:    %s", result.magisk_version)
    logger.info("  Magisk.zip:     %s", result.magisk_zip_path)
    logger.info("  推送成功:       %s", result.push_success)
    logger.info("  安装成功:       %s", result.install_success)
    logger.info("  清理完成:       %s", result.cleanup_success)

    if result.install_success:
        logger.info("  状态: ✓ Magisk %s 安装完成，设备已 Root", result.magisk_version)
    else:
        logger.error("  状态: ✗ 安装失败，请检查日志")

    logger.info("=" * 60)


# ── CLI 入口 ───────────────────────────────────────────────────────

def main() -> None:
    """Install Magisk && Root Phone 的命令行入口。

    用法:
        python install_magisk.py [--magisk-zip <path>]

    参数:
        --magisk-zip: Magisk.zip 文件路径。
                     默认: WiresharkLog/5.0-Install Magisk && Root Phone/Magisk.zip
    """
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Python 官方推荐：使用 argparse 模块处理命令行参数
    parser = argparse.ArgumentParser(
        description="Install Magisk && Root Phone — 安装 Magisk 并 Root 手机",
    )
    parser.add_argument(
        "--magisk-zip",
        type=Path,
        default=None,
        help="Magisk.zip 文件路径 (默认: 项目内置路径)",
    )

    args = parser.parse_args()

    # 使用项目内置的 platform-tools/adb.exe
    project_root = Path(__file__).resolve().parent
    adb_path = project_root / "platform-tools" / "adb.exe"

    if not adb_path.exists():
        logger.error("未找到 ADB: %s", adb_path)
        sys.exit(1)

    # 确定 Magisk.zip 路径
    if args.magisk_zip is not None:
        magisk_zip_path = args.magisk_zip
    else:
        magisk_zip_path = project_root / _DEFAULT_MAGISK_ZIP

    logger.info("ADB:        %s", adb_path)
    logger.info("Magisk.zip: %s", magisk_zip_path)

    executor = AdbExecutor(adb_path=adb_path)

    try:
        result = install_magisk(executor, magisk_zip_path)
    except AdbError as e:
        logger.error("ADB 错误: %s", e)
        sys.exit(1)

    # 根据安装结果设置退出码
    sys.exit(0 if result.install_success else 1)


if __name__ == "__main__":
    main()

