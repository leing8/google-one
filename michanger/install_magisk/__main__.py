"""
Install Magisk CLI 入口。

支持 python -m michanger.install_magisk 运行。
在 TWRP Recovery 中安装 Magisk，完成设备 Root。

用法：
    python -m michanger.install_magisk [--adb-path PATH] [--serial SERIAL]
                                       [--magisk-zip PATH] [--dry-run] [-v]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from michanger.common import AdbError, auto_detect_serial, setup_logging
from .install_magisk import install_magisk
from .models import MagiskInstallResult

# 默认 adb 路径：项目根目录下的 platform-tools/adb.exe
# michanger/install_magisk/__main__.py → 3 级 parent 到项目根
_DEFAULT_ADB_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent / "platform-tools" / "adb.exe"
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
        prog="michanger.install_magisk",
        description=(
            "Install Magisk & Root Phone — "
            "通过 TWRP Recovery 安装 Magisk，实现设备 Root"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python -m michanger.install_magisk\n"
            "  python -m michanger.install_magisk --serial ABCD1234\n"
            "  python -m michanger.install_magisk --dry-run\n"
            "  python -m michanger.install_magisk -v\n"
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

    setup_logging(verbose=args.verbose)
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
    serial: str = args.serial or auto_detect_serial(
        args.adb_path, allow_recovery=True,
    )

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
