"""
Install Magisk CLI 入口。

支持 python -m install-magisk 运行。
在 TWRP Recovery 中安装 Magisk，完成设备 Root。

用法：
    python -m install-magisk [--adb-path PATH] [--serial SERIAL]
                             [--magisk-zip PATH] [--dry-run] [-v]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .adb_executor import AdbError, list_devices
from .install_magisk import install_magisk
from .models import MagiskInstallResult

# 默认 adb 路径：项目根目录下的 platform-tools/adb.exe
_DEFAULT_ADB_PATH: Path = (
    Path(__file__).resolve().parent.parent / "platform-tools" / "adb.exe"
)

# 默认 Magisk.zip 路径：模块目录下的 Magisk.zip
_DEFAULT_MAGISK_ZIP: Path = (
    Path(__file__).resolve().parent / "Magisk.zip"
)


def _build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。

    遵循 Python argparse 官方最佳实践：
    - 使用 prog 指定程序名
    - 使用 type=Path 自动转换路径参数
    - 提供 epilog 示例用法

    参考：https://docs.python.org/3/library/argparse.html
    """
    parser = argparse.ArgumentParser(
        prog="install-magisk",
        description=(
            "Install Magisk & Root Phone — "
            "通过 TWRP Recovery 安装 Magisk，实现设备 Root"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python -m install-magisk\n"
            "  python -m install-magisk --serial ABCD1234\n"
            "  python -m install-magisk --dry-run\n"
            "  python -m install-magisk -v\n"
        ),
    )
    parser.add_argument(
        "--adb-path",
        type=Path,
        default=_DEFAULT_ADB_PATH,
        help=f"adb 可执行文件路径（默认：{_DEFAULT_ADB_PATH}）",
    )
    parser.add_argument(
        "--serial",
        type=str,
        default=None,
        help="设备序列号（默认：自动检测第一台在线设备）",
    )
    parser.add_argument(
        "--magisk-zip",
        type=Path,
        default=_DEFAULT_MAGISK_ZIP,
        help=f"Magisk.zip 文件路径（默认：{_DEFAULT_MAGISK_ZIP}）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印命令序列，不实际执行",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="显示详细日志（DEBUG 级别）",
    )
    return parser


def _setup_logging(*, verbose: bool) -> None:
    """配置日志系统。

    遵循 Python logging 官方最佳实践：
    - 使用 logging.basicConfig() 进行简单配置
    - 日志输出到 stderr（不干扰 stdout 的结构化输出）
    - 使用 %-style 格式化（logging 推荐）

    参考：https://docs.python.org/3/howto/logging.html

    Args:
        verbose: 是否启用 DEBUG 级别日志
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def _auto_detect_serial(adb_path: Path) -> str:
    """自动检测第一台在线设备的序列号。

    Args:
        adb_path: adb 可执行文件路径

    Returns:
        设备序列号

    Raises:
        SystemExit: 无在线设备
    """
    devices = list_devices(adb_path=adb_path)

    if not devices:
        print("错误：未检测到已连接的 ADB 设备", file=sys.stderr)
        sys.exit(1)

    # 优先查找在线设备（state == "device"），其次 Recovery 设备
    online = [d for d in devices if d.is_online]
    recovery = [d for d in devices if d.is_recovery]

    if online:
        serial = online[0].serial
        print(f"自动检测到在线设备: {serial}", file=sys.stderr)
        return serial

    if recovery:
        serial = recovery[0].serial
        print(
            f"自动检测到 Recovery 模式设备: {serial}",
            file=sys.stderr,
        )
        return serial

    # 列出所有设备状态
    for device in devices:
        print(
            f"  设备 {device.serial}: {device.state}",
            file=sys.stderr,
        )
    print("错误：无在线或 Recovery 模式的设备", file=sys.stderr)
    sys.exit(1)


def _print_result(result: MagiskInstallResult) -> None:
    """打印安装结果。

    Args:
        result: Magisk 安装结果
    """
    status = "[OK]" if result.success else "[FAIL]"

    print()
    print("=" * 50)
    print(f"  Magisk 安装结果: {status}")
    print("=" * 50)
    print(f"  TWRP Version:   {result.twrp_version}")
    print(f"  Magisk Version: {result.magisk_version}")
    print(f"  Boot Slot:      {result.boot_slot}")
    print(f"  Target Image:   {result.target_image}")
    print(f"  Platform:       {result.platform}")
    print(f"  Log Lines:      {len(result.install_log)}")
    print()


def main() -> None:
    """CLI 主入口。"""
    parser = _build_parser()
    args = parser.parse_args()

    _setup_logging(verbose=args.verbose)
    log = logging.getLogger(__name__)

    # 验证 Magisk.zip 存在
    magisk_zip: Path = args.magisk_zip
    if not magisk_zip.is_file():
        print(
            f"错误：Magisk.zip 不存在：{magisk_zip}",
            file=sys.stderr,
        )
        sys.exit(1)

    # 自动检测或使用指定的序列号
    serial: str = args.serial or _auto_detect_serial(args.adb_path)

    try:
        result = install_magisk(
            adb_path=args.adb_path,
            serial=serial,
            magisk_zip=magisk_zip,
            dry_run=args.dry_run,
        )
    except AdbError as exc:
        log.error("Install Magisk 失败: %s", exc)
        sys.exit(1)
    except FileNotFoundError as exc:
        log.error("文件未找到: %s", exc)
        sys.exit(1)

    _print_result(result)

    if not result.success and not args.dry_run:
        sys.exit(1)


if __name__ == "__main__":
    main()
