"""
Install Apk-XApk CLI 入口。

支持 python -m michanger.install_apk_xapk 运行。
批量安装 APK/XAPK 分割包。

用法：
    python -m michanger.install_apk_xapk [--adb-path PATH] [--serial SERIAL]
                                          [--apk-dir DIR] [--no-play-store]
                                          [--dry-run] [-v]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from michanger.common import AdbError, auto_detect_serial, setup_logging
from .install_apk_xapk import install_apk_xapk
from .models import InstallApkXapkResult
from .xapk_parser import XapkParseError

# 默认 adb 路径：项目根目录下的 platform-tools/adb.exe
# michanger/install_apk_xapk/__main__.py → 3 级 parent 到项目根
_DEFAULT_ADB_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent
    / "platform-tools"
    / "adb.exe"
)

# 默认 APK 目录：模块包内的 apk/ 子目录
_DEFAULT_APK_DIR: Path = (
    Path(__file__).resolve().parent / "apk"
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
        prog="michanger.install_apk_xapk",
        description=(
            "Install Apk-XApk — "
            "批量安装 APK/XAPK 分割包（Google One、Play Integrity Checker 等）"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python -m michanger.install_apk_xapk\n"
            "  python -m michanger.install_apk_xapk --serial ABCD1234\n"
            "  python -m michanger.install_apk_xapk --apk-dir /path/to/apks\n"
            "  python -m michanger.install_apk_xapk --no-play-store\n"
            "  python -m michanger.install_apk_xapk --dry-run\n"
            "  python -m michanger.install_apk_xapk -v\n"
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
        "--apk-dir",
        type=Path,
        default=_DEFAULT_APK_DIR,
        help=f"APK/XAPK 文件目录（默认：{_DEFAULT_APK_DIR}）",
    )
    parser.add_argument(
        "--no-play-store",
        action="store_true",
        help="安装后不启用 Google Play Store",
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


def _print_result(result: InstallApkXapkResult) -> None:
    """打印安装结果。

    Args:
        result: 安装结果
    """
    status = "[OK]" if result.success else "[FAIL]"

    print()
    print("=" * 60)
    print(f"  APK/XAPK 安装结果: {status}")
    print("=" * 60)
    print(
        f"  安装成功:    "
        f"{result.success_count}/{result.total_count}"
    )
    print(
        f"  Play Store:  "
        f"{'已启用' if result.play_store_enabled else '未启用'}"
    )
    print()

    # 逐个包的安装状态
    if result.install_results:
        print("  包详情:")
        for r in result.install_results:
            icon = "[OK]" if r.success else "[FAIL]"
            xapk_label = (
                f" ({r.apk_count} split APKs)"
                if r.apk_count > 1
                else ""
            )
            print(
                f"    {icon} {r.package_name}{xapk_label}"
            )
            if not r.success and r.error_message:
                # 只显示错误的第一行
                first_line = r.error_message.strip().split("\n")[0]
                print(f"      错误: {first_line}")
        print()


def main() -> None:
    """CLI 主入口。"""
    parser = _build_parser()
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)
    log = logging.getLogger(__name__)

    # 验证 APK 目录存在
    apk_dir: Path = args.apk_dir
    if not apk_dir.is_dir():
        print(
            f"错误：APK 目录不存在：{apk_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    # 验证目录中有 .apk/.xapk 文件
    pkg_count = sum(
        1 for f in apk_dir.iterdir()
        if f.is_file()
        and f.suffix.lower() in (".apk", ".xapk")
    )
    if pkg_count == 0:
        print(
            f"错误：APK 目录中未找到 .apk/.xapk 文件：{apk_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    # 自动检测或使用指定的序列号
    serial: str = args.serial or auto_detect_serial(args.adb_path)

    try:
        result = install_apk_xapk(
            adb_path=args.adb_path,
            serial=serial,
            apk_dir=apk_dir,
            enable_play_store=not args.no_play_store,
            dry_run=args.dry_run,
        )
    except AdbError as exc:
        log.error("Install Apk-XApk 失败: %s", exc)
        sys.exit(1)
    except XapkParseError as exc:
        log.error("XAPK 解析失败: %s", exc)
        sys.exit(1)
    except FileNotFoundError as exc:
        log.error("文件未找到: %s", exc)
        sys.exit(1)

    _print_result(result)

    if not result.success and not args.dry_run:
        sys.exit(1)


if __name__ == "__main__":
    main()
