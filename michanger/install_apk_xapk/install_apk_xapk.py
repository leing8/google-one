"""
Install Apk-XApk — 核心业务逻辑。

严格按照 12.0-Install Apk-XApk.pcapng 抓包还原的命令序列实现。
安装 apk/ 目录中的所有 .apk 和 .xapk 文件，然后启用 Google Play Store。

pcapng 命令序列（29 步）：

    对每个 XAPK 文件，执行一轮 install-create → install-write × N → install-commit：

    [Step  1]    exec:cmd package 'install-create' -r -d -t --user 0
                 → Success: created install session [103311713]
    [Step  2-21] exec:cmd package 'install-write' -S {size} {session} {name}.apk × 20
                 → Success: streamed N bytes (per APK)
    [Step  22]   exec:cmd package 'install-commit' {session}
                 → Success
    [Step  23]   exec:cmd package 'install-create' -r -d -t --user 0
                 → Success: created install session [1452379699]
    [Step  24-27] exec:cmd package 'install-write' -S {size} {session} {name}.apk × 4
                 → Success: streamed N bytes (per APK)
    [Step  28]   exec:cmd package 'install-commit' {session}
                 → Success
    [Step  29]   shell,v2,raw:pm enable com.android.vending
                 → Package com.android.vending new state: enabled

等效高层 adb 命令：
    - .xapk: adb install-multiple -r -d -t --user 0 <base.apk> <split1.apk> ...
             内部自动执行 install-create → install-write × N → install-commit
    - .apk:  adb install -r -d -t --user 0 <file.apk>
    - 最后:  adb shell pm enable com.android.vending

关键验证（pcapng 一致性）：
    - install-create 参数: -r -d -t --user 0 ← pcapng 完全匹配
    - install-write 文件集: 与 XAPK manifest 中的 APK 集合完全匹配（multiset）
    - install-commit: 每轮 XAPK 安装后执行一次
    - 最终步骤: pm enable com.android.vending

参考：
- https://docs.python.org/3/library/subprocess.html#subprocess.run
- https://docs.python.org/3/library/pathlib.html
- https://docs.python.org/3/library/tempfile.html
- https://docs.python.org/3/library/logging.html
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from michanger.common import AdbExecutor
from .models import (
    InstallApkXapkResult,
    PackageInstallResult,
)
from .xapk_parser import (
    discover_apk_packages,
    extract_xapk,
    parse_xapk,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量（来自 pcapng 抓包）
# ---------------------------------------------------------------------------

# pcapng Step 29: 启用 Google Play Store 的包名
_PLAY_STORE_PACKAGE: str = "com.android.vending"

# 安装超时（秒）— 大 XAPK 传输 + 安装
_INSTALL_TIMEOUT: float = 600.0


# ---------------------------------------------------------------------------
# 单个包安装
# ---------------------------------------------------------------------------

def _install_single_xapk(
    adb: AdbExecutor,
    xapk_path: Path,
    step_prefix: str,
) -> PackageInstallResult:
    """安装单个 XAPK 文件（多个 split APK）。

    严格对应 pcapng 中的一轮：
        install-create -r -d -t --user 0
        install-write -S {size} {session} {name}.apk × N
        install-commit {session}

    使用 adb install-multiple -r -d -t --user 0 <apk1> <apk2> ...
    内部自动执行上述 3 步流程。

    流程：
    1. 解析 manifest.json 获取包信息和 APK 列表
    2. 使用 tempfile.TemporaryDirectory 创建临时目录
    3. 解压 APK 文件到临时目录
    4. 调用 adb install-multiple 安装
    5. 临时目录自动清理（context manager 保证）

    Args:
        adb: ADB 执行器
        xapk_path: XAPK 文件路径
        step_prefix: 日志步骤前缀

    Returns:
        PackageInstallResult 安装结果
    """
    # 解析 XAPK
    logger.info(
        "%s 解析 XAPK: %s", step_prefix, xapk_path.name,
    )
    xapk_info = parse_xapk(xapk_path)
    logger.info(
        "%s 包名: %s, 版本: %s, APK 数: %d, 大小: %.1f MB",
        step_prefix,
        xapk_info.package_name,
        xapk_info.version_name,
        xapk_info.apk_count,
        xapk_info.total_size_mb,
    )

    # 使用 tempfile.TemporaryDirectory 作为 context manager
    # Python 官方推荐的临时目录管理方式：
    # - 自动清理，即使发生异常
    # - ignore_cleanup_errors=True 处理 Windows 文件锁问题
    with tempfile.TemporaryDirectory(
        prefix=f"michanger_xapk_{xapk_info.package_name}_",
        ignore_cleanup_errors=True,
    ) as tmp_dir:
        tmp_path = Path(tmp_dir)

        # 解压 APK 到临时目录
        logger.info(
            "%s 解压 %d 个 APK 到临时目录",
            step_prefix, xapk_info.apk_count,
        )
        extracted_apks = extract_xapk(xapk_path, tmp_path)

        # 构建 APK 路径元组
        # adb install-multiple 内部决定 install-write 顺序
        apk_paths = tuple(apk.path for apk in extracted_apks)

        # 调用 adb install-multiple -r -d -t --user 0
        # 参数与 pcapng install-create 完全一致
        logger.info(
            "%s 执行: adb install-multiple -r -d -t --user 0 "
            "(%d 个 APK)",
            step_prefix, len(apk_paths),
        )

        for apk in extracted_apks:
            logger.info(
                "%s   -> %s (%.1f MB, id=%s)",
                step_prefix,
                apk.name,
                apk.size_mb,
                apk.split_id or "?",
            )

        result = adb.install_multiple(
            apk_paths,
            replace=True,
            downgrade=True,
            test=True,
            user=0,
            timeout=_INSTALL_TIMEOUT,
        )

    # 解析安装结果
    output = result.output
    success = result.success and "Success" in output

    if success:
        logger.info(
            "%s 安装成功: %s", step_prefix, output.strip(),
        )
    else:
        logger.error(
            "%s 安装失败: %s (returncode=%d)",
            step_prefix, output.strip(), result.returncode,
        )

    return PackageInstallResult(
        package_name=xapk_info.package_name,
        xapk_name=xapk_info.xapk_name,
        apk_count=xapk_info.apk_count,
        install_output=output,
        success=success,
        error_message="" if success else output,
    )


def _install_single_apk(
    adb: AdbExecutor,
    apk_path: Path,
    step_prefix: str,
) -> PackageInstallResult:
    """安装单个独立 APK 文件（非 XAPK 分割包）。

    使用 adb install -r -d -t --user 0 <apk>
    参数与 pcapng 中 install-create 的参数一致。

    Args:
        adb: ADB 执行器
        apk_path: APK 文件路径
        step_prefix: 日志步骤前缀

    Returns:
        PackageInstallResult 安装结果
    """
    logger.info(
        "%s 安装 APK: %s (%.1f MB)",
        step_prefix,
        apk_path.name,
        apk_path.stat().st_size / (1024 * 1024),
    )

    # 使用 adb install（单个 APK）
    result = adb.install_apk(
        apk_path,
        replace=True,
        downgrade=True,
        test=True,
        user=0,
        timeout=_INSTALL_TIMEOUT,
    )

    output = result.output
    success = result.success and "Success" in output

    if success:
        logger.info(
            "%s 安装成功: %s", step_prefix, output.strip(),
        )
    else:
        logger.error(
            "%s 安装失败: %s", step_prefix, output.strip(),
        )

    return PackageInstallResult(
        package_name=apk_path.stem,
        xapk_name=None,
        apk_count=1,
        install_output=output,
        success=success,
        error_message="" if success else output,
    )


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def install_apk_xapk(
    adb_path: Path,
    serial: str,
    apk_dir: Path,
    *,
    enable_play_store: bool = True,
    dry_run: bool = False,
) -> InstallApkXapkResult:
    """安装 apk_dir 中的所有 APK/XAPK 文件。

    严格按照 12.0-Install Apk-XApk.pcapng 抓包还原的流程：
    1. 遍历 apk_dir 中的所有 .apk/.xapk 文件（按文件名排序）
    2. 对每个 .xapk：解压 → adb install-multiple -r -d -t --user 0
       （等价于 pcapng install-create → install-write × N → install-commit）
    3. 对每个 .apk：adb install -r -d -t --user 0
    4. 最后：adb shell pm enable com.android.vending（pcapng Step 29）

    apk_dir 中可以放置任意数量的 .apk 和 .xapk 文件。

    Args:
        adb_path: adb.exe 的路径
        serial: 设备序列号
        apk_dir: APK/XAPK 文件目录
        enable_play_store: 是否在安装后启用 Google Play Store
        dry_run: 如果为 True，仅打印命令序列，不实际执行

    Returns:
        InstallApkXapkResult 安装结果

    Raises:
        AdbError: 任一关键步骤失败
        XapkParseError: XAPK 解析失败
    """
    # 发现 apk_dir 中所有 .apk/.xapk 文件
    package_files = discover_apk_packages(apk_dir)

    if dry_run:
        return _dry_run(serial, package_files, enable_play_store)

    adb = AdbExecutor(adb_path=adb_path, serial=serial)

    total_packages = len(package_files)
    total_steps = total_packages + (1 if enable_play_store else 0)

    logger.info("=" * 60)
    logger.info("Install Apk-XApk -- [%s]", serial)
    logger.info(
        "%d packages + %s",
        total_packages,
        "pm enable Play Store" if enable_play_store else "skip Play Store",
    )
    logger.info("=" * 60)

    # ------------------------------------------------------------------
    # 逐个安装（对应 pcapng Step 1-28）
    # 每个 XAPK 对应一轮 install-create/write/commit
    # ------------------------------------------------------------------
    install_results: list[PackageInstallResult] = []

    for idx, pkg_path in enumerate(package_files, start=1):
        step_prefix = f"[Step {idx}/{total_steps}]"

        if pkg_path.suffix.lower() == ".xapk":
            result = _install_single_xapk(adb, pkg_path, step_prefix)
        else:
            result = _install_single_apk(adb, pkg_path, step_prefix)

        install_results.append(result)

    # ------------------------------------------------------------------
    # 启用 Google Play Store（对应 pcapng Step 29）
    # shell,v2,raw:pm enable com.android.vending
    # → Package com.android.vending new state: enabled
    # ------------------------------------------------------------------
    play_store_enabled = False

    if enable_play_store:
        step_prefix = f"[Step {total_steps}/{total_steps}]"
        logger.info(
            "%s pm enable %s",
            step_prefix, _PLAY_STORE_PACKAGE,
        )

        pm_result = adb.pm_enable(_PLAY_STORE_PACKAGE)

        play_store_enabled = (
            pm_result.success
            and "enabled" in pm_result.output.lower()
        )

        if play_store_enabled:
            logger.info(
                "%s Play Store enabled: %s",
                step_prefix, pm_result.output.strip(),
            )
        else:
            logger.warning(
                "%s Play Store enable uncertain: %s",
                step_prefix, pm_result.output.strip(),
            )

    # 汇总结果
    all_installed = all(r.success for r in install_results)
    overall_success = all_installed and (
        play_store_enabled if enable_play_store else True
    )

    final_result = InstallApkXapkResult(
        install_results=tuple(install_results),
        play_store_enabled=play_store_enabled,
        success=overall_success,
    )

    logger.info("=" * 60)
    logger.info(
        "Install Apk-XApk done -- [%s] -- %d/%d success%s",
        serial,
        final_result.success_count,
        final_result.total_count,
        ", Play Store enabled" if play_store_enabled else "",
    )
    logger.info("=" * 60)

    return final_result


def _dry_run(
    serial: str,
    package_files: tuple[Path, ...],
    enable_play_store: bool,
) -> InstallApkXapkResult:
    """Dry-run 模式：仅打印完整 adb 命令序列，不实际执行。

    Args:
        serial: 设备序列号
        package_files: APK/XAPK 文件路径列表
        enable_play_store: 是否显示 pm enable 命令

    Returns:
        InstallApkXapkResult（success=False，表示未实际执行）
    """
    total_steps = len(package_files) + (1 if enable_play_store else 0)

    print()
    print("=" * 60)
    print(f"Install Apk-XApk -- Dry Run -- [{serial}]")
    print("=" * 60)
    print()

    install_results: list[PackageInstallResult] = []

    for idx, pkg_path in enumerate(package_files, start=1):
        step_label = f"[Step {idx:2d}/{total_steps}]"

        if pkg_path.suffix.lower() == ".xapk":
            xapk_info = parse_xapk(pkg_path)
            print(
                f"  {step_label} adb -s {serial} install-multiple "
                f"-r -d -t --user 0"
            )
            print(
                f"           package: {xapk_info.package_name} "
                f"v{xapk_info.version_name}"
            )
            for apk in xapk_info.apk_files:
                print(
                    f"             -> {apk.name} "
                    f"({apk.size_mb:.1f} MB, id={apk.split_id})"
                )

            install_results.append(PackageInstallResult(
                package_name=xapk_info.package_name,
                xapk_name=xapk_info.xapk_name,
                apk_count=xapk_info.apk_count,
                install_output="(dry-run)",
                success=False,
            ))
        else:
            size_mb = pkg_path.stat().st_size / (1024 * 1024)
            print(
                f"  {step_label} adb -s {serial} install "
                f"-r -d -t --user 0 {pkg_path.name} ({size_mb:.1f} MB)"
            )

            install_results.append(PackageInstallResult(
                package_name=pkg_path.stem,
                xapk_name=None,
                apk_count=1,
                install_output="(dry-run)",
                success=False,
            ))

    if enable_play_store:
        step_label = f"[Step {total_steps:2d}/{total_steps}]"
        print(
            f"  {step_label} adb -s {serial} shell "
            f"pm enable {_PLAY_STORE_PACKAGE}"
        )

    print()

    return InstallApkXapkResult(
        install_results=tuple(install_results),
        play_store_enabled=False,
        success=False,
    )
