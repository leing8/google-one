"""
Update Integrity Fix — 核心业务逻辑。

严格按照 8.0-Update Integrity Fix.pcapng 抓包还原的命令序列实现。

pcapng 命令序列（28 步）：
    Phase A: Root 验证 + 清理
        1.  shell:su -c "id"                          → 验证 root
        2.  shell:rm -rf /sdcard/modules/*.zip        → 清理旧模块
    Phase B: 模块1 — Tricky Store OSS
        3.  adb push fix.zip → /sdcard/modules/fix.zip
        4.  shell:ls -1 /sdcard/modules/*.zip         → 验证
        5.  shell:su -c "magisk --install-module ..."  → 安装
        6.  shell:rm -rf /sdcard/modules/             → 清理
        7.  shell:rm -rf /sdcard/modules/*.zip        → 清理
    Phase C: 模块2 — OneChanger PIF Premium
        8.  adb push fix.zip → /sdcard/modules/fix.zip
        9.  shell:ls -1 /sdcard/modules/*.zip         → 验证
        10. shell:su -c "magisk --install-module ..."  → 安装
        11. shell:rm -rf /sdcard/modules/             → 清理
    Phase D: 系统配置写入
        12-14. mount -o rw,remount / /product /vendor
        15-19. config 哈希写入 /system/etc/config
        20-22. mount -o rw,remount / /product /vendor
        23-27. security_patch 写入 tricky_store
    Phase E: 重启
        28. reboot:

参考：
- https://docs.python.org/3/library/subprocess.html#subprocess.run
- https://docs.python.org/3/library/pathlib.html
- https://docs.python.org/3/library/logging.html
"""

from __future__ import annotations

import logging
import re
import urllib.request
from pathlib import Path

from michanger.common import AdbError, AdbExecutor
from .models import (
    ModuleFileInfo,
    ModuleInstallResult,
    SystemConfigResult,
    UpdateIntegrityFixResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量（来自 pcapng 抓包）
# ---------------------------------------------------------------------------

_REMOTE_MODULE_PATH: str = "/sdcard/modules/fix.zip"
_REMOTE_MODULES_DIR: str = "/sdcard/modules"
_INSTALL_CMD: str = "magisk --install-module /sdcard/modules/fix.zip"
_INSTALL_TIMEOUT: float = 120.0
_PUSH_TIMEOUT: float = 600.0
_BOOT_WAIT_TIMEOUT: float = 180.0

# config 哈希值（pcapng Frame 507）
# TODO: 预留自动计算功能，当前使用固定值
_CONFIG_HASH: str = (
    "cd0315e9f43897fcd9eef362b4a43b77d801d99b6f18fe3845028e92b6a1b836"
)

# security_patch 日期（pcapng Frame 629）
_SECURITY_PATCH_VALUE: str = "all=2026-04-05"

# 挂载点列表（pcapng 中每次配置写入前都重新挂载这三个）
_MOUNT_POINTS: tuple[str, ...] = ("/", "/product", "/vendor")

# 下载 URL
_TRICKY_STORE_URL: str = (
    "https://drive.usercontent.google.com/uc?"
    "id=1l2uBTj_7N23vYaxdHeH_RVUw6_1U4_9a&export=download"
)
_PIF_PREMIUM_URL: str = (
    "https://drive.usercontent.google.com/uc?"
    "id=1LJgXrpx3tcNpaYJAJqlKy8oYudqAlQmB&export=download"
)

# id 输出解析
_UID_PATTERN: re.Pattern[str] = re.compile(r"uid=(\d+)")

# 模块安装输出解析
_BOOT_SLOT_PATTERN: re.Pattern[str] = re.compile(
    r"Current boot slot:\s*(\S+)"
)
_PLATFORM_PATTERN: re.Pattern[str] = re.compile(
    r"Device platform:\s*(\S+)"
)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _verify_root(output: str) -> bool:
    """验证 su -c id 的输出确认 root 权限。"""
    match = _UID_PATTERN.search(output)
    if match is None:
        return False
    return match.group(1) == "0"


def _parse_install_output(
    module_name: str,
    output: str,
) -> ModuleInstallResult:
    """解析 magisk --install-module 的输出。"""
    lines = tuple(
        line.strip()
        for line in output.splitlines()
        if line.strip()
    )
    slot_match = _BOOT_SLOT_PATTERN.search(output)
    boot_slot = slot_match.group(1) if slot_match else "unknown"
    platform_match = _PLATFORM_PATTERN.search(output)
    platform = platform_match.group(1) if platform_match else "unknown"
    has_done = any(line.startswith("- Done") for line in lines)
    has_error = any(
        line.startswith("!") or "Error" in line for line in lines
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


def _get_config_hash() -> str:
    """获取 config 哈希值。

    TODO: 预留自动计算功能，当前返回固定值。
    """
    return _CONFIG_HASH


def _download_module_file(
    modules_dir: Path,
    filename: str,
    download_url: str,
) -> Path:
    """每次运行都从 URL 下载最新模块文件。

    遵循 Python urllib.request 官方最佳实践：
    - https://docs.python.org/3/library/urllib.request.html

    Args:
        modules_dir: 模块文件目录
        filename: 文件名
        download_url: 下载地址

    Returns:
        下载后的文件路径

    Raises:
        AdbError: 下载失败
    """
    modules_dir.mkdir(parents=True, exist_ok=True)
    file_path = modules_dir / filename

    # 删除旧文件（如果存在）
    if file_path.is_file():
        logger.info("删除旧模块文件: %s", filename)
        file_path.unlink()

    logger.info("开始下载模块: %s", filename)
    logger.info("下载 URL: %s", download_url)

    try:
        urllib.request.urlretrieve(download_url, str(file_path))
    except Exception as exc:
        raise AdbError(
            f"模块文件下载失败: {filename}\nURL: {download_url}\n错误: {exc}"
        ) from exc

    if not file_path.is_file() or file_path.stat().st_size == 0:
        raise AdbError(f"下载的文件无效: {file_path}")

    logger.info(
        "下载完成: %s (%.1f MB)",
        filename, file_path.stat().st_size / (1024 * 1024),
    )
    return file_path


def _remount_partitions(adb: AdbExecutor) -> None:
    """挂载系统分区为可写（pcapng 中的 mount -o rw,remount）。"""
    for mount_point in _MOUNT_POINTS:
        cmd = f"su -c mount -o rw,remount {mount_point}"
        logger.info("挂载分区: %s", mount_point)
        adb.shell(cmd, timeout=10.0)


# ---------------------------------------------------------------------------
# 单模块 push → verify → install → cleanup 循环
# ---------------------------------------------------------------------------

def _install_single_module(
    adb: AdbExecutor,
    module: ModuleFileInfo,
    step_prefix: str,
) -> ModuleInstallResult:
    """执行单个模块的 push → verify → install → cleanup。

    严格按 pcapng 序列：每个模块都推送为 /sdcard/modules/fix.zip。

    Args:
        adb: ADB 执行器
        module: 模块文件信息
        step_prefix: 日志步骤前缀（如 "Phase B"）

    Returns:
        ModuleInstallResult

    Raises:
        AdbError: 关键步骤失败
    """
    local_path = Path(module.local_path)

    # push
    logger.info("[%s] 推送模块: %s → %s",
                step_prefix, local_path.name, _REMOTE_MODULE_PATH)
    push_result = adb.push(local_path, _REMOTE_MODULE_PATH,
                           timeout=_PUSH_TIMEOUT)
    if not push_result.success:
        raise AdbError(f"模块推送失败: {push_result.output}")

    # verify
    logger.info("[%s] 验证推送: ls -1 /sdcard/modules/*.zip", step_prefix)
    ls_result = adb.shell("ls -1 /sdcard/modules/*.zip")
    if not ls_result.success or "fix.zip" not in ls_result.output:
        raise AdbError(f"模块推送验证失败: {ls_result.output}")
    logger.info("[%s] 验证通过: %s", step_prefix, ls_result.output.strip())

    # install
    logger.info("[%s] 安装模块: %s", step_prefix, module.name)
    install_result = adb.shell_su(_INSTALL_CMD, timeout=_INSTALL_TIMEOUT)
    module_result = _parse_install_output(module.name, install_result.output)

    for line in module_result.install_log:
        logger.info("  %s", line)

    if not module_result.success:
        logger.error("[%s] 模块 %s 安装失败！", step_prefix, module.name)
    else:
        logger.info("[%s] 模块 %s 安装成功", step_prefix, module.name)

    # cleanup: rm -rf /sdcard/modules/
    logger.info("[%s] 清理: rm -rf /sdcard/modules/", step_prefix)
    adb.shell("rm -rf /sdcard/modules/")

    return module_result


# ---------------------------------------------------------------------------
# 系统配置写入
# ---------------------------------------------------------------------------

def _write_system_config(
    adb: AdbExecutor,
    config_hash: str,
    security_patch: str,
) -> SystemConfigResult:
    """写入系统配置（config + security_patch）。

    严格按 pcapng Phase D 序列：
    1. 挂载分区
    2. 写入 /system/etc/config
    3. 再次挂载分区
    4. 写入 /data/adb/tricky_store/security_patch.txt
    """
    # --- D1: 挂载 + config 哈希 ---
    logger.info("[Phase D1] 挂载系统分区为可写")
    _remount_partitions(adb)

    # Step 15: rm -rf /sdcard/config
    logger.info("[Phase D1] 清理: rm -rf /sdcard/config")
    adb.shell_su("rm -rf /sdcard/config")

    # Step 16: rm -rf /system/etc/config
    logger.info("[Phase D1] 清理: rm -rf /system/etc/config")
    adb.shell_su("rm -rf /system/etc/config")

    # Step 17: printf config hash > /sdcard/config
    logger.info("[Phase D1] 写入 config 哈希到 /sdcard/config")
    adb.shell_su(f"printf '{config_hash}' > /sdcard/config")

    # Step 18: mv /sdcard/config /system/etc/config
    logger.info("[Phase D1] 移动 config → /system/etc/config")
    adb.shell_su("mv /sdcard/config /system/etc/config")

    # Step 19: chmod 644
    logger.info("[Phase D1] 设置权限: chmod 644 /system/etc/config")
    adb.shell_su("chmod 644 /system/etc/config")

    config_written = True

    # --- D2: 挂载 + security_patch ---
    logger.info("[Phase D2] 挂载系统分区为可写")
    _remount_partitions(adb)

    # Step 23: rm -rf /sdcard/security_patch.txt
    logger.info("[Phase D2] 清理: rm -rf /sdcard/security_patch.txt")
    adb.shell_su("rm -rf /sdcard/security_patch.txt")

    # Step 24: rm -rf tricky_store/security_patch.txt
    logger.info("[Phase D2] 清理: rm -rf .../security_patch.txt")
    adb.shell_su(
        "rm -rf /data/adb/tricky_store/security_patch.txt"
    )

    # Step 25: printf security_patch > /sdcard/security_patch.txt
    logger.info("[Phase D2] 写入 security_patch: %s", security_patch)
    adb.shell_su(
        f"printf '{security_patch}' > /sdcard/security_patch.txt"
    )

    # Step 26: mv
    logger.info("[Phase D2] 移动 → tricky_store/security_patch.txt")
    adb.shell_su(
        "mv /sdcard/security_patch.txt "
        "/data/adb/tricky_store/security_patch.txt"
    )

    # Step 27: chmod 644
    logger.info("[Phase D2] 设置权限: chmod 644")
    adb.shell_su(
        "chmod 644 /data/adb/tricky_store/security_patch.txt"
    )

    security_patch_written = True

    return SystemConfigResult(
        config_written=config_written,
        config_hash=config_hash,
        security_patch_written=security_patch_written,
        security_patch_value=security_patch,
    )


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def update_integrity_fix(
    adb_path: Path,
    serial: str,
    modules_dir: Path,
    *,
    dry_run: bool = False,
) -> UpdateIntegrityFixResult:
    """执行 Update Integrity Fix 完整流程。

    严格按照 8.0-Update Integrity Fix.pcapng 的 28 步命令序列执行。

    Args:
        adb_path: adb.exe 路径
        serial: 设备序列号
        modules_dir: 本地模块文件目录
        dry_run: 仅打印命令序列，不实际执行

    Returns:
        UpdateIntegrityFixResult

    Raises:
        AdbError: 关键步骤失败
    """
    config_hash = _get_config_hash()

    # 每次运行都重新下载最新模块文件
    ts_path = _download_module_file(
        modules_dir,
        "TrickyStore-OSS.zip",
        _TRICKY_STORE_URL,
    )
    pif_path = _download_module_file(
        modules_dir,
        "OneChanger-PIF-Premium.zip",
        _PIF_PREMIUM_URL,
    )

    tricky_store = ModuleFileInfo(
        name="Tricky Store OSS",
        local_path=str(ts_path),
        remote_path=_REMOTE_MODULE_PATH,
        size_bytes=ts_path.stat().st_size,
        download_url=_TRICKY_STORE_URL,
    )
    pif_premium = ModuleFileInfo(
        name="OneChanger PIF Premium",
        local_path=str(pif_path),
        remote_path=_REMOTE_MODULE_PATH,
        size_bytes=pif_path.stat().st_size,
        download_url=_PIF_PREMIUM_URL,
    )

    if dry_run:
        return _dry_run(serial, tricky_store, pif_premium, config_hash)

    adb = AdbExecutor(adb_path=adb_path, serial=serial)

    logger.info("=" * 60)
    logger.info("Update Integrity Fix — 设备 [%s]", serial)
    logger.info("=" * 60)

    # Phase A: Root 验证 + 清理
    logger.info("[Phase A] Step 1: 验证 root 权限")
    id_result = adb.shell_su("id")
    root_verified = _verify_root(id_result.output)
    if not root_verified:
        raise AdbError(
            f"root 权限验证失败: {id_result.output!r}\n"
            "请确保设备已安装 Magisk 并已授权 root。"
        )
    logger.info("[Phase A] root 验证通过: %s", id_result.output)

    logger.info("[Phase A] Step 2: 清理旧模块文件")
    adb.shell("rm -rf /sdcard/modules/*.zip")

    # Phase B: Tricky Store OSS
    logger.info("[Phase B] 安装 Tricky Store OSS")
    ts_result = _install_single_module(adb, tricky_store, "Phase B")

    # pcapng Step 7: 额外清理 *.zip
    logger.info("[Phase B] 额外清理: rm -rf /sdcard/modules/*.zip")
    adb.shell("rm -rf /sdcard/modules/*.zip")

    # Phase C: OneChanger PIF Premium
    logger.info("[Phase C] 安装 OneChanger PIF Premium")
    pif_result = _install_single_module(adb, pif_premium, "Phase C")

    # Phase D: 系统配置写入
    logger.info("[Phase D] 写入系统配置")
    sys_config = _write_system_config(
        adb, config_hash, _SECURITY_PATCH_VALUE
    )

    # Phase E: 重启
    logger.info("[Phase E] 重启设备")
    adb.reboot()

    logger.info("[Phase E] 等待设备启动...")
    adb.wait_for_device("device", timeout=_BOOT_WAIT_TIMEOUT)
    adb.wait_for_shell_ready(
        probe_command="echo ready", timeout=60.0, poll_interval=3.0
    )
    reboot_initiated = True

    all_success = (
        ts_result.success
        and pif_result.success
        and sys_config.config_written
        and sys_config.security_patch_written
    )

    final = UpdateIntegrityFixResult(
        root_verified=root_verified,
        modules_cleaned=True,
        tricky_store_result=ts_result,
        pif_premium_result=pif_result,
        system_config=sys_config,
        reboot_initiated=reboot_initiated,
        success=all_success,
    )

    logger.info("=" * 60)
    logger.info(
        "Update Integrity Fix 完成 — 设备 [%s] — %s",
        serial, "成功" if all_success else "失败",
    )
    logger.info("=" * 60)

    return final


def _dry_run(
    serial: str,
    tricky_store: ModuleFileInfo,
    pif_premium: ModuleFileInfo,
    config_hash: str,
) -> UpdateIntegrityFixResult:
    """Dry-run 模式：仅打印命令序列。"""
    s = serial
    print()
    print("=" * 60)
    print(f"Update Integrity Fix — Dry Run — 设备 [{s}]")
    print("=" * 60)
    print()

    # Phase A
    print("--- Phase A: Root 验证 + 清理 ---")
    print(f"  [Step  1] adb -s {s} shell su -c \"id\"")
    print(f"  [Step  2] adb -s {s} shell rm -rf /sdcard/modules/*.zip")
    print()

    # Phase B
    print("--- Phase B: Tricky Store OSS ---")
    print(f"  [Step  3] adb -s {s} push "
          f"{tricky_store.local_path} → {_REMOTE_MODULE_PATH}")
    print(f"            ({tricky_store.size_mb:.1f} MB)")
    print(f"  [Step  4] adb -s {s} shell ls -1 /sdcard/modules/*.zip")
    print(f"  [Step  5] adb -s {s} shell su -c \"{_INSTALL_CMD}\"")
    print(f"  [Step  6] adb -s {s} shell rm -rf /sdcard/modules/")
    print(f"  [Step  7] adb -s {s} shell rm -rf /sdcard/modules/*.zip")
    print()

    # Phase C
    print("--- Phase C: OneChanger PIF Premium ---")
    print(f"  [Step  8] adb -s {s} push "
          f"{pif_premium.local_path} → {_REMOTE_MODULE_PATH}")
    print(f"            ({pif_premium.size_mb:.1f} MB)")
    print(f"  [Step  9] adb -s {s} shell ls -1 /sdcard/modules/*.zip")
    print(f"  [Step 10] adb -s {s} shell su -c \"{_INSTALL_CMD}\"")
    print(f"  [Step 11] adb -s {s} shell rm -rf /sdcard/modules/")
    print()

    # Phase D
    print("--- Phase D: 系统配置写入 ---")
    for i, mp in enumerate(_MOUNT_POINTS, start=12):
        print(f"  [Step {i:2d}] adb -s {s} shell "
              f"su -c mount -o rw,remount {mp}")
    print(f"  [Step 15] adb -s {s} shell "
          f"su -c \"rm -rf /sdcard/config\"")
    print(f"  [Step 16] adb -s {s} shell "
          f"su -c \"rm -rf /system/etc/config\"")
    print(f"  [Step 17] adb -s {s} shell "
          f"su -c \"printf '{config_hash[:16]}...' > /sdcard/config\"")
    print(f"  [Step 18] adb -s {s} shell "
          f"su -c \"mv /sdcard/config /system/etc/config\"")
    print(f"  [Step 19] adb -s {s} shell "
          f"su -c \"chmod 644 /system/etc/config\"")
    for i, mp in enumerate(_MOUNT_POINTS, start=20):
        print(f"  [Step {i:2d}] adb -s {s} shell "
              f"su -c mount -o rw,remount {mp}")
    print(f"  [Step 23] adb -s {s} shell "
          f"su -c \"rm -rf /sdcard/security_patch.txt\"")
    print(f"  [Step 24] adb -s {s} shell "
          f"su -c \"rm -rf .../security_patch.txt\"")
    print(f"  [Step 25] adb -s {s} shell "
          f"su -c \"printf '{_SECURITY_PATCH_VALUE}' "
          f"> /sdcard/security_patch.txt\"")
    print(f"  [Step 26] adb -s {s} shell "
          f"su -c \"mv ... tricky_store/security_patch.txt\"")
    print(f"  [Step 27] adb -s {s} shell "
          f"su -c \"chmod 644 .../security_patch.txt\"")
    print()

    # Phase E
    print("--- Phase E: 重启 ---")
    print(f"  [Step 28] adb -s {s} reboot")
    print()

    return UpdateIntegrityFixResult(
        root_verified=False,
        modules_cleaned=False,
        tricky_store_result=None,
        pif_premium_result=None,
        system_config=None,
        reboot_initiated=False,
        success=False,
    )
