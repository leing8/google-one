"""Install Apk-XApk — 从 XAPK 安装 Split APK.

严格按照 WiresharkLog/12.0-Install Apk-XApk/12.0-Install Apk-XApk.pcapng 抓包日志中的
ADB 命令序列一比一实现 Split APK 会话安装功能。

命令序列（7 步）：
    1. exec:cmd package 'install-create' -r -d -t --user 0
       → 创建安装会话，获取 session_id
    2. exec:cmd package 'install-write' -S 41369 <sid> baseAPK.apk
       → 流式写入 base APK (config.en.apk → baseAPK.apk)
    3. exec:cmd package 'install-write' -S 29081 <sid> splitAPK0.apk
       → 流式写入 split APK 0 (config.fr.apk → splitAPK0.apk)
    4. exec:cmd package 'install-write' -S 49565 <sid> splitAPK1.apk
       → 流式写入 split APK 1 (config.mdpi.apk → splitAPK1.apk)
    5. exec:cmd package 'install-write' -S 2306944 <sid> splitAPK2.apk
       → 流式写入 split APK 2 (gr...integritycheck.apk → splitAPK2.apk)
    6. exec:cmd package 'install-commit' <sid>
       → 提交安装会话
    7. pm enable com.android.vending
       → 启用 Play Store

XAPK → APK 名称映射（严格对应抓包日志字节大小）：
    manifest.json split_apks 顺序:
        [0] base → gr.nikolasspyr.integritycheck.apk (2306944) → splitAPK2.apk
        [1] config.mdpi → config.mdpi.apk (49565)              → splitAPK1.apk
        [2] config.fr → config.fr.apk (29081)                  → splitAPK0.apk
        [3] config.en → config.en.apk (41369)                  → baseAPK.apk

    抓包日志安装顺序（按步骤 2-5）：
        步骤 2: baseAPK.apk  (41369)  ← config.en.apk
        步骤 3: splitAPK0.apk (29081) ← config.fr.apk
        步骤 4: splitAPK1.apk (49565) ← config.mdpi.apk
        步骤 5: splitAPK2.apk (2306944) ← gr...integritycheck.apk

抓包上下文：
    - 设备: Pixel 4 XL (coral), Android 12
    - 应用: Play Integrity API Checker v2.2
    - 包名: gr.nikolasspyr.integritycheck

Python 官方最佳实践：
    - subprocess.run(input=bytes) 向 stdin 管道发送二进制数据（Python 3.14 文档）
    - re.search() 解析结构化输出
    - pathlib.Path 用于文件路径操作
    - dataclasses(frozen=True) 实现不可变数据模型
    - logging 模块进行结构化日志
    - argparse 模块处理命令行参数
    - shutil.rmtree() 清理临时目录

参考:
    https://docs.python.org/3/library/subprocess.html#subprocess.run
    https://docs.python.org/3/library/re.html
    https://docs.python.org/3/library/pathlib.html
    https://developer.android.com/reference/android/content/pm/PackageInstaller
"""

from __future__ import annotations

import logging
import re
import shutil
import sys
from pathlib import Path

from adb_executor import AdbError, AdbExecutor
from models import ApkWriteDetail, InstallApkResult
from xapk_extractor import ExtractedApk, XapkContent, XapkError, extract_xapk

logger = logging.getLogger(__name__)

# ── 常量 ───────────────────────────────────────────────────────────

# 默认 XAPK 文件路径（相对于项目根目录）
_DEFAULT_XAPK_PATH: str = (
    "WiresharkLog/12.0-Install Apk-XApk/apk/"
    "Play Integrity API Checker_2.2_APKPure.xapk"
)

# install-create 参数（严格按照抓包日志步骤 1）
_INSTALL_CREATE_FLAGS: tuple[str, ...] = ("-r", "-d", "-t", "--user", "0")

# Play Store 包名（严格按照抓包日志步骤 7）
_PLAY_STORE_PACKAGE: str = "com.android.vending"

# 超时设置（秒）
_SHELL_TIMEOUT: int = 30
_STREAMING_TIMEOUT: int = 120
_ENABLE_TIMEOUT: int = 30

# 解析 install-create 输出的正则表达式
# 匹配: "Success: created install session [1421557098]"
_SESSION_ID_PATTERN: re.Pattern[str] = re.compile(
    r"Success: created install session \[(\d+)\]"
)

# 解析 install-write 输出的正则表达式
# 匹配: "Success: streamed 41369 bytes"
_STREAMED_BYTES_PATTERN: re.Pattern[str] = re.compile(
    r"Success: streamed (\d+) bytes"
)

# install-commit 成功标志
_COMMIT_SUCCESS_MARKER: str = "Success"

# pm enable 成功标志
_ENABLE_SUCCESS_MARKER: str = "new state: enabled"


# ── 安装名称映射 ───────────────────────────────────────────────────


def _build_install_order(
    extracted_apks: tuple[ExtractedApk, ...],
) -> list[tuple[ExtractedApk, str]]:
    """构建安装顺序和名称映射。

    严格按照抓包日志的安装顺序（通过字节大小精确匹配验证）：
        步骤 2: baseAPK.apk   (41369)  ← config.en.apk   (manifest [3])
        步骤 3: splitAPK0.apk (29081)  ← config.fr.apk   (manifest [2])
        步骤 4: splitAPK1.apk (49565)  ← config.mdpi.apk (manifest [1])
        步骤 5: splitAPK2.apk (2306944) ← base APK        (manifest [0])

    规律: manifest.json 中 split_apks 数组的倒序。
    命名规则: 第一个为 "baseAPK.apk"，后续为 "splitAPK{i}.apk" (i 从 0 开始)。

    参数:
        extracted_apks: 从 XAPK 提取的 APK 列表（按 manifest.json split_apks 顺序）。

    返回:
        (ExtractedApk, 安装名称) 的有序列表，顺序对应步骤 2-5。
    """
    # 将 manifest.json 中 split_apks 顺序倒序（严格对应抓包日志）
    reversed_apks = list(reversed(extracted_apks))

    # 构建安装名称：第一个为 baseAPK.apk，后续为 splitAPK{i}.apk
    ordered: list[tuple[ExtractedApk, str]] = []

    for i, apk in enumerate(reversed_apks):
        if i == 0:
            install_name = "baseAPK.apk"
        else:
            install_name = f"splitAPK{i - 1}.apk"
        ordered.append((apk, install_name))

    return ordered


# ── Step 1: install-create ─────────────────────────────────────────


def _install_create(executor: AdbExecutor) -> tuple[bool, str]:
    """步骤 1: exec:cmd package 'install-create' -r -d -t --user 0

    对应抓包日志:
        [Frame  7] OUT OPEN arg0=3541 arg1=0 len=52 |
            exec:cmd package 'install-create' -r -d -t --user 0
        [Frame 11] IN  OKAY arg0=1 arg1=3541 len=0
        [Frame 13] IN  WRTE arg0=1 arg1=3541 len=46 |
            Success: created install session [1421557098]

    创建安装会话，返回会话 ID 用于后续 install-write 命令。

    参数:
        executor: ADB 执行器实例。

    返回:
        (是否成功, session_id) 的元组。session_id 为空字符串表示失败。
    """
    flags_str = " ".join(_INSTALL_CREATE_FLAGS)
    command = f"cmd package 'install-create' {flags_str}"

    logger.info("步骤 1: exec:%s", command)

    result = executor.run_shell(command, timeout=_SHELL_TIMEOUT)

    output = result.stdout if result.success else result.stderr
    logger.info("  输出: %s", output)

    # 使用正则解析 session_id
    match = _SESSION_ID_PATTERN.search(output)
    if match:
        session_id = match.group(1)
        logger.info("  会话 ID: %s ✓", session_id)
        return True, session_id

    logger.error("  创建安装会话失败 — 未匹配到 session_id")
    return False, ""


# ── Step 2-5: install-write ────────────────────────────────────────


def _install_write(
    executor: AdbExecutor,
    session_id: str,
    apk: ExtractedApk,
    install_name: str,
    step_num: int,
) -> ApkWriteDetail:
    """步骤 2-5: exec:cmd package 'install-write' -S <size> <sid> <name>.apk

    对应抓包日志（以步骤 2 为例）:
        [Frame 22] OUT OPEN arg0=3542 arg1=0 len=65 |
            exec:cmd package 'install-write' -S 41369 1421557098 baseAPK.apk
        [Frame 29] OUT WRTE arg0=3542 arg1=2 len=41369 | [40.4 KB data]
        [Frame 35] IN  WRTE arg0=2 arg1=3542 len=30 |
            Success: streamed 41369 bytes

    严格对应抓包日志协议：
    1. 通过 exec: 协议发送 install-write 命令（包含 -S <size> 声明）
    2. 将 APK 文件的完整二进制数据通过 stdin 管道发送
    3. 设备端 PackageManager 从 stdin 读取 <size> 字节

    参数:
        executor: ADB 执行器实例。
        session_id: install-create 返回的会话 ID。
        apk: 要写入的 APK 文件信息。
        install_name: 安装时使用的逻辑名称（例如 "baseAPK.apk"）。
        step_num: 步骤编号（2-5），用于日志。

    返回:
        包含写入结果的 ApkWriteDetail。
    """
    # 读取 APK 文件的完整二进制数据（Python pathlib 推荐：read_bytes()）
    apk_data = apk.local_path.read_bytes()
    apk_size = len(apk_data)

    command = (
        f"cmd package 'install-write' -S {apk_size} {session_id} {install_name}"
    )

    logger.info("步骤 %d: exec:%s", step_num, command)
    logger.info(
        "  文件: %s → %s (%d bytes)",
        apk.original_name,
        install_name,
        apk_size,
    )

    # 严格按照抓包日志协议：通过 stdin 管道发送 APK 二进制数据
    result = executor.run_streaming_shell(
        command, apk_data, timeout=_STREAMING_TIMEOUT
    )

    output = result.stdout if result.success else result.stderr
    logger.info("  输出: %s", output)

    # 使用正则解析 streamed bytes
    match = _STREAMED_BYTES_PATTERN.search(output)
    streamed_bytes = int(match.group(1)) if match else 0
    write_success = match is not None

    if write_success:
        logger.info(
            "  %s 写入成功: streamed %d bytes ✓",
            install_name,
            streamed_bytes,
        )
    else:
        logger.error("  %s 写入失败: %s", install_name, output)

    return ApkWriteDetail(
        apk_name=install_name,
        original_name=apk.original_name,
        size=apk_size,
        streamed_bytes=streamed_bytes,
        write_success=write_success,
    )


# ── Step 6: install-commit ─────────────────────────────────────────


def _install_commit(
    executor: AdbExecutor, session_id: str
) -> bool:
    """步骤 6: exec:cmd package 'install-commit' <session_id>

    对应抓包日志:
        [Frame 158] OUT OPEN arg0=3546 arg1=0 len=45 |
            exec:cmd package 'install-commit' 1421557098
        [Frame 163] IN  OKAY arg0=6 arg1=3546 len=0
        [Frame 165] IN  WRTE arg0=6 arg1=3546 len=8 | Success

    提交安装会话，完成 Split APK 安装。

    参数:
        executor: ADB 执行器实例。
        session_id: install-create 返回的会话 ID。

    返回:
        安装是否成功提交。
    """
    command = f"cmd package 'install-commit' {session_id}"

    logger.info("步骤 6: exec:%s", command)

    result = executor.run_shell(command, timeout=_SHELL_TIMEOUT)

    output = result.stdout if result.success else result.stderr
    logger.info("  输出: %s", output)

    commit_success = _COMMIT_SUCCESS_MARKER in output

    if commit_success:
        logger.info("  安装提交成功 ✓")
    else:
        logger.error("  安装提交失败: %s", output)

    return commit_success


# ── Step 7: pm enable ──────────────────────────────────────────────


def _enable_play_store(executor: AdbExecutor) -> bool:
    """步骤 7: pm enable com.android.vending

    对应抓包日志:
        [Frame 177] OUT OPEN arg0=3550 arg1=0 len=43 |
            shell,v2,raw:pm enable com.android.vending
        [Frame 189] IN  WRTE arg0=7 arg1=3550 len=52 |
            Package com.android.vending new state: enabled

    启用 Google Play Store 应用。

    参数:
        executor: ADB 执行器实例。

    返回:
        Play Store 是否成功启用。
    """
    command = f"pm enable {_PLAY_STORE_PACKAGE}"

    logger.info("步骤 7: %s", command)

    result = executor.run_shell(command, timeout=_ENABLE_TIMEOUT)

    output = result.stdout if result.success else result.stderr
    logger.info("  输出: %s", output)

    enabled = _ENABLE_SUCCESS_MARKER in output

    if enabled:
        logger.info("  %s 已启用 ✓", _PLAY_STORE_PACKAGE)
    else:
        logger.error("  启用失败: %s", output)

    return enabled


# ── 主流程 ─────────────────────────────────────────────────────────


def install_apk_xapk(
    executor: AdbExecutor,
    xapk_path: Path,
) -> InstallApkResult:
    """从 XAPK 安装 Split APK。

    严格按照 12.0-Install Apk-XApk.pcapng 抓包日志中的命令顺序执行 7 步：
        1. exec:cmd package 'install-create' -r -d -t --user 0
           → 创建安装会话
        2. exec:cmd package 'install-write' -S 41369 <sid> baseAPK.apk
           → 流式写入 config.en.apk
        3. exec:cmd package 'install-write' -S 29081 <sid> splitAPK0.apk
           → 流式写入 config.fr.apk
        4. exec:cmd package 'install-write' -S 49565 <sid> splitAPK1.apk
           → 流式写入 config.mdpi.apk
        5. exec:cmd package 'install-write' -S 2306944 <sid> splitAPK2.apk
           → 流式写入 gr.nikolasspyr.integritycheck.apk
        6. exec:cmd package 'install-commit' <sid>
           → 提交安装会话
        7. pm enable com.android.vending
           → 启用 Play Store

    参数:
        executor: ADB 命令执行器实例。
        xapk_path: XAPK 文件路径。

    返回:
        包含所有步骤执行结果的 InstallApkResult。

    抛出:
        AdbError: 如果 ADB 不可用或设备未连接。
        XapkError: 如果 XAPK 文件无效。
    """
    logger.info("=" * 60)
    logger.info("Install Apk-XApk — 开始安装 Split APK")
    logger.info("=" * 60)

    # ── 解包 XAPK ──────────────────────────────────────────────
    logger.info("解包 XAPK: %s", xapk_path)
    content: XapkContent = extract_xapk(xapk_path)

    logger.info("包名: %s", content.manifest.package_name)
    logger.info("应用: %s v%s", content.manifest.name, content.manifest.version_name)

    # 构建安装顺序（严格对应抓包日志步骤 2-5 的大小和名称）
    install_order = _build_install_order(content.extracted_apks)

    logger.info("安装顺序 (%d 个 APK):", len(install_order))
    for apk, name in install_order:
        logger.info("  %s → %s (%d bytes)", apk.original_name, name, apk.size)

    # ── Step 1: install-create ──────────────────────────────────
    create_success, session_id = _install_create(executor)

    if not create_success:
        logger.error("创建安装会话失败，中止安装")
        _cleanup_temp(content.extract_dir)
        return InstallApkResult(
            xapk_path=str(xapk_path),
            package_name=content.manifest.package_name,
            app_name=content.manifest.name,
            version_name=content.manifest.version_name,
            session_id="",
            create_success=False,
            write_results=(),
            commit_success=False,
            vending_enabled=False,
            all_success=False,
        )

    # ── Step 2-5: install-write ─────────────────────────────────
    write_results: list[ApkWriteDetail] = []

    for step_num, (apk, install_name) in enumerate(install_order, start=2):
        detail = _install_write(
            executor, session_id, apk, install_name, step_num
        )
        write_results.append(detail)

    all_writes_ok = all(w.write_success for w in write_results)

    if not all_writes_ok:
        logger.error("部分 APK 写入失败，仍尝试 commit")

    # ── Step 6: install-commit ──────────────────────────────────
    commit_success = _install_commit(executor, session_id)

    # ── Step 7: pm enable ───────────────────────────────────────
    vending_enabled = _enable_play_store(executor)

    # ── 清理临时目录 ────────────────────────────────────────────
    _cleanup_temp(content.extract_dir)

    # ── 构建结果 ────────────────────────────────────────────────
    all_success = all([
        create_success,
        all_writes_ok,
        commit_success,
        vending_enabled,
    ])

    result = InstallApkResult(
        xapk_path=str(xapk_path),
        package_name=content.manifest.package_name,
        app_name=content.manifest.name,
        version_name=content.manifest.version_name,
        session_id=session_id,
        create_success=create_success,
        write_results=tuple(write_results),
        commit_success=commit_success,
        vending_enabled=vending_enabled,
        all_success=all_success,
    )

    _print_summary(result)
    return result


# ── 临时目录清理 ───────────────────────────────────────────────────


def _cleanup_temp(extract_dir: Path) -> None:
    """清理 XAPK 提取的临时目录。

    Python 官方推荐：使用 shutil.rmtree() 递归删除目录。

    参数:
        extract_dir: 要清理的临时目录。
    """
    try:
        shutil.rmtree(extract_dir, ignore_errors=True)
        logger.info("临时目录已清理: %s", extract_dir)
    except OSError as e:
        logger.warning("清理临时目录失败: %s", e)


# ── 结果输出 ───────────────────────────────────────────────────────


def _print_summary(result: InstallApkResult) -> None:
    """打印可读的安装结果汇总。"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("Install Apk-XApk — 安装结果汇总")
    logger.info("=" * 60)
    logger.info("  XAPK:             %s", result.xapk_path)
    logger.info("  包名:             %s", result.package_name)
    logger.info("  应用:             %s v%s", result.app_name, result.version_name)
    logger.info("  会话 ID:          %s", result.session_id)
    logger.info("  创建会话:         %s", result.create_success)
    logger.info("  APK 写入结果:")
    for w in result.write_results:
        status = "✓" if w.write_success else "✗"
        logger.info(
            "    %s %s ← %s (%d bytes, streamed %d)",
            status,
            w.apk_name,
            w.original_name,
            w.size,
            w.streamed_bytes,
        )
    logger.info("  安装提交:         %s", result.commit_success)
    logger.info("  Play Store 启用:  %s", result.vending_enabled)

    if result.all_success:
        logger.info("  状态: ✓ 安装成功完成")
    else:
        logger.error("  状态: ✗ 部分步骤失败，请检查日志")

    logger.info("=" * 60)


# ── CLI 入口 ───────────────────────────────────────────────────────


def main() -> None:
    """Install Apk-XApk 的命令行入口。

    用法:
        python install_apk_xapk.py [--xapk-path <path>]
    """
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Python 官方推荐：使用 argparse 模块处理命令行参数
    parser = argparse.ArgumentParser(
        description="Install Apk-XApk — 从 XAPK 安装 Split APK",
    )
    parser.add_argument(
        "--xapk-path",
        type=Path,
        default=None,
        help="XAPK 文件路径 (默认: 项目内置路径)",
    )

    args = parser.parse_args()

    # 使用项目内置的 platform-tools/adb.exe
    project_root = Path(__file__).resolve().parent
    adb_path = project_root / "platform-tools" / "adb.exe"

    if not adb_path.exists():
        logger.error("未找到 ADB: %s", adb_path)
        sys.exit(1)

    # 确定 XAPK 路径
    if args.xapk_path is not None:
        xapk_path = args.xapk_path
    else:
        xapk_path = project_root / _DEFAULT_XAPK_PATH

    logger.info("ADB:         %s", adb_path)
    logger.info("XAPK:        %s", xapk_path)

    executor = AdbExecutor(adb_path=adb_path)

    try:
        result = install_apk_xapk(executor, xapk_path)
    except (AdbError, XapkError) as e:
        logger.error("错误: %s", e)
        sys.exit(1)

    # 根据安装结果设置退出码
    sys.exit(0 if result.all_success else 1)


if __name__ == "__main__":
    main()
