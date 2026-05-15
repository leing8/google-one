"""
Install Magisk & Root Phone — 核心业务逻辑。

严格按照 5.0-Install Magisk && Root Phone.pcapng 抓包还原的命令序列实现。
所有命令按原始顺序执行，不做任何跳过或短路优化。

pcapng 命令序列（6 步）：
    1. reboot:recovery                      → 重启进入 TWRP Recovery
    2. shell:twrp --version                 → 验证 TWRP 就绪
    3. sync: SEND /sdcard/Magisk.zip        → 推送 Magisk.zip（adb push）
    4. shell:twrp install /sdcard/Magisk.zip → 安装 Magisk
    5. shell,v2,raw:rm -rf /sdcard/Magisk.zip → 清理临时文件
    6. reboot:                              → 重启回正常系统

参考：
- https://docs.python.org/3/library/subprocess.html#subprocess.run
- https://docs.python.org/3/library/pathlib.html
- https://docs.python.org/3/library/logging.html
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from michanger.common import AdbError, AdbExecutor
from .models import MagiskInstallResult, TwrpInfo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量（来自 pcapng 抓包）
# ---------------------------------------------------------------------------

# 设备端 Magisk.zip 存放路径（pcapng 中的 SEND 目标路径）
_REMOTE_MAGISK_PATH: str = "/sdcard/Magisk.zip"

# TWRP 版本检测命令（pcapng Step 2）
_TWRP_VERSION_CMD: str = "twrp --version"

# TWRP 安装命令模板（pcapng Step 4）
_TWRP_INSTALL_CMD: str = "twrp install {remote_path}"

# 清理命令（pcapng Step 5: shell,v2,raw:rm -rf /sdcard/Magisk.zip）
_CLEANUP_CMD: str = "rm -rf {remote_path}"

# TWRP 安装命令超时（秒）— 安装过程涉及 boot 镜像修补
_INSTALL_TIMEOUT: float = 120.0

# 等待 Recovery 模式超时（秒）
_RECOVERY_WAIT_TIMEOUT: float = 120.0

# 等待 TWRP daemon + 存储就绪超时（秒）
_TWRP_READY_TIMEOUT: float = 60.0

# 等待正常启动超时（秒）
_BOOT_WAIT_TIMEOUT: float = 180.0

# 推送后文件验证重试次数
_PUSH_VERIFY_RETRIES: int = 3


# ---------------------------------------------------------------------------
# Step 2: TWRP 版本检测
# ---------------------------------------------------------------------------

# TWRP 版本输出格式：TWRP openrecoveryscript command line tool, TWRP version 3.6.2_11-0
_TWRP_VERSION_PATTERN: re.Pattern[str] = re.compile(
    r"TWRP\s+version\s+([\d._-]+)"
)


def _parse_twrp_version(output: str) -> TwrpInfo:
    """解析 twrp --version 的输出。

    pcapng 中的输出：
        TWRP openrecoveryscript command line tool, TWRP version 3.6.2_11-0

    Args:
        output: twrp --version 的标准输出

    Returns:
        TwrpInfo 包含版本号和完整输出

    Raises:
        AdbError: 无法解析 TWRP 版本
    """
    match = _TWRP_VERSION_PATTERN.search(output)
    if match is None:
        raise AdbError(
            f"无法解析 TWRP 版本，输出：{output!r}"
        )

    version = match.group(1)
    logger.info("TWRP 版本: %s", version)
    return TwrpInfo(version=version, full_output=output.strip())


# ---------------------------------------------------------------------------
# Step 4: Magisk 安装输出解析
# ---------------------------------------------------------------------------

# 从安装日志中提取的关键信息模式
_MAGISK_VERSION_PATTERN: re.Pattern[str] = re.compile(
    r"Magisk\s+([\d.]+)\s+Installer"
)
_BOOT_SLOT_PATTERN: re.Pattern[str] = re.compile(
    r"Current boot slot:\s*(\S+)"
)
_TARGET_IMAGE_PATTERN: re.Pattern[str] = re.compile(
    r"Target image:\s*(\S+)"
)
_PLATFORM_PATTERN: re.Pattern[str] = re.compile(
    r"Device platform:\s*(\S+)"
)


def _parse_install_output(
    output: str,
    twrp_version: str,
) -> MagiskInstallResult:
    """解析 twrp install 命令的输出。

    从 pcapng 中观察到的完整输出提取关键信息：
    - Magisk 版本
    - Boot slot
    - Target image
    - Device platform
    - 安装是否成功

    Args:
        output: twrp install 命令的完整输出
        twrp_version: 已检测到的 TWRP 版本

    Returns:
        MagiskInstallResult 安装结果
    """
    lines = tuple(
        line.strip()
        for line in output.splitlines()
        if line.strip()
    )

    # 提取 Magisk 版本（默认 "unknown"）
    magisk_match = _MAGISK_VERSION_PATTERN.search(output)
    magisk_version = magisk_match.group(1) if magisk_match else "unknown"

    # 提取 boot slot（默认 "unknown"）
    slot_match = _BOOT_SLOT_PATTERN.search(output)
    boot_slot = slot_match.group(1) if slot_match else "unknown"

    # 提取 target image（默认 "unknown"）
    image_match = _TARGET_IMAGE_PATTERN.search(output)
    target_image = image_match.group(1) if image_match else "unknown"

    # 提取 device platform（默认 "unknown"）
    platform_match = _PLATFORM_PATTERN.search(output)
    platform = platform_match.group(1) if platform_match else "unknown"

    # 判断安装成功：
    # 1. 必须包含 "- Done" 标志
    # 2. 不能包含 "Error installing" 或 "Unable to locate"
    has_done = any(
        line.startswith("- Done")
        for line in lines
    )
    has_error = any(
        "Error installing" in line or "Unable to locate" in line
        for line in lines
    )
    success = has_done and not has_error

    result = MagiskInstallResult(
        twrp_version=twrp_version,
        magisk_version=magisk_version,
        boot_slot=boot_slot,
        target_image=target_image,
        platform=platform,
        install_log=lines,
        success=success,
    )

    logger.info(
        "安装结果: Magisk %s, slot=%s, target=%s, platform=%s, success=%s",
        magisk_version, boot_slot, target_image, platform, success,
    )

    return result


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def install_magisk(
    adb_path: Path,
    serial: str,
    magisk_zip: Path,
    *,
    dry_run: bool = False,
) -> MagiskInstallResult:
    """执行 Magisk 安装与设备 Root。

    严格按照 5.0-Install Magisk && Root Phone.pcapng 抓包还原的
    完整命令序列，所有命令按原始顺序依次执行。

    步骤：
        1. adb reboot recovery              → 进入 TWRP Recovery
        2. adb shell twrp --version          → 验证 TWRP 就绪
        3. adb push Magisk.zip /sdcard/      → 推送安装包
        4. adb shell twrp install /sdcard/Magisk.zip → 执行安装
        5. adb shell rm -rf /sdcard/Magisk.zip → 清理临时文件
        6. adb reboot                        → 重启回正常系统

    Args:
        adb_path: adb.exe 的路径
        serial: 设备序列号
        magisk_zip: 本地 Magisk.zip 的路径
        dry_run: 如果为 True，仅打印命令序列，不实际执行

    Returns:
        MagiskInstallResult 安装结果

    Raises:
        AdbError: 任一步骤失败
        FileNotFoundError: Magisk.zip 文件不存在
    """
    # 验证 Magisk.zip 存在
    resolved_zip = magisk_zip.resolve()
    if not resolved_zip.is_file():
        raise FileNotFoundError(
            f"Magisk.zip 不存在：{resolved_zip}"
        )

    adb = AdbExecutor(adb_path=adb_path, serial=serial)

    if dry_run:
        return _dry_run(serial, resolved_zip)

    logger.info("=" * 60)
    logger.info("Install Magisk — 设备 [%s]", serial)
    logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Step 1: 重启进入 TWRP Recovery（pcapng: OPEN reboot:recovery）
    # ------------------------------------------------------------------
    logger.info("[Step 1/6] 重启进入 TWRP Recovery")
    reboot_result = adb.reboot("recovery")
    if not reboot_result.success:
        logger.warning(
            "reboot recovery 返回非零: %s", reboot_result.stderr
        )

    # 等待设备进入 Recovery 模式（USB 连接层面）
    logger.info("[Step 1/6] 等待设备进入 Recovery 模式...")
    adb.wait_for_device("recovery", timeout=_RECOVERY_WAIT_TIMEOUT)

    # 等待 TWRP daemon 完全就绪 + /sdcard 存储挂载完成
    # 注意：adb wait-for-recovery 仅等待 USB 连接，
    # TWRP daemon 和存储挂载需要额外时间
    logger.info("[Step 1/6] 等待 TWRP daemon 和存储就绪...")
    twrp_ready = adb.wait_for_twrp_ready(
        timeout=_TWRP_READY_TIMEOUT,
        poll_interval=3.0,
    )
    if not twrp_ready:
        raise AdbError(
            "TWRP daemon 或存储未就绪，无法继续。"
            "请确认设备已安装 TWRP Recovery 并正确启动。"
        )

    # ------------------------------------------------------------------
    # Step 2: 检查 TWRP 版本（pcapng: OPEN shell:twrp --version）
    # ------------------------------------------------------------------
    logger.info("[Step 2/6] 检查 TWRP 版本")
    version_result = adb.shell(_TWRP_VERSION_CMD)

    if not version_result.success:
        raise AdbError(
            f"twrp --version 执行失败：{version_result.output}"
        )

    twrp_info = _parse_twrp_version(version_result.output)

    # ------------------------------------------------------------------
    # Step 3: 推送 Magisk.zip（pcapng: OPEN sync: → SEND DATA...）
    # ------------------------------------------------------------------
    logger.info("[Step 3/6] 推送 Magisk.zip 到设备")
    push_result = adb.push(resolved_zip, _REMOTE_MAGISK_PATH)

    if not push_result.success:
        raise AdbError(
            f"adb push 失败：{push_result.output}"
        )

    # 验证文件已成功写入设备
    # 因为 TWRP 存储挂载可能有延迟，push 命令可能「成功」但文件未实际写入
    logger.info("[Step 3/6] 验证文件已推送到设备...")
    for attempt in range(1, _PUSH_VERIFY_RETRIES + 1):
        if adb.file_exists(_REMOTE_MAGISK_PATH):
            logger.info("[Step 3/6] 推送验证通过")
            break
        if attempt < _PUSH_VERIFY_RETRIES:
            logger.warning(
                "文件验证失败（第 %d 次），2s 后重试...",
                attempt,
            )
            time.sleep(2.0)
    else:
        raise AdbError(
            f"文件推送验证失败：设备上未找到 {_REMOTE_MAGISK_PATH}。"
            f"可能 TWRP 存储未正确挂载。"
        )

    # ------------------------------------------------------------------
    # Step 4: 安装 Magisk（pcapng: OPEN shell:twrp install ...）
    # ------------------------------------------------------------------
    install_cmd = _TWRP_INSTALL_CMD.format(
        remote_path=_REMOTE_MAGISK_PATH
    )
    logger.info("[Step 4/6] 安装 Magisk: %s", install_cmd)
    install_result = adb.shell(install_cmd, timeout=_INSTALL_TIMEOUT)

    if not install_result.success:
        raise AdbError(
            f"twrp install 执行失败：{install_result.output}"
        )

    # 解析安装输出
    magisk_result = _parse_install_output(
        install_result.output,
        twrp_info.version,
    )

    if not magisk_result.success:
        logger.error("Magisk 安装未检测到 '- Done' 标志")
        # 不直接抛异常，仍然返回结果让调用方判断

    # 打印安装日志
    for line in magisk_result.install_log:
        logger.info("  %s", line)

    # ------------------------------------------------------------------
    # Step 5: 清理临时文件（pcapng: OPEN shell,v2,raw:rm -rf ...）
    # ------------------------------------------------------------------
    cleanup_cmd = _CLEANUP_CMD.format(remote_path=_REMOTE_MAGISK_PATH)
    logger.info("[Step 5/6] 清理: %s", cleanup_cmd)
    cleanup_result = adb.shell(cleanup_cmd)

    if not cleanup_result.success:
        logger.warning(
            "清理命令执行失败（非致命）：%s", cleanup_result.output
        )

    # ------------------------------------------------------------------
    # Step 6: 重启回正常系统（pcapng: OPEN reboot:）
    # ------------------------------------------------------------------
    logger.info("[Step 6/6] 重启设备")
    adb.reboot()

    # 等待设备启动完成
    logger.info("[Step 6/6] 等待设备启动...")
    adb.wait_for_device("device", timeout=_BOOT_WAIT_TIMEOUT)

    boot_ready = adb.wait_for_shell_ready(
        probe_command="echo ready",
        timeout=60.0,
        poll_interval=3.0,
    )
    if not boot_ready:
        logger.warning("设备启动后 shell 未就绪，但 Magisk 安装可能已成功")

    logger.info("=" * 60)
    logger.info("Install Magisk 完成 — 设备 [%s]", serial)
    logger.info("=" * 60)

    return magisk_result


def _dry_run(serial: str, magisk_zip: Path) -> MagiskInstallResult:
    """Dry-run 模式：仅打印命令序列。

    Args:
        serial: 设备序列号
        magisk_zip: Magisk.zip 本地路径

    Returns:
        包含空数据的 MagiskInstallResult
    """
    print()
    print("=" * 60)
    print(f"Install Magisk — Dry Run — 设备 [{serial}]")
    print("=" * 60)
    print()
    print(f"  [Step 1/6] adb -s {serial} reboot recovery")
    print(f"             adb -s {serial} wait-for-recovery")
    print(f"  [Step 2/6] adb -s {serial} shell twrp --version")
    print(f"  [Step 3/6] adb -s {serial} push {magisk_zip} "
          f"{_REMOTE_MAGISK_PATH}")
    print(f"  [Step 4/6] adb -s {serial} shell "
          f"twrp install {_REMOTE_MAGISK_PATH}")
    print(f"  [Step 5/6] adb -s {serial} shell "
          f"rm -rf {_REMOTE_MAGISK_PATH}")
    print(f"  [Step 6/6] adb -s {serial} reboot")
    print(f"             adb -s {serial} wait-for-device")
    print()

    return MagiskInstallResult(
        twrp_version="(dry-run)",
        magisk_version="(dry-run)",
        boot_slot="(dry-run)",
        target_image="(dry-run)",
        platform="(dry-run)",
        install_log=(),
        success=False,
    )
