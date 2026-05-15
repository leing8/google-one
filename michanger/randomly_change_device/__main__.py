"""
Randomly Change Device CLI 入口。

支持 python -m michanger.randomly_change_device 运行。
设备信息随机化。

用法：
    python -m michanger.randomly_change_device [--adb-path PATH] [--serial SERIAL]
                                                [--profile NAME] [--dry-run] [-v]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from michanger.common import AdbError, auto_detect_serial, setup_logging
from .models import ChangeDeviceResult
from .randomly_change_device import randomly_change_device

# 默认 adb 路径：项目根目录下的 platform-tools/adb.exe
_DEFAULT_ADB_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent / "platform-tools" / "adb.exe"
)


def _build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。

    遵循 Python argparse 官方最佳实践：
    - 使用 prog 指定程序名
    - 使用 type=Path 自动转换路径参数

    参考：https://docs.python.org/3/library/argparse.html
    """
    parser = argparse.ArgumentParser(
        prog="michanger.randomly_change_device",
        description=(
            "Randomly Change Device — "
            "设备信息随机化（修改 build.prop、mi_info、settings 等）"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python -m michanger.randomly_change_device\n"
            "  python -m michanger.randomly_change_device --serial ABCD1234\n"
            "  python -m michanger.randomly_change_device --profile blazer\n"
            "  python -m michanger.randomly_change_device --dry-run\n"
            "  python -m michanger.randomly_change_device -v\n"
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
        "--profile",
        type=str,
        default=None,
        help="设备配置名称（默认：使用第一个 JSON 配置）",
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


def _print_result(result: ChangeDeviceResult) -> None:
    """打印执行结果。"""
    status = "[OK]" if result.success else "[FAIL]"

    print()
    print("=" * 60)
    print(f"  设备随机化结果: {status}")
    print("=" * 60)
    print(f"  阶段: {result.success_count}/{result.total_phases} 成功")
    print(f"  命令: {result.total_commands} 条")
    if result.locale:
        print(f"  Locale: {result.locale}")
    print()

    if result.phase_results:
        print("  阶段详情:")
        for p in result.phase_results:
            icon = "✓" if p.success else "✗"
            print(
                f"    {icon} Phase {p.phase_number:>2}: "
                f"{p.phase_name} ({p.commands_executed} 命令) "
                f"— {p.message}"
            )
        print()


def main() -> None:
    """CLI 主入口。"""
    parser = _build_parser()
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)
    log = logging.getLogger(__name__)

    # 自动检测或使用指定的序列号
    serial: str = args.serial or auto_detect_serial(args.adb_path)

    try:
        result = randomly_change_device(
            adb_path=args.adb_path,
            serial=serial,
            profile_name=args.profile,
            dry_run=args.dry_run,
        )
    except AdbError as exc:
        log.error("Randomly Change Device 失败: %s", exc)
        sys.exit(1)
    except FileNotFoundError as exc:
        log.error("文件未找到: %s", exc)
        sys.exit(1)

    _print_result(result)

    if not result.success and not args.dry_run:
        sys.exit(1)


if __name__ == "__main__":
    main()
